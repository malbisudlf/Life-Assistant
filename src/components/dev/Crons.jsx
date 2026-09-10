// ¿Sigue corriendo lo que corre solo?
//
// La pestaña existe por la copia de seguridad de Supabase, que estuvo meses fallando en
// cada ejecución sin que nadie se enterara. Aquello ya tiene su aviso al móvil
// (`programado-roto.yml`), pero un aviso salta cuando algo FALLA — no cuando algo deja de
// correr, ni cuando el que deja de correr es un sondeo que nadie vigila. Aquí están las
// tres cosas en la misma pantalla: los workflows de GitHub, los envíos del backend y
// quién sigue llamando a la puerta.
import { useState, useEffect, useCallback } from "react";

import { MONO, panelStyle, tituloStyle, COLOR_TONO, horaCorta, desdeHace,
         leerCrons, estadoWorkflow, estadoSondeo, textoCada, enPieDesde } from "../../lib/dev";
import { Boton, Vacio } from "./ui";

// Un minuto. Todo esto es gratis (backend propio y Supabase) salvo los workflows, que
// gastan cuota de la API de GitHub: por eso el refresco automático solo se enciende si el
// backend tiene credencial — sin ella son 60 peticiones/hora para toda la casa.
const REFRESCO_MS = 60_000;

