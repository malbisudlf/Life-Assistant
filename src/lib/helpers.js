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

// Horas de sueño efectivas de una fila de sleep_analysis: el valor guardado si lo
// hay y, si no, la suma de las fases. Vivía copiado en tres sitios (el motor de
// conclusiones, el memo de métricas del Dashboard y el widget de sueño), con el
// riesgo de que las copias se separaran.
export function sleepHours(d) {
  if (!d) return 0;
  if (d.value && d.value > 0) return Number(d.value);
  if (d.extra?.asleep > 0) return Number(d.extra.asleep);
  return (Number(d.extra?.deep)  || 0) + (Number(d.extra?.rem)  || 0)
       + (Number(d.extra?.light) || 0) + (Number(d.extra?.core) || 0);
}

// Desglose de la puntuación de sueño. Mismo patrón que `wellnessBreakdown`: el
// desglose es la ÚNICA fuente de verdad de los umbrales y `sleepScore` se limita a
// sumarlo. Cuando el tooltip del widget tenía su propia copia de estas reglas se le
// coló otra vez el bug histórico del `h >= 1` en la hora de acostarse: enseñaba una
// penalización de -10 pts para las 22:00–23:00 que la puntuación real no aplicaba,
// así que las filas no cuadraban con su propio total. Con una sola fuente ya no
// puede volver a desincronizarse.
// Devuelve null si no hay noche suficiente que puntuar, y `{ filas, cap }` si la hay.
export function sleepBreakdown(total, deep, rem, awake, sleepStart) {
  if (!total || total < 0.5) return null;
  const filas = [];
  // Un valor de fase 0 (o ausente) no puntúa como "mal", sino como "sin dato".
  const pct = parte => parte ? (parte / total) * 100 : null;

  // Duración (40 pts) — objetivo 8h para adulto joven
  const durPts = total >= 8 && total <= 9.5 ? 40 : total >= 7.5 ? 34 : total >= 7 ? 26 : total >= 6 ? 16 : 6;
  filas.push({ label: "Duración", detail: hoursToHM(total), pts: durPts, max: 40 });

  // Sueño profundo (25 pts)
  const dp = pct(deep);
  const deepPts = dp == null ? 12 : dp >= 13 && dp <= 23 ? 25 : dp >= 10 ? 19 : dp >= 7 ? 13 : 6;
  filas.push({ label: "Sueño profundo", detail: deep != null ? `${Math.round(dp ?? 0)}% · ${hoursToHM(deep)}` : "–", pts: deepPts, max: 25 });

  // REM (25 pts)
  const rp = pct(rem);
  const remPts = rp == null ? 12 : rp >= 20 && rp <= 25 ? 25 : rp >= 15 ? 19 : rp >= 10 ? 13 : 6;
  filas.push({ label: "REM", detail: rem != null ? `${Math.round(rp ?? 0)}% · ${hoursToHM(rem)}` : "–", pts: remPts, max: 25 });

  // Tiempo despierto (10 pts)
  const ap = awake ? (awake / total) * 100 : 0;
  const awakePts = ap < 5 ? 10 : ap < 10 ? 7 : ap < 15 ? 4 : 0;
  filas.push({ label: "Tiempo despierto", detail: awake != null ? `${Math.round(ap)}% · ${hoursToHM(awake)}` : "–", pts: awakePts, max: 10 });

  // Penalización por hora de acostarse. Las horas 0–5 son "pasada medianoche"; de
  // las 6 en adelante es tarde/noche del día anterior y NO se penaliza (el `h >= 1`
  // "equivalente" castigaba las 22:00 igual que la 01:00 — ver CLAUDE.md).
  if (sleepStart) {
    const h = parseInt(String(sleepStart).slice(0, 2), 10);
    const pen = h >= 2 && h < 6 ? -15 : h === 1 ? -10 : h === 0 ? -5 : 0;
    if (pen < 0) filas.push({ label: "Hora de acostarse", detail: String(sleepStart).slice(0, 5), pts: pen, max: 0 });
  }

  // Techo por duración: dormir poco no puede dar una nota alta por muy buenas que
  // sean las fases.
  const cap = total >= 8 ? 100 : total >= 7.5 ? 82 : total >= 7 ? 68 : 52;
  return { filas, cap };
}

