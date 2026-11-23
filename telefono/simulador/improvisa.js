/**
 * El Mikel que improvisa (2026-11-23): quien llama a Jarvis en el simulador deja de ser un
 * guion y pasa a ser un modelo. Codex CLI, con la cuenta de ChatGPT de Mikel (plan Go), sin
 * API de pago. Era la tarea «del Qwen» que esperaba a la P100. Ver docs/SIMULADOR.md.
 *
 * Tres cosas, las tres con Codex y las tres SIN herramientas (ni MCP, ni web, ni terminal):
 *
 *   inventar(catalogo, n)   n llamadas plausibles: qué quiere Mikel, cómo lo pide y qué
 *                           contestaría cada herramienta en el mundo de mentira.
 *   siguiente(caso, turnos) lo siguiente que diría Mikel, o que cuelga.
 *   juzgar(caso, turnos)    si consiguió lo que quería, y dónde rozó.
 *
 * Las salidas van por `--output-schema`: JSON con forma fija, no texto que adivinar.
 *
 * Lo que cuesta de verdad no está aquí: cada frase de Mikel la contesta el Jarvis real, o
 * sea, Claude con la suscripción. Por eso el tope de llamadas por noche lo pone simular.js.
 */
'use strict';

const fs = require('fs');
const os = require('os');
const path = require('path');
const { spawn, execFileSync } = require('child_process');

const CODEX_BIN = process.env.CODEX_BIN || path.join(os.homedir(), '.local', 'bin', 'codex');
const MAX_TURNOS = 6;

// Lo mismo que apaga chat/jarvis_claude.py, y por lo mismo: sin terminal. `--disable` con una
// función que la versión no conoce tumba a Codex, así que se cruza con su lista.
const OBLIGATORIAS = ['shell_tool', 'unified_exec'];
const APAGADO = OBLIGATORIAS.concat(['apps', 'plugins', 'browser_use', 'browser_use_external',
  'computer_use', 'image_generation', 'view_image', 'multi_agent', 'multi_agent_v2', 'hooks',
  'goals', 'memories', 'skill_search', 'tool_suggest', 'in_app_browser', 'in_app_local_automation',
  'code_mode_host', 'skill_mcp_dependency_install', 'remote_plugin', 'sleep_tool']);
// Lista blanca, como en chat/jarvis_claude.py: lo que no sea esto (un comando, un parche, un
// subagente) corta la llamada. `error` es el aviso del modo código apagado.
const PERMITIDOS = ['agent_message', 'assistant_message', 'reasoning', 'error', 'todo_list'];

let conocidas = null;

function funcionesConocidas(listado) {
  return new Set(String(listado || '').split('\n').map(function (l) { return l.trim().split(/\s+/)[0]; })
    .filter(Boolean));
}

function leerFunciones() {
  if (conocidas) return conocidas;
  let listado = '';
  try { listado = execFileSync(CODEX_BIN, ['features', 'list'], { encoding: 'utf8', timeout: 30000 }); } catch { /* vacío */ }
  conocidas = funcionesConocidas(listado);
  const faltan = OBLIGATORIAS.filter(function (f) { return !conocidas.has(f); });
  if (faltan.length) {
    throw new Error('esta versión de Codex no tiene ' + faltan.join(', ') + ': no sé quitarle la terminal');
  }
  return conocidas;
}

/** Los argumentos de `codex exec`. Pura: se prueba sin lanzarlo. */
function argsCodex(sistema, esquema, salida, dir, funciones, modelo) {
  const args = ['exec', '--json', '--ephemeral', '--skip-git-repo-check', '--ignore-user-config',
    '--ignore-rules', '--sandbox', 'read-only', '-C', dir,
    '-c', 'approval_policy="never"', '-c', 'model_instructions_file="' + sistema + '"',
    '-c', 'project_doc_max_bytes=0', '-c', 'history.persistence="none"',
    '-c', 'web_search="disabled"', '-c', 'model_reasoning_effort="low"',
    '--output-schema', esquema, '-o', salida];
  APAGADO.forEach(function (f) {
    if (OBLIGATORIAS.indexOf(f) >= 0 || funciones.has(f)) args.push('--disable', f);
  });
  if (modelo) args.push('-m', modelo);
  return args.concat(['-']);
}

