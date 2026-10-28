import { describe, it, expect } from "vitest";
import {
  estadoHud, nombreModelo, motorEsperado, protocolosUsados, nombreProtocolo,
  trocearRespuesta, duracionTecleo, textoDuracion,
} from "../../src/lib/jarvisHud";

describe("estadoHud", () => {
  it("la llamada manda sobre todo lo demás", () => {
    expect(estadoHud({ enLlamada: true, faseLlamada: "hablando", pensando: true })).toBe("hablando");
    expect(estadoHud({ enLlamada: true, faseLlamada: "rara" })).toBe("escuchando");
  });

  it("pensando, luego lo que espera permiso, luego el micro y la voz", () => {
    expect(estadoHud({ pensando: true, pendiente: true })).toBe("pensando");
    expect(estadoHud({ pendiente: true, escuchando: true })).toBe("alerta");
    expect(estadoHud({ escuchando: true, hablando: true })).toBe("escuchando");
    expect(estadoHud({ hablando: true })).toBe("hablando");
    expect(estadoHud({})).toBe("reposo");
  });
});

describe("nombreModelo", () => {
  it("traduce los ids de Claude y deja lo demás tal cual", () => {
    expect(nombreModelo("claude-opus-5-5")).toBe("Opus 5.5");
    expect(nombreModelo("claude-sonnet-5-5")).toBe("Sonnet 5.5");
    expect(nombreModelo("gpt-5-mini")).toBe("gpt-5-mini");
    expect(nombreModelo("")).toBe("");
    expect(nombreModelo(undefined)).toBe("");
  });
});

describe("motorEsperado", () => {
  it("dice lo pedido mientras no haya turnos", () => {
    expect(motorEsperado({ potente: true })).toEqual({ nombre: "Opus 5.5", nota: "" });
    expect(motorEsperado({ potente: false })).toEqual({ nombre: "Sonnet 5.5", nota: "" });
  });

  it("si se pidió potencia y contestó otro, el servicio no está actualizado y se dice", () => {
    const r = motorEsperado({ potente: true, ultimo: { motor: "claude", modelo: "claude-sonnet-5-5", potente: true } });
    expect(r.nombre).toBe("Sonnet 5.5");
    expect(r.nota).toMatch(/caja/);
  });

  it("un turno viejo sin potencia no cuenta como prueba de nada", () => {
    const r = motorEsperado({ potente: true, ultimo: { motor: "claude", modelo: "claude-sonnet-5-5", potente: false } });
    expect(r).toEqual({ nombre: "Opus 5.5", nota: "" });
  });

  it("avisa si contestó el respaldo", () => {
    expect(motorEsperado({ potente: false, ultimo: { motor: "openai" } }).nota).toMatch(/respaldo/);
  });
});

describe("protocolosUsados", () => {
  it("del más reciente al más antiguo, sin repetir y con cuántas veces", () => {
    const mensajes = [
      { rol: "assistant", herramientas: ["agenda", "clima"] },
      { rol: "user", texto: "x" },
      { rol: "assistant", herramientas: ["salud", "agenda"] },
    ];
    expect(protocolosUsados(mensajes)).toEqual([
      { nombre: "salud", veces: 1 }, { nombre: "agenda", veces: 2 }, { nombre: "clima", veces: 1 },
    ]);
    expect(protocolosUsados(mensajes, 1)).toHaveLength(1);
    expect(protocolosUsados([])).toEqual([]);
  });

  it("nombreProtocolo lo pone en mayúsculas de HUD", () => {
    expect(nombreProtocolo("agenda_semana")).toBe("AGENDA SEMANA");
  });
});

describe("trocearRespuesta", () => {
  it("párrafos, listas, títulos y negritas, como datos y no como HTML", () => {
    const b = trocearRespuesta("## Hoy\nTiene **dos** cosas:\n- Gimnasio a las 18:00\n- Cena\n\n<b>no</b>");
    expect(b[0]).toEqual({ tipo: "titulo", trozos: [{ texto: "Hoy", fuerte: false }] });
    expect(b[1].trozos).toEqual([
      { texto: "Tiene ", fuerte: false }, { texto: "dos", fuerte: true }, { texto: " cosas:", fuerte: false },
    ]);
    expect(b[2].tipo).toBe("lista");
    expect(b[2].items).toHaveLength(2);
    // Lo que parezca HTML se queda en texto: lo pinta React como texto.
    expect(b[3].trozos[0].texto).toBe("<b>no</b>");
  });

  it("las listas numeradas también, y una línea en blanco corta la lista", () => {
    const b = trocearRespuesta("1. uno\n2) dos\n\n- tres");
    expect(b.map(x => x.tipo)).toEqual(["lista", "lista"]);
    expect(b[0].items).toHaveLength(2);
  });

  it("vacío no da bloques", () => {
    expect(trocearRespuesta("")).toEqual([]);
    expect(trocearRespuesta(null)).toEqual([]);
  });
});

describe("tiempos", () => {
  it("el tecleo tiene tope", () => {
    expect(duracionTecleo("hola")).toBe(36);
    expect(duracionTecleo("x".repeat(10000))).toBe(1600);
  });

  it("textoDuracion", () => {
    expect(textoDuracion(850)).toBe("850 ms");
    expect(textoDuracion(12430)).toBe("12,4 s");
    expect(textoDuracion(undefined)).toBe("");
  });
});
