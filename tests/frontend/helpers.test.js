import { describe, test, expect, vi, afterEach } from "vitest";
import {
  isToday, isFuture, isPast, isActive, daysUntil, formatTime, formatUpcomingTime,
  urgencyColor, formatShortDate, isoToDdMmYyyy,
  hoursToHM, sleepScore, calcRecoveryMod, findMetric, weatherFromCode,
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
});
