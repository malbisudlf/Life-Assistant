// Lo que la zona de desarrollo sabe sin ser una pantalla: los estilos que la distinguen
// del dashboard, cómo se lee el estado del sistema y cómo se resume en una línea.
//
// Vive aquí y no junto a los componentes por la regla de siempre (CLAUDE.md): un fichero
// .jsx no puede exportar más que componentes o se rompe el refresco en caliente, y
// además el resumen lo necesita también el panel ⚙ del dashboard.
import { API, authHeaders, apiFetch } from "./api";
import { isoToDdMmYyyy } from "./helpers";

export const MONO = "'DM Mono', ui-monospace, SFMono-Regular, Menlo, monospace";

// Los cuatro tonos del semáforo. El texto dice siempre qué pasa: el color no puede ser
// la única señal.
export const COLOR_TONO = {
  green:  "var(--green)",
  accent: "var(--accent)",
  red:    "#d4645a",
  muted:  "var(--muted2)",
};

export const panelStyle = {
  background:   "var(--surface)",
  border:       "0.5px solid var(--border)",
  borderRadius: 10,
  padding:      16,
};

export const tituloStyle = {
  fontSize:      10,
  letterSpacing: "0.14em",
  textTransform: "uppercase",
  color:         "var(--muted2)",
  marginBottom:  10,
};

export const inputStyle = {
  padding:      "7px 10px",
  background:   "var(--surface2)",
  border:       "0.5px solid var(--border2)",
  borderRadius: 6,
  color:        "var(--text)",
  fontSize:     12,
  fontFamily:   MONO,
};

export const botonStyle = {
  padding:      "6px 11px",
  background:   "transparent",
  border:       "0.5px solid var(--border2)",
  borderRadius: 6,
  color:        "var(--muted)",
  fontSize:     11,
  cursor:       "pointer",
  fontFamily:   "'DM Sans', sans-serif",
};

// Hora corta para las tablas: el día se da por sabido salvo que la fila sea de otro.
export function horaCorta(iso) {
  if (!iso) return "";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return "";
  // A mano y no con toLocaleDateString: el relleno con ceros de `2-digit` depende de los
  // datos de idioma del entorno, y en una tabla monoespaciada una fila más corta que las
  // demás descoloca la columna entera.
  const dd = (n) => String(n).padStart(2, "0");
  const hora = `${dd(d.getHours())}:${dd(d.getMinutes())}:${dd(d.getSeconds())}`;
  if (d.toDateString() === new Date().toDateString()) return hora;
  return `${dd(d.getDate())}/${dd(d.getMonth() + 1)} ${hora}`;
}

// "hace 3 min". Sirve para todo lo que aquí se pregunta como "¿cuándo fue la última vez?".
export function desdeHace(iso) {
  if (!iso) return null;
  const t = new Date(iso).getTime();
  if (Number.isNaN(t)) return null;
  const seg = Math.max(0, Math.round((Date.now() - t) / 1000));
  if (seg < 60)    return `hace ${seg}s`;
  if (seg < 3600)  return `hace ${Math.round(seg / 60)} min`;
  if (seg < 86400) return `hace ${Math.round(seg / 3600)} h`;
  return `hace ${Math.round(seg / 86400)} d`;
}

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
    registro:  "/logs?dias=7&limite=50",
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
  return datos;
}

