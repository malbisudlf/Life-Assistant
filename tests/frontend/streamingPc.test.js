import { describe, test, expect } from "vitest";
import {
  motivoFalloJob, cierreDeJob, JOB_GRACIA_MOTIVO,
  textoEstadoCaja, CAJA_MARGEN_MS, CAJA_SIN_PEDIDO,
  agenteSinArrancar, AGENTE_ARRANQUE_MAX_MS,
} from "../../src/lib/helpers";

// Lo que el modal del streaming saca de los eventos del job y del estado de `caja`.

describe("motivoFalloJob", () => {
  test("saca el motivo del mensaje de job_done", () => {
    const eventos = [
      { stage: "job_claimed", message: "Worker w1 reclamó el job" },
      { stage: "job_done", message: "failed: Apollo no arrancó en 30 s" },
    ];
    expect(motivoFalloJob(eventos)).toBe("Apollo no arrancó en 30 s");
  });

  test("un cierre bueno no tiene motivo", () => {
    expect(motivoFalloJob([{ stage: "job_done", message: "done" }])).toBe("");
  });

  test("sin cierre, o sin texto tras «failed», no hay motivo", () => {
    expect(motivoFalloJob([{ stage: "job_claimed", message: "failed: no es un cierre" }])).toBe("");
    expect(motivoFalloJob([{ stage: "job_done", message: "failed" }])).toBe("");
    expect(motivoFalloJob([])).toBe("");
    expect(motivoFalloJob(null)).toBe("");
  });

  test("se queda con el último cierre", () => {
    const eventos = [
      { stage: "job_done", message: "failed: el primero" },
      { stage: "job_done", message: "failed: el segundo" },
    ];
    expect(motivoFalloJob(eventos)).toBe("el segundo");
  });
});

describe("cierreDeJob", () => {
  const fallo = [{ stage: "job_done", message: "failed: sin red" }];

  test("un job en marcha no está cerrado", () => {
    expect(cierreDeJob("pending", [])).toBe(null);
    expect(cierreDeJob("running", fallo)).toBe(null);
    expect(cierreDeJob(undefined, [])).toBe(null);
  });

  test("un fallo con su cierre trae el motivo", () => {
    expect(cierreDeJob("failed", fallo)).toEqual({ status: "failed", reason: "sin red" });
  });

  test("un fallo sin cierre todavía espera unos sondeos al motivo", () => {
    // El agente cierra el job antes de reportar job_done: cerrar aquí dejaba el fallo
    // sin explicar, porque con el job terminado se deja de sondear.
    expect(cierreDeJob("failed", [], 0)).toBe(null);
    expect(cierreDeJob("failed", [], JOB_GRACIA_MOTIVO - 1)).toBe(null);
    expect(cierreDeJob("failed", [], JOB_GRACIA_MOTIVO)).toEqual({ status: "failed", reason: "" });
  });

  test("un job hecho se cierra en el acto, sin motivo", () => {
    expect(cierreDeJob("done", [])).toEqual({ status: "done", reason: "" });
  });
});

