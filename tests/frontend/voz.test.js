/**
 * Tests de la lógica pura del modo llamada (src/lib/voz.js).
 *
 * Lo que se prueba aquí es dónde se corta una frase para mandarla al sintetizador. Es la
 * diferencia entre una voz que suena a persona y una que suena a locutor de estación de
 * tren, y no hace falta un navegador para comprobarlo. Ver docs/JARVIS_VOZ.md.
 */
import { describe, it, expect } from "vitest";
import {
  trocearParaVoz, textoParaVoz, segundosPendientes, partirEventosSse,
  llamadaEntranteDeUrl, aperturaDeLlamada, detectorDeHabla, rmsDeMuestras,
  pcm16DesdeFloat32, base64DeBytes, pareceEco,
} from "../../src/lib/voz.js";

describe("trocearParaVoz", () => {
  it("no suelta nada hasta que hay bastante que decir", () => {
    // Mandar "Mañana" solo haría que lo entonara como una frase entera y se quedara
    // callado esperando el resto.
    const { trozos, resto } = trocearParaVoz("Mañana tienes");
    expect(trozos).toEqual([]);
    expect(resto).toBe("Mañana tienes");
  });

  it("corta en el final de frase, no a mitad", () => {
    const texto = "Mañana tienes dos clases por la mañana. La primera es a las nueve y "
                + "la segunda a las once en punto.";
    const { trozos } = trocearParaVoz(texto);
    expect(trozos[0]).toBe("Mañana tienes dos clases por la mañana.");
  });

  it("se conforma con una coma si no hay punto", () => {
    const texto = "Tienes clase a las nueve y luego otra a las once, "
                + "y después el entrenamiento de la tarde con el grupo";
    const { trozos } = trocearParaVoz(texto);
    expect(trozos[0]).toBe("Tienes clase a las nueve y luego otra a las once,");
  });

  it("una coma demasiado pronto no vale como corte", () => {
    // Cortar en la primera coma daría un trozo de tres palabras: picado y más caro.
    const { trozos, resto } = trocearParaVoz("Sí, claro");
    expect(trozos).toEqual([]);
    expect(resto).toBe("Sí, claro");
  });

  it("nunca parte una palabra por la mitad", () => {
    // Una parrafada sin un solo signo de puntuación: hay que cortar por algún sitio, pero
    // por un espacio.
    const texto = "palabra ".repeat(40);
    const { trozos } = trocearParaVoz(texto);
    expect(trozos.length).toBeGreaterThan(0);
    for (const t of trozos) expect(t.endsWith("palabra")).toBe(true);
  });

  it("respeta el máximo", () => {
    const texto = "palabra ".repeat(60);
    const { trozos } = trocearParaVoz(texto, { max: 100 });
    for (const t of trozos) expect(t.length).toBeLessThanOrEqual(100);
  });

  it("al terminar suelta lo que quede, aunque sea corto", () => {
    // Sin esto la última frase de cada respuesta se quedaba sin decir, que es el peor
    // sitio posible para perder texto.
    const { trozos, resto } = trocearParaVoz("Y ya está.", { fin: true });
    expect(trozos).toEqual(["Y ya está."]);
    expect(resto).toBe("");
  });

  it("lo que sobra vuelve al buffer para el trozo siguiente", () => {
    const { trozos, resto } = trocearParaVoz("Esta frase ya es bastante larga. Y esta no");
    expect(trozos).toEqual(["Esta frase ya es bastante larga."]);
    expect(resto.trim()).toBe("Y esta no");
  });

  it("aguanta el vacío", () => {
    expect(trocearParaVoz("")).toEqual({ trozos: [], resto: "" });
    expect(trocearParaVoz("", { fin: true })).toEqual({ trozos: [], resto: "" });
  });
});

describe("textoParaVoz", () => {
  it("se come el markdown en vez de leerlo", () => {
    expect(textoParaVoz("Tienes **dos** clases")).toBe("Tienes dos clases");
    expect(textoParaVoz("## Resumen")).toBe("Resumen");
  });

  it("no dicta URLs", () => {
    // "hache te te pe dos puntos barra barra" por teléfono es desconcertante.
    expect(textoParaVoz("Míralo en https://ejemplo.com/algo ahora")).toBe("Míralo en ahora");
  });

  it("de un enlace dice el texto, no la dirección", () => {
    expect(textoParaVoz("Está en [el panel](https://ejemplo.com)")).toBe("Está en el panel");
  });

  it("tira los bloques de código enteros", () => {
    expect(textoParaVoz("Prueba esto:\n```\nnpm run dev\n```\ny listo")).toBe("Prueba esto: y listo");
  });
});

