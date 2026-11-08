/**
 * Parches 15 y 16: Claude piensa mientras suena la frase de espera, y se le puede
 * interrumpir mientras contesta (barge-in).
 *
 * Igual que parche12.test.js: FreeSWITCH, la voz, Whisper, Claude y el oído son
 * dobles, y lo que corre es el código de verdad de lib/ (sip-handler para las
 * entrantes, conversation-loop para las salientes, audio-fork para el detector).
 * Se lanza con `node --test test/parche15y16.test.js`, dentro de la imagen recién
 * construida y sin red: ver telefono/PARCHES.md, «Los parches 15 y 16».
 */
'use strict';

const test = require('node:test');
const assert = require('node:assert');
const Module = require('node:module');
const { EventEmitter } = require('node:events');

// `ws` solo hace falta para el servidor; la sesión recibe el socket hecho.
const requireDeVerdad = Module.prototype.require;
Module.prototype.require = function (id) {
  if (id === 'ws') return { Server: function () {} };
  return requireDeVerdad.apply(this, arguments);
};
const registro = [];
for (const nivel of ['log', 'warn', 'error']) {
  console[nivel] = function () { registro.push(Array.from(arguments).join(' ')); };
}

const { pensar, decirInterrumpible, AVISO_INTERRUPCION } = require('../lib/turno-rapido');
const { AudioForkSession } = require('../lib/audio-fork');
const { handleInvite } = require('../lib/sip-handler');
const { runConversationLoop } = require('../lib/conversation-loop');

const tick = function () { return new Promise(function (r) { setImmediate(r); }); };

// ── Dobles ───────────────────────────────────────────────────────────────────
const tts = { generateSpeech: async function (texto) { return 'tts:' + texto; } };

/**
 * Un endpoint de FreeSWITCH que apunta lo que suena. `bloquea(url)` decide qué
 * reproducciones se quedan sonando hasta un uuid_break (la música, o una respuesta
 * que se va a interrumpir); el resto acaban solas.
 */
function endpointFalso(bloquea) {
  const ep = new EventEmitter();
  ep.uuid = 'ep-1';
  ep.hecho = [];
  ep._sonando = [];
  ep.play = function (url) {
    ep.hecho.push('play ' + url);
    if (bloquea && bloquea(url)) {
      return new Promise(function (r) { ep._sonando.push(r); });
    }
    return Promise.resolve();
  };
  ep.api = async function (cmd) {
    ep.hecho.push('api ' + cmd);
    if (cmd === 'uuid_break') { const s = ep._sonando; ep._sonando = []; s.forEach(function (r) { r(); }); }
  };
  ep.forkAudioStart = async function () {};
  ep.forkAudioStop = async function () {};
  ep.destroy = async function () {};
  return ep;
}

/** Claude: apunta lo que se le pregunta y contesta cuando se le dice (o al momento). */
function claudeFalso(opciones) {
  const c = { preguntas: [], pendientes: [] };
  c.query = function (texto) {
    c.preguntas.push(texto);
    if (opciones && opciones.aMano) {
      return new Promise(function (r) { c.pendientes.push(r); });
    }
    return Promise.resolve('🗣️ VOICE_RESPONSE: respuesta ' + c.preguntas.length);
  };
  c.contestar = function () { c.pendientes.shift()('🗣️ VOICE_RESPONSE: lista'); };
  c.endSession = async function () {};
  return c;
}

/**
 * El oído de una conversación: lo que dice la persona en cada turno, y en qué
 * respuestas de Jarvis se pone a hablar encima (emite 'barge' al armarse).
 */
function sesionFalsa(frases, cortaEnRespuesta) {
  const s = new EventEmitter();
  s.capturas = [];
  let i = 0;
  let respuestas = 0;
  s.setCaptureEnabled = function (v) { s.capturas.push(v); };
  s.forceFinalize = function () {};
  s.armarBargeIn = function () {
    respuestas++;
    s.capturas.push('armado');
    if (cortaEnRespuesta.indexOf(respuestas) >= 0) setImmediate(function () { s.emit('barge'); });
  };
  s.waitForUtterance = async function () {
    const f = frases[i++];
    if (f == null) throw new Error('Timed out waiting for utterance');
    return { audio: Buffer.from(f), reason: 'end_silence' };
  };
  return s;
}

const whisper = { transcribe: async function (audio) { return audio.toString(); } };

