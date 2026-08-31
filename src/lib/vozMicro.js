// El micrófono mientras Jarvis habla: lo único que hace es decidir si le has cortado.
//
// Va aquí y no en Dashboard.jsx por lo mismo que vozEleven.js: no pinta nada, es un
// cliente de audio. Las reglas de "esto es voz y no un portazo" son puras y viven en
// voz.js (`detectorDeHabla`), para poder probarlas sin navegador.
//
// ── Por qué esto no es simplemente "dejar el micro abierto" ──────────────────────────
//
// El modo llamada CIERRA el micrófono mientras Jarvis habla, y no por ahorrar: por
// altavoz se oye a sí mismo, se transcribe y se contesta solo, en una llamada infinita
// que además cuesta dinero. Esa regla sigue en pie. Lo que se abre aquí no es el
// reconocimiento sino un medidor de energía: no transcribe nada, no manda nada a ningún
// sitio y no puede "entender" a Jarvis diciendo algo. Solo mide cuánto suena la sala.
//
// Y se abre y se cierra en cada turno a propósito, en vez de dejarlo puesto toda la
// llamada. Así NUNCA coexisten dos capturas del micrófono —esta y la del
// reconocimiento—, que es lo que se rompe en los WebView y en iOS. El permiso solo se
// pide la primera vez, así que reabrir cuesta milisegundos.

import { detectorDeHabla, rmsDeMuestras } from "./voz.js";

/** Vigila el micrófono y llama a `alHablar` la primera vez que decide que te has puesto
 *  a hablar encima. Devuelve `{ parar }`, o `null` si no se ha podido abrir el micro
 *  (permiso denegado, navegador sin `getUserMedia`, dispositivo ocupado).
 *
 *  Que devuelva `null` NO es un fallo que haya que anunciar: significa que esta llamada
 *  se queda sin barge-in y va por turnos, que es como funcionaba antes. Lo que no puede
 *  hacer nunca es tirar la llamada. */
export async function vigilarInterrupcion({ alHablar, umbral, msSostenidos, msGracia, msMuestra = 40 } = {}) {
  const Contexto = typeof window !== "undefined"
    ? (window.AudioContext || window.webkitAudioContext)
    : null;
  const medios = typeof navigator !== "undefined" ? navigator.mediaDevices : null;
  if (!Contexto || !medios?.getUserMedia || typeof alHablar !== "function") return null;

  let stream;
  try {
    // Las tres ayudas del navegador encendidas a propósito. `echoCancellation` es la que
    // sostiene todo esto: sin ella, la voz de Jarvis saliendo por el altavoz entra por el
    // micro con energía de sobra y se corta a sí mismo a la primera frase.
    stream = await medios.getUserMedia({
      audio: { echoCancellation: true, noiseSuppression: true, autoGainControl: true },
    });
  } catch {
    return null;   // sin micro no hay barge-in, y la llamada sigue por turnos
  }

  const ctx       = new Contexto();
  const analizador = ctx.createAnalyser();
  analizador.fftSize = 1024;
  // El micro NO se conecta a `ctx.destination`: se oiría a sí mismo por el altavoz, que
  // es exactamente el acople que este fichero existe para evitar.
  ctx.createMediaStreamSource(stream).connect(analizador);

  const detector = detectorDeHabla({ umbral, msSostenidos, msGracia });
  const flotante = new Float32Array(analizador.fftSize);
  const bytes    = new Uint8Array(analizador.fftSize);
  let reloj      = null;

  function parar() {
    if (reloj) { clearInterval(reloj); reloj = null; }
    try { stream.getTracks().forEach(t => t.stop()); } catch { /* mejor esfuerzo */ }
    try { ctx.close(); } catch { /* mejor esfuerzo */ }
  }

  function nivel() {
    // `getFloatTimeDomainData` no existe en los Safari viejos; ahí toca la versión en
    // bytes, donde el silencio es 128 y hay que recentrar.
    if (analizador.getFloatTimeDomainData) {
      analizador.getFloatTimeDomainData(flotante);
      return rmsDeMuestras(flotante);
    }
    analizador.getByteTimeDomainData(bytes);
    let suma = 0;
    for (let i = 0; i < bytes.length; i++) {
      const x = (bytes[i] - 128) / 128;
      suma += x * x;
    }
    return Math.sqrt(suma / bytes.length);
  }

  reloj = setInterval(() => {
    let rms;
    try { rms = nivel(); } catch { return; }   // el contexto se cerró bajo los pies
    if (!detector.mira(rms, Date.now())) return;
    // Se para ANTES de avisar: quien escucha va a abrir el reconocimiento, y dejar el
    // medidor puesto sería la segunda captura del micro que este fichero evita.
    parar();
    alHablar();
  }, msMuestra);

  return { parar };
}
