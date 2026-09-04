import { describe, test, expect } from "vitest";
import {
  MINUTOS_DIA, ANCHO_MINIMO_PCT, CARRILES,
  FUENTE_OK, FUENTE_CARGANDO, FUENTE_ERROR, FUENTE_AUSENTE, FUENTE_PARCIAL,
  CARRIL_CON_DATOS, CARRIL_VACIO,
  fechaLocalISO, inicioDelDiaLocal, desplazarDia, largoDelDiaMin, tieneHora,
  aFechaLocal, formatoHora, porcentajeDelDia, recortarAlDia, tramoDelDia,
  horasDelEje, posicionAhora, repartirEnFilas,
  normalizarEventos, normalizarSueno, normalizarEntrenos, normalizarPresencia, normalizarAvisos,
  construirLineaTiempo, textoEstadoCarril, etiquetaDia,
} from "../../src/lib/lineaTiempo";

// Todas las fechas de estos tests son de JUNIO a propósito: es el único mes en que
// ningún huso del mundo cambia la hora, así que la suite da igual en la máquina en que
// corra. Lo que sí se comprueba es que nada se apoya en UTC.
const DIA  = "2026-06-15";
const AYER = "2026-06-14";
const MANANA = "2026-06-16";

describe("fechas locales", () => {
  test("fechaLocalISO usa los componentes LOCALES, no los de UTC", () => {
    // A las 23:30 de Madrid ya es el día siguiente en UTC: toISOString() daría el 16.
    expect(fechaLocalISO(new Date(2026, 5, 15, 23, 30))).toBe("2026-06-15");
    expect(fechaLocalISO(new Date(2026, 5, 15, 0, 15))).toBe("2026-06-15");
    expect(fechaLocalISO("nada")).toBe("");
  });

  test("inicioDelDiaLocal es la medianoche local de ESE día", () => {
    const d = inicioDelDiaLocal(DIA);
    expect(d.getFullYear()).toBe(2026);
    expect(d.getMonth()).toBe(5);
    expect(d.getDate()).toBe(15);
    expect(d.getHours()).toBe(0);
    expect(inicioDelDiaLocal("2026-6-1")).toBeNull();
    expect(inicioDelDiaLocal(null)).toBeNull();
  });

  test("desplazarDia cruza meses y años sin desviarse", () => {
    expect(desplazarDia(DIA, -1)).toBe(AYER);
    expect(desplazarDia(DIA, 1)).toBe(MANANA);
    expect(desplazarDia("2026-06-01", -1)).toBe("2026-05-31");
    expect(desplazarDia("2026-12-31", 1)).toBe("2027-01-01");
  });

  test("largoDelDiaMin da un día normal de 24 h", () => {
    expect(largoDelDiaMin(DIA)).toBe(MINUTOS_DIA);
  });

  test("aFechaLocal respeta la hora de pared del exportador de salud", () => {
    // "2026-06-15 07:12:33 +0200" es lo que escribe Health Auto Export. La hora buena
    // es la que pone, no la que salga de renegociar el desfase con el huso de quien
    // mira: `new Date(cadena)` daría 07:12 solo en Madrid y otra cosa en cualquier
    // otro sitio.
    const d = aFechaLocal("2026-06-15 07:12:33 +0200");
    expect(d.getHours()).toBe(7);
    expect(d.getMinutes()).toBe(12);
    expect(fechaLocalISO(d)).toBe(DIA);
    expect(formatoHora(d)).toBe("07:12");
  });

  test("aFechaLocal acepta Date, ISO con T y basura", () => {
    const ref = new Date(2026, 5, 15, 9, 0);
    expect(aFechaLocal(ref)).toBe(ref);
    expect(formatoHora(aFechaLocal("2026-06-15T09:30:00"))).toBe("09:30");
    expect(aFechaLocal("")).toBeNull();
    expect(aFechaLocal("mañana por la tarde")).toBeNull();
    expect(aFechaLocal(new Date("x"))).toBeNull();
  });

  test("tieneHora distingue una fecha suelta de un instante", () => {
    expect(tieneHora("2026-06-15")).toBe(false);
    expect(tieneHora("2026-06-15 07:12:33 +0200")).toBe(true);
    expect(tieneHora("2026-06-15T07:12:00")).toBe(true);
    expect(tieneHora(new Date())).toBe(true);
    expect(tieneHora(null)).toBe(false);
  });
});

