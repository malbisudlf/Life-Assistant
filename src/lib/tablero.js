// Lógica pura del tablero de la tele (src/components/jarvis/TableroTele.jsx).
// La tele de la sala abre https://<frontend>/#tele=<llave>: la llave va en el FRAGMENTO, que
// el navegador no manda a ningún servidor ni deja en ningún log, y la página la guarda y la
// quita de la barra. Es la llave de solo lectura de GET /tele/tablero, no la del dashboard.

export const CLAVE_TELE = "la_tele_token";

/** La llave del fragmento («#tele=abc» → «abc»), o "" si no la hay. */
export function llaveDelFragmento(hash) {
  const m = /^#tele=([A-Za-z0-9_-]{16,200})$/.exec(String(hash || ""));
  return m ? m[1] : "";
}

/** Si esta carga es la del tablero: con la llave en el fragmento, o «#tele» a secas
 *  (la tele ya la tiene guardada). */
export function esTablero(hash) {
  const h = String(hash || "");
  return h === "#tele" || h.startsWith("#tele=");
}

/** «12 °C · 8–17 · lluvia 40 %», o "" si no hay tiempo. */
export function lineaTiempo(t) {
  if (!t || typeof t.ahora !== "number") return "";
  const partes = [`${t.ahora} °C`];
  if (typeof t.min === "number" && typeof t.max === "number") partes.push(`${t.min}–${t.max}`);
  if (typeof t.lluvia_prob === "number" && t.lluvia_prob >= 20) partes.push(`lluvia ${t.lluvia_prob} %`);
  return partes.join(" · ");
}

/** Las máquinas, en el orden en que se pintan: [{nombre, estado: "ok"|"caida"|"nose"}]. */
export function maquinas(m) {
  const nombres = [["caja", "caja"], ["jacobo", "jacobo"], ["casa", "la casa"]];
  return nombres.map(([clave, nombre]) => ({
    nombre,
    estado: !m || m[clave] === undefined || m[clave] === null ? "nose" : (m[clave] ? "ok" : "caida"),
  }));
}

/** «Nadie espera respuesta» / «1 chat espera respuesta» / «3 chats esperan respuesta». */
export function textoWhatsapp(n) {
  if (typeof n !== "number") return "";
  if (n === 0) return "Nadie espera respuesta";
  return n === 1 ? "1 chat espera respuesta" : `${n} chats esperan respuesta`;
}
