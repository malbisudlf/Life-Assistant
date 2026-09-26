// La zona de desarrollo: el armazón y sus pestañas. Ver docs/ZONA_DEV.md.
//
// Vive fuera de Dashboard.jsx a propósito, y es la única excepción a la regla de "toda la
// UI en un fichero" (anotada también en CLAUDE.md): esto no es un widget, es otra
// aplicación dentro de la aplicación, y ninguna sesión que vaya a tocar el dashboard
// necesita cargarla.
import { useState, useEffect, useCallback, useMemo, useRef } from "react";

import { PESTANAS, MONO, COLOR_TONO, panelStyle, desdeHace, refrescarMientrasSeVea,
         LECTURAS_AUTO, LECTURAS_ABRIR, LECTURAS_GITHUB, leerParte, parteDelSistema,
         insigniasPorPestana, trozosDelParte, etiquetaConInsignia } from "../../lib/dev";
import { Boton } from "./ui";
import Ideas from "./Ideas";
import Estado from "./Estado";
import Logs from "./Logs";
import Despliegue from "./Despliegue";
import Crons from "./Crons";
import BaseDeDatos from "./BaseDeDatos";
import Config from "./Config";
import LineaTiempo from "./LineaTiempo";
import Jobs from "./Jobs";
import SaludDatos from "./SaludDatos";
import Avisos from "./Avisos";

// Las pestañas (PESTANAS) viven en src/lib/dev.js: el parte necesita sus nombres.

const TAB_KEY = "la_dev_tab";

