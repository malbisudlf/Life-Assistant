// La zona de desarrollo: el armazón y sus pestañas. Ver docs/ZONA_DEV.md.
//
// Vive fuera de Dashboard.jsx a propósito, y es la única excepción a la regla de "toda la
// UI en un fichero" (anotada también en CLAUDE.md): esto no es un widget, es otra
// aplicación dentro de la aplicación, y ninguna sesión que vaya a tocar el dashboard
// necesita cargarla.
import { useState, useEffect } from "react";

import Ideas from "./Ideas";
import Estado from "./Estado";
import Logs from "./Logs";
import Despliegue from "./Despliegue";
import Crons from "./Crons";

// Las pestañas que existen y las que existirán. Las de fases posteriores se enseñan
// apagadas en vez de esconderse: el plan a la vista es lo que evita que la zona dev se
// quede a medias y nadie se acuerde de qué faltaba.
const PESTANAS = [
  { id: "ideas",  etiqueta: "Ideas",      fase: 1 },
  { id: "estado", etiqueta: "Estado",     fase: 1 },
  { id: "logs",   etiqueta: "Logs",       fase: 1 },
  { id: "deploy", etiqueta: "Despliegue", fase: 1 },
  { id: "crons",  etiqueta: "Crons",      fase: 1 },
  { id: "bd",     etiqueta: "Base de datos", fase: 2 },
  { id: "config", etiqueta: "Config",     fase: 2 },
  { id: "linea",  etiqueta: "Línea de tiempo", fase: 3 },
  { id: "jobs",   etiqueta: "Agente y jobs", fase: 3 },
  { id: "datos",  etiqueta: "Salud de datos", fase: 3 },
  { id: "avisos", etiqueta: "Avisos",     fase: 3 },
  { id: "gasto",  etiqueta: "Gasto",      fase: 4 },
];

const TAB_KEY = "la_dev_tab";

export default function ZonaDev({ onSalir, agentId, filasExtra }) {
  // La pestaña abierta sobrevive a recargar: se entra aquí una y otra vez a mirar lo
  // mismo mientras se prueba algo.
  const [tab, setTab] = useState(() => {
    const guardada = localStorage.getItem(TAB_KEY);
    return PESTANAS.some(p => p.id === guardada && p.fase === 1) ? guardada : "ideas";
  });

  useEffect(() => { localStorage.setItem(TAB_KEY, tab); }, [tab]);

  // Escape vuelve al dashboard, como en los modales del resto de la app.
  useEffect(() => {
    function alPulsar(e) { if (e.key === "Escape") onSalir(); }
    window.addEventListener("keydown", alPulsar);
    return () => window.removeEventListener("keydown", alPulsar);
  }, [onSalir]);

  return (
    <div style={{
      minHeight: "100vh", background: "var(--bg)", color: "var(--text)",
      padding: "16px 20px 40px", display: "flex", flexDirection: "column", gap: 14,
    }}>
      <header style={{ display: "flex", alignItems: "center", gap: 14, flexWrap: "wrap" }}>
        <button
          type="button"
          onClick={onSalir}
          style={{
            background: "transparent", border: "0.5px solid var(--border2)",
            borderRadius: 6, color: "var(--muted)", fontSize: 12,
            padding: "6px 11px", cursor: "pointer",
          }}
        >
          ← dashboard
        </button>
        <span style={{
          fontSize: 11, letterSpacing: "0.22em", textTransform: "uppercase",
          color: "var(--accent)",
        }}>
          🛠 zona dev
        </span>
      </header>

      <nav style={{ display: "flex", gap: 2, flexWrap: "wrap", borderBottom: "0.5px solid var(--border)" }}>
        {PESTANAS.map(p => {
          const activa   = p.id === tab;
          const pendiente = p.fase > 1;
          return (
            <button
              key={p.id}
              type="button"
              disabled={pendiente}
              onClick={() => setTab(p.id)}
              title={pendiente ? `Fase ${p.fase} — todavía no` : undefined}
              style={{
                background:  activa ? "var(--surface)" : "transparent",
                border:      "0.5px solid",
                borderColor: activa ? "var(--border2)" : "transparent",
                borderBottom: activa ? "0.5px solid var(--bg)" : "0.5px solid transparent",
                borderRadius: "6px 6px 0 0",
                marginBottom: -1,
                padding:     "7px 12px",
                fontSize:    12,
                fontFamily:  "'DM Sans', sans-serif",
                color:       activa ? "var(--accent)" : pendiente ? "var(--muted2)" : "var(--muted)",
                opacity:     pendiente ? 0.45 : 1,
                cursor:      pendiente ? "default" : "pointer",
              }}
            >
              {p.etiqueta}
              {pendiente && <span style={{ fontSize: 9, marginLeft: 5 }}>F{p.fase}</span>}
            </button>
          );
        })}
      </nav>

      <main style={{ minWidth: 0 }}>
        {tab === "ideas"  && <Ideas />}
        {tab === "estado" && <Estado agentId={agentId} filasExtra={filasExtra} />}
        {tab === "logs"   && <Logs />}
        {tab === "deploy" && <Despliegue />}
        {tab === "crons"  && <Crons />}
      </main>
    </div>
  );
}