// ── Parche 15: pensar() ──────────────────────────────────────────────────────
// Desde el parche 34 la frase de espera no suena hasta ESPERA_FRASE_MS (2,5 s). Estos tres
// casos son de lo que pasa una vez suena, así que se les quita esa espera.
const pasan = function (ms) { return new Promise(function (r) { setTimeout(r, ms); }); };
function esperaDeFrase(t, ms) {
  process.env.ESPERA_FRASE_MS = String(ms);
  t.after(function () { delete process.env.ESPERA_FRASE_MS; });
}

test('15: Claude ya está preguntado antes de que termine la frase de espera', async function (t) {
  esperaDeFrase(t, 0);
  const ep = endpointFalso(function (url) { return url.indexOf('tts:') === 0 || url === 'musica'; });
  const claude = claudeFalso({ aMano: true });
  const hecho = pensar({ consultar: function () { return claude.query('hola'); }, endpoint: ep,
    ttsService: tts, frase: 'Un momento...', voiceId: 'v', musicaUrl: 'musica' });
  await pasan(20);
  assert.deepStrictEqual(ep.hecho, ['play tts:Un momento...']);
  assert.deepStrictEqual(claude.preguntas, ['hola'], 'antes del parche se preguntaba al acabar la frase');
  // Claude contesta mientras suena la frase: se corta y no suena música.
  claude.contestar();
  await tick();
  ep._sonando.forEach(function (r) { r(); });
  assert.strictEqual(await hecho, '🗣️ VOICE_RESPONSE: lista');
  assert.ok(ep.hecho.indexOf('play musica') < 0, 'sin música si Claude ya ha contestado');
});

test('15: si Claude tarda más que la frase, suena la música y se para al contestar', async function (t) {
  esperaDeFrase(t, 0);
  const ep = endpointFalso(function (url) { return url === 'musica'; });
  const claude = claudeFalso({ aMano: true });
  const hecho = pensar({ consultar: function () { return claude.query('hola'); }, endpoint: ep,
    ttsService: tts, frase: 'Un momento...', voiceId: 'v', musicaUrl: 'musica' });
  await pasan(20);
  assert.deepStrictEqual(ep.hecho, ['play tts:Un momento...', 'play musica']);
  claude.contestar();
  await hecho;
  assert.strictEqual(ep.hecho[ep.hecho.length - 1], 'api uuid_break');
});

test('15: un fallo de Claude se sigue lanzando, y la música se para igual', async function (t) {
  esperaDeFrase(t, 0);
  const ep = endpointFalso(function (url) { return url === 'musica'; });
  let rechazar;
  const hecho = pensar({ consultar: function () { return new Promise(function (_, r) { rechazar = r; }); },
    endpoint: ep, ttsService: tts, frase: 'Un momento...', voiceId: 'v', musicaUrl: 'musica' });
  await pasan(20);
  rechazar(new Error('Claude API returned failure'));
  await assert.rejects(hecho, /Claude API returned failure/);
  assert.strictEqual(ep.hecho[ep.hecho.length - 1], 'api uuid_break');
});

test('34: si Claude contesta antes de ESPERA_FRASE_MS, ni frase ni música', async function (t) {
  esperaDeFrase(t, 1000);
  const ep = endpointFalso();
  const claude = claudeFalso({ aMano: true });
  const hecho = pensar({ consultar: function () { return claude.query('hola'); }, endpoint: ep,
    ttsService: tts, frase: 'Un momento...', voiceId: 'v', musicaUrl: 'musica' });
  await tick();
  claude.contestar();
  assert.strictEqual(await hecho, '🗣️ VOICE_RESPONSE: lista');
  assert.deepStrictEqual(ep.hecho, []);
});

test('34: la respuesta se sintetiza en cuanto Claude la tiene', async function (t) {
  esperaDeFrase(t, 1000);
  const anticipadas = [];
  const ttsConAnticipo = Object.assign({ anticipar: function (texto, voz) { anticipadas.push([texto, voz]); } }, tts);
  const claude = claudeFalso({ aMano: true });
  const hecho = pensar({ consultar: function () { return claude.query('hola'); }, endpoint: endpointFalso(),
    ttsService: ttsConAnticipo, frase: 'Un momento...', voiceId: 'v', musicaUrl: 'musica',
    extraer: function (r) { return r.replace('🗣️ VOICE_RESPONSE: ', ''); } });
  await tick();
  claude.contestar();
  await hecho;
  assert.deepStrictEqual(anticipadas, [['lista', 'v']]);
});

