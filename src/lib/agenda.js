// ── LO SIGUIENTE ─────────────────────────────────────────────────────────────
// Lógica pura del widget «Lo siguiente»: qué es lo próximo con hora, cuánto falta y,
// si hay que desplazarse, en qué fase está la hora de salida. Sin React, sin fetch y
// sin localStorage a propósito: el componente vive en Dashboard.jsx y solo pinta lo
// que sale de aquí, y la memoria del modo (coche/andando) se guarda allí con esta
// forma pero sin que esto sepa dónde.
//
// Las fechas pasan SIEMPRE por `aFechaLocal` (lineaTiempo.js), nunca por `new Date(iso)`
// a secas: es el punto único que sabe distinguir un ISO de Graph de una fecha suelta, y
// la invariante número uno de este repositorio es no dejar que el navegador negocie
// husos por su cuenta.

import { aFechaLocal, tieneHora, desplazarDia, fechaLocalISO } from "./lineaTiempo.js";
import { MESES_CORTOS_ES } from "./helpers.js";

// Espejo del valor por defecto de `SALIR_VENTANA_MIN` en el backend (las reglas de
// «sal ya»). Si un evento entra en esa ventana, el backend ya va a calcular la salida
// para avisar; el dashboard la pide en el mismo momento y la caché de /maps/departure
// hace que las dos cosas sean UNA petición a Google. Si cambias uno, cambia el otro.
export const VENTANA_SALIDA_MIN = 180;
// A partir de aquí la salida deja de ser holgada y se pinta en ámbar.
export const UMBRAL_PRONTO_MIN  = 15;
// Lo mismo que consulta /calendar/events: más allá no hay datos, así que decir «nada»
// de lo que queda fuera sería afirmar algo que nadie ha mirado.
export const HORIZONTE_DIAS     = 7;

const DIAS_SEMANA = ["domingo", "lunes", "martes", "miércoles", "jueves", "viernes", "sábado"];

// ── Ubicaciones ──────────────────────────────────────────────────────────────

const MARCAS_ONLINE = ["teams", "zoom", "meet.google", "webex", "skype",
                       "en línea", "en linea", "online", "virtual"];

