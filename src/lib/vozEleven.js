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
  let turnoVivo    = false;  // hay un turno en marcha (aunque nadie espere su final)
  let finRecibido  = false;
  let sono         = false;  // no "llegaron bytes": SONÓ. Ver `quizasTerminar`
  let ultimoTexto  = "";     // para poder repetirlo con otra voz si esta no suena
  // Esta voz ya no vale para nada más (token caducado, socket caído, turno mudo). Se
  // marca para que las frases siguientes se caigan a la voz del navegador AL INSTANTE en
  // vez de encolarse contra un socket que no las va a sintetizar nunca.
  let muerto       = false;
  let cerradoAqui  = false;  // el cierre lo pedimos nosotros: no es una caída
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
    // nueva. Se compara SIEMPRE, no solo cuando `contexto` está a algo: `callar()` lo
    // deja a null, y comparar solo si es verdadero dejaba pasar el resto de un turno
    // cortado durante esa ventana.
    if (dato.contextId && dato.contextId !== contexto) return;
    // El servidor manda los fallos POR EL SOCKET y luego lo cierra. El más frecuente con
    // diferencia es `invalid_token` ("Token not found or has expired"): el token de
    // /voz/token dura 15 minutos, y en el móvil es normalísimo abrir el dashboard, dejar
    // el teléfono en el bolsillo y llamar media hora después. Sin mirar esto, el error se
    // ignoraba en silencio y Jarvis se quedaba mudo sin decir por qué.
    if (dato.error || dato.message) { rendirse(); return; }
    if (dato.audio) reproducir(dato.audio, contexto);
    if (dato.isFinal) { finRecibido = true; quizasTerminar(); }
  };

  // Una caída del socket a media llamada NO es el final normal de un turno: quien
  // esperaba la voz tiene que enterarse y seguir con la del navegador. Tratarlo como un
  // final normal dejaba la llamada colgada — el turno siguiente se "arrancaba" contra un
  // socket cerrado, `enviar` lo tiraba sin ruido y nadie volvía a llamar a `alTerminar`.
  ws.onerror = () => { if (!cerradoAqui) rendirse(); };
  ws.onclose = () => { if (!cerradoAqui) rendirse(); };

  function reproducir(base64, contextoDeEstaFrase) {
    pendientes++;
    cola = cola.then(() => decodificar(base64)).then((buffer) => {
      pendientes--;
      // La decodificación es asíncrona: si para cuando termina ya se ha cortado el
      // turno (`callar()`) y arrancado el siguiente, `contexto` vuelve a ser verdadero
      // pero de OTRO turno. Comparar con el que tenía este trozo al llegar —no solo
      // mirar si hay alguno— es lo que evita que suene mezclado con la respuesta nueva.
      if (!buffer || contexto !== contextoDeEstaFrase) { quizasTerminar(); return; }
      const fuente = ctx.createBufferSource();
      fuente.buffer = buffer;
      fuente.connect(salida);
      // Un pelín por delante del reloj: programar en `currentTime` exacto llega tarde y
      // el trozo se pierde. A partir de ahí cada uno se encadena al final del anterior,
      // que es lo que hace que no se oigan costuras entre frases.
      const inicio = Math.max(ctx.currentTime + 0.06, finProgramado);
      fuente.start(inicio);
      sono = true;
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
    if (!turnoVivo || pendientes > 0 || fuentes.size > 0 || !finRecibido) return;
    // TURNO TERMINADO SIN QUE HAYA SONADO NADA. Dos casos distintos con el mismo
    // remedio: ElevenLabs contesta `isFinal` con cero bytes y ningún error (lo hace con
    // una voz de la biblioteca en plan gratuito), o los bytes llegan pero no hay manera
    // de decodificarlos. Lo que importa no es que llegara audio, sino que sonara; medir
    // lo primero daba por buena una respuesta que nadie oyó.
    if (!sono) { rendirse(); return; }
    terminarTurno();
  }

  /** Manda una frase a sintetizar y la deja sonando. */
  function arrancar(dicho, alFinal) {
    ultimoTexto = dicho;
    alTerminar  = alFinal || null;
    // Contra un socket ya cerrado no se arranca nada: `enviar` tiraría los mensajes sin
    // ruido y el turno se quedaría esperando un `isFinal` que no va a llegar.
    if (muerto || ws.readyState > WebSocket.OPEN) { rendirse(); return; }
    // iOS suspende el AudioContext salvo que se reanude dentro de un gesto; llamarlo
    // aquí también cubre el caso de que el móvil lo haya suspendido a media llamada.
    if (ctx.state === "suspended") ctx.resume().catch(() => {});
    contexto    = `t${Date.now()}${Math.random().toString(36).slice(2, 7)}`;
    turnoVivo   = true;
    finRecibido = false;
    sono        = false;
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
    turnoVivo    = false;
    try { avisar?.(); } catch { /* mejor esfuerzo */ }
    const siguiente = pendientesDeDecir.shift();
    if (siguiente) arrancar(siguiente[0], siguiente[1]);
  }

  /** Esta voz no sirve: se le devuelve a quien la abrió TODO lo que se quedó sin decir
   *  —la frase que estaba en el aire y las que esperaban cola— para que lo diga como
   *  pueda. Cada una va con su `alFinal`: el modo llamada encadena la escucha con el de
   *  la última, y perderlo dejaría la llamada colgada oyendo el silencio.
   *
   *  A partir de aquí la voz queda muerta: lo que se le mande después se cae al
   *  navegador sin pasar por el socket. */
  function rendirse() {
    const seguiaVivo = turnoVivo || pendientesDeDecir.length > 0;
    const sinDecir   = turnoVivo ? [[ultimoTexto, alTerminar]] : [];
    sinDecir.push(...pendientesDeDecir);
    pendientesDeDecir.length = 0;
    muerto     = true;
    turnoVivo  = false;
    alTerminar = null;
    contexto   = null;
    if (!seguiaVivo) return;   // se cayó sin nada en la boca: no hay nada que rescatar
    if (alFallar) { try { alFallar(sinDecir); return; } catch { /* abajo */ } }
    for (const [, avisar] of sinDecir) {
      try { avisar?.(); } catch { /* mejor esfuerzo */ }
    }
  }

  return {
    /** Dice un texto entero. `alFinal` se llama SIEMPRE, suene o no: el modo llamada
     *  encadena la escucha con él y un camino que no avisara dejaría la llamada colgada
     *  en silencio esperando a alguien que ya no va a hablar. */
    decir(texto, alFinal) {
      const dicho = textoParaVoz(texto);
      if (!dicho) { try { alFinal?.(); } catch { /* mejor esfuerzo */ } return; }
      // Voz ya descartada: se devuelve en el acto en vez de encolar contra un socket
      // muerto. Quien la abrió puede seguir teniendo la referencia un instante más —
      // `alFallar` es asíncrono para él— y esa frase no puede perderse.
      if (muerto) {
        if (alFallar) { try { alFallar([[dicho, alFinal]]); return; } catch { /* abajo */ } }
        try { alFinal?.(); } catch { /* mejor esfuerzo */ }
        return;
      }
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
      turnoVivo = false;
      alTerminar = null;
    },

    cerrar() {
      // Antes de cerrar: este cierre es nuestro, y `onclose` no debe confundirlo con una
      // caída y ponerse a rescatar frases de una llamada que ya se ha colgado.
      cerradoAqui = true;
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
