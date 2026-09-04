/**
 * Tests del micrófono continuo de la llamada (src/lib/vozScribe.js).
 *
 * Lo que se prueba es lo que cuesta dinero o deja la llamada sorda, que son las dos
 * formas en que esta pieza puede fallar sin que nadie se entere:
 *
 *   - Que al parar se cierre TODO. Scribe cobra micrófono abierto, silencios incluidos:
 *     un socket que sobreviva a la llamada es dinero corriendo que no se ve en ninguna
 *     pantalla.
 *   - Que un cierre inesperado se trate como fallo y no como el final de nada. Es la
 *     lección del TTS, donde confundir las dos cosas dejó la llamada colgada oyendo el
 *     silencio (ver docs/JARVIS_VOZ.md).
 *   - Que lo que se captura antes de que el socket abra no se tire: son las primeras
 *     décimas, o sea justo el «hola».
 *
 * El WebSocket, el AudioContext y el micrófono son de mentira. No hay navegador que valga
 * para esto y tampoco hace falta: lo que se comprueba es el reparto, no el sonido.
 */
import { describe, it, expect, beforeEach, vi } from "vitest";
import { escucharConScribe } from "../../src/lib/vozScribe.js";

let socket = null;

class WebSocketFalso {
  constructor(url) {
    this.url        = url;
    this.readyState = 0;      // conectando: el `onopen` lo dispara el test
    this.enviados   = [];
    this.cerrado    = false;
    socket          = this;
  }
  send(texto) { this.enviados.push(JSON.parse(texto)); }
  close()     { this.cerrado = true; this.readyState = 3; }

  abrir()             { this.readyState = 1; this.onopen?.({}); }
  recibir(mensaje)    { this.onmessage?.({ data: JSON.stringify(mensaje) }); }
  caerse()            { this.readyState = 3; this.onclose?.({}); }
}

let pistas = [];
let contexto = null;

class AudioContextFalso {
  constructor(opciones) {
    this.opciones = opciones;
    this.cerrado  = false;
    contexto      = this;
  }
  createMediaStreamSource() { return { connect: () => {}, disconnect: () => {} }; }
  createScriptProcessor()   {
    this.procesador = { connect: () => {}, disconnect: () => {}, onaudioprocess: null };
    return this.procesador;
  }
  resume() {}
  close()  { this.cerrado = true; }
}

/** Simula un trozo de audio capturado por el micrófono. */
function capturar(valor = 0.5, n = 8) {
  const muestras = new Float32Array(n).fill(valor);
  contexto.procesador.onaudioprocess({ inputBuffer: { getChannelData: () => muestras } });
}

beforeEach(() => {
  socket = null;
  contexto = null;
  pistas = [{ stop: vi.fn() }];
  globalThis.WebSocket = WebSocketFalso;
  globalThis.window = { AudioContext: AudioContextFalso };
  globalThis.navigator = { mediaDevices: { getUserMedia: vi.fn(async () => ({ getTracks: () => pistas })) } };
});

