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
export function aPantalla(p, ancho, alto, { margen = 0.15, espejo = true, cubre = null } = {}) {
  const x = espejo ? 1 - p.x : p.x;
  // En el modo inmersivo el vídeo ocupa la pantalla entera (`object-fit: cover`, con lo
  // que sobra recortado por los lados o por arriba): el punto tiene que caer encima del
  // dedo que se ve, sin margen ni estirar nada.
  if (cubre?.ancho && cubre?.alto) {
    const escala = Math.max(ancho / cubre.ancho, alto / cubre.alto);
    const w = cubre.ancho * escala;
    const h = cubre.alto * escala;
    return { x: (ancho - w) / 2 + x * w, y: (alto - h) / 2 + p.y * h };
  }
  const util = 1 - 2 * margen;
  const nx = Math.min(1, Math.max(0, (x - margen) / util));
  const ny = Math.min(1, Math.max(0, (p.y - margen) / util));
  return { x: nx * ancho, y: ny * alto };
}

/** El filtro «One Euro» (Casiez, Roussel y Vogel, 2012), el de siempre para cursores
 *  que siguen una mano: con la mano quieta filtra mucho (el seguimiento tiembla unos
 *  píxeles en cada fotograma) y con la mano rápida casi nada, así que no tiembla ni se
 *  queda atrás. Una media móvil fija, que es lo que había, solo podía elegir una de las
 *  dos cosas: a 0,4 el cursor arrastraba un retraso que se notaba al mover el brazo. */
export class FiltroOneEuro {
  constructor({ minCorte = 1.0, beta = 0.015, corteDerivada = 1.0 } = {}) {
    Object.assign(this, { minCorte, beta, corteDerivada });
    this.reinicia();
  }

  reinicia() {
    this.previo = null;
    this.derivada = 0;
    this.t = null;
  }

  static alfa(corte, dt) {
    const tau = 1 / (2 * Math.PI * corte);
    return 1 / (1 + tau / dt);
  }

  /** `t` en segundos. */
  filtrar(valor, t) {
    if (this.previo == null || this.t == null || t <= this.t) {
      this.previo = valor;
      this.t = t;
      return valor;
    }
    const dt = t - this.t;
    this.t = t;
    const derivadaCruda = (valor - this.previo) / dt;
    const ad = FiltroOneEuro.alfa(this.corteDerivada, dt);
    this.derivada = ad * derivadaCruda + (1 - ad) * this.derivada;
    const corte = this.minCorte + this.beta * Math.abs(this.derivada);
    const a = FiltroOneEuro.alfa(corte, dt);
    this.previo = a * valor + (1 - a) * this.previo;
    return this.previo;
  }
}

/** Sigue una mano fotograma a fotograma.
 *
 *  El pellizco se mide en proporción al tamaño de la mano (muñeca → nudillo del corazón),
 *  así que vale igual con la mano cerca o lejos de la cámara. Lleva histéresis —se cierra
 *  por debajo de `cierra` y no se abre hasta pasar de `abre`— para que un pellizco no
 *  parpadee en el límite y dispare diez clics. El cursor va por `FiltroOneEuro`. */
export class LectorDeMano {
  constructor({ cierra = 0.32, abre = 0.45, filtro = {} } = {}) {
    Object.assign(this, { cierra, abre });
    this.fx = new FiltroOneEuro(filtro);
    this.fy = new FiltroOneEuro(filtro);
    this.pellizco = false;
    this.cursor = null;
  }

