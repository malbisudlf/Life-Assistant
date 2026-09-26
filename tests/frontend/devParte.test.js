// El parte de la zona de desarrollo: una frase con lo peor de todas las pestañas y una
// insignia en cada botón del menú.
//
// Lo que se fija aquí es que el parte no invente nada: que «no lo sé» salga en gris y
// nunca en verde, que no endurezca el tono de ninguna pestaña (un «sin configurar» o un PC
// apagado no son averías), que lo repetido se agrupe para que no grite, y que el refresco
// de cada minuto no toque lo que gasta cuota.
import { describe, test, expect, vi, afterEach } from "vitest";

import { parteDelSistema, insigniasPorPestana, textoDelParte, leerParte, PESTANAS,
         LECTURAS_AUTO, etiquetaConInsignia } from "../../src/lib/dev";

const AHORA = new Date("2026-09-27T12:00:00Z").getTime();
const haceDias = (d) => new Date(AHORA - d * 86400000).toISOString();

afterEach(() => { vi.useRealTimers(); vi.unstubAllGlobals(); });

// Las formas reales de cada respuesta, en su versión «todo bien».
function sistemaBien(extra = {}) {
  return {
    backend:   { ok: true, ms: 120, version: "abc1234" },
    agente:    { exists: true, offline: false, hostname: "pc" },
    registro:  { errores: 0, entradas: [] },
    presencia: { conocida: true, vigente: true, en_casa: true, hace_minutos: 1 },
    brief:     { activo: true, pausado: false, enviado_hoy: true },
    avisos:    { activo: true, canal: "movil", sondeo_hace_segundos: 10 },
    gasto:     { total: { euros: 1.2, llamadas: 40, euros_incompleto: false }, cacheado_pct: 80 },
    enviados:  [],
    comprobado: AHORA,
    ...extra,
  };
}

const bdBien = () => ({
  migraciones: [{ nombre: "20260910_migraciones_aplicadas", puesta: true }],
  tablas:      [{ tabla: "ideas", existe: true, filas: 12, migracion: "20260501_ideas" }],
  espacio:     { mb: 40, limite_mb: 500, pct: 8, aviso_pct: 80, tablas: [] },
});

const configBien = () => ({
  version: "abc1234",
  zona:    { nombre: "Europe/Madrid", valida: true },
  graph:   { conectado: true, con_refresco: true, expira_en: 1800 },
  grupos:  [{ nombre: "Núcleo", completo: true, faltan: [] }],
});

const jobsBien = () => ({ agentes: [], jobs: [], resultados: [], max_intentos: 3, timeout_segundos: 60 });

const datosBien = () => ({
  fuentes:  { "health-auto-export": { ultima_escritura: new Date().toISOString() } },
  metricas: { fc: { dias_atras: 0, huecos: 0, dias_con_dato: 30, fuentes: ["health-auto-export"] } },
  sin_fuente: 0,
});

const avisosBien = () => ({ activo: true, canal: "movil", reglas: [], enviados: [], presupuesto: { gastado: 0, tope: 10 } });

const ok = (datos) => ({ ok: true, datos, cuando: AHORA });
const fallo = { ok: false, error: "el backend respondió 500", cuando: AHORA };

// Todas las lecturas que no son de GitHub, bien.
function lecturasBien(cambios = {}) {
  return {
    sistema: ok(sistemaBien()),
    jobs:    ok(jobsBien()),
    avisos:  ok(avisosBien()),
    datos:   ok(datosBien()),
    bd:      ok(bdBien()),
    config:  ok(configBien()),
    ...cambios,
  };
}

const parte = (lecturas, opciones = {}) => parteDelSistema(lecturas, { ahora: AHORA, ...opciones });