export default function Crons() {
  const [datos, setDatos]     = useState(null);
  const [error, setError]     = useState("");
  const [leyendo, setLeyendo] = useState(true);
  const [tic, setTic]         = useState(0);

  useEffect(() => {
    let vivo = true;
    (async () => {
      try {
        const d = await leerCrons();
        if (vivo) { setDatos(d); setError(""); }
      } catch (e) {
        if (vivo) setError(e.message || "no se pudo consultar");
      } finally {
        if (vivo) setLeyendo(false);
      }
    })();
    return () => { vivo = false; };
  }, [tic]);

  const autorefresco = datos?.github?.con_credencial;
  useEffect(() => {
    if (!autorefresco) return undefined;
    const id = setInterval(() => setTic(t => t + 1), REFRESCO_MS);
    return () => clearInterval(id);
  }, [autorefresco]);

  const recargar = useCallback(() => { setLeyendo(true); setTic(t => t + 1); }, []);

  const brief   = datos?.brief?.[0];
  const informe = datos?.informe?.[0];

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 14 }}>
      <div style={panelStyle}>
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 12 }}>
          <div style={{ ...tituloStyle, marginBottom: 0 }}>Workflows programados</div>
          <div style={{ display: "flex", gap: 8, alignItems: "center" }}>
            {!autorefresco && !leyendo && (
              <span style={{ fontSize: 10, color: "var(--muted2)" }}>
                sin refresco automático (falta DEPLOY_GITHUB_TOKEN)
              </span>
            )}
            <Boton onClick={recargar} disabled={leyendo}>
              {leyendo ? "Mirando…" : "Actualizar"}
            </Boton>
          </div>
        </div>

        {error && <Vacio>No se pudo consultar: {error}</Vacio>}
        {!error && !datos?.workflows?.length && !leyendo && (
          <Vacio>No se ha podido preguntar a GitHub por los workflows.</Vacio>
        )}

        <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
          {(datos?.workflows || []).map(wf => {
            const semaforo = estadoWorkflow(wf);
            return (
              <div key={wf.fichero} style={{ display: "flex", alignItems: "baseline", gap: 8 }}>
                <span style={{ width: 7, height: 7, borderRadius: "50%", flexShrink: 0,
                               alignSelf: "center", background: COLOR_TONO[semaforo.tono] }} />
                <span style={{ fontSize: 12, color: "var(--text)", minWidth: 200 }}>
                  {wf.nombre}
                  <span style={{ display: "block", fontFamily: MONO, fontSize: 9, color: "var(--muted2)" }}>
                    {wf.fichero} · cada {textoCada(wf.cada_horas)}
                  </span>
                </span>
                <span style={{ fontSize: 11, color: "var(--muted)", flex: 1, textAlign: "right" }}>
                  {semaforo.texto}
                  {wf.run?.url && (
                    <a href={wf.run.url} target="_blank" rel="noreferrer"
                       style={{ marginLeft: 8, color: "var(--accent)", fontSize: 10 }}>ver</a>
                  )}
                </span>
              </div>
            );
          })}
        </div>
      </div>

      <div style={panelStyle}>
        <div style={tituloStyle}>Envíos del backend</div>
        <div style={{ display: "flex", flexDirection: "column", gap: 7 }}>
          <Envio nombre="Resumen diario" fila={brief}
                 extra={brief?.fuente ? `lo disparó: ${brief.fuente}` : null} />
          <Envio nombre="Informe semanal" fila={informe} />
        </div>
        <div style={{ fontSize: 10, color: "var(--muted2)", marginTop: 8 }}>
          Estas dos filas salen de la tabla, no del workflow: el correo lo dispara la señal
          de despertar y GitHub es solo la red de seguridad. Si aquí sale hoy y arriba el
          workflow no ha corrido, todo está bien.
        </div>
      </div>

      <div style={panelStyle}>
        <div style={tituloStyle}>Quién sigue sondeando</div>
        <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
          {(datos?.sondeos || []).map(s => {
            const semaforo = estadoSondeo(s, datos?.proceso_desde_hace);
            return (
              <div key={s.ruta} style={{ display: "flex", alignItems: "baseline", gap: 8 }}>
                <span style={{ width: 7, height: 7, borderRadius: "50%", flexShrink: 0,
                               alignSelf: "center", background: COLOR_TONO[semaforo.tono] }} />
                <span style={{ fontSize: 12, color: "var(--text)", minWidth: 200 }}>
                  {s.nombre}
                  <span style={{ display: "block", fontFamily: MONO, fontSize: 9, color: "var(--muted2)" }}>
                    {s.ruta}
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
          Se cuenta en memoria y se pierde al reiniciar el backend, que lleva en pie{" "}
          {enPieDesde(datos?.proceso_desde_hace)}. Las dos últimas filas dependen de que el
          PC esté encendido (o el dashboard abierto): ahí el silencio es lo normal.
        </div>
      </div>

      {!!datos?.vigilantes?.length && (
        <div style={panelStyle}>
          <div style={tituloStyle}>Averías que el vigilante tiene abiertas</div>
          <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
            {datos.vigilantes.map(v => (
              <div key={v.clave} style={{ display: "flex", alignItems: "baseline", gap: 8 }}>
                <span style={{ fontFamily: MONO, fontSize: 11, color: "var(--text)", minWidth: 200 }}>
                  {v.clave}
                </span>
                <span style={{ fontSize: 11, color: "var(--muted)", flex: 1, textAlign: "right" }}>
                  {v.veces} {v.veces === 1 ? "vez" : "veces"} · última {desdeHace(v.ultima_vez) || horaCorta(v.ultima_vez)}
                  {v.issue_url && (
                    <a href={v.issue_url} target="_blank" rel="noreferrer"
                       style={{ marginLeft: 8, color: "var(--accent)", fontSize: 10 }}>issue</a>
                  )}
                </span>
              </div>
            ))}
          </div>
          <div style={{ fontSize: 10, color: "var(--muted2)", marginTop: 8 }}>
            Una que se repite todos los días no está arreglada, esté el issue cerrado o no.
          </div>
        </div>
      )}
    </div>
  );
}

// Un envío. Que no haya fila no es que haya fallado: puede que hoy todavía no toque, y esa
// diferencia es justo la que esta pantalla existe para no borrar.
function Envio({ nombre, fila, extra }) {
  return (
    <div style={{ display: "flex", alignItems: "baseline", gap: 8 }}>
      <span style={{ width: 7, height: 7, borderRadius: "50%", flexShrink: 0, alignSelf: "center",
                     background: COLOR_TONO[fila ? "green" : "muted"] }} />
      <span style={{ fontSize: 12, color: "var(--text)", minWidth: 200 }}>{nombre}</span>
      <span style={{ fontSize: 11, color: "var(--muted)", flex: 1, textAlign: "right" }}>
        {fila
          ? `el último, el ${fila.fecha}${fila.enviado_at ? ` (${desdeHace(fila.enviado_at)})` : ""}`
          : "no consta ninguno"}
        {extra && <span style={{ display: "block", fontSize: 10, color: "var(--muted2)" }}>{extra}</span>}
      </span>
    </div>
  );
}
