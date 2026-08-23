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

// Marca de tiempo de una entrada del registro del backend, en hora local. Lo de hoy
// solo lleva la hora: lo que se busca casi siempre es "¿y esto cuándo ha sido?", y las
// entradas van ordenadas de más reciente a más antigua.
export function formatLogTime(iso, ahora = new Date()) {
  if (!iso) return "";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return "";
  const hora = `${formatTime(d)}:${String(d.getSeconds()).padStart(2, "0")}`;
  if (d.toDateString() === ahora.toDateString()) return hora;
  return `${d.getDate()} ${MONTHS_ES[d.getMonth()].slice(0, 3)} ${hora}`;
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
export function seriesTrend(data, shortDays = 7, longDays = 30, { hoy = null } = {}) {
  const clean = (data || []).filter(d => d && d.value != null && !isNaN(Number(d.value)));
  if (!clean.length) return null;
  const avg = a => a.reduce((x, y) => x + y, 0) / a.length;
  const fin = hoy || _isoHoy();

  // Las ventanas van por FECHA REAL, no por número de registros. Con la serie
  // agujereada —que es lo que deja un mes sin llevar el reloj— `slice(-7)` no coge los
  // últimos siete días: coge las últimas siete MEDIDAS, que pueden abarcar dos meses, y
  // `slice(-30)` puede abarcar el histórico entero. Así la "media de 7d" y la de "30d"
  // acababan siendo casi el mismo dato y salía una tendencia de la comparación de algo
  // consigo mismo. Es exactamente el bug que ya se corrigió en el correo (`_media`
  // promediaba los últimos N registros), aquí un piso más arriba y peor: el correo daba
  // una cifra sin base y esto AFIRMA ("tu HRV está un 12% por debajo de tu media").
  const conFecha = clean.filter(d => _sumarDias(String(d.date), 0) != null);
  if (!conFecha.length) {
    // Serie sin fechas utilizables (la del histórico de bienestar en algunos tests, o
    // cualquier serie ya recortada por quien llama): se mantiene el conteo por
    // registros. No se puede hacer mejor sin fechas, pero tampoco se puede fingir.
    const nums = clean.map(d => Number(d.value));
    const avgShort = avg(nums.slice(-shortDays));
    const avgLong  = avg(nums.slice(-longDays));
    return {
      latest: nums[nums.length - 1], avgShort, avgLong,
      deltaPct: avgLong ? ((avgShort - avgLong) / avgLong) * 100 : 0,
      n: clean.length, nCorto: Math.min(shortDays, nums.length), nLargo: Math.min(longDays, nums.length),
      porFecha: false,
    };
  }

  const desde = n => _sumarDias(fin, -(n - 1));
  const enVentana = n => conFecha.filter(d => String(d.date) >= desde(n) && String(d.date) <= fin)
    .map(d => Number(d.value));
  const cortos = enVentana(shortDays);
  const largos = enVentana(longDays);
  // Sin nada reciente no hay tendencia que contar. Devolver una calculada sobre datos
  // viejos sería el error de antes con otra cara.
  if (!cortos.length || !largos.length) return null;
  const avgShort = avg(cortos);
  const avgLong  = avg(largos);
  const ultimo   = conFecha[conFecha.length - 1];
  return {
    latest: Number(ultimo.value), avgShort, avgLong,
    deltaPct: avgLong ? ((avgShort - avgLong) / avgLong) * 100 : 0,
    n: clean.length, nCorto: cortos.length, nLargo: largos.length,
    porFecha: true,
  };
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
// Hoy en ISO "YYYY-MM-DD" con los componentes LOCALES: `toISOString()` desplaza el día
// hacia atrás en Europe/Madrid al convertir a UTC (el mismo error que daba eventos
// creados un día antes de lo pedido).
function _isoHoy(ahora = new Date()) {
  const p = n => String(n).padStart(2, "0");
  return `${ahora.getFullYear()}-${p(ahora.getMonth() + 1)}-${p(ahora.getDate())}`;
}

function _sumarDias(iso, n) {
  const d = new Date(`${iso}T12:00:00Z`);
  if (isNaN(d.getTime())) return null;
  d.setUTCDate(d.getUTCDate() + n);
  return d.toISOString().slice(0, 10);
}

// Días enteros entre dos fechas ISO, o null si alguna no lo es.
function _diasEntre(desde, hasta) {
  const a = new Date(`${desde}T12:00:00Z`), b = new Date(`${hasta}T12:00:00Z`);
  if (isNaN(a.getTime()) || isNaN(b.getTime())) return null;
  return Math.round((b - a) / 86400000);
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

// ── Catálogo de cruces entre series ─────────────────────────────
// Los cruces estaban escritos a mano, uno detrás de otro, dentro de
// healthConclusions. Al declararlos aquí, el MISMO cruce sirve para dos ventanas
// distintas sin duplicar la fórmula: la de 30 días que alimenta las conclusiones del
// día a día, y la larga (hasta un año) del panel de patrones. Antes, ampliar la
// ventana habría significado tener dos copias de cada fórmula que se podían
// desincronizar y llegar a decir cosas contrarias en la misma pantalla.
//
// Cada entrada declara qué serie enfrenta a cuál, con qué desfase, a partir de qué
// efecto merece contarse, y cómo se redacta. `minEfecto` va por cruce porque no
// todos tienen la misma escala: un 3% en la FC en reposo es mucho, un 3% en el
// sueño profundo es ruido.

const _serieSueno = h => findMetric(h, "sleep_analysis", "sleep")
  .filter(d => !d.extra?.excluded)
  .map(d => ({ ...d, value: sleepHours(d) }))
  .filter(d => d.value > 0);

const _serieProfundo = h => _serieSueno(h)
  .filter(d => Number(d.extra?.deep) > 0)
  .map(d => ({ date: d.date, value: Number(d.extra.deep) }));

const _positiva = (...nombres) => h => findMetric(h, ...nombres).filter(d => d.value > 0);

// Horas fuera de casa (las manda Home Assistant a `time_at_home`: `value` son las horas
// en casa y `extra.fuera` las de fuera). Solo cuentan los días con COBERTURA_PRESENCIA
// horas contabilizadas o más: si HA estuvo caído media jornada, ese día sale con pocas
// horas en las dos columnas y sin el filtro se colaría como "día tranquilo en casa",
// que es justo lo contrario de lo que dice el dato — no dice nada.
export const COBERTURA_PRESENCIA = 16;

const _serieFuera = h => findMetric(h, "time_at_home")
  .map(d => ({ date: d.date, casa: Number(d.value) || 0, value: Number(d.extra?.fuera) || 0 }))
  .filter(d => d.casa + d.value >= COBERTURA_PRESENCIA);

const _r = n => Math.round(n);
const _miles = n => _r(n).toLocaleString("es");

const _CRUCES = [
  {
    id: "acostarse_hrv",
    // No pasa por pairByDate/splitCompare: agrupa por hora de acostarse, no por
    // mediana de un valor continuo. Por eso trae su propio cálculo.
    calcular: (h, { minPorGrupo }) => {
      const r = bedtimeHrvInsight(findMetric(h, "sleep_analysis", "sleep"),
        _positiva("heart_rate_variability", "heartRateVariability")(h));
      if (!r || r.earlyN < minPorGrupo || r.lateN < minPorGrupo) return null;
      return { ...r, altoN: r.earlyN, bajoN: r.lateN, n: r.earlyN + r.lateN };
    },
    minEfecto: 5,
    texto: r => ({
      tone: "info",
      text: `Las noches que te acuestas antes de la 01:00 tu HRV es un ${r.deltaPct > 0 ? "+" : ""}${_r(r.deltaPct)}% ${r.deltaPct > 0 ? "más alta" : "más baja"} (${r.earlyN} vs ${r.lateN} noches).`,
    }),
  },
  {
    // Desfase 1: el sueño de la noche del día D queda registrado en la fecha D+1.
    id: "pasos_sueno",
    causa: _positiva("step_count", "steps"),
    efecto: _serieSueno,
    desfase: 1,
    minEfecto: 5,
    texto: r => ({
      tone: r.deltaPct > 0 ? "good" : "info",
      text: `Los días que superas los ${_miles(r.corte)} pasos duermes ${hoursToHM(r.altoAvg)} frente a ${hoursToHM(r.bajoAvg)} — un ${Math.abs(_r(r.deltaPct))}% ${r.deltaPct > 0 ? "más" : "menos"} (${r.altoN} vs ${r.bajoN} días).`,
    }),
  },
  {
    // Umbral 0: separa los días con entreno de los de descanso.
    id: "entreno_rhr",
    causa: h => findMetric(h, "workouts", "workout"),
    efecto: _positiva("resting_heart_rate"),
    desfase: 1,
    umbral: 0,
    minEfecto: 3,
    texto: r => ({
      tone: r.deltaPct > 0 ? "info" : "good",
      text: `El día después de entrenar tu FC en reposo ${r.deltaPct > 0 ? "sube" : "baja"} a ${_r(r.altoAvg)} bpm frente a ${_r(r.bajoAvg)} los días de descanso${r.deltaPct > 0 ? " — es el coste normal del esfuerzo, salvo que se mantenga días" : " — señal de que estás asimilando bien la carga"}.`,
    }),
  },
  {
    id: "luz_sueno",
    causa: _positiva("time_in_daylight"),
    efecto: _serieSueno,
    desfase: 1,
    minEfecto: 5,
    // Solo se cuenta si va a favor: que dormir menos con más luz sería un hallazgo
    // raro, y casi siempre es ruido de muestra pequeña.
    soloPositivo: true,
    texto: r => ({
      tone: "good",
      text: `Los días que pasas más de ${_r(r.corte)} min al aire libre duermes ${hoursToHM(r.altoAvg)} frente a ${hoursToHM(r.bajoAvg)} — la luz de día ordena el ritmo circadiano.`,
    }),
  },
  {
    // El sueño profundo es la fase que más se asocia a la recuperación física, así
    // que es donde debería notarse el ejercicio. Se cruza contra los minutos y no
    // contra "entrené sí/no" porque aquí importa la dosis, no el hecho.
    id: "ejercicio_profundo",
    causa: _positiva("apple_exercise_time", "exercise_time"),
    efecto: _serieProfundo,
    desfase: 1,
    minEfecto: 8,
    texto: r => ({
      tone: r.deltaPct > 0 ? "good" : "info",
      text: `Los días que pasas de ${_r(r.corte)} min de ejercicio duermes ${hoursToHM(r.altoAvg)} de sueño profundo frente a ${hoursToHM(r.bajoAvg)} — un ${Math.abs(_r(r.deltaPct))}% ${r.deltaPct > 0 ? "más" : "menos"} (${r.altoN} vs ${r.bajoN} días).`,
    }),
  },
  {
    // Complementa el cruce de entrenos: recoge la carga del día a día (andar mucho),
    // que no aparece como entrenamiento pero también deja huella al día siguiente.
    id: "pasos_rhr",
    causa: _positiva("step_count", "steps"),
    efecto: _positiva("resting_heart_rate"),
    desfase: 1,
    minEfecto: 3,
    texto: r => ({
      tone: r.deltaPct > 0 ? "info" : "good",
      text: `Tras los días de más de ${_miles(r.corte)} pasos tu FC en reposo ${r.deltaPct > 0 ? "sube" : "baja"} a ${_r(r.altoAvg)} bpm frente a ${_r(r.bajoAvg)}${r.deltaPct > 0 ? " — moverte mucho también es carga" : " — el movimiento suave te está sentando bien"}.`,
    }),
  },
  {
    // La luz de día ordena el ritmo circadiano, y eso se ve tanto en cuánto duermes
    // (cruce de arriba) como en cómo te recuperas esa noche.
    id: "luz_hrv",
    causa: _positiva("time_in_daylight"),
    efecto: _positiva("heart_rate_variability", "heartRateVariability"),
    desfase: 1,
    minEfecto: 5,
    texto: r => ({
      tone: r.deltaPct > 0 ? "good" : "info",
      text: `Los días con más de ${_r(r.corte)} min de luz natural tu HRV nocturna es de ${_r(r.altoAvg)}ms frente a ${_r(r.bajoAvg)}ms — un ${Math.abs(_r(r.deltaPct))}% ${r.deltaPct > 0 ? "más alta" : "más baja"} (${r.altoN} vs ${r.bajoN} días).`,
    }),
  },
  {
    // Lo que peor se ve mirando una sola métrica: dormir poco hoy y recuperarse peor
    // mañana. Solo aparece con ventana larga porque hacen falta bastantes noches
    // malas para que los dos grupos tengan muestra suficiente.
    id: "sueno_hrv",
    causa: _serieSueno,
    efecto: _positiva("heart_rate_variability", "heartRateVariability"),
    desfase: 1,
    minEfecto: 5,
    texto: r => ({
      tone: r.deltaPct > 0 ? "info" : "warn",
      text: `Las noches que duermes más de ${hoursToHM(r.corte)} tu HRV del día siguiente es de ${_r(r.altoAvg)}ms frente a ${_r(r.bajoAvg)}ms — un ${Math.abs(_r(r.deltaPct))}% ${r.deltaPct > 0 ? "más alta" : "más baja"} (${r.altoN} vs ${r.bajoN} noches).`,
    }),
  },
  {
    id: "sueno_rhr",
    causa: _serieSueno,
    efecto: _positiva("resting_heart_rate"),
    desfase: 1,
    minEfecto: 3,
    texto: r => ({
      tone: r.deltaPct > 0 ? "warn" : "good",
      text: `Tras dormir más de ${hoursToHM(r.corte)} tu FC en reposo queda en ${_r(r.altoAvg)} bpm frente a ${_r(r.bajoAvg)} las noches cortas (${r.altoN} vs ${r.bajoN} noches).`,
    }),
  },
  {
    // Las horas fuera de casa son la única serie que no sale del Watch: la manda HA.
    // Aporta el contexto que ninguna métrica de Apple recoge — un día de pocos pasos
    // encerrado en casa y uno de pocos pasos en clase se parecen en todo lo demás.
    id: "fuera_sueno",
    causa: _serieFuera,
    efecto: _serieSueno,
    desfase: 1,
    minEfecto: 5,
    texto: r => ({
      tone: r.deltaPct > 0 ? "info" : "warn",
      text: `Los días que pasas más de ${_r(r.corte)} h fuera de casa duermes ${hoursToHM(r.altoAvg)} frente a ${hoursToHM(r.bajoAvg)} — un ${Math.abs(_r(r.deltaPct))}% ${r.deltaPct > 0 ? "más" : "menos"} (${r.altoN} vs ${r.bajoN} días).`,
    }),
  },
  {
    id: "fuera_hrv",
    causa: _serieFuera,
    efecto: _positiva("heart_rate_variability", "heartRateVariability"),
    desfase: 1,
    minEfecto: 5,
    texto: r => ({
      tone: r.deltaPct > 0 ? "good" : "warn",
      text: `Tras los días de más de ${_r(r.corte)} h fuera de casa tu HRV es de ${_r(r.altoAvg)}ms frente a ${_r(r.bajoAvg)}ms — un ${Math.abs(_r(r.deltaPct))}% ${r.deltaPct > 0 ? "más alta" : "más baja"} (${r.altoN} vs ${r.bajoN} días).`,
    }),
  },
];

// Ejecuta el catálogo de cruces sobre las series que se le den.
//
// `minPorGrupo` es la palanca que separa los dos usos: con 3 (por defecto) sirve para
// la ventana de 30 días de las conclusiones diarias; el panel de patrones lo sube
// porque con un año de datos un grupo de 3 días ya no es un hallazgo, es una
// casualidad que la muestra grande debería haber diluido.
//
// Devuelve, por cruce que supere el listón: el texto ya redactado, el tamaño de
// muestra y el efecto — para poder ordenarlos por fuerza y para que quien lo lea
// juzgue cuánto fiarse.
export function healthCorrelations(healthData, { minPorGrupo = 3 } = {}) {
  const salida = [];
  for (const cruce of _CRUCES) {
    let r;
    if (cruce.calcular) {
      r = cruce.calcular(healthData, { minPorGrupo });
    } else {
      const pares = pairByDate(cruce.causa(healthData), cruce.efecto(healthData), cruce.desfase);
      r = splitCompare(pares, { umbral: cruce.umbral ?? null, minPorGrupo });
      if (r) r = { ...r, n: r.altoN + r.bajoN };
    }
    if (!r) continue;
    if (cruce.soloPositivo ? r.deltaPct < cruce.minEfecto : Math.abs(r.deltaPct) < cruce.minEfecto) continue;
    const { tone, text } = cruce.texto(r);
    salida.push({ id: cruce.id, domain: "Patrón", tone, text, deltaPct: r.deltaPct, n: r.n });
  }
  // Lo que más se desvía primero: con varios patrones a la vez, el orden por fuerza
  // del efecto es el que pone arriba lo que de verdad mueve la aguja.
  salida.sort((a, b) => Math.abs(b.deltaPct) - Math.abs(a.deltaPct));
  return salida;
}

// Días distintos con dato en la serie más larga: es el respaldo real del análisis,
// que no tiene por qué coincidir con los días pedidos a la API (puede haber huecos).
export function healthCoverageDays(healthData) {
  const fechas = new Set();
  for (const serie of Object.values(healthData || {})) {
    for (const d of serie || []) if (d?.date) fechas.add(d.date);
  }
  return fechas.size;
}

// ── Uso del reloj ────────────────────────────────────────────────
// El backend manda en /health/metrics un `reloj` con `dias` (fecha → estado) y
// `fuentes` (métrica → "dia"|"noche"). La CLASIFICACIÓN de métricas se queda allí a
// propósito: repetirla aquí crearía dos listas que se desincronizan a la primera
// métrica nueva, que es la trampa que ya sortea `findMetric` recibiendo los alias en
// vez de conocerlos.
//
// Estados: "ambos" | "dia" | "noche" (reloj puesto) · "sin_reloj" (hubo datos del
// móvil, o sea que el reloj estaba en un cajón) · "sin_datos" (no llegó nada de nada:
// no se sabe si fue el reloj o la sincronización, y no se puede dar por ninguna).
const _PUESTO = { ambos: ["dia", "noche"], dia: ["dia"], noche: ["noche"] };

export function relojPuesto(estado, fuente = null) {
  const cubre = _PUESTO[estado];
  if (!cubre) return false;
  return fuente ? cubre.includes(fuente) : true;
}

// Cobertura del reloj en los últimos `dias`: cuántos se llevó puesto (de día y de
// noche), cuántos no, y cuántos no se sabe. `medibles` es el denominador honesto de
// cualquier media del Watch — los días sin datos de nada NO cuentan como días sin
// reloj, pero tampoco como medibles: son un "no lo sé" y se cuentan aparte.
export function relojCobertura(reloj, { dias = 7, hoy = null } = {}) {
  const fin  = hoy || _isoHoy();
  const mapa = (reloj && reloj.dias) || {};
  const out  = { dias, dia: 0, noche: 0, sinReloj: 0, sinDatos: 0, ultimoDia: null, ultimaNoche: null, hay: false };
  for (let i = 0; i < dias; i++) {
    const f = _sumarDias(fin, -i);
    if (f == null) break;
    const estado = mapa[f];
    if (estado == null || estado === "sin_datos") { out.sinDatos++; continue; }
    out.hay = true;
    if (relojPuesto(estado, "dia"))   { out.dia++;   out.ultimoDia   = out.ultimoDia   || f; }
    if (relojPuesto(estado, "noche")) { out.noche++; out.ultimaNoche = out.ultimaNoche || f; }
    if (!relojPuesto(estado))          out.sinReloj++;
  }
  return out;
}

// Días seguidos, contando desde AYER, con datos del móvil pero ninguno del reloj. Hoy
// queda fuera porque la jornada está a medias: contarla se inventaría una racha que aún
// no ha pasado. Un día "sin_datos" ni suma ni rompe — no se sabe qué pasó.
export function relojRachaSinReloj(reloj, { hoy = null, max = 60 } = {}) {
  const fin  = hoy || _isoHoy();
  const mapa = (reloj && reloj.dias) || {};
  let racha = 0;
  for (let i = 1; i <= max; i++) {
    const f = _sumarDias(fin, -i);
    if (f == null) break;
    const estado = mapa[f];
    if (estado == null || estado === "sin_datos") continue;
    if (relojPuesto(estado)) break;
    racha++;
  }
  return racha;
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

// ── Firma de "algo va mal" ──────────────────────────────────────
// FC en reposo ARRIBA + HRV ABAJO + frecuencia respiratoria ARRIBA, las tres a la vez
// contra su media de 30 días. Por separado cada una se mueve por ruido casi a diario y
// no dice nada; juntas y en la misma dirección son la señal más fiable que da el Watch,
// y suelen adelantarse un día o dos a notar el resfriado o el exceso de carga.
//
// Los umbrales de entrada (3% / -5% / 3%) son más BAJOS que los que cada métrica exige
// para hablar por su cuenta (5% / -8% / 6%): que las tres coincidan es precisamente la
// evidencia que a cada una por separado le falta. Los `claro*` son el segundo escalón,
// el que separa un "ojo con esto" (warn) de un "esto está pasando" (bad).
const _FIRMA = { rhr: 3, hrv: -5, resp: 3, claroRhr: 6, claroHrv: -10, claroResp: 6, minNoches: 3 };

// Devuelve `{ tone, text }` o null. No afirma nunca sin base: si las tres apuntan a peor
// pero alguna tendencia no tiene fondo a los dos lados —o el reloj estuvo en el cajón la
// mayoría de las noches—, lo que sale es "no hay base", sin porcentajes. Un aviso de
// enfermedad calculado sobre dos noches sueltas es justo lo que enseña a ignorarlos.
function _firmaMalestar({ tRhr, tHrv, tResp, fiable, nochesReloj = null }) {
  if (!tRhr || !tHrv || !tResp) return null;
  const apuntanMal = tRhr.deltaPct >= _FIRMA.rhr
    && tHrv.deltaPct  <= _FIRMA.hrv
    && tResp.deltaPct >= _FIRMA.resp;
  if (!apuntanMal) return null;

  const pct    = n => `${n > 0 ? "+" : ""}${Math.round(n)}%`;
  // Sobre cuántas noches se apoya la pata más débil: la firma no puede presumir del
  // respaldo de la métrica mejor medida. Si el reloj estuvo puesto menos noches de las
  // que hay datos, manda el reloj — el resto lo escribió el teléfono.
  let noches = Math.min(tRhr.nCorto, tHrv.nCorto, tResp.nCorto);
  if (nochesReloj != null) noches = Math.min(noches, nochesReloj);

  const conBase = fiable(tRhr) && fiable(tHrv) && fiable(tResp)
    && (nochesReloj == null || nochesReloj >= _FIRMA.minNoches);
  if (!conBase) {
    return {
      tone: "info",
      text: `Las tres señales de recuperación (FC en reposo, HRV y respiración) apuntan a peor a la vez, pero solo hay ${noches} noche${noches === 1 ? "" : "s"} medida${noches === 1 ? "" : "s"} detrás — no hay base para afirmarlo. Ponte el reloj estas noches y se sabrá.`,
    };
  }
  const claro = tRhr.deltaPct >= _FIRMA.claroRhr
    && tHrv.deltaPct  <= _FIRMA.claroHrv
    && tResp.deltaPct >= _FIRMA.claroResp;
  return {
    tone: claro ? "bad" : "warn",
    text: `Las tres señales de recuperación se han movido a la vez sobre ${noches} noches medidas: FC en reposo ${pct(tRhr.deltaPct)}, HRV ${pct(tHrv.deltaPct)} y respiración ${pct(tResp.deltaPct)} frente a tu media de 30 días — es la firma de estar incubando algo o de haberte pasado de carga. ${claro ? "Descansa hoy" : "Baja intensidad"} y vigílalo mañana.`,
  };
}

// `now` es inyectable para poder testear el cómputo de "últimos 7 días". `reloj` es lo
// que manda /health/metrics: con él, las conclusiones saben cuándo NO se pudo medir y
// dejan de confundirlo con "no ha pasado nada".
export function healthConclusions(healthData, now = new Date(), { reloj = null } = {}) {
  const C = [];
  const push = (domain, tone, text) => C.push({ domain, tone, text });
  const round = n => Math.round(n);
  const hoy = _isoHoy(now);

  // Todas las ventanas van por FECHA, no por número de registros. Con la serie
  // agujereada, `slice(-7)` no da "los últimos 7 días": da las últimas 7 medidas, que
  // pueden abarcar meses. Es el bug que ya se corrigió en el correo, y aquí es peor
  // porque estas frases AFIRMAN en vez de listar cifras.
  const ventana = (serie, dias = 7) => {
    const desde = _sumarDias(hoy, -(dias - 1));
    return (serie || []).filter(d => String(d.date) >= desde && String(d.date) <= hoy);
  };
  // Una tendencia necesita fondo a los dos lados: con dos medidas sueltas comparadas
  // contra otras dos, el % que sale es ruido con aspecto de hallazgo.
  const fiable = t => !!t && t.nCorto >= 3 && t.nLargo >= 7;
  const base = n => n === 1 ? "1 noche medida" : `${n} noches medidas`;

  // ── Reloj: qué se ha podido medir esta semana ──
  // Va primero porque condiciona todo lo que viene después. Sin esto, una semana con el
  // reloj en el cajón se lee como una semana sin novedad.
  const cob = reloj ? relojCobertura(reloj, { dias: 7, hoy }) : null;
  if (cob && (cob.hay || cob.sinDatos)) {
    const medibles = cob.dias - cob.sinDatos;
    const racha    = relojRachaSinReloj(reloj, { hoy });
    if (medibles > 0 && cob.noche === 0 && cob.dia === 0) {
      push("Reloj", "warn", `Sin rastro del reloj en los últimos ${medibles} día${medibles === 1 ? "" : "s"} — sueño, HRV y FC en reposo no se han podido medir.`);
    } else if (medibles > 0 && cob.noche < medibles) {
      push("Reloj", "info", `Llevaste el reloj ${cob.noche} de las ${medibles} noches: el sueño, la HRV y la FC en reposo de esta semana se apoyan solo en esas.`);
    }
    if (racha >= 2) push("Reloj", "warn", `Llevas ${racha} días seguidos sin ponerte el reloj — lo de esas noches ya no se puede recuperar.`);
    // "No llegó nada" no es "no llevabas el reloj": puede ser la sincronización caída, y
    // darlo por hábito del usuario sería el error de siempre por el otro lado.
    if (cob.sinDatos >= 2) push("Reloj", "warn", `${cob.sinDatos} de los últimos 7 días no llegó ningún dato: ahí no se sabe si fue el reloj o la sincronización.`);
  }

  // ── Sueño ──
  const sleep = findMetric(healthData, "sleep_analysis", "sleep")
    .filter(d => !d.extra?.excluded)
    .map(d => ({ ...d, value: sleepHours(d) }))
    .filter(d => d.value > 0);
  const sleep7 = ventana(sleep);
  if (sleep7.length) {
    const a7 = _avgVal(sleep7);
    const t  = seriesTrend(sleep, 7, 30, { hoy });
    const tone = a7 >= 7.5 ? "good" : a7 >= 6.5 ? "warn" : "bad";
    let text = `Duermes de media ${hoursToHM(a7)} ${sleep7.length >= 7 ? "las últimas 7 noches" : `sobre ${base(sleep7.length)} esta semana`}`;
    if      (a7 < 6.5)  text += " — por debajo de lo recomendable, prioriza descansar";
    else if (a7 < 7.5)  text += " — algo justo, intenta acostarte antes";
    else                text += " — buen descanso";
    if (fiable(t) && Math.abs(t.deltaPct) >= 8) text += t.deltaPct > 0 ? "; mejorando frente al mes" : "; empeorando frente al mes";
    push("Sueño", tone, text);

    // Fases (si hay desglose): sueño profundo bajo mantenido.
    const withPhases = sleep7.filter(d => Number(d.extra?.deep) > 0);
    if (withPhases.length >= 3) {
      const deepPct = _avgVal(withPhases.map(d => ({ value: (Number(d.extra.deep) / sleepHours(d)) * 100 })));
      if (deepPct != null && deepPct < 10) push("Sueño", "warn", `Tu sueño profundo está bajo (${round(deepPct)}% del total) — se asocia a peor recuperación física.`);
    }
  }

  // ── Recuperación: HRV ──
  const hrv  = findMetric(healthData, "heart_rate_variability", "heartRateVariability").filter(d => d.value > 0);
  const hrv7 = ventana(hrv);
  const tHrv = seriesTrend(hrv, 7, 30, { hoy });
  if (hrv7.length) {
    const a7 = _avgVal(hrv7);
    if      (fiable(tHrv) && tHrv.deltaPct <= -8) push("Recuperación", "bad",  `Tu HRV está un ${Math.abs(round(tHrv.deltaPct))}% por debajo de tu media de 30 días (${round(a7)}ms) — señal de fatiga o estrés. Baja intensidad y prioriza el sueño.`);
    else if (fiable(tHrv) && tHrv.deltaPct >= 8)  push("Recuperación", "good", `Tu HRV va al alza, un ${round(tHrv.deltaPct)}% sobre tu media de 30 días (${round(a7)}ms) — buena recuperación.`);
    else if (fiable(tHrv))                        push("Recuperación", "info", `HRV estable en torno a ${round(a7)}ms.`);
    // Sin fondo no se afirma tendencia ninguna: se dice el valor y sobre qué se apoya.
    else                                          push("Recuperación", "info", `HRV en ${round(a7)}ms, sobre ${base(hrv7.length)} — sin base para hablar de tendencia.`);
  }

  // ── Recuperación: FC en reposo ──
  const rhr  = findMetric(healthData, "resting_heart_rate").filter(d => d.value > 0);
  const rhr7 = ventana(rhr);
  const tRhr = seriesTrend(rhr, 7, 30, { hoy });
  if (rhr7.length) {
    const a7 = _avgVal(rhr7);
    if (fiable(tRhr) && tRhr.deltaPct >= 5) push("Recuperación", "warn", `Tu FC en reposo ha subido un ${round(tRhr.deltaPct)}% (${round(a7)} bpm) — puede indicar carga acumulada, falta de sueño o algo incubándose.`);
    else                                    push("Recuperación", "good", `FC en reposo en ${round(a7)} bpm${fiable(tRhr) && tRhr.deltaPct <= -3 ? ", bajando (buena señal)" : ""}.`);
  }

  // ── Recuperación: frecuencia respiratoria y firma de "algo va mal" ──
  const resp  = findMetric(healthData, "respiratory_rate").filter(d => d.value > 0);
  const tResp = seriesTrend(resp, 7, 30, { hoy });
  // La firma vive AQUÍ y no en el catálogo `_CRUCES` a propósito. Aquel cruza dos series
  // entre sí para describir un hábito estable ("los días que…") y lo ejecuta también el
  // panel de patrones sobre la ventana larga, donde esto no significaría nada: una firma
  // de enfermedad de hace ocho meses no es un hallazgo, es una gripe que ya se pasó.
  // Esto no es un patrón, es un ESTADO de ahora mismo contra la propia línea base, y
  // caduca en cuanto la semana avanza. El sitio de eso son las conclusiones.
  const firma = _firmaMalestar({ tRhr, tHrv, tResp, fiable, nochesReloj: cob ? cob.noche : null });
  // La conclusión suelta de respiración dice lo mismo que la firma, con menos contexto y
  // sin número: si la firma ha saltado, sobra. Se mantiene cuando no hay firma, porque la
  // respiración subiendo sola también es señal, solo que más débil.
  if (ventana(resp).length && fiable(tResp) && tResp.deltaPct >= 6 && !(firma && firma.tone !== "info")) {
    push("Recuperación", "warn", `Tu frecuencia respiratoria nocturna ha subido frente a tu media — a veces precede a un resfriado o refleja estrés.`);
  }
  if (firma) push("Recuperación", firma.tone, firma.text);

  // ── Actividad: pasos ──
  const steps7 = ventana(findMetric(healthData, "step_count", "steps").filter(d => d.value > 0));
  if (steps7.length) {
    const a7 = _avgVal(steps7);
    const tone = a7 >= 10000 ? "good" : a7 >= 7000 ? "info" : "warn";
    push("Actividad", tone, `Media de ${round(a7).toLocaleString("es")} pasos al día${a7 >= 10000 ? " — objetivo cumplido" : a7 < 7000 ? " — algo bajo, intenta moverte más" : ""}.`);
  }

  // ── Actividad: minutos de ejercicio ──
  const ex7 = ventana(findMetric(healthData, "apple_exercise_time", "exercise_time").filter(d => d.value > 0));
  if (ex7.length) {
    const a7 = _avgVal(ex7);
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
    // La referencia se busca por FECHA (la última pesada de hace 7 días o más), no
    // contando ocho registros hacia atrás: uno no se pesa a diario, así que ese octavo
    // registro podía ser de hace un mes y la frase seguía diciendo "hace ~1 semana".
    const ultimo = weight[weight.length - 1];
    const corte  = _sumarDias(hoy, -7);
    const previo = [...weight].reverse().find(d => String(d.date) <= corte) || weight[0];
    const cur = ultimo.value;
    const d   = cur - previo.value;
    const dias = _diasEntre(previo.date, ultimo.date);
    const cuando = dias == null ? "la medida anterior"
      : dias >= 6 && dias <= 9 ? "hace ~1 semana"
      : `hace ${dias} días`;
    if (Math.abs(d) >= 0.3) push("Composición", "info", `Peso ${cur.toFixed(1)} kg (${d > 0 ? "+" : ""}${d.toFixed(1)} kg vs ${cuando}).`);
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

  // ── Patrones (cruces entre series) ──
  // Todos salen del catálogo `_CRUCES`, para que el panel de patrones de ventana
  // larga use exactamente las mismas fórmulas que estas conclusiones del día a día.
  for (const p of healthCorrelations(healthData)) push(p.domain, p.tone, p.text);

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

// ── Línea base personal ─────────────────────────────────────────
// Los umbrales fijos de `wellnessBreakdown` ("FC en reposo ≤50 = 8 pts") premian la
// constitución, no el progreso: con una basal de 62 esos puntos no se sacan nunca por
// mucho que se mejore, y con 48 se sacan durmiendo mal. Donde eso pasa, el listón sale de
// los percentiles del propio histórico — que es exactamente lo que ya hacía el componente
// de HRV con su referencia de la semana anterior y no hacía ningún otro.
//
// Dos reglas que no se pueden relajar:
//  1. La ventana se ancla a la FECHA QUE SE PUNTÚA, nunca a hoy. Con una baseline
//     calculada "a día de hoy" el mismo día puntúa distinto según cuándo se mire y el
//     histórico de `wellnessHistory` deja de ser reproducible. Es la misma solución que
//     `_refHrv`, que ancla la referencia de HRV a la ventana D-14..D-8 de ESE día.
//  2. Sin histórico suficiente se cae al umbral fijo de siempre. Un p25 sacado de cinco
//     medidas no es una línea base: es la más baja de cinco. Y el desglose lo DICE, para
//     que quien mira el tooltip sepa contra qué se le está puntuando.
//
// La ventana termina el día ANTERIOR al que se puntúa: incluir el propio día convertiría
// la comparación en una consigo misma. En la vista semanal quedan solapados los 7 días
// que se promedian, que sobre 90 son el 8% de la muestra y no mueven un percentil.
export const BASELINE_DIAS     = 90;
export const BASELINE_MIN_DIAS = 21;

// Percentil con interpolación lineal sobre una lista YA ordenada.
function _percentil(ordenados, p) {
  if (!ordenados.length) return null;
  const pos = (ordenados.length - 1) * (p / 100);
  const lo  = Math.floor(pos), hi = Math.ceil(pos);
  return lo === hi ? ordenados[lo] : ordenados[lo] + (ordenados[hi] - ordenados[lo]) * (pos - lo);
}

// Percentiles del propio histórico de una serie en la ventana anclada a `fecha`.
// Devuelve null —y quien llama vuelve al umbral fijo— si no hay días suficientes.
export function baselinePersonal(serie, fecha, { dias = BASELINE_DIAS, minDias = BASELINE_MIN_DIAS } = {}) {
  const hasta = fecha ? _sumarDias(fecha, -1)    : null;
  const desde = fecha ? _sumarDias(fecha, -dias) : null;
  if (hasta == null || desde == null) return null;
  const vals = (serie || [])
    .filter(d => d && d.date != null && String(d.date) >= desde && String(d.date) <= hasta)
    .map(d => Number(d.value))
    // Un 0 en estas métricas es "no se midió" (el Atajo de iOS guarda ceros los días sin
    // reloj): colarlo en los percentiles hundiría la línea base entera.
    .filter(v => !isNaN(v) && v > 0)
    .sort((a, b) => a - b);
  if (vals.length < minDias) return null;
  return {
    p25: _percentil(vals, 25), p50: _percentil(vals, 50), p75: _percentil(vals, 75),
    n: vals.length, dias,
  };
}

// Qué componentes se puntúan contra uno mismo, y por qué solo estos:
//  - FC en reposo y FC caminando son FISIOLOGÍA: su valor absoluto es sobre todo
//    constitución, y lo que dice algo del día es dónde cae respecto a tu propio rango.
//  - Sueño, pasos, energía, pisos y de pie son CONDUCTA: los decides tú. Puntuarlos
//    contra la propia media es calificar en curva — premiaría a quien lleva un mes en el
//    sofá por un día un poco menos sedentario, y 7,5 h de sueño son 7,5 h para cualquiera.
//  - La HRV ya va contra su referencia (`hrvPrev`) desde siempre: no se toca.
//  - La respiración se queda fuera a propósito aunque sea fisiológica: su desviación
//    contra la baseline ya la mide `calcRecoveryMod`, y meterla aquí también dejaría dos
//    reglas distintas para la misma señal, que es como se cuelan las incoherencias.
const _SERIES_BASELINE = {
  rhr:    h => findMetric(h, "resting_heart_rate"),
  walkHr: h => findMetric(h, "walking_heart_rate_average"),
};

export function wellnessBaselines(healthData, fecha, opts = {}) {
  const out = {};
  for (const [clave, serie] of Object.entries(_SERIES_BASELINE)) {
    out[clave] = baselinePersonal(serie(healthData), fecha, opts);
  }
  return out;
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
// `baselines` es lo que devuelve `wellnessBaselines` para la fecha que se puntúa. Sin
// él (o con histórico corto) los componentes que lo admiten caen al umbral fijo.
export function wellnessBreakdown({
  isDaily = false, expectedByNow = 0,
  sleep = null, work = 0, exercise = null, steps = null, activeEnergy = null,
  stand = null, flights = null, hrv = null, hrvPrev = null, rhr = null,
  cardioRec = null, vo2 = null, walkHr = null, bodyFat = null,
  daylight = null, resp = null, baselines = null,
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

  // FC en reposo (8) — contra la línea base propia cuando la hay (ver arriba). Es el
  // caso de manual: 50 lpm es un número, no un logro.
  let rhrPts = 0;
  let rhrDetalle = "sin datos";
  const bRhr = baselines && baselines.rhr;
  if (rhr != null && bRhr) {
    // Por cuartiles de tu propio histórico. El suelo es 2 y no 0 a propósito: estar por
    // encima de tu p75 es un mal día para ti, no una urgencia.
    if      (rhr <= bRhr.p25) rhrPts = 8;
    else if (rhr <= bRhr.p50) rhrPts = 6;
    else if (rhr <= bRhr.p75) rhrPts = 4;
    else                      rhrPts = 2;
    rhrDetalle = `${Math.round(rhr)} lpm · tu rango ${Math.round(bRhr.p25)}–${Math.round(bRhr.p75)} (n=${bRhr.n})`;
  } else if (rhr != null) {
    if      (rhr <= 50) rhrPts = 8;
    else if (rhr <= 55) rhrPts = 7;
    else if (rhr <= 60) rhrPts = 6;
    else if (rhr <= 65) rhrPts = 4;
    else if (rhr <= 70) rhrPts = 3;
    else if (rhr <= 80) rhrPts = 1;
    rhrDetalle = `${Math.round(rhr)} lpm · umbral general`;
  }
  add("🫀 FC reposo", rhrPts, 8, rhrDetalle, rhr == null);

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
      // Mismo criterio que la FC en reposo: andar a 68 lpm o a 84 depende del corazón
      // que te tocó tanto como de la forma física, y lo que informa del día es dónde cae
      // respecto a tu propio rango.
      const bWalk = baselines && baselines.walkHr;
      let whrPts = 0;
      let whrDetalle;
      if (bWalk) {
        if      (walkHr <= bWalk.p25) whrPts = 4;
        else if (walkHr <= bWalk.p50) whrPts = 3;
        else if (walkHr <= bWalk.p75) whrPts = 2;
        else                          whrPts = 1;
        whrDetalle = `${Math.round(walkHr)} lpm · tu rango ${Math.round(bWalk.p25)}–${Math.round(bWalk.p75)} (n=${bWalk.n})`;
      } else {
        if      (walkHr <= 70)  whrPts = 4;
        else if (walkHr <= 80)  whrPts = 3;
        else if (walkHr <= 90)  whrPts = 2;
        else if (walkHr <= 100) whrPts = 1;
        whrDetalle = `${Math.round(walkHr)} lpm · umbral general`;
      }
      add("🏃 FC caminando", whrPts, 4, whrDetalle);
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
  const todas = (breakdown || []).filter(b => b && Number(b.max) > 0);
  const filas = todas.filter(b => !b.sinDatos);
  const pts   = filas.reduce((s, b) => s + (Number(b.pts) || 0), 0);
  const max   = filas.reduce((s, b) => s + (Number(b.max) || 0), 0);
  const maxTotal = todas.reduce((s, b) => s + (Number(b.max) || 0), 0);
  // Sobre cuánto de lo puntuable se ha medido de verdad. Normalizar a 100 hace
  // comparables un día con nueve componentes y otro con cuatro, pero los deja también
  // INDISTINGUIBLES: un 78 medido con medio reloj se pinta a la misma altura que un 78
  // completo. La cobertura es lo que permite decirlo sin romper la comparación.
  return {
    pts, max,
    score:     max > 0 ? Math.round((pts / max) * 100) : null,
    cobertura: maxTotal > 0 ? max / maxTotal : null,
    componentes: filas.length,
    sinDatos:    todas.length - filas.length,
  };
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

export function wellnessHistory(healthData, { dias = 30, reloj = null } = {}) {
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

    const { score, cobertura, sinDatos } = scoreFromBreakdown(wellnessBreakdown({
      isDaily: true,
      sleep, work, steps, rhr,
      exercise:     val("exercise"),
      activeEnergy: energia,
      stand:        val("stand"),
      flights:      val("flights"),
      hrv:          val("hrv"),
      hrvPrev:      _refHrv(series.hrv, fecha),
      // Anclada a ESTE día, no a hoy: si no, el mismo día del histórico puntuaría
      // distinto cada vez que se abre el dashboard y la sparkline dejaría de ser
      // comparable consigo misma. Misma razón que `_refHrv`.
      baselines:    wellnessBaselines(healthData, fecha),
      cardioRec:    ultimo.cardioRec,
      vo2:          ultimo.vo2,
      walkHr:       val("walkHr"),
      bodyFat:      ultimo.bodyFat,
      daylight:     val("daylight"),
      resp:         val("resp"),
    }));
    // Cada punto lleva con qué se midió, no solo cuánto puntuó: un día sin reloj puntúa
    // sobre cuatro componentes en vez de sobre nueve, y en la sparkline eso se pinta
    // exactamente igual que un día malo. `estadoReloj` es null cuando no hay dato de
    // uso del reloj (histórico viejo o backend sin la sección), que no es lo mismo que
    // "sin_datos" — ahí sabemos que no llegó nada; aquí no sabemos nada.
    const estadoReloj = (reloj && reloj.dias) ? (reloj.dias[fecha] || "sin_datos") : null;
    if (score != null) salida.push({
      date: fecha, value: score, cobertura, sinDatos,
      estadoReloj, sinReloj: estadoReloj != null && !relojPuesto(estadoReloj),
    });
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

// ── Streaming PC ─────────────────────────────────────────────────────────
// La IP a la que hay que apuntar Moonlight cuando estás fuera de casa. El agente
// la reporta en el mensaje del stage `vpn_ready` (Tailscale da una IP fija por
// máquina), así que se saca de ahí en vez de guardarla en ningún sitio: si el
// túnel no llegó a levantar, no hay evento y no hay IP que enseñar.
const RE_IPV4 = /\b(\d{1,3})\.(\d{1,3})\.(\d{1,3})\.(\d{1,3})\b/;

export function hostStreaming(eventos) {
  for (let i = (eventos?.length || 0) - 1; i >= 0; i--) {
    const ev = eventos[i];
    if (ev?.stage !== "vpn_ready") continue;
    const m = RE_IPV4.exec(ev.message || "");
    if (m && m.slice(1).every(oct => Number(oct) <= 255)) return m[0];
  }
  return null;
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

// ── Jarvis ───────────────────────────────────────────────────────
// Tope de turnos que se mandan al backend. Tiene que ser <= JARVIS_MAX_HISTORIAL del
// backend (si no, el 422 llega en mitad de una conversación) y es lo único que hace
// crecer el coste de un turno: el historial viaja entero en cada petición.
export const JARVIS_MAX_HISTORIAL = 10;

// Tope de caracteres por turno. Tiene que ser <= JARVIS_MAX_MENSAJE del backend, que
// valida cada turno del historial con el mismo límite que el mensaje nuevo (`JarvisTurno.
// texto`, no solo `JarvisIn.mensaje`). Sin este recorte, una respuesta larga de Jarvis se
// queda en el historial y el 422 lo dispara ella, no el mensaje que estás escribiendo
// ahora — pero el error que se enseña dice "el mensaje es demasiado largo" igualmente,
// porque `detail` de FastAPI para un 422 de validación es una lista, no un string, y
// `motivoJarvis()` la descarta. Bloqueaba la conversación hasta que ese turno saliera de
// la ventana de los últimos JARVIS_MAX_HISTORIAL.
export const JARVIS_MAX_TURNO = 2000;

/** Turnos que se mandan como contexto: solo los que tienen texto, y solo los últimos.
 *  Los mensajes de sistema (errores de red, avisos de la UI) no son conversación y no
 *  deben viajar: pagarlos por token cada turno para que el modelo lea "Error de
 *  conexión" no aporta nada. */
export function jarvisHistorial(mensajes, max = JARVIS_MAX_HISTORIAL) {
  return (mensajes || [])
    .filter(m => (m?.rol === "user" || m?.rol === "assistant") && (m?.texto || "").trim())
    .slice(-max)
    .map(m => ({ rol: m.rol, texto: m.texto.slice(0, JARVIS_MAX_TURNO) }));
}

/** Fecha ISO a DD/MM/AAAA para las etiquetas de confirmación. */
function _fechaLegible(iso) {
  if (!/^\d{4}-\d{2}-\d{2}$/.test(iso || "")) return "";
  const [y, m, d] = iso.split("-");
  return `${d}/${m}/${y}`;
}

/** Descripción legible de la acción que Jarvis deja propuesta, para el botón de
 *  confirmar. Sale de los ARGUMENTOS que ya viajan en la respuesta, no de cómo lo haya
 *  redactado el modelo: el usuario tiene que poder ver qué aprueba.
 *
 *  `contexto` trae lo que el dashboard YA tiene cargado (eventos, ideas) para traducir
 *  un id a su nombre real. Un id de Graph no se puede leer, así que sin esto la etiqueta
 *  de "borrar evento" sería un botón de confirmar a ciegas — y el nombre no puede salir
 *  del modelo, que es justo de quien hay que desconfiar aquí. */
export function jarvisEtiquetaAccion(pendiente, contexto = {}) {
  if (!pendiente) return null;
  const a = pendiente.argumentos || {};
  const nombreDe = (lista, id, campo) => {
    const encontrado = (lista || []).find(x => x?.id === id);
    return encontrado ? `"${encontrado[campo]}"` : "(uno que no está en la lista de ahora)";
  };

  switch (pendiente.herramienta) {
    case "crear_evento": {
      const titulo = (a.titulo || "").trim();
      if (!titulo) return null;
      const partes = [`Crear "${titulo}"`];
      const fecha = _fechaLegible(a.fecha);
      if (fecha) partes.push(`el ${fecha}`);
      if (/^\d{2}:\d{2}$/.test(a.hora_inicio || "")) partes.push(`a las ${a.hora_inicio}`);
      else partes.push("(todo el día)");
      if ((a.lugar || "").trim()) partes.push(`en ${a.lugar.trim()}`);
      return partes.join(" ");
    }
    case "editar_evento": {
      if (!a.evento_id) return null;
      const cambios = [];
      if ((a.titulo || "").trim()) cambios.push(`título "${a.titulo.trim()}"`);
      const fecha = _fechaLegible(a.fecha);
      if (fecha && /^\d{2}:\d{2}$/.test(a.hora_inicio || "")) cambios.push(`${fecha} a las ${a.hora_inicio}`);
      if ((a.lugar || "").trim()) cambios.push(`en ${a.lugar.trim()}`);
      if (!cambios.length) return null;
      return `Cambiar el evento ${nombreDe(contexto.eventos, a.evento_id, "title")}: ${cambios.join(", ")}`;
    }
    case "borrar_evento":
      if (!a.evento_id) return null;
      return `Borrar del calendario el evento ${nombreDe(contexto.eventos, a.evento_id, "title")}`;
    case "borrar_idea":
      if (!a.idea_id) return null;
      return `Borrar la nota ${nombreDe(contexto.ideas, a.idea_id, "key")}`;
    case "cobrar_entrenamiento":
      return "Marcar como cobradas las sesiones pendientes de entrenamiento";
    case "arreglar_revision":
      // Sin argumentos que enseñar: lo que se aprueba es lanzar un agente que va a
      // tocar el repositorio, así que la etiqueta dice exactamente eso.
      return "Lanzar el agente que arregla los hallazgos de la última revisión nocturna "
        + "(abrirá un PR y lo mergeará si el CI pasa)";
    case "casa_ordenar": {
      // Solo llega aquí lo que no es un interruptor (cerraduras, persianas, alarma): se
      // enseña el servicio y la entidad tal cual van a viajar a Home Assistant.
      const servicio = String(a.servicio || "").trim();
      const entidad  = String(a.entidad || "").trim();
      if (!servicio || !entidad) return null;
      return `En casa: ejecutar ${servicio} sobre ${entidad}`;
    }
    case "mcp_conectar": {
      const nombre = String(a.nombre || "").trim();
      const url    = String(a.url || "").trim();
      if (!nombre || !url) return null;
      // El token NUNCA se enseña: solo si lo lleva. Esta etiqueta acaba en pantalla.
      const cred = String(a.token || "").trim() ? "con la credencial que le has dado" : "sin credencial";
      return `Conectar el servidor MCP "${nombre}" (${url.slice(0, 120)}), ${cred}`;
    }
    case "mcp_desconectar":
      if (!String(a.nombre || "").trim()) return null;
      return `Desconectar el servidor MCP "${String(a.nombre).trim()}"`;
    case "mcp_usar": {
      // Acción sobre un servidor MCP: se enseña el servidor, la herramienta y los
      // argumentos TAL CUAL van a viajar — es lo que el usuario está aprobando.
      const servidor = String(a.servidor || "").trim();
      const util     = String(a.herramienta || "").trim();
      if (!servidor || !util) return null;
      const args  = JSON.stringify(a.argumentos || {});
      const extra = args && args !== "{}" ? ` con ${args.slice(0, 160)}` : "";
      return `Ejecutar "${util}" en el servidor ${servidor}${extra}`;
    }
    default:
      return null;
  }
}

/** Traduce un fallo de /jarvis a algo que se pueda leer y accionar.
 *  Un "no he podido responder" a secas mandaba a mirar la red cuando el problema real
 *  era un backend sin desplegar: cada código dice una cosa distinta y solo uno de ellos
 *  se arregla reintentando. */
export function jarvisMotivoError(status, detalle = "") {
  const d = (detalle || "").trim();
  if (status === 0)   return "No he podido conectar con el backend. ¿Está levantado?";
  if (status === 404) return "Este backend todavía no tiene Jarvis: falta desplegarlo (fly deploy).";
  if (status === 503) return d || "Falta configurar OPENAI_API_KEY en el backend.";
  if (status === 429) return "Demasiadas peticiones seguidas. Espera un momento.";
  if (status === 413 || status === 422) return d || "El mensaje es demasiado largo.";
  if (status >= 500)  return `El backend ha fallado (${status}). Mira el registro en ajustes.`;
  return d || `No he podido responder (error ${status}).`;
}

/** La mejor voz en español de las que ofrece el navegador (speechSynthesis.getVoices()).
 *  Preferencias, por orden: es-ES sobre otras variantes, y las voces "Natural"/"Neural"
 *  (las de Edge y Windows 11, mucho mejores que las clásicas) sobre las locales de
 *  sistema. Devuelve null si no hay ninguna en español: el que llama pone entonces solo
 *  `lang`, y el navegador elige. */
export function elegirVozEspanola(voces) {
  const candidatas = (voces || []).filter(v =>
    (v?.lang || "").toLowerCase().replace("_", "-").startsWith("es"));
  if (!candidatas.length) return null;
  const puntos = v => {
    const lang   = (v.lang || "").toLowerCase().replace("_", "-");
    const nombre = (v.name || "").toLowerCase();
    return (lang === "es-es" ? 4 : 0)
      + (/natural|neural/.test(nombre) ? 2 : 0)
      + (v.localService === false ? 1 : 0);
  };
  return candidatas.reduce((mejor, v) => (puntos(v) > puntos(mejor) ? v : mejor));
}

/** Prepara una respuesta de Jarvis para leerla en voz alta: las URLs deletreadas son
 *  insufribles y los adornos de markdown no se pronuncian. Acotado: una respuesta
 *  kilométrica tampoco se escucha entera. */
export function textoHablable(texto, max = 600) {
  return String(texto || "")
    .replace(/https?:\/\/\S+/g, "(enlace)")
    .replace(/[*_#`]+/g, "")
    .replace(/\s+/g, " ")
    .trim()
    .slice(0, max);
}

/** Silencio que se espera antes de dar por terminada una frase en el modo llamada.
 *
 *  Es la única pieza que decide si la conversación fluye o interrumpe. Demasiado corto y
 *  te corta a mitad de frase mientras piensas; demasiado largo y cada turno arrastra un
 *  silencio incómodo. 1,3 s es el punto donde una pausa normal al hablar todavía no
 *  cuenta como final. No se fía del `isFinal` del navegador: Chrome lo emite muy pronto y
 *  trocea una frase en tres. */
export const JARVIS_SILENCIO_MS = 1300;

/** Si lo que se ha dicho es una despedida, para colgar sin tocar el botón.
 *
 *  Deliberadamente corta y anclada al principio de la frase: "adiós" suelto cuelga, pero
 *  "dile adiós a las vacaciones" no. Colgar por error a media conversación molesta más
 *  que tener que pulsar. */
export function esFinDeLlamada(texto) {
  const t = String(texto || "")
    .toLowerCase()
    .normalize("NFD").replace(/\p{Diacritic}/gu, "")   // adiós → adios
    .replace(/[.,;!?¡¿]/g, " ")
    .trim();
  return /^(adios|chao|chau|cuelga|corta( la llamada)?|hasta luego|hasta ahora|nos vemos)( |$)/.test(t);
}

// ── Finanzas (cartera de Indexa Capital) ─────────────────────────
// Todo lo que llega del backend puede venir a `null`, y ahí `null` significa "no se
// sabe" (Indexa no respondió a la parte de rendimiento), nunca cero. De ahí que los tres
// formateadores devuelvan "—" en vez de "0 €": un cero es una afirmación sobre el dinero
// de alguien y esa afirmación no la tenemos.

/** Euros con separador de miles español. `signo` antepone el + a los positivos, que es
 *  lo que quiere una plusvalía y no un saldo. */
export function formatoEuros(valor, { decimales = 0, signo = false } = {}) {
  if (typeof valor !== "number" || !Number.isFinite(valor)) return "—";
  const txt = valor.toLocaleString("es-ES", {
    minimumFractionDigits: decimales,
    maximumFractionDigits: decimales,
  });
  return `${signo && valor > 0 ? "+" : ""}${txt} €`;
}

/** Un porcentaje que YA viene en porcentaje (13.64 → "13,6 %"). */
export function formatoPorcentaje(pct, { decimales = 1, signo = false } = {}) {
  if (typeof pct !== "number" || !Number.isFinite(pct)) return "—";
  const txt = pct.toLocaleString("es-ES", {
    minimumFractionDigits: decimales,
    maximumFractionDigits: decimales,
  });
  return `${signo && pct > 0 ? "+" : ""}${txt} %`;
}

/** Las rentabilidades de Indexa vienen en FRACCIÓN (0.0523 = 5,23 %). Existe esta función
 *  aparte para que la conversión esté en un solo sitio: multiplicar por 100 a ojo en cada
 *  sitio donde se pinte es la forma segura de que algún día se muestre un 0,05 %. */
export function formatoRentabilidad(fraccion, opciones = {}) {
  if (typeof fraccion !== "number" || !Number.isFinite(fraccion)) return "—";
  return formatoPorcentaje(fraccion * 100, opciones);
}

// Orden fijo de las clases de activo en la barra de mezcla. Fijo y no por tamaño a
// propósito: si los tramos se reordenaran cada vez que una clase adelanta a otra, la
// barra dejaría de poder compararse de un vistazo con la de la semana pasada.
export const CLASES_CARTERA = ["acciones", "bonos", "monetario", "efectivo", "otros"];

/** Distribución {clase: euros} → tramos ordenados con su peso en la cartera.
 *  Las clases sin dinero no salen; una clase que el backend no conozca va al final. */
export function mezclaCartera(distribucion) {
  const entradas = Object.entries(distribucion || {})
    .filter(([, v]) => typeof v === "number" && Number.isFinite(v) && v > 0);
  const total = entradas.reduce((acc, [, v]) => acc + v, 0);
  if (!total) return [];
  return entradas
    .sort((a, b) => {
      const ia = CLASES_CARTERA.indexOf(a[0]), ib = CLASES_CARTERA.indexOf(b[0]);
      return (ia === -1 ? 99 : ia) - (ib === -1 ? 99 : ib);
    })
    .map(([clase, valor]) => ({ clase, valor, pct: (valor / total) * 100 }));
}

/** Cuánto se ha movido la cartera desde el día anterior de la serie.
 *
 *  Se compara con el ÚLTIMO DÍA CON DATO, no con "ayer" del calendario: Indexa no valora
 *  fines de semana ni festivos, así que restar contra una fecha que no existe en la serie
 *  daría siempre 0 en lunes — un "no se movió" que sería mentira. */
export function variacionCartera(serie) {
  const puntos = (serie || []).filter(p => p && typeof p.valor === "number");
  if (puntos.length < 2) return null;
  const [anterior, ultimo] = [puntos[puntos.length - 2], puntos[puntos.length - 1]];
  const delta = ultimo.valor - anterior.valor;
  return {
    desde: anterior.fecha,
    valor: delta,
    pct:   anterior.valor ? (delta / anterior.valor) * 100 : null,
  };
}