describe("parteDelSistema: lo que no se sabe", () => {
  test("una lectura fallida va a noLeidas y su pestaña lleva un «?» en gris", () => {
    const p = parte(lecturasBien({ bd: fallo }));
    expect(p.noLeidas).toEqual(["bd"]);
    expect(p.tono).toBe("muted");
    expect(insigniasPorPestana(p).bd).toEqual({ tono: "muted", n: null });
  });

  test("si falla la lectura del sistema, nunca sale verde", () => {
    const p = parte(lecturasBien({ sistema: fallo }));
    expect(p.tono).not.toBe("green");
    expect(p.noLeidas).toContain("estado");
  });

  test("sin ninguna lectura no dice que todo va bien", () => {
    expect(parte({}).tono).toBe("muted");
  });

  test("con el backend caído sale el Backend en rojo, primero, y el parte es rojo", () => {
    const caido = { ...sistemaBien(), backend: { ok: false, ms: null, version: null },
                    agente: null, registro: null, presencia: null, avisos: null, gasto: null, brief: null };
    const p = parte(lecturasBien({ sistema: ok(caido), jobs: fallo, bd: fallo }));
    expect(p.tono).toBe("red");
    expect(p.items[0]).toMatchObject({ pestana: "estado", tono: "red", titulo: "Backend: no responde" });
  });

  test("sin leer crons ni despliegue, las dos van a sinComprobar y el parte puede ser verde", () => {
    const p = parte(lecturasBien());
    expect(p.sinComprobar).toEqual(["crons", "deploy"]);
    expect(p.noLeidas).toEqual([]);
    expect(p.tono).toBe("green");
  });
});

describe("parteDelSistema: no endurece ningún tono", () => {
  test("un grupo de config sin configurar no es un problema", () => {
    const cfg = { ...configBien(), grupos: [{ nombre: "Voz", completo: false, faltan: ["ELEVEN_API_KEY"] }] };
    const p = parte(lecturasBien({ config: ok(cfg) }));
    expect(p.items).toEqual([]);
    expect(p.tono).toBe("green");
  });

  test("el Agente PC apagado no genera nada", () => {
    const sys = sistemaBien({ agente: { exists: true, offline: true, silence_seconds: 7200 } });
    const p = parte(lecturasBien({ sistema: ok(sys) }));
    expect(p.items).toEqual([]);
  });

  test("un sondeo opcional que lleva días callado no genera nada", () => {
    const crons = {
      workflows: [], github: { con_credencial: false }, proceso_desde_hace: 90000,
      sondeos: [{ ruta: "/jobs/pending", nombre: "Agente PC", hace_segundos: 5 * 86400, opcional: true }],
    };
    const p = parte(lecturasBien({ crons: ok(crons) }));
    expect(p.items.filter(i => i.pestana === "crons")).toEqual([]);
  });

  test("una zona horaria inválida es roja, como en la pestaña Config", () => {
    const cfg = { ...configBien(), zona: { nombre: "Marte/Olympus", valida: false } };
    const p = parte(lecturasBien({ config: ok(cfg) }));
    expect(p.items).toEqual([expect.objectContaining({ pestana: "config", tono: "red" })]);
  });
});

