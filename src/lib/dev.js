// Lo que la zona de desarrollo sabe sin ser una pantalla: los estilos que la distinguen
// del dashboard, cómo se lee el estado del sistema y cómo se resume en una línea.
//
// Vive aquí y no junto a los componentes por la regla de siempre (CLAUDE.md): un fichero
// .jsx no puede exportar más que componentes o se rompe el refresco en caliente, y
// además el resumen lo necesita también el panel ⚙ del dashboard.
import { API, authHeaders, jsonHeaders, apiFetch } from "./api";
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

// ── FASE 2: DESPLIEGUE ────────────────────────────────────────────────────────

// De qué commit se construyó este bundle. Lo hornea vite.config.js con lo que Vercel pone
// en el entorno del build; en local es "dev" y no se puede comparar con nada.
export const COMMIT_FRONTEND = import.meta.env.VITE_COMMIT_SHA || "dev";

// Un sha para leerlo de un vistazo. Siete caracteres es lo que enseña git y lo que se
// puede comparar a ojo con la pestaña de GitHub abierta al lado.
export function shaCorto(sha) {
  if (!sha || sha === "desconocida" || sha === "dev") return sha || "—";
  return String(sha).slice(0, 7);
}

// El semáforo de un lado del despliegue (backend o frontend) a partir de lo que devuelve
// `GET /dev/despliegue`. Lo que no se sabe se dice; nunca se da por al día.
export function estadoDespliegue(lado) {
  if (!lado)             return { tono: "muted", texto: "sin comprobar" };
  if (lado.sha === "dev") return { tono: "muted", texto: "en local, sin sha que comparar" };
  if (!lado.conocido) {
    return { tono: "accent", texto: lado.motivo || "no se ha podido comparar con main" };
  }
  if (lado.al_dia) return { tono: "green", texto: `al día con main (${shaCorto(lado.sha)})` };
  const n = lado.detras;
  return {
    tono: "red",
    texto: `${n} commit${n === 1 ? "" : "s"} por desplegar (sirve ${shaCorto(lado.sha)})`,
  };
}

// ── FASE 2: PROGRAMADOS ───────────────────────────────────────────────────────

// El mismo margen que usa el backend (PROGRAMADO_MARGEN). GitHub retrasa los crons cuando
// tiene cola, y la revisión nocturna no corre las noches sin commits: con menos margen
// esto estaría en rojo media semana y dejaría de mirarse.
export const MARGEN_PROGRAMADO = 2;

export function textoCada(horas) {
  if (!horas) return "";
  if (horas % 168 === 0) return horas === 168 ? "semana" : `${horas / 168} semanas`;
  if (horas % 24 === 0)  return horas === 24 ? "día" : `${horas / 24} días`;
  return `${horas} h`;
}

// Qué significa el último run de un workflow. Son dos preguntas y no una: si la última
// vez FALLÓ y si ha corrido CUANDO tocaba. La copia de seguridad de Supabase estuvo meses
// contestando "sí" a la segunda y "no" a la primera, y por mirar solo una no lo vio nadie.
export function estadoWorkflow(wf, ahora = Date.now()) {
  if (!wf) return { tono: "muted", texto: "sin comprobar" };
  if (!wf.run) {
    return { tono: "muted", texto: wf.motivo || "no ha corrido nunca" };
  }
  const { estado, resultado, cuando } = wf.run;
  const hace  = cuando ? (ahora - new Date(cuando).getTime()) / 3600000 : null;
  const desde = desdeHace(cuando) || "sin fecha";

  if (estado && estado !== "completed") return { tono: "accent", texto: `corriendo (${desde})` };
  if (resultado === "failure" || resultado === "timed_out") {
    return { tono: "red", texto: `falló ${desde}` };
  }
  if (resultado && resultado !== "success") {
    // "cancelled", "skipped", "startup_failure": ni bien ni mal, pero no es un éxito y
    // no puede pintarse en verde.
    return { tono: "accent", texto: `${resultado} ${desde}` };
  }
  // Corrió bien, pero ¿hace cuánto? Un cron que dejó de dispararse no falla: calla.
  if (wf.cada_horas && hace != null && hace > wf.cada_horas * MARGEN_PROGRAMADO) {
    return { tono: "red", texto: `bien, pero la última fue ${desde} (toca cada ${textoCada(wf.cada_horas)})` };
  }
  return { tono: "green", texto: `bien ${desde}` };
}

