// ── LÍNEA DE TIEMPO DEL DÍA ──────────────────────────────────────────────────
// Lógica pura del widget «El día»: pone sobre un MISMO eje de 24 h todo lo que le
// pasó a una jornada —eventos, sueño, entrenos, presencia, avisos y casa— con un
// carril por familia. Sin React y sin fetch a propósito: el componente vive en
// Dashboard.jsx y se limita a pintar lo que sale de aquí.
//
// Existe porque cada dato ya vive en su widget y las coincidencias las tiene que ver
// el usuario a ojo. El motor de conclusiones de `helpers.js` cruza SERIES (dos
// métricas a lo largo de semanas); esto cruza MOMENTOS, que es lo que un cruce
// estadístico no puede ver. Por eso se optimiza para que se vean las coincidencias,
// no para que quepa todo.
//
// Tres invariantes que no se pueden relajar:
//
// 1. TODO se interpreta en hora LOCAL. Una fecha "AAAA-MM-DD" pasa a medianoche local
//    construyéndola por componentes, nunca con `new Date(iso)` a secas ni con
//    `toISOString()`, que en Europe/Madrid desplaza el día entero. Es la fuente de
//    bugs número uno de este repositorio.
// 2. El eje mide el día REAL, no 24 h fijas: los dos días del año en que cambia la
//    hora duran 23 o 25 h y las posiciones se calculan contra `largoDelDiaMin`. Con
//    1440 clavado, media jornada del domingo de octubre se pintaría corrida una hora.
// 3. "No hay dato" y "no pasó nada" NO se pintan igual. Cada carril arrastra el
//    ESTADO de su fuente: si no se pudo consultar, dice que no lo sabe en vez de
//    quedarse en blanco como si la jornada hubiese estado vacía.

export const MINUTOS_DIA = 1440;

// Un evento de 5 min sobre un eje de 24 h ocupa un 0,35 %: invisible. El mínimo es
// para que se vea que ocurrió; el ancho real se conserva aparte para quien lo mire.
export const ANCHO_MINIMO_PCT = 0.7;

// Estado de una FUENTE (lo que el componente sabe de su llamada al backend).
export const FUENTE_OK        = "ok";
export const FUENTE_CARGANDO  = "cargando";
export const FUENTE_ERROR     = "error";
export const FUENTE_AUSENTE   = "ausente";        // el backend no publica ese dato
export const FUENTE_PARCIAL   = "parcial";        // hay fuente, pero no cubre este día

// Estado de un CARRIL ya construido. Los dos primeros solo salen de una fuente `ok`.
export const CARRIL_CON_DATOS = "con_datos";
export const CARRIL_VACIO     = "vacio";          // se pudo mirar y no pasó nada

export const CARRILES = [
  { id: "eventos",   etiqueta: "Eventos",   icono: "📅", color: "#8bb4d4" },
  { id: "sueno",     etiqueta: "Sueño",     icono: "😴", color: "#8f86d4" },
  { id: "entrenos",  etiqueta: "Entrenos",  icono: "💪", color: "#6aaa82" },
  { id: "presencia", etiqueta: "Presencia", icono: "🏠", color: "#c8a96e" },
  { id: "avisos",    etiqueta: "Avisos",    icono: "🔔", color: "#d4645a" },
  { id: "casa",      etiqueta: "Casa",      icono: "💡", color: "#7fbfc4" },
];

// ── Fechas y husos ───────────────────────────────────────────────────────────

