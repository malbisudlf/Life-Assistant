// ── EL MOMENTO DEL DÍA ───────────────────────────────────────────
// La cabecera contesta en una línea a «¿qué me toca ahora?». Todo sale de lo que el
// dashboard ya tiene cargado: sin llamadas nuevas, sin modelo y sin backend.
//
// Nada de aquí lee el reloj: `ahora` llega SIEMPRE por parámetro. Por eso no se usan los
// helpers de fechas `is*` de helpers.js, que miran el reloj real por dentro — con ellos
// la frase no se podría probar en los bordes de cada franja ni al cruzar la medianoche,
// que es justo donde se equivoca.
//
// La regla madre: NUNCA se afirma sobre una fuente que no ha cargado. «No lo sé» y «no
// hay nada» se dicen distinto, y decir «hoy no tienes nada» mientras Outlook aún no ha
// contestado es mentir durante medio segundo (o para siempre, si la sesión caducó).

import {
  formatTime, sleepHours, findMetric, alarmaCuandoTexto, alarmaSonando, agruparParteNoche,
} from "./helpers.js";

const TITULO_BASE = "Life Assistant";
const MAX_TITULO  = 40;
const MAX_CHIPS   = 3;
// Por encima de este % de probabilidad la lluvia merece un chip. Por debajo es ruido:
// la previsión de Open-Meteo da un 20-30 % casi cualquier día nublado.
const UMBRAL_LLUVIA = 50;

