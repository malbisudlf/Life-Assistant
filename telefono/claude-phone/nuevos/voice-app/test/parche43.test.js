/**
 * Parche 43: en las llamadas a otros, Jarvis se prepara antes de marcar y habla antes al
 * descolgar. Y sigue sin barge-in (parche 35).
 *
 * La voz, el oído y el backend son dobles: `node --test test/parche43.test.js`, dentro de la
 * imagen y sin red.
 */
'use strict';

const test = require('node:test');
const assert = require('node:assert');
const { EventEmitter } = require('node:events');

for (const nivel of ['log', 'warn', 'error', 'info']) console[nivel] = function () {};

const { runConversacionTercero, prepararLlamada, esperarSaludo } = require('../lib/conversacion-tercero');

const TID = '11111111-2222-3333-4444-555555555555';
const APERTURA = 'Hola, Erik. Soy Jarvis, el asistente de Mikel. ¿Comes hoy con él?';

function dormir(ms) { return new Promise((r) => setTimeout(r, ms)); }

/** Una voz falsa: la URL llega enseguida y el audio entero, `enteraMs` después. */
function vozFalsa(enteraMs) {
  const acabadas = new Set();
  const pedidas = [];
  return {
    pedidas,
    acabadas,
    generateSpeech: async (t) => {
      pedidas.push(t);
      const url = 'tts:' + t;
      setTimeout(() => acabadas.add(url), enteraMs);
      return url;
    },
    esperarAcabada: async (url, maxMs) => {
      const hasta = Date.now() + maxMs;
      while (!acabadas.has(url) && Date.now() < hasta) await dormir(5);
      return acabadas.has(url);
    }
  };
}

/** El backend del guion: `listoTras` peticiones sin guion y luego el guion entero. */
function backendGuion(frases, listoTras) {
  let veces = 0;
  const fn = async (url) => {
    assert.ok(url.endsWith('/telefono/tercero/' + TID + '/guion'), url);
    veces++;
    if (veces <= listoTras) return { ok: true, status: 200, json: async () => ({ frases: [], listo: false }) };
    return { ok: true, status: 200, json: async () => ({ frases, listo: true }) };
  };
  fn.veces = () => veces;
  return fn;
}

// ── Antes de marcar ──────────────────────────────────────────────────────────
test('no vuelve hasta tener la presentación entera y el guion con su voz', async () => {
  const voz = vozFalsa(80);
  const fetch = backendGuion(['Perfecto, se lo digo.', 'Vale, gracias.'], 2);
  const t0 = Date.now();
  const p = await prepararLlamada({ tercero: TID, apertura: APERTURA, ttsService: voz, fetch, guionSondeoMs: 10 });
  const ms = Date.now() - t0;
  assert.strictEqual(await p.aperturaUrl, 'tts:' + APERTURA);
  assert.ok(voz.acabadas.has('tts:' + APERTURA), 'la presentación no estaba entera');
  assert.strictEqual(p.guionListo, true);
  assert.deepStrictEqual(Array.from(p.guion.keys()), ['Perfecto, se lo digo.', 'Vale, gracias.']);
  for (const f of p.guion.keys()) assert.ok(voz.acabadas.has('tts:' + f), 'sin terminar: ' + f);
  assert.strictEqual(fetch.veces(), 3);
  assert.ok(ms >= 80, 'volvió antes de tener la voz: ' + ms + ' ms');
});

test('si el backend no tiene el guion a tiempo, marca igual al tope y con la presentación', async () => {
  const voz = vozFalsa(10);
  const t0 = Date.now();
  const p = await prepararLlamada({ tercero: TID, apertura: APERTURA, ttsService: voz,
                                    fetch: backendGuion([], 1e9), guionSondeoMs: 10, prepararTopeMs: 200 });
  const ms = Date.now() - t0;
  assert.ok(ms >= 190 && ms < 600, 'tardó ' + ms + ' ms');
  assert.strictEqual(p.guionListo, false);
  assert.strictEqual(await p.aperturaUrl, 'tts:' + APERTURA);
});

test('si la voz falla, no lanza: la presentación queda en null y se pedirá al descolgar', async () => {
  const p = await prepararLlamada({
    tercero: TID, apertura: APERTURA, prepararTopeMs: 300,
    ttsService: { generateSpeech: async () => { throw new Error('sin voz'); } },
    fetch: backendGuion([], 0)
  });
  assert.strictEqual(await p.aperturaUrl, null);
  assert.strictEqual(p.guionListo, true);
});

test('sin esperarAcabada (voz que escribe ficheros), vale con tener la URL', async () => {
  const p = await prepararLlamada({ tercero: TID, apertura: APERTURA, prepararTopeMs: 300,
                                    ttsService: { generateSpeech: async (t) => 'http:' + t },
                                    fetch: backendGuion(['Vale.'], 0) });
  assert.strictEqual(await p.aperturaUrl, 'http:' + APERTURA);
  assert.strictEqual(await p.guion.get('Vale.'), 'http:Vale.');
});

// ── Al descolgar ─────────────────────────────────────────────────────────────
function escena(oido, backend) {
  const dichos = [];
  const sesion = new EventEmitter();
  const cola = oido.slice();
  sesion.setCaptureEnabled = () => {};
  sesion.waitForUtterance = async () => {
    const t = cola.length ? cola.shift() : null;
    if (t === null) throw new Error('timeout');
    return { audio: Buffer.from(t) };
  };
  const pedidosGuion = [];
  const o = {
    audioForkServer: { expectSession: async () => sesion, cancelExpectation() {} },
    whisperClient: { transcribe: async (audio) => audio.toString() },
    ttsService: { generateSpeech: async (t) => 'tts:' + t },
    wsPort: 3001,
    tercero: TID,
    apertura: APERTURA,
    esperarSaludo: async () => null,
    fetch: async (url) => {
      if (url.endsWith('/guion')) {
        pedidosGuion.push(url);
        return { ok: true, status: 200, json: async () => ({ frases: [], listo: true }) };
      }
      const r = backend.shift();
      return { ok: true, status: 200, json: async () => r };
    }
  };
  const endpoint = { async forkAudioStart() {}, async forkAudioStop() {},
                     async play(url) { dichos.push(url.replace('tts:', '')); } };
  return { o, endpoint, dialog: new EventEmitter(), dichos, pedidosGuion, sesion };
}

