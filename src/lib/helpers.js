// ── HELPERS PUROS DEL DASHBOARD ──────────────────────────────────
// Extraídos de Dashboard.jsx para poder testearlos de forma aislada.

// ── Fechas ───────────────────────────────────────────────────────
export function isToday(dateStr) {
  const d = new Date(dateStr);
  const t = new Date();
  return d.getFullYear() === t.getFullYear() && d.getMonth() === t.getMonth() && d.getDate() === t.getDate();
}
export function isFuture(dateStr) { return new Date(dateStr) > new Date(); }
export function isPast(dateStr) { return new Date(dateStr) < new Date(); }
export function isActive(startStr, endStr) {
  const now = new Date();
  return new Date(startStr) <= now && new Date(endStr) >= now;
}
export function daysUntil(dateStr) {
  return Math.ceil((new Date(dateStr) - new Date()) / (1000 * 60 * 60 * 24));
}
export function formatTime(dateStr) {
  const d = new Date(dateStr);
  return `${String(d.getHours()).padStart(2,"0")}:${String(d.getMinutes()).padStart(2,"0")}`;
}
export function formatUpcomingTime(dateStr) {
  const d = new Date(dateStr);
  const tomorrow = new Date(); tomorrow.setDate(tomorrow.getDate() + 1);
  const DAYS = ["Dom","Lun","Mar","Mié","Jue","Vie","Sáb"];
  if (isToday(dateStr)) return formatTime(dateStr);
  if (d.toDateString() === tomorrow.toDateString()) return `Mañana ${formatTime(dateStr)}`;
  return `${DAYS[d.getDay()]} ${formatTime(dateStr)}`;
}
export function urgencyColor(days) {
  if (days <= 3) return "#d4645a";
  if (days <= 7) return "#c8a45a";
  return "#6aaa82";
}
export function formatShortDate(dateStr) {
  if (!dateStr) return "";
  const [, m, d] = dateStr.split("-").map(Number);
  return `${d} ${MONTHS_ES[m - 1].slice(0, 3)}`;
}

export const DAYS_ES       = ["Domingo","Lunes","Martes","Miércoles","Jueves","Viernes","Sábado"];
export const DAYS_SHORT_ES = ["Dom","Lun","Mar","Mié","Jue","Vie","Sáb"];
export const MONTHS_ES = ["enero","febrero","marzo","abril","mayo","junio","julio","agosto","septiembre","octubre","noviembre","diciembre"];

// Día de la semana corto ("Lun", "Mar"…) de una fecha ISO "YYYY-MM-DD".
// Se parsea como medianoche LOCAL para que no baile de día según la zona.
export function weekdayShort(isoDate) {
  const d = new Date(`${isoDate}T00:00:00`);
  return Number.isNaN(d.getTime()) ? "" : DAYS_SHORT_ES[d.getDay()];
}

export function isoToDdMmYyyy(iso) {
  if (!iso) return "";
  const [y, m, d] = iso.split("-");
  return `${d}/${m}/${y}`;
}

// ── Salud ────────────────────────────────────────────────────────
export function hoursToHM(h) {
  if (h == null || isNaN(h)) return "—";
  const hrs  = Math.floor(h);
  const mins = Math.round((h - hrs) * 60);
  if (mins === 0) return `${hrs}h`;
  return `${hrs}h ${mins}m`;
}

