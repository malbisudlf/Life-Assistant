/**
 * Parche 50: el sí listo y la música en la escucha pasiva. Ver telefono/PARCHES.md en Life
 * Assistant. Sin red: el backend y el servicio de la música son dobles.
 */
'use strict';

const test = require('node:test');
const assert = require('node:assert');
for (const nivel of ['log', 'warn', 'error']) console[nivel] = function () {};

const { siONo, pareceSi, resolverConfirmacion } = require('../lib/confirmacion');

const PREGUNTA = '¿Llamo a Saioa?';

test('el sí listo: «sí, hazlo», «sí, dale» y los imperativos con pronombre', function () {
  for (const dicho of ['sí', 'Sí, hazlo', 'sí, dale', 'Dale caña', 'Por supuesto', 'claro que sí',
    'sí, sí, adelante', 'perfecto, hazlo', 'Llámala', 'sí, bórralas', 'quítalas todas',
    'mándaselo', 'Hazlo ya, por favor', 'Sí señor', 'venga, va', 'sí, ponlo']) {
    assert.strictEqual(siONo(dicho, PREGUNTA), 'si', dicho);
  }
});

test('el no también: «ni de coña», «cancélalo», «ahora no»', function () {
  for (const dicho of ['no', 'No, déjalo', 'mejor no', 'ni de coña', 'cancélalo', 'olvídalo',
    'no lo hagas', 'ahora no', 'que va']) {
    assert.strictEqual(siONo(dicho, PREGUNTA), 'no', dicho);
  }
});

test('lo que matiza, opina o dice otra cosa no decide nada', function () {
  for (const dicho of ['sí, pero a las once', 'espera', 'perfecto', 'eso es', 'correcto',
    'la pastilla', 'el regalo', 'sí no', 'llama a Erik mejor', '¿qué hora es?', '']) {
    assert.strictEqual(siONo(dicho, PREGUNTA), null, dicho);
  }
});

test('las palabras de la pregunta valen de relleno, las de otra no', function () {
  assert.strictEqual(siONo('sí, llama a Saioa', '¿Llamo a Saioa?'), 'si');
  assert.strictEqual(siONo('sí, llama a Saioa', '¿Llamo a Erik?'), null);
  assert.strictEqual(pareceSi('sí, llama a Saioa ahora audio', '¿Llamo a Saioa?'), true);
});

test('resolverConfirmacion usa la pregunta guardada', async function () {
  const dichas = [];
  const enviados = [];
  process.env.CONFIRMAR_TOKEN = 'conf';
  const c = {
    voiceId: 'v', endpoint: { play: async function () {}, api: async function () {} },
    session: { on: function () {}, removeListener: function () {} },
    ttsService: { generateSpeech: async function (t) { dichas.push(t); return 'http://x/a.wav'; } },
    fetchImpl: async function (url, opciones) {
      enviados.push(JSON.parse(opciones.body));
      return { ok: true, json: async function () { return { ok: true, frase: 'Hecho. Llamando a Saioa.' }; } };
    }
  };
  const r = await resolverConfirmacion({ id: 'x', frase: 'Llamar a Saioa: «…».', pregunta: PREGUNTA },
    'sí, llama a Saioa', c);
  assert.strictEqual(r.resuelta, true);
  assert.deepStrictEqual(enviados, [{ respuesta: 'si' }]);
  assert.deepStrictEqual(dichas, ['Hecho. Llamando a Saioa.']);
});

// ── La música debajo de la escucha pasiva ────────────────────────────────────
const Module = require('node:module');
const { EventEmitter } = require('node:events');
const requireDeVerdad = Module.prototype.require;
Module.prototype.require = function (id) {
  if (id === 'ws') return { Server: function () {} };
  return requireDeVerdad.apply(this, arguments);
};
const { MusicaPasiva, ruta } = require('../lib/musica');
const { runConversationLoop } = require('../lib/conversation-loop');

function endpointConApi(respuesta) {
  const ep = new EventEmitter();
  ep.uuid = 'ep-1';
  ep.hecho = [];
  ep.play = async function (url) { ep.hecho.push('play ' + url); };
  ep.api = async function (cmd, args) { ep.hecho.push('api ' + cmd + ' ' + (args || '')); return respuesta; };
  ep.forkAudioStart = async function () {};
  ep.forkAudioStop = async function () {};
  ep.destroy = async function () {};
  return ep;
}