test('34: si la frase de espera falla, se sigue esperando a Claude', async function (t) {
  esperaDeFrase(t, 0);
  const ep = endpointFalso(function (url) { return url === 'musica'; });
  const claude = claudeFalso({ aMano: true });
  const ttsRoto = { generateSpeech: async function () { throw new Error('File Not Found'); } };
  const hecho = pensar({ consultar: function () { return claude.query('hola'); }, endpoint: ep,
    ttsService: ttsRoto, frase: 'Un momento...', voiceId: 'v', musicaUrl: 'musica' });
  await pasan(20);
  assert.deepStrictEqual(ep.hecho, ['play musica'], 'un adorno no puede tumbar la llamada');
  claude.contestar();
  assert.strictEqual(await hecho, '🗣️ VOICE_RESPONSE: lista');
});

// ── Parche 16: decirInterrumpible() ──────────────────────────────────────────
test('16: si hablas encima, Jarvis se calla y el oído sigue abierto', async function () {
  const ep = endpointFalso(function () { return true; });
  const s = sesionFalsa([], [1]);
  const cortado = await decirInterrumpible(ep, s, 'tts:respuesta');
  assert.strictEqual(cortado, true);
  assert.deepStrictEqual(ep.hecho, ['play tts:respuesta', 'api uuid_break']);
  assert.deepStrictEqual(s.capturas, ['armado'], 'no se cierra el oído: lo que dices es el turno siguiente');
  assert.strictEqual(s.listenerCount('barge'), 0);
});

test('16: si no hablas, la respuesta suena entera y el oído se cierra como antes', async function () {
  const ep = endpointFalso();
  const s = sesionFalsa([], []);
  assert.strictEqual(await decirInterrumpible(ep, s, 'tts:respuesta'), false);
  assert.deepStrictEqual(ep.hecho, ['play tts:respuesta']);
  assert.deepStrictEqual(s.capturas, ['armado', false]);
});

test('16: con BARGE_IN=0 no se arma nada', async function () {
  process.env.BARGE_IN = '0';
  try {
    const ep = endpointFalso();
    const s = sesionFalsa([], [1]);
    assert.strictEqual(await decirInterrumpible(ep, s, 'tts:respuesta'), false);
    assert.deepStrictEqual(s.capturas, []);
  } finally {
    delete process.env.BARGE_IN;
  }
});

// ── Parche 16: el detector de verdad ─────────────────────────────────────────
// 20 ms de audio a 16 kHz: 640 bytes. Voz = ±15000; silencio = ceros.
function trozo(voz) {
  const b = Buffer.alloc(640);
  if (voz) for (let i = 0; i < 320; i++) b.writeInt16LE(i % 2 ? 15000 : -15000, i * 2);
  return b;
}
function detector() {
  const ws = new EventEmitter();
  const s = new AudioForkSession({ ws: ws, callUuid: 'c1' });
  s.oir = function (vozMs, silencioMs) {
    for (let t = 0; t < vozMs; t += 20) ws.emit('message', trozo(true));
    for (let t = 0; t < (silencioMs || 0); t += 20) ws.emit('message', trozo(false));
  };
  // El turno anterior escuchando en silencio: fija el orden de bytes y el suelo de
  // ruido, como en una llamada (sin esto el suelo se plantaría en la propia voz).
  s.setCaptureEnabled(true);
  s.oir(0, 1000);
  s.setCaptureEnabled(false);
  return s;
}

test('16: el detector avisa a los 500 ms de voz con Jarvis hablando, y solo una vez', function () {
  const s = detector();
  let avisos = 0;
  s.on('barge', function () { avisos++; });
  s.armarBargeIn();
  s.oir(0, 600);       // escuchas a Jarvis callado
  assert.strictEqual(avisos, 0);
  s.oir(300);
  assert.strictEqual(avisos, 0, 'un «mm» o una tos no cortan a Jarvis');
  s.oir(400);
  assert.strictEqual(avisos, 1);
  s.oir(1000);
  assert.strictEqual(avisos, 1);
});

test('16: sin armar, hablar no avisa (el turno normal no cambia)', function () {
  const s = detector();
  let avisos = 0;
  s.on('barge', function () { avisos++; });
  s.setCaptureEnabled(true);
  s.oir(1000);
  assert.strictEqual(avisos, 0);
});

test('16: la frase que acaba antes de volver a escuchar no se pierde', async function () {
  const s = detector();
  s.armarBargeIn();
  s.oir(800, 1600);    // hablas y te callas mientras Jarvis aún se está callando
  s.setCaptureEnabled(true);
  const u = await s.waitForUtterance({ timeoutMs: 50 });
  assert.ok(u.speechMs >= 700, 'es la frase entera, con su principio');
  assert.strictEqual(u.reason, 'end_silence');
});

