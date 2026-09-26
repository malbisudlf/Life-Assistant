import { describe, test, expect, vi, beforeEach, afterEach } from "vitest";
import { render, screen, cleanup, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import Dashboard from "../../src/components/Dashboard";

// El widget de Ideas montado dentro del Dashboard entero, con sesión y el backend
// simulado. La lógica fina está en ideas.test.js; aquí se comprueba que el widget la
// usa: estados, buscador, chips, recorte y el borrado en dos toques.

function idea(n, extra = {}) {
  return {
    id: `00000000-0000-4000-8000-${String(n).padStart(12, "0")}`,
    key: `Nota número ${n}`,
    full_text: `Texto de la nota ${n}`,
    tag: "varios",
    created_at: new Date(2026, 5, 20 - n, 10).toISOString(),
    ...extra,
  };
}

const IDEAS = [
  idea(1, { key: "Viaje a Japón", full_text: "Ver los cerezos en flor", tag: "Trabajo" }),
  idea(2, { key: "Informe trimestral", full_text: "Preparar el informe para Kioto", tag: "trabajo" }),
  ...Array.from({ length: 10 }, (_, i) => idea(i + 3)),
];

function montar({ ideas = IDEAS, fallo = false } = {}) {
  const llamadas = [];
  globalThis.fetch = vi.fn(async (url, options = {}) => {
    const u = String(url);
    llamadas.push([u, options.method || "GET"]);
    if (u.endsWith("/ideas") && (options.method || "GET") === "GET") {
      return fallo
        ? { status: 502, ok: false, json: async () => ({ detail: "caído" }) }
        : { status: 200, ok: true, json: async () => ideas };
    }
    if (u.includes("/ideas/") && options.method === "DELETE") {
      return { status: 200, ok: true, json: async () => ({ ok: true }) };
    }
    if (u.includes("/calendar/events")) return { status: 200, ok: true, json: async () => ({ events: [] }) };
    return { status: 404, ok: false, json: async () => ({}) };
  });
  render(<Dashboard />);
  return llamadas;
}

async function tarjetaIdeas() {
  const titulo = await screen.findByText("Ideas", { selector: "div" });
  return titulo.closest("[data-card]");
}

beforeEach(() => {
  localStorage.clear();
  localStorage.setItem("la_token", "jwt-de-prueba");
});

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});

