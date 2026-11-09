/**
 * Tests del simulador de llamadas (docs/SIMULADOR.md). Sin red ni Claude:
 *
 *   node --test telefono/simulador/test/
 *
 * Lo que confirma es el `confirmacion.js` de verdad, el de la foto de la voice-app.
 */
'use strict';

const test = require('node:test');
const assert = require('node:assert');
const fs = require('fs');
const os = require('os');
const path = require('path');

const { crearMundo } = require('../mundo');
const { oir } = require('../oido');
const { evaluar, herramientasQueNoExisten } = require('../juez');
const { correrCaso, extraerVoz, montarPuente } = require('../simular');

// La foto de la voice-app no trae su package.json (es del repositorio original) y el de la
// raíz de este dice "module": se copian los dos ficheros a un sitio donde son CommonJS.
const FOTO = path.join(__dirname, '..', '..', 'claude-phone', 'nuevos', 'voice-app', 'lib');
const VOZ = fs.mkdtempSync(path.join(os.tmpdir(), 'sim-voz-'));
fs.writeFileSync(path.join(VOZ, 'package.json'), '{"type":"commonjs"}');
['confirmacion.js', 'turno-rapido.js'].forEach(function (f) { fs.copyFileSync(path.join(FOTO, f), path.join(VOZ, f)); });
test.after(function () { fs.rmSync(VOZ, { recursive: true, force: true }); });
const CATALOGO = [{ name: 'garaje' }, { name: 'agenda' }, { name: 'recordarme' }];

function dependencias(mundo, respuestas) {
  process.env.CONFIRMAR_TOKEN = 'simulacro';
  process.env.BARGE_IN = '0';
  const pedidos = [];
  return {
    pedidos: pedidos, mundo: mundo, ruido: 'limpio',
    confirmacion: require(path.join(VOZ, 'confirmacion.js')),
    avisos: { pasiva: '[coche] ', interrupcion: '[cortado] ' },
    preguntar: async function (prompt) {
      pedidos.push(prompt);
      const r = respuestas.shift();
      return { response: typeof r === 'function' ? r() : r };
    },
    colgar: async function () {},
  };
}

test('mundo: una herramienta que se confirma no hace nada, propone', function () {
  const m = crearMundo({ catalogo: CATALOGO });
  m.poner({ frases: { garaje: 'Abrir la puerta del garaje.' } });
  const r = m.usar('garaje', { accion: 'abrir' }).resultado;
  assert.strictEqual(r.estado, 'pendiente_en_el_movil');
  assert.match(r.linea_para_la_llamada, /^✅ CONFIRMAR: [0-9a-f-]{36}$/);
  assert.deepStrictEqual(m.propuestas().map(function (p) { return [p.herramienta, p.respuesta]; }), [['garaje', null]]);
});

test('mundo: contesta lo que diga el caso, un error si lo pide, y ok si no dice nada', function () {
  const m = crearMundo({ catalogo: CATALOGO });
  m.poner({ mundo: { agenda: { _error: 'Outlook no responde.' } } });
  assert.deepStrictEqual(m.usar('agenda', {}), { error: 'Outlook no responde.' });
  assert.deepStrictEqual(m.usar('recordarme', { texto: 'x' }), { resultado: { ok: true } });
  const fuera = m.rpc({ id: 1, method: 'tools/call', params: { name: 'desplegar', arguments: {} } });
  assert.strictEqual(fuera.json.error.code, -32602);
  assert.deepStrictEqual(m.llamadas().map(function (l) { return l.nombre; }), ['agenda', 'recordarme']);
});