// El semáforo de un sondeo. `margen` es cuánto se le tolera sin dar señales: los sondeos
// de HA pasan cada 15-60 s, así que cinco minutos son varios perdidos seguidos; el del
// agente PC no, porque el PC está apagado la mayor parte del día y eso es lo normal.
export function estadoSondeo(sondeo, procesoDesdeHace = null) {
  if (!sondeo) return { tono: "muted", texto: "sin comprobar" };
  const seg = sondeo.hace_segundos;
  if (seg == null) {
    // Un backend recién arrancado no ha visto sondear a nadie todavía, y eso no es que
    // nadie sondee. Decirlo evita diez filas en rojo tras cada reconstrucción.
    if (procesoDesdeHace != null && procesoDesdeHace < 600) {
      return { tono: "muted",
               texto: `sin datos aún (el backend lleva ${enPieDesde(procesoDesdeHace)} en pie)` };
    }
    return { tono: "accent", texto: "no ha sondeado desde que arrancó el backend" };
  }
  const texto = seg < 60 ? `hace ${seg}s`
    : seg < 3600 ? `hace ${Math.round(seg / 60)} min`
    : `hace ${Math.round(seg / 3600)} h`;
  if (sondeo.opcional) return { tono: seg > 86400 ? "muted" : "green", texto };
  return { tono: seg > 600 ? "red" : seg > 300 ? "accent" : "green", texto };
}

// Los sondeos que solo pasan cuando algo está encendido: el PC no está siempre puesto, y
// pintar en rojo que su agente lleva horas sin pedir jobs sería llamar avería a la noche.
export const SONDEOS_OPCIONALES = ["/jobs/pending", "/llamada/pendiente"];

// Cuánto lleva el backend en pie, en las mismas palabras en los dos sitios donde se dice.
// Con dos redondeos distintos, la misma pantalla llegó a decir "1 min" arriba y "0 min"
// abajo — y una pantalla que se contradice a sí misma no se cree en lo demás.
export function enPieDesde(segundos) {
  if (segundos == null) return "un rato";
  const min = Math.round(segundos / 60);
  return min < 1 ? "menos de un minuto" : `${min} min`;
}

// Junta lo que hace falta para la pestaña de programados: una llamada por bloque, en
// paralelo, y todo contra el propio backend (es decir, gratis: se puede refrescar solo).
export async function leerCrons() {
  const r = await apiFetch(`${API}/dev/crons`, { headers: authHeaders() });
  if (!r.ok) throw new Error(`el backend respondió ${r.status}`);
  const datos = await r.json();
  return {
    ...datos,
    sondeos: (datos.sondeos || []).map(s => ({ ...s, opcional: SONDEOS_OPCIONALES.includes(s.ruta) })),
  };
}

export async function leerDespliegue() {
  const sha = COMMIT_FRONTEND === "dev" ? "" : COMMIT_FRONTEND;
  const r = await apiFetch(`${API}/dev/despliegue${sha ? `?frontend=${encodeURIComponent(sha)}` : ""}`,
                           { headers: authHeaders() });
  if (!r.ok) throw new Error(`el backend respondió ${r.status}`);
  const datos = await r.json();
  // El backend no puede saber que estamos en local: lo sabe el bundle, y de aquí sale el
  // "en local, sin sha que comparar" en vez de un hueco sin explicación.
  if (!sha) datos.frontend = { sha: "dev", conocido: false, motivo: "en local" };
  return datos;
}

// ── FASE 2: BASE DE DATOS ─────────────────────────────────────────────────────

// El semáforo de una tabla. Cero filas y "no lo sé" no se pintan igual: una tabla vacía
// puede ser correcta (nadie ha guardado nada todavía), pero una que no responde no dice
// nada de sus datos.
export function estadoTabla(t) {
  if (!t)              return { tono: "muted", texto: "sin comprobar" };
  if (t.existe === false) return { tono: "red", texto: `no existe · falta ${t.migracion}` };
  if (t.existe == null)   return { tono: "accent", texto: t.motivo || "no se ha podido consultar" };
  if (t.filas == null)    return { tono: "accent", texto: "existe, sin cuenta de filas" };
  return { tono: t.filas ? "green" : "muted", texto: `${t.filas.toLocaleString("es-ES")} filas` };
}

// Lo que resume la pestaña en una línea: cuántas migraciones faltan por aplicar. Es LA
// pregunta, y la respuesta tiene que caber antes de mirar la tabla entera.
export function resumenMigraciones(bd) {
  if (!bd) return { tono: "muted", texto: "sin comprobar" };
  if (!bd.migraciones) {
    return { tono: "accent", texto: bd.motivo || "no se ha podido comprobar" };
  }
  const faltan = bd.migraciones.filter(m => !m.puesta);
  if (!faltan.length) return { tono: "green", texto: "todas aplicadas" };
  return {
    tono: "red",
    texto: `${faltan.length} sin aplicar: ${faltan.map(m => m.nombre).join(", ")}`,
  };
}

