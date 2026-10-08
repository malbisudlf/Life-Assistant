import { describe, test, expect } from "vitest";
import { cuandoVence, detalleAsignatura, ordenarAsignaturas, avisoIncompleto } from "../../src/lib/uni";

// Un mediodía fijo, en hora local: los días se cuentan en la zona del navegador.
const AHORA = new Date(2026, 9, 8, 12, 0);
const en = (dias, hora = 23) => new Date(2026, 9, 8 + dias, hora, 59).toISOString();

describe("cuandoVence", () => {
  test("hoy, mañana y en N días, por día de calendario y no por horas", () => {
    expect(cuandoVence({ vence: en(0) }, AHORA)).toBe("hoy");
    expect(cuandoVence({ vence: en(1, 0) }, AHORA)).toBe("mañana");
    expect(cuandoVence({ vence: en(5) }, AHORA)).toBe("en 5 días");
  });

  test("vencida si Moodle lo dice o si la fecha ya pasó", () => {
    expect(cuandoVence({ vence: en(3), vencida: true }, AHORA)).toBe("vencida");
    expect(cuandoVence({ vence: en(-1) }, AHORA)).toBe("vencida");
  });

  test("sin próxima o con fecha rota, nada", () => {
    expect(cuandoVence(null, AHORA)).toBeNull();
    expect(cuandoVence({ vence: "no-es-fecha" }, AHORA)).toBeNull();
  });
});

describe("detalleAsignatura", () => {
  test("cuántas y cuándo la próxima", () => {
    expect(detalleAsignatura({ pendientes: 2, proxima: { vence: en(1) } }, AHORA))
      .toBe("2 entregas · la próxima mañana");
    expect(detalleAsignatura({ pendientes: 1, proxima: { vence: en(-2) } }, AHORA))
      .toBe("1 entrega · una vencida");
  });

  test("«nada pendiente» solo si se sabe; sin dato no dice nada", () => {
    expect(detalleAsignatura({ pendientes: 0 }, AHORA)).toBe("Nada pendiente");
    expect(detalleAsignatura({ pendientes: null }, AHORA)).toBe("");
  });
});

describe("ordenarAsignaturas", () => {
  test("primero lo que vence antes, luego el resto por nombre", () => {
    const lista = [
      { nombre: "Zoología", pendientes: 0 },
      { nombre: "Bases", pendientes: 1, proxima: { vence: en(5) } },
      { nombre: "Álgebra", pendientes: 0 },
      { nombre: "Redes", pendientes: 2, proxima: { vence: en(1) } },
    ];
    expect(ordenarAsignaturas(lista).map(a => a.nombre))
      .toEqual(["Redes", "Bases", "Álgebra", "Zoología"]);
  });

  test("no muta la lista y aguanta que no haya", () => {
    const lista = [{ nombre: "B" }, { nombre: "A" }];
    ordenarAsignaturas(lista);
    expect(lista[0].nombre).toBe("B");
    expect(ordenarAsignaturas(undefined)).toEqual([]);
  });
});

describe("avisoIncompleto", () => {
  test("dice qué falta, y nada si llegó todo", () => {
    expect(avisoIncompleto([])).toBe("");
    expect(avisoIncompleto(["notas"])).toBe("Moodle no ha devuelto las notas; el resto está al día.");
    expect(avisoIncompleto(["entregas", "notas"]))
      .toBe("Moodle no ha devuelto las notas ni las entregas; el resto está al día.");
  });
});
