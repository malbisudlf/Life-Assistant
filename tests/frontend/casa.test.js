import { describe, test, expect } from "vitest";
import {
  accionAlTocar, iconoDominio, estadoFicha, ordenVigentePorEntidad, ordenEfectiva,
  hayOrdenesSinResolver, textoEdad, catalogoViejo, textoPresencia, favoritosEfectivos,
  filtrarCatalogo, escenasYScripts, estadoEsperado, textoEstado, ACCIONES_POR_DOMINIO,
  VENTANA_ORDENES_MS, HECHA_GRACIA_MS, intervaloRefrescoCasa, textoFuenteCasa,
  REFRESCO_ORDENES_MS, REFRESCO_VIVO_MS, REFRESCO_CATALOGO_MS, RECOGIDA_RECIENTE_MS,
  tonoFase, acuseActivar,
} from "../../src/lib/casa";

const luz = (estado, extra = {}) => ({ id: "light.salon", nombre: "Salón", estado, dominio: "light", solo_lectura: false, ...extra });
const AHORA = Date.parse("2026-09-27T12:00:00Z");

describe("accionAlTocar", () => {
  test("se manda lo contrario de lo que se ve", () => {
    expect(accionAlTocar(luz("on"), "on")).toMatchObject({ accion: "apagar", confirmar: false });
    expect(accionAlTocar(luz("off"), "off")).toMatchObject({ accion: "encender", confirmar: false });
    // Lo que manda es lo que se VE (el optimista), no el catálogo.
    expect(accionAlTocar(luz("off"), "on").accion).toBe("apagar");
  });

  test("un aparato que HA no alcanza, o el PC, no se tocan", () => {
    expect(accionAlTocar(luz("unavailable"), "unavailable")).toBeNull();
    expect(accionAlTocar(luz("unknown"), "unknown")).toBeNull();
    expect(accionAlTocar(luz("on", { solo_lectura: true }), "on")).toBeNull();
  });

  test("persianas y cerraduras piden confirmación en las dos direcciones", () => {
    const garaje = { id: "cover.garaje", dominio: "cover", estado: "closed" };
    expect(accionAlTocar(garaje, "closed")).toMatchObject({ accion: "abrir", confirmar: true, etiqueta: "Abrir" });
    expect(accionAlTocar(garaje, "opening")).toMatchObject({ accion: "cerrar", confirmar: true });
    // Un garaje sin sensor vive en «unknown»: se puede abrir igual.
    expect(accionAlTocar(garaje, "unknown").accion).toBe("abrir");
    const puerta = { id: "lock.puerta", dominio: "lock", estado: "locked" };
    expect(accionAlTocar(puerta, "locked")).toMatchObject({ accion: "desbloquear", confirmar: true });
    expect(accionAlTocar(puerta, "unlocked")).toMatchObject({ accion: "bloquear", confirmar: true });
  });

  test("escenas, scripts y reproductores", () => {
    expect(accionAlTocar({ id: "scene.cine", estado: "2026-09-27" }).accion).toBe("activar");
    expect(accionAlTocar({ id: "script.salir", estado: "off" }).accion).toBe("activar");
    expect(accionAlTocar({ id: "media_player.salon", estado: "playing" }).accion).toBe("play_pause");
  });

  test("nunca devuelve toggle y siempre una acción que el backend acepta", () => {
    const estados = ["on", "off", "open", "closed", "locked", "unlocked", "playing", "unknown", ""];
    for (const dominio of Object.keys(ACCIONES_POR_DOMINIO)) {
      for (const estado of estados) {
        const r = accionAlTocar({ id: `${dominio}.x`, estado }, estado);
        if (!r) continue;
        expect(r.accion).not.toMatch(/toggle/);
        expect(ACCIONES_POR_DOMINIO[dominio][r.accion]).toBeTruthy();
      }
    }
  });
});

describe("iconoDominio y textoEstado", () => {
  test("un icono por dominio y uno genérico para el resto", () => {
    expect(iconoDominio("light")).toBe("💡");
    expect(iconoDominio("lock")).toBe("🔒");
    expect(iconoDominio("vacuum")).toBe("❔");
  });

  test("el estado en palabras", () => {
    expect(textoEstado("light", "on")).toBe("encendida");
    expect(textoEstado("cover", "closed")).toBe("cerrada");
    expect(textoEstado("light", "unavailable")).toBe("no disponible");
    // La fecha que pone HA como estado de una escena no le dice nada a nadie.
    expect(textoEstado("scene", "2026-09-27T20:00:00")).toBe("");
  });
});

