import { describe, test, expect, vi, beforeEach, afterEach } from "vitest";
import { render, screen, cleanup } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import Dashboard from "../../src/components/Dashboard";

// El dashboard con sesión y un backend que no contesta nada (404 a todo): es el estado
// que se pinta mientras llegan los datos, y el que tiene que poder usarse con el
// teclado y un lector de pantalla igual que con el ratón. Se busca todo por ROL y
// NOMBRE a propósito: es exactamente lo que ve un lector de pantalla, y un botón que
// solo enseña "✎" o "↑" no se encuentra así.
beforeEach(() => {
  localStorage.clear();
  localStorage.setItem("la_token", "jwt-de-prueba");
  globalThis.fetch = vi.fn(async () => ({ status: 404, ok: false, json: async () => ({}) }));
});

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});

async function montar() {
  const user = userEvent.setup();
  render(<Dashboard />);
  await screen.findByRole("button", { name: "Ajustes" });
  return user;
}

describe("accesibilidad del dashboard", () => {
  test("el foco del teclado se ve aunque el reset global quite el outline", async () => {
    await montar();
    const css = document.getElementById("dashboard-global-css")?.textContent || "";
    expect(css).toMatch(/button:focus-visible[^{]*\{[^}]*outline:\s*1px solid/);
    expect(css).toContain('[role="button"]:focus-visible');
  });

  test("Jarvis: el campo y el botón de enviar tienen nombre", async () => {
    await montar();
    expect(screen.getByRole("textbox", { name: "Mensaje para Jarvis" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Enviar" })).toBeDisabled();
  });

  test("los días de una alarma se marcan con el teclado y dicen si están puestos", async () => {
    const user = await montar();
    const lunes = screen.getByRole("button", { name: "lunes", pressed: false });
    lunes.focus();
    await user.keyboard("{Enter}");
    expect(screen.getByRole("button", { name: "lunes", pressed: true })).toBeInTheDocument();
    await user.keyboard(" ");
    expect(screen.getByRole("button", { name: "lunes", pressed: false })).toBeInTheDocument();
  });

  test("«+ Evento» se abre con el teclado", async () => {
    const user = await montar();
    const crear = screen.getByRole("button", { name: "+ Evento" });
    crear.focus();
    await user.keyboard("{Enter}");
    expect(await screen.findByText("Nuevo evento en Outlook")).toBeInTheDocument();
  });

  test("ajustes: cada widget es una casilla con nombre y sus flechas dicen cuál mueven", async () => {
    const user = await montar();
    await user.click(screen.getByRole("button", { name: "Ajustes" }));

    const jarvis = screen.getByRole("checkbox", { name: "Mostrar Jarvis" });
    expect(jarvis).toBeChecked();
    // Los de detalle de salud nacen ocultos: la casilla tiene que decirlo.
    expect(screen.getByRole("checkbox", { name: "Mostrar HRV" })).not.toBeChecked();

    // El primero no puede subir y el último no puede bajar.
    expect(screen.getByRole("button", { name: "Subir Jarvis" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "Bajar Jarvis" })).toBeEnabled();

    await user.click(jarvis);
    expect(screen.getByRole("checkbox", { name: "Mostrar Jarvis" })).not.toBeChecked();

    // Los días de entrenamiento por defecto son lunes, miércoles, jueves y domingo.
    expect(screen.getByRole("button", { name: "Lunes", pressed: true })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Martes", pressed: false })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "2 columnas", pressed: true })).toBeInTheDocument();
  });

  test("el panel de clases cuenta en singular cuando solo hay una", async () => {
    const hoy = new Date();
    const a = h => new Date(hoy.getFullYear(), hoy.getMonth(), hoy.getDate(), h).toISOString();
    globalThis.fetch = vi.fn(async url => {
      const u = String(url);
      if (u.includes("/calendar/classes")) {
        return { status: 200, ok: true, json: async () => ({ events: [{ id: "c1", title: "Redes", start: a(10), end: a(11) }] }) };
      }
      if (u.includes("/calendar/events")) return { status: 200, ok: true, json: async () => ({ events: [] }) };
      return { status: 404, ok: false, json: async () => ({}) };
    });
    const user = await montar();
    await user.click(await screen.findByText("Clases (1)"));
    expect(await screen.findByText("1 clase")).toBeInTheDocument();
  });

  test("ningún botón visible se queda sin nombre", async () => {
    const user = await montar();
    await user.click(screen.getByRole("button", { name: "Ajustes" }));
    // Este nombre lo usa el E2E para entrar en la zona dev: si cambia, cámbialo allí.
    expect(screen.getByRole("button", { name: "Zona de desarrollo" })).toBeInTheDocument();
    const botones = screen.getAllByRole("button");
    // Que de verdad se estén mirando los del dashboard y el panel, no una pantalla vacía.
    expect(botones.length).toBeGreaterThan(20);
    const sinNombre = botones.filter(b => {
      const nombre = (b.getAttribute("aria-label") || b.textContent || "").trim();
      // Un nombre de solo símbolos (✕, ↑, →, ⚙…) es como no tener nombre.
      return !/[\p{L}\p{N}]/u.test(nombre);
    });
    // El HTML y no un recuento, para que el fallo diga qué botones son.
    expect(sinNombre.map(b => b.outerHTML.slice(0, 120))).toEqual([]);
  });
});
