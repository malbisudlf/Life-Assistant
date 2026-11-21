// La casa en holograma: dónde va cada habitación, cómo se gira, qué se dice de cada una y
// qué pasa al tocarla. Y pintada: las privadas no se pueden tocar y tocar una apagada pide
// encenderla.
import { describe, it, expect, vi, afterEach } from "vitest";
import { render, screen, fireEvent, cleanup } from "@testing-library/react";
import {
  GIRO_INICIAL, alTocar, claseArea, girar, planoPiso, resumenArea, resumenCasa, trasTocar,
} from "../../src/lib/holograma";
import { Holograma } from "../../src/components/jarvis/Holograma";

const SALON = { id: "salon", nombre: "Salón", luces: [{ id: "light.a", on: false }, { id: "light.b", on: false }],
                luces_on: 0, temp: 21.4, presencia: true };
const COCINA = { id: "cocina", nombre: "Cocina", luces: [{ id: "light.c", on: true }], luces_on: 1 };
const IKER = { id: "cuarto_iker", nombre: "Cuarto Iker", privado: true };
const DATOS = { clase: "casa", ok: true, pisos: [
  { id: "planta_1", nombre: "Planta 1", nivel: 1, areas: [SALON, COCINA] },
  { id: "planta_2", nombre: "Planta 2", nivel: 2, areas: [IKER] },
] };

describe("holograma: el plano de una planta", () => {
  it("una rejilla lo más cuadrada posible, sin salirse ni pisarse", () => {
    const hs = planoPiso([{ id: "a" }, { id: "b" }, { id: "c" }, { id: "d" }, { id: "e" }]);
    expect(hs).toHaveLength(5);
    for (const h of hs) {
      expect(h.x).toBeGreaterThanOrEqual(0);
      expect(h.x + h.w).toBeLessThanOrEqual(100);
      expect(h.y + h.h).toBeLessThanOrEqual(100);
    }
    expect(hs[0].y).toBe(hs[2].y);   // tres columnas: a, b, c en la primera fila
    expect(hs[3].y).toBeGreaterThan(hs[0].y);
  });

  it("si la habitación trae su caja (CASA_PLANO), manda la caja", () => {
    const [h] = planoPiso([{ id: "salon", caja: [10, 20, 50, 30] }]);
    expect([h.x, h.y, h.w, h.h]).toEqual([10, 20, 50, 30]);
  });
});

describe("holograma: girar, contar y tocar", () => {
  it("arrastrar gira y no deja ponerla de canto", () => {
    expect(girar(GIRO_INICIAL, 100, 0).z).toBe(GIRO_INICIAL.z + 40);
    expect(girar(GIRO_INICIAL, 0, -1000).x).toBe(80);
    expect(girar(GIRO_INICIAL, 0, 1000).x).toBe(15);
  });

  it("lo que se dice de cada habitación", () => {
    expect(resumenArea(SALON)).toBe("0/2 luces · 21,4 °C · alguien");
    expect(resumenArea(IKER)).toBe("Privado");
    expect(resumenArea({ luces: [] })).toBe("Sin sensores");
  });

  it("tocar enciende la apagada, apaga la encendida y la privada no se toca", () => {
    expect(alTocar(SALON)).toEqual({ area: "salon", encender: true });
    expect(alTocar(COCINA)).toEqual({ area: "cocina", encender: false });
    expect(alTocar(IKER)).toBeNull();
    expect(claseArea(COCINA)).toBe("encendida");
    expect(claseArea(IKER)).toBe("privado");
    expect(trasTocar(SALON, true).luces_on).toBe(2);
  });

  it("el resumen de la casa no cuenta lo privado", () => {
    expect(resumenCasa(DATOS.pisos)).toEqual({ luces: 1, gente: 1 });
  });
});

describe("Holograma", () => {
  afterEach(cleanup);

  it("pinta las plantas, toca una habitación y deja la privada quieta", () => {
    const tocar = vi.fn();
    render(<Holograma datos={DATOS} onTocar={tocar} />);
    expect(screen.getByText("Planta 1")).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: /^Salón/ }));
    expect(tocar).toHaveBeenCalledWith(expect.objectContaining({ id: "salon" }), true);
    fireEvent.click(screen.getByRole("button", { name: /^Cuarto Iker: Privado/ }));
    expect(tocar).toHaveBeenCalledTimes(1);
  });

  it("elegir una planta apaga las demás", () => {
    const { container } = render(<Holograma datos={DATOS} onTocar={() => {}} />);
    fireEvent.click(screen.getByRole("button", { name: "Planta 2" }));
    expect(container.querySelectorAll(".jh-holo-piso.fuera")).toHaveLength(1);
  });

  it("en grande, un solo juego de mandos (el de la capa) y × la cierra", () => {
    render(<Holograma datos={DATOS} onTocar={() => {}} />);
    fireEvent.click(screen.getByRole("button", { name: "Abrir la maqueta en grande" }));
    expect(screen.getByText("Abierta en grande.")).toBeTruthy();
    expect(screen.getAllByRole("button", { name: "Girar a la izquierda" })).toHaveLength(1);
    const cerrar = screen.getAllByRole("button", { name: "Cerrar la maqueta grande" });
    expect(cerrar).toHaveLength(1);
    expect(screen.getByRole("dialog", { name: "La casa en grande" }).contains(cerrar[0])).toBe(true);
    fireEvent.click(cerrar[0]);
    expect(screen.queryByText("Abierta en grande.")).toBeNull();
  });

  it("sin casa lo dice", () => {
    render(<Holograma datos={{ ok: false, motivo: "Home Assistant no contesta." }} onTocar={() => {}} />);
    expect(screen.getByText("Home Assistant no contesta.")).toBeTruthy();
  });
});