test('con el guion ya preparado, no se vuelve a pedir al descolgar y suena su voz', async () => {
  const e = escena(['A las dos'], [{ decir: 'Perfecto, se lo digo.', colgar: true }]);
  e.o.guion = new Map([['Perfecto, se lo digo.', Promise.resolve('tts:PREPARADA')]]);
  e.o.guionListo = true;
  e.o.aperturaUrl = Promise.resolve('tts:APERTURA PREPARADA');
  const r = await runConversacionTercero(e.endpoint, e.dialog, 'c1', e.o);
  assert.strictEqual(r.endReason, 'goodbye');
  assert.deepStrictEqual(e.pedidosGuion, []);
  assert.deepStrictEqual(e.dichos, ['APERTURA PREPARADA', 'PREPARADA']);
});

test('si el guion no llegó antes de marcar, se sigue pidiendo durante la llamada', async () => {
  const e = escena(['A las dos'], [{ decir: 'Vale.', colgar: true }]);
  e.o.guion = new Map();
  e.o.guionListo = false;
  await runConversacionTercero(e.endpoint, e.dialog, 'c1', e.o);
  assert.ok(e.pedidosGuion.length >= 1);
});

test('un «¿Quién?» corto con silencio delante no se toma por buzón: se presenta sin esperar al oído', async () => {
  // La llamada del 2026-11-08 a las 19:41: 3,3 s de audio, 1,4 s de voz.
  const e = escena([], []);
  e.o.esperarSaludo = async () => ({ audio: Buffer.alloc(105600), speechMs: 1400 });
  let transcribiendo = 0;
  e.o.whisperClient = { transcribe: async () => { transcribiendo++; await dormir(800); return '¿Quién?'; } };
  let alPresentarse = null;
  const t0 = Date.now();
  e.endpoint.play = async (url) => { if (alPresentarse === null) alPresentarse = Date.now() - t0; e.dichos.push(url); };
  await runConversacionTercero(e.endpoint, e.dialog, 'c1', e.o);
  assert.ok(transcribiendo >= 1, 'el saludo se transcribe igual, de fondo');
  assert.ok(alPresentarse !== null && alPresentarse < 300, 'se presentó a los ' + alPresentarse + ' ms');
});

test('un saludo largo de verdad (mucha voz) sí se mira antes por si es un buzón', async () => {
  const e = escena([], []);
  e.o.esperarSaludo = async () => ({ audio: Buffer.alloc(105600), speechMs: 2600 });
  e.o.whisperClient = { transcribe: async () => { await dormir(150); return 'Deje su mensaje después de la señal'; } };
  let pitido = false;
  e.o.esperarSilencio = async () => { pitido = true; };
  const r = await runConversacionTercero(e.endpoint, e.dialog, 'c1', e.o);
  assert.ok(pitido);
  assert.strictEqual(r.endReason, 'voicemail');
});

test('saludo: lo que devuelve el detector lleva la voz que hubo, no solo el audio', async () => {
  const s = new EventEmitter();
  s._inSpeech = false; s._silenceMs = 0; s._utteranceChunks = []; s._speechBytes = 0;
  setTimeout(() => {
    s._inSpeech = true;
    s._utteranceChunks = [Buffer.alloc(64000)];   // 2 s de audio
    s._speechBytes = 16000;                       // medio segundo de voz
  }, 50);
  setTimeout(() => { s._silenceMs = 400; }, 150);
  const u = await esperarSaludo(s);
  assert.strictEqual(u.speechMs, 500);
  assert.strictEqual(u.audio.length, 64000);
});

// ── Sin barge-in (parche 35), comprobado otra vez ────────────────────────────
test('Jarvis no se deja cortar: cada frase suena entera con el oído cerrado', async () => {
  const e = escena(['Sí', 'Vale'], [{ decir: '¿A qué hora?' }, { decir: 'Hecho. ¡Adiós!', colgar: true }]);
  let captura = false;
  let armados = 0;
  const alHablar = [];
  const original = e.o.audioForkServer.expectSession;
  e.o.audioForkServer.expectSession = async () => {
    const s = await original();
    s.setCaptureEnabled = (v) => { captura = v; };
    s.armarBargeIn = () => { armados++; };
    return s;
  };
  e.endpoint.play = async (url) => { alHablar.push(captura); e.dichos.push(url); };
  await runConversacionTercero(e.endpoint, e.dialog, 'c1', e.o);
  assert.strictEqual(armados, 0);
  assert.strictEqual(alHablar.length, 3);
  assert.ok(alHablar.every((abierto) => abierto === false), JSON.stringify(alHablar));
});

// ── La voz: esperar a que una frase en directo haya llegado entera ───────────
test('esperarAcabada: un fichero ya escrito no se espera; un directo que no existe, no vale', async () => {
  const tts = require('../lib/tts-service');
  assert.strictEqual(await tts.esperarAcabada('http://127.0.0.1:3000/audio-files/x.mp3', 50), true);
  assert.strictEqual(await tts.esperarAcabada(null, 50), false);
  assert.strictEqual(await tts.esperarAcabada('shout://127.0.0.1:3000/tts-stream/0123456789abcdef.mp3', 50), false);
});