  /** `puntos`: los 21 de una mano; `t`, el instante del fotograma en segundos. Devuelve
   *  `{ x, y, pellizco, cambio, fuerza }`, donde `cambio` es "baja" al cerrar el
   *  pellizco, "sube" al abrirlo y null si sigue igual, y `fuerza` va de 0 (dedos
   *  separados) a 1 (pellizco cerrado), para pintar el anillo. */
  leer(puntos, ancho, alto, opciones, t = (typeof performance !== "undefined" ? performance.now() : Date.now()) / 1000) {
    if (!puntos || puntos.length < 21) return null;
    const tam = distancia(puntos[PUNTO.MUNECA], puntos[PUNTO.NUDILLO_CORAZON]) || 1;
    const separacion = distancia(puntos[PUNTO.PULGAR], puntos[PUNTO.INDICE]) / tam;
    let cambio = null;
    // Con el índice plegado no es un pellizco: es un puño, y al cerrarlo el pulgar roza el
    // índice. Sin esto, cerrar el puño para abrir el menú pulsaba lo que hubiera debajo.
    const indicePlegado = plegado(puntos, PUNTO.INDICE, tam);
    if (!this.pellizco && separacion < this.cierra && !indicePlegado) { this.pellizco = true; cambio = "baja"; }
    else if (this.pellizco && separacion > this.abre) { this.pellizco = false; cambio = "sube"; }
    // El cursor es el punto entre pulgar e índice: al pellizcar, el índice se mueve hacia
    // el pulgar y el cursor apuntado se iría con él justo al hacer clic.
    const medio = {
      x: (puntos[PUNTO.PULGAR].x + puntos[PUNTO.INDICE].x) / 2,
      y: (puntos[PUNTO.PULGAR].y + puntos[PUNTO.INDICE].y) / 2,
    };
    const crudo = aPantalla(medio, ancho, alto, opciones);
    this.cursor = { x: this.fx.filtrar(crudo.x, t), y: this.fy.filtrar(crudo.y, t) };
    const fuerza = Math.min(1, Math.max(0, (this.abre * 1.6 - separacion) / (this.abre * 1.6 - this.cierra)));
    return { x: this.cursor.x, y: this.cursor.y, pellizco: this.pellizco, cambio, fuerza };
  }

  /** La mano ha salido del fotograma: un pellizco a medias se da por soltado. */
  perdida() {
    const estaba = this.pellizco;
    this.pellizco = false;
    this.cursor = null;
    this.fx.reinicia();
    this.fy.reinicia();
    return estaba ? "sube" : null;
  }
}

// ── El puño ───────────────────────────────────────────────────────────────────────
// Cerrar el puño abre el menú radial de los proyectos. Un dedo está plegado cuando su
// punta queda cerca del centro de la palma (la media de la muñeca y los cuatro nudillos),
// en proporción al tamaño de la mano. Extendido, la punta está a ~1,5 veces ese tamaño;
// plegado, a menos de 0,8.
const PUNTAS_DEDOS = [8, 12, 16, 20];

function centroPalma(puntos) {
  const ids = [0, 5, 9, 13, 17];
  return {
    x: ids.reduce((a, i) => a + puntos[i].x, 0) / ids.length,
    y: ids.reduce((a, i) => a + puntos[i].y, 0) / ids.length,
  };
}

function plegado(puntos, punta, tam, umbral = 0.8) {
  return distancia(puntos[punta], centroPalma(puntos)) / tam < umbral;
}

/** El centro de la palma en pantalla: donde se ancla el menú del puño. */
export function palmaEnPantalla(puntos, ancho, alto, opciones) {
  return aPantalla(centroPalma(puntos), ancho, alto, opciones);
}

/** El centro del menú del puño, metido en la pantalla con el radio y sus burbujas. */
export function centroDelMenu(punto, radio, ventana, margen = 70) {
  const borde = radio + margen;
  return {
    x: Math.round(Math.min(ventana.width - borde, Math.max(borde, punto.x))),
    y: Math.round(Math.min(ventana.height - borde, Math.max(borde, punto.y))),
  };
}

/** Cuánto se parece a un puño: cuántos de los cuatro dedos están plegados (0-4). */
export function dedosPlegados(puntos, umbral = 0.8) {
  if (!puntos || puntos.length < 21) return 0;
  const tam = distancia(puntos[PUNTO.MUNECA], puntos[PUNTO.NUDILLO_CORAZON]) || 1;
  return PUNTAS_DEDOS.filter(p => plegado(puntos, p, tam, umbral)).length;
}

