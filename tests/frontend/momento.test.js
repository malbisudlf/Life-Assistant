import { describe, test, expect } from "vitest";
import {
  franjaDelDia, saludoDeFranja, jornadaObjetivo, cuantoFalta, momentoDelDia, destinoDeWidget,
} from "../../src/lib/momento";

// El reloj va SIEMPRE inyectado y en hora local: el 28/09/2026 es lunes y queda lejos
// de los dos cambios de hora, así que la suite da igual en la máquina en que corra.
const a = (H, M = 0, dia = 28) => new Date(2026, 8, dia, H, M);
const HOY    = "2026-09-28";
const AYER   = "2026-09-27";
const MANANA = "2026-09-29";

// Un evento con horas locales (sin zona: se parsea como hora de pared, igual que Graph).
function ev(titulo, ini, fin, extra = {}) {
  return { id: `id-${titulo}-${ini}`, title: titulo, start: ini, end: fin, isAllDay: false, location: "", ...extra };
}
const t = (dia, hhmm) => `${dia}T${hhmm}:00`;

// Entrada base: todo cargado y vacío. Cada test cambia lo suyo.
function entrada(extra = {}) {
  return {
    ahora: a(10), eventos: [], clases: [], marcadorEntregas: "📚",
    cargandoAgenda: false, sinAgenda: false,
    alarmas: [], parteNoche: {}, healthData: {}, healthCargando: false,
    reloj: null, clima: null, salidas: {},
    ...extra,
  };
}

describe("franjaDelDia", () => {
  test.each([
    [5, 59, "noche"], [6, 0, "manana"], [12, 59, "manana"], [13, 0, "tarde"],
    [19, 59, "tarde"], [20, 0, "noche"], [23, 59, "noche"], [0, 0, "noche"],
  ])("%i:%i → %s", (h, m, esperado) => {
    expect(franjaDelDia(a(h, m))).toBe(esperado);
  });
});

describe("saludoDeFranja conserva los cortes de siempre", () => {
  test("12:59 días, 13:00 tardes, 19:59 tardes, 20:00 noches", () => {
    expect(saludoDeFranja(a(12, 59))).toBe("Buenos días");
    expect(saludoDeFranja(a(13, 0))).toBe("Buenas tardes");
    expect(saludoDeFranja(a(19, 59))).toBe("Buenas tardes");
    expect(saludoDeFranja(a(20, 0))).toBe("Buenas noches");
  });
});

describe("jornadaObjetivo", () => {
  test("a las 22:00 es mañana, a las 02:00 y a las 10:00 es hoy", () => {
    expect(jornadaObjetivo(a(22))).toBe(MANANA);
    expect(jornadaObjetivo(a(2))).toBe(HOY);
    expect(jornadaObjetivo(a(10))).toBe(HOY);
  });
  test("el último día del mes salta al mes siguiente", () => {
    expect(jornadaObjetivo(new Date(2026, 8, 30, 21))).toBe("2026-10-01");
  });
});

describe("cuantoFalta", () => {
  const ahora = a(10);
  const mas = ms => new Date(ahora.getTime() + ms);
  test("menos de un minuto → ya", () => {
    expect(cuantoFalta(mas(30_000), ahora)).toBe("ya");
  });
  test("minutos por debajo de la hora", () => {
    expect(cuantoFalta(mas(25 * 60_000), ahora)).toBe("en 25 min");
    expect(cuantoFalta(mas(59 * 60_000), ahora)).toBe("en 59 min");
  });
  test("a partir de la hora, hora de reloj", () => {
    expect(cuantoFalta(mas(61 * 60_000), ahora)).toBe("a las 11:01");
  });
});