describe("estadoFicha", () => {
  const pedida = new Date(AHORA - 10_000).toISOString();

  test("optimista mientras va en cola o HA la acaba de recoger", () => {
    const orden = { entidad: "light.salon", servicio: "light.turn_on", estado: "en_cola", pedida };
    expect(estadoFicha(luz("off"), orden, AHORA)).toEqual(
      { estadoVisto: "on", fase: "en_cola", texto: "pedido…" });
    expect(estadoFicha(luz("off"), { ...orden, estado: "recogida" }, AHORA)).toEqual(
      { estadoVisto: "on", fase: "recogida", texto: "HA la recogió" });
  });

  test("si caduca vuelve al catálogo y lo dice", () => {
    const orden = { entidad: "light.salon", servicio: "light.turn_on", estado: "caducada", pedida };
    expect(estadoFicha(luz("off"), orden, AHORA)).toEqual(
      { estadoVisto: "off", fase: "caducada", texto: "no se ejecutó" });
  });

  test("confirmada no lleva marca", () => {
    const orden = { entidad: "light.salon", servicio: "light.turn_on", estado: "confirmada", pedida };
    expect(estadoFicha(luz("on"), orden, AHORA)).toEqual({ estadoVisto: "on", fase: null, texto: "" });
  });

  test("sin orden, o con una de hace más de un cuarto de hora, el del catálogo", () => {
    expect(estadoFicha(luz("on"), null, AHORA).estadoVisto).toBe("on");
    const vieja = { servicio: "light.turn_off", estado: "en_cola",
                    pedida: new Date(AHORA - VENTANA_ORDENES_MS - 1000).toISOString() };
    expect(estadoFicha(luz("on"), vieja, AHORA)).toEqual({ estadoVisto: "on", fase: null, texto: "" });
  });

  test("una escena no tiene estado que esperar", () => {
    expect(estadoEsperado("scene.turn_on")).toBeNull();
    const orden = { servicio: "scene.turn_on", estado: "en_cola", pedida };
    expect(estadoFicha({ id: "scene.cine", estado: "x" }, orden, AHORA).estadoVisto).toBe("x");
  });
});

describe("ordenVigentePorEntidad y ordenEfectiva", () => {
  test("se queda con la última orden de cada entidad", () => {
    const por = ordenVigentePorEntidad([
      { id: "a", entidad: "light.salon", pedida: "2026-09-27T11:00:00Z" },
      { id: "b", entidad: "light.cocina", pedida: "2026-09-27T11:01:00Z" },
      { id: "c", entidad: "light.salon", pedida: "2026-09-27T11:02:00Z" },
    ]);
    expect(por["light.salon"].id).toBe("c");
    expect(por["light.cocina"].id).toBe("b");
    expect(ordenVigentePorEntidad(null)).toEqual({});
  });

  test("el pedido local manda hasta que el backend lo conoce", () => {
    const local = { id: null, servicio: "light.turn_on", momento: AHORA - 1000 };
    expect(ordenEfectiva(null, local, AHORA).estado).toBe("en_cola");
    const vieja = { id: "z", estado: "confirmada", pedida: new Date(AHORA - 60_000).toISOString() };
    expect(ordenEfectiva(vieja, local, AHORA).estado).toBe("en_cola");
    const suya = { id: "k", estado: "recogida", pedida: new Date(AHORA - 500).toISOString() };
    expect(ordenEfectiva(suya, { ...local, id: "k" }, AHORA)).toBe(suya);
    expect(ordenEfectiva(suya, null, AHORA)).toBe(suya);
  });

  test("hay algo sin resolver mientras va en cola o se acaba de recoger", () => {
    const hace = ms => new Date(AHORA - ms).toISOString();
    expect(hayOrdenesSinResolver([{ estado: "en_cola", pedida: hace(1000) }], AHORA)).toBe(true);
    expect(hayOrdenesSinResolver([{ estado: "recogida", pedida: hace(30_000) }], AHORA)).toBe(true);
    expect(hayOrdenesSinResolver([{ estado: "recogida", pedida: hace(3 * 60_000) }], AHORA)).toBe(false);
    expect(hayOrdenesSinResolver([{ estado: "confirmada", pedida: hace(1000) }], AHORA)).toBe(false);
    expect(hayOrdenesSinResolver(null, AHORA)).toBe(false);
  });
});

