import { describe, it, expect, vi, afterEach } from "vitest";
import { render, screen, cleanup } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import MenuRadial from "../../src/components/jarvis/MenuRadial";
import { nombreCorto, proyectosDelMenu, prDeConfianza } from "../../src/lib/proyectos";
import { posicionesRadiales, centroDelMenu } from "../../src/lib/gestos";

afterEach(cleanup);

const PROYECTOS = [
  { id: "a", titulo: "web: lista de la compra", estado: "terminado", progreso: 1 },
  { id: "b", titulo: "app: entrenos", estado: "trabajando", progreso: { hechos: 1, pasos: 4 } },
  { id: "c", titulo: "bot de telegram", estado: "en_cola" },
];

describe("los proyectos en el menú", () => {
  it("los que están en marcha van primero", () => {
    expect(proyectosDelMenu(PROYECTOS).map(p => p.id)).toEqual(["b", "c", "a"]);
    expect(proyectosDelMenu(PROYECTOS, 2)).toHaveLength(2);
    expect(proyectosDelMenu([null, {}])).toEqual([]);
  });

  it("el nombre corto quita el área del título", () => {
    expect(nombreCorto(PROYECTOS[0])).toBe("lista de la compra");
    expect(nombreCorto(PROYECTOS[2])).toBe("bot de telegram");
    expect(nombreCorto({ titulo: "x: " + "muy largo ".repeat(10) }, 12)).toHaveLength(12);
  });

  it("el PR solo si es de GitHub", () => {
    expect(prDeConfianza("https://github.com/u/r/pull/3")).toBe("https://github.com/u/r/pull/3");
    expect(prDeConfianza("https://malo.test/pull/3")).toBe("");
  });

  it("el centro del menú no se sale de la pantalla", () => {
    const v = { width: 1400, height: 900 };
    expect(centroDelMenu({ x: 10, y: 10 }, 175, v)).toEqual({ x: 245, y: 245 });
    expect(centroDelMenu({ x: 700, y: 450 }, 175, v)).toEqual({ x: 700, y: 450 });
    expect(centroDelMenu({ x: 1399, y: 899 }, 175, v)).toEqual({ x: 1155, y: 655 });
  });
});

describe("MenuRadial", () => {
  const items = [...proyectosDelMenu(PROYECTOS), { id: "nuevo" }];
  const posiciones = posicionesRadiales(items.length, 175);

  it("sin centro no pinta nada", () => {
    const { container } = render(<MenuRadial centro={null} items={items} posiciones={posiciones} elegido={-1} />);
    expect(container).toBeEmptyDOMElement();
  });

  it("una burbuja por proyecto más la de nuevo, y la elegida se marca", () => {
    render(<MenuRadial centro={{ x: 500, y: 400 }} items={items} posiciones={posiciones} elegido={0} sujeto />);
    const burbujas = screen.getAllByRole("menuitem");
    expect(burbujas).toHaveLength(4);
    expect(burbujas[0]).toHaveTextContent("entrenos");
    expect(burbujas[0]).toHaveTextContent("25 %");
    expect(burbujas[0].className).toContain("elegida");
    expect(burbujas[3]).toHaveTextContent("+ Nuevo");
    expect(screen.getByText("Mueva el puño y abra la mano")).toBeInTheDocument();
  });

  it("pulsar una burbuja la elige y el centro cierra", async () => {
    const onElegir = vi.fn();
    const onCerrar = vi.fn();
    render(<MenuRadial centro={{ x: 500, y: 400 }} items={items} posiciones={posiciones} elegido={-1}
                       onElegir={onElegir} onCerrar={onCerrar} />);
    await userEvent.click(screen.getAllByRole("menuitem")[3]);
    expect(onElegir).toHaveBeenCalledWith("nuevo");
    await userEvent.click(screen.getByRole("button", { name: "Cerrar el menú de proyectos" }));
    expect(onCerrar).toHaveBeenCalled();
  });
});
