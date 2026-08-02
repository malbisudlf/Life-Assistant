import { describe, test, expect, vi, afterEach } from "vitest";
import {
  isToday, isFuture, isPast, isActive, daysUntil, formatTime, formatUpcomingTime,
  urgencyColor, formatShortDate, isoToDdMmYyyy, formatLogTime,
  hoursToHM, sleepScore, sleepBreakdown, sleepHours, calcRecoveryMod, findMetric,
  weatherFromCode, weekdayShort,
  seriesTrend, trendDirection, bedtimeHrvInsight, pairByDate, splitCompare,
  healthConclusions, healthOverall, wellnessBreakdown, scoreFromBreakdown, wellnessHistory,
  formatMoney, clothingTotals,
} from "../../src/lib/helpers";

afterEach(() => {
  vi.useRealTimers();
});

describe("helpers de fecha", () => {
  test("isToday / isFuture / isPast", () => {
    vi.useFakeTimers();
    vi.setSystemTime(new Date("2026-07-05T12:00:00"));
    expect(isToday("2026-07-05T09:00:00")).toBe(true);
    expect(isToday("2026-07-06T09:00:00")).toBe(false);
    expect(isFuture("2026-07-05T13:00:00")).toBe(true);
    expect(isFuture("2026-07-05T11:00:00")).toBe(false);
    expect(isPast("2026-07-05T11:00:00")).toBe(true);
    expect(isPast("2026-07-05T13:00:00")).toBe(false);
  });

  test("isActive detecta un evento en curso", () => {
    vi.useFakeTimers();
    vi.setSystemTime(new Date("2026-07-05T12:00:00"));
    expect(isActive("2026-07-05T11:00:00", "2026-07-05T13:00:00")).toBe(true);
    expect(isActive("2026-07-05T13:00:00", "2026-07-05T14:00:00")).toBe(false);
    expect(isActive("2026-07-05T09:00:00", "2026-07-05T10:00:00")).toBe(false);
  });

  test("daysUntil redondea hacia arriba", () => {
    vi.useFakeTimers();
    vi.setSystemTime(new Date("2026-07-05T12:00:00"));
    expect(daysUntil("2026-07-06T12:00:00")).toBe(1);
    expect(daysUntil("2026-07-06T13:00:00")).toBe(2); // 1 día y 1 hora → 2
    expect(daysUntil("2026-07-05T13:00:00")).toBe(1);
  });

  test("formatTime da HH:MM en hora local", () => {
    expect(formatTime("2026-07-05T09:05:00")).toBe("09:05");
    expect(formatTime("2026-07-05T23:59:00")).toBe("23:59");
  });

  test("formatUpcomingTime: hoy, mañana y día de la semana", () => {
    vi.useFakeTimers();
    vi.setSystemTime(new Date("2026-07-05T08:00:00")); // domingo
    expect(formatUpcomingTime("2026-07-05T10:30:00")).toBe("10:30");
    expect(formatUpcomingTime("2026-07-06T10:30:00")).toBe("Mañana 10:30");
    expect(formatUpcomingTime("2026-07-08T10:30:00")).toBe("Mié 10:30");
  });

  test("urgencyColor por proximidad", () => {
    expect(urgencyColor(1)).toBe("#d4645a");
    expect(urgencyColor(3)).toBe("#d4645a");
    expect(urgencyColor(5)).toBe("#c8a45a");
    expect(urgencyColor(10)).toBe("#6aaa82");
  });

  test("formatShortDate e isoToDdMmYyyy", () => {
    expect(formatShortDate("2026-07-05")).toBe("5 jul");
    expect(formatShortDate("")).toBe("");
    expect(isoToDdMmYyyy("2026-07-05")).toBe("05/07/2026");
    expect(isoToDdMmYyyy("")).toBe("");
  });

  test("formatLogTime: lo de hoy solo lleva la hora", () => {
    const ahora = new Date(2026, 7, 2, 18, 0, 0);
    expect(formatLogTime(new Date(2026, 7, 2, 9, 5, 30).toISOString(), ahora)).toBe("09:05:30");
    // De otro día hace falta saber cuál, si no todas las entradas parecen de hoy.
    expect(formatLogTime(new Date(2026, 6, 30, 9, 5, 30).toISOString(), ahora)).toBe("30 jul 09:05:30");
  });

  test("formatLogTime aguanta lo que no es una fecha", () => {
    expect(formatLogTime("")).toBe("");
    expect(formatLogTime(null)).toBe("");
    expect(formatLogTime("no soy una fecha")).toBe("");
  });
});