describe("textoEstadoCaja", () => {
  const desde = Date.parse("2026-09-27T10:00:00Z");
  const estado = (ultimo, pendientes = []) => ({ motor: "caja", ultimo, pendientes });

  test("sin estado no se dice nada", () => {
    expect(textoEstadoCaja(null, desde)).toBe(null);
  });

  test("con Home Assistant de motor, lo dice", () => {
    expect(textoEstadoCaja({ motor: "ha", ultimo: null, pendientes: [] }, desde).texto)
      .toMatch(/Home Assistant/);
  });

  test("lo último que ha hecho caja, si es de este pedido", () => {
    const r = textoEstadoCaja(estado({ accion: "relanzar", ok: true, cuando: "2026-09-27T10:01:00Z" }), desde);
    expect(r).toEqual({ ok: true, texto: "caja: agente lanzado" });
  });

  test("si no llega al PC, lo dice con el detalle", () => {
    const r = textoEstadoCaja(estado({
      accion: "relanzar", ok: false, detalle: "el PC no contesta por SSH",
      cuando: "2026-09-27T10:02:30Z",
    }), desde);
    expect(r).toEqual({ ok: false, texto: "caja no llega al PC: el PC no contesta por SSH" });
  });

  test("un encendido fallido no es «no llega al PC»", () => {
    const r = textoEstadoCaja(estado({ accion: "wol", ok: false, cuando: "2026-09-27T10:00:05Z" }), desde);
    expect(r.ok).toBe(false);
    expect(r.texto).toMatch(/encendido/);
  });

  test("un resultado de antes del pedido no cuenta", () => {
    const viejo = new Date(desde - CAJA_MARGEN_MS - 1000).toISOString();
    const r = textoEstadoCaja(estado({ accion: "apagar", ok: true, cuando: viejo }, ["wol", "relanzar"]), desde);
    expect(r).toEqual({ ok: true, texto: "caja: en cola (wol, relanzar)" });
  });

  test("dentro del margen de reloj sí cuenta", () => {
    const casi = new Date(desde - CAJA_MARGEN_MS + 1000).toISOString();
    const r = textoEstadoCaja(estado({ accion: "wol", ok: true, cuando: casi }, ["relanzar"]), desde);
    expect(r.texto).toBe("caja: encendido enviado · en cola: relanzar");
  });

  test("con PC_DIR pero sin poder dejar el pedido, lo dice en rojo", () => {
    // Antes esto era «caja: trabajando en el pedido…» durante cinco minutos, de una orden
    // que caja no había recibido nunca.
    const r = textoEstadoCaja({ motor: "caja_sin_montar", ultimo: null, pendientes: [] }, desde);
    expect(r).toEqual({ ok: false, texto: CAJA_SIN_PEDIDO });
  });

  test("si el pedido fue a Home Assistant, caja no está trabajando en él", () => {
    // /pc/estado dice "caja" (el volumen ha vuelto, o el fallo no se ve), pero la
    // respuesta del pedido decía "ha": manda la respuesta, que es de esta orden.
    expect(textoEstadoCaja(estado(null), desde, ["caja", "ha"]))
      .toEqual({ ok: false, texto: CAJA_SIN_PEDIDO });
  });

  test("con los pedidos en caja, o sin saberlo, sigue como siempre", () => {
    expect(textoEstadoCaja(estado(null), desde, ["caja", "caja"]).texto).toMatch(/trabajando/);
    expect(textoEstadoCaja(estado(null), desde, []).texto).toMatch(/trabajando/);
    expect(textoEstadoCaja(estado(null), desde, null).texto).toMatch(/trabajando/);
    // Sin caja configurada, "ha" es lo normal y no es ningún fallo.
    expect(textoEstadoCaja({ motor: "ha", ultimo: null, pendientes: [] }, desde, ["ha", "ha"]))
      .toEqual({ ok: true, texto: "Home Assistant lo recogerá en su próximo sondeo" });
  });

  test("sin resultado ni cola, está en ello", () => {
    expect(textoEstadoCaja(estado(null), desde).texto).toMatch(/trabajando/);
    expect(textoEstadoCaja(estado({ accion: "wol", ok: true, cuando: "no es una fecha" }), desde).texto)
      .toMatch(/trabajando/);
  });
});

describe("agenteSinArrancar", () => {
  const desde = 1_000_000;

  test("antes del tope, todavía no", () => {
    expect(agenteSinArrancar({ desde, ahora: desde + AGENTE_ARRANQUE_MAX_MS - 1, status: "pending", eventos: [] }))
      .toBe(false);
  });

  test("pasado el tope sin que nadie reclame el job, sí", () => {
    expect(agenteSinArrancar({ desde, ahora: desde + AGENTE_ARRANQUE_MAX_MS + 1, status: "pending", eventos: [] }))
      .toBe(true);
  });

  test("si el agente ya ha dado señales, no", () => {
    const tarde = desde + AGENTE_ARRANQUE_MAX_MS * 2;
    expect(agenteSinArrancar({ desde, ahora: tarde, status: "claimed", eventos: [] })).toBe(false);
    expect(agenteSinArrancar({ desde, ahora: tarde, status: "pending",
                               eventos: [{ stage: "job_claimed" }] })).toBe(false);
  });

  test("sin saber desde cuándo, no se afirma nada", () => {
    expect(agenteSinArrancar({ desde: null, ahora: desde, status: "pending" })).toBe(false);
    expect(agenteSinArrancar()).toBe(false);
  });
});
