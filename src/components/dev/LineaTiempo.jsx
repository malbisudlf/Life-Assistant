// Todo lo que pasó un día, en un solo hilo y por orden.
//
// Es la pestaña que contesta "¿y qué pasó justo antes de que se rompiera?". Hasta aquí esa
// respuesta estaba repartida en seis tablas de Supabase que no se pueden cruzar sin
// ordenarlas a mano, y el orden —lo único que hace falta para entender una avería— no lo
// tenía nadie.
//
// El refresco automático solo se enciende mirando HOY: un día pasado no cambia, y refrescar
// el pasado es gastar peticiones para volver a pintar lo mismo.
import { useState, useEffect, useCallback } from "react";

import { MONO, panelStyle, COLOR_TONO, horaCorta,
         CARRILES, diaLocal, diaDesplazado, leerLinea, resumenLinea } from "../../lib/dev";
import { Boton, Vacio } from "./ui";

const REFRESCO_MS = 20_000;

export default function LineaTiempo() {
  const [dia, setDia]         = useState(() => diaLocal());
  const [datos, setDatos]     = useState(null);
  const [error, setError]     = useState("");
  const [leyendo, setLeyendo] = useState(true);
  const [ocultos, setOcultos] = useState([]);   // carriles apagados
  const [tic, setTic]         = useState(0);

  useEffect(() => {
    let vivo = true;
    (async () => {
      try {
        const d = await leerLinea(dia);
        if (vivo) { setDatos(d); setError(""); }
      } catch (e) {
        if (vivo) { setDatos(null); setError(e.message || "no se pudo consultar"); }
      } finally {
        if (vivo) setLeyendo(false);
      }
    })();
    return () => { vivo = false; };
  }, [dia, tic]);

  const esHoy = dia === diaLocal();
  useEffect(() => {
    if (!esHoy) return undefined;
    const id = setInterval(() => setTic(t => t + 1), REFRESCO_MS);
    return () => clearInterval(id);
  }, [esHoy]);

  const mover = useCallback((dias) => {
    setLeyendo(true);
    setDia(d => diaDesplazado(d, dias));
  }, []);

  function alternar(carril) {
    setOcultos(o => (o.includes(carril) ? o.filter(c => c !== carril) : [...o, carril]));
  }

  const resumen  = resumenLinea(datos);
  const eventos  = (datos?.eventos || []).filter(e => !ocultos.includes(e.carril));
  const porCarril = {};
  for (const e of datos?.eventos || []) porCarril[e.carril] = (porCarril[e.carril] || 0) + 1;

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 12 }}>
      <div style={{ ...panelStyle, display: "flex", gap: 10, alignItems: "center", flexWrap: "wrap" }}>
        <Boton onClick={() => mover(-1)} title="El día anterior">←</Boton>
        <span style={{ fontFamily: MONO, fontSize: 13, color: "var(--text)", minWidth: 96, textAlign: "center" }}>
          {dia}
        </span>
        <Boton onClick={() => mover(1)} disabled={esHoy} title="El día siguiente">→</Boton>
        {!esHoy && <Boton onClick={() => { setLeyendo(true); setDia(diaLocal()); }}>hoy</Boton>}

        <span style={{ display: "flex", alignItems: "center", gap: 7, flex: 1, minWidth: 140 }}>
          <span style={{ width: 7, height: 7, borderRadius: "50%", background: COLOR_TONO[resumen.tono] }} />
          <span style={{ fontSize: 11, color: "var(--muted)" }}>{resumen.texto}</span>
        </span>

        {esHoy && (
          <span style={{ fontSize: 10, color: "var(--muted2)" }}>
            se refresca solo cada 20 s
          </span>
        )}
        <Boton onClick={() => { setLeyendo(true); setTic(t => t + 1); }} disabled={leyendo}>
          {leyendo ? "Mirando…" : "Actualizar"}
        </Boton>
      </div>

      <div style={{ display: "flex", gap: 6, flexWrap: "wrap" }}>
        {CARRILES.map(c => {
          const apagado = ocultos.includes(c.id);
          return (
            <button
              key={c.id}
              type="button"
              onClick={() => alternar(c.id)}
              title={apagado ? "Enseñar este carril" : "Ocultar este carril"}
              style={{
                background: "transparent", cursor: "pointer", borderRadius: 6,
                border: "0.5px solid var(--border2)", padding: "4px 9px",
                fontSize: 11, fontFamily: MONO,
                color: apagado ? "var(--muted2)" : "var(--muted)",
                opacity: apagado ? 0.45 : 1,
              }}
            >
              {c.etiqueta} {porCarril[c.id] || 0}
            </button>
          );
        })}
      </div>

      {!!datos?.sin_leer?.length && (
        <div style={{ ...panelStyle, borderColor: "rgba(212,100,90,0.35)", fontSize: 11, color: "#d4645a" }}>
          No se ha podido leer: {datos.sin_leer.join(", ")}. Lo que falta abajo puede no ser
          que no pasara nada, sino que no se sabe.
        </div>
      )}

      <div style={{ ...panelStyle, padding: 0 }}>
        {error && <Vacio>No se pudo consultar: {error}</Vacio>}
        {!error && leyendo && datos === null && <Vacio>Cargando…</Vacio>}
        {!error && !leyendo && !eventos.length && (
          <Vacio>
            {datos?.total
              ? "Todos los carriles de este día están ocultos."
              : "Ese día no pasó nada de lo que aquí se mira."}
          </Vacio>
        )}

        {eventos.map((e, i) => (
          <div
            key={`${e.cuando}-${i}`}
            style={{
              display: "flex", gap: 10, alignItems: "baseline",
              padding: "6px 14px", borderBottom: "0.5px solid var(--border)",
              fontFamily: MONO, fontSize: 12,
            }}
          >
            <span style={{ color: "var(--muted2)", flexShrink: 0 }}>{horaCorta(e.cuando)}</span>
            <span style={{ width: 7, height: 7, borderRadius: "50%", flexShrink: 0,
                           alignSelf: "center", background: COLOR_TONO[e.tono] }} />
            <span style={{ color: "var(--muted2)", width: 74, flexShrink: 0, fontSize: 10,
                           overflow: "hidden", textOverflow: "ellipsis" }}>
              {e.carril}
            </span>
            <span style={{ color: "var(--text)", flexShrink: 0, maxWidth: 260,
                           overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
              {e.titulo}
            </span>
            <span style={{ color: "var(--muted)", flex: 1, minWidth: 0,
                           overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
              {e.detalle}
            </span>
            {e.extra && (
              <span style={{ color: "var(--muted2)", fontSize: 10, flexShrink: 0 }}>{e.extra}</span>
            )}
          </div>
        ))}
      </div>

      <div style={{ fontSize: 10, color: "var(--muted2)" }}>
        {datos?.recortado
          ? `Se enseñan los últimos ${eventos.length} de ${datos.total}: lo último que pasó es lo que se está mirando.`
          : "El registro solo guarda avisos y errores, así que un día sin filas de registro es un día bueno."}
        {!!datos?.sin_hora && ` · ${datos.sin_hora} fila(s) sin hora, que no se pueden colocar aquí.`}
      </div>
    </div>
  );
}