describe("geometría del eje", () => {
  test("porcentajeDelDia reparte sobre las 24 h reales", () => {
    expect(porcentajeDelDia(0, DIA)).toBe(0);
    expect(porcentajeDelDia(720, DIA)).toBe(50);
    expect(porcentajeDelDia(1440, DIA)).toBe(100);
  });

  test("recortarAlDia deja dentro lo que cae dentro", () => {
    const r = recortarAlDia(new Date(2026, 5, 15, 9), new Date(2026, 5, 15, 10, 30), DIA);
    expect(r.desdeMin).toBe(540);
    expect(r.hastaMin).toBe(630);
    expect(r.cortadoAntes).toBe(false);
    expect(r.cortadoDespues).toBe(false);
  });

  test("recortarAlDia descarta lo de otros días", () => {
    expect(recortarAlDia(new Date(2026, 5, 14, 9), new Date(2026, 5, 14, 10), DIA)).toBeNull();
    expect(recortarAlDia(new Date(2026, 5, 16, 9), new Date(2026, 5, 16, 10), DIA)).toBeNull();
    // Un evento que ACABA exactamente a medianoche es del día anterior, no de este.
    expect(recortarAlDia(new Date(2026, 5, 14, 23), new Date(2026, 5, 15, 0), DIA)).toBeNull();
    // Y uno que empieza a las 24:00 es del siguiente.
    expect(recortarAlDia(new Date(2026, 5, 16, 0), new Date(2026, 5, 16, 1), DIA)).toBeNull();
  });

  test("recortarAlDia marca los dos cortes de medianoche", () => {
    const entra = recortarAlDia(new Date(2026, 5, 14, 23, 30), new Date(2026, 5, 15, 7), DIA);
    expect(entra.desdeMin).toBe(0);
    expect(entra.hastaMin).toBe(420);
    expect(entra.cortadoAntes).toBe(true);
    expect(entra.cortadoDespues).toBe(false);

    const sale = recortarAlDia(new Date(2026, 5, 15, 23), new Date(2026, 5, 16, 6), DIA);
    expect(sale.desdeMin).toBe(1380);
    expect(sale.hastaMin).toBe(MINUTOS_DIA);
    expect(sale.cortadoAntes).toBe(false);
    expect(sale.cortadoDespues).toBe(true);
  });

  test("recortarAlDia acepta un instante sin duración y rechaza el fin antes del inicio", () => {
    const p = recortarAlDia(new Date(2026, 5, 15, 8), new Date(2026, 5, 15, 8), DIA);
    expect(p.desdeMin).toBe(480);
    expect(p.hastaMin).toBe(480);
    expect(recortarAlDia(new Date(2026, 5, 15, 10), new Date(2026, 5, 15, 9), DIA)).toBeNull();
  });

  test("tramoDelDia nunca deja una barra invisible ni la saca del eje", () => {
    const corto = tramoDelDia(new Date(2026, 5, 15, 8), new Date(2026, 5, 15, 8, 2), DIA);
    expect(corto.anchoRealPct).toBeCloseTo(2 / 1440 * 100, 6);
    expect(corto.anchoPct).toBe(ANCHO_MINIMO_PCT);

    const final = tramoDelDia(new Date(2026, 5, 15, 23, 59), new Date(2026, 5, 15, 23, 59, 30), DIA);
    expect(final.izquierdaPct + final.anchoPct).toBeLessThanOrEqual(100);
  });

  test("horasDelEje y posicionAhora colocan las marcas donde toca", () => {
    const marcas = horasDelEje(DIA, 6);
    expect(marcas.map(m => m.etiqueta)).toEqual(["00:00", "06:00", "12:00", "18:00"]);
    expect(marcas[2].izquierdaPct).toBe(50);

    expect(posicionAhora(DIA, new Date(2026, 5, 15, 12)).izquierdaPct).toBe(50);
    expect(posicionAhora(DIA, new Date(2026, 5, 16, 12))).toBeNull();
  });
});

