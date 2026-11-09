/**
 * Parche 20: la llamada lee también la semana, el correo y las tareas, y lo que Jarvis
 * propone (`✅ CONFIRMAR: <id>`) se confirma diciendo sí o no, sin que lo decida Claude.
 *
 * Mismos dobles que parche18.test.js; el backend es un fetch falso. Se lanza con
 * `node --test test/parche20.test.js`, dentro de la imagen y sin red.
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
const { preguntarSiLoPide, resolverConfirmacion, siONo, pedidoDeConfirmacion } =
  require('../lib/confirmacion');
const { handleInvite } = require('../lib/sip-handler');
const { runConversationLoop } = require('../lib/conversation-loop');

const ID = '0b6f7a52-2f5c-4b7e-9a51-6c2d1e0f9a11';
const FRASE = 'Crear «Dentista» mañana de 10:00 a 11:00.';

// ── Dobles (los de parche18.test.js) ─────────────────────────────────────────
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

function sesionFalsa(frases, cortaEn) {
  const s = new EventEmitter();
  let i = 0;
  let armados = 0;
  s.setCaptureEnabled = function () {};
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

function interrumpibles(ep) {
  return ep.hecho.filter(function (h) { return h.indexOf('play tts:') === 0; });
}

/** El backend: GET de la confirmación, POST con la respuesta, y lecturas. */
function backendFalso(apunte, opciones) {
  const o = opciones || {};
  return async function (url, op) {
    const metodo = (op && op.method) || 'GET';
    apunte.push({ url: url, metodo: metodo, cuerpo: op && op.body, auth: op && op.headers.Authorization });
    let datos;
    if (url.indexOf('/telefono/confirmar/') >= 0 && metodo === 'GET') {
      datos = o.ver || { ok: true, frase: FRASE };
    } else if (url.indexOf('/telefono/confirmar/') >= 0) {
      const r = JSON.parse(op.body).respuesta;
      datos = r === 'si' ? { ok: true, hecho: true, frase: 'Hecho. Creado «Dentista» mañana.' }
                         : { ok: true, hecho: true, frase: 'Vale, no lo hago.' };
    } else {
      datos = o.lectura || { ok: true, nombre: 'la agenda de la semana', secciones: [
        { n: 1, titulo: 'Mañana', trozos: ['Mañana. A las 10:00, Dentista.'] }] };
    }
    return { ok: true, status: 200, json: async function () { return datos; } };
  };
}

function conToken(fn) {
  return async function () {
    const antes = process.env.CONFIRMAR_TOKEN;
    process.env.CONFIRMAR_TOKEN = 'confirmar';
    try { await fn(); } finally {
      if (antes === undefined) delete process.env.CONFIRMAR_TOKEN; else process.env.CONFIRMAR_TOKEN = antes;
    }
  };
}

// ── Lectura de otras cosas ───────────────────────────────────────────────────
test('20: la marca lee semana, correo y tareas; lo demás no', function () {
  assert.strictEqual(pedidoDeLectura('📖 LEER: semana').que, 'semana');
  assert.strictEqual(pedidoDeLectura('📖 LEER: correo desde=2').desde, 2);
  assert.strictEqual(pedidoDeLectura('📖 LEER: tareas').que, 'tareas');
  assert.strictEqual(pedidoDeLectura('📖 LEER: briefing').que, 'briefing');
  assert.strictEqual(pedidoDeLectura('📖 LEER: poemas'), null);
});

test('20: la semana se pide a /telefono/lectura y se cierra con «Eso es todo»', async function () {
  const ep = endpointFalso();
  const pedidos = [];
  const r = await leerSiLoPide('📖 LEER: semana', {
    endpoint: ep, session: sesionFalsa([], []), ttsService: ttsFalso(), voiceId: 'v',
    fetchImpl: backendFalso(pedidos) });
  assert.match(pedidos[0].url, /\/telefono\/lectura\?que=semana&desde=1&hasta=0$/);
  assert.deepStrictEqual(interrumpibles(ep), ['play tts:Mañana. A las 10:00, Dentista.',
    'play tts:Eso es todo.']);
  assert.match(r.aviso, /leído la agenda de la semana entero/);
});

