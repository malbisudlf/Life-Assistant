// Qué tiene configurado el backend y qué le falta.
//
// Lo mismo que dice `backend/check_config.py`, que hasta ahora había que ejecutar por
// consola en una máquina con el `.env` delante — es decir, nunca, y menos desde el móvil.
// Sale de la MISMA lista (`GRUPOS`), porque dos listas que dicen lo que falta acaban
// diciendo cosas distintas.
//
// **Nunca enseña un valor**, solo si está puesta. Enseñarlos convertiría esta pantalla en
// un volcado de secretos protegido por un JWT de treinta días.
import { useState, useEffect, useCallback } from "react";

import { MONO, panelStyle, tituloStyle, COLOR_TONO, desdeHace,
         leerConfig, estadoGrupo, estadoGraph, shaCorto } from "../../lib/dev";
import { Boton, Vacio } from "./ui";

export default function Config() {
  const [cfg, setCfg]         = useState(null);
  const [error, setError]     = useState("");
  const [leyendo, setLeyendo] = useState(true);
  const [tic, setTic]         = useState(0);

  useEffect(() => {
    let vivo = true;
    (async () => {
      try {
        const d = await leerConfig();
        if (vivo) { setCfg(d); setError(""); }
      } catch (e) {
        if (vivo) setError(e.message || "no se pudo consultar");
      } finally {
        if (vivo) setLeyendo(false);
      }
    })();
    return () => { vivo = false; };
  }, [tic]);

  // Sin refresco automático: esto solo cambia cuando alguien toca el `.env` y reconstruye
  // el add-on, y entonces ya se viene aquí a mirar.
  const recargar = useCallback(() => { setLeyendo(true); setTic(t => t + 1); }, []);

  const grupos     = cfg?.grupos || [];
  const incompletos = grupos.filter(g => !g.completo);
  const graph      = estadoGraph(cfg?.graph);

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 14 }}>
      <div style={panelStyle}>
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 12 }}>
          <div style={{ ...tituloStyle, marginBottom: 0 }}>Este backend</div>
          <Boton onClick={recargar} disabled={leyendo}>
            {leyendo ? "Mirando…" : "Actualizar"}
          </Boton>
        </div>

        {error && <Vacio>No se pudo consultar: {error}</Vacio>}

        {!error && cfg && (
          <div style={{ display: "flex", flexDirection: "column", gap: 7 }}>
            <Fila nombre="Versión desplegada" tono="muted"
                  detalle={shaCorto(cfg.version)} />
            <Fila nombre="Zona horaria" tono={cfg.zona?.valida ? "green" : "red"}
                  detalle={cfg.zona?.valida ? cfg.zona.nombre : `${cfg.zona?.nombre} no es una zona IANA válida`} />
            <Fila nombre="Sesión de Microsoft" tono={graph.tono} detalle={graph.texto} />
            <Fila nombre="Núcleo" tono="green"
                  detalle={`${(cfg.nucleo || []).join(" y ")} — puestas (si no, el backend no arrancaría)`} />
            <Fila nombre="Funcionalidades" tono={incompletos.length ? "muted" : "green"}
                  detalle={incompletos.length
                    ? `${grupos.length - incompletos.length} de ${grupos.length} completas`
                    : "todas configuradas"} />
          </div>
        )}
      </div>

      <div style={panelStyle}>
        <div style={tituloStyle}>Por funcionalidad</div>
        <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
          {grupos.map(g => {
            const semaforo = estadoGrupo(g);
            return (
              <div key={g.nombre} style={{ display: "flex", alignItems: "baseline", gap: 8 }}>
                <span style={{ width: 7, height: 7, borderRadius: "50%", flexShrink: 0,
                               alignSelf: "center", background: COLOR_TONO[semaforo.tono] }} />
                <span style={{ fontSize: 12, color: "var(--text)", flex: 1, minWidth: 0 }}>
                  {g.nombre}
                  <span style={{ display: "block", fontFamily: MONO, fontSize: 9, color: "var(--muted2)",
                                 overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
                    {g.variables.join(" · ")}
                  </span>
                </span>
                <span style={{ fontSize: 11, color: g.completo ? "var(--muted)" : "var(--muted2)",
                               textAlign: "right", maxWidth: "45%" }}>
                  {semaforo.texto}
                </span>
              </div>
            );
          })}
        </div>
        {!grupos.length && !leyendo && <Vacio>No se ha podido leer la configuración.</Vacio>}
        <div style={{ fontSize: 10, color: "var(--muted2)", marginTop: 10, lineHeight: 1.5 }}>
          Que algo esté sin configurar <strong>no es un fallo</strong>: media aplicación es
          opcional a propósito, y esta misma lista sirve para el kit de terceros
          (<code>docs/DESPLIEGUE.md</code>), que se instala a trozos. Lo que dice esta
          pantalla es qué parte NO va a funcionar, no qué está roto.
        </div>
        <div style={{ fontSize: 10, color: "var(--muted2)", marginTop: 6 }}>
          Nunca se enseña el valor de una variable, solo si está puesta.
          {cfg?.graph?.renovado && ` La sesión de Microsoft se renovó ${desdeHace(cfg.graph.renovado)}.`}
        </div>
      </div>
    </div>
  );
}

function Fila({ nombre, tono, detalle }) {
  return (
    <div style={{ display: "flex", alignItems: "baseline", gap: 8 }}>
      <span style={{ width: 7, height: 7, borderRadius: "50%", flexShrink: 0, alignSelf: "center",
                     background: COLOR_TONO[tono] }} />
      <span style={{ fontSize: 12, color: "var(--text)", minWidth: 170 }}>{nombre}</span>
      <span style={{ fontSize: 11, color: "var(--muted)", flex: 1, textAlign: "right" }}>{detalle}</span>
    </div>
  );
}
