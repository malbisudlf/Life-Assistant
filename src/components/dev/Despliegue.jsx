// ¿Entró la reconstrucción?
//
// Son tres despliegues independientes que nadie sincroniza —el add-on del Green, Vercel y
// el `main` de GitHub— y hasta ahora compararlos era abrir tres pestañas y mirar shas a
// ojo. No se hacía, y por eso el add-on sirvió durante días el código de otro día sin que
// nadie lo notara (CLAUDE.md, «Despliegue»).
//
// Esta pestaña SÍ reconstruye, desde septiembre de 2026: el add-on se lo pide al
// Supervisor él solo. Antes no podía, y el segundo paso —ir a la interfaz de HA y pulsar
// Reconstruir— se posponía, así que producción se quedaba atrás mientras el aviso del
// móvil daba el arreglo por desplegado. Lo que no hace es reconstruir sola: pregunta.
import { useState, useEffect, useCallback } from "react";

import { MONO, panelStyle, tituloStyle, COLOR_TONO, horaCorta, desdeHace,
         leerDespliegue, estadoDespliegue, shaCorto, COMMIT_FRONTEND,
         reconstruirAddon, esperarAlBackend } from "../../lib/dev";
import { Boton, Vacio } from "./ui";

// Cinco minutos, y solo si el backend tiene credencial de GitHub. Sin ella son 60
// peticiones/hora para toda la red de casa y una pestaña abierta las gasta sola.
const REFRESCO_MS = 5 * 60_000;

