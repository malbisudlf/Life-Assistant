// Las manos de la vista J.A.R.V.I.S.: la mano que ve la cámara, dibujada en grande sobre
// la pantalla como un holograma, y con ella un cursor. El índice y el pulgar juntos
// (pellizco) pulsan lo que hay debajo; pellizcar sobre el título de un panel y mover la
// mano lo arrastra.
//
// El seguimiento es MediaPipe (HandLandmarker) en el propio navegador: el vídeo no sale
// del equipo para esto. Su motor (WASM) y el modelo se bajan de su CDN la primera vez que
// se activan, y no antes: son unos megas que no tiene que pagar quien no use las manos.
// Las reglas —dónde apunta, cuándo pellizca, cuándo es un clic— están en src/lib/gestos.js.
import { useEffect, useRef } from "react";
import { LectorDeMano, HUESOS, aPantalla, esClic } from "../../lib/gestos";

const VERSION_MEDIAPIPE = "0.10.35";   // la de package.json: el WASM tiene que casar
const WASM   = `https://cdn.jsdelivr.net/npm/@mediapipe/tasks-vision@${VERSION_MEDIAPIPE}/wasm`;
const MODELO = "https://storage.googleapis.com/mediapipe-models/hand_landmarker/hand_landmarker/float16/1/hand_landmarker.task";

// Lo que se puede pulsar con un pellizco. Lo demás (texto, fondos) no reacciona.
const PULSABLE = 'button:not(:disabled), a[href], input:not(:disabled), textarea, select, [role="button"]';
const PUNTAS = new Set([4, 8, 12, 16, 20]);

