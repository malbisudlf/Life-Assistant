// Lógica pura de la vista de Jarvis a pantalla completa (src/components/jarvis/).
// Lo que se pinta vive en el componente; aquí, lo que decide QUÉ se pinta: en qué
// estado está el reactor, cómo se llama el modelo que ha contestado, qué protocolos
// (herramientas) se han usado y cómo se trocea el texto de una respuesta en párrafos,
// listas y negritas sin meter HTML de nadie en la página.

/** El estado del reactor, por orden de prioridad. La llamada manda sobre todo: es lo
 *  único que dice si el micrófono está abierto. Después, lo que espera tu permiso,
 *  porque no avanza solo. */
export function estadoHud({ enLlamada, faseLlamada, pensando, pendiente, escuchando, hablando } = {}) {
  if (enLlamada) {
    return ["escuchando", "pensando", "hablando"].includes(faseLlamada) ? faseLlamada : "escuchando";
  }
  if (pensando)   return "pensando";
  if (pendiente)  return "alerta";
  if (escuchando) return "escuchando";
  if (hablando)   return "hablando";
  return "reposo";
}

/** Lo que dice el reactor debajo, en mayúsculas de HUD. */
export const TEXTO_ESTADO = {
  reposo:     "A su servicio",
  pensando:   "Procesando",
  escuchando: "Escuchando",
  hablando:   "Respondiendo",
  alerta:     "Autorización requerida",
};

/** «claude-opus-5-5» → «Opus 5.5». Lo que no se reconoce se enseña tal cual: mejor un
 *  id feo que un nombre bonito inventado. Vacío si no se sabe. */
export function nombreModelo(id) {
  const m = /^claude-([a-z]+)-(\d+)-(\d+)/.exec(String(id || "").trim());
  if (!m) return String(id || "").trim();
  return `${m[1].charAt(0).toUpperCase()}${m[1].slice(1)} ${m[2]}.${m[3]}`;
}

/** El motor que va a pensar el próximo turno, tal como lo puede saber el cliente: lo
 *  pedido, corregido con lo que dijo el último turno (si pidió potencia y el servicio
 *  contestó con otro, es que no está actualizado, y se dice). */
export function motorEsperado({ potente, ultimo } = {}) {
  const pedido = potente ? "Opus 5.5" : "Sonnet 5.5";
  if (!ultimo) return { nombre: pedido, nota: "" };
  if (ultimo.motor === "openai") return { nombre: pedido, nota: "El último turno lo contestó el respaldo" };
  const real = nombreModelo(ultimo.modelo);
  if (potente && ultimo.potente && real && real !== pedido) {
    return { nombre: real, nota: "El servicio de caja aún no acepta la potencia máxima" };
  }
  return { nombre: pedido, nota: "" };
}

/** Los protocolos usados en la conversación, del más reciente al más antiguo y sin
 *  repetir, con cuántas veces. */
export function protocolosUsados(mensajes = [], max = 8) {
  const cuenta = new Map();
  for (let i = mensajes.length - 1; i >= 0; i--) {
    for (const h of mensajes[i]?.herramientas || []) {
      cuenta.set(h, (cuenta.get(h) || 0) + 1);
    }
  }
  return [...cuenta.entries()].slice(0, max).map(([nombre, veces]) => ({ nombre, veces }));
}

/** «agenda_semana» → «AGENDA SEMANA». */
export function nombreProtocolo(nombre) {
  return String(nombre || "").replace(/_/g, " ").toUpperCase();
}

/** Trocea una respuesta en bloques: párrafos y listas, y cada línea en trozos de texto
 *  normal y negrita (`**así**`). Devuelve datos, no HTML: el componente los pinta como
 *  nodos de React, así que nada de lo que escriba el modelo llega a ser marcado. */
export function trocearRespuesta(texto) {
  const bloques = [];
  let lista = null;
  for (const bruta of String(texto || "").split("\n")) {
    const linea = bruta.trimEnd();
    const item  = /^\s*(?:[-•*]|\d+[.)])\s+(.*)$/.exec(linea);
    if (item) {
      if (!lista) { lista = { tipo: "lista", items: [] }; bloques.push(lista); }
      lista.items.push(trozosEnLinea(item[1]));
      continue;
    }
    lista = null;
    if (!linea.trim()) continue;
    const titulo = /^#{1,6}\s+(.*)$/.exec(linea);
    bloques.push(titulo
      ? { tipo: "titulo", trozos: trozosEnLinea(titulo[1]) }
      : { tipo: "parrafo", trozos: trozosEnLinea(linea) });
  }
  return bloques;
}

function trozosEnLinea(linea) {
  const trozos = [];
  const re = /\*\*([^*]+)\*\*/g;
  let desde = 0;
  let m;
  while ((m = re.exec(linea))) {
    if (m.index > desde) trozos.push({ texto: linea.slice(desde, m.index), fuerte: false });
    trozos.push({ texto: m[1], fuerte: true });
    desde = m.index + m[0].length;
  }
  if (desde < linea.length) trozos.push({ texto: linea.slice(desde), fuerte: false });
  return trozos;
}

/** Cuánto se tarda en «escribir» una respuesta en pantalla: rápido y con tope, porque
 *  es adorno y nadie debe esperar a que acabe para leer. */
export function duracionTecleo(texto, { msPorLetra = 9, maxMs = 1600 } = {}) {
  return Math.min(maxMs, String(texto || "").length * msPorLetra);
}

/** «12,4 s» o «850 ms». */
export function textoDuracion(ms) {
  if (!Number.isFinite(ms) || ms < 0) return "";
  if (ms < 1000) return `${Math.round(ms)} ms`;
  return `${(ms / 1000).toFixed(1).replace(".", ",")} s`;
}
