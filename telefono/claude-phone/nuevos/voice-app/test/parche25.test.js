/**
 * Parche 25: el STT va primero al oído de jacobo y, si falla, a OpenAI.
 * Parche 34: el sondeo de /salud y la carrera contra OpenAI.
 *
 * `fetch` y `openai` son dobles: se lanza con `node --test test/parche25.test.js`,
 * dentro de la imagen y sin red.
 */
'use strict';

const test = require('node:test');
const assert = require('node:assert');
const Module = require('node:module');

for (const nivel of ['log', 'warn', 'error']) console[nivel] = function () {};

// ── Dobles ───────────────────────────────────────────────────────────────────
const openaiPedidos = [];
const requireDeVerdad = Module.prototype.require;
Module.prototype.require = function (id) {
  if (id === 'openai') {
    return function OpenAI() {
      this.audio = { transcriptions: { create: async function (p) {
        openaiPedidos.push(p);
        p.file.on('error', function () {}); // el de verdad lo lee; aquí se abre ya borrado
        return 'de openai\n';
      } } };
    };
  }
  return requireDeVerdad.apply(this, arguments);
};

// Parche 34: whisper-client sondea /salud al cargarse y cada OIDO_SONDEO_MS. Eso va por
// `salud`, sin contar en fetchPedidos, que son las transcripciones.
let fetchPedidos = [];
const saludBien = async function () { return { status: 200 }; };
const saludCaida = async function () { const e = new Error('fetch failed'); e.cause = { code: 'ECONNREFUSED' }; throw e; };
function fetchQue(responde, salud) {
  fetchPedidos = [];
  global.fetch = async function (url, opciones) {
    if (url.endsWith('/salud')) return (salud || saludBien)(url, opciones);
    fetchPedidos.push({ url: url, opciones: opciones });
    return responde(url, opciones);
  };
}

const RUTA = require.resolve('../lib/whisper-client');
function cliente(entorno) {
  for (const k of ['OIDO', 'OIDO_URL', 'OIDO_TOKEN', 'OIDO_PAUSA_MS', 'OIDO_CARRERA_MS', 'OIDO_SONDEO_MS', 'OPENAI_API_KEY']) delete process.env[k];
  Object.assign(process.env, entorno);
  delete require.cache[RUTA];
  openaiPedidos.length = 0;
  return require('../lib/whisper-client');
}

const PCM = Buffer.alloc(16000 * 2); // 0,5 s de silencio a 16 kHz
const CON_OIDO = { OIDO_URL: 'http://jacobo:8770/', OIDO_TOKEN: 'llave', OPENAI_API_KEY: 'sk-x' };
const bien = async function () {
  return { ok: true, status: 200, json: async function () { return { texto: 'Jarvis, ¿qué tengo hoy?', ms: 900 }; } };
};

// ── Casos ────────────────────────────────────────────────────────────────────
test('con el oído configurado, transcribe jacobo y OpenAI no se toca', async function () {
  fetchQue(bien);
  const w = cliente(CON_OIDO);
  const texto = await w.transcribe(PCM, { format: 'pcm', sampleRate: 16000, language: 'es', prompt: 'Jarvis.' });
  assert.strictEqual(texto, 'Jarvis, ¿qué tengo hoy?');
  assert.strictEqual(openaiPedidos.length, 0);
  assert.strictEqual(fetchPedidos.length, 1);
  const p = fetchPedidos[0];
  assert.strictEqual(p.url, 'http://jacobo:8770/transcribir');
  assert.strictEqual(p.opciones.headers['X-Auth-Token'], 'llave');
  assert.strictEqual(p.opciones.headers['X-Idioma'], 'es');
  assert.strictEqual(p.opciones.body.subarray(0, 4).toString(), 'RIFF');
  assert.ok(p.opciones.signal, 'lleva tiempo máximo');
});

test('si el oído contesta con error, la misma frase va a OpenAI', async function () {
  fetchQue(async function () { return { ok: false, status: 503, json: async function () { return {}; } }; });
  const w = cliente(CON_OIDO);
  assert.strictEqual(await w.transcribe(PCM, { sampleRate: 16000, prompt: 'Jarvis.' }), 'de openai\n');
  assert.strictEqual(openaiPedidos.length, 1);
  assert.strictEqual(openaiPedidos[0].prompt, 'Jarvis.');
});

// Con jacobo apagado también falla el sondeo. Si /salud contesta y solo falla /transcribir,
// el sondeo siguiente lo devuelve antes de tiempo: ver «El parche 34» en PARCHES.md.
test('tras un fallo, el oído se salta durante la pausa', async function () {
  fetchQue(async function () { const e = new Error('fetch failed'); e.cause = { code: 'ECONNREFUSED' }; throw e; }, saludCaida);
  const w = cliente(CON_OIDO);
  await w.transcribe(PCM);
  await w.transcribe(PCM);
  assert.strictEqual(fetchPedidos.length, 1, 'solo se le pregunta una vez');
  assert.strictEqual(openaiPedidos.length, 2);
});

