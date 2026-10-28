// El micrófono de la llamada con el Whisper de jacobo (`telefono/oido/`), a través del
// puente `/voz/oido` del backend. Va delante de Scribe (vozScribe.js): es gratis, es el
// mismo oído que el teléfono, y si jacobo no está la llamada cae a Scribe y, si tampoco,
// al reconocimiento del navegador.
//
// La diferencia con Scribe que obliga a tener aquí lógica propia: **jacobo no decide
// dónde acaba una frase**. Scribe trae su propio VAD; el oído espera a que el cliente le
// diga «fin» (es lo que hace la voice-app en el teléfono). Así que aquí se mide la
// energía del micro y se corta: se manda audio solo mientras hablas —con unas décimas de
// antes, para no comerse la primera sílaba— y «fin» tras un silencio. Esa regla, que es
// pura, es `CortadorDeFrases`; el resto del fichero es fontanería de audio, la misma que
// la de Scribe.

import { pcm16DesdeFloat32 } from "./voz.js";

const MUESTREO = 16000;
// 1024 muestras a 16 kHz son 64 ms: el silencio del final se mide con esa resolución.
const BUFER    = 1024;
const TRAMA_MS = (BUFER / MUESTREO) * 1000;

/** Decide, trama a trama, si estás hablando y cuándo has terminado la frase.
 *
 *  El umbral se adapta al ruido de fondo (el coche, la calle): es el ruido medido en las
 *  tramas calladas por un factor, con un suelo para que en una habitación en silencio
 *  no salte con un roce. */
export class CortadorDeFrases {
  constructor({
    umbralMin = 0.012, factorRuido = 3, arranqueMs = 120,
    silencioFinMs = 750, maxFraseMs = 25000, prerrollMs = 320,
  } = {}) {
    Object.assign(this, { umbralMin, factorRuido, arranqueMs, silencioFinMs, maxFraseMs });
    this.prerrollTramas = Math.max(1, Math.round(prerrollMs / TRAMA_MS));
    this.ruido = umbralMin / factorRuido;
    this.reinicia();
  }

  reinicia() {
    this.hablando  = false;
    this.vozMs     = 0;
    this.silencioMs = 0;
    this.fraseMs   = 0;
  }

  get umbral() {
    return Math.max(this.umbralMin, this.ruido * this.factorRuido);
  }

  /** Una trama. Devuelve "callado" (no se manda), "empieza" (manda lo de antes y esta),
   *  "sigue" (se manda) o "fin" (se manda y se cierra la frase). */
  trama(rms, ms = TRAMA_MS) {
    const voz = rms > this.umbral;
    if (!this.hablando) {
      if (!voz) {
        this.vozMs = 0;
        // El ruido de fondo solo se aprende cuando no hablas: aprenderlo con tu voz
        // subiría el umbral hasta dejar de oírte.
        this.ruido = this.ruido * 0.95 + rms * 0.05;
        return "callado";
      }
      this.vozMs += ms;
      if (this.vozMs < this.arranqueMs) return "callado";
      this.hablando = true;
      this.fraseMs = this.vozMs;
      this.silencioMs = 0;
      return "empieza";
    }
    this.fraseMs += ms;
    this.silencioMs = voz ? 0 : this.silencioMs + ms;
    if (this.silencioMs >= this.silencioFinMs || this.fraseMs >= this.maxFraseMs) {
      this.reinicia();
      return "fin";
    }
    return "sigue";
  }
}

/** La energía de una trama de audio (Float32, -1..1). */
export function rmsDe(muestras) {
  let suma = 0;
  for (let i = 0; i < muestras.length; i++) suma += muestras[i] * muestras[i];
  return muestras.length ? Math.sqrt(suma / muestras.length) : 0;
}

/** Lo que se le enseña a la llamada mientras hablas: lo fijo y lo provisional juntos. */
export function textoDeParcial(msg) {
  return `${msg?.fijo || ""} ${msg?.provisional || ""}`.replace(/\s+/g, " ").trim();
}

/** La URL del puente, a partir de la del backend. */
export function urlDelOido(api) {
  return `${String(api || "").replace(/^http/, "ws").replace(/\/$/, "")}/voz/oido`;
}

/** Abre el micrófono y lo transcribe con jacobo mientras dure la llamada.
 *
 *  Misma interfaz que `escucharConScribe`: devuelve `{ parar }`, o `null` si no se ha
 *  podido montar (jacobo apagado, sin sesión, sin micro). Con `null` quien llama prueba
 *  con Scribe; no es un fallo que tirar por pantalla. A diferencia de Scribe, aquí se
 *  espera a que el puente diga «listo» antes de abrir el micro: así un jacobo apagado se
 *  sabe ANTES de empezar la llamada y no a la primera frase.
 *
 *  - `alParcial(texto)`  — lo que va entendiendo de la frase en curso.
 *  - `alCerrar(texto)`   — una frase cerrada.
 *  - `alFallar(motivo)`  — el puente se ha caído a media llamada.
 */
