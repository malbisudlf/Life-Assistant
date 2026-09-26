/**
 * Bitácora de llamadas: la memoria de Jarvis entre una llamada y la siguiente.
 *
 * Cada llamada es una sesión de Claude Code distinta, así que al colgar se olvidaba
 * todo: si te llamaba, no lo cogías y le devolvías la llamada, no sabía para qué te
 * había llamado. Aquí se apunta cada llamada (saliente, entrante o al buzón), lo que
 * se iba a decir y lo que se habló, y al empezar una sesión nueva se le pasa a Claude.
 *
 * Vive en un JSON junto al CLAUDE.md del directorio de trabajo, no en memoria: el
 * servicio se reinicia y la llamada que más importa recordar es justo la anterior.
 */

const fs = require('fs');
const path = require('path');

const RUTA = process.env.BITACORA_PATH || path.join(process.cwd(), 'llamadas-recientes.json');
const HORAS = parseInt(process.env.BITACORA_HORAS) || 72;
const MAX_LLAMADAS = 40;       // guardadas
const MAX_EN_PROMPT = 12;      // las que se le pasan a Claude
const MAX_TURNOS = 8;          // por llamada
const MAX_TEXTO = 400;

const PREFIJO_SALIENTE = '[SYSTEM CONTEXT - DO NOT REPEAT]: You just called the user to tell them: "';

function recortar(texto, max) {
  const t = String(texto || '').replace(/\s+/g, ' ').trim();
  return t.length > max ? t.slice(0, max - 1) + '…' : t;
}

function leer() {
  try {
    const datos = JSON.parse(fs.readFileSync(RUTA, 'utf8'));
    return Array.isArray(datos) ? datos : [];
  } catch {
    return [];
  }
}

function guardar(llamadas) {
  const limite = Date.now() - HORAS * 3600 * 1000;
  const vigentes = llamadas
    .filter(function (l) { return Date.parse(l.inicio) >= limite; })
    .slice(-MAX_LLAMADAS);
  // Escritura atómica: un JSON a medias es perder toda la memoria de golpe.
  const tmp = RUTA + '.tmp';
  fs.writeFileSync(tmp, JSON.stringify(vigentes, null, 1));
  fs.renameSync(tmp, RUTA);
}

function actualizar(callId, cambio) {
  if (!callId) return;
  try {
    const llamadas = leer();
    let l = llamadas.find(function (x) { return x.callId === callId; });
    if (!l) {
      l = { callId: callId, tipo: 'entrante', inicio: new Date().toISOString(), turnos: [] };
      llamadas.push(l);
    }
    cambio(l);
    guardar(llamadas);
  } catch (e) {
    // La memoria es un extra: si falla, la llamada sigue igual.
    console.warn('[BITACORA] No se pudo guardar:', e.message);
  }
}

/** Lo que llega a /ask. Devuelve true si era el aviso de «acabas de llamarle». */
function apuntarConsulta(callId, prompt) {
  const p = String(prompt || '');
  if (p.startsWith(PREFIJO_SALIENTE)) {
    const fin = p.indexOf('". They have answered');
    const mensaje = p.slice(PREFIJO_SALIENTE.length, fin > 0 ? fin : undefined);
    actualizar(callId, function (l) {
      l.tipo = 'saliente';
      l.mensaje = recortar(mensaje, MAX_TEXTO);
      l.contestada = true;
    });
    return true;
  }
  return false;
}

function apuntarTurno(callId, dicho, respuesta) {
  const m = /VOICE_RESPONSE:\s*(.+)/.exec(String(respuesta || ''));
  actualizar(callId, function (l) {
    l.turnos = (l.turnos || []).concat([{
      mikel: recortar(dicho, MAX_TEXTO),
      jarvis: recortar(m ? m[1] : respuesta, MAX_TEXTO)
    }]).slice(-MAX_TURNOS);
  });
}

/** Lo que manda voice-app al acabar una llamada saliente (POST /bitacora). */
function apuntarSaliente(datos) {
  if (!datos || !datos.callId) return;
  actualizar(datos.callId, function (l) {
    l.tipo = datos.mode === 'announce' ? 'buzon' : 'saliente';
    if (datos.createdAt) l.inicio = datos.createdAt;
    if (datos.message) l.mensaje = recortar(datos.message, MAX_TEXTO);
    l.contestada = !!datos.answeredAt;
    l.resultado = datos.reason || datos.state || null;
  });
}

function hora(iso) {
  const d = new Date(iso);
  const opciones = { timeZone: 'Europe/Madrid' };
  const dia = function (x) { return x.toLocaleDateString('es-ES', opciones); };
  const hhmm = d.toLocaleTimeString('es-ES', Object.assign({ hour: '2-digit', minute: '2-digit' }, opciones));
  if (dia(d) === dia(new Date())) return 'hoy a las ' + hhmm;
  if (dia(d) === dia(new Date(Date.now() - 86400000))) return 'ayer a las ' + hhmm;
  return d.toLocaleDateString('es-ES', Object.assign({ weekday: 'long' }, opciones)) + ' a las ' + hhmm;
}

function describir(l) {
  let linea;
  if (l.tipo === 'buzon') {
    linea = '- ' + hora(l.inicio) + ', Jarvis ' + (l.contestada
      ? 'dejó este mensaje en el buzón de Mikel'
      : 'intentó dejar un mensaje en el buzón (no se grabó)') + ': «' + (l.mensaje || '') + '»';
  } else if (l.tipo === 'saliente') {
    linea = '- ' + hora(l.inicio) + ', Jarvis llamó a Mikel ' +
      (l.contestada ? 'y lo cogió' : 'y NO lo cogió') + '. Le llamaba para decirle: «' + (l.mensaje || '') + '»';
  } else {
    linea = '- ' + hora(l.inicio) + ', Mikel llamó a Jarvis.';
  }
  const turnos = (l.turnos || []).map(function (t) {
    return '    Mikel: «' + t.mikel + '» / Jarvis: «' + t.jarvis + '»';
  });
  return [linea].concat(turnos).join('\n');
}

/** El bloque que se antepone al primer mensaje de cada sesión nueva. */
function contexto(callIdActual) {
  const otras = leer().filter(function (l) { return l.callId !== callIdActual; }).slice(-MAX_EN_PROMPT);
  if (!otras.length) return '';
  return '[LLAMADAS RECIENTES — tu memoria entre llamadas, de la más antigua a la más nueva]\n' +
    otras.map(describir).join('\n') + '\n' +
    'Si Mikel pregunta por una llamada anterior («antes me has llamado, ¿qué querías?», «¿qué me ' +
    'dejaste en el buzón?»), contéstale con esto. Si no pregunta, no lo saques.\n' +
    '[FIN LLAMADAS RECIENTES]\n\n';
}

module.exports = { apuntarConsulta, apuntarTurno, apuntarSaliente, contexto, RUTA };