describe("helpers de salud", () => {
  test("hoursToHM formatea horas decimales", () => {
    expect(hoursToHM(8)).toBe("8h");
    expect(hoursToHM(7.5)).toBe("7h 30m");
    expect(hoursToHM(0.25)).toBe("0h 15m");
    expect(hoursToHM(null)).toBe("—");
    expect(hoursToHM(NaN)).toBe("—");
  });

  test("sleepScore: null si no hay sueño suficiente", () => {
    expect(sleepScore(null)).toBeNull();
    expect(sleepScore(0)).toBeNull();
    expect(sleepScore(0.4)).toBeNull();
  });

  test("sleepScore: noche perfecta llega al máximo", () => {
    // 8h, 18% profundo, 22% REM, 0 despierto, acostado a las 23h
    const score = sleepScore(8, 1.44, 1.76, 0, "23:00");
    expect(score).toBe(100);
  });

  test("sleepScore: cap por duración", () => {
    // 7h no puede superar 68 aunque las fases sean perfectas
    const score = sleepScore(7, 1.26, 1.54, 0, "23:00");
    expect(score).toBeLessThanOrEqual(68);
    // 6h queda capado a 52
    const short = sleepScore(6, 1.08, 1.32, 0, "23:00");
    expect(short).toBeLessThanOrEqual(52);
  });

  test("sleepScore: penaliza acostarse tarde", () => {
    const early = sleepScore(8, 1.44, 1.76, 0, "23:00");
    const late  = sleepScore(8, 1.44, 1.76, 0, "03:00");
    expect(late).toBeLessThan(early);
    expect(early - late).toBe(15);
  });

  test("sleepScore: nunca es negativo y aplica recoveryMod", () => {
    const bad = sleepScore(1, 0, 0, 0.5, "04:00", -20);
    expect(bad).toBeGreaterThanOrEqual(0);
    const base = sleepScore(8, 1.44, 1.76, 0, "22:00", 0);
    const modded = sleepScore(8, 1.44, 1.76, 0, "22:00", -10);
    expect(base - modded).toBe(10);
  });

  // El tooltip del widget de sueño llegó a tener su propia copia de los umbrales y se
  // le coló otra vez el bug histórico del `h >= 1`: enseñaba -10 pts por acostarse a
  // las 22:00 que la puntuación real nunca aplicaba. Ahora ambos salen del desglose.
  test("sleepBreakdown: acostarse antes de medianoche no genera fila de penalización", () => {
    for (const hora of ["21:30", "22:00", "23:45"]) {
      const filas = sleepBreakdown(8, 1.44, 1.76, 0, hora).filas;
      expect(filas.find(f => f.label === "Hora de acostarse")).toBeUndefined();
    }
    // A partir de medianoche sí penaliza, y con el peso que documenta sleepScore
    expect(sleepBreakdown(8, 1.44, 1.76, 0, "00:30").filas.at(-1)).toMatchObject({ label: "Hora de acostarse", pts: -5 });
    expect(sleepBreakdown(8, 1.44, 1.76, 0, "01:15").filas.at(-1)).toMatchObject({ label: "Hora de acostarse", pts: -10 });
    expect(sleepBreakdown(8, 1.44, 1.76, 0, "03:00").filas.at(-1)).toMatchObject({ label: "Hora de acostarse", pts: -15 });
  });

  test("sleepBreakdown: las filas suman exactamente el score (sin cap ni recoveryMod)", () => {
    const casos = [
      [8,   1.44, 1.76, 0,    "23:00"],
      [8.5, 0.9,  2.2,  0.4,  "01:00"],
      [9,   1.2,  1.5,  1.1,  "22:15"],
    ];
    for (const c of casos) {
      const { filas } = sleepBreakdown(...c);
      const suma = filas.reduce((s, f) => s + f.pts, 0);
      expect(sleepScore(...c)).toBe(suma);
    }
  });

  test("sleepBreakdown: null cuando no hay noche que puntuar", () => {
    expect(sleepBreakdown(null)).toBeNull();
    expect(sleepBreakdown(0.4)).toBeNull();
  });

  test("sleepHours: valor guardado, si no asleep, si no suma de fases", () => {
    expect(sleepHours({ value: 7.5 })).toBe(7.5);
    expect(sleepHours({ value: 0, extra: { asleep: 6.2 } })).toBe(6.2);
    expect(sleepHours({ value: 0, extra: { deep: 1, rem: 1.5, core: 4, light: 0.5 } })).toBe(7);
    expect(sleepHours(null)).toBe(0);
  });

  test("calcRecoveryMod: sin datos no penaliza", () => {
    expect(calcRecoveryMod(null, null, null, 0, 0, 0)).toBe(0);
    expect(calcRecoveryMod(50, 60, 15, 50, 60, 15)).toBe(0);
  });

  test("calcRecoveryMod: penalización máxima -20", () => {
    // HRV -30%, FC reposo +20%, respiración +20%
    expect(calcRecoveryMod(35, 72, 18, 50, 60, 15)).toBe(-20);
  });

  test("calcRecoveryMod: tramos intermedios", () => {
    expect(calcRecoveryMod(45, null, null, 50, 0, 0)).toBe(-3);  // HRV -10%
    expect(calcRecoveryMod(null, 64, null, 0, 60, 0)).toBe(-3);  // RHR +6.7%
    expect(calcRecoveryMod(null, null, 16.7, 0, 0, 15)).toBe(-3); // resp +11.3%
  });

  test("findMetric devuelve la primera métrica con datos", () => {
    const metrics = { step_count: [], steps: [{ date: "2026-07-05", value: 100 }] };
    expect(findMetric(metrics, "step_count", "steps")).toEqual([{ date: "2026-07-05", value: 100 }]);
    expect(findMetric(metrics, "no_existe")).toEqual([]);
    expect(findMetric(null, "steps")).toEqual([]);
  });

  test("weatherFromCode traduce códigos WMO y cae en un default", () => {
    expect(weatherFromCode(0)).toEqual({ emoji: "☀️", label: "Despejado" });
    expect(weatherFromCode(3)).toEqual({ emoji: "☁️", label: "Nublado" });
    expect(weatherFromCode(95)).toEqual({ emoji: "⛈️", label: "Tormenta" });
    expect(weatherFromCode(1234)).toEqual({ emoji: "🌡️", label: "—" });
  });

  test("weekdayShort da el día corto en español y '' si es inválido", () => {
    expect(weekdayShort("2026-07-23")).toBe("Jue");
    expect(weekdayShort("no-es-fecha")).toBe("");
  });
});