// El parte se relee solo cada minuto, pero solo lo barato (LECTURAS_AUTO). Lo de GitHub,
// si el backend tiene credencial, cada cinco: la misma cadencia que la pestaña Despliegue.
const REFRESCO_PARTE_MS  = 60_000;
const REFRESCO_GITHUB_MS = 5 * 60_000;

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

  // ── El parte (docs/ZONA_DEV.md) ──
  // `lecturas` se ACUMULA: cada clave se sobrescribe solo cuando se vuelve a leer, así que
  // lo que se leyó al abrir (la base de datos, la config) sigue contando aunque el
  // intervalo no lo repita.
  const [lecturas, setLecturas]         = useState({});
  const [leyendoParte, setLeyendoParte] = useState(true);
  const vivo = useRef(true);

  useEffect(() => {
    vivo.current = true;
    return () => { vivo.current = false; };
  }, []);

  // `avisar` enciende el «comprobando…» y apaga los botones. Solo lo hacen las lecturas
  // que pide alguien: que la franja parpadee cada minuto por el refresco sería ruido.
  const leer = useCallback(async (incluir, { avisar = true } = {}) => {
    if (avisar) setLeyendoParte(true);
    const nuevas = await leerParte({ agentId, incluir });   // no lanza: allSettled
    if (!vivo.current) return;
    setLecturas(prev => ({ ...prev, ...nuevas }));
    if (avisar) setLeyendoParte(false);
  }, [agentId]);

  // Al abrir: todo lo que no gasta cuota de GitHub. El estado se escribe DESPUÉS del
  // await (nada de setState síncrono en un efecto, docs/FRONTEND.md).
  useEffect(() => {
    let activo = true;
    (async () => {
      const nuevas = await leerParte({ agentId, incluir: LECTURAS_ABRIR });
      if (!activo) return;
      setLecturas(prev => ({ ...prev, ...nuevas }));
      setLeyendoParte(false);
    })();
    return () => { activo = false; };
  }, [agentId]);

  // Cada minuto, lo barato, y nada con la pestaña del navegador oculta: la zona dev se
  // queda abierta toda la tarde en una pestaña que no se mira. Al volver a ella se lee al
  // momento si lo último tiene más de un minuto, para no enseñar un parte de hace una hora.
  // Es el mismo `refrescarMientrasSeVea` de las pestañas (docs/ZONA_DEV.md).
  useEffect(
    () => refrescarMientrasSeVea(() => leer(LECTURAS_AUTO, { avisar: false }), REFRESCO_PARTE_MS),
    [leer],
  );

  // GitHub solo se refresca solo si el backend tiene credencial, y eso lo dice la propia
  // respuesta: se deriva de la última lectura y no se guarda aparte, para que no pueda
  // quedarse encendido después de que una respuesta diga lo contrario.
  const conGithub = [lecturas.crons, lecturas.despliegue]
    .some(l => l?.ok && l.datos?.github?.con_credencial === true);
  useEffect(() => {
    if (!conGithub) return undefined;
    return refrescarMientrasSeVea(() => leer(LECTURAS_GITHUB, { avisar: false }), REFRESCO_GITHUB_MS);
  }, [conGithub, leer]);

  const parte     = useMemo(() => parteDelSistema(lecturas, { filasExtra }), [lecturas, filasExtra]);
  const insignias = useMemo(() => insigniasPorPestana(parte), [parte]);

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

      <Parte
        parte={parte}
        lecturas={lecturas}
        leyendo={leyendoParte}
        onIr={setTab}
        onComprobarTodo={() => leer(LECTURAS_ABRIR)}
        onGithub={() => leer(LECTURAS_GITHUB)}
      />

      <nav style={{ display: "flex", gap: 2, flexWrap: "wrap", borderBottom: "0.5px solid var(--border)" }}>
        {PESTANAS.map(p => {
          const activa   = p.id === tab;
          const pendiente = p.fase > 1;
          // Las apagadas no llevan insignia: no hay nada que abrir.
          const insignia = pendiente ? null : insignias[p.id];
          return (
            <button
              key={p.id}
              type="button"
              disabled={pendiente}
              onClick={() => setTab(p.id)}
              title={pendiente ? `Fase ${p.fase} — todavía no` : undefined}
              aria-label={insignia ? etiquetaConInsignia(p.etiqueta, insignia) : undefined}
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
              {insignia && (
                <span aria-hidden="true" style={{
                  marginLeft: 6, padding: "0 5px", borderRadius: 8,
                  border: "0.5px solid currentColor", fontSize: 9, fontFamily: MONO,
                  color: COLOR_TONO[insignia.tono],
                }}>
                  {insignia.n ?? "?"}
                </span>
              )}
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
        {tab === "bd"     && <BaseDeDatos />}
        {tab === "config" && <Config />}
        {tab === "linea"  && <LineaTiempo />}
        {tab === "jobs"   && <Jobs />}
        {tab === "datos"  && <SaludDatos />}
        {tab === "avisos" && <Avisos />}
      </main>
    </div>
  );
}

// Los puntos de la frase: enlaces que abren su pestaña, con el color de su tono.
const enlaceStyle = {
  background: "transparent", border: 0, padding: 0, margin: 0, cursor: "pointer",
  font: "inherit", textAlign: "left", textDecoration: "underline dotted",
  textUnderlineOffset: 3, minWidth: 0, overflowWrap: "anywhere",
};

// Un trozo de la frase con su separador delante, en la misma caja.
function Trozo({ separador = "·", children }) {
  return (
    <span style={{ display: "inline-flex", alignItems: "baseline", gap: 8, minWidth: 0 }}>
      <span aria-hidden="true" style={{ color: "var(--muted2)" }}>{separador}</span>
      {children}
    </span>
  );
}

// La franja del parte: un punto y una frase con lo peor de todas las pestañas. Lo que no
// se ha podido leer se pinta en gris y se dice; nunca sale verde por no saber.
function Parte({ parte, lecturas, leyendo, onIr, onComprobarTodo, onGithub }) {
  const nada   = !Object.keys(lecturas).length;
  const trozos = trozosDelParte(parte, 4);
  // «Comprobado hace…» cuenta desde la lectura MÁS VIEJA de las que se enseñan: la base
  // de datos se lee al abrir y no cada minuto, y decir «hace 10 s» por el sistema sería
  // presumir de una frescura que la mitad del parte no tiene.
  const cuandos    = Object.values(lecturas).map(l => l.cuando).filter(Boolean);
  const comprobado = cuandos.length ? desdeHace(Math.min(...cuandos)) : null;
  const tonoPunto  = leyendo || nada ? "muted" : parte.tono;
  const colorCabecera = parte.items.length ? "var(--text)"
    : parte.tono === "green" ? COLOR_TONO.green : "var(--muted)";

  return (
    <div style={{
      ...panelStyle, padding: "10px 14px", display: "flex", gap: 10, flexWrap: "wrap",
      alignItems: "center", fontSize: 12,
    }}>
      {/* A la altura de la primera línea: en el móvil la frase ocupa varias. */}
      <span style={{ width: 8, height: 8, borderRadius: "50%", flexShrink: 0,
                     alignSelf: "flex-start", marginTop: 6,
                     background: COLOR_TONO[tonoPunto] }} />

      {/* Cada trozo es una caja con su separador dentro: un botón cuyo texto salta de
          línea ocupa el ancho entero, y con el separador suelto delante quedaba un «·»
          huérfano en su propia línea en el móvil. */}
      <span style={{ fontFamily: MONO, flex: "1 1 260px", minWidth: 0, lineHeight: 1.6,
                     display: "flex", flexWrap: "wrap", alignItems: "baseline",
                     columnGap: 8, rowGap: 2 }}>
        {nada ? (
          <span style={{ color: "var(--muted)" }}>comprobando…</span>
        ) : (
          <>
            <span style={{ color: colorCabecera }}>{trozos.cabecera}</span>
            {trozos.items.map((it, i) => (
              <Trozo key={`${it.pestana}-${i}`} separador={i === 0 ? "—" : "·"}>
                <button type="button" onClick={() => onIr(it.pestana)} title={it.detalle}
                        style={{ ...enlaceStyle, color: COLOR_TONO[it.tono] }}>
                  {it.titulo}
                </button>
              </Trozo>
            ))}
            {trozos.resto > 0 && (
              <Trozo>
                <span style={{ color: "var(--muted)" }}
                      title={parte.items.slice(trozos.items.length).map(i => i.titulo).join("\n")}>
                  +{trozos.resto} más
                </span>
              </Trozo>
            )}
            {trozos.notas.map(n => (
              <Trozo key={n}><span style={{ color: "var(--muted2)" }}>{n}</span></Trozo>
            ))}
          </>
        )}
      </span>

      <span style={{ marginLeft: "auto", display: "flex", gap: 8, alignItems: "center", flexWrap: "wrap" }}>
        <span style={{ fontSize: 10, color: "var(--muted2)" }}>
          {leyendo ? "comprobando…" : comprobado ? `comprobado ${comprobado}` : ""}
        </span>
        <Boton onClick={onComprobarTodo} disabled={leyendo}
               title="Relee el estado, los jobs, los avisos, los datos, la base de datos y la config">
          comprobar todo
        </Boton>
        <Boton onClick={onGithub} disabled={leyendo}
               title="gasta cuota de la API de GitHub; sin DEPLOY_GITHUB_TOKEN son 60 por hora">
          + GitHub
        </Boton>
      </span>
    </div>
  );
}
