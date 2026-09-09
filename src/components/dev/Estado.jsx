// El estado del sistema: si algo responde y si algo ha fallado.
//
// Vivía dentro del panel ⚙ del dashboard y se muda aquí entero (docs/ZONA_DEV.md). En ⚙
// queda el semáforo de una línea, que es lo que se mira deprisa desde el móvil.
import { useState, useEffect } from "react";

import { API, authHeaders, apiFetch } from "../../lib/api";
import { formatLogTime } from "../../lib/helpers";
import { MONO, COLOR_TONO, panelStyle, tituloStyle, desdeHace,
         leerEstadoSistema, filasDeEstado } from "../../lib/dev";
import { Boton } from "./ui";

const REFRESCO_MS = 30_000;

export default function Estado({ agentId, filasExtra = [] }) {
  const [sys, setSys]                 = useState(null);
  const [tic, setTic]                 = useState(0);   // cada incremento, otra lectura
  const [avisoPrueba, setAvisoPrueba] = useState("");
  const [envio, setEnvio]             = useState("");

  // La lectura entera vive dentro del efecto y el estado se escribe DESPUÉS del await:
  // nada de setState síncrono dentro de un efecto (regla react-hooks del proyecto). El
  // `vivo` evita escribir sobre un componente ya desmontado si se sale de la pestaña
  // mientras las siete llamadas están en vuelo.
  useEffect(() => {
    let vivo = true;
    (async () => {
      const datos = await leerEstadoSistema(agentId);
      if (vivo) setSys(datos);
    })();
    return () => { vivo = false; };
  }, [agentId, tic]);

  // Refresco automático: todo lo que se pide aquí es gratis (backend propio y Supabase).
  // Lo que cuesta dinero no se refresca solo nunca — docs/ZONA_DEV.md.
  useEffect(() => {
    const id = setInterval(() => setTic(t => t + 1), REFRESCO_MS);
    return () => clearInterval(id);
  }, []);

  // Instalar el YAML de HA y no saber si funciona hasta que toque un aviso de verdad es la
  // forma más rápida de darlo por puesto sin estarlo: esto recorre la cadena entera.
  async function probarAviso() {
    setAvisoPrueba("…");
    try {
      const r = await apiFetch(`${API}/avisos/probar`, { method: "POST", headers: authHeaders() });
      const d = await r.json().catch(() => ({}));
      // "Enviado" sería mentira en el caso del móvil: lo único que sabe el backend es que
      // lo ha encolado y que HA está pasando a recoger. Si la automatización de HA falla
      // —el `notify` mal escrito, por ejemplo— el aviso se pierde ahí y aquí no se puede
      // saber. Decirlo es la diferencia entre buscar el fallo en el sitio correcto y
      // darlo por enviado, que es el error de siempre de este proyecto.
      setAvisoPrueba(d.canal === "movil"
        ? "encolado — HA lo recoge en ≤30 s. Si no suena nada, el fallo está en su "
          + "automatización o en el nombre del notify"
        : "enviado por correo (nadie recoge los avisos del móvil)");
    } catch { setAvisoPrueba("no se pudo enviar"); }
  }

  // Manda un correo de verdad, así que pregunta antes. Es de las pocas cosas que la zona
  // dev ejecuta: repetible y sin efectos que no se puedan comprobar mirando el buzón.
  async function forzar(ruta, nombre) {
    if (!window.confirm(`¿Enviar ${nombre} ahora? Sale un correo de verdad.`)) return;
    setEnvio(`${nombre}: enviando…`);
    try {
      const r = await apiFetch(`${API}${ruta}`, { method: "POST", headers: authHeaders() });
      setEnvio(r.ok ? `${nombre}: enviado` : `${nombre}: no se pudo (${r.status})`);
    } catch { setEnvio(`${nombre}: no se pudo`); }
  }

  const filas = [...filasDeEstado(sys), ...filasExtra];
  const gas   = sys?.gasto;
  const reg   = sys?.registro;

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 14 }}>
      <div style={panelStyle}>
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 12 }}>
          <div style={{ ...tituloStyle, marginBottom: 0 }}>Semáforo</div>
          <div style={{ display: "flex", gap: 8, alignItems: "center" }}>
            <span style={{ fontSize: 10, color: "var(--muted2)", fontFamily: MONO }}>
              {sys ? desdeHace(new Date(sys.comprobado).toISOString()) : "comprobando…"}
            </span>
            <Boton onClick={() => setTic(t => t + 1)}>Actualizar</Boton>
          </div>
        </div>

        <div style={{ display: "flex", flexDirection: "column", gap: 7 }}>
          {filas.map(f => (
            <div key={f.nombre} style={{ display: "flex", alignItems: "baseline", gap: 8 }}>
              <span style={{
                width: 7, height: 7, borderRadius: "50%", flexShrink: 0, alignSelf: "center",
                background: COLOR_TONO[f.tono],
              }} />
              <span style={{ fontSize: 12, color: "var(--text)", minWidth: 110 }}>{f.nombre}</span>
              <span style={{ fontSize: 11, color: "var(--muted)", flex: 1, textAlign: "right" }}>
                {f.detalle}
              </span>
            </div>
          ))}
        </div>

        {sys?.backend?.version && (
          <div style={{ marginTop: 10, fontSize: 10, color: "var(--muted2)", fontFamily: MONO }}>
            backend {String(sys.backend.version).slice(0, 7)} — que coincida con el último
            commit de main es lo que dice si la reconstrucción del add-on entró
          </div>
        )}
      </div>

      <div style={{ ...panelStyle, display: "flex", gap: 8, flexWrap: "wrap", alignItems: "center" }}>
        <div style={{ ...tituloStyle, marginBottom: 0, marginRight: 4 }}>Comprobar</div>
        <Boton onClick={probarAviso} disabled={avisoPrueba === "…"}>Probar aviso</Boton>
        <Boton onClick={() => forzar("/brief/send", "el resumen diario")}>Enviar resumen</Boton>
        <Boton onClick={() => forzar("/informe/send", "el informe semanal")}>Enviar informe</Boton>
        {!!avisoPrueba && <span style={{ fontSize: 11, color: "var(--muted)" }}>{avisoPrueba}</span>}
        {!!envio && <span style={{ fontSize: 11, color: "var(--muted)" }}>{envio}</span>}
      </div>

      {!!sys?.enviados?.length && (
        <div style={panelStyle}>
          <div style={tituloStyle}>Avisos de hoy</div>
          <AvisosDeHoy avisos={sys.enviados} />
        </div>
      )}

      {!!gas?.total?.llamadas && (
        <div style={panelStyle}>
          <div style={tituloStyle}>Coste por boca</div>
          <DesgloseGasto gasto={gas} />
        </div>
      )}

      {!!reg?.entradas?.length && (
        <div style={panelStyle}>
          <div style={tituloStyle}>Últimas incidencias</div>
          <div style={{ display: "flex", flexDirection: "column", gap: 8, maxHeight: 260, overflowY: "auto" }}>
            {reg.entradas.slice(0, 12).map((e, i) => (
              <div key={`${e.created_at}-${i}`} style={{
                borderLeft: `2px solid ${e.level === "ERROR" || e.level === "CRITICAL" ? "#d4645a" : "var(--accent)"}`,
                paddingLeft: 8,
              }}>
                <div style={{ fontFamily: MONO, fontSize: 10, color: "var(--muted2)" }}>
                  {formatLogTime(e.created_at)} · {e.level}
                  {e.context?.peticion ? ` · ${e.context.peticion}` : ""}
                </div>
                {/* pre-wrap: los logger.exception() traen traza de varias líneas */}
                <div style={{ fontSize: 11, color: "var(--muted)", whiteSpace: "pre-wrap", wordBreak: "break-word" }}>
                  {e.message}
                </div>
              </div>
            ))}
          </div>
          <div style={{ fontSize: 10, color: "var(--muted2)", marginTop: 8 }}>
            El registro entero, con filtros y búsqueda, está en la pestaña Logs.
          </div>
        </div>
      )}
    </div>
  );
}