describe("helpers de tendencias de salud", () => {
  test("seriesTrend calcula medias corta/larga y delta%", () => {
    // 30 valores: primeros 23 a 40, últimos 7 a 50 → media 7d=50, media 30d≈42.33
    const data = [];
    for (let i = 0; i < 23; i++) data.push({ date: `d${i}`, value: 40 });
    for (let i = 0; i < 7; i++)  data.push({ date: `e${i}`, value: 50 });
    const t = seriesTrend(data, 7, 30);
    expect(t.avgShort).toBe(50);
    expect(t.avgLong).toBeCloseTo(42.33, 1);
    expect(t.deltaPct).toBeGreaterThan(0);
    expect(t.latest).toBe(50);
    expect(t.n).toBe(30);
  });

  test("seriesTrend ignora valores nulos y devuelve null sin datos", () => {
    expect(seriesTrend([])).toBe(null);
    expect(seriesTrend([{ value: null }, { value: undefined }])).toBe(null);
    expect(seriesTrend(null)).toBe(null);
    const t = seriesTrend([{ value: 10 }, { value: null }, { value: 20 }], 2, 2);
    expect(t.avgShort).toBe(15); // solo cuenta 10 y 20
  });

  test("trendDirection valora según si más es mejor y el umbral", () => {
    expect(trendDirection(1, true)).toEqual({ arrow: "→", tone: "estable" });   // < umbral
    expect(trendDirection(10, true)).toEqual({ arrow: "↑", tone: "bien" });      // sube y sube=bien
    expect(trendDirection(10, false)).toEqual({ arrow: "↑", tone: "mal" });      // sube pero menos=mejor
    expect(trendDirection(-10, false)).toEqual({ arrow: "↓", tone: "bien" });    // baja y menos=mejor
    expect(trendDirection(-10, true)).toEqual({ arrow: "↓", tone: "mal" });
    expect(trendDirection(null, true)).toEqual({ arrow: "→", tone: "estable" });
  });

  test("bedtimeHrvInsight compara HRV según hora de acostarse", () => {
    const sleep = [
      { date: "2026-07-01", extra: { sleep_start: "23:30" } }, // temprano
      { date: "2026-07-02", extra: { sleep_start: "22:45" } }, // temprano
      { date: "2026-07-03", extra: { sleep_start: "00:20" } }, // temprano (antes de la 01)
      { date: "2026-07-04", extra: { sleep_start: "01:40" } }, // tarde
      { date: "2026-07-05", extra: { sleep_start: "02:10" } }, // tarde
      { date: "2026-07-06", extra: { sleep_start: "03:00" } }, // tarde
    ];
    const hrv = [
      { date: "2026-07-01", value: 60 },
      { date: "2026-07-02", value: 62 },
      { date: "2026-07-03", value: 58 },
      { date: "2026-07-04", value: 50 },
      { date: "2026-07-05", value: 48 },
      { date: "2026-07-06", value: 52 },
    ];
    const r = bedtimeHrvInsight(sleep, hrv);
    expect(r.earlyN).toBe(3);
    expect(r.lateN).toBe(3);
    expect(r.avgEarly).toBeCloseTo(60, 5);
    expect(r.avgLate).toBeCloseTo(50, 5);
    expect(r.deltaPct).toBeCloseTo(20, 5); // HRV 20% mayor acostándose temprano
  });

  test("bedtimeHrvInsight devuelve null sin muestras suficientes o excluidas", () => {
    expect(bedtimeHrvInsight([], [])).toBe(null);
    const sleep = [
      { date: "d1", extra: { sleep_start: "23:00", excluded: true } },
      { date: "d2", extra: { sleep_start: "23:00" } },
    ];
    const hrv = [{ date: "d1", value: 60 }, { date: "d2", value: 60 }];
    expect(bedtimeHrvInsight(sleep, hrv)).toBe(null); // solo 1 noche válida
  });
});

