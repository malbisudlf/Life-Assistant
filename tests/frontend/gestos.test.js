import { describe, it, expect } from "vitest";
import {
  LectorDeMano, FiltroOneEuro, aPantalla, esClic, moverPanel, porcentajeDe, distancia, acercar, claveDeMano,
  DetectorDePuno, dedosPlegados, posicionesRadiales, elegirPorDireccion,
  DetectorDePulsaciones, cercanias, velocidadDeSuelta, pasoDeInercia,
} from "../../src/lib/gestos";

/** Una mano con los cuatro dedos extendidos hacia arriba, o plegados sobre la palma. */
function manoDeDedos(plegados) {
  const x = 0.5;
  const p = Array.from({ length: 21 }, () => ({ x, y: 0.5 }));
  p[0] = { x, y: 0.7 };                               // muñeca
  [5, 9, 13, 17].forEach((i, k) => { p[i] = { x: x - 0.06 + k * 0.04, y: 0.5 }; });   // nudillos
  [8, 12, 16, 20].forEach((i, k) => {
    p[i] = plegados > k ? { x: x - 0.06 + k * 0.04, y: 0.58 } : { x: x - 0.06 + k * 0.04, y: 0.2 };
  });
  p[4] = { x: x - 0.09, y: 0.55 };
  return p;
}

/** Una mano de juguete: muñeca abajo, nudillo del corazón 0,2 más arriba, y las puntas
 *  del pulgar y el índice por encima de la palma (como al pellizcar de verdad), separadas
 *  `abierto` veces ese tamaño. */
function mano(abierto, { x = 0.5, y = 0.5 } = {}) {
  const p = Array.from({ length: 21 }, () => ({ x, y }));
  p[0] = { x, y: y + 0.2 };
  p[9] = { x, y };
  p[4] = { x: x - (abierto * 0.2) / 2, y: y - 0.25 };
  p[8] = { x: x + (abierto * 0.2) / 2, y: y - 0.25 };
  return p;
}

describe("LectorDeMano", () => {
  it("cierra y abre el pellizco con histéresis", () => {
    const l = new LectorDeMano({ cierra: 0.32, abre: 0.45 });
    expect(l.leer(mano(1), 1000, 800).cambio).toBe(null);
    expect(l.leer(mano(0.2), 1000, 800).cambio).toBe("baja");
    // Entre los dos umbrales sigue pellizcado: no parpadea.
    const medio = l.leer(mano(0.4), 1000, 800);
    expect(medio.pellizco).toBe(true);
    expect(medio.cambio).toBe(null);
    expect(l.leer(mano(0.6), 1000, 800).cambio).toBe("sube");
  });

  it("vale igual con la mano cerca o lejos", () => {
    const cerca = new LectorDeMano();
    const lejos = new LectorDeMano();
    const grande = mano(0.2).map(p => ({ x: 0.5 + (p.x - 0.5) * 2, y: 0.5 + (p.y - 0.5) * 2 }));
    expect(cerca.leer(grande, 1000, 800).pellizco).toBe(true);
    expect(lejos.leer(mano(0.2), 1000, 800).pellizco).toBe(true);
  });

  it("en espejo: la mano a la izquierda del fotograma es la derecha de la pantalla", () => {
    const l = new LectorDeMano();
    const r = l.leer(mano(1, { x: 0.25 }), 1000, 800, undefined, 0);
    expect(r.x).toBeGreaterThan(500);
  });

  it("filtra el cursor con el tiempo de cada fotograma", () => {
    const l = new LectorDeMano();
    const a = l.leer(mano(1, { x: 0.3 }), 1000, 800, undefined, 0);
    const b = l.leer(mano(1, { x: 0.7 }), 1000, 800, undefined, 1 / 30);
    const crudo = new LectorDeMano().leer(mano(1, { x: 0.7 }), 1000, 800, undefined, 0);
    // Se mueve hacia el sitio nuevo, pero no de golpe.
    expect(b.x).toBeLessThan(a.x);
    expect(b.x).toBeGreaterThan(crudo.x);
  });

  it("perder la mano suelta lo que tuviera cogido", () => {
    const l = new LectorDeMano();
    l.leer(mano(0.1), 1000, 800);
    expect(l.perdida()).toBe("sube");
    expect(l.perdida()).toBe(null);
  });

  it("sin puntos no hay lectura", () => {
    expect(new LectorDeMano().leer([], 100, 100)).toBe(null);
  });
});