/** Una llamada a Codex que devuelve el JSON del esquema. Lanza si algo va mal. */
function codex(prompt, sistema, esquema, opciones) {
  const o = opciones || {};
  const funciones = leerFunciones();
  const tmp = fs.mkdtempSync(path.join(os.tmpdir(), 'simulador-codex-'));
  const fSis = path.join(tmp, 'sistema.txt');
  const fEsq = path.join(tmp, 'esquema.json');
  const fSal = path.join(tmp, 'salida.json');
  fs.writeFileSync(fSis, sistema);
  fs.writeFileSync(fEsq, JSON.stringify(esquema));
  return new Promise(function (resolve, reject) {
    const proceso = spawn(CODEX_BIN, argsCodex(fSis, fEsq, fSal, tmp, funciones, o.modelo || process.env.SIMULADOR_CODEX_MODELO),
      { cwd: tmp, env: Object.assign({}, process.env, { NO_COLOR: '1', CODEX_DISABLE_TELEMETRY: '1' }),
        stdio: ['pipe', 'pipe', 'pipe'] });
    let resto = '';
    let prohibido = '';
    const reloj = setTimeout(function () { proceso.kill('SIGKILL'); }, o.esperaMs || 180000);
    proceso.stdout.on('data', function (trozo) {
      resto += trozo;
      const lineas = resto.split('\n');
      resto = lineas.pop();
      lineas.forEach(function (l) {
        let d; try { d = JSON.parse(l); } catch { return; }
        const clase = ((d && d.item) || {}).type;
        if (clase && PERMITIDOS.indexOf(clase) < 0) { prohibido = clase; proceso.kill('SIGKILL'); }
      });
    });
    proceso.stderr.on('data', function () {});
    proceso.on('error', function (e) { clearTimeout(reloj); reject(e); });
    proceso.on('close', function (codigo) {
      clearTimeout(reloj);
      try {
        if (prohibido) throw new Error('Codex intentó usar ' + prohibido + '; cortado');
        if (codigo !== 0) throw new Error('Codex salió con ' + codigo);
        resolve(JSON.parse(fs.readFileSync(fSal, 'utf8')));
      } catch (e) { reject(e); } finally { fs.rmSync(tmp, { recursive: true, force: true }); }
    });
    proceso.stdin.end(prompt);
  });
}

// ── Los esquemas (estrictos: todo requerido, nada de más) ─────────────────────

const ESQUEMA_CASOS = {
  type: 'object', additionalProperties: false, required: ['casos'],
  properties: { casos: { type: 'array', items: {
    type: 'object', additionalProperties: false,
    required: ['id', 'objetivo', 'primera', 'modo', 'ruido', 'mundo'],
    properties: {
      id: { type: 'string' },
      objetivo: { type: 'string' },
      primera: { type: 'string' },
      modo: { type: 'string', enum: ['normal', 'coche'] },
      ruido: { type: 'string', enum: ['limpio', 'coche', 'malo'] },
      mundo: { type: 'array', items: { type: 'object', additionalProperties: false,
        required: ['herramienta', 'respuesta_json'],
        properties: { herramienta: { type: 'string' }, respuesta_json: { type: 'string' } } } },
    } } } },
};

const ESQUEMA_FRASE = {
  type: 'object', additionalProperties: false, required: ['dice', 'cuelga'],
  properties: { dice: { type: 'string' }, cuelga: { type: 'boolean' } },
};

const ESQUEMA_JUICIO = {
  type: 'object', additionalProperties: false, required: ['conseguido', 'roces'],
  properties: { conseguido: { type: 'boolean' }, roces: { type: 'array', items: { type: 'string' } } },
};

const SISTEMA_INVENTAR = 'Inventas llamadas de prueba para Jarvis, el asistente por teléfono de Mikel ' +
  '(estudiante universitario, habla español de España, coloquial y con prisa; a veces conduce). ' +
  'Cada llamada es algo que Mikel podría pedir de verdad con las herramientas que te pasan: ' +
  'variadas (agenda, casa, mensajes, salud, cine, recordatorios, tráfico…), algunas ambiguas, ' +
  'alguna que encadene dos cosas, alguna con un cambio de idea a mitad. `primera` es su ' +
  'primera frase, tal como la diría. `mundo` es lo que contestaría cada herramienta que ' +
  'Jarvis probablemente use (respuesta_json: un objeto JSON en texto, verosímil y breve). ' +
  'Usa SOLO nombres de herramienta de la lista. Datos inventados, nunca de personas reales ' +
  'salvo nombres de pila corrientes. `id`: corto, en minúsculas y con guiones.';

