/**
 * Parche 51: small primero y turbo detrás, para que el cierre rápido salte de verdad.
 *
 * Hasta aquí el cierre rápido (700 ms) lo decidía turbo, que tarda ~1,15 s en jacobo: la
 * frase siempre se cerraba por los 1.200 ms y el pitido llegaba a 1,5-2 s. Ahora small
 * (0,42 s) decide si la frase está acabada y turbo transcribe después, en fila.
 *
 * El detector de verdad (audio-fork) con audio sintético y Whisper como doble que se
 * contesta a mano, para poder decir CUÁNDO llega cada transcripción respecto al silencio.
 * Se lanza con `node --test test/parche51.test.js`, dentro de la imagen y sin red.
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
delete process.env.ANTICIPO_PRIMERO;
delete process.env.ANTICIPO_RAPIDO;

const { AudioForkSession } = require('../lib/audio-fork');
const { armarAnticipo, transcribirFrase, primeroActivo } = require('../lib/anticipo');

function trozo(voz) {
  const b = Buffer.alloc(640);
  if (voz) for (let i = 0; i < 320; i++) b.writeInt16LE(i % 2 ? 15000 : -15000, i * 2);
  return b;
}
function detector() {
  const ws = new EventEmitter();
  const s = new AudioForkSession({ ws: ws, callUuid: 'p51' });
  s.oir = function (vozMs, silencioMs) {
    for (let t = 0; t < vozMs; t += 20) ws.emit('message', trozo(true));
    for (let t = 0; t < (silencioMs || 0); t += 20) ws.emit('message', trozo(false));
  };
  s.setCaptureEnabled(true);
  s.oir(0, 1000);
  return s;
}

/** Whisper que no contesta hasta que se le dice: `w.contesta('small', texto)`. */
function whisperAMano(opciones) {
  opciones = opciones || {};
  const w = { pedidos: [], pendientes: [] };
  w.oidoDisponible = function () { return opciones.oido !== false; };
  w.transcribe = function (audio, o) {
    const modelo = o && o.rapido ? 'small' : 'turbo';
    w.pedidos.push(modelo);
    return new Promise(function (resolve, reject) {
      w.pendientes.push({ modelo: modelo, resolve: resolve, reject: reject });
    });
  };
  w.contesta = async function (modelo, texto) {
    const i = w.pendientes.findIndex(function (p) { return p.modelo === modelo; });
    assert.ok(i >= 0, 'nadie le ha pedido nada a ' + modelo);
    const p = w.pendientes.splice(i, 1)[0];
    if (texto instanceof Error) p.reject(texto); else p.resolve(texto);
    for (let k = 0; k < 5; k++) await new Promise(setImmediate);
  };
  return w;
}

test('51: va por defecto, y ANTICIPO_PRIMERO=0 o ANTICIPO_RAPIDO=1 lo apagan', function () {
  assert.strictEqual(primeroActivo(), true);
  process.env.ANTICIPO_PRIMERO = '0';
  assert.strictEqual(primeroActivo(), false);
  delete process.env.ANTICIPO_PRIMERO;
  process.env.ANTICIPO_RAPIDO = '1';
  assert.strictEqual(primeroActivo(), false);
  delete process.env.ANTICIPO_RAPIDO;
});

test('51: al pausar se pide solo small; turbo, cuando small contesta', async function () {
  const s = detector();
  const w = whisperAMano();
  armarAnticipo(s, w);
  s.oir(1000, 300);
  assert.deepStrictEqual(w.pedidos, ['small'], 'turbo no se pelea con small por la GPU');
  await w.contesta('small', 'Mándale un mensaje a');
  assert.deepStrictEqual(w.pedidos, ['small', 'turbo']);
});

test('51: small dice que está acabada → la frase se cierra a los 700 ms y el texto es de turbo', async function () {
  const s = detector();
  const w = whisperAMano();
  armarAnticipo(s, w);
  let u = null;
  s.once('utterance', function (x) { u = x; });
  s.oir(1000, 400);
  await w.contesta('small', 'Llamad a Dick y pregúntale si viene a comer.');
  s.oir(0, 200);
  assert.strictEqual(u, null, 'a los 600 ms aún no');
  s.oir(0, 100);
  assert.ok(u, 'a los 700 ms, cerrada: el pitido ya puede sonar');
  const texto = transcribirFrase(w, u);
  await w.contesta('turbo', 'Llama a Erik y pregúntale si viene a comer.');
  assert.strictEqual(await texto, 'Llama a Erik y pregúntale si viene a comer.', 'lo que se usa es turbo, no small');
  assert.deepStrictEqual(w.pedidos, ['small', 'turbo'], 'sin transcribir la frase dos veces');
});

