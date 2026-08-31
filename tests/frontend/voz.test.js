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
  llamadaEntranteDeUrl, aperturaDeLlamada,
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