describe("FiltroOneEuro", () => {
  const ruido = (i) => ((i * 7919) % 13) / 13 - 0.5;   // determinista, entre -0,5 y 0,5

  it("quieto, se come el temblor", () => {
    const f = new FiltroOneEuro();
    const salida = [];
    for (let i = 0; i < 90; i++) salida.push(f.filtrar(500 + ruido(i) * 8, i / 30));
    const ultimos = salida.slice(-30);
    const vaiven = Math.max(...ultimos) - Math.min(...ultimos);
    expect(vaiven).toBeLessThan(4);   // la entrada oscila 8 px
  });

  it("deprisa, apenas se queda atrás", () => {
    const f = new FiltroOneEuro();
    let x = 0;
    let salida = 0;
    for (let i = 0; i < 30; i++) { x = i * 40; salida = f.filtrar(x, i / 30); }   // 1.200 px/s
    expect(x - salida).toBeLessThan(80);
  });

  it("un salto atrás en el tiempo empieza de nuevo", () => {
    const f = new FiltroOneEuro();
    f.filtrar(100, 1);
    expect(f.filtrar(300, 0.5)).toBe(300);
  });
});

describe("el puño", () => {
  it("cuenta los dedos plegados", () => {
    expect(dedosPlegados(manoDeDedos(0))).toBe(0);
    expect(dedosPlegados(manoDeDedos(4))).toBe(4);
    expect(dedosPlegados(manoDeDedos(2))).toBe(2);
  });

  it("hay que aguantarlo para que cuente, y se suelta al extender dos dedos", () => {
    const d = new DetectorDePuno({ aguantaMs: 250 });
    expect(d.leer(manoDeDedos(4), 0)).toBe(null);
    expect(d.leer(manoDeDedos(4), 100)).toBe(null);
    expect(d.leer(manoDeDedos(4), 260)).toBe("cierra");
    expect(d.leer(manoDeDedos(3), 300)).toBe(null);    // un dedo a medias no lo suelta
    expect(d.leer(manoDeDedos(2), 340)).toBe("abre");
  });

  it("un puño de paso no abre nada", () => {
    const d = new DetectorDePuno({ aguantaMs: 250 });
    d.leer(manoDeDedos(4), 0);
    d.leer(manoDeDedos(0), 100);
    expect(d.leer(manoDeDedos(4), 300)).toBe(null);
  });

  it("con el índice plegado no hay pellizco aunque el pulgar lo toque", () => {
    const l = new LectorDeMano();
    const puno = manoDeDedos(4);
    puno[4] = { ...puno[8] };                          // el pulgar sobre el índice plegado
    expect(l.leer(puno, 1000, 800, undefined, 0).pellizco).toBe(false);
  });
});

describe("el menú radial", () => {
  it("las burbujas empiezan arriba y siguen las agujas del reloj", () => {
    const [arriba, derecha, abajo, izquierda] = posicionesRadiales(4, 100);
    expect(arriba).toEqual({ x: 0, y: -100 });
    expect(derecha).toEqual({ x: 100, y: 0 });
    expect(abajo.y).toBe(100);
    expect(izquierda.x).toBe(-100);
  });

  it("se elige moviendo el puño hacia una, y sin moverse no se elige ninguna", () => {
    expect(elegirPorDireccion({ x: 0, y: -120 }, 4)).toBe(0);
    expect(elegirPorDireccion({ x: 110, y: 10 }, 4)).toBe(1);
    expect(elegirPorDireccion({ x: -90, y: -5 }, 4)).toBe(3);
    expect(elegirPorDireccion({ x: 20, y: 10 }, 4)).toBe(-1);
    expect(elegirPorDireccion({ x: 200, y: 0 }, 0)).toBe(-1);
  });
});

describe("acercar", () => {
  it("va a medio camino y la primera vez llega", () => {
    expect(acercar(null, { x: 10, y: 10 })).toEqual({ x: 10, y: 10 });
    expect(acercar({ x: 0, y: 0 }, { x: 10, y: 20 })).toEqual({ x: 5, y: 10 });
  });
});

describe("claveDeMano", () => {
  it("la izquierda y la derecha por su nombre, y si no, por orden", () => {
    expect(claveDeMano([[{ categoryName: "Right" }], [{ categoryName: "Left" }]], 1)).toBe("Left");
    expect(claveDeMano(undefined, 0)).toBe("mano0");
  });
});

describe("aPantalla", () => {
  it("el centro va al centro y los márgenes se estiran a los bordes", () => {
    expect(aPantalla({ x: 0.5, y: 0.5 }, 1000, 800)).toEqual({ x: 500, y: 400 });
    expect(aPantalla({ x: 0.9, y: 0.1 }, 1000, 800)).toEqual({ x: 0, y: 0 });
    expect(aPantalla({ x: 0.1, y: 0.9 }, 1000, 800, { espejo: true })).toEqual({ x: 1000, y: 800 });
  });
});