export function sleepScore(total, deep, rem, core, awake, sleepStart, recoveryMod = 0) {
  if (!total || total < 0.5) return null;
  let s = 0;
  // Duración (40 pts) — objetivo 8h para adulto joven
  if      (total >= 8 && total <= 9.5) s += 40;
  else if (total >= 7.5)               s += 34;
  else if (total >= 7)                 s += 26;
  else if (total >= 6)                 s += 16;
  else                                 s += 6;
  // Sueño profundo (25 pts)
  const dp = deep ? (deep / total) * 100 : null;
  if      (dp == null)            s += 12;
  else if (dp >= 13 && dp <= 23)  s += 25;
  else if (dp >= 10)              s += 19;
  else if (dp >= 7)               s += 13;
  else                            s += 6;
  // REM (25 pts)
  const rp = rem ? (rem / total) * 100 : null;
  if      (rp == null)            s += 12;
  else if (rp >= 20 && rp <= 25)  s += 25;
  else if (rp >= 15)              s += 19;
  else if (rp >= 10)              s += 13;
  else                            s += 6;
  // Tiempo despierto (10 pts)
  const ap = awake ? (awake / total) * 100 : 0;
  if      (ap < 5)   s += 10;
  else if (ap < 10)  s += 7;
  else if (ap < 15)  s += 4;
  // Penalización por hora de acostarse
  if (sleepStart) {
    const h = parseInt(sleepStart.slice(0, 2), 10);
    // Horas nocturnas tardías (0-5) se tratan como "pasada medianoche"
    if      (h >= 2 && h < 6)  s -= 15;
    else if (h === 1)          s -= 10;
    else if (h === 0)          s -= 5;
    // h >= 6 (tarde/noche antes de medianoche) → sin penalización
  }
  const cap = total >= 8 ? 100 : total >= 7.5 ? 82 : total >= 7 ? 68 : 52;
  return Math.min(cap, Math.max(0, Math.round(s + recoveryMod)));
}

// Penalización por señales fisiológicas de recuperación deficiente (hasta -20 pts).
// Compara HRV, FC reposo y frecuencia respiratoria contra baseline de 30 días.
export function calcRecoveryMod(hrv, rhr, resp, hrvBase, rhrBase, respBase) {
  let mod = 0;
  // HRV bajo → recuperación deficiente (hasta -8 pts)
  if (hrv != null && hrvBase > 0) {
    const pct = (hrv - hrvBase) / hrvBase * 100;
    if      (pct < -25) mod -= 8;
    else if (pct < -15) mod -= 6;
    else if (pct < -5)  mod -= 3;
  }
  // FC reposo elevada → carga acumulada (hasta -7 pts)
  if (rhr != null && rhrBase > 0) {
    const pct = (rhr - rhrBase) / rhrBase * 100;
    if      (pct > 15) mod -= 7;
    else if (pct > 10) mod -= 5;
    else if (pct > 5)  mod -= 3;
  }
  // Frecuencia respiratoria elevada → estrés/inflamación (hasta -5 pts)
  if (resp != null && respBase > 0) {
    const pct = (resp - respBase) / respBase * 100;
    if      (pct > 15) mod -= 5;
    else if (pct > 10) mod -= 3;
    else if (pct > 5)  mod -= 2;
  }
  return mod;
}

// ── Tendencias de salud ──────────────────────────────────────────
// Compara la media de una ventana corta (por defecto 7 días) contra una larga
// (30 días) para detectar señales tempranas: HRV cayendo, FC en reposo subiendo,
// peso derivando, etc. `data` es la serie ya ordenada por fecha ascendente tal
// como la sirve el backend ([{ date, value }, ...]). Devuelve null si no hay datos.
export function seriesTrend(data, shortDays = 7, longDays = 30) {
  const clean = (data || []).filter(d => d && d.value != null && !isNaN(Number(d.value)));
  if (!clean.length) return null;
  const nums     = clean.map(d => Number(d.value));
  const shortArr = nums.slice(-shortDays);
  const longArr  = nums.slice(-longDays);
  const avg      = a => a.reduce((x, y) => x + y, 0) / a.length;
  const avgShort = avg(shortArr);
  const avgLong  = avg(longArr);
  // Delta de la ventana corta frente a la larga, en % (0 si la larga es 0).
  const deltaPct = avgLong ? ((avgShort - avgLong) / avgLong) * 100 : 0;
  return { latest: nums[nums.length - 1], avgShort, avgLong, deltaPct, n: clean.length };
}

