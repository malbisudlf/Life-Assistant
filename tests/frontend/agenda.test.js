import { describe, test, expect } from "vitest";
import {
  VENTANA_SALIDA_MIN, UMBRAL_PRONTO_MIN, HORIZONTE_DIAS,
  esUbicacionOnline, proximoCompromiso, cuentaAtras, faltaPara, textoHueco,
  textoErrorRuta, faseSalida, recordarModo, modoPara,
} from "../../src/lib/agenda";

// Las fechas se construyen por componentes LOCALES (`new Date(a, m, d, h, min)`) y se
// pasan como Date o como ISO con zona: vitest no fija TZ, así que un "10:00" escrito a
// mano en UTC daría resultados distintos en cada máquina.
const L = (a, m, d, h = 0, min = 0) => new Date(a, m - 1, d, h, min);
const iso = d => d.toISOString();
const MIN = 60000;

// Un evento como los de /calendar/events: ISO UTC con "Z".
const ev = (id, inicio, fin, extra = {}) => ({
  id, title: `Evento ${id}`, start: iso(inicio), end: iso(fin), location: "", ...extra,
});

describe("constantes", () => {
  test("la ventana es la de las reglas del backend", () => {
    expect(VENTANA_SALIDA_MIN).toBe(180);
    expect(UMBRAL_PRONTO_MIN).toBe(15);
    expect(HORIZONTE_DIAS).toBe(7);
  });
});

describe("esUbicacionOnline", () => {
  test("lo que no es un sitio físico", () => {
    expect(esUbicacionOnline("https://teams.microsoft.com/l/meetup-join/xyz")).toBe(true);
    expect(esUbicacionOnline("http://ejemplo.com")).toBe(true);
    expect(esUbicacionOnline("Reunión de Microsoft Teams")).toBe(true);
    expect(esUbicacionOnline("Zoom")).toBe(true);
    expect(esUbicacionOnline("Google Meet: meet.google.com/abc")).toBe(true);
    expect(esUbicacionOnline("En línea")).toBe(true);
    expect(esUbicacionOnline("")).toBe(true);
    expect(esUbicacionOnline(null)).toBe(true);
  });

  test("un sitio de verdad", () => {
    expect(esUbicacionOnline("Gimnasio Bilbao")).toBe(false);
    expect(esUbicacionOnline("Aula 2.1")).toBe(false);
  });
});

