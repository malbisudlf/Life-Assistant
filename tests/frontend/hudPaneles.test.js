import { describe, it, expect } from "vitest";
import {
  abanico, barras, claveDatos, colocar, etiquetaDia, eurosCortos, guardar, leerGuardados, repartir,
  resumenSerie, textoValor, tocaReponer, trazo,
} from "../../src/lib/hudPaneles";

function almacenFalso(inicial = {}) {
  const datos = { ...inicial };
  return { getItem: k => (k in datos ? datos[k] : null), setItem: (k, v) => { datos[k] = v; }, datos };
}

describe("hudPaneles: cómo se dice un valor", () => {
  it("usa coma decimal, miles con punto y la unidad detrás", () => {
    expect(textoValor(7.4, "h")).toBe("7,4 h");
    expect(textoValor(7.25, "h")).toBe("7,25 h");
    expect(textoValor(52, "ms")).toBe("52 ms");
    expect(textoValor(8240)).toBe("8.240");
    expect(textoValor(73.56, "kg")).toBe("73,6 kg");
  });
  it("sin dato pone una raya, no un cero", () => {
    expect(textoValor(null, "h")).toBe("—");
    expect(textoValor(undefined)).toBe("—");
  });
  it("dice el día corto", () => {
    expect(etiquetaDia("2026-11-12")).toBe("12/11");
    expect(etiquetaDia("")).toBe("");
  });
});

describe("hudPaneles: de puntos a dibujo", () => {
  const serie = [{ d: "2026-11-10", v: 6 }, { d: "2026-11-11", v: 8 }, { d: "2026-11-12", v: 7 }];

  it("coloca los puntos dentro del lienzo, lo alto arriba", () => {
    const cs = colocar(serie, 220, 70, 6);
    expect(cs).toHaveLength(3);
    expect(cs[0].x).toBe(6);
    expect(cs[2].x).toBe(214);
    expect(cs[1].y).toBeLessThan(cs[2].y);
    expect(cs[2].y).toBeLessThan(cs[0].y);
    for (const c of cs) { expect(c.y).toBeGreaterThan(6); expect(c.y).toBeLessThan(64); }
  });
  it("una serie plana o de un punto va por el medio, sin dividir entre cero", () => {
    expect(colocar([{ d: "a", v: 5 }, { d: "b", v: 5 }])[0].y).toBe(35);
    const [solo] = colocar([{ d: "a", v: 5 }], 220, 70, 6);
    expect(solo.x).toBe(110);
    expect(Number.isFinite(solo.y)).toBe(true);
  });
  it("salta los puntos sin valor y no pinta nada sin puntos", () => {
    expect(colocar([{ d: "a", v: null }, { d: "b", v: 3 }])).toHaveLength(1);
    expect(colocar([])).toEqual([]);
    expect(trazo([])).toBe("");
    expect(barras([])).toEqual([]);
  });
  it("une los puntos en un trazo y levanta las barras desde abajo", () => {
    expect(trazo([{ x: 1, y: 2 }, { x: 3, y: 4 }])).toBe("M1 2 L3 4");
    const bs = barras(serie, 220, 70, 6);
    expect(bs).toHaveLength(3);
    for (const b of bs) expect(Math.round(b.y + b.h)).toBe(64);
    expect(bs[1].h).toBeGreaterThan(bs[0].h);
  });
  it("resume la serie", () => {
    expect(resumenSerie(serie)).toEqual({ ultimo: 7, media: 7, min: 6, max: 8, n: 3 });
    expect(resumenSerie([])).toBeNull();
  });
});

describe("hudPaneles: las recetas guardadas", () => {
  const panel = { id: "abcd1234", titulo: "Sueño", tipo: "linea", fuentes: ["sueno"], dias: 14 };

  it("guarda y lee, y una copia rota es como no tener copia", () => {
    const a = almacenFalso();
    guardar("i1", [panel], a);
    expect(leerGuardados(a)).toEqual({ instancia: "i1", paneles: [panel] });
    expect(leerGuardados(almacenFalso({ la_hud_paneles: "{roto" }))).toEqual({ instancia: "", paneles: [] });
    expect(leerGuardados(almacenFalso())).toEqual({ instancia: "", paneles: [] });
  });
  it("repone solo si el backend se ha reiniciado y está vacío", () => {
    const guardados = { instancia: "i1", paneles: [panel] };
    expect(tocaReponer({ instancia: "i2", paneles: [] }, guardados)).toBe(true);
    // La misma instancia y vacío: Jarvis los quitó. No se resucitan.
    expect(tocaReponer({ instancia: "i1", paneles: [] }, guardados)).toBe(false);
    expect(tocaReponer({ instancia: "i2", paneles: [panel] }, guardados)).toBe(false);
    expect(tocaReponer({ instancia: "i2", paneles: [] }, { instancia: "i1", paneles: [] })).toBe(false);
  });
  it("comparte petición entre paneles iguales y distingue el destino del tráfico", () => {
    expect(claveDatos("sueno", panel)).toBe("sueno|14||");
    expect(claveDatos("trafico", { dias: 14, destino: "uni" })).toBe("trafico|14|uni|");
    expect(claveDatos("sueno", { dias: 14, destino: "uni" })).toBe("sueno|14||");
    expect(claveDatos("dia", { dias: 1, param: "2026-08-03" })).toBe("dia|1||2026-08-03");
  });
  it("reparte los tres primeros a la derecha y el resto a la izquierda", () => {
    const ps = [1, 2, 3, 4, 5].map(n => ({ id: String(n) }));
    const r = repartir(ps);
    expect(r.derecha.map(p => p.id)).toEqual(["1", "2", "3"]);
    expect(r.izquierda.map(p => p.id)).toEqual(["4", "5"]);
  });
});

describe("hudPaneles: el abanico de una simulación", () => {
  const puntos = [
    { d: "2026", p10: 50000, p50: 50000, p90: 50000, base: 55000 },
    { d: "2027", p10: 40000, p50: 52000, p90: 66000, base: 58000 },
    { d: "2028", p10: 38000, p50: 55000, p90: 80000, base: 62000 },
  ];

  it("banda cerrada, mediana y la de sin el gasto, en la misma escala", () => {
    const a = abanico(puntos, 220, 90);
    expect(a.banda.startsWith("M") && a.banda.endsWith("Z")).toBe(true);
    expect(a.mediana.split("L")).toHaveLength(3);
    expect(a.base).not.toBeNull();
    expect(a.min).toBe(38000);
    expect(a.max).toBe(80000);
    expect(a.cero).toBeNull();
    expect(a.ultimo.d).toBe("2028");
  });

  it("si baja de cero, el cero se ve; sin gasto, no hay segunda línea", () => {
    const a = abanico([{ d: "2026", p10: -5000, p50: 1000, p90: 9000 }, { d: "2027", p10: -9000, p50: 2000, p90: 15000 }]);
    expect(a.cero).not.toBeNull();
    expect(a.base).toBeNull();
  });

  it("sin puntos no hay abanico, y los euros caben en el eje", () => {
    expect(abanico([])).toBeNull();
    expect(eurosCortos(52300)).toBe("52 k€");
    expect(eurosCortos(1250000)).toBe("1,3 M€");
    expect(eurosCortos(-800)).toBe("-800 €");
  });
});