describe("solapes dentro de un carril", () => {
  const it = (id, desdeMin, hastaMin) => ({ id, desdeMin, hastaMin, sinHora: false });

  test("lo que no se solapa cabe en una sola fila", () => {
    const r = repartirEnFilas([it("a", 0, 60), it("b", 60, 120), it("c", 200, 260)]);
    expect(r.filas).toBe(1);
    expect(r.items.every(x => x.fila === 0)).toBe(true);
  });

  test("tres cosas a la vez ocupan tres filas", () => {
    const r = repartirEnFilas([it("a", 0, 120), it("b", 30, 90), it("c", 60, 180)]);
    expect(r.filas).toBe(3);
    expect(r.items.map(x => x.fila)).toEqual([0, 1, 2]);
  });

  test("una fila se reutiliza en cuanto queda libre", () => {
    const r = repartirEnFilas([it("a", 0, 60), it("b", 10, 30), it("c", 70, 90)]);
    expect(r.filas).toBe(2);
    expect(r.items.find(x => x.id === "c").fila).toBe(0);
  });

  test("los items sin hora quedan fuera del reparto y nunca hay cero filas", () => {
    const r = repartirEnFilas([{ id: "x", sinHora: true }]);
    expect(r.items).toEqual([]);
    expect(r.filas).toBe(1);
    expect(repartirEnFilas(null).filas).toBe(1);
  });
});

describe("normalizarEventos", () => {
  const eventos = [
    { id: "1", title: "Clase", start: "2026-06-15T09:00:00", end: "2026-06-15T11:00:00", location: "Deusto" },
    { id: "2", title: "Otro día", start: "2026-06-17T09:00:00", end: "2026-06-17T10:00:00" },
    { id: "3", title: "Vacaciones", start: "2026-06-14", end: "2026-06-17", isAllDay: true },
  ];

  test("solo entran los del día y con su tramo", () => {
    const r = normalizarEventos(eventos, DIA);
    expect(r).toHaveLength(2);
    const clase = r.find(x => x.etiqueta === "Clase");
    expect(clase.desdeMin).toBe(540);
    expect(clase.horaTexto).toBe("09:00 – 11:00");
    expect(clase.detalle).toBe("Deusto");
  });

  test("un evento de todo el día va SIN tramo, no de 00:00 a 24:00", () => {
    const todoElDia = normalizarEventos(eventos, DIA).find(x => x.etiqueta === "Vacaciones");
    expect(todoElDia.sinHora).toBe(true);
    expect(todoElDia.horaTexto).toBe("sin hora");
    // Y respeta el rango: el 17 ya no está dentro.
    expect(normalizarEventos(eventos, "2026-06-17").some(x => x.etiqueta === "Vacaciones")).toBe(false);
  });

  test("una lista vacía o nula no revienta", () => {
    expect(normalizarEventos([], DIA)).toEqual([]);
    expect(normalizarEventos(null, DIA)).toEqual([]);
  });
});

