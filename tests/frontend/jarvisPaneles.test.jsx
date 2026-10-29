// Los paneles de la vista J.A.R.V.I.S. con las manos: una los lleva y las dos juntas los
// redimensionan. Las manos de verdad (MediaPipe) no corren en jsdom, así que se sustituye
// Manos.jsx por uno que solo guarda lo que le pasa la vista, y se le llama a mano con lo
// que mandaría cada mano.
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { render, cleanup, act } from "@testing-library/react";

let manos = null;
vi.mock("../../src/components/jarvis/Manos", () => ({
  default: (props) => { manos = props; return null; },
}));

import JarvisHUD from "../../src/components/jarvis/JarvisHUD";

const nada = () => {};

function abrir() {
  return render(
    <JarvisHUD mensajes={[]} borrador="" setBorrador={nada} onEnviar={nada} pensando={false}
               etiquetaPendiente="" onConfirmar={nada} onDescartar={nada} confirmando={false}
               escuchando={false} onDictar={nada} habla={false} onHabla={nada} hablando={false}
               enLlamada={false} faseLlamada="" parcial="" onLlamar={nada} onColgar={nada}
               potente={false} onPotente={nada} onNueva={nada} onSalir={nada} briefing={null}
               host="caja" onCapturador={nada} />,
  );
}

const panel = () => document.querySelector('[data-panel="sistema"]');
const mano = (fase, x, y, quien) => act(() => { manos.onArrastre("sistema", fase, { x, y }, quien); });

beforeEach(() => {
  try { localStorage.clear(); } catch { /* jsdom */ }
  vi.stubGlobal("fetch", vi.fn(() => Promise.reject(new Error("sin red"))));
  Element.prototype.scrollIntoView = Element.prototype.scrollIntoView || (() => {});
  // jsdom no maqueta: el panel mide 200x100 y está en (200, 200).
  vi.spyOn(HTMLElement.prototype, "offsetWidth", "get").mockReturnValue(200);
  vi.spyOn(HTMLElement.prototype, "offsetHeight", "get").mockReturnValue(100);
  vi.spyOn(Element.prototype, "getBoundingClientRect").mockReturnValue(
    { left: 200, top: 200, width: 200, height: 100, right: 400, bottom: 300, x: 200, y: 200 });
});

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
});

describe("los paneles con las dos manos", () => {
  it("una mano lo lleva", () => {
    abrir();
    mano("empieza", 100, 100, "Left");
    mano("mueve", 150, 120, "Left");
    expect(panel().style.transform).toBe("translate3d(50px, 20px, 0)");
  });

  it("con la otra mano encima, separarlas lo agranda y va con el punto medio", () => {
    abrir();
    mano("empieza", 100, 100, "Left");
    mano("empieza", 300, 100, "Right");          // a 200 px la una de la otra
    mano("mueve", 500, 100, "Right");            // a 400: el doble
    expect(panel().style.transform).toBe("translate3d(100px, 0px, 0) scale(2.000)");
    expect(panel().classList.contains("jh-pinza")).toBe(true);
  });

  it("juntarlas lo encoge, con tope", () => {
    abrir();
    mano("empieza", 100, 100, "Left");
    mano("empieza", 300, 100, "Right");
    mano("mueve", 105, 100, "Right");            // casi juntas
    expect(panel().style.transform).toContain("scale(0.600)");
  });

  it("al soltar una, la otra sigue llevándolo con su tamaño, y se guarda", () => {
    abrir();
    mano("empieza", 100, 100, "Left");
    mano("empieza", 300, 100, "Right");
    mano("mueve", 500, 100, "Right");
    mano("suelta", 100, 100, "Left");
    expect(panel().classList.contains("jh-pinza")).toBe(false);
    mano("mueve", 550, 100, "Right");
    expect(panel().style.transform).toBe("translate3d(150px, 0px, 0) scale(2.000)");
    mano("suelta", 550, 100, "Right");
    expect(JSON.parse(localStorage.getItem("la_jarvis_paneles")).sistema).toEqual({ x: 150, y: 0, s: 2 });
  });

  it("el ratón no hace pinza con una mano", () => {
    abrir();
    mano("empieza", 100, 100, "Left");
    mano("empieza", 300, 100, "raton");
    mano("mueve", 500, 100, "raton");
    expect(panel().style.transform).toBe("");
    expect(panel().classList.contains("jh-pinza")).toBe(false);
  });
});