describe("motor de conclusiones de salud", () => {
  // Genera una serie de N días con un valor constante (o función por índice).
  const serie = (n, v) => Array.from({ length: n }, (_, i) => ({
    date: `2026-06-${String(i + 1).padStart(2, "0")}`,
    value: typeof v === "function" ? v(i) : v,
  }));

  test("HRV cayendo genera una conclusión roja de fatiga", () => {
    // 23 días a 60ms y 7 a 45ms → media 7d muy por debajo de la de 30d
    const hrv = [...serie(23, 60), ...serie(7, 45).map((d, i) => ({ ...d, date: `2026-07-${String(i + 1).padStart(2, "0")}` }))];
    const c = healthConclusions({ heart_rate_variability: hrv });
    const rec = c.find(x => x.domain === "Recuperación" && x.tone === "bad");
    expect(rec).toBeTruthy();
    expect(rec.text).toMatch(/HRV/);
  });

  test("sueño corto es conclusión roja; sueño bueno es verde", () => {
    const corto = healthConclusions({ sleep_analysis: serie(7, 5.5) });
    expect(corto.find(x => x.domain === "Sueño").tone).toBe("bad");
    const bueno = healthConclusions({ sleep_analysis: serie(7, 8) });
    expect(bueno.find(x => x.domain === "Sueño").tone).toBe("good");
  });

  test("cuenta entrenamientos de los últimos 7 días según 'now'", () => {
    const now = new Date("2026-06-10T12:00:00");
    const work = [
      { date: "2026-06-09", extra: { workouts: [{}, {}] } }, // dentro
      { date: "2026-06-01", extra: { workouts: [{}] } },     // fuera (>7d)
    ];
    const c = healthConclusions({ workouts: work }, now);
    const w = c.find(x => x.domain === "Entrenamiento");
    expect(w.text).toMatch(/^2 entrenamientos/);
  });

  test("las conclusiones se ordenan por prioridad (bad antes que good)", () => {
    const c = healthConclusions({
      heart_rate_variability: [...serie(23, 60), ...serie(7, 45).map((d, i) => ({ ...d, date: `2026-07-0${i + 1}` }))],
      step_count: serie(7, 12000), // good
    });
    const idxBad  = c.findIndex(x => x.tone === "bad");
    const idxGood = c.findIndex(x => x.tone === "good");
    expect(idxBad).toBeLessThan(idxGood);
  });

  test("healthOverall resume el peor tono presente", () => {
    expect(healthOverall([{ tone: "good" }, { tone: "warn" }, { tone: "bad" }]).tone).toBe("bad");
    expect(healthOverall([{ tone: "good" }, { tone: "warn" }]).tone).toBe("warn");
    expect(healthOverall([{ tone: "good" }]).tone).toBe("good");
    expect(healthOverall([]).label).toMatch(/Sin datos/);
  });

  test("sin datos no revienta y devuelve lista vacía", () => {
    expect(healthConclusions({})).toEqual([]);
    expect(healthConclusions(null)).toEqual([]);
  });
});

describe("helpers de conteo de ropa", () => {
  test("formatMoney: entero sin decimales, decimal con coma", () => {
    expect(formatMoney(20, "EUR")).toBe("20 €");
    expect(formatMoney(12.5, "EUR")).toBe("12,50 €");
    expect(formatMoney(450, "THB")).toBe("450 ฿");
    expect(formatMoney(0, "EUR")).toBe("0 €");
  });

  test("formatMoney: valores inválidos cuentan como 0 y moneda desconocida sin símbolo", () => {
    expect(formatMoney(null, "EUR")).toBe("0 €");
    expect(formatMoney("abc", "THB")).toBe("0 ฿");
    expect(formatMoney(10, "XXX")).toBe("10");
  });

  test("clothingTotals agrupa por moneda", () => {
    const items = [
      { price: 20, currency: "EUR" },
      { price: 12.5, currency: "EUR" },
      { price: 450, currency: "THB" },
    ];
    expect(clothingTotals(items)).toEqual({ EUR: 32.5, THB: 450 });
  });

  test("clothingTotals: default EUR, precios inválidos como 0, lista vacía", () => {
    expect(clothingTotals([{ price: 5 }, { price: "x", currency: "EUR" }])).toEqual({ EUR: 5 });
    expect(clothingTotals([])).toEqual({});
    expect(clothingTotals(null)).toEqual({});
  });
});

