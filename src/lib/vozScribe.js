// El micrófono de la llamada: ElevenLabs Scribe v2 Realtime por WebSocket.
//
// Sustituye al reconocimiento del navegador (`SpeechRecognition`), que en el iPhone es el
// de Apple. Va aquí y no en Dashboard.jsx por lo mismo que vozEleven.js: no pinta nada,
// es un cliente de audio. Las reglas puras —el PCM, el base64, si lo oído es eco— viven
// en voz.js, para poder probarlas sin navegador.
//
// ── Qué cambia respecto al reconocimiento del navegador ─────────────────────────────
//
// Una cosa, y lo cambia todo: **el micrófono no se cierra nunca**. Hasta aquí el modo
// llamada lo cerraba mientras Jarvis hablaba —por altavoz se oía a sí mismo, se
// transcribía y se contestaba solo— y para poder cortarle se abría en su lugar un medidor
// de energía que no transcribía nada (`vozMicro.js`). Aquello funcionaba, pero se comía
// el principio de tu frase: el reconocimiento arrancaba DESPUÉS de decidir que habías
// hablado, y para entonces llevabas unos 300 ms hablando.
//
// Con el micro abierto de continuo eso desaparece: cuando la llamada decide que le has
// cortado, tu primera palabra ya está transcrita. A cambio hay que sostener tres cosas:
//
//   1. `echoCancellation` del navegador, que resta lo que sale por el altavoz de lo que
//      entra por el micro. Es la pieza que hace posible tener los dos abiertos a la vez.
//   2. `pareceEco()` como segunda defensa, por si esa cancelación no da abasto — en iOS
//      por altavoz es el riesgo conocido de todo esto.
//   3. El contador: Scribe cobra MICRÓFONO ABIERTO (0,39 $/hora), silencios incluidos.
//      Por eso `parar()` tiene que llamarse al colgar sí o sí, y por eso la llamada
//      cuelga sola tras un rato sin oír nada. Un socket olvidado es dinero corriendo.
//
// El VAD lo hace ElevenLabs (`commit_strategy=vad`), así que no hay umbrales que calibrar
// aquí: llega `partial_transcript` mientras hablas y `committed_transcript` cuando cierra
// la frase.

import { pcm16DesdeFloat32, base64DeBytes } from "./voz.js";

const URL_SCRIBE = "wss://api.elevenlabs.io/v1/speech-to-text/realtime";
// 16 kHz es el formato nativo del modelo: pedirle más es pagar ancho de banda por nada.
const MUESTREO   = 16000;
// Cuántas muestras se juntan antes de mandar un trozo. 4096 a 16 kHz son ~256 ms, que es
// el equilibrio de siempre: más pequeño manda más mensajes (y en móvil eso se nota en la
// batería y en la red), más grande añade latencia justo donde se estaba comprando.
const BUFER      = 4096;

/** Abre el micrófono y lo transcribe en directo mientras dure la llamada.
 *
 *  Devuelve `{ parar }`, o `null` si no se ha podido montar: sin micrófono, sin permiso,
 *  sin WebSocket o sin token. Que devuelva `null` NO es un fallo que tirar por pantalla:
 *  significa que esta llamada se queda sin Scribe, y quien llama a esto vuelve al
 *  reconocimiento del navegador, que es como funcionaba antes y sigue siendo gratis.
 *
 *  - `alParcial(texto)`  — lo que va entendiendo. Se pisa entero cada vez, no se acumula.
 *  - `alCerrar(texto)`   — una frase cerrada. ESTO sí se acumula.
 *  - `alFallar(motivo)`  — el socket se ha caído a media llamada. Quien escucha decide si
 *                          cae al navegador o cuelga; aquí ya no queda nada vivo.
 */
