/**
 * Lo que Jarvis ya sabe al descolgar (parche 19): la agenda que queda de hoy y la de
 * mañana, el tiempo, las tareas que vencen, los recordatorios y dónde estás, pedidos al
 * backend (`GET /telefono/contexto`) y metidos al empezar cada sesión.
 *
 * Es lo mismo que el permiso de despliegue ya hacía: la pregunta más probable de la
 * llamada se contesta sin ir a buscar el dato, que por herramienta son tres pasos en
 * serie. Si el backend no contesta a tiempo, la llamada sigue sin él: es un extra de
 * velocidad, no una condición.
 *
 * El token es el del MCP del teléfono, el mismo que ya lleva `.mcp.json` en el
 * directorio de trabajo (y `LECTURA_TOKEN` en la voice-app): no hace falta otro sitio
 * donde ponerlo ni otro sitio donde rotarlo.
 */

const fs = require('fs');
const path = require('path');

const URL_BACKEND = process.env.CONTEXTO_URL || 'http://127.0.0.1:8080';
const ESPERA_MS   = parseInt(process.env.CONTEXTO_ESPERA_MS) || 2500;

function token() {
  if (process.env.CONTEXTO_TOKEN) return process.env.CONTEXTO_TOKEN;
  try {
    const mcp = JSON.parse(fs.readFileSync(path.join(process.cwd(), '.mcp.json'), 'utf8'));
    for (const servidor of Object.values(mcp.mcpServers || {})) {
      const auth = (servidor.headers || {}).Authorization || '';
      if (/^Bearer /.test(auth) && /\/mcp\/telefono/.test(servidor.url || '')) {
        return auth.slice('Bearer '.length);
      }
    }
  } catch { /* sin .mcp.json no hay token */ }
  return '';
}

/** El bloque para el prompt, o '' si no se ha podido traer. Nunca lanza. */
async function pedir({ fetchFn = globalThis.fetch } = {}) {
  const t = token();
  if (!t) {
    console.warn('[CONTEXTO] Sin token del MCP del teléfono: la llamada empieza sin contexto');
    return '';
  }
  const abortar = new AbortController();
  const reloj = setTimeout(function () { abortar.abort(); }, ESPERA_MS);
  try {
    const r = await fetchFn(URL_BACKEND + '/telefono/contexto', {
      headers: { Authorization: 'Bearer ' + t }, signal: abortar.signal,
    });
    if (!r.ok) {
      console.warn('[CONTEXTO] El backend respondió ' + r.status);
      return '';
    }
    const texto = String(((await r.json()) || {}).texto || '').trim();
    return texto ? '[CONTEXTO AL DESCOLGAR]\n' + texto + '\n[FIN DEL CONTEXTO]\n\n' : '';
  } catch (e) {
    console.warn('[CONTEXTO] No se pudo traer (' + (e.name === 'AbortError' ? 'tardó más de ' + ESPERA_MS + ' ms' : e.message) + ')');
    return '';
  } finally {
    clearTimeout(reloj);
  }
}

module.exports = { pedir, token };
