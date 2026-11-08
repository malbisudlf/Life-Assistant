/**
 * Parche 24: el lector con mando. Si cuelgas a media lectura, «sigue leyendo» en otra
 * llamada sigue por el mismo trozo; y cortándole, «siguiente», «anterior», «repite»,
 * «para» o «ve a la de economía» los cumple la llamada sin preguntarle a Claude.
 *
 * Mismos dobles que parche18.test.js; el backend es un fetch falso que trocea como el
 * de verdad (`desde`, `trozo`, `seguir`) y se acuerda de la última posición apuntada.
 * Se lanza con `node --test test/parche24.test.js`, dentro de la imagen y sin red.
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

const { leerSiLoPide, pedidoDeLectura, ordenDeLectura, ControlLectura, FRASES } = require('../lib/lectura');
const { handleInvite } = require('../lib/sip-handler');
const { runConversationLoop } = require('../lib/conversation-loop');

// ── El briefing de mentira ───────────────────────────────────────────────────
// Con la forma del de verdad: una sección «3.5», bloques que empiezan a media sección y
// bloques en el trozo 0 (que son la misma parada que su sección).
const SECCIONES = [
  { n: 1, etiqueta: '1', titulo: 'Tecnología General', trozos: ['Tec·0', 'Tec·1'], bloques: [] },
  { n: 2, etiqueta: '2', titulo: 'Inteligencia Artificial', trozos: ['IA·0', 'IA·1', 'IA·2', 'IA·3'],
    bloques: [{ trozo: 0, titulo: 'IA General' }, { trozo: 2, titulo: 'Nuevos lanzamientos y actualizaciones' }] },
  { n: 3, etiqueta: '3', titulo: 'Actualidad General', trozos: ['Act·0', 'Act·1', 'Act·2'],
    bloques: [{ trozo: 0, titulo: 'España' }, { trozo: 1, titulo: 'Resto del mundo' },
              { trozo: 2, titulo: 'El Blog de Enrique Dans' }] },
  { n: 4, etiqueta: '3.5', titulo: 'Economía y Geopolítica', trozos: ['Eco·0', 'Eco·1', 'Eco·2'],
    bloques: [{ trozo: 0, titulo: 'Al día' }, { trozo: 1, titulo: 'Financial Times' },
              { trozo: 2, titulo: 'La palabra del día: SEPA y las transferencias inmediatas' }] },
  { n: 5, etiqueta: '4', titulo: 'Tu agenda de hoy', trozos: ['Age·0'], bloques: [] },
  { n: 6, etiqueta: '5', titulo: 'Tu día', trozos: ['Dia·0', 'Dia·1'],
    bloques: [{ trozo: 0, titulo: 'Clima' }, { trozo: 1, titulo: 'Estado físico' }] }
];
const INDICE = SECCIONES.map(function (s) {
  return { n: s.n, etiqueta: s.etiqueta, titulo: s.titulo, bloques: s.bloques };
});

/** El backend: trocea como /telefono/lectura y apunta lo que le manda la llamada. */
function backendFalso(posicion) {
  const b = { gets: [], posts: [], posicion: posicion || null };
  b.fetch = async function (url, opciones) {
    if (opciones && opciones.method === 'POST') {
      const cuerpo = JSON.parse(opciones.body);
      b.posts.push(cuerpo);
      b.posicion = cuerpo;
      return { ok: true, status: 200, json: async function () { return { ok: true }; } };
    }
    b.gets.push(url);
    const q = new URL(url).searchParams;
    let desde = parseInt(q.get('desde'), 10) || 1;
    let trozo = parseInt(q.get('trozo'), 10) || 0;
    if (q.get('seguir')) {
      if (!b.posicion || b.posicion.terminada) {
        return { ok: true, status: 200, json: async function () {
          return { ok: false, frase: 'No tengo ninguna lectura a medias que seguir.' }; } };
      }
      desde = b.posicion.n;
      trozo = b.posicion.trozo;
    }
    const secciones = SECCIONES.filter(function (s) { return s.n >= desde; }).map(function (s, i) {
      const k = i === 0 ? trozo : 0;
      return { n: s.n, titulo: s.titulo, trozos: s.trozos.slice(k), primer_trozo: k };
    });
    const datos = { ok: true, que: 'briefing', nombre: 'el briefing', fecha: '2026-10-25',
                    indice: INDICE, secciones: secciones };
    return { ok: true, status: 200, json: async function () { return datos; } };
  };
  return b;
}