describe("esClic", () => {
  it("corto y quieto es clic; largo o movido, no", () => {
    expect(esClic({ movido: 5, ms: 200 })).toBe(true);
    expect(esClic({ movido: 80, ms: 200 })).toBe(false);
    expect(esClic({ movido: 5, ms: 3000 })).toBe(false);
  });
});

describe("moverPanel", () => {
  const caja = { left: 100, top: 100, width: 250, height: 300 };
  const ventana = { width: 1400, height: 900 };
  it("mueve lo arrastrado", () => {
    expect(moverPanel({ x: 0, y: 0 }, { x: 40, y: -20 }, caja, ventana)).toEqual({ x: 40, y: -20 });
  });
  it("no deja que se pierda fuera de la pantalla", () => {
    const lejos = moverPanel({ x: 0, y: 0 }, { x: 5000, y: 5000 }, caja, ventana);
    expect(caja.left + lejos.x).toBeLessThanOrEqual(ventana.width - 60);
    expect(caja.top + lejos.y).toBeLessThanOrEqual(ventana.height - 60);
    expect(moverPanel({ x: 0, y: 0 }, { x: 0, y: -900 }, caja, ventana).y).toBe(-100);
  });
});

describe("porcentajeDe", () => {
  it("entiende los formatos que puede mandar el puente", () => {
    expect(porcentajeDe(0.5)).toBe(50);
    expect(porcentajeDe(75)).toBe(75);
    expect(porcentajeDe({ hechos: 3, pasos: 4 })).toBe(75);
    expect(porcentajeDe({ pct: 40 })).toBe(40);
    expect(porcentajeDe("✓ paso 1, paso 2 (50 %)")).toBe(50);
    expect(porcentajeDe("sin plan")).toBe(null);
    expect(porcentajeDe(null)).toBe(null);
  });
});

describe("distancia", () => {
  it("euclídea", () => {
    expect(distancia({ x: 0, y: 0 }, { x: 3, y: 4 })).toBe(5);
  });
});

/** Una mano abierta de frente, con `doblados` (números de punta de MediaPipe) doblados
 *  sobre la palma. El pulgar, extendido hacia un lado salvo que esté en la lista. */
function manoAbierta(doblados = []) {
  const p = manoDeDedos(0);
  [8, 12, 16, 20].forEach((i, k) => { if (doblados.includes(i)) p[i] = { x: 0.44 + k * 0.04, y: 0.56 }; });
  p[4] = doblados.includes(4) ? { x: 0.56, y: 0.55 } : { x: 0.3, y: 0.5 };
  p[2] = { x: 0.42, y: 0.56 };                         // la base del pulgar
  return p.map(q => ({ ...q, z: 0 }));
}

/** La misma mano, `escala` veces más grande en la imagen (más cerca de la cámara),
 *  movida `dx` y con la `z` que se diga en algunas puntas. */
function transformar(p, { escala = 1, dx = 0, z = {} } = {}) {
  return p.map((q, i) => ({
    x: 0.5 + (q.x - 0.5) * escala + dx,
    y: 0.5 + (q.y - 0.5) * escala,
    z: (z[i] ?? q.z ?? 0) * escala,
  }));
}

