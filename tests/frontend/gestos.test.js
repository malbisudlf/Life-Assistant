import { describe, it, expect } from "vitest";
import { LectorDeMano, aPantalla, esClic, moverPanel, porcentajeDe, distancia } from "../../src/lib/gestos";

/** Una mano de juguete: muñeca abajo, nudillo del corazón 0,2 más arriba, y el pulgar y
 *  el índice separados `abierto` veces ese tamaño. */
function mano(abierto, { x = 0.5, y = 0.5 } = {}) {
  const p = Array.from({ length: 21 }, () => ({ x, y }));
  p[0] = { x, y: y + 0.2 };
  p[9] = { x, y };
  p[4] = { x: x - (abierto * 0.2) / 2, y };
  p[8] = { x: x + (abierto * 0.2) / 2, y };
  return p;
}

describe("LectorDeMano", () => {
  it("cierra y abre el pellizco con histéresis", () => {
    const l = new LectorDeMano({ cierra: 0.32, abre: 0.45 });
    expect(l.leer(mano(1), 1000, 800).cambio).toBe(null);
    expect(l.leer(mano(0.2), 1000, 800).cambio).toBe("baja");
    // Entre los dos umbrales sigue pellizcado: no parpadea.
    const medio = l.leer(mano(0.4), 1000, 800);
    expect(medio.pellizco).toBe(true);
    expect(medio.cambio).toBe(null);
    expect(l.leer(mano(0.6), 1000, 800).cambio).toBe("sube");
  });

  it("vale igual con la mano cerca o lejos", () => {
    const cerca = new LectorDeMano();
    const lejos = new LectorDeMano();
    const grande = mano(0.2).map(p => ({ x: 0.5 + (p.x - 0.5) * 2, y: 0.5 + (p.y - 0.5) * 2 }));
    expect(cerca.leer(grande, 1000, 800).pellizco).toBe(true);
    expect(lejos.leer(mano(0.2), 1000, 800).pellizco).toBe(true);
  });

  it("en espejo: la mano a la izquierda del fotograma es la derecha de la pantalla", () => {
    const l = new LectorDeMano({ suavizado: 0 });
    const r = l.leer(mano(1, { x: 0.25 }), 1000, 800);
    expect(r.x).toBeGreaterThan(500);
  });

  it("suaviza el cursor", () => {
    const l = new LectorDeMano({ suavizado: 0.5 });
    const a = l.leer(mano(1, { x: 0.3 }), 1000, 800);
    const b = l.leer(mano(1, { x: 0.7 }), 1000, 800);
    const sinSuavizar = new LectorDeMano({ suavizado: 0 }).leer(mano(1, { x: 0.7 }), 1000, 800);
    expect(b.x).toBeLessThan(a.x);
    expect(b.x).toBeGreaterThan(sinSuavizar.x);
  });

  it("perder la mano suelta lo que tuviera cogido", () => {
    const l = new LectorDeMano();
    l.leer(mano(0.1), 1000, 800);
    expect(l.perdida()).toBe("sube");
    expect(l.perdida()).toBe(null);
  });

  it("sin puntos no hay lectura", () => {
    expect(new LectorDeMano().leer([], 100, 100)).toBe(null);
  });
});

describe("aPantalla", () => {
  it("el centro va al centro y los márgenes se estiran a los bordes", () => {
    expect(aPantalla({ x: 0.5, y: 0.5 }, 1000, 800)).toEqual({ x: 500, y: 400 });
    expect(aPantalla({ x: 0.9, y: 0.1 }, 1000, 800)).toEqual({ x: 0, y: 0 });
    expect(aPantalla({ x: 0.1, y: 0.9 }, 1000, 800, { espejo: true })).toEqual({ x: 1000, y: 800 });
  });
});

describe("esClic", () => {
  it("corto y quieto es clic; largo o movido, no", () => {
    expect(esClic({ movido: 5, ms: 200 })).toBe(true);
    expect(esClic({ movido: 80, ms: 200 })).toBe(false);
    expect(esClic({ movido: 5, ms: 3000 })).toBe(false);
  });
});

describe("moverPanel", () => {
  const caja = { left: 100, top: 100, width: 250, height: 300 };
  const ventana = { width: 1400, height: 900 };
  it("mueve lo arrastrado", () => {
    expect(moverPanel({ x: 0, y: 0 }, { x: 40, y: -20 }, caja, ventana)).toEqual({ x: 40, y: -20 });
  });
  it("no deja que se pierda fuera de la pantalla", () => {
    const lejos = moverPanel({ x: 0, y: 0 }, { x: 5000, y: 5000 }, caja, ventana);
    expect(caja.left + lejos.x).toBeLessThanOrEqual(ventana.width - 60);
    expect(caja.top + lejos.y).toBeLessThanOrEqual(ventana.height - 60);
    expect(moverPanel({ x: 0, y: 0 }, { x: 0, y: -900 }, caja, ventana).y).toBe(-100);
  });
});

describe("porcentajeDe", () => {
  it("entiende los formatos que puede mandar el puente", () => {
    expect(porcentajeDe(0.5)).toBe(50);
    expect(porcentajeDe(75)).toBe(75);
    expect(porcentajeDe({ hechos: 3, pasos: 4 })).toBe(75);
    expect(porcentajeDe({ pct: 40 })).toBe(40);
    expect(porcentajeDe("✓ paso 1, paso 2 (50 %)")).toBe(50);
    expect(porcentajeDe("sin plan")).toBe(null);
    expect(porcentajeDe(null)).toBe(null);
  });
});

describe("distancia", () => {
  it("euclídea", () => {
    expect(distancia({ x: 0, y: 0 }, { x: 3, y: 4 })).toBe(5);
  });
});
