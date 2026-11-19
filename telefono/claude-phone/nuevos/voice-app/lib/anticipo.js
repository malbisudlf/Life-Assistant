/**
 * Parche 26: transcribir durante el silencio que cierra la frase, no después.
 * Ver telefono/PARCHES.md en Life Assistant.
 *
 * El detector (audio-fork.js) da la frase por acabada tras endSilenceMs (1,5 s) de
 * silencio, y hasta aquí la transcripción empezaba entonces: ~1,1 s más de turbo en
 * jacobo, que siempre procesa una ventana de 30 s aunque la frase dure 3. Ahora, a los
 * STT_ANTICIPO_MS (400) de silencio, la sesión emite 'pausa' con lo dicho hasta ahí y
 * se le manda al oído. Si el silencio sigue hasta cerrar la frase, la transcripción ya
 * está hecha o a punto; si vuelves a hablar, esa pausa se tira y la frase entera se
 * transcribe como siempre.
 *
 * - Es el mismo modelo sobre el mismo audio (menos el silencio del final): no se
 *   cambia precisión por velocidad.
 * - Parche 34: también contra OpenAI. Una pausa a media frase son 0,03 céntimos
 *   tirados, y con jacobo caído ahorra ~1 s por turno. Y la transcripción de la pausa
 *   decide si se cierra antes: si parece una frase acabada, no se esperan los
 *   endSilenceMs enteros (session.cerrarPausa). Con jacobo se pregunta además a
 *   `small`, que tarda 0,3 s, solo para decidir eso; lo que se transcribe es turbo.
 * - Parche 38: `small` ya no va por defecto. Medido en jacobo el 2026-11-08 con audios de
 *   teléfono de 3-6 s: a la vez que turbo, la GPU se reparte y turbo pasa de 1,09 a
 *   1,26 s y small de 0,33 a 0,62. Como lo que se espera al cerrar es turbo, small
 *   adelantaba el cierre ~0,3 s pero retrasaba el texto ~0,17 s, y lo que oyes depende
 *   del texto. Sin small, el cierre lo decide turbo y el texto está listo al cerrar.
 *   ANTICIPO_RAPIDO=1 lo devuelve.
 * - No con la escucha pasiva dormida (`activo`): con la radio del coche las pausas no
 *   paran, y cada una sería una pasada más de la GPU de jacobo para nada. Parche 46:
 *   salvo que ya le hayan nombrado o lo dicho sea corto (`activo` recibe la pausa).
 * - Parche 51 (2026-11-19): `small` PRIMERO y turbo detrás. Desde el 38 el cierre rápido
 *   no saltaba nunca: lo decidía turbo, que tarda ~1,15 s, y a los 300 + 1.150 ms la
 *   frase ya se había cerrado por los 1.200 de siempre. 59 turnos seguidos con «cierre
 *   1,2» en el cronómetro, y el pitido llegaba a 1,5-2 s de dejar de hablar. Medido en
 *   jacobo ese día: small solo, 0,42 s; los dos a la vez, small 0,70 y turbo 1,35 (se
 *   reparten la GPU). En fila, small dice a los ~0,72 s de silencio si la frase está
 *   acabada —el pitido suena medio segundo antes— y turbo transcribe después, sin
 *   pelearse con nadie. A cambio el texto llega ~0,3 s más tarde que antes. Si vuelves
 *   a hablar antes de que conteste small, turbo ni se lanza: una pasada menos de GPU.
 *   Si small no contesta en ESPERA_SMALL_MS, turbo arranca igual. ANTICIPO_PRIMERO=0
 *   vuelve a lo del 38 (solo turbo); ANTICIPO_RAPIDO=1, a los dos a la vez.
 */

const OPCIONES = { format: 'pcm', sampleRate: 16000, language: 'es' };

function rapidoActivo() {
  return process.env.ANTICIPO_RAPIDO === '1';
}

function primeroActivo() {
  return process.env.ANTICIPO_PRIMERO !== '0' && !rapidoActivo();
}

// Lo que se espera a small antes de lanzar turbo de todos modos. Con jacobo bien, small
// tarda 0,42 s; más de esto es que está atascado, y turbo no puede esperarle.
function esperaSmallMs() {
  const n = parseInt(process.env.ANTICIPO_ESPERA_SMALL_MS || '700', 10);
  return n > 0 ? n : 700;
}

/**
 * Parche 51: si esta pausa sigue siendo la del detector. Deja de serlo si has vuelto a
 * hablar o si la frase ya se cerró sin ella (por los 1.200 ms enteros); entonces su
 * turbo no lo va a usar nadie.
 */
