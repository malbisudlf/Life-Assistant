/**
 * Parche 27: la sesión de la llamada se precalienta al descolgar (POST /precalentar).
 *
 * Arranca server.js de verdad, en un directorio temporal y con un Claude de mentira que
 * apunta lo que recibe y contesta un `result` por mensaje, como el de parche19.test.js.
 * Se lanza con `node --test test/parche27.test.js` desde claude-api-server/, sin red.
 */
'use strict';

const test = require('node:test');
const assert = require('node:assert');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const { spawn } = require('node:child_process');

const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'parche27-'));
const RECIBIDO = path.join(dir, 'recibido.jsonl');
const CLAUDE_FALSO = path.join(dir, 'claude-falso');
fs.writeFileSync(CLAUDE_FALSO, `#!${process.execPath}
const fs = require('fs');
let buf = '';
process.stdin.on('data', d => {
  buf += d;
  let i;
  while ((i = buf.indexOf('\\n')) >= 0) {
    const linea = JSON.parse(buf.slice(0, i)); buf = buf.slice(i + 1);
    if (linea.type !== 'user') continue;          // las órdenes de corte del parche 28
    const texto = linea.message.content;
    fs.appendFileSync(${JSON.stringify(RECIBIDO)}, JSON.stringify(texto) + '\\n');
    const calentar = /responde únicamente «listo»/.test(texto);
    if (calentar && process.env.FALLA_PRECALENTAR) {
      console.log(JSON.stringify({type:'result', is_error:true, result:'OAuth session expired'}));
    } else {
      console.log(JSON.stringify({type:'result', result: calentar ? 'listo' : '🗣️ VOICE_RESPONSE: eco ' + texto.slice(-12), session_id:'s1'}));
    }
  }
});
process.stdin.on('end', () => process.exit(0));
`, { mode: 0o755 });

let puerto = 34100;
async function servidor(entorno) {
  try { fs.unlinkSync(RECIBIDO); } catch { /* no estaba */ }
  const p = ++puerto;
  const proc = spawn(process.execPath, [path.join(__dirname, '..', 'server.js')], {
    cwd: dir,
    env: Object.assign({}, process.env, { PORT: String(p), CLAUDE_BIN: CLAUDE_FALSO, CONTEXTO_URL: 'http://127.0.0.1:9' }, entorno),
    stdio: ['ignore', 'pipe', 'pipe'],
  });
  await new Promise((resolve, reject) => {
    proc.stdout.on('data', (d) => { if (/Listening on/.test(d.toString())) resolve(); });
    proc.on('exit', (c) => reject(new Error('server.js salió con ' + c)));
  });
  const url = 'http://127.0.0.1:' + p;
  return {
    pedir: async (ruta, cuerpo) => (await fetch(url + ruta, {
      method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(cuerpo),
    })).json(),
    recibido: () => fs.existsSync(RECIBIDO)
      ? fs.readFileSync(RECIBIDO, 'utf8').trim().split('\n').map((l) => JSON.parse(l)) : [],
    parar: () => proc.kill('SIGTERM'),
  };
}
const espera = (ms) => new Promise((r) => setTimeout(r, ms));

test('precalentar contesta al momento, y la primera pregunta va detrás de su turno', async function () {
  const s = await servidor();
  try {
    assert.deepStrictEqual(await s.pedir('/precalentar', { callId: 'c1', devicePrompt: 'Eres Jarvis' }), { success: true });
    const r = await s.pedir('/ask', { prompt: '¿qué tengo hoy?', callId: 'c1', devicePrompt: 'Eres Jarvis' });
    assert.strictEqual(r.success, true);
    assert.match(r.response, /tengo hoy\?$/,'la respuesta es la de la pregunta, no la de precalentar');
    const m = s.recibido();
    assert.strictEqual(m.length, 2);
    assert.match(m[0], /\[DEVICE IDENTITY\]\nEres Jarvis/);
    assert.match(m[0], /responde únicamente «listo»/);
    assert.doesNotMatch(m[1], /llamadas recientes|CONTEXTO AL DESCOLGAR/i, 'el contexto no se repite');
  } finally {
    s.parar();
  }
});

test('dos veces, o sin callId, no arranca nada de más', async function () {
  const s = await servidor();
  try {
    await s.pedir('/precalentar', { callId: 'c2' });
    assert.deepStrictEqual(await s.pedir('/precalentar', { callId: 'c2' }), { success: true, yaEstaba: true });
    assert.strictEqual((await s.pedir('/precalentar', {})).success, false);
    await espera(300);
    assert.strictEqual(s.recibido().length, 1);
  } finally {
    s.parar();
  }
});

test('si precalentar falla, la primera pregunta empieza de cero con su contexto', async function () {
  const s = await servidor({ FALLA_PRECALENTAR: '1' });
  try {
    await s.pedir('/precalentar', { callId: 'c3', devicePrompt: 'Eres Jarvis' });
    await espera(500);
    const r = await s.pedir('/ask', { prompt: 'hola', callId: 'c3', devicePrompt: 'Eres Jarvis' });
    assert.strictEqual(r.success, true);
    assert.match(r.response, /hola$/);
  } finally {
    s.parar();
  }
});

test('con SESION_VIVA=0 no hay precalentado y /ask sigue como siempre', async function () {
  const s = await servidor({ SESION_VIVA: '0' });
  try {
    assert.strictEqual((await s.pedir('/precalentar', { callId: 'c4' })).success, false);
    await espera(200);
    assert.strictEqual(s.recibido().length, 0);
  } finally {
    s.parar();
  }
});
