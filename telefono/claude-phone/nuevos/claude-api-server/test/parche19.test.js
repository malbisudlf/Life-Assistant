/**
 * Parche 19: la sesión viva (un proceso de Claude por llamada) y el contexto al descolgar.
 *
 * Claude es un doble: un script de Node que lee los mensajes stream-json de stdin y
 * contesta un `result` por cada uno, como hace `claude -p --input-format stream-json`.
 * Se lanza con `node --test test/parche19.test.js` desde claude-api-server/, sin red.
 */
'use strict';

const test = require('node:test');
const assert = require('node:assert');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');

for (const nivel of ['log', 'warn', 'error']) console[nivel] = function () {};

const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'parche19-'));
const CLAUDE_FALSO = path.join(dir, 'claude-falso.js');
fs.writeFileSync(CLAUDE_FALSO, `
// Como el de verdad: un turno detrás de otro, nunca dos a la vez.
let buf = '';
const cola = [];
let ocupado = false;
function siguiente() {
  if (ocupado || !cola.length) return;
  ocupado = true;
  const texto = cola.shift();
  if (texto === 'muere') process.exit(3);
  if (texto === 'cuelgate') return;
  const espera = texto === 'lento' ? 150 : 0;
  setTimeout(() => {
    if (texto === 'error') console.log(JSON.stringify({type:'result', is_error:true, result:'Invalid API key'}));
    else console.log(JSON.stringify({type:'result', result:'eco: ' + texto, session_id:'s1'}));
    ocupado = false;
    siguiente();
  }, espera);
}
process.stdin.on('data', d => {
  buf += d;
  let i;
  while ((i = buf.indexOf('\\n')) >= 0) {
    cola.push(JSON.parse(buf.slice(0, i)).message.content); buf = buf.slice(i + 1);
  }
  siguiente();
});
process.stdin.on('end', () => process.exit(0));
`);

const sesionViva = require('../sesion-viva');
const contexto = require('../contexto');

function abrir() {
  return sesionViva.crear({ bin: process.execPath, args: [CLAUDE_FALSO], env: process.env });
}

test('contesta los turnos en orden, aunque el primero tarde más', async function () {
  const s = abrir();
  try {
    const [a, b] = await Promise.all([s.preguntar('lento'), s.preguntar('rápido')]);
    assert.strictEqual(a.response, 'eco: lento');
    assert.strictEqual(b.response, 'eco: rápido');
    assert.strictEqual(a.sessionId, 's1');
  } finally {
    s.cerrar();
  }
});

test('un error de Claude vuelve marcado, no como respuesta', async function () {
  const s = abrir();
  try {
    const r = await s.preguntar('error');
    assert.strictEqual(r.isError, true);
    assert.match(r.response, /Invalid API key/);
  } finally {
    s.cerrar();
  }
});

test('si el proceso muere, lo que esperaba falla y se avisa a quien escucha', async function () {
  const s = abrir();
  let avisado = false;
  s.alMorir(function () { avisado = true; });
  await assert.rejects(s.preguntar('muere'), /se cerró/);
  assert.strictEqual(s.viva, false);
  assert.strictEqual(avisado, true);
  await assert.rejects(s.preguntar('otra'), /ya no está/);
});

test('un turno colgado no deja la llamada colgada: se mata el proceso', async function () {
  process.env.SESION_VIVA_TURNO_MS = '200';
  delete require.cache[require.resolve('../sesion-viva')];
  const conTope = require('../sesion-viva');
  const s = conTope.crear({ bin: process.execPath, args: [CLAUDE_FALSO], env: process.env });
  await assert.rejects(s.preguntar('cuelgate'), /sin respuesta/);
  assert.strictEqual(s.viva, false);
  delete process.env.SESION_VIVA_TURNO_MS;
});

test('cerrar deja la sesión muerta y no deja nada esperando', async function () {
  const s = abrir();
  await s.preguntar('hola');
  s.cerrar();
  assert.strictEqual(s.viva, false);
});

test('el contexto sale del token de .mcp.json y llega envuelto', async function () {
  const antes = process.cwd();
  const trabajo = fs.mkdtempSync(path.join(os.tmpdir(), 'parche19-cwd-'));
  fs.writeFileSync(path.join(trabajo, '.mcp.json'), JSON.stringify({ mcpServers: { la: {
    type: 'http', url: 'https://backend/mcp/telefono',
    headers: { Authorization: 'Bearer secreto' } } } }));
  process.chdir(trabajo);
  try {
    let pedido = null;
    const texto = await contexto.pedir({ fetchFn: async function (url, opciones) {
      pedido = { url, auth: opciones.headers.Authorization };
      return { ok: true, json: async function () { return { texto: 'Mañana: 10:00 Dentista.' }; } };
    } });
    assert.match(pedido.url, /\/telefono\/contexto$/);
    assert.strictEqual(pedido.auth, 'Bearer secreto');
    assert.match(texto, /CONTEXTO AL DESCOLGAR[\s\S]*Dentista/);
  } finally {
    process.chdir(antes);
  }
});

test('sin backend, la llamada sigue sin contexto (y sin lanzar)', async function () {
  process.env.CONTEXTO_TOKEN = 'secreto';
  try {
    assert.strictEqual(await contexto.pedir({ fetchFn: async function () {
      throw new Error('ECONNREFUSED');
    } }), '');
    assert.strictEqual(await contexto.pedir({ fetchFn: async function () {
      return { ok: false, status: 404 };
    } }), '');
  } finally {
    delete process.env.CONTEXTO_TOKEN;
  }
});