// Los avisos que SALIERON hoy, y por qué. Antes de esto un aviso enviado desaparecía: lo
// único que quedaba era la notificación del móvil, que se borra. Sin poder volver sobre
// uno, la señal de utilidad dice QUÉ reglas se ignoran pero nunca POR QUÉ fallan.
function AvisosDeHoy({ avisos }) {
  const [abierto, setAbierto] = useState("");
  const [porque, setPorque]   = useState({});   // id → { cargando } | { motivo } | { error }

  async function verPorque(id) {
    if (abierto === id) { setAbierto(""); return; }
    setAbierto(id);
    if (porque[id]) return;                      // ya pedido: no se vuelve a pagar el viaje
    setPorque(p => ({ ...p, [id]: { cargando: true } }));
    try {
      const r = await apiFetch(`${API}/avisos/${id}/porque`, { headers: authHeaders() });
      if (!r.ok) throw new Error("no");
      const d = await r.json();
      setPorque(p => ({ ...p, [id]: { motivo: d.motivo?.datos || null } }));
    } catch {
      // "No se pudo preguntar" no es "no hay motivo": son cosas distintas y se dicen
      // distinto, que es la regla de todo el proyecto.
      setPorque(p => ({ ...p, [id]: { error: true } }));
    }
  }

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
      {avisos.map(a => {
        const estado = porque[a.id];
        return (
          <div key={a.id} style={{ borderLeft: "2px solid var(--border2)", paddingLeft: 8 }}>
            <div style={{ fontFamily: MONO, fontSize: 10, color: "var(--muted2)" }}>
              {formatLogTime(a.enviado_at)} · {a.regla || "tuyo"}
              {a.util === true ? " · te sirvió" : a.util === false ? " · no te sirvió" : ""}
            </div>
            <div style={{ fontSize: 11, color: "var(--muted)" }}>{a.texto}</div>
            <button onClick={() => verPorque(a.id)} style={{
              background: "transparent", border: "none", padding: 0, cursor: "pointer",
              color: "var(--accent)", fontSize: 10, fontFamily: "'DM Sans', sans-serif",
            }}>{abierto === a.id ? "Ocultar" : "¿Por qué?"}</button>
            {abierto === a.id && (
              <div style={{ fontFamily: MONO, fontSize: 10, color: "var(--muted2)", whiteSpace: "pre-wrap", wordBreak: "break-word", marginTop: 2 }}>
                {estado?.cargando ? "…"
                  : estado?.error ? "No se ha podido consultar"
                  : estado?.motivo ? JSON.stringify(estado.motivo, null, 1)
                  : "Este aviso no guardó con qué se disparó"}
              </div>
            )}
          </div>
        );
      })}
    </div>
  );
}

