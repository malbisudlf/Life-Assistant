/**
 * Parche 46: despertar a Jarvis en la escucha pasiva tardaba el doble que un turno
 * normal. Ahora busca su nombre mientras hablas (tono incluido), transcribe la frase
 * una sola vez y, si puede, durante el silencio que la cierra; y el cronómetro cuenta
 * el despertar desde que callaste.
 *
 * Se lanza con `node --test test/parche46.test.js`, dentro de la imagen y sin red.
 */
'use strict';

const test = require('node:test');
const assert = require('node:assert');
const Module = require('node:module');
const { EventEmitter } = require('node:events');

const requireDeVerdad = Module.prototype.require;
Module.prototype.require = function (id) {
  if (id === 'ws') return { Server: function () {} };
  return requireDeVerdad.apply(this, arguments);
};
for (const nivel of ['log', 'warn', 'error']) console[nivel] = function () {};

const { EscuchaPasiva } = require('../lib/escucha-pasiva');
const { armarAnticipo } = require('../lib/anticipo');
const { AudioForkSession } = require('../lib/audio-fork');
const cronometro = require('../lib/cronometro');

const tic = function () { return new Promise(function (r) { setImmediate(r); }); };

/** Una sesión a la que el test le da las frases a mano. */
function sesionManual() {
  const s = new EventEmitter();
  s.setCaptureEnabled = function () {};
  s.pendientes = [];
  s.waitForUtterance = function () {
    return new Promise(function (resolve, reject) { s.pendientes.push({ resolve: resolve, reject: reject }); });
  };
  s.llega = function (u) { s.pendientes.shift().resolve(u); };
  s.cuelga = function () { s.pendientes.shift().reject(new Error('AudioForkSession closed for call x')); };
  return s;
}

/** Con el oído de jacobo: apunta qué se le pide y con qué modelo. */
function whisperConOido(disponible) {
  const w = { pedidos: [] };
  w.oidoDisponible = function () { return disponible !== false; };
  w.transcribe = async function (a, o) {
    w.pedidos.push({ texto: a.toString(), rapido: Boolean(o && o.rapido), soloOido: Boolean(o && o.soloOido) });
    return a.toString();
  };
  return w;
}

test('46: con jacobo, una frase larga se transcribe una sola vez y entera', async function () {
  process.env.ESCUCHA_PASIVA_VENTANA_MS = '1';            // 32 bytes: todo es «largo»
  try {
    const p = new EscuchaPasiva({ activa: true });
    const w = whisperConOido();
    const s = sesionManual();
    const espera = p.esperarPalabra({ session: s, whisperClient: w });
    const orden = 'Jarvis, escúchame, estoy yendo a la universidad, ¿hay mucho tráfico?';
    s.llega({ audio: Buffer.from(orden), reason: 'end_silence', finHabla: 1000 });
    const r = await espera;
    assert.strictEqual(w.pedidos.length, 1, 'antes eran dos pasadas seguidas');
    assert.strictEqual(w.pedidos[0].texto, orden);
    assert.ok(/tráfico/.test(r.resto));
    assert.strictEqual(p.ultimaFrase.finHabla, 1000);
    assert.ok(p.ultimaFrase.cierreEn <= p.ultimaFrase.textoEn);
  } finally {
    delete process.env.ESCUCHA_PASIVA_VENTANA_MS;
  }
});

test('46: sin jacobo sigue la ventana del 22 (el principio y, si trae el nombre, entera)', async function () {
  process.env.ESCUCHA_PASIVA_VENTANA_MS = '1';
  try {
    const p = new EscuchaPasiva({ activa: true });
    const w = whisperConOido(false);
    const s = sesionManual();
    const espera = p.esperarPalabra({ session: s, whisperClient: w });
    s.llega({ audio: Buffer.from('Jarvis, apaga la calefacción de casa que se nos ha olvidado'), reason: 'end_silence' });
    await espera;
    assert.strictEqual(w.pedidos.length, 2);
    assert.ok(w.pedidos[0].texto.length < w.pedidos[1].texto.length, 'primero solo el principio');
    assert.ok(/^Jarvis, apaga/.test(w.pedidos[0].texto));
  } finally {
    delete process.env.ESCUCHA_PASIVA_VENTANA_MS;
  }
});

