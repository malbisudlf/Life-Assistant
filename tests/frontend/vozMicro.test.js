/**
 * Tests del medidor del barge-in (src/lib/vozMicro.js).
 *
 * Lo que se comprueba aquí son las tres cosas que, si fallan, rompen la llamada entera:
 * que un micrófono negado NO tire la llamada, que al avisar de que le has cortado el
 * micro quede CERRADO (o habría dos capturas a la vez y el reconocimiento no arranca), y
 * que nada de esto se conecte al altavoz, que sería el acople que se viene a evitar.
 *
 * El micrófono y el AudioContext son de mentira: no hay navegador aquí, y tampoco hace
 * falta, porque las reglas de "esto es voz" son puras y se prueban en voz.test.js.
 */
import { describe, it, expect, beforeEach, afterEach, vi } from "vitest";
import { vigilarInterrupcion } from "../../src/lib/vozMicro.js";

let pistas;      // las pistas del micrófono falso
let contexto;    // el AudioContext falso que se creó

class AnalizadorFalso {
  constructor() { this.fftSize = 2048; this.nivel = 0; }
  getFloatTimeDomainData(destino) { destino.fill(this.nivel); }
}

class AudioContextFalso {
  constructor() {
    this.cerrado    = false;
    this.destination = {};
    this.analizador = new AnalizadorFalso();
    this.conectadoADestino = false;
    contexto = this;
  }
  createAnalyser() { return this.analizador; }
  createMediaStreamSource() {
    const destino = this;
    return { connect(a) { if (a === destino.destination) destino.conectadoADestino = true; } };
  }
  close() { this.cerrado = true; }
}

/** El micrófono. `nivel` es lo que "suena" en la sala. */
function micro() {
  pistas = [{ parado: false, stop() { this.parado = true; } }];
  return { getTracks: () => pistas };
}

beforeEach(() => {
  vi.useFakeTimers();
  contexto = null;
  pistas   = [];
  window.AudioContext = AudioContextFalso;
  navigator.mediaDevices = { getUserMedia: vi.fn().mockResolvedValue(micro()) };
});

afterEach(() => {
  vi.useRealTimers();
  delete window.AudioContext;
});

describe("vigilarInterrupcion", () => {
  it("sin micrófono la llamada sigue: devuelve null y no revienta", async () => {
    // Permiso denegado es lo normal la primera vez, y en un WebView puede no haber
    // getUserMedia siquiera. Quedarse sin barge-in es aceptable; tirar la llamada no.
    navigator.mediaDevices.getUserMedia = vi.fn().mockRejectedValue(new Error("NotAllowedError"));
    const alHablar = vi.fn();
    expect(await vigilarInterrupcion({ alHablar })).toBe(null);
    expect(alHablar).not.toHaveBeenCalled();
  });

  it("pide la cancelación de eco, que es lo que sostiene todo esto", async () => {
    await vigilarInterrupcion({ alHablar: () => {} });
    const pedido = navigator.mediaDevices.getUserMedia.mock.calls[0][0];
    expect(pedido.audio.echoCancellation).toBe(true);
  });

  it("no conecta el micrófono al altavoz", async () => {
    await vigilarInterrupcion({ alHablar: () => {} });
    expect(contexto.conectadoADestino).toBe(false);
  });

  it("avisa cuando hablas encima, y para el micro ANTES de avisar", async () => {
    let microAbiertoAlAvisar = null;
    const alHablar = vi.fn(() => { microAbiertoAlAvisar = !pistas[0].parado; });
    await vigilarInterrupcion({ alHablar, msMuestra: 40 });

    contexto.analizador.nivel = 0.3;   // te pones a hablar
    await vi.advanceTimersByTimeAsync(3000);

    expect(alHablar).toHaveBeenCalledTimes(1);
    // Si el medidor siguiera abierto, la captura del reconocimiento se pelearía con
    // esta: en iOS y en los WebView eso es una llamada que se queda sorda.
    expect(microAbiertoAlAvisar).toBe(false);
    expect(contexto.cerrado).toBe(true);
  });

  it("el silencio no avisa de nada por mucho que se espere", async () => {
    const alHablar = vi.fn();
    await vigilarInterrupcion({ alHablar });
    contexto.analizador.nivel = 0.004;
    await vi.advanceTimersByTimeAsync(30000);
    expect(alHablar).not.toHaveBeenCalled();
  });

  it("parar() cierra el micrófono: el punto rojo del navegador se apaga", async () => {
    const vigilante = await vigilarInterrupcion({ alHablar: () => {} });
    vigilante.parar();
    expect(pistas[0].parado).toBe(true);
    expect(contexto.cerrado).toBe(true);
    // Y ya no mide nada más, aunque la sala se ponga a gritar.
    const alHablar = vi.fn();
    contexto.analizador.nivel = 0.9;
    await vi.advanceTimersByTimeAsync(5000);
    expect(alHablar).not.toHaveBeenCalled();
  });
});