// ── Dobles de la llamada (los de parche18.test.js) ───────────────────────────
function ttsFalso() {
  const t = { pedidos: [] };
  t.generateSpeech = async function (texto) { t.pedidos.push(texto); return 'tts:' + texto; };
  return t;
}

/** Lo que `bloquea` devuelve true se queda sonando hasta un uuid_break (solo la vez que diga). */
function endpointFalso(bloquea) {
  const ep = new EventEmitter();
  const veces = {};
  ep.uuid = 'ep-1';
  ep.hecho = [];
  ep._sonando = [];
  ep.play = function (url) {
    ep.hecho.push('play ' + url);
    veces[url] = (veces[url] || 0) + 1;
    if (bloquea && bloquea(url, veces[url])) return new Promise(function (r) { ep._sonando.push(r); });
    return Promise.resolve();
  };
  ep.api = async function (cmd) {
    ep.hecho.push('api ' + cmd);
    if (cmd === 'uuid_break') { const s = ep._sonando; ep._sonando = []; s.forEach(function (r) { r(); }); }
  };
  ep.forkAudioStart = async function () {};
  ep.forkAudioStop = async function () {};
  ep.destroy = async function () {};
  return ep;
}

/** El oído: corta en la reproducción interrumpible número N (cuenta desde 1). */
function sesionFalsa(frases, cortaEn) {
  const s = new EventEmitter();
  let i = 0;
  let armados = 0;
  s.setCaptureEnabled = function () {};
  s.forceFinalize = function () {};
  s.armarBargeIn = function () {
    armados++;
    if ((cortaEn || []).indexOf(armados) >= 0) setImmediate(function () { s.emit('barge'); });
  };
  s.waitForUtterance = async function () {
    const f = frases[i++];
    if (f == null) throw new Error('Timed out waiting for utterance');
    return { audio: Buffer.from(f), reason: 'end_silence' };
  };
  return s;
}

function interrumpibles(ep) {
  return ep.hecho.filter(function (h) { return h.indexOf('play tts:') === 0; })
    .map(function (h) { return h.slice('play tts:'.length); });
}

function estadoEn(n, trozo, recien) {
  return { que: 'briefing', fecha: '2026-10-25', nombre: 'el briefing', indice: INDICE,
           n: n, trozo: trozo, titulo: SECCIONES[n - 1].titulo, fin: false, recien: recien !== false };
}

function donde(o) { return o && o.tipo + ' ' + o.n + ':' + o.trozo; }

// ── La marca ─────────────────────────────────────────────────────────────────
test('24: la marca entiende `seguir`, con y sin qué, y `trozo`', function () {
  assert.deepStrictEqual(pedidoDeLectura('📖 LEER: briefing seguir'),
    { que: 'briefing', fecha: '', desde: 1, hasta: 0, seguir: true });
  assert.deepStrictEqual(pedidoDeLectura('📖 LEER: seguir'),
    { que: '', fecha: '', desde: 1, hasta: 0, seguir: true });
  assert.strictEqual(pedidoDeLectura('📖 LEER: briefing desde=2 trozo=3').trozo, 3);
  // Lo de siempre no cambia de forma (parche 18).
  assert.deepStrictEqual(pedidoDeLectura('📖 LEER: briefing'),
    { que: 'briefing', fecha: '', desde: 1, hasta: 0 });
});

// ── Las órdenes ──────────────────────────────────────────────────────────────
test('24: seguir, suelto justo después de leer y explícito siempre', function () {
  assert.strictEqual(donde(ordenDeLectura('Sigue.', estadoEn(2, 1))), 'seguir 2:1');
  assert.strictEqual(donde(ordenDeLectura('Vale, sigue, por favor', estadoEn(2, 1))), 'seguir 2:1');
  // Tras un turno de Claude, «sigue» puede contestar a otra cosa: que lo vea Claude.
  assert.strictEqual(ordenDeLectura('sigue', estadoEn(2, 1, false)), null);
  assert.strictEqual(donde(ordenDeLectura('sigue leyendo', estadoEn(2, 1, false))), 'seguir 2:1');
  assert.strictEqual(donde(ordenDeLectura('continúa por donde ibas', estadoEn(3, 2, false))), 'seguir 3:2');
  assert.strictEqual(ordenDeLectura('sigue buscando', estadoEn(2, 1)), null);
});

