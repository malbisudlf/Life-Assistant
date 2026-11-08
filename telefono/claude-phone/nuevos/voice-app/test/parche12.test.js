/**
 * Parche 12: contestar no es coger, y una llamada descolgada se cuelga siempre.
 *
 * Se prueba sin llamar a nadie: la centralita (drachtio), FreeSWITCH, la voz
 * (ElevenLabs), el oído (audio fork) y Whisper son dobles; lo que corre es el código
 * de verdad de lib/. Se lanza con `node --test test/parche12.test.js` (el fichero, no
 * el directorio: en Node 22+ `node --test test/` no lo encuentra). En caja, dentro de
 * la imagen recién construida y sin red: ver telefono/PARCHES.md, «El parche 12».
 */
'use strict';

const test = require('node:test');
const assert = require('node:assert');
const Module = require('node:module');
const crypto = require('node:crypto');
const { EventEmitter } = require('node:events');

// ── Dobles, enganchados ANTES de cargar nada de lib/ ─────────────────────────
// El tts-service de verdad llama a ElevenLabs y deja un setInterval vivo; express y
// uuid se sustituyen para que el test no dependa de node_modules.
const voz = { rota: false, dichas: [] };
const ttsFalso = {
  generateSpeech: async function (texto) {
    if (voz.rota) throw new Error('TTS generation failed: getaddrinfo EAI_AGAIN api.elevenlabs.io');
    voz.dichas.push(texto);
    return 'http://127.0.0.1/audio.mp3';
  }
};
const rutas = {};
const expressFalso = {
  Router: function () {
    return {
      post: function (ruta, fn) { rutas['POST ' + ruta] = fn; },
      get: function (ruta, fn) { rutas['GET ' + ruta] = fn; }
    };
  }
};
const requireDeVerdad = Module.prototype.require;
Module.prototype.require = function (id) {
  if (id === 'express') return expressFalso;
  if (id === 'uuid') return { v4: function () { return crypto.randomUUID(); } };
  if (id === './tts-service') return ttsFalso;
  return requireDeVerdad.apply(this, arguments);
};
// La bitácora avisa por fetch al claude-api-server: aquí no sale nada.
globalThis.fetch = async function () { return { ok: true }; };
// El log de claude-phone, a una lista: así se puede comprobar lo que deja escrito.
const registro = [];
for (const nivel of ['log', 'warn', 'error']) {
  console[nivel] = function () { registro.push(Array.from(arguments).join(' ')); };
}

const { OutboundSession, getSession } = require('../lib/outbound-session');
const { quienContesta } = require('../lib/outbound-handler');
const { setupRoutes } = require('../lib/outbound-routes');

// Los Contact tal como los manda el 3CX, con los datos cambiados.
const PERSONA = '"Mikel" <sip:10000@192.0.2.10:5060>';
const BUZON = '<sip:10000@192.0.2.10:5060>';

function centralita(opciones) {
  const hecho = { endpoints: [], dialogos: [], invites: 0 };
  const mediaServer = {
    createEndpoint: async function () {
      const ep = new EventEmitter();
      ep.local = { sdp: 'v=0' };
      ep.uuid = 'ep-' + hecho.endpoints.length;
      ep.destruido = false;
      ep.modify = async function () {
        if (opciones.falloModify) throw new Error('endpoint no longer active');
      };
      ep.play = async function () {};
      ep.api = async function () {};
      ep.forkAudioStart = async function () {};
      ep.forkAudioStop = async function () {};
      ep.destroy = async function () { ep.destruido = true; };
      hecho.endpoints.push(ep);
      return ep;
    }
  };
  const srf = {
    createUAC: async function (uri, opts, cbs) {
      hecho.invites++;
      cbs.cbRequest(null, { cancel: function () {} });
      if (!opciones.contesta) {
        const e = new Error('Temporarily Unavailable');
        e.status = 480;
        throw e;
      }
      const uac = new EventEmitter();
      uac.res = { get: function (h) { return h === 'Contact' ? opciones.contact : ''; } };
      uac.remote = { sdp: 'v=0' };
      uac.colgado = false;
      uac.destroy = async function () { uac.colgado = true; };
      hecho.dialogos.push(uac);
      return uac;
    }
  };
  return { srf: srf, mediaServer: mediaServer, hecho: hecho };
}

/** El otro lado de la línea: lo que dice en cada turno (null = silencio). */
function oido(frases) {
  let i = 0;
  const sesion = {
    setCaptureEnabled: function () {},
    forceFinalize: function () {},
    waitForUtterance: async function () {
      const f = frases[i++];
      if (f == null) throw new Error('Timed out waiting for utterance');
      return { audio: Buffer.from(f), reason: 'end_silence' };
    }
  };
  return {
    expectSession: async function () { return sesion; },
    cancelExpectation: function () {},
    emit: function () {}
  };
}

const whisper = { transcribe: async function (audio) { return audio.toString(); } };
const claude = {
  query: async function () { return '🗣️ VOICE_RESPONSE: Vale.'; },
  endSession: async function () {}
};

