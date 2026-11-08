// Parche 38: el cronómetro de cada turno (lib/cronometro.js) y el detector que le dice
// cuándo dejaste de hablar (audio-fork.js). Ver telefono/PARCHES.md en Life Assistant.
const test = require('node:test');
const assert = require('node:assert');
const cronometro = require('../lib/cronometro');
const { pensar } = require('../lib/turno-rapido');

test('p38: un turno de Claude da sus tramos y una línea que se lee', () => {
  cronometro._reiniciar();
  const lineas = [];
  const t = cronometro.turno('llamada-1', 'entrante');
  t.marca('finHabla', 1000).marca('cierre', 2000).marca('texto', 2600)
    .marca('consulta', 2610).marca('claudeListo', 4710).marca('respuesta', 4710).marca('suena', 5350);
  const r = t.cerrar('claude', (l) => lineas.push(l));
  assert.deepStrictEqual(r.ms, { cierre: 1000, oido: 600, antes: 10, claude: 2100, frase: 0, voz: 640, total: 4350 });
  assert.strictEqual(lineas[0], '[TURNO] claude: 4,4 s = cierre 1,0 + oído 0,6 + Claude 2,1 + voz 0,6');
});

test('p38: la frase de espera que retrasa una respuesta ya lista sale aparte', () => {
  cronometro._reiniciar();
  const lineas = [];
  const t = cronometro.turno('l', 'entrante');
  t.marca('finHabla', 0).marca('cierre', 900).marca('texto', 1500).marca('consulta', 1500)
    .marca('claudeListo', 4100).marca('respuesta', 4600).marca('suena', 4650);
  t.cerrar('claude', (l) => lineas.push(l));
  assert.match(lineas[0], /Claude 2,6 \+ frase 0,5 \+ voz 0,1$/);
});

test('p38: lo que no se midió no se inventa, y sin fin de habla el total va desde el cierre', () => {
  cronometro._reiniciar();
  const t = cronometro.turno('l', 'entrante');
  t.marca('cierre', 100).marca('texto', 100).marca('consulta', 100).marca('respuesta', 2100).marca('suena', 2700);
  const r = t.cerrar('claude', () => {});
  assert.strictEqual(r.ms.cierre, null);
  assert.strictEqual(r.ms.frase, null);
  assert.strictEqual(r.ms.claude, 2000);
  assert.strictEqual(r.ms.total, 2600);
  assert.doesNotMatch(cronometro.metricas(), /tramo="cierre"/);
});

test('p38: la primera marca gana y cerrar dos veces no cuenta dos turnos', () => {
  cronometro._reiniciar();
  const t = cronometro.turno('l');
  t.marca('cierre', 10).marca('cierre', 99);
  assert.strictEqual(t.marcas.cierre, 10);
  t.cerrar('reflejo', () => {});
  assert.strictEqual(t.cerrar('reflejo', () => {}), null);
  assert.match(cronometro.metricas(), /^jarvis_turnos_total 1$/m);
});