describe("proximoCompromiso", () => {
  const ahora = L(2026, 6, 15, 10, 0);

  test("nada", () => {
    expect(proximoCompromiso([], [], ahora)).toEqual({ actual: null, siguiente: null, huecoMin: null });
    expect(proximoCompromiso(undefined, undefined, ahora)).toEqual({ actual: null, siguiente: null, huecoMin: null });
  });

  test("solo futuros: el más cercano, normalizado", () => {
    const eventos = [
      ev("b", L(2026, 6, 15, 16), L(2026, 6, 15, 17)),
      ev("a", L(2026, 6, 15, 12), L(2026, 6, 15, 13), { location: "  Aula 3 " }),
    ];
    const r = proximoCompromiso(eventos, [], ahora);
    expect(r.actual).toBeNull();
    expect(r.huecoMin).toBeNull();
    expect(r.siguiente).toMatchObject({
      key: "a", id: "a", titulo: "Evento a", lugar: "Aula 3", tipo: "evento",
      start: eventos[1].start,
    });
    expect(r.siguiente.inicio.getTime()).toBe(L(2026, 6, 15, 12).getTime());
    expect(r.siguiente.raw).toBe(eventos[1]);
  });

  test("sin título ni id: título por defecto y la clave cae al inicio", () => {
    const e = { start: iso(L(2026, 6, 15, 12)), end: iso(L(2026, 6, 15, 13)) };
    const r = proximoCompromiso([e], [], ahora);
    expect(r.siguiente.titulo).toBe("(Sin título)");
    expect(r.siguiente.key).toBe(e.start);
  });

  test("uno en curso y el siguiente, con el hueco entre los dos", () => {
    const r = proximoCompromiso([
      ev("curso", L(2026, 6, 15, 9, 30), L(2026, 6, 15, 10, 30)),
      ev("luego", L(2026, 6, 15, 11, 10), L(2026, 6, 15, 12)),
    ], [], ahora);
    expect(r.actual.id).toBe("curso");
    expect(r.siguiente.id).toBe("luego");
    expect(r.huecoMin).toBe(40);
  });

  test("dos en curso: el que acaba antes", () => {
    const r = proximoCompromiso([
      ev("largo", L(2026, 6, 15, 8), L(2026, 6, 15, 14)),
      ev("corto", L(2026, 6, 15, 9, 45), L(2026, 6, 15, 10, 15)),
    ], [], ahora);
    expect(r.actual.id).toBe("corto");
  });

  test("solape: el hueco sale negativo y así se devuelve", () => {
    const r = proximoCompromiso([
      ev("curso", L(2026, 6, 15, 9), L(2026, 6, 15, 11)),
      ev("luego", L(2026, 6, 15, 10, 30), L(2026, 6, 15, 12)),
    ], [], ahora);
    expect(r.huecoMin).toBe(-30);
  });

  test("los de todo el día nunca son lo siguiente", () => {
    const r = proximoCompromiso([
      ev("todo", L(2026, 6, 16, 0), L(2026, 6, 17, 0), { isAllDay: true }),
      { id: "sin-hora", title: "Fecha suelta", start: "2026-06-16", end: "2026-06-17" },
    ], [], ahora);
    expect(r.siguiente).toBeNull();
  });

  test("lo que ya ha acabado queda fuera", () => {
    const r = proximoCompromiso([
      ev("pasado", L(2026, 6, 15, 8), L(2026, 6, 15, 9)),
      ev("justo", L(2026, 6, 15, 9), L(2026, 6, 15, 10)),   // fin == ahora
    ], [], ahora);
    expect(r).toEqual({ actual: null, siguiente: null, huecoMin: null });
  });

  test("clases mezcladas con eventos; a la misma hora, primero el evento", () => {
    const clases = [ev("clase-1", L(2026, 6, 15, 12), L(2026, 6, 15, 14))];
    const eventos = [ev("evento-1", L(2026, 6, 15, 12), L(2026, 6, 15, 13))];
    const r = proximoCompromiso(eventos, clases, ahora);
    expect(r.siguiente.id).toBe("evento-1");
    expect(r.siguiente.tipo).toBe("evento");
    const soloClase = proximoCompromiso([ev("tarde", L(2026, 6, 15, 18), L(2026, 6, 15, 19))], clases, ahora);
    expect(soloClase.siguiente.id).toBe("clase-1");
    expect(soloClase.siguiente.tipo).toBe("clase");
  });

  test("las entregas no son lo siguiente si se pasa el marcador", () => {
    const eventos = [
      ev("entrega", L(2026, 6, 15, 11), L(2026, 6, 15, 11, 30), { title: "📚 Práctica 3" }),
      ev("reunion", L(2026, 6, 16, 9), L(2026, 6, 16, 10)),
    ];
    expect(proximoCompromiso(eventos, [], ahora, { marcadorEntregas: "📚" }).siguiente.id).toBe("reunion");
    // Sin marcador (quien no lo pase) se comporta como antes.
    expect(proximoCompromiso(eventos, [], ahora).siguiente.id).toBe("entrega");
  });

  test("un duplicado por id cuenta una sola vez", () => {
    const e = ev("dup", L(2026, 6, 15, 9, 30), L(2026, 6, 15, 10, 30));
    const r = proximoCompromiso([e], [{ ...e }], ahora);
    expect(r.actual.id).toBe("dup");
    expect(r.actual.tipo).toBe("evento");
    expect(r.siguiente).toBeNull();
  });

  test("un evento que cruza la medianoche sigue en curso a las 00:30", () => {
    const r = proximoCompromiso([
      ev("fiesta", L(2026, 6, 15, 22), L(2026, 6, 16, 2)),
    ], [], L(2026, 6, 16, 0, 30));
    expect(r.actual.id).toBe("fiesta");
  });

  test("más allá de 7 días queda fuera", () => {
    const r = proximoCompromiso([
      ev("lejos", L(2026, 6, 22, 10, 1), L(2026, 6, 22, 11)),
    ], [], ahora);
    expect(r.siguiente).toBeNull();
    const cerca = proximoCompromiso([
      ev("cerca", L(2026, 6, 22, 9, 59), L(2026, 6, 22, 11)),
    ], [], ahora);
    expect(cerca.siguiente.id).toBe("cerca");
  });

  test("una fecha que no se puede parsear se ignora", () => {
    const r = proximoCompromiso([
      { id: "roto", title: "Roto", start: "no es fecha 10:00", end: "tampoco" },
      { id: "roto2", title: "Roto", start: "2026-06-15T25:99:00Z", end: "2026-06-15T26:00:00Z" },
      ev("bien", L(2026, 6, 15, 12), L(2026, 6, 15, 13)),
    ], [], ahora);
    expect(r.siguiente.id).toBe("bien");
  });
});

