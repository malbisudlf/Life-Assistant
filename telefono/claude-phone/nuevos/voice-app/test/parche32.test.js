/**
 * Parche 32: la línea fija de O2 y la conversación con otra persona.
 *
 * drachtio, FreeSWITCH, el oído, la voz y el backend son dobles: se lanza con
 * `node --test test/parche32.test.js`, dentro de la imagen y sin red.
 */
'use strict';

const test = require('node:test');
const assert = require('node:assert');
const { EventEmitter } = require('node:events');

for (const nivel of ['log', 'warn', 'error', 'info']) console[nivel] = function () {};

const { LineaO2 } = require('../lib/linea-o2');
const { runConversacionTercero, esperarSaludo, esperarLocucion, esperarSilencio, prepararGuion,
        conModeloRapido, FRASES } = require('../lib/conversacion-tercero');

const USUARIO = 'usuario-de-prueba';
const TID = '11111111-2222-3333-4444-555555555555';

// ── La línea ─────────────────────────────────────────────────────────────────
function srfFalso(respuestas) {
  const pedidos = [];
  return {
    pedidos,
    request(uri, opciones, cb) {
      pedidos.push({ uri, opciones });
      const req = new EventEmitter();
      cb(null, req);
      const r = respuestas.shift() || { status: 200, contact: '' };
      setImmediate(() => req.emit('response', {
        status: r.status, get: (h) => (h === 'Contact' ? r.contact : '')
      }));
    }
  };
}

function linea(srf) {
  return new LineaO2(srf, { usuario: USUARIO, proxy: '198.51.100.9:5070', ipLocal: '192.0.2.5',
                            puertoLocal: 5070 });
}

test('sin usuario o sin proxy no está configurada', () => {
  assert.strictEqual(new LineaO2({}, { proxy: '198.51.100.9:5070', ipLocal: 'x' }).configurada(), false);
  assert.strictEqual(new LineaO2({}, { usuario: 'u', proxy: 'telefonica', ipLocal: 'x' }).configurada(), false);
  assert.strictEqual(linea({}).configurada(), true);
});

test('las URIs y cabeceras son las que dejaron sonar el móvil', () => {
  const l = linea({});
  assert.strictEqual(l.destino('+34600111222'), 'sip:+34600111222@telefonica.net:5060');
  const h = l.cabeceras('+34600111222');
  assert.strictEqual(h.From, `"${USUARIO}" <sip:${USUARIO}@telefonica.net:5070>`);
  assert.strictEqual(h.To, '<sip:+34600111222@telefonica.net:5060>');
  assert.strictEqual(h.Route, '<sip:198.51.100.9:5070;lr>');
  assert.strictEqual(h.Contact, `<sip:${USUARIO}@192.0.2.5:5070;transport=udp>`);
});

test('una llamada entrante del proxy es suya; la del 3CX no', () => {
  const l = linea({});
  assert.strictEqual(l.esSuya({ source_address: '198.51.100.9' }), true);
  assert.strictEqual(l.esSuya({ source_address: '127.0.0.1' }), false);
});

test('registra al usar y quita SOLO su Contact al soltar, nunca el asterisco', async () => {
  const srf = srfFalso([
    { status: 200, contact: `<sip:${USUARIO}@192.0.2.5:5070;transport=udp>;expires=130, <sip:${USUARIO}@203.0.113.1:5070>;expires=1275` },
    { status: 200 }
  ]);
  const l = linea(srf);
  await l.usar();
  assert.strictEqual(l.registrada, true);
  const reg = srf.pedidos[0].opciones;
  assert.strictEqual(reg.method, 'REGISTER');
  assert.strictEqual(reg.proxy, 'sip:198.51.100.9:5070');
  assert.strictEqual(reg.headers.Expires, '120');
  assert.strictEqual(l._concedido({ get: () => srf.pedidos.length && `<sip:${USUARIO}@192.0.2.5:5070>;expires=130, <sip:x@203.0.113.1:5070>;expires=1275` }, 120), 130);
  await l.soltar();
  const baja = srf.pedidos[1].opciones;
  assert.strictEqual(baja.headers.Expires, '0');
  assert.ok(baja.headers.Contact.startsWith(`<sip:${USUARIO}@192.0.2.5:5070`));
  assert.ok(!baja.headers.Contact.includes('*'));
  assert.strictEqual(l.registrada, false);
});

