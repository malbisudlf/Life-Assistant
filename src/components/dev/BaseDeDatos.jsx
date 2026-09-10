// Qué hay en la base de datos y, sobre todo, qué migraciones faltan por aplicar.
//
// Las migraciones se pegan a mano en el editor SQL de Supabase, así que se olvidan:
// `20260824_salud_ajustes` estuvo un mes sin aplicar, con `PATCH /health/ajustes`
// respondiendo 502 y la copia de seguridad muriendo entera al llegar a esa tabla. Nadie
// tenía forma de verlo sin comparar a ojo un directorio con un editor SQL.
//
// Lo aplicado sale de la tabla `migraciones_aplicadas` y lo esperado del propio
// repositorio: ninguna de las dos listas se mantiene a mano.
import { useState, useEffect, useCallback } from "react";

import { MONO, panelStyle, tituloStyle, COLOR_TONO, horaCorta,
         leerBd, estadoTabla, resumenMigraciones } from "../../lib/dev";
import { Boton, Vacio } from "./ui";

export default function BaseDeDatos() {
  const [bd, setBd]           = useState(null);
  const [error, setError]     = useState("");
  const [leyendo, setLeyendo] = useState(true);
  const [tic, setTic]         = useState(0);

  useEffect(() => {
    let vivo = true;
    (async () => {
      try {
        const d = await leerBd();
        if (vivo) { setBd(d); setError(""); }
      } catch (e) {
        if (vivo) setError(e.message || "no se pudo consultar");
      } finally {
        if (vivo) setLeyendo(false);
      }
    })();
    return () => { vivo = false; };
  }, [tic]);

  // Sin refresco automático, y no por dinero: son treinta y tantas consultas de cuenta a
  // Supabase, que es plan gratuito con cuota mensual. Esto se mira cuando se acaba de
  // aplicar una migración, no cada minuto.
  const recargar = useCallback(() => { setLeyendo(true); setTic(t => t + 1); }, []);

  const resumen  = resumenMigraciones(bd);
  const pendientes = (bd?.migraciones || []).filter(m => !m.puesta);
  // Alfabéticas y no en el orden del backend (que va por migración): aquí se viene a
  // buscar una tabla concreta entre treinta y pico, y para eso el orden útil es el del
  // abecedario.
  const tablas   = [...(bd?.tablas || [])].sort((a, b) => a.tabla.localeCompare(b.tabla));
  const faltando = tablas.filter(t => t.existe === false);

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 14 }}>
      <div style={panelStyle}>
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 12 }}>
          <div style={{ ...tituloStyle, marginBottom: 0 }}>Migraciones</div>
          <Boton onClick={recargar} disabled={leyendo}>
            {leyendo ? "Mirando…" : "Actualizar"}
          </Boton>
        </div>

        {error && <Vacio>No se pudo consultar: {error}</Vacio>}

        {!error && (
          <div style={{ display: "flex", alignItems: "baseline", gap: 8 }}>
            <span style={{ width: 7, height: 7, borderRadius: "50%", flexShrink: 0,
                           alignSelf: "center", background: COLOR_TONO[resumen.tono] }} />
            <span style={{ fontSize: 12, color: "var(--text)" }}>{resumen.texto}</span>
          </div>
        )}

        {!!pendientes.length && (
          <div style={{ marginTop: 12, display: "flex", flexDirection: "column", gap: 5 }}>
            {pendientes.map(m => (
              <div key={m.nombre} style={{ fontFamily: MONO, fontSize: 11, color: "#c9736b" }}>
                supabase/migrations/{m.nombre}.sql
              </div>
            ))}
            <div style={{ fontSize: 10, color: "var(--muted2)", marginTop: 4, lineHeight: 1.5 }}>
              Se aplican pegándolas en el editor SQL de Supabase. Cada una termina
              insertándose en <code>migraciones_aplicadas</code>: si aplicas una y aquí
              sigue saliendo, es que le falta esa línea al fichero.
            </div>
          </div>
        )}

        {!error && bd && !bd.migraciones && (
          <div style={{ fontSize: 11, color: "var(--muted)", marginTop: 10, lineHeight: 1.5 }}>
            {bd.motivo || "No se ha podido comprobar."}
            {bd.motivo?.includes(bd.registro) && (
              <> Es la primera: pégala en Supabase y esta pestaña empezará a saber lo que
              hay puesto.</>
            )}
          </div>
        )}
      </div>

      <div style={panelStyle}>
        <div style={{ ...tituloStyle, display: "flex", justifyContent: "space-between" }}>
          <span>Tablas</span>
          <span>{tablas.length ? `${tablas.length} conocidas` : ""}</span>
        </div>

        {!!faltando.length && (
          <div style={{ fontSize: 11, color: "#c9736b", marginBottom: 10 }}>
            {faltando.length === 1 ? "Falta una tabla" : `Faltan ${faltando.length} tablas`}:
            todo lo que dependa de {faltando.length === 1 ? "ella" : "ellas"} responde 502.
          </div>
        )}

        <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(280px, 1fr))", gap: "6px 20px" }}>
          {tablas.map(t => {
            const semaforo = estadoTabla(t);
            return (
              <div key={t.tabla} style={{ display: "flex", alignItems: "baseline", gap: 8 }}>
                <span style={{ width: 6, height: 6, borderRadius: "50%", flexShrink: 0,
                               alignSelf: "center", background: COLOR_TONO[semaforo.tono] }} />
                <span style={{ fontFamily: MONO, fontSize: 11, color: "var(--text)", flex: 1,
                               minWidth: 0, overflow: "hidden", textOverflow: "ellipsis" }}>
                  {t.tabla}
                </span>
                <span style={{ fontSize: 10, color: "var(--muted)", fontFamily: MONO }}>
                  {semaforo.texto}
                </span>
              </div>
            );
          })}
        </div>

        {!tablas.length && !leyendo && <Vacio>No se ha podido leer ninguna tabla.</Vacio>}

        <div style={{ fontSize: 10, color: "var(--muted2)", marginTop: 12, lineHeight: 1.5 }}>
          Cero filas no es un error: hay tablas que solo se llenan cuando pasa algo (una
          avería, un job, un cobro). Lo que sí lo es, siempre, es una que no existe.
        </div>
      </div>

      {!!bd?.migraciones?.length && (
        <div style={panelStyle}>
          <div style={tituloStyle}>Todas las migraciones</div>
          <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(320px, 1fr))", gap: "4px 20px" }}>
            {bd.migraciones.map(m => (
              <div key={m.nombre} style={{ display: "flex", alignItems: "baseline", gap: 8 }}>
                <span style={{ width: 6, height: 6, borderRadius: "50%", flexShrink: 0, alignSelf: "center",
                               background: COLOR_TONO[m.huerfana ? "accent" : m.puesta ? "green" : "red"] }} />
                <span style={{ fontFamily: MONO, fontSize: 10, color: "var(--muted)", flex: 1,
                               minWidth: 0, overflow: "hidden", textOverflow: "ellipsis" }}>
                  {m.nombre}
                </span>
                <span style={{ fontSize: 10, color: "var(--muted2)", fontFamily: MONO }}>
                  {m.huerfana ? "no está en el repo" : m.puesta ? horaCorta(m.aplicada) || "puesta" : "sin aplicar"}
                </span>
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}