describe("cuentaAtras", () => {
  const desde = L(2026, 6, 15, 10, 0);   // lunes

  test("ahora, y también para lo que ya pasó", () => {
    expect(cuentaAtras(desde, new Date(desde.getTime() + 30000))).toBe("ahora");
    expect(cuentaAtras(desde, L(2026, 6, 15, 9, 0))).toBe("ahora");
  });

  test("minutos", () => {
    expect(cuentaAtras(desde, L(2026, 6, 15, 10, 12))).toBe("en 12 min");
    expect(cuentaAtras(desde, L(2026, 6, 15, 10, 1))).toBe("en 1 min");
  });

  test("horas exactas y con minutos, el mismo día", () => {
    expect(cuentaAtras(desde, L(2026, 6, 15, 12, 0))).toBe("en 2 h");
    expect(cuentaAtras(desde, L(2026, 6, 15, 11, 12))).toBe("en 1 h 12 min");
  });

  test("mañana, un día de la semana y una fecha lejana", () => {
    expect(cuentaAtras(desde, L(2026, 6, 16, 9, 0))).toBe("mañana, 09:00");
    // Menos de 24 h, pero otro día: también «mañana».
    expect(cuentaAtras(L(2026, 6, 15, 23, 0), L(2026, 6, 16, 8, 30))).toBe("mañana, 08:30");
    expect(cuentaAtras(desde, L(2026, 6, 18, 9, 0))).toBe("jueves, 09:00");
    expect(cuentaAtras(desde, L(2026, 10, 12, 9, 0))).toBe("12 oct, 09:00");
  });

  test("acepta ISO además de Date", () => {
    expect(cuentaAtras(iso(desde), iso(L(2026, 6, 15, 10, 12)))).toBe("en 12 min");
  });

  test("el domingo de cambio de hora se mide por tiempo real", () => {
    // 25 de octubre de 2026: en Europa el reloj vuelve de 3:00 a 2:00. Dos horas
    // REALES después de la 1:00 son «en 2 h», aunque el reloj de pared diga otra cosa.
    const d = L(2026, 10, 25, 1, 0);
    expect(cuentaAtras(d, new Date(d.getTime() + 2 * 3600000))).toBe("en 2 h");
  });
});

describe("faltaPara", () => {
  const desde = L(2026, 6, 15, 10, 0);
  test("minutos y horas", () => {
    expect(faltaPara(desde, L(2026, 6, 15, 10, 20))).toBe("acaba en 20 min");
    expect(faltaPara(desde, L(2026, 6, 15, 10, 1))).toBe("acaba en 1 min");
    expect(faltaPara(desde, L(2026, 6, 15, 11, 5))).toBe("acaba en 1 h 5 min");
    expect(faltaPara(desde, L(2026, 6, 15, 12, 0))).toBe("acaba en 2 h");
  });
});

describe("textoHueco", () => {
  test("solape, justo después y tiempo libre", () => {
    expect(textoHueco(-10)).toBe("se solapa con lo actual");
    expect(textoHueco(0)).toBe("justo después");
    expect(textoHueco(4)).toBe("justo después");
    expect(textoHueco(5)).toBe("te quedan 5 min libres");
    expect(textoHueco(40)).toBe("te quedan 40 min libres");
  });

  test("singular y plural según la primera cifra", () => {
    expect(textoHueco(60)).toBe("te queda 1 h libre");
    expect(textoHueco(70)).toBe("te queda 1 h 10 min libre");
    expect(textoHueco(120)).toBe("te quedan 2 h libres");
    expect(textoHueco(135)).toBe("te quedan 2 h 15 min libres");
  });

  test("sin hueco no dice nada", () => {
    expect(textoHueco(null)).toBe("");
  });
});

describe("textoErrorRuta", () => {
  test("siempre con el sitio, y el motivo solo si no es el genérico", () => {
    expect(textoErrorRuta("Aula 3", "No se pudo calcular la ruta")).toBe("No se pudo calcular la ruta a «Aula 3»");
    expect(textoErrorRuta("Aula 3", undefined)).toBe("No se pudo calcular la ruta a «Aula 3»");
    expect(textoErrorRuta("Aula 3", [{ msg: "x" }])).toBe("No se pudo calcular la ruta a «Aula 3»");
    expect(textoErrorRuta("Aula 3", "No se pudo consultar Google Maps"))
      .toBe("No se pudo calcular la ruta a «Aula 3» (No se pudo consultar Google Maps)");
  });
});

