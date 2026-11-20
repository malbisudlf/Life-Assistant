// Los paneles que Jarvis dibuja en su vista: «enséñame el sueño de dos semanas contra el
// HRV» y aparece ese panel. Jarvis solo deja la receta (`hud_panel` en el backend, de un
// catálogo cerrado); aquí se pinta y se mantiene vivo SIN modelo: cada panel pide sus
// datos a `/hud/datos` y los refresca solo.
//
// Nada de lo que escribe el modelo llega a ser marcado: el título es un nodo de texto y
// lo demás son números y filas que da el backend.
import { useCallback, useEffect, useRef, useState } from "react";
import { API, authHeaders, jsonHeaders, apiFetch } from "../../lib/api";
import { trasTocar } from "../../lib/holograma";
import { Holograma } from "./Holograma";
import {
  ICONO_DIA, REFRESCO_MS, abanico, barras, claveDatos, colocar, etiquetaDia, eurosCortos,
  resumenSerie, textoValor, trazo,
} from "../../lib/hudPaneles";

const ANCHO = 220;
const ALTO  = 72;
const COLORES = ["var(--jh-c)", "var(--jh-amb)"];

/** Los datos de las fuentes de un panel, refrescados solos. `null` mientras llegan. */
function useDatos(panel) {
  const [datos, setDatos] = useState({});
  const [vuelta, setVuelta] = useState(0);
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
        if (p.param) q.set("param", p.param);
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
  }, [claves, vuelta]);

  const recargar = useCallback(() => setVuelta(v => v + 1), []);
  return { datos, setDatos, recargar };
}

/** La maqueta de la casa, con lo de tocar: la habitación cambia en el acto (lo que se ve
 *  mientras la orden viaja) y se vuelve a preguntar a la casa al poco. */
function Casa({ datos, setDatos, recargar }) {
  const tocar = useCallback(async (area, encender) => {
    setDatos(d => ({
      ...d,
      casa: { ...d.casa, pisos: (d.casa?.pisos || []).map(p => ({
        ...p, areas: p.areas.map(a => (a.id === area.id ? trasTocar(a, encender) : a)) })) },
    }));
    try {
      await apiFetch(`${API}/casa/holograma/luces`, {
        method: "POST", headers: jsonHeaders(), body: JSON.stringify({ area: area.id, encender }),
      });
    } catch { /* lo dirá la siguiente lectura */ }
    setTimeout(recargar, 1200);
  }, [setDatos, recargar]);
  return <Holograma datos={datos} onTocar={tocar} />;
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

/** La línea de un día (`dia_reconstruir`): las cifras del cuerpo arriba y, debajo, todo lo
 *  que pasó por horas, cada cosa con su marca. */
function Dia({ datos }) {
  return (
    <>
      <div className="jh-nota jh-dia-nombre">{datos.nombre}</div>
      {datos.cifras?.length > 0 && (
        <div className="jh-dia-cifras">
          {datos.cifras.map(c => (
            <div key={c.n} className="jh-dia-cifra">
              <span className="jh-dia-valor">{textoValor(c.v, c.u)}</span>
              <span className="jh-dia-etiqueta">{c.n}</span>
            </div>
          ))}
        </div>
      )}
      <div className="jh-dia-linea">
        {datos.items?.length
          ? datos.items.map((it, i) => (
            <div key={`${it.a}-${i}`} className={`jh-dia-fila jh-dia-${it.k}`}>
              <span className="jh-vivo-cuando">{it.a}</span>
              <span className="jh-dia-marca" aria-hidden="true">{ICONO_DIA[it.k] || "·"}</span>
              <span className="jh-vivo-que">{it.b}</span>
            </div>
          ))
          : <div className="jh-nota">De ese día no hay nada guardado</div>}
      </div>
      {datos.nota && <div className="jh-nota">{datos.nota}</div>}
    </>
  );
}

const ALTO_ABANICO = 96;

/** El abanico de una simulación (`simular_finanzas`): del malo (p10) al bueno (p90), la
 *  mediana encima y, si hay gasto, la mediana sin él en discontinua. */
function Abanico({ datos }) {
  const a = abanico(datos.puntos, ANCHO, ALTO_ABANICO);
  if (!a) return <div className="jh-nota">{datos.nota || "Sin datos"}</div>;
  const puntos = datos.puntos || [];
  return (
    <>
      <svg className="jh-vivo-grafica" viewBox={`0 0 ${ANCHO} ${ALTO_ABANICO}`} role="img"
           aria-label={`Simulación hasta ${a.ultimo.d}: mediana ${eurosCortos(a.ultimo.p50)}`}>
        <path d={a.banda} fill="var(--jh-c)" opacity=".16" />
        {a.cero !== null && <line x1="0" x2={ANCHO} y1={a.cero} y2={a.cero} className="jh-abanico-cero" />}
        {a.base && <path d={a.base} fill="none" stroke="var(--jh-amb)" strokeWidth="1.4" strokeDasharray="4 3" />}
        <path d={a.mediana} fill="none" stroke="var(--jh-c)" strokeWidth="1.8" strokeLinejoin="round" />
        <text x="2" y="10" className="jh-abanico-eje">{eurosCortos(a.max)}</text>
        <text x="2" y={ALTO_ABANICO - 2} className="jh-abanico-eje">{eurosCortos(a.min)}</text>
      </svg>
      <div className="jh-abanico-anos">
        <span>{puntos[0]?.d}</span><span>{a.ultimo.d}</span>
      </div>
      <div className="jh-vivo-pie">
        <div className="jh-vivo-leyenda">
          <span className="jh-vivo-punto" style={{ background: "var(--jh-c)" }} />
          <span className="jh-vivo-nombre">Mediana</span>
          <span className="jh-vivo-valor">{eurosCortos(a.ultimo.p50)}</span>
          <span className="jh-vivo-media">{eurosCortos(a.ultimo.p10)} – {eurosCortos(a.ultimo.p90)}</span>
        </div>
        {a.base && (
          <div className="jh-vivo-leyenda">
            <span className="jh-vivo-punto" style={{ background: "var(--jh-amb)" }} />
            <span className="jh-vivo-nombre">Sin el gasto</span>
            <span className="jh-vivo-valor">{eurosCortos(a.ultimo.base)}</span>
          </div>
        )}
      </div>
      <div className="jh-nota">{datos.nombre} · {datos.nota}</div>
    </>
  );
}

/** Un panel dibujado por Jarvis. `asa` son las props de arrastre de la vista. */
export function PanelVivo({ panel, asa, onQuitar }) {
  const { datos, setDatos, recargar } = useDatos(panel);
  const fuentes = panel.fuentes || [];
  const llegados = fuentes.map(f => datos[f]).filter(Boolean);
  const cargando = llegados.length < fuentes.length;
  const fallo = llegados.some(d => d.fallo);
  const primero = llegados[0];

  let cuerpo;
  if (cargando) cuerpo = <div className="jh-nota">Trayendo datos…</div>;
  else if (fallo) cuerpo = <div className="jh-nota">No he podido traer los datos</div>;
  else if (primero.clase === "dia") cuerpo = <Dia datos={primero} />;
  else if (primero.clase === "abanico") cuerpo = <Abanico datos={primero} />;
  else if (primero.clase === "casa") cuerpo = <Casa datos={primero} setDatos={setDatos} recargar={recargar} />;
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