test('24: en una llamada nueva, solo «sigue leyendo» y parecidos, y se lo pide al backend', function () {
  assert.deepStrictEqual(ordenDeLectura('Sigue leyendo', null), { tipo: 'seguir', backend: true, que: '' });
  assert.deepStrictEqual(ordenDeLectura('sigue con el briefing', null),
    { tipo: 'seguir', backend: true, que: 'briefing' });
  assert.deepStrictEqual(ordenDeLectura('léeme el resto de la agenda', null),
    { tipo: 'seguir', backend: true, que: 'semana' });
  assert.strictEqual(ordenDeLectura('sigue', null), null);
  assert.strictEqual(ordenDeLectura('ve a la de economía', null), null);
});

test('24: siguiente salta al bloque siguiente; «siguiente sección», a la sección', function () {
  // En la 2, trozo 0 («IA General», que es la misma parada que la sección).
  assert.strictEqual(donde(ordenDeLectura('siguiente', estadoEn(2, 0))), 'ir 2:2');
  assert.strictEqual(donde(ordenDeLectura('¡Sáltate esto!', estadoEn(2, 1))), 'ir 2:2');
  assert.strictEqual(donde(ordenDeLectura('esto no me interesa', estadoEn(2, 3))), 'ir 3:0');
  assert.strictEqual(donde(ordenDeLectura('pasa a la siguiente sección', estadoEn(2, 0, false))), 'ir 3:0');
  assert.strictEqual(donde(ordenDeLectura('la siguiente noticia', estadoEn(3, 0))), 'ir 3:1');
  // Pasado el último bloque no hay adónde ir.
  assert.strictEqual(ordenDeLectura('siguiente', estadoEn(6, 1)).tipo, 'nada');
});

test('24: anterior, repite y desde el principio', function () {
  assert.strictEqual(donde(ordenDeLectura('anterior', estadoEn(3, 2))), 'ir 3:1');
  assert.strictEqual(donde(ordenDeLectura('vuelve atrás', estadoEn(3, 1))), 'ir 3:0');
  assert.strictEqual(donde(ordenDeLectura('la sección anterior', estadoEn(3, 2, false))), 'ir 2:0');
  assert.strictEqual(donde(ordenDeLectura('repite', estadoEn(2, 3))), 'ir 2:3');
  assert.strictEqual(donde(ordenDeLectura('repite esta noticia', estadoEn(2, 3))), 'ir 2:2');
  assert.strictEqual(donde(ordenDeLectura('repite la sección', estadoEn(2, 3, false))), 'ir 2:0');
  assert.strictEqual(donde(ordenDeLectura('desde el principio', estadoEn(4, 1, false))), 'ir 1:0');
});

test('24: ir a una sección o a un bloque, por título o por número', function () {
  const e = estadoEn(1, 1, false);
  assert.strictEqual(donde(ordenDeLectura('ve a la de economía', e)), 'ir 4:0');
  assert.strictEqual(donde(ordenDeLectura('pasa a la de IA', e)), 'ir 2:0');
  assert.strictEqual(donde(ordenDeLectura('léeme la palabra del día', e)), 'ir 4:2');
  assert.strictEqual(donde(ordenDeLectura('lo del Financial Times', e)), 'ir 4:1');
  assert.strictEqual(donde(ordenDeLectura('lee el blog de Enrique Dance', e)), 'ir 3:2');
  assert.strictEqual(donde(ordenDeLectura('salta a las noticias de España', e)), 'ir 3:0');
  // Los números son los del correo: «4. Tu agenda» es la quinta, porque hay una 3.5.
  assert.strictEqual(donde(ordenDeLectura('la sección cuatro', e)), 'ir 5:0');
  assert.strictEqual(donde(ordenDeLectura('ve a la tres y media', e)), 'ir 4:0');
  assert.strictEqual(donde(ordenDeLectura('ve a la última', e)), 'ir 6:0');
  // «Tu día» y «La palabra del día» tienen «día»: gana la que no tiene más.
  assert.strictEqual(donde(ordenDeLectura('ve a tu día', e)), 'ir 6:0');
});

test('24: recién cortado vale el título a secas; lo que no es una orden va a Claude', function () {
  assert.strictEqual(donde(ordenDeLectura('el tiempo', estadoEn(2, 1))), 'ir 6:0');
  assert.strictEqual(donde(ordenDeLectura('economía', estadoEn(2, 1))), 'ir 4:0');
  assert.strictEqual(ordenDeLectura('economía', estadoEn(2, 1, false)), null);
  for (const frase of ['¿qué hora es?', 'pon música', 'para, ¿qué hora es?', 'apaga la luz',
                       'sáltate la palabra del día', 'no', 'gracias']) {
    assert.strictEqual(ordenDeLectura(frase, estadoEn(2, 1)), null, frase);
  }
  assert.strictEqual(ordenDeLectura('para', estadoEn(2, 1)).tipo, 'parar');
  assert.strictEqual(ordenDeLectura('déjalo ahí', estadoEn(2, 1)).tipo, 'parar');
  assert.strictEqual(ordenDeLectura('para', estadoEn(2, 1, false)), null);
});

