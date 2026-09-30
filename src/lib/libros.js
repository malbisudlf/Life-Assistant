// ── LIBROS: ESTADO, ORDEN Y FECHAS ───────────────────────────────
// Lógica pura del widget de Libros. Trabaja sobre lo que devuelve `GET /libros`
// (`titulo`, `autor`, `portada`, `empezado`, `terminado`, `created_at`). El estado no
// se guarda: sale de las fechas, así que no puede desincronizarse de ellas.

import { MONTHS_ES } from "./helpers";

// «leyendo» = empezado y sin terminar. Sin fechas, «pendiente»: un libro apuntado sin
// haberlo abierto todavía.
export function estadoLibro(libro) {
  if (libro?.terminado) return "terminado";
  if (libro?.empezado) return "leyendo";
  return "pendiente";
}

// Lo que se lee ahora, primero (el empezado más reciente arriba); luego los pendientes;
// luego lo terminado, del más reciente al más antiguo.
export function agruparLibros(libros) {
  const lista = Array.isArray(libros) ? libros : [];
  const porFechaDesc = (campo) => (a, b) =>
    String(b[campo] || "").localeCompare(String(a[campo] || ""))
    || String(b.created_at || "").localeCompare(String(a.created_at || ""));
  return {
    leyendo:    lista.filter(l => estadoLibro(l) === "leyendo").sort(porFechaDesc("empezado")),
    pendientes: lista.filter(l => estadoLibro(l) === "pendiente").sort(porFechaDesc("created_at")),
    terminados: lista.filter(l => estadoLibro(l) === "terminado").sort(porFechaDesc("terminado")),
  };
}

export function terminadosEnAnio(libros, anio) {
  return (libros || []).filter(l => l.terminado && String(l.terminado).startsWith(`${anio}-`)).length;
}

// «5 sep 2026». Se trocea la cadena en vez de pasar por `new Date`: "2026-09-05" se
// interpreta como UTC y en zonas al oeste saldría el día anterior.
export function fechaLibro(iso) {
  const m = /^(\d{4})-(\d{2})-(\d{2})/.exec(iso || "");
  if (!m) return "";
  return `${Number(m[3])} ${MONTHS_ES[Number(m[2]) - 1].slice(0, 3)} ${m[1]}`;
}

function aDias(iso) {
  const m = /^(\d{4})-(\d{2})-(\d{2})/.exec(iso || "");
  return m ? Date.UTC(Number(m[1]), Number(m[2]) - 1, Number(m[3])) / 86400000 : null;
}

// Días entre dos fechas ISO (los dos extremos cuentan: empezar y acabar el mismo día es
// 1). `null` si falta una. `hasta` es la fecha de fin, o hoy si se está leyendo.
export function diasDeLectura(desde, hasta) {
  const a = aDias(desde), b = aDias(hasta);
  if (a == null || b == null || b < a) return null;
  return b - a + 1;
}

export function textoDuracion(libro, hoy) {
  const dias = diasDeLectura(libro.empezado, libro.terminado || hoy);
  if (dias == null) return "";
  return `${dias} ${dias === 1 ? "día" : "días"}`;
}

// El autocompletado se pide mientras se escribe: por debajo de dos letras no se busca.
export const MIN_LETRAS_BUSQUEDA = 2;
export function puedeBuscar(texto) {
  return String(texto || "").trim().length >= MIN_LETRAS_BUSQUEDA;
}
