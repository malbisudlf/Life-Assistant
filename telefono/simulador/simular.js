#!/usr/bin/env node
/**
 * El simulador de llamadas: alguien que hace de Mikel llama a Jarvis, y se mira qué pasa.
 * Ver docs/SIMULADOR.md.
 *
 * Se ejecuta EN caja, que es donde vive el teléfono:
 *
 *   node telefono/simulador/simular.js                       # los casos de casos.json
 *   node telefono/simulador/simular.js --filtro garaje       # solo los que casen
 *   node telefono/simulador/simular.js --ruido coche         # como se oye en el coche
 *   node telefono/simulador/simular.js --casos ~/telefono-repaso/casos-reales.json
 *
 * Lo que es de verdad y lo que no:
 *   - **El cerebro es el de verdad**: el mismo `server.js` del puente, con el mismo RUNBOOK,
 *     el mismo modelo y el catálogo de herramientas real. Se lanza una copia aparte, en otro
 *     puerto, para no tocar el que atiende el teléfono.
 *   - **Lo que confirma es lo de verdad**: `confirmacion.js` de la voice-app decide qué es un
 *     sí, igual que en una llamada.
 *   - **El mundo es de mentira** (`mundo.js`): las herramientas no llegan al backend. Nada
 *     de lo que pase aquí abre una puerta, manda un mensaje ni apunta una cita.
 *   - **Sin terminal.** La sesión del teléfono tiene Bash y `--dangerously-skip-permissions`;
 *     una llamada simulada que dijera «reinicia el backend» lo reiniciaría de verdad. La
 *     copia se lanza con `--tools ''`, y si no se puede garantizar, no se lanza.
 *   - **Sin voz.** Va en texto: no hay Fish, ni Azure, ni oído. Lo que cuesta es lo que
 *     gasta Claude Code de la suscripción, lo mismo que una llamada de verdad igual de larga.
 */
'use strict';

const fs = require('fs');
const os = require('os');
const net = require('net');
const path = require('path');
const crypto = require('crypto');
const { spawn } = require('child_process');

const { crearMundo } = require('./mundo');
const { oir, semillaDe } = require('./oido');
const { evaluar, herramientasQueNoExisten } = require('./juez');

// Copias de respaldo de lo que la voice-app pone delante de un turno; si está su código a
// mano se usan las suyas (ver `cargarVozApp`).
const AVISO_PASIVA_COPIA =
  '[Modo coche: estabas a la escucha en silencio y te ha llamado por tu nombre. ' +
  'Contesta breve; después vuelves a escuchar sin hablar.] ';
const AVISO_INTERRUPCION_COPIA =
  '[Te ha interrumpido mientras hablabas: puede que no oyera el final de tu respuesta] ';

// Cuántas llamadas simuladas como mucho de una vez. Cada una gasta lo que una llamada de
// verdad: sin tope, «pásalos todos con cinco repeticiones» se come la suscripción.
const MAX_LLAMADAS = 15;

function opciones(argv) {
  const casa = os.homedir();
  const o = {
    casos: path.join(__dirname, 'casos.json'), filtro: '', ruido: 'limpio', repeticiones: 1,
    max: MAX_LLAMADAS, puente: path.join(casa, '.claude-phone-cli', 'claude-api-server'),
    voz: path.join(casa, '.claude-phone-cli', 'voice-app'),
    trabajo: path.join(casa, 'telefono-jarvis'), backend: 'http://127.0.0.1:8080',
    salida: path.join(casa, 'telefono-simulador'), modelo: '', conservar: false,
  };
  for (let i = 0; i < argv.length; i++) {
    const a = argv[i];
    if (a === '--conservar') o.conservar = true;
    else if (a.indexOf('--') === 0 && a.slice(2) in o) {
      const v = argv[++i];
      o[a.slice(2)] = (typeof o[a.slice(2)] === 'number') ? parseInt(v, 10) : v;
    } else throw new Error('No entiendo ' + a);
  }
  if (o.casos.indexOf('~') === 0) o.casos = path.join(casa, o.casos.slice(1));
  return o;
}

