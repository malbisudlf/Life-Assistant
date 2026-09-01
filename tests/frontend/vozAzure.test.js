/**
 * Tests del cliente de la voz de Azure (src/lib/vozAzure.js).
 *
 * Mismo criterio que vozEleven.test.js, porque el fallo que importa es el mismo: cuando
 * la voz de pago no sirve, lo que se iba a decir NO se pierde y quien la abrió se entera.
 * Un fallo aquí no sale por ninguna consola — sale como silencio, y como una llamada
 * colgada esperando a alguien que ya no va a hablar.
 *
 * El AudioContext es de mentira y el audio también: lo que se comprueba es el reparto de
 * turnos, el orden y el rescate, no que suene un MP3.
 */
import { describe, it, expect, beforeEach, vi } from "vitest";
import { abrirVozAzure } from "../../src/lib/vozAzure.js";

let fuentes = [];

class AudioContextFalso {
  constructor() { this.state = "running"; this.currentTime = 0; this.destination = {}; }
  createGain() { return { connect() {} }; }
  createBufferSource() {
    // No suena sola: cada test decide CUÁNDO termina, que es lo que deja mirar el estado
    // a mitad de una frase.
    const f = { connect() {}, stop() {}, start() {} };
    fuentes.push(f);
    return f;
  }
  decodeAudioData() { return Promise.resolve({ duration: 1 }); }
  resume() { return Promise.resolve(); }
  close() { this.state = "closed"; }
}

/** Deja correr las promesas pendientes (la petición y la decodificación). */
const respirar = () => new Promise((r) => setTimeout(r, 0));

/** Termina la frase que está sonando. */
async function terminarFrase() {
  const f = fuentes.shift();
  f?.onended?.();
  await respirar();
}

beforeEach(() => {
  fuentes = [];
  vi.stubGlobal("AudioContext", AudioContextFalso);
  vi.stubGlobal("AbortController", class {
    constructor() { this.signal = { abortada: false }; }
    abort() { this.signal.abortada = true; }
  });
});

const audioOk = () => Promise.resolve(new ArrayBuffer(8));

describe("abrirVozAzure", () => {
  it("no se abre si el navegador no puede", () => {
    vi.stubGlobal("AudioContext", undefined);
    vi.stubGlobal("webkitAudioContext", undefined);
    expect(abrirVozAzure({ pedirAudio: audioOk })).toBe(null);
  });

  it("dice las frases EN ORDEN y no dos a la vez", async () => {
    const pedidos = [];
    const voz = abrirVozAzure({ pedirAudio: (t) => { pedidos.push(t); return audioOk(); } });
    const dichas = [];
    voz.decir("Uno.", () => dichas.push("Uno."));
    voz.decir("Dos.", () => dichas.push("Dos."));
    await respirar();

    // Solo una suena; la segunda espera turno aunque su audio ya se esté pidiendo.
    expect(fuentes).toHaveLength(1);
    expect(dichas).toEqual([]);
    await terminarFrase();
    expect(dichas).toEqual(["Uno."]);
    await terminarFrase();
    expect(dichas).toEqual(["Uno.", "Dos."]);
  });

  it("va pidiendo la siguiente mientras suena la de ahora", async () => {
    // Es lo que quita el silencio entre frases: sin esto cada una espera a que termine
    // la anterior para ni siquiera empezar a pedirse, y se oye la costura.
    const pedidos = [];
    const voz = abrirVozAzure({ pedirAudio: (t) => { pedidos.push(t); return audioOk(); } });
    voz.decir("Uno.", () => {});
    voz.decir("Dos.", () => {});
    await respirar();
    expect(pedidos).toEqual(["Uno.", "Dos."]);
  });

  it("si el audio no llega, lo que quedaba sin decir se devuelve entero", async () => {
    // El caso que importa: quien abrió la voz tiene que poder decirlo con la del
    // navegador. Y con su `alFinal`, porque el modo llamada encadena la escucha con él.
    let rescatado = null;
    const voz = abrirVozAzure({
      pedirAudio: () => Promise.reject(new Error("503")),
      alFallar:   (sinDecir) => { rescatado = sinDecir; },
    });
    voz.decir("Uno.", () => {});
    voz.decir("Dos.", () => {});
    await respirar();
    expect(rescatado.map(([t]) => t)).toEqual(["Uno.", "Dos."]);
  });

  it("una vez muerta, lo siguiente se devuelve al instante", async () => {
    const rescates = [];
    const voz = abrirVozAzure({
      pedirAudio: () => Promise.reject(new Error("503")),
      alFallar:   (sinDecir) => rescates.push(...sinDecir.map(([t]) => t)),
    });
    voz.decir("Uno.", () => {});
    await respirar();
    voz.decir("Dos.", () => {});
    // Sin ida y vuelta de por medio: encolar contra una voz muerta es silencio.
    expect(rescates).toEqual(["Uno.", "Dos."]);
  });

  it("un audio que no decodifica cuenta como fallo, no como turno hecho", async () => {
    // El fallo MUDO: llegaron bytes pero no sonó nada. Medir que llegó audio daba por
    // buena una respuesta que nadie oyó.
    vi.stubGlobal("AudioContext", class extends AudioContextFalso {
      decodeAudioData() { return Promise.reject(new Error("no es un mp3")); }
    });
    let rescatado = null;
    const voz = abrirVozAzure({ pedirAudio: audioOk, alFallar: (s) => { rescatado = s; } });
    voz.decir("Uno.", () => {});
    await respirar();
    expect(rescatado.map(([t]) => t)).toEqual(["Uno."]);
  });

  it("callar corta lo que suena y tira lo que esperaba, sin rescatarlo", async () => {
    // Es el barge-in: si te has puesto a hablar encima, lo que Jarvis tenía preparado ya
    // no viene a cuento. Rescatarlo aquí sería que la voz del navegador siguiera
    // diciéndolo justo cuando le acabas de cortar.
    let rescatado = null;
    const voz = abrirVozAzure({ pedirAudio: audioOk, alFallar: (s) => { rescatado = s; } });
    voz.decir("Uno.", () => {});
    voz.decir("Dos.", () => {});
    await respirar();
    voz.callar();
    await respirar();
    expect(rescatado).toBe(null);
    // Y después de callar se puede seguir hablando: callar no mata la voz.
    voz.decir("Tres.", () => {});
    await respirar();
    expect(fuentes.length).toBeGreaterThan(0);
  });

  it("un texto que se queda en nada avisa igual", () => {
    // `alFinal` se llama SIEMPRE, suene o no: el modo llamada encadena la escucha con él.
    const voz = abrirVozAzure({ pedirAudio: audioOk });
    let avisado = false;
    voz.decir("   ", () => { avisado = true; });
    expect(avisado).toBe(true);
  });

  it("cerrar no deja nada sonando", async () => {
    const voz = abrirVozAzure({ pedirAudio: audioOk });
    voz.decir("Uno.", () => {});
    await respirar();
    voz.cerrar();
    voz.decir("Dos.", () => {});
    await respirar();
    // Nada nuevo empieza a sonar después de colgar.
    expect(fuentes).toHaveLength(1);
  });
});