// ── Puntuación de bienestar ─────────────────────────────────────
describe("scoreFromBreakdown", () => {
  test("el total sale de sumar el desglose, normalizado a 100", () => {
    const b = [
      { label: "Sueño", pts: 25, max: 25 },
      { label: "Pasos", pts: 4,  max: 8 },
      { label: "HRV",   pts: 6,  max: 12 },
    ];
    expect(scoreFromBreakdown(b)).toEqual({ pts: 35, max: 45, score: 78 });
  });

  test("las métricas sin dato no cuentan ni arriba ni abajo", () => {
    // No tener sensor de pisos no debe penalizar la puntuación.
    const conPisos = [
      { label: "Sueño", pts: 25, max: 25 },
      { label: "Pisos", pts: 0,  max: 2, sinDatos: true },
    ];
    expect(scoreFromBreakdown(conPisos)).toEqual({ pts: 25, max: 25, score: 100 });
  });

  test("semanal y diaria se comparan sobre la misma escala", () => {
    // Antes: la semanal sumaba como mucho 82 y la diaria 106, pero ambas usaban el
    // umbral fijo de 80 → "Semana excelente" exigía el 97% y "Día excelente" el 75%.
    const semanal = [{ pts: 41, max: 82 }];
    const diaria  = [{ pts: 53, max: 106 }];
    expect(scoreFromBreakdown(semanal).score).toBe(50);
    expect(scoreFromBreakdown(diaria).score).toBe(50);
  });

  test("desglose vacío o sin máximos devuelve score nulo", () => {
    expect(scoreFromBreakdown([]).score).toBeNull();
    expect(scoreFromBreakdown(null).score).toBeNull();
    expect(scoreFromBreakdown([{ pts: 0, max: 0 }]).score).toBeNull();
  });

  test("ignora filas corruptas sin romper", () => {
    const b = [{ pts: 5, max: 10 }, null, { pts: "x", max: 10 }];
    expect(scoreFromBreakdown(b)).toEqual({ pts: 5, max: 20, score: 25 });
  });
});