describe("parteDelSistema: cada fuente", () => {
  test("una migración sin aplicar es un item rojo en bd que la nombra", () => {
    const bd = { ...bdBien(), migraciones: [{ nombre: "20260924_espacio_bd", puesta: false }] };
    const p = parte(lecturasBien({ bd: ok(bd) }));
    expect(p.items).toHaveLength(1);
    expect(p.items[0]).toMatchObject({ pestana: "bd", tono: "red" });
    expect(p.items[0].titulo).toContain("20260924_espacio_bd");
  });

  test("tres tablas que no existen son UN solo item", () => {
    const tablas = ["a", "b", "c"].map(t => ({ tabla: t, existe: false, migracion: `2026_${t}` }));
    const p = parte(lecturasBien({ bd: ok({ ...bdBien(), tablas }) }));
    const deBd = p.items.filter(i => i.pestana === "bd");
    expect(deBd).toHaveLength(1);
    expect(deBd[0].titulo).toBe("3 tablas no existen");
  });

  test("el espacio sin medir no cuenta; al 96 % es rojo", () => {
    expect(parte(lecturasBien({ bd: ok({ ...bdBien(), espacio: null }) })).items).toEqual([]);
    const lleno = { ...bdBien(), espacio: { mb: 480, limite_mb: 500, pct: 96, aviso_pct: 80, tablas: [] } };
    expect(parte(lecturasBien({ bd: ok(lleno) })).items[0]).toMatchObject({ pestana: "bd", tono: "red" });
  });

  test("un job fallido de hace 10 días no cuenta; uno de ayer sí", () => {
    const job = (dias, id) => ({ id, status: "failed", attempt: 1, claimed_by: "pc",
                                 created_at: haceDias(dias), payload: { accion: "entrega" }, dedupe_key: id });
    const viejo = parte(lecturasBien({ jobs: ok({ ...jobsBien(), jobs: [job(10, "j1")] }) }));
    expect(viejo.items).toEqual([]);
    const nuevo = parte(lecturasBien({ jobs: ok({ ...jobsBien(), jobs: [job(10, "j1"), job(1, "j2")] }) }));
    expect(nuevo.items).toEqual([expect.objectContaining({ pestana: "jobs", tono: "red",
                                                           titulo: "1 job fallido en 7 días" })]);
  });

  test("cinco métricas en rojo son un solo item con como mucho tres nombres", () => {
    const metricas = Object.fromEntries(["fc", "hrv", "pasos", "sueno", "peso"]
      .map(n => [n, { dias_atras: 9, huecos: 0, dias_con_dato: 3, fuentes: [] }]));
    const p = parte(lecturasBien({ datos: ok({ ...datosBien(), metricas }) }));
    const deDatos = p.items.filter(i => i.pestana === "datos");
    expect(deDatos).toHaveLength(1);
    expect(deDatos[0].titulo).toBe("5 métricas sin datos desde hace más de 3 días (fc, hrv, pasos…)");
    expect(deDatos[0].titulo).not.toContain("sueno");
  });

  test("una regla silenciada es un item rojo con su nombre", () => {
    const reglas = [{ regla: "lluvia", enviados: 0, utiles: 0, no_utiles: 3, sin_votar: 0, silenciada: true }];
    const p = parte(lecturasBien({ avisos: ok({ ...avisosBien(), reglas }) }));
    expect(p.items).toHaveLength(1);
    expect(p.items[0]).toMatchObject({ pestana: "avisos", tono: "red" });
    expect(p.items[0].titulo).toContain("lluvia");
  });

  test("la fila «Registro» con errores va a Logs, no a Estado", () => {
    const sys = sistemaBien({ registro: { errores: 2, entradas: [{}, {}] } });
    const p = parte(lecturasBien({ sistema: ok(sys) }));
    expect(p.items).toEqual([expect.objectContaining({ pestana: "logs", tono: "red" })]);
  });

  test("las filas del dashboard entran en Estado", () => {
    const p = parte(lecturasBien(), { filasExtra: [{ nombre: "Outlook", tono: "red", detalle: "sesión caducada" }] });
    expect(p.items).toEqual([expect.objectContaining({ pestana: "estado", titulo: "Outlook: sesión caducada" })]);
  });
});

describe("parteDelSistema: el orden", () => {
  test("rojos antes que ámbar, y dentro de cada tono en el orden del menú", () => {
    const sys = sistemaBien({ presencia: { conocida: true, vigente: false, en_casa: false, hace_minutos: 400 } });
    const reglas = [
      { regla: "tren", enviados: 5, utiles: 1, no_utiles: 4, sin_votar: 0 },          // ámbar
      { regla: "lluvia", enviados: 0, utiles: 0, no_utiles: 3, silenciada: true },    // rojo
    ];
    const bd = { ...bdBien(), migraciones: [{ nombre: "x", puesta: false }] };      // rojo
    const p = parte(lecturasBien({ sistema: ok(sys), avisos: ok({ ...avisosBien(), reglas }), bd: ok(bd) }));
    expect(p.items.map(i => [i.tono, i.pestana])).toEqual([
      ["red", "bd"], ["red", "avisos"], ["accent", "estado"], ["accent", "avisos"],
    ]);
    // Coherente con el menú: bd va antes que avisos en PESTANAS.
    const ids = PESTANAS.map(q => q.id);
    expect(ids.indexOf("bd")).toBeLessThan(ids.indexOf("avisos"));
    expect(p.tono).toBe("red");
  });
});