describe("momentoDelDia: la frase", () => {
  test("un evento en curso gana al siguiente, que sale como chip «Luego»", () => {
    const m = momentoDelDia(entrada({
      ahora: a(10, 15),
      eventos: [ev("Reunión A", t(HOY, "10:00"), t(HOY, "11:00")), ev("Comida", t(HOY, "14:00"), t(HOY, "15:00"))],
    }));
    expect(m.frase).toBe("Ahora: Reunión A hasta las 11:00.");
    expect(m.chips[0]).toMatchObject({ texto: "Luego 14:00 · Comida", widget: "timeline" });
    expect(m.titulo).toBe("Ahora · Reunión A — Life Assistant");
  });

  test("siguiente hoy en minutos, con la hora de salida ya calculada", () => {
    const e = ev("Médico", t(HOY, "10:25"), t(HOY, "11:00"));
    const m = momentoDelDia(entrada({ eventos: [e], salidas: { [e.id]: { departure_time: "09:35" } } }));
    expect(m.frase).toBe("Médico en 25 min · sal a las 09:35.");
    expect(m.titulo).toBe("10:25 · Médico — Life Assistant");
  });

  test("una salida con error no se enseña", () => {
    const e = ev("Médico", t(HOY, "17:00"), t(HOY, "18:00"));
    const m = momentoDelDia(entrada({ eventos: [e], salidas: { [e.id]: { departure_time: "16:30", error: "Error al calcular" } } }));
    expect(m.frase).toBe("Médico a las 17:00.");
  });

  test("sin id, la salida se busca por la hora de inicio, como en el widget", () => {
    const e = { ...ev("Clase", t(HOY, "10:40"), t(HOY, "12:00")), id: undefined };
    const m = momentoDelDia(entrada({ eventos: [e], salidas: { [e.start]: { departure_time: "10:10" } } }));
    expect(m.frase).toBe("Clase en 40 min · sal a las 10:10.");
  });

  test("los de todo el día y las entregas no son «lo siguiente»", () => {
    const m = momentoDelDia(entrada({
      eventos: [
        ev("Festivo", t(HOY, "00:00"), t(MANANA, "00:00"), { isAllDay: true }),
        ev("📚 Práctica 3", t(HOY, "10:30"), t(HOY, "10:30")),
        ev("Dentista", t(HOY, "12:00"), t(HOY, "12:30")),
      ],
    }));
    expect(m.frase).toBe("Dentista a las 12:00.");
  });

  test("lo que no trae fechas parseables se ignora", () => {
    const m = momentoDelDia(entrada({ eventos: [ev("Roto", "no-es-fecha", ""), ev("Bien", t(HOY, "15:00"), t(HOY, "16:00"))] }));
    expect(m.frase).toBe("Bien a las 15:00.");
  });

  test("una clase mezclada con eventos se ordena por hora", () => {
    const m = momentoDelDia(entrada({
      eventos: [ev("Reunión", t(HOY, "13:00"), t(HOY, "14:00"))],
      clases:  [ev("Álgebra", t(HOY, "11:00"), t(HOY, "12:00"))],
    }));
    expect(m.frase).toBe("Álgebra a las 11:00.");
  });

  test("a las 21:00, un evento de hoy a las 21:30 gana al primero de mañana", () => {
    const m = momentoDelDia(entrada({
      ahora: a(21),
      eventos: [ev("Llamada", t(HOY, "21:30"), t(HOY, "22:00")), ev("Clase", t(MANANA, "08:00"), t(MANANA, "10:00"))],
    }));
    expect(m.frase).toBe("Llamada en 30 min.");
  });

  test("a las 23:00 sin nada más hoy habla de mañana; a las 02:00, de hoy", () => {
    const manana = momentoDelDia(entrada({ ahora: a(23), eventos: [ev("Clase", t(MANANA, "08:00"), t(MANANA, "10:00"))] }));
    expect(manana.frase).toBe("Mañana empiezas a las 08:00 con Clase.");
    expect(manana.titulo).toBe("Life Assistant");

    const hoy = momentoDelDia(entrada({ ahora: a(2, 0, 29), eventos: [ev("Clase", t(MANANA, "08:00"), t(MANANA, "10:00"))] }));
    expect(hoy.frase).toBe("Hoy empiezas a las 08:00 con Clase.");
  });

  test("de noche sin nada en la jornada lo dice, con Mañana u Hoy según la hora", () => {
    expect(momentoDelDia(entrada({ ahora: a(22) })).frase).toBe("Mañana no tienes nada en la agenda.");
    expect(momentoDelDia(entrada({ ahora: a(3) })).frase).toBe("Hoy no tienes nada en la agenda.");
  });

  test("cruce de medianoche: los mismos datos a las 23:59 y a las 00:00", () => {
    const eventos = [ev("Examen", t(MANANA, "09:00"), t(MANANA, "11:00"))];
    expect(momentoDelDia(entrada({ ahora: a(23, 59), eventos })).frase).toBe("Mañana empiezas a las 09:00 con Examen.");
    expect(momentoDelDia(entrada({ ahora: new Date(2026, 8, 29, 0, 0), eventos })).frase).toBe("Hoy empiezas a las 09:00 con Examen.");
  });

  test("cargando la agenda: frase vacía y título neutro", () => {
    const m = momentoDelDia(entrada({ cargandoAgenda: true, eventos: [ev("X", t(HOY, "11:00"), t(HOY, "12:00"))] }));
    expect(m.saludo).toBe("Buenos días");
    expect(m.frase).toBe("");
    expect(m.chips).toEqual([]);
    expect(m.titulo).toBe("Life Assistant");
  });

  test("sin Outlook dice que no lo sabe, nunca que no hay nada", () => {
    for (const hora of [a(10), a(16), a(22), a(3)]) {
      const m = momentoDelDia(entrada({ ahora: hora, sinAgenda: true }));
      expect(m.frase).toBe("Outlook sin conectar: no sé qué tienes hoy.");
      expect(m.frase).not.toMatch(/no tienes nada/);
      expect(m.chips[0]).toMatchObject({ texto: "Conectar Outlook", widget: "timeline" });
      expect(m.titulo).toBe("Life Assistant");
    }
  });

  test("tarde sin nada pendiente: distingue si hubo algo hoy, y ofrece el primero de mañana", () => {
    const manana = ev("Dentista", t(MANANA, "09:30"), t(MANANA, "10:00"));
    const conAlgo = momentoDelDia(entrada({ ahora: a(17), eventos: [ev("Reunión", t(HOY, "10:00"), t(HOY, "11:00")), manana] }));
    expect(conAlgo.frase).toBe("No te queda nada más hoy.");
    expect(conAlgo.chips[0]).toMatchObject({ texto: "Mañana 09:30 · Dentista", widget: "upcoming" });

    const sinNada = momentoDelDia(entrada({ ahora: a(17), eventos: [manana] }));
    expect(sinNada.frase).toBe("Hoy no tienes nada en la agenda.");
  });

  test("por la mañana no se ofrece el chip de mañana", () => {
    const m = momentoDelDia(entrada({ ahora: a(11), eventos: [ev("Dentista", t(MANANA, "09:30"), t(MANANA, "10:00"))] }));
    expect(m.chips).toEqual([]);
  });

  test("un título de más de 40 caracteres se recorta con «…»", () => {
    const largo = "Reunión de seguimiento trimestral con todo el equipo de producto";
    const m = momentoDelDia(entrada({ eventos: [ev(largo, t(HOY, "12:00"), t(HOY, "13:00"))] }));
    const recortado = m.frase.replace(" a las 12:00.", "");
    expect(Array.from(recortado)).toHaveLength(40);
    expect(recortado.endsWith("…")).toBe(true);
  });

  test("sin título sale «(Sin título)»", () => {
    const m = momentoDelDia(entrada({ eventos: [ev("", t(HOY, "12:00"), t(HOY, "13:00"))] }));
    expect(m.frase).toBe("(Sin título) a las 12:00.");
  });
});

