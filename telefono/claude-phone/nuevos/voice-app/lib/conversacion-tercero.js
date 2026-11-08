/**
 * Parche 32: la conversación de Jarvis con OTRA persona (llamar_a_alguien).
 * Ver telefono/PARCHES.md y docs/LLAMADAS_TERCEROS.md en Life Assistant.
 *
 * No es la conversación de siempre (conversation-loop.js), a propósito:
 *   - **El cerebro es el backend, no Claude Code.** Cada frase del otro va a
 *     `POST /telefono/tercero/{id}/turno`, que la piensa con un modelo SIN herramientas.
 *     El Claude de claude-api-server tiene shell en caja: lo que diga un desconocido por
 *     teléfono no puede llegar a él.
 *   - **Sin pitidos, sin música de espera, sin «Un momento, señor».** Eso es para Mikel;
 *     a un amigo suyo le suena a centralita.
 *   - **Primero contesta él.** Quien coge dice «¿Sí?»: se le deja decirlo y entonces
 *     Jarvis se presenta. Hablar nada más descolgar pisa el «¿Diga?» y lo primero que oye
 *     es media frase. Pero sin la espera de una frase normal (`esperarSaludo`): los 1,5 s
 *     de silencio que cierran un turno, más 4 s de tope, eran casi todo el retraso entre
 *     descolgar y oír algo (~4,8 s el 2026-11-01).
 *   - **Lo que se puede, por adelantado.** La presentación se genera mientras suena, el
 *     backend (Claude) prepara un guion con las respuestas probables y aquí se genera su
 *     voz mientras habla el otro (`prepararGuion`): si la respuesta es del guion, suena al
 *     instante. Y se transcribe con el modelo pequeño del oído (`conModeloRapido`).
 *   - Nada de lectura, confirmaciones ni escucha pasiva: aquí no hay nada de eso que hacer.
 *   - **Sin barge-in (parche 35).** Jarvis dice su frase entera, con el oído cerrado: lo
 *     que el otro diga encima no le corta ni cuenta como turno. Mikel lo quiso así
 *     (2026-11-05). En sus propias llamadas con Jarvis se le sigue pudiendo cortar.
 */

const { armarAnticipo, transcribirFrase } = require('./anticipo');

// El saludo: tope total, lo que se espera a que empiece a hablar y el silencio que lo da
// por dicho (un «¿Sí?» no necesita los 1,5 s de `endSilenceMs`).
const ESPERA_SALUDO_MS = 3000;
const SALUDO_NADIE_MS = 2000;
const SALUDO_SILENCIO_MS = 450;
const SALUDO_SONDEO_MS = 50;
// La voz mínima para que una frase cuente. La de siempre (350 ms, audio-fork.js) tiraba
// un «sí» suelto de 300 ms (2026-11-01), y aquí un «sí» o un «vale» es justo la
// respuesta que se busca. El ruido suelto se queda en decenas de ms: sigue fuera.
const VOZ_MINIMA_MS = 200;
// El silencio que da una frase por acabada. El de siempre (1,5 s, audio-fork.js) es para
// hablar con Jarvis, que a veces se piensa lo que dice; aquí son respuestas cortas
// («sí», «a las dos») y ese medio segundo largo se notaba en cada turno (2026-11-01).
// La transcripción anticipada (400 ms, parche 26) sigue cabiendo antes.
const FIN_FRASE_MS = 900;
const ESPERA_TURNO_MS = 15000;
const TURNOS_MAX = 20;
const PREGUNTA_BACKEND_MS = 15000;
// Lo más que se espera a FreeSWITCH al cerrar el audio: con la llamada ya colgada,
// forkAudioStop puede no contestar nunca (EPIPE) y dejar la conversación sin terminar.
const CIERRE_MS = 2000;
// El buzón de voz. Un «¿Sí?» dura menos de un segundo; una locución («El número al que
// llama no está disponible; deje su mensaje después de la señal»), varios. Si a los
// ESPERA_SALUDO_MS sigue hablando, se le deja acabar (hasta LOCUCION_MAX_MS); y con más
// de SALUDO_LARGO_MS de audio se mira qué ha dicho antes de presentarse. Si es un buzón,
// se espera al pitido (PITIDO_SILENCIO_MS callado tras él) y se deja el recado: la
// presentación, que ya dice el motivo, y FRASES.recado. Sin esto, Jarvis se presentaba
// encima de la locución y el buzón le cortaba (2026-11-01).
const SALUDO_LARGO_MS = 1800;
const LOCUCION_MAX_MS = 30000;
const BUZON_TRANSCRIPCION_MS = 3000;
// Una locución grabada hace pausas entre frases; 1,5 s callado ya es el pitido y después.
const PITIDO_SILENCIO_MS = 1500;
const PITIDO_MAX_MS = 15000;
// Lo que dice un buzón. Va por lo que transcribe el oído, que con el modelo pequeño y el
// idioma en español TRADUCE las locuciones en inglés: la de Mikel salió como «Tu llamada
// ha estado forwardada a Voice Mail. Si lo estás intentando alcanzar, no es disponible»
// (2026-11-01). Por eso hay palabras de los dos idiomas y de la traducción.
const BUZON_RE = new RegExp([
  'mensaje', 'se[ñn]al', 'buz[oó]n', 'contestador', 'correo de voz', 'voice ?mail',
  'disponible', 'available', 'grab(e|ar|aci)', 'tono', 'desv[ií]', 'forward', 'alcanzar',
  'leave a message', 'after the (tone|beep)'
].join('|'), 'i');

