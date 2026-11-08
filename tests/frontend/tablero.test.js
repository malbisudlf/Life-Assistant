import { describe, it, expect } from "vitest";
import { llaveDelFragmento, esTablero, lineaTiempo, maquinas, textoWhatsapp } from "../../src/lib/tablero";

describe("tablero de la tele", () => {
  it("saca la llave del fragmento y nada más", () => {
    expect(llaveDelFragmento("#tele=abcdefghijklmnop_-12")).toBe("abcdefghijklmnop_-12");
    expect(llaveDelFragmento("#tele=corta")).toBe("");
    expect(llaveDelFragmento("#tele=abcdefghijklmnop&x=1")).toBe("");
    expect(llaveDelFragmento("")).toBe("");
  });

  it("sabe si esta carga es la del tablero", () => {
    expect(esTablero("#tele")).toBe(true);
    expect(esTablero("#tele=abcdefghijklmnopq")).toBe(true);
    expect(esTablero("#telefono")).toBe(false);
    expect(esTablero("")).toBe(false);
  });

  it("dice el tiempo en una línea, y la lluvia solo si la hay", () => {
    expect(lineaTiempo({ ahora: 12, min: 8, max: 17, lluvia_prob: 40 })).toBe("12 °C · 8–17 · lluvia 40 %");
    expect(lineaTiempo({ ahora: 12, min: 8, max: 17, lluvia_prob: 5 })).toBe("12 °C · 8–17");
    expect(lineaTiempo(null)).toBe("");
  });

  it("pinta las máquinas, y lo que no se sabe no es ni bien ni mal", () => {
    expect(maquinas({ caja: true, jacobo: false })).toEqual([
      { nombre: "caja", estado: "ok" }, { nombre: "jacobo", estado: "caida" }, { nombre: "la casa", estado: "nose" }]);
  });

  it("de WhatsApp solo cuántos", () => {
    expect(textoWhatsapp(0)).toBe("Nadie espera respuesta");
    expect(textoWhatsapp(1)).toBe("1 chat espera respuesta");
    expect(textoWhatsapp(3)).toBe("3 chats esperan respuesta");
    expect(textoWhatsapp(null)).toBe("");
  });
});
