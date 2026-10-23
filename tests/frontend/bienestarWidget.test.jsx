/**
 * El widget de bienestar montado de verdad, con un /health/metrics simulado.
 *
 * Los helpers ya tienen sus tests con series agujereadas (`helpers.test.js`, «bienestar:
 * días, no registros»); aquí se mira lo que se PINTA, que es donde vivía el fallo: el
 * memo `datosSalud` contaba registros y no días aunque los helpers ya supieran hacerlo.
 */
import { describe, test, expect, vi, beforeEach, afterEach } from "vitest";
import { render, cleanup, fireEvent, act, within } from "@testing-library/react";
import Dashboard from "../../src/components/Dashboard";
import { isoHoy } from "../../src/lib/helpers";

function respuesta(cuerpo, status = 200) {
  return {
    status, ok: status >= 200 && status < 300,
    headers: { get: () => null },
    json: async () => cuerpo,
  };
}

// Fecha ISO de hace `n` días, contada en hora local como la cuenta el dashboard.
function haceDias(n) {
  const d = new Date();
  d.setHours(12, 0, 0, 0);
  d.setDate(d.getDate() - n);
  return isoHoy(d);
}

function simularSalud(metrics) {
  globalThis.fetch = vi.fn(async (url) => {
    const u = String(url);
    if (u.includes("/health/metrics")) return respuesta({ metrics });
    if (u.includes("/calendar/events")) return respuesta({ events: [] });
    return respuesta({}, 404);
  });
}

async function montar() {
  const r = render(<Dashboard />);
  await act(async () => { await new Promise(res => setTimeout(res, 50)); });
  const card = r.container.querySelector('[data-card="health_wellness"]');
  expect(card).not.toBeNull();
  return card;
}

// Una pesada por semana, como se pesa uno de verdad. El código de antes comparaba con el
// octavo registro hacia atrás; con cuatro registros no existe y caía en el primero, a
// tres semanas, llamándolo «semana pasada»: −2,0 kg en vez de −0,5.
const PESADAS_SEMANALES = () => [
  { date: haceDias(21), value: 82 },
  { date: haceDias(14), value: 81 },
  { date: haceDias(7),  value: 80.5 },
  { date: haceDias(0),  value: 80 },
];

beforeEach(() => {
  localStorage.clear();
  localStorage.setItem("la_token", "jwt-de-prueba");
  Element.prototype.scrollIntoView ??= () => {};
});

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});

describe("bienestar: días, no registros", () => {
  test("el peso se compara con la pesada de hace una semana, no con el octavo registro", async () => {
    simularSalud({
      step_count:       [{ date: haceDias(0), value: 9000 }],
      weight_body_mass: PESADAS_SEMANALES(),
    });
    const card = await montar();
    expect(within(card).getByText(/\(-0\.5 kg vs semana pasada\)/)).toBeInTheDocument();
  });

  test("un día sin pesada no mueve la flecha del peso", async () => {
    // Pesada ayer y una fila de hoy sin medida. Antes la fila a 0 era «la última
    // pesada»: el peso desaparecía del widget y la referencia se corría un registro.
    simularSalud({
      step_count:       [{ date: haceDias(0), value: 9000 }],
      weight_body_mass: [
        { date: haceDias(22), value: 82 },
        { date: haceDias(15), value: 81 },
        { date: haceDias(8),  value: 80.5 },
        { date: haceDias(1),  value: 80 },
        { date: haceDias(0),  value: 0 },
      ],
    });
    const card = await montar();
    expect(within(card).getByText(/\(-0\.5 kg vs semana pasada\)/)).toBeInTheDocument();
  });

  test("la vista «Hoy» no puntúa con los pasos de ayer", async () => {
    simularSalud({
      sleep_analysis: [{ date: haceDias(0), value: 7.5, extra: {} }],
      step_count:     [{ date: haceDias(1), value: 12000 }],
    });
    const card = await montar();
    fireEvent.click(within(card).getByRole("button", { name: "Hoy" }));
    // Con la fila de ayer, el widget decía «Muy activo hoy — 12.000 pasos».
    expect(within(card).queryByText(/12\.000 pasos/)).toBeNull();
    expect(within(card).getByText(/Noche excelente/)).toBeInTheDocument();
  });
});