const FRASES = {
  hola: '¿Hola? ¿Me oyes?',
  repite: 'Perdona, no te he entendido bien. ¿Me lo repites?',
  fallo: 'Perdona, se me ha cortado algo por aquí. Mikel te escribirá. ¡Hasta luego!',
  tope: 'Bueno, te dejo, que se lo cuento a Mikel. ¡Hasta luego!',
  recado: 'Cuando puedas, contéstale a Mikel. ¡Hasta luego!'
};

function dormir(ms) {
  return new Promise(function (r) { setTimeout(r, ms); });
}

/** Milisegundos de audio: 16 kHz, 16 bits, mono (el fork de FreeSWITCH). */
function duracionMs(audio) {
  return audio ? audio.length / 32 : 0;
}

/**
 * Espera el «¿Sí?» de quien descuelga, sin la espera de un turno normal. Vuelve con
 * {audio} en cuanto, tras hablar, lleva SALUDO_SILENCIO_MS callado (o la frase se cierra
 * sola); con null si en SALUDO_NADIE_MS no ha empezado a hablar; y si a los
 * ESPERA_SALUDO_MS sigue hablando, con lo dicho y `larga` (una locución). Mira el estado del detector de voz de la sesión (audio-fork.js), que
 * es quien sabe si está hablando; quien llama apaga la captura después, lo que descarta
 * la frase a medias.
 */
function esperarSaludo(session) {
  return new Promise(function (resolver) {
    const inicio = Date.now();
    let hecho = false;
    const acabar = function (u) {
      if (hecho) return;
      hecho = true;
      clearInterval(sondeo);
      session.off('utterance', alAcabar);
      resolver(u || null);
    };
    const loDicho = function () {
      return session._utteranceChunks && session._utteranceChunks.length
        ? { audio: Buffer.concat(session._utteranceChunks) } : null;
    };
    const alAcabar = function (u) { acabar(u); };
    session.on('utterance', alAcabar);
    const sondeo = setInterval(function () {
      const pasado = Date.now() - inicio;
      if (session._inSpeech && session._silenceMs >= SALUDO_SILENCIO_MS) return acabar(loDicho());
      if (!session._inSpeech && pasado >= SALUDO_NADIE_MS) return acabar(null);
      if (pasado >= ESPERA_SALUDO_MS) {
        return acabar(session._inSpeech
          ? Object.assign(loDicho() || { audio: Buffer.alloc(0) }, { larga: true }) : null);
      }
    }, SALUDO_SONDEO_MS);
  });
}

/**
 * Deja acabar una locución larga: vuelve con la frase entera (`larga`) cuando el detector
 * la cierra, o con lo último que tenía si la tira o pasa LOCUCION_MAX_MS.
 */
