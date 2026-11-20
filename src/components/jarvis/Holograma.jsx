// La casa en holograma: la maqueta 3D de la casa, planta a planta, dentro de un panel de la
// vista J.A.R.V.I.S. (fuente `casa` del HUD). Las habitaciones con luz brillan, la presencia
// late, y tocar una habitación enciende o apaga sus luces. Es CSS 3D (perspectiva y
// `preserve-3d`), sin motor gráfico: son unas pocas cajas y así no hay dependencia nueva.
//
// Se gira arrastrando la escena con el ratón (o con los botones, que se pulsan también con
// un pellizco), se elige planta, y ⤢ la abre en grande. Las habitaciones de los demás
// llegan como «privado» y no se pueden tocar. La lógica pura está en src/lib/holograma.js.
import { useRef, useState } from "react";
import { createPortal } from "react-dom";
import {
  GIRO_INICIAL, SEPARACION_PISOS, alTocar, claseArea, girar, planoPiso, resumenArea, resumenCasa,
} from "../../lib/holograma";

function Maqueta({ pisos, giro, planta, elegida, onElegir, onTocar, grande }) {
  const lado = grande ? 420 : 190;
  const separacion = SEPARACION_PISOS * (grande ? 2 : 1);
  return (
    <div className="jh-holo-mundo" style={{ width: lado, height: lado,
      transform: `rotateX(${giro.x}deg) rotateZ(${giro.z}deg)` }}>
      {pisos.map((p, i) => {
        const fuera = planta !== null && p.nivel !== planta;
        return (
          <div key={p.id} className={`jh-holo-piso${fuera ? " fuera" : ""}`}
               style={{ transform: `translateZ(${(i - (pisos.length - 1) / 2) * separacion}px)` }}>
            <span className="jh-holo-planta">{p.nombre}</span>
            {planoPiso(p.areas).map(a => {
              const accion = alTocar(a);
              return (
                <button key={a.id} type="button" disabled={fuera}
                        className={`jh-holo-hab ${claseArea(a)}${elegida === a.id ? " elegida" : ""}${a.presencia ? " gente" : ""}`}
                        style={{ left: `${a.x}%`, top: `${a.y}%`, width: `${a.w}%`, height: `${a.h}%` }}
                        aria-label={`${a.nombre}: ${resumenArea(a)}${accion ? (accion.encender ? ". Tocar enciende" : ". Tocar apaga") : ""}`}
                        onMouseEnter={() => onElegir(a.id)} onFocus={() => onElegir(a.id)}
                        onClick={() => { onElegir(a.id); if (accion) onTocar(a, accion.encender); }}>
                  <span className="jh-holo-nombre">{a.privado ? "Privado" : a.nombre}</span>
                  {a.presencia && <span className="jh-holo-latido" aria-hidden="true" />}
                </button>
              );
            })}
          </div>
        );
      })}
    </div>
  );
}

/** La maqueta con sus mandos. `datos` es lo de `/hud/datos?fuente=casa`; `onTocar(area,
 *  encender)` manda la orden. */
export function Holograma({ datos, onTocar }) {
  const [giro, setGiro] = useState(GIRO_INICIAL);
  const [planta, setPlanta] = useState(null);
  const [elegida, setElegida] = useState(null);
  const [grande, setGrande] = useState(false);
  const arrastre = useRef(null);

  if (!datos?.ok) return <div className="jh-nota">{datos?.motivo || "Sin datos de la casa"}</div>;
  const pisos = datos.pisos || [];
  const todas = pisos.flatMap(p => p.areas || []);
  const area = todas.find(a => a.id === elegida);
  const total = resumenCasa(pisos);

  const escena = {
    onPointerDown: (e) => {
      if (e.button !== 0 || e.target.closest("button")) return;
      arrastre.current = { x: e.clientX, y: e.clientY, giro };
      e.currentTarget.setPointerCapture?.(e.pointerId);
    },
    onPointerMove: (e) => {
      const a = arrastre.current;
      if (a) setGiro(girar(a.giro, e.clientX - a.x, e.clientY - a.y));
    },
    onPointerUp: () => { arrastre.current = null; },
    onPointerCancel: () => { arrastre.current = null; },
  };

  const mandos = (
    <div className="jh-holo-mandos">
      <button type="button" className="jh-mini" onClick={() => setGiro(g => girar(g, -60, 0))} aria-label="Girar a la izquierda">⟲</button>
      <button type="button" className="jh-mini" onClick={() => setGiro(g => girar(g, 60, 0))} aria-label="Girar a la derecha">⟳</button>
      <button type="button" className={`jh-mini${planta === null ? " activo" : ""}`} onClick={() => setPlanta(null)}>Todas</button>
      {pisos.map(p => (
        <button key={p.id} type="button" className={`jh-mini${planta === p.nivel ? " activo" : ""}`}
                onClick={() => setPlanta(v => (v === p.nivel ? null : p.nivel))} aria-label={p.nombre}>
          {p.nivel}
        </button>
      ))}
      <button type="button" className="jh-mini" onClick={() => setGrande(v => !v)}
              aria-label={grande ? "Cerrar la maqueta grande" : "Abrir la maqueta en grande"}>{grande ? "×" : "⤢"}</button>
    </div>
  );

  const vista = (
    <>
      <div className={`jh-holo-escena${grande ? " grande" : ""}`} {...escena}>
        <Maqueta pisos={pisos} giro={giro} planta={planta} elegida={elegida} grande={grande}
                 onElegir={setElegida} onTocar={onTocar} />
      </div>
      {mandos}
      <div className="jh-holo-info" aria-live="polite">
        {area ? <><b>{area.privado ? "Privado" : area.nombre}</b> · {resumenArea(area)}</>
          : `${total.luces} luces encendidas · ${total.gente ? `alguien en ${total.gente}` : "nadie a la vista"}`}
      </div>
    </>
  );

  if (grande) {
    return (
      <>
        <div className="jh-nota">Abierta en grande.</div>
        {mandos}
        {/* Dentro de la vista (`.jh`) y no en <body>: de ahí salen sus colores. */}
        {createPortal(
          <div className="jh-holo-capa" role="dialog" aria-label="La casa en grande"
               onKeyDown={e => { if (e.key === "Escape") setGrande(false); }}>
            {vista}
          </div>, document.querySelector(".jh") || document.body)}
      </>
    );
  }
  return vista;
}
