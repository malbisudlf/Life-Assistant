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
 *   - **Lo que se puede, por adelantado.** El backend (Claude) prepara un guion con las
 *     respuestas probables y aquí se genera su voz (`prepararGuion`): si la respuesta es
 *     del guion, suena al instante. Y se transcribe con el modelo pequeño del oído
 *     (`conModeloRapido`).
 *   - **Preparado antes de marcar (parche 43).** La presentación entera y el guion con su
 *     voz, antes de que suene el teléfono del otro (`prepararLlamada`, en
 *     outbound-routes.js): al descolgar no queda nada por generar.
 *   - Nada de lectura, confirmaciones ni escucha pasiva: aquí no hay nada de eso que hacer.
 *   - **Sin barge-in (parche 35).** Jarvis dice su frase entera, con el oído cerrado: lo
 *     que el otro diga encima no le corta ni cuenta como turno. Mikel lo quiso así
 *     (2026-11-05). En sus propias llamadas con Jarvis se le sigue pudiendo cortar.
 */

const { armarAnticipo, transcribirFrase } = require('./anticipo');

// El saludo: tope total, lo que se espera a que empiece a hablar y el silencio que lo da
// por dicho (un «¿Sí?» no necesita los 1,5 s de `endSilenceMs`).
// Parche 43: 1,2 s y 350 ms (eran 2 s y 450). Mikel oía unos 3 s de silencio al descolgar
// (2026-11-09). En la llamada del 2026-11-08 a las 20:25 nadie dijo nada: Jarvis esperó
// los 2 s enteros y después el otro colgó. Quien coge dice su «¿Sí?» en menos de un
// segundo; si a los 1,2 s no ha empezado, no lo va a decir.
const ESPERA_SALUDO_MS = 3000;
const SALUDO_NADIE_MS = 1200;
const SALUDO_SILENCIO_MS = 350;
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

// Parche 39: la consulta a Mikel sin colgar (dos llamadas a la vez). Cada cuánto se pregunta
// al backend si ya ha contestado, cada cuánto se le dice algo al otro para que no cuelgue, y
// el tope: el backend corta a los TERCEROS_CONSULTA_SEG (90) y contesta él; esto es la red
// por si el backend no contesta nunca.
const CONSULTA_SONDEO_MS = 2000;
const CONSULTA_RECUERDO_MS = 30000;
const CONSULTA_TOPE_MS = 120000;
const MUSICA_URL = 'http://127.0.0.1:' + (process.env.HTTP_PORT || 3000) + '/static/hold-music.wav';

const FRASES = {
  sigo: 'Sigo aquí, un momento, que me está contestando.',
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
 * Parche 43: cuánto ha HABLADO en el saludo, no cuánto audio hay. El audio lleva delante
 * el pre-roll y el silencio de antes de hablar: un «¿Quién?» de 1,4 s de voz llegó con
 * 3,3 s de audio (2026-11-08), pasó por locución y Jarvis esperó a la transcripción
 * (~0,4 s más) antes de presentarse.
 */
function habladoMs(saludo) {
  return saludo && typeof saludo.speechMs === 'number' ? saludo.speechMs : duracionMs(saludo && saludo.audio);
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
      if (!session._utteranceChunks || !session._utteranceChunks.length) return null;
      const u = { audio: Buffer.concat(session._utteranceChunks) };
      if (typeof session._speechBytes === 'number') u.speechMs = duracionMs({ length: session._speechBytes });
      return u;
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
 * URL). Pregunta hasta que esté (`listo`) o pasen `esperaMs` (GUION_ESPERA_MS). Nunca
 * lanza. Vuelve con true si ya no hay nada más que esperar del backend, false si se cansó.
 */
async function prepararGuion(o, cache, voiceId, log, esperaMs) {
  const fetchFn = o.fetch || fetch;
  const url = backendUrl() + '/telefono/tercero/' + encodeURIComponent(o.tercero) + '/guion';
  const hasta = Date.now() + (esperaMs || GUION_ESPERA_MS);
  while (Date.now() < hasta) {
    try {
      const r = await fetchFn(url, { headers: { 'X-Auth-Token': process.env.TELEFONO_TERCEROS_TOKEN || '' },
                                     signal: AbortSignal.timeout(3000) });
      if (r.status === 404) return true;
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
          return true;
        }
      }
    } catch (e) { /* el backend tarda o no está: se vuelve a preguntar */ }
    await new Promise(function (r) { setTimeout(r, o.guionSondeoMs || GUION_SONDEO_MS); });
  }
  return false;
}