// ── El sí o el no ────────────────────────────────────────────────────────────
test('20: sí o no con la frase entera, y lo demás es «no lo sé»', function () {
  assert.strictEqual(siONo('Sí.'), 'si');
  assert.strictEqual(siONo('Vale, por favor.'), 'si');
  assert.strictEqual(siONo('Hazlo'), 'si');
  assert.strictEqual(siONo('No.'), 'no');
  assert.strictEqual(siONo('Mejor no'), 'no');
  assert.strictEqual(siONo('Sí, pero a las once'), null);
  assert.strictEqual(siONo('Perfecto'), null);
  assert.strictEqual(siONo(''), null);
});

test('20: el id sale de la marca, y sin marca no hay nada', function () {
  assert.strictEqual(pedidoDeConfirmacion('🗣️ VOICE_RESPONSE: x\n✅ CONFIRMAR: ' + ID), ID);
  assert.strictEqual(pedidoDeConfirmacion('✅ CONFIRMAR: no-es-un-id'), null);
  assert.strictEqual(pedidoDeConfirmacion('🗣️ VOICE_RESPONSE: hola'), null);
});

test('20: sin su token no pregunta nada (se queda en el botón)', async function () {
  delete process.env.CONFIRMAR_TOKEN;
  const ep = endpointFalso();
  const r = await preguntarSiLoPide('✅ CONFIRMAR: ' + ID, {
    endpoint: ep, session: sesionFalsa([], []), ttsService: ttsFalso(), voiceId: 'v',
    fetchImpl: function () { throw new Error('no debería preguntar'); } });
  assert.deepStrictEqual(r, { pendiente: null, interrumpio: false });
  assert.deepStrictEqual(ep.hecho, []);
});

test('20: lee la frase del BACKEND y pregunta', conToken(async function () {
  const ep = endpointFalso();
  const pedidos = [];
  const r = await preguntarSiLoPide('🗣️ VOICE_RESPONSE: Te lo leo.\n✅ CONFIRMAR: ' + ID, {
    endpoint: ep, session: sesionFalsa([], []), ttsService: ttsFalso(), voiceId: 'v',
    fetchImpl: backendFalso(pedidos) });
  assert.deepStrictEqual(r.pendiente, { id: ID, frase: FRASE });
  assert.deepStrictEqual(interrumpibles(ep), ['play tts:' + FRASE + ' ¿Lo hago?']);
  assert.strictEqual(pedidos[0].auth, 'Bearer confirmar');
}));

test('44: si el backend manda la pregunta corta, se dice esa y nada más', conToken(async function () {
  const ep = endpointFalso();
  const r = await preguntarSiLoPide('🗣️ VOICE_RESPONSE: De acuerdo.\n✅ CONFIRMAR: ' + ID, {
    endpoint: ep, session: sesionFalsa([], []), ttsService: ttsFalso(), voiceId: 'v',
    fetchImpl: backendFalso([], { ver: { ok: true, frase: FRASE, pregunta: '¿Abro la puerta del garaje?' } }) });
  // La frase entera se guarda: es la que se le cuenta a Claude en el turno siguiente.
  assert.deepStrictEqual(r.pendiente, { id: ID, frase: FRASE });
  assert.deepStrictEqual(interrumpibles(ep), ['play tts:¿Abro la puerta del garaje?']);
}));

test('20: si el backend dice que va con botón, no pregunta', conToken(async function () {
  const ep = endpointFalso();
  const r = await preguntarSiLoPide('✅ CONFIRMAR: ' + ID, {
    endpoint: ep, session: sesionFalsa([], []), ttsService: ttsFalso(), voiceId: 'v',
    fetchImpl: backendFalso([], { ver: { ok: false, motivo: 'Esto se confirma con el botón del móvil.' } }) });
  assert.strictEqual(r.pendiente, null);
  assert.deepStrictEqual(ep.hecho, []);
}));

