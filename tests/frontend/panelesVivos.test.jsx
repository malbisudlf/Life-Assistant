// Los paneles que dibuja Jarvis, pintados de verdad: una serie, dos, una lista y una
// cifra, con el backend simulado. Y lo que importa de seguridad: el título que escribe
// el modelo es texto, no marcado.
import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, waitFor, fireEvent } from "@testing-library/react";

vi.mock("../../src/lib/api", () => ({
  API: "http://backend.test",
  authHeaders: () => ({}),
  jsonHeaders: () => ({}),
  apiFetch: vi.fn(),
}));

import { apiFetch } from "../../src/lib/api";
import { PanelVivo } from "../../src/components/jarvis/PanelesVivos";

const DATOS = {
  sueno: { clase: "serie", nombre: "Sueño", unidad: "h",
           puntos: [{ d: "2026-11-10", v: 6.5 }, { d: "2026-11-11", v: 8 }, { d: "2026-11-12", v: 7.25 }] },
  hrv: { clase: "serie", nombre: "HRV", unidad: "ms",
         puntos: [{ d: "2026-11-10", v: 48 }, { d: "2026-11-12", v: 52 }] },
  agenda: { clase: "lista", nombre: "Agenda", items: [{ a: "15:00", b: "Clase de redes" }] },
  trafico: { clase: "cifra", nombre: "A uni", valor: 29, unidad: "min", nota: "+7 min sobre lo normal · AP-8" },
};

beforeEach(() => {
  apiFetch.mockReset();
  apiFetch.mockImplementation(async (url) => {
    const fuente = new URL(url).searchParams.get("fuente");
    return { ok: Boolean(DATOS[fuente]), json: async () => DATOS[fuente] };
  });
});

function pintar(panel, onQuitar = () => {}) {
  return render(<PanelVivo panel={{ id: "abcd1234", dias: 14, ...panel }} asa={{}} onQuitar={onQuitar} />);
}

describe("PanelVivo", () => {
  it("pinta una serie con su último valor y su media", async () => {
    const { container } = pintar({ titulo: "Sueño", tipo: "linea", fuentes: ["sueno"] });
    expect(screen.getByText("Trayendo datos…")).toBeTruthy();
    await waitFor(() => expect(container.querySelector("svg path")).toBeTruthy());
    expect(container.querySelectorAll("svg circle")).toHaveLength(3);
    expect(screen.getByText("7,25 h")).toBeTruthy();
    expect(screen.getByText("media 7,25 h")).toBeTruthy();
    expect(apiFetch.mock.calls[0][0]).toBe("http://backend.test/hud/datos?fuente=sueno&dias=14");
  });

  it("en barras pinta una por día", async () => {
    const { container } = pintar({ titulo: "Sueño", tipo: "barras", fuentes: ["sueno"] });
    await waitFor(() => expect(container.querySelectorAll("svg rect")).toHaveLength(3));
  });

  it("dos fuentes son dos trazos, una contra otra", async () => {
    const { container } = pintar({ titulo: "Sueño contra HRV", tipo: "linea", fuentes: ["sueno", "hrv"] });
    await waitFor(() => expect(container.querySelectorAll("svg path")).toHaveLength(2));
    expect(screen.getByText("52 ms")).toBeTruthy();
  });

  it("la agenda es una lista y el tráfico una cifra, con su destino en la petición", async () => {
    pintar({ titulo: "Hoy", tipo: "lista", fuentes: ["agenda"] });
    await waitFor(() => expect(screen.getByText("Clase de redes")).toBeTruthy());
    pintar({ titulo: "A la uni", tipo: "cifra", fuentes: ["trafico"], destino: "uni" });
    await waitFor(() => expect(screen.getByText("29 min")).toBeTruthy());
    expect(screen.getByText("+7 min sobre lo normal · AP-8")).toBeTruthy();
    expect(apiFetch.mock.calls.some(c => c[0].includes("fuente=trafico") && c[0].includes("destino=uni"))).toBe(true);
  });

  it("si el backend falla lo dice, y no se queda cargando", async () => {
    pintar({ titulo: "Raro", tipo: "linea", fuentes: ["inventada"] });
    await waitFor(() => expect(screen.getByText("No he podido traer los datos")).toBeTruthy());
  });

  it("el título que escribe el modelo es texto, y la × quita el panel", async () => {
    const quitar = vi.fn();
    const { container } = pintar({ titulo: "<img src=x onerror=alert(1)>", tipo: "linea", fuentes: ["sueno"] }, quitar);
    expect(container.querySelector("img")).toBeNull();
    expect(screen.getByText("<img src=x onerror=alert(1)>")).toBeTruthy();
    fireEvent.click(container.querySelector("button[aria-label^='Quitar el panel']"));
    expect(quitar).toHaveBeenCalledTimes(1);
  });
});
