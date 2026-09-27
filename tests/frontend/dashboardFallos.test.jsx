/**
 * El dashboard cuando el backend NO contesta bien.
 *
 * Cada caso de aquí es un sitio donde un fallo se pintaba como otra cosa: una caída de
 * Graph como sesión caducada, un 502 de /alarmas como «Ninguna puesta», un 429 del login
 * como contraseña incorrecta, el JSON de error de /export descargado como si fuera la
 * copia. Se monta el Dashboard entero con sesión y un fetch simulado, igual que
 * login.test.jsx, porque lo que falla es lo que se PINTA.
 */
import { describe, test, expect, vi, beforeEach, afterEach } from "vitest";
import { render, screen, cleanup, fireEvent, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import Dashboard from "../../src/components/Dashboard";

// Una respuesta simulada con lo que el código mira: status, ok, json() y cabeceras.
function respuesta(cuerpo, status = 200, cabeceras = {}) {
  return {
    status, ok: status >= 200 && status < 300,
    headers: { get: nombre => cabeceras[nombre] ?? null },
    json: async () => cuerpo,
  };
}

// `rutas`: { fragmento: respuesta | (url, opciones) => respuesta }. Lo demás, 404.
function simularBackend(rutas) {
  globalThis.fetch = vi.fn(async (url, opciones = {}) => {
    for (const [fragmento, r] of Object.entries(rutas)) {
      if (String(url).includes(fragmento)) {
        const res = typeof r === "function" ? r(url, opciones) : r;
        if (res instanceof Error) throw res;
        return res;
      }
    }
    return respuesta({}, 404);
  });
}

// Mediodía de hoy en hora local: cae en el widget «Hoy» sea la hora que sea.
function hoyA(hora) {
  const d = new Date();
  return new Date(d.getFullYear(), d.getMonth(), d.getDate(), hora, 0).toISOString();
}

beforeEach(() => {
  localStorage.clear();
});

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});

describe("calendario", () => {
  test("una caída de Graph dice lo que pasa, no «Conectar Outlook»", async () => {
    localStorage.setItem("la_token", "jwt");
    simularBackend({
      "/calendar/events": respuesta({ error: "No se pudo consultar el calendario de Outlook" }),
    });
    render(<Dashboard />);
    expect(await screen.findByText("No se pudo consultar el calendario de Outlook.")).toBeInTheDocument();
    expect(screen.queryByText("→ Conectar Outlook")).toBeNull();
  });

  test("la sesión caducada sí ofrece reconectar", async () => {
    localStorage.setItem("la_token", "jwt");
    simularBackend({
      "/calendar/events": respuesta({ error: "Sesión de Outlook caducada", reconectar: true }),
    });
    render(<Dashboard />);
    expect(await screen.findByText("→ Conectar Outlook")).toBeInTheDocument();
  });

  test("el aviso no se queda pegado cuando la carga siguiente va bien", async () => {
    localStorage.setItem("la_token", "jwt");
    let intentos = 0;
    simularBackend({
      "/calendar/events": () => (++intentos === 1
        ? new Error("backend desplegándose")
        : respuesta({ events: [{ id: "ev1", title: "Dentista", start: hoyA(12), end: hoyA(13) }] })),
    });
    const user = userEvent.setup();
    render(<Dashboard />);
    await screen.findByText("No se ha podido cargar el calendario.");
    const hoy = document.querySelector('[data-card="timeline"]');
    await user.click(within(hoy).getByText("Reintentar"));
    expect((await screen.findAllByText("Dentista")).length).toBeGreaterThan(0);
    expect(screen.queryByText("→ Conectar Outlook")).toBeNull();
    expect(screen.queryByText(/No se ha podido cargar el calendario/)).toBeNull();
  });
});

describe("alarmas", () => {
  test("un fallo de /alarmas no se pinta como «Ninguna puesta»", async () => {
    localStorage.setItem("la_token", "jwt");
    simularBackend({ "/alarmas": respuesta({ detail: "Error en el almacenamiento de datos" }, 502) });
    render(<Dashboard />);
    expect(await screen.findByText("No se han podido consultar las alarmas.")).toBeInTheDocument();
    expect(screen.queryByText("Ninguna puesta.")).toBeNull();
  });
});

describe("parte del turno de noche", () => {
  test("un fallo de /noche/parte no se pinta como «no hay ningún parte»", async () => {
    localStorage.setItem("la_token", "jwt");
    simularBackend({ "/noche/parte": respuesta({ detail: "Error en el almacenamiento de datos" }, 502) });
    render(<Dashboard />);
    expect(await screen.findByText("No se ha podido consultar el parte.")).toBeInTheDocument();
    expect(screen.queryByText("Todavía no hay ningún parte.")).toBeNull();
  });
});