describe("wellnessBreakdown", () => {
  const etiquetas = b => b.map(x => x.label);
  const fila      = (b, txt) => b.find(x => x.label.includes(txt));

  // Todas las métricas de la vista semanal con dato: 25+15+8+5+2+2+12+8 = 77
  const semanaCompleta = { isDaily: false, sleep: 8, work: 4, expectedByNow: 4, steps: 12000,
    activeEnergy: 700, stand: 13, flights: 12, hrv: 60, hrvPrev: 50, rhr: 48 };

  test("la vista semanal no incluye los componentes que solo tienen sentido a diario", () => {
    // VO₂max, FC caminando, % grasa, luz y respiración se actualizan de forma
    // esporádica: promediarlos por semana no dice nada.
    const b = wellnessBreakdown({ ...semanaCompleta, vo2: 50, walkHr: 65, bodyFat: 11, daylight: 90, resp: 14 });
    expect(etiquetas(b).join()).not.toMatch(/VO₂max|caminando|Grasa|Luz|Resp/);
    expect(scoreFromBreakdown(b).max).toBe(77);
    // Con recuperación cardio son 5 más
    expect(scoreFromBreakdown(wellnessBreakdown({ ...semanaCompleta, cardioRec: 35 })).max).toBe(82);
  });

  test("la vista diaria sí los incluye cuando hay dato", () => {
    const b = wellnessBreakdown({ isDaily: true, sleep: 8, vo2: 50, walkHr: 65, bodyFat: 11, daylight: 90, resp: 14 });
    expect(fila(b, "VO₂max").pts).toBe(6);
    expect(fila(b, "caminando").pts).toBe(4);
    expect(fila(b, "Grasa").pts).toBe(4);
    expect(fila(b, "Luz").pts).toBe(5);
    expect(fila(b, "Resp").pts).toBe(5);
  });

  test("todo lo que suma aparece en el desglose", () => {
    // La regresión original: VO₂max y luz natural sumaban sin registrar su fila.
    const b = wellnessBreakdown({
      isDaily: true, sleep: 8, work: 1, steps: 12000, activeEnergy: 700, stand: 13,
      flights: 12, hrv: 60, hrvPrev: 50, rhr: 48, cardioRec: 35, vo2: 52,
      walkHr: 65, bodyFat: 10, daylight: 90, resp: 14,
    });
    const { pts, max, score } = scoreFromBreakdown(b);
    expect(pts).toBe(max);        // todo al máximo
    expect(score).toBe(100);
    expect(b.every(f => f.pts <= f.max)).toBe(true);
  });

  test("una métrica sin dato se marca y no entra en la fracción", () => {
    const b = wellnessBreakdown({ ...semanaCompleta, steps: null });
    expect(fila(b, "Pasos").sinDatos).toBe(true);
    expect(fila(b, "Sueño").sinDatos).toBe(false);
    // Sin sensor de pasos, sus 8 puntos salen del denominador en vez de contar como 0
    expect(scoreFromBreakdown(b).max).toBe(77 - 8);
    // ...y por eso no baja la puntuación: el resto sigue al máximo
    expect(scoreFromBreakdown(b).score).toBe(100);
  });

  test("el entreno semanal se escala por los días que ya han pasado", () => {
    // 2 de 2 días esperados = objetivo al día, aunque la semana pida 4 en total.
    const alDia = wellnessBreakdown({ isDaily: false, work: 2, expectedByNow: 2 });
    expect(fila(alDia, "Entreno").pts).toBe(15);
    // 2 de 4 esperados = va a medias
    const aMedias = wellnessBreakdown({ isDaily: false, work: 2, expectedByNow: 4 });
    expect(fila(aMedias, "Entreno").pts).toBe(7);
  });

  test("un día sin entreno puntúa algo si la recuperación es buena", () => {
    const conHrvAlta = wellnessBreakdown({ isDaily: true, work: 0, hrv: 75 });
    const conHrvBaja = wellnessBreakdown({ isDaily: true, work: 0, hrv: 40 });
    expect(fila(conHrvAlta, "Entreno").pts).toBe(3);
    expect(fila(conHrvBaja, "Entreno").pts).toBe(1);
    // Pero 30 min de ejercicio pesan más que descansar bien
    const conEjercicio = wellnessBreakdown({ isDaily: true, work: 0, exercise: 35, hrv: 75 });
    expect(fila(conEjercicio, "Entreno").pts).toBe(9);
  });

  test("la HRV se puntúa contra su referencia, no en absoluto", () => {
    expect(fila(wellnessBreakdown({ hrv: 60, hrvPrev: 50 }), "HRV").pts).toBe(12); // subiendo
    expect(fila(wellnessBreakdown({ hrv: 50, hrvPrev: 50 }), "HRV").pts).toBe(8);  // estable
    expect(fila(wellnessBreakdown({ hrv: 40, hrvPrev: 50 }), "HRV").pts).toBe(4);  // bajando
    expect(fila(wellnessBreakdown({ hrv: 50 }), "HRV").pts).toBe(6);               // sin referencia
  });

  test("sin ningún dato devuelve el desglose base todo a cero", () => {
    const b = wellnessBreakdown();
    expect(b.length).toBeGreaterThan(0);
    expect(b.every(f => f.pts === 0 || f.label.includes("Entreno"))).toBe(true);
    expect(scoreFromBreakdown(b).score).toBe(0);
  });
});

