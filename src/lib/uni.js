// Lógica pura del widget «Uni»: las asignaturas de este curso con su nota, su progreso y
// lo que queda por entregar. Los datos los junta el backend (`GET /moodle/uni`, sección
// «Moodle: el widget Uni» de main.py); aquí solo se decide el orden y cómo se dice.

/** Días de calendario (en la zona del navegador) entre `ahora` y una fecha ISO. */
function diasHasta(iso, ahora) {
  const fecha = new Date(iso);
  if (Number.isNaN(fecha.getTime())) return null;
  const dia = d => new Date(d.getFullYear(), d.getMonth(), d.getDate()).getTime();
  return Math.round((dia(fecha) - dia(ahora)) / 86400000);
}

/** «hoy», «mañana», «en 5 días», «vencida»: cuándo toca la próxima entrega. */
export function cuandoVence(proxima, ahora = new Date()) {
  if (!proxima) return null;
  const dias = diasHasta(proxima.vence, ahora);
  if (proxima.vencida || (dias !== null && dias < 0)) return "vencida";
  if (dias === null) return null;
  if (dias === 0) return "hoy";
  if (dias === 1) return "mañana";
  return `en ${dias} días`;
}

/** La línea de debajo del nombre. Distingue «no hay» de «no se sabe»: con `pendientes`
 *  a null (Moodle no devolvió las entregas) no se dice nada, nunca «sin entregas». */
export function detalleAsignatura(a, ahora = new Date()) {
  if (a.pendientes === null || a.pendientes === undefined) return "";
  if (a.pendientes === 0) return "Nada pendiente";
  const cuando = cuandoVence(a.proxima, ahora);
  const cuantas = a.pendientes === 1 ? "1 entrega" : `${a.pendientes} entregas`;
  if (!cuando) return cuantas;
  return cuando === "vencida"
    ? `${cuantas} · una vencida`
    : `${cuantas} · la próxima ${cuando}`;
}

/** Primero lo que tiene algo pendiente, lo que vence antes arriba; luego el resto por
 *  nombre. Es la pregunta que se hace al mirar el widget: «¿de qué tengo que ocuparme?». */
export function ordenarAsignaturas(lista) {
  const vence = a => (a.pendientes > 0 && a.proxima ? new Date(a.proxima.vence).getTime() : Infinity);
  return [...(lista || [])].sort((x, y) =>
    vence(x) - vence(y) || String(x.nombre).localeCompare(String(y.nombre), "es"));
}

/** Qué no pudo leer el backend, en una frase. Vacía si llegó todo. */
export function avisoIncompleto(incompleto) {
  const faltan = ["notas", "entregas"].filter(x => (incompleto || []).includes(x));
  if (!faltan.length) return "";
  return `Moodle no ha devuelto las ${faltan.join(" ni las ")}; el resto está al día.`;
}
