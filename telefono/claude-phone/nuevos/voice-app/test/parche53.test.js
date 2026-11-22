/**
 * Parche 53: la llamada a tres. «Jarvis, ponme con Erik»: Jarvis llama por la línea O2 y
 * mete a Mikel y a Erik en una conferencia de FreeSWITCH, callado hasta que Mikel le
 * nombra. Todo con dobles: ni FreeSWITCH, ni línea, ni backend.
 *
 * Se lanza con `node --test test/parche53.test.js`, dentro de la imagen y sin red.
 */
'use strict';

const test = require('node:test');
const assert = require('node:assert');
const { EventEmitter } = require('node:events');
const Module = require('node:module');

const requireDeVerdad = Module.prototype.require;
Module.prototype.require = function (id) {
  if (id === 'ws') return { Server: function () {} };
  return requireDeVerdad.apply(this, arguments);
};
for (const nivel of ['log', 'warn', 'error']) console[nivel] = function () {};

const aTres = require('../lib/a-tres');
const { MusicaPasiva } = require('../lib/musica');
const { EscuchaPasiva } = require('../lib/escucha-pasiva');

const espera = (ms) => new Promise((r) => setTimeout(r, ms || 0));

function evento(cabeceras) {
  return { getHeader: (h) => cabeceras[h] };
}

/** Una conferencia de mentira: contesta a `conference <nombre> play` y avisa al acabar. */
function mundo(opciones) {
  const op = opciones || {};
  const m = { api: [], dicho: [], pedidos: [], colgados: [], soltada: 0, usada: 0, unidos: [] };
  m.conf = new EventEmitter();
  m.conf.name = 'a-tres-x';
  m.conf.destroy = async () => { m.confDestruida = true; };

  function apiDe(quien) {
    return async (cmd, args) => {
      m.api.push(quien + ': ' + cmd + ' ' + args);
      if (cmd === 'conference' && / play /.test(args)) {
        const url = args.split(' play ')[1];
        if (!/^tone_stream/.test(url)) setImmediate(() => m.conf.emit('playFileDone', evento({ File: url })));
        return { body: '+OK (play) Playing file ' + url };
      }
      return { body: '+OK' };
    };
  }

  m.endpoint = {
    uuid: 'uuid-mikel',
    api: apiDe('mikel'),
    play: async (url) => { m.dicho.push(url); },
    join: async () => { m.unidos.push('mikel'); return { memberId: 7 }; },
    on() {}, off() {}
  };
  m.salida = aTres.envolver(m.endpoint);

  m.dialogoB = new EventEmitter();
  m.dialogoB.destroy = async () => { m.colgados.push('erik'); };
  m.sesionB = new EventEmitter();
  m.frasesB = (op.frasesB || []).slice();
  m.sesionB.setCaptureEnabled = () => {};
  m.sesionB.waitForUtterance = async () => {
    await espera(5);
    if (m.frasesB.length) return { audio: Buffer.from(m.frasesB.shift()) };
    if (m.forkBParado) throw new Error('AudioForkSession closed');
    await espera(20);
    throw new Error('timeout');
  };
  m.endpointB = {
    uuid: 'uuid-erik',
    api: apiDe('erik'),
    join: async () => { m.unidos.push('erik'); return { memberId: 8 }; },
    forkAudioStart: async () => { m.forkB = true; },
    forkAudioStop: async () => { m.forkBParado = true; },
    destroy: async () => { m.endpointBDestruido = true; }
  };

  aTres.configurar({
    srf: () => ({}),
    mediaServer: () => ({ createConference: async (nombre, o) => { m.perfil = o.profile; return m.conf; } }),
    lineaO2: () => ({
      configurada: () => true,
      usar: async () => { m.usada++; },
      soltar: async () => { m.soltada++; }
    }),
    marcar: async (srf, ms, o) => {
      m.marcado = o;
      if (op.noContesta) throw new Error(op.noContesta);
      return { dialog: m.dialogoB, endpoint: m.endpointB };
    }
  });

  m.pasiva = new EscuchaPasiva({});
  m.c = {
    salida: m.salida, endpoint: m.endpoint, callUuid: 'llamada-1', voiceId: null, wsPort: 3001,
    ttsService: { generateSpeech: async (t) => 'voz:' + t },
    whisperClient: { transcribe: async (a) => a.toString() },
    audioForkServer: { expectSession: async () => m.sesionB, cancelExpectation() {} },
    pasiva: m.pasiva,
    sigueActiva: () => !m.mikelColgado,
    fetch: async (url, o) => {
      const cuerpo = JSON.parse(o.body);
      m.pedidos.push({ url, cuerpo, token: o.headers['X-Auth-Token'] });
      if (/\/fin$/.test(url)) return { ok: true, json: async () => ({ ok: true }) };
      return { ok: true, json: async () => (op.backend || {
        ok: true, tid: '11111111-2222-3333-4444-555555555555', nombre: 'Erik Pérez',
        pila: 'Erik', telefono: '+34600111222'
      }) };
    }
  };
  return m;
}