// Parche 43: lo más que se espera, antes de marcar, a tener la presentación y el guion con
// su voz; y cada cuánto se pregunta entonces por el guion (aquí cada décima cuenta).
const PREPARAR_TOPE_MS = 12000;
const PREPARAR_SONDEO_MS = 250;

/**
 * Parche 43: Jarvis se prepara ANTES de marcar, no mientras suena. Mikel lo pidió así
 * (2026-11-09): «si no está preparado para hablar, que primero se prepare y luego llame».
 * Hasta ahora la presentación se pedía a la voz al marcar (casi siempre a tiempo, pero sin
 * garantía) y el guion se pedía al descolgar, con seis voces generándose a la vez justo
 * cuando había que hablar. Ahora se marca cuando:
 *   - la presentación ha llegado ENTERA de la voz (`esperarAcabada`), y
 *   - el backend tiene el guion (su Claude ya está abierto y pensado) y la voz de cada
 *     frase ha llegado entera.
 * Con PREPARAR_TOPE_MS de tope: si algo no llega, se marca igual con lo que haya (y el
 * guion se sigue pidiendo durante la llamada, como antes). Nunca lanza.
 * @returns {Promise<{aperturaUrl: Promise<string|null>, guion: Map, guionListo: boolean}>}
 */
async function prepararLlamada(o) {
  const log = o.log || function () {};
  const inicio = Date.now();
  const voiceId = o.voiceId || null;
  const tts = o.ttsService;
  const tope = o.prepararTopeMs || PREPARAR_TOPE_MS;
  const acabada = function (url) {
    if (!url) return Promise.resolve(false);
    return typeof tts.esperarAcabada === 'function' ? tts.esperarAcabada(url, tope) : Promise.resolve(true);
  };
  const aperturaUrl = Promise.resolve()
    .then(function () { return tts.generateSpeech(o.apertura, voiceId); })
    .catch(function (e) { log('TERCERO: presentación anticipada fallida (' + e.message + ')'); return null; });
  const guion = new Map();
  let guionListo = false;
  let aperturaLista = false;
  const trabajo = Promise.all([
    aperturaUrl.then(acabada).then(function (ok) { aperturaLista = ok; }),
    prepararGuion(Object.assign({}, o, { guionSondeoMs: o.guionSondeoMs || PREPARAR_SONDEO_MS }), guion, voiceId, log, tope)
      .then(function (listo) {
        guionListo = listo;
        return Promise.all(Array.from(guion.values()).map(function (p) { return p.then(acabada); }));
      })
  ]).catch(function () {});
  let reloj = null;
  const aTiempo = await Promise.race([
    trabajo.then(function () { return true; }),
    new Promise(function (r) { reloj = setTimeout(function () { r(false); }, tope); })
  ]);
  clearTimeout(reloj);
  log('TERCERO: preparado en ' + (Date.now() - inicio) + ' ms (presentación ' +
      (aperturaLista ? 'entera' : 'SIN terminar') + ', guion de ' + guion.size + ' frases' +
      (guionListo ? '' : ', SIN terminar') + ')' + (aTiempo ? '' : '; tope, marco igual'));
  return { aperturaUrl: aperturaUrl, guion: guion, guionListo: guionListo };
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
    return { decir: decir, colgar: Boolean(d.colgar), esperar: Boolean(d.esperar) && !d.colgar };
  } catch (e) {
    if (opciones && opciones.log) opciones.log('TERCERO: el backend no contestó (' + e.message + ')');
    return { decir: FRASES.fallo, colgar: true, fallo: true };
  } finally {
    clearTimeout(vigia);
  }
}

