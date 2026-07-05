import { describe, test, expect, vi, beforeEach, afterEach } from "vitest";
import { render, screen, cleanup, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import Dashboard from "../../src/components/Dashboard";

function mockFetch(routes) {
  return vi.fn(async (url, options = {}) => {
    for (const [fragment, responder] of Object.entries(routes)) {
      if (String(url).includes(fragment)) {
        const data = typeof responder === "function" ? responder(url, options) : responder;
        return { status: 200, ok: true, json: async () => data };
      }
    }
    return { status: 404, ok: false, json: async () => ({}) };
  });
}

beforeEach(() => {
  localStorage.clear();
});

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});

describe("Dashboard sin sesión", () => {
  test("muestra la pantalla de login cuando no hay token", async () => {
    globalThis.fetch = mockFetch({ "/calendar/events": { events: [] } });
    render(<Dashboard />);
    expect(screen.getByText("Life Assistant")).toBeInTheDocument();
    expect(screen.getByText("Acceso privado")).toBeInTheDocument();
    expect(screen.getByPlaceholderText("Contraseña")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Entrar" })).toBeInTheDocument();
  });

  test("login correcto guarda el token en localStorage", async () => {
    globalThis.fetch = mockFetch({
      "/calendar/events": { events: [] },
      "/auth/password": (url, options) => {
        const body = JSON.parse(options.body);
        return body.password === "1234" ? { token: "jwt-de-prueba" } : { detail: "no" };
      },
    });
    // jsdom no implementa location.reload; el flujo de login lo llama tras guardar el token
    const user = userEvent.setup();
    render(<Dashboard />);

    await user.type(screen.getByPlaceholderText("Contraseña"), "1234");
    await user.click(screen.getByRole("button", { name: "Entrar" }));

    await waitFor(() => {
      expect(localStorage.getItem("la_token")).toBe("jwt-de-prueba");
    });
    const authCall = globalThis.fetch.mock.calls.find(([u]) => String(u).includes("/auth/password"));
    expect(authCall).toBeTruthy();
    expect(JSON.parse(authCall[1].body)).toEqual({ password: "1234" });
  });

  test("contraseña incorrecta muestra el error y no guarda token", async () => {
    globalThis.fetch = mockFetch({
      "/calendar/events": { events: [] },
      "/auth/password": { detail: "Contraseña incorrecta" },
    });
    const user = userEvent.setup();
    render(<Dashboard />);

    // El input tiene pattern="[0-9]*": una contraseña no numérica bloquearía el submit en jsdom
    await user.type(screen.getByPlaceholderText("Contraseña"), "9999");
    await user.click(screen.getByRole("button", { name: "Entrar" }));

    expect(await screen.findByText("Contraseña incorrecta")).toBeInTheDocument();
    expect(localStorage.getItem("la_token")).toBeNull();
  });

  test("error de red muestra mensaje de conexión", async () => {
    globalThis.fetch = vi.fn(async url => {
      if (String(url).includes("/auth/password")) throw new Error("network");
      return { status: 200, ok: true, json: async () => ({ events: [] }) };
    });
    const user = userEvent.setup();
    render(<Dashboard />);

    await user.type(screen.getByPlaceholderText("Contraseña"), "1234");
    await user.click(screen.getByRole("button", { name: "Entrar" }));

    expect(await screen.findByText("Error de conexión")).toBeInTheDocument();
  });
});