describe("login", () => {
  test("el bloqueo por intentos no se disfraza de contraseña incorrecta", async () => {
    simularBackend({
      "/auth/password": respuesta({ detail: "Demasiados intentos. Reintenta en 300s" }, 429,
                                  { "Retry-After": "300" }),
    });
    const user = userEvent.setup();
    render(<Dashboard />);
    await user.type(screen.getByPlaceholderText("Contraseña"), "1234");
    await user.click(screen.getByRole("button", { name: "Entrar" }));
    expect(await screen.findByText("Demasiados intentos. Espera 5 min y vuelve a probar")).toBeInTheDocument();
    expect(screen.queryByText("Contraseña incorrecta")).toBeNull();
  });
});

describe("exportar datos", () => {
  test("un 502 de /export no se descarga como copia de seguridad", async () => {
    localStorage.setItem("la_token", "jwt");
    simularBackend({ "/export": respuesta({ detail: "Error en el almacenamiento de datos" }, 502) });
    const crearUrl = vi.fn(() => "blob:simulado");
    const original = URL.createObjectURL;
    URL.createObjectURL = crearUrl;
    URL.revokeObjectURL ??= () => {};
    try {
      const user = userEvent.setup();
      render(<Dashboard />);
      await user.click(await screen.findByTitle("Ajustes de widgets"));
      await user.click(screen.getByText("Exportar backup"));
      expect(await screen.findByText(/No se ha hecho la copia/)).toBeInTheDocument();
      expect(crearUrl).not.toHaveBeenCalled();
    } finally {
      URL.createObjectURL = original;
    }
  });
});

describe("entrenamiento", () => {
  test("una sesión rechazada no cierra el formulario ni se calla", async () => {
    localStorage.setItem("la_token", "jwt");
    simularBackend({
      "/training/summary": respuesta({
        client: { price_per_hour: 30, sessions_per_payment: 4 },
        sessions_since_payment: 1, hours_since_payment: 1, amount_owed: 30,
        sessions_per_payment: 4, all_recent_sessions: [],
      }),
      "/training/sessions": respuesta({ detail: [{ msg: "Value error, Fecha inválida" }] }, 422),
    });
    const user = userEvent.setup();
    render(<Dashboard />);
    await user.click(await screen.findByText("+ Sesión"));
    // El input de fecha vaciado: es la forma real de mandar una fecha que el backend
    // rechaza con un 422.
    const fecha = document.querySelector('[data-card="training"] input[type="date"]');
    fireEvent.change(fecha, { target: { value: "" } });
    await user.click(screen.getByText("✓"));
    expect(await screen.findByText("Datos no válidos: Fecha inválida")).toBeInTheDocument();
    expect(screen.getByText("✓")).toBeInTheDocument();   // el formulario sigue abierto
  });
});

describe("ideas", () => {
  const ideas = [
    { id: "a", key: "Idea A", tag: "x", full_text: "Texto completo A" },
    { id: "b", key: "Idea B", tag: "x", full_text: "Texto completo B" },
  ];

  // Borra la primera idea de la lista: el ✕ arma y «¿Borrar?» confirma (dos toques).
  const borrarPrimera = async user => {
    const card = document.querySelector('[data-card="ideas"]');
    await user.click(within(card).getAllByRole("button", { name: "Borrar idea" })[0]);
    await user.click(within(card).getByText("¿Borrar?"));
  };

  test("un borrado que el backend no confirma no quita la idea", async () => {
    localStorage.setItem("la_token", "jwt");
    simularBackend({
      "/ideas": (url, opciones) => (opciones.method === "DELETE"
        ? respuesta({ ok: false })            // así responde si falla Supabase
        : respuesta(ideas)),
    });
    const user = userEvent.setup();
    render(<Dashboard />);
    await screen.findByText("Idea A");
    await borrarPrimera(user);
    expect(await screen.findByText("No se ha podido borrar la idea")).toBeInTheDocument();
    expect(screen.getByText("Idea A")).toBeInTheDocument();
  });

  test("la idea abierta sigue abierta aunque la lista se mueva", async () => {
    localStorage.setItem("la_token", "jwt");
    simularBackend({
      "/ideas": (url, opciones) => respuesta(opciones.method === "DELETE" ? { ok: true } : ideas),
    });
    const user = userEvent.setup();
    render(<Dashboard />);
    await user.click(await screen.findByText("Idea B"));
    expect(screen.getByText("Texto completo B")).toBeInTheDocument();
    // Borrar la de arriba desplaza la B a la posición 0: con el índice guardado, la B se
    // cerraba (o se abría otra).
    await borrarPrimera(user);
    await waitFor(() => expect(screen.queryByText("Idea A")).toBeNull());
    expect(screen.getByText("Texto completo B")).toBeInTheDocument();
  });
});
