/**
 * El mundo falso del simulador: lo que la sesión de Claude del teléfono cree que es el
 * backend. Ver docs/SIMULADOR.md.
 *
 * Sirve lo mismo que le pide el puente y la llamada al backend de verdad:
 *   POST /mcp/telefono            el MCP del teléfono (initialize, tools/list, tools/call)
 *   GET  /telefono/contexto       lo ya mirado al descolgar
 *   GET  /telefono/confirmar/:id  la pregunta de una propuesta
 *   POST /telefono/confirmar/:id  el sí o el no
 *
 * **Nada de aquí sale de este proceso.** Es la razón de que exista: una llamada simulada
 * que dice «abre el garaje» o «dile a Ane que llego tarde» tiene que poder decir que sí
 * sin que se abra nada ni salga ningún mensaje. Las herramientas contestan lo que diga el
 * caso (`mundo`), y lo que no diga, un `{"ok": true}` que no significa nada.
 *
 * El catálogo de herramientas SÍ es el de verdad (nombres, descripciones y parámetros):
 * lo pide `simular.js` al backend una vez, solo para leerlo, y se lo pasa aquí.
 */
'use strict';

const http = require('http');
const crypto = require('crypto');

// Las que el backend no hace sin un sí (ver «Qué pide permiso» en docs/JARVIS.md y el
// final de telefono/RUNBOOK.md). Un caso puede cambiarlas con `se_confirma`.
const SE_CONFIRMAN = ['whatsapp_enviar', 'whatsapp_programar', 'borrar_idea', 'pelis_borrar', 'garaje'];

// La misma nota que `_proponer_en_movil` en backend/main.py: es parte de lo que Claude
// lee, así que es parte de lo que se prueba. Si cambia allí, cambia aquí.
const NOTA_PROPUESTA =
  'NO está hecho. Pon linea_para_la_llamada tal cual en tu respuesta: la llamada se lo ' +
  'pregunta en una frase y él contesta sí o no hablando. En VOICE_RESPONSE di SOLO «De ' +
  'acuerdo.»: no repitas lo que se hará ni le pidas que confirme, que eso ya lo dice la ' +
  'llamada. Un sí hablado vale, no le mandes al móvil. Tú no confirmas nada.';

const CONTEXTO_POR_DEFECTO =
  'Hoy no le queda nada en la agenda. Mañana: nada apuntado. Tiempo: 14 grados y nubes. ' +
  'Sin tareas que venzan hoy. Está en casa.';

function leerCuerpo(req) {
  return new Promise(function (resolve) {
    const trozos = [];
    let total = 0;
    req.on('data', function (t) { total += t.length; if (total < 1e6) trozos.push(t); });
    req.on('end', function () {
      try { resolve(JSON.parse(Buffer.concat(trozos).toString('utf8') || '{}')); } catch { resolve({}); }
    });
    req.on('error', function () { resolve({}); });
  });
}

