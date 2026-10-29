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
// cada fotograma de la pantalla (60 o más). Atados, el cursor iba a saltos. Por lo mismo,
// un panel cogido se mueve desde lo que se pinta y no desde lo que se ve: a 60 y suave.
//
// En el modo inmersivo (`inmersivo`) la cámara ocupa la pantalla entera y lo dibujado cae
// encima de la mano que se ve, sin margen. Ahí, además, **cada punta de cada dedo pulsa**
// como un botón de verdad: echándola hacia la pantalla (`DetectorDePulsaciones`). Cada
// punta lleva un anillo que se cierra según empuja, y lo que pulsaría va iluminado.
import { useEffect, useRef } from "react";
import {
  LectorDeMano, DetectorDePuno, DetectorDePulsaciones, HUESOS, aPantalla, esClic, acercar, claveDeMano,
  palmaEnPantalla,
} from "../../lib/gestos";

const VERSION_MEDIAPIPE = "0.10.35";   // la de package.json: el WASM tiene que casar
const WASM   = `https://cdn.jsdelivr.net/npm/@mediapipe/tasks-vision@${VERSION_MEDIAPIPE}/wasm`;
const MODELO = "https://storage.googleapis.com/mediapipe-models/hand_landmarker/hand_landmarker/float16/1/hand_landmarker.task";
const MAX_MANOS = 2;

// Lo que se puede pulsar con un pellizco. Lo demás (texto, fondos) no reacciona.
const PULSABLE = 'button:not(:disabled), a[href], input:not(:disabled), textarea, select, [role="button"]';
const PUNTAS = new Set([4, 8, 12, 16, 20]);
const PUNTAS_LISTA = [...PUNTAS];
// Cuánto se acerca lo pintado a lo visto en cada fotograma de pantalla.
const ACERCA_CURSOR = 0.55;
const ACERCA_MANO = 0.6;

// Lo que dura el círculo que deja un toque.
const ONDA_MS = 420;

/** El elemento pulsable bajo un punto de la pantalla, o null. */
function pulsableEn(x, y) {
  return document.elementFromPoint(x, y)?.closest?.(PULSABLE) || null;
}

function pulsar(el) {
  if (el.matches("input, textarea, select")) el.focus();
  else el.click();
}

