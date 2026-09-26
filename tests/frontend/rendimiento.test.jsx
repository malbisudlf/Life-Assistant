// Lo que se hizo para que el dashboard pese y trabaje menos, y que no puede volver atrás
// sin que se note: el chunk principal sin la lógica de la zona dev, los componentes
// memorizados que siguen actualizándose cuando les toca, y los refrescos que se paran
// con la pestaña oculta.
import { describe, test, expect, vi, beforeEach, afterEach } from "vitest";
import { readFileSync } from "node:fs";
import { render, screen, cleanup, fireEvent, act, within } from "@testing-library/react";
import Dashboard from "../../src/components/Dashboard";
import { refrescarMientrasSeVea } from "../../src/lib/dev";

// Un `document` de mentira: lo único que mira el refresco es si la pestaña se ve y el
// evento que avisa de que ha cambiado.
function documentoFalso(estado = "visible") {
  const doc = new EventTarget();
  doc.visibilityState = estado;
  doc.cambiar = (nuevo) => { doc.visibilityState = nuevo; doc.dispatchEvent(new Event("visibilitychange")); };
  return doc;
}

describe("refrescarMientrasSeVea", () => {
  beforeEach(() => { vi.useFakeTimers(); });
  afterEach(() => { vi.useRealTimers(); });

  test("con la pestaña a la vista refresca a su ritmo", () => {
    const alTocar = vi.fn();
    const parar = refrescarMientrasSeVea(alTocar, 1000, documentoFalso());
    vi.advanceTimersByTime(3000);
    expect(alTocar).toHaveBeenCalledTimes(3);
    parar();
  });

  test("con la pestaña oculta no pide nada, y al volver refresca en el acto", () => {
    const doc = documentoFalso("hidden");
    const alTocar = vi.fn();
    const parar = refrescarMientrasSeVea(alTocar, 1000, doc);
    vi.advanceTimersByTime(10_000);
    expect(alTocar).not.toHaveBeenCalled();

    doc.cambiar("visible");
    expect(alTocar).toHaveBeenCalledTimes(1);
    parar();
  });

  test("el tic que llega justo detrás de volver no repite la petición", () => {
    const doc = documentoFalso("hidden");
    const alTocar = vi.fn();
    const parar = refrescarMientrasSeVea(alTocar, 1000, doc);
    vi.advanceTimersByTime(1900);
    doc.cambiar("visible");            // refresca aquí…
    vi.advanceTimersByTime(100);       // …y el tic de los 2000 ms, a 100 ms, se salta
    expect(alTocar).toHaveBeenCalledTimes(1);
    vi.advanceTimersByTime(1000);      // el siguiente ya va normal
    expect(alTocar).toHaveBeenCalledTimes(2);
    parar();
  });

  test("volver antes de que tocara no adelanta nada", () => {
    const doc = documentoFalso();
    const alTocar = vi.fn();
    const parar = refrescarMientrasSeVea(alTocar, 1000, doc);
    vi.advanceTimersByTime(300);
    doc.cambiar("hidden");
    doc.cambiar("visible");
    expect(alTocar).not.toHaveBeenCalled();
    parar();
  });

  test("al pararlo deja de refrescar y de escuchar a la pestaña", () => {
    const doc = documentoFalso("hidden");
    const alTocar = vi.fn();
    refrescarMientrasSeVea(alTocar, 1000, doc)();
    vi.advanceTimersByTime(5000);
    doc.cambiar("visible");
    vi.advanceTimersByTime(5000);
    expect(alTocar).not.toHaveBeenCalled();
  });
});

