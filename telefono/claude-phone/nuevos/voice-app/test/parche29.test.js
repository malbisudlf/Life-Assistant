/**
 * Parche 29: si ElevenLabs se queda sin cuota (o cae), la frase la dice Azure.
 *
 * `axios` es un doble: se lanza con `node --test test/parche29.test.js`, dentro de la
 * imagen y sin red.
 */
'use strict';

const test = require('node:test');
const assert = require('node:assert');
const Module = require('node:module');
const os = require('node:os');
const fs = require('node:fs');
const path = require('node:path');
const { Readable, PassThrough } = require('node:stream');

for (const nivel of ['log', 'warn', 'error', 'info']) console[nivel] = function () {};

// ── Dobles ───────────────────────────────────────────────────────────────────
let pedidos = [];
let responder = null;
const axiosFalso = async function axios(opciones) {
  pedidos.push(opciones);
  const r = await responder(opciones);
  // En directo (parche 31) se pide un stream: un Buffer se entrega como uno de un trozo
  if (opciones.responseType === 'stream' && Buffer.isBuffer(r.data)) r.data = Readable.from([r.data]);
  return r;
};
axiosFalso.defaults = {};   // parche 34: tts-service le pone aquí su httpsAgent al cargarse
const requireDeVerdad = Module.prototype.require;
Module.prototype.require = function (id) {
  if (id === 'axios') return axiosFalso;
  return requireDeVerdad.apply(this, arguments);
};

const RUTA = require.resolve('../lib/tts-service');
const DIR = fs.mkdtempSync(path.join(os.tmpdir(), 'p29-'));
function servicio(entorno) {
  for (const k of ['ELEVENLABS_API_KEY', 'AZURE_SPEECH_KEY', 'AZURE_SPEECH_REGION', 'AZURE_SPEECH_VOICE',
                   'TTS_ORDEN', 'TTS_PAUSA_CUOTA_MS', 'TTS_PAUSA_MS', 'VOZ_URL', 'VOZ_TOKEN', 'VOZ_VOZ',
                   'TTS_EN_DIRECTO', 'TTS_PRIMER_BYTE_MS', 'FISH_AUDIO_API_KEY', 'FISH_AUDIO_VOICE']) delete process.env[k];
  // Los casos de los parches 29 y 30 son de voces enteras, a disco
  process.env.TTS_EN_DIRECTO = '';
  Object.assign(process.env, entorno);
  delete require.cache[RUTA];
  pedidos = [];
  const s = require('../lib/tts-service');
  s.setAudioDir(DIR);
  return s;
}

const AMBAS = { ELEVENLABS_API_KEY: 'sk_x', AZURE_SPEECH_KEY: 'az', AZURE_SPEECH_REGION: 'francecentral',
                AZURE_SPEECH_VOICE: 'es-ES-AlvaroNeural' };
const MP3 = Buffer.from('ID3fake-mp3');
function esEleven(o) { return o.url.indexOf('elevenlabs') !== -1; }
function sinCuota() {
  const e = new Error('Request failed with status code 401');
  e.response = { status: 401, data: Buffer.from('{"detail":{"status":"quota_exceeded"}}') };
  return e;
}

// ── Casos ────────────────────────────────────────────────────────────────────
test('con ElevenLabs bien, habla ElevenLabs y Azure no se toca', async function () {
  responder = async function () { return { data: MP3 }; };
  const s = servicio(AMBAS);
  const url = await s.generateSpeech('Buenos días, señor.', 'voz1');
  assert.match(url, /\/audio-files\/tts-\d+-[0-9a-f]{8}\.mp3$/);
  assert.strictEqual(pedidos.length, 1);
  assert.ok(esEleven(pedidos[0]));
  assert.ok(pedidos[0].timeout > 0, 'sin timeout una API colgada deja la llamada muda');
});

