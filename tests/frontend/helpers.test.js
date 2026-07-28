import { describe, test, expect, vi, afterEach } from "vitest";
import {
  isToday, isFuture, isPast, isActive, daysUntil, formatTime, formatUpcomingTime,
  urgencyColor, formatShortDate, isoToDdMmYyyy,
  hoursToHM, sleepScore, calcRecoveryMod, findMetric, weatherFromCode, weekdayShort,
  seriesTrend, trendDirection, bedtimeHrvInsight,
  healthConclusions, healthOverall, scoreFromBreakdown,
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
    // 8h, 18% profundo, 22% REM, resto core, 0 despierto, acostado a las 23h
    const score = sleepScore(8, 1.44, 1.76, 4.8, 0, "23:00");
    expect(score).toBe(100);
  });

  test("sleepScore: cap por duración", () => {
    // 7h no puede superar 68 aunque las fases sean perfectas
    const score = sleepScore(7, 1.26, 1.54, 4.2, 0, "23:00");
    expect(score).toBeLessThanOrEqual(68);
    // 6h queda capado a 52
    const short = sleepScore(6, 1.08, 1.32, 3.6, 0, "23:00");
    expect(short).toBeLessThanOrEqual(52);
  });

  test("sleepScore: penaliza acostarse tarde", () => {
    const early = sleepScore(8, 1.44, 1.76, 4.8, 0, "23:00");
    const late  = sleepScore(8, 1.44, 1.76, 4.8, 0, "03:00");
    expect(late).toBeLessThan(early);
    expect(early - late).toBe(15);
  });

  test("sleepScore: nunca es negativo y aplica recoveryMod", () => {
    const bad = sleepScore(1, 0, 0, 0, 0.5, "04:00", -20);
    expect(bad).toBeGreaterThanOrEqual(0);
    const base = sleepScore(8, 1.44, 1.76, 4.8, 0, "22:00", 0);
    const modded = sleepScore(8, 1.44, 1.76, 4.8, 0, "22:00", -10);
    expect(base - modded).toBe(10);
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
