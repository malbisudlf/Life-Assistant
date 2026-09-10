// La lógica de las pestañas Despliegue y Crons de la zona de desarrollo.
//
// Lo que se fija aquí es cuándo algo se pinta en rojo, que es lo único que decide si estas
// dos pantallas sirven o se ignoran: un cron que corrió BIEN pero hace tres semanas está
// tan roto como uno que falla, y un backend que no se ha podido comparar con main no está
// al día — está sin saber.
import { describe, test, expect, vi, afterEach } from "vitest";

import { estadoDespliegue, estadoWorkflow, estadoSondeo, textoCada, shaCorto,
         MARGEN_PROGRAMADO, estadoTabla, resumenMigraciones, estadoGrupo,
         estadoGraph, esperarAlBackend } from "../../src/lib/dev";

// `esperarAlBackend` sondea con fetch a pelo (durante el arranque no hay nada más que
// responda), así que se sustituye; devolverlo a su sitio evita que el siguiente fichero
// de tests herede el doble.
const fetchOriginal = globalThis.fetch;
afterEach(() => { globalThis.fetch = fetchOriginal; });

const AHORA = new Date("2026-09-10T12:00:00Z").getTime();
const haceHoras = h => new Date(AHORA - h * 3600_000).toISOString();

describe("estadoDespliegue", () => {
  test("sin datos no es al día", () => {
    expect(estadoDespliegue(null).tono).toBe("muted");
  });

  test("en local lo dice en vez de comparar contra nada", () => {
    expect(estadoDespliegue({ sha: "dev" }).texto).toMatch(/local/);
  });

  test("al día, en verde y con el sha a la vista", () => {
    const e = estadoDespliegue({ sha: "abcdef1234", conocido: true, al_dia: true, detras: 0 });
    expect(e.tono).toBe("green");
    expect(e.texto).toContain("abcdef1");
  });

  test("commits sin desplegar es rojo y dice cuántos", () => {
    const e = estadoDespliegue({ sha: "abcdef1234", conocido: true, al_dia: false, detras: 3 });
    expect(e.tono).toBe("red");
    expect(e.texto).toContain("3 commits");
  });

  test("uno solo se dice en singular", () => {
    const e = estadoDespliegue({ sha: "abcdef1234", conocido: true, al_dia: false, detras: 1 });
    expect(e.texto).toContain("1 commit por desplegar");
  });

  test("no haber podido comparar no se pinta como al día", () => {
    const e = estadoDespliegue({ sha: "abc", conocido: false, motivo: "ese commit ya no está" });
    expect(e.tono).not.toBe("green");
    expect(e.texto).toBe("ese commit ya no está");
  });
});

describe("estadoWorkflow", () => {
  const cada = h => ({ nombre: "x", fichero: "x.yml", cada_horas: h });

  test("un fallo es rojo", () => {
    const e = estadoWorkflow({ ...cada(24), run: { estado: "completed", resultado: "failure", cuando: haceHoras(2) } }, AHORA);
    expect(e.tono).toBe("red");
    expect(e.texto).toMatch(/falló/);
  });

  test("corrió bien y hace poco: verde", () => {
    const e = estadoWorkflow({ ...cada(24), run: { estado: "completed", resultado: "success", cuando: haceHoras(3) } }, AHORA);
    expect(e.tono).toBe("green");
  });

  test("corrió BIEN pero hace tres semanas: rojo igual", () => {
    // El fallo del que nace la pestaña era el contrario (fallaba y nadie miraba), pero
    // éste es peor de ver: no hay un solo run rojo al que agarrarse.
    const e = estadoWorkflow({ ...cada(168), run: { estado: "completed", resultado: "success", cuando: haceHoras(24 * 21) } }, AHORA);
    expect(e.tono).toBe("red");
    expect(e.texto).toMatch(/toca cada semana/);
  });

  test("dentro del margen no se da la alarma", () => {
    const dentro = 24 * MARGEN_PROGRAMADO - 1;
    const e = estadoWorkflow({ ...cada(24), run: { estado: "completed", resultado: "success", cuando: haceHoras(dentro) } }, AHORA);
    expect(e.tono).toBe("green");
  });

  test("cancelado no es ni éxito ni fallo", () => {
    const e = estadoWorkflow({ ...cada(24), run: { estado: "completed", resultado: "cancelled", cuando: haceHoras(1) } }, AHORA);
    expect(e.tono).toBe("accent");
  });

  test("mientras corre, se dice que corre", () => {
    const e = estadoWorkflow({ ...cada(24), run: { estado: "in_progress", resultado: null, cuando: haceHoras(0.1) } }, AHORA);
    expect(e.tono).toBe("accent");
    expect(e.texto).toMatch(/corriendo/);
  });

  test("no haber corrido nunca no se pinta en verde", () => {
    const e = estadoWorkflow({ ...cada(24), run: null, motivo: null }, AHORA);
    expect(e.tono).toBe("muted");
  });
});