export default function Manos({ videoRef, activa, onArrastre, onEstado }) {
  const lienzoRef = useRef(null);
  const cursorRef = useRef(null);
  // Los callbacks cambian en cada render del HUD; el bucle de vídeo vive mucho más.
  const arrastreRef = useRef(onArrastre);
  const estadoRef = useRef(onEstado);
  useEffect(() => { arrastreRef.current = onArrastre; estadoRef.current = onEstado; });

  useEffect(() => {
    if (!activa) return;
    let vivo = true;
    let detector = null;
    let raf = 0;
    let ultimoT = -1;
    let pulsado = null;   // { x0, y0, t0, movido, arrastre, objetivo }
    let encima = null;
    const lector = new LectorDeMano();
    estadoRef.current?.("cargando");

    function marcarEncima(el) {
      if (el === encima) return;
      encima?.classList.remove("jh-mano-encima");
      encima = el;
      encima?.classList.add("jh-mano-encima");
    }

    function soltar(x, y) {
      if (!pulsado) return;
      const p = pulsado;
      pulsado = null;
      if (p.arrastre) {
        arrastreRef.current?.(p.arrastre, "suelta", { x, y });
        return;
      }
      if (p.objetivo && esClic({ movido: p.movido, ms: performance.now() - p.t0 })) {
        const el = p.objetivo;
        if (el.matches("input, textarea, select")) el.focus();
        else el.click();
        cursorRef.current?.classList.add("pulso");
        setTimeout(() => cursorRef.current?.classList.remove("pulso"), 260);
      }
    }

    function dibujar(puntos, ancho, alto) {
      const lienzo = lienzoRef.current;
      if (!lienzo) return;
      const dpr = window.devicePixelRatio || 1;
      if (lienzo.width !== Math.round(ancho * dpr)) {
        lienzo.width = Math.round(ancho * dpr);
        lienzo.height = Math.round(alto * dpr);
      }
      const g = lienzo.getContext("2d");
      g.setTransform(dpr, 0, 0, dpr, 0, 0);
      g.clearRect(0, 0, ancho, alto);
      if (!puntos) return;
      const p = puntos.map(q => aPantalla(q, ancho, alto));
      const color = getComputedStyle(lienzo).getPropertyValue("--jh-c").trim() || "#5ee7ff";
      g.lineCap = "round";
      g.shadowColor = color;
      g.shadowBlur = 14;
      g.strokeStyle = color;
      g.globalAlpha = 0.55;
      g.lineWidth = 3;
      g.beginPath();
      for (const [a, b] of HUESOS) { g.moveTo(p[a].x, p[a].y); g.lineTo(p[b].x, p[b].y); }
      g.stroke();
      g.globalAlpha = 0.9;
      g.fillStyle = color;
      p.forEach((q, i) => {
        g.beginPath();
        g.arc(q.x, q.y, PUNTAS.has(i) ? 6 : 3.5, 0, Math.PI * 2);
        g.fill();
      });
      g.globalAlpha = 1;
    }

    function procesar(puntos) {
      const ancho = window.innerWidth;
      const alto = window.innerHeight;
      dibujar(puntos, ancho, alto);
      const cursor = cursorRef.current;
      if (!puntos) {
        if (lector.perdida() === "sube") soltar(0, 0);
        marcarEncima(null);
        if (cursor) cursor.style.opacity = "0";
        return;
      }
      const r = lector.leer(puntos, ancho, alto);
      if (!r) return;
      if (cursor) {
        cursor.style.opacity = "1";
        cursor.style.transform = `translate(${r.x}px, ${r.y}px)`;
        cursor.style.setProperty("--fuerza", r.fuerza.toFixed(2));
        cursor.classList.toggle("cerrado", r.pellizco);
      }
      const bajo = document.elementFromPoint(r.x, r.y);
      const pulsable = bajo?.closest?.(PULSABLE) || null;
      if (!pulsado) marcarEncima(pulsable);
      if (r.cambio === "baja") {
        const asa = bajo?.closest?.("[data-arrastre]");
        pulsado = { x0: r.x, y0: r.y, t0: performance.now(), movido: 0,
                    arrastre: asa?.dataset.arrastre || null, objetivo: pulsable };
        if (pulsado.arrastre) arrastreRef.current?.(pulsado.arrastre, "empieza", { x: r.x, y: r.y });
      } else if (r.cambio === "sube") {
        soltar(r.x, r.y);
      } else if (pulsado) {
        pulsado.movido = Math.max(pulsado.movido, Math.hypot(r.x - pulsado.x0, r.y - pulsado.y0));
        if (pulsado.arrastre) arrastreRef.current?.(pulsado.arrastre, "mueve", { x: r.x, y: r.y });
      }
    }

    (async () => {
      try {
        const { FilesetResolver, HandLandmarker } = await import("@mediapipe/tasks-vision");
        const fileset = await FilesetResolver.forVisionTasks(WASM);
        detector = await HandLandmarker.createFromOptions(fileset, {
          baseOptions: { modelAssetPath: MODELO, delegate: "GPU" },
          runningMode: "VIDEO",
          numHands: 1,
        });
      } catch {
        if (vivo) estadoRef.current?.("error");
        return;
      }
      if (!vivo) { detector.close(); return; }
      estadoRef.current?.("activa");
      const paso = () => {
        if (!vivo) return;
        const v = videoRef.current;
        if (v && v.readyState >= 2 && v.currentTime !== ultimoT) {
          ultimoT = v.currentTime;
          try {
            procesar(detector.detectForVideo(v, performance.now()).landmarks?.[0] || null);
          } catch { /* un fotograma raro no tumba el bucle */ }
        }
        raf = requestAnimationFrame(paso);
      };
      raf = requestAnimationFrame(paso);
    })();

    return () => {
      vivo = false;
      cancelAnimationFrame(raf);
      try { detector?.close(); } catch { /* ya cerrado */ }
      if (pulsado?.arrastre) arrastreRef.current?.(pulsado.arrastre, "suelta", { x: 0, y: 0 });
      marcarEncima(null);
      estadoRef.current?.("apagada");
    };
  }, [activa, videoRef]);

  if (!activa) return null;
  return (
    <>
      <canvas ref={lienzoRef} className="jh-manos-lienzo" aria-hidden="true" />
      <div ref={cursorRef} className="jh-manos-cursor" aria-hidden="true"><span /></div>
    </>
  );
}
