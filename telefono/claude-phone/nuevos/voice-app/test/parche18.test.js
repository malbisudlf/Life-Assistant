/**
 * Parche 18: «📖 LEER: briefing» en la respuesta de Claude → la llamada lee el
 * briefing entero, trozo a trozo, sin pasar por Claude ni por el tope de 40 palabras.
 *
 * Mismos dobles que parche15y16.test.js; el backend es un fetch falso. Se lanza con
 * `node --test test/parche18.test.js`, dentro de la imagen y sin red.
 */
'use strict';

const test = require('node:test');
const assert = require('node:assert');
const Module = require('node:module');
const { EventEmitter } = require('node:events');

const requireDeVerdad = Module.prototype.require;
Module.prototype.require = function (id) {
  if (id === 'ws') return { Server: function () {} };
  return requireDeVerdad.apply(this, arguments);
};
for (const nivel of ['log', 'warn', 'error']) console[nivel] = function () {};

const { leerSiLoPide, pedidoDeLectura } = require('../lib/lectura');
const { handleInvite } = require('../lib/sip-handler');
const { runConversationLoop } = require('../lib/conversation-loop');

// ── Dobles ───────────────────────────────────────────────────────────────────
function ttsFalso() {
  const t = { pedidos: [] };
  t.generateSpeech = async function (texto) { t.pedidos.push(texto); return 'tts:' + texto; };
  return t;
}