test('lo concedido: el de nuestro Contact, si no la cabecera Expires, si no 70', () => {
  const l = linea({});
  const res = (cab) => ({ get: (h) => cab[h] || '' });
  assert.strictEqual(l._concedido(res({ Contact: '<sip:u@203.0.113.1:5070>;expires=1275', Expires: '70' }), 120), 70);
  assert.strictEqual(l._concedido(res({}), 120), 70);
  assert.strictEqual(l._concedido(res({}), 60), 60);
  assert.strictEqual(l._concedido(res({ Contact: `<sip:${USUARIO}@192.0.2.5:5070>;expires=90`, Expires: '70' }), 120), 90);
});

test('con 70 concedidos renueva a los 42 s, antes de que caduque', () => {
  const l = linea({});
  const antes = global.setTimeout;
  let ms = null;
  global.setTimeout = function (fn, t) { ms = t; return { unref() {} }; };
  try { l._programarRefresco(70); } finally { global.setTimeout = antes; }
  assert.strictEqual(ms, 42000);
});

test('dos usos a la vez: un registro, y la baja con el último', async () => {
  const srf = srfFalso([{ status: 200 }, { status: 200 }]);
  const l = linea(srf);
  await l.usar();
  await l.usar();
  assert.strictEqual(srf.pedidos.length, 1);
  await l.soltar();
  assert.strictEqual(srf.pedidos.length, 1);
  await l.soltar();
  assert.strictEqual(srf.pedidos.length, 2);
});

test('si Telefónica no acepta el registro, usar lanza y no queda en uso', async () => {
  const l = linea(srfFalso([{ status: 403 }]));
  await assert.rejects(l.usar(), /o2_register_403/);
  assert.strictEqual(l.usos, 0);
  assert.strictEqual(l.registrada, false);
});

// ── La conversación ──────────────────────────────────────────────────────────
function escena(guion) {
  // guion.oido: lo que "dice" el otro en cada espera (texto, o null = silencio)
  const dichos = [];
  const pedidosBackend = [];
  const dialog = new EventEmitter();
  const sesion = new EventEmitter();
  const oido = guion.oido.slice();
  sesion.setCaptureEnabled = () => {};
  sesion.waitForUtterance = async () => {
    const t = oido.length ? oido.shift() : null;
    if (t === null) throw new Error('timeout');
    return { audio: Buffer.from(t), texto: t };
  };
  const endpoint = {
    async forkAudioStart() {}, async forkAudioStop() {},
    async play(url) { dichos.push(url.replace('tts:', '')); }
  };
  const o = {
    audioForkServer: { expectSession: async () => sesion, cancelExpectation() {} },
    whisperClient: { transcribe: async (audio) => audio.toString() },
    ttsService: { generateSpeech: async (texto) => 'tts:' + texto },
    wsPort: 3001,
    tercero: TID,
    apertura: 'Hola, Erik. Soy Jarvis, el asistente de Mikel. ¿Comes hoy con él?',
    onTurno: () => {},
    // El saludo, del mismo guion que el resto (esperarSaludo se prueba aparte).
    esperarSaludo: (s) => s.waitForUtterance({ timeoutMs: 1 }).catch(() => null),
    fetch: async (url, opciones) => {
      if (url.endsWith('/guion')) {
        return { ok: true, status: 200, json: async () => ({ frases: guion.guion || [], listo: true }) };
      }
      pedidosBackend.push({ url, opciones, cuerpo: JSON.parse(opciones.body) });
      const r = guion.backend.shift();
      if (r instanceof Error) throw r;
      return { ok: r.status ? r.status < 300 : true, status: r.status || 200, json: async () => r };
    }
  };
  return { endpoint, dialog, o, dichos, pedidosBackend };
}