async function llamar(cuerpo, opciones, frases) {
  // Cada llamada empieza limpia (sin beforeEach: los hooks de raíz de node:test han
  // cambiado entre versiones, y la imagen de caja lleva Node 20).
  voz.rota = !!opciones.vozRota;
  voz.dichas.length = 0;
  registro.length = 0;
  const c = centralita(opciones);
  setupRoutes({ srf: c.srf, mediaServer: c.mediaServer, audioForkServer: oido(frases || []),
                whisperClient: whisper, claudeBridge: claude, ttsService: ttsFalso });
  let respuesta = null;
  let codigo = 200;
  const res = {
    status: function (n) { codigo = n; return res; },
    json: function (d) { respuesta = d; return res; }
  };
  await rutas['POST /outbound-call']({ body: cuerpo }, res);
  if (codigo !== 200) return { codigo: codigo, respuesta: respuesta, hecho: c.hecho };
  // El resto corre en segundo plano, igual que en caja: se espera a que acabe.
  const limite = Date.now() + 3000;
  while (Date.now() < limite) {
    const s = getSession(respuesta.callId);
    if (s && (s.state === 'COMPLETED' || s.state === 'FAILED')) {
      await new Promise(function (r) { setTimeout(r, 20); });   // lo que va tras el final
      return { codigo: codigo, sesion: s, info: s.getInfo(), hecho: c.hecho };
    }
    await new Promise(function (r) { setTimeout(r, 5); });
  }
  throw new Error('la llamada no terminó');
}

const CONVERSACION = { to: '10000', message: 'Mikel, soy Jarvis. La web lleva un rato caída.',
                       mode: 'conversation', timeoutSeconds: 14 };
const RECADO = 'Mikel, soy Jarvis. Te he llamado y no lo has cogido, así que te lo dejo aquí.';

test('quién descuelga, por el Contact del 200 OK', function () {
  assert.strictEqual(quienContesta(PERSONA), 'person');
  assert.strictEqual(quienContesta('Mikel <sip:10000@192.0.2.10>'), 'person');
  assert.strictEqual(quienContesta(BUZON), 'voicemail');
  assert.strictEqual(quienContesta('  ' + BUZON), 'voicemail');
  // Ante la duda, 'unknown': se conversa como siempre.
  assert.strictEqual(quienContesta('sip:10000@192.0.2.10'), 'unknown');
  assert.strictEqual(quienContesta(''), 'unknown');
  assert.strictEqual(quienContesta(undefined), 'unknown');
});

test('la sesión dice quién descolgó y cuántas veces habló alguien, desde el principio', function () {
  const s = new OutboundSession(null, { to: '10000', message: 'x', mode: 'conversation' });
  const info = s.getInfo();
  assert.ok('answeredBy' in info, 'la clave va siempre: es la marca del parche 12');
  assert.strictEqual(info.answeredBy, null);
  assert.strictEqual(info.userTurns, 0);
});

test('un final es final: el BYE de después no lo reescribe', function () {
  const s = new OutboundSession(null, { to: '10000', message: 'x', mode: 'conversation' });
  s.transition('DIALING');
  s.transition('FAILED', 'unplayed');
  s.transition('COMPLETED', 'remote_hangup');
  assert.strictEqual(s.state, 'FAILED');
  assert.strictEqual(s.reason, 'unplayed');
});

test('27/09: descuelga el buzón, la voz falla y se CUELGA (antes quedaba abierta)', async function () {
  const r = await llamar(CONVERSACION, { contesta: true, contact: BUZON, vozRota: true });
  // Lo primero, lo que falló de verdad: contra el código de caja, esto es lo que rompe.
  assert.ok(r.hecho.dialogos[0].colgado, 'la pata SIP tiene que colgarse');
  assert.ok(r.hecho.endpoints[0].destruido);
  assert.strictEqual(r.info.state, 'FAILED');
  assert.strictEqual(r.info.reason, 'unplayed');
  assert.strictEqual(r.info.answeredBy, 'voicemail');
});

test('con detectVoicemail y recado: el buzón se queda con el recado y no se conversa', async function () {
  const r = await llamar(Object.assign({}, CONVERSACION, {
    detectVoicemail: true, voicemailMessage: RECADO, voicemailDelaySeconds: 0
  }), { contesta: true, contact: BUZON });
  assert.strictEqual(r.info.state, 'COMPLETED');
  assert.strictEqual(r.info.reason, 'voicemail_message');
  assert.strictEqual(r.info.answeredBy, 'voicemail');
  assert.deepStrictEqual(voz.dichas, [RECADO]);
  assert.strictEqual(r.info.message, RECADO, 'la bitácora apunta lo que se dejó de verdad');
  assert.ok(r.hecho.dialogos[0].colgado);
});

test('con detectVoicemail sin recado: se cuelga sin decir nada', async function () {
  const r = await llamar(Object.assign({}, CONVERSACION, { detectVoicemail: true }),
                         { contesta: true, contact: BUZON });
  assert.strictEqual(r.info.state, 'FAILED');
  assert.strictEqual(r.info.reason, 'voicemail');
  assert.deepStrictEqual(voz.dichas, []);
  assert.ok(r.hecho.dialogos[0].colgado);
});