/** Decide cuándo el puño está cerrado de verdad. Hace falta aguantarlo `aguantaMs`: una
 *  mano que pasa por un puño al moverse (o que se cierra para pellizcar) no abre nada. Se
 *  da por abierto en cuanto se extienden dos dedos, que es menos que lo que pide cerrarlo:
 *  así no parpadea con un dedo a medias. */
export class DetectorDePuno {
  constructor({ aguantaMs = 250 } = {}) {
    this.aguantaMs = aguantaMs;
    this.cerrado = false;
    this.desde = null;
  }

  /** `t` en milisegundos. Devuelve "cierra" al confirmarse el puño, "abre" al soltarlo
   *  y null si nada cambia. */
  leer(puntos, t) {
    const n = dedosPlegados(puntos);
    if (!this.cerrado) {
      if (n === 4) {
        if (this.desde == null) this.desde = t;
        if (t - this.desde >= this.aguantaMs) { this.cerrado = true; return "cierra"; }
      } else {
        this.desde = null;
      }
      return null;
    }
    if (n <= 2) {
      this.cerrado = false;
      this.desde = null;
      return "abre";
    }
    return null;
  }

  /** La mano ha salido del fotograma. */
  perdida() {
    const estaba = this.cerrado;
    this.cerrado = false;
    this.desde = null;
    return estaba ? "abre" : null;
  }
}

// ── Pulsar con la punta de un dedo (modo inmersivo) ──────────────────────────────
// Se pulsa como un botón de verdad: echando la punta HACIA la pantalla. Una webcam no da
// la profundidad exacta, pero sí dos pistas que se suman en la «cercanía» de cada punta:
//   - el tamaño aparente de la mano: si se empuja la mano entera, crece en la imagen
//     (va en logaritmo, para que cuente lo mismo cerca que lejos de la cámara);
//   - la `z` de MediaPipe de la punta, relativa a la muñeca y negativa hacia la cámara:
//     si solo se adelanta el dedo, esa punta se acerca más que el resto de la mano.
// Es una pulsación cuando la cercanía de una punta sube `umbral` en menos de `ventanaMs`
// —un empujón, no acercarse despacio— sin que la punta se desplace mucho por la imagen
// (eso es barrer, no pulsar) y sin que el dedo se pliegue (al cerrar la mano las puntas
// también se acercan a la cámara). Cuenta dónde estaba la punta al empezar el empujón,
// que es a lo que apuntaba, y no vuelve a pulsar hasta echar la mano atrás.
export const PUNTAS_PULSAN = [4, 8, 12, 16, 20];
// Contra qué se mide si un dedo se ha plegado: su nudillo (el del pulgar, su base).
const BASE_DEDO = { 4: 2, 8: 5, 12: 9, 16: 13, 20: 17 };

/** El tamaño de la mano en la imagen: la media de su largo (muñeca → nudillo del
 *  corazón) y su ancho (nudillo del índice → nudillo del meñique). Con las dos, girar la
 *  mano cambia menos el número que con una sola. */
export function tamanoMano(puntos) {
  return (distancia(puntos[0], puntos[9]) + distancia(puntos[5], puntos[17])) / 2 || 1e-6;
}

/** Lo cerca de la cámara que está cada punta (`PUNTAS_PULSAN`), en unidades sin escala. */
export function cercanias(puntos, { beta = 0.35 } = {}) {
  if (!puntos || puntos.length < 21) return null;
  const tam = tamanoMano(puntos);
  const base = Math.log(tam);
  return PUNTAS_PULSAN.map(i => base + beta * (-(puntos[i].z ?? 0) / tam));
}

