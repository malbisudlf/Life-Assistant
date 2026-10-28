// Las manos de la vista J.A.R.V.I.S.: las manos que ve la cámara (hasta dos), dibujadas
// en grande sobre la pantalla como un holograma, y con cada una un cursor. El índice y el
// pulgar juntos (pellizco) pulsan lo que hay debajo; pellizcar sobre el título de un panel
// y mover la mano lo arrastra. Con las dos se pueden llevar dos paneles a la vez. Y
// cerrar el puño abre el menú de los proyectos alrededor de él (MenuRadial.jsx): aquí
// solo se avisa de que el puño se cierra, se mueve y se abre (`onPuno`).
//
// El seguimiento es MediaPipe (HandLandmarker) en el propio navegador: el vídeo no sale
// del equipo para esto. Su motor (WASM) y el modelo se bajan de su CDN la primera vez que
// se activan, y no antes: son unos megas que no tiene que pagar quien no use las manos.
// Las reglas —dónde apunta, cuándo pellizca, cuándo es un clic, el filtro del cursor—
// están en src/lib/gestos.js.
//
// Detectar y pintar van a ritmos distintos a propósito: MediaPipe corre a lo que dé la
// cámara (unos 30 fotogramas por segundo) y lo que se pinta se acerca a lo último visto en
// cada fotograma de la pantalla (60 o más). Atados, el cursor iba a saltos.
import { useEffect, useRef } from "react";
import {
  LectorDeMano, DetectorDePuno, HUESOS, aPantalla, esClic, acercar, claveDeMano, palmaEnPantalla,
} from "../../lib/gestos";

const VERSION_MEDIAPIPE = "0.10.35";   // la de package.json: el WASM tiene que casar
const WASM   = `https://cdn.jsdelivr.net/npm/@mediapipe/tasks-vision@${VERSION_MEDIAPIPE}/wasm`;
const MODELO = "https://storage.googleapis.com/mediapipe-models/hand_landmarker/hand_landmarker/float16/1/hand_landmarker.task";
const MAX_MANOS = 2;

// Lo que se puede pulsar con un pellizco. Lo demás (texto, fondos) no reacciona.
const PULSABLE = 'button:not(:disabled), a[href], input:not(:disabled), textarea, select, [role="button"]';
const PUNTAS = new Set([4, 8, 12, 16, 20]);
// Cuánto se acerca lo pintado a lo visto en cada fotograma de pantalla.
const ACERCA_CURSOR = 0.55;
const ACERCA_MANO = 0.6;