test('16: cerrar el oído tira la frase guardada y desarma', async function () {
  const s = detector();
  let avisos = 0;
  s.on('barge', function () { avisos++; });
  s.armarBargeIn();
  s.oir(400, 1600);    // 400 ms: se acepta como frase, pero no llega a cortar
  assert.strictEqual(avisos, 0);
  s.setCaptureEnabled(false);
  s.setCaptureEnabled(true);
  s.oir(800);
  assert.strictEqual(avisos, 0, 'desarmado');
  await assert.rejects(s.waitForUtterance({ timeoutMs: 30 }), /Timed out/);
});

// ── Los dos bucles, enteros ──────────────────────────────────────────────────
function opcionesComunes(sesion, claude) {
  return {
    ttsService: tts, whisperClient: whisper, claudeBridge: claude, wsPort: 3001,
    audioForkServer: { expectSession: async function () { return sesion; }, cancelExpectation: function () {}, emit: function () {} }
  };
}
function beeps(ep) {
  return ep.hecho.filter(function (h) { return h.indexOf('ready-beep') >= 0; }).length;
}

test('16, entrante: interrumpes la 1.ª respuesta → sin pitido, y Claude sabe que le cortaste', async function () {
  const ep = endpointFalso(function (url) { return url === 'tts:respuesta 1' || url.indexOf('hold-music') >= 0; });
  const sesion = sesionFalsa(['¿qué tengo hoy?', 'para, ¿y mañana?', 'adiós'], [1]);
  const claude = claudeFalso();
  const dialogo = new EventEmitter();
  dialogo.destroy = function () {};
  const opciones = opcionesComunes(sesion, claude);
  opciones.mediaServer = { connectCaller: async function () { return { endpoint: ep, dialog: dialogo }; } };
  const req = { get: function (h) { return h === 'To' ? '<sip:10001@x>' : '<sip:10000@x>'; }, body: 'v=0' };
  await handleInvite(req, { send: function () {} }, opciones);

  assert.deepStrictEqual(claude.preguntas, ['¿qué tengo hoy?', AVISO_INTERRUPCION + 'para, ¿y mañana?']);
  assert.ok(ep.hecho.indexOf('api uuid_break') >= 0);
  // Pitidos: turno 1 y turno 3. El 2 empezó hablando encima de Jarvis.
  assert.strictEqual(beeps(ep), 2);
  assert.ok(ep.hecho.indexOf('play tts:Hasta luego. Llámame cuando quieras.') >= 0);
});

test('16, saliente: igual en conversation-loop', async function () {
  const ep = endpointFalso(function (url) { return url === 'tts:respuesta 1' || url.indexOf('hold-music') >= 0; });
  const sesion = sesionFalsa(['dime', 'espera, otra cosa', 'adiós'], [1]);
  const claude = claudeFalso();
  const dialogo = new EventEmitter();
  const r = await runConversationLoop(ep, dialogo, 'c-sal', Object.assign(opcionesComunes(sesion, claude), { skipGreeting: true }));
  assert.strictEqual(r.endReason, 'goodbye');
  assert.deepStrictEqual(claude.preguntas, ['dime', AVISO_INTERRUPCION + 'espera, otra cosa']);
  assert.strictEqual(beeps(ep), 2);
});

test('16, entrante sin interrumpir: todo como antes (pitido en cada turno, pregunta tal cual)', async function () {
  const ep = endpointFalso(function (url) { return url.indexOf('hold-music') >= 0; });
  const sesion = sesionFalsa(['hola', 'adiós'], []);
  const claude = claudeFalso();
  const dialogo = new EventEmitter();
  dialogo.destroy = function () {};
  const opciones = opcionesComunes(sesion, claude);
  opciones.mediaServer = { connectCaller: async function () { return { endpoint: ep, dialog: dialogo }; } };
  const req = { get: function () { return '<sip:10001@x>'; }, body: 'v=0' };
  await handleInvite(req, { send: function () {} }, opciones);
  assert.deepStrictEqual(claude.preguntas, ['hola']);
  assert.strictEqual(beeps(ep), 2);
  assert.ok(ep.hecho.indexOf('api uuid_break') < 0 || ep.hecho.indexOf('play tts:respuesta 1') > ep.hecho.lastIndexOf('api uuid_break'),
    'el único uuid_break posible es el de la música, antes de la respuesta');
});