// El gasto repartido por boca. El total ya sale en el semáforo; esto es la pregunta que no
// se podía responder: por dónde se va el dinero. El modo llamada es el candidato obvio —
// paga salida por token Y segundos de voz.
function DesgloseGasto({ gasto }) {
  const bocas = Object.entries(gasto.por_boca || {}).sort((a, b) => b[1].euros - a[1].euros);
  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 4 }}>
      {bocas.map(([boca, d]) => (
        <div key={boca} style={{ display: "flex", alignItems: "baseline", gap: 8 }}>
          <span style={{ fontSize: 11, color: "var(--text)", minWidth: 80 }}>{boca}</span>
          <span style={{ fontSize: 10, color: "var(--muted2)", flex: 1, textAlign: "right", fontFamily: MONO }}>
            {d.euros.toFixed(3)} €{d.euros_incompleto ? "+" : ""} · {d.llamadas} · {(d.entrada / 1000).toFixed(1)}k ent / {(d.salida / 1000).toFixed(1)}k sal
            {d.segundos_audio ? ` · ${Math.round(d.segundos_audio)} s audio` : ""}
          </span>
        </div>
      ))}
      {!!gasto.sin_tarifa?.length && (
        <div style={{ fontSize: 10, color: "var(--muted2)" }}>
          Sin tarifa configurada: {gasto.sin_tarifa.join(", ")} — sus tokens cuentan, sus
          euros no. Se pone en MODELO_TARIFAS.
        </div>
      )}
    </div>
  );
}
