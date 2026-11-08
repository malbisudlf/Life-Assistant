/**
 * Parche 14: un REGISTER que se pierde sin respuesta se vuelve a mandar.
 *
 * Se prueba sin centralita: drachtio es un doble que decide qué pasa con cada
 * REGISTER (perderse, contestar 200, contestar tarde, fallar). Lo que corre es el
 * lib/multi-registrar.js de verdad. Se lanza con `node --test test/parche14.test.js`.
 * Ver telefono/PARCHES.md, «El parche 14».
 */
'use strict';

process.env.REGISTER_TIMEOUT_SECONDS = '0.05';

const test = require('node:test');
const assert = require('node:assert');
const { EventEmitter } = require('node:events');
const MultiRegistrar = require('../lib/multi-registrar');

const espera = function(ms) { return new Promise(function(r) { setTimeout(r, ms); }); };

// Cada REGISTER consume el siguiente guion de la lista; sin guion, se pierde.
function drachtioFalso(guiones) {
  const srf = { enviados: [], pendientes: [] };
  srf.request = function(uri, opts, cb) {
    const guion = guiones.shift() || 'perder';
    srf.enviados.push(guion);
    if (guion === 'lanzar') throw new Error('drachtio no conectado');
    const req = new EventEmitter();
    cb(null, req);
    const contestar = function(status) {
      req.emit('response', { status: status, reason: 'x', get: function() { return null; } });
    };
    if (guion === 'ok') setImmediate(function() { contestar(200); });
    if (guion === 'tarde') srf.pendientes.push(function() { contestar(200); });
    if (guion === 'reto') setImmediate(function() { contestar(407); });
  };
  return srf;
}

let lineas = [];
const silencio = function() {
  const log = console.log, error = console.error;
  lineas = [];
  console.log = console.error = function(t) { lineas.push(String(t)); };
  return function() { console.log = log; console.error = error; };
};

const base = { domain: 'd', registrar: '127.0.0.1', registrar_port: 5060, expiry: 3600,
               local_address: '10.0.0.1', local_port: 5070 };
const dispositivos = { '100': { name: 'Jarvis', extension: '100', authId: 'a', password: 'p' } };

test('el caso del 2026-10-06: el primer REGISTER se pierde y el segundo registra', async function() {
  const volver = silencio();
  const srf = drachtioFalso(['perder', 'ok']);
  const r = new MultiRegistrar(srf, base);
  r.registerAll(dispositivos);
  await espera(150);
  volver();
  assert.deepStrictEqual(srf.enviados, ['perder', 'ok']);
  assert.ok(r.registrations.has('100'));
  r.stop();
});

test('registrado, ya no se reintenta: solo queda el refresco', async function() {
  const volver = silencio();
  const srf = drachtioFalso(['ok']);
  const r = new MultiRegistrar(srf, base);
  r.registerAll(dispositivos);
  await espera(200);
  volver();
  assert.deepStrictEqual(srf.enviados, ['ok']);
  r.stop();
});

test('un reto 407 sin respuesta final también acaba en reintento', async function() {
  const volver = silencio();
  const srf = drachtioFalso(['reto', 'ok']);
  const r = new MultiRegistrar(srf, base);
  r.registerAll(dispositivos);
  await espera(150);
  volver();
  assert.deepStrictEqual(srf.enviados, ['reto', 'ok']);
  assert.ok(r.registrations.has('100'));
  r.stop();
});

test('la respuesta tardía de un intento viejo se ignora', async function() {
  const volver = silencio();
  const srf = drachtioFalso(['tarde', 'ok']);
  const r = new MultiRegistrar(srf, base);
  r.registerAll(dispositivos);
  await espera(90);                                // el segundo intento ya registró
  srf.pendientes.forEach(function(f) { f(); });    // y ahora contesta el primero
  await espera(20);
  volver();
  // Si no se ignorase, programaría un segundo refresco y se irían duplicando.
  const exitos = lineas.filter(function(l) { return l.indexOf('SUCCESS') !== -1; });
  assert.strictEqual(exitos.length, 1);
  r.stop();
});

test('si drachtio lanza al pedir, se reintenta en vez de morir', async function() {
  const volver = silencio();
  const srf = drachtioFalso(['lanzar']);
  const r = new MultiRegistrar(srf, base);
  assert.doesNotThrow(function() { r.registerAll(dispositivos); });
  volver();
  const e = r.estado.get('100');
  assert.ok(e.siguiente, 'no quedó un reintento programado');
  r.stop();
});

test('tras stop() no sale ningún REGISTER más', async function() {
  const volver = silencio();
  const srf = drachtioFalso([]);
  const r = new MultiRegistrar(srf, base);
  r.registerAll(dispositivos);
  r.stop();
  await espera(150);
  volver();
  assert.strictEqual(srf.enviados.length, 1);
});