/** Lo que Claude dice en voz alta de su respuesta (como `extractVoiceLine` de la voice-app). */
function extraerVoz(respuesta) {
  const m = String(respuesta || '').match(/🗣️\s*VOICE_RESPONSE:\s*([^\n]+)/im);
  if (m) return m[1].replace(/\*+/g, '').trim();
  return String(respuesta || '').split('\n')
    .filter(function (l) { return !/^\s*(✅|📖|🗣️)/u.test(l); }).join(' ').replace(/\s+/g, ' ').trim();
}

/**
 * Una llamada entera. `d` trae lo que cambia entre la de verdad y la de los tests:
 *   mundo, confirmacion (el módulo de la voice-app), preguntar(prompt, callId) → { response },
 *   colgar(callId), ruido, avisos { pasiva, interrupcion }.
 */
async function correrCaso(caso, d, repeticion) {
  d.mundo.poner(caso);
  const callId = crypto.randomUUID();
  const turnos = [];
  let pendiente = null;
  let aviso = '';
  const lista = caso.turnos || [];
  for (let i = 0; i < lista.length; i++) {
    const t = typeof lista[i] === 'string' ? { dice: lista[i] } : lista[i];
    const oido = oir(t.dice, t.ruido || caso.ruido || d.ruido,
                     semillaDe((caso.id || '') + ':' + i + ':' + (repeticion || 0)));
    const turno = { dicho: t.dice, oido: oido, voz: [], llamada: [], propuso: false, segundos: 0 };
    turnos.push(turno);
    // Lo que la llamada dice por su cuenta (la pregunta, el «Hecho.») se apunta aparte de
    // lo que dice Claude: son dos voces y se les piden cosas distintas.
    const c = {
      endpoint: { uuid: 'simulacro', play: async function () {}, api: async function () {} },
      session: {}, voiceId: 'simulacro', sigueActiva: function () { return true; },
      ttsService: { generateSpeech: async function (texto) { turno.llamada.push(texto); return 'simulacro'; } },
      log: function () {},
    };
    if (pendiente) {
      const rc = await d.confirmacion.resolverConfirmacion(pendiente, oido, c);
      pendiente = rc.pendiente || null;
      aviso = rc.aviso || '';
      if (rc.resuelta) continue;   // dicho y hecho sin Claude, como en la llamada
    }
    const prefijo = (caso.modo === 'coche' ? d.avisos.pasiva : '') +
                    (t.corta ? d.avisos.interrupcion : '') + aviso;
    aviso = '';
    const t0 = Date.now();
    let r;
    try {
      r = await d.preguntar(prefijo + oido, callId);
    } catch (e) {
      turno.error = 'Claude no contestó: ' + e.message;
      break;
    }
    turno.segundos = (Date.now() - t0) / 1000;
    turno.respuesta = r.response;
    turno.voz.push(extraerVoz(r.response));
    turno.propuso = Boolean(d.confirmacion.pedidoDeConfirmacion(r.response));
    pendiente = (await d.confirmacion.preguntarSiLoPide(r.response, c)).pendiente;
  }
  await d.colgar(callId);
  return { turnos: turnos, herramientas: d.mundo.llamadas(), propuestas: d.mundo.propuestas(),
           desconocidas: d.mundo.desconocidas() };
}

// ── Lo que solo existe en caja ────────────────────────────────────────────────

function puertoLibre() {
  return new Promise(function (resolve, reject) {
    const s = net.createServer();
    s.once('error', reject);
    s.listen(0, '127.0.0.1', function () { const p = s.address().port; s.close(function () { resolve(p); }); });
  });
}

/**
 * La copia del puente, sin terminal. Devuelve el directorio donde queda montada.
 * Lanza si no puede quitar Bash con certeza: mejor no simular que simular con una shell.
 */
