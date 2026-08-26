// La voz de Jarvis por ElevenLabs: el WebSocket de síntesis y la reproducción.
//
// Aquí NO hay clave de API. El navegador se autentica con un token de un solo uso que
// emite el backend en /voz/token, vale 15 minutos y se consume al abrir el socket. La
// clave nunca sale de Fly — ver docs/JARVIS_VOZ.md y el comentario de la sección de voz
// en backend/main.py.
//
// Va en src/lib/ y no en Dashboard.jsx porque no es UI: es un cliente de red con un
// reproductor de audio dentro. La regla del proyecto (un solo fichero de UI) es sobre
// componentes, y esto no pinta nada.

import { textoParaVoz } from "./voz.js";

const WS_BASE = "wss://api.elevenlabs.io/v1/text-to-speech";

/** Abre la voz. Devuelve un objeto con `decir`, `callar` y `cerrar`, o `null` si el
 *  navegador no puede (sin WebSocket o sin AudioContext).
 *
 *  El socket se abre UNA VEZ por llamada y se reutiliza para todos los turnos: cada
 *  turno es un "contexto" dentro del mismo socket. Ese es justo el motivo de usar el
 *  endpoint multi-contexto — cerrar un contexto cancela lo que quedaba por sintetizar
 *  sin tirar la conexión, que es la primitiva del barge-in y además evita pagar audio
 *  que nadie va a oír. */