describe("correlaciones entre series", () => {
  const serie = (desde, valores) => valores.map((v, i) => ({
    date: new Date(Date.UTC(2026, 5, desde + i)).toISOString().slice(0, 10),
    value: v,
  }));

  test("pairByDate cruza por fecha e ignora lo que no casa", () => {
    const a = serie(1, [10, 20, 30]);
    const b = [{ date: "2026-06-02", value: 7 }, { date: "2026-06-09", value: 9 }];
    expect(pairByDate(a, b)).toEqual([{ date: "2026-06-02", x: 20, y: 7 }]);
  });

  test("pairByDate con desfase cruza el día D con el D+1", () => {
    // "lo que hago hoy, ¿cómo me afecta mañana?"
    const pasos = serie(1, [8000, 12000]);
    const sueno = serie(2, [7, 8]);
    expect(pairByDate(pasos, sueno, 1)).toEqual([
      { date: "2026-06-01", x: 8000,  y: 7 },
      { date: "2026-06-02", x: 12000, y: 8 },
    ]);
  });

  test("pairByDate cruza bien el cambio de mes", () => {
    const a = [{ date: "2026-06-30", value: 1 }];
    const b = [{ date: "2026-07-01", value: 2 }];
    expect(pairByDate(a, b, 1)).toEqual([{ date: "2026-06-30", x: 1, y: 2 }]);
  });

  test("splitCompare parte por la mediana y compara medias", () => {
    const pares = [
      { x: 1, y: 6 }, { x: 2, y: 6 }, { x: 3, y: 6 },
      { x: 8, y: 8 }, { x: 9, y: 8 }, { x: 10, y: 8 },
    ];
    const r = splitCompare(pares);
    expect(r.altoAvg).toBe(8);
    expect(r.bajoAvg).toBe(6);
    expect(r.deltaPct).toBeCloseTo(33.3, 1);
    expect(r.altoN).toBe(3);
    expect(r.bajoN).toBe(3);
  });

  test("splitCompare acepta un umbral fijo (entrené / no entrené)", () => {
    const pares = [
      { x: 0, y: 50 }, { x: 0, y: 52 }, { x: 0, y: 51 },
      { x: 1, y: 55 }, { x: 2, y: 57 }, { x: 1, y: 56 },
    ];
    const r = splitCompare(pares, { umbral: 0 });
    expect(r.bajoAvg).toBeCloseTo(51, 1);   // días de descanso
    expect(r.altoAvg).toBeCloseTo(56, 1);   // día después de entrenar
    expect(r.deltaPct).toBeGreaterThan(0);
  });

  test("splitCompare devuelve null sin muestras suficientes en ambos grupos", () => {
    // Con pocos datos la comparación es ruido, no señal.
    expect(splitCompare([{ x: 1, y: 1 }, { x: 9, y: 2 }])).toBe(null);
    const casiTodoAlto = [
      { x: 9, y: 1 }, { x: 9, y: 1 }, { x: 9, y: 1 },
      { x: 9, y: 1 }, { x: 9, y: 1 }, { x: 1, y: 2 },
    ];
    expect(splitCompare(casiTodoAlto)).toBe(null);
    expect(splitCompare([])).toBe(null);
    expect(splitCompare(null)).toBe(null);
  });

  test("healthConclusions saca el patrón de pasos ↔ sueño", () => {
    const dia = n => new Date(Date.UTC(2026, 5, n)).toISOString().slice(0, 10);
    const step_count = [], sleep_analysis = [];
    for (let i = 0; i < 8; i++) {
      const muchos = i % 2 === 0;
      step_count.push({ date: dia(1 + i), value: muchos ? 14000 : 3000 });
      // La noche siguiente duerme más cuando ha andado mucho
      sleep_analysis.push({ date: dia(2 + i), value: muchos ? 8.2 : 6.4, extra: {} });
    }
    const c = healthConclusions({ step_count, sleep_analysis }, new Date("2026-06-09T12:00:00Z"));
    const patron = c.find(x => x.domain === "Patrón" && x.text.includes("pasos"));
    expect(patron).toBeTruthy();
    expect(patron.text).toMatch(/duermes/);
  });

  // Fecha ISO del día n de junio de 2026, para construir series legibles.
  const dia = n => new Date(Date.UTC(2026, 5, n)).toISOString().slice(0, 10);
  const AHORA = new Date("2026-06-11T12:00:00Z");

  test("healthConclusions cruza minutos de ejercicio ↔ sueño profundo de esa noche", () => {
    const apple_exercise_time = [], sleep_analysis = [];
    for (let i = 0; i < 8; i++) {
      const duro = i % 2 === 0;
      apple_exercise_time.push({ date: dia(1 + i), value: duro ? 65 : 5 });
      // La noche siguiente hay más sueño profundo cuando ese día se ha entrenado fuerte
      sleep_analysis.push({ date: dia(2 + i), value: 7.5, extra: { deep: duro ? 1.8 : 0.7 } });
    }
    const c = healthConclusions({ apple_exercise_time, sleep_analysis }, AHORA);
    const patron = c.find(x => x.domain === "Patrón" && x.text.includes("sueño profundo"));
    expect(patron).toBeTruthy();
    expect(patron.tone).toBe("good");
    expect(patron.text).toMatch(/min de ejercicio/);
  });

  test("healthConclusions cruza pasos ↔ FC en reposo del día siguiente", () => {
    const step_count = [], resting_heart_rate = [];
    for (let i = 0; i < 8; i++) {
      const muchos = i % 2 === 0;
      step_count.push({ date: dia(1 + i), value: muchos ? 18000 : 2500 });
      // Andar mucho deja la FC en reposo más alta al día siguiente
      resting_heart_rate.push({ date: dia(2 + i), value: muchos ? 62 : 54 });
    }
    const c = healthConclusions({ step_count, resting_heart_rate }, AHORA);
    const patron = c.find(x => x.domain === "Patrón" && x.text.includes("FC en reposo"));
    expect(patron).toBeTruthy();
    expect(patron.text).toMatch(/sube/);
    expect(patron.tone).toBe("info");
  });

  test("healthConclusions cruza luz natural ↔ HRV de esa noche", () => {
    const time_in_daylight = [], heart_rate_variability = [];
    for (let i = 0; i < 8; i++) {
      const sol = i % 2 === 0;
      time_in_daylight.push({ date: dia(1 + i), value: sol ? 120 : 8 });
      heart_rate_variability.push({ date: dia(2 + i), value: sol ? 78 : 52 });
    }
    const c = healthConclusions({ time_in_daylight, heart_rate_variability }, AHORA);
    const patron = c.find(x => x.domain === "Patrón" && x.text.includes("luz natural"));
    expect(patron).toBeTruthy();
    expect(patron.tone).toBe("good");
    expect(patron.text).toMatch(/HRV nocturna/);
  });

  test("wellnessHistory: un día por fecha con datos, siempre normalizado a 100", () => {
    const sleep_analysis = [], step_count = [];
    for (let i = 1; i <= 5; i++) {
      sleep_analysis.push({ date: dia(i), value: 7.5, extra: {} });
      step_count.push({ date: dia(i), value: 11000 });
    }
    const h = wellnessHistory({ sleep_analysis, step_count });
    expect(h.map(d => d.date)).toEqual([dia(1), dia(2), dia(3), dia(4), dia(5)]);
    expect(h.every(d => d.value >= 0 && d.value <= 100)).toBe(true);
  });

  test("wellnessHistory: refleja la mejora del mes en la tendencia", () => {
    const sleep_analysis = [], step_count = [];
    for (let i = 1; i <= 20; i++) {
      sleep_analysis.push({ date: dia(i), value: 5.5 + i * 0.12, extra: {} });
      step_count.push({ date: dia(i), value: 4000 + i * 400 });
    }
    const h = wellnessHistory({ sleep_analysis, step_count });
    expect(h[h.length - 1].value).toBeGreaterThan(h[0].value);
    expect(seriesTrend(h, 7, 30).deltaPct).toBeGreaterThan(0);
  });

  test("wellnessHistory: se salta los días sin nada que puntuar y respeta noches anuladas", () => {
    const h = wellnessHistory({
      sleep_analysis: [
        { date: dia(1), value: 8, extra: {} },
        { date: dia(2), value: 8, extra: { excluded: true } },   // anulada a mano
      ],
      // dia(3) solo tiene una métrica que no cuenta como "hay algo que puntuar"
      flights_climbed: [{ date: dia(3), value: 12 }],
    });
    expect(h.map(d => d.date)).toEqual([dia(1)]);
  });

  test("wellnessHistory: las métricas esporádicas arrastran su último valor conocido", () => {
    const base = {
      sleep_analysis: [1, 2, 3].map(i => ({ date: dia(i), value: 7.5, extra: {} })),
      step_count:     [1, 2, 3].map(i => ({ date: dia(i), value: 11000 })),
    };
    const sinVo2 = wellnessHistory(base);
    // Un VO2max excelente medido el día 1 debe seguir puntuando los días 2 y 3
    const conVo2 = wellnessHistory({ ...base, vo2_max: [{ date: dia(1), value: 55 }] });
    expect(conVo2).toHaveLength(3);
    expect(conVo2[2].value).not.toBe(sinVo2[2].value);
  });

  test("wellnessHistory: sin datos devuelve lista vacía y recorta a `dias`", () => {
    expect(wellnessHistory({})).toEqual([]);
    expect(wellnessHistory(null)).toEqual([]);
    const sleep_analysis = [], step_count = [];
    for (let i = 1; i <= 12; i++) {
      sleep_analysis.push({ date: dia(i), value: 7, extra: {} });
      step_count.push({ date: dia(i), value: 9000 });
    }
    expect(wellnessHistory({ sleep_analysis, step_count }, { dias: 5 })).toHaveLength(5);
  });

  test("los cruces nuevos callan si no hay muestras suficientes en ambos grupos", () => {
    // Dos días no dan para partir en dos grupos de 3 (mínimo de splitCompare)
    const c = healthConclusions({
      apple_exercise_time:      [{ date: dia(1), value: 60 }, { date: dia(2), value: 5 }],
      time_in_daylight:         [{ date: dia(1), value: 90 }, { date: dia(2), value: 4 }],
      step_count:               [{ date: dia(1), value: 15000 }, { date: dia(2), value: 2000 }],
      resting_heart_rate:       [{ date: dia(2), value: 60 }, { date: dia(3), value: 55 }],
      heart_rate_variability:   [{ date: dia(2), value: 70 }, { date: dia(3), value: 50 }],
      sleep_analysis:           [{ date: dia(2), value: 7.5, extra: { deep: 1.2 } }],
    }, AHORA);
    expect(c.filter(x => x.domain === "Patrón")).toEqual([]);
  });
});