test('espera el «¿Sí?», se presenta, conversa con el backend y cuelga cuando él lo dice', async () => {
  process.env.TELEFONO_TERCEROS_TOKEN = 'token-de-prueba';
  const e = escena({
    oido: ['¿Sí?', 'Sí, a las dos y media'],
    backend: [{ decir: 'Perfecto, se lo digo. ¡Hasta luego!', colgar: true }]
  });
  const turnos = [];
  e.o.onTurno = (quien, texto) => turnos.push([quien, texto]);
  const r = await runConversacionTercero(e.endpoint, e.dialog, 'c1', e.o);
  assert.strictEqual(r.endReason, 'goodbye');
  assert.deepStrictEqual(e.dichos, [e.o.apertura, 'Perfecto, se lo digo. ¡Hasta luego!']);
  assert.strictEqual(e.pedidosBackend.length, 1);
  assert.ok(e.pedidosBackend[0].url.endsWith('/telefono/tercero/' + TID + '/turno'));
  assert.strictEqual(e.pedidosBackend[0].opciones.headers['X-Auth-Token'], 'token-de-prueba');
  assert.deepStrictEqual(e.pedidosBackend[0].cuerpo, { dicho: 'Sí, a las dos y media' });
  // El saludo se transcribe de fondo: entra en el historial cuando llega.
  assert.deepStrictEqual(turnos.map((t) => t[0]).sort(), ['jarvis', 'jarvis', 'otro', 'otro']);
  assert.deepStrictEqual(turnos.find((t) => t[0] === 'jarvis'), ['jarvis', e.o.apertura]);
});

test('la presentación pedida mientras sonaba no se vuelve a pedir', async () => {
  const e = escena({ oido: ['¿Sí?', 'Vale'], backend: [{ decir: 'Genial. ¡Adiós!', colgar: true }] });
  const pedidas = [];
  e.o.ttsService = { generateSpeech: async (t) => { pedidas.push(t); return 'tts:' + t; } };
  e.o.aperturaUrl = Promise.resolve('tts:PREVIA');
  await runConversacionTercero(e.endpoint, e.dialog, 'c1', e.o);
  assert.deepStrictEqual(e.dichos, ['PREVIA', 'Genial. ¡Adiós!']);
  assert.deepStrictEqual(pedidas, ['Genial. ¡Adiós!']);
});

test('si la presentación anticipada falló, se pide al descolgar', async () => {
  const e = escena({ oido: ['¿Sí?', 'Vale'], backend: [{ decir: 'Adiós.', colgar: true }] });
  e.o.aperturaUrl = Promise.resolve(null);
  await runConversacionTercero(e.endpoint, e.dialog, 'c1', e.o);
  assert.strictEqual(e.dichos[0], e.o.apertura);
});

// ── Sin barge-in (parche 35) ─────────────────────────────────────────────────
test('Jarvis dice cada frase entera: oído cerrado, sin armar el corte y sin uuid_break', async () => {
  const e = escena({ oido: ['¿Sí?', 'Sí', 'x', 'Vale'],
                     backend: [{ decir: '¿A qué hora?' }, { decir: 'Hecho. ¡Adiós!', colgar: true }] });
  const original = e.o.audioForkServer.expectSession;
  let captura = false;
  let armados = 0;
  const cortes = [];
  const oidoAlHablar = [];
  e.o.audioForkServer.expectSession = async () => {
    const s = await original();
    s.setCaptureEnabled = (v) => { captura = v; };
    s.armarBargeIn = () => { armados++; captura = true; };
    return s;
  };
  const decirAntes = e.endpoint.play;
  e.endpoint.play = async function (url) { oidoAlHablar.push(captura); return decirAntes.call(this, url); };
  e.endpoint.api = async (orden) => { cortes.push(orden); };
  e.endpoint.uuid = 'u';
  const r = await runConversacionTercero(e.endpoint, e.dialog, 'c1', e.o);
  assert.strictEqual(r.endReason, 'goodbye');
  assert.strictEqual(armados, 0);
  assert.deepStrictEqual(cortes, []);
  assert.ok(oidoAlHablar.length >= 3);
  assert.ok(oidoAlHablar.every((abierto) => abierto === false), JSON.stringify(oidoAlHablar));
});

