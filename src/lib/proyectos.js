// Lógica pura de cómo se enseñan los proyectos del programador en la vista J.A.R.V.I.S.:
// en el panel de proyectos y en las burbujas del menú del puño. Lo que cuenta el
// programador lo escribe un modelo que ha leído repositorios: se recorta y se pinta como
// texto, y el enlace al PR solo vale si es de GitHub.

export const ESTADOS = {
  trabajando: "Trabajando", en_cola: "En cola", cola: "En cola", terminado: "Terminado",
  fallido: "Fallido", esperando: "Esperando",
};

export function prDeConfianza(url) {
  return /^https:\/\/github\.com\/[A-Za-z0-9-]{1,39}\/[A-Za-z0-9._-]{1,100}\/pull\/\d{1,7}$/.test(String(url || ""))
    ? url : "";
}

export function recorta(texto, n) {
  const t = String(texto || "").replace(/\s+/g, " ").trim();
  return t.length > n ? `${t.slice(0, n - 1)}…` : t;
}

/** El nombre corto de un proyecto para su burbuja: sin el «área:» del título
 *  («web: lista de la compra» → «lista de la compra»), y recortado. */
export function nombreCorto(proyecto, n = 22) {
  const titulo = String(proyecto?.titulo || proyecto?.proyecto || "").trim();
  const sinArea = titulo.includes(":") ? titulo.split(":").slice(1).join(":").trim() : titulo;
  return recorta(sinArea || titulo, n);
}

/** Los que van al menú del puño: primero los que están en marcha, luego los últimos. */
export function proyectosDelMenu(proyectos = [], max = 7) {
  const orden = { trabajando: 0, en_cola: 1, cola: 1, esperando: 2 };
  return [...proyectos]
    .filter(p => p && (p.id || p.proyecto))
    .sort((a, b) => (orden[a.estado] ?? 3) - (orden[b.estado] ?? 3))
    .slice(0, max);
}