export async function escucharConOido({ url, token, alParcial, alCerrar, alFallar, esperaMs = 6000 } = {}) {
  const Contexto = typeof window !== "undefined"
    ? (window.AudioContext || window.webkitAudioContext)
    : null;
  const medios = typeof navigator !== "undefined" ? navigator.mediaDevices : null;
  if (!url || !token || !Contexto || !medios?.getUserMedia || typeof WebSocket === "undefined") return null;

  let socket;
  try {
    socket = new WebSocket(url);
  } catch {
    return null;
  }
  const listo = await new Promise((resolver) => {
    const plazo = setTimeout(() => resolver(false), esperaMs);
    const acabar = (bien) => { clearTimeout(plazo); resolver(bien); };
    socket.onopen = () => {
      try { socket.send(JSON.stringify({ token })); } catch { acabar(false); }
    };
    socket.onmessage = (ev) => {
      try { acabar(JSON.parse(ev.data)?.tipo === "listo"); } catch { acabar(false); }
    };
    socket.onerror = () => acabar(false);
    socket.onclose = () => acabar(false);
  });
  if (!listo) {
    try { socket.close(); } catch { /* mejor esfuerzo */ }
    return null;
  }

  let stream, ctx, fuente, procesador, mudo;
  let vivo = true;

  function parar() {
    vivo = false;
    try { procesador?.disconnect(); } catch { /* mejor esfuerzo */ }
    try { mudo?.disconnect(); } catch { /* mejor esfuerzo */ }
    try { fuente?.disconnect(); } catch { /* mejor esfuerzo */ }
    try { stream?.getTracks().forEach(t => t.stop()); } catch { /* mejor esfuerzo */ }
    try { ctx?.close(); } catch { /* mejor esfuerzo */ }
    try { socket.close(); } catch { /* mejor esfuerzo */ }
  }

  try {
    // Las mismas ayudas que Scribe: `echoCancellation` es lo que deja el micro abierto
    // mientras Jarvis habla por el altavoz.
    stream = await medios.getUserMedia({
      audio: { echoCancellation: true, noiseSuppression: true, autoGainControl: true },
    });
    ctx = new Contexto({ sampleRate: MUESTREO });
    ctx.resume?.();
    fuente = ctx.createMediaStreamSource(stream);
    // ScriptProcessor y sumidero mudo por lo mismo que en vozScribe.js (ver allí).
    procesador = ctx.createScriptProcessor(BUFER, 1, 1);
    mudo = ctx.createGain();
    mudo.gain.value = 0;
  } catch {
    parar();
    return null;
  }

  const cortador = new CortadorDeFrases();
  let antes = [];   // las últimas tramas calladas: el principio de la frase

  function mandar(datos) {
    if (!vivo || socket.readyState !== 1) return;
    try { socket.send(datos); } catch { /* mejor esfuerzo: el socket se cerró bajo los pies */ }
  }

  procesador.onaudioprocess = (e) => {
    if (!vivo) return;
    const muestras = e.inputBuffer.getChannelData(0);
    let pcm;
    try { pcm = pcm16DesdeFloat32(muestras); } catch { return; }
    const decision = cortador.trama(rmsDe(muestras));
    if (decision === "callado") {
      antes.push(pcm);
      if (antes.length > cortador.prerrollTramas) antes.shift();
      return;
    }
    if (decision === "empieza") {
      antes.forEach(t => mandar(t.buffer));
      antes = [];
    }
    mandar(pcm.buffer);
    if (decision === "fin") mandar(JSON.stringify({ tipo: "fin" }));
  };
  fuente.connect(procesador);
  procesador.connect(mudo);
  mudo.connect(ctx.destination);

  socket.onmessage = (ev) => {
    if (!vivo) return;
    let msg;
    try { msg = JSON.parse(ev.data); } catch { return; }
    if (msg?.tipo === "parcial") {
      const texto = textoDeParcial(msg);
      if (texto) alParcial?.(texto);
    } else if (msg?.tipo === "final") {
      const texto = (msg.texto || "").trim();
      if (texto) alCerrar?.(texto);
    } else if (msg?.tipo === "error" && msg.detalle !== "mensaje_desconocido") {
      // «transcripcion» es una frase perdida, no el puente caído: jacobo sigue.
      if (msg.detalle === "transcripcion") return;
      parar();
      alFallar?.(String(msg.detalle || "error"));
    }
  };
  socket.onclose = () => {
    if (!vivo) return;
    parar();
    alFallar?.("se cerró la conexión con jacobo");
  };
  socket.onerror = () => {
    if (!vivo) return;
    parar();
    alFallar?.("no se pudo hablar con jacobo");
  };

  return { parar };
}