describe("textoEdad, catalogoViejo y textoPresencia", () => {
  test("bordes de la edad", () => {
    expect(textoEdad(0)).toBe("ahora mismo");
    expect(textoEdad(59)).toBe("hace 59 min");
    expect(textoEdad(60)).toBe("hace 1 h");
    expect(textoEdad(90)).toBe("hace 1 h");
    expect(textoEdad(91)).toBe("hace 1 h");
    expect(textoEdad(null)).toBe("sin dato");
  });

  test("más de hora y media es viejo", () => {
    expect(catalogoViejo(0)).toBe(false);
    expect(catalogoViejo(59)).toBe(false);
    expect(catalogoViejo(60)).toBe(false);
    expect(catalogoViejo(90)).toBe(false);
    expect(catalogoViejo(91)).toBe(true);
    expect(catalogoViejo(null)).toBe(false);
  });

  test("la presencia en una frase", () => {
    expect(textoPresencia({ conocida: true, en_casa: true, hace_minutos: 3, vigente: true }))
      .toBe("En casa · hace 3 min");
    expect(textoPresencia({ conocida: true, en_casa: false, hace_minutos: 12, vigente: true }))
      .toBe("Fuera · hace 12 min");
    expect(textoPresencia({ conocida: true, en_casa: true, hace_minutos: 400, vigente: false }))
      .toBe("En casa · hace 6 h (dato viejo)");
    expect(textoPresencia({ conocida: false })).toBe("Presencia desconocida");
    expect(textoPresencia(null)).toBe("Presencia desconocida");
  });
});

describe("favoritosEfectivos", () => {
  const entidades = Array.from({ length: 30 }, (_, i) => ({ id: `light.l${i}` }));

  test("los guardados que sigan existiendo, en su orden", () => {
    expect(favoritosEfectivos(["light.l3", "light.borrada", "light.l1"], ["light.l0"], entidades))
      .toEqual(["light.l3", "light.l1"]);
  });

  test("sin guardados, o si ya no queda ninguno, los sugeridos", () => {
    expect(favoritosEfectivos([], ["light.l0", "light.l2"], entidades)).toEqual(["light.l0", "light.l2"]);
    expect(favoritosEfectivos(null, ["light.l0"], entidades)).toEqual(["light.l0"]);
    expect(favoritosEfectivos(["light.borrada"], ["light.l0"], entidades)).toEqual(["light.l0"]);
  });

  test("como mucho 24", () => {
    expect(favoritosEfectivos(entidades.map(e => e.id), [], entidades)).toHaveLength(24);
  });
});

describe("filtrarCatalogo y escenasYScripts", () => {
  const entidades = [
    { id: "light.salon_techo", nombre: "Luz del Salón" },
    { id: "light.cocina", nombre: "Luz cocina" },
    { id: "switch.salon_enchufe", nombre: "Enchufe" },
    { id: "scene.noche", nombre: "Noche" },
    { id: "script.cine", nombre: "Cine" },
  ];

  test("todas las palabras, sin mirar mayúsculas", () => {
    expect(filtrarCatalogo(entidades, "SALÓN luz").map(e => e.id)).toEqual(["light.salon_techo"]);
    expect(filtrarCatalogo(entidades, "salon").map(e => e.id))
      .toEqual(["light.salon_techo", "switch.salon_enchufe"]);
    expect(filtrarCatalogo(entidades, "")).toHaveLength(5);
  });

  test("con tope", () => {
    expect(filtrarCatalogo(entidades, "", 2)).toHaveLength(2);
  });

  test("escenas y scripts ordenados por nombre, ocho como mucho", () => {
    expect(escenasYScripts(entidades).map(e => e.id)).toEqual(["script.cine", "scene.noche"]);
    const muchas = Array.from({ length: 12 }, (_, i) => ({ id: `scene.s${i}`, nombre: `S${i}` }));
    expect(escenasYScripts(muchas)).toHaveLength(8);
    expect(escenasYScripts(null)).toEqual([]);
  });
});