describe("estadoSondeo", () => {
  test("hace segundos: verde", () => {
    expect(estadoSondeo({ hace_segundos: 20 }).tono).toBe("green");
  });

  test("más de diez minutos sin sondear es rojo", () => {
    expect(estadoSondeo({ hace_segundos: 900 }).tono).toBe("red");
  });

  test("un backend recién arrancado no tiene medio sistema caído", () => {
    // Sin esto, cada reconstrucción del add-on dejaba diez filas en rojo durante un rato.
    const e = estadoSondeo({ hace_segundos: null }, 30);
    expect(e.tono).toBe("muted");
    expect(e.texto).toMatch(/backend lleva/);
  });

  test("pero si lleva horas en pie y nadie sondea, se avisa", () => {
    expect(estadoSondeo({ hace_segundos: null }, 7200).tono).toBe("accent");
  });

  test("lo que depende del PC encendido no se pinta en rojo por callar", () => {
    // El PC está apagado la mayor parte del día: llamar avería a eso es llamar avería a
    // la noche.
    expect(estadoSondeo({ hace_segundos: 4000, opcional: true }).tono).toBe("green");
  });
});

describe("textoCada y shaCorto", () => {
  test("las horas se dicen en días y semanas cuando cuadran", () => {
    expect(textoCada(24)).toBe("día");
    expect(textoCada(168)).toBe("semana");
    expect(textoCada(48)).toBe("2 días");
    expect(textoCada(6)).toBe("6 h");
  });

  test("el sha se acorta a lo que enseña git", () => {
    expect(shaCorto("a54b78bcafe")).toBe("a54b78b");
  });

  test("lo que no es un sha se deja como está", () => {
    expect(shaCorto("desconocida")).toBe("desconocida");
    expect(shaCorto("")).toBe("—");
  });
});

describe("estadoTabla", () => {
  test("una tabla que no existe nombra la migración que falta", () => {
    const e = estadoTabla({ tabla: "salud_ajustes", existe: false, migracion: "20260824_salud_ajustes" });
    expect(e.tono).toBe("red");
    expect(e.texto).toContain("20260824_salud_ajustes");
  });

  test("cero filas no es rojo: hay tablas que solo se llenan cuando pasa algo", () => {
    expect(estadoTabla({ existe: true, filas: 0 }).tono).toBe("muted");
  });

  test("sin cuenta de filas no se dice que esté vacía", () => {
    const e = estadoTabla({ existe: true, filas: null });
    expect(e.texto).not.toContain("0");
    expect(e.tono).toBe("accent");
  });

  test("no haber podido consultar no es no existir", () => {
    const e = estadoTabla({ existe: null, motivo: "Supabase no responde" });
    expect(e.tono).toBe("accent");
    expect(e.texto).toBe("Supabase no responde");
  });
});