export default function Despliegue() {
  const [datos, setDatos]   = useState(null);
  const [error, setError]   = useState("");
  const [leyendo, setLeyendo] = useState(true);
  const [tic, setTic]       = useState(0);
  const [obra, setObra]     = useState("");   // qué está pasando con la reconstrucción

  useEffect(() => {
    let vivo = true;
    (async () => {
      try {
        const d = await leerDespliegue();
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

  // Reconstruir es sustituir el código que corre en producción, así que pregunta y dice
  // en la pregunta lo que va a pasar: el backend se para un par de minutos y con él el
  // dashboard entero.
  const reconstruir = useCallback(async () => {
    if (!window.confirm(
      "¿Reconstruir el add-on ahora?\n\n"
      + "Clona main y sustituye lo que está corriendo. El backend se para 1-2 minutos: "
      + "mientras tanto el dashboard no responde.")) return;
    setObra("lanzando…");
    try {
      const r = await reconstruirAddon();
      setObra("reconstruyendo… (1-2 min)");
      const fin = await esperarAlBackend({ antes: r.version_antes });
      // Tres finales distintos, y ninguno se puede decir con las palabras de otro. El de
      // en medio —volvió con el mismo sha— es el normal cuando ya estabas al día, y
      // durante un rato se enseñó como si hubiera fallado.
      setObra(
        fin.ok && fin.cambio  ? `listo · ahora sirve ${shaCorto(fin.version)}`
        : fin.ok              ? `listo · sigue sirviendo ${shaCorto(fin.version)} (ya estaba al día)`
        : fin.cayo            ? "se paró pero no ha vuelto en 3 min — míralo en Home Assistant"
        : "el backend no ha llegado a pararse: la reconstrucción no ha arrancado. "
          + "Suele ser que al add-on le faltan permisos (hassio_role) — mira la pestaña Logs");
      if (fin.ok) setTic(t => t + 1);
    } catch (e) {
      setObra(e.message || "no se ha podido lanzar");
    }
  }, []);

  const backend  = datos?.backend;
  const frontend = datos?.frontend;

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 14 }}>
      <div style={panelStyle}>
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 12 }}>
          <div style={{ ...tituloStyle, marginBottom: 0 }}>Qué código corre dónde</div>
          <div style={{ display: "flex", gap: 8, alignItems: "center" }}>
            {!autorefresco && !leyendo && (
              <span style={{ fontSize: 10, color: "var(--muted2)" }}>
                sin refresco automático (falta DEPLOY_GITHUB_TOKEN)
              </span>
            )}
            <Boton onClick={recargar} disabled={leyendo}>
              {leyendo ? "Mirando…" : "Actualizar"}
            </Boton>
            <Boton onClick={reconstruir} tono="peligro" disabled={!!obra && !obra.startsWith("listo")}
                   title="Clona main y sustituye el backend que está corriendo">
              Reconstruir
            </Boton>
          </div>
        </div>

        {!!obra && (
          <div style={{ fontSize: 11, color: "var(--accent)", marginBottom: 10 }}>{obra}</div>
        )}

        {error && <Vacio>No se pudo consultar: {error}</Vacio>}
        {!error && datos?.github?.ok === false && (
          <Vacio>No se ha podido preguntar a GitHub: {datos.github.motivo}</Vacio>
        )}

        {!error && datos?.main && (
          <div style={{ display: "flex", flexDirection: "column", gap: 10 }}>
            <Lado nombre="Backend (add-on del Green)" lado={backend}
                  nota="se despliega con el botón Reconstruir, nunca solo" />
            <Lado nombre="Frontend (Vercel)" lado={frontend}
                  nota="se despliega solo al hacer push a main" />
            <div style={{ borderTop: "0.5px solid var(--border)", paddingTop: 10 }}>
              <div style={{ display: "flex", alignItems: "baseline", gap: 8 }}>
                <span style={{ fontSize: 12, color: "var(--text)", minWidth: 190 }}>
                  Último commit de main
                </span>
                <span style={{ fontFamily: MONO, fontSize: 11, color: "var(--muted)" }}>
                  {shaCorto(datos.main.sha)}
                </span>
                <span style={{ fontSize: 11, color: "var(--muted)", flex: 1, textAlign: "right" }}>
                  {datos.main.mensaje} · {desdeHace(datos.main.fecha) || horaCorta(datos.main.fecha)}
                </span>
              </div>
            </div>
          </div>
        )}
      </div>

      {!!backend?.commits?.length && (
        <div style={panelStyle}>
          <div style={tituloStyle}>Lo que le falta al backend</div>
          <div style={{ display: "flex", flexDirection: "column", gap: 5 }}>
            {backend.commits.map(c => (
              <div key={c.sha} style={{ display: "flex", alignItems: "baseline", gap: 8 }}>
                <span style={{ fontFamily: MONO, fontSize: 10, color: "var(--muted2)" }}>
                  {shaCorto(c.sha)}
                </span>
                <span style={{ fontSize: 11, color: "var(--muted)", flex: 1, minWidth: 0,
                               overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
                  {c.mensaje}
                </span>
                <span style={{ fontFamily: MONO, fontSize: 10, color: "var(--muted2)" }}>
                  {horaCorta(c.fecha)}
                </span>
              </div>
            ))}
          </div>
          {backend.detras > backend.commits.length && (
            <div style={{ fontSize: 10, color: "var(--muted2)", marginTop: 8 }}>
              …y {backend.detras - backend.commits.length} más.
            </div>
          )}
          <div style={{ fontSize: 10, color: "var(--muted2)", marginTop: 10, lineHeight: 1.5 }}>
            Para que entren, el botón <strong>Reconstruir</strong> de arriba: el add-on se lo
            pide al Supervisor él solo y clona <code>main</code>. Si responde que no puede,
            el <code>config.yaml</code> del Green es el viejo — ese fichero se copia a mano
            por Samba y no sale de git.
          </div>
        </div>
      )}

      <div style={{ ...panelStyle, fontSize: 10, color: "var(--muted2)", lineHeight: 1.6 }}>
        El sha del frontend va horneado en este bundle ({shaCorto(COMMIT_FRONTEND)}), porque
        el despliegue de Vercel no pasa por el backend y nadie más puede contarlo. En
        desarrollo pone «dev»: lo que corre es lo que hay en el disco, y eso no tiene sha.
      </div>
    </div>
  );
}

// Una línea por sitio donde corre código. El sha va siempre, incluso cuando está al día:
// es lo que se compara a ojo con la pestaña de GitHub cuando algo no cuadra.
function Lado({ nombre, lado, nota }) {
  const semaforo = estadoDespliegue(lado);
  return (
    <div style={{ display: "flex", alignItems: "baseline", gap: 8 }}>
      <span style={{ width: 7, height: 7, borderRadius: "50%", flexShrink: 0, alignSelf: "center",
                     background: COLOR_TONO[semaforo.tono] }} />
      <span style={{ fontSize: 12, color: "var(--text)", minWidth: 190 }}>{nombre}</span>
      <span style={{ fontSize: 11, color: "var(--muted)", flex: 1, textAlign: "right" }}>
        {semaforo.texto}
        <span style={{ display: "block", fontSize: 10, color: "var(--muted2)" }}>{nota}</span>
      </span>
    </div>
  );
}
