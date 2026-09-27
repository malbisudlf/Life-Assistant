// Lógica pura del widget «Casa»: qué se manda al tocar una ficha, qué enseña mientras la
// orden viaja y qué favoritos se pintan. El componente vive en Dashboard.jsx y solo pinta.
//
// La idea que lo ordena todo: lo que se ve puede no ser lo que hay. Con Home Assistant en
// directo (`fuente: "vivo"`) el estado es el de hace unos segundos; si HA no contesta, o
// no hay directo, sale del catálogo, que llega cada hora, y el «encendida» puede tener
// cincuenta minutos. Por eso al tocar se manda lo CONTRARIO DE LO QUE SE VE (encender o
// apagar), nunca `toggle`: si el dato iba por detrás y la luz ya estaba apagada, un toggle
// la encendería justo cuando querías apagarla.

// Espejo de `_CASA_ACCIONES_WIDGET` en backend/main.py. El servicio lo fija el backend; esto
// solo sirve para saber qué estado esperar mientras la orden viaja.
export const ACCIONES_POR_DOMINIO = {
  light:         { encender: "light.turn_on", apagar: "light.turn_off" },
  switch:        { encender: "switch.turn_on", apagar: "switch.turn_off" },
  fan:           { encender: "fan.turn_on", apagar: "fan.turn_off" },
  input_boolean: { encender: "input_boolean.turn_on", apagar: "input_boolean.turn_off" },
  scene:         { activar: "scene.turn_on" },
  script:        { activar: "script.turn_on" },
  media_player:  { play_pause: "media_player.media_play_pause" },
  cover:         { abrir: "cover.open_cover", cerrar: "cover.close_cover" },
  lock:          { bloquear: "lock.lock", desbloquear: "lock.unlock" },
};

const ENCENDIBLES   = new Set(["light", "switch", "fan", "input_boolean"]);
const SIN_ESTADO    = new Set(["scene", "script"]);
const NO_RESPONDE   = new Set(["unavailable", "unknown"]);
// Pasado esto, una orden ya no dice nada de la ficha. Es la misma ventana con la que el
// backend devuelve las órdenes recientes (CASA_ORDENES_VENTANA).
export const VENTANA_ORDENES_MS = 15 * 60 * 1000;
// Mientras HA no la recoge, o la acaba de recoger, el widget pregunta más a menudo.
export const RECOGIDA_RECIENTE_MS = 2 * 60 * 1000;
export const CASA_MAX_FAVORITOS  = 24;
// Una orden que HA ya ejecutó en directo enseña lo pedido durante estos segundos, diga lo
// que diga la lectura: hay integraciones (las de la nube, y a veces ESPHome o MQTT por
// carrera) que tardan un momento en reflejar el cambio, y la lectura de justo después
// todavía dice el estado de antes. La ficha no puede volver a «apagada» medio segundo
// después de encender. Pasado esto, manda lo que diga HA, y lo que lo dice es una lectura
// POSTERIOR: el «ahora» con el que se mide es la hora de la última lectura (ver Dashboard).
export const HECHA_GRACIA_MS      = 10 * 1000;
// Cada cuánto pregunta el widget, siempre solo con la pestaña a la vista y el widget
// puesto. Con HA en directo, cada pocos segundos: la pregunta no sale de la LAN de casa y
// no cuesta nada, y es lo que hace que el mando no mienta. Sin directo, el catálogo no
// cambia más que cada hora y preguntar más a menudo no traería nada nuevo.
export const REFRESCO_ORDENES_MS  = 5 * 1000;
export const REFRESCO_VIVO_MS     = 10 * 1000;
export const REFRESCO_CATALOGO_MS = 60 * 1000;

const ETIQUETAS = {
  encender: "Encender", apagar: "Apagar", activar: "Activar", play_pause: "Play/pausa",
  abrir: "Abrir", cerrar: "Cerrar", bloquear: "Bloquear", desbloquear: "Desbloquear",
};

/** «Abrir», «Desbloquear»… para el botón de confirmar. */
export function etiquetaAccion(accion) {
  return ETIQUETAS[accion] || String(accion || "");
}

export function dominioDe(entidad) {
  return entidad?.dominio || String(entidad?.id || "").split(".")[0];
}

/** Qué acción manda un toque sobre la ficha, según lo que se VE. Null si no se puede
 *  tocar: el PC (solo lectura) o un aparato que HA no alcanza. */