test('mundo: por HTTP habla MCP y sirve el contexto y la confirmación', async function () {
  const m = crearMundo({ catalogo: CATALOGO });
  const url = await m.escuchar();
  try {
    m.poner({ contexto: 'Mañana: 10:00 Dentista.', preguntas: { garaje: '¿Abro la puerta del garaje?' } });
    const rpc = async function (cuerpo) {
      const r = await fetch(url + '/mcp/telefono', { method: 'POST', body: JSON.stringify(cuerpo) });
      return r.status === 204 ? null : r.json();
    };
    assert.strictEqual((await rpc({ id: 1, method: 'initialize', params: { protocolVersion: 'x' } })).result.protocolVersion, 'x');
    assert.strictEqual(await rpc({ method: 'notifications/initialized' }), null);
    assert.strictEqual((await rpc({ id: 2, method: 'tools/list' })).result.tools.length, 3);
    const llamada = await rpc({ id: 3, method: 'tools/call', params: { name: 'garaje', arguments: { accion: 'abrir' } } });
    const id = JSON.parse(llamada.result.content[0].text).id;
    assert.strictEqual((await (await fetch(url + '/telefono/contexto')).json()).texto, 'Mañana: 10:00 Dentista.');
    assert.strictEqual((await (await fetch(url + '/telefono/confirmar/' + id)).json()).pregunta, '¿Abro la puerta del garaje?');
    const si = await (await fetch(url + '/telefono/confirmar/' + id, { method: 'POST', body: '{"respuesta":"si"}' })).json();
    assert.strictEqual(si.frase, 'Hecho.');
    assert.strictEqual(m.propuestas()[0].respuesta, 'si');
    assert.strictEqual((await fetch(url + '/telefono/lectura')).status, 404);
    assert.deepStrictEqual(m.desconocidas(), ['GET /telefono/lectura']);
  } finally {
    await m.cerrar();
  }
});

test('oído: limpio no toca nada, y el ruido es el mismo para la misma semilla', function () {
  const frase = 'Jarvis, abre la puerta del garaje, por favor';
  assert.strictEqual(oir(frase, 'limpio', 1), frase);
  assert.strictEqual(oir(frase, 'coche', 7), oir(frase, 'coche', 7));
  const sucio = oir(frase, 'malo', 7);
  assert.doesNotMatch(sucio, /[,.A-ZÁÉÍÓÚ]/);
  assert.ok(sucio.split(' ').length <= frase.split(' ').length);
  const variantes = new Set();
  for (let s = 0; s < 40; s++) variantes.add(oir(frase, 'malo', s));
  assert.ok(variantes.size > 3, 'con otra semilla se oye otra cosa');
});

test('juez: herramientas, argumentos, lo dicho y lo que se confirma', function () {
  const traza = {
    turnos: [{ voz: ['De acuerdo.'], llamada: ['¿Abro la puerta del garaje?'], propuso: true, segundos: 3 },
             { voz: [], llamada: ['Hecho.'], propuso: false, segundos: 0 }],
    herramientas: [{ nombre: 'garaje', args: { accion: 'abrir' } }],
    propuestas: [{ herramienta: 'garaje', respuesta: 'si' }],
  };
  assert.deepStrictEqual(evaluar({ espera: { propone: 'garaje', confirmado: true, herramientas: ['garaje'],
    argumentos: { garaje: { accion: 'abrir' } }, dice: ['¿abro'], no_dice: ['di sí o no'] } }, traza),
    { ok: true, fallos: [] });
  const mal = evaluar({ espera: { confirmado: false, herramientas: ['agenda'], sin_herramientas: ['garaje'],
    argumentos: { garaje: { accion: 'cerrar' } }, max_segundos: 2 } }, traza);
  assert.strictEqual(mal.ok, false);
  assert.strictEqual(mal.fallos.length, 5);
});

test('juez: al proponer, Claude solo dice «De acuerdo.» (parche 44), y nunca más de 40 palabras', function () {
  const charlatan = { turnos: [{ voz: ['Voy a abrir la puerta del garaje, se lo leo para que me confirme.'], propuso: true, segundos: 1 }] };
  assert.match(evaluar({}, charlatan).fallos[0], /al proponer dijo 14 palabras/);
  const largo = { turnos: [{ voz: [new Array(45).fill('palabra').join(' ')], propuso: false, segundos: 1 }] };
  assert.match(evaluar({}, largo).fallos[0], /45 palabras \(tope 40\)/);
  assert.deepStrictEqual(herramientasQueNoExisten({ espera: { herramientas: ['garaje', 'inventada'] } }, CATALOGO), ['inventada']);
});

test('extraerVoz: la línea de voz, y si no la hay, lo que no sea una marca', function () {
  assert.strictEqual(extraerVoz('🗣️ VOICE_RESPONSE: De **acuerdo**.\n✅ CONFIRMAR: x'), 'De acuerdo.');
  assert.strictEqual(extraerVoz('Hecho, señor.\n📖 LEER: semana'), 'Hecho, señor.');
});