function esperarLocucion(session) {
  return new Promise(function (resolver) {
    const inicio = Date.now();
    let ultimo = null;
    let hecho = false;
    const acabar = function (u) {
      if (hecho) return;
      hecho = true;
      clearInterval(sondeo);
      session.off('utterance', alAcabar);
      resolver(u || ultimo);
    };
    const alAcabar = function (u) { acabar(Object.assign({}, u, { larga: true })); };
    session.on('utterance', alAcabar);
    const sondeo = setInterval(function () {
      if (session._utteranceChunks && session._utteranceChunks.length) {
        ultimo = { audio: Buffer.concat(session._utteranceChunks), larga: true };
      }
      if (!session._inSpeech || Date.now() - inicio >= LOCUCION_MAX_MS) acabar(null);
    }, SALUDO_SONDEO_MS);
  });
}

/** El pitido del buzón: espera a PITIDO_SILENCIO_MS sin voz (el pitido cuenta como voz). */
function esperarSilencio(session) {
  return new Promise(function (resolver) {
    const inicio = Date.now();
    let callado = Date.now();
    const sondeo = setInterval(function () {
      if (session._inSpeech) callado = Date.now();
      if (Date.now() - callado >= PITIDO_SILENCIO_MS || Date.now() - inicio >= PITIDO_MAX_MS) {
        clearInterval(sondeo);
        resolver();
      }
    }, SALUDO_SONDEO_MS);
  });
}

function backendUrl() {
  return (process.env.LECTURA_URL || 'http://127.0.0.1:8080').replace(/\/+$/, '');
}

// Cada cuánto se pregunta por el guion y hasta cuándo: lo prepara Claude mientras suena.
const GUION_SONDEO_MS = 1000;
const GUION_ESPERA_MS = 20000;

/**
 * El mismo cliente del oído, pidiendo el modelo pequeño: aquí las respuestas son cortas
 * («sí», «a las cinco») y `small` tarda ~0,3 s donde `turbo` tarda ~1,1.
 */
function conModeloRapido(whisperClient) {
  if (!whisperClient || typeof whisperClient.transcribe !== 'function') return whisperClient;
  return {
    oidoDisponible: whisperClient.oidoDisponible ? whisperClient.oidoDisponible.bind(whisperClient) : undefined,
    transcribe: function (audio, opciones) {
      return whisperClient.transcribe(audio, Object.assign({}, opciones, { rapido: true }));
    }
  };
}

/**
 * Pide al backend las frases del guion y genera su voz ya, en `cache` (texto → promesa de
 * URL). Pregunta hasta que esté (`listo`) o pasen GUION_ESPERA_MS. Nunca lanza.
 */
async function prepararGuion(o, cache, voiceId, log) {
  const fetchFn = o.fetch || fetch;
  const url = backendUrl() + '/telefono/tercero/' + encodeURIComponent(o.tercero) + '/guion';
  const hasta = Date.now() + GUION_ESPERA_MS;
  while (Date.now() < hasta) {
    try {
      const r = await fetchFn(url, { headers: { 'X-Auth-Token': process.env.TELEFONO_TERCEROS_TOKEN || '' },
                                     signal: AbortSignal.timeout(3000) });
      if (r.status === 404) return;
      if (r.ok) {
        const d = await r.json();
        const frases = Array.isArray(d && d.frases) ? d.frases : [];
        for (const f of frases) {
          const texto = String(f || '').trim();
          if (texto && !cache.has(texto)) {
            cache.set(texto, o.ttsService.generateSpeech(texto, voiceId).catch(function () { return null; }));
          }
        }
        if (frases.length || (d && d.listo)) {
          log('TERCERO: guion de ' + frases.length + ' frases, voz pedida por adelantado');
          return;
        }
      }
    } catch (e) { /* el backend tarda o no está: se vuelve a preguntar */ }
    await new Promise(function (r) { setTimeout(r, o.guionSondeoMs || GUION_SONDEO_MS); });
  }
}

/**
 * Lo que contesta Jarvis a lo que ha dicho el otro: {decir, colgar}. Si el backend no
 * contesta, la despedida y colgar: una llamada a un tercero sin cerebro no se alarga.
 */
