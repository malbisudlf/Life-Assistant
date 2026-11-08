/**
 * Parche 26: se transcribe durante el silencio que cierra la frase (el anticipo).
 * Parche 34: a los 300 ms, también contra OpenAI, y si lo transcrito parece acabado la
 * frase se cierra antes (con jacobo lo decide `small`; lo que se usa es turbo).
 *
 * El detector de verdad (audio-fork) con audio sintético, como en parche15y16.test.js,
 * y Whisper como doble. Se lanza con `node --test test/parche26.test.js`, dentro de la
 * imagen y sin red.
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

const { AudioForkSession } = require('../lib/audio-fork');
const { armarAnticipo, transcribirFrase } = require('../lib/anticipo');

// ── Dobles ───────────────────────────────────────────────────────────────────
function trozo(voz) {
  const b = Buffer.alloc(640);
  if (voz) for (let i = 0; i < 320; i++) b.writeInt16LE(i % 2 ? 15000 : -15000, i * 2);
  return b;
}
function detector() {
  const ws = new EventEmitter();
  const s = new AudioForkSession({ ws: ws, callUuid: 'p26' });
  s.oir = function (vozMs, silencioMs) {
    for (let t = 0; t < vozMs; t += 20) ws.emit('message', trozo(true));
    for (let t = 0; t < (silencioMs || 0); t += 20) ws.emit('message', trozo(false));
  };
  s.setCaptureEnabled(true);
  s.oir(0, 1000);          // fija el orden de bytes y el suelo de ruido
  return s;
}

/**
 * Whisper: apunta lo que se le pide y contesta según `oido` (jacobo arriba o no). `falla`
 * lo hace fallar todo hasta que se apague; `dice` es el texto de turbo y de `small`.
 */
function whisperFalso(opciones) {
  opciones = opciones || {};
  const w = { pedidos: [], oido: opciones.oido !== false, falla: !!opciones.falla };
  w.oidoDisponible = function () { return w.oido; };
  w.transcribe = function (audio, o) {
    const rapido = !!(o && o.rapido);
    w.pedidos.push({ bytes: audio.length, soloOido: !!(o && o.soloOido), rapido: rapido });
    if (w.falla) return Promise.reject(new Error('no contesta'));
    if (opciones.dice) return Promise.resolve(opciones.dice);
    return Promise.resolve((rapido ? 'small ' : 'turbo ') + audio.length);
  };
  return w;
}

function frase(s) {
  return new Promise(function (r) { s.once('utterance', r); });
}

// ── El detector ──────────────────────────────────────────────────────────────
test('a los 300 ms de silencio avisa una vez, y la frase lleva esa pausa', async function () {
  const s = detector();
  const pausas = [];
  s.on('pausa', function (p) { pausas.push(p); });
  const llega = frase(s);
  s.oir(1000, 200);
  assert.strictEqual(pausas.length, 0, 'a los 200 ms aún no');
  s.oir(0, 200);
  assert.strictEqual(pausas.length, 1);
  s.oir(0, 1100);
  const u = await llega;
  assert.strictEqual(pausas.length, 1, 'una sola vez por silencio');
  assert.strictEqual(u.reason, 'end_silence');
  assert.strictEqual(u.pausa, pausas[0]);
  assert.ok(u.pausa.audio.length < u.audio.length, 'la pausa no lleva el silencio del final');
});

test('si vuelves a hablar, esa pausa no vale y la frase lleva la nueva', async function () {
  const s = detector();
  const pausas = [];
  s.on('pausa', function (p) { pausas.push(p); });
  const llega = frase(s);
  s.oir(800, 600);         // pausa a media frase…
  s.oir(800, 1500);        // …y sigues hablando
  const u = await llega;
  assert.strictEqual(pausas.length, 2);
  assert.strictEqual(u.pausa, pausas[1]);
  assert.ok(u.pausa.audio.length > pausas[0].audio.length);
});

test('sin nadie escuchando, con STT_ANTICIPO_MS=0 o con la frase cerrada por tope, no hay pausa', async function () {
  let s = detector();
  let llega = frase(s);
  s.oir(800, 1500);
  assert.strictEqual((await llega).pausa, null, 'sin oyente no se copia el audio');

  process.env.STT_ANTICIPO_MS = '0';
  try {
    s = detector();
    let pausas = 0;
    s.on('pausa', function () { pausas++; });
    llega = frase(s);
    s.oir(800, 1500);
    assert.strictEqual((await llega).pausa, null);
    assert.strictEqual(pausas, 0);
  } finally {
    delete process.env.STT_ANTICIPO_MS;
  }

  s = detector();
  s.on('pausa', function () {});
  llega = frase(s);
  s.oir(800, 600);
  s.forceFinalize();       // la # del teclado: no lo cerró ese silencio
  assert.strictEqual((await llega).pausa, null);
});

test('una tos (menos de minSpeechMs de voz) no lanza anticipo', function () {
  const s = detector();
  let pausas = 0;
  s.on('pausa', function () { pausas++; });
  s.oir(200, 600);
  assert.strictEqual(pausas, 0);
});

