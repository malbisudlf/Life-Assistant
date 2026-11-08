/**
 * Sesión viva: UN proceso de Claude Code por llamada, en vez de uno por turno (parche 19).
 *
 * Hasta aquí cada turno era un `claude -p --resume` nuevo, y arrancarlo costaba ~3,5 s
 * fijos de Node antes de que el modelo empezara a pensar (medido el 2026-10-13, ver
 * «Los parches 15 y 16» en telefono/PARCHES.md del repo de Life Assistant). Con
 * `--input-format stream-json` el proceso se queda abierto leyendo mensajes por stdin y
 * suelta un evento `result` por turno: medido en caja el 2026-10-15, el segundo turno
 * de «responde solo: adiós» bajó de ~8 s a 1,3 s.
 *
 * Lo que no se puede perder respecto al camino viejo:
 *  - **Los mismos argumentos de siempre** (permisos, modelo, --session-id/--resume): la
 *    sesión se guarda en disco igual, así que si el proceso muere a media llamada el
 *    turno siguiente puede seguir por el camino viejo con --resume sin perder el hilo.
 *  - **Un turno colgado no deja la llamada colgada para siempre**: pasado TURNO_MS se
 *    mata el proceso, y lo que esperaba falla (quien llama cae al camino viejo).
 *  - **Nada vivo al colgar**: se cierra en /end-session, y si nadie lo cierra (la
 *    voice-app reiniciada a media llamada), por inactividad.
 */

const { spawn } = require('child_process');

const TURNO_MS    = parseInt(process.env.SESION_VIVA_TURNO_MS) || 120 * 1000;
const INACTIVA_MS = parseInt(process.env.SESION_VIVA_INACTIVA_MS) || 10 * 60 * 1000;
const CIERRE_MS   = 5000;

function crear({ args, env, cwd, bin }) {
  const inicio = Date.now();
  const proc = spawn(bin || process.env.CLAUDE_BIN || 'claude', args, {
    stdio: ['pipe', 'pipe', 'pipe'], shell: false, env, cwd,
  });
  const pendientes = [];          // FIFO: Claude contesta los turnos en orden
  const alMorir = [];
  let buffer = '';
  let stderr = '';
  let viva = true;
  let inactividad = null;

  function morir(motivo) {
    if (!viva) return;
    viva = false;
    clearTimeout(inactividad);
    const error = new Error(motivo + (stderr ? ': ' + stderr.slice(-500) : ''));
    while (pendientes.length) {
      const p = pendientes.shift();
      clearTimeout(p.reloj);
      p.reject(error);
    }
    for (const fn of alMorir) {
      try { fn(); } catch { /* quien escucha no puede tumbar a los demás */ }
    }
  }

  function cerrar() {
    if (!viva) return;
    try { proc.stdin.end(); } catch { /* ya cerrado */ }
    const matar = setTimeout(function () { try { proc.kill('SIGTERM'); } catch { /* ya muerto */ } }, CIERRE_MS);
    if (matar.unref) matar.unref();
    morir('la sesión viva se ha cerrado');
  }

  function reiniciarInactividad() {
    clearTimeout(inactividad);
    inactividad = setTimeout(function () {
      console.log('[SESION-VIVA] Cerrada por inactividad');
      cerrar();
    }, INACTIVA_MS);
    if (inactividad.unref) inactividad.unref();
  }

  proc.stdout.on('data', function (trozo) {
    buffer += trozo.toString();
    let i;
    while ((i = buffer.indexOf('\n')) >= 0) {
      const linea = buffer.slice(0, i);
      buffer = buffer.slice(i + 1);
      let evento;
      try { evento = JSON.parse(linea); } catch { continue; }
      // Parche 28: Claude Code suelta un `system init` al empezar cada turno. Así se
      // sabe cuál está en marcha, que es el único que una interrupción puede cortar.
      if (evento.type === 'system' && evento.subtype === 'init') {
        const p = pendientes.find(function (x) { return !x.empezado; });
        if (p) {
          p.empezado = true;
          if (p.cortar) enviarInterrupcion();
        }
        continue;
      }
      if (evento.type !== 'result') continue;
      const p = pendientes.shift();
      if (!p) continue;
      clearTimeout(p.reloj);
      p.resolve({
        response: String(evento.result || ''),
        sessionId: evento.session_id || null,
        isError: Boolean(evento.is_error),
        cortado: Boolean(p.cortar),
        duration_ms: Date.now() - p.enviado,
      });
    }
  });
  proc.stderr.on('data', function (trozo) {
    stderr = (stderr + trozo.toString()).slice(-4000);
  });
  proc.on('error', function (e) { morir('no se pudo lanzar claude (' + e.message + ')'); });
  proc.on('close', function (code) { morir('claude se cerró (código ' + code + ')'); });
  proc.stdin.on('error', function () { /* lo cuenta el close */ });

  function preguntar(texto) {
    if (!viva) return Promise.reject(new Error('la sesión viva ya no está'));
    reiniciarInactividad();
    return new Promise(function (resolve, reject) {
      const p = { resolve, reject, enviado: Date.now() };
      p.reloj = setTimeout(function () {
        console.warn('[SESION-VIVA] Turno sin respuesta en ' + TURNO_MS + ' ms: se mata');
        try { proc.kill('SIGTERM'); } catch { /* ya muerto */ }
        morir('turno sin respuesta en ' + TURNO_MS + ' ms');
      }, TURNO_MS);
      pendientes.push(p);
      proc.stdin.write(JSON.stringify({
        type: 'user', message: { role: 'user', content: String(texto) },
      }) + '\n');
    });
  }

  // Parche 34: cambia de modelo para los turnos siguientes (se manda por stdin, así que
  // va en orden con las preguntas).
  let controles = 0;
  function fijarModelo(modelo) {
    if (!viva) return;
    proc.stdin.write(JSON.stringify({
      type: 'control_request', request_id: 'modelo-' + (++controles), request: { subtype: 'set_model', model: modelo },
    }) + '\n');
  }

  let cortes = 0;
  function enviarInterrupcion() {
    proc.stdin.write(JSON.stringify({
      type: 'control_request', request_id: 'corta-' + (++cortes), request: { subtype: 'interrupt' },
    }) + '\n');
  }

  /**
   * Parche 28: corta el turno en curso, que suelta igualmente su `result` (con error),
   * así que la FIFO no se descuadra, y lo ya enviado se queda en la conversación. Si
   * el turno aún no ha empezado, se corta en cuanto empiece: interrumpir antes no hace
   * nada y el turno correría entero. Devuelve false si no hay nada que cortar.
   */
  function interrumpir() {
    const p = pendientes[0];
    if (!viva || !p || p.cortar) return false;
    p.cortar = true;
    if (p.empezado) enviarInterrupcion();
    return true;
  }

  reiniciarInactividad();
  return {
    preguntar,
    interrumpir,
    fijarModelo,
    cerrar,
    alMorir: function (fn) { alMorir.push(fn); },
    get viva() { return viva; },
    get edad_ms() { return Date.now() - inicio; },
  };
}

module.exports = { crear, TURNO_MS, INACTIVA_MS };
