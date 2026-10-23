/**
 * Vacío no es error, y las escrituras dicen si entraron (bloque 8 del plan de octubre).
 *
 * El hermano de `dashboardFallos.test.jsx`, con el mismo montaje: el Dashboard entero con
 * sesión y un fetch simulado, porque lo que falla es lo que se PINTA. Aquí van los sitios
 * donde «no lo sé» salía como «no hay nada» (Próximos eventos, Entregas, Clima), las
 * escrituras que fallaban sin decir nada, lo que el navegador puede no tener
 * (`Notification`, el micrófono) y el `ErrorBoundary` de cada widget.
 */
import { describe, test, expect, vi, beforeEach, afterEach } from "vitest";
import { render, screen, cleanup, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import Dashboard from "../../src/components/Dashboard";
import { API } from "../../src/lib/api";

// Una respuesta simulada con lo que el código mira: status, ok, json() y cabeceras.
function respuesta(cuerpo, status = 200) {
  return {
    status, ok: status >= 200 && status < 300,
    headers: { get: () => null },
    json: async () => cuerpo,
  };
}

// `rutas`: { fragmento: respuesta | (url, opciones) => respuesta }, en orden: gana la
// primera que case. Lo demás, 404. La raíz contesta siempre: sin ella, ⚙ da el backend
// por caído y no pide nada más (ni los ajustes del resumen diario).
function simularBackend(rutas) {
  globalThis.fetch = vi.fn(async (url, opciones = {}) => {
    if (String(url) === `${API}/`) return respuesta({ version: "abc1234" });
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

const tarjetaDe = id => within(document.querySelector(`[data-card="${id}"]`));
// La tarjeta cuando ya está en pantalla: mientras llega el calendario se pinta el skeleton.
async function tarjeta(id) {
  await waitFor(() => expect(document.querySelector(`[data-card="${id}"]`)).not.toBeNull());
  return tarjetaDe(id);
}

beforeEach(() => {
  localStorage.clear();
  localStorage.setItem("la_token", "jwt");
});

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});

describe("vacío no es error", () => {
  test("con Outlook sin conectar, «Próximos eventos» no dice que no hay eventos", async () => {
    simularBackend({
      "/calendar/events": respuesta({ error: "Sesión de Outlook caducada", reconectar: true }),
    });
    render(<Dashboard />);
    await waitFor(() => expect(tarjetaDe("upcoming").getByText(/Outlook no está conectado/)).toBeInTheDocument());
    expect(tarjetaDe("upcoming").queryByText("Sin eventos próximos")).toBeNull();
    expect(tarjetaDe("entregas").queryByText(/Sin entregas/)).toBeNull();
  });

  test("con el calendario caído, «Próximos eventos» y «Entregas» lo dicen y se reintentan", async () => {
    let intentos = 0;
    simularBackend({
      "/calendar/events": () => (++intentos === 1 ? new Error("sin red") : respuesta({ events: [] })),
      "/calendar/classes": respuesta({ events: [] }),
    });
    const user = userEvent.setup();
    render(<Dashboard />);
    await waitFor(() => expect(tarjetaDe("upcoming").getByText(/No se ha podido cargar el calendario/)).toBeInTheDocument());
    expect(tarjetaDe("upcoming").queryByText("Sin eventos próximos")).toBeNull();
    expect(tarjetaDe("entregas").getByText(/No se ha podido cargar el calendario/)).toBeInTheDocument();
    expect(tarjetaDe("entregas").queryByText(/Sin entregas/)).toBeNull();
    await user.click(tarjetaDe("upcoming").getByRole("button", { name: "Reintentar leer los próximos eventos" }));
    expect(await (await tarjeta("upcoming")).findByText("Sin eventos próximos")).toBeInTheDocument();
  });

  test("un 502 con cuerpo JSON de /calendar/events tampoco es una agenda vacía", async () => {
    simularBackend({ "/calendar/events": respuesta({ detail: "Error interno" }, 502) });
    render(<Dashboard />);
    await waitFor(() => expect(tarjetaDe("upcoming").getByText(/No se ha podido cargar el calendario/)).toBeInTheDocument());
    expect(tarjetaDe("upcoming").queryByText("Sin eventos próximos")).toBeNull();
  });

  test("si fallan solo las clases, «Entregas» avisa de que puede faltar alguna", async () => {
    let intentos = 0;
    simularBackend({
      "/calendar/events": respuesta({ events: [] }),
      "/calendar/classes": () => (++intentos === 1
        ? respuesta({ error: "No se pudo consultar el calendario de clases" })
        : respuesta({ events: [] })),
    });
    const user = userEvent.setup();
    render(<Dashboard />);
    await waitFor(() => expect(tarjetaDe("entregas").getByText(/No se han podido leer las clases/)).toBeInTheDocument());
    expect(tarjetaDe("entregas").queryByText(/Sin entregas/)).toBeNull();
    await user.click(tarjetaDe("entregas").getByRole("button", { name: "Reintentar leer las entregas" }));
    expect(await (await tarjeta("entregas")).findByText(/Sin entregas/)).toBeInTheDocument();
  });

  test("un fallo del clima no es «Sin datos de clima», y se reintenta", async () => {
    let intentos = 0;
    simularBackend({
      "/weather": () => (++intentos === 1
        ? respuesta({ detail: "Open-Meteo no contesta" }, 502)
        : respuesta({ temp: 21, temp_max: 24, temp_min: 12, code: 0 })),
    });
    const user = userEvent.setup();
    render(<Dashboard />);
    await waitFor(() => expect(tarjetaDe("weather").getByText(/No se ha podido consultar el clima/)).toBeInTheDocument());
    expect(tarjetaDe("weather").queryByText("Sin datos de clima")).toBeNull();
    await user.click(tarjetaDe("weather").getByRole("button", { name: "Reintentar leer el clima" }));
    expect(await (await tarjeta("weather")).findByText("21°")).toBeInTheDocument();
  });
});

describe("las escrituras dicen si entraron", () => {
  const PARTE = {
    fecha: "2026-10-23",
    items: [{ id: "i1", area: "correo", estado: "pendiente", titulo: "Contestar a Ana" }],
  };

  test("«Visto» del parte que el backend rechaza lo dice y deja los botones", async () => {
    simularBackend({
      "/noche/items/": respuesta({ detail: "No se pudo guardar la decisión" }, 502),
      "/noche/parte": respuesta(PARTE),
    });
    const user = userEvent.setup();
    render(<Dashboard />);
    await user.click(await (await tarjeta("noche")).findByRole("button", { name: "Visto" }));
    expect(await (await tarjeta("noche")).findByText(/No se pudo guardar la decisión/)).toBeInTheDocument();
    expect(tarjetaDe("noche").getByRole("button", { name: "Visto" })).toBeInTheDocument();
  });

  const ALARMA = { id: "a1", cuando: "2099-01-01 07:00", estado: "armada", repetir: [], etiqueta: "" };

  test("quitar una alarma pide confirmación, y si el backend no la quita, lo dice", async () => {
    const borrados = [];
    simularBackend({
      "/alarmas/a1": (url, opciones) => {
        if (opciones.method === "DELETE") borrados.push(url);
        return respuesta({ ok: false, motivo: "esa alarma ya no estaba activa" });
      },
      "/alarmas": respuesta({ alarmas: [ALARMA] }),
    });
    const user = userEvent.setup();
    render(<Dashboard />);
    const quitar = await (await tarjeta("alarmas")).findByRole("button", { name: "Quitar alarma" });
    // Un toque con el dedo necesita sitio: el ✕ de 12 px era fácil de pulsar sin querer.
    expect(parseInt(quitar.style.minWidth, 10)).toBeGreaterThanOrEqual(40);
    expect(parseInt(quitar.style.minHeight, 10)).toBeGreaterThanOrEqual(40);
    await user.click(quitar);
    expect(borrados).toHaveLength(0);          // el primer toque solo arma
    await user.click(tarjetaDe("alarmas").getByRole("button", { name: "Confirmar quitar alarma" }));
    await waitFor(() => expect(borrados).toHaveLength(1));
    expect(await (await tarjeta("alarmas")).findByText(/esa alarma ya no estaba activa/)).toBeInTheDocument();
  });

  test("«Estoy despierto» sin conexión no se calla", async () => {
    simularBackend({
      "/despierto": new TypeError("Failed to fetch"),
      "/alarmas": respuesta({ alarmas: [{ ...ALARMA, estado: "avisada" }] }),
    });
    const user = userEvent.setup();
    render(<Dashboard />);
    await user.click(await (await tarjeta("alarmas")).findByRole("button", { name: "Estoy despierto" }));
    expect(await (await tarjeta("alarmas")).findByText(/Sin conexión con el backend/)).toBeInTheDocument();
  });

  test("crear un evento que el backend rechaza con un 422 no cierra el formulario", async () => {
    simularBackend({
      "/calendar/events": (url, opciones) => (opciones.method === "POST"
        ? respuesta({ detail: [{ msg: "Value error, La hora de fin es anterior a la de inicio" }] }, 422)
        : respuesta({ events: [] })),
    });
    const user = userEvent.setup();
    render(<Dashboard />);
    await user.click(await screen.findByText("+ Evento"));
    await user.type(screen.getByPlaceholderText("Título"), "Dentista");
    await user.click(screen.getByRole("button", { name: "Crear" }));
    expect(await screen.findByText("Datos no válidos: La hora de fin es anterior a la de inicio")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Crear" })).toBeInTheDocument();
  });

  test("el interruptor del resumen diario dice si el backend no lo guardó", async () => {
    simularBackend({
      "/brief/ajustes": (url, opciones) => (opciones.method === "PATCH"
        ? respuesta({ detail: "Error en el almacenamiento de datos" }, 502)
        : respuesta({ activo: true, pausado: false, pausado_hasta: null })),
    });
    const user = userEvent.setup();
    render(<Dashboard />);
    await user.click(await screen.findByTitle("Ajustes de widgets"));
    await user.click(await screen.findByRole("button", { name: "Activado" }));
    expect(await screen.findByText(/No se ha guardado: Error en el almacenamiento de datos/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Activado" })).toBeInTheDocument();
  });
});

describe("lo que el navegador no tiene", () => {
  test("⚙ se abre en un navegador sin Notification (Safari fuera de la PWA)", async () => {
    simularBackend({});
    const original = window.Notification;
    delete window.Notification;
    try {
      const user = userEvent.setup();
      render(<Dashboard />);
      await user.click(await screen.findByTitle("Ajustes de widgets"));
      expect(await screen.findByText(/Este navegador no tiene notificaciones/)).toBeInTheDocument();
    } finally {
      window.Notification = original;
    }
  });

  test("«● Grabar idea» con el micrófono denegado lo dice en vez de no hacer nada", async () => {
    simularBackend({ "/ideas": respuesta([]) });
    const original = Object.getOwnPropertyDescriptor(navigator, "mediaDevices");
    Object.defineProperty(navigator, "mediaDevices", {
      configurable: true,
      value: { getUserMedia: vi.fn().mockRejectedValue(Object.assign(new Error("denegado"), { name: "NotAllowedError" })) },
    });
    // jsdom no tiene MediaRecorder, y sin él ni se pide el micrófono (se dice antes).
    globalThis.MediaRecorder ??= class {};
    try {
      const user = userEvent.setup();
      render(<Dashboard />);
      await user.click(await (await tarjeta("ideas")).findByText("● Grabar idea"));
      expect(await (await tarjeta("ideas")).findByText(/permiso del micrófono/i)).toBeInTheDocument();
      expect(tarjetaDe("ideas").getByText("● Grabar idea")).toBeInTheDocument();
    } finally {
      if (original) Object.defineProperty(navigator, "mediaDevices", original);
      else delete navigator.mediaDevices;
    }
  });
});

describe("un widget que revienta no tumba el dashboard", () => {
  test("el fallo se queda en su tarjeta y el resto se sigue viendo", async () => {
    // Un título que no es texto hace que React lance al pintar la tarjeta del parte: es
    // la forma más corta de provocar una excepción dentro de un widget concreto.
    simularBackend({
      "/noche/parte": respuesta({ fecha: "2026-10-23", items: [{ id: "i1", area: "correo", estado: "pendiente", titulo: { raro: 1 } }] }),
      "/alarmas": respuesta({ alarmas: [] }),
    });
    // React cuenta por consola cada error que atrapa un boundary: aquí es lo esperado.
    vi.spyOn(console, "error").mockImplementation(() => {});
    const user = userEvent.setup();
    render(<Dashboard />);
    expect(await screen.findByText(/«Anoche» ha fallado al pintarse/)).toBeInTheDocument();
    expect(tarjetaDe("alarmas").getByText("Ninguna puesta.")).toBeInTheDocument();
    expect(screen.getByText("Lo siguiente")).toBeInTheDocument();
    // Reintentar vuelve a pintarlo: con los mismos datos vuelve a fallar, sin llevarse nada.
    await user.click(screen.getByRole("button", { name: "Reintentar pintar Anoche" }));
    expect(await screen.findByText(/«Anoche» ha fallado al pintarse/)).toBeInTheDocument();
    expect(tarjetaDe("alarmas").getByText("Ninguna puesta.")).toBeInTheDocument();
  });
});
