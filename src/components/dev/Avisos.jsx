// Qué avisos salieron, por qué, qué reglas siguen vivas y cuáles se han callado.
//
// El gobierno de los avisos ya existía —una regla votada "no útil" varias veces se silencia
// sola— pero se gobernaba a ciegas: `/avisos/estado` dice cuántas hay calladas y nada más, y
// para saber si una regla acierta había que acordarse de unos avisos que se borran del móvil
// al leerlos.
//
// Una regla silenciada se pinta en ROJO aunque no haya fallado nada: significa que el
// sistema dejó de avisarte de algo y no te lo dijo, que es el fallo más caro que puede
// cometer una regla.
import { useState, useEffect, useCallback } from "react";

import { API, authHeaders, apiFetch } from "../../lib/api";
import { MONO, panelStyle, tituloStyle, COLOR_TONO, horaCorta, desdeHace,
         leerAvisosDev, estadoRegla, reactivarRegla } from "../../lib/dev";
import { Boton, Vacio } from "./ui";

const VENTANAS = [1, 7, 30];

export default function Avisos() {
  const [dias, setDias]       = useState(7);
  const [datos, setDatos]     = useState(null);
  const [error, setError]     = useState("");
  const [leyendo, setLeyendo] = useState(true);
  const [abierto, setAbierto] = useState(null);
  const [porque, setPorque]   = useState({});   // id -> motivo o "nada"
  const [tic, setTic]         = useState(0);

  useEffect(() => {
    let vivo = true;
    (async () => {
      try {
        const d = await leerAvisosDev(dias);
        if (vivo) { setDatos(d); setError(""); }
      } catch (e) {
        if (vivo) { setDatos(null); setError(e.message || "no se pudo consultar"); }
      } finally {
        if (vivo) setLeyendo(false);
      }
    })();
    return () => { vivo = false; };
  }, [dias, tic]);

  const recargar = useCallback(() => { setLeyendo(true); setTic(t => t + 1); }, []);

  // El "por qué" se pide solo al abrir un aviso, no con la lista: son doscientos avisos y
  // doscientas consultas para enseñar una.
  async function abrir(aviso) {
    if (abierto === aviso.id) { setAbierto(null); return; }
    setAbierto(aviso.id);
    if (porque[aviso.id] !== undefined) return;
    try {
      const r = await apiFetch(`${API}/avisos/${aviso.id}/porque`, { headers: authHeaders() });
      const cuerpo = r.ok ? await r.json() : null;
      setPorque(p => ({ ...p, [aviso.id]: cuerpo?.motivo || null }));
    } catch {
      setPorque(p => ({ ...p, [aviso.id]: null }));
    }
  }

  async function reactivar(regla) {
    try {
      await reactivarRegla(regla);
      recargar();
    } catch { /* la pantalla se recarga sola en el siguiente intento */ }
  }

  const reglas    = datos?.reglas;
  const enviados  = datos?.enviados;
  const gastado   = datos?.presupuesto?.gastado ?? 0;
  const tope      = datos?.presupuesto?.tope ?? 0;

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 14 }}>
      <div style={{ ...panelStyle, display: "flex", gap: 10, alignItems: "center", flexWrap: "wrap" }}>
        <span style={{ ...tituloStyle, marginBottom: 0 }}>Ventana</span>
        {VENTANAS.map(d => (
          <Boton key={d} onClick={() => { setLeyendo(true); setDias(d); }}
                 tono={d === dias ? "acento" : "normal"}>
            {d === 1 ? "hoy" : `${d} días`}
          </Boton>
        ))}
        <span style={{ flex: 1 }} />
        <span style={{ fontSize: 11, color: "var(--muted)" }}>
          {datos ? (datos.activo ? `canal: ${datos.canal}` : "móvil desactivado") : "—"}
          {datos && ` · ${gastado}/${tope} avisos hoy`}
        </span>
        <Boton onClick={recargar} disabled={leyendo}>{leyendo ? "Mirando…" : "Actualizar"}</Boton>
      </div>

      {error && <div style={panelStyle}><Vacio>No se pudo consultar: {error}</Vacio></div>}

      <div style={panelStyle}>
        <div style={tituloStyle}>Reglas</div>
        {reglas === null && <Vacio>No se ha podido leer ni los avisos ni el gobierno de reglas.</Vacio>}
        {reglas?.length === 0 && (
          <Vacio>Ninguna regla ha mandado nada en la ventana, y ninguna está silenciada.</Vacio>
        )}
        <div style={{ display: "flex", flexDirection: "column", gap: 7 }}>
          {(reglas || []).map(r => {
            const semaforo = estadoRegla(r);
            return (
              <div key={r.regla} style={{ display: "flex", alignItems: "baseline", gap: 8 }}>
                <span style={{ width: 7, height: 7, borderRadius: "50%", flexShrink: 0,
                               alignSelf: "center", background: COLOR_TONO[semaforo.tono] }} />
                <span style={{ fontFamily: MONO, fontSize: 12, color: "var(--text)", minWidth: 180 }}>
                  {r.regla}
                  <span style={{ display: "block", fontSize: 9, color: "var(--muted2)" }}>
                    {r.enviados} en {dias === 1 ? "hoy" : `${dias} días`}
                    {r.ultimo ? ` · último ${desdeHace(r.ultimo)}` : ""}
                  </span>
                </span>
                <span style={{ fontSize: 11, color: "var(--muted)", flex: 1, textAlign: "right" }}>
                  {semaforo.texto}
                </span>
                {r.silenciada && (
                  <Boton onClick={() => reactivar(r.regla)} tono="acento"
                         title="Le devuelve la voz. Si vuelve a acumular votos negativos, se callará otra vez.">
                    Reactivar
                  </Boton>
                )}
              </div>
            );
          })}
        </div>
      </div>

      <div style={{ ...panelStyle, padding: 0 }}>
        <div style={{ ...tituloStyle, padding: "14px 16px 8px" }}>Lo que salió</div>
        {enviados === null && <Vacio>No se han podido leer los avisos enviados.</Vacio>}
        {enviados?.length === 0 && (
          <Vacio>No ha salido ningún aviso en esta ventana. Silencio y avería se parecen: mira las reglas de arriba.</Vacio>
        )}
        {(enviados || []).map(a => {
          const activo = abierto === a.id;
          return (
            <div key={a.id} style={{ borderBottom: "0.5px solid var(--border)" }}>
              <button
                type="button"
                onClick={() => abrir(a)}
                style={{
                  display: "flex", gap: 10, alignItems: "baseline", width: "100%",
                  background: "transparent", border: 0, padding: "6px 14px", cursor: "pointer",
                  textAlign: "left", fontFamily: MONO, fontSize: 12, color: "var(--text)",
                }}
                title="Con qué números se disparó"
              >
                <span style={{ color: "var(--muted2)", flexShrink: 0 }}>{horaCorta(a.enviado_at)}</span>
                <span style={{ color: "var(--accent)", width: 130, flexShrink: 0,
                               overflow: "hidden", textOverflow: "ellipsis" }}>
                  {a.regla || "sin regla"}
                </span>
                <span style={{ flex: 1, minWidth: 0, color: "var(--muted)",
                               overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
                  {a.texto}
                </span>
                <span style={{ fontSize: 10, flexShrink: 0,
                               color: a.util === false ? "#c9736b"
                                    : a.util === true ? "var(--green)" : "var(--muted2)" }}>
                  {a.util === true ? "útil" : a.util === false ? "no útil" : "sin votar"}
                </span>
                <span style={{ color: "var(--muted2)", flexShrink: 0 }}>{activo ? "▾" : "▸"}</span>
              </button>
              {activo && (
                <pre style={{
                  margin: "0 14px 12px 14px", padding: 10, background: "var(--surface2)",
                  border: "0.5px solid var(--border)", borderRadius: 6,
                  fontFamily: MONO, fontSize: 11, color: "var(--muted)",
                  overflowX: "auto", whiteSpace: "pre-wrap", wordBreak: "break-word",
                }}>
                  {porque[a.id] === undefined ? "Preguntando…"
                    : porque[a.id] === null
                      ? "Sin motivo guardado. No es un fallo: las reglas anteriores a que se "
                        + "guardara el porqué no dejaron ninguno."
                      : JSON.stringify(porque[a.id].datos ?? porque[a.id], null, 2)}
                </pre>
              )}
            </div>
          );
        })}
      </div>

      {!!datos?.de_usuario?.length && (
        <div style={panelStyle}>
          <div style={tituloStyle}>Reglas que propuso Jarvis y aprobaste tú</div>
          <div style={{ display: "flex", flexDirection: "column", gap: 5 }}>
            {datos.de_usuario.map(r => (
              <div key={r.clave} style={{ display: "flex", gap: 10, alignItems: "baseline", fontSize: 11 }}>
                <span style={{ width: 7, height: 7, borderRadius: "50%", flexShrink: 0, alignSelf: "center",
                               background: COLOR_TONO[r.activa ? "green" : "muted"] }} />
                <span style={{ fontFamily: MONO, fontSize: 12, color: "var(--text)", minWidth: 150 }}>
                  {r.clave}
                </span>
                <span style={{ color: "var(--muted2)", width: 130, flexShrink: 0, fontSize: 10 }}>
                  {r.plantilla}
                </span>
                <span style={{ color: "var(--muted)", flex: 1, minWidth: 0,
                               overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
                  {JSON.stringify(r.parametros)}
                </span>
                <span style={{ color: "var(--muted2)", fontSize: 10, flexShrink: 0 }}>
                  {r.ultima_vez ? `disparó ${desdeHace(r.ultima_vez)}` : "nunca ha disparado"}
                </span>
              </div>
            ))}
          </div>
          <div style={{ fontSize: 10, color: "var(--muted2)", marginTop: 8 }}>
            Aquí no hay lógica guardada: cada una es una plantilla que el código ya sabe
            evaluar, con sus huecos rellenos. El modelo propone, tú apruebas.
          </div>
        </div>
      )}

      {!!datos?.vigilancias?.length && (
        <div style={panelStyle}>
          <div style={tituloStyle}>Páginas vigiladas</div>
          <div style={{ display: "flex", flexDirection: "column", gap: 5 }}>
            {datos.vigilancias.map(v => (
              <div key={v.clave} style={{ display: "flex", gap: 10, alignItems: "baseline", fontSize: 11 }}>
                <span style={{ fontFamily: MONO, fontSize: 12, color: "var(--text)", minWidth: 150 }}>
                  {v.clave}
                </span>
                <span style={{ color: "var(--muted2)", flex: 1, minWidth: 0, fontSize: 10,
                               overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
                  {v.buscar ? `busca "${v.buscar}"` : "cualquier cambio"} · {v.url}
                </span>
                <span style={{ color: "var(--muted)", flexShrink: 0 }}>
                  {v.avisos} {v.avisos === 1 ? "aviso" : "avisos"}
                  {v.ultima_vez ? ` · mirada ${desdeHace(v.ultima_vez)}` : " · sin mirar aún"}
                </span>
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}