// "AAAA-MM-DD" de una fecha, con sus componentes LOCALES. `toISOString()` daría el día
// de UTC, que en Madrid es el anterior desde las 22:00 (23:00 en invierno).
export function fechaLocalISO(fecha) {
  const d = fecha instanceof Date ? fecha : new Date(fecha);
  if (Number.isNaN(d.getTime())) return "";
  const p = n => String(n).padStart(2, "0");
  return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())}`;
}

// Medianoche local del día. Se construye por componentes y no parseando la cadena:
// es la única forma de que el resultado no dependa de cómo interprete el navegador
// una fecha suelta.
export function inicioDelDiaLocal(diaISO) {
  const m = /^(\d{4})-(\d{2})-(\d{2})$/.exec(String(diaISO || ""));
  if (!m) return null;
  const d = new Date(+m[1], +m[2] - 1, +m[3], 0, 0, 0, 0);
  return Number.isNaN(d.getTime()) ? null : d;
}

export function desplazarDia(diaISO, dias) {
  const base = inicioDelDiaLocal(diaISO);
  if (!base) return "";
  base.setDate(base.getDate() + dias);
  return fechaLocalISO(base);
}

// Minutos que dura el día de verdad: 1380 el domingo que se adelanta la hora y 1500 el
// que se atrasa. El eje entero se escala con esto.
export function largoDelDiaMin(diaISO) {
  const a = inicioDelDiaLocal(diaISO);
  const b = inicioDelDiaLocal(desplazarDia(diaISO, 1));
  if (!a || !b) return MINUTOS_DIA;
  const min = Math.round((b.getTime() - a.getTime()) / 60000);
  return min > 0 ? min : MINUTOS_DIA;
}

// ¿La cadena trae hora, o es solo una fecha? Un entreno con fecha pero sin hora no se
// puede colocar en el eje, y fingir que fue a medianoche sería inventarse el dato.
export function tieneHora(valor) {
  if (valor instanceof Date) return true;
  return /\d{1,2}:\d{2}/.test(String(valor || ""));
}

// Convierte a `Date` local lo que llega de cada fuente.
//
// Los eventos de Graph vienen como ISO con "T" y los parsea el navegador, igual que
// hace `formatTime` en helpers.js. El exportador de salud, en cambio, escribe cosas
// como "2026-09-01 07:12:33 +0200": esa hora es la del reloj de pared, así que se
// construye por componentes en vez de dejar que el navegador negocie el desfase —
// mismo criterio que `_hora_entreno` en el backend, que se queda con el HH:MM literal.
export function aFechaLocal(valor) {
  if (valor instanceof Date) return Number.isNaN(valor.getTime()) ? null : valor;
  const s = String(valor ?? "").trim();
  if (!s) return null;
  if (s.includes("T")) {
    const d = new Date(s);
    return Number.isNaN(d.getTime()) ? null : d;
  }
  const f = /^(\d{4})-(\d{2})-(\d{2})/.exec(s);
  if (!f) return null;
  const h = /(\d{1,2}):(\d{2})(?::(\d{2}))?/.exec(s);
  const d = new Date(+f[1], +f[2] - 1, +f[3],
                     h ? +h[1] : 0, h ? +h[2] : 0, h && h[3] ? +h[3] : 0, 0);
  return Number.isNaN(d.getTime()) ? null : d;
}

export function formatoHora(fecha) {
  const d = aFechaLocal(fecha);
  if (!d) return "";
  const p = n => String(n).padStart(2, "0");
  return `${p(d.getHours())}:${p(d.getMinutes())}`;
}

// ── Geometría del eje ────────────────────────────────────────────────────────

export function porcentajeDelDia(min, diaISO) {
  const largo = largoDelDiaMin(diaISO);
  return (min / largo) * 100;
}

// Recorta un tramo a los límites del día. Devuelve `null` si no lo toca.
// `cortadoAntes`/`cortadoDespues` marcan que el tramo sigue fuera de la pantalla: es
// lo que hace legible el sueño, que casi siempre empieza el día anterior.
export function recortarAlDia(inicio, fin, diaISO) {
  const base = inicioDelDiaLocal(diaISO);
  const i = aFechaLocal(inicio);
  const f = aFechaLocal(fin);
  if (!base || !i || !f) return null;

  const largo = largoDelDiaMin(diaISO);
  const t0 = base.getTime();
  let desde = (i.getTime() - t0) / 60000;
  let hasta = (f.getTime() - t0) / 60000;
  if (hasta < desde) return null;   // fin antes que inicio: dato malo, no se dibuja

  if (desde === hasta) {
    // Instante sin duración (un aviso, una acción de la casa): entra si cae dentro.
    if (desde < 0 || desde >= largo) return null;
  } else if (hasta <= 0 || desde >= largo) {
    return null;
  }

  const cortadoAntes   = desde < 0;
  const cortadoDespues = hasta > largo;
  desde = Math.max(0, desde);
  hasta = Math.min(largo, hasta);
  return { desdeMin: desde, hastaMin: hasta, cortadoAntes, cortadoDespues, largoMin: largo };
}

// El tramo ya en porcentajes, listo para el `style` del componente.
export function tramoDelDia(inicio, fin, diaISO) {
  const r = recortarAlDia(inicio, fin, diaISO);
  if (!r) return null;
  const izquierdaPct = porcentajeDelDia(r.desdeMin, diaISO);
  const anchoRealPct = porcentajeDelDia(r.hastaMin - r.desdeMin, diaISO);
  return {
    ...r,
    izquierdaPct,
    anchoRealPct,
    // Nunca se sale por la derecha aunque el mínimo lo empuje.
    anchoPct: Math.min(Math.max(anchoRealPct, ANCHO_MINIMO_PCT), 100 - izquierdaPct),
  };
}

// Marcas horarias del eje. Se calculan con horas locales reales, así que el día en que
// cambia la hora sale con las marcas donde de verdad están y no repartidas a partes
// iguales.
export function horasDelEje(diaISO, paso = 3) {
  const base = inicioDelDiaLocal(diaISO);
  if (!base) return [];
  const largo = largoDelDiaMin(diaISO);
  const marcas = [];
  for (let h = 0; h < 24; h += paso) {
    const d = new Date(base.getFullYear(), base.getMonth(), base.getDate(), h, 0, 0, 0);
    const min = (d.getTime() - base.getTime()) / 60000;
    if (min < 0 || min >= largo) continue;
    marcas.push({
      hora: h,
      etiqueta: `${String(h).padStart(2, "0")}:00`,
      izquierdaPct: porcentajeDelDia(min, diaISO),
    });
  }
  return marcas;
}

// Dónde cae "ahora" dentro del día, o `null` si `ahora` no es de ese día. El componente
// pinta ahí la línea del presente: sin ella, un día a medias parece un día vacío.
export function posicionAhora(diaISO, ahora = new Date()) {
  const base = inicioDelDiaLocal(diaISO);
  const d = aFechaLocal(ahora);
  if (!base || !d) return null;
  const largo = largoDelDiaMin(diaISO);
  const min = (d.getTime() - base.getTime()) / 60000;
  if (min < 0 || min > largo) return null;
  return { min, izquierdaPct: porcentajeDelDia(min, diaISO) };
}

// ── Solapes dentro de un carril ──────────────────────────────────────────────

// Reparte los items de un carril en subfilas para que dos cosas simultáneas no se
// tapen. Voraz sobre los inicios: cada item va a la primera subfila que ya haya
// terminado. Es la forma más barata de que el número de subfilas sea el máximo de
// cosas solapadas a la vez, que es justo lo que hay que enseñar.
export function repartirEnFilas(items) {
  const conTramo = (items || []).filter(it => it && !it.sinHora && Number.isFinite(it.desdeMin));
  const ordenados = [...conTramo].sort(
    (a, b) => (a.desdeMin - b.desdeMin) || (a.hastaMin - b.hastaMin),
  );
  const finales = [];
  const colocados = ordenados.map(it => {
    let fila = finales.findIndex(fin => fin <= it.desdeMin);
    if (fila === -1) { fila = finales.length; finales.push(it.hastaMin); }
    else finales[fila] = it.hastaMin;
    return { ...it, fila };
  });
  return { items: colocados, filas: Math.max(finales.length, 1) };
}

// ── Normalizadores: de lo que devuelve cada endpoint a items del eje ─────────

function textoTramo(item) {
  if (item.sinHora) return "sin hora";
  const ini = item.cortadoAntes   ? `←${formatoHora(item.inicio)}` : formatoHora(item.inicio);
  const fin = item.cortadoDespues ? `${formatoHora(item.fin)}→`    : formatoHora(item.fin);
  return `${ini} – ${fin}`;
}

function conTramo(base, inicio, fin, diaISO) {
  const t = tramoDelDia(inicio, fin, diaISO);
  if (!t) return null;
  const item = { ...base, inicio: aFechaLocal(inicio), fin: aFechaLocal(fin), sinHora: false, ...t };
  return { ...item, horaTexto: textoTramo(item) };
}

function sinTramo(base) {
  return { ...base, inicio: null, fin: null, sinHora: true, horaTexto: "sin hora" };
}

// `/calendar/events` y `/calendar/classes`: {id, title, start, end, isAllDay, location}.
export function normalizarEventos(eventos, diaISO) {
  const salida = [];
  (eventos || []).forEach((ev, i) => {
    if (!ev) return;
    const base = {
      id: `evento-${ev.id || i}`,
      carril: "eventos",
      etiqueta: ev.title || "Evento",
      detalle: ev.location || "",
    };
    if (ev.isAllDay) {
      // Un evento de todo el día no marca ningún momento: pintarlo de 00:00 a 24:00
      // taparía el carril entero y haría ilegible lo que sí tiene hora.
      const desde = String(ev.start || "").slice(0, 10);
      const hasta = String(ev.end || "").slice(0, 10);
      const dentro = hasta ? (diaISO >= desde && diaISO < hasta) : diaISO === desde;
      if (dentro) salida.push(sinTramo({ ...base, detalle: base.detalle || "Todo el día" }));
      return;
    }
    const item = conTramo(base, ev.start, ev.end || ev.start, diaISO);
    if (item) salida.push(item);
  });
  return salida;
}

// Filas de `sleep_analysis` de `/health/metrics`: {date, value, extra:{sleep_start,…}}.
//
// La fila se guarda con la fecha en que uno SE DESPIERTA, y `extra.sleep_start` es la
// hora de pared a la que se acostó. Así que una hora de acostarse por la tarde/noche
// (>= 12:00) pertenece al día ANTERIOR al de la fila: es la decisión que hace que el
// sueño cruce la medianoche de verdad en vez de aplastarse dentro de un solo día.
//
// De ahí que se miren dos filas para cada día: la del propio día (la noche que terminó
// esa mañana, que entra cortada por la izquierda) y la del día siguiente (la noche que
// empezó esa tarde, cortada por la derecha).
export function normalizarSueno(filas, diaISO) {
  const salida = [];
  const siguiente = desplazarDia(diaISO, 1);
  for (const fila of filas || []) {
    if (!fila) continue;
    const fecha = String(fila.date || "").slice(0, 10);
    if (fecha !== diaISO && fecha !== siguiente) continue;

    const horas = horasDeSueno(fila);
    const anulada = fila.extra?.excluded === true;
    const base = {
      id: `sueno-${fecha}`,
      carril: "sueno",
      etiqueta: anulada ? "Sueño (noche anulada)" : "Sueño",
      detalle: horas > 0 ? `${textoHoras(horas)} dormidas` : "sin duración",
      tono: anulada ? "atenuado" : "normal",
      anulada,
    };

    const acostado = String(fila.extra?.sleep_start || "");
    const m = /^(\d{1,2}):(\d{2})$/.exec(acostado);
    if (!m || horas <= 0) {
      // Se sabe que durmió, no cuándo. Solo cuenta en el día de la propia fila: la
      // noche del día siguiente no se puede colocar sin hora de inicio.
      if (fecha === diaISO) salida.push(sinTramo(base));
      continue;
    }
    const hora = +m[1];
    const minuto = +m[2];
    // Acostarse por la tarde/noche cuenta como el día anterior al del despertar.
    const diaInicio = hora >= 12 ? desplazarDia(fecha, -1) : fecha;
    const arranque = inicioDelDiaLocal(diaInicio);
    if (!arranque) continue;
    arranque.setHours(hora, minuto, 0, 0);
    const fin = new Date(arranque.getTime() + horas * 3600 * 1000);

    const item = conTramo({ ...base, id: `sueno-${fecha}` }, arranque, fin, diaISO);
    if (item) salida.push(item);
  }
  return salida;
}

// Duración efectiva de una fila de sueño. Réplica deliberadamente mínima de
// `sleepHours` de helpers.js: este módulo no importa aquel para no arrastrar el motor
// de conclusiones entero dentro del widget.
function horasDeSueno(fila) {
  if (!fila) return 0;
  if (fila.value > 0) return Number(fila.value);
  const e = fila.extra || {};
  if (e.asleep > 0) return Number(e.asleep);
  return (Number(e.deep) || 0) + (Number(e.rem) || 0)
       + (Number(e.light) || 0) + (Number(e.core) || 0);
}

function textoHoras(h) {
  const hrs = Math.floor(h);
  const min = Math.round((h - hrs) * 60);
  return min === 0 ? `${hrs} h` : `${hrs} h ${min} min`;
}

// Entrenos: los del reloj (filas de la métrica `workouts`, con hora real) y las
// sesiones de entrenamiento personal de `/training/summary`, que solo tienen FECHA.
// Las segundas van siempre sin hora: la tabla no guarda ninguna y colocarlas en un
// punto del eje sería inventarse el momento, que es justo lo que este widget existe
// para no hacer.
export function normalizarEntrenos({ workouts = [], sesiones = [] } = {}, diaISO) {
  const salida = [];

  for (const fila of workouts || []) {
    const lista = fila?.extra?.workouts;
    if (!Array.isArray(lista)) continue;
    lista.forEach((w, i) => {
      if (!w) return;
      const fecha = String(w.start || fila.date || "").slice(0, 10);
      if (fecha !== diaISO) return;
      const nombre = w.name || w.workoutActivityType || w.type || "Entrenamiento";
      // Mismo criterio de unidades que el widget «Entrenamientos AW»: el exportador
      // manda segundos en v2 y minutos en versiones viejas.
      const bruto = Number(w.duration);
      const minutos = Number.isFinite(bruto) ? (bruto > 300 ? bruto / 60 : bruto) : null;
      const base = {
        id: `entreno-${fecha}-${i}`,
        carril: "entrenos",
        etiqueta: nombre,
        detalle: minutos ? `${Math.round(minutos)} min` : "",
      };
      if (!tieneHora(w.start) || !minutos) { salida.push(sinTramo(base)); return; }
      const inicio = aFechaLocal(w.start);
      if (!inicio) { salida.push(sinTramo(base)); return; }
      const item = conTramo(base, inicio, new Date(inicio.getTime() + minutos * 60000), diaISO);
      salida.push(item || sinTramo(base));
    });
  }

  (sesiones || []).forEach((s, i) => {
    if (!s || String(s.date || "").slice(0, 10) !== diaISO) return;
    const horas = Number(s.duration_hours);
    salida.push(sinTramo({
      id: `sesion-${s.id || i}`,
      carril: "entrenos",
      etiqueta: "Sesión de entrenamiento personal",
      detalle: Number.isFinite(horas) ? `${textoHoras(horas)} · la tabla no guarda la hora` : "la tabla no guarda la hora",
    }));
  });

  return salida;
}

// `/avisos/enviados`: {dia, avisos: [{id, texto, regla, prioridad, enviado_at, util}]}.
// A diferencia de `/avisos/estado` (que solo da el recuento del día en curso),
// `enviado_at` es una hora real por aviso, para cualquier día — así que cada aviso entra
// como un instante en el eje (inicio == fin, ver `recortarAlDia`), no como un resumen.
export function normalizarAvisos(avisos, diaISO) {
  const salida = [];
  (avisos || []).forEach((a, i) => {
    if (!a) return;
    const base = {
      id: `aviso-${a.id || i}`,
      carril: "avisos",
      etiqueta: a.texto || "Aviso",
      detalle: a.regla || "",
    };
    const momento = aFechaLocal(a.enviado_at);
    if (!momento) { salida.push(sinTramo(base)); return; }
    // `null` aquí es que el momento cae fuera de este día (el backend ya filtra por
    // `dia`, pero un cambio de huso podría desplazar la medianoche): se queda fuera del
    // todo, no se cuela como "sin hora" — eso sería un dato inventado.
    const item = conTramo(base, momento, momento, diaISO);
    if (item) salida.push(item);
  });
  return salida;
}

// Presencia: la serie diaria `time_at_home` (horas en casa en `value`, horas fuera en
// `extra.fuera`). NO hay tramos horarios y no los va a haber: guardar un histórico de
// presencia está descartado a propósito en docs/IDEAS.md por ser el dato más sensible
// del proyecto. Así que este carril da un RESUMEN del día, y lo dice.
export function normalizarPresencia(filas, diaISO) {
  for (const fila of filas || []) {
    if (String(fila?.date || "").slice(0, 10) !== diaISO) continue;
    const casa  = Number(fila.value) || 0;
    const fuera = Number(fila.extra?.fuera) || 0;
    if (casa <= 0 && fuera <= 0) return null;
    return {
      casa,
      fuera,
      cubiertas: casa + fuera,
      texto: `${textoHoras(casa)} en casa · ${textoHoras(fuera)} fuera`,
    };
  }
  return null;
}

// ── Construcción del día completo ────────────────────────────────────────────

function carrilBase(id) {
  return CARRILES.find(c => c.id === id) || { id, etiqueta: id, icono: "", color: "#888" };
}

function estadoDe(fuente, items, resumen) {
  const estado = fuente?.estado || FUENTE_AUSENTE;
  if (estado !== FUENTE_OK) return estado;
  return (items.length > 0 || resumen) ? CARRIL_CON_DATOS : CARRIL_VACIO;
}

function construirCarril(id, fuente, items, extra = {}) {
  const conFilas = repartirEnFilas(items);
  const sinHora  = items.filter(it => it.sinHora);
  const estado   = estadoDe(fuente, items, extra.resumen);
  return {
    ...carrilBase(id),
    estado,
    nota: fuente?.nota || null,
    items: conFilas.items,
    filas: conFilas.filas,
    sinHora,
    resumen: extra.resumen || null,
    // Un carril "sabe" cuando se pudo mirar: es lo único que separa "no pasó nada" de
    // "no lo sé", y el componente pinta cosas distintas según esto.
    conocido: estado === CARRIL_CON_DATOS || estado === CARRIL_VACIO,
  };
}

// Frase que va debajo del carril cuando no hay nada que dibujar. Nunca se deja en
// blanco: el silencio es justo lo que no se puede distinguir a ojo.
export function textoEstadoCarril(carril) {
  switch (carril?.estado) {
    case CARRIL_CON_DATOS: return "";
    case CARRIL_VACIO:     return "Nada este día";
    case FUENTE_CARGANDO:  return "Cargando…";
    case FUENTE_ERROR:     return "No se pudo consultar: no lo sé";
    case FUENTE_PARCIAL:   return "Sin datos para este día: no lo sé";
    default:               return "Sin fuente de histórico: no lo sé";
  }
}

// Arma el día entero. `fuentes` lleva, por familia, `{estado, datos, nota}` — el
// estado lo pone quien hizo la llamada, porque solo él sabe si falló, si sigue
// cargando o si el endpoint sencillamente no ofrece histórico.
export function construirLineaTiempo({ dia, hoy = null, ahora = null, fuentes = {} } = {}) {
  const diaISO = /^\d{4}-\d{2}-\d{2}$/.test(String(dia || "")) ? dia : fechaLocalISO(new Date());
  const hoyISO = hoy || fechaLocalISO(new Date());

  const f = fuentes || {};
  const eventos   = f.eventos?.estado   === FUENTE_OK ? normalizarEventos(f.eventos.datos, diaISO) : [];
  const sueno     = f.sueno?.estado     === FUENTE_OK ? normalizarSueno(f.sueno.datos, diaISO) : [];
  const entrenos  = f.entrenos?.estado  === FUENTE_OK ? normalizarEntrenos(f.entrenos.datos, diaISO) : [];
  const presencia = f.presencia?.estado === FUENTE_OK ? normalizarPresencia(f.presencia.datos?.filas, diaISO) : null;

  // Avisos: `/avisos/enviados` da la hora real de cada uno, para cualquier día —a
  // diferencia de `/avisos/estado`, que solo sabe el recuento del día en curso—, así que
  // el carril se construye igual que eventos/sueño/entrenos, con items de verdad.
  const avisos = f.avisos?.estado === FUENTE_OK ? normalizarAvisos(f.avisos.datos, diaISO) : [];

  const carriles = [
    construirCarril("eventos",   f.eventos,   eventos),
    construirCarril("sueno",     f.sueno,     sueno),
    construirCarril("entrenos",  f.entrenos,  entrenos),
    construirCarril("presencia", f.presencia, [], { resumen: presencia }),
    construirCarril("avisos",    f.avisos,    avisos),
    construirCarril("casa",      f.casa,      []),
  ];

  return {
    dia: diaISO,
    hoy: hoyISO,
    esHoy: diaISO === hoyISO,
    largoMin: largoDelDiaMin(diaISO),
    horas: horasDelEje(diaISO),
    ahora: diaISO === hoyISO ? posicionAhora(diaISO, ahora || new Date()) : null,
    carriles,
    // Cuántos carriles se pudieron mirar de verdad. La cabecera lo dice: un día con
    // dos de seis carriles conocidos no es un día tranquilo, es un día sin datos.
    conocidos: carriles.filter(c => c.conocido).length,
    total: carriles.length,
  };
}

// Título largo del día ("miércoles, 3 de septiembre"), en minúscula como el resto de
// la UI. Vive aquí y no en helpers.js porque solo lo usa este widget.
const DIAS_LARGO = ["domingo", "lunes", "martes", "miércoles", "jueves", "viernes", "sábado"];
const MESES_LARGO = ["enero", "febrero", "marzo", "abril", "mayo", "junio", "julio",
                     "agosto", "septiembre", "octubre", "noviembre", "diciembre"];

export function etiquetaDia(diaISO, hoyISO = null) {
  const d = inicioDelDiaLocal(diaISO);
  if (!d) return "";
  const hoy = hoyISO || fechaLocalISO(new Date());
  if (diaISO === hoy) return "hoy";
  if (diaISO === desplazarDia(hoy, -1)) return "ayer";
  return `${DIAS_LARGO[d.getDay()]}, ${d.getDate()} de ${MESES_LARGO[d.getMonth()]}`;
}