describe("resumenMigraciones", () => {
  test("todas aplicadas, en verde", () => {
    const e = resumenMigraciones({ migraciones: [{ nombre: "a", puesta: true }] });
    expect(e.tono).toBe("green");
  });

  test("las que faltan se nombran, que es lo que hay que pegar en Supabase", () => {
    const e = resumenMigraciones({ migraciones: [
      { nombre: "20260824_salud_ajustes", puesta: false },
      { nombre: "20260909_ideas_dev", puesta: true },
    ] });
    expect(e.tono).toBe("red");
    expect(e.texto).toContain("20260824_salud_ajustes");
    expect(e.texto).not.toContain("ideas_dev");
  });

  test("no haber podido comprobarlo no es que estén todas", () => {
    const e = resumenMigraciones({ migraciones: null, motivo: "falta aplicar la migración X" });
    expect(e.tono).not.toBe("green");
    expect(e.texto).toContain("falta aplicar");
  });
});

describe("estadoGrupo y estadoGraph", () => {
  test("sin configurar no es un error: media aplicación es opcional", () => {
    const e = estadoGrupo({ completo: false, faltan: ["SMTP_HOST"] });
    expect(e.tono).toBe("muted");
    expect(e.texto).toContain("SMTP_HOST");
  });

  test("una sesión de Microsoft sin refresh token sí es rojo", () => {
    // Morirá cuando expire el acceso y habrá que volver a pasar por el login a mano.
    expect(estadoGraph({ conectado: true, con_refresco: false }).tono).toBe("red");
  });

  test("conectada y con refresco, en verde y con lo que le queda al acceso", () => {
    const e = estadoGraph({ conectado: true, con_refresco: true, expira_en: 1800 });
    expect(e.tono).toBe("green");
    expect(e.texto).toContain("30 min");
  });

  test("un acceso expirado no es una sesión rota: se renueva sola al usarla", () => {
    const e = estadoGraph({ conectado: true, con_refresco: true, expira_en: -10 });
    expect(e.tono).toBe("accent");
  });

  test("no haber podido consultar no es estar desconectado", () => {
    expect(estadoGraph({ conectado: null, motivo: "no se ha podido consultar" }).tono).toBe("accent");
  });
});

describe("esperarAlBackend", () => {
  // Cada respuesta del guion es un sondeo: `null` significa "no responde", que es lo que
  // pasa mientras el add-on está reconstruyendo.
  function guion(respuestas) {
    globalThis.fetch = vi.fn(async () => {
      const v = respuestas.shift();
      if (v == null) throw new Error("sin red");
      return { ok: true, json: async () => ({ version: v }) };
    });
  }
  const esperar = extra => esperarAlBackend({ antes: "viejo", cada: 0, dormir: async () => {}, ...extra });

  test("el sha nuevo se da por bueno en cuanto aparece", async () => {
    guion(["viejo", null, "nuevo"]);
    const fin = await esperar();
    expect(fin).toMatchObject({ ok: true, version: "nuevo", cambio: true });
  });

  test("volver con el MISMO sha también es haber vuelto", async () => {
    // El caso que se pintaba como fallo: reconstruir estando ya al día devuelve el mismo
    // commit, y esperar un cambio dejaba «no ha vuelto a tiempo» tras tres minutos de una
    // reconstrucción perfecta.
    guion(["viejo", null, null, "viejo"]);
    const fin = await esperar();
    expect(fin).toMatchObject({ ok: true, version: "viejo", cambio: false, cayo: true });
  });

  test("mientras no se haya caído, seguir respondiendo lo mismo no es haber vuelto", async () => {
    // El Supervisor tarda en parar el add-on: justo después de lanzarla sigue contestando
    // el proceso viejo, y darlo por terminado ahí sería mentir.
    guion(["viejo", "viejo", "viejo"]);
    const fin = await esperar({ intentos: 3 });
    expect(fin.ok).toBe(false);
  });

  test("si nunca se cae, se distingue de si se cayó y no volvió", async () => {
    // Son dos averías distintas: una es que la reconstrucción no arrancó (permisos del
    // add-on), la otra que arrancó y algo se rompió. Llevan a mirar sitios distintos.
    guion(["viejo", "viejo", "viejo"]);
    expect((await esperar({ intentos: 3 })).cayo).toBe(false);
    guion([null, null, null]);
    expect((await esperar({ intentos: 3 })).cayo).toBe(true);
  });
});