describe("segundosPendientes", () => {
  it("no devuelve tiempos negativos cuando ya ha sonado todo", () => {
    expect(segundosPendientes(3, 10)).toBe(0);
    expect(segundosPendientes(10.5, 10)).toBeCloseTo(0.5);
    expect(segundosPendientes(0, 0)).toBe(0);
  });
});

describe("partirEventosSse", () => {

  it("solo devuelve los eventos ya cerrados", () => {
    // El evento a medias NO se entrega: se completa en la lectura siguiente. Parsearlo
    // aquí tiraría el turno entero por un trozo que iba a llegar entero un instante
    // después.
    const { eventos, resto } = partirEventosSse(
      'event: herramienta\ndata: {"nombre":"agenda"}\n\nevent: fin\ndata: {"resp'
    );
    expect(eventos).toEqual([["herramienta", { nombre: "agenda" }]]);
    expect(resto).toBe('event: fin\ndata: {"resp');
  });

  it("junta lo que llega partido entre dos lecturas", () => {
    const primero = partirEventosSse('event: fin\ndata: {"a"');
    expect(primero.eventos).toEqual([]);
    const segundo = partirEventosSse(primero.resto + ':1}\n\n');
    expect(segundo.eventos).toEqual([["fin", { a: 1 }]]);
    expect(segundo.resto).toBe("");
  });

  it("un evento ilegible no se lleva por delante a los demás", () => {
    const { eventos } = partirEventosSse(
      'event: error\ndata: {roto\n\nevent: fin\ndata: {"ok":true}\n\n'
    );
    expect(eventos).toEqual([["fin", { ok: true }]]);
  });

  it("aguanta un buffer vacío", () => {
    expect(partirEventosSse("")).toEqual({ eventos: [], resto: "" });
  });
});

describe("el troceado tal y como lo usa el modo llamada", () => {
  // Lo de arriba prueba el troceador con el texto entero delante. Esto prueba el uso
  // real: los deltas de `/jarvis/voz` llegan de uno en uno, se acumulan en un buffer y se
  // suelta lo que ya da para una frase. Es donde de verdad se pierde texto si algo está
  // mal, y perder texto aquí significa una frase que no se oye y no se nota en ninguna
  // otra parte.
  function comoLlegaDelModelo(texto, tamano = 6) {
    const deltas = [];
    for (let i = 0; i < texto.length; i += tamano) deltas.push(texto.slice(i, i + tamano));
    return deltas;
  }

  function decirSegunLlega(deltas, cierre = "") {
    const dichos = [];
    let buffer = "";
    for (const delta of deltas) {
      buffer += delta;
      const { trozos, resto } = trocearParaVoz(buffer);
      buffer = resto;
      dichos.push(...trozos);
    }
    // El cierre del turno: lo que quede sale aunque sea corto, más lo que el backend diga
    // que todavía no se ha dicho.
    dichos.push(...trocearParaVoz(buffer + cierre, { fin: true }).trozos);
    return dichos;
  }

  it("dice todo lo que el modelo escribió, sin perder ni repetir nada", () => {
    const texto = "Mañana tienes tres cosas. La primera es a las nueve, en el gimnasio. "
                + "Después no tienes nada hasta la tarde.";
    const dichos = decirSegunLlega(comoLlegaDelModelo(texto));
    expect(dichos.join(" ")).toBe(texto.replace(/\s+/g, " ").trim());
  });

  it("empieza a hablar mucho antes de tener la respuesta entera", () => {
    // El motivo de todo esto: si el primer trozo saliera al final, no se habría ganado
    // nada sobre el turno de una pieza.
    const texto  = "Hace veintiún grados y está despejado. Por la tarde bajará a quince.";
    const deltas = comoLlegaDelModelo(texto);
    let buffer = "", primero = -1;
    deltas.forEach((delta, i) => {
      buffer += delta;
      const { trozos, resto } = trocearParaVoz(buffer);
      buffer = resto;
      if (trozos.length && primero < 0) primero = i;
    });
    expect(primero).toBeGreaterThanOrEqual(0);
    expect(primero).toBeLessThan(deltas.length - 1);
  });

  it("cuando el modelo se queda mudo, se dice lo que el backend puso en su lugar", () => {
    // `por_decir` con la respuesta entera y ni un solo delta: el caso de la respuesta
    // vacía. Sin esto el turno terminaría en silencio con el texto escrito en pantalla.
    const dichos = decirSegunLlega([], "Me he quedado sin respuesta. Vuelve a pedírmelo.");
    expect(dichos.join(" ")).toBe("Me he quedado sin respuesta. Vuelve a pedírmelo.");
  });

  it("no dice nada cuando ya se dijo todo mientras se escribía", () => {
    // `por_decir` vacío es el caso NORMAL: repetir la respuesta al cerrar la haría sonar
    // dos veces seguidas.
    const dichos = decirSegunLlega(comoLlegaDelModelo("Hecho."), "");
    expect(dichos.join(" ")).toBe("Hecho.");
  });
});

