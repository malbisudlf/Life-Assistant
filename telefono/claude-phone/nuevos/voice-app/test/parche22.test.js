/**
 * Parche 22: la escucha pasiva («modo coche»). La llamada se queda abierta, Jarvis
 * callado, y solo contesta cuando alguien dice su nombre.
 *
 * Mismos dobles que parche20.test.js. Se lanza con `node --test test/parche22.test.js`,
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

const { EscuchaPasiva, buscarPalabra, esFinDeTurno, FRASES, AVISO_PASIVA } =
  require('../lib/escucha-pasiva');
const { handleInvite } = require('../lib/sip-handler');
const { runConversationLoop } = require('../lib/conversation-loop');

// ── Dobles ───────────────────────────────────────────────────────────────────
function ttsFalso() {
  const t = { pedidos: [] };
  t.generateSpeech = async function (texto) { t.pedidos.push(texto); return 'tts:' + texto; };
  return t;
}

function endpointFalso() {
  const ep = new EventEmitter();
  ep.uuid = 'ep-1';
  ep.hecho = [];
  ep.play = async function (url) { ep.hecho.push('play ' + url); };
  ep.api = async function (cmd) { ep.hecho.push('api ' + cmd); };
  ep.forkAudioStart = async function () {};
  ep.forkAudioStop = async function () {};
  ep.destroy = async function () {};
  return ep;
}

/** Cada frase es lo que se oye; null es un minuto (o los 8 s de seguir) sin que nadie hable. */
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

function whisperFalso() {
  const w = { oido: [], prompts: [] };
  w.transcribe = async function (a, o) { w.oido.push(a.toString()); w.prompts.push(o && o.prompt); return a.toString(); };
  return w;
}

function claudeFalso() {
  const c = { preguntas: [] };
  c.query = async function (texto) { c.preguntas.push(texto); return '🗣️ VOICE_RESPONSE: Doce grados, señor.'; };
  c.endSession = async function () {};
  return c;
}

function opciones(sesion, claude, whisper, tts) {
  return {
    ttsService: tts, whisperClient: whisper, claudeBridge: claude, wsPort: 3001,
    audioForkServer: { expectSession: async function () { return sesion; },
                       cancelExpectation: function () {}, emit: function () {} }
  };
}

function dichas(ep) {
  return ep.hecho.filter(function (h) { return h.indexOf('play tts:') === 0; })
    .map(function (h) { return h.slice('play tts:'.length); });
}

// ── La palabra ───────────────────────────────────────────────────────────────
test('22: oye su nombre como lo escribe Whisper, y no lo confunde', function () {
  assert.deepStrictEqual(buscarPalabra('Jarvis, ¿qué tengo hoy?'), { resto: 'qué tengo hoy?' });
  assert.deepStrictEqual(buscarPalabra('Oye Yarvis pon música'), { resto: 'pon música' });
  assert.deepStrictEqual(buscarPalabra('Charvis, apaga la luz.'), { resto: 'apaga la luz.' });
  assert.deepStrictEqual(buscarPalabra('jarbis cuánto queda'), { resto: 'cuánto queda' });
  // Al final: la frase que lo lleva, no lo que se hablaba antes.
  assert.deepStrictEqual(buscarPalabra('Y eso fue todo. ¿Qué hora es, Jarvis?'), { resto: 'Qué hora es' });
  // Solo el nombre: toca preguntar.
  assert.deepStrictEqual(buscarPalabra('Jarvis.'), { resto: '' });
  for (const t of ['Fuimos al cine con Travis', 'Gervasio llega tarde', 'el coche de Marvis', 'avisa a tu madre', '']) {
    assert.strictEqual(buscarPalabra(t), null, t);
  }
});

test('22: «gracias» o «eso es todo» solos le duermen; dentro de otra frase, no', function () {
  assert.ok(esFinDeTurno('Gracias.'));
  assert.ok(esFinDeTurno('Vale, gracias, Jarvis.'));
  assert.ok(esFinDeTurno('Eso es todo'));
  assert.ok(!esFinDeTurno('Gracias, y pon música'));
});

test('22: las órdenes de la escucha', function () {
  const p = new EscuchaPasiva();
  assert.strictEqual(p.orden('gracias'), null, 'sin escucha pasiva, «gracias» va a Claude');
  assert.deepStrictEqual(p.orden('Pon el modo coche'), { frase: FRASES.activada });
  assert.ok(p.dormida());
  p.despierta = true;
  assert.deepStrictEqual(p.orden('gracias'), { frase: FRASES.dormir });
  assert.ok(p.dormida());
  assert.deepStrictEqual(p.orden('modo normal'), { frase: FRASES.normal });
  assert.ok(!p.activa && !p.dormida());
});

// ── Escuchar dormido ─────────────────────────────────────────────────────────
test('22: dormido no contesta a la charla, y despierta con su nombre', async function () {
  const p = new EscuchaPasiva({ activa: true });
  const w = whisperFalso();
  const r = await p.esperarPalabra({
    session: sesionFalsa([null, 'hablábamos del partido', 'Jarvis, ¿y el tiempo?']), whisperClient: w });
  assert.deepStrictEqual(r, { resto: 'y el tiempo?' });
  assert.deepStrictEqual(w.oido, ['hablábamos del partido', 'Jarvis, ¿y el tiempo?']);
  assert.ok(w.prompts.every(function (x) { return x === 'Jarvis.'; }), 'le pista el nombre a Whisper');
  assert.ok(!p.dormida());
});