const SISTEMA_MIKEL = 'Haces de Mikel hablando por teléfono con Jarvis, su asistente. Tienes un ' +
  'objetivo. Contestas como hablaría él: frases cortas, español de España, sin cortesías de ' +
  'más. Si Jarvis te pregunta algo, contestas. Si te propone hacer algo que querías, dices «sí» ' +
  'o similar. Si no te entiende, lo repites de otra forma, con algo de impaciencia. Cuando ' +
  'ya tienes lo que querías, o Jarvis no puede y ya lo ha dejado claro, cuelga (cuelga=true, ' +
  'dice vacío o una despedida corta). No inventes datos que Jarvis no te haya dado. ' +
  'Lo que va entre corchetes, «[la llamada te lee aquí…]», es que la llamada te ha leído ' +
  'en voz alta ese resultado: dalo por oído y sigue como si tuvieras el dato.';

const SISTEMA_JUEZ = 'Juzgas una llamada de prueba entre Mikel y Jarvis, su asistente por teléfono. ' +
  'Dices si Mikel consiguió su objetivo y, en `roces`, como mucho cuatro problemas concretos ' +
  'de Jarvis (no entendió, se repitió, habló de más, preguntó lo obvio, usó mal una ' +
  'herramienta, tardó…), cada uno en una frase citando el turno. Si fue bien, roces vacío. ' +
  'Lo que dicen las herramientas es de mentira a propósito: no lo juzgues. Lo que va entre ' +
  'corchetes («[la llamada te lee aquí…]») es una lectura en voz alta que hace la llamada, ' +
  'no Jarvis: cuenta como que Mikel lo oyó. «…» como frase de Mikel es silencio.';

function escribirConversacion(turnos) {
  return turnos.map(function (t, i) {
    const jarvis = (t.voz || []).concat(t.llamada || []).join(' ').trim();
    return (i + 1) + '. Mikel: ' + t.dicho + '\n   Jarvis: ' + (jarvis || (t.error ? '(' + t.error + ')' : '(nada)'));
  }).join('\n');
}

/** Del JSON de Codex a casos del simulador. Pura: descarta herramientas inventadas. */
function aCasos(salida, catalogo) {
  const nombres = new Set((catalogo || []).map(function (t) { return t.name; }));
  const vistos = new Set();
  return ((salida && salida.casos) || []).map(function (c, i) {
    const mundo = {};
    (c.mundo || []).forEach(function (m) {
      if (!nombres.has(m.herramienta)) return;
      try { mundo[m.herramienta] = JSON.parse(m.respuesta_json); } catch { /* sin respuesta: ok */ }
    });
    let id = 'improvisa-' + String(c.id || i).toLowerCase().replace(/[^a-z0-9-]+/g, '-').slice(0, 40);
    while (vistos.has(id)) id += '-' + i;
    vistos.add(id);
    return { id: id, improvisa: true, objetivo: String(c.objetivo || '').slice(0, 400),
             primera: String(c.primera || '').slice(0, 300), mundo: mundo,
             modo: c.modo === 'coche' ? 'coche' : undefined, ruido: c.ruido || 'limpio' };
  }).filter(function (c) { return c.primera && c.objetivo; });
}

async function inventar(catalogo, n, opciones) {
  const lista = catalogo.map(function (t) {
    return '- ' + t.name + ': ' + String(t.description || '').split('\n')[0].slice(0, 140);
  }).join('\n');
  const salida = await codex('Inventa ' + n + ' llamadas distintas. Herramientas que tiene Jarvis:\n' + lista,
                             SISTEMA_INVENTAR, ESQUEMA_CASOS, opciones);
  return aCasos(salida, catalogo).slice(0, n);
}

async function siguiente(caso, turnos, opciones) {
  const r = await codex('Tu objetivo: ' + caso.objetivo + '\n\nLa llamada hasta ahora:\n' +
                        escribirConversacion(turnos) + '\n\n¿Qué dices ahora?',
                        SISTEMA_MIKEL, ESQUEMA_FRASE, opciones);
  return { dice: String(r.dice || '').trim().slice(0, 300), fin: Boolean(r.cuelga) || !String(r.dice || '').trim() };
}

async function juzgar(caso, turnos, opciones) {
  const r = await codex('Objetivo de Mikel: ' + caso.objetivo + '\n\nLa llamada:\n' + escribirConversacion(turnos),
                        SISTEMA_JUEZ, ESQUEMA_JUICIO, opciones);
  return { conseguido: Boolean(r.conseguido),
           roces: (r.roces || []).map(function (x) { return String(x).slice(0, 300); }).slice(0, 4) };
}

module.exports = { argsCodex, funcionesConocidas, aCasos, escribirConversacion, inventar, siguiente,
                   juzgar, MAX_TURNOS, APAGADO, OBLIGATORIAS };
