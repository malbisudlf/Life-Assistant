// La checklist de ideas del proyecto (tabla `ideas_dev`, ver docs/ZONA_DEV.md).
//
// La forma la copia docs/IDEAS.md, que es como ya se piensan aquí las ideas: el qué, el
// PORQUÉ —la parte que no se puede reconstruir tres meses después— y por dónde se
// empieza. Pero se crea con solo el título y Enter: la idea que hay que rellenar entera
// para poder guardarla acaba no guardándose.
import { useState, useEffect } from "react";

import { API, authHeaders, jsonHeaders, apiFetch } from "../../lib/api";
import { MONO, inputStyle, panelStyle, tituloStyle, desdeHace } from "../../lib/dev";
import { Boton, Vacio } from "./ui";

const ESTADOS = [
  { id: "pendiente",  etiqueta: "Pendiente",  color: "var(--accent)" },
  { id: "en_curso",   etiqueta: "En curso",   color: "var(--accent2)" },
  { id: "hecha",      etiqueta: "Hecha",      color: "var(--green)" },
  { id: "descartada", etiqueta: "Descartada", color: "var(--muted2)" },
];

const ESFUERZOS = [
  { valor: 1, punto: "●",   texto: "una tarde" },
  { valor: 2, punto: "●●",  texto: "medio" },
  { valor: 3, punto: "●●●", texto: "grande, o con partes fuera del código" },
];

function colorEstado(estado) {
  return (ESTADOS.find(e => e.id === estado) || ESTADOS[0]).color;
}

