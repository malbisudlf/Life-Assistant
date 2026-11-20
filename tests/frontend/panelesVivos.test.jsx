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
  dia: { clase: "dia", nombre: "Lunes 03/08/2026", cifras: [{ n: "Pasos", v: 12345, u: "" }],
         items: [{ a: "10:30", b: "Dentista · Centro", k: "agenda" }, { a: "12:00", b: "<b>WhatsApp con Aimar</b>", k: "whatsapp" }],
         nota: "Sin mirar: el calendario" },
  simulacion: { clase: "abanico", nombre: "Escenario normal", unidad: "€", nota: "Mediano 55.000 €",
                puntos: [{ d: "2026", p10: 50000, p50: 50000, p90: 50000, base: 55000 },
                         { d: "2027", p10: 40000, p50: 52000, p90: 66000, base: 58000 }] },
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

  it("la línea de un día: cifras, cada cosa con su hora, y los nombres como texto", async () => {
    pintar({ titulo: "El 03/08/2026", tipo: "dia", fuentes: ["dia"], dias: 1, param: "2026-08-03" });
    await waitFor(() => expect(screen.getByText("Dentista · Centro")).toBeTruthy());
    expect(screen.getByText("12.345")).toBeTruthy();
    expect(screen.getByText("<b>WhatsApp con Aimar</b>")).toBeTruthy();
    expect(screen.getByText("Sin mirar: el calendario")).toBeTruthy();
    expect(apiFetch.mock.calls[0][0]).toBe("http://backend.test/hud/datos?fuente=dia&dias=1&param=2026-08-03");
  });

  it("el abanico: banda, mediana y la de sin el gasto", async () => {
    const { container } = pintar({ titulo: "¿Y si…?", tipo: "abanico", fuentes: ["simulacion"], dias: 1, param: "i=1;n=1" });
    await waitFor(() => expect(container.querySelectorAll("svg path")).toHaveLength(3));
    expect(screen.getByText("Sin el gasto")).toBeTruthy();
    expect(screen.getByText("52 k€", { selector: ".jh-vivo-valor" })).toBeTruthy();
  });
});