// ¿El «lugar» del evento NO es un sitio al que ir? Outlook rellena la ubicación con
// «Reunión de Microsoft Teams» o con el enlace, y pedirle a Google la ruta hasta eso
// es pagar una petición para recibir un NOT_FOUND.
export function esUbicacionOnline(lugar) {
  const t = String(lugar ?? "").trim().toLowerCase();
  if (!t) return true;
  if (/^https?:\/\//.test(t)) return true;
  return MARCAS_ONLINE.some(m => t.includes(m));
}

// ── Próximo compromiso ───────────────────────────────────────────────────────

function normalizar(ev, tipo, ahora, limite, marcadorEntregas) {
  if (!ev || ev.isAllDay) return null;
  if (marcadorEntregas && typeof ev.title === "string" && ev.title.includes(marcadorEntregas)) return null;
  if (!tieneHora(ev.start)) return null;
  const inicio = aFechaLocal(ev.start);
  const fin    = aFechaLocal(ev.end);
  if (!inicio || !fin) return null;
  if (fin.getTime() <= ahora.getTime()) return null;
  if (inicio.getTime() > limite) return null;
  return {
    key:    ev.id || ev.start,
    id:     ev.id,
    titulo: ev.title || "(Sin título)",
    lugar:  String(ev.location || "").trim(),
    inicio,
    fin,
    tipo,
    start:  ev.start,       // el ISO crudo: es lo que /maps/departure espera
    raw:    ev,
  };
}

// Empate a la misma hora: primero el evento de Outlook y después la clase. Un evento
// que coincide con una clase casi siempre es la excepción (una tutoría, un examen) y es
// lo que conviene tener delante.
const RANGO_TIPO = { evento: 0, clase: 1 };

// Las entregas (`marcadorEntregas` en el título) no cuentan: son plazos, no citas, y ya
// tienen su widget. Con ellas dentro, una entrega a las 23:59 tapaba la reunión de
// mañana y la cabecera (momento.js, que las excluía) decía otra cosa que este widget.
export function proximoCompromiso(eventos = [], clases = [], ahora = new Date(), { marcadorEntregas = "" } = {}) {
  const vacio = { actual: null, siguiente: null, huecoMin: null };
  const t0 = aFechaLocal(ahora);
  if (!t0) return vacio;
  const limite = t0.getTime() + HORIZONTE_DIAS * 24 * 3600 * 1000;

  const vistos = new Set();
  const todos = [];
  const fuentes = [[eventos, "evento"], [clases, "clase"]];
  for (const [lista, tipo] of fuentes) {
    for (const ev of Array.isArray(lista) ? lista : []) {
      const c = normalizar(ev, tipo, t0, limite, marcadorEntregas);
      if (!c) continue;
      // Un mismo evento puede llegar por las dos listas (el calendario de clases es
      // también un calendario de Outlook): contarlo dos veces lo pondría de «actual»
      // y de «siguiente» a la vez.
      if (c.id) {
        if (vistos.has(c.id)) continue;
        vistos.add(c.id);
      }
      todos.push(c);
    }
  }

  const ahoraMs = t0.getTime();
  const enCurso = todos
    .filter(c => c.inicio.getTime() <= ahoraMs && ahoraMs < c.fin.getTime())
    .sort((a, b) => (a.fin - b.fin) || (RANGO_TIPO[a.tipo] - RANGO_TIPO[b.tipo]));
  const futuros = todos
    .filter(c => c.inicio.getTime() > ahoraMs)
    .sort((a, b) => (a.inicio - b.inicio) || (RANGO_TIPO[a.tipo] - RANGO_TIPO[b.tipo]));

  const actual    = enCurso[0] || null;
  const siguiente = futuros[0] || null;
  const huecoMin  = actual && siguiente
    ? Math.round((siguiente.inicio.getTime() - actual.fin.getTime()) / 60000)
    : null;
  return { actual, siguiente, huecoMin };
}

// ── Textos ───────────────────────────────────────────────────────────────────

const p2 = n => String(n).padStart(2, "0");
const hhmm = d => `${p2(d.getHours())}:${p2(d.getMinutes())}`;

// «40 min», «2 h», «1 h 5 min».
function duracion(min) {
  const m = Math.max(0, Math.round(min));
  if (m < 60) return `${m} min`;
  const h = Math.floor(m / 60);
  const r = m % 60;
  return r ? `${h} h ${r} min` : `${h} h`;
}

// Días de calendario entre dos fechas locales. Por medianoches construidas con
// componentes y redondeando: el domingo de cambio de hora un «día» dura 23 o 25 h, y
// dividir milisegundos entre 24 h a secas daría 0,96 días.
function diasDeCalendario(desde, hasta) {
  const a = new Date(desde.getFullYear(), desde.getMonth(), desde.getDate());
  const b = new Date(hasta.getFullYear(), hasta.getMonth(), hasta.getDate());
  return Math.round((b.getTime() - a.getTime()) / 86400000);
}

// La cuenta atrás se mide en milisegundos reales y no restando horas de pared: así
// no la engaña el domingo de cambio de hora (dos horas reales son «en 2 h» aunque el
// reloj salte de 1:00 a 4:00). La fecha de pared solo se usa para decir QUÉ día.
export function cuentaAtras(desde, hasta) {
  const a = aFechaLocal(desde);
  const b = aFechaLocal(hasta);
  if (!a || !b) return "";
  const ms = b.getTime() - a.getTime();
  if (ms < 60000) return "ahora";
  const min = Math.round(ms / 60000);
  if (min < 60) return `en ${min} min`;
  const dias = diasDeCalendario(a, b);
  if (ms < 24 * 3600 * 1000 && dias === 0) return `en ${duracion(min)}`;
  if (dias === 1) return `mañana, ${hhmm(b)}`;
  if (dias < 7) return `${DIAS_SEMANA[b.getDay()]}, ${hhmm(b)}`;
  return `${b.getDate()} ${MESES_CORTOS_ES[b.getMonth()]}, ${hhmm(b)}`;
}

export function faltaPara(desde, hasta) {
  const a = aFechaLocal(desde);
  const b = aFechaLocal(hasta);
  if (!a || !b) return "";
  const min = Math.round((b.getTime() - a.getTime()) / 60000);
  if (min < 1) return "acaba ya";
  return `acaba en ${duracion(min)}`;
}

export function textoHueco(huecoMin) {
  if (huecoMin == null || Number.isNaN(Number(huecoMin))) return "";
  const m = Math.round(Number(huecoMin));
  if (m < 0) return "se solapa con lo actual";
  if (m < 5) return "justo después";
  // El verbo concuerda con la primera cifra: «te queda 1 h 10 min libre», pero
  // «te quedan 40 min libres» y «te quedan 2 h libres».
  const singular = Math.floor(m / 60) === 1;
  return singular ? `te queda ${duracion(m)} libre` : `te quedan ${duracion(m)} libres`;
}

// Lo que se dice cuando /maps/departure falla. Siempre con el sitio: «no se pudo
// calcular la ruta» a secas no deja saber si el problema es la dirección que se
// escribió en Outlook (lo normal: un NOT_FOUND) o Google. Si el backend dio un motivo
// distinto del genérico (cuota, clave), se añade entre paréntesis.
export function textoErrorRuta(lugar, error) {
  const base = `No se pudo calcular la ruta a «${String(lugar ?? "").trim()}»`;
  const motivo = typeof error === "string" ? error.trim() : "";
  if (!motivo || motivo.startsWith("No se pudo calcular la ruta")) return base;
  return `${base} (${motivo})`;
}

// ── Fase de la salida ────────────────────────────────────────────────────────

// Dónde estás respecto a la hora de salir. Se recalcula en cada render con el `ahora`
// del reloj del dashboard, que es lo único que cambia: la hora de salida se pide una
// vez y lo que avanza es la fase, sin volver a preguntar a Google.
export function faseSalida({ salida, empieza, ahora } = {}) {
  const s = aFechaLocal(salida);
  const t = aFechaLocal(ahora);
  if (!s || !t) return null;
  const e = aFechaLocal(empieza);
  const restante = s.getTime() - t.getTime();
  const porcentaje = Math.min(1, Math.max(0, restante / 3600000));
  if (e && t.getTime() >= e.getTime()) return { fase: "en_curso", minutos: 0, texto: "", porcentaje: 0 };
  const m = Math.round(restante / 60000);
  if (m > UMBRAL_PRONTO_MIN) return { fase: "holgado", minutos: m, texto: `sal en ${duracion(m)}`, porcentaje };
  if (m >= 1)                return { fase: "pronto",  minutos: m, texto: `sal en ${duracion(m)}`, porcentaje };
  if (m === 0)               return { fase: "ya",      minutos: 0, texto: "sal ya", porcentaje };
  return { fase: "tarde", minutos: m, texto: `vas ${duracion(-m)} tarde`, porcentaje };
}

// ── Memoria del modo (coche / andando) ───────────────────────────────────────

// Puro: devuelve el mapa nuevo y quien llama decide dónde guardarlo. Se poda a las
// últimas `maximo` claves porque cada evento deja la suya y, sin tope, localStorage
// acumularía una entrada por cada reunión de la historia.
export function recordarModo(mapa, key, modo, maximo = 50) {
  const previo = (mapa && typeof mapa.porEvento === "object" && mapa.porEvento) || {};
  const porEvento = { ...previo };
  // Borrar antes de escribir la mueve al final: el orden de inserción es la antigüedad.
  delete porEvento[key];
  porEvento[key] = modo;
  const claves = Object.keys(porEvento);
  const podado = {};
  for (const k of claves.slice(Math.max(0, claves.length - maximo))) podado[k] = porEvento[k];
  return { porEvento: podado, ultimo: modo };
}

export function modoPara(mapa, key) {
  return mapa?.porEvento?.[key] || mapa?.ultimo || "driving";
}

// ── Formulario de evento (crear / editar en Outlook) ─────────────────────────

// Lo que el modal enseña al abrir un evento existente. Uno de todo el día llega de Graph
// como medianoche UTC sin más (y el fin, la medianoche del día siguiente): su día es el
// literal del ISO, igual que en `normalizarEventos`. Pasarlo por la hora local lo dejaba
// en «02:00 → 02:00» y, al guardar con horas, Graph lo rechazaba entero (ver
// `cuerpoEvento`). Las horas de un evento de día completo son las que se pondrían si se
// desmarca la casilla, no las suyas, que no tiene.
export function formularioDesdeEvento(ev) {
  const p = n => String(n).padStart(2, "0");
  if (ev?.isAllDay) {
    const desde = String(ev.start || "").slice(0, 10);
    const hasta = String(ev.end || "").slice(0, 10);
    const dias  = Math.max(1, Math.round((Date.parse(`${hasta}T12:00:00Z`) - Date.parse(`${desde}T12:00:00Z`)) / 86400000) || 1);
    return { subject: ev.title || "", date: desde, allDay: true, dias,
             startTime: "09:00", endTime: "09:30", location: ev.location || "",
             calendarId: "", alud_url: ev.alud_url || "" };
  }
  const sd = aFechaLocal(ev?.start) || new Date();
  const ed = aFechaLocal(ev?.end) || sd;
  return { subject: ev?.title || "", date: fechaLocalISO(sd), allDay: false, dias: 1,
           startTime: `${p(sd.getHours())}:${p(sd.getMinutes())}`,
           endTime: `${p(ed.getHours())}:${p(ed.getMinutes())}`,
           location: ev?.location || "", calendarId: "", alud_url: ev?.alud_url || "" };
}

// El cuerpo de POST/PATCH /calendar/events. `is_all_day` va SIEMPRE, también al editar:
// si no se manda, Graph conserva el que tenía el evento, y a uno de todo el día no le
// acepta un inicio que no sea medianoche («The Event.Start property for an all-day event
// needs to be set to midnight»). Así cambiar la hora de una entrega de día completo lo
// convierte en un evento con hora, que es lo que se ha pedido.
export function cuerpoEvento(form) {
  const { subject, date, startTime, endTime, location, alud_url, allDay } = form;
  const cuerpo = { subject: subject.trim(), location: location.trim() || null };
  if (allDay) {
    cuerpo.is_all_day = true;
    cuerpo.start = `${date}T00:00:00`;
    cuerpo.end   = `${desplazarDia(date, Math.max(1, form.dias || 1))}T00:00:00`;
  } else {
    cuerpo.is_all_day = false;
    cuerpo.start = `${date}T${startTime}:00`;
    // «23:30 → 00:30» termina al día siguiente; con la misma fecha, Graph lo rechaza
    // por acabar antes de empezar.
    cuerpo.end = `${endTime < startTime ? desplazarDia(date, 1) : date}T${endTime}:00`;
  }
  if (alud_url && alud_url.trim()) cuerpo.description = `alud_url: ${alud_url.trim()}`;
  return cuerpo;
}