describe("escucharConScribe", () => {
  it("pide el micro con cancelación de eco, que es lo que sostiene todo esto", async () => {
    await escucharConScribe({ token: "t" });
    const pedido = globalThis.navigator.mediaDevices.getUserMedia.mock.calls[0][0];
    expect(pedido.audio.echoCancellation).toBe(true);
  });

  it("abre el socket con el VAD de ElevenLabs y el token", async () => {
    await escucharConScribe({ token: "tok-123", modelo: "scribe_v2_realtime" });
    expect(socket.url).toContain("token=tok-123");
    expect(socket.url).toContain("commit_strategy=vad");
    expect(socket.url).toContain("audio_format=pcm_16000");
    // El contexto se pide ya a 16 kHz: remuestrear a mano sería peor y más lento.
    expect(contexto.opciones.sampleRate).toBe(16000);
  });

  it("no tira lo que se captura antes de que el socket abra", async () => {
    // Son las primeras décimas de la llamada, o sea justo el «hola». Perderlas era el
    // fallo que esto viene a arreglar, y volvería por otro sitio.
    await escucharConScribe({ token: "t" });
    capturar();
    capturar();
    expect(socket.enviados).toHaveLength(0);
    socket.abrir();
    expect(socket.enviados).toHaveLength(2);
    expect(socket.enviados[0].message_type).toBe("input_audio_chunk");
    expect(socket.enviados[0].audio_base_64.length).toBeGreaterThan(0);
  });

  it("no acumula sin límite si el socket no abre nunca", async () => {
    await escucharConScribe({ token: "t" });
    for (let i = 0; i < 100; i++) capturar();
    socket.abrir();
    // Un socket que no abre no puede comerse la memoria del móvil.
    expect(socket.enviados.length).toBeLessThanOrEqual(32);
  });

  it("reparte parciales y frases cerradas", async () => {
    const parciales = [], cerradas = [];
    await escucharConScribe({ token: "t", alParcial: t => parciales.push(t), alCerrar: t => cerradas.push(t) });
    socket.abrir();
    socket.recibir({ message_type: "session_started" });
    socket.recibir({ message_type: "partial_transcript", text: "oye jarv" });
    socket.recibir({ message_type: "committed_transcript", text: "oye Jarvis" });
    expect(parciales).toEqual(["oye jarv"]);
    expect(cerradas).toEqual(["oye Jarvis"]);
  });

  it("un cierre inesperado es un FALLO, no el final de nada", async () => {
    // Aquí no hay turnos que terminen: el micro no se cierra hasta colgar. Tratar el
    // `onclose` como fin normal es lo que dejó la llamada colgada con el TTS.
    const fallos = [];
    await escucharConScribe({ token: "t", alFallar: m => fallos.push(m) });
    socket.abrir();
    socket.caerse();
    expect(fallos).toHaveLength(1);
    expect(pistas[0].stop).toHaveBeenCalled();   // y se suelta el micrófono
  });

  it("un error del servidor cierra y avisa con el motivo", async () => {
    const fallos = [];
    await escucharConScribe({ token: "t", alFallar: m => fallos.push(m) });
    socket.abrir();
    // `quota_exceeded` es "se acabó el saldo", y conviene que se pueda decir tal cual.
    socket.recibir({ message_type: "quota_exceeded", error: "se acabó el saldo" });
    expect(fallos).toEqual(["se acabó el saldo"]);
    expect(socket.cerrado).toBe(true);
  });

  it("parar cierra el micrófono, el contexto y el socket", async () => {
    // Es la prueba del contador: Scribe cobra micrófono abierto, así que lo que aquí
    // quede vivo se sigue pagando sin que aparezca en ninguna pantalla.
    const escucha = await escucharConScribe({ token: "t" });
    socket.abrir();
    escucha.parar();
    expect(pistas[0].stop).toHaveBeenCalled();
    expect(contexto.cerrado).toBe(true);
    expect(socket.cerrado).toBe(true);
  });

  it("después de parar no se avisa de nada ni se manda nada", async () => {
    const fallos = [], parciales = [];
    const escucha = await escucharConScribe({ token: "t", alFallar: m => fallos.push(m), alParcial: t => parciales.push(t) });
    socket.abrir();
    escucha.parar();
    socket.caerse();
    socket.recibir({ message_type: "partial_transcript", text: "tarde" });
    capturar();
    expect(fallos).toEqual([]);
    expect(parciales).toEqual([]);
  });

  it("sin token no se abre nada", async () => {
    expect(await escucharConScribe({})).toBeNull();
    expect(globalThis.navigator.mediaDevices.getUserMedia).not.toHaveBeenCalled();
  });

  it("sin permiso de micrófono devuelve null en vez de romper la llamada", async () => {
    // `null` significa "esta llamada se queda sin Scribe", y quien llama vuelve al
    // reconocimiento del navegador. Lo que no puede hacer nunca es tirar la llamada.
    globalThis.navigator.mediaDevices.getUserMedia = vi.fn(async () => { throw new Error("denegado"); });
    expect(await escucharConScribe({ token: "t" })).toBeNull();
  });
});