describe("normalizarSueno: la noche a caballo entre dos días", () => {
  // La fila se guarda con la fecha en la que uno SE DESPIERTA. Acostarse a las 23:40
  // significa que la noche empezó el día anterior al de la fila.
  const filas = [
    { date: "2026-06-15", value: 7.5, extra: { sleep_start: "23:40" } },
    { date: "2026-06-16", value: 6,   extra: { sleep_start: "00:30" } },
  ];

  test("la noche que terminó esta mañana entra cortada por la izquierda", () => {
    const r = normalizarSueno(filas, DIA).filter(x => !x.sinHora);
    const anoche = r.find(x => x.cortadoAntes);
    expect(anoche).toBeTruthy();
    expect(anoche.desdeMin).toBe(0);
    expect(anoche.hastaMin).toBe(7 * 60 + 10);   // 23:40 + 7,5 h = 07:10
    expect(anoche.cortadoDespues).toBe(false);
    expect(anoche.horaTexto).toBe("←23:40 – 07:10");
    expect(anoche.detalle).toBe("7 h 30 min dormidas");
  });

  test("la misma noche, vista desde el día anterior, entra cortada por la derecha", () => {
    const r = normalizarSueno(filas, AYER);
    expect(r).toHaveLength(1);
    expect(r[0].desdeMin).toBe(23 * 60 + 40);
    expect(r[0].hastaMin).toBe(MINUTOS_DIA);
    expect(r[0].cortadoAntes).toBe(false);
    expect(r[0].cortadoDespues).toBe(true);
  });

  test("acostarse pasada la medianoche NO se mueve al día anterior", () => {
    // La fila del 16 con sleep_start 00:30 empieza el propio 16, así que el día 15 no
    // la ve: si se restara un día siempre, esta noche se pintaría 24 h antes.
    expect(normalizarSueno(filas, DIA).some(x => x.desdeMin === 30)).toBe(false);
    const r = normalizarSueno(filas, MANANA).filter(x => !x.sinHora);
    expect(r[0].desdeMin).toBe(30);
    expect(r[0].hastaMin).toBe(6 * 60 + 30);
  });

  test("sin hora de acostarse se sabe que durmió, no cuándo", () => {
    const r = normalizarSueno([{ date: DIA, value: 7 }], DIA);
    expect(r).toHaveLength(1);
    expect(r[0].sinHora).toBe(true);
    expect(r[0].detalle).toBe("7 h dormidas");
    // Y no se cuela como noche del día anterior: sin inicio no hay dónde ponerla.
    expect(normalizarSueno([{ date: MANANA, value: 7 }], DIA)).toEqual([]);
  });

  test("la duración sale de las fases cuando value viene a 0", () => {
    const r = normalizarSueno(
      [{ date: DIA, value: 0, extra: { sleep_start: "23:00", deep: 1.5, rem: 1.5, core: 4 } }], DIA);
    expect(r[0].hastaMin).toBe(6 * 60);   // 23:00 + 7 h
  });

  test("una noche anulada se enseña marcada, no se esconde", () => {
    const r = normalizarSueno(
      [{ date: DIA, value: 7.5, extra: { sleep_start: "23:40", excluded: true } }], DIA);
    expect(r[0].anulada).toBe(true);
    expect(r[0].tono).toBe("atenuado");
    expect(r[0].etiqueta).toContain("anulada");
  });

  test("una noche con hora pero sin duración no se dibuja como tramo", () => {
    // Pasa de verdad: Health Auto Export deja `value` a 0 y a veces tampoco manda las
    // fases. Se sabe que hay fila, no cuánto se durmió: un tramo de duración cero sería
    // un dato inventado.
    const r = normalizarSueno([{ date: DIA, value: 0, extra: { sleep_start: "23:40" } }], DIA);
    expect(r).toHaveLength(1);
    expect(r[0].sinHora).toBe(true);
    expect(r[0].detalle).toBe("sin duración");
  });
});