test('46: oye su nombre mientras hablas: suena el tono y esa frase se anticipa', async function () {
  const p = new EscuchaPasiva({ activa: true });
  const w = whisperConOido();
  const s = sesionManual();
  let tonos = 0;
  const espera = p.esperarPalabra({ session: s, whisperClient: w, alNombrar: function () { tonos++; } });
  const larga = { audio: Buffer.alloc(p.anticipoMs * 32 * 3) };
  assert.strictEqual(p.anticipar(larga, w), false, 'una frase larga sin nombre no se anticipa');

  s.emit('hablando', { audio: Buffer.from('Jarvis, escúch') });
  await tic(); await tic();
  assert.strictEqual(tonos, 1);
  assert.deepStrictEqual(w.pedidos[0], { texto: 'Jarvis, escúch', rapido: true, soloOido: true });
  assert.ok(p.nombrada());
  assert.strictEqual(p.anticipar(larga, w), true);
  // El segundo aviso de la misma frase no repite ni el tono ni la consulta.
  s.emit('hablando', { audio: Buffer.from('Jarvis, escúchame, estoy') });
  await tic();
  assert.strictEqual(tonos, 1);
  assert.strictEqual(w.pedidos.length, 1);

  // La frase llega con la transcripción del anticipo: no se pide otra.
  s.llega({
    audio: Buffer.from('x'), reason: 'end_silence', finHabla: 5,
    pausa: { transcripcion: Promise.resolve('Jarvis, escúchame, ¿hay tráfico?') }
  });
  const r = await espera;
  assert.deepStrictEqual(r, { resto: 'escúchame, ¿hay tráfico?' });
  assert.strictEqual(w.pedidos.length, 1);
  assert.strictEqual(p.ultimaFrase.tono, true);
  assert.strictEqual(s.listenerCount('hablando'), 0, 'al despertar deja de mirar');
});

test('46: la charla sin su nombre ni suena ni despierta, y lo oído de una frase no vale para la siguiente', async function () {
  const p = new EscuchaPasiva({ activa: true });
  const w = whisperConOido();
  let lento = null;
  const transcribe = w.transcribe;
  w.transcribe = function (a, o) {
    if (o && o.rapido) return new Promise(function (r) { lento = function () { r(a.toString()); }; });
    return transcribe(a, o);
  };
  const s = sesionManual();
  let tonos = 0;
  const espera = p.esperarPalabra({ session: s, whisperClient: w, alNombrar: function () { tonos++; } });
  s.emit('hablando', { audio: Buffer.from('Jarvis, pon') });      // `small` aún no ha contestado…
  s.llega({ audio: Buffer.from('y el partido de ayer'), reason: 'end_silence' });
  await tic(); await tic();
  lento();                                                         // …y contesta con la frase ya cerrada
  await tic(); await tic();
  assert.strictEqual(tonos, 0);
  assert.ok(!p.nombrada());
  s.cuelga();
  assert.strictEqual(await espera, null);
  assert.ok(p.dormida());
});

test('46: si el tono ya sonó y el texto final no trae el nombre, pregunta «¿Señor?»', async function () {
  const p = new EscuchaPasiva({ activa: true });
  const w = whisperConOido();
  const s = sesionManual();
  const espera = p.esperarPalabra({ session: s, whisperClient: w, alNombrar: function () {} });
  s.emit('hablando', { audio: Buffer.from('Jarvis') });
  await tic(); await tic();
  s.llega({ audio: Buffer.from('ya vi eso'), reason: 'end_silence' });
  assert.deepStrictEqual(await espera, { resto: '' });
});

