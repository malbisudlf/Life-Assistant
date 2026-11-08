/**
 * Parche 28: si la primera pregunta llega con el precalentado aún en marcha, se corta
 * ese turno en vez de esperar a su «listo».
 *
 * El Claude falso hace lo que se midió en caja con el de verdad: un `system init` al
 * empezar cada turno, la interrupción corta el turno en curso y suelta su `result` con
 * error, y una interrupción sin turno en curso no hace nada. Se lanza con
 * `node --test test/parche28.test.js` desde claude-api-server/, sin red.
 */
'use strict';

const test = require('node:test');
const assert = require('node:assert');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const { spawn } = require('node:child_process');

const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'parche28-'));
const RECIBIDO = path.join(dir, 'recibido.jsonl');
const CLAUDE_FALSO = path.join(dir, 'claude-falso');
fs.writeFileSync(CLAUDE_FALSO, `#!${process.execPath}
const fs = require('fs');
const apuntar = (x) => fs.appendFileSync(${JSON.stringify(RECIBIDO)}, JSON.stringify(x) + '\\n');
const ARRANQUE_MS = parseInt(process.env.ARRANQUE_MS || '0');
const LISTO_MS = parseInt(process.env.LISTO_MS || '0');
let buf = '', cola = [], enCurso = null, arrancado = false;
setTimeout(() => { arrancado = true; siguiente(); }, ARRANQUE_MS);
function siguiente() {
  if (!arrancado || enCurso || !cola.length) return;
  const texto = cola.shift();
  console.log(JSON.stringify({type:'system', subtype:'init'}));
  const calentar = /responde únicamente «listo»/.test(texto);
  enCurso = setTimeout(() => {
    enCurso = null;
    console.log(JSON.stringify({type:'result', subtype:'success', result: calentar ? 'listo' : '🗣️ VOICE_RESPONSE: eco ' + texto.slice(-12), session_id:'s1'}));
    siguiente();
  }, calentar ? LISTO_MS : 20);
}
process.stdin.on('data', d => {
  buf += d;
  let i;
  while ((i = buf.indexOf('\\n')) >= 0) {
    const l = JSON.parse(buf.slice(0, i)); buf = buf.slice(i + 1);
    if (l.type === 'control_request') {
      apuntar({ corte: true, enCurso: Boolean(enCurso) });
      console.log(JSON.stringify({type:'control_response', response:{subtype:'success', request_id:l.request_id}}));
      if (enCurso) {
        clearTimeout(enCurso); enCurso = null;
        console.log(JSON.stringify({type:'result', subtype:'error_during_execution', is_error:true, result:''}));
        siguiente();
      }
      continue;
    }
    apuntar(l.message.content);
    cola.push(l.message.content);
  }
  siguiente();
});
process.stdin.on('end', () => process.exit(0));
`, { mode: 0o755 });

const recibido = () => fs.existsSync(RECIBIDO)
  ? fs.readFileSync(RECIBIDO, 'utf8').trim().split('\n').map((l) => JSON.parse(l)) : [];
const limpiar = () => { try { fs.unlinkSync(RECIBIDO); } catch { /* no estaba */ } };
const espera = (ms) => new Promise((r) => setTimeout(r, ms));
const LISTO = 'Prepárate. [responde únicamente «listo»]';

// ── La sesión viva por dentro ────────────────────────────────────────────────
function abrir(entorno) {
  const sesionViva = require('../sesion-viva');
  return sesionViva.crear({ bin: process.execPath, args: [CLAUDE_FALSO],
    env: Object.assign({}, process.env, entorno) });
}

test('28: corta el turno en curso y la pregunta sale detrás sin esperarlo', async function () {
  limpiar();
  const s = abrir({ LISTO_MS: '5000' });
  try {
    const calentar = s.preguntar(LISTO);
    await espera(200);
    const t0 = Date.now();
    assert.strictEqual(s.interrumpir(), true);
    const r = await s.preguntar('¿qué tengo mañana?');
    assert.ok(Date.now() - t0 < 1000, 'no espera a los 5 s del «listo»');
    assert.match(r.response, /engo mañana\?$/);
    const c = await calentar;
    assert.strictEqual(c.cortado, true);
    assert.strictEqual(c.isError, true);
    assert.deepStrictEqual(recibido().filter((x) => x.corte), [{ corte: true, enCurso: true }]);
  } finally {
    s.cerrar();
  }
});

