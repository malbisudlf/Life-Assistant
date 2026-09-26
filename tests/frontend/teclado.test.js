import { describe, test, expect, vi } from "vitest";
import { comoBoton } from "../../src/lib/teclado";

// Un evento de teclado mínimo: lo único que mira comoBoton es la tecla y si se puede
// cancelar lo que haría el navegador por defecto.
const tecla = key => ({ key, preventDefault: vi.fn() });

describe("comoBoton", () => {
  test("entra en el orden del tabulador y se anuncia como botón", () => {
    const props = comoBoton(() => {});
    expect(props.role).toBe("button");
    expect(props.tabIndex).toBe(0);
  });

  test("el clic sigue haciendo lo mismo que antes", () => {
    const accion = vi.fn();
    comoBoton(accion).onClick("clic");
    expect(accion).toHaveBeenCalledWith("clic");
  });

  test("Enter y Espacio pulsan, y el Espacio no desplaza la página", () => {
    const accion = vi.fn();
    const { onKeyDown } = comoBoton(accion);
    const enter = tecla("Enter");
    const espacio = tecla(" ");
    onKeyDown(enter);
    onKeyDown(espacio);
    expect(accion).toHaveBeenCalledTimes(2);
    expect(enter.preventDefault).toHaveBeenCalled();
    expect(espacio.preventDefault).toHaveBeenCalled();
  });

  test("cualquier otra tecla no hace nada ni se come su comportamiento", () => {
    const accion = vi.fn();
    const { onKeyDown } = comoBoton(accion);
    for (const key of ["Tab", "Escape", "a", "ArrowDown"]) {
      const e = tecla(key);
      onKeyDown(e);
      expect(e.preventDefault).not.toHaveBeenCalled();
    }
    expect(accion).not.toHaveBeenCalled();
  });

  test("la etiqueta da nombre a lo que solo enseña un icono", () => {
    expect(comoBoton(() => {}, { etiqueta: "Editar evento" })["aria-label"]).toBe("Editar evento");
    // Sin etiqueta no se pone ninguna vacía: el nombre sale del texto visible.
    expect("aria-label" in comoBoton(() => {})).toBe(false);
  });

  test("pulsado lo anuncia como interruptor, también cuando está apagado", () => {
    expect(comoBoton(() => {}, { pulsado: true })["aria-pressed"]).toBe(true);
    expect(comoBoton(() => {}, { pulsado: false })["aria-pressed"]).toBe(false);
    expect("aria-pressed" in comoBoton(() => {})).toBe(false);
  });
});