describe("normalizarEntrenos", () => {
  const workouts = [{
    date: DIA,
    extra: {
      workouts: [
        { name: "Functional Strength Training", duration: 3600, start: "2026-06-15 18:30:00 +0200" },
        { name: "Caminata", duration: 45, start: "2026-06-15" },     // fecha sin hora
        { name: "De otro día", duration: 1800, start: "2026-06-14 08:00:00 +0200" },
      ],
    },
  }];

  test("el entreno del reloj con hora se coloca en el eje", () => {
    const r = normalizarEntrenos({ workouts }, DIA);
    const fuerza = r.find(x => x.etiqueta.startsWith("Functional"));
    expect(fuerza.sinHora).toBe(false);
    expect(fuerza.desdeMin).toBe(18 * 60 + 30);
    expect(fuerza.hastaMin).toBe(19 * 60 + 30);   // 3600 s = 60 min
    expect(fuerza.detalle).toBe("60 min");
  });

  test("un entreno con fecha pero sin hora no se inventa el momento", () => {
    const caminata = normalizarEntrenos({ workouts }, DIA).find(x => x.etiqueta === "Caminata");
    expect(caminata.sinHora).toBe(true);
    expect(caminata.detalle).toBe("45 min");      // 45 <= 300 → ya son minutos
  });

  test("cada entreno cae en el día de SU inicio, no en el de la fila", () => {
    // La fila de `workouts` se agrupa por día, pero un entreno de madrugada puede
    // acabar guardado con otra fecha: manda el `start` de cada uno.
    expect(normalizarEntrenos({ workouts }, DIA).some(x => x.etiqueta === "De otro día")).toBe(false);
    const ayer = normalizarEntrenos({ workouts }, AYER);
    expect(ayer.map(x => x.etiqueta)).toEqual(["De otro día"]);
    expect(ayer[0].desdeMin).toBe(8 * 60);
    expect(normalizarEntrenos({ workouts }, MANANA)).toEqual([]);
  });

  test("las sesiones de entrenamiento personal van SIEMPRE sin hora", () => {
    const r = normalizarEntrenos({
      workouts: [],
      sesiones: [{ id: "s1", date: DIA, duration_hours: 1 }, { id: "s2", date: AYER, duration_hours: 1 }],
    }, DIA);
    expect(r).toHaveLength(1);
    expect(r[0].sinHora).toBe(true);
    expect(r[0].detalle).toContain("no guarda la hora");
  });

  test("sin fuentes no revienta", () => {
    expect(normalizarEntrenos(undefined, DIA)).toEqual([]);
    expect(normalizarEntrenos({ workouts: [{ date: DIA, extra: {} }] }, DIA)).toEqual([]);
  });
});

describe("normalizarPresencia", () => {
  const filas = [
    { date: DIA, value: 15.5, extra: { fuera: 8.5 } },
    { date: AYER, value: 0, extra: { fuera: 0 } },
  ];

  test("resume el día en horas, no en tramos", () => {
    const r = normalizarPresencia(filas, DIA);
    expect(r.casa).toBe(15.5);
    expect(r.fuera).toBe(8.5);
    expect(r.texto).toBe("15 h 30 min en casa · 8 h 30 min fuera");
  });

  test("un día a cero o sin fila es no saber nada, no cero horas", () => {
    expect(normalizarPresencia(filas, AYER)).toBeNull();
    expect(normalizarPresencia(filas, MANANA)).toBeNull();
    expect(normalizarPresencia(null, DIA)).toBeNull();
  });
});