export function accionAlTocar(entidad, estadoVisto) {
  if (!entidad || entidad.solo_lectura) return null;
  const dominio = dominioDe(entidad);
  const estado  = String(estadoVisto ?? entidad.estado ?? "").toLowerCase();
  const con = (accion, confirmar = false) => ({ accion, confirmar, etiqueta: ETIQUETAS[accion] });

  if (ENCENDIBLES.has(dominio)) {
    if (NO_RESPONDE.has(estado)) return null;
    return con(estado === "on" ? "apagar" : "encender");
  }
  // Un aparato que HA no alcanza no va a hacer nada con la orden. «unknown» sí se deja en
  // persianas y cerraduras: un garaje sin sensor de posición vive en ese estado.
  if (estado === "unavailable" && !SIN_ESTADO.has(dominio)) return null;
  // Persianas y cerraduras se confirman siempre, en las dos direcciones: es la misma
  // frontera que `_casa_pide_confirmar` en el backend.
  if (dominio === "cover") return con(estado === "open" || estado === "opening" ? "cerrar" : "abrir", true);
  if (dominio === "lock")  return con(estado === "locked" ? "desbloquear" : "bloquear", true);
  if (SIN_ESTADO.has(dominio)) return con("activar");
  if (dominio === "media_player") return con("play_pause");
  return null;
}

const ICONOS = {
  light: "💡", switch: "🔌", fan: "🌀", input_boolean: "🎚", scene: "🎬", script: "📜",
  media_player: "🔊", cover: "🪟", lock: "🔒",
};
export function iconoDominio(dominio) {
  return ICONOS[dominio] || "❔";
}

/** El estado en palabras, para debajo del nombre. Lo desconocido se enseña crudo. */
export function textoEstado(dominio, estado) {
  const e = String(estado || "").toLowerCase();
  if (e === "unavailable") return "no disponible";
  // Una escena no tiene estado (HA pone la fecha de la última vez, o «unknown»).
  if (SIN_ESTADO.has(dominio)) return "";
  if (e === "unknown" || e === "") return "sin estado";
  const TEXTOS = {
    on: "encendida", off: "apagada", open: "abierta", opening: "abriéndose",
    closed: "cerrada", closing: "cerrándose", locked: "bloqueada", unlocked: "desbloqueada",
    locking: "bloqueándose", unlocking: "desbloqueándose", playing: "sonando",
    paused: "en pausa", idle: "parada", standby: "en reposo",
  };
  return TEXTOS[e] || e;
}

/** Si la ficha se pinta como «encendida» (fondo y borde de acento). */
export function estadoActivo(estado) {
  return ["on", "open", "opening", "playing", "unlocked"].includes(String(estado || "").toLowerCase());
}

// Lo que deja la orden si sale bien. Sin entrada, no hay estado que esperar (escenas,
// scripts, play/pausa) y la ficha sigue enseñando el del catálogo.
const ESPERADO = {
  turn_on: "on", turn_off: "off", lock: "locked", unlock: "unlocked",
  open_cover: "open", close_cover: "closed",
};
export function estadoEsperado(servicio) {
  const [dominio, accion] = String(servicio || "").split(".");
  if (SIN_ESTADO.has(dominio)) return null;
  return ESPERADO[accion] || null;
}

function momentoDe(orden) {
  if (typeof orden?.momento === "number") return orden.momento;
  const t = Date.parse(orden?.pedida || "");
  return Number.isNaN(t) ? null : t;
}

/** Qué enseña una ficha: el estado que se ve y la marca de cómo va su orden.
 *
 *  Mientras la orden va en cola o HA la acaba de recoger, se ve ya el estado esperado
 *  (optimista): es lo que has pedido y lo que casi siempre va a pasar. Si caduca, vuelve
 *  al del catálogo y lo dice — no se queda fingiendo que se encendió.
 *
 *  Con HA en directo hay tres finales: `hecha` (HA la ejecutó), `rechazada` (HA dijo que
 *  no: ni se hizo ni se encoló) y `sin_confirmar` (HA la recibió y no contestó; no se
 *  repite, y la lectura siguiente dice qué pasó). */
