/**
 * Tests del cliente de la voz de ElevenLabs (src/lib/vozEleven.js).
 *
 * Lo que se prueba aquí es UNA sola cosa, la que costó encontrar en el móvil: que
 * cuando la voz de pago no sirve, lo que se iba a decir NO se pierde y quien abrió la
 * voz se entera. Un fallo de esta parte no da error en ninguna consola — da silencio, y
 * una llamada colgada esperando a alguien que ya no va a hablar. Ver docs/JARVIS_VOZ.md.
 *
 * El WebSocket y el AudioContext son de mentira: no hay navegador que valga para esto y
 * tampoco hace falta, porque lo que se comprueba es el reparto de turnos.
 */
import { describe, it, expect, beforeEach, vi } from "vitest";
import { abrirVozEleven } from "../../src/lib/vozEleven.js";

let socket = null;

class WebSocketFalso {
  static CONNECTING = 0;
  static OPEN       = 1;
  static CLOSING    = 2;
  static CLOSED     = 3;

  constructor(url) {
    this.url        = url;
    this.readyState = WebSocketFalso.OPEN;   // abierto ya: nos ahorra el onopen
    this.enviados   = [];
    socket          = this;
  }

  send(texto) { this.enviados.push(JSON.parse(texto)); }
  close()     { this.readyState = WebSocketFalso.CLOSED; this.onclose?.({}); }

  /** Lo que mandaría ElevenLabs. */
  recibir(mensaje) { this.onmessage?.({ data: JSON.stringify(mensaje) }); }

  /** El contexto del turno que está en el aire. */
  get contexto() { return this.enviados.at(-1)?.context_id; }
}

let fuentesCreadas = [];

class AudioContextFalso {
  constructor() { this.state = "running"; this.currentTime = 0; this.destination = {}; }
  createGain()  { return { connect() {} }; }
  createBufferSource() {
    // El trozo "suena" en el tick siguiente: es `onended` lo que cierra el turno.
    const f = { connect() {}, stop() {}, start() { setTimeout(() => f.onended?.(), 0); } };
    fuentesCreadas.push(f);
    return f;
  }
  createBuffer(canales, largo, hz) {
    return { duration: largo / hz, getChannelData: () => new Float32Array(largo) };
  }
  decodeAudioData() { return Promise.resolve({ duration: 1 }); }
  resume() { return Promise.resolve(); }
  close()  { this.state = "closed"; }
}

beforeEach(() => {
  socket = null;
  fuentesCreadas = [];
  vi.stubGlobal("WebSocket", WebSocketFalso);
  vi.stubGlobal("AudioContext", AudioContextFalso);
  vi.stubGlobal("atob", (s) => s);
});

function abrir(alFallar) {
  return abrirVozEleven({ token: "sutkn_x", voiceId: "v1", modelId: "m", alFallar });
}