// Dirección de una tendencia teniendo en cuenta si "más es mejor" (HRV, sueño) o
// "menos es mejor" (FC reposo, frec. respiratoria, peso si se quiere bajar). Un
// cambio por debajo de `threshold` (en %) se considera estable. Devuelve el signo
// del cambio y su valoración ("bien" | "mal" | "estable") para colorear la flecha.
export function trendDirection(deltaPct, higherIsBetter = true, threshold = 2) {
  if (deltaPct == null || Math.abs(deltaPct) < threshold) {
    return { arrow: "→", tone: "estable" };
  }
  const up = deltaPct > 0;
  const good = up === higherIsBetter;
  return { arrow: up ? "↑" : "↓", tone: good ? "bien" : "mal" };
}

// Correlación simple entre la hora de acostarse y la HRV de esa misma noche.
// Agrupa las noches en "temprano" (acostarse antes de `cutoffHour`, tratando las
// horas 18–23 como temprano y 0..cutoff como pasada medianoche pero aún temprano)
// y "tarde", y compara la HRV media de cada grupo. `sleepData` son filas de
// sleep_analysis (con extra.sleep_start "HH:MM"); `hrvData`, la serie de HRV.
// Devuelve null si no hay muestras suficientes en ambos grupos (mín. 3 cada uno).
export function bedtimeHrvInsight(sleepData, hrvData, cutoffHour = 1) {
  const hrvByDate = {};
  for (const d of hrvData || []) {
    if (d && d.value != null) hrvByDate[d.date] = Number(d.value);
  }
  const early = [], late = [];
  for (const s of sleepData || []) {
    if (!s || s.extra?.excluded) continue;
    const start = s.extra?.sleep_start;
    const hrv   = hrvByDate[s.date];
    if (!start || hrv == null || isNaN(hrv)) continue;
    const h = parseInt(String(start).slice(0, 2), 10);
    if (isNaN(h)) continue;
    // Temprano: tarde/noche antes de medianoche (18–23) o madrugada antes del corte.
    const isEarly = h >= 18 || h < cutoffHour;
    (isEarly ? early : late).push(hrv);
  }
  if (early.length < 3 || late.length < 3) return null;
  const avg      = a => a.reduce((x, y) => x + y, 0) / a.length;
  const avgEarly = avg(early);
  const avgLate  = avg(late);
  const deltaPct = avgLate ? ((avgEarly - avgLate) / avgLate) * 100 : 0;
  return { avgEarly, avgLate, deltaPct, earlyN: early.length, lateN: late.length };
}

// ── Análisis de salud: conclusiones en lenguaje claro ───────────
// Motor puro que exprime TODAS las métricas del Apple Watch y devuelve
// conclusiones accionables (no solo números). Cada una lleva dominio, tono
// (good|warn|bad|info) y texto. El widget compacto muestra el veredicto y las
// principales; el modal las muestra todas. Se apoya en findMetric/seriesTrend/
// bedtimeHrvInsight de este mismo fichero.

const _avgVal = arr => (arr && arr.length) ? arr.reduce((s, d) => s + (Number(d.value) || 0), 0) / arr.length : null;

// Horas de sueño efectivas (mismo criterio que el widget de Bienestar).
function _sleepHours(d) {
  if (d.value && d.value > 0) return Number(d.value);
  if (d.extra?.asleep > 0) return Number(d.extra.asleep);
  return (Number(d.extra?.deep) || 0) + (Number(d.extra?.rem) || 0) + (Number(d.extra?.light) || 0) + (Number(d.extra?.core) || 0);
}

// Prioridad de tono para ordenar (lo más accionable primero).
const _TONE_ORDER = { bad: 0, warn: 1, good: 2, info: 3 };