export function estadoFicha(entidad, orden, ahoraMs) {
  const delCatalogo = entidad?.estado ?? "";
  const momento = momentoDe(orden);
  if (!orden || (momento != null && ahoraMs - momento > VENTANA_ORDENES_MS)) {
    return { estadoVisto: delCatalogo, fase: null, texto: "" };
  }
  const esperado = estadoEsperado(orden.servicio);
  switch (orden.estado) {
    case "en_cola":
      return { estadoVisto: esperado ?? delCatalogo, fase: "en_cola", texto: "pedido…" };
    case "recogida":
      return { estadoVisto: esperado ?? delCatalogo, fase: "recogida", texto: "HA la recogió" };
    case "caducada":
      return { estadoVisto: delCatalogo, fase: "caducada", texto: "no se ejecutó" };
    case "rechazada":
      // HA dijo que no (el usuario del backend no puede, o los datos no valían): no se ha
      // hecho ni va a hacerse, así que la ficha enseña lo que hay y lo dice.
      return { estadoVisto: delCatalogo, fase: "rechazada", texto: "HA la rechazó" };
    case "sin_confirmar":
      // HA la recibió y no contestó: puede haberse hecho o no. Nada de optimismo —lo pedido
      // podría ser mentira— y nada de repetirla: se enseña lo que diga la lectura, que el
      // backend ha forzado a ser nueva, y se avisa. Si esa lectura dice lo pedido, el
      // backend la pasa a «confirmada» y la marca se va sola.
      return { estadoVisto: delCatalogo, fase: "sin_confirmar", texto: "sin confirmar: mira en unos segundos" };
    case "hecha": {
      // HA la ejecutó en directo. En los primeros segundos manda lo pedido: una lectura
      // de justo después puede ser todavía la de antes, y darle prioridad era lo que
      // devolvía la ficha a «apagada» con el ventilador encendido. `estadoEntidad` (lo
      // que HA dijo que cambió durante la orden) solo cuenta cuando no hay nada pedido
      // que esperar: una escena, un play/pausa. Después, lo que traiga el refresco: si
      // alguien apaga el ventilador a mano un minuto más tarde, la ficha tiene que
      // enterarse. Sin marca: ya no hay nada que esperar.
      const reciente = momento != null && ahoraMs - momento < HECHA_GRACIA_MS;
      const visto = reciente ? (esperado || orden.estadoEntidad || delCatalogo) : delCatalogo;
      return { estadoVisto: visto, fase: null, texto: "" };
    }
    default:
      // Confirmada: el catálogo ya dice lo que se pidió, no hay nada que marcar.
      return { estadoVisto: delCatalogo, fase: null, texto: "" };
  }
}

/** Cómo se pinta la marca de una ficha: `error` lo que no se ha hecho (caducada,
 *  rechazada), `aviso` lo que no se sabe (sin confirmar), null lo demás. */
export function tonoFase(fase) {
  if (fase === "caducada" || fase === "rechazada") return "error";
  if (fase === "sin_confirmar") return "aviso";
  return null;
}

/** El acuse del botón de una escena o un script, que no tiene estado que enseñar: según
 *  en qué quedó la orden al mandarla. «✓ enviada» sería mentir si HA no la confirmó. */
export function acuseActivar(estadoOrden) {
  if (estadoOrden === "sin_confirmar") return { texto: "HA no la confirmó", tipo: "aviso" };
  return { texto: "✓ enviada", tipo: "ok" };
}

/** La ÚLTIMA orden de cada entidad: es la que decide lo que se ve. */
export function ordenVigentePorEntidad(ordenes) {
  const por = {};
  for (const o of ordenes || []) {
    if (!o?.entidad) continue;
    const previa = por[o.entidad];
    const t = momentoDe(o), tp = momentoDe(previa);
    if (!previa || t == null || tp == null || t >= tp) por[o.entidad] = o;
  }
  return por;
}

/** La orden que manda en una ficha: la del backend o el pedido local que aún no ha
 *  vuelto en `/casa/estado`. El local gana mientras el backend no lo conozca, que es el
 *  «pedido…» instantáneo al tocar. Si la respuesta de `POST /casa/orden` ya dijo en qué
 *  quedó (`hecha`, y el estado si HA lo dijo al contestar), eso es lo que enseña hasta el
 *  refresco, y ese estado se conserva cuando el backend devuelve la misma orden sin él. */
export function ordenEfectiva(delServidor, local, ahoraMs) {
  if (!local || ahoraMs - local.momento > VENTANA_ORDENES_MS) return delServidor || null;
  if (delServidor && delServidor.id === local.id) {
    return local.estadoEntidad ? { ...delServidor, estadoEntidad: local.estadoEntidad } : delServidor;
  }
  if (delServidor && (momentoDe(delServidor) ?? 0) > local.momento) return delServidor;
  return { ...local, estado: local.estado || "en_cola" };
}

/** Si hay algo sin resolver: lo que marca si el widget pregunta cada 5 s o cada minuto. */
export function hayOrdenesSinResolver(ordenes, ahoraMs) {
  return (ordenes || []).some(o => {
    if (!o) return false;
    if (o.estado === "en_cola") return true;
    const t = momentoDe(o);
    // Una sin confirmar también: la lectura siguiente es la que dice si se hizo.
    return (o.estado === "recogida" || o.estado === "sin_confirmar")
      && t != null && ahoraMs - t < RECOGIDA_RECIENTE_MS;
  });
}

/** Si una orden directa sigue en su gracia, o acaba de salir de ella. No está «sin
 *  resolver» (HA ya la ejecutó), pero mientras dura la gracia la ficha enseña lo pedido,
 *  y lo que la cierra tiene que ser una lectura hecha DESPUÉS de que HA haya tenido tiempo
 *  de reflejar el cambio. Al ritmo normal (10 s) la última lectura antes de cerrarla podía
 *  ser la de justo después de la orden, la que todavía dice el estado de antes. */