describe("faseSalida", () => {
  const ahora = L(2026, 6, 15, 10, 0);
  const empieza = L(2026, 6, 15, 11, 0);
  const salidaEn = min => new Date(ahora.getTime() + min * MIN);

  test("sin salida no hay fase", () => {
    expect(faseSalida({ salida: null, empieza, ahora })).toBeNull();
    expect(faseSalida({ empieza, ahora })).toBeNull();
  });

  test("holgado por encima de 15 min", () => {
    expect(faseSalida({ salida: salidaEn(16), empieza, ahora })).toMatchObject({
      fase: "holgado", minutos: 16, texto: "sal en 16 min",
    });
    expect(faseSalida({ salida: salidaEn(65), empieza: L(2026, 6, 15, 12), ahora }).texto).toBe("sal en 1 h 5 min");
  });

  test("pronto de 15 a 1 min", () => {
    expect(faseSalida({ salida: salidaEn(15), empieza, ahora })).toMatchObject({ fase: "pronto", texto: "sal en 15 min" });
    expect(faseSalida({ salida: salidaEn(9), empieza, ahora }).texto).toBe("sal en 9 min");
    expect(faseSalida({ salida: salidaEn(1), empieza, ahora }).fase).toBe("pronto");
  });

  test("ya y tarde", () => {
    expect(faseSalida({ salida: salidaEn(0), empieza, ahora })).toMatchObject({ fase: "ya", minutos: 0, texto: "sal ya" });
    expect(faseSalida({ salida: salidaEn(-1), empieza, ahora })).toMatchObject({ fase: "tarde", texto: "vas 1 min tarde" });
    expect(faseSalida({ salida: salidaEn(-6), empieza, ahora }).texto).toBe("vas 6 min tarde");
  });

  test("en curso: el evento ya empezó", () => {
    expect(faseSalida({ salida: salidaEn(-30), empieza: ahora, ahora })).toMatchObject({
      fase: "en_curso", minutos: 0, texto: "",
    });
  });

  test("el porcentaje va de 0 a 1 sobre la última hora", () => {
    expect(faseSalida({ salida: salidaEn(120), empieza: L(2026, 6, 15, 13), ahora }).porcentaje).toBe(1);
    expect(faseSalida({ salida: salidaEn(30), empieza, ahora }).porcentaje).toBeCloseTo(0.5);
    expect(faseSalida({ salida: salidaEn(-10), empieza, ahora }).porcentaje).toBe(0);
  });

  test("acepta ISO", () => {
    expect(faseSalida({ salida: iso(salidaEn(9)), empieza: iso(empieza), ahora }).fase).toBe("pronto");
  });
});

describe("recordarModo y modoPara", () => {
  test("recuerda por evento y el último como respaldo", () => {
    let m = recordarModo({}, "ev-1", "walking");
    expect(m).toEqual({ porEvento: { "ev-1": "walking" }, ultimo: "walking" });
    m = recordarModo(m, "ev-2", "driving");
    expect(modoPara(m, "ev-1")).toBe("walking");
    expect(modoPara(m, "ev-2")).toBe("driving");
    expect(modoPara(m, "otro")).toBe("driving");   // el último
  });

  test("es puro: no toca el mapa de entrada", () => {
    const antes = { porEvento: { a: "driving" }, ultimo: "driving" };
    recordarModo(antes, "a", "walking");
    expect(antes).toEqual({ porEvento: { a: "driving" }, ultimo: "driving" });
  });

  test("se poda a las últimas 50 claves, contando la reelegida como nueva", () => {
    let m = {};
    for (let i = 0; i < 60; i++) m = recordarModo(m, `ev-${i}`, "driving");
    expect(Object.keys(m.porEvento)).toHaveLength(50);
    expect(m.porEvento["ev-9"]).toBeUndefined();
    expect(m.porEvento["ev-10"]).toBe("driving");
    m = recordarModo(m, "ev-10", "walking");
    m = recordarModo(m, "nuevo", "driving");
    expect(m.porEvento["ev-10"]).toBe("walking");
    expect(m.porEvento["ev-11"]).toBeUndefined();
    expect(Object.keys(recordarModo({}, "x", "walking", 3).porEvento)).toHaveLength(1);
  });

  test("sin memoria cae al último y luego a coche", () => {
    expect(modoPara(null, "x")).toBe("driving");
    expect(modoPara({}, "x")).toBe("driving");
    expect(modoPara({ ultimo: "walking" }, "x")).toBe("walking");
    expect(modoPara({ porEvento: "basura", ultimo: "walking" }, "x")).toBe("walking");
  });
});
