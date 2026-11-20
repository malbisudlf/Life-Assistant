/**
 * Parche 52: las llamadas a otras personas se graban (en estéreo), se sirven al backend con
 * llave y se borran solas a los 30 días. Grabar nunca puede tumbar ni retrasar la llamada.
 *
 * FreeSWITCH es un doble: `node --test test/parche52.test.js`, dentro de la imagen y sin red.
 */
'use strict';

const test = require('node:test');
const assert = require('node:assert');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const { EventEmitter } = require('node:events');

for (const nivel of ['log', 'warn', 'error', 'info']) console[nivel] = function () {};

const DIR = fs.mkdtempSync(path.join(os.tmpdir(), 'grab-'));
process.env.GRABACIONES_DIR = DIR;
process.env.TELEFONO_TERCEROS_TOKEN = 'llave';

const grabacion = require('../lib/grabacion');
const { runConversacionTercero } = require('../lib/conversacion-tercero');

const TID = '11111111-2222-3333-4444-555555555555';

function freeswitch(respuesta) {
  const ordenes = [];
  return {
    uuid: 'uuid-del-canal',
    ordenes,
    async set(k, v) { ordenes.push(['set', k, v]); },
    async api(cmd, args) {
      ordenes.push([cmd, args]);
      if (cmd === 'uuid_record' && respuesta) return respuesta(args);
      return { body: '+OK' };
    },
    async forkAudioStart() {}, async forkAudioStop() {}, async play() {}
  };
}

test('graba en estéreo con el id de la llamada y la para al acabar', async () => {
  const ep = freeswitch();
  const f = await grabacion.empezar(ep, TID);
  assert.strictEqual(f, path.join(DIR, TID + '.wav'));
  assert.deepStrictEqual(ep.ordenes[0], ['set', 'RECORD_STEREO', 'true']);
  assert.deepStrictEqual(ep.ordenes[1], ['uuid_record', 'uuid-del-canal start ' + f]);
  await grabacion.parar(ep, f);
  assert.deepStrictEqual(ep.ordenes[2], ['uuid_record', 'uuid-del-canal stop ' + f]);
});

test('un id que no es un UUID no llega a FreeSWITCH (va dentro de una orden)', async () => {
  const ep = freeswitch();
  assert.strictEqual(await grabacion.empezar(ep, '../../etc/passwd'), null);
  assert.strictEqual(await grabacion.empezar(ep, TID + ' stop /x'), null);
  assert.deepStrictEqual(ep.ordenes, []);
});

test('si FreeSWITCH dice que no, no se lanza nada', async () => {
  const ep = freeswitch(() => ({ body: '-ERR Cannot open file' }));
  assert.strictEqual(await grabacion.empezar(ep, TID), null);
});

test('GRABAR=0 lo apaga', async () => {
  process.env.GRABAR = '0';
  try {
    const ep = freeswitch();
    assert.strictEqual(await grabacion.empezar(ep, TID), null);
    assert.deepStrictEqual(ep.ordenes, []);
  } finally { delete process.env.GRABAR; }
});

test('las de más de 30 días se borran, las demás no', () => {
  const vieja = path.join(DIR, 'aaaaaaaa-2222-3333-4444-555555555555.wav');
  const nueva = path.join(DIR, 'bbbbbbbb-2222-3333-4444-555555555555.wav');
  fs.writeFileSync(vieja, 'x');
  fs.writeFileSync(nueva, 'x');
  const hace31 = (Date.now() - 31 * 86400000) / 1000;
  fs.utimesSync(vieja, hace31, hace31);
  assert.strictEqual(grabacion.limpiar(), 1);
  assert.ok(!fs.existsSync(vieja) && fs.existsSync(nueva));
  assert.deepStrictEqual(grabacion.listar().map((g) => g.id), ['bbbbbbbb-2222-3333-4444-555555555555']);
  fs.unlinkSync(nueva);
});

test('la conversación graba desde el principio y no espera a que la grabación arranque', async () => {
  const sesion = new EventEmitter();
  sesion.setCaptureEnabled = () => {};
  sesion.waitForUtterance = async () => { throw new Error('timeout'); };
  const sucesos = [];
  const lenta = {
    empezar: () => new Promise((r) => setTimeout(() => { sucesos.push('grabando'); r('/grabaciones/x.wav'); }, 200)),
    parar: async (ep, f) => { sucesos.push('parada ' + f); }
  };
  const ep = freeswitch();
  ep.play = async (url) => { sucesos.push('dice ' + url); };
  const r = await runConversacionTercero(ep, new EventEmitter(), 'c1', {
    audioForkServer: { expectSession: async () => sesion, cancelExpectation() {} },
    whisperClient: { transcribe: async () => '' },
    ttsService: { generateSpeech: async (t) => t },
    tercero: TID, apertura: 'Hola', guion: new Map(), guionListo: true,
    esperarSaludo: async () => null, grabacion: lenta, fetch: async () => ({ ok: true, json: async () => ({}) })
  });
  assert.ok(['silence', 'max_turns'].includes(r.endReason), r.endReason);
  assert.strictEqual(sucesos[0], 'dice Hola', 'la presentación no esperó a la grabación');
  assert.strictEqual(sucesos[sucesos.length - 1], 'parada /grabaciones/x.wav');
});

test('si grabar falla, la llamada sigue igual', async () => {
  const sesion = new EventEmitter();
  sesion.setCaptureEnabled = () => {};
  sesion.waitForUtterance = async () => { throw new Error('timeout'); };
  const ep = freeswitch(() => { throw new Error('ESL caído'); });
  const dichos = [];
  ep.play = async (u) => { dichos.push(u); };
  await runConversacionTercero(ep, new EventEmitter(), 'c1', {
    audioForkServer: { expectSession: async () => sesion, cancelExpectation() {} },
    whisperClient: { transcribe: async () => '' },
    ttsService: { generateSpeech: async (t) => t },
    tercero: TID, apertura: 'Hola', guion: new Map(), guionListo: true,
    esperarSaludo: async () => null, fetch: async () => ({ ok: true, json: async () => ({}) })
  });
  assert.strictEqual(dichos[0], 'Hola');
});

test('servir pide la llave y solo ids de verdad', async () => {
  const rutas = {};
  const app = { get(r, fn) { rutas[r] = fn; } };
  grabacion.montar(app);
  fs.writeFileSync(path.join(DIR, TID + '.wav'), 'RIFF');
  const res = () => {
    const r = { codigo: 200, cuerpo: null, cabeceras: {} };
    r.status = (c) => { r.codigo = c; return r; };
    r.json = (j) => { r.cuerpo = j; return r; };
    r.set = (k, v) => { r.cabeceras[k] = v; };
    r.type = (t) => { r.cabeceras.type = t; };
    return r;
  };
  const req = (llave, id) => ({ get: () => llave, params: { id } });
  let r = res();
  rutas['/api/grabacion/:id'](req('mala', TID), r);
  assert.strictEqual(r.codigo, 403);
  r = res();
  rutas['/api/grabacion/:id'](req('llave', '..%2F..%2Fetc'), r);
  assert.strictEqual(r.codigo, 404);
  r = res();
  rutas['/api/grabaciones'](req('llave'), r);
  assert.strictEqual(r.cuerpo.grabaciones[0].id, TID);
});