test('24: con un backend sin índice, seguir vale y moverse se lo deja a Claude', function () {
  const e = Object.assign(estadoEn(2, 1), { indice: [] });
  assert.strictEqual(donde(ordenDeLectura('sigue', e)), 'seguir 2:1');
  assert.strictEqual(ordenDeLectura('siguiente', e), null);
  assert.strictEqual(ordenDeLectura('ve a la de economía', e), null);
});

// ── La posición ──────────────────────────────────────────────────────────────
test('24: apunta cada trozo antes de que suene, y que terminó al acabar', async function () {
  const b = backendFalso();
  const control = new ControlLectura();
  await leerSiLoPide('📖 LEER: briefing desde=5', {
    endpoint: endpointFalso(), session: sesionFalsa([], []), ttsService: ttsFalso(), voiceId: 'v',
    fetchImpl: b.fetch, control: control });
  assert.deepStrictEqual(b.posts.map(function (p) { return p.n + ':' + p.trozo + (p.terminada ? ' fin' : ''); }),
    ['5:0', '6:0', '6:1', '6:1 fin']);
  assert.strictEqual(b.posts[0].que, 'briefing');
  assert.strictEqual(b.posts[0].fecha, '2026-10-25');
  assert.strictEqual(control.estado.fin, true);
});

test('24: si cuelgas, lo último apuntado es el trozo que sonaba', async function () {
  const b = backendFalso();
  let viva = true;
  const ep = endpointFalso();
  const playDeVerdad = ep.play;
  ep.play = function (url) {
    if (url === 'tts:IA·1') viva = false;           // cuelga mientras suena
    return playDeVerdad(url);
  };
  await leerSiLoPide('📖 LEER: briefing desde=2', {
    endpoint: ep, session: sesionFalsa([], []), ttsService: ttsFalso(), voiceId: 'v',
    fetchImpl: b.fetch, sigueActiva: function () { return viva; } });
  assert.deepStrictEqual(b.posicion, { que: 'briefing', fecha: '2026-10-25', n: 2, trozo: 1,
                                       titulo: 'Inteligencia Artificial', terminada: false });
});

test('24: seguir en otra llamada retoma ese trozo y dice dónde está', async function () {
  const b = backendFalso({ que: 'briefing', fecha: '2026-10-25', n: 4, trozo: 1, terminada: false });
  const ep = endpointFalso();
  await leerSiLoPide('🗣️ VOICE_RESPONSE: Sigo.\n📖 LEER: briefing seguir', {
    endpoint: ep, session: sesionFalsa([], []), ttsService: ttsFalso(), voiceId: 'v', fetchImpl: b.fetch });
  assert.match(b.gets[0], /\/telefono\/lectura\?que=briefing&desde=1&hasta=0&seguir=true$/);
  assert.deepStrictEqual(interrumpibles(ep).slice(0, 3),
    ['Sigo con el briefing, en «Economía y Geopolítica».', 'Eco·1', 'Eco·2']);
  // La posición cuenta desde el principio de la sección, no desde donde retomó.
  assert.strictEqual(b.posts[0].n + ':' + b.posts[0].trozo, '4:1');
});

// ── Los dos bucles ───────────────────────────────────────────────────────────
function claudeQueLee() {
  const c = { preguntas: [] };
  c.query = async function (texto) {
    c.preguntas.push(texto);
    return c.preguntas.length === 1
      ? '🗣️ VOICE_RESPONSE: Te lo leo.\n📖 LEER: briefing\n🎯 COMPLETED: lectura'
      : '🗣️ VOICE_RESPONSE: vale';
  };
  c.endSession = async function () {};
  return c;
}
function opcionesComunes(sesion, claude) {
  return {
    ttsService: ttsFalso(), whisperClient: { transcribe: async function (a) { return a.toString(); } },
    claudeBridge: claude, wsPort: 3001,
    audioForkServer: { expectSession: async function () { return sesion; },
                       cancelExpectation: function () {}, emit: function () {} }
  };
}

