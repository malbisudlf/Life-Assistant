// Los ojos de Jarvis: con la cámara trasera el vídeo no va en espejo y no se ofrecen las
// manos ni el inmersivo, que cuentan con verse uno mismo.
import { describe, it, expect, vi, afterEach } from "vitest";
import { render, screen, fireEvent, cleanup } from "@testing-library/react";
import { PanelCamara } from "../../src/components/jarvis/Camara";

const BASE = { ponVideo: () => {}, estado: "en_directo", error: "", jarvisVe: true, onJarvisVe: () => {},
               manos: false, onManos: () => {}, estadoManos: "apagada", asa: {}, inmersivo: false,
               onInmersivo: () => {} };

describe("PanelCamara", () => {
  afterEach(cleanup);

  it("con la frontal: espejo, manos e inmersivo", () => {
    const girar = vi.fn();
    const { container } = render(<PanelCamara {...BASE} onGirar={girar} />);
    expect(container.querySelector("video.trasera")).toBeNull();
    expect(screen.getByText("Usar las manos")).toBeTruthy();
    fireEvent.click(screen.getByText("⟲ Frontal"));
    expect(girar).toHaveBeenCalledTimes(1);
  });

  it("con la trasera: sin espejo y sin manos", () => {
    const { container } = render(<PanelCamara {...BASE} trasera onGirar={() => {}} />);
    expect(container.querySelector("video.trasera")).toBeTruthy();
    expect(screen.queryByText("Usar las manos")).toBeNull();
    expect(screen.queryByText("Modo inmersivo")).toBeNull();
    expect(screen.getByText("⟲ Trasera")).toBeTruthy();
  });
});
