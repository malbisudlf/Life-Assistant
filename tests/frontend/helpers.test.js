import { describe, test, expect, vi, afterEach } from "vitest";
import {
  isToday, isFuture, isPast, isActive, daysUntil, formatTime, formatUpcomingTime,
  urgencyColor, formatShortDate, isoToDdMmYyyy, formatLogTime,
  hoursToHM, sleepScore, sleepBreakdown, sleepHours, calcRecoveryMod, findMetric,
  weatherFromCode, weekdayShort,
  seriesTrend, trendDirection, bedtimeHrvInsight, pairByDate, splitCompare,
  healthConclusions, healthOverall, healthCorrelations, healthCoverageDays,
  wellnessBreakdown, scoreFromBreakdown, wellnessHistory,
  relojPuesto, relojCobertura, relojRachaSinReloj,
  formatMoney, clothingTotals, hostStreaming,
  jarvisHistorial, jarvisEtiquetaAccion, jarvisMotivoError, JARVIS_MAX_HISTORIAL,
  elegirVozEspanola, textoHablable, esFinDeLlamada,
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

  test("seriesTrend mide por fecha real, no por número de registros", () => {
    // Un mes sin llevar el reloj deja la serie agujereada: `slice(-30)` alcanzaba
    // hasta junio y la "media de 30 días" acababa comparando julio contra junio.
    const data = [
      ...Array.from({ length: 23 }, (_, i) => ({ date: `2026-06-${String(i + 1).padStart(2, "0")}`, value: 40 })),
      ...Array.from({ length: 7 },  (_, i) => ({ date: `2026-07-${String(i + 25).padStart(2, "0")}`, value: 50 })),
    ];
    const t = seriesTrend(data, 7, 30, { hoy: "2026-07-31" });
    expect(t.nCorto).toBe(7);
    expect(t.nLargo).toBe(7);      // junio queda fuera de los 30 días reales
    expect(t.avgLong).toBe(50);
    expect(t.deltaPct).toBe(0);    // antes salía un +18% que no existía
  });

  test("seriesTrend no inventa tendencia si no hay nada reciente", () => {
    const vieja = [{ date: "2026-06-01", value: 40 }, { date: "2026-06-02", value: 60 }];
    expect(seriesTrend(vieja, 7, 30, { hoy: "2026-08-16" })).toBe(null);
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

  // Las ventanas van por fecha real, así que `now` tiene que caer donde caen los datos:
  // una serie de hace dos meses NO es "los últimos 7 días" y ya no se cuenta como tal.
  const AHORA = new Date("2026-07-07T12:00:00");
  const julio = (n, v) => Array.from({ length: n }, (_, i) => ({
    date: `2026-07-${String(i + 1).padStart(2, "0")}`,
    value: typeof v === "function" ? v(i) : v,
  }));

  test("HRV cayendo genera una conclusión roja de fatiga", () => {
    // 23 días a 60ms y 7 a 45ms → media 7d muy por debajo de la de 30d
    const hrv = [...serie(23, 60), ...julio(7, 45)];
    const c = healthConclusions({ heart_rate_variability: hrv }, AHORA);
    const rec = c.find(x => x.domain === "Recuperación" && x.tone === "bad");
    expect(rec).toBeTruthy();
    expect(rec.text).toMatch(/HRV/);
  });

  test("sueño corto es conclusión roja; sueño bueno es verde", () => {
    const ahora = new Date("2026-06-07T12:00:00");
    const corto = healthConclusions({ sleep_analysis: serie(7, 5.5) }, ahora);
    expect(corto.find(x => x.domain === "Sueño").tone).toBe("bad");
    const bueno = healthConclusions({ sleep_analysis: serie(7, 8) }, ahora);
    expect(bueno.find(x => x.domain === "Sueño").tone).toBe("good");
  });

  test("una serie vieja no se cuenta como 'las últimas 7 noches'", () => {
    // El bug del correo, un piso más arriba: `slice(-7)` daba las últimas 7 MEDIDAS,
    // aunque fueran de hace dos meses, y la frase las presentaba como de esta semana.
    const c = healthConclusions({ sleep_analysis: serie(7, 5.5) }, new Date("2026-08-16T12:00:00"));
    expect(c.find(x => x.domain === "Sueño")).toBeUndefined();
  });

  test("con pocas noches medidas se dice sobre qué se apoya, sin afirmar tendencia", () => {
    const c = healthConclusions({
      heart_rate_variability: [
        ...serie(20, 60),                                   // junio, fuera de ventana
        { date: "2026-07-06", value: 40 }, { date: "2026-07-07", value: 42 },
      ],
    }, AHORA);
    const rec = c.find(x => x.domain === "Recuperación");
    expect(rec.text).toMatch(/2 noches medidas/);
    expect(rec.text).toMatch(/sin base para hablar de tendencia/);
    expect(rec.tone).toBe("info");
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
      heart_rate_variability: [...serie(23, 60), ...julio(7, 45)],
      step_count: julio(7, 12000), // good
    }, AHORA);
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

describe("uso del reloj", () => {
  // `reloj` es lo que manda /health/metrics: fecha → estado.
  const HOY = "2026-08-16";
  const dias = pares => ({ dias: Object.fromEntries(pares) });
  const menos = n => new Date(`${HOY}T12:00:00Z`).getTime() - n * 86400000;
  const d = n => new Date(menos(n)).toISOString().slice(0, 10);

  test("relojPuesto distingue los tres estados y el día de la noche", () => {
    expect(relojPuesto("ambos")).toBe(true);
    expect(relojPuesto("dia", "noche")).toBe(false);
    expect(relojPuesto("noche", "noche")).toBe(true);
    expect(relojPuesto("sin_reloj")).toBe(false);
    expect(relojPuesto("sin_datos")).toBe(false);
    expect(relojPuesto(undefined)).toBe(false);
  });

  test("relojCobertura cuenta días, noches y los días de los que no se sabe nada", () => {
    const reloj = dias([
      [d(0), "ambos"], [d(1), "dia"], [d(2), "sin_reloj"], [d(3), "sin_datos"],
      [d(4), "noche"], [d(5), "sin_reloj"],
      // d(6) no aparece: no llegó nada, que es lo mismo que "sin_datos"
    ]);
    const c = relojCobertura(reloj, { dias: 7, hoy: HOY });
    expect(c.dia).toBe(2);          // ambos + dia
    expect(c.noche).toBe(2);        // ambos + noche
    expect(c.sinReloj).toBe(2);
    expect(c.sinDatos).toBe(2);     // el declarado y el que falta
    expect(c.ultimaNoche).toBe(d(0));
  });

  test("un día sin datos de nada no cuenta como día sin reloj", () => {
    const c = relojCobertura(dias([[d(0), "sin_datos"]]), { dias: 3, hoy: HOY });
    expect(c.sinReloj).toBe(0);
    expect(c.sinDatos).toBe(3);
    expect(c.hay).toBe(false);
  });

  test("la racha sin reloj no cuenta hoy y los huecos no la rompen", () => {
    // Hoy sin señal (la jornada está a medias), ayer y anteayer sin reloj, con un día
    // sin datos por medio, y hace cuatro días sí lo llevaba.
    const reloj = dias([
      [d(0), "sin_reloj"], [d(1), "sin_reloj"], [d(2), "sin_datos"],
      [d(3), "sin_reloj"], [d(4), "ambos"],
    ]);
    expect(relojRachaSinReloj(reloj, { hoy: HOY })).toBe(2);
  });

  test("con el reloj puesto ayer no hay racha", () => {
    expect(relojRachaSinReloj(dias([[d(1), "noche"]]), { hoy: HOY })).toBe(0);
  });
});

describe("conclusiones conscientes del reloj", () => {
  const HOY = "2026-07-07";
  const AHORA = new Date(`${HOY}T12:00:00`);
  const d = n => new Date(new Date(`${HOY}T12:00:00Z`).getTime() - n * 86400000)
    .toISOString().slice(0, 10);
  const reloj = pares => ({ dias: Object.fromEntries(pares) });

  test("dice cuántas noches de la semana se pudo medir", () => {
    const c = healthConclusions({}, AHORA, {
      reloj: reloj([...Array(7)].map((_, i) => [d(i), i < 2 ? "ambos" : "sin_reloj"])),
    });
    const r = c.find(x => x.domain === "Reloj");
    expect(r.text).toMatch(/Llevaste el reloj 2 de las 7 noches/);
  });

  test("avisa de la racha sin ponérselo", () => {
    const c = healthConclusions({}, AHORA, {
      reloj: reloj([...Array(7)].map((_, i) => [d(i), "sin_reloj"])),
    });
    expect(c.some(x => x.domain === "Reloj" && /días seguidos sin ponerte/.test(x.text))).toBe(true);
    expect(c.some(x => x.domain === "Reloj" && /Sin rastro del reloj/.test(x.text))).toBe(true);
  });

  test("los días sin datos de nada se avisan aparte, no como días sin reloj", () => {
    const c = healthConclusions({}, AHORA, {
      reloj: reloj([[d(0), "ambos"], [d(1), "ambos"], [d(2), "ambos"],
                    [d(3), "ambos"], [d(4), "ambos"]]),   // d(5) y d(6) no llegaron
    });
    const avisos = c.filter(x => x.domain === "Reloj");
    expect(avisos.some(x => /no llegó ningún dato/.test(x.text))).toBe(true);
    expect(avisos.some(x => /sin ponerte el reloj/.test(x.text))).toBe(false);
  });

  test("con el reloj puesto toda la semana no dice nada del reloj", () => {
    const c = healthConclusions({}, AHORA, {
      reloj: reloj([...Array(7)].map((_, i) => [d(i), "ambos"])),
    });
    expect(c.some(x => x.domain === "Reloj")).toBe(false);
  });

  test("sin sección de reloj (backend viejo) las conclusiones siguen saliendo", () => {
    const c = healthConclusions({ step_count: [{ date: HOY, value: 12000 }] }, AHORA);
    expect(c.some(x => x.domain === "Actividad")).toBe(true);
    expect(c.some(x => x.domain === "Reloj")).toBe(false);
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

// ── Streaming PC ────────────────────────────────────────────────

describe("hostStreaming", () => {
  test("saca la IP del mensaje del stage vpn_ready", () => {
    const eventos = [
      { stage: "job_claimed", message: "Worker pc-mikel-ab12 reclamó el job" },
      { stage: "vpn_ready", message: "VPN conectada — Moonlight: 100.87.12.4" },
      { stage: "streaming_ready", message: "Sunshine abierto" },
    ];
    expect(hostStreaming(eventos)).toBe("100.87.12.4");
  });

  test("se queda con el vpn_ready más reciente", () => {
    const eventos = [
      { stage: "vpn_ready", message: "VPN conectada — Moonlight: 100.87.12.4" },
      { stage: "vpn_ready", message: "VPN conectada — Moonlight: 100.64.0.9" },
    ];
    expect(hostStreaming(eventos)).toBe("100.64.0.9");
  });

  test("sin vpn_ready no hay IP que enseñar", () => {
    expect(hostStreaming([{ stage: "vpn_error", message: "La VPN no llegó a conectar" }])).toBe(null);
    expect(hostStreaming([{ stage: "vpn_ready", message: "VPN conectada" }])).toBe(null);
    expect(hostStreaming([])).toBe(null);
    expect(hostStreaming(null)).toBe(null);
  });

  test("ignora números con forma de IP pero octetos fuera de rango", () => {
    expect(hostStreaming([{ stage: "vpn_ready", message: "versión 1.999.12.4" }])).toBe(null);
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
    expect(scoreFromBreakdown(b)).toMatchObject({ pts: 35, max: 45, score: 78 });
    // Todo medido: la cobertura es completa.
    expect(scoreFromBreakdown(b).cobertura).toBe(1);
  });

  test("las métricas sin dato no cuentan ni arriba ni abajo", () => {
    // No tener sensor de pisos no debe penalizar la puntuación.
    const conPisos = [
      { label: "Sueño", pts: 25, max: 25 },
      { label: "Pisos", pts: 0,  max: 2, sinDatos: true },
    ];
    expect(scoreFromBreakdown(conPisos)).toMatchObject({ pts: 25, max: 25, score: 100 });
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
    expect(scoreFromBreakdown(b)).toMatchObject({ pts: 5, max: 20, score: 25 });
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
    // `hoy` anclado al final de la serie: las ventanas de seriesTrend van por fecha real.
    expect(seriesTrend(h, 7, 30, { hoy: dia(20) }).deltaPct).toBeGreaterThan(0);
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

  test("wellnessHistory: cada día dice con qué se midió", () => {
    // Dos días idénticos en pasos y sueño, pero el segundo sin reloj: el score se
    // parece y lo que cambia es sobre cuánto se ha calculado.
    const h = wellnessHistory({
      sleep_analysis: [{ date: dia(1), value: 7.5, extra: {} }, { date: dia(2), value: 7.5, extra: {} }],
      step_count:     [{ date: dia(1), value: 11000 }, { date: dia(2), value: 11000 }],
      heart_rate_variability: [{ date: dia(1), value: 55 }],
    }, { reloj: { dias: { [dia(1)]: "ambos", [dia(2)]: "sin_reloj" } } });
    expect(h[0].sinReloj).toBe(false);
    expect(h[1].sinReloj).toBe(true);
    expect(h[1].cobertura).toBeLessThan(h[0].cobertura);
    expect(h[1].sinDatos).toBeGreaterThan(h[0].sinDatos);
  });

  test("wellnessHistory: sin datos de reloj no se inventa el estado", () => {
    const h = wellnessHistory({
      sleep_analysis: [{ date: dia(1), value: 7.5, extra: {} }],
      step_count:     [{ date: dia(1), value: 11000 }],
    });
    expect(h[0].estadoReloj).toBe(null);
    expect(h[0].sinReloj).toBe(false);
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

// ── Correlaciones sobre ventana larga (idea 14) ────────────────────────────────
// Mismo motor que alimenta los patrones de healthConclusions, pero pensado para
// correr sobre meses de datos y no sobre 30 días. Lo que se prueba aquí es que la
// exigencia de muestra escala: con minPorGrupo alto, un patrón sostenido por pocos
// días deja de contarse.
describe("healthCorrelations", () => {
  const d = n => new Date(Date.UTC(2026, 0, n)).toISOString().slice(0, 10);

  // Construye n días alternando "mucho / poco" en la causa, con el efecto al día
  // siguiente correlacionado.
  function series(n, { causaAlta, causaBaja, efectoAlto, efectoBajo }) {
    const causa = [], efecto = [];
    for (let i = 0; i < n; i++) {
      const alto = i % 2 === 0;
      causa.push({ date: d(1 + i), value: alto ? causaAlta : causaBaja });
      efecto.push({ date: d(2 + i), value: alto ? efectoAlto : efectoBajo });
    }
    return { causa, efecto };
  }

  test("saca el patrón de pasos ↔ sueño con muestra suficiente", () => {
    const { causa, efecto } = series(40, {
      causaAlta: 14000, causaBaja: 3000, efectoAlto: 8.2, efectoBajo: 6.4,
    });
    const r = healthCorrelations(
      { step_count: causa, sleep_analysis: efecto.map(x => ({ ...x, extra: {} })) },
      { minPorGrupo: 10 },
    );
    const p = r.find(x => x.id === "pasos_sueno");
    expect(p).toBeTruthy();
    expect(p.n).toBeGreaterThanOrEqual(20);
    expect(p.text).toMatch(/duermes/);
  });

  test("con minPorGrupo alto, un patrón de pocos días deja de contarse", () => {
    // 8 días dan 4 y 4: suficiente para el mínimo de 3, insuficiente para 10.
    const { causa, efecto } = series(8, {
      causaAlta: 14000, causaBaja: 3000, efectoAlto: 8.2, efectoBajo: 6.4,
    });
    const datos = { step_count: causa, sleep_analysis: efecto.map(x => ({ ...x, extra: {} })) };
    expect(healthCorrelations(datos, { minPorGrupo: 3 }).some(x => x.id === "pasos_sueno")).toBe(true);
    expect(healthCorrelations(datos, { minPorGrupo: 10 }).some(x => x.id === "pasos_sueno")).toBe(false);
  });

  test("ordena por fuerza del efecto, no por orden del catálogo", () => {
    // Dos cruces a la vez: luz↔HRV con un efecto enorme y pasos↔FC con uno pequeño.
    const luz = [], hrv = [], pasos = [], rhr = [];
    for (let i = 0; i < 40; i++) {
      const alto = i % 2 === 0;
      luz.push({ date: d(1 + i), value: alto ? 150 : 5 });
      hrv.push({ date: d(2 + i), value: alto ? 90 : 45 });        // +100%
      pasos.push({ date: d(1 + i), value: alto ? 12000 : 4000 });
      rhr.push({ date: d(2 + i), value: alto ? 58 : 55 });        // ~+5%
    }
    const r = healthCorrelations(
      { time_in_daylight: luz, heart_rate_variability: hrv, step_count: pasos, resting_heart_rate: rhr },
      { minPorGrupo: 10 },
    );
    const ids = r.map(x => x.id);
    expect(ids.indexOf("luz_hrv")).toBeLessThan(ids.indexOf("pasos_rhr"));
    expect(Math.abs(r[0].deltaPct)).toBeGreaterThanOrEqual(Math.abs(r[r.length - 1].deltaPct));
  });

  test("cruza las horas fuera de casa (Home Assistant) con el sueño", () => {
    // Única serie que no viene del Watch: la manda HA. `value` son las horas EN CASA
    // y extra.fuera las de fuera; el cruce mira las de fuera.
    const presencia = [], sueno = [];
    for (let i = 0; i < 40; i++) {
      const fuera = i % 2 === 0 ? 12 : 2;
      presencia.push({ date: d(1 + i), value: 24 - fuera, extra: { fuera } });
      sueno.push({ date: d(2 + i), value: fuera === 12 ? 6.2 : 8.0, extra: {} });
    }
    const r = healthCorrelations(
      { time_at_home: presencia, sleep_analysis: sueno },
      { minPorGrupo: 10 },
    );
    const p = r.find(x => x.id === "fuera_sueno");
    expect(p).toBeTruthy();
    expect(p.text).toMatch(/fuera de casa/);
    expect(p.deltaPct).toBeLessThan(0);   // más horas fuera → menos sueño
  });

  test("los días sin cobertura de presencia no entran en el cruce", () => {
    // HA caído media jornada deja el día con pocas horas en las DOS columnas. Sin el
    // filtro de cobertura se colaría como "día tranquilo en casa", que es lo contrario
    // de lo que dice el dato: el dato no dice nada.
    const presencia = [], sueno = [];
    for (let i = 0; i < 40; i++) {
      const fuera = i % 2 === 0 ? 12 : 2;
      presencia.push({ date: d(1 + i), value: 1, extra: { fuera } });   // cobertura ≪ 16 h
      sueno.push({ date: d(2 + i), value: fuera === 12 ? 6.2 : 8.0, extra: {} });
    }
    const r = healthCorrelations(
      { time_at_home: presencia, sleep_analysis: sueno },
      { minPorGrupo: 10 },
    );
    expect(r.some(x => x.id === "fuera_sueno")).toBe(false);
  });

  test("descarta los efectos por debajo del umbral de cada cruce", () => {
    // Diferencia de sueño mínima (7.0 vs 7.05): no llega al 5% que exige el cruce.
    const { causa, efecto } = series(40, {
      causaAlta: 14000, causaBaja: 3000, efectoAlto: 7.05, efectoBajo: 7.0,
    });
    const r = healthCorrelations(
      { step_count: causa, sleep_analysis: efecto.map(x => ({ ...x, extra: {} })) },
      { minPorGrupo: 10 },
    );
    expect(r.some(x => x.id === "pasos_sueno")).toBe(false);
  });

  test("cruza sueño ↔ HRV del día siguiente", () => {
    const { causa, efecto } = series(40, {
      causaAlta: 8.5, causaBaja: 5.5, efectoAlto: 72, efectoBajo: 48,
    });
    const r = healthCorrelations(
      { sleep_analysis: causa.map(x => ({ ...x, extra: {} })), heart_rate_variability: efecto },
      { minPorGrupo: 10 },
    );
    const p = r.find(x => x.id === "sueno_hrv");
    expect(p).toBeTruthy();
    expect(p.text).toMatch(/HRV del día siguiente/);
  });

  test("sin datos devuelve lista vacía en vez de reventar", () => {
    expect(healthCorrelations({})).toEqual([]);
    expect(healthCorrelations(null)).toEqual([]);
  });
});

describe("healthCoverageDays", () => {
  test("cuenta días distintos, no filas", () => {
    const datos = {
      // La misma fecha en dos series cuenta una sola vez
      step_count:     [{ date: "2026-01-01", value: 1 }, { date: "2026-01-02", value: 2 }],
      sleep_analysis: [{ date: "2026-01-02", value: 7 }, { date: "2026-01-03", value: 8 }],
    };
    expect(healthCoverageDays(datos)).toBe(3);
  });

  test("sin datos devuelve 0", () => {
    expect(healthCoverageDays(null)).toBe(0);
    expect(healthCoverageDays({})).toBe(0);
  });
});

// ── Jarvis ───────────────────────────────────────────────────────

describe("jarvisHistorial", () => {
  test("solo manda turnos de la conversación", () => {
    const out = jarvisHistorial([
      { rol: "user", texto: "hola" },
      { rol: "aviso", texto: "Error de conexión" },
      { rol: "assistant", texto: "buenas" },
    ]);
    expect(out).toEqual([
      { rol: "user", texto: "hola" },
      { rol: "assistant", texto: "buenas" },
    ]);
  });

  test("descarta los mensajes vacíos", () => {
    expect(jarvisHistorial([{ rol: "user", texto: "   " }])).toEqual([]);
  });

  test("se queda con los últimos y respeta el tope", () => {
    const muchos = Array.from({ length: 30 }, (_, i) => ({ rol: "user", texto: `m${i}` }));
    const out = jarvisHistorial(muchos);
    expect(out).toHaveLength(JARVIS_MAX_HISTORIAL);
    expect(out[out.length - 1].texto).toBe("m29");
  });

  test("no revienta sin datos", () => {
    expect(jarvisHistorial(undefined)).toEqual([]);
    expect(jarvisHistorial([null])).toEqual([]);
  });

  test("no arrastra campos de más al backend", () => {
    const out = jarvisHistorial([{ rol: "assistant", texto: "ok", herramientas: ["clima"] }]);
    expect(out[0]).toEqual({ rol: "assistant", texto: "ok" });
  });
});

describe("jarvisEtiquetaAccion", () => {
  test("describe el evento con fecha en formato local", () => {
    expect(jarvisEtiquetaAccion({
      herramienta: "crear_evento",
      argumentos: { titulo: "Dentista", fecha: "2026-09-01", hora_inicio: "10:00" },
    })).toBe('Crear "Dentista" el 01/09/2026 a las 10:00');
  });

  test("sin hora se marca como todo el día", () => {
    expect(jarvisEtiquetaAccion({
      herramienta: "crear_evento",
      argumentos: { titulo: "Vacaciones", fecha: "2026-09-01" },
    })).toBe('Crear "Vacaciones" el 01/09/2026 (todo el día)');
  });

  test("incluye el lugar si lo hay", () => {
    expect(jarvisEtiquetaAccion({
      herramienta: "crear_evento",
      argumentos: { titulo: "Café", fecha: "2026-09-01", hora_inicio: "17:30", lugar: "Bilbao" },
    })).toContain("en Bilbao");
  });

  test("ignora fechas y horas con formato inválido", () => {
    const out = jarvisEtiquetaAccion({
      herramienta: "crear_evento",
      argumentos: { titulo: "X", fecha: "mañana", hora_inicio: "por la tarde" },
    });
    expect(out).toBe('Crear "X" (todo el día)');
  });

  test("sin título no hay nada que confirmar", () => {
    expect(jarvisEtiquetaAccion({ herramienta: "crear_evento", argumentos: { fecha: "2026-09-01" } })).toBeNull();
  });

  test("devuelve null si no hay acción pendiente", () => {
    expect(jarvisEtiquetaAccion(null)).toBeNull();
    expect(jarvisEtiquetaAccion({ herramienta: "apagar_pc", argumentos: {} })).toBeNull();
  });

  test("una llamada MCP enseña servidor, herramienta y argumentos reales", () => {
    // El usuario aprueba lo que va a viajar de verdad, no lo que el modelo redactó.
    expect(jarvisEtiquetaAccion({
      herramienta: "mcp_usar",
      argumentos: { servidor: "correo", herramienta: "enviar", argumentos: { para: "x@y.z" } },
    })).toBe('Ejecutar "enviar" en el servidor correo con {"para":"x@y.z"}');
  });

  test("una llamada MCP sin argumentos no arrastra un {} vacío", () => {
    expect(jarvisEtiquetaAccion({
      herramienta: "mcp_usar",
      argumentos: { servidor: "correo", herramienta: "listar" },
    })).toBe('Ejecutar "listar" en el servidor correo');
  });

  test("una llamada MCP incompleta no pinta botón", () => {
    expect(jarvisEtiquetaAccion({ herramienta: "mcp_usar", argumentos: { servidor: "correo" } })).toBeNull();
    expect(jarvisEtiquetaAccion({ herramienta: "mcp_usar", argumentos: {} })).toBeNull();
  });
});

describe("voz de Jarvis", () => {
  test("elegirVozEspanola prefiere es-ES y las voces Natural", () => {
    const voces = [
      { name: "Google US English", lang: "en-US" },
      { name: "Paulina", lang: "es-MX", localService: true },
      { name: "Microsoft Elvira Online (Natural)", lang: "es-ES", localService: false },
      { name: "Monica", lang: "es-ES", localService: true },
    ];
    expect(elegirVozEspanola(voces).name).toBe("Microsoft Elvira Online (Natural)");
  });

  test("elegirVozEspanola cae a cualquier variante de español", () => {
    const voces = [
      { name: "Google US English", lang: "en-US" },
      { name: "Paulina", lang: "es-MX" },
    ];
    expect(elegirVozEspanola(voces).name).toBe("Paulina");
  });

  test("elegirVozEspanola devuelve null si no hay español", () => {
    expect(elegirVozEspanola([{ name: "X", lang: "en-GB" }])).toBeNull();
    expect(elegirVozEspanola([])).toBeNull();
    expect(elegirVozEspanola(null)).toBeNull();
  });

  test("textoHablable quita URLs y adornos: deletrearlos es insufrible", () => {
    expect(textoHablable("Míralo en https://example.com/a?b=1 — es **importante**"))
      .toBe("Míralo en (enlace) — es importante");
  });

  test("textoHablable acota la longitud", () => {
    expect(textoHablable("palabra ".repeat(200)).length).toBeLessThanOrEqual(600);
  });
});

describe("jarvisMotivoError", () => {
  test("un 404 apunta al despliegue, no a la red", () => {
    expect(jarvisMotivoError(404)).toContain("fly deploy");
  });

  test("sin conexión se distingue de un error del backend", () => {
    expect(jarvisMotivoError(0)).toContain("conectar");
  });

  test("un 503 enseña el detalle del backend", () => {
    expect(jarvisMotivoError(503, "falta OPENAI_API_KEY")).toBe("falta OPENAI_API_KEY");
  });

  test("un 503 sin detalle sigue diciendo algo útil", () => {
    expect(jarvisMotivoError(503)).toContain("OPENAI_API_KEY");
  });

  test("el 429 invita a esperar, que es lo único que arregla un rate limit", () => {
    expect(jarvisMotivoError(429)).toContain("Espera");
  });

  test("los 5xx mandan al registro", () => {
    expect(jarvisMotivoError(500)).toContain("registro");
    expect(jarvisMotivoError(502)).toContain("502");
  });

  test("un código desconocido no se queda mudo", () => {
    expect(jarvisMotivoError(418)).toContain("418");
  });
});

describe("jarvisEtiquetaAccion — lo que se aprueba con un botón", () => {
  const contexto = {
    eventos: [{ id: "ev1", title: "Entrega de Sistemas" }],
    ideas:   [{ id: "id1", key: "Llamar al dentista" }],
  };

  test("un evento se nombra por su título real, no por su id", () => {
    // El id de Graph es ilegible: sin traducirlo, confirmar sería aprobar a ciegas. Y el
    // nombre no puede venir del modelo, que es justo de quien hay que desconfiar aquí.
    const out = jarvisEtiquetaAccion(
      { herramienta: "borrar_evento", argumentos: { evento_id: "ev1" } }, contexto);
    expect(out).toContain("Entrega de Sistemas");
  });

  test("si el id no está en la lista cargada, se dice", () => {
    const out = jarvisEtiquetaAccion(
      { herramienta: "borrar_evento", argumentos: { evento_id: "otro" } }, contexto);
    expect(out).toContain("no está en la lista");
  });

  test("editar enseña qué cambia", () => {
    const out = jarvisEtiquetaAccion({
      herramienta: "editar_evento",
      argumentos: { evento_id: "ev1", fecha: "2026-09-01", hora_inicio: "18:00" },
    }, contexto);
    expect(out).toContain("Entrega de Sistemas");
    expect(out).toContain("01/09/2026 a las 18:00");
  });

  test("editar sin ningún cambio no ofrece botón", () => {
    expect(jarvisEtiquetaAccion(
      { herramienta: "editar_evento", argumentos: { evento_id: "ev1" } }, contexto)).toBeNull();
  });

  test("una nota se nombra por su título", () => {
    expect(jarvisEtiquetaAccion(
      { herramienta: "borrar_idea", argumentos: { idea_id: "id1" } }, contexto))
      .toContain("Llamar al dentista");
  });

  test("conectar un MCP enseña nombre y URL, NUNCA el token", () => {
    const out = jarvisEtiquetaAccion({
      herramienta: "mcp_conectar",
      argumentos: { nombre: "github", url: "https://api.example/mcp", token: "ghp_secreto" },
    });
    expect(out).toContain("github");
    expect(out).toContain("https://api.example/mcp");
    expect(out).not.toContain("ghp_secreto");
  });

  test("una orden de casa enseña el servicio y la entidad tal cual viajan", () => {
    expect(jarvisEtiquetaAccion({
      herramienta: "casa_ordenar",
      argumentos: { servicio: "lock.unlock", entidad: "lock.puerta" },
    })).toBe("En casa: ejecutar lock.unlock sobre lock.puerta");
  });

  test("cobrar dice lo que hace sin necesitar contexto", () => {
    expect(jarvisEtiquetaAccion({ herramienta: "cobrar_entrenamiento", argumentos: {} }))
      .toContain("cobradas");
  });

  test("sin los argumentos mínimos no hay botón", () => {
    expect(jarvisEtiquetaAccion({ herramienta: "mcp_conectar", argumentos: { nombre: "x" } })).toBeNull();
    expect(jarvisEtiquetaAccion({ herramienta: "borrar_idea", argumentos: {} })).toBeNull();
    expect(jarvisEtiquetaAccion({ herramienta: "casa_ordenar", argumentos: { servicio: "light.turn_on" } })).toBeNull();
  });
});

describe("esFinDeLlamada", () => {
  test("una despedida cuelga", () => {
    expect(esFinDeLlamada("adiós")).toBe(true);
    expect(esFinDeLlamada("Adios!")).toBe(true);
    expect(esFinDeLlamada("cuelga")).toBe(true);
    expect(esFinDeLlamada("hasta luego, gracias")).toBe(true);
  });

  test("una despedida dentro de una frase NO cuelga", () => {
    // Colgar por error a media conversación molesta más que tener que pulsar el botón.
    expect(esFinDeLlamada("dile adiós a las vacaciones")).toBe(false);
    expect(esFinDeLlamada("apunta que tengo que despedirme de Ana")).toBe(false);
  });

  test("el silencio no cuelga", () => {
    expect(esFinDeLlamada("")).toBe(false);
    expect(esFinDeLlamada(null)).toBe(false);
  });
});
