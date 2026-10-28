// La cámara de la vista J.A.R.V.I.S.: el vídeo en directo, el fotograma que viaja con
// cada mensaje cuando «Jarvis ve» está encendido, y la fuente de las manos (Manos.jsx).
//
// Una sola captura de la cámara para las tres cosas: pedirla dos veces abre dos veces el
// dispositivo, y en algunos portátiles la segunda falla. Se apaga al desactivarla y al
// cerrar la vista: una cámara encendida sin que se vea es justo lo que no puede pasar,
// por eso su panel (Camara.jsx) lleva siempre el «EN DIRECTO» en rojo.
import { useCallback, useEffect, useRef, useState } from "react";

// Lo que viaja al backend: lo bastante para ver gestos, ropa o lo que se enseña, y
// pequeño (unos 40-80 KB en JPEG) para no frenar el turno.
const ANCHO_FOTOGRAMA = 640;
const CALIDAD_FOTOGRAMA = 0.72;

/** Abre la cámara mientras `activa` y devuelve la referencia del <video>, en qué estado
 *  está y `capturar()`, que da el fotograma actual en base64 (sin el prefijo data:). */
export function useCamara(activa) {
  const videoRef = useRef(null);
  const [estado, setEstado] = useState("pidiendo");   // pidiendo | en_directo | error
  const [error, setError]   = useState("");

  useEffect(() => {
    if (!activa) return;
    const video = videoRef.current;
    let stream = null;
    let cancelado = false;
    const medios = navigator.mediaDevices;
    if (!medios?.getUserMedia) {
      Promise.resolve().then(() => { setEstado("error"); setError("Este navegador no da acceso a la cámara"); });
      return;
    }
    medios.getUserMedia({ video: { width: { ideal: 1280 }, height: { ideal: 720 }, facingMode: "user" }, audio: false })
      .then((s) => {
        if (cancelado) { s.getTracks().forEach(t => t.stop()); return; }
        stream = s;
        if (video) {
          video.srcObject = s;
          video.play?.()?.catch?.(() => { /* autoplay silenciado: el vídeo arranca igual */ });
        }
        setError("");
        setEstado("en_directo");
      })
      .catch((e) => {
        if (cancelado) return;
        setEstado("error");
        setError(e?.name === "NotAllowedError" ? "Permiso de cámara denegado"
          : e?.name === "NotFoundError" ? "No hay ninguna cámara" : "No se ha podido abrir la cámara");
      });
    return () => {
      cancelado = true;
      stream?.getTracks().forEach(t => t.stop());
      if (video) video.srcObject = null;
      setEstado("pidiendo");
    };
  }, [activa]);

  const capturar = useCallback(() => {
    const v = videoRef.current;
    if (!v || v.readyState < 2 || !v.videoWidth) return "";
    const alto = Math.round((v.videoHeight * ANCHO_FOTOGRAMA) / v.videoWidth);
    const lienzo = document.createElement("canvas");
    lienzo.width = ANCHO_FOTOGRAMA;
    lienzo.height = alto;
    try {
      lienzo.getContext("2d").drawImage(v, 0, 0, ANCHO_FOTOGRAMA, alto);
      return lienzo.toDataURL("image/jpeg", CALIDAD_FOTOGRAMA).split(",")[1] || "";
    } catch {
      return "";
    }
  }, []);

  return { videoRef, estado: activa ? estado : "apagada", error, capturar };
}
