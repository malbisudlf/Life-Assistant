import { describe, test, expect } from "vitest";
import {
  estadoLibro, agruparLibros, terminadosEnAnio, fechaLibro,
  diasDeLectura, textoDuracion, puedeBuscar,
} from "../../src/lib/libros";

describe("estadoLibro", () => {
  test("sale de las fechas", () => {
    expect(estadoLibro({ empezado: "2026-09-01", terminado: "2026-09-10" })).toBe("terminado");
    expect(estadoLibro({ empezado: "2026-09-01", terminado: null })).toBe("leyendo");
    expect(estadoLibro({})).toBe("pendiente");
    expect(estadoLibro(null)).toBe("pendiente");
  });
});

describe("agruparLibros", () => {
  test("separa y ordena por lo más reciente", () => {
    const g = agruparLibros([
      { id: 1, empezado: "2026-01-01", terminado: "2026-01-20" },
      { id: 2, empezado: "2026-02-01", terminado: "2026-02-10" },
      { id: 3, empezado: "2026-08-01", terminado: null },
      { id: 4, empezado: "2026-09-01", terminado: null },
      { id: 5, created_at: "2026-05-01" },
    ]);
    expect(g.leyendo.map(l => l.id)).toEqual([4, 3]);
    expect(g.terminados.map(l => l.id)).toEqual([2, 1]);
    expect(g.pendientes.map(l => l.id)).toEqual([5]);
  });
  test("tolera lo que no es lista", () => {
    expect(agruparLibros(undefined)).toEqual({ leyendo: [], pendientes: [], terminados: [] });
  });
});

test("terminadosEnAnio cuenta solo el año pedido", () => {
  const ls = [{ terminado: "2026-01-02" }, { terminado: "2025-12-31" }, { terminado: null }];
  expect(terminadosEnAnio(ls, 2026)).toBe(1);
});

test("fechaLibro no se desplaza de día", () => {
  expect(fechaLibro("2026-09-05")).toBe("5 sep 2026");
  expect(fechaLibro(null)).toBe("");
});

describe("duración", () => {
  test("cuenta ambos extremos", () => {
    expect(diasDeLectura("2026-09-01", "2026-09-01")).toBe(1);
    expect(diasDeLectura("2026-09-01", "2026-09-10")).toBe(10);
    expect(diasDeLectura("2026-09-10", "2026-09-01")).toBeNull();
    expect(diasDeLectura(null, "2026-09-01")).toBeNull();
  });
  test("si no ha terminado cuenta hasta hoy", () => {
    expect(textoDuracion({ empezado: "2026-09-28" }, "2026-09-30")).toBe("3 días");
    expect(textoDuracion({ empezado: "2026-09-30" }, "2026-09-30")).toBe("1 día");
    expect(textoDuracion({}, "2026-09-30")).toBe("");
  });
});

test("puedeBuscar exige dos letras", () => {
  expect(puedeBuscar("d")).toBe(false);
  expect(puedeBuscar(" d ")).toBe(false);
  expect(puedeBuscar("du")).toBe(true);
});