describe("normalizarAvisos", () => {
  test("cada aviso entra como un instante, con la hora real de enviado_at", () => {
    const avisos = [
      { id: "a1", texto: "Sal ya", regla: "salida", enviado_at: "2026-06-15T08:05:00" },
      { id: "a2", texto: "Vuelve a casa", regla: "vuelta", enviado_at: "2026-06-15T19:30:00" },
    ];
    const r = normalizarAvisos(avisos, DIA);
    expect(r).toHaveLength(2);
    expect(r[0].sinHora).toBe(false);
    expect(r[0].desdeMin).toBe(r[0].hastaMin);
    expect(r[0].horaTexto).toBe("08:05 – 08:05");
    expect(r[0].etiqueta).toBe("Sal ya");
    expect(r[0].detalle).toBe("salida");
  });

  test("un aviso de otro día no entra", () => {
    const avisos = [{ id: "a1", texto: "Sal ya", enviado_at: "2026-06-14T08:05:00" }];
    expect(normalizarAvisos(avisos, DIA)).toEqual([]);
  });

  test("sin lista, o un aviso sin enviado_at, no revienta", () => {
    expect(normalizarAvisos(null, DIA)).toEqual([]);
    expect(normalizarAvisos([{ id: "a1", texto: "Sal ya" }], DIA)[0].sinHora).toBe(true);
  });
});

describe("construirLineaTiempo: fuente ausente contra fuente vacía", () => {
  const soloEventos = extra => construirLineaTiempo({
    dia: DIA, hoy: DIA, fuentes: { eventos: extra },
  }).carriles.find(c => c.id === "eventos");

  test("una fuente que respondió y no trajo nada dice que no pasó nada", () => {
    const c = soloEventos({ estado: FUENTE_OK, datos: [] });
    expect(c.estado).toBe(CARRIL_VACIO);
    expect(c.conocido).toBe(true);
    expect(textoEstadoCarril(c)).toBe("Nada este día");
  });

  test("una fuente que trajo algo pasa a con_datos", () => {
    const c = soloEventos({
      estado: FUENTE_OK,
      datos: [{ id: "1", title: "Cita", start: "2026-06-15T17:00:00", end: "2026-06-15T18:00:00" }],
    });
    expect(c.estado).toBe(CARRIL_CON_DATOS);
    expect(c.items).toHaveLength(1);
    expect(textoEstadoCarril(c)).toBe("");
  });

  test("una fuente que falló, que carga o que no existe NUNCA se pinta vacía", () => {
    for (const [estado, texto] of [
      [FUENTE_CARGANDO, "Cargando…"],
      [FUENTE_ERROR,    "No se pudo consultar: no lo sé"],
      [FUENTE_PARCIAL,  "Sin datos para este día: no lo sé"],
      [FUENTE_AUSENTE,  "Sin fuente de histórico: no lo sé"],
    ]) {
      const c = soloEventos({ estado });
      expect(c.estado).toBe(estado);
      expect(c.conocido).toBe(false);
      expect(c.items).toEqual([]);
      expect(textoEstadoCarril(c)).toBe(texto);
    }
  });

  test("una fuente que no se pasa se trata como ausente, no como vacía", () => {
    const linea = construirLineaTiempo({ dia: DIA, hoy: DIA });
    expect(linea.carriles).toHaveLength(CARRILES.length);
    expect(linea.conocidos).toBe(0);
    expect(linea.total).toBe(CARRILES.length);
    expect(linea.carriles.every(c => c.estado === FUENTE_AUSENTE)).toBe(true);
  });

  test("la cabecera cuenta cuántos carriles se pudieron mirar de verdad", () => {
    const linea = construirLineaTiempo({
      dia: DIA, hoy: DIA,
      fuentes: {
        eventos:  { estado: FUENTE_OK, datos: [] },
        sueno:    { estado: FUENTE_OK, datos: [] },
        entrenos: { estado: FUENTE_ERROR },
      },
    });
    expect(linea.conocidos).toBe(2);
  });

  test("los avisos entran con hora real, no como un resumen — de cualquier día", () => {
    const datos = [
      { id: "a1", texto: "Sal ya", enviado_at: "2026-06-14T08:05:00" },
    ];
    const c = construirLineaTiempo({
      dia: AYER, hoy: DIA, fuentes: { avisos: { estado: FUENTE_OK, datos } },
    }).carriles.find(c2 => c2.id === "avisos");
    expect(c.estado).toBe(CARRIL_CON_DATOS);
    expect(c.resumen).toBeNull();
    expect(c.items).toHaveLength(1);
    expect(c.items[0].horaTexto).toBe("08:05 – 08:05");
  });

  test("cero avisos ese día sí es un dato y se dice", () => {
    const c = construirLineaTiempo({
      dia: DIA, hoy: DIA,
      fuentes: { avisos: { estado: FUENTE_OK, datos: [] } },
    }).carriles.find(c2 => c2.id === "avisos");
    expect(c.estado).toBe(CARRIL_VACIO);
    expect(textoEstadoCarril(c)).toBe("Nada este día");
  });
});