describe("insigniasPorPestana", () => {
  test("cuenta los items de cada pestaña y se queda con el peor tono", () => {
    const i = insigniasPorPestana({ items: [
      { pestana: "bd", tono: "accent" }, { pestana: "bd", tono: "red" }, { pestana: "avisos", tono: "accent" },
    ], noLeidas: [] });
    expect(i.bd).toEqual({ tono: "red", n: 2 });
    expect(i.avisos).toEqual({ tono: "accent", n: 1 });
  });

  test("una pestaña limpia no aparece", () => {
    const i = insigniasPorPestana(parte(lecturasBien()));
    expect(i).toEqual({});
  });

  test("el lector de pantalla oye qué dice la insignia", () => {
    expect(etiquetaConInsignia("Base de datos", { tono: "red", n: 1 })).toBe("Base de datos: 1 en rojo");
    expect(etiquetaConInsignia("Config", { tono: "muted", n: null })).toContain("no se ha podido");
  });
});

describe("textoDelParte", () => {
  const item = (n) => ({ pestana: "bd", tono: "red", titulo: `cosa ${n}`, detalle: "" });

  test("con seis cosas y un máximo de cuatro dice «+2 más»", () => {
    const t = textoDelParte({ tono: "red", items: [1, 2, 3, 4, 5, 6].map(item), noLeidas: [], sinComprobar: [] }, 4);
    expect(t).toContain("6 cosas que mirar");
    expect(t).toContain("cosa 4");
    expect(t).not.toContain("cosa 5");
    expect(t).toContain("+2 más");
  });

  test("dice qué se ha quedado sin comprobar", () => {
    const t = textoDelParte(parte(lecturasBien()));
    expect(t).toBe("Todo en orden en lo comprobado · Crons y Despliegue sin comprobar (a botón)");
  });

  test("lo que no se ha podido leer se nombra, sin verde", () => {
    const t = textoDelParte(parte(lecturasBien({ bd: fallo, config: fallo })));
    expect(t).toContain("No se ha podido comprobar: Base de datos, Config");
  });
});

describe("leerParte", () => {
  // Registra cada URL pedida. `/dev/jobs` puede fallar a propósito.
  function montar({ fallaJobs = false } = {}) {
    const pedidas = [];
    vi.stubGlobal("fetch", vi.fn(async (url) => {
      pedidas.push(String(url));
      if (fallaJobs && String(url).includes("/dev/jobs")) {
        return { ok: false, status: 500, json: async () => ({}) };
      }
      return { ok: true, status: 200, json: async () => ({ version: "abc" }) };
    }));
    return pedidas;
  }

  test("el refresco automático no toca ni la base de datos, ni la config, ni GitHub", async () => {
    const pedidas = montar();
    const r = await leerParte({ agentId: "pc", incluir: LECTURAS_AUTO });
    expect(Object.keys(r).sort()).toEqual(["avisos", "datos", "jobs", "sistema"]);
    for (const ruta of ["/dev/bd", "/dev/config", "/dev/crons", "/dev/despliegue"]) {
      expect(pedidas.some(u => u.includes(ruta))).toBe(false);
    }
    expect(pedidas.some(u => u.includes("/dev/jobs"))).toBe(true);
    expect(pedidas.some(u => u.includes("/health/diagnostico"))).toBe(true);
  });

  test("un 500 de /dev/jobs deja esa lectura en fallo y las demás bien", async () => {
    montar({ fallaJobs: true });
    const r = await leerParte({ agentId: "pc", incluir: ["sistema", "jobs", "avisos", "datos"] });
    expect(r.jobs.ok).toBe(false);
    expect(r.jobs.error).toContain("500");
    expect(r.sistema.ok).toBe(true);
    expect(r.avisos.ok).toBe(true);
    expect(r.datos.ok).toBe(true);
  });
});