test('20: un sí claro se confirma y se dice lo que contestó el backend', conToken(async function () {
  const ep = endpointFalso();
  const pedidos = [];
  const r = await resolverConfirmacion({ id: ID, frase: FRASE }, 'Sí, por favor.', {
    endpoint: ep, session: sesionFalsa([], []), ttsService: ttsFalso(), voiceId: 'v',
    fetchImpl: backendFalso(pedidos) });
  assert.strictEqual(r.resuelta, true);
  assert.deepStrictEqual(JSON.parse(pedidos[0].cuerpo), { respuesta: 'si' });
  assert.deepStrictEqual(interrumpibles(ep), ['play tts:Hecho. Creado «Dentista» mañana.']);
  assert.match(r.aviso, /ha contestado «sí»/);
}));

test('20: lo que no es un sí ni un no no confirma nada y va a Claude', conToken(async function () {
  const ep = endpointFalso();
  const r = await resolverConfirmacion({ id: ID, frase: FRASE }, 'Mejor a las once', {
    endpoint: ep, session: sesionFalsa([], []), ttsService: ttsFalso(), voiceId: 'v',
    fetchImpl: function () { throw new Error('no debería confirmar nada'); } });
  assert.strictEqual(r.resuelta, false);
  assert.match(r.aviso, /sigue pendiente en el móvil/);
  assert.deepStrictEqual(ep.hecho, []);
}));

// ── Los dos bucles ───────────────────────────────────────────────────────────
function claudeQuePropone() {
  const c = { preguntas: [] };
  c.query = async function (texto) {
    c.preguntas.push(texto);
    return c.preguntas.length === 1
      ? '🗣️ VOICE_RESPONSE: Te lo leo para que me confirmes.\n✅ CONFIRMAR: ' + ID + '\n🎯 COMPLETED: propuesta'
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

test('20, saliente: «sí» lo confirma sin pasar por Claude, y Claude se entera después',
  conToken(async function () {
    const fetchAntes = global.fetch;
    const pedidos = [];
    global.fetch = backendFalso(pedidos);
    try {
      const ep = endpointFalso(function (url) { return url.indexOf('hold-music') >= 0; });
      const claude = claudeQuePropone();
      const sesion = sesionFalsa(['apúntame el dentista mañana a las diez', 'sí', 'gracias', 'adiós'], []);
      const r = await runConversationLoop(ep, new EventEmitter(), 'c-sal',
        Object.assign(opcionesComunes(sesion, claude), { skipGreeting: true }));
      assert.strictEqual(r.endReason, 'goodbye');
      // Dos preguntas a Claude, no tres: el «sí» no le llega como pregunta.
      assert.strictEqual(claude.preguntas.length, 2);
      assert.match(claude.preguntas[1], /^\[Has preguntado de viva voz .* ha contestado «sí».*\] gracias$/);
      assert.ok(interrumpibles(ep).indexOf('play tts:Hecho. Creado «Dentista» mañana.') >= 0);
      assert.deepStrictEqual(pedidos.filter(function (p) { return p.metodo === 'POST'; })
        .map(function (p) { return JSON.parse(p.cuerpo); }), [{ respuesta: 'si' }]);
    } finally {
      global.fetch = fetchAntes;
    }
  }));

test('20, entrante: si contestas otra cosa, va a Claude con la propuesta pendiente',
  conToken(async function () {
    const fetchAntes = global.fetch;
    const pedidos = [];
    global.fetch = backendFalso(pedidos);
    try {
      const ep = endpointFalso(function (url) { return url.indexOf('hold-music') >= 0; });
      const claude = claudeQuePropone();
      const sesion = sesionFalsa(['apúntame el dentista', 'mejor a las once', 'adiós'], []);
      const dialogo = new EventEmitter();
      dialogo.destroy = function () {};
      const opciones = opcionesComunes(sesion, claude);
      opciones.mediaServer = { connectCaller: async function () { return { endpoint: ep, dialog: dialogo }; } };
      const req = { get: function (h) { return h === 'To' ? '<sip:10001@x>' : '<sip:10000@x>'; }, body: 'v=0' };
      await handleInvite(req, { send: function () {} }, opciones);
      assert.match(claude.preguntas[1], /^\[Le has preguntado de viva voz .*sigue pendiente en el móvil.*\] mejor a las once$/);
      assert.strictEqual(pedidos.filter(function (p) { return p.metodo === 'POST'; }).length, 0);
    } finally {
      global.fetch = fetchAntes;
    }
  }));