describe("llamadaEntranteDeUrl", () => {
  it("reconoce la llegada desde el aviso del móvil", () => {
    expect(llamadaEntranteDeUrl("?llamada=1")).toBe(true);
    expect(llamadaEntranteDeUrl("?otra=x&llamada=1")).toBe(true);
  });

  it("no abre una llamada por entrar al dashboard de siempre", () => {
    // El caso que importa: abrir el dashboard a diario no puede hacer sonar nada.
    expect(llamadaEntranteDeUrl("")).toBe(false);
    expect(llamadaEntranteDeUrl("?llamada=0")).toBe(false);
    expect(llamadaEntranteDeUrl("?llamada=si")).toBe(false);
    expect(llamadaEntranteDeUrl(undefined)).toBe(false);
  });
});

describe("aperturaDeLlamada", () => {
  it("dice lo que manda el backend, que es quien sabe qué hay pendiente", () => {
    const dicha = aperturaDeLlamada({ apertura: "He detectado un fallo. ¿Lo despliego?" });
    expect(dicha).toBe("He detectado un fallo. ¿Lo despliego?");
  });

  it("nunca descuelga en silencio", () => {
    // Descolgar y no oír nada parece que la llamada se ha roto. Pasa de verdad: el aviso
    // llega tarde, o ya decidiste desde el botón del móvil.
    for (const vacio of [null, undefined, {}, { apertura: "   " }]) {
      expect(aperturaDeLlamada(vacio).length).toBeGreaterThan(0);
    }
  });
});

describe("detectorDeHabla", () => {
  /** Alimenta el detector con un nivel constante durante `ms`, muestreando cada 40 ms
   *  como hace vozMicro.js. Devuelve el instante del disparo, o `null`. */
  function alimentar(det, { rms, ms, desde = 0 }) {
    for (let t = desde; t < desde + ms; t += 40) {
      if (det.mira(rms, t)) return t;
    }
    return null;
  }

  it("no corta a Jarvis por el ruido de la sala", () => {
    const det = detectorDeHabla();
    expect(alimentar(det, { rms: 0.01, ms: 5000 })).toBe(null);
  });

  it("corta cuando hablas encima", () => {
    const det = detectorDeHabla();
    // Voz clara y seguida: dispara, pero no antes de la gracia ni antes del sostenido.
    const cuando = alimentar(det, { rms: 0.2, ms: 3000 });
    expect(cuando).not.toBe(null);
    expect(cuando).toBeGreaterThanOrEqual(400);
  });

  it("un portazo no es hablar", () => {
    // Lo que distingue una voz de un golpe es que la voz SIGUE. Un pico de dos muestras
    // pasa el umbral y no debe cortar nada: cortar a Jarvis cada vez que alguien cierra
    // una puerta haría la llamada inservible.
    const det = detectorDeHabla();
    let disparo = null;
    for (let t = 0; t < 6000; t += 40) {
      const pico = t % 1000 < 80;   // 80 ms de golpe por segundo
      if (det.mira(pico ? 0.5 : 0.005, t)) { disparo = t; break; }
    }
    expect(disparo).toBe(null);
  });

  it("no cuenta las primeras décimas, que son la cola de tu propia frase", () => {
    const det = detectorDeHabla({ msGracia: 400, msSostenidos: 300 });
    // Voz desde el instante cero: aun así no puede disparar dentro de la gracia.
    for (let t = 0; t < 400; t += 40) expect(det.mira(0.3, t)).toBe(false);
  });

  it("dispara una sola vez: quien lo usa ya ha cortado y lo tira", () => {
    const det = detectorDeHabla();
    expect(alimentar(det, { rms: 0.3, ms: 3000 })).not.toBe(null);
    expect(alimentar(det, { rms: 0.3, ms: 3000, desde: 5000 })).toBe(null);
  });

  it("con el umbral subido aguanta lo que antes cortaba", () => {
    // Es lo que hace la llamada sola cuando un corte resulta ser el eco de Jarvis.
    const flojo = detectorDeHabla({ umbral: 0.055 });
    const duro  = detectorDeHabla({ umbral: 0.4 });
    expect(alimentar(flojo, { rms: 0.1, ms: 3000 })).not.toBe(null);
    expect(alimentar(duro,  { rms: 0.1, ms: 3000 })).toBe(null);
  });

  it("una lectura rota no dispara", () => {
    // NaN saliendo del analizador no puede leerse como "está hablando".
    const det = detectorDeHabla();
    expect(alimentar(det, { rms: NaN, ms: 3000 })).toBe(null);
  });
});

