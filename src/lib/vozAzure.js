// La voz de Jarvis por Azure Speech: pide el audio al backend y lo reproduce.
//
// Hermano de vozEleven.js y con la MISMA interfaz a propósito (`decir`, `callar`,
// `cerrar`), para que el modo llamada pueda usar una u otra sin enterarse de cuál tiene
// delante. Lo que cambia es de dónde sale el sonido, y ahí las dos son opuestas:
// ElevenLabs habla directamente con el navegador por WebSocket y aquí el audio viene del
// backend, una petición por frase. El porqué está en backend/main.py, en el banner de
// Azure Speech — en corto: el backend ya está caliente cuando hay algo que decir, Fly y
// el recurso de Azure están los dos en París, y así no hay ni SDK que meter en el bundle
// ni protocolo propietario que hablar.
//
// Este fichero NO sabe de red ni de autenticación: recibe `pedirAudio` y lo llama. Así
// se puede probar sin navegador y sin backend, que es la mitad de la razón de que viva
// en src/lib/ y no dentro de Dashboard.jsx.

import { textoParaVoz } from "./voz.js";

/** Abre la voz. Devuelve `{ decir, callar, cerrar }`, o `null` si el navegador no puede.
 *
 *  - `pedirAudio(texto, señal)` → Promise<ArrayBuffer> con el MP3 de esa frase. La
 *    `señal` es un AbortSignal: al cortar a Jarvis se aborta lo que estuviera pedido y
 *    no se paga —ni se espera— audio que ya no viene a cuento.
 *  - `alFallar(sinDecir)` recibe TODO lo que se quedó sin decir, cada frase con su
 *    `alFinal`, para que quien la abrió lo diga con la voz del navegador. */
