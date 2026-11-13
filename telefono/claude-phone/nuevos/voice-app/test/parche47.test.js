/**
 * Parche 47: «Jarvis, apunta eso». La escucha pasiva recuerda en memoria lo oído en el
 * último minuto y medio y, si se lo piden, lo manda al backend sin pasar por Claude.
 *
 * Se lanza con `node --test test/parche47.test.js`, dentro de la imagen y sin red.
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
for (const nivel of ['log', 'warn', 'error']) console[nivel] = function () {};

const { EscuchaPasiva, antesDelNombre } = require('../lib/escucha-pasiva');
const apunte = require('../lib/apunte');

function sesionFalsa(frases) {
  let i = 0;
  return {
    setCaptureEnabled: function () {},
    waitForUtterance: async function () {
      if (i >= frases.length) throw new Error('AudioForkSession closed for call x');
      return { audio: Buffer.from(frases[i++]), reason: 'end_silence' };
    }
  };
}

function whisperFalso() {
  return { transcribe: async function (a) { return a.toString(); } };
}

function contexto(pasiva, respuesta) {
  const c = { pasiva: pasiva, dicho: [], pedidos: [], registro: [] };
  c.endpoint = { play: async function (url) { c.dicho.push(url); } };
  c.ttsService = { generateSpeech: async function (t) { return t; } };
  c.log = function (m) { c.registro.push(m); };
  c.fetch = async function (url, o) {
    c.pedidos.push({ url: url, cuerpo: JSON.parse(o.body), auth: o.headers.Authorization });
    if (respuesta === 'caido') throw new Error('ECONNREFUSED');
    return { ok: true, json: async function () { return respuesta || { ok: true }; } };
  };
  return c;
}

test('47: qué es «apunta eso» y qué es una nota que toma Claude', function () {
  for (const t of ['Apunta eso.', 'Jarvis, apunta eso', 'apúntame eso, por favor', 'Anota lo que acabo de decir',
    'guarda lo que hemos dicho', 'apunta lo último', 'Apúntalo.', 'toma nota de eso', 'apunta lo que han dicho',
    'Vale, apunta lo de antes', 'apunta lo último que he dicho']) {
    assert.ok(apunte.pideApuntar(t), t);
  }
  for (const t of ['apunta que mañana tengo dentista', 'apunta', 'guarda', 'apunta una idea', 'recuerda',
    'eso apunta bien', 'guarda eso en la lista de la compra', '¿qué has apuntado?', '']) {
    assert.ok(!apunte.pideApuntar(t), t);
  }
});

test('47: recuerda lo oído dormido, también lo de delante del nombre, y despierta', async function () {
  const p = new EscuchaPasiva({ activa: true });
  const r = await p.esperarPalabra({
    session: sesionFalsa(['Hay que llamar al fontanero el jueves', 'y comprar pan. Jarvis, apunta eso']),
    whisperClient: whisperFalso()
  });
  assert.deepStrictEqual(r, { resto: 'apunta eso' });
  assert.strictEqual(antesDelNombre('y comprar pan. Jarvis, apunta eso'), 'y comprar pan.');
  assert.strictEqual(p.loReciente(), 'Hay que llamar al fontanero el jueves y comprar pan.');
  assert.strictEqual(p.loReciente(), '', 'una vez pedido, se olvida');
});

test('47: lo viejo se olvida solo, «modo normal» lo borra y con 0 no se guarda nada', function () {
  const p = new EscuchaPasiva({ activa: true });
  p.recordar('lo de hace dos minutos');
  p._reciente[0].en -= 120000;
  p.recordar('lo de ahora');
  assert.strictEqual(p.loReciente(), 'lo de ahora');
  p.recordar('algo');
  p.orden('modo normal');
  assert.strictEqual(p.loReciente(), '');
  process.env.ESCUCHA_PASIVA_MEMORIA_S = '0';
  try {
    const sin = new EscuchaPasiva({ activa: true });
    sin.recordar('algo');
    assert.strictEqual(sin.loReciente(), '');
  } finally {
    delete process.env.ESCUCHA_PASIVA_MEMORIA_S;
  }
});

test('47: «apunta eso» lo manda al backend, lo dice y no deja el texto en el registro', async function () {
  process.env.LECTURA_URL = 'http://backend.test/';
  process.env.LECTURA_TOKEN = 'llave';
  try {
    const p = new EscuchaPasiva({ activa: true });
    p.recordar('La matrícula del coche de Erik es 1234 ABC');
    const c = contexto(p);
    assert.strictEqual(await apunte.atender('Apunta eso', c), true);
    assert.deepStrictEqual(c.pedidos, [{
      url: 'http://backend.test/telefono/apunte',
      cuerpo: { texto: 'La matrícula del coche de Erik es 1234 ABC' }, auth: 'Bearer llave'
    }]);
    assert.deepStrictEqual(c.dicho, [apunte.FRASES.hecho]);
    assert.ok(!/1234|Erik/.test(c.registro.join(' ')));
  } finally {
    delete process.env.LECTURA_URL;
    delete process.env.LECTURA_TOKEN;
  }
});

test('47: sin nada que apuntar lo dice; si el backend falla, también; y fuera de la escucha no es cosa suya', async function () {
  const p = new EscuchaPasiva({ activa: true });
  let c = contexto(p);
  assert.strictEqual(await apunte.atender('apunta eso', c), true);
  assert.deepStrictEqual(c.dicho, [apunte.FRASES.nada]);
  assert.strictEqual(c.pedidos.length, 0);

  p.recordar('algo que apuntar');
  c = contexto(p, 'caido');
  assert.strictEqual(await apunte.atender('apunta eso', c), true);
  assert.deepStrictEqual(c.dicho, [apunte.FRASES.fallo]);

  p.recordar('otra cosa');
  c = contexto(p, { ok: false });
  await apunte.atender('apunta eso', c);
  assert.deepStrictEqual(c.dicho, [apunte.FRASES.fallo]);

  c = contexto(new EscuchaPasiva());
  assert.strictEqual(await apunte.atender('apunta eso', c), false, 'en una llamada normal, que lo piense Claude');
  c = contexto(p);
  assert.strictEqual(await apunte.atender('apunta que tengo dentista', c), false);
});