test('53: la marca de Claude', () => {
  assert.strictEqual(aTres.pideATres('🗣️ VOICE_RESPONSE: Le pongo con Erik, señor.\n📞 A TRES: Erik'), 'Erik');
  assert.strictEqual(aTres.pideATres('📞 A TRES: «Ama»'), 'Ama');
  assert.strictEqual(aTres.pideATres('📞 a tres:   Jon Ander  '), 'Jon Ander');
  assert.strictEqual(aTres.pideATres('🗣️ VOICE_RESPONSE: Le llamo yo.'), null);
  assert.strictEqual(aTres.pideATres('📞 A TRES: x'), null);
  assert.strictEqual(aTres.pideATres(''), null);
});

test('53: fuera de la conferencia, la salida es el endpoint tal cual', async () => {
  const m = mundo();
  await m.salida.play('http://a/b.mp3');
  await m.salida.api('uuid_break', 'uuid-mikel');
  assert.deepStrictEqual(m.dicho, ['http://a/b.mp3']);
  assert.deepStrictEqual(m.api, ['mikel: uuid_break uuid-mikel']);
  assert.strictEqual(m.salida.uuid, 'uuid-mikel');
  assert.strictEqual(m.salida.enConferencia, false);
});

test('53: dentro, suena para todos, espera a que acabe, la música de espera no entra y el corte para', async () => {
  const m = mundo();
  m.salida.entrar(m.conf);
  await m.salida.play('shout://127.0.0.1:3010/tts-stream/ab.mp3');
  await m.salida.play('http://127.0.0.1:3010/static/hold-music.wav');
  await m.salida.api('uuid_break', 'uuid-mikel');
  assert.deepStrictEqual(m.api, [
    'mikel: conference a-tres-x play shout://127.0.0.1:3010/tts-stream/ab.mp3',
    'mikel: conference a-tres-x stop all'
  ]);
  assert.deepStrictEqual(m.dicho, []);
  // Lo que suena cuando se sale de la conferencia deja de esperar.
  m.conf.removeAllListeners('playFileDone');
  m.conf.emit = () => true;
  const sonando = m.salida.play('http://x/larga.mp3');
  await espera(5);
  m.salida.salir();
  await sonando;
});

test('53: la música del modo coche no suena en la conferencia', async () => {
  process.env.MUSICA_URL = 'http://127.0.0.1:8095';
  const m = mundo();
  m.salida.entrar(m.conf);
  const musica = new MusicaPasiva(m.salida);
  assert.strictEqual(await musica.sonar(), false);
  assert.deepStrictEqual(m.api, []);
  delete process.env.MUSICA_URL;
});

test('53: si el backend no deja, lo dice y no marca', async () => {
  const m = mundo({ backend: { ok: false, frase: 'No le he oído pedirme que llame a Erik, señor.' } });
  const tres = await aTres.empezarSiLoPide('📞 A TRES: Erik', 'llama a mi madre', m.c);
  assert.strictEqual(tres, null);
  assert.strictEqual(m.marcado, undefined);
  assert.strictEqual(m.usada, 0);
  assert.deepStrictEqual(m.dicho, ['voz:No le he oído pedirme que llame a Erik, señor.']);
  assert.deepStrictEqual(m.pedidos[0].cuerpo, { nombre: 'Erik', dicho: 'llama a mi madre', call_id: 'llamada-1' });
});