// ── El saludo ────────────────────────────────────────────────────────────────
function detector() {
  const s = new EventEmitter();
  s._inSpeech = false; s._silenceMs = 0; s._utteranceChunks = [];
  return s;
}

test('saludo: tras decir «¿Sí?» y callar 350 ms (parche 43; eran 450), no espera más', async () => {
  const s = detector();
  const t0 = Date.now();
  setTimeout(() => { s._inSpeech = true; s._utteranceChunks = [Buffer.from('si')]; }, 100);
  setTimeout(() => { s._silenceMs = 360; }, 300);
  const u = await esperarSaludo(s);
  assert.strictEqual(u.audio.toString(), 'si');
  assert.ok(Date.now() - t0 < 600, 'tardó ' + (Date.now() - t0) + ' ms');
});

test('saludo: si nadie habla en 1,2 s (parche 43; eran 2), se presenta sin esperar los 3', async () => {
  const s = detector();
  const t0 = Date.now();
  assert.strictEqual(await esperarSaludo(s), null);
  const ms = Date.now() - t0;
  assert.ok(ms >= 1150 && ms < 1600, 'tardó ' + ms + ' ms');
});

test('saludo: si la frase se cierra sola, vale esa', async () => {
  const s = detector();
  setTimeout(() => s.emit('utterance', { audio: Buffer.from('diga') }), 50);
  const u = await esperarSaludo(s);
  assert.strictEqual(u.audio.toString(), 'diga');
  assert.strictEqual(s.listenerCount('utterance'), 0);
});

test('saludo: hablando sin parar, a los 3 s se presenta con lo dicho', async () => {
  const s = detector();
  s._inSpeech = true; s._utteranceChunks = [Buffer.from('bla')];
  const t0 = Date.now();
  const u = await esperarSaludo(s);
  assert.ok(Date.now() - t0 >= 2950);
  assert.strictEqual(u.audio.toString(), 'bla');
});

test('un «sí» suelto cuenta: la voz mínima baja a 200 ms', async () => {
  const e = escena({ oido: ['¿Sí?', 'Sí'], backend: [{ decir: 'Genial. ¡Adiós!', colgar: true }] });
  const sesiones = [];
  const original = e.o.audioForkServer.expectSession;
  e.o.audioForkServer.expectSession = async () => {
    const s = await original(); s.minSpeechMs = 350; s.endSilenceMs = 1500; sesiones.push(s); return s;
  };
  await runConversacionTercero(e.endpoint, e.dialog, 'c1', e.o);
  assert.strictEqual(sesiones[0].minSpeechMs, 200);
  // Y la frase se da por acabada a los 0,9 s de silencio, no a los 1,5.
  assert.strictEqual(sesiones[0].endSilenceMs, 900);
});

// ── Lo preparado ─────────────────────────────────────────────────────────────
test('la voz del guion se pide por adelantado y se usa si la frase es del guion', async () => {
  const e = escena({ oido: ['¿Sí?', 'A las cinco'], guion: ['Perfecto, se lo digo a Mikel.'],
                     backend: [{ decir: 'Perfecto, se lo digo a Mikel.', colgar: true }] });
  const pedidas = [];
  e.o.ttsService = { generateSpeech: async (t) => { pedidas.push(t); return 'tts:PREVIA ' + t; } };
  e.o.aperturaUrl = Promise.resolve('tts:apertura');
  await runConversacionTercero(e.endpoint, e.dialog, 'c1', e.o);
  // Pedida una sola vez, por adelantado, y sonó la preparada.
  assert.deepStrictEqual(pedidas, ['Perfecto, se lo digo a Mikel.']);
  assert.deepStrictEqual(e.dichos, ['apertura', 'PREVIA Perfecto, se lo digo a Mikel.']);
});