// `now` es inyectable para poder testear el cómputo de "últimos 7 días".
export function healthConclusions(healthData, now = new Date()) {
  const C = [];
  const push = (domain, tone, text) => C.push({ domain, tone, text });
  const round = n => Math.round(n);

  // ── Sueño ──
  const sleep = findMetric(healthData, "sleep_analysis", "sleep")
    .filter(d => !d.extra?.excluded)
    .map(d => ({ ...d, value: _sleepHours(d) }))
    .filter(d => d.value > 0);
  if (sleep.length) {
    const a7 = _avgVal(sleep.slice(-7));
    const t  = seriesTrend(sleep, 7, 30);
    const tone = a7 >= 7.5 ? "good" : a7 >= 6.5 ? "warn" : "bad";
    let text = `Duermes de media ${hoursToHM(a7)} las últimas ${Math.min(7, sleep.length)} noches`;
    if      (a7 < 6.5)  text += " — por debajo de lo recomendable, prioriza descansar";
    else if (a7 < 7.5)  text += " — algo justo, intenta acostarte antes";
    else                text += " — buen descanso";
    if (t && Math.abs(t.deltaPct) >= 8) text += t.deltaPct > 0 ? "; mejorando frente al mes" : "; empeorando frente al mes";
    push("Sueño", tone, text);

    // Fases (si hay desglose): sueño profundo bajo mantenido.
    const withPhases = sleep.slice(-7).filter(d => Number(d.extra?.deep) > 0);
    if (withPhases.length >= 3) {
      const deepPct = _avgVal(withPhases.map(d => ({ value: (Number(d.extra.deep) / _sleepHours(d)) * 100 })));
      if (deepPct != null && deepPct < 10) push("Sueño", "warn", `Tu sueño profundo está bajo (${round(deepPct)}% del total) — se asocia a peor recuperación física.`);
    }
  }

  // ── Recuperación: HRV ──
  const hrv = findMetric(healthData, "heart_rate_variability", "heartRateVariability").filter(d => d.value > 0);
  if (hrv.length >= 3) {
    const t  = seriesTrend(hrv, 7, 30);
    const a7 = _avgVal(hrv.slice(-7));
    if      (t && t.deltaPct <= -8) push("Recuperación", "bad",  `Tu HRV está un ${Math.abs(round(t.deltaPct))}% por debajo de tu media de 30 días (${round(a7)}ms) — señal de fatiga o estrés. Baja intensidad y prioriza el sueño.`);
    else if (t && t.deltaPct >= 8)  push("Recuperación", "good", `Tu HRV va al alza, un ${round(t.deltaPct)}% sobre tu media de 30 días (${round(a7)}ms) — buena recuperación.`);
    else                            push("Recuperación", "info", `HRV estable en torno a ${round(a7)}ms.`);
  }

  // ── Recuperación: FC en reposo ──
  const rhr = findMetric(healthData, "resting_heart_rate").filter(d => d.value > 0);
  if (rhr.length >= 3) {
    const t  = seriesTrend(rhr, 7, 30);
    const a7 = _avgVal(rhr.slice(-7));
    if (t && t.deltaPct >= 5) push("Recuperación", "warn", `Tu FC en reposo ha subido un ${round(t.deltaPct)}% (${round(a7)} bpm) — puede indicar carga acumulada, falta de sueño o algo incubándose.`);
    else                      push("Recuperación", "good", `FC en reposo en ${round(a7)} bpm${t && t.deltaPct <= -3 ? ", bajando (buena señal)" : ""}.`);
  }

  // ── Recuperación: frecuencia respiratoria ──
  const resp = findMetric(healthData, "respiratory_rate").filter(d => d.value > 0);
  if (resp.length >= 3) {
    const t = seriesTrend(resp, 7, 30);
    if (t && t.deltaPct >= 6) push("Recuperación", "warn", `Tu frecuencia respiratoria nocturna ha subido frente a tu media — a veces precede a un resfriado o refleja estrés.`);
  }

  // ── Actividad: pasos ──
  const steps = findMetric(healthData, "step_count", "steps").filter(d => d.value > 0);
  if (steps.length) {
    const a7 = _avgVal(steps.slice(-7));
    const tone = a7 >= 10000 ? "good" : a7 >= 7000 ? "info" : "warn";
    push("Actividad", tone, `Media de ${round(a7).toLocaleString("es")} pasos al día${a7 >= 10000 ? " — objetivo cumplido" : a7 < 7000 ? " — algo bajo, intenta moverte más" : ""}.`);
  }

  // ── Actividad: minutos de ejercicio ──
  const ex = findMetric(healthData, "apple_exercise_time", "exercise_time").filter(d => d.value > 0);
  if (ex.length) {
    const a7 = _avgVal(ex.slice(-7));
    push("Actividad", a7 >= 30 ? "good" : "info", `${round(a7)} min de ejercicio al día de media.`);
  }

  // ── Forma física: VO2 max ──
  const vo2 = findMetric(healthData, "vo2_max", "cardioFitness").filter(d => d.value > 0);
  if (vo2.length) {
    const v = vo2[vo2.length - 1].value;
    const cat = v >= 50 ? "excelente" : v >= 45 ? "muy bueno" : v >= 40 ? "bueno" : v >= 35 ? "normal" : "mejorable";
    push("Forma física", v >= 40 ? "good" : "info", `VO₂max de ${v.toFixed(1)} ml/kg/min — nivel ${cat}.`);
  }

  // ── Composición corporal: peso ──
  const weight = findMetric(healthData, "weight_body_mass", "weight").filter(d => d.value > 0);
  if (weight.length >= 2) {
    const cur  = weight[weight.length - 1].value;
    const prev = (weight[weight.length - 8] ?? weight[0]).value;
    const d = cur - prev;
    if (Math.abs(d) >= 0.3) push("Composición", "info", `Peso ${cur.toFixed(1)} kg (${d > 0 ? "+" : ""}${d.toFixed(1)} kg vs hace ~1 semana).`);
    else                    push("Composición", "info", `Peso estable en ${cur.toFixed(1)} kg.`);
  }

  // ── Entrenamientos (últimos 7 días) ──
  const work = findMetric(healthData, "workouts", "workout");
  if (work.length) {
    const cutoff = new Date(now.getTime() - 7 * 86400000).toISOString().slice(0, 10);
    const count = work.filter(d => d.date >= cutoff).reduce((s, d) => s + (d.extra?.workouts?.length || 0), 0);
    push("Entrenamiento", count >= 4 ? "good" : count >= 2 ? "info" : "warn",
      `${count} entrenamiento${count !== 1 ? "s" : ""} en los últimos 7 días${count >= 4 ? " — buen ritmo" : count === 0 ? " — toca moverse" : ""}.`);
  }

  // ── Patrón: hora de acostarse ↔ HRV ──
  const insight = bedtimeHrvInsight(findMetric(healthData, "sleep_analysis", "sleep"), hrv);
  if (insight && Math.abs(insight.deltaPct) >= 5) {
    push("Patrón", "info", `Las noches que te acuestas antes de la 01:00 tu HRV es un ${insight.deltaPct > 0 ? "+" : ""}${round(insight.deltaPct)}% ${insight.deltaPct > 0 ? "más alta" : "más baja"} (${insight.earlyN} vs ${insight.lateN} noches).`);
  }

  C.sort((a, b) => _TONE_ORDER[a.tone] - _TONE_ORDER[b.tone]);
  return C;
}

