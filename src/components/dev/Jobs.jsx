// El agente PC y su cola, enteros.
//
// Del agente solo se veía una fila en el panel ⚙ ("online" o "apagado") y de la cola no se
// veía nada: para saber por qué una entrega no había salido había que abrir Supabase y
// mirar `jobs`, `job_events` y `job_results` por separado — que es exactamente lo que hace
// que no se mire.
//
// Lo único que esta pestaña TOCA es reintentar un job fallido y despertar el PC; las dos
// cosas son repetibles y las dos ya existían como endpoint (docs/ZONA_DEV.md).
import { useState, useEffect, useCallback } from "react";

import { API, authHeaders, apiFetch } from "../../lib/api";
import { MONO, panelStyle, tituloStyle, COLOR_TONO, horaCorta, desdeHace,
         leerJobs, estadoAgente, estadoJob, reintentarJob } from "../../lib/dev";
import { Boton, Vacio } from "./ui";

const REFRESCO_MS = 15_000;

export default function Jobs() {
  const [datos, setDatos]     = useState(null);
  const [error, setError]     = useState("");
  const [leyendo, setLeyendo] = useState(true);
  const [abierto, setAbierto] = useState(null);
  const [aviso, setAviso]     = useState("");
  const [tic, setTic]         = useState(0);

  useEffect(() => {
    let vivo = true;
    (async () => {
      try {
        const d = await leerJobs(30);
        if (vivo) { setDatos(d); setError(""); }
      } catch (e) {
        if (vivo) setError(e.message || "no se pudo consultar");
      } finally {
        if (vivo) setLeyendo(false);
      }
    })();
    return () => { vivo = false; };
  }, [tic]);

  // Va contra Supabase: gratis, así que puede refrescarse solo. Cada 15 s porque lo que se
  // mira aquí —un job avanzando de etapa— dura segundos.
  useEffect(() => {
    const id = setInterval(() => setTic(t => t + 1), REFRESCO_MS);
    return () => clearInterval(id);
  }, []);

  const recargar = useCallback(() => { setLeyendo(true); setTic(t => t + 1); }, []);

  async function despertar() {
    setAviso("");
    try {
      await apiFetch(`${API}/wake-pc`, { method: "POST", headers: authHeaders() });
      setAviso("Encolado el magic packet: lo manda Home Assistant en su próximo sondeo.");
    } catch {
      setAviso("No se pudo pedir el encendido.");
    }
  }

  async function reintentar(job) {
    setAviso("");
    try {
      await reintentarJob(job.id, job.claimed_by);
      setAviso(`Job ${job.id.slice(0, 8)} devuelto a la cola.`);
      recargar();
    } catch (e) {
      setAviso(`No se pudo reintentar: ${e.message}`);
    }
  }

  const agentes = datos?.agentes;
  const jobs    = datos?.jobs;

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 14 }}>
      <div style={panelStyle}>
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 12 }}>
          <div style={{ ...tituloStyle, marginBottom: 0 }}>Agentes</div>
          <div style={{ display: "flex", gap: 8 }}>
            <Boton onClick={despertar} title="Pide el Wake-on-LAN; lo manda HA al sondear">
              Despertar el PC
            </Boton>
            <Boton onClick={recargar} disabled={leyendo}>
              {leyendo ? "Mirando…" : "Actualizar"}
            </Boton>
          </div>
        </div>

        {error && <Vacio>No se pudo consultar: {error}</Vacio>}
        {!error && agentes === null && <Vacio>No se ha podido leer la tabla de agentes.</Vacio>}
        {!error && agentes?.length === 0 && (
          <Vacio>Ningún agente se ha registrado nunca. El agente PC es efímero: se apunta al arrancar.</Vacio>
        )}

        <div style={{ display: "flex", flexDirection: "column", gap: 7 }}>
          {(agentes || []).map(a => {
            const semaforo = estadoAgente(a, datos?.timeout_segundos);
            return (
              <div key={a.agent_id} style={{ display: "flex", alignItems: "baseline", gap: 8 }}>
                <span style={{ width: 7, height: 7, borderRadius: "50%", flexShrink: 0,
                               alignSelf: "center", background: COLOR_TONO[semaforo.tono] }} />
                <span style={{ fontFamily: MONO, fontSize: 12, color: "var(--text)", minWidth: 180 }}>
                  {a.agent_id}
                  <span style={{ display: "block", fontSize: 9, color: "var(--muted2)" }}>
                    {a.hostname || "sin hostname"}{a.version ? ` · v${a.version}` : ""}
                  </span>
                </span>
                <span style={{ fontSize: 11, color: "var(--muted)", flex: 1, textAlign: "right" }}>
                  {semaforo.texto}
                </span>
              </div>
            );
          })}
        </div>
        <div style={{ fontSize: 10, color: "var(--muted2)", marginTop: 8 }}>
          Que lleve horas callado es lo normal: el PC está apagado la mayor parte del día, y
          llamar avería a eso sería llamar avería a la noche.
        </div>
      </div>

      {aviso && (
        <div style={{ ...panelStyle, fontSize: 11, color: "var(--muted)" }}>{aviso}</div>
      )}

      <div style={{ ...panelStyle, padding: 0 }}>
        <div style={{ ...tituloStyle, padding: "14px 16px 8px" }}>La cola</div>
        {jobs === null && <Vacio>No se ha podido leer la cola.</Vacio>}
        {jobs?.length === 0 && <Vacio>No hay ningún job. Se crean al empezar una clase con entrega.</Vacio>}

        {(jobs || []).map(j => {
          const semaforo = estadoJob(j, datos?.max_intentos);
          const activo   = abierto === j.id;
          const payload  = j.payload || {};
          return (
            <div key={j.id} style={{ borderBottom: "0.5px solid var(--border)" }}>
              <div style={{ display: "flex", gap: 10, alignItems: "baseline", padding: "7px 14px" }}>
                <span style={{ color: "var(--muted2)", fontFamily: MONO, fontSize: 11, flexShrink: 0 }}>
                  {horaCorta(j.created_at)}
                </span>
                <span style={{ width: 7, height: 7, borderRadius: "50%", flexShrink: 0,
                               alignSelf: "center", background: COLOR_TONO[semaforo.tono] }} />
                <button
                  type="button"
                  onClick={() => setAbierto(activo ? null : j.id)}
                  style={{
                    flex: 1, minWidth: 0, textAlign: "left", background: "transparent",
                    border: 0, padding: 0, cursor: "pointer", fontFamily: MONO, fontSize: 12,
                    color: "var(--text)", overflow: "hidden", textOverflow: "ellipsis",
                    whiteSpace: "nowrap",
                  }}
                  title="Ver las etapas por las que pasó"
                >
                  {payload.accion || "entrega"} · {j.dedupe_key}
                </button>
                <span style={{ fontSize: 11, color: "var(--muted)", flexShrink: 0 }}>
                  {semaforo.texto}
                </span>
                {semaforo.reintentable ? (
                  <Boton onClick={() => reintentar(j)} tono="acento">Reintentar</Boton>
                ) : semaforo.motivo ? (
                  <span style={{ fontSize: 10, color: "var(--muted2)", flexShrink: 0 }}>
                    {semaforo.motivo}
                  </span>
                ) : null}
                <span style={{ color: "var(--muted2)", fontSize: 10, flexShrink: 0 }}>
                  {j.etapas?.length || 0} {activo ? "▾" : "▸"}
                </span>
              </div>

              {activo && (
                <div style={{ padding: "0 14px 12px 52px" }}>
                  {!j.etapas?.length && (
                    <div style={{ fontSize: 11, color: "var(--muted2)" }}>
                      Sin etapas: el agente no llegó a cogerlo, o murió antes de apuntar la primera.
                    </div>
                  )}
                  {(j.etapas || []).map((e, i) => (
                    <div key={i} style={{ display: "flex", gap: 10, fontFamily: MONO, fontSize: 11 }}>
                      <span style={{ color: "var(--muted2)" }}>{horaCorta(e.created_at)}</span>
                      <span style={{ color: "var(--accent)", minWidth: 90 }}>{e.stage}</span>
                      <span style={{ color: "var(--muted)", flex: 1, wordBreak: "break-word" }}>
                        {e.message}
                      </span>
                    </div>
                  ))}
                  {j.claimed_by && (
                    <div style={{ fontSize: 10, color: "var(--muted2)", marginTop: 6 }}>
                      lo cogió {j.claimed_by} {desdeHace(j.claimed_at) || ""}
                    </div>
                  )}
                </div>
              )}
            </div>
          );
        })}
      </div>

      {!!datos?.resultados?.length && (
        <div style={panelStyle}>
          <div style={tituloStyle}>Últimas entregas resueltas</div>
          <div style={{ display: "flex", flexDirection: "column", gap: 5 }}>
            {datos.resultados.map(r => (
              <div key={r.id} style={{ display: "flex", gap: 10, fontSize: 11 }}>
                <span style={{ fontFamily: MONO, color: "var(--muted2)", flexShrink: 0 }}>
                  {horaCorta(r.created_at)}
                </span>
                <span style={{ color: "var(--text)", flex: 1, minWidth: 0,
                               overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
                  {r.titulo}
                </span>
              </div>
            ))}
          </div>
          <div style={{ fontSize: 10, color: "var(--muted2)", marginTop: 8 }}>
            La solución se entrega a mano: esto solo dice que el agente la dejó escrita.
          </div>
        </div>
      )}
    </div>
  );
}
