/**
 * Parche 35: el sí hablado se oye. Las frases de los casos son las de llamadas reales del
 * 2026-11-04 y 05, en las que Mikel dijo que sí y Jarvis acabó mandándole al botón.
 *
 * FreeSWITCH, la voz, el oído, Claude y el backend son dobles; el detector es el de verdad
 * con audio sintético. Se lanza con `node --test test/parche35.test.js`, dentro de la imagen
 * y sin red.
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

const { siONo, pareceSi, turnoDeRespuesta, resolverConfirmacion } = require('../lib/confirmacion');
const { AudioForkSession } = require('../lib/audio-fork');
const { FRASES } = require('../lib/escucha-pasiva');
const { handleInvite } = require('../lib/sip-handler');
const { runConversationLoop } = require('../lib/conversation-loop');

const ID = '0b6f7a52-2f5c-4b7e-9a51-6c2d1e0f9a11';
const FRASE = 'Mandar por WhatsApp a Aimar: «Llego tarde».';
const HECHO = 'Hecho. Mandado a Aimar.';
const OTRA_VEZ = 'Perdone, señor, no le he oído bien. ¿Lo hago? Diga sí o no.';

// ── Lo que cuenta como sí ────────────────────────────────────────────────────
test('35: un sí con relleno es un sí', function () {
  for (const f of ['Sí, créalo, anda, venga, créalo', 'Sí, sí, sí, ando, tío.', 'Sí, mándalo',
                   'Venga, sí, joder', 'Vale, envíaselo', 'Claro, hazlo ya']) {
    assert.strictEqual(siONo(f), 'si', f);
  }
  for (const f of ['No, joder', 'Que no, hombre', 'No, cancélalo', 'Mejor no']) {
    assert.strictEqual(siONo(f), 'no', f);
  }
});

test('35: lo que dice otra cosa sigue sin ser ni sí ni no', function () {
  for (const f of ['Sí, pero a las once', 'Sí, a las nueve', 'Si lo haces', 'Si no', 'Vale, para',
                   'No, no, lo que quiero que hagas es que apuntes a las 9', 'No, venga, hazlo',
                   'Perfecto', 'Anda', 'Pero si le he dado que sí', '']) {
    assert.strictEqual(siONo(f), null, f);
  }
});

test('35: suena a sí solo con casi todo de sí y nada que lo matice', function () {
  assert.strictEqual(pareceSi('Sí, sí, audio, venga.'), true);
  for (const f of ['Sí, a las nueve', 'Sí, pero a las once', 'Le acabo de dar, ¿vale?',
                   'Hola, buenos días', 'No, sí, audio', '¿Puedes ir al gimnasio o a clase?']) {
    assert.strictEqual(pareceSi(f), false, f);
  }
});

// ── El detector de verdad ────────────────────────────────────────────────────
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
  s.setCaptureEnabled(true);
  s.oir(0, 1000);
  s.setCaptureEnabled(false);
  return s;
}
function frasesDe(s, oir) {
  const oidas = [];
  const alOir = function (u) { oidas.push(u); };
  s.on('utterance', alOir);
  oir();
  s.off('utterance', alOir);
  return oidas;
}
// Una frase con mucho silencio dentro: la voz se queda por debajo del 12 %.
function aTrozos(s) {
  for (let i = 0; i < 6; i++) s.oir(120, 1000);
  s.oir(0, 1400);
}

test('35: un «sí» de 300 ms se tira en un turno normal y vale contestando a una pregunta', function () {
  const s = detector();
  s.setCaptureEnabled(true);
  assert.strictEqual(frasesDe(s, function () { s.oir(300, 1400); }).length, 0);
  s.setCaptureEnabled(false);

  s.setCaptureEnabled(true);
  assert.strictEqual(turnoDeRespuesta(s, { id: ID }, 8000), 20000);
  assert.strictEqual(frasesDe(s, function () { s.oir(300, 1400); }).length, 1);
  s.setCaptureEnabled(false);

  // Al cerrar el oído vuelve a lo de siempre: el turno siguiente no hereda nada.
  s.setCaptureEnabled(true);
  assert.strictEqual(frasesDe(s, function () { s.oir(300, 1400); }).length, 0);
  s.setCaptureEnabled(false);
});

test('35: tampoco se tira por llevar poca voz entre el ruido', function () {
  const s = detector();
  s.setCaptureEnabled(true);
  assert.strictEqual(frasesDe(s, function () { aTrozos(s); }).length, 0);
  s.setCaptureEnabled(false);

  s.setCaptureEnabled(true);
  turnoDeRespuesta(s, { id: ID }, 8000);
  assert.strictEqual(frasesDe(s, function () { aTrozos(s); }).length, 1);
  s.setCaptureEnabled(false);
});

test('35: sin pregunta en el aire el turno espera lo de siempre', function () {
  const s = detector();
  s.setCaptureEnabled(true);
  assert.strictEqual(turnoDeRespuesta(s, null, 8000), 8000);
  assert.strictEqual(s._respuestaCorta, false);
});

// ── Los dos bucles ───────────────────────────────────────────────────────────
function ttsFalso() {
  return { generateSpeech: async function (texto) { return 'tts:' + texto; } };
}
function endpointFalso() {
  const ep = new EventEmitter();
  ep.uuid = 'ep-1';
  ep.hecho = [];
  ep.play = async function (url) { ep.hecho.push(url); };
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
  s.esperas = [];
  s.waitForUtterance = async function (o) {
    s.esperas.push(o && o.timeoutMs);
    if (i >= frases.length) throw new Error('AudioForkSession closed for call x');
    const f = frases[i++];
    if (f == null) throw new Error('Timed out waiting for utterance');
    return { audio: Buffer.from(f), reason: 'end_silence' };
  };
  return s;
}
function claudeQuePropone() {
  const c = { preguntas: [] };
  c.query = async function (texto) {
    c.preguntas.push(texto);
    return c.preguntas.length === 1
      ? '🗣️ VOICE_RESPONSE: Te lo leo para que me confirmes.\n✅ CONFIRMAR: ' + ID
      : '🗣️ VOICE_RESPONSE: vale';
  };
  c.endSession = async function () {};
  return c;
}
function opciones(sesion, claude) {
  return {
    ttsService: ttsFalso(), claudeBridge: claude, wsPort: 3001,
    whisperClient: { transcribe: async function (a) { return a.toString(); } },
    audioForkServer: { expectSession: async function () { return sesion; },
                       cancelExpectation: function () {}, emit: function () {} }
  };
}
function conBackend(fn) {
  return async function () {
    const antesF = global.fetch;
    const antesT = process.env.CONFIRMAR_TOKEN;
    process.env.CONFIRMAR_TOKEN = 'confirmar';
    const posts = [];
    global.fetch = async function (url, op) {
      const post = op && op.method === 'POST';
      if (post) posts.push(JSON.parse(op.body).respuesta);
      const datos = post ? { ok: true, hecho: true, frase: HECHO } : { ok: true, frase: FRASE };
      return { ok: true, status: 200, json: async function () { return datos; } };
    };
    try { await fn(posts); } finally {
      global.fetch = antesF;
      if (antesT === undefined) delete process.env.CONFIRMAR_TOKEN; else process.env.CONFIRMAR_TOKEN = antesT;
    }
  };
}
function coche(frases) {
  const ep = endpointFalso();
  const claude = claudeQuePropone();
  const sesion = sesionFalsa(frases);
  return runConversationLoop(ep, new EventEmitter(), 'c-coche',
    Object.assign(opciones(sesion, claude), { skipGreeting: true, escuchaPasiva: true }))
    .then(function (r) { return { r, ep, claude, sesion }; });
}

test('35, coche: «vale» confirma, y no le duerme', conBackend(async function (posts) {
  const { ep, sesion, claude } = await coche(['Jarvis, dile a Aimar que llego tarde', 'vale', 'Jarvis, cuelga']);
  assert.deepStrictEqual(posts, ['si']);
  assert.ok(ep.hecho.indexOf('tts:' + HECHO) >= 0);
  assert.ok(ep.hecho.indexOf('tts:' + FRASES.dormir) < 0);
  assert.ok(sesion.esperas.indexOf(20000) >= 0, JSON.stringify(sesion.esperas));
  assert.strictEqual(claude.preguntas.length, 1);
}));

test('35, coche: el ruido en mitad de la pregunta no le duerme, y el sí de después vale',
  conBackend(async function (posts) {
    const { ep } = await coche(['Jarvis, dile a Aimar que llego tarde', '', 'sí', 'Jarvis, cuelga']);
    assert.deepStrictEqual(posts, ['si']);
    assert.ok(ep.hecho.indexOf('tts:' + HECHO) >= 0);
  }));

test('35, coche: si sigue diciendo que no con relleno, no se manda', conBackend(async function (posts) {
  await coche(['Jarvis, dile a Aimar que llego tarde', 'no, joder', 'Jarvis, cuelga']);
  assert.deepStrictEqual(posts, ['no']);
}));

test('35, saliente: lo que suena a sí se pregunta una vez más, sin pasar por Claude',
  conBackend(async function (posts) {
    const ep = endpointFalso();
    const claude = claudeQuePropone();
    const sesion = sesionFalsa(['dile a Aimar que llego tarde', 'Sí, sí, audio, venga', 'sí', 'adiós']);
    await runConversationLoop(ep, new EventEmitter(), 'c-sal',
      Object.assign(opciones(sesion, claude), { skipGreeting: true }));
    assert.deepStrictEqual(posts, ['si']);
    assert.ok(ep.hecho.indexOf('tts:' + OTRA_VEZ) >= 0);
    assert.strictEqual(claude.preguntas.length, 1);
  }));

test('35, entrante: se vuelve a preguntar una sola vez; la segunda va a Claude y no confirma',
  conBackend(async function (posts) {
    const ep = endpointFalso();
    const claude = claudeQuePropone();
    const sesion = sesionFalsa(['dile a Aimar que llego tarde', 'Sí, sí, audio, venga', 'sí, sí, radio, venga', 'adiós']);
    const dialogo = new EventEmitter();
    dialogo.destroy = function () {};
    const o = opciones(sesion, claude);
    o.mediaServer = { connectCaller: async function () { return { endpoint: ep, dialog: dialogo }; } };
    const req = { get: function (h) { return h === 'To' ? '<sip:10001@x>' : '<sip:10000@x>'; }, body: 'v=0' };
    await handleInvite(req, { send: function () {} }, o);
    assert.deepStrictEqual(posts, []);
    assert.strictEqual(ep.hecho.filter(function (u) { return u === 'tts:' + OTRA_VEZ; }).length, 1);
    assert.match(claude.preguntas[1], /sigue pendiente en el móvil/);
  }));

test('35: Claude sabe que puede volver a preguntar, y con qué id', async function () {
  const ep = endpointFalso();
  const r = await resolverConfirmacion({ id: ID, frase: FRASE }, 'Mejor a las once', {
    endpoint: ep, session: sesionFalsa([]), ttsService: ttsFalso(), voiceId: 'v',
    fetchImpl: function () { throw new Error('no debería confirmar nada'); } });
  assert.strictEqual(r.resuelta, false);
  assert.ok(r.aviso.indexOf('✅ CONFIRMAR: ' + ID) >= 0);
  assert.match(r.aviso, /Un sí hablado sí vale/);
  assert.deepStrictEqual(ep.hecho, []);
});