function montarPuente(dirPuente, dirTrabajo, tmp) {
  const original = fs.readFileSync(path.join(dirPuente, 'server.js'), 'utf8');
  const CON_BASH = "'--tools', 'Bash',";
  if (original.split(CON_BASH).length !== 2 || original.split("'--tools'").length !== 2) {
    throw new Error('server.js ya no lanza la sesión con `' + CON_BASH + '` una sola vez: ' +
                    'no sé quitarle la terminal, así que no simulo. Revisa montarPuente.');
  }
  const api = path.join(tmp, 'api');
  fs.mkdirSync(api);
  fs.writeFileSync(path.join(api, 'server.js'), original.replace(CON_BASH, "'--tools', '',"));
  fs.readdirSync(dirPuente).forEach(function (f) {
    if (f === 'server.js' || /\.bak/.test(f)) return;
    fs.symlinkSync(path.join(dirPuente, f), path.join(api, f));
  });
  const cwd = path.join(tmp, 'llamada');
  fs.mkdirSync(cwd);
  fs.copyFileSync(path.join(dirTrabajo, 'CLAUDE.md'), path.join(cwd, 'CLAUDE.md'));
  // El puente cambia esta URL por CONTEXTO_URL (el mundo falso). Si un día dejara de
  // hacerlo, `.invalid` no resuelve: la sesión se queda sin herramientas, no con las de verdad.
  fs.writeFileSync(path.join(cwd, '.mcp.json'), JSON.stringify({ mcpServers: { 'life-assistant-telefono': {
    type: 'http', url: 'http://simulacro.invalid/mcp/telefono',
    headers: { Authorization: 'Bearer simulacro' } } } }), { mode: 0o600 });
  return { api: api, cwd: cwd };
}

/** El catálogo de herramientas del teléfono, leído del backend de verdad. Solo lee. */
async function catalogoReal(backend, dirTrabajo) {
  const mcp = JSON.parse(fs.readFileSync(path.join(dirTrabajo, '.mcp.json'), 'utf8'));
  const servidor = Object.values(mcp.mcpServers || {}).find(function (s) { return /\/mcp\/telefono/.test(s.url || ''); });
  if (!servidor) throw new Error('No encuentro el MCP del teléfono en ' + dirTrabajo + '/.mcp.json');
  const cabeceras = { 'Content-Type': 'application/json', Accept: 'application/json, text/event-stream',
                      Authorization: (servidor.headers || {}).Authorization || '' };
  const url = backend.replace(/\/+$/, '') + '/mcp/telefono';
  const ini = await fetch(url, { method: 'POST', headers: cabeceras, signal: AbortSignal.timeout(10000),
    body: JSON.stringify({ jsonrpc: '2.0', id: 1, method: 'initialize', params: {
      protocolVersion: '2025-03-26', capabilities: {}, clientInfo: { name: 'simulador', version: '1' } } }) });
  if (!ini.ok) throw new Error('El backend no deja leer el catálogo (HTTP ' + ini.status + ')');
  cabeceras['Mcp-Session-Id'] = ini.headers.get('mcp-session-id') || '';
  const r = await fetch(url, { method: 'POST', headers: cabeceras, signal: AbortSignal.timeout(10000),
    body: JSON.stringify({ jsonrpc: '2.0', id: 2, method: 'tools/list' }) });
  const tools = (((await r.json()) || {}).result || {}).tools;
  if (!Array.isArray(tools) || !tools.length) throw new Error('El backend ha devuelto un catálogo vacío');
  return tools;
}

function cargarVozApp(dirVoz) {
  const confirmacion = require(path.join(dirVoz, 'lib', 'confirmacion.js'));
  const avisos = { pasiva: AVISO_PASIVA_COPIA, interrupcion: AVISO_INTERRUPCION_COPIA };
  try { avisos.pasiva = require(path.join(dirVoz, 'lib', 'escucha-pasiva.js')).AVISO_PASIVA || avisos.pasiva; } catch { /* la copia */ }
  try { avisos.interrupcion = require(path.join(dirVoz, 'lib', 'turno-rapido.js')).AVISO_INTERRUPCION || avisos.interrupcion; } catch { /* la copia */ }
  let identidad = '';
  try {
    const dispositivos = JSON.parse(fs.readFileSync(path.join(dirVoz, 'config', 'devices.json'), 'utf8'));
    identidad = (Object.values(dispositivos).find(function (x) { return x && x.prompt; }) || {}).prompt || '';
  } catch { /* sin identidad, la que ponga el puente */ }
  return { confirmacion: confirmacion, avisos: avisos, identidad: identidad };
}

