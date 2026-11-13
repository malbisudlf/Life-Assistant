/**
 * Parche 48: «Jarvis, mira mi pantalla». Como internet (parche 37): Claude pone
 * `📖 LEER: pantalla pregunta=…`, el backend mira la captura y la llamada lo cuenta, sin
 * que lo que hay escrito en la pantalla pase por el Claude con shell.
 *
 * Se lanza con `node --test test/parche48.test.js`, dentro de la imagen y sin red.
 */
'use strict';

const test = require('node:test');
const assert = require('node:assert');
for (const nivel of ['log', 'warn', 'error']) console[nivel] = function () {};

const { pedidoDeLectura } = require('../lib/lectura');

test('48: la línea de la pantalla, con pregunta y sin ella', function () {
  const p = pedidoDeLectura('Lo miro, señor.\n📖 LEER: pantalla pregunta=¿Qué error sale en la terminal?');
  assert.strictEqual(p.que, 'pantalla');
  assert.strictEqual(p.pregunta, '¿Qué error sale en la terminal?');
  assert.strictEqual(pedidoDeLectura('📖 LEER: pantalla').pregunta, '¿Qué hay en pantalla?');
  assert.strictEqual(pedidoDeLectura('📖 LEER: pantalla qué pone en el correo abierto').pregunta,
    'qué pone en el correo abierto');
});

test('48: «seguir» sobre la pantalla repite lo ya contado, sin otra captura', function () {
  const p = pedidoDeLectura('📖 LEER: pantalla seguir');
  assert.strictEqual(p.que, 'pantalla');
  assert.ok(p.seguir);
  assert.ok(!p.pregunta);
});

test('48: internet sigue igual', function () {
  const p = pedidoDeLectura('📖 LEER: internet pregunta=¿Cuándo juega el Athletic?');
  assert.strictEqual(p.que, 'internet');
  assert.strictEqual(p.pregunta, '¿Cuándo juega el Athletic?');
  assert.ok(!pedidoDeLectura('📖 LEER: internet seguir').pregunta);
});