describe("pulsar echando la punta hacia delante", () => {
  it("empujar la mano hacia la pantalla pulsa con la punta más adelantada", () => {
    const d = new DetectorDePulsaciones();
    const quieta = transformar(manoAbierta(), { z: { 8: -0.04 } });     // el índice apunta
    expect(d.leer(quieta, 0)).toEqual([]);
    expect(d.leer(transformar(manoAbierta(), { escala: 1.05, z: { 8: -0.04 } }), 80)).toEqual([]);
    const pulsa = d.leer(transformar(manoAbierta(), { escala: 1.14, z: { 8: -0.04 } }), 160);
    expect(pulsa).toHaveLength(1);
    expect(pulsa[0].punta).toBe(8);
    // Donde apuntaba al empezar el empujón, no donde acabó.
    expect(pulsa[0].punto).toEqual({ x: quieta[8].x, y: quieta[8].y });
  });

  it("adelantar solo un dedo también pulsa, con ese dedo", () => {
    for (const punta of [4, 12, 20]) {
      const d = new DetectorDePulsaciones();
      d.leer(manoAbierta(), 0);
      const r = d.leer(transformar(manoAbierta(), { z: { [punta]: -0.06 } }), 120);
      expect(r.map(x => x.punta)).toEqual([punta]);
    }
  });

  it("acercarse despacio no pulsa: es acercar la mano, no empujar", () => {
    const d = new DetectorDePulsaciones({ ventanaMs: 300 });
    for (let k = 0; k <= 10; k++) {
      expect(d.leer(transformar(manoAbierta(), { escala: 1 + k * 0.03 }), k * 100)).toEqual([]);
    }
  });

  it("barrer de lado mientras se acerca no pulsa", () => {
    const d = new DetectorDePulsaciones();
    d.leer(manoAbierta(), 0);
    expect(d.leer(transformar(manoAbierta(), { escala: 1.15, dx: 0.25 }), 120)).toEqual([]);
  });

  it("cerrar la mano no pulsa aunque las puntas vengan hacia la cámara", () => {
    const d = new DetectorDePulsaciones();
    d.leer(manoAbierta(), 0);
    const puno = transformar(manoAbierta([4, 8, 12, 16, 20]), { z: { 4: -0.06, 8: -0.06, 12: -0.06, 16: -0.06, 20: -0.06 } });
    expect(d.leer(puno, 120)).toEqual([]);
  });

  it("no vuelve a pulsar hasta echar la mano atrás", () => {
    const d = new DetectorDePulsaciones();
    d.leer(manoAbierta(), 0);
    expect(d.leer(transformar(manoAbierta(), { escala: 1.15 }), 100)).toHaveLength(1);
    expect(d.leer(transformar(manoAbierta(), { escala: 1.3 }), 180)).toEqual([]);   // sigue empujando
    d.leer(transformar(manoAbierta(), { escala: 1.2 }), 400);                         // atrás
    d.leer(transformar(manoAbierta(), { escala: 1.2 }), 450);
    expect(d.leer(transformar(manoAbierta(), { escala: 1.38 }), 550)).toHaveLength(1);
  });

  it("el progreso sube con el empujón, para dibujar cuánto falta", () => {
    const d = new DetectorDePulsaciones();
    d.leer(manoAbierta(), 0);
    d.leer(transformar(manoAbierta(), { escala: 1.05 }), 60);
    expect(Math.max(...d.progreso)).toBeGreaterThan(0.3);
    expect(Math.max(...d.progreso)).toBeLessThan(1);
  });

  it("en pausa (pellizcando) se olvida lo visto", () => {
    const d = new DetectorDePulsaciones();
    d.leer(manoAbierta(), 0);
    d.pausa();
    expect(d.leer(transformar(manoAbierta(), { escala: 1.15 }), 100)).toEqual([]);
  });

  it("la cercanía crece con la mano y con la punta adelantada", () => {
    const [, lejos] = cercanias(manoAbierta());
    const [, cerca] = cercanias(transformar(manoAbierta(), { escala: 1.2 }));
    const [, adelantado] = cercanias(transformar(manoAbierta(), { z: { 8: -0.05 } }));
    expect(cerca).toBeGreaterThan(lejos);
    expect(adelantado).toBeGreaterThan(lejos);
  });
});

describe("aPantalla sobre el vídeo a pantalla completa", () => {
  it("cae encima de lo que se ve, con el recorte del cover", () => {
    // Vídeo 1280x720 en una pantalla 1000x1000: se escala a 1777x1000 y sobra por los lados.
    const cubre = { ancho: 1280, alto: 720 };
    const centro = aPantalla({ x: 0.5, y: 0.5 }, 1000, 1000, { cubre });
    expect(centro.x).toBeCloseTo(500);
    expect(centro.y).toBeCloseTo(500);
    const arriba = aPantalla({ x: 0.5, y: 0 }, 1000, 1000, { cubre });
    expect(arriba.y).toBeCloseTo(0);
    // En espejo: lo que está a la izquierda del fotograma sale a la derecha.
    expect(aPantalla({ x: 0.3, y: 0.5 }, 1000, 1000, { cubre }).x).toBeGreaterThan(500);
  });
});

describe("soltar con impulso", () => {
  it("la velocidad sale del tramo antes de soltar, sin el tirón del final", () => {
    const muestras = [
      { t: 0, x: 0, y: 0 }, { t: 50, x: 50, y: 0 }, { t: 100, x: 100, y: 0 },
      { t: 140, x: 400, y: 0 },                        // el tirón al abrir los dedos
    ];
    const v = velocidadDeSuelta(muestras, 150, { desdeMs: 150, hastaMs: 30 });
    expect(v.x).toBeCloseTo(1);
    expect(v.y).toBe(0);
  });

  it("sin muestras suficientes no hay impulso, y tiene tope", () => {
    expect(velocidadDeSuelta([{ t: 0, x: 0, y: 0 }], 50)).toEqual({ x: 0, y: 0 });
    const loco = velocidadDeSuelta([{ t: 0, x: 0, y: 0 }, { t: 60, x: 6000, y: 0 }], 100, { max: 3 });
    expect(loco.x).toBe(3);
  });

  it("la inercia frena a la mitad en su media vida", () => {
    const { dx, vel } = pasoDeInercia({ x: 2, y: 0 }, 110, { mediaVidaMs: 110 });
    expect(dx).toBeCloseTo(220);
    expect(vel.x).toBeCloseTo(1);
  });
});