test('24, saliente: «siguiente», «para» y «sigue» sin preguntarle a Claude', async function () {
  const b = backendFalso();
  const fetchAntes = global.fetch;
  global.fetch = b.fetch;
  try {
    // Se quedan sonando (para cortarlos) la primera vez que suenan IA·0 y Act·0.
    const ep = endpointFalso(function (url, vez) {
      return url.indexOf('hold-music') >= 0 || (vez === 1 && (url === 'tts:IA·0' || url === 'tts:Act·0'));
    });
    const claude = claudeQueLee();
    // Interrumpibles: 1 «Te lo leo», 2 Tec·0, 3 Tec·1, 4 IA·0 ← corta; «siguiente» →
    // 5 IA·2, 6 IA·3, 7 Act·0 ← corta; «para» → 8 la frase de parar; «sigue» → Act·0…
    const sesion = sesionFalsa(['léeme el briefing', 'siguiente', 'para', 'sigue', 'adiós'], [4, 7]);
    const r = await runConversationLoop(ep, new EventEmitter(), 'c-sal',
      Object.assign(opcionesComunes(sesion, claude), { skipGreeting: true }));
    assert.strictEqual(r.endReason, 'goodbye');
    assert.strictEqual(claude.preguntas.length, 1, 'Claude solo pidió la lectura');
    const leido = interrumpibles(ep);
    assert.deepStrictEqual(leido.slice(leido.indexOf('Te lo leo.')), [
      'Te lo leo.', 'Tec·0', 'Tec·1', 'IA·0',
      'IA·2', 'IA·3', 'Act·0',
      FRASES.parar,
      'Act·0', 'Act·1', 'Act·2', 'Eco·0', 'Eco·1', 'Eco·2', 'Age·0', 'Dia·0', 'Dia·1',
      'Hasta aquí el briefing.', 'Hasta luego. Llámame cuando quieras.']);
    assert.deepStrictEqual(b.posicion.terminada, true);
  } finally {
    global.fetch = fetchAntes;
  }
});

test('24, entrante: llamada nueva, «sigue leyendo» y sigue donde se colgó', async function () {
  const b = backendFalso({ que: 'briefing', fecha: '2026-10-25', n: 6, trozo: 1, terminada: false });
  const fetchAntes = global.fetch;
  global.fetch = b.fetch;
  try {
    const ep = endpointFalso(function (url) { return url.indexOf('hold-music') >= 0; });
    const claude = claudeQueLee();
    const sesion = sesionFalsa(['sigue leyendo', 'adiós'], []);
    const dialogo = new EventEmitter();
    dialogo.destroy = function () {};
    const opciones = opcionesComunes(sesion, claude);
    opciones.mediaServer = { connectCaller: async function () { return { endpoint: ep, dialog: dialogo }; } };
    const req = { get: function (h) { return h === 'To' ? '<sip:10001@x>' : '<sip:10000@x>'; }, body: 'v=0' };
    await handleInvite(req, { send: function () {} }, opciones);
    assert.strictEqual(claude.preguntas.length, 0, 'ni siquiera pasó por Claude');
    assert.match(b.gets[0], /seguir=true/);
    const leido = interrumpibles(ep);
    assert.deepStrictEqual(leido.slice(leido.indexOf('Sigo con el briefing, en «Tu día».'), -1),
      ['Sigo con el briefing, en «Tu día».', 'Dia·1', 'Hasta aquí el briefing.']);
  } finally {
    global.fetch = fetchAntes;
  }
});

test('24, entrante: «sigue leyendo» sin nada a medias lo dice y Claude se entera', async function () {
  const b = backendFalso(null);
  const fetchAntes = global.fetch;
  global.fetch = b.fetch;
  try {
    const ep = endpointFalso(function (url) { return url.indexOf('hold-music') >= 0; });
    const claude = claudeQueLee();
    const sesion = sesionFalsa(['sigue leyendo', 'pues léeme el briefing', 'adiós'], []);
    const dialogo = new EventEmitter();
    dialogo.destroy = function () {};
    const opciones = opcionesComunes(sesion, claude);
    opciones.mediaServer = { connectCaller: async function () { return { endpoint: ep, dialog: dialogo }; } };
    const req = { get: function (h) { return h === 'To' ? '<sip:10001@x>' : '<sip:10000@x>'; }, body: 'v=0' };
    await handleInvite(req, { send: function () {} }, opciones);
    assert.ok(interrumpibles(ep).indexOf('No tengo ninguna lectura a medias que seguir.') >= 0);
    assert.match(claude.preguntas[0], /^\[La lectura a medias que te pidió seguir no se pudo hacer: «No tengo ninguna lectura a medias que seguir\.»\] pues léeme el briefing$/);
  } finally {
    global.fetch = fetchAntes;
  }
});