// Veredicto general a partir de las conclusiones: rojo si hay algo que atender,
// ámbar si hay matices, verde si todo va bien.
export function healthOverall(conclusions) {
  const has = tone => conclusions.some(c => c.tone === tone);
  if (has("bad"))          return { tone: "bad",  label: "Requiere atención" };
  if (has("warn"))         return { tone: "warn", label: "Bien, con matices" };
  if (conclusions.length)  return { tone: "good", label: "Todo en orden" };
  return { tone: "info", label: "Sin datos suficientes" };
}

// ── Puntuación de bienestar ──────────────────────────────────────
// El desglose (`breakdown`) es la única fuente de verdad: el total se deriva de él en
// vez de acumularse aparte. Antes el widget hacía `score += x` en 14 sitios pero solo
// registraba 12 filas, así que VO₂max y luz natural sumaban al número grande sin
// aparecer en el detalle y el tooltip no cuadraba con su propio total.
//
// Además normaliza a 100: la vista semanal y la diaria no puntúan sobre el mismo máximo
// (la diaria añade VO₂max, FC caminando, % grasa, luz y respiración), y usar los mismos
// umbrales para ambas hacía que "Semana excelente" exigiera el 97% y "Día excelente" el 75%.
export function scoreFromBreakdown(breakdown) {
  // `sinDatos` queda fuera de la fracción entera: no tener el sensor de una métrica
  // no debe puntuar como tenerlo y sacar un cero.
  const filas = (breakdown || []).filter(b => b && !b.sinDatos && Number(b.max) > 0);
  const pts   = filas.reduce((s, b) => s + (Number(b.pts) || 0), 0);
  const max   = filas.reduce((s, b) => s + (Number(b.max) || 0), 0);
  return { pts, max, score: max > 0 ? Math.round((pts / max) * 100) : null };
}