export async function leerBd() {
  const r = await apiFetch(`${API}/dev/bd`, { headers: authHeaders() });
  if (!r.ok) throw new Error(`el backend respondió ${r.status}`);
  return r.json();
}

// ── FASE 2: CONFIGURACIÓN ─────────────────────────────────────────────────────

// Un grupo de variables. "Sin configurar" NO es un error: la mitad de este proyecto es
// opcional y hay instalaciones (el kit de docs/DESPLIEGUE.md) que no quieren la mitad de
// las cosas. Rojo sería mentir; lo que hace falta es que se vea qué falta.
export function estadoGrupo(g) {
  if (!g)         return { tono: "muted", texto: "sin comprobar" };
  if (g.completo) return { tono: "green", texto: "configurado" };
  return { tono: "muted", texto: `falta ${g.faltan.join(", ")}` };
}

// La sesión de Microsoft es la única credencial que caduca sola, y cuando su refresh
// muere el calendario deja de cargar sin que nada más se entere.
export function estadoGraph(graph) {
  if (!graph)                return { tono: "muted", texto: "sin comprobar" };
  if (graph.conectado == null) return { tono: "accent", texto: graph.motivo || "no se ha podido consultar" };
  if (!graph.conectado)      return { tono: "accent", texto: graph.motivo || "sin conectar" };
  if (!graph.con_refresco) {
    // Sin refresh token, la sesión muere cuando expire el access y hay que volver a pasar
    // por el login de Microsoft a mano.
    return { tono: "red", texto: "conectado, pero SIN refresh token: morirá y habrá que reconectar" };
  }
  const seg = graph.expira_en;
  if (seg == null) return { tono: "green", texto: "conectado" };
  if (seg <= 0)    return { tono: "accent", texto: "conectado · el acceso ha expirado (se renueva al usarlo)" };
  return { tono: "green", texto: `conectado · el acceso vale ${Math.round(seg / 60)} min más` };
}

export async function leerConfig() {
  const r = await apiFetch(`${API}/dev/config`, { headers: authHeaders() });
  if (!r.ok) throw new Error(`el backend respondió ${r.status}`);
  return r.json();
}

// ── FASE 2: RECONSTRUIR ───────────────────────────────────────────────────────

// Lanza la reconstrucción del add-on. Es un despliegue de producción: quien llame a esto
// tiene que haber preguntado antes.
export async function reconstruirAddon() {
  const r = await apiFetch(`${API}/dev/reconstruir`, { method: "POST", headers: authHeaders() });
  const cuerpo = await r.json().catch(() => ({}));
  if (!r.ok) throw new Error(cuerpo.detail || `el backend respondió ${r.status}`);
  return cuerpo;
}

// Espera a que el backend vuelva y dice con qué sha lo ha hecho.
//
// Lo que se busca NO es que el sha cambie, aunque fuera lo primero que se escribió: si ya
// estabas al día —el caso normal cuando se reconstruye para recuperar un despliegue
// dudoso— vuelve con el mismo sha, y esperar un cambio dejaba «no ha vuelto a tiempo»
// después de tres minutos de una reconstrucción perfecta.
//
// Lo que se busca es la CAÍDA y la vuelta: reconstruir para el add-on, así que si el
// backend no llega a dejar de responder es que la reconstrucción nunca arrancó — y eso
// tiene un culpable concreto (el Supervisor la ha rechazado, casi siempre por permisos)
// que conviene decir en vez de disfrazarlo de tiempo agotado.
//
// Sondear `GET /` sin credenciales es a propósito: durante el arranque no hay nada más
// que responda.
export async function esperarAlBackend({ antes, intentos = 40, cada = 5000, dormir } = {}) {
  const pausa = dormir || (ms => new Promise(r => setTimeout(r, ms)));
  let cayo = false;
  for (let i = 0; i < intentos; i++) {
    await pausa(cada);
    let version = null;
    try {
      const r = await fetch(`${API}/`);
      if (r.ok) version = (await r.json())?.version || null;
    } catch { /* parado: es lo que se espera a mitad de reconstrucción */ }

    if (!version) { cayo = true; continue; }
    // Con sha nuevo no hace falta haber visto la caída: el código ya es otro.
    if (version !== antes) return { ok: true, version, cambio: true, cayo };
    if (cayo) return { ok: true, version, cambio: false, cayo };
  }
  return { ok: false, version: null, cambio: false, cayo };
}