describe("widget de Ideas", () => {
  test("si GET /ideas falla dice que no ha podido cargar, no que no hay ideas", async () => {
    montar({ fallo: true });
    expect(await screen.findByText("No he podido cargar las ideas.")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Reintentar" })).toBeInTheDocument();
    expect(screen.queryByText("Sin ideas todavía. ¡Graba una!")).toBeNull();
    expect(screen.queryByPlaceholderText("Buscar en tus ideas…")).toBeNull();
  });

  test("enseña 10 y un «Ver 2 más»; buscar «japon» resalta «Japón» con su tilde", async () => {
    const user = userEvent.setup();
    montar();
    const card = await tarjetaIdeas();
    const verMas = await within(card).findByRole("button", { name: "Ver 2 más" });
    expect(within(card).queryByText("Nota número 12")).toBeNull();
    await user.click(verMas);
    expect(within(card).getByText("Nota número 12")).toBeInTheDocument();
    expect(within(card).getByRole("button", { name: "Ver menos" })).toBeInTheDocument();

    await user.type(within(card).getByPlaceholderText("Buscar en tus ideas…"), "japon");
    const marca = card.querySelector("mark");
    expect(marca?.textContent).toBe("Japón");
    expect(within(card).getByText("1 de 12 ideas")).toBeInTheDocument();
    // Cambiar la búsqueda vuelve al recorte.
    expect(within(card).queryByRole("button", { name: "Ver menos" })).toBeNull();
  });

  test("si el acierto está solo en el texto, la tarjeta sale abierta con el texto resaltado", async () => {
    const user = userEvent.setup();
    montar();
    const card = await tarjetaIdeas();
    await user.type(await within(card).findByPlaceholderText("Buscar en tus ideas…"), "kioto");
    expect(card.querySelector("mark")?.textContent).toBe("Kioto");
    expect(within(card).getByText("Informe trimestral")).toBeInTheDocument();
  });

  test("«Trabajo» y «trabajo» son un solo chip que filtra y se quita", async () => {
    const user = userEvent.setup();
    montar();
    const card = await tarjetaIdeas();
    const chip = await within(card).findByRole("button", { name: "trabajo2" });
    await user.click(chip);
    expect(within(card).getByText("2 de 12 ideas")).toBeInTheDocument();
    await user.click(chip);
    expect(within(card).queryByText("2 de 12 ideas")).toBeNull();
  });

  test("filtro sin resultados: lo dice y ofrece quitar los filtros", async () => {
    const user = userEvent.setup();
    montar();
    const card = await tarjetaIdeas();
    await user.type(await within(card).findByPlaceholderText("Buscar en tus ideas…"), "zzz");
    expect(within(card).getByText(/Nada coincide con «zzz»/)).toBeInTheDocument();
    await user.click(within(card).getByRole("button", { name: "Quitar filtros" }));
    expect(within(card).getByPlaceholderText("Buscar en tus ideas…")).toHaveValue("");
  });

  test("el ✕ pide un segundo toque antes de borrar", async () => {
    const user = userEvent.setup();
    const llamadas = montar();
    const card = await tarjetaIdeas();
    const [primera] = await within(card).findAllByRole("button", { name: "Borrar idea" });
    await user.click(primera);
    const confirmar = within(card).getByText("¿Borrar?");
    expect(llamadas.some(([, m]) => m === "DELETE")).toBe(false);
    await user.click(confirmar);
    expect(llamadas.some(([u, m]) => m === "DELETE" && u.endsWith(IDEAS[0].id))).toBe(true);
  });

  test("agrupado, dos ideas casi iguales son una tarjeta «×2» que se despliega", async () => {
    localStorage.setItem("la_ideas_agrupar", "1");
    const user = userEvent.setup();
    const otra = idea(20, {
      key: "Viajar a Japón", full_text: "Ver cerezos en flor en Japón", tag: "viajes",
      created_at: new Date(2025, 0, 10, 10).toISOString(),
    });
    montar({ ideas: [...IDEAS, otra] });
    const card = await tarjetaIdeas();
    const marca = await within(card).findByRole("button", { name: /^×2 · la primera, hace/ });
    await user.click(marca);
    // Desplegado: cada miembro con su fecha corta y su propio ✕.
    expect(within(card).getByText("Viajar a Japón")).toBeInTheDocument();
    expect(within(card).getByText("10 ene 2025")).toBeInTheDocument();
    // Apagar el interruptor devuelve exactamente la lista de GET /ideas.
    await user.click(within(card).getByRole("button", { name: /Agrupar parecidas/ }));
    await user.click(within(card).getByRole("button", { name: "Ver 3 más" }));
    expect(within(card).getAllByRole("button", { name: "Borrar idea" })).toHaveLength(13);
  });

  test("capturar algo ya dicho avisa con «Ya lo dijiste», y «Vale» lo cierra", async () => {
    const user = userEvent.setup();
    montar();
    const nueva = idea(30, { key: "Viajar a Japón", full_text: "Ver cerezos en flor en Japón", tag: "viajes" });
    const fetchBase = globalThis.fetch;
    globalThis.fetch = vi.fn(async (url, options = {}) => (String(url).includes("/ideas/text")
      ? { status: 200, ok: true, json: async () => ({ ok: true, idea: nueva }) }
      : fetchBase(url, options)));
    const card = await tarjetaIdeas();
    await within(card).findByRole("button", { name: "Ver 2 más" });
    await user.click(within(card).getByRole("button", { name: "✎ Escribir idea" }));
    await user.type(screen.getByPlaceholderText("Escribe tu idea..."), "otra vez lo de Japón");
    await user.click(screen.getByRole("button", { name: "Guardar" }));
    expect(await within(card).findByText(/^Ya lo dijiste el/)).toBeInTheDocument();
    expect(within(card).getByText("«Viaje a Japón»")).toBeInTheDocument();
    await user.click(within(card).getByRole("button", { name: "Vale" }));
    expect(within(card).queryByText(/^Ya lo dijiste/)).toBeNull();
  });

  test("«Ver» del aviso agrupa, quita los filtros y abre el grupo de la idea nueva", async () => {
    const user = userEvent.setup();
    montar();
    const nueva = idea(32, {
      key: "Viajar a Japón", full_text: "Ver cerezos en flor en Japón", tag: "viajes",
      created_at: new Date(2026, 5, 25, 10).toISOString(),
    });
    const fetchBase = globalThis.fetch;
    globalThis.fetch = vi.fn(async (url, options = {}) => (String(url).includes("/ideas/text")
      ? { status: 200, ok: true, json: async () => ({ ok: true, idea: nueva }) }
      : fetchBase(url, options)));
    const card = await tarjetaIdeas();
    await user.type(await within(card).findByPlaceholderText("Buscar en tus ideas…"), "informe");
    await user.click(within(card).getByRole("button", { name: "✎ Escribir idea" }));
    await user.type(screen.getByPlaceholderText("Escribe tu idea..."), "Japón otra vez");
    await user.click(screen.getByRole("button", { name: "Guardar" }));
    await user.click(await within(card).findByRole("button", { name: "Ver" }));
    expect(localStorage.getItem("la_ideas_agrupar")).toBe("1");
    expect(within(card).getByPlaceholderText("Buscar en tus ideas…")).toHaveValue("");
    expect(within(card).getByRole("button", { name: /^×2 · la primera/ })).toBeInTheDocument();
    // Desplegado: la fila del miembro antiguo está a la vista.
    expect(within(card).getByText("Viaje a Japón")).toBeInTheDocument();
  });

  test("capturar algo nuevo no avisa de nada", async () => {
    const user = userEvent.setup();
    montar();
    const nueva = idea(31, { key: "Arreglar la bici", full_text: "Cambiar la cadena y los frenos", tag: "casa" });
    const fetchBase = globalThis.fetch;
    globalThis.fetch = vi.fn(async (url, options = {}) => (String(url).includes("/ideas/text")
      ? { status: 200, ok: true, json: async () => ({ ok: true, idea: nueva }) }
      : fetchBase(url, options)));
    const card = await tarjetaIdeas();
    await within(card).findByRole("button", { name: "Ver 2 más" });
    await user.click(within(card).getByRole("button", { name: "✎ Escribir idea" }));
    await user.type(screen.getByPlaceholderText("Escribe tu idea..."), "la bici");
    await user.click(screen.getByRole("button", { name: "Guardar" }));
    expect(await within(card).findByText("Arreglar la bici")).toBeInTheDocument();
    expect(within(card).queryByText(/^Ya lo dijiste/)).toBeNull();
  });

  test("«Agrupar parecidas» se guarda en la_ideas_agrupar", async () => {
    const user = userEvent.setup();
    montar();
    const card = await tarjetaIdeas();
    await user.click(await within(card).findByRole("button", { name: /Agrupar parecidas/ }));
    expect(localStorage.getItem("la_ideas_agrupar")).toBe("1");
  });
});