describe("rmsDeMuestras", () => {
  it("el silencio es cero y una onda llena es casi uno", () => {
    expect(rmsDeMuestras(new Float32Array(64))).toBe(0);
    expect(rmsDeMuestras(new Float32Array(64).fill(1))).toBeCloseTo(1);
    expect(rmsDeMuestras([])).toBe(0);
    expect(rmsDeMuestras(null)).toBe(0);
  });

  it("no depende del signo: una onda es tan alta abajo como arriba", () => {
    const alterna = Float32Array.from({ length: 64 }, (_, i) => (i % 2 ? 0.5 : -0.5));
    expect(rmsDeMuestras(alterna)).toBeCloseTo(0.5);
  });
});


describe("pcm16DesdeFloat32", () => {
  it("escala el rango entero", () => {
    const pcm = pcm16DesdeFloat32(new Float32Array([0, 1, -1]));
    expect(pcm[0]).toBe(0);
    expect(pcm[1]).toBe(32767);
    expect(pcm[2]).toBe(-32768);
  });

  it("recorta los picos en vez de dar la vuelta al entero", () => {
    // Sin el recorte, un pico por encima de 1 sale como un valor negativo enorme y suena
    // como un chasquido. Es de las pocas cosas que un transcriptor no perdona.
    const pcm = pcm16DesdeFloat32(new Float32Array([2, -2]));
    expect(pcm[0]).toBe(32767);
    expect(pcm[1]).toBe(-32768);
  });

  it("aguanta lo vacío", () => {
    expect(pcm16DesdeFloat32(null)).toHaveLength(0);
  });
});

describe("base64DeBytes", () => {
  it("codifica lo que le den", () => {
    expect(base64DeBytes(new Uint8Array([104, 111, 108, 97]))).toBe("aG9sYQ==");
  });

  it("no revienta con un buffer grande", () => {
    // Un `fromCharCode(...bytes)` de una vez peta la pila en Safari, y lo hace a media
    // llamada, que es el peor sitio para descubrirlo.
    expect(base64DeBytes(new Uint8Array(200000)).length).toBeGreaterThan(0);
  });
});

describe("pareceEco", () => {
  const suyo = "He detectado un fallo y ya lo he corregido. El CI está en verde.";

  it("reconoce a Jarvis oyéndose a sí mismo", () => {
    expect(pareceEco("he detectado un fallo y ya lo he corregido", suyo)).toBe(true);
  });

  it("NO se traga una interrupción de verdad", () => {
    expect(pareceEco("no, espera, mejor lo dejamos", suyo)).toBe(false);
  });

  it("deja pasar las palabras sueltas con las que se corta a alguien", () => {
    // «sí», «vale», «no» son justo lo que dirías para cortarle, y con una o dos palabras
    // cualquier cosa se parece a cualquier cosa. Confundirlas con eco sería peor que el
    // eco: te quedarías sin poder interrumpir.
    for (const corte of ["vale", "no", "sí", "para ya"]) {
      expect(pareceEco(corte, suyo)).toBe(false);
    }
  });

  it("sin nada dicho no hay eco posible", () => {
    expect(pareceEco("cualquier cosa que diga", "")).toBe(false);
  });

  it("compara sin acentos ni signos, que es como llega la transcripción", () => {
    expect(pareceEco("el ci esta en verde", suyo)).toBe(true);
  });
});