describe("Home Assistant en directo", () => {
  const orden = (extra = {}) => ({ id: "k", entidad: "fan.techo", servicio: "fan.turn_on",
    estado: "hecha", momento: AHORA - 2000, ...extra });
  const ventilador = estado => ({ id: "fan.techo", nombre: "Ventilador", estado, dominio: "fan" });

  test("una orden hecha enseña lo pedido durante la gracia, sin marca", () => {
    expect(estadoFicha(ventilador("off"), orden({ estadoEntidad: "on" }), AHORA)).toEqual(
      { estadoVisto: "on", fase: null, texto: "" });
    // El caso que lo trajo: encender el ventilador, y la lectura de justo después todavía
    // dice «off» porque la integración tarda en reflejarlo. Ni esa lectura ni la del
    // refresco inmediato pueden devolver la ficha a «apagada».
    expect(estadoFicha(ventilador("off"), orden({ estadoEntidad: "off" }), AHORA).estadoVisto).toBe("on");
  });

  test("lo que HA dijo que quedó cuenta cuando no hay nada pedido que esperar", () => {
    const altavoz = { id: "media_player.salon", estado: "paused", dominio: "media_player" };
    const playPausa = orden({ entidad: "media_player.salon", servicio: "media_player.media_play_pause",
                              estadoEntidad: "playing" });
    expect(estadoFicha(altavoz, playPausa, AHORA).estadoVisto).toBe("playing");
    expect(estadoFicha(altavoz, { ...playPausa, estadoEntidad: null }, AHORA).estadoVisto).toBe("paused");
  });

  test("la gracia la cierra una lectura posterior, y hasta entonces se pregunta a menudo", () => {
    const hecha = [{ estado: "hecha", pedida: new Date(AHORA - 2000).toISOString() }];
    expect(intervaloRefrescoCasa({ fuente: "vivo", ordenes: hecha }, AHORA)).toBe(REFRESCO_ORDENES_MS);
    // Justo pasada la gracia, todavía una lectura más al ritmo rápido.
    expect(intervaloRefrescoCasa({ fuente: "vivo", ordenes: hecha },
                                 AHORA - 2000 + HECHA_GRACIA_MS + 1000)).toBe(REFRESCO_ORDENES_MS);
    expect(intervaloRefrescoCasa({ fuente: "vivo", ordenes: hecha },
                                 AHORA - 2000 + HECHA_GRACIA_MS + REFRESCO_ORDENES_MS)).toBe(REFRESCO_VIVO_MS);
  });

  test("sin lectura, lo pedido unos segundos y luego lo que diga el refresco", () => {
    expect(estadoFicha(ventilador("off"), orden(), AHORA).estadoVisto).toBe("on");
    const pasada = orden({ estadoEntidad: "on", momento: AHORA - HECHA_GRACIA_MS - 1000 });
    // Alguien lo apagó a mano después: manda el dato de ahora, no la lectura de entonces.
    expect(estadoFicha(ventilador("off"), pasada, AHORA).estadoVisto).toBe("off");
  });

  test("la respuesta de la orden cuenta antes del refresco y sobrevive a él", () => {
    const local = { id: "k", servicio: "fan.turn_on", momento: AHORA - 1000,
                    estado: "hecha", estadoEntidad: "on" };
    expect(ordenEfectiva(null, local, AHORA)).toMatchObject({ estado: "hecha", estadoEntidad: "on" });
    const suya = { id: "k", estado: "hecha", pedida: new Date(AHORA - 1000).toISOString() };
    expect(ordenEfectiva(suya, local, AHORA)).toMatchObject({ estado: "hecha", estadoEntidad: "on" });
    // Mientras viaja, sin estado todavía, sigue siendo «pedido…».
    expect(ordenEfectiva(null, { ...local, id: null, estado: undefined }, AHORA).estado).toBe("en_cola");
  });

  test("una orden hecha no deja el widget preguntando cada 5 s", () => {
    expect(hayOrdenesSinResolver([{ estado: "hecha", pedida: new Date(AHORA).toISOString() }], AHORA)).toBe(false);
    const vieja = [{ estado: "hecha", pedida: new Date(AHORA - 60 * 1000).toISOString() }];
    expect(intervaloRefrescoCasa({ fuente: "vivo", ordenes: vieja }, AHORA)).toBe(REFRESCO_VIVO_MS);
  });

  test("el ritmo del refresco depende de lo que haya", () => {
    const pendiente = [{ estado: "en_cola", pedida: new Date(AHORA).toISOString() }];
    expect(intervaloRefrescoCasa({ fuente: "vivo", ordenes: pendiente }, AHORA)).toBe(REFRESCO_ORDENES_MS);
    expect(intervaloRefrescoCasa({ fuente: "vivo", ha_directo: true }, AHORA)).toBe(REFRESCO_VIVO_MS);
    // HA configurado pero sin contestar: se sigue preguntando a menudo para notar que vuelve.
    expect(intervaloRefrescoCasa({ fuente: "catalogo", ha_directo: true }, AHORA)).toBe(REFRESCO_VIVO_MS);
    expect(intervaloRefrescoCasa({ fuente: "catalogo", ha_directo: false }, AHORA)).toBe(REFRESCO_CATALOGO_MS);
    expect(intervaloRefrescoCasa(null, AHORA)).toBe(REFRESCO_CATALOGO_MS);
  });

  test("el aviso de dato viejo solo cuando el dato es del catálogo", () => {
    const catalogo = edad_min => ({ conocido: true, edad_min });
    expect(textoFuenteCasa({ fuente: "vivo", ha_directo: true, catalogo: catalogo(300) }))
      .toEqual({ texto: "estado de la casa en directo", aviso: false });
    expect(textoFuenteCasa({ fuente: "catalogo", ha_directo: false, catalogo: catalogo(30) }))
      .toEqual({ texto: "estado de la casa de hace 30 min", aviso: false });
    expect(textoFuenteCasa({ fuente: "catalogo", ha_directo: false, catalogo: catalogo(120) }))
      .toEqual({ texto: "estado de la casa de hace 2 h, puede no ser el real", aviso: true });
    // Debería contestar y no lo hace: se dice siempre, aunque el catálogo sea reciente.
    const caido = textoFuenteCasa({ fuente: "catalogo", ha_directo: true, catalogo: catalogo(5) });
    expect(caido.aviso).toBe(true);
    expect(caido.texto).toMatch(/^Home Assistant no contesta/);
    expect(textoFuenteCasa({ catalogo: { conocido: false } })).toEqual({ texto: "", aviso: false });
    // Un backend de antes, sin `fuente`: lo de siempre.
    expect(textoFuenteCasa({ catalogo: catalogo(10) }).texto).toBe("estado de la casa de hace 10 min");
  });
});

