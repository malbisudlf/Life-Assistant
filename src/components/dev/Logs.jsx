// El registro persistente (tabla `app_logs`) con lo que hacía falta para leerlo de
// verdad: filtro por nivel y por fuente, búsqueda, el contexto entero de cada entrada y
// refresco en vivo mientras se prueba algo.
//
// El refresco automático se permite porque esta consulta va contra Supabase y no cuesta
// dinero. Es la regla de la zona dev (docs/ZONA_DEV.md): lo que acaba en OpenAI o
// ElevenLabs no se refresca solo, nunca.
import { useState, useEffect } from "react";

import { API, authHeaders, apiFetch } from "../../lib/api";
import { MONO, inputStyle, panelStyle, tituloStyle, horaCorta } from "../../lib/dev";
import { Boton, Vacio } from "./ui";

const NIVELES = ["", "DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"];

const COLOR_NIVEL = {
  CRITICAL: "#c9736b",
  ERROR:    "#c9736b",
  WARNING:  "var(--accent)",
  INFO:     "var(--muted)",
  DEBUG:    "var(--muted2)",
};

const REFRESCO_MS = 5_000;

export default function Logs() {
  const [nivel, setNivel]     = useState("");
  const [fuente, setFuente]   = useState("");
  const [buscar, setBuscar]   = useState("");
  const [dias, setDias]       = useState(7);
  const [datos, setDatos]     = useState(null);
  const [error, setError]     = useState(false);
  const [envivo, setEnVivo]   = useState(false);
  const [abierta, setAbierta] = useState(null);
  const [tic, setTic]         = useState(0);   // cada incremento, otra lectura

  // El texto de búsqueda se manda con retardo: escribir "whisper" son siete peticiones
  // si se manda por cada tecla.
  const [buscarDebounced, setBuscarDebounced] = useState("");
  useEffect(() => {
    const t = setTimeout(() => setBuscarDebounced(buscar.trim()), 350);
    return () => clearTimeout(t);
  }, [buscar]);

  // La lectura entera vive dentro del efecto y el estado se escribe DESPUÉS del await:
  // nada de setState síncrono en un efecto (docs/FRONTEND.md).
  useEffect(() => {
    let vivo = true;
    (async () => {
      const params = new URLSearchParams({ dias: String(dias), limite: "300" });
      if (nivel)           params.set("nivel", nivel);
      if (fuente)          params.set("fuente", fuente);
      if (buscarDebounced) params.set("buscar", buscarDebounced);
      try {
        const r = await apiFetch(`${API}/logs?${params}`, { headers: authHeaders() });
        if (!vivo) return;
        if (!r.ok) { setError(true); return; }
        const cuerpo = await r.json();
        if (!vivo) return;
        setDatos(cuerpo);
        setError(false);
      } catch { if (vivo) setError(true); }
    })();
    return () => { vivo = false; };
  }, [nivel, fuente, buscarDebounced, dias, tic]);

  // El intervalo se limpia al apagar el modo en vivo o al salir de la pestaña: sin eso,
  // el registro se seguiría pidiendo para siempre en segundo plano.
  useEffect(() => {
    if (!envivo) return undefined;
    const id = setInterval(() => setTic(t => t + 1), REFRESCO_MS);
    return () => clearInterval(id);
  }, [envivo]);

  async function vaciar() {
    if (!window.confirm("¿Vaciar el registro entero? Sirve para ver si un problema se reproduce.")) return;
    try {
      await apiFetch(`${API}/logs`, { method: "DELETE", headers: authHeaders() });
      setTic(t => t + 1);
    } catch { /* mejor esfuerzo */ }
  }

  const entradas = datos?.entradas || [];

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 12 }}>
      <div style={{ ...panelStyle, display: "flex", gap: 8, flexWrap: "wrap", alignItems: "flex-end" }}>
        <div>
          <div style={tituloStyle}>Nivel</div>
          <select value={nivel} onChange={e => setNivel(e.target.value)} style={inputStyle}>
            {NIVELES.map(n => <option key={n} value={n}>{n || "todos"}</option>)}
          </select>
        </div>
        <div>
          <div style={tituloStyle}>Fuente</div>
          <select value={fuente} onChange={e => setFuente(e.target.value)} style={inputStyle}>
            <option value="">todas</option>
            {(datos?.fuentes || []).map(f => <option key={f} value={f}>{f}</option>)}
          </select>
        </div>
        <div style={{ flex: 1, minWidth: 180 }}>
          <div style={tituloStyle}>Buscar en el mensaje</div>
          <input
            value={buscar}
            onChange={e => setBuscar(e.target.value)}
            placeholder="whisper, 409, upsert…"
            style={{ ...inputStyle, width: "100%" }}
          />
        </div>
        <div>
          <div style={tituloStyle}>Días</div>
          <select value={dias} onChange={e => setDias(Number(e.target.value))} style={inputStyle}>
            {[1, 7, 30, 90].map(d => <option key={d} value={d}>{d}</option>)}
          </select>
        </div>
        <Boton onClick={() => setTic(t => t + 1)}>Recargar</Boton>
        <Boton onClick={() => setEnVivo(v => !v)} tono={envivo ? "acento" : "normal"}
               title="Se refresca cada 5 s. Va contra Supabase: no cuesta dinero.">
          {envivo ? "● en vivo" : "en vivo"}
        </Boton>
        <Boton onClick={vaciar} tono="peligro">Vaciar</Boton>
      </div>

      <div style={{ display: "flex", gap: 14, fontSize: 11, color: "var(--muted2)", fontFamily: MONO }}>
        <span>{entradas.length} entradas</span>
        <span style={{ color: datos?.errores ? "#c9736b" : "var(--muted2)" }}>
          {datos?.errores || 0} errores
        </span>
      </div>

      <div style={{ ...panelStyle, padding: 0, overflowX: "auto" }}>
        {error && <Vacio>No se ha podido leer el registro.</Vacio>}
        {!error && datos === null && <Vacio>Cargando…</Vacio>}
        {!error && datos !== null && entradas.length === 0 && (
          <Vacio>Nada que enseñar con estos filtros. Que el registro esté vacío es una buena noticia.</Vacio>
        )}
        {entradas.map((e, i) => {
          const clave  = `${e.created_at}-${i}`;
          const activa = abierta === clave;
          const tieneContexto = e.context && Object.keys(e.context).length > 0;
          return (
            <div key={clave} style={{ borderBottom: "0.5px solid var(--border)" }}>
              <button
                type="button"
                onClick={() => setAbierta(activa ? null : clave)}
                style={{
                  display: "flex", gap: 12, alignItems: "baseline", width: "100%",
                  background: "transparent", border: 0, padding: "6px 14px", cursor: "pointer",
                  textAlign: "left", fontFamily: MONO, fontSize: 12, color: "var(--text)",
                }}
              >
                <span style={{ color: "var(--muted2)", flexShrink: 0 }}>{horaCorta(e.created_at)}</span>
                <span style={{ color: COLOR_NIVEL[e.level] || "var(--muted)", width: 62, flexShrink: 0 }}>
                  {e.level}
                </span>
                <span style={{ color: "var(--muted)", width: 110, flexShrink: 0, overflow: "hidden", textOverflow: "ellipsis" }}>
                  {e.source}
                </span>
                <span style={{
                  flex: 1, minWidth: 0,
                  whiteSpace: activa ? "pre-wrap" : "nowrap",
                  overflow: activa ? "visible" : "hidden",
                  textOverflow: "ellipsis",
                }}>
                  {e.message}
                </span>
                {tieneContexto && <span style={{ color: "var(--muted2)", flexShrink: 0 }}>{activa ? "▾" : "▸"}</span>}
              </button>
              {activa && tieneContexto && (
                <pre style={{
                  margin: "0 14px 12px 14px", padding: 10, background: "var(--surface2)",
                  border: "0.5px solid var(--border)", borderRadius: 6,
                  fontFamily: MONO, fontSize: 11, color: "var(--muted)",
                  overflowX: "auto", whiteSpace: "pre-wrap", wordBreak: "break-word",
                }}>
                  {JSON.stringify(e.context, null, 2)}
                </pre>
              )}
            </div>
          );
        })}
      </div>
    </div>
  );
}
