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
 */

const OPCIONES = { format: 'pcm', sampleRate: 16000, language: 'es' };

function rapidoActivo() {
  return process.env.ANTICIPO_RAPIDO === '1';
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
    pausa.transcripcion = whisperClient.transcribe(pausa.audio, OPCIONES);
    // Que una pausa tirada que falla no acabe en un unhandledRejection.
    pausa.transcripcion.catch(function () {});
    const decidir = function (texto) {
      if (pareceCompleta(texto) && typeof session.cerrarPausa === 'function') session.cerrarPausa(pausa);
    };
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

module.exports = { armarAnticipo, transcribirFrase, pareceCompleta, rapidoActivo, OPCIONES };