test('46: dormido, una pausa corta se transcribe ya si contesta jacobo; despierto, siempre', function () {
  const p = new EscuchaPasiva({ activa: true });
  const corta = { audio: Buffer.alloc(p.anticipoMs * 32) };
  assert.strictEqual(p.anticipar(corta, whisperConOido()), true);
  assert.strictEqual(p.anticipar(corta, whisperConOido(false)), false, 'contra OpenAI, no');
  assert.strictEqual(p.anticipar(corta, { transcribe: function () {} }), false);
  p.despierta = true;
  assert.strictEqual(p.anticipar({ audio: Buffer.alloc(p.anticipoMs * 320) }, whisperConOido(false)), true);
  process.env.ESCUCHA_PASIVA_TEMPRANA_MS = '0';
  try {
    const apagada = new EscuchaPasiva({ activa: true });
    assert.strictEqual(apagada.anticipar(corta, whisperConOido()), false, 'apagado, como en el 22');
  } finally {
    delete process.env.ESCUCHA_PASIVA_TEMPRANA_MS;
  }
});

test('46: el anticipo le pasa la pausa a `activo`', function () {
  const s = new EventEmitter();
  const w = whisperConOido();
  const vistas = [];
  armarAnticipo(s, w, { activo: function (pausa) { vistas.push(pausa); return false; } });
  const pausa = { audio: Buffer.from('hola') };
  s.emit('pausa', pausa);
  assert.deepStrictEqual(vistas, [pausa]);
  assert.strictEqual(w.pedidos.length, 0);
});

test('46: el detector avisa a los 1,2 y 2,5 s de voz, una vez cada uno por frase', function () {
  const ws = new EventEmitter();
  const s = new AudioForkSession({ ws: ws, callUuid: 'x' });
  const avisos = [];
  s.on('hablando', function (t) { avisos.push(t.audio.length); });
  // 20 ms de voz a 16 kHz: una onda cuadrada bien por encima del umbral.
  const voz = Buffer.alloc(640);
  for (let i = 0; i < 320; i++) voz.writeInt16LE(i % 40 < 20 ? 12000 : -12000, i * 2);
  // Tres trozos de voz y uno de silencio: como al hablar, y el suelo de ruido se queda abajo.
  const callado = Buffer.alloc(640);
  const hablar = function (trozosDeVoz) {
    for (let i = 0; i < trozosDeVoz; i++) {
      ws.emit('message', voz);
      if (i % 3 === 2) ws.emit('message', callado);
    }
  };
  for (let i = 0; i < 10; i++) ws.emit('message', callado);
  hablar(57);                                                      // 1,14 s de voz
  assert.strictEqual(avisos.length, 0);
  hablar(6);
  assert.strictEqual(avisos.length, 1);
  hablar(90);                                                      // hasta ~3 s
  assert.strictEqual(avisos.length, 2);
  assert.ok(avisos[1] > avisos[0]);
  // Sin nadie escuchando el aviso, no se monta el audio para nada.
  s.removeAllListeners('hablando');
  s.setCaptureEnabled(false);
  s.setCaptureEnabled(true);
  hablar(70);
  assert.strictEqual(avisos.length, 2);
});

test('46: el cronómetro cuenta el despertar desde que callaste', function () {
  cronometro._reiniciar();
  const crono = cronometro.turno('x', 'saliente');
  const uf = { finHabla: 1000, cierreEn: 2200, textoEn: 2300 };
  crono.marca('finHabla', uf.finHabla);
  crono.marca('cierre', uf.cierreEn).marca('texto', uf.textoEn);
  crono.marca('consulta', 2300).marca('respuesta', 4700).marca('suena', 5200);
  const r = crono.cerrar('claude', function () {});
  assert.strictEqual(r.ms.cierre, 1200);
  assert.strictEqual(r.ms.oido, 100);
  assert.strictEqual(r.ms.total, 4200);
});
