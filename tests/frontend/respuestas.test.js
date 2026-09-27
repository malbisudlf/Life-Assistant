/**
 * Tests de src/lib/respuestas.js: qué frase merece cada respuesta del backend que NO ha
 * ido bien. Y de tres estados derivados que se quedaban desfasados en pantalla: el
 * evento del detalle de «Hoy», el día de «El día» al pasar la medianoche y el historial
 * de la llamada al cortarle a Jarvis.
 */
import { describe, it, expect } from "vitest";
import {
  detalleDeError, textoErrorApi, mensajeErrorLogin, leerCalendario, borradoConfirmado,
} from "../../src/lib/respuestas.js";
import { eventoDelDetalle } from "../../src/lib/helpers.js";
import { diaTrasCambioDeHoy } from "../../src/lib/lineaTiempo.js";
import { historialTrasCorte, MARCA_CORTE, MARCA_CORTE_TRAS_FIN } from "../../src/lib/voz.js";

describe("detalleDeError / textoErrorApi", () => {
  it("un 422 de FastAPI trae una lista, no un texto", () => {
    const cuerpo = { detail: [{ msg: "Value error, Fecha inválida", loc: ["body", "date"] }] };
    expect(detalleDeError(cuerpo)).toBe("Fecha inválida");
    expect(textoErrorApi(422, cuerpo)).toBe("Datos no válidos: Fecha inválida");
  });

  it("usa la explicación del backend cuando la hay", () => {
    expect(textoErrorApi(400, { detail: "No hay ningún cliente" })).toBe("No hay ningún cliente");
  });

  it("sin explicación, el código distingue backend roto de dato rechazado", () => {
    expect(textoErrorApi(502, {})).toMatch(/502/);
    expect(textoErrorApi(502, {})).toMatch(/backend/);
    expect(textoErrorApi(400, null)).toMatch(/400/);
  });
});

describe("mensajeErrorLogin", () => {
  it("un 429 dice que hay que esperar y cuánto, no que la contraseña está mal", () => {
    expect(mensajeErrorLogin(429, {}, "300")).toBe("Demasiados intentos. Espera 5 min y vuelve a probar");
    expect(mensajeErrorLogin(429, {}, "45")).toBe("Demasiados intentos. Espera 45 s y vuelve a probar");
  });

  it("un 429 sin Retry-After usa el detail del backend", () => {
    expect(mensajeErrorLogin(429, { detail: "Demasiados intentos. Reintenta en 60s" }, null))
      .toBe("Demasiados intentos. Reintenta en 60s");
  });

  it("un 5xx es error del servidor y el resto, contraseña incorrecta", () => {
    expect(mensajeErrorLogin(503, {}, null)).toBe("Error del servidor (503)");
    expect(mensajeErrorLogin(401, { detail: "Contraseña incorrecta" }, null)).toBe("Contraseña incorrecta");
    // El mock histórico de login.test.jsx responde 200 sin token: sigue siendo «incorrecta».
    expect(mensajeErrorLogin(200, { detail: "no" }, null)).toBe("Contraseña incorrecta");
  });
});

describe("leerCalendario", () => {
  it("solo un error de sesión pide reconectar", () => {
    expect(leerCalendario({ error: "Sesión de Outlook caducada", reconectar: true }))
      .toEqual({ eventos: null, reconectar: true, error: "" });
    expect(leerCalendario({ error: "No se pudo consultar el calendario de Outlook" }))
      .toEqual({ eventos: null, reconectar: false, error: "No se pudo consultar el calendario de Outlook" });
  });

  it("un backend sin el campo `reconectar` se reconoce por su texto", () => {
    expect(leerCalendario({ error: "Sesión de Outlook caducada. Vuelve a conectar" }).reconectar).toBe(true);
    expect(leerCalendario({ error: "No autenticado. Ve a /auth/login primero" }).reconectar).toBe(true);
  });

  it("la carga buena limpia las dos marcas", () => {
    expect(leerCalendario({ events: [{ id: "x" }] }))
      .toEqual({ eventos: [{ id: "x" }], reconectar: false, error: "" });
  });
});

describe("borradoConfirmado", () => {
  it("un 200 con ok:false no es un borrado", () => {
    expect(borradoConfirmado(200, { ok: false })).toBe(false);
    expect(borradoConfirmado(200, { ok: true })).toBe(true);
    expect(borradoConfirmado(502, {})).toBe(false);
  });
});

describe("eventoDelDetalle", () => {
  const hoy = [
    { id: "a", time: "10:00", active: false },
    { id: "b", time: "11:00", active: true },
  ];

  it("el pulsado se busca en los eventos de ahora, no en una copia vieja", () => {
    // Tras editar «a» a las 12:00, los eventos de hoy traen la hora nueva.
    const editados = [{ ...hoy[0], time: "12:00" }, hoy[1]];
    expect(eventoDelDetalle(editados, "a").time).toBe("12:00");
  });

  it("si el pulsado ya no está hoy, vuelve al que está en curso", () => {
    expect(eventoDelDetalle(hoy, "borrado").id).toBe("b");
    expect(eventoDelDetalle(hoy, null).id).toBe("b");
    expect(eventoDelDetalle([], "a")).toBeUndefined();
  });
});

describe("diaTrasCambioDeHoy", () => {
  it("si mirabas hoy, a medianoche pasas al día nuevo", () => {
    expect(diaTrasCambioDeHoy("2026-09-26", "2026-09-26", "2026-09-27")).toBe("2026-09-27");
  });

  it("si habías ido a otro día, te quedas en él", () => {
    expect(diaTrasCambioDeHoy("2026-09-20", "2026-09-26", "2026-09-27")).toBe("2026-09-20");
  });
});

describe("historialTrasCorte", () => {
  const respuesta = { rol: "assistant", texto: "Mañana tienes dentista. Luego clase. Y cena.", herramientas: ["agenda"] };

  it("tras `fin` no duplica la respuesta: anota el corte en la que ya está", () => {
    const antes = [{ rol: "user", texto: "¿Qué tengo mañana?" }, respuesta];
    const despues = historialTrasCorte(antes, respuesta.texto, true);
    expect(despues).toHaveLength(2);
    expect(despues[1].texto).toBe(`${respuesta.texto} ${MARCA_CORTE_TRAS_FIN}`);
    expect(despues[1].herramientas).toEqual(["agenda"]);
    expect(antes[1].texto).toBe(respuesta.texto);   // sin mutar el estado anterior
  });

  it("antes de `fin` guarda lo dicho como mensaje propio", () => {
    const antes = [{ rol: "user", texto: "¿Qué tengo mañana?" }];
    const despues = historialTrasCorte(antes, "Mañana tienes dentista.", false);
    expect(despues).toEqual([...antes, { rol: "assistant", texto: `Mañana tienes dentista. ${MARCA_CORTE}` }]);
  });

  it("sin nada dicho y sin turno cerrado, no toca el historial", () => {
    const antes = [{ rol: "user", texto: "hola" }];
    expect(historialTrasCorte(antes, "  ", false)).toBe(antes);
  });
});
