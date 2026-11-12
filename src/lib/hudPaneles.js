// Lógica pura de los paneles que Jarvis dibuja en su vista a pantalla completa
// (src/components/jarvis/PanelesVivos.jsx). Jarvis deja una RECETA —título, tipo y de qué
// fuentes bebe, de un catálogo cerrado del backend— y aquí se decide cómo se convierte un
// puñado de puntos en un trazo, en barras o en una cifra. Nada de lo que escribe el modelo
// llega a ser marcado: el título se pinta como texto y los datos son números del backend.

/** Cada cuánto se vuelve a pedir cada clase de dato. El tráfico cambia en minutos; el
 *  sueño de anoche, una vez al día. */
export const REFRESCO_MS = { serie: 10 * 60_000, lista: 5 * 60_000, cifra: 2 * 60_000 };

const CLAVE = "la_hud_paneles";

/** «7,4 h», «8.240», «52 ms». Sin dato, una raya: mejor que un cero que parece medido. */
export function textoValor(v, unidad = "") {
  if (!Number.isFinite(v)) return "—";
  const abs = Math.abs(v);
  const texto = abs >= 1000
    ? String(Math.round(v)).replace(/\B(?=(\d{3})+(?!\d))/g, ".")
    : (Number.isInteger(v) ? String(v) : v.toFixed(abs < 10 ? 2 : 1).replace(/0+$/, "").replace(/\.$/, "").replace(".", ","));
  return unidad ? `${texto} ${unidad}` : texto;
}

/** «2026-11-12» → «12/11». */
export function etiquetaDia(fecha) {
  const m = /^(\d{4})-(\d{2})-(\d{2})/.exec(String(fecha || ""));
  return m ? `${m[3]}/${m[2]}` : "";
}

/** Último valor, media, mínimo y máximo de una serie. `null` si no hay puntos. */
export function resumenSerie(puntos = []) {
  const vs = puntos.map(p => p.v).filter(Number.isFinite);
  if (!vs.length) return null;
  const suma = vs.reduce((a, b) => a + b, 0);
  return { ultimo: vs[vs.length - 1], media: suma / vs.length, min: Math.min(...vs), max: Math.max(...vs), n: vs.length };
}

/** Los puntos de una serie colocados en un lienzo de `ancho`×`alto`. Cada serie se
 *  estira a SU mínimo y máximo: dos series con unidades distintas (horas contra ms) se
 *  comparan por forma, que es lo que se mira en una contra otra. Con un margen del 12 %
 *  para que el trazo no toque los bordes, y una serie plana va por el medio. */
export function colocar(puntos = [], ancho = 220, alto = 70, margen = 6) {
  const validos = puntos.filter(p => Number.isFinite(p.v));
  if (!validos.length) return [];
  const vs = validos.map(p => p.v);
  let min = Math.min(...vs);
  let max = Math.max(...vs);
  if (max === min) { min -= 1; max += 1; }
  const holgura = (max - min) * 0.12;
  min -= holgura; max += holgura;
  const util = ancho - margen * 2;
  const paso = validos.length > 1 ? util / (validos.length - 1) : 0;
  return validos.map((p, i) => ({
    x: Math.round((margen + (validos.length > 1 ? i * paso : util / 2)) * 10) / 10,
    y: Math.round((alto - margen - ((p.v - min) / (max - min)) * (alto - margen * 2)) * 10) / 10,
    d: p.d, v: p.v,
  }));
}

/** El atributo `d` de un trazo SVG que une los puntos ya colocados. */
export function trazo(colocados = []) {
  return colocados.map((p, i) => `${i ? "L" : "M"}${p.x} ${p.y}`).join(" ");
}

/** Las barras de una serie: desde abajo hasta su punto, con un hueco entre ellas. */
export function barras(puntos = [], ancho = 220, alto = 70, margen = 6) {
  const colocados = colocar(puntos, ancho, alto, margen);
  if (!colocados.length) return [];
  const hueco = (ancho - margen * 2) / colocados.length;
  const w = Math.max(2, Math.min(14, hueco * 0.7));
  return colocados.map((p, i) => ({
    x: Math.round((margen + hueco * i + (hueco - w) / 2) * 10) / 10, y: p.y,
    w: Math.round(w * 10) / 10, h: Math.max(1, Math.round((alto - margen - p.y) * 10) / 10),
    d: p.d, v: p.v,
  }));
}

/** Lo que identifica los datos que pide una fuente de un panel: dos paneles con la misma
 *  fuente y los mismos días comparten petición. */
export function claveDatos(fuente, panel = {}) {
  return `${fuente}|${panel.dias || 14}|${fuente === "trafico" ? panel.destino || "" : ""}`;
}

/** La copia de las recetas que guarda el navegador, con la instancia del backend que las
 *  dio. Es lo que permite reponerlas tras un despliegue (el backend las tiene en memoria)
 *  sin resucitar un panel que Jarvis quitó: solo se reponen si la instancia ha cambiado. */
export function leerGuardados(almacen = globalThis.localStorage) {
  try {
    const d = JSON.parse(almacen?.getItem(CLAVE) || "null");
    if (d && Array.isArray(d.paneles)) {
      return { instancia: String(d.instancia || ""), paneles: d.paneles.filter(p => p && typeof p.id === "string") };
    }
  } catch { /* una copia rota es como no tener copia */ }
  return { instancia: "", paneles: [] };
}

export function guardar(instancia, paneles, almacen = globalThis.localStorage) {
  try {
    almacen?.setItem(CLAVE, JSON.stringify({ instancia, paneles }));
  } catch { /* sin almacenamiento, los paneles duran lo que la pestaña */ }
}

/** ¿Hay que reponer los paneles guardados? Solo si el backend no tiene ninguno, aquí sí
 *  los hay, y es OTRA instancia que la que los dio (o sea, se ha reiniciado). */
export function tocaReponer(remoto, guardados) {
  return Boolean(remoto && !remoto.paneles?.length && guardados.paneles.length
    && remoto.instancia && remoto.instancia !== guardados.instancia);
}

/** En qué columna va cada panel: los tres primeros a la derecha, bajo el día; el resto a
 *  la izquierda, bajo el sistema. */
export function repartir(paneles = []) {
  return { derecha: paneles.slice(0, 3), izquierda: paneles.slice(3) };
}