export function hayHechaReciente(ordenes, ahoraMs) {
  return (ordenes || []).some(o => {
    if (o?.estado !== "hecha") return false;
    const t = momentoDe(o);
    return t != null && ahoraMs - t < HECHA_GRACIA_MS + REFRESCO_ORDENES_MS;
  });
}

export function textoEdad(min) {
  if (min == null || Number.isNaN(Number(min))) return "sin dato";
  if (min < 1)  return "ahora mismo";
  if (min < 60) return `hace ${Math.floor(min)} min`;
  return `hace ${Math.floor(min / 60)} h`;
}

/** Con más de hora y media, el estado del catálogo puede no ser el real: HA lo manda cada
 *  hora, así que pasado ese margen es que se ha saltado al menos un envío. */
export function catalogoViejo(min) {
  return min != null && min > 90;
}

/** Cada cuánto pregunta el widget (ver las constantes REFRESCO_*). Con directo configurado
 *  pregunta a menudo aunque HA no conteste: es lo que hace que el aviso de «no contesta»
 *  se quite solo en cuanto HA vuelve. */
export function intervaloRefrescoCasa(datos, ahoraMs) {
  if (hayOrdenesSinResolver(datos?.ordenes, ahoraMs)) return REFRESCO_ORDENES_MS;
  if (hayHechaReciente(datos?.ordenes, ahoraMs)) return REFRESCO_ORDENES_MS;
  if (datos?.fuente === "vivo" || datos?.ha_directo) return REFRESCO_VIVO_MS;
  return REFRESCO_CATALOGO_MS;
}

/** La segunda mitad de la línea de estado: de dónde sale lo que se ve y si hay que
 *  desconfiar. `aviso` pinta el texto en color de aviso. El «puede no ser el real» solo
 *  sale cuando el dato es del catálogo: con HA en directo sería ruido, y un aviso que
 *  sale siempre acaba sin leerse. */
export function textoFuenteCasa(datos) {
  if (!datos?.catalogo?.conocido) return { texto: "", aviso: false };
  if (datos.fuente === "vivo") return { texto: "estado de la casa en directo", aviso: false };
  const edad = datos.catalogo.edad_min;
  if (datos.ha_directo) {
    return {
      texto: `Home Assistant no contesta: estado de la casa de ${textoEdad(edad)}, puede no ser el real`,
      aviso: true,
    };
  }
  const viejo = catalogoViejo(edad);
  return { texto: `estado de la casa de ${textoEdad(edad)}${viejo ? ", puede no ser el real" : ""}`, aviso: viejo };
}

/** La primera mitad de la línea de estado: dónde estás y de cuándo es el dato. */
export function textoPresencia(p) {
  if (!p?.conocida) return "Presencia desconocida";
  const donde = p.en_casa ? "En casa" : "Fuera";
  const cuando = p.hace_minutos != null ? ` · ${textoEdad(p.hace_minutos)}` : "";
  return `${donde}${cuando}${p.vigente === false ? " (dato viejo)" : ""}`;
}

/** Los favoritos que se pintan: los guardados que sigan existiendo, en su orden; si no
 *  hay (o ninguno sigue en el catálogo), los sugeridos por el backend. */
export function favoritosEfectivos(guardados, sugeridas, entidades) {
  const existen = new Set((entidades || []).map(e => e.id));
  if (Array.isArray(guardados) && guardados.length) {
    const vivos = guardados.filter(id => existen.has(id));
    if (vivos.length) return vivos.slice(0, CASA_MAX_FAVORITOS);
  }
  return (sugeridas || []).filter(id => existen.has(id)).slice(0, CASA_MAX_FAVORITOS);
}

/** El buscador del modo edición. Mismo criterio que `_j_casa_dispositivos`: todas las
 *  palabras (hasta cuatro) tienen que aparecer en el id o en el nombre. */
export function filtrarCatalogo(entidades, texto, max = 50) {
  const palabras = String(texto || "").toLowerCase().split(/\s+/).filter(Boolean).slice(0, 4);
  const lista = (entidades || []).filter(e =>
    palabras.every(p => `${e.id || ""} ${e.nombre || ""}`.toLowerCase().includes(p)));
  return lista.slice(0, max);
}

/** La fila de botones de arriba: escenas y scripts por nombre, ocho como mucho. */
export function escenasYScripts(entidades) {
  return (entidades || [])
    .filter(e => SIN_ESTADO.has(dominioDe(e)))
    .sort((a, b) => String(a.nombre || a.id).localeCompare(String(b.nombre || b.id), "es"))
    .slice(0, 8);
}