export default function Manos({ videoRef, activa, inmersivo = false, onArrastre, onEstado, onPuno, onDelante }) {
  const lienzoRef = useRef(null);
  const cursoresRef = useRef([]);
  // Los callbacks cambian en cada render del HUD; el bucle de vídeo vive mucho más.
  const arrastreRef = useRef(onArrastre);
  const estadoRef = useRef(onEstado);
  const punoRef = useRef(onPuno);
  const delanteRef = useRef(onDelante);
  const inmersivoRef = useRef(inmersivo);
  useEffect(() => {
    arrastreRef.current = onArrastre; estadoRef.current = onEstado; punoRef.current = onPuno;
    delanteRef.current = onDelante; inmersivoRef.current = inmersivo;
  });

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
    // Los círculos de los toques: { x, y, t }.
    let ondas = [];
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
        pulsar(p.objetivo);
        const cursor = cursoresRef.current[m.hueco];
        cursor?.classList.add("pulso");
        setTimeout(() => cursor?.classList.remove("pulso"), 260);
      }
    }

    // El encuadre: en el modo inmersivo, encima del vídeo que se ve a pantalla completa.
    function encuadre() {
      const v = videoRef.current;
      return inmersivoRef.current && v?.videoWidth
        ? { cubre: { ancho: v.videoWidth, alto: v.videoHeight } }
        : undefined;
    }

    /** Un toque con la punta de un dedo: lo de debajo se pulsa y, si es un panel, se trae
     *  delante. */
    function tocar(punto) {
      ondas.push({ x: punto.x, y: punto.y, t: performance.now() });
      const el = pulsableEn(punto.x, punto.y);
      if (el) { pulsar(el); return; }
      const panel = document.elementFromPoint(punto.x, punto.y)?.closest?.("[data-panel]");
      if (panel) delanteRef.current?.(panel.dataset.panel);
    }

    // ── Detectar: una vez por fotograma de la cámara ──
    function detectar(resultado) {
      const ancho = window.innerWidth;
      const alto = window.innerHeight;
      const opciones = encuadre();
      const ahora = performance.now();
      const vistas = new Set();
      (resultado?.landmarks || []).slice(0, MAX_MANOS).forEach((puntos, i) => {
        const clave = claveDeMano(resultado.handedness, i);
        let m = manos.get(clave);
        if (!m) {
          const hueco = huecoLibre();
          if (hueco < 0) return;
          m = { lector: new LectorDeMano(), puno: new DetectorDePuno(), pulsador: new DetectorDePulsaciones(),
                hueco, pulsado: null, puntosPintados: null, cursorPintado: null, puntas: [] };
          manos.set(clave, m);
        }
        vistas.add(clave);
        m.clave = clave;
        m.puntos = puntos.map(q => aPantalla(q, ancho, alto, opciones));
        // El puño, antes que el pellizco: con el puño cerrado no se pulsa ni se arrastra.
        const palma = palmaEnPantalla(puntos, ancho, alto, opciones);
        const puno = m.puno.leer(puntos, performance.now());
        if (puno === "cierra") punoRef.current?.("cierra", palma, clave);
        else if (puno === "abre") punoRef.current?.("abre", palma, clave);
        else if (m.puno.cerrado) punoRef.current?.("mueve", palma, clave);
        m.cerrado = m.puno.cerrado;
        const r = m.lector.leer(puntos, ancho, alto, opciones, ahora / 1000);
        if (!r) return;
        m.cursor = { x: r.x, y: r.y };
        m.pellizco = r.pellizco;
        m.fuerza = r.fuerza;
        const bajo = document.elementFromPoint(r.x, r.y);
        const pulsable = bajo?.closest?.(PULSABLE) || null;
        m.encima = m.pulsado ? null : pulsable;
        if (r.cambio === "baja") {
          // Pellizcar sobre un botón es pulsarlo; sobre el resto de un panel, cogerlo.
          const panelBajo = bajo?.closest?.("[data-arrastre]")?.dataset.arrastre || null;
          // Con la otra mano sujetando un panel, pellizcar ese mismo panel —aunque sea
          // encima de un botón— o en el vacío lo coge también, y con las dos se
          // redimensiona. En el vacío porque un panel pequeño no da sitio a dos manos.
          const otra = [...manos.values()].find(o => o !== m && o.pulsado?.arrastre)?.pulsado.arrastre || null;
          const aLaPinza = otra && (panelBajo === otra || (!panelBajo && !pulsable));
          const arrastre = aLaPinza ? otra : (pulsable ? null : panelBajo);
          const desde = m.cursorPintado || { x: r.x, y: r.y };
          m.pulsado = { x0: r.x, y0: r.y, t0: ahora, movido: 0,
                        arrastre, objetivo: aLaPinza ? null : pulsable };
          if (m.pulsado.arrastre) arrastreRef.current?.(m.pulsado.arrastre, "empieza", desde, clave);
        } else if (r.cambio === "sube") {
          soltar(clave, m, m.cursorPintado?.x ?? r.x, m.cursorPintado?.y ?? r.y);
        } else if (m.pulsado) {
          m.pulsado.movido = Math.max(m.pulsado.movido, Math.hypot(r.x - m.pulsado.x0, r.y - m.pulsado.y0));
        }

        // Las cinco puntas, solo en el modo inmersivo y con la mano libre: pellizcando o
        // con el puño cerrado las puntas se mueven sin querer pulsar nada.
        if (!inmersivoRef.current) { m.puntas = []; return; }
        m.puntas = PUNTAS_LISTA.map(i => m.puntos[i]);
        if (m.pellizco || m.cerrado || m.pulsado) { m.pulsador.pausa(); return; }
        for (const toque of m.pulsador.leer(puntos, ahora)) tocar(aPantalla(toque.punto, ancho, alto, opciones));
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
      // En el modo inmersivo se ilumina también lo que tiene una punta encima: es lo que
      // pulsaría ese dedo al empujarlo.
      for (const m of manos.values()) {
        for (const q of m.puntas || []) {
          const el = q && pulsableEn(q.x, q.y);
          if (el) encima.add(el);
        }
      }
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
      // Con la mano de verdad a la vista, el holograma va más fino para no taparla.
      const inm = inmersivoRef.current;
      const ahora = performance.now();
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
        g.globalAlpha = inm ? 0.35 : 0.55;
        g.lineWidth = inm ? 2 : 3;
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
        // Las puntas que pulsan, con su retícula: un anillo que se ve sobre cualquier fondo
        // y que se cierra y se rellena según la punta empuja hacia la pantalla, como un
        // botón que se hunde. Cerrado del todo, ha pulsado.
        if (inm) {
          const progreso = m.pulsador?.progreso || [];
          g.lineWidth = 2;
          g.shadowBlur = 10;
          PUNTAS_LISTA.forEach((i, k) => {
            const f = progreso[k] || 0;
            const radio = 13 - f * 6;
            g.globalAlpha = 0.95;
            g.beginPath();
            g.arc(p[i].x, p[i].y, radio, 0, Math.PI * 2);
            g.stroke();
            if (f > 0.05) {
              g.globalAlpha = 0.25 + f * 0.55;
              g.fill();
            }
          });
          g.shadowBlur = 0;
        }
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
        // Un panel cogido va con lo pintado, no con lo visto: así se mueve a 60 y suave.
        if (m.pulsado?.arrastre && m.cursorPintado) {
          arrastreRef.current?.(m.pulsado.arrastre, "mueve", m.cursorPintado, m.clave);
        }
      }
      // Las dos manos sobre el mismo panel: la línea que las une es lo que se estira.
      const enPinza = [...manos.values()].filter(m => m.pulsado?.arrastre && m.cursorPintado);
      if (enPinza.length === 2 && enPinza[0].pulsado.arrastre === enPinza[1].pulsado.arrastre) {
        const [a, b] = enPinza.map(m => m.cursorPintado);
        g.globalAlpha = 0.8;
        g.strokeStyle = color;
        g.lineWidth = 2;
        g.setLineDash([6, 6]);
        g.beginPath();
        g.moveTo(a.x, a.y);
        g.lineTo(b.x, b.y);
        g.stroke();
        g.setLineDash([]);
        g.globalAlpha = 1;
      }
      // Los círculos de los toques se abren y se apagan.
      ondas = ondas.filter(o => ahora - o.t < ONDA_MS);
      for (const o of ondas) {
        const f = (ahora - o.t) / ONDA_MS;
        g.globalAlpha = 1 - f;
        g.strokeStyle = color;
        g.lineWidth = 3 * (1 - f) + 1;
        g.beginPath();
        g.arc(o.x, o.y, 14 + f * 34, 0, Math.PI * 2);
        g.stroke();
      }
      g.globalAlpha = 1;
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