export default function Manos({ videoRef, activa, onArrastre, onEstado, onPuno }) {
  const lienzoRef = useRef(null);
  const cursoresRef = useRef([]);
  // Los callbacks cambian en cada render del HUD; el bucle de vídeo vive mucho más.
  const arrastreRef = useRef(onArrastre);
  const estadoRef = useRef(onEstado);
  const punoRef = useRef(onPuno);
  useEffect(() => { arrastreRef.current = onArrastre; estadoRef.current = onEstado; punoRef.current = onPuno; });

  useEffect(() => {
    if (!activa) return;
    let vivo = true;
    let detector = null;
    let raf = 0;
    let ultimoT = -1;
    let color = "#5ee7ff";
    let fotogramas = 0;
    // Una entrada por mano vista: { lector, hueco, pulsado, puntos, puntosPintados,
    // cursor, cursorPintado, pellizco, fuerza, encima }.
    const manos = new Map();
    let encimaAntes = new Set();
    estadoRef.current?.("cargando");

    function huecoLibre() {
      const usados = new Set([...manos.values()].map(m => m.hueco));
      for (let i = 0; i < MAX_MANOS; i++) if (!usados.has(i)) return i;
      return -1;
    }

    function soltar(clave, m, x, y) {
      if (!m.pulsado) return;
      const p = m.pulsado;
      m.pulsado = null;
      if (p.arrastre) {
        arrastreRef.current?.(p.arrastre, "suelta", { x, y }, clave);
        return;
      }
      if (p.objetivo && esClic({ movido: p.movido, ms: performance.now() - p.t0 })) {
        const el = p.objetivo;
        if (el.matches("input, textarea, select")) el.focus();
        else el.click();
        const cursor = cursoresRef.current[m.hueco];
        cursor?.classList.add("pulso");
        setTimeout(() => cursor?.classList.remove("pulso"), 260);
      }
    }

    // ── Detectar: una vez por fotograma de la cámara ──
    function detectar(resultado) {
      const ancho = window.innerWidth;
      const alto = window.innerHeight;
      const vistas = new Set();
      (resultado?.landmarks || []).slice(0, MAX_MANOS).forEach((puntos, i) => {
        const clave = claveDeMano(resultado.handedness, i);
        let m = manos.get(clave);
        if (!m) {
          const hueco = huecoLibre();
          if (hueco < 0) return;
          m = { lector: new LectorDeMano(), puno: new DetectorDePuno(), hueco, pulsado: null,
                puntosPintados: null, cursorPintado: null };
          manos.set(clave, m);
        }
        vistas.add(clave);
        m.puntos = puntos.map(q => aPantalla(q, ancho, alto));
        // El puño, antes que el pellizco: con el puño cerrado no se pulsa ni se arrastra.
        const palma = palmaEnPantalla(puntos, ancho, alto);
        const puno = m.puno.leer(puntos, performance.now());
        if (puno === "cierra") punoRef.current?.("cierra", palma, clave);
        else if (puno === "abre") punoRef.current?.("abre", palma, clave);
        else if (m.puno.cerrado) punoRef.current?.("mueve", palma, clave);
        m.cerrado = m.puno.cerrado;
        const r = m.lector.leer(puntos, ancho, alto, undefined, performance.now() / 1000);
        if (!r) return;
        m.cursor = { x: r.x, y: r.y };
        m.pellizco = r.pellizco;
        m.fuerza = r.fuerza;
        const bajo = document.elementFromPoint(r.x, r.y);
        const pulsable = bajo?.closest?.(PULSABLE) || null;
        m.encima = m.pulsado ? null : pulsable;
        if (r.cambio === "baja") {
          const asa = bajo?.closest?.("[data-arrastre]");
          m.pulsado = { x0: r.x, y0: r.y, t0: performance.now(), movido: 0,
                        arrastre: asa?.dataset.arrastre || null, objetivo: pulsable };
          if (m.pulsado.arrastre) arrastreRef.current?.(m.pulsado.arrastre, "empieza", { x: r.x, y: r.y }, clave);
        } else if (r.cambio === "sube") {
          soltar(clave, m, r.x, r.y);
        } else if (m.pulsado) {
          m.pulsado.movido = Math.max(m.pulsado.movido, Math.hypot(r.x - m.pulsado.x0, r.y - m.pulsado.y0));
          if (m.pulsado.arrastre) arrastreRef.current?.(m.pulsado.arrastre, "mueve", { x: r.x, y: r.y }, clave);
        }
      });
      // La que ya no se ve suelta lo que tuviera y deja su cursor libre.
      for (const [clave, m] of manos) {
        if (vistas.has(clave)) continue;
        if (m.lector.perdida() === "sube" || m.pulsado) soltar(clave, m, m.cursor?.x ?? 0, m.cursor?.y ?? 0);
        if (m.puno.perdida() === "abre") punoRef.current?.("perdida", m.cursor || { x: 0, y: 0 }, clave);
        const cursor = cursoresRef.current[m.hueco];
        if (cursor) cursor.style.opacity = "0";
        manos.delete(clave);
      }
      // Lo que tiene alguna mano encima, resaltado; lo demás, no. Con dos manos sobre el
      // mismo botón, que una se vaya no lo apaga.
      const encima = new Set([...manos.values()].map(m => m.encima).filter(Boolean));
      encimaAntes.forEach(el => { if (!encima.has(el)) el.classList.remove("jh-mano-encima"); });
      encima.forEach(el => el.classList.add("jh-mano-encima"));
      encimaAntes = encima;
    }

    // ── Pintar: una vez por fotograma de la pantalla ──
    function pintar() {
      const lienzo = lienzoRef.current;
      if (!lienzo) return;
      const ancho = window.innerWidth;
      const alto = window.innerHeight;
      const dpr = Math.min(2, window.devicePixelRatio || 1);
      if (lienzo.width !== Math.round(ancho * dpr) || lienzo.height !== Math.round(alto * dpr)) {
        lienzo.width = Math.round(ancho * dpr);
        lienzo.height = Math.round(alto * dpr);
      }
      // El color cambia con el estado del reactor; leerlo en cada fotograma cuesta un
      // recálculo de estilos, así que se lee de vez en cuando.
      if (fotogramas++ % 30 === 0) {
        color = getComputedStyle(lienzo).getPropertyValue("--jh-c").trim() || color;
      }
      const g = lienzo.getContext("2d");
      g.setTransform(dpr, 0, 0, dpr, 0, 0);
      g.clearRect(0, 0, ancho, alto);
      for (const m of manos.values()) {
        if (!m.puntos) continue;
        m.puntosPintados = m.puntosPintados
          ? m.puntosPintados.map((q, i) => acercar(q, m.puntos[i], ACERCA_MANO))
          : m.puntos;
        const p = m.puntosPintados;
        // Los huesos con resplandor y las articulaciones sin él: el `shadowBlur` es lo
        // caro de pintar, y en los puntos no se nota.
        g.lineCap = "round";
        g.strokeStyle = color;
        g.shadowColor = color;
        g.shadowBlur = 8;
        g.globalAlpha = 0.55;
        g.lineWidth = 3;
        g.beginPath();
        for (const [a, b] of HUESOS) { g.moveTo(p[a].x, p[a].y); g.lineTo(p[b].x, p[b].y); }
        g.stroke();
        g.shadowBlur = 0;
        g.globalAlpha = 0.9;
        g.fillStyle = color;
        g.beginPath();
        p.forEach((q, i) => {
          const r = PUNTAS.has(i) ? 6 : 3.5;
          g.moveTo(q.x + r, q.y);
          g.arc(q.x, q.y, r, 0, Math.PI * 2);
        });
        g.fill();
        g.globalAlpha = 1;

        const cursor = cursoresRef.current[m.hueco];
        if (cursor && m.cursor) {
          m.cursorPintado = acercar(m.cursorPintado, m.cursor, ACERCA_CURSOR);
          cursor.style.opacity = "1";
          cursor.style.transform = `translate3d(${m.cursorPintado.x}px, ${m.cursorPintado.y}px, 0)`;
          cursor.style.setProperty("--fuerza", (m.fuerza || 0).toFixed(2));
          cursor.classList.toggle("cerrado", Boolean(m.pellizco));
          cursor.classList.toggle("puno", Boolean(m.cerrado));
        }
      }
    }

    (async () => {
      try {
        const { FilesetResolver, HandLandmarker } = await import("@mediapipe/tasks-vision");
        const fileset = await FilesetResolver.forVisionTasks(WASM);
        detector = await HandLandmarker.createFromOptions(fileset, {
          baseOptions: { modelAssetPath: MODELO, delegate: "GPU" },
          runningMode: "VIDEO",
          numHands: MAX_MANOS,
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
            detectar(detector.detectForVideo(v, performance.now()));
          } catch { /* un fotograma raro no tumba el bucle */ }
        }
        pintar();
        raf = requestAnimationFrame(paso);
      };
      raf = requestAnimationFrame(paso);
    })();

    return () => {
      vivo = false;
      cancelAnimationFrame(raf);
      try { detector?.close(); } catch { /* ya cerrado */ }
      for (const [clave, m] of manos) {
        if (m.pulsado?.arrastre) arrastreRef.current?.(m.pulsado.arrastre, "suelta", { x: 0, y: 0 }, clave);
        if (m.puno.cerrado) punoRef.current?.("perdida", { x: 0, y: 0 }, clave);
      }
      encimaAntes.forEach(el => el.classList.remove("jh-mano-encima"));
      estadoRef.current?.("apagada");
    };
  }, [activa, videoRef]);

  if (!activa) return null;
  return (
    <>
      <canvas ref={lienzoRef} className="jh-manos-lienzo" aria-hidden="true" />
      {Array.from({ length: MAX_MANOS }, (_, i) => (
        <div key={i} ref={el => { cursoresRef.current[i] = el; }} className="jh-manos-cursor" aria-hidden="true"><span /></div>
      ))}
    </>
  );
}