// Las filas del semáforo que salen de lo que devuelve `leerEstadoSistema`. Las que
// dependen de lo que el dashboard ya tiene cargado (Outlook, el Watch, el entrenamiento)
// se le pasan aparte: volver a pedirlas sería repetir media carga del dashboard.
export function filasDeEstado(sys) {
  const filas = [];

  const b = sys?.backend;
  filas.push({
    nombre: "Backend",
    tono: !sys ? "muted" : b?.ok ? (b.ms > 3000 ? "accent" : "green") : "red",
    detalle: !sys ? "sin comprobar"
      : !b?.ok ? "no responde"
      : b.ms > 3000 ? `despierto tras ${(b.ms / 1000).toFixed(1)}s (arranque en frío)`
      : `despierto · ${b.ms} ms`,
  });

  const ag = sys?.agente;
  filas.push({
    nombre: "Agente PC",
    tono: !sys ? "muted" : !ag ? "muted" : ag.offline === false ? "green" : "muted",
    detalle: !sys ? "sin comprobar"
      : !ag ? "sin respuesta"
      : ag.exists === false ? "nunca se ha registrado"
      : ag.offline === false ? `online${ag.hostname ? ` · ${ag.hostname}` : ""}`
      : `apagado (visto hace ${Math.floor((ag.silence_seconds ?? 0) / 60)} min)`,
  });

  // Un dato de presencia caducado se muestra igual pero diciendo de cuándo es: no saber
  // dónde estás y creer que sigues donde estabas hace seis horas son cosas distintas.
  const pre = sys?.presencia;
  filas.push({
    nombre: "Presencia",
    tono: !sys ? "muted" : !pre?.conocida ? "muted" : pre.vigente ? "green" : "accent",
    detalle: !sys ? "sin comprobar"
      : !pre ? "sin respuesta del backend"
      : !pre.conocida ? "HA no ha reportado nunca"
      : `${pre.en_casa ? "en casa" : pre.zona || "fuera"} · ${
          pre.hace_minutos == null ? "sin fecha"
          : pre.hace_minutos < 2 ? "ahora mismo"
          : pre.hace_minutos < 60 ? `hace ${pre.hace_minutos} min`
          : `hace ${Math.floor(pre.hace_minutos / 60)} h`
        }${pre.vigente ? "" : " (caducado)"}`,
  });

  // Apagado a propósito y roto se parecen mucho desde fuera —en los dos casos el correo
  // no llega—, así que esta fila tiene que decir cuál de los dos es.
  const brief = sys?.brief;
  filas.push({
    nombre: "Resumen diario",
    tono: !brief ? "muted" : !brief.activo ? "muted" : brief.pausado ? "accent" : "green",
    detalle: !brief ? "sin comprobar"
      : !brief.activo ? "desactivado"
      : brief.pausado ? `pausado hasta el ${isoToDdMmYyyy(brief.pausado_hasta)}`
      : brief.enviado_hoy === true ? "activo · el de hoy ya ha salido"
      : brief.enviado_hoy === false ? "activo · hoy aún no ha salido"
      : "activo",
  });

  // El canal del móvil se cae en silencio (basta con que HA deje de sondear), así que
  // tiene que verse desde aquí: que el aviso salga y que llegue A TIEMPO no son la misma
  // pregunta.
  const av = sys?.avisos;
  filas.push({
    nombre: "Avisos",
    tono: !av ? "muted" : !av.activo ? "muted" : av.canal === "movil" ? "green" : "accent",
    detalle: !av ? "sin comprobar"
      : !av.activo ? "al correo (móvil desactivado)"
      : av.canal === "movil"
        ? `al móvil · HA sondeó hace ${av.sondeo_hace_segundos ?? 0} s`
        : av.sondeo_hace_segundos == null
          ? "al correo · HA no los recoge todavía"
          : `al correo · HA lleva ${Math.floor(av.sondeo_hace_segundos / 60)} min sin recogerlos`,
  });

  // Las demás filas dicen si algo RESPONDE; ésta dice si algo ha FALLADO, que es distinto
  // y es lo que faltaba: el 409 de la ingesta se registró durante días sin que nadie lo
  // viera, en el stdout de una máquina que se apagaba sola.
  const reg = sys?.registro;
  filas.push({
    nombre: "Registro",
    tono: !reg ? "muted" : reg.errores ? "red" : reg.entradas.length ? "accent" : "green",
    detalle: !reg ? "sin comprobar"
      : reg.errores ? `${reg.errores} ${reg.errores === 1 ? "error" : "errores"} en 7 días`
      : reg.entradas.length ? `${reg.entradas.length} avisos en 7 días`
      : "sin incidencias en 7 días",
  });

  // El % cacheado va al lado del euro porque es LA palanca de coste: si se hunde, algo
  // que cambia a menudo se ha colado delante del prompt.
  const gas = sys?.gasto;
  filas.push({
    nombre: "Coste del modelo",
    tono: !gas ? "muted" : gas.total.euros_incompleto ? "accent" : "green",
    detalle: !gas ? "sin comprobar"
      : gas.total.llamadas === 0 ? "sin gasto en 30 días"
      : `${gas.total.euros.toFixed(2)} € en 30 días · ${gas.total.llamadas} llamadas`
        + (gas.cacheado_pct != null ? ` · ${gas.cacheado_pct}% cacheado` : "")
        + (gas.total.euros_incompleto ? " · falta tarifa de algún modelo" : ""),
  });

  return filas;
}

// Una frase para el resumen del panel ⚙: lo peor que haya, o que todo responde. Lo peor
// primero y no un recuento, porque lo que se quiere saber de un vistazo no es cuántas
// cosas van bien sino si hay algo roto.
export function resumenEstado(sys, extra = []) {
  const filas = [...filasDeEstado(sys), ...extra];
  const roto  = filas.find(f => f.tono === "red");
  if (roto) return { tono: "red", texto: `${roto.nombre}: ${roto.detalle}` };
  const ojo = filas.find(f => f.tono === "accent");
  if (ojo) return { tono: "accent", texto: `${ojo.nombre}: ${ojo.detalle}` };
  if (!sys) return { tono: "muted", texto: "sin comprobar" };
  return { tono: "green", texto: "todo responde" };
}