export default function Ideas() {
  const [ideas, setIdeas]       = useState(null);   // null = todavía no se ha leído
  const [error, setError]       = useState(false);
  const [titulo, setTitulo]     = useState("");
  const [guardando, setGuardando] = useState(false);
  const [filtro, setFiltro]     = useState("vivas");
  const [abierta, setAbierta]   = useState(null);
  const [tic, setTic]           = useState(0);   // cada incremento, otra lectura

  // El estado se escribe DESPUÉS del await: nada de setState síncrono dentro de un
  // efecto (regla react-hooks del proyecto, ver docs/FRONTEND.md).
  useEffect(() => {
    let vivo = true;
    (async () => {
      try {
        const r = await apiFetch(`${API}/dev/ideas`, { headers: authHeaders() });
        if (!vivo) return;
        if (!r.ok) { setError(true); return; }
        const cuerpo = await r.json();
        if (!vivo) return;
        setIdeas(cuerpo.ideas || []);
        setError(false);
      } catch {
        if (vivo) setError(true);
      }
    })();
    return () => { vivo = false; };
  }, [tic]);

  const recargar = () => setTic(t => t + 1);

  async function crear() {
    const limpio = titulo.trim();
    if (!limpio || guardando) return;
    setGuardando(true);
    try {
      const r = await apiFetch(`${API}/dev/ideas`, {
        method: "POST", headers: jsonHeaders(), body: JSON.stringify({ titulo: limpio }),
      });
      if (r.ok) {
        const { idea } = await r.json();
        // Se antepone en local en vez de recargar la lista entera: escribir cuatro ideas
        // seguidas es lo normal aquí, y cada recarga sería un parpadeo.
        setIdeas(prev => [idea, ...(prev || [])]);
        setTitulo("");
      }
    } catch { /* mejor esfuerzo: el campo mantiene el texto y se puede reintentar */ }
    setGuardando(false);
  }

  async function actualizar(id, cambios) {
    // Optimista: el cambio se pinta ya y se corrige con lo que devuelva el backend. Un
    // desplegable de estado que tarda medio segundo en moverse se pulsa dos veces.
    setIdeas(prev => (prev || []).map(i => (i.id === id ? { ...i, ...cambios } : i)));
    try {
      const r = await apiFetch(`${API}/dev/ideas/${id}`, {
        method: "PATCH", headers: jsonHeaders(), body: JSON.stringify(cambios),
      });
      if (r.ok) {
        const { idea } = await r.json();
        setIdeas(prev => (prev || []).map(i => (i.id === id ? idea : i)));
      } else {
        recargar();
      }
    } catch { recargar(); }
  }

  async function borrar(id) {
    setIdeas(prev => (prev || []).filter(i => i.id !== id));
    try {
      await apiFetch(`${API}/dev/ideas/${id}`, { method: "DELETE", headers: authHeaders() });
    } catch { recargar(); }
  }

  const lista = (ideas || []).filter(i => {
    if (filtro === "todas") return true;
    if (filtro === "vivas") return i.estado === "pendiente" || i.estado === "en_curso";
    return i.estado === filtro;
  });

  const cuentas = ESTADOS.map(e => ({
    ...e, n: (ideas || []).filter(i => i.estado === e.id).length,
  }));

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 14 }}>
      <div style={panelStyle}>
        <div style={tituloStyle}>Apuntar una idea</div>
        <div style={{ display: "flex", gap: 8 }}>
          <input
            value={titulo}
            onChange={e => setTitulo(e.target.value)}
            onKeyDown={e => { if (e.key === "Enter") crear(); }}
            placeholder="Qué hay que hacer — Enter para guardar, el porqué se rellena luego"
            style={{ ...inputStyle, flex: 1 }}
          />
          <Boton onClick={crear} disabled={!titulo.trim() || guardando} tono="acento">
            Añadir
          </Boton>
        </div>
      </div>

      <div style={{ display: "flex", gap: 6, flexWrap: "wrap", alignItems: "center" }}>
        {[{ id: "vivas", etiqueta: "Vivas" }, ...ESTADOS, { id: "todas", etiqueta: "Todas" }].map(f => (
          <button
            key={f.id}
            type="button"
            onClick={() => setFiltro(f.id)}
            style={{
              padding: "4px 10px", borderRadius: 20, fontSize: 11, cursor: "pointer",
              fontFamily: "'DM Sans', sans-serif",
              background: filtro === f.id ? "rgba(200,169,110,0.12)" : "transparent",
              border: "0.5px solid",
              borderColor: filtro === f.id ? "rgba(200,169,110,0.35)" : "var(--border)",
              color: filtro === f.id ? "var(--accent)" : "var(--muted)",
            }}
          >
            {f.etiqueta}
            {cuentas.find(c => c.id === f.id) && (
              <span style={{ marginLeft: 6, fontFamily: MONO, color: "var(--muted2)" }}>
                {cuentas.find(c => c.id === f.id).n}
              </span>
            )}
          </button>
        ))}
      </div>

      <div style={{ ...panelStyle, padding: 0 }}>
        {error && <Vacio>No se ha podido leer la lista. ¿Está aplicada la migración <code>20260909_ideas_dev</code>?</Vacio>}
        {!error && ideas === null && <Vacio>Cargando…</Vacio>}
        {!error && ideas !== null && lista.length === 0 && (
          <Vacio>Nada por aquí. Escribe arriba lo primero que se te ocurra.</Vacio>
        )}
        {lista.map(idea => (
          <Fila
            key={idea.id}
            idea={idea}
            abierta={abierta === idea.id}
            onAbrir={() => setAbierta(abierta === idea.id ? null : idea.id)}
            onCambiar={cambios => actualizar(idea.id, cambios)}
            onBorrar={() => borrar(idea.id)}
          />
        ))}
      </div>
    </div>
  );
}