export function abrirVozEleven({ token, voiceId, modelId, formato = "mp3_44100_128", alFallar }) {
  const Contexto = typeof window !== "undefined"
    ? (window.AudioContext || window.webkitAudioContext)
    : null;
  if (!Contexto || typeof WebSocket === "undefined" || !token || !voiceId) return null;

  const ctx     = new Contexto();
  const salida  = ctx.createGain();
  salida.connect(ctx.destination);

  const url = `${WS_BASE}/${encodeURIComponent(voiceId)}/multi-stream-input`
    + `?model_id=${encodeURIComponent(modelId || "eleven_flash_v2_5")}`
    + `&output_format=${encodeURIComponent(formato)}`
    + `&single_use_token=${encodeURIComponent(token)}`;

  const ws = new WebSocket(url);
  ws.binaryType = "arraybuffer";

  let contexto     = null;   // id del contexto vivo (el turno que suena ahora)
  let alTerminar   = null;
  let finRecibido  = false;
  let huboAudio    = false;
  let ultimoTexto  = "";     // para poder repetirlo con otra voz si esta no suena
  // Frases esperando su turno. Se dicen de una en una, en orden: dos contextos a la
  // vez sonarían solapados, que es peor que esperar.
  const pendientesDeDecir = [];
  let fuentes      = new Set();
  let finProgramado = 0;
  // Las decodificaciones se encadenan en vez de lanzarse a la vez: decodeAudioData es
  // asíncrono y dos trozos en paralelo pueden acabar en orden distinto al que llegaron.
  // Una respuesta con las frases cambiadas de sitio es peor que una pausa.
  let cola         = Promise.resolve();
  let pendientes   = 0;
  const cuandoAbra = [];

  function enviar(mensaje) {
    if (ws.readyState === WebSocket.OPEN) ws.send(JSON.stringify(mensaje));
    else if (ws.readyState === WebSocket.CONNECTING) cuandoAbra.push(mensaje);
  }

  ws.onopen = () => {
    while (cuandoAbra.length) enviar(cuandoAbra.shift());
  };

  ws.onmessage = (ev) => {
    let dato;
    try { dato = JSON.parse(typeof ev.data === "string" ? ev.data : ""); } catch { return; }
    if (!dato) return;
    // Audio de un contexto que ya se canceló: llegó tarde, se tira. Sin esto, cortar a
    // Jarvis y volver a hablarle hacía que la frase interrumpida sonara encima de la
    // nueva.
    if (dato.contextId && contexto && dato.contextId !== contexto) return;
    if (dato.audio) { huboAudio = true; reproducir(dato.audio); }
    if (dato.isFinal) {
      finRecibido = true;
      // TERMINADO SIN UNA SOLA MUESTRA DE AUDIO. Pasa, y no manda ningún error al
      // hacerlo: con una voz de la biblioteca en plan gratuito, ElevenLabs contesta
      // `isFinal` y cero bytes, tan tranquilo. Sin esto Jarvis se queda mudo y no hay
      // nada en ningún sitio que diga por qué — el peor fallo posible en algo cuyo
      // único trabajo es sonar. Así que se avisa y se cae a la voz del navegador.
      if (!huboAudio) { rendirse(); return; }
      quizasTerminar();
    }
  };

  ws.onerror = () => { terminarTurno(); };
  ws.onclose = () => { terminarTurno(); };

  function reproducir(base64) {
    pendientes++;
    cola = cola.then(() => decodificar(base64)).then((buffer) => {
      pendientes--;
      if (!buffer || !contexto) { quizasTerminar(); return; }
      const fuente = ctx.createBufferSource();
      fuente.buffer = buffer;
      fuente.connect(salida);
      // Un pelín por delante del reloj: programar en `currentTime` exacto llega tarde y
      // el trozo se pierde. A partir de ahí cada uno se encadena al final del anterior,
      // que es lo que hace que no se oigan costuras entre frases.
      const inicio = Math.max(ctx.currentTime + 0.06, finProgramado);
      fuente.start(inicio);
      finProgramado = inicio + buffer.duration;
      fuentes.add(fuente);
      fuente.onended = () => { fuentes.delete(fuente); quizasTerminar(); };
    }).catch(() => { pendientes--; quizasTerminar(); });
  }

  // Restos de MP3 que no se pudieron decodificar sueltos. Los trozos que manda
  // ElevenLabs suelen venir alineados a frames y decodifican por su cuenta, pero no está
  // garantizado: cuando uno falla se guarda y se reintenta pegado al siguiente. Con PCM
  // no pasa nunca, porque no hay frames que valga.
  let sobrante = null;

  async function decodificar(base64) {
    const bytes = deBase64(base64);
    if (formato.startsWith("pcm_")) return desdePcm(bytes);
    const entrada = sobrante ? unir(sobrante, bytes) : bytes;
    try {
      const buffer = await ctx.decodeAudioData(entrada.buffer.slice(0));
      sobrante = null;
      return buffer;
    } catch {
      sobrante = entrada;
      return null;
    }
  }

  function desdePcm(bytes) {
    const hz      = parseInt(formato.split("_")[1], 10) || 24000;
    const muestras = new Int16Array(bytes.buffer, bytes.byteOffset, bytes.byteLength >> 1);
    const buffer  = ctx.createBuffer(1, muestras.length, hz);
    const canal   = buffer.getChannelData(0);
    for (let i = 0; i < muestras.length; i++) canal[i] = muestras[i] / 32768;
    return buffer;
  }

  function quizasTerminar() {
    if (!alTerminar || pendientes > 0 || fuentes.size > 0 || !finRecibido) return;
    terminarTurno();
  }

  /** Manda una frase a sintetizar y la deja sonando. */
  function arrancar(dicho, alFinal) {
    // iOS suspende el AudioContext salvo que se reanude dentro de un gesto; llamarlo
    // aquí también cubre el caso de que el móvil lo haya suspendido a media llamada.
    if (ctx.state === "suspended") ctx.resume().catch(() => {});
    contexto    = `t${Date.now()}${Math.random().toString(36).slice(2, 7)}`;
    alTerminar  = alFinal || null;
    finRecibido = false;
    huboAudio   = false;
    ultimoTexto = dicho;
    // El primer mensaje de un contexto abre el contexto: por eso va un espacio y no el
    // texto. Y el flush es lo que le dice que ya puede sintetizar sin esperar más.
    enviar({ text: " ", context_id: contexto });
    enviar({ text: dicho, context_id: contexto, flush: true });
    enviar({ context_id: contexto, close_context: true });
  }

  function terminarTurno() {
    const avisar = alTerminar;
    alTerminar   = null;
    contexto     = null;
    try { avisar?.(); } catch { /* mejor esfuerzo */ }
    const siguiente = pendientesDeDecir.shift();
    if (siguiente) arrancar(siguiente[0], siguiente[1]);
  }

  /** Esta voz no sirve: se le devuelve el turno a quien la abrió, con el texto que se
   *  quedó sin decir, para que lo diga como pueda. Se entrega el `alTerminar` también:
   *  el modo llamada encadena la escucha con él y perderlo dejaría la llamada colgada. */
  function rendirse() {
    const avisar = alTerminar;
    const texto  = ultimoTexto;
    alTerminar   = null;
    contexto     = null;
    if (alFallar) { try { alFallar(texto, avisar); return; } catch { /* abajo */ } }
    try { avisar?.(); } catch { /* mejor esfuerzo */ }
  }

  return {
    /** Dice un texto entero. `alFinal` se llama SIEMPRE, suene o no: el modo llamada
     *  encadena la escucha con él y un camino que no avisara dejaría la llamada colgada
     *  en silencio esperando a alguien que ya no va a hablar. */
    decir(texto, alFinal) {
      const dicho = textoParaVoz(texto);
      if (!dicho) { try { alFinal?.(); } catch { /* mejor esfuerzo */ } return; }
      // Se ENCOLA, no se pisa. Un turno son varias frases seguidas —"Déjame mirar el
      // calendario" y, cuatro segundos después, lo que ha encontrado— y si la segunda
      // cortara a la primera, el relleno no serviría para nada: se oiría media palabra.
      // Para cortar de verdad está `callar`, que es cosa del barge-in, no de hablar.
      if (contexto || pendientesDeDecir.length) {
        pendientesDeDecir.push([dicho, alFinal]);
        return;
      }
      arrancar(dicho, alFinal);
    },

    /** Calla AHORA: cancela lo que quedaba por sintetizar y corta lo que ya suena. Es el
     *  barge-in, y de paso deja de pagarse audio que nadie va a oír. */
    callar() {
      if (contexto) enviar({ context_id: contexto, close_context: true });
      for (const f of fuentes) { try { f.stop(); } catch { /* ya paró */ } }
      fuentes = new Set();
      finProgramado = 0;
      sobrante = null;
      // Lo que aún no había empezado a sonar también se cancela: si te has puesto a
      // hablar encima, lo que Jarvis tenía preparado ya no viene a cuento.
      pendientesDeDecir.length = 0;
      contexto = null;
      alTerminar = null;
    },

    cerrar() {
      this.callar();
      try { enviar({ close_socket: true }); } catch { /* mejor esfuerzo */ }
      try { ws.close(); } catch { /* mejor esfuerzo */ }
      try { ctx.close(); } catch { /* mejor esfuerzo */ }
    },
  };
}

function deBase64(base64) {
  const binario = atob(base64);
  const bytes   = new Uint8Array(binario.length);
  for (let i = 0; i < binario.length; i++) bytes[i] = binario.charCodeAt(i);
  return bytes;
}

function unir(a, b) {
  const junto = new Uint8Array(a.length + b.length);
  junto.set(a, 0);
  junto.set(b, a.length);
  return junto;
}
