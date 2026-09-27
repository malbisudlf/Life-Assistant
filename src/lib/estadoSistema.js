// Cómo se lee el estado del sistema para el semáforo. Va aparte de `dev.js` por lo mismo
// que `registro.js`: lo usan los dos lados —la pestaña Estado de la zona dev y la línea
// de ⚙ del dashboard—, y el dashboard no puede importar `dev.js` de forma estática sin
// meterlo entero en el chunk principal (ver el comentario de los imports de Dashboard.jsx).
//
// Antes el dashboard tenía su propia copia de esta lista de consultas, y ya se había
// separado de la buena: no guardaba `brief`, así que la línea de ⚙ decía «todo responde»
// con el resumen diario pausado mientras la zona dev lo pintaba en ámbar. Una sola lista.
import { API, authHeaders, apiFetch } from "./api";
import { juntarRegistro, RUTA_REGISTRO, RUTA_ERRORES_SEMANA } from "./registro";

// Junta lo que hace falta para el semáforo. Las llamadas van en paralelo: en serie serían
// siete idas y vueltas seguidas, y la primera ya mide lo que tarda en responder el backend.
//
// Todo esto pega contra el propio backend o contra Supabase, así que se puede refrescar
// solo sin que cueste un céntimo. Es la condición de la zona dev (docs/ZONA_DEV.md).
export async function leerEstadoSistema(agentId) {
  const reloj = () => (typeof performance !== "undefined" ? performance.now() : Date.now());
  const t0 = reloj();

  let backend = { ok: false, ms: null, version: null };
  try {
    const r = await fetch(`${API}/`);
    const ms = Math.round(reloj() - t0);
    let version = null;
    try { version = (await r.json())?.version || null; } catch { /* cuerpo raro: da igual */ }
    backend = { ok: r.ok, ms, version };
  } catch { /* sin red o backend caído: ok=false */ }

  const vacio = { backend, agente: null, registro: null, presencia: null, avisos: null,
                  gasto: null, brief: null, enviados: [], comprobado: Date.now() };
  if (!backend.ok) return vacio;

  const rutas = {
    agente:    `/agents/${agentId}`,
    registro:  RUTA_REGISTRO,
    erroresSemana: RUTA_ERRORES_SEMANA,
    presencia: "/presencia",
    brief:     "/brief/ajustes",
    avisos:    "/avisos/estado",
    gasto:     "/gasto?dias=30",
    enviados:  "/avisos/enviados",
  };
  const claves     = Object.keys(rutas);
  const respuestas = await Promise.all(
    claves.map(k => apiFetch(`${API}${rutas[k]}`, { headers: authHeaders() }).catch(() => null)),
  );

  const datos = { ...vacio };
  await Promise.all(respuestas.map(async (r, i) => {
    // Cada uno por su cuenta: que el gasto no responda no puede dejar sin agente al
    // panel. Lo que falle se queda en null, que es "no lo sé" y se pinta como tal.
    try { if (r?.ok) datos[claves[i]] = await r.json(); } catch { /* mejor esfuerzo */ }
  }));
  datos.enviados = datos.enviados?.avisos || [];
  datos.registro = juntarRegistro(datos.registro, datos.erroresSemana);
  delete datos.erroresSemana;
  return datos;
}