export function abrirVozAzure({ pedirAudio, alFallar }) {
  const Contexto = typeof window !== "undefined"
    ? (window.AudioContext || window.webkitAudioContext)
    : null;
  if (!Contexto || typeof pedirAudio !== "function") return null;

  const ctx    = new Contexto();
  const salida = ctx.createGain();
  salida.connect(ctx.destination);

  // Frases esperando turno: [texto, alFinal]. Se dicen de una en una y en orden — dos a
  // la vez sonarían solapadas, que es peor que esperar.
  const cola      = [];
  let sonando     = false;   // hay una frase en el aire (pedida, decodificando o sonando)
  let muerto      = false;   // esta voz ya no vale: lo siguiente se cae al navegador YA
  let cerrado     = false;
  let fuentes     = new Set();
  let finProgramado = 0;
  // Lo pedido por adelantado: {texto, promesa}. Mientras suena una frase se va pidiendo
  // la siguiente, que es lo que quita el silencio entre frase y frase — sin esto cada
  // una espera a que termine la anterior para ni siquiera empezar a pedirse.
  let adelantado  = null;
  let abortos     = new Set();

  function pedir(texto) {
    const control = new AbortController();
    abortos.add(control);
    return pedirAudio(texto, control.signal)
      .finally(() => abortos.delete(control));
  }

  /** Lo que se quedó sin decir, incluido lo que sonaba. A partir de aquí la voz muere. */
  function rendirse(loDeAhora) {
    const sinDecir = loDeAhora ? [loDeAhora] : [];
    sinDecir.push(...cola);
    cola.length = 0;
    adelantado  = null;
    muerto      = true;
    sonando     = false;
    if (!sinDecir.length) return;
    if (alFallar) { try { alFallar(sinDecir); return; } catch { /* abajo */ } }
    for (const [, avisar] of sinDecir) {
      try { avisar?.(); } catch { /* mejor esfuerzo */ }
    }
  }

  async function siguiente() {
    if (sonando || muerto || cerrado) return;
    const turno = cola.shift();
    if (!turno) return;
    const [texto, alFinal] = turno;
    sonando = true;

    let audio;
    try {
      // Si ya se había pedido por adelantado, aquí no se espera a la red: el audio lleva
      // rato viajando mientras sonaba la frase anterior.
      audio = await (adelantado && adelantado.texto === texto
        ? adelantado.promesa
        : pedir(texto));
    } catch {
      // Cortar a Jarvis aborta las peticiones en vuelo, y eso NO es un fallo de la voz:
      // es lo que se pedía. Sin esta comprobación, hablarle encima la mataba y el resto
      // de la llamada salía por el altavoz del navegador.
      adelantado = null;
      sonando = false;
      if (cerrado || muerto) return;
      rendirse([texto, alFinal]);
      return;
    }
    adelantado = null;
    if (cerrado || muerto) return;

    let buffer;
    try {
      buffer = await ctx.decodeAudioData(audio.slice(0));
    } catch {
      // Un MP3 que no decodifica es un turno mudo, y mudo es el fallo que no se ve.
      sonando = false;
      rendirse([texto, alFinal]);
      return;
    }
    if (cerrado || muerto) return;

    // iOS suspende el AudioContext en cuanto puede; reanudarlo aquí cubre que lo haya
    // hecho a media llamada, no solo al abrirla.
    if (ctx.state === "suspended") ctx.resume().catch(() => {});

    const fuente = ctx.createBufferSource();
    fuente.buffer = buffer;
    fuente.connect(salida);
    // Un pelín por delante del reloj: programar en `currentTime` exacto llega tarde y el
    // trozo se pierde. Cada frase se encadena al final de la anterior.
    const inicio = Math.max(ctx.currentTime + 0.06, finProgramado);
    fuente.start(inicio);
    finProgramado = inicio + buffer.duration;
    fuentes.add(fuente);

    // Y ya que esta suena, se va pidiendo la siguiente.
    if (cola.length) {
      const [proximo] = cola[0];
      adelantado = { texto: proximo, promesa: pedir(proximo) };
      // Un fallo aquí se recoge cuando le toque el turno, no ahora: sin este `catch` el
      // navegador lo cuenta como promesa rechazada sin capturar.
      adelantado.promesa.catch(() => {});
    }

    fuente.onended = () => {
      fuentes.delete(fuente);
      sonando = false;
      try { alFinal?.(); } catch { /* mejor esfuerzo */ }
      siguiente();
    };
  }

  return {
    /** Dice un texto entero. `alFinal` se llama SIEMPRE, suene o no: el modo llamada
     *  encadena la escucha con él, y un camino que no avisara dejaría la llamada colgada
     *  en silencio esperando a alguien que ya no va a hablar. */
    decir(texto, alFinal) {
      const dicho = textoParaVoz(texto);
      if (!dicho) { try { alFinal?.(); } catch { /* mejor esfuerzo */ } return; }
      if (muerto || cerrado) {
        if (alFallar) { try { alFallar([[dicho, alFinal]]); return; } catch { /* abajo */ } }
        try { alFinal?.(); } catch { /* mejor esfuerzo */ }
        return;
      }
      // Se ENCOLA, no se pisa: un turno son varias frases seguidas y la segunda no puede
      // cortar a la primera. Para cortar de verdad está `callar`.
      cola.push([dicho, alFinal]);
      siguiente();
    },

    /** Calla AHORA: corta lo que suena, aborta lo pedido y tira lo que esperaba. Es el
     *  barge-in. Lo cancelado no vuelve: si te has puesto a hablar encima, lo que Jarvis
     *  tenía preparado ya no viene a cuento. */
    callar() {
      for (const c of abortos) { try { c.abort(); } catch { /* ya estaba */ } }
      abortos = new Set();
      for (const f of fuentes) { try { f.onended = null; f.stop(); } catch { /* ya paró */ } }
      fuentes = new Set();
      cola.length   = 0;
      adelantado    = null;
      finProgramado = 0;
      sonando       = false;
    },

    cerrar() {
      // El orden importa: `cerrado` primero, para que lo que esté a medio camino no
      // intente seguir ni se tome el corte por una caída que hay que rescatar.
      cerrado = true;
      this.callar();
      try { ctx.close(); } catch { /* mejor esfuerzo */ }
    },
  };
}