describe("cuando la voz de pago falla", () => {
  it("devuelve la frase y el turno si el token está caducado", () => {
    // El caso del móvil: se abre el dashboard, se guarda el teléfono y se llama media
    // hora después. ElevenLabs acepta el socket y luego lo cierra con `invalid_token`.
    // Antes ese mensaje se ignoraba en silencio y la llamada se quedaba muda.
    const fallos = [];
    const voz = abrir((sinDecir) => fallos.push(...sinDecir));
    const fin = vi.fn();

    voz.decir("Hola, dime.", fin);
    socket.recibir({ message: "Token not found or has expired.", error: "invalid_token" });

    expect(fallos.map(([t]) => t)).toEqual(["Hola, dime."]);
    expect(fallos[0][1]).toBe(fin);
    expect(fin).not.toHaveBeenCalled();   // lo llamará la voz del navegador, no nosotros
  });

  it("devuelve TAMBIÉN las frases que esperaban en la cola", () => {
    // Un turno son varias frases seguidas. Rescatar solo la que estaba sonando dejaba a
    // Jarvis a medias, diciendo el relleno y comiéndose la respuesta.
    let sinDecir = [];
    const voz = abrir((p) => { sinDecir = p; });

    voz.decir("Déjame mirar el calendario.", () => {});
    voz.decir("Mañana tienes dos clases.", () => {});
    socket.close();

    expect(sinDecir.map(([t]) => t)).toEqual([
      "Déjame mirar el calendario.", "Mañana tienes dos clases.",
    ]);
  });

  it("no se queda muda cuando el turno termina sin sonar", () => {
    // `isFinal` con cero bytes y ningún error: lo que hace una voz de la biblioteca en
    // plan gratuito.
    let sinDecir = [];
    const voz = abrir((p) => { sinDecir = p; });

    voz.decir("Buenas tardes.", () => {});
    socket.recibir({ isFinal: true, contextId: socket.contexto });

    expect(sinDecir.map(([t]) => t)).toEqual(["Buenas tardes."]);
  });

  it("una vez descartada, lo siguiente se cae al navegador sin pasar por el socket", () => {
    // Quien la abrió sigue teniendo la referencia un instante más, y esa frase tampoco
    // puede perderse: encolarla contra un socket muerto era colgar la llamada.
    const fallos = [];
    const voz = abrir((p) => fallos.push(...p));

    voz.decir("Primera.", () => {});
    socket.recibir({ error: "invalid_token" });
    const enviadosAntes = socket.enviados.length;
    voz.decir("Segunda.", () => {});

    expect(fallos.map(([t]) => t)).toEqual(["Primera.", "Segunda."]);
    expect(socket.enviados.length).toBe(enviadosAntes);
  });

  it("colgar la llamada no cuenta como fallo", () => {
    // `cerrar()` dispara el `onclose` igual que una caída. Confundirlos sacaba un aviso
    // rojo y ponía a hablar a la voz del navegador justo después de colgar.
    const alFallar = vi.fn();
    const voz = abrir(alFallar);

    voz.decir("Hasta luego.", () => {});
    voz.cerrar();

    expect(alFallar).not.toHaveBeenCalled();
  });
});

describe("cuando la voz suena", () => {
  it("encadena las frases y avisa al terminar cada una", async () => {
    const alFallar = vi.fn();
    const voz = abrir(alFallar);
    const primera = vi.fn();

    voz.decir("Una.", primera);
    voz.decir("Dos.", () => {});
    socket.recibir({ audio: "abcd", contextId: socket.contexto });
    await new Promise(r => setTimeout(r, 0));
    socket.recibir({ isFinal: true, contextId: socket.contexto });
    await new Promise(r => setTimeout(r, 0));

    expect(alFallar).not.toHaveBeenCalled();
    expect(primera).toHaveBeenCalled();
    // Y la segunda ya está en el aire: un contexto nuevo con su texto.
    expect(socket.enviados.some(m => m.text === "Dos.")).toBe(true);
  });

  it("el resto de un turno cortado no suena mezclado con el turno siguiente", async () => {
    // La decodificación (`decodeAudioData`) es asíncrona. Si el trozo del turno viejo
    // llega justo antes de `callar()` pero termina de decodificarse DESPUÉS de que ya
    // haya arrancado el turno nuevo, `contexto` vuelve a ser verdadero —pero del turno
    // nuevo— y un chequeo de "¿hay contexto?" en vez de "¿es EL MISMO contexto?" dejaba
    // pasar ese resto, que sonaba encima de la respuesta nueva.
    const voz = abrir(() => {});

    voz.decir("Turno viejo.", () => {});
    socket.recibir({ audio: "viejo", contextId: socket.contexto });
    // Se corta y se arranca el turno nuevo ANTES de que la promesa de arriba resuelva.
    voz.callar();
    voz.decir("Turno nuevo.", () => {});
    socket.recibir({ audio: "nuevo", contextId: socket.contexto });

    await new Promise(r => setTimeout(r, 0));
    await new Promise(r => setTimeout(r, 0));
    await new Promise(r => setTimeout(r, 0));

    // Solo debería haber sonado el trozo del turno nuevo.
    expect(fuentesCreadas.length).toBe(1);
  });
});
