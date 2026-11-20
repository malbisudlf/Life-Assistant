/**
 * Parche 52: la grabación de las llamadas a otras personas (2026-11-20).
 * Ver telefono/PARCHES.md y docs/LLAMADAS_TERCEROS.md en Life Assistant.
 *
 * Mikel le pidió a Jarvis que le preguntara a un amigo dónde estaba y le llegó «en el
 * mine»: el oído entendió mal y no había forma de saber qué dijo. Ahora cada llamada a un
 * tercero se graba, para volver a escucharla o transcribirla con calma.
 *
 *   - **La graba FreeSWITCH** (`uuid_record`), en ESTÉREO: a la izquierda lo que dice el
 *     otro y a la derecha lo que dice Jarvis. Así el backend puede volver a transcribir
 *     solo al otro, con el modelo grande, sin que la voz de Jarvis estorbe.
 *   - **En `~/telefono-grabaciones` de caja**, montada en FreeSWITCH (que escribe) y en la
 *     voice-app (que la sirve y la limpia) en la misma ruta, `/grabaciones`. El nombre es
 *     el id de la llamada del backend (`tercero`), ya validado como UUID.
 *   - **Se borran solas a los GRABACIONES_DIAS días** (30): son voces de otros.
 *   - **Sin aviso**: decisión de Mikel; no son llamadas comerciales.
 *   - **Grabar nunca tumba la llamada**: si FreeSWITCH no puede, se registra y se sigue.
 *   - `GRABAR=0` en `~/.claude-phone/.env` lo apaga.
 */
'use strict';

const fs = require('fs');
const path = require('path');

const DIR = process.env.GRABACIONES_DIR || '/grabaciones';
const DIAS = parseInt(process.env.GRABACIONES_DIAS, 10) || 30;
const ID_RE = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/;
const ORDEN_MS = 3000;

function activa() {
  return process.env.GRABAR !== '0';
}

function ruta(id) {
  return ID_RE.test(String(id || '')) ? path.join(DIR, id + '.wav') : null;
}

function conTope(promesa, ms) {
  return Promise.race([promesa, new Promise(function (_, mal) {
    setTimeout(function () { mal(new Error('sin respuesta')); }, ms);
  })]);
}

/** Empieza a grabar. Devuelve la ruta, o null si no se graba (apagado, id raro o fallo). */
async function empezar(endpoint, id, log) {
  const fichero = ruta(id);
  if (!activa() || !fichero || !endpoint || !endpoint.uuid) return null;
  try {
    if (endpoint.set) await conTope(endpoint.set('RECORD_STEREO', 'true'), ORDEN_MS);
    const r = await conTope(endpoint.api('uuid_record', endpoint.uuid + ' start ' + fichero), ORDEN_MS);
    const cuerpo = String((r && (r.body || r)) || '');
    if (/^-ERR/.test(cuerpo)) throw new Error(cuerpo.trim().slice(0, 80));
    if (log) log('GRABACIÓN: empieza (' + id + ')');
    return fichero;
  } catch (e) {
    if (log) log('GRABACIÓN: no se puede grabar (' + e.message + '); la llamada sigue');
    return null;
  }
}

/** La para. Con la llamada ya colgada FreeSWITCH la cierra solo: un fallo aquí no importa. */
async function parar(endpoint, fichero) {
  if (!fichero || !endpoint || !endpoint.uuid) return;
  try {
    await conTope(endpoint.api('uuid_record', endpoint.uuid + ' stop ' + fichero), ORDEN_MS);
  } catch (e) { /* ya parada */ }
}

/** Borra las de más de DIAS días. Devuelve cuántas. */
function limpiar(ahora) {
  const tope = (ahora || Date.now()) - DIAS * 86400000;
  let borradas = 0;
  let nombres = [];
  try { nombres = fs.readdirSync(DIR); } catch (e) { return 0; }
  for (const n of nombres) {
    if (!/\.wav$/.test(n)) continue;
    const f = path.join(DIR, n);
    try {
      if (fs.statSync(f).mtimeMs < tope) { fs.unlinkSync(f); borradas++; }
    } catch (e) { /* otra la borró antes */ }
  }
  return borradas;
}

/** Las que hay, de la más nueva a la más vieja: {id, fecha, bytes}. */
function listar() {
  let nombres = [];
  try { nombres = fs.readdirSync(DIR); } catch (e) { return []; }
  const salida = [];
  for (const n of nombres) {
    const id = n.replace(/\.wav$/, '');
    if (!ID_RE.test(id) || !/\.wav$/.test(n)) continue;
    try {
      const st = fs.statSync(path.join(DIR, n));
      salida.push({ id: id, fecha: new Date(st.mtimeMs).toISOString(), bytes: st.size });
    } catch (e) { /* borrada entre medias */ }
  }
  return salida.sort(function (a, b) { return a.fecha < b.fecha ? 1 : -1; });
}

function llaveOk(req) {
  const llave = process.env.TELEFONO_TERCEROS_TOKEN || '';
  return !!llave && req.get('X-Auth-Token') === llave;
}

/** GET /api/grabaciones y GET /api/grabacion/:id, con la llave de los terceros. */
function montar(app) {
  app.get('/api/grabaciones', function (req, res) {
    if (!llaveOk(req)) return res.status(403).json({ ok: false });
    res.json({ ok: true, grabaciones: listar().slice(0, 50) });
  });
  app.get('/api/grabacion/:id', function (req, res) {
    if (!llaveOk(req)) return res.status(403).json({ ok: false });
    const fichero = ruta(req.params.id);
    if (!fichero || !fs.existsSync(fichero)) return res.status(404).json({ ok: false });
    res.set('Cache-Control', 'no-store');
    res.type('audio/wav');
    fs.createReadStream(fichero).pipe(res);
  });
  // La limpieza, al arrancar y cada seis horas.
  const pasar = function () {
    const n = limpiar();
    if (n) console.log('[' + new Date().toISOString() + '] GRABACIÓN: ' + n + ' borradas por viejas');
  };
  setTimeout(pasar, 10000).unref();
  setInterval(pasar, 6 * 3600 * 1000).unref();
}

module.exports = { empezar, parar, limpiar, listar, montar, ruta, DIR };