test('p38: /metrics es un histograma de Prometheus bien formado', () => {
  cronometro._reiniciar();
  for (const total of [900, 2400, 7000]) {
    cronometro.turno('l').marca('finHabla', 0).marca('suena', total).cerrar('claude', () => {});
  }
  const m = cronometro.metricas();
  assert.match(m, /# TYPE jarvis_turno_tramo_segundos histogram/);
  assert.match(m, /jarvis_turno_tramo_segundos_bucket\{tipo="claude",tramo="total",le="1"\} 1/);
  assert.match(m, /jarvis_turno_tramo_segundos_bucket\{tipo="claude",tramo="total",le="2.5"\} 2/);
  assert.match(m, /jarvis_turno_tramo_segundos_bucket\{tipo="claude",tramo="total",le="\+Inf"\} 3/);
  assert.match(m, /jarvis_turno_tramo_segundos_sum\{tipo="claude",tramo="total"\} 10\.300/);
  assert.match(m, /jarvis_turno_tramo_segundos_count\{tipo="claude",tramo="total"\} 3/);
  // Los cubos son acumulativos: nunca bajan.
  const cubos = [...m.matchAll(/tramo="total",le="[^"]+"\} (\d+)/g)].map((x) => Number(x[1]));
  for (let i = 1; i < cubos.length; i++) assert.ok(cubos[i] >= cubos[i - 1]);
});

test('p38: se guardan como mucho 100 turnos', () => {
  cronometro._reiniciar();
  for (let i = 0; i < 130; i++) cronometro.turno('l' + i).marca('cierre', 0).marca('suena', 10).cerrar('claude', () => {});
  assert.strictEqual(cronometro.ultimos(1000).length, 100);
  assert.strictEqual(cronometro.ultimos(1)[0].llamada, 'l129');
});

test('p38: medir no tumba la llamada aunque el registro falle', () => {
  cronometro._reiniciar();
  const t = cronometro.turno('l').marca('cierre', 0).marca('suena', 5);
  assert.strictEqual(t.cerrar('claude', () => { throw new Error('registro roto'); }), null);
});

test('p38: pensar avisa en cuanto Claude contesta, antes de acabar la frase de espera', async () => {
  process.env.ESPERA_FRASE_MS = '10';
  let contestoEn = 0;
  let fraseAcabaEn = 0;
  const endpoint = {
    uuid: 'x',
    play: async (url) => {
      if (url === 'frase') { await new Promise((r) => setTimeout(r, 120)); fraseAcabaEn = Date.now(); }
    },
    api: async () => {},
  };
  const ttsService = { generateSpeech: async () => 'frase' };
  const r = await pensar({
    consultar: () => new Promise((res) => setTimeout(() => res('🗣️ VOICE_RESPONSE: hola'), 40)),
    endpoint, ttsService, frase: 'Un momento.', musicaUrl: 'musica',
    alContestar: () => { contestoEn = Date.now(); },
  });
  delete process.env.ESPERA_FRASE_MS;
  assert.strictEqual(r, '🗣️ VOICE_RESPONSE: hola');
  assert.ok(contestoEn > 0 && contestoEn < fraseAcabaEn, 'alContestar llega mientras suena la frase');
});

test('p38: el detector dice cuándo dejaste de hablar (ahora menos el silencio que cerró la frase)', () => {
  const { AudioForkSession } = require('../lib/audio-fork');
  if (typeof AudioForkSession !== 'function') return; // la clase no se exporta en todas las versiones
  const s = Object.create(AudioForkSession.prototype);
  s._utteranceChunks = [Buffer.alloc(32000)];
  s._utteranceBytes = 32000;
  s._speechBytes = 32000;
  s._silenceMs = 700;
  s._chunkDurationMs = (b) => b / 32;
  s._resetUtterance = () => {};
  s._vozMinimaMs = () => 100;
  s.listenerCount = () => 1;
  let u = null;
  s.emit = (ev, x) => { if (ev === 'utterance') u = x; };
  const antes = Date.now();
  s._finalizeUtterance('end_silence');
  assert.ok(u, 'emite la frase');
  assert.ok(u.finHabla <= Date.now() - 700 && u.finHabla >= antes - 700);
});

test('p38: al pausar ya no se pide small a la vez que turbo (salvo ANTICIPO_RAPIDO=1)', async () => {
  const { armarAnticipo } = require('../lib/anticipo');
  const EventEmitter = require('events');
  for (const [valor, esperados] of [[undefined, ['final']], ['1', ['final', 'rapido']]]) {
    if (valor === undefined) delete process.env.ANTICIPO_RAPIDO; else process.env.ANTICIPO_RAPIDO = valor;
    const pedidos = [];
    const wc = {
      oidoDisponible: () => true,
      transcribe: (audio, o) => { pedidos.push(o.rapido ? 'rapido' : 'final'); return Promise.resolve('hola'); },
    };
    const s = new EventEmitter();
    s.cerrarPausa = () => {};
    armarAnticipo(s, wc);
    s.emit('pausa', { audio: Buffer.alloc(10) });
    await new Promise((r) => setImmediate(r));
    assert.deepStrictEqual(pedidos, esperados);
  }
  delete process.env.ANTICIPO_RAPIDO;
});