test('pasada la pausa, se le vuelve a preguntar al oído', async function () {
  let primera = true;
  fetchQue(async function () {
    if (primera) { primera = false; const e = new Error('timeout'); e.name = 'TimeoutError'; throw e; }
    return bien();
  });
  const w = cliente(Object.assign({ OIDO_PAUSA_MS: '0' }, CON_OIDO));
  assert.strictEqual(await w.transcribe(PCM), 'de openai\n');
  assert.strictEqual(await w.transcribe(PCM), 'Jarvis, ¿qué tengo hoy?');
  assert.strictEqual(fetchPedidos.length, 2);
});

test('el silencio del oído es un texto vacío, no un fallo', async function () {
  fetchQue(async function () { return { ok: true, status: 200, json: async function () { return { texto: '', ms: 300 }; } }; });
  const w = cliente(CON_OIDO);
  assert.strictEqual(await w.transcribe(PCM), '');
  assert.strictEqual(openaiPedidos.length, 0);
});

test('sin OIDO_URL, o con OIDO=0, va directo a OpenAI', async function () {
  fetchQue(bien);
  let w = cliente({ OPENAI_API_KEY: 'sk-x' });
  assert.strictEqual(await w.transcribe(PCM), 'de openai\n');
  w = cliente(Object.assign({ OIDO: '0' }, CON_OIDO));
  assert.strictEqual(await w.transcribe(PCM), 'de openai\n');
  assert.strictEqual(fetchPedidos.length, 0);
});

test('isAvailable vale con cualquiera de los dos', function () {
  assert.strictEqual(cliente({}).isAvailable(), false);
  assert.strictEqual(cliente({ OIDO_URL: 'http://jacobo:8770', OIDO_TOKEN: 'llave' }).isAvailable(), true);
  assert.strictEqual(cliente({ OPENAI_API_KEY: 'sk-x' }).isAvailable(), true);
});

// ── Parche 34 ────────────────────────────────────────────────────────────────
test('p34: si el oído tarda más que OIDO_CARRERA_MS, sale OpenAI a la vez y gana', async function () {
  fetchQue(function () { return new Promise(function () {}); });
  const w = cliente(Object.assign({ OIDO_CARRERA_MS: '5' }, CON_OIDO));
  assert.strictEqual(await w.transcribe(PCM, { sampleRate: 16000 }), 'de openai\n');
  assert.strictEqual(fetchPedidos.length, 1);
  assert.strictEqual(openaiPedidos.length, 1);
  assert.strictEqual(openaiPedidos[0].model, 'gpt-4o-transcribe');
});

test('p34: lo que devuelve la pista tal cual es silencio', async function () {
  fetchQue(async function () {
    return { ok: true, status: 200, json: async function () { return { texto: 'Netflix, YouTube, Prime Video', ms: 300 }; } };
  });
  const w = cliente(CON_OIDO);
  assert.strictEqual(await w.transcribe(PCM), '');
});

// Estos dos dejan un sondeo corriendo cada 20 ms hasta el final del fichero: van los últimos.
const pasan = function (ms) { return new Promise(function (r) { setTimeout(r, ms); }); };

test('p34: dos sondeos fallidos lo apartan sin gastar un turno, y uno bueno lo devuelve', async function () {
  let salud = saludCaida;
  fetchQue(bien, function () { return salud(); });
  const w = cliente(Object.assign({ OIDO_SONDEO_MS: '20' }, CON_OIDO));
  await pasan(50);
  assert.strictEqual(w.oidoDisponible(), false);
  assert.strictEqual(await w.transcribe(PCM), 'de openai\n');
  assert.strictEqual(fetchPedidos.length, 0, 'ya se sabía: no se le pregunta');
  salud = saludBien;
  await pasan(50);
  assert.strictEqual(w.oidoDisponible(), true);
});

test('p34: un 401 en /salud cuenta como que está, y un 500 como que no', async function () {
  fetchQue(bien, async function () { return { status: 401 }; });
  let w = cliente(Object.assign({ OIDO_SONDEO_MS: '20' }, CON_OIDO));
  await pasan(50);
  assert.strictEqual(w.oidoDisponible(), true);
  fetchQue(bien, async function () { return { status: 500 }; });
  w = cliente(Object.assign({ OIDO_SONDEO_MS: '20' }, CON_OIDO));
  await pasan(50);
  assert.strictEqual(w.oidoDisponible(), false);
});
