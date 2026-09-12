// La lógica de las pestañas de la fase 3 de la zona de desarrollo.
//
// Lo que se fija aquí es la diferencia entre "no hay" y "no lo sé", que es lo que decide si
// estas cuatro pantallas sirven o engañan: un día tranquilo y tres tablas caídas traen los
// dos cero eventos, un PC apagado no es una avería, y una regla silenciada es lo más grave
// que puede salir aunque no haya fallado nada.
import { describe, test, expect, vi, afterEach } from "vitest";

import { diaLocal, diaDesplazado, resumenLinea, estadoAgente, estadoJob,
         estadoMetrica, estadoFuente, estadoRegla, CARRILES } from "../../src/lib/dev";

afterEach(() => { vi.useRealTimers(); });

describe("el día que se está mirando", () => {
  test("va en hora local, no en UTC", () => {
    // 00:30 de un 12 de septiembre en Madrid son las 22:30 del 11 en UTC: con
    // `toISOString()` la pestaña abriría en el día de ayer.
    expect(diaLocal(new Date(2026, 8, 12, 0, 30))).toBe("2026-09-12");
  });

  test("rellena con ceros para que la fecha no baile de ancho", () => {
    expect(diaLocal(new Date(2026, 0, 5, 10))).toBe("2026-01-05");
  });

  test("se mueve un día atrás y otro adelante", () => {
    expect(diaDesplazado("2026-09-12", -1)).toBe("2026-09-11");
    expect(diaDesplazado("2026-09-12", 1)).toBe("2026-09-13");
  });

  test("cruza el cambio de mes", () => {
    expect(diaDesplazado("2026-03-01", -1)).toBe("2026-02-28");
  });

  test("el cambio de hora no se come ni repite un día", () => {
    // En España el reloj se atrasa la madrugada del último domingo de octubre.
    expect(diaDesplazado("2026-10-26", -1)).toBe("2026-10-25");
    expect(diaDesplazado("2026-10-24", 1)).toBe("2026-10-25");
  });
});

describe("resumenLinea", () => {
  test("sin datos no dice que no pasó nada", () => {
    expect(resumenLinea(null).tono).toBe("muted");
  });

  test("lo que no se ha podido leer manda sobre el recuento", () => {
    // Es el fallo que no se puede cometer: con las tablas caídas, cero eventos y un día
    // tranquilo se ven exactamente igual.
    const r = resumenLinea({ total: 0, eventos: [], sin_leer: ["registro", "avisos"] });
    expect(r.tono).toBe("accent");
    expect(r.texto).toContain("registro");
  });

  test("los eventos en rojo se cuentan antes que nada", () => {
    const r = resumenLinea({ total: 9, sin_leer: [], eventos: [{ tono: "red" }, { tono: "green" }] });
    expect(r.tono).toBe("red");
    expect(r.texto).toContain("1 en rojo");
  });

  test("un día sin nada se dice tal cual, no en verde", () => {
    expect(resumenLinea({ total: 0, eventos: [], sin_leer: [] }).tono).toBe("muted");
  });

  test("un día con eventos y ninguno en rojo es verde", () => {
    const r = resumenLinea({ total: 4, sin_leer: [], eventos: [{ tono: "green" }] });
    expect(r.tono).toBe("green");
  });
});

describe("los carriles", () => {
  test("no hay dos con el mismo id", () => {
    const ids = CARRILES.map(c => c.id);
    expect(new Set(ids).size).toBe(ids.length);
  });
});

describe("estadoAgente", () => {
  test("visto hace poco, en verde", () => {
    const e = estadoAgente({ status: "online", silencio_segundos: 12 }, 60);
    expect(e.tono).toBe("green");
    expect(e.texto).toContain("12s");
  });

  test("callado NO es rojo: el PC está apagado media vida", () => {
    const e = estadoAgente({ status: "online", silencio_segundos: 40000,
                             last_seen_at: new Date(Date.now() - 40000_000).toISOString() }, 60);
    expect(e.tono).toBe("muted");
    expect(e.texto).toContain("apagado");
  });

  test("una fecha ilegible no vale como vivo", () => {
    expect(estadoAgente({ status: "online", silencio_segundos: null }).tono).toBe("muted");
  });
});

