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