export function sleepScore(total, deep, rem, awake, sleepStart, recoveryMod = 0) {
  const b = sleepBreakdown(total, deep, rem, awake, sleepStart);
  if (!b) return null;
  const bruto = b.filas.reduce((s, f) => s + f.pts, 0);
  return Math.min(b.cap, Math.max(0, Math.round(bruto + recoveryMod)));
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

// ── Correlaciones entre series ───────────────────────────────────
// bedtimeHrvInsight demostró el patrón que más valor da de estos datos: cruzar dos
// series y contar algo que ninguna dice por separado. Esto lo generaliza para poder
// añadir cruces nuevos sin repetir la fontanería.

// Suma días a una fecha ISO "YYYY-MM-DD". Se trabaja a mediodía UTC para que el
// cambio de hora no desplace el día.
function _sumarDias(iso, n) {
  const d = new Date(`${iso}T12:00:00Z`);
  if (isNaN(d.getTime())) return null;
  d.setUTCDate(d.getUTCDate() + n);
  return d.toISOString().slice(0, 10);
}

// Empareja dos series por fecha. `desfase` desplaza la serie `b`: con 1, el valor de
// `a` del día D se cruza con el de `b` del día D+1 — que es lo que hace falta para
// preguntas del tipo "lo que hago hoy, ¿cómo me afecta mañana?".
export function pairByDate(a, b, desfase = 0) {
  const porFecha = {};
  for (const d of b || []) {
    if (d && d.date != null && d.value != null) porFecha[d.date] = Number(d.value);
  }
  const out = [];
  for (const d of a || []) {
    if (!d || d.date == null || d.value == null) continue;
    const fechaB = desfase ? _sumarDias(d.date, desfase) : d.date;
    const y = fechaB == null ? undefined : porFecha[fechaB];
    if (y == null || isNaN(y)) continue;
    const x = Number(d.value);
    if (isNaN(x)) continue;
    out.push({ date: d.date, x, y });
  }
  return out;
}

// Parte los pares en dos grupos según `x` y compara la media de `y` entre ellos.
// Sin `umbral` corta por la mediana (útil para métricas continuas como los pasos);
// con `umbral` corta ahí (p. ej. 0 para separar "entrené" de "no entrené").
// Devuelve null si algún grupo no llega a `minPorGrupo` — con menos muestras la
// comparación es ruido, no señal.
export function splitCompare(pares, { umbral = null, minPorGrupo = 3 } = {}) {
  const limpios = (pares || []).filter(p => p && !isNaN(p.x) && !isNaN(p.y));
  if (limpios.length < minPorGrupo * 2) return null;
  let corte = umbral;
  if (corte == null) {
    const xs = limpios.map(p => p.x).sort((m, n) => m - n);
    const mid = Math.floor(xs.length / 2);
    corte = xs.length % 2 ? xs[mid] : (xs[mid - 1] + xs[mid]) / 2;
  }
  const alto = limpios.filter(p => p.x > corte).map(p => p.y);
  const bajo = limpios.filter(p => p.x <= corte).map(p => p.y);
  if (alto.length < minPorGrupo || bajo.length < minPorGrupo) return null;
  const media = a => a.reduce((s, v) => s + v, 0) / a.length;
  const altoAvg = media(alto);
  const bajoAvg = media(bajo);
  return {
    corte, altoAvg, bajoAvg,
    altoN: alto.length, bajoN: bajo.length,
    deltaPct: bajoAvg ? ((altoAvg - bajoAvg) / bajoAvg) * 100 : 0,
  };
}

// ── Análisis de salud: conclusiones en lenguaje claro ───────────
// Motor puro que exprime TODAS las métricas del Apple Watch y devuelve
// conclusiones accionables (no solo números). Cada una lleva dominio, tono
// (good|warn|bad|info) y texto. El widget compacto muestra el veredicto y las
// principales; el modal las muestra todas. Se apoya en findMetric/seriesTrend/
// bedtimeHrvInsight de este mismo fichero.

const _avgVal = arr => (arr && arr.length) ? arr.reduce((s, d) => s + (Number(d.value) || 0), 0) / arr.length : null;

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
    .map(d => ({ ...d, value: sleepHours(d) }))
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
      const deepPct = _avgVal(withPhases.map(d => ({ value: (Number(d.extra.deep) / sleepHours(d)) * 100 })));
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

  // ── Patrón: pasos del día ↔ sueño de esa noche ──
  // Desfase 1: el sueño de la noche del día D queda registrado en la fecha D+1.
  const pasosSueno = splitCompare(pairByDate(steps, sleep, 1));
  if (pasosSueno && Math.abs(pasosSueno.deltaPct) >= 5) {
    const mas = pasosSueno.deltaPct > 0;
    push("Patrón", mas ? "good" : "info",
      `Los días que superas los ${round(pasosSueno.corte).toLocaleString("es")} pasos duermes ${hoursToHM(pasosSueno.altoAvg)} frente a ${hoursToHM(pasosSueno.bajoAvg)} — un ${Math.abs(round(pasosSueno.deltaPct))}% ${mas ? "más" : "menos"} (${pasosSueno.altoN} vs ${pasosSueno.bajoN} días).`);
  }

  // ── Patrón: entrenar ↔ FC en reposo del día siguiente ──
  // Umbral 0: separa los días con entreno de los de descanso.
  const entrenoRhr = splitCompare(pairByDate(work, rhr, 1), { umbral: 0 });
  if (entrenoRhr && Math.abs(entrenoRhr.deltaPct) >= 3) {
    const sube = entrenoRhr.deltaPct > 0;
    push("Patrón", sube ? "info" : "good",
      `El día después de entrenar tu FC en reposo ${sube ? "sube" : "baja"} a ${round(entrenoRhr.altoAvg)} bpm frente a ${round(entrenoRhr.bajoAvg)} los días de descanso${sube ? " — es el coste normal del esfuerzo, salvo que se mantenga días" : " — señal de que estás asimilando bien la carga"}.`);
  }

  // ── Patrón: luz natural ↔ sueño de esa noche ──
  const luz = findMetric(healthData, "time_in_daylight").filter(d => d.value > 0);
  const luzSueno = splitCompare(pairByDate(luz, sleep, 1));
  if (luzSueno && luzSueno.deltaPct >= 5) {
    push("Patrón", "good",
      `Los días que pasas más de ${round(luzSueno.corte)} min al aire libre duermes ${hoursToHM(luzSueno.altoAvg)} frente a ${hoursToHM(luzSueno.bajoAvg)} — la luz de día ordena el ritmo circadiano.`);
  }

  // ── Patrón: minutos de ejercicio ↔ sueño profundo de esa noche ──
  // El sueño profundo es la fase que más se asocia a la recuperación física, así que
  // es donde debería notarse el ejercicio. Se cruza contra los minutos en vez de
  // contra "entrené sí/no" porque aquí importa la dosis, no el hecho.
  const profundo = sleep
    .filter(d => Number(d.extra?.deep) > 0)
    .map(d => ({ date: d.date, value: Number(d.extra.deep) }));
  const ejercicioProfundo = splitCompare(pairByDate(ex, profundo, 1));
  if (ejercicioProfundo && Math.abs(ejercicioProfundo.deltaPct) >= 8) {
    const mas = ejercicioProfundo.deltaPct > 0;
    push("Patrón", mas ? "good" : "info",
      `Los días que pasas de ${round(ejercicioProfundo.corte)} min de ejercicio duermes ${hoursToHM(ejercicioProfundo.altoAvg)} de sueño profundo frente a ${hoursToHM(ejercicioProfundo.bajoAvg)} — un ${Math.abs(round(ejercicioProfundo.deltaPct))}% ${mas ? "más" : "menos"} (${ejercicioProfundo.altoN} vs ${ejercicioProfundo.bajoN} días).`);
  }

  // ── Patrón: pasos ↔ FC en reposo del día siguiente ──
  // Complementa el cruce de entrenos: recoge la carga del día a día (andar mucho),
  // que no aparece como entrenamiento pero también deja huella al día siguiente.
  const pasosRhr = splitCompare(pairByDate(steps, rhr, 1));
  if (pasosRhr && Math.abs(pasosRhr.deltaPct) >= 3) {
    const sube = pasosRhr.deltaPct > 0;
    push("Patrón", sube ? "info" : "good",
      `Tras los días de más de ${round(pasosRhr.corte).toLocaleString("es")} pasos tu FC en reposo ${sube ? "sube" : "baja"} a ${round(pasosRhr.altoAvg)} bpm frente a ${round(pasosRhr.bajoAvg)}${sube ? " — moverte mucho también es carga" : " — el movimiento suave te está sentando bien"}.`);
  }

  // ── Patrón: luz natural ↔ HRV de esa noche ──
  // La luz de día ordena el ritmo circadiano, y eso se ve tanto en cuánto duermes
  // (cruce de arriba) como en cómo te recuperas esa noche.
  const luzHrv = splitCompare(pairByDate(luz, hrv, 1));
  if (luzHrv && Math.abs(luzHrv.deltaPct) >= 5) {
    const mejor = luzHrv.deltaPct > 0;
    push("Patrón", mejor ? "good" : "info",
      `Los días con más de ${round(luzHrv.corte)} min de luz natural tu HRV nocturna es de ${round(luzHrv.altoAvg)}ms frente a ${round(luzHrv.bajoAvg)}ms — un ${Math.abs(round(luzHrv.deltaPct))}% ${mejor ? "más alta" : "más baja"} (${luzHrv.altoN} vs ${luzHrv.bajoN} días).`);
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
// Construye el desglose de la puntuación de bienestar a partir de los valores ya
// resueltos según la vista (diaria o semanal). Es lógica pura — todos los umbrales
// viven aquí, fuera del render, para poder testearlos.
//
// Máximos: sueño 25 · entreno 15 · pasos 8 · energía 5 · de pie 2 · pisos 2 ·
// HRV 12 · FC reposo 8 · recuperación cardio 5 · y, solo en la vista diaria,
// VO₂max 6 · FC caminando 4 · % grasa 4 · luz natural 5 · respiración 5.
// El total se saca con scoreFromBreakdown, que normaliza a 100.
export function wellnessBreakdown({
  isDaily = false, expectedByNow = 0,
  sleep = null, work = 0, exercise = null, steps = null, activeEnergy = null,
  stand = null, flights = null, hrv = null, hrvPrev = null, rhr = null,
  cardioRec = null, vo2 = null, walkHr = null, bodyFat = null,
  daylight = null, resp = null,
} = {}) {
  const b = [];
  const add = (label, pts, max, detail, sinDatos = false) => b.push({ label, pts, max, detail, sinDatos });

  // Sueño (25)
  let sPts = 0;
  if (sleep != null) {
    if      (sleep >= 7.5) sPts = 25;
    else if (sleep >= 7)   sPts = 21;
    else if (sleep >= 6.5) sPts = 15;
    else if (sleep >= 6)   sPts = 9;
    else                   sPts = 4;
  }
  add("😴 Sueño", sPts, 25, sleep != null ? hoursToHM(sleep) : "sin datos", sleep == null);

  // Entreno / ejercicio (15). En semanal se escala por los días de entreno que ya
  // han pasado, para no puntuar como fallado un objetivo que aún no toca cumplir.
  let wPts = 0;
  if (isDaily) {
    if      (work >= 1)                         wPts = 15;
    else if (exercise != null && exercise >= 30) wPts = 9;
    else if (exercise != null && exercise >= 15) wPts = 5;
    else if (hrv != null && hrv >= 70)          wPts = 3;
    else if (hrv != null && hrv >= 50)          wPts = 2;
    else                                        wPts = 1;
  } else {
    const escalado = expectedByNow > 0 ? Math.min(4, (work / expectedByNow) * 4) : work;
    if      (escalado >= 4) wPts = 15;
    else if (escalado >= 3) wPts = 11;
    else if (escalado >= 2) wPts = 7;
    else if (escalado >= 1) wPts = 3;
  }
  add("💪 Entreno", wPts, 15,
    isDaily
      ? (work >= 1 ? `${work} entreno` : exercise != null ? `${Math.round(exercise)}min ejercicio` : "descanso")
      : `${work}/4 ses.`);

  // Pasos (8)
  let stPts = 0;
  if (steps != null) {
    if      (steps >= 10000) stPts = 8;
    else if (steps >= 8000)  stPts = 6;
    else if (steps >= 6000)  stPts = 4;
    else if (steps >= 4000)  stPts = 2;
    else                     stPts = 1;
  }
  add("🚶 Pasos", stPts, 8, steps != null ? `${Math.round(steps).toLocaleString("es")}` : "sin datos", steps == null);

  // Energía activa (5)
  let aePts = 0;
  if (activeEnergy != null) {
    if      (activeEnergy >= 600) aePts = 5;
    else if (activeEnergy >= 400) aePts = 4;
    else if (activeEnergy >= 250) aePts = 3;
    else if (activeEnergy >= 100) aePts = 1;
  }
  add("🔥 Energía", aePts, 5, activeEnergy != null ? `${Math.round(activeEnergy)} kcal` : "sin datos", activeEnergy == null);

  // Horas de pie (2)
  let sdPts = 0;
  if (stand != null) {
    if      (stand >= 12) sdPts = 2;
    else if (stand >= 8)  sdPts = 1;
  }
  add("🧍 De pie", sdPts, 2, stand != null ? `${Math.round(stand)}h` : "sin datos", stand == null);

  // Pisos subidos (2)
  let flPts = 0;
  if (flights != null) {
    if      (flights >= 10) flPts = 2;
    else if (flights >= 5)  flPts = 1;
  }
  add("🪜 Pisos", flPts, 2, flights != null ? `${Math.round(flights)} pisos` : "sin datos", flights == null);

  // HRV (12), contra la referencia de la semana anterior
  let hrvPts = 0;
  if (hrv != null && hrvPrev != null) {
    if      (hrv >= hrvPrev * 1.05) hrvPts = 12;
    else if (hrv >= hrvPrev * 0.95) hrvPts = 8;
    else                            hrvPts = 4;
  } else if (hrv != null) hrvPts = 6;
  add("❤️ HRV", hrvPts, 12,
    hrv != null ? `${Math.round(hrv)}ms${hrvPrev != null ? ` (ref ${Math.round(hrvPrev)}ms)` : ""}` : "sin datos",
    hrv == null);

  // FC en reposo (8)
  let rhrPts = 0;
  if (rhr != null) {
    if      (rhr <= 50) rhrPts = 8;
    else if (rhr <= 55) rhrPts = 7;
    else if (rhr <= 60) rhrPts = 6;
    else if (rhr <= 65) rhrPts = 4;
    else if (rhr <= 70) rhrPts = 3;
    else if (rhr <= 80) rhrPts = 1;
  }
  add("🫀 FC reposo", rhrPts, 8, rhr != null ? `${Math.round(rhr)} lpm` : "sin datos", rhr == null);

  // Recuperación cardio (5) — solo si el Watch la reporta
  if (cardioRec != null) {
    let crPts = 0;
    if      (cardioRec >= 30) crPts = 5;
    else if (cardioRec >= 20) crPts = 4;
    else if (cardioRec >= 15) crPts = 3;
    else if (cardioRec >= 10) crPts = 1;
    add("💓 Recuperación cardio", crPts, 5, `${Math.round(cardioRec)} lpm/min`);
  }

  // Forma física y estilo de vida: solo en la vista diaria, porque son métricas que
  // el Watch actualiza de forma esporádica y promediarlas por semana no dice nada.
  if (isDaily) {
    if (vo2 != null) {
      let vo2Pts;   // todas las ramas asignan, incluida la final
      if      (vo2 >= 50) vo2Pts = 6;
      else if (vo2 >= 45) vo2Pts = 5;
      else if (vo2 >= 40) vo2Pts = 4;
      else if (vo2 >= 35) vo2Pts = 3;
      else                vo2Pts = 1;
      add("🫁 VO₂max", vo2Pts, 6, `${vo2.toFixed(1)} ml/kg/min`);
    }
    if (walkHr != null) {
      let whrPts = 0;
      if      (walkHr <= 70)  whrPts = 4;
      else if (walkHr <= 80)  whrPts = 3;
      else if (walkHr <= 90)  whrPts = 2;
      else if (walkHr <= 100) whrPts = 1;
      add("🏃 FC caminando", whrPts, 4, `${Math.round(walkHr)} lpm`);
    }
    if (bodyFat != null) {
      let bfPts = 0;
      if      (bodyFat < 12) bfPts = 4;
      else if (bodyFat < 18) bfPts = 3;
      else if (bodyFat < 25) bfPts = 2;
      else if (bodyFat < 30) bfPts = 1;
      add("⚖️ % Grasa", bfPts, 4, `${bodyFat.toFixed(1)}%`);
    }
    if (daylight != null) {
      let dlPts = 0;
      if      (daylight >= 60) dlPts = 5;
      else if (daylight >= 30) dlPts = 4;
      else if (daylight >= 15) dlPts = 2;
      else if (daylight >= 5)  dlPts = 1;
      add("☀️ Luz natural", dlPts, 5, `${Math.round(daylight)} min`);
    }
    if (resp != null) {
      let respPts = 1;
      if      (resp >= 12 && resp <= 16) respPts = 5;
      else if (resp > 16 && resp <= 18)  respPts = 4;
      else if (resp > 18 && resp <= 20)  respPts = 3;
      else if (resp < 12)                respPts = 4;
      add("🌬️ Resp.", respPts, 5, `${resp.toFixed(1)} rpm`);
    }
  }

  return b;
}

export function scoreFromBreakdown(breakdown) {
  // `sinDatos` queda fuera de la fracción entera: no tener el sensor de una métrica
  // no debe puntuar como tenerlo y sacar un cero.
  const filas = (breakdown || []).filter(b => b && !b.sinDatos && Number(b.max) > 0);
  const pts   = filas.reduce((s, b) => s + (Number(b.pts) || 0), 0);
  const max   = filas.reduce((s, b) => s + (Number(b.max) || 0), 0);
  return { pts, max, score: max > 0 ? Math.round((pts / max) * 100) : null };
}

// ── Histórico de la puntuación de bienestar ─────────────────────
// El widget solo enseña la foto de hoy o de la semana, así que no se ve si el mes va
// a mejor o a peor. Esto reconstruye la puntuación DIARIA de cada día a partir de las
// mismas series que ya sirve /health/metrics y con las mismas reglas
// (`wellnessBreakdown` en modo diario + `scoreFromBreakdown`): el histórico se deriva
// de lo que ya hay, sin tabla nueva ni nada que guardar.
//
// Como el score va normalizado a 100, los días con menos sensores siguen siendo
// comparables con los que los tienen todos.

// Índice fecha → valor numérico de una serie.
function _porFecha(serie) {
  const m = new Map();
  for (const d of serie || []) {
    if (d && d.date != null && d.value != null && !isNaN(Number(d.value))) m.set(d.date, Number(d.value));
  }
  return m;
}

// Referencia de HRV de un día: media de la ventana que va de D-14 a D-8. Es la misma
// que usa la vista diaria del widget (`slice(-14, -7)`), pero anclada a esa fecha en
// vez de a hoy, para que el día puntúe como habría puntuado entonces.
function _refHrv(hrvPorFecha, fecha) {
  const vals = [];
  for (let i = 14; i >= 8; i--) {
    const f = _sumarDias(fecha, -i);
    const v = f == null ? null : hrvPorFecha.get(f);
    if (v != null && v > 0) vals.push(v);
  }
  return vals.length ? vals.reduce((s, v) => s + v, 0) / vals.length : null;
}

export function wellnessHistory(healthData, { dias = 30 } = {}) {
  const series = {
    sleep: _porFecha(findMetric(healthData, "sleep_analysis", "sleep")
      .filter(d => !d.extra?.excluded)
      .map(d => ({ date: d.date, value: sleepHours(d) }))),
    work: _porFecha(findMetric(healthData, "workouts", "workout")
      .map(d => ({ date: d.date, value: d.extra?.workouts?.length || 0 }))),
    exercise: _porFecha(findMetric(healthData, "apple_exercise_time", "exercise_time")),
    steps:    _porFecha(findMetric(healthData, "step_count", "steps")),
    energia:  _porFecha(findMetric(healthData, "active_energy")),
    stand:    _porFecha(findMetric(healthData, "apple_stand_hour", "stand_hour")),
    flights:  _porFecha(findMetric(healthData, "flights_climbed")),
    hrv:      _porFecha(findMetric(healthData, "heart_rate_variability", "heartRateVariability")),
    rhr:      _porFecha(findMetric(healthData, "resting_heart_rate")),
    walkHr:   _porFecha(findMetric(healthData, "walking_heart_rate_average")),
    daylight: _porFecha(findMetric(healthData, "time_in_daylight")),
    resp:     _porFecha(findMetric(healthData, "respiratory_rate")),
  };
  // El Watch actualiza estas de higos a brevas: para cada día vale el último valor
  // conocido hasta esa fecha, que es lo que el widget habría mostrado ese día.
  const esporadicas = {
    vo2:       _porFecha(findMetric(healthData, "vo2_max", "cardioFitness")),
    bodyFat:   _porFecha(findMetric(healthData, "body_fat_percentage")),
    cardioRec: _porFecha(findMetric(healthData, "cardio_recovery")),
  };

  const fechas = new Set();
  for (const m of [...Object.values(series), ...Object.values(esporadicas)]) {
    for (const f of m.keys()) fechas.add(f);
  }
  const ordenadas = [...fechas].sort();

  const ultimo = { vo2: null, bodyFat: null, cardioRec: null };
  const salida = [];
  for (const fecha of ordenadas) {
    for (const k of Object.keys(ultimo)) {
      const v = esporadicas[k].get(fecha);
      if (v != null && v > 0) ultimo[k] = v;
    }

    // Un 0 en estas series es "no hubo dato", no "hubo cero" (igual que en el widget).
    const val = k => {
      const v = series[k].get(fecha);
      return v != null && v > 0 ? v : null;
    };
    const work    = series.work.get(fecha) || 0;
    const sleep   = val("sleep");
    const steps   = val("steps");
    const rhr     = val("rhr");
    const energia = val("energia");
    // Mismo criterio de "hay algo que puntuar" que el widget: si no, saldría un número
    // construido casi entero a base de "sin datos".
    if (sleep == null && steps == null && rhr == null && energia == null && work === 0) continue;

    const { score } = scoreFromBreakdown(wellnessBreakdown({
      isDaily: true,
      sleep, work, steps, rhr,
      exercise:     val("exercise"),
      activeEnergy: energia,
      stand:        val("stand"),
      flights:      val("flights"),
      hrv:          val("hrv"),
      hrvPrev:      _refHrv(series.hrv, fecha),
      cardioRec:    ultimo.cardioRec,
      vo2:          ultimo.vo2,
      walkHr:       val("walkHr"),
      bodyFat:      ultimo.bodyFat,
      daylight:     val("daylight"),
      resp:         val("resp"),
    }));
    if (score != null) salida.push({ date: fecha, value: score });
  }
  return salida.slice(-dias);
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