describe("construirLineaTiempo: el día completo", () => {
  const linea = construirLineaTiempo({
    dia: DIA,
    hoy: DIA,
    ahora: new Date(2026, 5, 15, 18, 0),
    fuentes: {
      eventos: { estado: FUENTE_OK, datos: [
        { id: "1", title: "Clase", start: "2026-06-15T09:00:00", end: "2026-06-15T11:00:00" },
        { id: "2", title: "Cena", start: "2026-06-15T21:30:00", end: "2026-06-15T23:00:00" },
      ] },
      sueno:     { estado: FUENTE_OK, datos: [{ date: DIA, value: 7.5, extra: { sleep_start: "23:40" } }] },
      entrenos:  { estado: FUENTE_OK, datos: { workouts: [], sesiones: [{ id: "s", date: DIA, duration_hours: 1 }] } },
      presencia: { estado: FUENTE_OK, datos: { filas: [{ date: DIA, value: 15, extra: { fuera: 9 } }] } },
      avisos:    { estado: FUENTE_ERROR },
      casa:      { estado: FUENTE_AUSENTE, nota: "sin histórico" },
    },
  });

  test("el orden de los carriles es siempre el mismo", () => {
    expect(linea.carriles.map(c => c.id)).toEqual(CARRILES.map(c => c.id));
  });

  test("el día lleva su eje, su ahora y su recuento", () => {
    expect(linea.dia).toBe(DIA);
    expect(linea.esHoy).toBe(true);
    expect(linea.largoMin).toBe(MINUTOS_DIA);
    expect(linea.ahora.izquierdaPct).toBe(75);
    expect(linea.horas.map(h => h.hora)).toEqual([0, 3, 6, 9, 12, 15, 18, 21]);
    expect(linea.conocidos).toBe(4);
  });

  test("un día que no es hoy no lleva línea de ahora", () => {
    expect(construirLineaTiempo({ dia: AYER, hoy: DIA }).ahora).toBeNull();
  });

  test("el carril de entrenos separa lo que tiene hora de lo que no", () => {
    const c = linea.carriles.find(x => x.id === "entrenos");
    expect(c.items).toEqual([]);
    expect(c.sinHora).toHaveLength(1);
    expect(c.estado).toBe(CARRIL_CON_DATOS);
    expect(c.nota).toBeNull();
  });

  test("un día sin fecha válida cae en hoy en vez de romperse", () => {
    const l = construirLineaTiempo({ dia: "el martes" });
    expect(l.dia).toBe(fechaLocalISO(new Date()));
  });
});

describe("etiquetaDia", () => {
  test("hoy y ayer se dicen con su nombre", () => {
    expect(etiquetaDia(DIA, DIA)).toBe("hoy");
    expect(etiquetaDia(AYER, DIA)).toBe("ayer");
  });

  test("el resto lleva día de la semana y mes en español", () => {
    const t = etiquetaDia("2026-06-10", DIA);
    expect(t).toContain("10 de junio");
    expect(t).toMatch(/^(lunes|martes|miércoles|jueves|viernes|sábado|domingo), /);
  });

  test("una fecha inválida no rompe la cabecera", () => {
    expect(etiquetaDia("x", DIA)).toBe("");
  });
});