function _iso(d) {
  const p = n => String(n).padStart(2, "0");
  return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())}`;
}

// El día siguiente a mediodía: sumar 24 h a una medianoche se come un día los domingos
// de cambio de hora.
function _isoManana(ahora) {
  return _iso(new Date(ahora.getFullYear(), ahora.getMonth(), ahora.getDate() + 1, 12));
}

// Recorte por caracteres reales (Array.from), no por unidades UTF-16: un título con un
// emoji en el corte acabaría en medio par sustituto y se pintaría como «�».
function _titulo(t) {
  const limpio = String(t || "").trim() || "(Sin título)";
  const chars  = Array.from(limpio);
  return chars.length > MAX_TITULO ? chars.slice(0, MAX_TITULO - 1).join("").trimEnd() + "…" : limpio;
}

/** "manana" | "tarde" | "noche". La noche incluye la madrugada: a las tres lo que
 *  importa sigue siendo cómo empieza el día, no qué queda de él. */
export function franjaDelDia(ahora) {
  const h = ahora.getHours();
  if (h >= 6 && h < 13)  return "manana";
  if (h >= 13 && h < 20) return "tarde";
  return "noche";
}

/** El saludo de siempre, con los mismos cortes que tenía la cabecera (13 y 20). */
export function saludoDeFranja(ahora) {
  const h = ahora.getHours();
  return h < 13 ? "Buenos días" : h < 20 ? "Buenas tardes" : "Buenas noches";
}

/** El «siguiente día que empieza», en ISO local. A partir de las 20:00 es mañana; en la
 *  madrugada ya es hoy (el día que empieza al despertar es el que tiene fecha de hoy). */
export function jornadaObjetivo(ahora) {
  return ahora.getHours() >= 20 ? _isoManana(ahora) : _iso(ahora);
}

/** Cuánto falta para `inicio`, dicho como se diría: "ya", "en 25 min", "a las 17:00".
 *  Por debajo de una hora los minutos se entienden mejor que una hora de reloj; por
 *  encima, al revés. Los minutos van por abajo: «en 1 min» con 90 s por delante es
 *  mejor que prometer 2. */
export function cuantoFalta(inicio, ahora) {
  const ms = new Date(inicio) - ahora;
  if (!(ms >= 60_000)) return "ya";
  if (ms < 3_600_000)  return `en ${Math.floor(ms / 60_000)} min`;
  return `a las ${formatTime(inicio)}`;
}

// Lo que cuenta como «algo a lo que vas». Fuera: los de todo el día (no tienen hora que
// cumplir), las entregas (son plazos, no citas: ya tienen su widget) y lo que no trae
// fechas parseables (no se puede colocar, y colocarlo a medianoche sería inventar).
function _candidatos(eventos, clases, marcador) {
  const todos = [
    ...(Array.isArray(eventos) ? eventos : []),
    ...(Array.isArray(clases) ? clases : []),
  ];
  return todos
    .filter(e => e && !e.isAllDay)
    .filter(e => !(marcador && typeof e.title === "string" && e.title.includes(marcador)))
    .map(e => ({ ev: e, ini: new Date(e.start), fin: new Date(e.end) }))
    .filter(c => c.ev.start && c.ev.end && !isNaN(c.ini) && !isNaN(c.fin))
    .sort((a, b) => a.ini - b.ini);
}

function _chipSueno(healthData, reloj, hoy) {
  const filas = findMetric(healthData, "sleep_analysis", "sleep").filter(d => !d?.extra?.excluded);
  const ultima = filas[filas.length - 1];
  // La noche se guarda con la fecha del DESPERTAR: la de hoy es la de anoche.
  if (ultima?.date === hoy) {
    const min = Math.round(sleepHours(ultima) * 60);
    if (min > 0) {
      return { id: "sueno", texto: `😴 ${Math.floor(min / 60)} h ${String(min % 60).padStart(2, "0")}`,
               widget: "health_sleep", tono: "normal" };
    }
  }
  // `sin_reloj` es un hecho (llegó el móvil y no el reloj). `sin_datos` es un «no se
  // sabe» —pudo ser la sincronización— y por eso no dice nada.
  if (reloj?.dias?.[hoy] === "sin_reloj") {
    return { id: "sueno", texto: "😴 El reloj no midió anoche", widget: "health_sleep", tono: "normal" };
  }
  return null;
}

function _chipLluvia(clima, jornada, hoy) {
  const daily = Array.isArray(clima?.daily) ? clima.daily : null;
  if (!daily) return null;
  const esManana = jornada !== hoy;
  // Por fecha si la trae (una previsión vieja no debe hablar del día equivocado); por
  // posición solo si no trae ninguna.
  const dia = daily.some(d => d?.date)
    ? daily.find(d => d?.date === jornada)
    : daily[esManana ? 1 : 0];
  const p = dia?.precip_prob;
  if (typeof p !== "number" || p < UMBRAL_LLUVIA) return null;
  return { id: "lluvia", texto: `🌧️ ${esManana ? "Mañana lluvia" : "Lluvia"} ${p} %`, widget: "weather", tono: "normal" };
}

function _chipAlarma(alarmas, ahora) {
  if (!Array.isArray(alarmas)) return null;
  // `cuando` es "YYYY-MM-DD HH:MM": como texto ya ordena igual que como fecha.
  const armadas = alarmas
    .filter(a => a?.estado === "armada" && a.cuando)
    .sort((a, b) => String(a.cuando).localeCompare(String(b.cuando)));
  if (!armadas.length) return null;
  const texto = alarmaCuandoTexto(armadas[0], ahora);
  return texto ? { id: "alarma", texto: `⏰ ${texto}`, widget: "alarmas", tono: "normal" } : null;
}

function _momento({
  ahora, eventos, clases, marcadorEntregas, cargandoAgenda, sinAgenda,
  alarmas, parteNoche, healthData, healthCargando, reloj, clima, salidas,
}) {
  const saludo  = saludoDeFranja(ahora);
  const franja  = franjaDelDia(ahora);
  const hora    = ahora.getHours();
  const hoy     = _iso(ahora);
  const manana  = _isoManana(ahora);
  const jornada = jornadaObjetivo(ahora);

  // 1. Una alarma sonando tapa todo: es lo único que quieres ver en ese momento, y
  //    cualquier otro chip es un sitio más donde pulsar sin querer.
  if (alarmaSonando(alarmas)) {
    return {
      saludo, frase: "La alarma está sonando: confirma que estás despierto.", tono: "alerta",
      chips: [{ id: "alarma-sonando", texto: "⏰ Estoy despierto", widget: "alarmas", tono: "alerta" }],
      titulo: `⏰ Alarma — ${TITULO_BASE}`,
    };
  }

  const chips = [];
  let frase  = "";
  let titulo = TITULO_BASE;

  if (cargandoAgenda) {
    // 2. Sin agenda todavía: solo el saludo. Los chips de otras fuentes sí salen.
  } else if (sinAgenda) {
    // 3. `authNeeded` también lo pone un error de red: esto es «no sé», nunca «nada».
    frase = "Outlook sin conectar: no sé qué tienes hoy.";
    chips.push({ id: "outlook", texto: "Conectar Outlook", widget: "timeline", tono: "normal" });
  } else {
    const cands = _candidatos(eventos, clases, marcadorEntregas);
    // Si se solapan varios, el que empezó el último: una reunión dentro de un bloque
    // largo de «trabajo» dice más que el bloque.
    const enCurso   = cands.filter(c => c.ini <= ahora && ahora < c.fin).pop() || null;
    const siguiente = cands.find(c => c.ini > ahora && _iso(c.ini) === hoy) || null;
    const primeroJ  = cands.find(c => c.ini > ahora && _iso(c.ini) === jornada) || null;
    const primeroM  = cands.find(c => _iso(c.ini) === manana) || null;
    const huboHoy   = cands.some(c => _iso(c.ini) === hoy);

    if (enCurso) {
      // 4.
      const t = _titulo(enCurso.ev.title);
      frase  = `Ahora: ${t} hasta las ${formatTime(enCurso.fin)}.`;
      titulo = `Ahora · ${t} — ${TITULO_BASE}`;
      if (siguiente) {
        chips.push({ id: "luego", texto: `Luego ${formatTime(siguiente.ini)} · ${_titulo(siguiente.ev.title)}`,
                     widget: "timeline", tono: "normal" });
      }
    } else if (siguiente && (franja !== "noche" || hora >= 20)) {
      // 5. De madrugada no: a las tres, «reunión a las 09:00» se dice como «hoy
      //    empiezas…», que es la frase de la noche.
      const t = _titulo(siguiente.ev.title);
      // Solo se LEE lo que ya se calculó a demanda: la hora de salida es Google Maps de
      // pago, y esta cabecera se recalcula cada minuto.
      const salida = salidas?.[siguiente.ev.id || siguiente.ev.start];
      const sal    = salida?.departure_time && !salida.error ? ` · sal a las ${salida.departure_time}` : "";
      frase = `${t} ${cuantoFalta(siguiente.ini, ahora)}${sal}.`;
    } else if (franja === "noche") {
      // 6.
      const cuando = hora >= 20 ? "Mañana" : "Hoy";
      frase = primeroJ
        ? `${cuando} empiezas a las ${formatTime(primeroJ.ini)} con ${_titulo(primeroJ.ev.title)}.`
        : `${cuando} no tienes nada en la agenda.`;
    } else {
      // 7.
      frase = huboHoy ? "No te queda nada más hoy." : "Hoy no tienes nada en la agenda.";
      if (franja === "tarde" && primeroM) {
        chips.push({ id: "manana", texto: `Mañana ${formatTime(primeroM.ini)} · ${_titulo(primeroM.ev.title)}`,
                     widget: "upcoming", tono: "normal" });
      }
    }

    if (!enCurso && siguiente) titulo = `${formatTime(siguiente.ini)} · ${_titulo(siguiente.ev.title)} — ${TITULO_BASE}`;
  }

  // Chips secundarios. Cada uno solo si su fuente ha cargado: `null` es «no se sabe».
  if (parteNoche && parteNoche.fecha === hoy) {
    const n = agruparParteNoche(parteNoche).pendientes;
    if (n > 0) chips.push({ id: "parte", texto: `🌙 Anoche: ${n} pendiente${n === 1 ? "" : "s"}`, widget: "noche", tono: "normal" });
  }
  // Sin puntuación de sueño a propósito: la del widget lleva los modificadores de
  // recuperación, y una copia aquí acabaría diciendo un número distinto del de abajo.
  if (franja === "manana" && !healthCargando) {
    const c = _chipSueno(healthData, reloj, hoy);
    if (c) chips.push(c);
  }
  const lluvia = _chipLluvia(clima, jornada, hoy);
  if (lluvia) chips.push(lluvia);
  // Solo de noche, y solo si HAY alarma: «no tienes alarma» no es un aviso, es el estado
  // de casi todos los días.
  if (franja === "noche") {
    const a = _chipAlarma(alarmas, ahora);
    if (a) chips.push(a);
  }

  return { saludo, frase, tono: "normal", chips: chips.slice(0, MAX_CHIPS), titulo };
}

/** La cabecera entera: `{ saludo, frase, tono, chips, titulo }`. Una cabecera no puede
 *  tumbar el dashboard (no hay ErrorBoundary): ante cualquier dato raro, solo el saludo. */
export function momentoDelDia(entrada) {
  try {
    return _momento(entrada || {});
  } catch {
    let saludo = "Hola";
    try { saludo = saludoDeFranja(entrada.ahora); } catch { /* sin hora válida, saludo neutro */ }
    return { saludo, frase: "", tono: "normal", chips: [], titulo: TITULO_BASE };
  }
}

/** Adónde lleva un chip. `{ visible: false }` si el widget no se está pintando en la
 *  vista activa (un chip que no hace nada al pulsarlo es peor que ninguno). En modo
 *  simple los widgets de salud viven en pestañas: `pestanaSalud` dice cuál abrir antes
 *  de saltar. `pestanasSalud` se pasa para no importar nada del componente. */
export function destinoDeWidget(id, { simpleMode, widgetConfig, simpleWidgetConfig, pestanasSalud } = {}) {
  const config = simpleMode ? simpleWidgetConfig : widgetConfig;
  const w = Array.isArray(config) ? config.find(c => c?.id === id) : null;
  if (!w || w.visible === false) return { visible: false };
  const pestanaSalud = simpleMode && pestanasSalud && Object.prototype.hasOwnProperty.call(pestanasSalud, id) ? id : null;
  return { visible: true, pestanaSalud };
}