describe("Rechazada y sin confirmar", () => {
  const orden = (estado, extra = {}) => ({ id: "k", entidad: "fan.techo", servicio: "fan.turn_on",
    estado, momento: AHORA - 2000, ...extra });
  const ventilador = estado => ({ id: "fan.techo", nombre: "Ventilador", estado, dominio: "fan" });

  test("una rechazada enseña lo que hay y lo dice, sin fingir que se hizo", () => {
    expect(estadoFicha(ventilador("off"), orden("rechazada"), AHORA)).toEqual(
      { estadoVisto: "off", fase: "rechazada", texto: "HA la rechazó" });
    expect(tonoFase("rechazada")).toBe("error");
  });

  test("una sin confirmar no enseña lo pedido: enseña la lectura y avisa", () => {
    const r = estadoFicha(ventilador("off"), orden("sin_confirmar", { estadoEntidad: "on" }), AHORA);
    expect(r.estadoVisto).toBe("off");
    expect(r.fase).toBe("sin_confirmar");
    expect(r.texto).toMatch(/sin confirmar/);
    expect(tonoFase("sin_confirmar")).toBe("aviso");
    // Si una lectura posterior dice lo pedido, el backend la da por confirmada: sin marca.
    expect(estadoFicha(ventilador("on"), orden("confirmada"), AHORA))
      .toEqual({ estadoVisto: "on", fase: null, texto: "" });
  });

  test("el tono de las demás marcas", () => {
    expect(tonoFase("caducada")).toBe("error");
    expect(tonoFase("en_cola")).toBeNull();
    expect(tonoFase(null)).toBeNull();
  });

  test("una sin confirmar hace preguntar a menudo un rato; una rechazada, no", () => {
    const sin = [{ estado: "sin_confirmar", pedida: new Date(AHORA - 2000).toISOString() }];
    expect(hayOrdenesSinResolver(sin, AHORA)).toBe(true);
    expect(intervaloRefrescoCasa({ fuente: "vivo", ordenes: sin }, AHORA)).toBe(REFRESCO_ORDENES_MS);
    expect(hayOrdenesSinResolver(sin, AHORA - 2000 + RECOGIDA_RECIENTE_MS + 1)).toBe(false);
    const rechazada = [{ estado: "rechazada", pedida: new Date(AHORA - 2000).toISOString() }];
    expect(hayOrdenesSinResolver(rechazada, AHORA)).toBe(false);
    expect(intervaloRefrescoCasa({ fuente: "vivo", ordenes: rechazada }, AHORA)).toBe(REFRESCO_VIVO_MS);
  });

  test("la respuesta sin confirmar cuenta antes del refresco", () => {
    const local = { id: "k", servicio: "fan.turn_on", momento: AHORA - 1000, estado: "sin_confirmar" };
    expect(ordenEfectiva(null, local, AHORA).estado).toBe("sin_confirmar");
  });

  test("el acuse de una escena no dice «enviada» si HA no la confirmó", () => {
    expect(acuseActivar("hecha")).toEqual({ texto: "✓ enviada", tipo: "ok" });
    expect(acuseActivar("en_cola")).toEqual({ texto: "✓ enviada", tipo: "ok" });
    expect(acuseActivar("sin_confirmar")).toEqual({ texto: "HA no la confirmó", tipo: "aviso" });
  });
});