describe("el chunk principal", () => {
  // Un import estático de src/lib/dev.js metía la lógica entera de la zona dev en el
  // bundle que descarga cada visita al dashboard (unos 14 kB). Tiene que llegar por
  // `import()`, como la propia zona dev.
  test("Dashboard no importa la zona dev ni su lógica de forma estática", () => {
    const fuente = readFileSync("src/components/Dashboard.jsx", "utf8");
    expect(fuente).not.toMatch(/^import[^;]*from\s+["']\.\.\/lib\/dev["']/m);
    expect(fuente).not.toMatch(/^import[^;]*from\s+["']\.\/dev\//m);
  });
});

// ── El dashboard con sesión ──────────────────────────────────────

function mockFetch() {
  return vi.fn(async (url) => {
    if (String(url).includes("/calendar/events")) {
      return { status: 200, ok: true, json: async () => ({ events: [] }) };
    }
    return { status: 404, ok: false, json: async () => ({}) };
  });
}

// Deja correr las cargas iniciales (todas contestan al momento).
async function asentar() {
  await act(async () => { await new Promise(r => setTimeout(r, 50)); });
}

describe("Dashboard con sesión", () => {
  beforeEach(() => {
    localStorage.clear();
    localStorage.setItem("la_token", "jwt-de-prueba");
    globalThis.fetch = mockFetch();
    // jsdom no lo implementa y el chat baja hasta el último mensaje cada vez que cambia.
    Element.prototype.scrollIntoView ??= () => {};
  });

  afterEach(() => {
    cleanup();
    vi.useRealTimers();
    delete document.visibilityState;   // vuelve el del prototipo
    vi.restoreAllMocks();
  });

  test("el historial de Jarvis se mantiene al escribir y se vacía al empezar otra conversación", async () => {
    localStorage.setItem("la_jarvis_chat", JSON.stringify([
      { rol: "user", texto: "¿Qué tengo hoy?" },
      { rol: "assistant", texto: "Nada en la agenda." },
    ]));
    render(<Dashboard />);
    await asentar();

    const entrada = screen.getByPlaceholderText("Habla con Jarvis");
    fireEvent.change(entrada, { target: { value: "y mañana" } });
    expect(entrada.value).toBe("y mañana");
    expect(screen.getByText("¿Qué tengo hoy?")).toBeInTheDocument();
    expect(screen.getByText("Nada en la agenda.")).toBeInTheDocument();

    // Los mensajes van memorizados: tienen que irse igual cuando cambia la conversación.
    fireEvent.click(screen.getByRole("button", { name: "Nueva conversación" }));
    expect(screen.queryByText("¿Qué tengo hoy?")).not.toBeInTheDocument();
    expect(screen.queryByText("Nada en la agenda.")).not.toBeInTheDocument();
  });

  test("«El día» sigue cambiando de día aunque vaya memorizado", async () => {
    render(<Dashboard />);
    await asentar();

    const tarjeta = within(document.querySelector('[data-card="dia_linea"]'));
    expect(tarjeta.getByText("El día · hoy")).toBeInTheDocument();
    fireEvent.click(tarjeta.getByRole("button", { name: "Día anterior" }));
    expect(tarjeta.getByText("El día · ayer")).toBeInTheDocument();
    fireEvent.click(tarjeta.getByRole("button", { name: "Hoy" }));
    expect(tarjeta.getByText("El día · hoy")).toBeInTheDocument();
  });

  test("el resumen de ⚙ llega aunque su lógica se descargue al abrirlo", async () => {
    render(<Dashboard />);
    await asentar();

    fireEvent.click(screen.getByTitle("Ajustes de widgets"));
    // El backend del mock no responde (404 en `/`): es lo peor que hay y lo que se dice.
    expect(await screen.findByText("Backend: no responde")).toBeInTheDocument();
  });

  test("con la pestaña oculta no se renuevan los tokens de voz, y al volver sí", async () => {
    vi.useFakeTimers({ toFake: ["setInterval", "clearInterval"] });
    let visibilidad = "visible";
    Object.defineProperty(document, "visibilityState", { configurable: true, get: () => visibilidad });
    const pedidosDeVoz = () => globalThis.fetch.mock.calls
      .filter(([u]) => String(u).includes("/voz/token")).length;

    render(<Dashboard />);
    await asentar();
    const alMontar = pedidosDeVoz();
    expect(alMontar).toBeGreaterThan(0);

    visibilidad = "hidden";
    await act(async () => { vi.advanceTimersByTime(11 * 60 * 1000); });
    await asentar();
    expect(pedidosDeVoz()).toBe(alMontar);

    visibilidad = "visible";
    await act(async () => { vi.advanceTimersByTime(11 * 60 * 1000); });
    await asentar();
    expect(pedidosDeVoz()).toBeGreaterThan(alMontar);
  });
});