test('28: si el turno aún no ha empezado, el corte espera a que empiece', async function () {
  limpiar();
  const s = abrir({ LISTO_MS: '5000', ARRANQUE_MS: '300' });
  try {
    const calentar = s.preguntar(LISTO);
    assert.strictEqual(s.interrumpir(), true);
    assert.strictEqual(s.interrumpir(), false, 'dos veces no corta dos turnos');
    const t0 = Date.now();
    const r = await s.preguntar('¿qué tengo mañana?');
    assert.ok(Date.now() - t0 < 1500);
    assert.match(r.response, /engo mañana\?$/);
    assert.strictEqual((await calentar).cortado, true);
    assert.deepStrictEqual(recibido().filter((x) => x.corte), [{ corte: true, enCurso: true }],
      'el corte llega con el turno ya en marcha, no antes');
  } finally {
    s.cerrar();
  }
});

test('28: sin turno pendiente no hay nada que cortar', async function () {
  limpiar();
  const s = abrir({});
  try {
    assert.strictEqual(s.interrumpir(), false);
    await s.preguntar('hola');
    assert.strictEqual(s.interrumpir(), false);
    assert.strictEqual(recibido().filter((x) => x.corte).length, 0);
  } finally {
    s.cerrar();
  }
});

// ── El puente de verdad ──────────────────────────────────────────────────────
let puerto = 34300;
async function servidor(entorno) {
  limpiar();
  const p = ++puerto;
  const proc = spawn(process.execPath, [path.join(__dirname, '..', 'server.js')], {
    cwd: dir,
    env: Object.assign({}, process.env, { PORT: String(p), CLAUDE_BIN: CLAUDE_FALSO, CONTEXTO_URL: 'http://127.0.0.1:9' }, entorno),
    stdio: ['ignore', 'pipe', 'pipe'],
  });
  let salida = '';
  await new Promise((resolve, reject) => {
    proc.stdout.on('data', (d) => { salida += d; if (/Listening on/.test(d.toString())) resolve(); });
    proc.on('exit', (c) => reject(new Error('server.js salió con ' + c)));
  });
  proc.stdout.on('data', (d) => { salida += d; });
  const url = 'http://127.0.0.1:' + p;
  return {
    pedir: async (ruta, cuerpo) => (await fetch(url + ruta, {
      method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(cuerpo),
    })).json(),
    salida: () => salida,
    parar: () => proc.kill('SIGTERM'),
  };
}

test('28, puente: precalentado lento; la pregunta lo corta y lleva el hilo', async function () {
  const s = await servidor({ LISTO_MS: '8000' });
  try {
    await s.pedir('/precalentar', { callId: 'c1', devicePrompt: 'Eres Jarvis' });
    await espera(300);
    const t0 = Date.now();
    const r = await s.pedir('/ask', { prompt: '¿qué tengo mañana?', callId: 'c1', devicePrompt: 'Eres Jarvis' });
    assert.ok(Date.now() - t0 < 2000, 'no espera a los 8 s del «listo»');
    assert.strictEqual(r.success, true);
    assert.match(r.response, /engo mañana\?$/);
    const r2 = await s.pedir('/ask', { prompt: '¿y pasado?', callId: 'c1', devicePrompt: 'Eres Jarvis' });
    assert.match(r2.response, /y pasado\?$/);
    await espera(100);
    const m = recibido().filter((x) => typeof x === 'string');
    assert.strictEqual(m.length, 3);
    assert.match(m[0], /responde únicamente «listo»/);
    for (const t of m.slice(1)) {
      assert.doesNotMatch(t, /llamadas recientes|CONTEXTO AL DESCOLGAR|responde únicamente/i,
        'cortado no es fallido: el contexto no se repite');
    }
    assert.match(s.salida(), /PRECALENTAR cortado por la pregunta/);
    assert.doesNotMatch(s.salida(), /PRECALENTAR falló/);
  } finally {
    s.parar();
  }
});

test('28, puente: si el precalentado ya acabó, no se corta nada', async function () {
  const s = await servidor({ LISTO_MS: '50' });
  try {
    await s.pedir('/precalentar', { callId: 'c2', devicePrompt: 'Eres Jarvis' });
    await espera(500);
    const r = await s.pedir('/ask', { prompt: 'hola', callId: 'c2', devicePrompt: 'Eres Jarvis' });
    assert.match(r.response, /hola$/);
    assert.strictEqual(recibido().filter((x) => x.corte).length, 0);
    assert.match(s.salida(), /PRECALENTADA c2/);
  } finally {
    s.parar();
  }
});