export async function escucharConScribe({
  token, modelo = "scribe_v2_realtime", idioma = "es",
  alParcial, alCerrar, alFallar,
} = {}) {
  const Contexto = typeof window !== "undefined"
    ? (window.AudioContext || window.webkitAudioContext)
    : null;
  const medios = typeof navigator !== "undefined" ? navigator.mediaDevices : null;
  if (!token || !Contexto || !medios?.getUserMedia || typeof WebSocket === "undefined") return null;

  let stream;
  try {
    // Las mismas tres ayudas que pedía el medidor de energía, y por el mismo motivo:
    // `echoCancellation` es la que sostiene que micro y altavoz estén abiertos a la vez.
    stream = await medios.getUserMedia({
      audio: { echoCancellation: true, noiseSuppression: true, autoGainControl: true },
    });
  } catch {
    return null;   // permiso denegado o micro ocupado: se cae al reconocimiento de siempre
  }

  let ctx, fuente, procesador, mudo, socket;
  let vivo = true;

  function parar() {
    vivo = false;
    // El orden importa: primero se deja de capturar, luego se cierra el socket. Al revés,
    // los últimos trozos se mandarían contra un socket cerrado y algunos navegadores
    // lanzan por eso en mitad de un callback de audio.
    try { procesador?.disconnect(); } catch { /* mejor esfuerzo */ }
    try { mudo?.disconnect(); } catch { /* mejor esfuerzo */ }
    try { fuente?.disconnect(); } catch { /* mejor esfuerzo */ }
    try { stream.getTracks().forEach(t => t.stop()); } catch { /* mejor esfuerzo */ }
    try { ctx?.close(); } catch { /* mejor esfuerzo */ }
    try { socket?.close(); } catch { /* mejor esfuerzo */ }
  }

  try {
    // El AudioContext se pide YA a 16 kHz y no se remuestrea a mano: el navegador lo hace
    // mejor y gratis. Si el dispositivo no admite ese ritmo, el `catch` de abajo se lleva
    // el montaje entero y la llamada cae al reconocimiento del navegador.
    ctx = new Contexto({ sampleRate: MUESTREO });
    // En iOS el contexto nace suspendido fuera de un gesto. No se espera al `resume`: si
    // no arranca, no llegan muestras y el silencio se nota; esperarlo aquí retrasaría la
    // llamada entera por algo que casi siempre ya está listo.
    ctx.resume?.();
    fuente = ctx.createMediaStreamSource(stream);
    // `createScriptProcessor` está deprecado y aun así es lo que hay: es lo único que
    // funciona igual en todos los Safari a los que va esto, y un AudioWorklet obligaría a
    // servir un módulo aparte. El trabajo por muestra son cuatro operaciones sobre audio
    // mono a 16 kHz, así que el coste en el hilo principal es despreciable. Si algún día
    // se oyen cortes en la captura, este es el sitio.
    // Un canal de salida y no cero: con cero, Chrome lanza `IndexSizeError` al crearlo
    // ("number of output channels must be greater than 0"), y donde no lanza, el nodo
    // igualmente no corre. La salida no se oye — va a un `GainNode` a cero, abajo.
    procesador = ctx.createScriptProcessor(BUFER, 1, 1);
    // El sumidero mudo. Un ScriptProcessor SOLO dispara `onaudioprocess` si algo tira de
    // él aguas abajo: sin un camino hasta `ctx.destination` el callback no se llama nunca
    // y el socket se queda sin recibir una sola muestra. Con ganancia a cero se cumplen
    // las dos cosas a la vez — el grafo tira del nodo y por el altavoz no sale nada.
    mudo = ctx.createGain();
    mudo.gain.value = 0;
  } catch {
    parar();
    return null;
  }

  const parametros = new URLSearchParams({
    token,
    model_id:        modelo,
    language_code:   idioma,
    audio_format:    `pcm_${MUESTREO}`,
    // El VAD lo pone ElevenLabs. Es justo lo que hace que esto sustituya al medidor de
    // energía en vez de sumarse a él: quien decide dónde acaba una frase es el mismo que
    // la transcribe, y no dos piezas que pueden no estar de acuerdo.
    commit_strategy: "vad",
  });

  try {
    socket = new WebSocket(`${URL_SCRIBE}?${parametros}`);
  } catch {
    parar();
    return null;
  }

  // Lo que se captura antes de que el socket abra no se tira: se guarda y se manda de
  // golpe al abrir. Son las primeras décimas de la llamada, que es exactamente cuando
  // dices «hola» — perderlas era el fallo que esto viene a arreglar, cambiado de sitio.
  let esperando = [];

  function mandar(base64) {
    if (!vivo || socket.readyState !== 1) return;
    try {
      socket.send(JSON.stringify({
        message_type: "input_audio_chunk",
        audio_base_64: base64,
        sample_rate:   MUESTREO,
      }));
    } catch { /* mejor esfuerzo: el socket se cerró bajo los pies */ }
  }

  procesador.onaudioprocess = (e) => {
    if (!vivo) return;
    let base64;
    try {
      base64 = base64DeBytes(new Uint8Array(pcm16DesdeFloat32(e.inputBuffer.getChannelData(0)).buffer));
    } catch { return; }
    if (socket.readyState === 0) {
      // Un tope, porque un socket que no abre nunca no puede comerse la memoria del
      // móvil: ~8 s de audio y a partir de ahí se descarta lo más viejo.
      esperando.push(base64);
      if (esperando.length > 32) esperando.shift();
      return;
    }
    mandar(base64);
  };
  // El grafo entero: micro → procesador → ganancia cero → altavoz. El último tramo es
  // el que hacía falta y no estaba. Iba sin él por miedo al acople —"se oiría a sí mismo
  // por el altavoz"—, y el miedo era razonable pero el remedio dejaba el nodo sin nadie
  // que tirara de él: `onaudioprocess` no se llamaba, no se mandaba audio, y ElevenLabs
  // cerraba la sesión por inactividad a los pocos segundos. Se veía como «se cerró la
  // conexión con el transcriptor», que parecía un problema de red o de plan y no lo era.
  // Con la ganancia a cero no se oye nada, así que el acople sigue sin poder pasar.
  fuente.connect(procesador);
  procesador.connect(mudo);
  mudo.connect(ctx.destination);

  socket.onopen = () => {
    const pendientes = esperando;
    esperando = [];
    pendientes.forEach(mandar);
  };

  socket.onmessage = (ev) => {
    if (!vivo) return;
    let msg;
    try { msg = JSON.parse(ev.data); } catch { return; }
    const texto = (msg?.text || "").trim();
    switch (msg?.message_type) {
      case "partial_transcript":
        if (texto) alParcial?.(texto);
        break;
      case "committed_transcript":
      case "committed_transcript_with_timestamps":
        if (texto) alCerrar?.(texto);
        break;
      case "session_started":
        break;
      default:
        // Todo lo demás que traiga `error` es un fallo con nombre propio: `auth_error`
        // (token caducado, el fallo que ya costó una tarde con el TTS), `quota_exceeded`
        // —que aquí es "se acabó el saldo", y conviene que se diga— o `rate_limited`.
        // Se tratan igual: esta llamada se queda sin Scribe y quien escucha decide.
        if (msg?.error || String(msg?.message_type || "").includes("error")) {
          const motivo = msg.error || msg.message_type;
          parar();
          alFallar?.(String(motivo));
        }
    }
  };

  // Un cierre inesperado es un fallo, no el final de nada: aquí no hay "turnos" que
  // terminen. Es la misma lección que el TTS, donde tratar el `onclose` como fin de turno
  // dejó la llamada colgada oyendo el silencio sin un solo aviso.
  socket.onclose = () => {
    if (!vivo) return;
    parar();
    alFallar?.("se cerró la conexión con el transcriptor");
  };
  socket.onerror = () => {
    if (!vivo) return;
    parar();
    alFallar?.("no se pudo conectar con el transcriptor");
  };

  return { parar };
}