function endpointFalso(bloquea) {
  const ep = new EventEmitter();
  ep.uuid = 'ep-1';
  ep.hecho = [];
  ep._sonando = [];
  ep.play = function (url) {
    ep.hecho.push('play ' + url);
    if (bloquea && bloquea(url)) return new Promise(function (r) { ep._sonando.push(r); });
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

/** El oído: corta en la reproducción interrumpible número N (cuenta desde 1). */
function sesionFalsa(frases, cortaEn) {
  const s = new EventEmitter();
  s.capturas = [];
  let i = 0;
  let armados = 0;
  s.setCaptureEnabled = function (v) { s.capturas.push(v); };
  s.forceFinalize = function () {};
  s.armarBargeIn = function () {
    armados++;
    if ((cortaEn || []).indexOf(armados) >= 0) setImmediate(function () { s.emit('barge'); });
  };
  s.waitForUtterance = async function () {
    const f = frases[i++];
    if (f == null) throw new Error('Timed out waiting for utterance');
    return { audio: Buffer.from(f), reason: 'end_silence' };
  };
  return s;
}

const BRIEFING = { ok: true, fecha: '2026-10-15', secciones: [
  { n: 1, titulo: 'Tecnología', trozos: ['Tecnología. Uno.', 'Dos.'] },
  { n: 2, titulo: 'Inteligencia Artificial', trozos: ['Inteligencia Artificial. Tres.'] }
] };

function fetchFalso(respuesta, apunte) {
  return async function (url, opciones) {
    if (apunte) apunte.push({ url: url, opciones: opciones });
    if (respuesta instanceof Error) throw respuesta;
    return { ok: respuesta.status ? respuesta.status < 300 : true, status: respuesta.status || 200,
             json: async function () { return respuesta; } };
  };
}

function interrumpibles(ep) {
  return ep.hecho.filter(function (h) { return h.indexOf('play tts:') === 0; });
}

// ── El pedido ────────────────────────────────────────────────────────────────
test('18: la marca se lee con y sin parámetros, y sin ella no hay pedido', function () {
  assert.deepStrictEqual(pedidoDeLectura('🗣️ VOICE_RESPONSE: Te lo leo.\n📖 LEER: briefing'),
    { que: 'briefing', fecha: '', desde: 1, hasta: 0 });
  assert.deepStrictEqual(pedidoDeLectura('📖 LEER: briefing desde=2 hasta=3 fecha=2026-10-14'),
    { que: 'briefing', fecha: '2026-10-14', desde: 2, hasta: 3 });
  assert.strictEqual(pedidoDeLectura('🗣️ VOICE_RESPONSE: hola'), null);
  assert.strictEqual(pedidoDeLectura('📖 LEER: otra cosa'), null);
});

// ── La lectura ───────────────────────────────────────────────────────────────
test('18: lo lee entero, en orden, y prepara cada trozo antes de que acabe el anterior', async function () {
  const ep = endpointFalso();
  const tts = ttsFalso();
  const pedidos = [];
  const r = await leerSiLoPide('📖 LEER: briefing desde=1', {
    endpoint: ep, session: sesionFalsa([], []), ttsService: tts, voiceId: 'v',
    fetchImpl: fetchFalso(BRIEFING, pedidos) });
  assert.deepStrictEqual(interrumpibles(ep), ['play tts:Tecnología. Uno.', 'play tts:Dos.',
    'play tts:Inteligencia Artificial. Tres.', 'play tts:Hasta aquí el briefing.']);
  assert.strictEqual(r.interrumpio, false);
  assert.match(r.aviso, /leído el briefing entero/);
  // Desde el parche 20 todo se pide a /telefono/lectura, el briefing incluido.
  assert.match(pedidos[0].url, /\/telefono\/lectura\?que=briefing&desde=1&hasta=0$/);
  assert.match(pedidos[0].opciones.headers.Authorization, /^Bearer /);
});

test('18: si le cortas, se calla ahí y a Claude le llega en qué sección iba', async function () {
  const ep = endpointFalso(function (url) { return url === 'tts:Inteligencia Artificial. Tres.'; });
  const r = await leerSiLoPide('📖 LEER: briefing', {
    endpoint: ep, session: sesionFalsa([], [3]), ttsService: ttsFalso(), voiceId: 'v',
    fetchImpl: fetchFalso(BRIEFING) });
  assert.strictEqual(r.interrumpio, true);
  assert.match(r.aviso, /sección 2 de 2 \(«Inteligencia Artificial»\)/);
  // Desde el parche 24, seguir es `seguir`: retoma el trozo exacto, no el principio.
  assert.match(r.aviso, /📖 LEER: briefing seguir/);
  assert.ok(ep.hecho.indexOf('play tts:Hasta aquí el briefing.') < 0);
});

test('18: si el backend no puede, lo dice en voz alta y no se queda mudo', async function () {
  const ep = endpointFalso();
  const r = await leerSiLoPide('📖 LEER: briefing', {
    endpoint: ep, session: sesionFalsa([], []), ttsService: ttsFalso(), voiceId: 'v',
    fetchImpl: fetchFalso({ ok: false, frase: 'Hoy no hay briefing enviado todavía.' }) });
  assert.deepStrictEqual(interrumpibles(ep), ['play tts:Hoy no hay briefing enviado todavía.']);
  assert.match(r.aviso, /no se pudo hacer/);
  const ep2 = endpointFalso();
  await leerSiLoPide('📖 LEER: briefing', {
    endpoint: ep2, session: sesionFalsa([], []), ttsService: ttsFalso(), voiceId: 'v',
    fetchImpl: fetchFalso(new Error('ECONNREFUSED')) });
  assert.deepStrictEqual(interrumpibles(ep2), ['play tts:No he podido traer el briefing para leértelo.']);
});

test('18: una respuesta sin marca no toca nada', async function () {
  const ep = endpointFalso();
  const r = await leerSiLoPide('🗣️ VOICE_RESPONSE: hola', {
    endpoint: ep, session: sesionFalsa([], []), ttsService: ttsFalso(), voiceId: 'v',
    fetchImpl: function () { throw new Error('no debería preguntar'); } });
  assert.deepStrictEqual(r, { interrumpio: false, aviso: '' });
  assert.deepStrictEqual(ep.hecho, []);
});

// ── Los dos bucles ───────────────────────────────────────────────────────────
function claudeQueLee() {
  const c = { preguntas: [] };
  c.query = async function (texto) {
    c.preguntas.push(texto);
    return c.preguntas.length === 1
      ? '🗣️ VOICE_RESPONSE: Te lo leo entero.\n📖 LEER: briefing\n🎯 COMPLETED: lectura'
      : '🗣️ VOICE_RESPONSE: vale';
  };
  c.endSession = async function () {};
  return c;
}
function opcionesComunes(sesion, claude) {
  return {
    ttsService: ttsFalso(), whisperClient: { transcribe: async function (a) { return a.toString(); } },
    claudeBridge: claude, wsPort: 3001,
    audioForkServer: { expectSession: async function () { return sesion; },
                       cancelExpectation: function () {}, emit: function () {} }
  };
}

test('18, saliente: «léeme el briefing» lo lee entero y el turno siguiente sabe que acabó', async function () {
  const fetchAntes = global.fetch;
  global.fetch = fetchFalso(BRIEFING);
  try {
    const ep = endpointFalso(function (url) { return url.indexOf('hold-music') >= 0; });
    const claude = claudeQueLee();
    const sesion = sesionFalsa(['léeme el briefing', 'gracias', 'adiós'], []);
    const r = await runConversationLoop(ep, new EventEmitter(), 'c-sal',
      Object.assign(opcionesComunes(sesion, claude), { skipGreeting: true }));
    assert.strictEqual(r.endReason, 'goodbye');
    const leido = interrumpibles(ep);
    const desde = leido.indexOf('play tts:Te lo leo entero.');
    assert.deepStrictEqual(leido.slice(desde, desde + 5), [
      'play tts:Te lo leo entero.', 'play tts:Tecnología. Uno.', 'play tts:Dos.',
      'play tts:Inteligencia Artificial. Tres.', 'play tts:Hasta aquí el briefing.']);
    assert.match(claude.preguntas[1], /^\[Ya le has leído el briefing entero.*\] gracias$/);
  } finally {
    global.fetch = fetchAntes;
  }
});

test('18, entrante: le cortas a media lectura y lo que dices es la pregunta siguiente', async function () {
  const fetchAntes = global.fetch;
  global.fetch = fetchFalso(BRIEFING);
  try {
    // Solo se queda sonando lo que se va a cortar; lo demás acaba solo.
    const ep = endpointFalso(function (url) { return url === 'tts:Dos.' || url.indexOf('hold-music') >= 0; });
    const claude = claudeQueLee();
    // Reproducciones interrumpibles: 1 «Te lo leo», 2 «Uno», 3 «Dos» ← ahí cortas.
    const sesion = sesionFalsa(['léeme el briefing', 'para, ¿qué hora es?', 'adiós'], [3]);
    const dialogo = new EventEmitter();
    dialogo.destroy = function () {};
    const opciones = opcionesComunes(sesion, claude);
    opciones.mediaServer = { connectCaller: async function () { return { endpoint: ep, dialog: dialogo }; } };
    const req = { get: function (h) { return h === 'To' ? '<sip:10001@x>' : '<sip:10000@x>'; }, body: 'v=0' };
    await handleInvite(req, { send: function () {} }, opciones);
    assert.match(claude.preguntas[1], /^\[Le estabas leyendo el briefing y te ha cortado en la sección 1 de 2.*\] para, ¿qué hora es\?$/);
    assert.ok(ep.hecho.indexOf('play tts:Inteligencia Artificial. Tres.') < 0, 'no sigue leyendo');
  } finally {
    global.fetch = fetchAntes;
  }
});
