// Los paneles que Jarvis dibuja en su vista: «enséñame el sueño de dos semanas contra el
// HRV» y aparece ese panel. Jarvis solo deja la receta (`hud_panel` en el backend, de un
// catálogo cerrado); aquí se pinta y se mantiene vivo SIN modelo: cada panel pide sus
// datos a `/hud/datos` y los refresca solo.
//
// Nada de lo que escribe el modelo llega a ser marcado: el título es un nodo de texto y
// lo demás son números y filas que da el backend.
import { useEffect, useRef, useState } from "react";
import { API, authHeaders, apiFetch } from "../../lib/api";
import {
  REFRESCO_MS, barras, claveDatos, colocar, etiquetaDia, resumenSerie, textoValor, trazo,
} from "../../lib/hudPaneles";

const ANCHO = 220;
const ALTO  = 72;
const COLORES = ["var(--jh-c)", "var(--jh-amb)"];

/** Los datos de las fuentes de un panel, refrescados solos. `null` mientras llegan. */
function useDatos(panel) {
  const [datos, setDatos] = useState({});
  const claves = (panel.fuentes || []).map(f => claveDatos(f, panel)).join("#");
  const panelRef = useRef(panel);
  useEffect(() => { panelRef.current = panel; }, [panel]);

  useEffect(() => {
    let vivo = true;
    let reloj = null;
    async function pedir() {
      const p = panelRef.current;
      const nuevos = {};
      let cada = REFRESCO_MS.serie;
      await Promise.all((p.fuentes || []).map(async (fuente) => {
        const q = new URLSearchParams({ fuente, dias: String(p.dias || 14) });
        if (fuente === "trafico" && p.destino) q.set("destino", p.destino);
        try {
          const r = await apiFetch(`${API}/hud/datos?${q}`, { headers: authHeaders() });
          nuevos[fuente] = r.ok ? await r.json() : { fallo: true };
        } catch {
          nuevos[fuente] = { fallo: true };
        }
        cada = Math.min(cada, REFRESCO_MS[nuevos[fuente]?.clase] || REFRESCO_MS.serie);
      }));
      if (!vivo) return;
      setDatos(nuevos);
      reloj = setTimeout(pedir, cada);
    }
    pedir();
    return () => { vivo = false; clearTimeout(reloj); };
  }, [claves]);

  return datos;
}

function Serie({ series, tipo }) {
  const una = series.length === 1;
  return (
    <>
      <svg className="jh-vivo-grafica" viewBox={`0 0 ${ANCHO} ${ALTO}`} role="img"
           aria-label={series.map(s => s.nombre).join(" y ")}>
        <line x1="0" y1={ALTO - 1} x2={ANCHO} y2={ALTO - 1} className="jh-vivo-eje" />
        {series.map((s, i) => {
          if (tipo === "barras" && una) {
            return barras(s.puntos, ANCHO, ALTO).map(b => (
              <rect key={b.d} x={b.x} y={b.y} width={b.w} height={b.h} fill={COLORES[0]} opacity=".75">
                <title>{`${etiquetaDia(b.d)} · ${textoValor(b.v, s.unidad)}`}</title>
              </rect>
            ));
          }
          const cs = colocar(s.puntos, ANCHO, ALTO);
          return (
            <g key={s.nombre}>
              <path d={trazo(cs)} fill="none" stroke={COLORES[i]} strokeWidth="1.6" strokeLinejoin="round" />
              {cs.map(c => (
                <circle key={c.d} cx={c.x} cy={c.y} r="1.9" fill={COLORES[i]}>
                  <title>{`${etiquetaDia(c.d)} · ${textoValor(c.v, s.unidad)}`}</title>
                </circle>
              ))}
            </g>
          );
        })}
      </svg>
      <div className="jh-vivo-pie">
        {series.map((s, i) => {
          const r = resumenSerie(s.puntos);
          return (
            <div key={s.nombre} className="jh-vivo-leyenda">
              <span className="jh-vivo-punto" style={{ background: COLORES[i] }} />
              <span className="jh-vivo-nombre">{s.nombre}</span>
              <span className="jh-vivo-valor">{r ? textoValor(r.ultimo, s.unidad) : "sin datos"}</span>
              {r && r.n > 1 && <span className="jh-vivo-media">media {textoValor(Math.round(r.media * 100) / 100, s.unidad)}</span>}
            </div>
          );
        })}
      </div>
    </>
  );
}

/** Un panel dibujado por Jarvis. `asa` son las props de arrastre de la vista. */
export function PanelVivo({ panel, asa, onQuitar }) {
  const datos = useDatos(panel);
  const fuentes = panel.fuentes || [];
  const llegados = fuentes.map(f => datos[f]).filter(Boolean);
  const cargando = llegados.length < fuentes.length;
  const fallo = llegados.some(d => d.fallo);
  const primero = llegados[0];

  let cuerpo;
  if (cargando) cuerpo = <div className="jh-nota">Trayendo datos…</div>;
  else if (fallo) cuerpo = <div className="jh-nota">No he podido traer los datos</div>;
  else if (primero.clase === "lista") {
    cuerpo = primero.items?.length
      ? primero.items.map((it, i) => (
        <div key={`${it.a}-${i}`} className="jh-vivo-fila">
          <span className="jh-vivo-cuando">{it.a}</span><span className="jh-vivo-que">{it.b}</span>
        </div>
      ))
      : <div className="jh-nota">Nada en estos días</div>;
  } else if (primero.clase === "cifra" || panel.tipo === "cifra") {
    const valor = primero.clase === "cifra" ? primero.valor : resumenSerie(primero.puntos)?.ultimo;
    cuerpo = (
      <>
        <div className="jh-vivo-cifra">{textoValor(valor, primero.unidad)}</div>
        <div className="jh-nota">{primero.clase === "cifra" ? primero.nota : primero.nombre}</div>
      </>
    );
  } else {
    const series = llegados.filter(d => d.clase === "serie");
    cuerpo = series.some(s => s.puntos?.length)
      ? <Serie series={series} tipo={panel.tipo} />
      : <div className="jh-nota">Sin datos en estos días</div>;
  }

  return (
    <>
      <div className="jh-panel-titulo jh-asa" {...asa}>
        <span>{panel.titulo}</span>
        <button type="button" className="jh-mini jh-vivo-cerrar" onClick={onQuitar}
                aria-label={`Quitar el panel ${panel.titulo}`} title="Quitar el panel">×</button>
      </div>
      {cuerpo}
    </>
  );
}
