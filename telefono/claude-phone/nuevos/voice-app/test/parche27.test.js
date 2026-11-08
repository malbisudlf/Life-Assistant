/**
 * Parche 27: la voice-app pide al puente que precaliente la sesión de Claude al
 * descolgar, antes de que suene el saludo.
 *
 * Mismos dobles que parche22.test.js. Se lanza con `node --test test/parche27.test.js`,
 * dentro de la imagen y sin red.
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

process.env.CLAUDE_API_URL = 'http://127.0.0.1:9';     // nadie escucha ahí
const claudeBridge = require('../lib/claude-bridge');
const { handleInvite } = require('../lib/sip-handler');
const { runConversationLoop } = require('../lib/conversation-loop');

// ── Dobles ───────────────────────────────────────────────────────────────────
const orden = [];
const tts = { generateSpeech: async function (texto) { return 'tts:' + texto; } };

function endpointFalso() {
  const ep = new EventEmitter();
  ep.uuid = 'ep-1';
  ep.play = async function (url) { orden.push('play ' + url); };
  ep.api = async function () {};
  ep.forkAudioStart = async function () {};
  ep.forkAudioStop = async function () {};
  ep.destroy = async function () {};
  return ep;
}

function sesionFalsa(frases) {
  const s = new EventEmitter();
  let i = 0;
  s.setCaptureEnabled = function () {};
  s.forceFinalize = function () {};
  s.armarBargeIn = function () {};
  s.waitForUtterance = async function () {
    if (i >= frases.length) throw new Error('AudioForkSession closed for call x');
    return { audio: Buffer.from(frases[i++]), reason: 'end_silence' };
  };
  return s;
}

function claudeFalso() {
  const c = { preguntas: [], precalentadas: [] };
  c.query = async function (texto) { c.preguntas.push(texto); return '🗣️ VOICE_RESPONSE: Hecho, señor.'; };
  c.precalentar = async function (callId) { orden.push('precalentar ' + callId); c.precalentadas.push(callId); return true; };
  c.endSession = async function () {};
  return c;
}

function opciones(sesion, claude) {
  return {
    ttsService: tts, whisperClient: { transcribe: async function (a) { return a.toString(); } },
    claudeBridge: claude, wsPort: 3001,
    audioForkServer: { expectSession: async function () { return sesion; },
                       cancelExpectation: function () {}, emit: function () {} }
  };
}

// ── Casos ────────────────────────────────────────────────────────────────────
test('27, entrante: precalienta antes de que suene el saludo', async function () {
  orden.length = 0;
  const ep = endpointFalso();
  const claude = claudeFalso();
  const dialogo = new EventEmitter();
  dialogo.destroy = function () {};
  const o = opciones(sesionFalsa(['qué tengo hoy', 'adiós']), claude);
  o.mediaServer = { connectCaller: async function () { return { endpoint: ep, dialog: dialogo }; } };
  const req = { get: function (h) { return h === 'To' ? '<sip:10001@x>' : '<sip:10000@x>'; }, body: 'v=0' };
  await handleInvite(req, { send: function () {} }, o);
  assert.strictEqual(claude.precalentadas.length, 1);
  assert.match(orden[0], /^precalentar /, 'lo primero, antes del saludo');
  assert.ok(orden[1].indexOf('play tts:') === 0);
  assert.deepStrictEqual(claude.preguntas.length, 1);
});

test('27, saliente: sin aviso precalienta; con aviso, ya lo arranca la consulta del aviso', async function () {
  let claude = claudeFalso();
  await runConversationLoop(endpointFalso(), new EventEmitter(), 'c-sin',
    Object.assign(opciones(sesionFalsa(['adiós']), claude), { skipGreeting: true }));
  assert.deepStrictEqual(claude.precalentadas, ['c-sin']);

  claude = claudeFalso();
  await runConversationLoop(endpointFalso(), new EventEmitter(), 'c-con',
    Object.assign(opciones(sesionFalsa(['adiós']), claude), { skipGreeting: true, initialContext: 'Tienes clase' }));
  assert.deepStrictEqual(claude.precalentadas, []);
});

test('27: un puente sin precalentar (los dobles de antes) no rompe nada', async function () {
  const claude = claudeFalso();
  delete claude.precalentar;
  const r = await runConversationLoop(endpointFalso(), new EventEmitter(), 'c-viejo',
    Object.assign(opciones(sesionFalsa(['qué hora es', 'adiós']), claude), { skipGreeting: true }));
  assert.strictEqual(r.endReason, 'goodbye');
  assert.strictEqual(claude.preguntas.length, 1);
});

test('27: precalentar nunca lanza: sin callId, apagado o con el puente caído', async function () {
  assert.strictEqual(await claudeBridge.precalentar(''), false);
  process.env.PRECALENTAR = '0';
  try {
    assert.strictEqual(await claudeBridge.precalentar('c1'), false);
  } finally {
    delete process.env.PRECALENTAR;
  }
  assert.strictEqual(await claudeBridge.precalentar('c1', 'Eres Jarvis'), false);
});