async function preguntarAlBackend(tercero, dicho, opciones) {
  const fetchFn = (opciones && opciones.fetch) || fetch;
  const ctl = new AbortController();
  const vigia = setTimeout(function () { ctl.abort(); }, PREGUNTA_BACKEND_MS);
  try {
    const r = await fetchFn(backendUrl() + '/telefono/tercero/' + encodeURIComponent(tercero) + '/turno', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json',
                 'X-Auth-Token': process.env.TELEFONO_TERCEROS_TOKEN || '' },
      body: JSON.stringify({ dicho: String(dicho || '').slice(0, 2000) }),
      signal: ctl.signal
    });
    if (!r.ok) throw new Error('backend ' + r.status);
    const d = await r.json();
    const decir = String((d && d.decir) || '').trim();
    if (!decir) throw new Error('respuesta vacía');
    return { decir: decir, colgar: Boolean(d.colgar) };
  } catch (e) {
    if (opciones && opciones.log) opciones.log('TERCERO: el backend no contestó (' + e.message + ')');
    return { decir: FRASES.fallo, colgar: true, fallo: true };
  } finally {
    clearTimeout(vigia);
  }
}

/**
 * @param {Object} endpoint - FreeSWITCH
 * @param {Object} dialog   - drachtio
 * @param {string} callId
 * @param {Object} o
 * @param {Object} o.audioForkServer
 * @param {Object} o.whisperClient
 * @param {Object} o.ttsService
 * @param {number} o.wsPort
 * @param {string} o.tercero    - el id de la llamada en el backend
 * @param {string} o.apertura   - la presentación («Hola, Erik. Soy Jarvis…»)
 * @param {Promise<string>} [o.aperturaUrl] - la presentación ya pedida a la voz mientras
 *   sonaba; si falla (null), se pide aquí
 * @param {string} [o.voiceId]
 * @param {Function} [o.onTurno] - (quien, texto) por cada frase, para GET /api/call
 * @param {Function} [o.onUserTurn]
 * @param {Function} [o.log]
 * @param {Function} [o.fetch]
 * @returns {Promise<{endReason: string}>} 'goodbye', 'silence', 'hangup', 'max_turns',
 *   'no_audio' o 'error'
 */
