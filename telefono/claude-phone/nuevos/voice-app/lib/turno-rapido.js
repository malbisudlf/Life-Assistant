/**
 * Parches 15 y 16: lo que comparten las dos conversaciones (la entrante, en
 * sip-handler.js, y la saliente, en conversation-loop.js), que son dos bucles
 * copiados y había que tocar igual. Ver telefono/PARCHES.md en Life Assistant.
 *
 * - pensar() (parche 15): Claude se pone a pensar a la vez que suena la frase de
 *   espera, no después. Antes se esperaba a que la frase terminara (~1,5-2 s por
 *   turno sin hacer nada), y la música de espera sonaba aunque Claude ya hubiera
 *   contestado.
 * - decirInterrumpible() (parche 16, barge-in): mientras Jarvis contesta, el oído
 *   sigue abierto; si te pones a hablar, se calla y lo que dices es el turno
 *   siguiente. Se apaga con BARGE_IN=0. El audio que llega al detector es solo tu
 *   lado de la línea (forkAudioStart con mixType 'mono'), así que la voz de Jarvis
 *   no se interrumpe a sí misma.
 */

// Lo que se le antepone a Claude cuando le has cortado: sin esto cree que oíste la
// respuesta entera y puede dar por sabido lo que no llegaste a oír.
const AVISO_INTERRUPCION = '[Te ha interrumpido mientras hablabas: puede que no oyera el final de tu respuesta] ';

function bargeInActivo() {
  return process.env.BARGE_IN !== '0';
}

/**
 * Pregunta a Claude y, mientras piensa, dice la frase de espera y pone la música.
 * Devuelve lo que conteste Claude (o lanza lo que lance claudeBridge.query).
 *
 * @param {Object} p
 * @param {Function} p.consultar   - () => Promise<string>, la llamada a claudeBridge.query
 * @param {Object}   p.endpoint
 * @param {Object}   p.ttsService
 * @param {string}   p.frase       - la frase de espera
 * @param {string}   p.voiceId
 * @param {string}   p.musicaUrl
 * @param {Function} [p.sigueActiva] - () => boolean; false si se ha colgado
 */
async function pensar(p) {
  const sigueActiva = p.sigueActiva || function () { return true; };
  let listo = false;
  const consulta = Promise.resolve().then(p.consultar);
  // Marca el final sin tragarse el error: el `await consulta` de abajo lo relanza.
  // Parche 34: y en cuanto Claude contesta se sintetiza la respuesta, sin esperar a
  // que acabe la frase de espera (`extraer` saca de la respuesta lo que se va a decir).
  consulta.then(function (respuesta) {
    listo = true;
    try {
      if (p.extraer && p.ttsService.anticipar) p.ttsService.anticipar(p.extraer(respuesta), p.voiceId);
    } catch (e) { /* lo intentará quien llama */ }
  }, function () { listo = true; });

  // Parche 34: la mayoría de las respuestas sin herramientas llegan antes de esto, y
  // entonces no hace falta decir «un momento» para contestar justo después.
  const esperaMs = parseInt(process.env.ESPERA_FRASE_MS || '2500', 10);
  await new Promise(function (resolve) {
    const reloj = setTimeout(resolve, esperaMs);
    consulta.then(function () { clearTimeout(reloj); resolve(); }, function () { clearTimeout(reloj); resolve(); });
  });
  if (sigueActiva() && !listo) {
    // Un adorno no puede tumbar la llamada: el 2026-11-04, un File Not Found aquí
    // acababa en «Perdona, algo ha fallado» y colgaba con la respuesta en camino.
    try {
      const fraseUrl = await p.ttsService.generateSpeech(p.frase, p.voiceId);
      if (sigueActiva() && !listo) await p.endpoint.play(fraseUrl);
    } catch (e) {
      console.warn('[PENSAR] La frase de espera falló (' + e.message + '); se sigue esperando');
    }
  }

  let musica = false;
  if (sigueActiva() && !listo) {
    Promise.resolve().then(function () { return p.endpoint.play(p.musicaUrl); }).catch(function () {});
    musica = true;
  }

  try {
    return await consulta;
  } finally {
    if (musica && sigueActiva()) {
      try { await p.endpoint.api('uuid_break', p.endpoint.uuid); } catch (e) { /* ya parada */ }
    }
  }
}

/**
 * Reproduce `url` dejando que la persona interrumpa. Devuelve true si interrumpió:
 * entonces el oído sigue abierto con lo que está diciendo, y el turno siguiente
 * tiene que saltarse el pitido y esperar esa frase. Si no interrumpió, deja el oído
 * cerrado, como estaba.
 */
async function decirInterrumpible(endpoint, session, url, log) {
  if (!bargeInActivo() || !session || typeof session.armarBargeIn !== 'function') {
    await endpoint.play(url);
    return false;
  }
  let cortado = false;
  const alInterrumpir = function () {
    cortado = true;
    if (log) log('BARGE-IN: te pones a hablar, Jarvis se calla');
    endpoint.api('uuid_break', endpoint.uuid).catch(function () {});
  };
  session.on('barge', alInterrumpir);
  session.armarBargeIn();
  try {
    await endpoint.play(url);
  } finally {
    session.off('barge', alInterrumpir);
    if (!cortado) session.setCaptureEnabled(false);
  }
  return cortado;
}

module.exports = { pensar, decirInterrumpible, bargeInActivo, AVISO_INTERRUPCION };