// ── FASE 3: LA LÍNEA DEL DÍA ──────────────────────────────────────────────────

// Los carriles de la línea. El orden es el de la leyenda, no el de los datos: cuando algo
// va mal, lo primero que se mira es el registro.
export const CARRILES = [
  { id: "registro", etiqueta: "Registro" },
  { id: "avisos",   etiqueta: "Avisos" },
  { id: "jobs",     etiqueta: "Cola del PC" },
  { id: "salud",    etiqueta: "Salud" },
  { id: "correo",   etiqueta: "Correos" },
];

// Hoy, en AAAA-MM-DD y en local. A mano y no con `toISOString()`, que devuelve UTC: a las
// 00:30 de la noche eso daría el día de ayer, que es exactamente el desfase que la ventana
// del backend existe para no cometer.
export function diaLocal(fecha = new Date()) {
  const dd = (n) => String(n).padStart(2, "0");
  return `${fecha.getFullYear()}-${dd(fecha.getMonth() + 1)}-${dd(fecha.getDate())}`;
}

// Mover el día que se está mirando. Se construye a mediodía para que un cambio de hora no
// se coma ni repita un día.
export function diaDesplazado(dia, dias) {
  const [a, m, d] = String(dia).split("-").map(Number);
  const f = new Date(a, (m || 1) - 1, d || 1, 12);
  f.setDate(f.getDate() + dias);
  return diaLocal(f);
}

export async function leerLinea(dia) {
  const r = await apiFetch(`${API}/dev/linea?dia=${encodeURIComponent(dia)}`,
                           { headers: authHeaders() });
  if (!r.ok) throw new Error(`el backend respondió ${r.status}`);
  return r.json();
}

// Lo que resume la línea en una frase. Lo que no se ha podido leer va ANTES que el
// recuento: un día tranquilo y un día con tres tablas caídas traen los dos cero eventos, y
// esa es la confusión que esta pantalla no puede permitirse.
export function resumenLinea(datos) {
  if (!datos) return { tono: "muted", texto: "sin comprobar" };
  if (datos.sin_leer?.length) {
    return { tono: "accent", texto: `no se ha podido leer: ${datos.sin_leer.join(", ")}` };
  }
  const rojos = (datos.eventos || []).filter(e => e.tono === "red").length;
  if (rojos) return { tono: "red", texto: `${rojos} en rojo de ${datos.total} eventos` };
  if (!datos.total) return { tono: "muted", texto: "no pasó nada ese día" };
  return { tono: "green", texto: `${datos.total} eventos, ninguno en rojo` };
}

// ── FASE 3: AGENTE Y JOBS ─────────────────────────────────────────────────────

export async function leerJobs(limite = 30) {
  const r = await apiFetch(`${API}/dev/jobs?limite=${limite}`, { headers: authHeaders() });
  if (!r.ok) throw new Error(`el backend respondió ${r.status}`);
  return r.json();
}

// El semáforo de un agente. Callar NO es rojo: el PC está apagado la mayor parte del día,
// y una pantalla que grita cuando todo está bien deja de mirarse (docs/ZONA_DEV.md).
export function estadoAgente(agente, timeout = 60) {
  if (!agente) return { tono: "muted", texto: "sin comprobar" };
  const seg = agente.silencio_segundos;
  if (seg == null) return { tono: "muted", texto: "su última señal tiene fecha ilegible" };
  if (seg <= timeout) return { tono: "green", texto: `${agente.status} · visto hace ${seg}s` };
  return { tono: "muted", texto: `apagado · visto ${desdeHace(agente.last_seen_at)}` };
}

// El semáforo de un job y si se puede reintentar. Reintentar solo vale para los fallidos
// que ya tienen dueño: el endpoint exige `claimed_by`, así que ofrecer el botón en un
// `pending` sería ofrecer un 409.
export function estadoJob(job, maxIntentos = 3) {
  if (!job) return { tono: "muted", texto: "sin comprobar", reintentable: false, motivo: null };
  const tono = { done: "green", failed: "red", running: "accent",
                 claimed: "accent", pending: "muted" }[job.status] || "muted";
  const agotado = (job.attempt ?? 0) >= maxIntentos;
  return {
    tono,
    texto: job.status + (job.attempt ? ` · intento ${job.attempt}/${maxIntentos}` : ""),
    reintentable: job.status === "failed" && !!job.claimed_by && !agotado,
    // Se dice POR QUÉ no se puede en vez de esconder el botón sin explicación: quedarse
    // sin intentos y no haber sido cogido nunca son dos problemas distintos.
    motivo: job.status !== "failed" ? null
      : !job.claimed_by ? "nadie llegó a cogerlo: no hay a quién devolvérselo"
      : agotado ? `agotó los ${maxIntentos} intentos`
      : null,
  };
}

