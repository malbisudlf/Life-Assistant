// Los dos botones de la zona dev que TOCAN algo (src/components/dev/): desplegar el
// backend y despertar el PC. Lo que se fija es qué dicen cuando el backend falla, porque
// es justo cuando hace falta que digan la verdad y dejen volver a intentarlo.
import { describe, test, expect, vi, beforeEach, afterEach } from "vitest";
import { render, screen, cleanup, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

import Despliegue from "../../src/components/dev/Despliegue";
import Jobs from "../../src/components/dev/Jobs";

// Cada ruta devuelve [status, cuerpo]; lo que no está en la tabla es un 404.
function backendFalso(rutas) {
  return vi.fn(async (url) => {
    for (const [trozo, [status, cuerpo]] of Object.entries(rutas)) {
      if (String(url).includes(trozo)) {
        return { status, ok: status < 300, json: async () => cuerpo };
      }
    }
    return { status: 404, ok: false, json: async () => ({}) };
  });
}

beforeEach(() => {
  localStorage.clear();
  vi.stubGlobal("confirm", vi.fn(() => true));
});

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

describe("Despliegue", () => {
  test("tras un fallo el botón vuelve a estar disponible para reintentar", async () => {
    // Se bloqueaba mientras el mensaje no empezara por «listo»: con el 503 de
    // DESPLIEGUE_DIR sin montar se quedaba desactivado hasta salir de la pestaña.
    vi.stubGlobal("fetch", backendFalso({
      "/dev/despliegue":   [200, { github: { ok: true } }],
      "/dev/reconstruir":  [503, { detail: "No se ha podido dejar el pedido" }],
    }));
    render(<Despliegue />);
    const boton = screen.getByRole("button", { name: "Desplegar" });
    await userEvent.click(boton);
    await screen.findByText("No se ha podido dejar el pedido");
    expect(boton).not.toBeDisabled();
  });
});

describe("Jobs", () => {
  test("despertar el PC no dice «encolado» si el backend responde un error", async () => {
    // `apiFetch` no lanza con un 5xx: sin mirar el status, la pestaña daba por encolado
    // un encendido que nadie había apuntado.
    vi.stubGlobal("fetch", backendFalso({
      "/dev/jobs": [200, { agentes: [], jobs: [] }],
      "/wake-pc":  [502, {}],
    }));
    render(<Jobs />);
    await userEvent.click(screen.getByRole("button", { name: "Despertar el PC" }));
    await waitFor(() => expect(screen.getByText(/No se pudo pedir el encendido/)).toBeInTheDocument());
    expect(screen.queryByText(/Encolado/)).toBeNull();
  });

  test("con un 200 sí lo da por encolado", async () => {
    vi.stubGlobal("fetch", backendFalso({
      "/dev/jobs": [200, { agentes: [], jobs: [] }],
      "/wake-pc":  [200, { ok: true }],
    }));
    render(<Jobs />);
    await userEvent.click(screen.getByRole("button", { name: "Despertar el PC" }));
    await screen.findByText(/Encolado el magic packet/);
  });
});
