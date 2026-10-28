// El menú del puño: al cerrar el puño sale un círculo grande a su alrededor y de él, las
// burbujas de los proyectos (las que están en marcha primero) y una de «+ Nuevo». Se
// elige moviendo el puño hacia una y abriendo la mano; o, con el menú abierto, pulsando
// una burbuja con un pellizco o con el ratón, porque son botones de verdad.
//
// Dónde va cada burbuja y cuál se elige con el movimiento lo decide src/lib/gestos.js
// (`posicionesRadiales`, `elegirPorDireccion`); qué proyectos y cómo se llaman,
// src/lib/proyectos.js.
import { porcentajeDe } from "../../lib/gestos";
import { ESTADOS, nombreCorto } from "../../lib/proyectos";

/** `centro`: dónde se cerró el puño (ya metido en pantalla). `items`: lo que sale en las
 *  burbujas, en orden. `elegido`: el índice que señala el puño, o -1. */
export default function MenuRadial({ centro, items, posiciones, elegido, onElegir, onCerrar, sujeto }) {
  if (!centro) return null;
  return (
    <div className={`jh-radial${sujeto ? " sujeto" : ""}`} role="menu" aria-label="Proyectos"
         style={{ "--cx": `${centro.x}px`, "--cy": `${centro.y}px` }}>
      <svg className="jh-radial-radios" aria-hidden="true">
        {posiciones.map((p, i) => (
          <line key={i} x1={centro.x} y1={centro.y} x2={centro.x + p.x} y2={centro.y + p.y}
                className={i === elegido ? "elegido" : ""} />
        ))}
      </svg>
      <button type="button" className="jh-radial-nucleo" style={{ left: centro.x, top: centro.y }}
              onClick={onCerrar} aria-label="Cerrar el menú de proyectos">
        <span className="jh-radial-anillo" />
        <span className="jh-radial-anillo dos" />
        <span className="jh-radial-titulo">Proyectos</span>
        <span className="jh-radial-cuenta">
          {sujeto ? "Mueva el puño y abra la mano" : "Pulse uno · aquí para cerrar"}
        </span>
      </button>
      {items.map((item, i) => {
        const p = posiciones[i];
        const pct = item.id === "nuevo" ? null : porcentajeDe(item.progreso);
        return (
          <button key={item.id} type="button" role="menuitem"
                  className={`jh-burbuja${i === elegido ? " elegida" : ""}${item.id === "nuevo" ? " nueva" : ""} e-${item.estado || ""}`}
                  style={{ left: centro.x + p.x, top: centro.y + p.y, "--dx": `${-p.x}px`, "--dy": `${-p.y}px`,
                           "--pct": pct ?? 0, animationDelay: `${i * 40}ms` }}
                  onClick={() => onElegir(item.id)}>
            {pct != null && <span className="jh-burbuja-progreso" aria-hidden="true" />}
            <span className="jh-burbuja-nombre">{item.id === "nuevo" ? "+ Nuevo" : nombreCorto(item)}</span>
            {item.id !== "nuevo" && (
              <span className="jh-burbuja-estado">
                {ESTADOS[item.estado] || item.estado || ""}
                {pct != null && <span className="jh-burbuja-pct">{pct} %</span>}
              </span>
            )}
          </button>
        );
      })}
    </div>
  );
}