test('ElevenLabs sin cuota: la frase la dice Azure, y la siguiente ya no pregunta a ElevenLabs', async function () {
  responder = async function (o) { if (esEleven(o)) throw sinCuota(); return { data: MP3 }; };
  const s = servicio(AMBAS);
  const url = await s.generateSpeech('Hola', 'voz1');
  assert.match(url, /\.mp3$/);
  assert.deepStrictEqual(pedidos.map(esEleven), [true, false]);
  const fichero = path.join(DIR, url.split('/').pop());
  assert.deepStrictEqual(fs.readFileSync(fichero), MP3);

  pedidos = [];
  await s.generateSpeech('Otra frase', 'voz1');
  assert.deepStrictEqual(pedidos.map(esEleven), [false], 'apartada: no se paga su viaje en cada frase');
});

test('el SSML de Azure va escapado y con la voz configurada', async function () {
  responder = async function (o) { if (esEleven(o)) throw sinCuota(); return { data: MP3 }; };
  const s = servicio(AMBAS);
  await s.generateSpeech('5 < 6 & "Jarvis" <voice name="x">', 'voz1');
  const az = pedidos[1];
  assert.match(az.url, /^https:\/\/francecentral\.tts\.speech\.microsoft\.com\//);
  assert.strictEqual(az.headers['Ocp-Apim-Subscription-Key'], 'az');
  assert.match(az.data, /<voice name="es-ES-AlvaroNeural">/);
  assert.ok(az.data.indexOf('<voice name="x">') === -1, 'el texto no puede meter marcado');
  assert.match(az.data, /5 &lt; 6 &amp; &quot;Jarvis&quot;/);
});

test('si todas fallan, lanza (y las apartadas se prueban igual antes que callar)', async function () {
  responder = async function () { throw sinCuota(); };
  const s = servicio(AMBAS);
  await assert.rejects(s.generateSpeech('Hola', 'voz1'), /ninguna voz/);
  pedidos = [];
  await assert.rejects(s.generateSpeech('Hola', 'voz1'), /ninguna voz/);
  assert.strictEqual(pedidos.length, 2, 'apartadas, pero se intentan');
});

test('TTS_ORDEN manda, y una voz sin configurar se salta', async function () {
  responder = async function () { return { data: MP3 }; };
  let s = servicio(Object.assign({}, AMBAS, { TTS_ORDEN: 'azure,elevenlabs' }));
  await s.generateSpeech('Hola', 'voz1');
  assert.deepStrictEqual(pedidos.map(esEleven), [false]);

  s = servicio({ AZURE_SPEECH_KEY: 'az', AZURE_SPEECH_REGION: 'francecentral' });
  await s.generateSpeech('Hola', 'voz1');
  assert.deepStrictEqual(pedidos.map(esEleven), [false], 'sin llave de ElevenLabs, directa a Azure');
});

test('una caída (no la cuota) aparta poco: pasada la pausa vuelve a ElevenLabs', async function () {
  let caida = true;
  responder = async function (o) {
    if (esEleven(o) && caida) { const e = new Error('timeout of 8000ms exceeded'); throw e; }
    return { data: MP3 };
  };
  const s = servicio(Object.assign({}, AMBAS, { TTS_PAUSA_MS: '1' }));
  await s.generateSpeech('Hola', 'voz1');
  caida = false;
  await new Promise(function (r) { setTimeout(r, 5); });
  pedidos = [];
  await s.generateSpeech('Hola', 'voz1');
  assert.deepStrictEqual(pedidos.map(esEleven), [true]);
});

// ── Parche 30: la voz de jacobo ─────────────────────────────────────────────────
const CON_JACOBO = Object.assign({}, AMBAS, { VOZ_URL: 'http://jacobo:8772/', VOZ_TOKEN: 'llave',
                                              TTS_ORDEN: 'jacobo,azure,elevenlabs' });
const WAV = Buffer.from('RIFFfake-wav');
function esJacobo(o) { return o.url.indexOf('jacobo') !== -1; }

test('p30: con jacobo delante, habla jacobo en WAV y con su llave en cabecera', async function () {
  responder = async function (o) { return { data: esJacobo(o) ? WAV : MP3 }; };
  const s = servicio(Object.assign({}, CON_JACOBO, { VOZ_VOZ: 'piper:es_ES-davefx-medium' }));
  const url = await s.generateSpeech('Hola, señor.', 'voz1');
  assert.match(url, /\.wav$/);
  assert.strictEqual(pedidos.length, 1);
  assert.strictEqual(pedidos[0].url, 'http://jacobo:8772/decir');
  assert.strictEqual(pedidos[0].headers['X-Auth-Token'], 'llave');
  assert.strictEqual(pedidos[0].data.voz, 'piper:es_ES-davefx-medium');
  assert.ok(pedidos[0].url.indexOf('llave') === -1, 'la llave nunca en la URL');
  assert.ok(pedidos[0].timeout <= 3000);
  assert.deepStrictEqual(fs.readFileSync(path.join(DIR, url.split('/').pop())), WAV);
});

test('p30: si jacobo no contesta, la frase sigue por Azure en MP3', async function () {
  responder = async function (o) {
    if (esJacobo(o)) { const e = new Error('connect ECONNREFUSED'); throw e; }
    return { data: MP3 };
  };
  const s = servicio(CON_JACOBO);
  const url = await s.generateSpeech('Hola', 'voz1');
  assert.match(url, /\.mp3$/);
  assert.deepStrictEqual(pedidos.map(esJacobo), [true, false]);
});

test('p30: sin VOZ_TOKEN jacobo no cuenta como configurada', async function () {
  responder = async function () { return { data: MP3 }; };
  const s = servicio(Object.assign({}, CON_JACOBO, { VOZ_TOKEN: '' }));
  await s.generateSpeech('Hola', 'voz1');
  assert.deepStrictEqual(pedidos.map(esJacobo), [false]);
});

// ── Parche 31: Fish (y Azure) en directo ────────────────────────────────────────
const CON_FISH = Object.assign({}, AMBAS, { FISH_AUDIO_API_KEY: 'fk', FISH_AUDIO_VOICE: 'jarvis-id',
                                            TTS_ORDEN: 'fish,azure', TTS_EN_DIRECTO: 'fish,azure' });
function esFish(o) { return o.url.indexOf('fish.audio') !== -1; }

// Un `res` de express mínimo para servirEnDirecto
function resFalso() {
  const escrito = [];
  const r = new (require('node:events').EventEmitter)();
  r.cabeceras = {};
  r.acabado = false;
  r.setHeader = function (k, v) { r.cabeceras[k] = v; };
  r.status = function (c) { r.codigo = c; return r; };
  r.write = function (b) { escrito.push(Buffer.from(b)); };
  r.end = function () { r.acabado = true; r.emit('acabado'); };
  r.cuerpo = function () { return Buffer.concat(escrito); };
  return r;
}

test('p31: Fish en directo devuelve shout:// en cuanto llega el primer trozo, y sirve el resto según llega', async function () {
  const flujo = new PassThrough();
  responder = async function (o) { return { status: 200, data: flujo }; };
  const s = servicio(CON_FISH);
  setTimeout(function () { flujo.write(Buffer.from('ID3uno')); }, 5);
  const url = await s.generateSpeech('Buenos días, señor.', 'voz1');
  assert.match(url, /^shout:\/\/127\.0\.0\.1:\d+\/tts-stream\/[0-9a-f]{16}\.mp3$/);
  assert.strictEqual(pedidos.length, 1);
  assert.ok(esFish(pedidos[0]));
  assert.strictEqual(pedidos[0].responseType, 'stream');
  assert.strictEqual(pedidos[0].headers.Authorization, 'Bearer fk');
  assert.strictEqual(pedidos[0].data.reference_id, 'jarvis-id');
  assert.strictEqual(pedidos[0].data.text, 'Buenos días, señor.');

  const res = resFalso();
  s.servirEnDirecto({ params: { id: url.split('/').pop() } }, res);
  assert.strictEqual(res.cabeceras['Content-Type'], 'audio/mpeg');
  flujo.write(Buffer.from('dos'));
  flujo.end(Buffer.from('tres'));
  await new Promise(function (r) { res.once('acabado', r); });
  assert.strictEqual(res.cuerpo().toString(), 'ID3unodostres');

  // Ya acabado se puede volver a pedir entero
  const otra = resFalso();
  s.servirEnDirecto({ params: { id: url.split('/').pop() } }, otra);
  assert.ok(otra.acabado);
  assert.strictEqual(otra.cuerpo().toString(), 'ID3unodostres');
});

test('p31: un id que no existe es un 404', async function () {
  const s = servicio(CON_FISH);
  const res = resFalso();
  s.servirEnDirecto({ params: { id: 'nada.mp3' } }, res);
  assert.strictEqual(res.codigo, 404);
});

test('p31: si Fish no da audio a tiempo, la frase la dice Azure (también en directo, con <lang>)', async function () {
  responder = async function (o) {
    if (esFish(o)) return { status: 200, data: new PassThrough() };   // nunca llega nada
    return { status: 200, data: MP3 };
  };
  const s = servicio(Object.assign({}, CON_FISH, { TTS_PRIMER_BYTE_MS: '30',
                                                   AZURE_SPEECH_VOICE: 'en-GB-Ryan:DragonHDLatestNeural' }));
  const url = await s.generateSpeech('Hola', 'voz1');
  assert.match(url, /^shout:/);
  assert.deepStrictEqual(pedidos.map(esFish), [true, false]);
  assert.match(pedidos[1].data, /<voice name="en-GB-Ryan:DragonHDLatestNeural"><lang xml:lang="es-ES">Hola<\/lang>/);
});

test('p31: Fish sin cuota se aparta y la siguiente frase va directa a Azure', async function () {
  responder = async function (o) {
    if (esFish(o)) { const e = new Error('Request failed with status code 402'); e.response = { status: 402, data: new PassThrough() }; throw e; }
    return { status: 200, data: MP3 };
  };
  const s = servicio(CON_FISH);
  await s.generateSpeech('Hola', 'voz1');
  pedidos = [];
  await s.generateSpeech('Otra', 'voz1');
  assert.deepStrictEqual(pedidos.map(esFish), [false]);
});

test('p31: fuera de TTS_EN_DIRECTO, Fish se pide entero y se guarda en disco', async function () {
  responder = async function () { return { status: 200, data: MP3 }; };
  const s = servicio(Object.assign({}, CON_FISH, { TTS_EN_DIRECTO: '' }));
  const url = await s.generateSpeech('Hola', 'voz1');
  assert.match(url, /^http:\/\/.*\.mp3$/);
  assert.strictEqual(pedidos[0].responseType, 'arraybuffer');
  assert.deepStrictEqual(fs.readFileSync(path.join(DIR, url.split('/').pop())), MP3);
});

// ── Parche 34 ────────────────────────────────────────────────────────────────
test('p34: la conexión con las voces se reutiliza', function () {
  servicio(AMBAS);
  assert.strictEqual(axiosFalso.defaults.httpsAgent.keepAlive, true);
});

test('p34: la respuesta anticipada se sintetiza una vez, y solo sirve para esa frase', async function () {
  responder = async function () { return { data: MP3 }; };
  const s = servicio(AMBAS);
  s.anticipar('Ya está, señor.', 'voz1');
  const url = await s.generateSpeech('Ya está, señor.', 'voz1');
  assert.match(url, /\.mp3$/);
  assert.strictEqual(pedidos.length, 1);
  await s.generateSpeech('Ya está, señor.', 'voz1');
  assert.strictEqual(pedidos.length, 2, 'ya gastada, la siguiente se sintetiza');
});