test('guion: pregunta hasta que esté listo y no lanza si el backend falla', async () => {
  let veces = 0;
  const cache = new Map();
  const o = {
    tercero: 'x', guionSondeoMs: 5,
    ttsService: { generateSpeech: async (t) => 'tts:' + t },
    fetch: async () => {
      veces++;
      if (veces === 1) throw new Error('caído');
      if (veces === 2) return { ok: true, status: 200, json: async () => ({ frases: [], listo: false }) };
      return { ok: true, status: 200, json: async () => ({ frases: ['Vale'], listo: true }) };
    }
  };
  await prepararGuion(o, cache, null, () => {});
  assert.strictEqual(veces, 3);
  assert.strictEqual(await cache.get('Vale'), 'tts:Vale');
});

test('guion: con 404 (sin llamada) deja de preguntar', async () => {
  let veces = 0;
  await prepararGuion({ tercero: 'x', ttsService: {}, fetch: async () => { veces++; return { ok: false, status: 404 }; } },
                      new Map(), null, () => {});
  assert.strictEqual(veces, 1);
});

test('el oído de estas llamadas pide el modelo pequeño', async () => {
  const pedidas = [];
  const cliente = { oidoDisponible: () => true, transcribe: async (a, op) => { pedidas.push(op); return 'x'; } };
  const rapido = conModeloRapido(cliente);
  await rapido.transcribe(Buffer.from(''), { soloOido: true });
  assert.deepStrictEqual(pedidas[0], { soloOido: true, rapido: true });
  assert.strictEqual(rapido.oidoDisponible(), true);
});

// ── El buzón de voz ─────────────────────────────────────────────────────────
test('saludo: hablando sin parar a los 3 s es una locución (larga)', async () => {
  const s = detector();
  s._inSpeech = true; s._utteranceChunks = [Buffer.from('el número')];
  const u = await esperarSaludo(s);
  assert.strictEqual(u.larga, true);
});

test('locución: vuelve con la frase entera cuando se cierra', async () => {
  const s = detector();
  s._inSpeech = true; s._utteranceChunks = [Buffer.from('el número')];
  setTimeout(() => s.emit('utterance', { audio: Buffer.from('el número no está disponible') }), 60);
  const u = await esperarLocucion(s);
  assert.strictEqual(u.audio.toString(), 'el número no está disponible');
  assert.strictEqual(u.larga, true);
});

test('pitido: espera a que lleve 1,5 s sin voz', async () => {
  const s = detector();
  s._inSpeech = true;
  setTimeout(() => { s._inSpeech = false; }, 300);
  const t0 = Date.now();
  await esperarSilencio(s);
  const ms = Date.now() - t0;
  assert.ok(ms >= 1750 && ms < 2200, 'tardó ' + ms + ' ms');
});

test('buzón reconocido tarde: en la primera respuesta, recado entero tras el pitido', async () => {
  const e = escena({ oido: ['Tu llamada ha estado forwardada a Voice Mail.',
                            'Si lo estás intentando alcanzar, no es disponible.'], backend: [] });
  let pitido = false;
  e.o.esperarSilencio = async () => { pitido = true; };
  const r = await runConversacionTercero(e.endpoint, e.dialog, 'c1', e.o);
  assert.strictEqual(r.endReason, 'voicemail');
  assert.ok(pitido);
  assert.deepStrictEqual(e.dichos, [e.o.apertura, e.o.apertura, FRASES.recado]);
  assert.strictEqual(e.pedidosBackend.length, 0);
});

test('la locución de Mikel, traducida por el oído, suena a buzón', async () => {
  const e = escenaBuzon('Tu llamada ha estado forwardada a Voice Mail.');
  const r = await runConversacionTercero(e.endpoint, e.dialog, 'c1', e.o);
  assert.strictEqual(r.endReason, 'voicemail');
});

