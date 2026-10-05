import { describe, test, expect } from "vitest";
import {
  lugarDePresencia, ordenarPorLugar, reordenaEn, etiquetaTramo, notaPresenciaAhora,
} from "../../src/lib/lugares";

const vigente = (lugar, extra = {}) => ({ conocida: true, vigente: true, lugar, ...extra });

describe("lugarDePresencia", () => {
  test("solo los tres sitios con nombre, y solo con el dato vigente", () => {
    expect(lugarDePresencia(vigente("uni"))).toBe("uni");
    expect(lugarDePresencia(vigente("gimnasio"))).toBe("gimnasio");
    expect(lugarDePresencia(vigente("casa"))).toBe("casa");
    expect(lugarDePresencia(vigente("fuera"))).toBe(null);
    // Caducado: «hace seis horas en la uni» no es estar en la uni.
    expect(lugarDePresencia({ ...vigente("uni"), vigente: false })).toBe(null);
    expect(lugarDePresencia({ conocida: false })).toBe(null);
    expect(lugarDePresencia(null)).toBe(null);
  });
});

describe("ordenarPorLugar", () => {
  const IDS = ["jarvis", "training", "casa", "timeline", "ideas", "entregas", "siguiente"];

  test("en la uni sube lo de clase, baja la casa y Jarvis sigue el primero", () => {
    expect(ordenarPorLugar(IDS, "uni")).toEqual(
      ["jarvis", "siguiente", "timeline", "entregas", "training", "ideas", "casa"]);
  });

  test("en el gimnasio sube el entrenamiento", () => {
    const orden = ordenarPorLugar(IDS, "gimnasio");
    expect(orden.slice(0, 3)).toEqual(["jarvis", "training", "siguiente"]);
    expect(orden.slice(-2)).toEqual(["casa", "entregas"]);
  });

  test("en casa o sin saberlo, tal cual", () => {
    expect(ordenarPorLugar(IDS, "casa")).toEqual(IDS);
    expect(ordenarPorLugar(IDS, null)).toEqual(IDS);
    expect(reordenaEn("casa")).toBe(false);
    expect(reordenaEn("uni")).toBe(true);
  });

  test("no inventa ni pierde widgets", () => {
    const orden = ordenarPorLugar(["ideas", "casa"], "uni");
    expect([...orden].sort()).toEqual(["casa", "ideas"]);
  });
});

describe("etiquetas", () => {
  test("de cada tramo", () => {
    expect(etiquetaTramo({ en_casa: true })).toBe("En casa");
    expect(etiquetaTramo({ en_casa: false, lugar: "uni" })).toBe("Uni");
    expect(etiquetaTramo({ en_casa: false, lugar: "gimnasio" })).toBe("Gimnasio");
    expect(etiquetaTramo({ en_casa: false })).toBe("Fuera");
  });

  test("la nota del carril de hoy", () => {
    expect(notaPresenciaAhora(vigente("gimnasio", { en_casa: false }))).toBe("ahora en el gimnasio");
    expect(notaPresenciaAhora(vigente("fuera", { en_casa: false }))).toBe("ahora fuera");
    expect(notaPresenciaAhora({ conocida: true, vigente: false, en_casa: true, lugar: "casa" }))
      .toBe("ahora en casa");
    expect(notaPresenciaAhora({ conocida: false })).toBe("");
  });
});