function Fila({ idea, abierta, onAbrir, onCambiar, onBorrar }) {
  const tachada = idea.estado === "hecha" || idea.estado === "descartada";
  return (
    <div style={{ borderBottom: "0.5px solid var(--border)" }}>
      <div style={{ display: "flex", alignItems: "center", gap: 10, padding: "9px 14px" }}>
        <span style={{
          width: 6, height: 6, borderRadius: "50%", flexShrink: 0,
          background: colorEstado(idea.estado),
        }} />
        <button
          type="button"
          onClick={onAbrir}
          style={{
            flex: 1, textAlign: "left", background: "transparent", border: 0, padding: 0,
            cursor: "pointer", fontSize: 13, fontFamily: "'DM Sans', sans-serif",
            color: tachada ? "var(--muted2)" : "var(--text)",
            textDecoration: idea.estado === "descartada" ? "line-through" : "none",
          }}
        >
          {idea.titulo}
        </button>
        {idea.area && (
          <span style={{ fontSize: 10, color: "var(--muted2)", fontFamily: MONO }}>{idea.area}</span>
        )}
        <span title={idea.esfuerzo ? ESFUERZOS[idea.esfuerzo - 1].texto : "esfuerzo sin estimar"}
              style={{ fontSize: 9, color: "var(--accent)", width: 26, textAlign: "right" }}>
          {idea.esfuerzo ? ESFUERZOS[idea.esfuerzo - 1].punto : ""}
        </span>
        <select
          value={idea.estado}
          onChange={e => onCambiar({ estado: e.target.value })}
          style={{ ...inputStyle, padding: "3px 6px", fontSize: 11, color: colorEstado(idea.estado) }}
        >
          {ESTADOS.map(e => <option key={e.id} value={e.id}>{e.etiqueta}</option>)}
        </select>
      </div>

      {abierta && (
        <div style={{ padding: "4px 14px 14px 30px", display: "flex", flexDirection: "column", gap: 10 }}>
          <Campo
            etiqueta="Por qué"
            valor={idea.porque}
            placeholder="La parte que no se puede reconstruir dentro de tres meses"
            onGuardar={v => onCambiar({ porque: v })}
          />
          <Campo
            etiqueta="Por dónde se empieza"
            valor={idea.por_donde}
            placeholder="El primer paso concreto: qué fichero, qué endpoint"
            onGuardar={v => onCambiar({ por_donde: v })}
          />
          <div style={{ display: "flex", gap: 14, alignItems: "flex-end", flexWrap: "wrap" }}>
            <div>
              <div style={tituloStyle}>Esfuerzo</div>
              <div style={{ display: "flex", gap: 4 }}>
                {ESFUERZOS.map(e => (
                  <button
                    key={e.valor}
                    type="button"
                    title={e.texto}
                    onClick={() => onCambiar({ esfuerzo: idea.esfuerzo === e.valor ? null : e.valor })}
                    style={{
                      ...inputStyle, cursor: "pointer", fontSize: 10, padding: "5px 9px",
                      color: idea.esfuerzo === e.valor ? "var(--accent)" : "var(--muted2)",
                      borderColor: idea.esfuerzo === e.valor ? "rgba(200,169,110,0.35)" : "var(--border2)",
                    }}
                  >
                    {e.punto}
                  </button>
                ))}
              </div>
            </div>
            <div style={{ flex: 1, minWidth: 140 }}>
              <Campo
                etiqueta="Área"
                valor={idea.area}
                placeholder="backend, frontend, salud…"
                onGuardar={v => onCambiar({ area: v })}
              />
            </div>
            <span style={{ fontSize: 10, color: "var(--muted2)", fontFamily: MONO }}>
              {desdeHace(idea.creada)}
            </span>
            <Boton tono="peligro" onClick={onBorrar}>Borrar</Boton>
          </div>
        </div>
      )}
    </div>
  );
}

// Campo de texto que guarda al salir del foco. Sin botón de guardar: son notas, y un
// formulario con su botón para cada una de ellas es justo lo que hace que no se escriban.
function Campo({ etiqueta, valor, placeholder, onGuardar }) {
  const [texto, setTexto]   = useState(valor || "");
  // Ajuste durante el render y no en un efecto: es el patrón del proyecto para
  // sincronizar estado con una prop (ver DateInput/TimeInput en Dashboard.jsx).
  const [previo, setPrevio] = useState(valor);
  if (valor !== previo) { setPrevio(valor); setTexto(valor || ""); }

  return (
    <div>
      <div style={tituloStyle}>{etiqueta}</div>
      <input
        value={texto}
        placeholder={placeholder}
        onChange={e => setTexto(e.target.value)}
        onBlur={() => { if (texto !== (valor || "")) onGuardar(texto.trim() || null); }}
        style={{ ...inputStyle, width: "100%", fontFamily: "'DM Sans', sans-serif", fontSize: 12 }}
      />
    </div>
  );
}