function conMusica(url, fn) {
  return async function () {
    const antes = process.env.MUSICA_URL;
    if (url == null) delete process.env.MUSICA_URL; else process.env.MUSICA_URL = url;
    try { await fn(); } finally {
      if (antes == null) delete process.env.MUSICA_URL; else process.env.MUSICA_URL = antes;
    }
  };
}

test('50: la ruta de la música, de MUSICA_URL', conMusica('http://127.0.0.1:8095/', function () {
  assert.strictEqual(ruta(), 'shout://127.0.0.1:8095/musica.mp3');
}));

test('50: sin MUSICA_URL no se toca FreeSWITCH', conMusica(null, async function () {
  const ep = endpointConApi('+OK');
  const m = new MusicaPasiva(ep);
  assert.strictEqual(await m.sonar(), false);
  await m.callar();
  assert.deepStrictEqual(ep.hecho, []);
}));

test('50: suena mezclada hacia quien llama, y se calla una vez', conMusica('127.0.0.1:8095', async function () {
  const ep = endpointConApi('+OK Success');
  const m = new MusicaPasiva(ep);
  assert.strictEqual(await m.sonar(), true);
  assert.strictEqual(await m.sonar(), true);
  await m.callar();
  await m.callar();
  assert.deepStrictEqual(ep.hecho, [
    'api uuid_displace ep-1 start shout://127.0.0.1:8095/musica.mp3 0 mux',
    'api uuid_displace ep-1 stop shout://127.0.0.1:8095/musica.mp3'
  ]);
}));

test('50: si FreeSWITCH dice -ERR, no cuenta como sonando', conMusica('127.0.0.1:8095', async function () {
  const ep = endpointConApi('-ERR Cannot open file');
  const m = new MusicaPasiva(ep);
  assert.strictEqual(await m.sonar(), false);
  await m.callar();
  assert.strictEqual(ep.hecho.length, 1);
}));

test('50, saliente: la música suena dormido y se corta al oír «Jarvis»', conMusica('127.0.0.1:8095', async function () {
  const ep = endpointConApi('+OK');
  const tts = { generateSpeech: async function (t) { return 'tts:' + t; } };
  const momentos = [];
  const frases = ['charla con música', 'Jarvis, ¿qué tiempo hace?', null, 'Jarvis, cuelga'];
  let i = 0;
  const sesion = new EventEmitter();
  sesion.setCaptureEnabled = function () {};
  sesion.forceFinalize = function () {};
  sesion.armarBargeIn = function () {};
  sesion.waitForUtterance = async function () {
    // Lo que sonaba cuando se le escuchaba: lo último que se hizo con la música.
    const ultima = ep.hecho.filter(function (h) { return h.indexOf('uuid_displace') >= 0; }).pop() || '';
    momentos.push(ultima.indexOf(' start ') >= 0 ? 'con música' : 'sin música');
    if (i >= frases.length) throw new Error('AudioForkSession closed for call x');
    const f = frases[i++];
    if (f == null) throw new Error('Timed out waiting for utterance');
    return { audio: Buffer.from(f), reason: 'end_silence' };
  };
  const whisper = { transcribe: async function (a) { return a.toString(); } };
  const claude = { query: async function () { return '🗣️ VOICE_RESPONSE: Doce grados, señor.'; },
                   endSession: async function () {} };
  const r = await runConversationLoop(ep, new EventEmitter(), 'c-musica', {
    ttsService: tts, whisperClient: whisper, claudeBridge: claude, wsPort: 3001,
    audioForkServer: { expectSession: async function () { return sesion; },
                       cancelExpectation: function () {}, emit: function () {} },
    skipGreeting: true, escuchaPasiva: true
  });
  assert.strictEqual(r.endReason, 'goodbye');
  // Dormido (las dos primeras y la última), con música; despierto («qué tiempo hace» y
  // los 8 s de seguir hablando), sin ella.
  assert.deepStrictEqual(momentos.slice(0, 3), ['con música', 'con música', 'sin música']);
  const usos = ep.hecho.filter(function (h) { return h.indexOf('uuid_displace') >= 0; });
  assert.ok(usos.length >= 4, usos.join('\n'));
  assert.ok(usos[usos.length - 1].indexOf(' stop ') >= 0, 'al colgar, callada');
}));