export class DetectorDePulsaciones {
  /** `umbral`: cuánto tiene que acercarse la punta (0,1 ≈ la mano un 10 % más grande en la
   *  imagen); `ventanaMs`: en cuánto tiempo, como mucho; `deriva`: cuánto puede moverse la
   *  punta por la imagen mientras tanto, en tamaños de mano; `plegado`: hasta qué fracción
   *  de su largo puede encogerse el dedo; `vuelta`: cuánto hay que echarse atrás (en
   *  umbrales) para poder pulsar otra vez. */
  constructor({ umbral = 0.1, ventanaMs = 300, deriva = 0.8, plegado = 0.7, vuelta = 0.5, beta = 0.35,
                rearmeMs = 1500 } = {}) {
    Object.assign(this, { umbral, ventanaMs, deriva, plegado, vuelta, beta, rearmeMs });
    this.reinicia();
  }

  reinicia() {
    this.muestras = [];
    this.pulsada = null;      // { i, cima, t }: la punta que pulsó, hasta echarse atrás
    this.progreso = PUNTAS_PULSAN.map(() => 0);
  }

  /** `t` en milisegundos. Devuelve las pulsaciones de este fotograma (cero o una), cada
   *  una como `{ punta, punto }`: el número de MediaPipe de la punta y dónde estaba en el
   *  fotograma (0-1) al empezar a empujar. Deja en `progreso` (0-1 por punta) cuánto le
   *  falta a cada una, para dibujarlo. */
  leer(puntos, t) {
    const c = cercanias(puntos, this);
    if (!c) return [];
    const tam = tamanoMano(puntos);
    const largos = PUNTAS_PULSAN.map(i => distancia(puntos[i], puntos[BASE_DEDO[i]]) / tam);
    const pos = PUNTAS_PULSAN.map(i => ({ x: puntos[i].x, y: puntos[i].y }));
    this.muestras.push({ t, c, pos, largos, tam });
    while (this.muestras.length > 1 && t - this.muestras[0].t > this.ventanaMs) this.muestras.shift();

    if (this.pulsada) {
      const { i, cima } = this.pulsada;
      const cimaNueva = Math.max(cima, c[i]);
      this.pulsada.cima = cimaNueva;
      this.progreso = PUNTAS_PULSAN.map((_, j) => (j === i ? 1 : 0));
      if (c[i] <= cimaNueva - this.umbral * this.vuelta || t - this.pulsada.t > this.rearmeMs) {
        this.pulsada = null;
        this.muestras = [this.muestras[this.muestras.length - 1]];
      }
      return [];
    }

    let mejor = -1;
    this.progreso = PUNTAS_PULSAN.map((_, i) => {
      // El punto de partida es el más lejano de la ventana: desde ahí empezó el empujón.
      const desde = this.muestras.reduce((a, m) => (m.c[i] < a.c[i] ? m : a), this.muestras[0]);
      const subida = c[i] - desde.c[i];
      const quieta = distancia(pos[i], desde.pos[i]) / Math.max(tam, desde.tam) <= this.deriva;
      const estirado = largos[i] >= desde.largos[i] * this.plegado;
      const p = quieta && estirado ? Math.max(0, Math.min(1, subida / this.umbral)) : 0;
      if (p >= 1 && (mejor < 0 || c[i] > c[mejor])) mejor = i;
      return p;
    });
    if (mejor < 0) return [];
    // De las que han empujado a la vez (la mano entera hacia delante), la que va más
    // adelantada: la del dedo que apunta.
    const desde = this.muestras.reduce((a, m) => (m.c[mejor] < a.c[mejor] ? m : a), this.muestras[0]);
    this.pulsada = { i: mejor, cima: c[mejor], t };
    return [{ punta: PUNTAS_PULSAN[mejor], punto: desde.pos[mejor] }];
  }

  /** Pellizcando o con el puño cerrado no se pulsa nada: se olvida lo visto, para que al
   *  soltar no cuente como empujón lo que pasó mientras tanto. */
  pausa() {
    this.muestras = [];
    this.pulsada = null;
    this.progreso = PUNTAS_PULSAN.map(() => 0);
  }
}