describe("momentoDelDia: la alarma sonando lo tapa todo", () => {
  test.each(["avisada", "escalada"])("estado %s", estado => {
    const m = momentoDelDia(entrada({
      ahora: a(7),
      alarmas: [{ id: 1, estado, cuando: `${HOY} 07:00` }],
      eventos: [ev("Reunión", t(HOY, "09:00"), t(HOY, "10:00"))],
      parteNoche: { fecha: HOY, items: [{ area: "correo", estado: "pendiente" }] },
      clima: { daily: [{ date: HOY, precip_prob: 90 }] },
    }));
    expect(m.frase).toBe("La alarma está sonando: confirma que estás despierto.");
    expect(m.tono).toBe("alerta");
    expect(m.chips).toEqual([{ id: "alarma-sonando", texto: "⏰ Estoy despierto", widget: "alarmas", tono: "alerta" }]);
    expect(m.titulo).toBe("⏰ Alarma — Life Assistant");
  });
});

describe("momentoDelDia: chips secundarios", () => {
  const sueno = (date, extra = {}) => ({ date, value: 7.5, extra });

  test("sueño: la noche de hoy da las horas", () => {
    const m = momentoDelDia(entrada({ ahora: a(8), healthData: { sleep_analysis: [sueno(AYER), sueno(HOY)] } }));
    expect(m.chips).toContainEqual({ id: "sueno", texto: "😴 7 h 30", widget: "health_sleep", tono: "normal" });
  });

  test("sueño: sin noche de hoy y el reloj sin_reloj → no midió", () => {
    const m = momentoDelDia(entrada({
      ahora: a(8), healthData: { sleep_analysis: [sueno(AYER)] }, reloj: { dias: { [HOY]: "sin_reloj" } },
    }));
    expect(m.chips.map(c => c.texto)).toContain("😴 El reloj no midió anoche");
  });

  test("sueño: sin_datos es «no se sabe» y no dice nada", () => {
    const m = momentoDelDia(entrada({
      ahora: a(8), healthData: { sleep_analysis: [sueno(AYER)] }, reloj: { dias: { [HOY]: "sin_datos" } },
    }));
    expect(m.chips.find(c => c.id === "sueno")).toBeUndefined();
  });

  test("sueño: mientras carga la salud, nada", () => {
    const m = momentoDelDia(entrada({ ahora: a(8), healthCargando: true, healthData: { sleep_analysis: [sueno(HOY)] } }));
    expect(m.chips.find(c => c.id === "sueno")).toBeUndefined();
  });

  test("sueño: una noche anulada se salta", () => {
    const m = momentoDelDia(entrada({
      ahora: a(8), healthData: { sleep_analysis: [sueno(AYER), sueno(HOY, { excluded: true })] },
    }));
    expect(m.chips.find(c => c.id === "sueno")).toBeUndefined();
  });

  test("sueño: solo por la mañana", () => {
    const m = momentoDelDia(entrada({ ahora: a(15), healthData: { sleep_analysis: [sueno(HOY)] } }));
    expect(m.chips.find(c => c.id === "sueno")).toBeUndefined();
  });

  test("lluvia: 50 % sí, 49 % no", () => {
    const con = momentoDelDia(entrada({ clima: { daily: [{ date: HOY, precip_prob: 50 }] } }));
    expect(con.chips).toContainEqual({ id: "lluvia", texto: "🌧️ Lluvia 50 %", widget: "weather", tono: "normal" });
    const sin = momentoDelDia(entrada({ clima: { daily: [{ date: HOY, precip_prob: 49 }] } }));
    expect(sin.chips.find(c => c.id === "lluvia")).toBeUndefined();
  });

  test("lluvia: de noche mira el día de mañana", () => {
    const m = momentoDelDia(entrada({
      ahora: a(22), clima: { daily: [{ date: HOY, precip_prob: 10 }, { date: MANANA, precip_prob: 70 }] },
    }));
    expect(m.chips.map(c => c.texto)).toContain("🌧️ Mañana lluvia 70 %");
  });

  test("lluvia: sin fechas en la previsión, por posición", () => {
    const m = momentoDelDia(entrada({ ahora: a(22), clima: { daily: [{ precip_prob: 10 }, { precip_prob: 60 }] } }));
    expect(m.chips.map(c => c.texto)).toContain("🌧️ Mañana lluvia 60 %");
  });

  test("lluvia: sin clima, nada", () => {
    expect(momentoDelDia(entrada({ clima: null })).chips).toEqual([]);
    expect(momentoDelDia(entrada({ clima: { temp: 20 } })).chips).toEqual([]);
  });

  test("alarma de noche: la armada más temprana, ignorando las que no están armadas", () => {
    const m = momentoDelDia(entrada({
      ahora: a(22),
      alarmas: [
        { id: 1, estado: "armada", cuando: `${MANANA} 08:30` },
        { id: 2, estado: "confirmada", cuando: `${MANANA} 06:00` },
        { id: 3, estado: "armada", cuando: `${MANANA} 07:15` },
      ],
    }));
    expect(m.chips).toContainEqual({ id: "alarma", texto: "⏰ mañana a las 07:15", widget: "alarmas", tono: "normal" });
  });

  test("alarma: sin cargar o sin ninguna armada, no hay chip", () => {
    expect(momentoDelDia(entrada({ ahora: a(22), alarmas: null })).chips).toEqual([]);
    expect(momentoDelDia(entrada({ ahora: a(22), alarmas: [] })).chips).toEqual([]);
  });

  test("alarma: de día no se enseña", () => {
    const m = momentoDelDia(entrada({ ahora: a(10), alarmas: [{ estado: "armada", cuando: `${MANANA} 07:00` }] }));
    expect(m.chips).toEqual([]);
  });

  test("parte de noche: pendientes de hoy sí; de ayer, sin pendientes o sin cargar, no", () => {
    const items = [{ area: "correo", estado: "pendiente" }, { area: "codigo", estado: "pendiente" }, { area: "agenda", estado: "aprobado" }];
    const hoy = momentoDelDia(entrada({ parteNoche: { fecha: HOY, items } }));
    expect(hoy.chips).toContainEqual({ id: "parte", texto: "🌙 Anoche: 2 pendientes", widget: "noche", tono: "normal" });
    const uno = momentoDelDia(entrada({ parteNoche: { fecha: HOY, items: items.slice(0, 1) } }));
    expect(uno.chips[0].texto).toBe("🌙 Anoche: 1 pendiente");

    expect(momentoDelDia(entrada({ parteNoche: { fecha: AYER, items } })).chips).toEqual([]);
    expect(momentoDelDia(entrada({ parteNoche: { fecha: HOY, items: items.slice(2) } })).chips).toEqual([]);
    expect(momentoDelDia(entrada({ parteNoche: null })).chips).toEqual([]);
    expect(momentoDelDia(entrada({ parteNoche: {} })).chips).toEqual([]);
  });

  test("los chips secundarios salen aunque la agenda aún esté cargando", () => {
    const m = momentoDelDia(entrada({ cargandoAgenda: true, clima: { daily: [{ date: HOY, precip_prob: 80 }] } }));
    expect(m.frase).toBe("");
    expect(m.chips.map(c => c.id)).toEqual(["lluvia"]);
  });

  test("nunca más de 3 chips, y el de la frase va primero", () => {
    const m = momentoDelDia(entrada({
      ahora: a(8, 30),
      eventos: [ev("Clase", t(HOY, "08:00"), t(HOY, "10:00")), ev("Tutoría", t(HOY, "12:00"), t(HOY, "12:30"))],
      parteNoche: { fecha: HOY, items: [{ area: "correo", estado: "pendiente" }] },
      healthData: { sleep_analysis: [{ date: HOY, value: 8 }] },
      clima: { daily: [{ date: HOY, precip_prob: 80 }] },
    }));
    expect(m.chips).toHaveLength(3);
    expect(m.chips.map(c => c.id)).toEqual(["luego", "parte", "sueno"]);
  });
});

