import { describe, it, expect } from "vitest";
import { CortadorDeFrases, rmsDe, textoDeParcial, urlDelOido } from "../../src/lib/vozOido";

/** Pasa una serie de tramas de 64 ms y devuelve las decisiones. */
function pasar(cortador, rmsPorTrama) {
  return rmsPorTrama.map(r => cortador.trama(r, 64));
}

describe("CortadorDeFrases", () => {
  it("callado mientras no hables, empieza al oír voz sostenida y corta tras el silencio", () => {
    const c = new CortadorDeFrases({ arranqueMs: 120, silencioFinMs: 640 });
    const silencio = Array(5).fill(0.001);
    const voz      = Array(10).fill(0.1);
    const pausa    = Array(10).fill(0.001);
    const d = pasar(c, [...silencio, ...voz, ...pausa]);
    expect(d.slice(0, 5)).toEqual(Array(5).fill("callado"));
    // 64 ms no llegan a los 120 del arranque; a la segunda trama de voz, sí.
    expect(d[5]).toBe("callado");
    expect(d[6]).toBe("empieza");
    expect(d.slice(7, 15)).toEqual(Array(8).fill("sigue"));
    // 10 tramas de silencio = 640 ms: la décima cierra la frase.
    expect(d.slice(15, 24)).toEqual(Array(9).fill("sigue"));
    expect(d[24]).toBe("fin");
    expect(c.hablando).toBe(false);
  });

  it("un golpe suelto no abre frase", () => {
    const c = new CortadorDeFrases({ arranqueMs: 120 });
    expect(pasar(c, [0.001, 0.2, 0.001, 0.001])).toEqual(Array(4).fill("callado"));
  });

  it("una pausa corta a media frase no la corta", () => {
    const c = new CortadorDeFrases({ arranqueMs: 64, silencioFinMs: 750 });
    const d = pasar(c, [0.1, 0.1, ...Array(5).fill(0.001), 0.1, ...Array(5).fill(0.001)]);
    expect(d).not.toContain("fin");
  });

  it("una frase interminable se corta en el máximo", () => {
    const c = new CortadorDeFrases({ arranqueMs: 64, maxFraseMs: 640 });
    expect(pasar(c, Array(12).fill(0.1))).toContain("fin");
  });

  it("el umbral sube con el ruido de fondo y no con la voz", () => {
    const c = new CortadorDeFrases({ umbralMin: 0.01, factorRuido: 3 });
    pasar(c, Array(200).fill(0.008));   // un coche: ruido constante por debajo del suelo
    expect(c.umbral).toBeGreaterThan(0.02);
    const antes = c.umbral;
    pasar(c, Array(20).fill(0.3));      // hablar no lo mueve
    expect(c.umbral).toBe(antes);
  });
});

describe("utilidades del oído", () => {
  it("rmsDe", () => {
    expect(rmsDe(new Float32Array([0.5, -0.5]))).toBeCloseTo(0.5);
    expect(rmsDe(new Float32Array([]))).toBe(0);
  });

  it("textoDeParcial junta lo fijo y lo provisional", () => {
    expect(textoDeParcial({ fijo: "abre", provisional: " spotify " })).toBe("abre spotify");
    expect(textoDeParcial({})).toBe("");
  });

  it("urlDelOido pasa de http a ws", () => {
    expect(urlDelOido("https://api.ejemplo.test")).toBe("wss://api.ejemplo.test/voz/oido");
    expect(urlDelOido("http://127.0.0.1:8000/")).toBe("ws://127.0.0.1:8000/voz/oido");
  });
});