// ── Conteo de ropa (widget temporal) ────────────────────────────
// Monedas soportadas: euro y baht tailandés (símbolo ฿).
export const CLOTHING_CURRENCIES = { EUR: "€", THB: "฿" };

// Formatea un importe con su símbolo de moneda al estilo español: coma decimal
// y sin decimales si el importe es entero.
export function formatMoney(amount, currency) {
  const sym = CLOTHING_CURRENCIES[currency] || "";
  const n   = Number(amount) || 0;
  const txt = Number.isInteger(n) ? String(n) : n.toFixed(2).replace(".", ",");
  return `${txt} ${sym}`.trim();
}

// Suma los precios de las prendas agrupados por moneda. Devuelve un objeto
// { EUR: 12.5, THB: 450 } solo con las monedas presentes en la lista.
export function clothingTotals(items) {
  const totals = {};
  for (const it of items || []) {
    const cur   = it.currency || "EUR";
    const price = Number(it.price) || 0;
    totals[cur] = (totals[cur] || 0) + price;
  }
  return totals;
}

export function findMetric(metrics, ...names) {
  if (!metrics) return [];
  for (const name of names) {
    if (metrics[name]?.length) return metrics[name];
  }
  return [];
}

// Traduce el código WMO de Open-Meteo a icono + texto en español.
// Los códigos se agrupan por familia (grupos de la especificación WMO 4677).
export function weatherFromCode(code) {
  const map = {
    0:  ["☀️", "Despejado"],
    1:  ["🌤️", "Poco nuboso"],
    2:  ["⛅", "Parcialmente nuboso"],
    3:  ["☁️", "Nublado"],
    45: ["🌫️", "Niebla"],
    48: ["🌫️", "Niebla helada"],
    51: ["🌦️", "Llovizna ligera"],
    53: ["🌦️", "Llovizna"],
    55: ["🌦️", "Llovizna intensa"],
    56: ["🌧️", "Llovizna helada"],
    57: ["🌧️", "Llovizna helada"],
    61: ["🌧️", "Lluvia ligera"],
    63: ["🌧️", "Lluvia"],
    65: ["🌧️", "Lluvia fuerte"],
    66: ["🌧️", "Lluvia helada"],
    67: ["🌧️", "Lluvia helada"],
    71: ["🌨️", "Nieve ligera"],
    73: ["🌨️", "Nieve"],
    75: ["❄️", "Nieve fuerte"],
    77: ["🌨️", "Aguanieve"],
    80: ["🌦️", "Chubascos"],
    81: ["🌧️", "Chubascos"],
    82: ["⛈️", "Chubascos fuertes"],
    85: ["🌨️", "Chubascos de nieve"],
    86: ["❄️", "Chubascos de nieve"],
    95: ["⛈️", "Tormenta"],
    96: ["⛈️", "Tormenta con granizo"],
    99: ["⛈️", "Tormenta con granizo"],
  };
  const [emoji, label] = map[code] || ["🌡️", "—"];
  return { emoji, label };
}