function pausaVigente(session, pausa) {
  return pausa.completa === true || session._pausa === pausa;
}

function conTope(promesa, ms) {
  let reloj;
  const tope = new Promise(function (resolve) { reloj = setTimeout(function () { resolve(null); }, ms); });
  return Promise.race([promesa.catch(function () { return null; }), tope])
    .then(function (x) { clearTimeout(reloj); return x; });
}

/**
 * Engancha el anticipo a la sesión de audio de una llamada.
 * @param {Object}   session        - AudioForkSession
 * @param {Object}   whisperClient
 * @param {Object}   [p]
 * @param {Function} [p.activo]     - () => boolean; false para no anticipar ahora
 * @returns {Function} lo desengancha
 */
function armarAnticipo(session, whisperClient, p) {
  p = p || {};
  if (!session || typeof session.on !== 'function') return function () {};
  if (!whisperClient || typeof whisperClient.oidoDisponible !== 'function') return function () {};
  const activo = p.activo || function () { return true; };
  const alPausar = function (pausa) {
    if (!activo(pausa)) return;
    pausa.desde = Date.now();
    const decidir = function (texto) {
      if (pareceCompleta(texto) && typeof session.cerrarPausa === 'function') session.cerrarPausa(pausa);
    };
    if (primeroActivo() && whisperClient.oidoDisponible()) {
      // Parche 51: small decide el cierre; turbo, detrás, da el texto.
      const small = whisperClient.transcribe(pausa.audio, Object.assign({ soloOido: true, rapido: true }, OPCIONES));
      small.then(decidir, function () {});
      pausa.transcripcion = conTope(small, esperaSmallMs()).then(function () {
        if (!pausaVigente(session, pausa)) throw new Error('pausa sin vigencia');
        return whisperClient.transcribe(pausa.audio, OPCIONES);
      });
      pausa.transcripcion.catch(function () {});
      return;
    }
    pausa.transcripcion = whisperClient.transcribe(pausa.audio, OPCIONES);
    // Que una pausa tirada que falla no acabe en un unhandledRejection.
    pausa.transcripcion.catch(function () {});
    pausa.transcripcion.then(decidir, function () {});
    if (rapidoActivo() && whisperClient.oidoDisponible()) {
      whisperClient.transcribe(pausa.audio, Object.assign({ soloOido: true, rapido: true }, OPCIONES))
        .then(decidir, function () {});
    }
  };
  session.on('pausa', alPausar);
  return function () { session.off('pausa', alPausar); };
}

/**
 * La transcripción de una frase: la del anticipo si la frase la cerró esa pausa y
 * salió bien; si no, la de la frase entera, con la reserva de OpenAI de siempre.
 */
async function transcribirFrase(whisperClient, utterance, log) {
  const pausa = utterance && utterance.pausa;
  if (pausa && pausa.transcripcion) {
    const t0 = Date.now();
    try {
      const texto = await pausa.transcripcion;
      if (log) log('ANTICIPO: transcrita durante el silencio; al cerrar la frase, ' + (Date.now() - t0) + ' ms de espera');
      if (typeof whisperClient.sombra === 'function') whisperClient.sombra(utterance.audio, texto, OPCIONES);
      return texto;
    } catch (e) {
      if (log) log('ANTICIPO: falló (' + e.message + '); transcribo la frase entera');
    }
  }
  return whisperClient.transcribe(utterance.audio, OPCIONES);
}

// Lo que deja la frase claramente a medias, si acaba en ello. Whisper pone punto final
// aunque te hayas quedado pensando, así que el punto no dice nada.
const A_MEDIAS = /(?:^|\s)(?:y|e|o|u|ni|que|de|del|a|al|en|por|para|con|sin|pero|porque|si|como|cuando|donde|el|la|los|las|un|una|unos|unas|mi|mis|tu|tus|su|sus|me|te|se|lo|le|les|nos|es|eh|em|mm+|este|esto|esta|pues|entonces|o sea|a ver|tambien|también|mas|más|muy|ya que|y que)$/i;

function pareceCompleta(texto) {
  const s = String(texto || '').trim();
  if (s.length < 2) return false;
  if (/(?:\.\.\.|…|,|:|;|-)$/.test(s)) return false;
  const sin = s.replace(/[.?!¿¡"»”]+$/, '').trim();
  return sin.length > 0 && !A_MEDIAS.test(sin);
}

module.exports = { armarAnticipo, transcribirFrase, pareceCompleta, rapidoActivo, primeroActivo, OPCIONES };