// ── El anticipo ──────────────────────────────────────────────────────────────
test('con jacobo arriba, la frase sale del anticipo y no se transcribe dos veces', async function () {
  const s = detector();
  const w = whisperFalso();
  armarAnticipo(s, w);
  const llega = frase(s);
  s.oir(1000, 1500);
  const u = await llega;
  assert.deepStrictEqual(w.pedidos.map(function (p) { return [p.soloOido, p.rapido]; }),
    [[false, false], [true, true]], 'turbo con su reserva, y small solo contra jacobo');
  assert.strictEqual(await transcribirFrase(w, u), 'turbo ' + u.pausa.audio.length, 'lo que se usa es turbo');
  assert.strictEqual(w.pedidos.length, 2);
});

test('con el oído caído se anticipa igual, por OpenAI y sin preguntar a small', async function () {
  const s = detector();
  const w = whisperFalso({ oido: false });
  armarAnticipo(s, w);
  const llega = frase(s);
  s.oir(1000, 1500);
  const u = await llega;
  assert.deepStrictEqual(w.pedidos.map(function (p) { return [p.soloOido, p.rapido]; }), [[false, false]]);
  assert.strictEqual(await transcribirFrase(w, u), 'turbo ' + u.pausa.audio.length);
  assert.strictEqual(w.pedidos.length, 1, 'no se transcribe dos veces');
});

test('si el anticipo falla, se transcribe la frase entera', async function () {
  const s = detector();
  const w = whisperFalso({ falla: true });
  armarAnticipo(s, w);
  const llega = frase(s);
  s.oir(1000, 1500);
  const u = await llega;
  w.falla = false;
  assert.strictEqual(await transcribirFrase(w, u), 'turbo ' + u.audio.length);
  assert.strictEqual(w.pedidos.length, 3, 'turbo y small en la pausa, y la frase entera');
  assert.strictEqual(w.pedidos[2].bytes, u.audio.length);
});

test('con la escucha pasiva dormida no se anticipa (la radio del coche)', async function () {
  const s = detector();
  const w = whisperFalso();
  let dormida = true;
  armarAnticipo(s, w, { activo: function () { return !dormida; } });
  let llega = frase(s);
  s.oir(1000, 1500);
  await llega;
  assert.strictEqual(w.pedidos.length, 0);
  dormida = false;
  llega = frase(s);
  s.oir(1000, 1500);
  await llega;
  assert.strictEqual(w.pedidos.length, 2, 'despierta: turbo y small');
});

test('un whisperClient sin oidoDisponible (los dobles de los otros tests) no se toca', async function () {
  const s = detector();
  const w = { pedidos: 0, transcribe: async function () { w.pedidos++; return 'hola'; } };
  armarAnticipo(s, w);
  const llega = frase(s);
  s.oir(1000, 1500);
  const u = await llega;
  assert.strictEqual(w.pedidos, 0);
  assert.strictEqual(await transcribirFrase(w, u), 'hola');
});

// ── El cierre rápido (parche 34) ─────────────────────────────────────────────
test('34: si lo transcrito parece acabado, la frase se cierra a los 700 ms', async function () {
  const s = detector();
  armarAnticipo(s, whisperFalso({ dice: 'Apaga la tele.' }));
  let cerrada = false;
  s.once('utterance', function () { cerrada = true; });
  s.oir(1000, 400);
  await new Promise(setImmediate);   // aquí llega la transcripción de la pausa
  s.oir(0, 200);
  assert.strictEqual(cerrada, false, 'a los 600 ms aún no');
  s.oir(0, 100);
  assert.strictEqual(cerrada, true);
});

test('34: si se queda a medias, se esperan los 1.200 ms', async function () {
  const s = detector();
  armarAnticipo(s, whisperFalso({ dice: 'Mándale un mensaje a' }));
  let cerrada = false;
  s.once('utterance', function () { cerrada = true; });
  s.oir(1000, 400);
  await new Promise(setImmediate);
  s.oir(0, 700);
  assert.strictEqual(cerrada, false, 'a los 1.100 ms aún no');
  s.oir(0, 100);
  assert.strictEqual(cerrada, true);
});

test('34: si has vuelto a hablar, la transcripción de la pausa vieja no cierra nada', async function () {
  const s = detector();
  armarAnticipo(s, whisperFalso({ dice: 'Apaga la tele.' }));
  let cerrada = false;
  s.once('utterance', function () { cerrada = true; });
  s.oir(1000, 250);
  s.oir(0, 100);           // la pausa ya salió, y su transcripción aún no ha llegado…
  s.oir(500, 0);           // …cuando vuelves a hablar
  await new Promise(setImmediate);
  s.oir(0, 280);           // sin llegar a los 300 de la pausa nueva
  await new Promise(setImmediate);
  s.oir(0, 400);
  assert.strictEqual(cerrada, false, 'a los 680 ms: la pausa nueva sale aquí y aún no tiene texto');
  s.oir(0, 520);
  assert.strictEqual(cerrada, true);
});
