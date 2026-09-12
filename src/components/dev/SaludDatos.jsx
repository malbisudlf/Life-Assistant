// ¿Llegan los datos del reloj, de quién y qué falta?
//
// `GET /health/diagnostico` ya contestaba esto desde agosto, pero solo desde una consola:
// había que llamarlo a mano y leer un JSON de cincuenta métricas. Aquí es una tabla.
//
// La fila que de verdad importa no es ninguna métrica sino la de arriba: **quién ha dejado
// de escribir**. Health Auto Export y el Atajo de iOS escriben en la misma tabla, así que
// sin mirar la fuente, que una de las dos se caiga se ve exactamente igual que un día sin
// datos — y eso es lo que dejó al Watch días sin sincronizar sin que se notara.
import { useState, useEffect, useCallback } from "react";

import { MONO, panelStyle, tituloStyle, COLOR_TONO,
         leerDiagnostico, estadoMetrica, estadoFuente } from "../../lib/dev";
import { Boton, Vacio } from "./ui";

const VENTANAS = [7, 30, 90];

export default function SaludDatos() {
  const [dias, setDias]       = useState(30);
  const [datos, setDatos]     = useState(null);
  const [error, setError]     = useState("");
  const [leyendo, setLeyendo] = useState(true);
  const [tic, setTic]         = useState(0);

  useEffect(() => {
    let vivo = true;
    (async () => {
      try {
        const d = await leerDiagnostico(dias);
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

  const fuentes  = Object.entries(datos?.fuentes || {});
  const metricas = Object.entries(datos?.metricas || {});
  // Lo que peor está, arriba: en cincuenta métricas, las tres que llevan una semana sin
  // llegar no se encuentran leyendo por orden alfabético.
  const ordenadas = [...metricas].sort(
    ([, a], [, b]) => (b.dias_atras ?? 9999) - (a.dias_atras ?? 9999),
  );

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 14 }}>
      <div style={{ ...panelStyle, display: "flex", gap: 10, alignItems: "center", flexWrap: "wrap" }}>
        <span style={{ ...tituloStyle, marginBottom: 0 }}>Ventana</span>
        {VENTANAS.map(d => (
          <Boton key={d} onClick={() => { setLeyendo(true); setDias(d); }}
                 tono={d === dias ? "acento" : "normal"}>
            {d} días
          </Boton>
        ))}
        <span style={{ flex: 1 }} />
        <Boton onClick={recargar} disabled={leyendo}>{leyendo ? "Mirando…" : "Actualizar"}</Boton>
      </div>

      {error && <div style={panelStyle}><Vacio>No se pudo consultar: {error}</Vacio></div>}

      <div style={panelStyle}>
        <div style={tituloStyle}>Quién está escribiendo</div>
        {!fuentes.length && !leyendo && !error && (
          <Vacio>Ninguna fila de la ventana dice de dónde vino.</Vacio>
        )}
        <div style={{ display: "flex", flexDirection: "column", gap: 7 }}>
          {fuentes.map(([nombre, f]) => {
            const semaforo = estadoFuente(f.ultima_escritura);
            return (
              <div key={nombre} style={{ display: "flex", alignItems: "baseline", gap: 8 }}>
                <span style={{ width: 7, height: 7, borderRadius: "50%", flexShrink: 0,
                               alignSelf: "center", background: COLOR_TONO[semaforo.tono] }} />
                <span style={{ fontFamily: MONO, fontSize: 12, color: "var(--text)", minWidth: 180 }}>
                  {nombre}
                </span>
                <span style={{ fontSize: 11, color: "var(--muted)", flex: 1, textAlign: "right" }}>
                  última escritura {semaforo.texto}
                </span>
              </div>
            );
          })}
        </div>
        {!!datos?.sin_fuente && (
          <div style={{ fontSize: 10, color: "var(--muted2)", marginTop: 8 }}>
            {datos.sin_fuente} filas sin fuente: son anteriores a que se guardara, y no se
            les puede inventar una.
          </div>
        )}
      </div>

      <div style={{ ...panelStyle, padding: 0 }}>
        <div style={{ ...tituloStyle, padding: "14px 16px 8px" }}>
          Por métrica ({metricas.length})
        </div>
        {!metricas.length && !leyendo && !error && (
          <Vacio>No hay ni una fila en esta ventana. Eso no es un hueco: es que no llega nada.</Vacio>
        )}
        {ordenadas.map(([nombre, m]) => {
          const semaforo = estadoMetrica(m);
          return (
            <div key={nombre} style={{
              display: "flex", gap: 10, alignItems: "baseline", padding: "5px 14px",
              borderBottom: "0.5px solid var(--border)", fontSize: 11,
            }}>
              <span style={{ width: 7, height: 7, borderRadius: "50%", flexShrink: 0,
                             alignSelf: "center", background: COLOR_TONO[semaforo.tono] }} />
              <span style={{ fontFamily: MONO, fontSize: 12, color: "var(--text)", minWidth: 210,
                             overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
                {nombre}
              </span>
              <span style={{ color: "var(--muted2)", width: 150, flexShrink: 0, fontSize: 10 }}>
                {(m.fuentes || []).join(", ") || "sin fuente"}
              </span>
              <span style={{ color: "var(--muted2)", width: 90, flexShrink: 0, fontSize: 10 }}>
                {m.dias_con_dato} con dato
              </span>
              <span style={{ color: "var(--muted)", flex: 1, textAlign: "right" }}>
                {semaforo.texto}
                {!!m.filas_sin_medida && (
                  <span style={{ color: "var(--muted2)", fontSize: 10 }}>
                    {" "}· {m.filas_sin_medida} de relleno
                  </span>
                )}
              </span>
            </div>
          );
        })}
      </div>

      <div style={{ fontSize: 10, color: "var(--muted2)" }}>
        Una fila de relleno (los ceros que manda el Atajo cuando no hay medida) no tapa un
        hueco: es un hueco con una fila encima, y por eso se cuentan aparte. Los huecos solo
        se cuentan desde el primer día que hubo dato — antes de empezar a medir no hay nada
        que echar en falta.
      </div>
    </div>
  );
}