test('una llamada: propone, la llamada pregunta, el sí lo decide la voice-app y no pasa por Claude', async function () {
  const m = crearMundo({ catalogo: CATALOGO });
  process.env.LECTURA_URL = await m.escuchar();
  try {
    const caso = { id: 'garaje', preguntas: { garaje: '¿Abro la puerta del garaje?' },
                   turnos: ['abre el garaje', 'sí, venga'], espera: { propone: 'garaje', confirmado: true } };
    const d = dependencias(m, [function () {
      const r = m.usar('garaje', { accion: 'abrir' }).resultado;
      return '🗣️ VOICE_RESPONSE: De acuerdo.\n' + r.linea_para_la_llamada;
    }]);
    const traza = await correrCaso(caso, d, 0);
    assert.strictEqual(d.pedidos.length, 1, 'el sí no gasta un turno de Claude');
    assert.deepStrictEqual(traza.turnos[0].llamada, ['¿Abro la puerta del garaje?']);
    assert.deepStrictEqual(traza.turnos[1].llamada, ['Hecho.']);
    assert.deepStrictEqual(evaluar(caso, traza), { ok: true, fallos: [] });
  } finally {
    await m.cerrar();
  }
});

test('una llamada: «sí, pero…» no confirma y vuelve a Claude con el aviso; el coche pone el suyo', async function () {
  const m = crearMundo({ catalogo: CATALOGO });
  process.env.LECTURA_URL = await m.escuchar();
  try {
    const caso = { id: 'matiz', modo: 'coche', turnos: ['abre el garaje', 'sí, pero espera un minuto'] };
    const d = dependencias(m, [function () {
      return '🗣️ VOICE_RESPONSE: De acuerdo.\n' + m.usar('garaje', {}).resultado.linea_para_la_llamada;
    }, '🗣️ VOICE_RESPONSE: Espero, señor.']);
    const traza = await correrCaso(caso, d, 0);
    assert.strictEqual(d.pedidos.length, 2);
    assert.match(d.pedidos[0], /^\[coche\] abre el garaje$/);
    assert.match(d.pedidos[1], /no ha contestado sí o no/);
    assert.strictEqual(traza.propuestas[0].respuesta, null);
  } finally {
    await m.cerrar();
  }
});

test('la copia del puente va sin terminal, y si no se puede garantizar no se monta', function () {
  const tmp = fs.mkdtempSync(path.join(os.tmpdir(), 'sim-test-'));
  try {
    const puente = path.join(tmp, 'puente');
    const trabajo = path.join(tmp, 'trabajo');
    fs.mkdirSync(puente); fs.mkdirSync(trabajo);
    fs.writeFileSync(path.join(trabajo, 'CLAUDE.md'), 'runbook');
    fs.writeFileSync(path.join(puente, 'bitacora.js'), '');
    fs.writeFileSync(path.join(puente, 'server.js.bak-x'), '');
    fs.writeFileSync(path.join(puente, 'server.js'), "const a = [\n  '--tools', 'Bash',\n];");
    const uno = path.join(tmp, 'uno'); fs.mkdirSync(uno);
    let montado;
    try {
      montado = montarPuente(puente, trabajo, uno);
    } catch (e) {
      // Windows sin permiso para enlaces simbólicos: allí no corre el simulador.
      if (e.code === 'EPERM') return;
      throw e;
    }
    assert.match(fs.readFileSync(path.join(montado.api, 'server.js'), 'utf8'), /'--tools', '',/);
    assert.deepStrictEqual(fs.readdirSync(montado.api).sort(), ['bitacora.js', 'server.js']);
    const mcp = JSON.parse(fs.readFileSync(path.join(montado.cwd, '.mcp.json'), 'utf8'));
    assert.match(mcp.mcpServers['life-assistant-telefono'].url, /\.invalid\/mcp\/telefono$/);

    fs.writeFileSync(path.join(puente, 'server.js'), "const a = ['--tools', 'Bash,Read'];");
    const dos = path.join(tmp, 'dos'); fs.mkdirSync(dos);
    assert.throws(function () { montarPuente(puente, trabajo, dos); }, /no simulo/);
  } finally {
    fs.rmSync(tmp, { recursive: true, force: true });
  }
});