// ── Soltar un panel con impulso ───────────────────────────────────────────────────

/** La velocidad (px/ms) con la que se soltó un arrastre, de las muestras `{ t, x, y }`
 *  entre `desdeMs` y `hastaMs` antes de soltar. Lo último se descarta a propósito: al
 *  abrir un pellizco los dedos se separan y el cursor da un tirón que no es el gesto. */
export function velocidadDeSuelta(muestras, t, { desdeMs = 140, hastaMs = 30, max = 3 } = {}) {
  const tramo = (muestras || []).filter(m => t - m.t <= desdeMs && t - m.t >= hastaMs);
  if (tramo.length < 2) return { x: 0, y: 0 };
  const a = tramo[0];
  const b = tramo[tramo.length - 1];
  const dt = b.t - a.t;
  if (dt <= 0) return { x: 0, y: 0 };
  const limita = v => Math.max(-max, Math.min(max, v));
  return { x: limita((b.x - a.x) / dt), y: limita((b.y - a.y) / dt) };
}

/** Un paso de la inercia: cuánto se mueve el panel en `dtMs` y con qué velocidad sigue.
 *  Frena en exponencial (`mediaVidaMs`: en ese tiempo va a la mitad), que es lo que se
 *  siente natural al lanzar algo sobre una mesa. */
export function pasoDeInercia(vel, dtMs, { mediaVidaMs = 110 } = {}) {
  const f = Math.pow(0.5, dtMs / mediaVidaMs);
  return { dx: vel.x * dtMs, dy: vel.y * dtMs, vel: { x: vel.x * f, y: vel.y * f } };
}

/** Dónde va cada burbuja del menú radial alrededor del puño, empezando arriba y en el
 *  sentido de las agujas del reloj. Desplazamientos desde el centro, en píxeles. */
export function posicionesRadiales(n, radio) {
  return Array.from({ length: n }, (_, i) => {
    const a = -Math.PI / 2 + (i * 2 * Math.PI) / n;
    return { x: Math.round(Math.cos(a) * radio), y: Math.round(Math.sin(a) * radio) };
  });
}

/** Qué burbuja se elige moviendo el puño desde el centro: la que está en esa dirección,
 *  si se ha movido al menos `umbral` píxeles; -1 si no. */
export function elegirPorDireccion(desplazamiento, n, { umbral = 70 } = {}) {
  if (!n || Math.hypot(desplazamiento.x, desplazamiento.y) < umbral) return -1;
  const angulo = Math.atan2(desplazamiento.y, desplazamiento.x);
  let mejor = -1;
  let menor = Infinity;
  for (let i = 0; i < n; i++) {
    const a = -Math.PI / 2 + (i * 2 * Math.PI) / n;
    const d = Math.abs(Math.atan2(Math.sin(angulo - a), Math.cos(angulo - a)));
    if (d < menor) { menor = d; mejor = i; }
  }
  return mejor;
}

/** Acerca lo que se pinta a lo último que se vio: el seguimiento llega a lo que dé la
 *  cámara (unos 30 fotogramas por segundo) y la pantalla pinta a 60 o más. Sin esto el
 *  cursor y la mano iban a saltos aunque el filtro estuviera bien. */
export function acercar(actual, destino, factor = 0.5) {
  if (!actual) return destino;
  return { x: actual.x + (destino.x - actual.x) * factor, y: actual.y + (destino.y - actual.y) * factor };
}

/** De qué mano es cada detección, para que cada una siga con su cursor aunque MediaPipe
 *  las devuelva en otro orden. `handedness` es la de MediaPipe; si no viene, el orden. */
export function claveDeMano(handedness, i) {
  const nombre = handedness?.[i]?.[0]?.categoryName;
  return nombre === "Left" || nombre === "Right" ? nombre : `mano${i}`;
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