function crearMundo(opciones) {
  const catalogo = (opciones && opciones.catalogo) || [];
  let caso = {};
  let llamadas = [];        // { nombre, args }
  let propuestas = {};      // id → { herramienta, args, frase, respuesta }
  let desconocidas = [];    // rutas que nadie esperaba: algo que el simulador no cubre

  function poner(nuevo) {
    caso = nuevo || {};
    llamadas = [];
    propuestas = {};
    desconocidas = [];
  }

  /** Lo que contesta una herramienta. Devuelve { resultado, error }. */
  function usar(nombre, args) {
    llamadas.push({ nombre: nombre, args: args });
    const preparado = (caso.mundo || {})[nombre];
    if (preparado && typeof preparado === 'object' && preparado._error) {
      return { error: String(preparado._error) };
    }
    if (preparado !== undefined) return { resultado: preparado };
    const confirman = caso.se_confirma || SE_CONFIRMAN;
    if (confirman.indexOf(nombre) >= 0) {
      const id = crypto.randomUUID();
      const frase = ((caso.frases || {})[nombre]) || (nombre + ' ' + JSON.stringify(args));
      propuestas[id] = { herramienta: nombre, args: args, frase: frase, respuesta: null };
      return { resultado: { ok: true, estado: 'pendiente_en_el_movil', id: id, canal: 'ninguno',
                            lo_que_se_hara: frase, linea_para_la_llamada: '✅ CONFIRMAR: ' + id,
                            nota: NOTA_PROPUESTA } };
    }
    return { resultado: { ok: true } };
  }

  function rpc(cuerpo) {
    const id = cuerpo.id;
    const metodo = cuerpo.method;
    if (metodo === 'initialize') {
      return { cabeceras: { 'Mcp-Session-Id': 'simulacro' },
               json: { jsonrpc: '2.0', id: id, result: {
                 protocolVersion: (cuerpo.params || {}).protocolVersion || '2025-03-26',
                 capabilities: { tools: {} },
                 serverInfo: { name: 'life-assistant-jarvis-telefono', version: '1.0' } } } };
    }
    if (typeof metodo === 'string' && metodo.indexOf('notifications/') === 0) return { estado: 204 };
    if (metodo === 'ping') return { json: { jsonrpc: '2.0', id: id, result: {} } };
    if (metodo === 'tools/list') return { json: { jsonrpc: '2.0', id: id, result: { tools: catalogo } } };
    if (metodo === 'tools/call') {
      const p = cuerpo.params || {};
      const nombre = String(p.name || '');
      const args = (p.arguments && typeof p.arguments === 'object') ? p.arguments : {};
      if (catalogo.length && !catalogo.some(function (h) { return h.name === nombre; })) {
        return { json: { jsonrpc: '2.0', id: id, error: { code: -32602, message: 'Herramienta desconocida: ' + nombre } } };
      }
      const r = usar(nombre, args);
      if (r.error) {
        return { json: { jsonrpc: '2.0', id: id, result: { isError: true, content: [{ type: 'text', text: r.error }] } } };
      }
      return { json: { jsonrpc: '2.0', id: id, result: { content: [{ type: 'text', text: JSON.stringify(r.resultado) }] } } };
    }
    return { json: { jsonrpc: '2.0', id: id, error: { code: -32601, message: 'Método desconocido: ' + metodo } } };
  }

  async function atender(req, res) {
    const ruta = (req.url || '').split('?')[0];
    function responder(estado, json, cabeceras) {
      res.writeHead(estado, Object.assign({ 'Content-Type': 'application/json' }, cabeceras || {}));
      res.end(json === undefined ? '' : JSON.stringify(json));
    }
    if (ruta === '/mcp/telefono' && req.method === 'POST') {
      const r = rpc(await leerCuerpo(req));
      return responder(r.estado || 200, r.json, r.cabeceras);
    }
    if (ruta === '/mcp/telefono') return responder(405, { error: 'solo POST' });
    if (ruta === '/telefono/contexto' && req.method === 'GET') {
      return responder(200, { texto: caso.contexto || CONTEXTO_POR_DEFECTO });
    }
    const m = ruta.match(/^\/telefono\/confirmar\/([0-9a-f-]{36})$/);
    if (m) {
      const p = propuestas[m[1]];
      if (!p) return responder(200, { ok: false, motivo: 'Esa propuesta no existe.', frase: 'Esa propuesta no existe.' });
      if (req.method === 'GET') {
        return responder(200, { ok: true, frase: p.frase, pregunta: (caso.preguntas || {})[p.herramienta] || '¿Lo hago?' });
      }
      const cuerpo = await leerCuerpo(req);
      p.respuesta = cuerpo.respuesta === 'si' ? 'si' : 'no';
      return responder(200, { ok: true, hecho: true, frase: p.respuesta === 'si' ? 'Hecho.' : 'Vale, no lo hago.' });
    }
    desconocidas.push(req.method + ' ' + ruta);
    return responder(404, { error: 'El mundo falso no tiene ' + ruta });
  }

  const servidor = http.createServer(function (req, res) {
    atender(req, res).catch(function (e) {
      res.writeHead(500, { 'Content-Type': 'application/json' });
      res.end(JSON.stringify({ error: e.message }));
    });
  });

  return {
    poner: poner,
    usar: usar,
    rpc: rpc,
    llamadas: function () { return llamadas.slice(); },
    propuestas: function () { return Object.keys(propuestas).map(function (id) { return Object.assign({ id: id }, propuestas[id]); }); },
    desconocidas: function () { return desconocidas.slice(); },
    escuchar: function () {
      return new Promise(function (resolve, reject) {
        servidor.once('error', reject);
        // Solo en la propia máquina: es un backend de mentira, sin credencial.
        servidor.listen(0, '127.0.0.1', function () { resolve('http://127.0.0.1:' + servidor.address().port); });
      });
    },
    cerrar: function () { return new Promise(function (resolve) { servidor.close(function () { resolve(); }); }); },
  };
}

module.exports = { crearMundo, SE_CONFIRMAN, NOTA_PROPUESTA, CONTEXTO_POR_DEFECTO };
