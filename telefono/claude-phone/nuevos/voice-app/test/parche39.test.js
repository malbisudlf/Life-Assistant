// Parche 39: la consulta a Mikel sin colgar al otro (dos llamadas a la vez).
// Ver «El parche 39» en telefono/PARCHES.md de Life Assistant.
const test = require('node:test');
const assert = require('node:assert');
const { EventEmitter } = require('node:events');
const { runConversacionTercero, preguntarAlBackend, esperarConsulta, FRASES } = require('../lib/conversacion-tercero');

const TID = '11111111-2222-3333-4444-555555555555';

function respuesta(cuerpo, status) {
  return { ok: (status || 200) < 300, status: status || 200, json: async () => cuerpo };
}

test('p39: el backend puede pedir que se espere (y si cuelga, no se espera)', async () => {
  const pedir = (d) => preguntarAlBackend(TID, 'hola', { fetch: async () => respuesta(d) });
  assert.deepStrictEqual(await pedir({ decir: 'Un segundo.', colgar: false, esperar: true }),
    { decir: 'Un segundo.', colgar: false, esperar: true });
  assert.strictEqual((await pedir({ decir: 'Adiós.', colgar: true, esperar: true })).esperar, false);
  assert.strictEqual((await pedir({ decir: 'Vale.', colgar: false })).esperar, false);
});

test('p39: esperarConsulta pregunta hasta que hay respuesta, con música y sin recordar antes de tiempo', async () => {
  const cola = [{ listo: false }, { listo: false }, { listo: true, decir: 'Perfecto, el jueves.', colgar: true }];
  const urls = [];
  const musica = [];
  let t = 0;
  const r = await esperarConsulta(TID, {
    fetch: async (url) => { urls.push(url); return respuesta(cola.shift()); },
    dormir: async (ms) => { t += ms; },
    ahora: () => t,
    musica: (on) => musica.push(on),
    recordar: async () => { throw new Error('no hacía falta recordar'); }
  });
  assert.deepStrictEqual(r, { decir: 'Perfecto, el jueves.', colgar: true });
  assert.strictEqual(urls.length, 3);
  assert.ok(urls[0].endsWith('/telefono/tercero/' + TID + '/consulta'));
  assert.deepStrictEqual(musica, [true, false]);
});

test('p39: cada medio minuto le dice al otro que sigue ahí, cortando la música', async () => {
  let t = 0;
  const cola = Array.from({ length: 20 }, () => ({ listo: false })).concat([{ listo: true, decir: 'Vale.', colgar: false }]);
  const pasos = [];
  await esperarConsulta(TID, {
    fetch: async () => respuesta(cola.shift()),
    dormir: async (ms) => { t += ms; },
    ahora: () => t,
    musica: (on) => pasos.push(on ? 'música' : 'silencio'),
    recordar: async () => pasos.push('sigo aquí')
  });
  assert.ok(pasos.includes('sigo aquí'));
  const i = pasos.indexOf('sigo aquí');
  assert.deepStrictEqual(pasos.slice(i - 1, i + 2), ['silencio', 'sigo aquí', 'música']);
  assert.strictEqual(pasos[pasos.length - 1], 'silencio');
});

test('p39: tres fallos seguidos del backend, o el tope, acaban en la despedida de fallo', async () => {
  let t = 0;
  const caido = await esperarConsulta(TID, {
    fetch: async () => { throw new Error('ECONNREFUSED'); },
    dormir: async (ms) => { t += ms; }, ahora: () => t
  });
  assert.deepStrictEqual(caido, { decir: FRASES.fallo, colgar: true, fallo: true });
  t = 0;
  const tope = await esperarConsulta(TID, {
    fetch: async () => respuesta({ listo: false }),
    dormir: async (ms) => { t += ms; }, ahora: () => t, topeMs: 10000
  });
  assert.strictEqual(tope.fallo, true);
});

test('p39: si cuelgan mientras espera, se deja de esperar', async () => {
  let viva = true;
  const r = await esperarConsulta(TID, {
    fetch: async () => { viva = false; return respuesta({ listo: false }); },
    dormir: async () => {}, sigueActiva: () => viva
  });
  assert.strictEqual(r.colgada, true);
});

test('p39: en la llamada, «un segundo», música, la respuesta de Mikel y adiós', async () => {
  const dialog = new EventEmitter();
  const sesion = new EventEmitter();
  const oido = ['¿Sí?', 'Solo tengo el jueves a las nueve'];
  sesion.setCaptureEnabled = () => {};
  sesion.waitForUtterance = async () => {
    const tx = oido.length ? oido.shift() : null;
    if (tx === null) throw new Error('timeout');
    return { audio: Buffer.from(tx) };
  };
  const sonado = [];
  const endpoint = {
    uuid: 'u', async forkAudioStart() {}, async forkAudioStop() {},
    async play(url) { sonado.push(url.replace('tts:', '')); },
    async api() { sonado.push('(corta la música)'); }
  };
  const consultas = [{ listo: false }, { listo: true, decir: 'Perfecto, el jueves a las nueve. ¡Gracias!', colgar: true }];
  const r = await runConversacionTercero(endpoint, dialog, 'c1', {
    audioForkServer: { expectSession: async () => sesion, cancelExpectation() {} },
    whisperClient: { transcribe: async (a) => a.toString() },
    ttsService: { generateSpeech: async (tx) => 'tts:' + tx },
    wsPort: 3001, tercero: TID, apertura: 'Hola, soy Jarvis.', musicaUrl: 'MUSICA',
    esperarSaludo: (s) => s.waitForUtterance({ timeoutMs: 1 }).catch(() => null),
    dormir: async () => {},
    fetch: async (url) => {
      if (url.endsWith('/guion')) return respuesta({ frases: [], listo: true });
      if (url.endsWith('/turno')) return respuesta({ decir: 'Un segundo, que se lo consulto a Mikel.', colgar: false, esperar: true });
      if (url.endsWith('/consulta')) return respuesta(consultas.shift());
      throw new Error('url inesperada ' + url);
    }
  });
  await new Promise((res) => setImmediate(res));
  assert.strictEqual(r.endReason, 'goodbye');
  const sin = sonado.filter((x) => x !== '(corta la música)');
  assert.deepStrictEqual(sin, ['Hola, soy Jarvis.', 'Un segundo, que se lo consulto a Mikel.', 'MUSICA',
                               'Perfecto, el jueves a las nueve. ¡Gracias!']);
  assert.ok(sonado.includes('(corta la música)'));
});