test('53: un número que no es de España tampoco se marca, diga lo que diga el backend', async () => {
  const m = mundo({ backend: { ok: true, tid: 't', nombre: 'X', telefono: '+447700900000' } });
  assert.strictEqual(await aTres.empezarSiLoPide('📞 A TRES: X', 'ponme con X', m.c), null);
  assert.strictEqual(m.marcado, undefined);
});

test('53: descuelga, quedan en conferencia y Jarvis duerme oyendo solo a Mikel', async () => {
  const m = mundo({ frasesB: ['Hola, ¿qué tal?', 'Jarvis, abre la puerta del garaje'] });
  m.pasiva.activa = false;
  const tres = await aTres.empezarSiLoPide('📞 A TRES: Erik', 'Jarvis, ponme con Erik', m.c);
  assert.ok(tres && tres.activa);
  assert.strictEqual(m.perfil, 'sla');
  assert.deepStrictEqual(m.unidos, ['mikel', 'erik']);
  assert.strictEqual(m.marcado.to, '+34600111222');
  assert.strictEqual(m.usada, 1);
  assert.ok(m.api.some((a) => /play tone_stream/.test(a)), 'el tono mientras suena');
  assert.ok(m.api.some((a) => /energy all 0/.test(a)));
  assert.strictEqual(m.salida.enConferencia, true);
  assert.strictEqual(m.pasiva.activa, true);
  assert.strictEqual(m.pasiva.dormida(), true);
  assert.ok(/Llamada a tres con Erik/.test(tres.aviso()));

  // Lo de Erik se apunta para el resumen y para «apunta eso», pero no despierta a Jarvis.
  await espera(60);
  assert.deepStrictEqual(tres.turnos.map((t) => t.quien + ':' + t.texto),
    ['otro:Hola, ¿qué tal?', 'otro:Jarvis, abre la puerta del garaje']);
  assert.ok(/\(Erik\) Hola/.test(m.pasiva.loReciente()));
  m.pasiva.oyente('Vale, el jueves a las cinco');
  tres.anotar('jarvis', 'El jueves está libre, señor.');

  // Erik cuelga: Mikel sale de la conferencia (kick), se suelta la línea y se avisa.
  m.dialogoB.emit('destroy');
  await espera(20);
  assert.strictEqual(tres.activa, false);
  assert.ok(m.api.some((a) => a === 'mikel: conference a-tres-x kick 7'));
  assert.strictEqual(m.salida.enConferencia, false);
  assert.strictEqual(m.soltada, 1);
  assert.strictEqual(m.confDestruida, true);
  assert.deepStrictEqual(m.colgados, [], 'a Erik no se le cuelga: ya ha colgado él');
  assert.ok(m.dicho.includes('voz:Erik ha colgado, señor. Sigo a la escucha.'));
  const fin = m.pedidos.find((p) => /\/fin$/.test(p.url));
  assert.ok(/\/telefono\/a-tres\/11111111-2222-3333-4444-555555555555\/fin$/.test(fin.url));
  assert.strictEqual(fin.cuerpo.fin, 'colgada');
  assert.deepStrictEqual(fin.cuerpo.turnos.map((t) => t.quien),
    ['otro', 'otro', 'mikel', 'jarvis']);
  assert.strictEqual(m.pasiva.oyente, null);
});

test('53: «Jarvis, cuelga» cuelga a Erik y Mikel sigue con Jarvis', async () => {
  const m = mundo();
  const tres = await aTres.empezarSiLoPide('📞 A TRES: Erik', 'ponme con Erik', m.c);
  assert.strictEqual(await tres.orden('pues nada, ¿qué tal el día?'), false);
  assert.strictEqual(await tres.orden('cuélgale, Jarvis'), true);
  await espera(5);
  assert.deepStrictEqual(m.colgados, ['erik']);
  assert.strictEqual(tres.activa, false);
  assert.ok(m.dicho.includes('voz:Colgado, señor. Sigo a la escucha.'));
  assert.strictEqual(m.pedidos.find((p) => /\/fin$/.test(p.url)).cuerpo.fin, 'colgamos');
  // Cerrar dos veces (el BYE de Erik después, o el final de la conversación) no repite nada.
  m.dialogoB.emit('destroy');
  await tres.terminar();
  assert.strictEqual(m.pedidos.filter((p) => /\/fin$/.test(p.url)).length, 1);
  assert.strictEqual(m.soltada, 1);
});