/**
 * Parche 39: mientras Mikel contesta en el móvil, el otro oye música y, cada
 * CONSULTA_RECUERDO_MS, «sigo aquí». Pregunta al backend cada CONSULTA_SONDEO_MS; vuelve
 * con {decir, colgar} cuando hay respuesta (o cuando el backend da la espera por perdida).
 * Si el backend falla tres veces seguidas o se pasa el tope, la despedida de fallo.
 */
async function esperarConsulta(tercero, o) {
  const fetchFn = o.fetch || fetch;
  const dormirFn = o.dormir || dormir;
  const ahora = o.ahora || Date.now;
  const inicio = ahora();
  let recuerdo = inicio;
  let fallos = 0;
  if (o.musica) o.musica(true);
  try {
    while (ahora() - inicio < (o.topeMs || CONSULTA_TOPE_MS)) {
      if (o.sigueActiva && !o.sigueActiva()) return { decir: '', colgar: true, colgada: true };
      await dormirFn(o.sondeoMs || CONSULTA_SONDEO_MS);
      try {
        const r = await fetchFn(backendUrl() + '/telefono/tercero/' + encodeURIComponent(tercero) + '/consulta', {
          headers: { 'X-Auth-Token': process.env.TELEFONO_TERCEROS_TOKEN || '' },
          signal: AbortSignal.timeout(5000)
        });
        if (!r.ok) throw new Error('backend ' + r.status);
        const d = await r.json();
        fallos = 0;
        if (d && d.listo) {
          const decir = String(d.decir || '').trim();
          return decir ? { decir: decir, colgar: Boolean(d.colgar) } : { decir: FRASES.fallo, colgar: true, fallo: true };
        }
      } catch (e) {
        if (o.log) o.log('TERCERO: la consulta no contestó (' + e.message + ')');
        if (++fallos >= 3) return { decir: FRASES.fallo, colgar: true, fallo: true };
      }
      if (ahora() - recuerdo >= (o.recuerdoMs || CONSULTA_RECUERDO_MS) && o.recordar) {
        recuerdo = ahora();
        if (o.musica) o.musica(false);
        await o.recordar();
        if (o.musica) o.musica(true);
      }
    }
    return { decir: FRASES.fallo, colgar: true, fallo: true };
  } finally {
    if (o.musica) o.musica(false);
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
  // Parche 43: el guion ya viene preparado de antes de marcar (`prepararLlamada`); si no
  // llegó a tiempo, se sigue pidiendo ahora, como antes.
  const guion = o.guion instanceof Map ? o.guion : new Map();
  if (!o.guionListo) prepararGuion(o, guion, voiceId, log);

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
      if (saludo.larga || habladoMs(saludo) >= SALUDO_LARGO_MS) {
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

      let r = await preguntarAlBackend(o.tercero, dicho, { log: log, fetch: o.fetch });
      if (!activa) break;
      if (r.esperar) {
        // Parche 39: «Un segundo, que se lo consulto a Mikel» y a esperar su botón.
        await decir(r.decir);
        if (!activa) break;
        log('TERCERO: consultando a Mikel; el otro espera');
        let sonando = false;
        r = await esperarConsulta(o.tercero, {
          fetch: o.fetch, log: log, dormir: o.dormir,
          sigueActiva: function () { return activa; },
          recordar: function () { return decir(FRASES.sigo); },
          musica: function (encender) {
            if (encender && !sonando && activa) {
              sonando = true;
              Promise.resolve().then(function () { return endpoint.play(o.musicaUrl || MUSICA_URL); }).catch(function () {});
            } else if (!encender && sonando) {
              sonando = false;
              Promise.resolve().then(function () { return endpoint.api('uuid_break', endpoint.uuid); }).catch(function () {});
            }
          }
        });
        if (!activa || r.colgada) break;
      }
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

module.exports = { runConversacionTercero, preguntarAlBackend, esperarConsulta, esperarSaludo, esperarLocucion,
                   esperarSilencio, prepararGuion, prepararLlamada, conModeloRapido, FRASES };