test('sin detectVoicemail, el buzón no cambia nada: se conversa y acaba en no_speech', async function () {
  const r = await llamar(CONVERSACION, { contesta: true, contact: BUZON }, [null, null]);
  assert.strictEqual(r.info.state, 'COMPLETED');
  assert.strictEqual(r.info.reason, 'no_speech');
  assert.strictEqual(r.info.userTurns, 0);
  assert.strictEqual(r.info.answeredBy, 'voicemail');
  assert.ok(voz.dichas.includes(CONVERSACION.message));
});

test('si descuelga una persona, detectVoicemail no la toca', async function () {
  const r = await llamar(Object.assign({}, CONVERSACION, {
    detectVoicemail: true, voicemailMessage: RECADO, voicemailDelaySeconds: 0
  }), { contesta: true, contact: PERSONA }, ['sí, dime', 'vale, adiós']);
  assert.strictEqual(r.info.state, 'COMPLETED');
  assert.strictEqual(r.info.reason, 'conversation_complete');
  assert.strictEqual(r.info.answeredBy, 'person');
  assert.strictEqual(r.info.userTurns, 2);
  assert.ok(!voz.dichas.includes(RECADO));
});

test('descuelga una persona y no dice nada: no_speech sin turnos, pero answeredBy person (el backend lo da por cogida)', async function () {
  // Mikel coge, oye el mensaje y no dice nada que se transcriba: habló encima del primer
  // mensaje, o un «sí» tan bajo que no se oyó. claude-phone no decide si eso es cogerla;
  // lo que tiene que hacer es contarlo tal cual, con answeredBy, para que el backend no
  // vuelva a llamar a quien ya ha cogido.
  const r = await llamar(Object.assign({}, CONVERSACION, {
    detectVoicemail: true, voicemailMessage: RECADO, voicemailDelaySeconds: 0
  }), { contesta: true, contact: PERSONA }, [null, null]);
  assert.strictEqual(r.info.state, 'COMPLETED');
  assert.strictEqual(r.info.reason, 'no_speech');
  assert.strictEqual(r.info.answeredBy, 'person');
  assert.strictEqual(r.info.userTurns, 0);
  assert.ok(!voz.dichas.includes(RECADO), 'a una persona no se le deja el recado');
});

test('habló y luego se calló: no_speech, pero con turnos (el backend lo da por cogida)', async function () {
  const r = await llamar(CONVERSACION, { contesta: true, contact: PERSONA },
                         ['sí, dime', null, null]);
  assert.strictEqual(r.info.reason, 'no_speech');
  assert.strictEqual(r.info.userTurns, 1);
});

test('si falla el audio después de descolgar, también se cuelga', async function () {
  const r = await llamar(CONVERSACION, { contesta: true, contact: PERSONA, falloModify: true });
  assert.ok(r.hecho.dialogos[0].colgado, 'antes el catch solo destruía el endpoint');
  assert.strictEqual(r.info.state, 'FAILED');
  assert.strictEqual(r.info.reason, 'unplayed');
});

test('si no lo coge nadie, sigue siendo no_answer y nadie ha descolgado', async function () {
  const r = await llamar(CONVERSACION, { contesta: false });
  assert.strictEqual(r.info.state, 'FAILED');
  assert.strictEqual(r.info.reason, 'no_answer');
  assert.strictEqual(r.info.answeredBy, null);
});

test('un recado que no es texto se rechaza con 400', async function () {
  const r = await llamar(Object.assign({}, CONVERSACION, {
    detectVoicemail: true, voicemailMessage: 'x'.repeat(1001)
  }), { contesta: true, contact: BUZON });
  assert.strictEqual(r.codigo, 400);
  assert.strictEqual(r.hecho.invites, 0);
});

test('el Contact queda en el log de cada llamada contestada', async function () {
  await llamar(CONVERSACION, { contesta: true, contact: PERSONA }, ['adiós']);
  assert.ok(registro.some(function (l) { return l.includes('Quién descuelga') && l.includes('person'); }));
});

test('GET /api/call/:id: lo que lee el backend, por la ruta de verdad', async function () {
  const r = await llamar(CONVERSACION, { contesta: true, contact: PERSONA }, ['sí, dime', 'adiós']);
  let codigo = 200;
  let cuerpo = null;
  const res = {
    status: function (n) { codigo = n; return res; },
    json: function (d) { cuerpo = d; return res; }
  };
  rutas['GET /call/:callId']({ params: { callId: r.sesion.callId } }, res);
  assert.strictEqual(codigo, 200);
  assert.strictEqual(cuerpo.data.state, 'COMPLETED');
  assert.strictEqual(cuerpo.data.reason, 'conversation_complete');
  assert.strictEqual(cuerpo.data.answeredBy, 'person');
  assert.strictEqual(cuerpo.data.userTurns, 2);
  assert.ok(cuerpo.data.answeredAt, 'answeredAt sigue ahí para el backend sin el 12');
});