async function runConversacionTercero(endpoint, dialog, callId, o) {
  const log = o.log || function () {};
  const voiceId = o.voiceId || null;
  let activa = true;
  const alColgar = function () { activa = false; };
  dialog.on('destroy', alColgar);
  let session = null;
  let fork = false;
  let desarmar = function () {};
  let fin = 'max_turns';
  const oido = conModeloRapido(o.whisperClient);
  const guion = new Map();
  prepararGuion(o, guion, voiceId, log);

  const decir = async function (texto, previa) {
    if (o.onTurno) o.onTurno('jarvis', texto);
    const lista = previa || guion.get(texto);
    const url = (lista && await lista) || await o.ttsService.generateSpeech(texto, voiceId);
    if (!activa) return;
    await endpoint.play(url);
  };

  try {
    const esperada = o.audioForkServer.expectSession(callId, { timeoutMs: 10000 });
    await endpoint.forkAudioStart({
      wsUrl: 'ws://127.0.0.1:' + o.wsPort + '/' + encodeURIComponent(callId),
      mixType: 'mono',
      sampling: '16k'
    });
    fork = true;
    try {
      session = await esperada;
    } catch (e) {
      log('TERCERO: sin audio (' + e.message + ')');
      fin = 'no_audio';
      return { endReason: fin };
    }
    desarmar = armarAnticipo(session, oido);
    if (typeof session.minSpeechMs === 'number') session.minSpeechMs = Math.min(session.minSpeechMs, VOZ_MINIMA_MS);
    if (typeof session.endSilenceMs === 'number') session.endSilenceMs = Math.min(session.endSilenceMs, FIN_FRASE_MS);

    // El «¿Sí?» del otro: se espera lo justo y Jarvis se presenta enseguida. Se transcribe
    // de fondo, para el historial; solo si es largo (una locución) se mira antes qué dice.
    session.setCaptureEnabled(true);
    let saludo = await (o.esperarSaludo || esperarSaludo)(session);
    if (saludo && saludo.larga && activa) {
      saludo = (await (o.esperarLocucion || esperarLocucion)(session)) || saludo;
    }
    let buzon = false;
    let transcrito = null;
    if (saludo && activa) {
      transcrito = transcribirFrase(oido, saludo, log).catch(function () { return ''; });
      if (saludo.larga || duracionMs(saludo.audio) >= SALUDO_LARGO_MS) {
        const t = String(await Promise.race([transcrito, dormir(BUZON_TRANSCRIPCION_MS).then(function () { return ''; })]) || '');
        buzon = BUZON_RE.test(t);
        if (buzon && activa) {
          log('TERCERO: buzón de voz («' + t.slice(0, 60) + '»); espero al pitido');
          await (o.esperarSilencio || esperarSilencio)(session);
        }
      }
    }
    session.setCaptureEnabled(false);
    if (!activa) { fin = 'hangup'; return { endReason: fin }; }
    if (transcrito) {
      transcrito.then(function (t) {
        if (t && t.trim()) {
          if (o.onTurno) o.onTurno('otro', t.trim());
          if (o.onUserTurn) o.onUserTurn(t.trim());
        }
      });
    }
    if (buzon) {
      // El recado: la presentación (ya dice quién y para qué) y que le conteste a Mikel.
      await decir(o.apertura, o.aperturaUrl);
      if (activa) await decir(FRASES.recado);
      fin = activa ? 'voicemail' : 'hangup';
      return { endReason: fin };
    }

    await decir(o.apertura, o.aperturaUrl);
    let silencios = 0;
    let turnos = 0;

    while (activa && turnos < TURNOS_MAX) {
      turnos++;
      session.setCaptureEnabled(true);
      let frase = null;
      try {
        frase = await session.waitForUtterance({ timeoutMs: ESPERA_TURNO_MS });
      } catch (e) { /* silencio */ }
      session.setCaptureEnabled(false);
      if (!activa) break;

      if (!frase) {
        silencios++;
        if (silencios >= 2) { fin = 'silence'; break; }
        await decir(FRASES.hola);
        continue;
      }
      silencios = 0;

      const dicho = String(await transcribirFrase(oido, frase, log).catch(function () { return ''; }) || '').trim();
      if (!activa) break;
      if (turnos === 1 && BUZON_RE.test(dicho)) {
        // El buzón se ha reconocido tarde (la locución hizo una pausa y Jarvis ya se había
        // presentado encima): se espera al pitido y se deja el recado entero.
        log('TERCERO: buzón de voz en la primera respuesta («' + dicho.slice(0, 60) + '»); espero al pitido');
        if (o.onTurno) o.onTurno('otro', dicho);
        session.setCaptureEnabled(true);
        await (o.esperarSilencio || esperarSilencio)(session);
        session.setCaptureEnabled(false);
        if (activa) await decir(o.apertura, o.aperturaUrl);
        if (activa) await decir(FRASES.recado);
        fin = activa ? 'voicemail' : 'hangup';
        return { endReason: fin };
      }
      if (dicho.length < 2) {
        await decir(FRASES.repite);
        continue;
      }
      log('TERCERO: oído «' + dicho.slice(0, 80) + '»');
      if (o.onTurno) o.onTurno('otro', dicho);
      if (o.onUserTurn) o.onUserTurn(dicho);

      const r = await preguntarAlBackend(o.tercero, dicho, { log: log, fetch: o.fetch });
      if (!activa) break;
      if (r.colgar) {
        await decir(r.decir);
        fin = r.fallo ? 'error' : 'goodbye';
        break;
      }
      await decir(r.decir);
    }

    if (activa && turnos >= TURNOS_MAX && fin === 'max_turns') await decir(FRASES.tope);
    if (!activa && fin !== 'silence' && fin !== 'goodbye') fin = 'hangup';
  } catch (e) {
    log('TERCERO: fallo en la conversación (' + e.message + ')');
    fin = 'error';
  } finally {
    dialog.off('destroy', alColgar);
    desarmar();
    if (session) session.setCaptureEnabled(false);
    if (o.audioForkServer.cancelExpectation) o.audioForkServer.cancelExpectation(callId);
    if (fork) {
      try {
        await Promise.race([endpoint.forkAudioStop(),
                            new Promise(function (r) { setTimeout(r, CIERRE_MS); })]);
      } catch (e) { /* ya parado */ }
    }
  }
  return { endReason: fin };
}

module.exports = { runConversacionTercero, preguntarAlBackend, esperarSaludo, esperarLocucion,
                   esperarSilencio, prepararGuion, conModeloRapido, FRASES };
