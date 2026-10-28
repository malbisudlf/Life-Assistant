// Lógica pura de las manos de la vista J.A.R.V.I.S.: de los 21 puntos que da MediaPipe
// (HandLandmarker) a un cursor en pantalla, si estás pellizcando y si un pellizco ha sido
// un clic o un arrastre. El seguimiento, la cámara y el dibujo viven en el componente;
// aquí solo las reglas, para poder probarlas sin cámara.
//
// Los puntos que importan (numeración de MediaPipe): 0 la muñeca, 4 la punta del pulgar,
// 8 la del índice y 9 el nudillo del corazón. Todo va normalizado a 0-1 del fotograma.

export const PUNTO = { MUNECA: 0, PULGAR: 4, INDICE: 8, NUDILLO_CORAZON: 9 };

// Los huesos que se dibujan, como pares de puntos.
export const HUESOS = [
  [0, 1], [1, 2], [2, 3], [3, 4],
  [0, 5], [5, 6], [6, 7], [7, 8],
  [5, 9], [9, 10], [10, 11], [11, 12],
  [9, 13], [13, 14], [14, 15], [15, 16],
  [13, 17], [17, 18], [18, 19], [19, 20], [0, 17],
];

export function distancia(a, b) {
  return Math.hypot((a?.x ?? 0) - (b?.x ?? 0), (a?.y ?? 0) - (b?.y ?? 0));
}

/** Un punto del fotograma (0-1) a la pantalla. En espejo, porque la cámara te ve de
 *  frente y la mano derecha tiene que mover el cursor a la derecha. Con margen: el centro
 *  del fotograma llega a toda la pantalla, para no tener que estirar el brazo hasta el
 *  borde de lo que ve la cámara. */
export function aPantalla(p, ancho, alto, { margen = 0.15, espejo = true } = {}) {
  const util = 1 - 2 * margen;
  const x = espejo ? 1 - p.x : p.x;
  const nx = Math.min(1, Math.max(0, (x - margen) / util));
  const ny = Math.min(1, Math.max(0, (p.y - margen) / util));
  return { x: nx * ancho, y: ny * alto };
}

/** Sigue una mano fotograma a fotograma.
 *
 *  El pellizco se mide en proporción al tamaño de la mano (muñeca → nudillo del corazón),
 *  así que vale igual con la mano cerca o lejos de la cámara. Lleva histéresis —se cierra
 *  por debajo de `cierra` y no se abre hasta pasar de `abre`— para que un pellizco no
 *  parpadee en el límite y dispare diez clics. El cursor se suaviza, porque el seguimiento
 *  tiembla unos píxeles en cada fotograma. */
export class LectorDeMano {
  constructor({ cierra = 0.32, abre = 0.45, suavizado = 0.4 } = {}) {
    Object.assign(this, { cierra, abre, suavizado });
    this.pellizco = false;
    this.cursor = null;
  }

  /** `puntos`: los 21 de una mano. Devuelve `{ x, y, pellizco, cambio, fuerza }`, donde
   *  `cambio` es "baja" al cerrar el pellizco, "sube" al abrirlo y null si sigue igual, y
   *  `fuerza` va de 0 (dedos separados) a 1 (pellizco cerrado), para pintar el anillo. */
  leer(puntos, ancho, alto, opciones) {
    if (!puntos || puntos.length < 21) return null;
    const tam = distancia(puntos[PUNTO.MUNECA], puntos[PUNTO.NUDILLO_CORAZON]) || 1;
    const separacion = distancia(puntos[PUNTO.PULGAR], puntos[PUNTO.INDICE]) / tam;
    let cambio = null;
    if (!this.pellizco && separacion < this.cierra) { this.pellizco = true; cambio = "baja"; }
    else if (this.pellizco && separacion > this.abre) { this.pellizco = false; cambio = "sube"; }
    // El cursor es el punto entre pulgar e índice: al pellizcar, el índice se mueve hacia
    // el pulgar y el cursor apuntado se iría con él justo al hacer clic.
    const medio = {
      x: (puntos[PUNTO.PULGAR].x + puntos[PUNTO.INDICE].x) / 2,
      y: (puntos[PUNTO.PULGAR].y + puntos[PUNTO.INDICE].y) / 2,
    };
    const crudo = aPantalla(medio, ancho, alto, opciones);
    const a = this.suavizado;
    this.cursor = this.cursor
      ? { x: this.cursor.x + (crudo.x - this.cursor.x) * (1 - a), y: this.cursor.y + (crudo.y - this.cursor.y) * (1 - a) }
      : crudo;
    const fuerza = Math.min(1, Math.max(0, (this.abre * 1.6 - separacion) / (this.abre * 1.6 - this.cierra)));
    return { x: this.cursor.x, y: this.cursor.y, pellizco: this.pellizco, cambio, fuerza };
  }

  /** La mano ha salido del fotograma: un pellizco a medias se da por soltado. */
  perdida() {
    const estaba = this.pellizco;
    this.pellizco = false;
    this.cursor = null;
    return estaba ? "sube" : null;
  }
}

/** Al soltar un pellizco que no ha arrastrado nada: ¿era un clic? Lo es si apenas se
 *  movió y fue corto; si no, era la mano yendo a otra parte con los dedos juntos. */
export function esClic({ movido, ms }, { maxMovido = 28, maxMs = 900 } = {}) {
  return movido <= maxMovido && ms <= maxMs;
}

/** La posición de un panel tras arrastrarlo, sin que se salga de la pantalla: siempre
 *  queda a la vista al menos `asa` píxeles para poder cogerlo otra vez. */
export function moverPanel(inicio, delta, caja, ventana, { asa = 60 } = {}) {
  const x = inicio.x + delta.x;
  const y = inicio.y + delta.y;
  const minX = -caja.left + asa - caja.width;
  const maxX = ventana.width - caja.left - asa;
  const minY = -caja.top;
  const maxY = ventana.height - caja.top - asa;
  return {
    x: Math.round(Math.min(maxX, Math.max(minX, x))),
    y: Math.round(Math.min(maxY, Math.max(minY, y))),
  };
}

/** Lo que el panel de proyectos enseña del progreso, venga como venga del puente: un
 *  número (0-100 o 0-1), un objeto con `pct`/`porcentaje`/`hechos` y `pasos`, o texto. */
export function porcentajeDe(progreso) {
  if (progreso == null) return null;
  if (typeof progreso === "number" && Number.isFinite(progreso)) {
    return Math.round(Math.min(100, Math.max(0, progreso <= 1 ? progreso * 100 : progreso)));
  }
  if (typeof progreso === "object") {
    const pct = progreso.pct ?? progreso.porcentaje;
    if (typeof pct === "number") return porcentajeDe(pct > 1 ? pct : pct * 100);
    const { hechos, pasos } = progreso;
    if (typeof hechos === "number" && typeof pasos === "number" && pasos > 0) {
      return Math.round((hechos / pasos) * 100);
    }
    return null;
  }
  const m = /(\d{1,3})\s*%/.exec(String(progreso));
  return m ? Math.min(100, Number(m[1])) : null;
}
