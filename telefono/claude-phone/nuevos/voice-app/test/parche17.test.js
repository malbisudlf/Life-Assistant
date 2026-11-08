/**
 * Parche 17: el detector no adivina el orden de los bytes por volumen.
 *
 * El 2026-10-14, en el coche, dos llamadas seguidas: el primer trozo de audio traía
 * un poco de ruido del Bluetooth (RMS 53 y 160), el original eligió BE porque leído
 * al revés daba más volumen, y el resto de la llamada el detector vio ruido a tope
 * (RMS ~19.000). Jarvis no sabía cuándo hablabas. Se lanza con
 * `node --test test/parche17.test.js`, dentro de la imagen y sin red.
 */
'use strict';

const test = require('node:test');
const assert = require('node:assert');
const Module = require('node:module');

const requireDeVerdad = Module.prototype.require;
Module.prototype.require = function (id) {
  if (id === 'ws') return { Server: function () {} };
  return requireDeVerdad.apply(this, arguments);
};
console.log = function () {};

const { AudioForkSession } = require('../lib/audio-fork');

const RATE = 16000;
const TROZO = 320; // 20 ms a 16 kHz

/** Muestras LE: un seno de `amp` más un ruido de fondo de `ruido`. */
function audio(ms, amp, ruido, fase) {
  const n = Math.round(RATE * ms / 1000);
  const buf = Buffer.alloc(n * 2);
  for (let i = 0; i < n; i++) {
    const t = (fase || 0) + i;
    const v = amp * Math.sin(2 * Math.PI * 220 * t / RATE) + ruido * (Math.random() * 2 - 1);
    buf.writeInt16LE(Math.max(-32768, Math.min(32767, Math.round(v))), i * 2);
  }
  return buf;
}

function trozos(buf) {
  const out = [];
  for (let i = 0; i < buf.length; i += TROZO * 2) out.push(buf.subarray(i, i + TROZO * 2));
  return out;
}

function sesion() {
  const ws = { on: function () {}, close: function () {} };
  return new AudioForkSession({ ws, callUuid: 'p17', sampleRate: RATE });
}

/** Mete silencio con algo de ruido, una frase y otra vez silencio; devuelve la frase. */
async function conversar(s) {
  const fin = s.waitForUtterance({ timeoutMs: 5000 });
  const todo = Buffer.concat([audio(600, 0, 60), audio(1200, 6000, 60), audio(2000, 0, 60)]);
  for (const t of trozos(todo)) s._onMessage(t);
  return fin;
}

test('con algo de ruido al empezar (el coche) se lee LE y la frase se cierra', async function () {
  delete process.env.AUDIO_FORK_ENDIAN;
  const s = sesion();
  const u = await conversar(s);
  assert.strictEqual(s._pcmEndian, 'LE');
  assert.strictEqual(u.reason, 'end_silence');
  assert.ok(u.speechMs >= 800, 'se oyó la frase: ' + u.speechMs + ' ms');
});

test('AUDIO_FORK_ENDIAN=BE lo fuerza', function () {
  process.env.AUDIO_FORK_ENDIAN = 'BE';
  try {
    assert.strictEqual(sesion()._detectEndian(audio(20, 0, 60)), 'BE');
  } finally {
    delete process.env.AUDIO_FORK_ENDIAN;
  }
});

test('auto acierta con LE y con BE, también con un trozo casi en silencio', function () {
  process.env.AUDIO_FORK_ENDIAN = 'auto';
  try {
    const le = audio(20, 3000, 60);
    const be = Buffer.from(le);
    be.swap16();
    assert.strictEqual(sesion()._detectEndian(le), 'LE');
    assert.strictEqual(sesion()._detectEndian(be), 'BE');
    const flojo = audio(20, 0, 60);
    assert.strictEqual(sesion()._detectEndian(flojo), 'LE');
  } finally {
    delete process.env.AUDIO_FORK_ENDIAN;
  }
});