describe("momentoDelDia: nunca revienta", () => {
  test("una entrada imposible devuelve solo el saludo", () => {
    const m = momentoDelDia({ ahora: a(10), eventos: [{ get title() { throw new Error("roto"); }, start: t(HOY, "11:00"), end: t(HOY, "12:00") }] });
    expect(m).toEqual({ saludo: "Buenos días", frase: "", tono: "normal", chips: [], titulo: "Life Assistant" });
  });
  test("sin entrada ni hora", () => {
    expect(momentoDelDia(undefined).titulo).toBe("Life Assistant");
  });
});

describe("destinoDeWidget", () => {
  const widgetConfig       = [{ id: "timeline", visible: true }, { id: "health_sleep", visible: false }];
  const simpleWidgetConfig = [{ id: "timeline", visible: true }, { id: "health_sleep", visible: true }];
  const pestanasSalud      = { health_sleep: "Sueño" };

  test("un widget oculto (o que no existe) no es destino", () => {
    expect(destinoDeWidget("health_sleep", { simpleMode: false, widgetConfig, simpleWidgetConfig, pestanasSalud })).toEqual({ visible: false });
    expect(destinoDeWidget("nada", { simpleMode: false, widgetConfig, simpleWidgetConfig, pestanasSalud })).toEqual({ visible: false });
  });

  test("en modo simple, un widget de salud pide cambiar de pestaña", () => {
    expect(destinoDeWidget("health_sleep", { simpleMode: true, widgetConfig, simpleWidgetConfig, pestanasSalud }))
      .toEqual({ visible: true, pestanaSalud: "health_sleep" });
  });

  test("fuera de la salud, o en modo completo, no hay pestaña", () => {
    expect(destinoDeWidget("timeline", { simpleMode: true, widgetConfig, simpleWidgetConfig, pestanasSalud }))
      .toEqual({ visible: true, pestanaSalud: null });
    expect(destinoDeWidget("timeline", { simpleMode: false, widgetConfig, simpleWidgetConfig, pestanasSalud }))
      .toEqual({ visible: true, pestanaSalud: null });
  });
});