export async function reintentarJob(id, worker) {
  const r = await apiFetch(`${API}/jobs/${id}/retry`, {
    method:  "POST",
    headers: jsonHeaders(),
    body:    JSON.stringify({ worker_id: worker }),
  });
  const cuerpo = await r.json().catch(() => ({}));
  if (!r.ok) throw new Error(cuerpo.detail || `el backend respondió ${r.status}`);
  return cuerpo;
}

// ── FASE 3: SALUD DE LOS DATOS ────────────────────────────────────────────────

export async function leerDiagnostico(dias = 30) {
  const r = await apiFetch(`${API}/health/diagnostico?dias=${dias}`, { headers: authHeaders() });
  if (!r.ok) throw new Error(`el backend respondió ${r.status}`);
  return r.json();
}

// El semáforo de una métrica. Lo que importa no es cuántos datos hay sino desde cuándo no
// llega ninguno: el Watch estuvo días sin sincronizar con la tabla llena de filas viejas, y
// desde fuera aquello se veía igual de bien que ahora.
export function estadoMetrica(m) {
  if (!m)                   return { tono: "muted", texto: "sin comprobar" };
  if (m.dias_atras == null) return { tono: "muted", texto: "nunca ha llegado un dato" };
  const cuando = m.dias_atras === 0 ? "hoy"
    : m.dias_atras === 1 ? "ayer"
    : `hace ${m.dias_atras} días`;
  const huecos = m.huecos ? ` · ${m.huecos} ${m.huecos === 1 ? "hueco" : "huecos"}` : "";
  // Un día de retraso es lo normal: el sueño de esta noche llega por la mañana.
  if (m.dias_atras <= 1) return { tono: "green",  texto: cuando + huecos };
  if (m.dias_atras <= 3) return { tono: "accent", texto: cuando + huecos };
  return { tono: "red", texto: cuando + huecos };
}

// Quién ha dejado de escribir. Es la pregunta de verdad cuando algo falla —no "¿falta el
// sueño?" sino "¿quién ha dejado de mandar?"— y las dos fuentes escriben en la misma
// tabla, así que sin la columna `fuente` no había forma de distinguirlas.
export function estadoFuente(ultima) {
  if (!ultima) return { tono: "muted", texto: "sin escrituras" };
  const horas = (Date.now() - new Date(ultima).getTime()) / 3600000;
  if (Number.isNaN(horas)) return { tono: "muted", texto: "fecha ilegible" };
  const texto = desdeHace(ultima);
  // 26 horas y no 24: el envío diario no cae siempre a la misma hora, y un margen justo
  // pondría en ámbar media semana.
  if (horas <= 26) return { tono: "green",  texto };
  if (horas <= 72) return { tono: "accent", texto };
  return { tono: "red", texto };
}

// ── FASE 3: AVISOS Y REGLAS ───────────────────────────────────────────────────

export async function leerAvisosDev(dias = 7) {
  const r = await apiFetch(`${API}/dev/avisos?dias=${dias}`, { headers: authHeaders() });
  if (!r.ok) throw new Error(`el backend respondió ${r.status}`);
  return r.json();
}

// El semáforo de una regla. Silenciada es ROJO aunque no haya fallado nada: significa que
// el sistema dejó de avisarte de algo y no te lo dijo, que es el fallo más caro que puede
// cometer una regla.
export function estadoRegla(r) {
  if (!r) return { tono: "muted", texto: "sin comprobar" };
  if (r.silenciada) {
    return { tono: "red",
             texto: `silenciada${r.silenciada_desde ? ` ${desdeHace(r.silenciada_desde)}` : ""}` };
  }
  if (!r.enviados) return { tono: "muted", texto: "no ha mandado nada en la ventana" };
  if (!r.utiles && !r.no_utiles) {
    return { tono: "muted", texto: `${r.enviados} ${r.enviados === 1 ? "aviso" : "avisos"}, ninguno votado` };
  }
  return {
    tono:  r.no_utiles > r.utiles ? "accent" : "green",
    texto: `${r.utiles} útiles / ${r.no_utiles} no · ${r.sin_votar} sin votar`,
  };
}

export async function reactivarRegla(regla) {
  const r = await apiFetch(`${API}/avisos/reglas/${encodeURIComponent(regla)}/reactivar`,
                           { method: "POST", headers: authHeaders() });
  if (!r.ok) throw new Error(`el backend respondió ${r.status}`);
  return r.json();
}