function escenaBuzon(locucion) {
  const e = escena({ oido: [], backend: [] });
  e.o.esperarSaludo = async () => ({ audio: Buffer.from('El número'), larga: true });
  e.o.esperarLocucion = async () => ({ audio: Buffer.from(locucion), larga: true });
  let pitido = false;
  e.o.esperarSilencio = async () => { pitido = true; };
  e.pitido = () => pitido;
  return e;
}

test('buzón: espera al pitido, deja el recado y cuelga sin preguntar al backend', async () => {
  const e = escenaBuzon('El número al que llama no está disponible. Deje su mensaje después de la señal.');
  const r = await runConversacionTercero(e.endpoint, e.dialog, 'c1', e.o);
  assert.strictEqual(r.endReason, 'voicemail');
  assert.ok(e.pitido());
  assert.deepStrictEqual(e.dichos, [e.o.apertura, FRASES.recado]);
  assert.strictEqual(e.pedidosBackend.length, 0);
});

test('una persona que habla mucho al descolgar no es un buzón', async () => {
  const e = escenaBuzon('Hola hola, dime, que estoy conduciendo y te oigo regular');
  e.o.esperarSaludo = async () => ({ audio: Buffer.from('Hola hola'), larga: true });
  const r = await runConversacionTercero(e.endpoint, e.dialog, 'c1', e.o);
  assert.ok(!e.pitido());
  assert.strictEqual(e.dichos[0], e.o.apertura);
  assert.notStrictEqual(r.endReason, 'voicemail');
});

test('si nadie dice nada al descolgar, se presenta igual', async () => {
  const e = escena({ oido: [null, 'Vale'], backend: [{ decir: 'Genial. ¡Adiós!', colgar: true }] });
  const r = await runConversacionTercero(e.endpoint, e.dialog, 'c1', e.o);
  assert.strictEqual(e.dichos[0], e.o.apertura);
  assert.strictEqual(r.endReason, 'goodbye');
});

test('sin backend, se despide y cuelga', async () => {
  const e = escena({ oido: ['¿Sí?', 'Hola'], backend: [{ status: 404 }] });
  const r = await runConversacionTercero(e.endpoint, e.dialog, 'c1', e.o);
  assert.strictEqual(r.endReason, 'error');
  assert.strictEqual(e.dichos[e.dichos.length - 1], FRASES.fallo);
});

test('dos silencios seguidos y cuelga; con uno pregunta si le oye', async () => {
  const e = escena({ oido: ['¿Sí?', null, null], backend: [] });
  const r = await runConversacionTercero(e.endpoint, e.dialog, 'c1', e.o);
  assert.strictEqual(r.endReason, 'silence');
  assert.deepStrictEqual(e.dichos, [e.o.apertura, FRASES.hola]);
});

test('si FreeSWITCH no contesta al cerrar el audio, la conversación acaba igual', async () => {
  const e = escena({ oido: ['¿Sí?', 'Vale'], backend: [{ decir: 'Adiós.', colgar: true }] });
  e.endpoint.forkAudioStop = () => new Promise(() => {});   // el EPIPE: nunca resuelve
  const r = await runConversacionTercero(e.endpoint, e.dialog, 'c1', e.o);
  assert.strictEqual(r.endReason, 'goodbye');
});

test('si cuelga el otro, acaba como hangup sin seguir hablando', async () => {
  const e = escena({ oido: ['¿Sí?', 'Espera'], backend: [] });
  e.o.fetch = async (url) => {
    if (url.endsWith('/guion')) return { ok: true, status: 200, json: async () => ({ frases: [], listo: true }) };
    e.dialog.emit('destroy'); return { ok: true, json: async () => ({ decir: 'x', colgar: false }) };
  };
  const r = await runConversacionTercero(e.endpoint, e.dialog, 'c1', e.o);
  assert.strictEqual(r.endReason, 'hangup');
  assert.deepStrictEqual(e.dichos, [e.o.apertura]);
});