describe("estadoJob", () => {
  const fallido = { status: "failed", claimed_by: "pc", attempt: 1 };

  test("un fallido con dueño se puede reintentar", () => {
    const e = estadoJob(fallido, 3);
    expect(e.tono).toBe("red");
    expect(e.reintentable).toBe(true);
    expect(e.texto).toContain("intento 1/3");
  });

  test("sin dueño no se ofrece el botón, y se dice por qué", () => {
    // El endpoint exige `claimed_by`: ofrecerlo sería ofrecer un 409.
    const e = estadoJob({ ...fallido, claimed_by: null }, 3);
    expect(e.reintentable).toBe(false);
    expect(e.motivo).toMatch(/cogerlo/);
  });

  test("agotados los intentos, tampoco", () => {
    const e = estadoJob({ ...fallido, attempt: 3 }, 3);
    expect(e.reintentable).toBe(false);
    expect(e.motivo).toContain("3 intentos");
  });

  test("un pendiente no se reintenta ni necesita explicación", () => {
    const e = estadoJob({ status: "pending", attempt: 0 }, 3);
    expect(e.reintentable).toBe(false);
    expect(e.motivo).toBe(null);
    expect(e.tono).toBe("muted");
  });

  test("uno hecho es verde", () => {
    expect(estadoJob({ status: "done", attempt: 0 }, 3).tono).toBe("green");
  });
});

describe("estadoMetrica", () => {
  test("que nunca haya llegado nada no es un hueco", () => {
    expect(estadoMetrica({ dias_atras: null, huecos: 30 }).tono).toBe("muted");
  });

  test("un día de retraso es lo normal: el sueño llega por la mañana", () => {
    const e = estadoMetrica({ dias_atras: 1, huecos: 0, dias_con_dato: 30 });
    expect(e.tono).toBe("green");
    expect(e.texto).toBe("ayer");
  });

  test("tres días es para mirarlo; cinco es una avería", () => {
    expect(estadoMetrica({ dias_atras: 3, huecos: 0 }).tono).toBe("accent");
    expect(estadoMetrica({ dias_atras: 5, huecos: 0 }).tono).toBe("red");
  });

  test("los huecos se dicen en singular cuando es uno", () => {
    expect(estadoMetrica({ dias_atras: 0, huecos: 1 }).texto).toBe("hoy · 1 hueco");
    expect(estadoMetrica({ dias_atras: 0, huecos: 4 }).texto).toBe("hoy · 4 huecos");
  });
});

describe("estadoFuente", () => {
  const AHORA = new Date("2026-09-12T12:00:00Z");
  const haceHoras = h => new Date(AHORA.getTime() - h * 3600_000).toISOString();

  test("sin escrituras no se pinta en rojo: puede que esa fuente no exista aquí", () => {
    expect(estadoFuente(null).tono).toBe("muted");
  });

  test("un envío de ayer sigue siendo verde", () => {
    vi.useFakeTimers();
    vi.setSystemTime(AHORA);
    // 26 horas y no 24: el envío diario no cae siempre a la misma hora.
    expect(estadoFuente(haceHoras(25)).tono).toBe("green");
  });

  test("dos días callada es para mirarlo; cuatro es que ha dejado de escribir", () => {
    vi.useFakeTimers();
    vi.setSystemTime(AHORA);
    expect(estadoFuente(haceHoras(48)).tono).toBe("accent");
    expect(estadoFuente(haceHoras(96)).tono).toBe("red");
  });

  test("una fecha ilegible se dice, no se da por buena", () => {
    expect(estadoFuente("cuando sea").tono).toBe("muted");
  });
});

describe("estadoRegla", () => {
  test("silenciada es rojo aunque no haya fallado nada", () => {
    // Dejar de avisarte de algo sin decírtelo es el fallo más caro de los que puede
    // cometer una regla, y por eso no es ámbar.
    const e = estadoRegla({ regla: "reloj", enviados: 0, silenciada: true,
                            silenciada_desde: "2026-09-01T00:00:00Z" });
    expect(e.tono).toBe("red");
    expect(e.texto).toContain("silenciada");
  });

  test("una regla callada pero viva no alarma", () => {
    expect(estadoRegla({ enviados: 0, silenciada: false }).tono).toBe("muted");
  });

  test("sin votos no se juzga", () => {
    const e = estadoRegla({ enviados: 3, utiles: 0, no_utiles: 0, sin_votar: 3, silenciada: false });
    expect(e.tono).toBe("muted");
    expect(e.texto).toContain("3 avisos");
  });

  test("más votos negativos que positivos es para mirarlo", () => {
    const e = estadoRegla({ enviados: 5, utiles: 1, no_utiles: 3, sin_votar: 1, silenciada: false });
    expect(e.tono).toBe("accent");
  });

  test("una regla que acierta es verde", () => {
    const e = estadoRegla({ enviados: 5, utiles: 4, no_utiles: 0, sin_votar: 1, silenciada: false });
    expect(e.tono).toBe("green");
  });
});