async function esperarPuente(url, proceso) {
  for (let i = 0; i < 60; i++) {
    if (proceso.exitCode !== null) throw new Error('La copia del puente se ha cerrado al arrancar');
    try {
      const r = await fetch(url + '/health', { signal: AbortSignal.timeout(1000) });
      if (r.ok) return;
    } catch { /* aún no */ }
    await new Promise(function (r) { setTimeout(r, 250); });
  }
  throw new Error('La copia del puente no arranca');
}

async function principal() {
  const o = opciones(process.argv.slice(2));
  const fichero = JSON.parse(fs.readFileSync(o.casos, 'utf8'));
  let casos = (Array.isArray(fichero) ? fichero : fichero.casos || [])
    .filter(function (c) { return !o.filtro || String(c.id).indexOf(o.filtro) >= 0; });
  const total = casos.length * o.repeticiones;
  if (!total) throw new Error('Ningún caso que correr');
  if (total > o.max) {
    throw new Error(total + ' llamadas simuladas son más que el tope (' + o.max + '). Cada una ' +
                    'gasta lo que una llamada de verdad: usa --filtro, o súbelo a propósito con --max.');
  }

  const tmp = fs.mkdtempSync(path.join(os.tmpdir(), 'simulador-'));
  const catalogo = await catalogoReal(o.backend, o.trabajo);
  casos.forEach(function (c) {
    const faltan = herramientasQueNoExisten(c, catalogo);
    if (faltan.length) console.warn('⚠ ' + c.id + ': el catálogo no tiene ' + faltan.join(', '));
  });
  const mundo = crearMundo({ catalogo: catalogo });
  const urlMundo = await mundo.escuchar();

  // Antes de cargar la voice-app: `confirmacion.js` lee esto al preguntar.
  process.env.LECTURA_URL = urlMundo;
  process.env.CONFIRMAR_TOKEN = 'simulacro';
  process.env.BARGE_IN = '0';
  const voz = cargarVozApp(o.voz);

  const montado = montarPuente(o.puente, o.trabajo, tmp);
  const puerto = await puertoLibre();
  const entorno = Object.assign({}, process.env, {
    PORT: String(puerto), HOST: '127.0.0.1', CONTEXTO_URL: urlMundo, CONTEXTO_TOKEN: 'simulacro',
    BITACORA_PATH: path.join(tmp, 'bitacora.json'), SESION_FLACA: '1',
  });
  if (o.modelo) entorno.CLAUDE_MODEL = o.modelo;
  const registro = fs.openSync(path.join(tmp, 'puente.log'), 'a');
  const puente = spawn(process.execPath, [path.join(montado.api, 'server.js')],
                       { cwd: montado.cwd, env: entorno, stdio: ['ignore', registro, registro] });
  const urlPuente = 'http://127.0.0.1:' + puerto;

  const d = {
    mundo: mundo, confirmacion: voz.confirmacion, avisos: voz.avisos, ruido: o.ruido,
    preguntar: async function (prompt, callId) {
      const r = await fetch(urlPuente + '/ask', {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ prompt: prompt, callId: callId, devicePrompt: voz.identidad }),
        signal: AbortSignal.timeout(120000) });
      const datos = await r.json();
      if (!datos.success) throw new Error(String(datos.error || 'sin respuesta').slice(0, 200));
      return datos;
    },
    colgar: async function (callId) {
      await fetch(urlPuente + '/end-session', { method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ callId: callId }), signal: AbortSignal.timeout(5000) }).catch(function () {});
    },
  };

  const resultados = [];
  let rojo = false;
  try {
    await esperarPuente(urlPuente, puente);
    console.log('Simulador: ' + total + ' llamadas, oído «' + o.ruido + '», ' + catalogo.length + ' herramientas en el catálogo.\n');
    for (const caso of casos) {
      for (let rep = 0; rep < o.repeticiones; rep++) {
        const traza = await correrCaso(caso, d, rep);
        const veredicto = evaluar(caso, traza);
        const lento = Math.max.apply(null, [0].concat(traza.turnos.map(function (t) { return t.segundos; })));
        console.log((veredicto.ok ? '✔ ' : '✖ ') + caso.id + (o.repeticiones > 1 ? ' #' + (rep + 1) : '') +
                    '  (' + traza.turnos.length + ' turnos, el más lento ' + lento.toFixed(1) + ' s)');
        veredicto.fallos.forEach(function (f) { console.log('    · ' + f); });
        if (traza.desconocidas.length) console.log('    · pidió al backend algo que el mundo falso no tiene: ' + traza.desconocidas.join(', '));
        rojo = rojo || !veredicto.ok;
        resultados.push({ id: caso.id, repeticion: rep, ok: veredicto.ok, fallos: veredicto.fallos, traza: traza });
      }
    }
  } finally {
    puente.kill('SIGTERM');
    // Hasta que no ha salido (y la sesión de Claude con él) no se borra nada: lo último que
    // hace al cerrarse es escribir su transcripción, y volvía a crear lo recién borrado.
    await new Promise(function (r) {
      if (puente.exitCode !== null) return r();
      puente.once('exit', r);
      setTimeout(r, 3000);
    });
    await new Promise(function (r) { setTimeout(r, 1000); });
    await mundo.cerrar();
    fs.closeSync(registro);
    if (o.conservar) console.log('\nDirectorio de trabajo conservado: ' + tmp);
    else {
      fs.rmSync(tmp, { recursive: true, force: true });
      // Claude Code guarda cada sesión por directorio de trabajo: las de mentira no se
      // quedan, y nunca se mezclan con las del teléfono (el repaso lee esas).
      const sesiones = path.join(os.homedir(), '.claude', 'projects', montado.cwd.replace(/[^a-zA-Z0-9]/g, '-'));
      if (/simulador-/.test(path.basename(sesiones))) fs.rmSync(sesiones, { recursive: true, force: true });
    }
  }

  const bien = resultados.filter(function (r) { return r.ok; }).length;
  const segundos = resultados.flatMap(function (r) { return r.traza.turnos.map(function (t) { return t.segundos; }); })
    .filter(Boolean).sort(function (a, b) { return a - b; });
  const mediana = segundos.length ? segundos[Math.floor(segundos.length / 2)] : 0;
  console.log('\n' + bien + ' de ' + resultados.length + ' llamadas bien. Turno mediano: ' + mediana.toFixed(1) + ' s.');
  // Fuera del repositorio y solo para él: una llamada simulada con casos reales lleva lo
  // que se dijo en la de verdad, y el repositorio es público.
  fs.mkdirSync(o.salida, { recursive: true, mode: 0o700 });
  const sello = new Date().toISOString().replace(/[:.]/g, '-').slice(0, 19);
  const donde = path.join(o.salida, sello + '.json');
  fs.writeFileSync(donde, JSON.stringify({ cuando: new Date().toISOString(), ruido: o.ruido, casos: o.casos,
    bien: bien, total: resultados.length, turno_mediano_s: mediana, resultados: resultados }, null, 1), { mode: 0o600 });
  console.log('Detalle: ' + donde);
  process.exitCode = rojo ? 1 : 0;
}

if (require.main === module) {
  principal().catch(function (e) { console.error('Simulador: ' + e.message); process.exitCode = 2; });
}

module.exports = { correrCaso, extraerVoz, montarPuente, opciones, MAX_LLAMADAS };