test('53: «déjanos solos»: Jarvis se va, no se queda con nada y espera a que cuelguen', async () => {
  const m = mundo({ frasesB: ['algo que dijo antes'] });
  const tres = await aTres.empezarSiLoPide('📞 A TRES: Erik', 'ponme con Erik', m.c);
  await espera(30);
  assert.strictEqual(await tres.orden('Jarvis, déjanos solos'), true);
  assert.strictEqual(tres.privado, true);
  assert.strictEqual(m.forkBParado, true);
  assert.strictEqual(m.pasiva.loReciente(), '');
  let acabo = false;
  tres.esperarFin().then(() => { acabo = true; });
  await espera(5);
  assert.strictEqual(acabo, false);
  m.dialogoB.emit('destroy');
  await espera(20);
  assert.strictEqual(acabo, true);
  assert.deepStrictEqual(m.pedidos.find((p) => /\/fin$/.test(p.url)).cuerpo.turnos, []);
});

test('53: si no lo coge, Mikel sale de la conferencia y lo oye', async () => {
  const m = mundo({ noContesta: 'no_answer' });
  const tres = await aTres.empezarSiLoPide('📞 A TRES: Erik', 'ponme con Erik', m.c);
  assert.strictEqual(tres, null);
  assert.ok(m.api.includes('mikel: conference a-tres-x kick 7'));
  assert.strictEqual(m.salida.enConferencia, false);
  assert.strictEqual(m.soltada, 1);
  assert.ok(m.dicho.includes('voz:Erik no lo coge, señor.'));
  assert.strictEqual(m.pedidos.find((p) => /\/fin$/.test(p.url)).cuerpo.fin, 'sin_contestar:no_answer');
});

test('53: si comunica, lo dice', async () => {
  const m = mundo({ noContesta: 'busy' });
  assert.strictEqual(await aTres.empezarSiLoPide('📞 A TRES: Erik', 'ponme con Erik', m.c), null);
  assert.ok(m.dicho.includes('voz:Erik comunica, señor.'));
});

test('53: si Mikel cuelga mientras suena, se cuelga a Erik al descolgar', async () => {
  const m = mundo();
  m.mikelColgado = true;
  assert.strictEqual(await aTres.empezarSiLoPide('📞 A TRES: Erik', 'ponme con Erik', m.c), null);
  assert.deepStrictEqual(m.colgados, ['erik']);
  assert.strictEqual(m.soltada, 1);
  assert.deepStrictEqual(m.dicho, []);
});

test('53: con una ya en marcha no se abre otra', async () => {
  const m = mundo();
  m.salida.entrar(m.conf);
  assert.strictEqual(await aTres.empezarSiLoPide('📞 A TRES: Jon', 'ponme con Jon', m.c), null);
  assert.strictEqual(m.marcado, undefined);
});

test('53: qué es colgar y qué es dejarles solos', () => {
  for (const t of ['Jarvis, cuelga', 'cuélgale', 'córtale no, corta', 'Jarvis, termina la llamada', 'ya está con él, cuelga']) {
    assert.ok(aTres.RE_COLGAR.test(t), t);
  }
  for (const t of ['no cuelgues', 'el cuelgue', 'te cuento']) assert.ok(!aTres.RE_COLGAR.test(t), t);
  for (const t of ['Jarvis, déjanos solos', 'vete, Jarvis', 'Jarvis, adiós', 'déjanos hablar']) {
    assert.ok(aTres.RE_SOLOS.test(t), t);
  }
});

test('53: la escucha pasiva pasa a la llamada a tres lo que oye dormida', async () => {
  const p = new EscuchaPasiva({ activa: true });
  const oido = [];
  p.oyente = (t) => oido.push(t);
  let i = 0;
  const frases = ['el jueves me va bien', 'Jarvis, ¿tengo algo el jueves?'];
  const r = await p.esperarPalabra({
    session: { setCaptureEnabled() {}, waitForUtterance: async () => ({ audio: Buffer.from(frases[i++]) }) },
    whisperClient: { transcribe: async (a) => a.toString() }
  });
  assert.strictEqual(r.resto, 'tengo algo el jueves?');
  assert.deepStrictEqual(oido, frases);
});