test('22: de una frase larga transcribe solo el principio, y entera si trae el nombre', async function () {
  process.env.ESCUCHA_PASIVA_VENTANA_MS = '1';            // 32 bytes
  try {
    const p = new EscuchaPasiva({ activa: true });
    const w = whisperFalso();
    const charla = 'esto es una frase larga de las que se dicen en el coche';
    const orden = 'Jarvis, apaga la calefacción de casa que se nos ha olvidado';
    const r = await p.esperarPalabra({ session: sesionFalsa([charla, orden]), whisperClient: w });
    const principio = function (t) { return Buffer.from(t).subarray(0, 32).toString(); };
    assert.deepStrictEqual(w.oido, [principio(charla), principio(orden), orden]);
    assert.strictEqual(r.resto, 'apaga la calefacción de casa que se nos ha olvidado');
  } finally {
    delete process.env.ESCUCHA_PASIVA_VENTANA_MS;
  }
});

test('22: al colgar deja de escuchar, y el tope de tiempo cuelga', async function () {
  const p = new EscuchaPasiva({ activa: true });
  assert.strictEqual(await p.esperarPalabra({ session: sesionFalsa(['charla']), whisperClient: whisperFalso() }), null);
  const viejo = new EscuchaPasiva({ activa: true });
  viejo.desde = Date.now() - viejo.topeMs - 1;
  assert.deepStrictEqual(await viejo.esperarPalabra({ session: sesionFalsa([]), whisperClient: whisperFalso() }),
    { tope: true });
});

// ── Los dos bucles ───────────────────────────────────────────────────────────
test('22, saliente: la llamada del coche empieza callada y solo contesta a «Jarvis»', async function () {
  const ep = endpointFalso();
  const tts = ttsFalso();
  const claude = claudeFalso();
  const turnos = [];
  const sesion = sesionFalsa(['qué tráfico hay hoy', 'Jarvis, ¿qué tiempo hace?', null,
    'otra vez charla', 'Jarvis', 'pon las noticias', 'gracias', 'Jarvis, cuelga']);
  const r = await runConversationLoop(ep, new EventEmitter(), 'c-coche',
    Object.assign(opciones(sesion, claude, whisperFalso(), tts),
      { skipGreeting: true, escuchaPasiva: true, onUserTurn: function (t) { turnos.push(t); } }));
  assert.strictEqual(r.endReason, 'goodbye');
  // Solo lo que iba con su nombre (y lo que siguió al «¿Señor?») llega a Claude.
  assert.deepStrictEqual(claude.preguntas, [AVISO_PASIVA + 'qué tiempo hace?', AVISO_PASIVA + 'pon las noticias']);
  const d = dichas(ep);
  assert.ok(d.indexOf('No te he oído. ¿Sigues ahí?') < 0, 'dormido, el silencio es lo normal');
  assert.ok(d.indexOf(FRASES.despierta) >= 0);
  assert.ok(d.indexOf(FRASES.dormir) >= 0);
  // Tras contestar, los 8 s para seguir hablando sin repetir el nombre.
  assert.ok(sesion.esperas.indexOf(8000) >= 0);
  assert.deepStrictEqual(turnos, ['qué tiempo hace?', 'Jarvis', 'cuelga']);
});

test('22, entrante: «modo coche» a media llamada, y «modo normal» la devuelve', async function () {
  const ep = endpointFalso();
  const tts = ttsFalso();
  const claude = claudeFalso();
  const sesion = sesionFalsa(['activa el modo coche', 'charla del coche', null,
    'Jarvis, modo normal', 'qué hora es', 'adiós']);
  const dialogo = new EventEmitter();
  dialogo.destroy = function () {};
  const o = opciones(sesion, claude, whisperFalso(), tts);
  o.mediaServer = { connectCaller: async function () { return { endpoint: ep, dialog: dialogo }; } };
  const req = { get: function (h) { return h === 'To' ? '<sip:10001@x>' : '<sip:10000@x>'; }, body: 'v=0' };
  await handleInvite(req, { send: function () {} }, o);
  const d = dichas(ep);
  assert.ok(d.indexOf(FRASES.activada) >= 0);
  assert.ok(d.indexOf(FRASES.normal) >= 0);
  // «modo coche» y «modo normal» no van a Claude; la charla tampoco. Lo de después, sí,
  // y ya sin el aviso del modo coche.
  assert.deepStrictEqual(claude.preguntas, ['qué hora es']);
  assert.ok(d.indexOf('Hasta luego. Llámame cuando quieras.') >= 0);
});

test('22: sin escucha pasiva, todo sigue como antes', async function () {
  const ep = endpointFalso();
  const claude = claudeFalso();
  const r = await runConversationLoop(ep, new EventEmitter(), 'c-normal',
    Object.assign(opciones(sesionFalsa(['hola', null, null]), claude, whisperFalso(), ttsFalso()),
      { skipGreeting: true }));
  assert.strictEqual(r.endReason, 'silence');
  assert.deepStrictEqual(claude.preguntas, ['hola']);
  assert.ok(dichas(ep).indexOf('No te he oído. ¿Sigues ahí?') >= 0);
});
