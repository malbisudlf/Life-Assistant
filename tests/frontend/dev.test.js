// Lógica de la zona de desarrollo (src/lib/dev.js): cómo se traduce lo que responden los
// endpoints a las filas del semáforo, y cómo se resume todo en una línea para el panel ⚙.
//
// Lo que se fija aquí es sobre todo la distinción que sostiene medio proyecto: "no lo sé"
// no es "no hay". Un backend que no responde y un backend sin comprobar no pueden salir
// pintados igual, porque llevan a mirar sitios distintos.
import { describe, test, expect, vi, afterEach } from "vitest";

import { filasDeEstado, resumenEstado, desdeHace, horaCorta } from "../../src/lib/dev";

function fila(sys, nombre) {
  return filasDeEstado(sys).find(f => f.nombre === nombre);
}

const SANO = {
  backend:   { ok: true, ms: 120, version: "a54b78b" },
  agente:    { offline: false, hostname: "pc" },
  presencia: { conocida: true, vigente: true, en_casa: true, hace_minutos: 1 },
  brief:     { activo: true, pausado: false, enviado_hoy: true },
  avisos:    { activo: true, canal: "movil", sondeo_hace_segundos: 12 },
  registro:  { entradas: [], errores: 0 },
  gasto:     { total: { llamadas: 10, euros: 0.42, euros_incompleto: false }, cacheado_pct: 88 },
  enviados:  [],
  comprobado: Date.now(),
};

describe("filasDeEstado", () => {
  test("sin comprobar no es lo mismo que roto", () => {
    expect(fila(null, "Backend").tono).toBe("muted");
    expect(fila(null, "Backend").detalle).toBe("sin comprobar");
    expect(fila({ backend: { ok: false } }, "Backend").tono).toBe("red");
  });

  test("un backend lento se marca, no se da por bueno", () => {
    // El aviso importa: 3 s de respuesta es lo que delata un arranque en frío, y da igual
    // que la petición acabe saliendo bien.
    expect(fila({ backend: { ok: true, ms: 120 } }, "Backend").tono).toBe("green");
    expect(fila({ backend: { ok: true, ms: 9000 } }, "Backend").tono).toBe("accent");
    expect(fila({ backend: { ok: true, ms: 9000 } }, "Backend").detalle).toContain("arranque en frío");
  });

  test("con todo sano ninguna fila pide atención", () => {
    expect(filasDeEstado(SANO).every(f => f.tono === "green")).toBe(true);
  });

  test("presencia caducada lo dice en vez de mentir con el último sitio conocido", () => {
    const f = fila({ ...SANO, presencia: { conocida: true, vigente: false, en_casa: true, hace_minutos: 400 } }, "Presencia");
    expect(f.tono).toBe("accent");
    expect(f.detalle).toContain("caducado");
  });

  test("HA que no ha reportado nunca no es HA que dice que estás fuera", () => {
    expect(fila({ ...SANO, presencia: { conocida: false } }, "Presencia").detalle)
      .toBe("HA no ha reportado nunca");
    expect(fila({ ...SANO, presencia: null }, "Presencia").detalle)
      .toBe("sin respuesta del backend");
  });

  test("el resumen apagado y el resumen roto se distinguen", () => {
    expect(fila({ ...SANO, brief: { activo: false } }, "Resumen diario").detalle).toBe("desactivado");
    expect(fila({ ...SANO, brief: { activo: true, pausado: true, pausado_hasta: "2026-09-20" } },
                "Resumen diario").detalle).toContain("20/09/2026");
  });

  test("los avisos al correo con HA sin recoger avisan de que el canal se ha caído", () => {
    const f = fila({ ...SANO, avisos: { activo: true, canal: "correo", sondeo_hace_segundos: 3600 } }, "Avisos");
    expect(f.tono).toBe("accent");
    expect(f.detalle).toContain("60 min sin recogerlos");
  });

  test("el registro con errores se pinta en rojo y los cuenta", () => {
    const f = fila({ ...SANO, registro: { entradas: [{}, {}], errores: 2 } }, "Registro");
    expect(f.tono).toBe("red");
    expect(f.detalle).toBe("2 errores en 7 días");
  });

  test("un gasto con algún modelo sin tarifa lo dice en vez de dar un total corto", () => {
    const f = fila({ ...SANO, gasto: { total: { llamadas: 3, euros: 0.1, euros_incompleto: true } } },
                   "Coste del modelo");
    expect(f.tono).toBe("accent");
    expect(f.detalle).toContain("falta tarifa");
  });
});

describe("resumenEstado", () => {
  test("enseña lo peor que haya, no un recuento", () => {
    const roto = { ...SANO, registro: { entradas: [{}], errores: 1 } };
    expect(resumenEstado(roto).tono).toBe("red");
    expect(resumenEstado(roto).texto).toContain("Registro");
  });

  test("lo rojo gana a lo ámbar", () => {
    const dos = { ...SANO,
      backend:  { ok: true, ms: 9000 },                       // ámbar
      registro: { entradas: [{}], errores: 1 } };             // rojo
    expect(resumenEstado(dos).texto).toContain("Registro");
  });

  test("las filas que aporta el dashboard cuentan igual", () => {
    const extra = [{ nombre: "Outlook", tono: "red", detalle: "sesión caducada" }];
    expect(resumenEstado(SANO, extra).texto).toBe("Outlook: sesión caducada");
  });

  test("sin haber comprobado nada no dice que todo va bien", () => {
    expect(resumenEstado(null).texto).toBe("sin comprobar");
    expect(resumenEstado(SANO).texto).toBe("todo responde");
  });
});

describe("desdeHace y horaCorta", () => {
  afterEach(() => { vi.useRealTimers(); });

  test("una fecha que no existe no inventa un 'hace 56 años'", () => {
    expect(desdeHace(null)).toBe(null);
    expect(desdeHace("no es una fecha")).toBe(null);
  });

  test("el hueco se dice en la unidad que se entiende", () => {
    vi.useFakeTimers();
    vi.setSystemTime(new Date("2026-09-09T12:00:00Z"));
    expect(desdeHace("2026-09-09T11:59:30Z")).toBe("hace 30s");
    expect(desdeHace("2026-09-09T11:30:00Z")).toBe("hace 30 min");
    expect(desdeHace("2026-09-09T06:00:00Z")).toBe("hace 6 h");
    expect(desdeHace("2026-09-05T12:00:00Z")).toBe("hace 4 d");
  });

  test("una entrada de otro día lleva la fecha delante, la de hoy no", () => {
    vi.useFakeTimers();
    vi.setSystemTime(new Date("2026-09-09T12:00:00"));
    expect(horaCorta("2026-09-09T09:30:00")).toBe("09:30:00");
    expect(horaCorta("2026-09-07T09:30:00")).toBe("07/09 09:30:00");
    expect(horaCorta(null)).toBe("");
  });
});
