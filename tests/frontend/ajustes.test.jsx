/**
 * Panel ⚙ → el interruptor del resumen diario y su fila del estado del sistema.
 *
 * Lo que se prueba aquí es una sola idea, la de siempre en este proyecto: "no he podido
 * preguntar" no puede pintarse igual que "aún no he preguntado" ni que "está apagado".
 * El caso real que lo motivó es el más probable de todos: el frontend lo despliega
 * Vercel al hacer push y el backend va a mano, así que la interfaz nueva convive a
 * ratos con una API que todavía no tiene `/brief/ajustes` y devuelve 404.
 */
import { describe, test, expect, vi, beforeEach, afterEach } from "vitest";
import { render, screen, cleanup, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import Dashboard from "../../src/components/Dashboard";

const AJUSTES_OK = {
  activo: true, pausado_hasta: null, pausado: false, motivo: null,
  leido: true, fecha: "2026-08-14", enviado_hoy: false,
};

// Backend vivo; solo se decide qué contesta /brief/ajustes. El resto de llamadas del
// arranque devuelven un cuerpo genérico vacío que sirve para todas.
function mockBackend(brief) {
  return vi.fn(async (url, options = {}) => {
    const u = String(url);
    if (u.endsWith("/brief/ajustes")) {
      const r = typeof brief === "function" ? brief(options) : brief;
      return { status: r.status, ok: r.status < 300, json: async () => r.body };
    }
    return {
      status: 200, ok: true,
      json: async () => ({ events: [], metrics: {}, last_sync: null, entradas: [], errores: 0 }),
    };
  });
}

async function abrirAjustes() {
  const user = userEvent.setup();
  render(<Dashboard />);
  await user.click(await screen.findByTitle("Ajustes de widgets"));
  await screen.findByText("Estado del sistema");
  return user;
}

function filaResumen() {
  return screen.getByText("Resumen diario", { selector: "span" }).parentElement;
}

beforeEach(() => {
  localStorage.clear();
  localStorage.setItem("la_token", "jwt-de-prueba");
});
afterEach(() => { cleanup(); vi.restoreAllMocks(); });

describe("estado del resumen diario en el panel de ajustes", () => {
  test("el estado normal se pinta con lo que dice el backend", async () => {
    globalThis.fetch = mockBackend({ status: 200, body: AJUSTES_OK });
    await abrirAjustes();

    await waitFor(() => expect(filaResumen()).toHaveTextContent("hoy aún no ha salido"));
    expect(screen.getByRole("button", { name: "Activado" })).toBeInTheDocument();
  });

  test("un backend sin el endpoint lo dice, en vez de quedarse en 'sin comprobar'", async () => {
    globalThis.fetch = mockBackend({ status: 404, body: { detail: "Not Found" } });
    await abrirAjustes();

    await waitFor(() => expect(filaResumen()).toHaveTextContent("falta desplegarlo"));
    expect(filaResumen()).not.toHaveTextContent("sin comprobar");
    // Y el botón deja de prometer que está comprobando algo que ya falló.
    expect(screen.getByRole("button", { name: "No disponible" })).toBeInTheDocument();
  });

  test("si el backend no pudo leer el ajuste guardado, no se pinta como activo a secas", async () => {
    // `leido: false` = el backend siguió con su defecto de emergencia (activo) porque
    // no pudo leer Supabase. Enseñarlo como un "activo" normal esconde que el botón de
    // apagarlo tampoco va a poder escribir.
    globalThis.fetch = mockBackend({ status: 200, body: { ...AJUSTES_OK, leido: false } });
    await abrirAjustes();

    await waitFor(() => expect(filaResumen()).toHaveTextContent("no se pudo leer el ajuste"));
    expect(await screen.findByText(/no pudo leer el ajuste guardado/)).toBeInTheDocument();
  });

  test("un cambio rechazado enseña el motivo del backend", async () => {
    // El efecto de este ajuste tarda un día en verse: un clic que no hace nada y un
    // clic rechazado son indistinguibles si nadie lo cuenta.
    globalThis.fetch = mockBackend(options =>
      options.method === "PATCH"
        ? { status: 400, body: { detail: "Esa fecha ya ha pasado" } }
        : { status: 200, body: AJUSTES_OK });
    const user = await abrirAjustes();

    await screen.findByRole("button", { name: "Activado" });
    await user.click(screen.getByRole("button", { name: "Activado" }));

    // Sale en los dos sitios: junto al botón y en la fila del estado del sistema.
    expect(await screen.findAllByText("Esa fecha ya ha pasado")).toHaveLength(2);
  });
});