test('51: small la ve a medias → se esperan los 1.200 ms, con turbo ya en marcha', async function () {
  const s = detector();
  const w = whisperAMano();
  armarAnticipo(s, w);
  let u = null;
  s.once('utterance', function (x) { u = x; });
  s.oir(1000, 400);
  await w.contesta('small', 'Pon la calefacción de mi');
  assert.deepStrictEqual(w.pedidos, ['small', 'turbo']);
  s.oir(0, 700);
  assert.strictEqual(u, null, 'a los 1.100 ms aún no');
  s.oir(0, 100);
  assert.ok(u);
  const texto = transcribirFrase(w, u);
  await w.contesta('turbo', 'Pon la calefacción de mi cuarto.');
  assert.strictEqual(await texto, 'Pon la calefacción de mi cuarto.');
});

test('51: si vuelves a hablar antes de que conteste small, turbo ni se lanza', async function () {
  const s = detector();
  const w = whisperAMano();
  armarAnticipo(s, w);
  s.oir(1000, 400);
  s.oir(500, 0);                       // sigues hablando
  await w.contesta('small', 'Apaga la tele.');
  assert.deepStrictEqual(w.pedidos, ['small'], 'una pasada de GPU menos');
});

test('51: si small falla, turbo arranca igual y la frase sale de él', async function () {
  const s = detector();
  const w = whisperAMano();
  armarAnticipo(s, w);
  let u = null;
  s.once('utterance', function (x) { u = x; });
  s.oir(1000, 400);
  await w.contesta('small', new Error('jacobo no contesta'));
  assert.deepStrictEqual(w.pedidos, ['small', 'turbo']);
  s.oir(0, 800);
  assert.ok(u, 'sin veredicto de small, los 1.200 ms de siempre');
  const texto = transcribirFrase(w, u);
  await w.contesta('turbo', 'Apaga la tele.');
  assert.strictEqual(await texto, 'Apaga la tele.');
});

test('51: si small se atasca, turbo arranca a los ANTICIPO_ESPERA_SMALL_MS', async function () {
  process.env.ANTICIPO_ESPERA_SMALL_MS = '30';
  try {
    const s = detector();
    const w = whisperAMano();
    armarAnticipo(s, w);
    s.oir(1000, 400);
    assert.deepStrictEqual(w.pedidos, ['small']);
    await new Promise(function (r) { setTimeout(r, 60); });
    assert.deepStrictEqual(w.pedidos, ['small', 'turbo']);
  } finally {
    delete process.env.ANTICIPO_ESPERA_SMALL_MS;
  }
});

test('51: si la frase se cerró por los 1.200 ms antes de que small conteste, se transcribe entera', async function () {
  const s = detector();
  const w = whisperAMano();
  armarAnticipo(s, w);
  let u = null;
  s.once('utterance', function (x) { u = x; });
  s.oir(1000, 1300);
  assert.ok(u);
  await w.contesta('small', 'Apaga la tele.');
  assert.deepStrictEqual(w.pedidos, ['small'], 'turbo de una pausa que ya no usa nadie, no');
  const texto = transcribirFrase(w, u);
  for (let k = 0; k < 5; k++) await new Promise(setImmediate);
  assert.deepStrictEqual(w.pedidos, ['small', 'turbo'], 'la frase entera, como sin anticipo');
  await w.contesta('turbo', 'Apaga la tele.');
  assert.strictEqual(await texto, 'Apaga la tele.');
});

test('51: con el oído caído no hay small (OpenAI no lo tiene): solo turbo, como antes', async function () {
  const s = detector();
  const w = whisperAMano({ oido: false });
  armarAnticipo(s, w);
  s.oir(1000, 400);
  assert.deepStrictEqual(w.pedidos, ['turbo']);
});
