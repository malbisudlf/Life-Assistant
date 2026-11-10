/**
 * Parche 45: las llamadas a otras personas hablan con una voz española de Azure, no con la
 * de Jarvis. Ver telefono/PARCHES.md en Life Assistant.
 *
 * `axios` es un doble: se lanza con `node --test test/parche45.test.js`, dentro de la
 * imagen y sin red.
 */
'use strict';

const test = require('node:test');
const assert = require('node:assert');
const Module = require('node:module');
const os = require('node:os');
const fs = require('node:fs');
const path = require('node:path');
const { Readable } = require('node:stream');

for (const nivel of ['log', 'warn', 'error', 'info']) console[nivel] = function () {};

let pedidos = [];
let responder = null;
const axiosFalso = async function axios(opciones) {
  pedidos.push(opciones);
  const r = await responder(opciones);
  if (opciones.responseType === 'stream' && Buffer.isBuffer(r.data)) r.data = Readable.from([r.data]);
  return r;
};
axiosFalso.defaults = {};
const requireDeVerdad = Module.prototype.require;
Module.prototype.require = function (id) {
  if (id === 'axios') return axiosFalso;
  return requireDeVerdad.apply(this, arguments);
};

const RUTA = require.resolve('../lib/tts-service');
const DIR = fs.mkdtempSync(path.join(os.tmpdir(), 'p45-'));
function servicio(entorno) {
  for (const k of ['ELEVENLABS_API_KEY', 'AZURE_SPEECH_KEY', 'AZURE_SPEECH_REGION', 'AZURE_SPEECH_VOICE',
                   'TTS_ORDEN', 'TTS_PAUSA_CUOTA_MS', 'TTS_PAUSA_MS', 'VOZ_URL', 'VOZ_TOKEN', 'VOZ_VOZ',
                   'TTS_EN_DIRECTO', 'TTS_PRIMER_BYTE_MS', 'FISH_AUDIO_API_KEY', 'FISH_AUDIO_VOICE']) delete process.env[k];
  process.env.TTS_EN_DIRECTO = '';
  Object.assign(process.env, entorno);
  delete require.cache[RUTA];
  pedidos = [];
  const s = require('../lib/tts-service');
  s.setAudioDir(DIR);
  return s;
}

// Como corre en caja: Fish (Jarvis) delante y la británica de Azure detrás.
const CASA = { FISH_AUDIO_API_KEY: 'fk', FISH_AUDIO_VOICE: 'jarvis-id', AZURE_SPEECH_KEY: 'az',
               AZURE_SPEECH_REGION: 'francecentral', AZURE_SPEECH_VOICE: 'en-GB-Ryan:DragonHDLatestNeural',
               TTS_ORDEN: 'fish,azure' };
const TRISTAN = 'azure:es-ES-Tristan:DragonHDLatestNeural';
const MP3 = Buffer.from('ID3fake-mp3');
function esFish(o) { return o.url.indexOf('fish.audio') !== -1; }
function esAzure(o) { return o.url.indexOf('tts.speech.microsoft.com') !== -1; }

test('45: sin voz pedida, todo como siempre (habla Fish, la de Jarvis)', async function () {
  responder = async function () { return { data: MP3 }; };
  const s = servicio(CASA);
  await s.generateSpeech('Buenos días, señor.', 'voz-del-dispositivo');
  assert.deepStrictEqual(pedidos.map(esFish), [true]);
});

test('45: con la voz pedida habla Azure con ESA voz, y Fish ni se toca', async function () {
  responder = async function () { return { data: MP3 }; };
  const s = servicio(CASA);
  const url = await s.generateSpeech('Hola, buenas tardes.', TRISTAN);
  assert.match(url, /\.mp3$/);
  assert.strictEqual(pedidos.length, 1);
  assert.ok(esAzure(pedidos[0]));
  assert.match(pedidos[0].data, /<voice name="es-ES-Tristan:DragonHDLatestNeural">/);
  assert.ok(pedidos[0].data.indexOf('en-GB-Ryan') === -1, 'no la británica de Jarvis');
});

test('45: en directo también va con la voz pedida', async function () {
  responder = async function () { return { data: MP3 }; };
  const s = servicio(Object.assign({}, CASA, { TTS_EN_DIRECTO: 'fish,azure' }));
  const url = await s.generateSpeech('Hola.', TRISTAN);
  assert.match(url, /^shout:\/\/.*\/tts-stream\/[0-9a-f]+\.mp3$/);
  assert.strictEqual(pedidos[0].responseType, 'stream');
  assert.match(pedidos[0].data, /<voice name="es-ES-Tristan:DragonHDLatestNeural">/);
});

test('45: si Azure falla, la frase sale con la de siempre antes que quedarse mudo', async function () {
  responder = async function (o) { if (esAzure(o)) throw new Error('503'); return { data: MP3 }; };
  const s = servicio(CASA);
  const url = await s.generateSpeech('Hola.', TRISTAN);
  assert.match(url, /\.mp3$/);
  assert.deepStrictEqual(pedidos.map(esAzure), [true, false]);
});

test('45: una frase anticipada con la voz de Jarvis no se cuela en la llamada a otro', async function () {
  responder = async function () { return { data: MP3 }; };
  const s = servicio(CASA);
  s.anticipar('Un momento.', 'voz-del-dispositivo');     // Jarvis, hablando con Mikel
  s.anticipar('Un momento.', TRISTAN);                    // no se anticipa nada con voz pedida
  await new Promise(function (r) { setImmediate(r); });
  assert.deepStrictEqual(pedidos.map(esFish), [true]);
  await s.generateSpeech('Un momento.', TRISTAN);
  assert.ok(esAzure(pedidos[1]), 'la llamada a otro la pide a Azure, no reutiliza la de Fish');
  assert.match(pedidos[1].data, /es-ES-Tristan/);
});

test('45: solo vale «azure:<voz>»: lo demás es la voz del dispositivo, como siempre', function () {
  const s = servicio(CASA);
  assert.strictEqual(s.vozPedida(TRISTAN), 'es-ES-Tristan:DragonHDLatestNeural');
  for (const mala of [null, undefined, '', 'default', 'es-ES-Tristan', 'azure:', 'azure:x"><break/>', 'fish:abc', 42]) {
    assert.strictEqual(s.vozPedida(mala), null);
  }
});

test('45: la ruta solo acepta `voz` en una llamada a terceros y con esa forma', function () {
  const { validateRequest } = require('../lib/outbound-routes');
  const base = { to: '+34600000000', message: 'Hola', mode: 'tercero', linea: 'o2',
                 tercero: '0b6f7a52-2f5c-4b7e-9a51-6c2d1e0f9a11' };
  assert.strictEqual(validateRequest(base).valid, true);
  assert.strictEqual(validateRequest(Object.assign({}, base, { voz: TRISTAN })).valid, true);
  assert.strictEqual(validateRequest(Object.assign({}, base, { voz: 'azure:x"><break/>' })).valid, false);
  assert.strictEqual(validateRequest(Object.assign({}, base, { voz: 'jarvis' })).valid, false);
  assert.strictEqual(validateRequest({ to: '11411', message: 'Hola', mode: 'announce', voz: TRISTAN }).valid, false);
});
