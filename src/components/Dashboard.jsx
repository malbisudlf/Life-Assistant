import React, { useState, useEffect, useRef, useMemo } from "react";
import {
  isToday, isFuture, isPast, isActive, daysUntil, formatTime, formatUpcomingTime,
  urgencyColor, formatShortDate, DAYS_ES, MONTHS_ES, isoToDdMmYyyy, formatLogTime,
  hoursToHM, sleepScore, sleepBreakdown, sleepHours, calcRecoveryMod, findMetric,
  mantenimientoEstimado, metricasMuertas,
  weatherFromCode, weekdayShort,
  healthConclusions, healthOverall, healthCorrelations, healthCoverageDays,
  wellnessBreakdown, scoreFromBreakdown, wellnessBaselines,
  wellnessHistory, seriesTrend, trendDirection,
  relojCobertura, relojRachaSinReloj, relojPuesto,
  formatMoney, clothingTotals, CLOTHING_CURRENCIES,
  formatoEuros, formatoPorcentaje, formatoRentabilidad, mezclaCartera, variacionCartera,
  hostStreaming,
  jarvisHistorial, jarvisEtiquetaAccion, jarvisMotivoError,
  elegirVozEspanola, textoHablable, esFinDeLlamada, JARVIS_SILENCIO_MS,
} from "../lib/helpers";

// Configuración de instancia (kit self-hosted): se personaliza con variables VITE_* en Vercel/.env
const API = import.meta.env.VITE_API_URL || "https://backend-tender-glow-160.fly.dev";
const HA_URL = (import.meta.env.VITE_HA_URL || "http://192.168.1.200:8123") +
               (import.meta.env.VITE_HA_DASHBOARD_PATH || "/lovelace/tablet");
// Marcador en el título del evento que lo convierte en "entrega" para el widget de entregas
const ENTREGAS_MARKER = import.meta.env.VITE_ENTREGAS_MARKER || "📚";
// Identificador del agente PC, el mismo que manda el heartbeat desde agent/agent.py
const AGENT_ID = import.meta.env.VITE_AGENT_ID || "pc-mikel";

// Ritmo del seguimiento de un job del agente PC.
const JOB_POLL_ACTIVO_MS = 2_000;    // modal delante: la barra de progreso va en vivo
const JOB_POLL_FONDO_MS  = 15_000;   // modal cerrado: solo hace falta para avisar al acabar
// Techo del seguimiento: el agente ignora los jobs de más de una hora (ver
// poll_pending_job en agent/agent.py), así que pasado ese punto no lo va a recoger
// nadie y seguir preguntando no aporta nada.
const JOB_POLL_MAX_MS    = 60 * 60 * 1000;

// Ventana del panel de patrones. Es el máximo que acepta /health/metrics: los cruces
// entre series ganan mucho con meses de respaldo — con 30 días un grupo de 3 noches
// ya cuenta como "hallazgo" y suele ser casualidad.
const HEALTH_DIAS_PATRONES = 365;
// Muestra mínima por grupo en la ventana larga. Muy por encima del 3 que usan las
// conclusiones del día a día, justamente porque aquí sí hay datos de sobra.
const HEALTH_MIN_MUESTRA_PATRONES = 10;

// Cabeceras de una llamada autenticada. El token se lee en el momento y no se captura
// en un closure: si la sesión se renueva a mitad de una pantalla, la siguiente llamada
// ya usa el nuevo. Único sitio que toca el esquema de autenticación.
function authHeaders(extra = {}) {
  const token = localStorage.getItem("la_token") || "";
  return { "Authorization": `Bearer ${token}`, ...extra };
}

// Atajo para las llamadas que mandan JSON, que son casi todas las de escritura.
function jsonHeaders() {
  return authHeaders({ "Content-Type": "application/json" });
}

async function apiFetch(url, options = {}) {
  const res = await fetch(url, options);
  if (res.status === 401 && localStorage.getItem("la_token")) {
    localStorage.removeItem("la_token");
    window.location.reload();
    await new Promise(resolve => setTimeout(resolve, 1000));
  }
  return res;
}

// /auth/login ahora exige el JWT del dashboard (ver backend/main.py): un <a href>
// directo al backend no manda cabeceras, así que se pide con fetch autenticado y se
// navega a la auth_url que devuelve — esa sí es la pantalla de consentimiento de
// Microsoft, no el JSON del backend.
async function conectarOutlook() {
  try {
    const res = await apiFetch(`${API}/auth/login`, { headers: authHeaders() });
    const data = await res.json();
    if (data.auth_url) window.open(data.auth_url, "_blank", "noopener,noreferrer");
  } catch {
    // mejor esfuerzo: si falla, el usuario puede pulsar otra vez
  }
}

// ── LOGIN SCREEN ─────────────────────────────────────────────────
function LoginScreen() {
  const [pwd, setPwd] = useState("");
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    const style = document.createElement("style");
    style.textContent = `@import url('https://fonts.googleapis.com/css2?family=DM+Mono:wght@400;500&family=DM+Sans:wght@300;400;500&display=swap'); *, *::before, *::after { box-sizing: border-box; margin: 0; padding: 0; } input, button { outline: none !important; box-shadow: none !important; -webkit-appearance: none; }`;
    document.head.appendChild(style);
    return () => document.head.removeChild(style);
  }, []);

  async function handleSubmit(e) {
    e.preventDefault();
    setLoading(true);
    setError("");
    try {
      const res = await fetch(`${API}/auth/password`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ password: pwd }),
      });
      const data = await res.json();
      if (data.token) {
        localStorage.setItem("la_token", data.token);
        window.location.reload();
      } else {
        setError("Contraseña incorrecta");
      }
    } catch {
      setError("Error de conexión");
    }
    setLoading(false);
  }

  return (
    <div style={{
      display: "flex", alignItems: "center", justifyContent: "center",
      minHeight: "100vh", background: "#0e0f11", fontFamily: "'DM Sans', sans-serif",
    }}>
      <div style={{
        background: "#161719", border: "0.5px solid rgba(255,255,255,0.07)",
        borderRadius: 16, padding: "40px 48px", width: 320,
      }}>
        <div style={{ fontFamily: "'DM Mono', monospace", fontSize: 22, color: "#e8e6e0", marginBottom: 4 }}>Life Assistant</div>
        <div style={{ fontSize: 12, color: "#7a7870", marginBottom: 32, letterSpacing: "0.05em", textTransform: "uppercase" }}>Acceso privado</div>
        <form onSubmit={handleSubmit}>
          <input
            type="password"
            value={pwd}
            onChange={e => setPwd(e.target.value)}
            placeholder="Contraseña"
            autoFocus
            inputMode="numeric"
            pattern="[0-9]*"
            autoComplete="current-password"
            enterKeyHint="go"
            style={{
              width: "100%", padding: "10px 14px", background: "#1e1f22",
              border: "0.5px solid rgba(255,255,255,0.12)", borderRadius: 8,
              color: "#e8e6e0", fontSize: 14, outline: "none",
              fontFamily: "'DM Sans', sans-serif", boxSizing: "border-box",
              WebkitAppearance: "none", boxShadow: "none",
            }}
          />
          {error && <div style={{ color: "#d4645a", fontSize: 12, marginTop: 8 }}>{error}</div>}
          <button
            type="submit"
            disabled={loading}
            style={{
              width: "100%", marginTop: 16, padding: "10px 0",
              background: "#c8a96e", border: "none", borderRadius: 8,
              color: "#0e0f11", fontSize: 14, fontWeight: 500,
              cursor: loading ? "not-allowed" : "pointer", opacity: loading ? 0.7 : 1,
              fontFamily: "'DM Sans', sans-serif",
            }}
          >
            {loading ? "Verificando..." : "Entrar"}
          </button>
        </form>
      </div>
    </div>
  );
}

// ── HELPERS DE FECHA Y SALUD ─────────────────────────────────────
// (extraídos a ../lib/helpers para poder testearlos de forma aislada)

function SleepStageTooltip({ label, color, tip, children }) {
  const [show, setShow] = useState(false);
  const [pos,  setPos]  = useState({ x: 0, y: 0 });
  const ref = useRef(null);

  useEffect(() => {
    if (!show) return;
    const handler = e => { if (ref.current && !ref.current.contains(e.target)) setShow(false); };
    document.addEventListener("mousedown", handler);
    return () => document.removeEventListener("mousedown", handler);
  }, [show]);

  return (
    <span ref={ref} style={{ position: "relative", cursor: "pointer" }}
      onClick={e => { e.stopPropagation(); setShow(v => !v); setPos({ x: e.clientX, y: e.clientY }); }}
    >
      {children}
      {show && (
        <div style={{
          position: "fixed", left: pos.x + 14, top: pos.y + 10,
          background: "#1a1b1e", border: "0.5px solid rgba(255,255,255,0.15)",
          borderLeft: `2px solid ${color}`,
          borderRadius: 8, padding: "10px 14px", zIndex: 2000,
          maxWidth: 260, fontSize: 12, color: "#c8c6c0", lineHeight: 1.6,
          boxShadow: "0 8px 32px rgba(0,0,0,0.6)",
        }}>
          <div style={{ fontWeight: 600, color: "#e8e6e0", marginBottom: 4 }}>{label}</div>
          {tip}
        </div>
      )}
    </span>
  );
}

// `objetivo` dibuja una línea discontinua de referencia (p. ej. el peso al que
// quieres llegar) y entra en el rango vertical para que nunca quede fuera del
// gráfico. `relleno` añade un área bajo la curva, útil cuando la serie es el
// contenido principal del bloque y no un adorno al lado de una cifra.
// `marcar` señala puntos que hay que mirar distinto (hoy: los días puntuados sin el
// reloj puesto). Sin la marca, un día medido con la mitad de los sensores se dibuja a
// la misma altura que un día malo, y la línea cuenta una caída que no ocurrió.
function Sparkline({ data, color = "var(--accent)", height = 40, objetivo = null, relleno = false,
                     marcar = null, colorMarca = "var(--muted2)" }) {
  const pts = data.filter(d => d.value != null);
  if (pts.length < 2) return (
    <div style={{ height, display: "flex", alignItems: "center", justifyContent: "center" }}>
      <span style={{ fontSize: 11, color: "var(--muted2)" }}>—</span>
    </div>
  );
  const vals = pts.map(d => Number(d.value));
  const todos = objetivo != null ? [...vals, Number(objetivo)] : vals;
  const min = Math.min(...todos), max = Math.max(...todos), range = max - min || 1;
  const W = 200, H = height;
  const px = i => (i / (pts.length - 1)) * (W - 4) + 2;
  const py = v => H - 4 - ((v - min) / range) * (H - 8);
  const points = pts.map((d, i) => `${px(i).toFixed(1)},${py(Number(d.value)).toFixed(1)}`).join(" ");
  return (
    <svg viewBox={`0 0 ${W} ${H}`} width="100%" height={height} preserveAspectRatio="none"
      style={{ display: "block" }} role="img" aria-hidden="true">
      {relleno && <polygon points={`2,${H} ${points} ${(W - 2).toFixed(1)},${H}`} fill={color} opacity="0.12" />}
      {objetivo != null && (
        <line x1="0" y1={py(Number(objetivo))} x2={W} y2={py(Number(objetivo))}
          stroke="var(--green)" strokeWidth="1" strokeDasharray="3 3" opacity="0.75" />
      )}
      <polyline points={points} fill="none" stroke={color} strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" />
      {marcar && pts.map((d, i) => marcar(d) ? (
        <circle key={i} cx={px(i)} cy={py(Number(d.value))} r="2" fill={colorMarca} opacity="0.85" />
      ) : null)}
    </svg>
  );
}

// Fuera del componente a propósito. Definido dentro, cada render de Dashboard creaba
// un TIPO de componente nuevo, así que React desmontaba y volvía a montar todo este
// subárbol en lugar de actualizarlo — dos veces por minuto solo por el tic del reloj,
// y cualquier estado propio que se le añadiera se habría perdido solo.
function DepartureWidget({ ev, departureMap, departureLoadingId, departurePickingId,
                           setDeparturePickingId, setDepartureMap, fetchDeparture }) {
  if (!ev?.loc) return null;
  const key = ev.id || ev.start;
  const info = departureMap[key];
  const isLoading = departureLoadingId === key;
  const isPicking = departurePickingId === key;
  const btnBase = { border: "0.5px solid", borderRadius: 6, fontSize: 11, padding: "4px 10px", cursor: "pointer", fontFamily: "'DM Sans', sans-serif", letterSpacing: "0.04em" };
  return (
    <div style={{ marginTop: 6 }}>
      {!info && !isLoading && !isPicking && (
        <button onClick={e => { e.stopPropagation(); setDeparturePickingId(key); }} style={{
          ...btnBase, background: "rgba(200,169,110,0.12)", borderColor: "rgba(200,169,110,0.3)", color: "var(--accent)",
        }}>¿A qué hora salir?</button>
      )}
      {isPicking && (
        <div style={{ display: "flex", gap: 6, alignItems: "center" }}>
          <button onClick={e => { e.stopPropagation(); fetchDeparture(ev, "driving"); }} style={{
            ...btnBase, background: "rgba(200,169,110,0.12)", borderColor: "rgba(200,169,110,0.3)", color: "var(--accent)",
          }}>🚗 En coche</button>
          <button onClick={e => { e.stopPropagation(); fetchDeparture(ev, "walking"); }} style={{
            ...btnBase, background: "rgba(100,180,130,0.12)", borderColor: "rgba(100,180,130,0.3)", color: "var(--green)",
          }}>🚶 Andando</button>
          <button onClick={e => { e.stopPropagation(); setDeparturePickingId(null); }} style={{
            ...btnBase, background: "transparent", borderColor: "transparent", color: "var(--muted)", padding: "4px 6px",
          }}>✕</button>
        </div>
      )}
      {isLoading && <div style={{ fontSize: 11, color: "var(--muted)" }}>Calculando ruta...</div>}
      {info && !info.error && (
        <div style={{ fontSize: 12, color: "var(--text)", lineHeight: 1.6 }}>
          <span style={{ color: "var(--accent)", fontFamily: "'DM Mono', monospace", fontSize: 13 }}>
            {info.mode === "walking" ? "🚶" : "🚗"} Salir a las {info.departure_time}
          </span>
          <span style={{ color: "var(--muted)", marginLeft: 8 }}>
            {info.duration_text} · {info.distance_text}
          </span>
          <button onClick={e => { e.stopPropagation(); setDepartureMap(prev => { const n = {...prev}; delete n[key]; return n; }); setDeparturePickingId(key); }} style={{
            ...btnBase, background: "transparent", borderColor: "transparent", color: "var(--muted)", padding: "2px 6px", marginLeft: 6, fontSize: 10,
          }}>↺</button>
        </div>
      )}
      {info?.error && <div style={{ fontSize: 11, color: "#d4645a" }}>{info.error}</div>}
    </div>
  );
}

// ── JARVIS ───────────────────────────────────────────────────────
// El componente es tonto a propósito: pinta mensajes y avisa hacia arriba. Toda la
// decisión (qué herramienta, qué se ejecuta, qué se propone) vive en el backend, para
// que el día que se le hable desde otro sitio no haya que reimplementarla aquí.

// Reconocimiento de voz del navegador. Es GRATIS —lo hace el propio dispositivo— frente
// a Whisper, que cuesta por minuto: para dictar una frase corta al chat no compensa
// pagar. Donde no exista (Firefox, algún WebView), simplemente no sale el botón y se
// escribe; no hay respaldo de pago a propósito.
const VOZ_NAVEGADOR = typeof window !== "undefined"
  ? (window.SpeechRecognition || window.webkitSpeechRecognition || null)
  : null;

// El espejo del micrófono: la voz de Jarvis también la pone el navegador, y también es
// gratis por lo mismo (la sintetiza el dispositivo). Nada de TTS de pago por carácter
// para leer dos frases. Donde no exista, el botón 🔊 no aparece y se lee.
const VOZ_SINTESIS = typeof window !== "undefined" && "speechSynthesis" in window
  ? window.speechSynthesis
  : null;

/** Lee la respuesta en voz alta. `alTerminar` se llama SIEMPRE, hable o no: el modo
 *  llamada encadena la escucha con él, y un camino que no avisara dejaría la llamada
 *  colgada en silencio esperando a alguien que ya no va a hablar. */
function hablarJarvis(texto, alTerminar) {
  const fin = () => { try { alTerminar?.(); } catch { /* mejor esfuerzo */ } };
  if (!VOZ_SINTESIS) { fin(); return; }
  try {
    VOZ_SINTESIS.cancel();   // una respuesta nueva corta a la anterior a media frase
    const dicho = textoHablable(texto);
    if (!dicho) { fin(); return; }
    const u = new SpeechSynthesisUtterance(dicho);
    u.lang = "es-ES";
    // getVoices() puede venir vacío en la primera llamada (Chrome las carga en
    // diferido): entonces basta el lang y elige el navegador.
    const voz = elegirVozEspanola(VOZ_SINTESIS.getVoices());
    if (voz) u.voice = voz;
    u.onend   = fin;
    u.onerror = fin;
    VOZ_SINTESIS.speak(u);
  } catch { fin(); }
}

// Saca el motivo real de una respuesta de error de /jarvis. El detalle de FastAPI
// viene en `detail`; si el cuerpo no es JSON (un 502 del proxy, por ejemplo), basta con
// el código.
async function motivoJarvis(r) {
  let detalle = "";
  try {
    detalle = (await r.json())?.detail || "";
  } catch { /* mejor esfuerzo: cuerpo vacío o no-JSON */ }
  const e = new Error(jarvisMotivoError(r.status, typeof detalle === "string" ? detalle : ""));
  // Marca para distinguir "el backend contestó un error" de "no llegué a hablar con él":
  // sin esto, un fallo de red enseñaría el "Failed to fetch" del navegador.
  e.explicado = true;
  return e;
}

function JarvisMensaje({ m }) {
  const esUsuario = m.rol === "user";
  const esAviso   = m.rol === "aviso";
  if (esAviso) {
    return <div style={{ fontSize: 12, color: "#d4645a", textAlign: "center", padding: "2px 0" }}>{m.texto}</div>;
  }
  return (
    <div style={{ display: "flex", justifyContent: esUsuario ? "flex-end" : "flex-start" }}>
      <div style={{
        maxWidth: "85%",
        padding: "8px 12px",
        borderRadius: 10,
        fontSize: 14,
        lineHeight: 1.5,
        whiteSpace: "pre-wrap",
        wordBreak: "break-word",
        color: esUsuario ? "var(--bg)" : "var(--text)",
        background: esUsuario ? "var(--accent)" : "var(--surface2)",
        border: esUsuario ? "none" : "0.5px solid var(--border)",
      }}>
        {m.texto}
        {!esUsuario && m.herramientas?.length > 0 && (
          <div style={{ marginTop: 6, fontSize: 10, color: "var(--muted2)", letterSpacing: "0.05em" }}>
            {m.herramientas.join(" · ")}
          </div>
        )}
      </div>
    </div>
  );
}

// Reaperturas seguidas del micrófono sin oír nada antes de colgar. Chrome cierra la
// sesión cada pocos segundos de silencio, así que esto son del orden de un minuto callado.
const REAPERTURAS_MAX = 8;

// Qué se ve en cada fase de la llamada. El usuario tiene que saber si le están
// escuchando o no: un micrófono que parece abierto y no lo está es lo que hace que la
// gente repita la frase tres veces.
const FASES_LLAMADA = {
  escuchando: { texto: "Te escucho…", color: "var(--accent)" },
  pensando:   { texto: "Pensando…",   color: "var(--accent2)" },
  hablando:   { texto: "Hablando…",   color: "var(--green)" },
};

function JarvisChat({
  mensajes, borrador, setBorrador, onEnviar, pensando,
  pendiente, onConfirmar, onDescartar, confirmando,
  escuchando, onDictar, habla, onHabla, finRef,
  enLlamada, faseLlamada, parcial, onLlamar, onColgar, contexto,
}) {
  const etiqueta = jarvisEtiquetaAccion(pendiente, contexto);
  const puedeEnviar = borrador.trim() && !pensando;
  const fase = FASES_LLAMADA[faseLlamada] || FASES_LLAMADA.escuchando;

  return (
    <>
      <div style={{
        display: "flex", flexDirection: "column", gap: 8,
        maxHeight: 340, overflowY: "auto", padding: "2px 0", marginBottom: 10,
      }}>
        {mensajes.length === 0 && (
          <div style={{ color: "var(--muted)", fontSize: 13, lineHeight: 1.6 }}>
            Pregúntale por tu agenda, tu sueño, el tiempo o el PC. También puede actuar:
            «enciende el PC», «apunta que tengo que llamar al dentista».
          </div>
        )}
        {mensajes.map((m, i) => <JarvisMensaje key={i} m={m} />)}
        {pensando && (
          <div style={{ fontSize: 13, color: "var(--accent)", animation: "pulse 1.5s infinite" }}>
            Pensando…
          </div>
        )}
        <div ref={finRef} />
      </div>

      {/* Lo que Jarvis propone pero no ejecuta. La etiqueta se construye con los
          argumentos reales, no con lo que el modelo haya dicho en su respuesta. */}
      {etiqueta && (
        <div style={{
          marginBottom: 10, padding: "10px 12px", borderRadius: 8,
          background: "var(--surface2)", border: "0.5px solid var(--accent2)",
        }}>
          <div style={{ fontSize: 13, color: "var(--text)", marginBottom: 8 }}>{etiqueta}</div>
          <div style={{ display: "flex", gap: 8 }}>
            <button onClick={onConfirmar} disabled={confirmando} style={{
              flex: 1, padding: "6px 10px", borderRadius: 6, fontSize: 13, cursor: "pointer",
              border: "none", background: "var(--accent)", color: "var(--bg)",
              opacity: confirmando ? 0.6 : 1,
            }}>{confirmando ? "Creando…" : "Confirmar"}</button>
            <button onClick={onDescartar} disabled={confirmando} style={{
              padding: "6px 10px", borderRadius: 6, fontSize: 13, cursor: "pointer",
              border: "0.5px solid var(--border)", background: "transparent", color: "var(--muted)",
            }}>Descartar</button>
          </div>
        </div>
      )}

      {/* En llamada no hay nada que escribir: el teclado sobra y lo que hace falta es
          ver en qué fase va y poder colgar de un toque. */}
      {enLlamada ? (
        <div style={{
          padding: "12px 14px", borderRadius: 10,
          background: "var(--surface2)", border: `0.5px solid ${fase.color}`,
        }}>
          <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
            <span style={{
              width: 8, height: 8, borderRadius: "50%", background: fase.color,
              animation: "pulse 1.5s infinite", flexShrink: 0,
            }} />
            <span style={{ fontSize: 13, color: fase.color, flex: 1 }}>{fase.texto}</span>
            <button type="button" onClick={onColgar} style={{
              padding: "6px 14px", borderRadius: 6, fontSize: 13, cursor: "pointer",
              border: "none", background: "#d4645a", color: "#fff", flexShrink: 0,
            }}>Colgar</button>
          </div>
          {parcial && (
            <div style={{ marginTop: 8, fontSize: 13, color: "var(--muted)", fontStyle: "italic" }}>
              {parcial}
            </div>
          )}
        </div>
      ) : (
        <form onSubmit={e => { e.preventDefault(); if (puedeEnviar) onEnviar(borrador); }}
              style={{ display: "flex", gap: 8 }}>
          <input
            value={borrador}
            onChange={e => setBorrador(e.target.value)}
            placeholder={escuchando ? "Escuchando…" : "Habla con Jarvis"}
            disabled={pensando}
            style={{
              flex: 1, padding: "9px 12px", borderRadius: 8, fontSize: 14,
              border: "0.5px solid var(--border)", background: "var(--surface2)",
              color: "var(--text)", outline: "none", minWidth: 0,
            }}
          />
          {VOZ_NAVEGADOR && VOZ_SINTESIS && (
            <button type="button" onClick={onLlamar} title="Hablar como en una llamada" style={{
              padding: "0 12px", borderRadius: 8, fontSize: 15, cursor: "pointer",
              border: "0.5px solid var(--border)", background: "transparent",
              color: "var(--green)", flexShrink: 0,
            }}>📞</button>
          )}
          {VOZ_NAVEGADOR && (
            <button type="button" onClick={onDictar} title="Dictar" style={{
              padding: "0 12px", borderRadius: 8, fontSize: 15, cursor: "pointer",
              border: "0.5px solid var(--border)", background: escuchando ? "var(--accent)" : "transparent",
              color: escuchando ? "var(--bg)" : "var(--muted)", flexShrink: 0,
            }}>🎙</button>
          )}
          {VOZ_SINTESIS && (
            <button type="button" onClick={onHabla}
              title={habla ? "Silenciar a Jarvis" : "Que Jarvis conteste en voz alta"} style={{
                padding: "0 12px", borderRadius: 8, fontSize: 15, cursor: "pointer",
                border: "0.5px solid var(--border)", background: habla ? "var(--accent)" : "transparent",
                color: habla ? "var(--bg)" : "var(--muted)", flexShrink: 0,
              }}>{habla ? "🔊" : "🔇"}</button>
          )}
          <button type="submit" disabled={!puedeEnviar} style={{
            padding: "0 14px", borderRadius: 8, fontSize: 14, flexShrink: 0,
            border: "none", background: "var(--accent)", color: "var(--bg)",
            cursor: puedeEnviar ? "pointer" : "default", opacity: puedeEnviar ? 1 : 0.4,
          }}>→</button>
        </form>
      )}
    </>
  );
}

// ── ESTILOS GLOBALES ─────────────────────────────────────────────
const GLOBAL_CSS = `
  @import url('https://fonts.googleapis.com/css2?family=DM+Mono:wght@400;500&family=DM+Sans:wght@300;400;500&display=swap');
  *, *::before, *::after { box-sizing: border-box; margin: 0; padding: 0; }
  input, button, textarea, select { outline: none !important; box-shadow: none !important; -webkit-appearance: none; }
  :root {
    --bg: #0e0f11; --surface: #161719; --surface2: #1e1f22;
    --border: rgba(255,255,255,0.07); --border2: rgba(255,255,255,0.12);
    --text: #e8e6e0; --muted: #928f86; --muted2: #6e6b62;
    --accent: #c8a96e; --accent2: #8bb4d4; --green: #6aaa82;
    --node-line: rgba(200,169,110,0.3);
  }
  html, body, #root { height: 100%; background: var(--bg); }
  body { font-family: 'DM Sans', sans-serif; color: var(--text); }
  .la-time-input { transition: border-color 0.15s, box-shadow 0.15s; }
  .la-time-input:focus { border-color: var(--accent) !important; box-shadow: 0 0 0 3px rgba(200,169,110,0.14) !important; }
  .la-time-option { transition: background 0.1s, color 0.1s; }
  .la-time-option:hover { background: rgba(200,169,110,0.12); color: var(--accent); }
  ::-webkit-scrollbar { width: 4px; height: 4px; }
  ::-webkit-scrollbar-track { background: transparent; }
  ::-webkit-scrollbar-thumb { background: var(--border2); border-radius: 2px; }
  @keyframes slideInRight { from { transform: translateX(100%); opacity: 0; } to { transform: translateX(0); opacity: 1; } }
  @keyframes fadeInOverlay { from { opacity: 0; } to { opacity: 1; } }
  @keyframes pulse { 0%, 100% { opacity: 1; } 50% { opacity: 0.4; } }
  @keyframes shimmer { 0% { background-position: -450px 0; } 100% { background-position: 450px 0; } }
  .la-skel { background: linear-gradient(90deg, rgba(255,255,255,0.03) 25%, rgba(255,255,255,0.08) 50%, rgba(255,255,255,0.03) 75%); background-size: 900px 100%; animation: shimmer 1.4s infinite linear; border-radius: 8px; }
  @keyframes nodeGlow { 0%, 100% { box-shadow: 0 0 8px rgba(200,169,110,0.4); } 50% { box-shadow: 0 0 16px rgba(200,169,110,0.7); } }
  body.resizing { cursor: se-resize !important; user-select: none !important; }
  body.dragging-widget { cursor: grabbing !important; user-select: none !important; }
  .widget-wrap { position: relative; min-width: 0; }
  .resize-handle {
    position: absolute; bottom: 5px; right: 5px;
    width: 20px; height: 20px; cursor: se-resize;
    display: flex; align-items: center; justify-content: center;
    opacity: 0; transition: opacity 0.15s; border-radius: 3px; z-index: 4;
  }
  .widget-wrap:hover .resize-handle { opacity: 0.35; }
  .resize-handle:hover { opacity: 1 !important; background: rgba(200,169,110,0.1); }
  .drag-handle {
    position: absolute; top: 8px; left: 8px; z-index: 5;
    cursor: grab; padding: 4px 5px; border-radius: 4px;
    opacity: 0; transition: opacity 0.15s;
    color: var(--muted); font-size: 11px; line-height: 1;
    background: rgba(14,15,17,0.7);
  }
  .widget-wrap:hover .drag-handle { opacity: 0.5; }
  .drag-handle:hover { opacity: 1 !important; color: var(--accent); }
  body.dragging-widget .drag-handle { opacity: 0 !important; }
  body.dragging-widget .resize-handle { opacity: 0 !important; }
  .snap-zone-bar { animation: fadeInOverlay 0.15s ease; }
  @media (max-width: 640px) {
    .clock { font-size: 42px !important; letter-spacing: -1px !important; }
    .dashboard-root { padding: 12px !important; gap: 12px !important; }
    .header-greeting { display: none !important; }
    .timeline-inner { min-width: 280px !important; }
    .widget-wrap { width: 100% !important; }
    .col-left, .col-right { flex: 1 1 0 !important; min-width: 0 !important; }
    .col-divider { display: none !important; }
  }
`;

const DEFAULT_SPLITS  = { 2: [0.65], 3: [0.33, 0.67] };
const ACTIVE_COLUMNS  = { 2: ["left", "right"], 3: ["left", "center", "right"] };
const COLUMN_LABELS   = { left: "izquierda", center: "centro", right: "derecha" };

// Columna por defecto de cada widget. Tiene que cubrir TODOS los ids de
// ALL_DEFAULT_WIDGETS: quien no aparezca aquí cae en "left" al reconstruir una
// config guardada sin columna, aunque su default sea otro (le pasaba a
// `acciones_pc`, que nacía a la derecha y reaparecía a la izquierda).
const DEFAULT_COLUMNS = {
  jarvis:            "left",
  timeline:          "left",
  weather:           "left",
  upcoming:          "left",
  entregas:          "right",
  acciones_pc:       "right",
  training:          "right",
  finanzas:          "right",
  ideas:             "right",
  clothing:          "right",
  health_wellness:   "left",
  health_sleep:      "right",
  health_heart:      "right",
  health_hrv:        "right",
  health_activity:   "right",
  health_workouts:   "right",
  health_hub:        "left",
};

const ALL_DEFAULT_WIDGETS = [
  { id: "jarvis",            label: "Jarvis",            visible: true,  column: "left"  },
  { id: "timeline",          label: "Hoy",              visible: true,  column: "left"  },
  { id: "weather",           label: "Clima",             visible: true,  column: "left"  },
  { id: "upcoming",          label: "Próximos eventos",  visible: true,  column: "left"  },
  { id: "entregas",          label: "Entregas",          visible: true,  column: "right" },
  { id: "training",          label: "Entrenamiento",     visible: true,  column: "right" },
  { id: "finanzas",          label: "Finanzas",          visible: true,  column: "right" },
  { id: "ideas",             label: "Ideas",             visible: true,  column: "right" },
  { id: "clothing",          label: "Conteo ropa",       visible: true,  column: "right" },
  { id: "acciones_pc",       label: "Streaming PC",      visible: true,  column: "right" },
  { id: "health_wellness",   label: "Bienestar semanal", visible: true,  column: "left"  },
  { id: "health_sleep",      label: "Sueño",             visible: true,  column: "right" },
  { id: "health_heart",      label: "Freq. cardíaca",    visible: false, column: "right" },
  { id: "health_hrv",        label: "HRV",               visible: false, column: "right" },
  { id: "health_activity",   label: "Actividad",         visible: false, column: "right" },
  { id: "health_workouts",   label: "Entrenamientos AW", visible: false, column: "right" },
  { id: "health_hub",        label: "Salud",             visible: true,  column: "left"  },
];

// Carga una config de widgets desde localStorage, fusionándola con los defaults
// (para incorporar widgets nuevos que aún no estén guardados) y saneando cada
// entrada. Se usa tanto para el modo completo ("la_widget_config") como para el
// simplificado ("la_simple_widget_config"), que tienen selecciones independientes.
function loadWidgetConfig(storageKey) {
  try {
    const saved = localStorage.getItem(storageKey);
    if (saved) {
      const parsed   = JSON.parse(saved).filter(w => w.id !== "__split__");
      const savedIds = new Set(parsed.map(w => w.id));
      const merged   = parsed.map(w => ({
        id: w.id,
        label: ALL_DEFAULT_WIDGETS.find(d => d.id === w.id)?.label || w.label,
        visible: w.visible !== false,
        column: w.column || DEFAULT_COLUMNS[w.id] || "left",
        width:  typeof w.width  === "number" ? w.width  : undefined,
        height: typeof w.height === "number" ? w.height : undefined,
        // widthPct es lo que de verdad pinta el ancho (wrapResizable). Al reconstruir
        // la entrada campo a campo se quedaba fuera, así que los anchos ajustados se
        // perdían en cada recarga.
        widthPct: typeof w.widthPct === "number" ? w.widthPct : undefined,
      }));
      for (const def of ALL_DEFAULT_WIDGETS) {
        if (!savedIds.has(def.id)) merged.push({ ...def });
      }
      return merged;
    }
  } catch { /* mejor esfuerzo: ignorar */ }
  return ALL_DEFAULT_WIDGETS.map(w => ({ ...w }));
}

// ── Constantes de presentación ────────────────────────────────────
// Todo esto vivía dentro del componente (o de `renderWidget`), así que se
// reconstruía entero en cada render — incluido el tic del reloj. Son valores fijos:
// aquí se crean una sola vez y además dejan de generar identidades nuevas que
// obligan a React a rehacer estilos en cada pasada.

// Etapas del job del agente PC, en orden: de ellas sale la barra de progreso.
const STAGES = ["heartbeat_online","job_claimed","login_ok","assignment_opened","enunciado_extracted","solver_started","result_saved","job_done"];
const STAGE_INDEX = new Map(STAGES.map((st, i) => [st, i]));
const STAGE_LABELS = {
  "heartbeat_online":     "Agente online",
  "job_claimed":          "Job recogido",
  "login_ok":             "Login en Alud OK",
  "assignment_opened":    "Entrega abierta",
  "enunciado_extracted":  "Enunciado extraído",
  "solver_started":       "Cowork iniciado",
  "result_saved":         "Instrucción enviada",
  "vpn_connecting":       "Conectando la VPN",
  "vpn_ready":            "VPN conectada",
  "vpn_error":            "VPN no disponible",
  "streaming_starting":   "Lanzando Sunshine",
  "streaming_ready":      "Sunshine listo — abre Moonlight",
  "job_done":             "Completado",
};
const JOB_STATUS_LABEL = {
  "pending":  "En cola — esperando agente",
  "claimed":  "Agente ha recogido el job",
  "running":  "En ejecución",
  "done":     "Completado",
  "failed":   "Error",
};

const INPUT_STYLE       = { padding: "9px 12px", background: "var(--surface2)", border: "0.5px solid var(--border2)", borderRadius: 8, color: "var(--text)", fontSize: 13, fontFamily: "'DM Sans', sans-serif", width: "100%" };
const FIELD_LABEL_STYLE = { fontSize: 11, letterSpacing: "0.1em", textTransform: "uppercase", color: "var(--muted2)", marginBottom: 6 };

// Qué hacer para ganar los puntos que faltan en cada componente del bienestar.
const POTENTIAL_VERBS = {
  "😴 Sueño": "Durmiendo más",
  "🚶 Pasos": "Caminando más pasos",
  "🔥 Energía": "Quemando más calorías activas",
  "🧍 De pie": "Pasando más horas de pie",
  "🪜 Pisos": "Subiendo más pisos",
  "❤️ HRV": "Mejorando tu recuperación (HRV)",
  "🫀 FC reposo": "Bajando tu FC en reposo",
  "💓 Recuperación cardio": "Mejorando tu recuperación cardio",
  "🫁 VO₂max": "Subiendo tu VO₂max",
  "🏃 FC caminando": "Bajando tu FC al caminar",
  "⚖️ % Grasa": "Bajando tu % de grasa",
  "☀️ Luz natural": "Saliendo más rato a la luz del día",
  "🌬️ Resp.": "Estabilizando tu frecuencia respiratoria",
};

// Explicación de cada fase del sueño (tooltip del widget).
const STAGE_TIPS = {
  deep: { label: "Sueño profundo (N3)", color: "#4a72b0", tip: "Restaura el cuerpo, consolida la memoria muscular y libera hormona del crecimiento. Es el más reparador. Óptimo: 13–23% del total (≈1–2h en 8h de sueño). Disminuye con la edad." },
  rem:  { label: "Sueño REM", color: "#8b68c4", tip: "Procesa emociones, consolida recuerdos y favorece la creatividad. Los sueños ocurren aquí. Óptimo: 20–25% del total (≈1.5–2h en 8h). Se acumula en la segunda mitad de la noche." },
  core: { label: "Sueño ligero (N1/N2)", color: "#4f8fa3", tip: "Fase de transición y procesamiento de información. Ocupa la mayor parte del sueño. Normal: 50–60% del total. Necesario para consolidar el ciclo de sueño." },
  awake:{ label: "Tiempo despierto", color: "var(--muted)", tip: "Microdespertares durante la noche. Normal: 10–30 min. Más de 45 min puede indicar apnea, estrés o mala higiene del sueño." },
};

const WORKOUT_ICONS = { Running:"🏃", Walking:"🚶", Cycling:"🚴", Swimming:"🏊", "Strength Training":"🏋️", HIIT:"⚡", Yoga:"🧘", Basketball:"🏀", Soccer:"⚽", Tennis:"🎾", Hiking:"🥾" };

// Widgets de salud que en modo simple se colapsan en un bloque con pestañas.
const HEALTH_TAB_LABELS = {
  health_wellness: "Bienestar",
  health_sleep:    "Sueño",
  health_activity: "Actividad",
  health_hrv:      "HRV",
  health_heart:    "FC",
  health_workouts: "Entrenos",
};

const DIAS_INICIAL = ["D","L","M","X","J","V","S"];

// Barra de mezcla de la cartera. Una clase que Indexa estrene y el backend no sepa
// clasificar cae en "otros" y se sigue viendo: desaparecer de la barra dejaría una
// cartera que no suma 100 % sin decir por qué.
const CLASES_CARTERA_COLOR = {
  acciones:  "var(--accent)",
  bonos:     "#4f8fa3",
  monetario: "#8b68c4",
  efectivo:  "#6aaa82",
  otros:     "var(--muted2)",
};
// Tipos de cuenta de Indexa. Un tipo nuevo cae a su nombre en crudo, que es feo pero
// cierto; inventarle una traducción sería peor.
const CUENTA_INDEXA_LABEL = {
  mutual: "Fondos", pension: "Pensiones", epsv: "EPSV", employment_plan: "Plan de empleo",
};
const CLASES_CARTERA_LABEL = {
  acciones: "Acciones", bonos: "Bonos", monetario: "Monetario",
  efectivo: "Efectivo", otros: "Otros",
};

// ── Preferencias de layout persistidas ───────────────────────────
// Se leen dos veces (estado + ref que usan los manejadores de arrastre), así que el
// parseo vive aquí una sola vez en lugar de copiado en cada inicializador.
function leerNumColumnas() {
  try { const s = localStorage.getItem("la_num_columns"); return s ? parseInt(s, 10) : 2; }
  catch { return 2; }
}

function leerColSplits() {
  try {
    const n = leerNumColumnas();
    const s = localStorage.getItem("la_col_splits");
    if (s) { const p = JSON.parse(s); if (Array.isArray(p) && p.length === n - 1) return p; }
    // migrar clave antigua
    const old = localStorage.getItem("la_column_split");
    if (old && n === 2) return [parseFloat(old)];
    return DEFAULT_SPLITS[n] || [0.65];
  }
  catch { return [0.65]; }
}

function leerBodyGoals() {
  try { const s = localStorage.getItem("la_body_goals"); return s ? JSON.parse(s) : {}; }
  catch { return {}; }
}

const TIME_OPTIONS = Array.from({ length: 48 }, (_, i) => {
  const totalMin = i * 30;
  return `${String(Math.floor(totalMin / 60)).padStart(2, "0")}:${String(totalMin % 60).padStart(2, "0")}`;
});

// Campo de fecha en formato DD/MM/AAAA fijo — independiente del locale del sistema/navegador
function DateInput({ value, onChange }) {
  const [text, setText] = useState(() => isoToDdMmYyyy(value));
  // Resincronizar el texto cuando cambia la prop, sin efecto (evita un render en cascada)
  const [prevValue, setPrevValue] = useState(value);
  if (value !== prevValue) {
    setPrevValue(value);
    setText(isoToDdMmYyyy(value));
  }

  function commit(raw) {
    const m = /^\s*(\d{1,2})[/\-.](\d{1,2})[/\-.](\d{2,4})\s*$/.exec(raw);
    if (m) {
      const dd = parseInt(m[1], 10);
      const mm = parseInt(m[2], 10);
      const yyyy = m[3].length === 2 ? 2000 + parseInt(m[3], 10) : parseInt(m[3], 10);
      const d = new Date(yyyy, mm - 1, dd);
      if (d.getFullYear() === yyyy && d.getMonth() === mm - 1 && d.getDate() === dd) {
        const iso = `${yyyy}-${String(mm).padStart(2, "0")}-${String(dd).padStart(2, "0")}`;
        setText(isoToDdMmYyyy(iso));
        if (iso !== value) onChange(iso);
        return;
      }
    }
    setText(isoToDdMmYyyy(value));
  }

  return (
    <input
      type="text" inputMode="numeric" placeholder="DD/MM/AAAA" className="la-time-input"
      value={text}
      onChange={e => setText(e.target.value)}
      onBlur={e => commit(e.target.value)}
      onKeyDown={e => { if (e.key === "Enter") { commit(e.target.value); e.currentTarget.blur(); } }}
      style={{
        width: "100%", padding: "9px 12px", background: "var(--surface2)",
        border: "0.5px solid var(--border2)", borderRadius: 8, color: "var(--text)",
        fontSize: 14, fontFamily: "'DM Mono', monospace",
      }}
    />
  );
}

// Campo de hora 24h: se puede escribir directamente o elegir de una lista pequeña y scrolleable
function TimeInput({ value, onChange }) {
  const [open, setOpen]   = useState(false);
  const [text, setText]   = useState(value || "");
  const wrapRef = useRef(null);
  // Resincronizar el texto cuando cambia la prop, sin efecto (evita un render en cascada)
  const [prevValue, setPrevValue] = useState(value);
  if (value !== prevValue) {
    setPrevValue(value);
    setText(value || "");
  }

  useEffect(() => {
    if (!open) return;
    const onOutside = e => { if (wrapRef.current && !wrapRef.current.contains(e.target)) setOpen(false); };
    document.addEventListener("mousedown", onOutside);
    return () => document.removeEventListener("mousedown", onOutside);
  }, [open]);

  function commit(raw) {
    const m = /^(\d{1,2})[:hH]?(\d{2})?$/.exec(raw.trim());
    if (m) {
      const hh = Math.min(23, parseInt(m[1], 10));
      const mm = m[2] ? Math.min(59, parseInt(m[2], 10)) : 0;
      const formatted = `${String(hh).padStart(2, "0")}:${String(mm).padStart(2, "0")}`;
      setText(formatted);
      if (formatted !== value) onChange(formatted);
    } else {
      setText(value || "");
    }
  }

  return (
    <div ref={wrapRef} style={{ position: "relative", flex: 1 }}>
      <input
        type="text" className="la-time-input" inputMode="numeric" placeholder="HH:MM"
        value={text}
        onFocus={() => setOpen(true)}
        onChange={e => setText(e.target.value)}
        onBlur={e => commit(e.target.value)}
        onKeyDown={e => { if (e.key === "Enter") { commit(e.target.value); setOpen(false); e.currentTarget.blur(); } }}
        style={{
          width: "100%", padding: "9px 10px", background: "var(--surface2)",
          border: "0.5px solid var(--border2)", borderRadius: 8, color: "var(--text)",
          fontSize: 14, fontFamily: "'DM Mono', monospace", textAlign: "center",
        }}
      />
      {open && (
        <div style={{
          position: "absolute", top: "calc(100% + 4px)", left: 0, right: 0,
          maxHeight: 160, overflowY: "auto", zIndex: 20,
          background: "var(--surface2)", border: "0.5px solid var(--border2)",
          borderRadius: 8, boxShadow: "0 12px 32px rgba(0,0,0,0.5)",
        }}>
          {TIME_OPTIONS.map(o => (
            <div key={o} className="la-time-option"
              onMouseDown={() => { commit(o); setOpen(false); }}
              style={{
                padding: "5px 10px", fontSize: 12, fontFamily: "'DM Mono', monospace",
                textAlign: "center", cursor: "pointer",
                color: o === text ? "var(--accent)" : "var(--text)",
              }}
            >{o}</div>
          ))}
        </div>
      )}
    </div>
  );
}

// ── COMPONENTE PRINCIPAL ─────────────────────────────────────────
export default function Dashboard() {
  const [token]               = useState(() => localStorage.getItem("la_token") || "");
  const [now, setNow]         = useState(new Date());
  const [notificationsEnabled, setNotificationsEnabled] = useState(() => {
    try { return localStorage.getItem("la_notifications") === "true" && Notification.permission === "granted"; } catch { return false; }
  });
  const [exporting, setExporting] = useState(false);
  const [activeEvent, setActiveEvent] = useState(null);
  const [openIdea, setOpenIdea]       = useState(null);
  const [allEvents, setAllEvents]     = useState([]);
  const [loading, setLoading]         = useState(true);
  const [slowBoot, setSlowBoot]       = useState(false);
  const [authNeeded, setAuthNeeded]   = useState(false);
  const [ideas, setIdeas]             = useState([]);
  const [recording, setRecording]     = useState(false);
  const [processing, setProcessing]   = useState(false);
  // Sugerencia de evento detectada por GPT al capturar una idea ("el martes al
  // dentista"). Vive solo en la sesión: es una oferta de un toque justo después de
  // dictarla, no un dato que haya que persistir.
  const [eventoSugerido, setEventoSugerido] = useState(null);   // {ideaId, titulo, fecha, hora}
  const [sugerenciaEstado, setSugerenciaEstado] = useState(null); // null | "creando" | "ok" | "error"
  const [showTextIdea, setShowTextIdea]     = useState(false);
  const [textIdeaInput, setTextIdeaInput]   = useState("");
  const [textIdeaSubmitting, setTextIdeaSubmitting] = useState(false);
  const [textIdeaError, setTextIdeaError]   = useState(null);

  // ── Jarvis ──
  // La conversación vive en el cliente: el backend no guarda nada (ver /jarvis). Se
  // persiste en localStorage para que no se pierda al recargar, con el mismo try/catch
  // que el resto de claves `la_`.
  const [jarvisMensajes, setJarvisMensajes] = useState(() => {
    try {
      const guardado = JSON.parse(localStorage.getItem("la_jarvis_chat") || "[]");
      return Array.isArray(guardado) ? guardado.slice(-40) : [];
    } catch { return []; /* mejor esfuerzo: empezar en blanco */ }
  });
  const [jarvisBorrador, setJarvisBorrador]     = useState("");
  const [jarvisPensando, setJarvisPensando]     = useState(false);
  const [jarvisPendiente, setJarvisPendiente]   = useState(null);
  const [jarvisConfirmando, setJarvisConfirmando] = useState(false);
  const [jarvisEscuchando, setJarvisEscuchando] = useState(false);
  const [jarvisHabla, setJarvisHabla] = useState(() => {
    try { return localStorage.getItem("la_jarvis_voz") === "1"; } catch { return false; }
  });
  const jarvisFinRef = useRef(null);
  const jarvisVozRef = useRef(null);

  // ── Modo llamada ──
  // Hablar con Jarvis como por teléfono: escucha seguida, se envía solo al detectar que
  // has terminado la frase, contesta en voz y vuelve a escuchar. Todo el estado vivo va
  // en refs y no en useState porque lo leen los callbacks del reconocimiento de voz, que
  // se crean una vez y sobreviven a los renders: con estado normal leerían siempre el
  // valor del render en que nacieron.
  const [jarvisLlamada, setJarvisLlamada] = useState(false);
  const [jarvisFase, setJarvisFase]       = useState("escuchando");
  const [jarvisParcial, setJarvisParcial] = useState("");
  const llamadaRef  = useRef(false);   // la llamada sigue viva
  const recRef      = useRef(null);    // reconocimiento en curso
  const silencioRef = useRef(null);    // temporizador de "ha terminado de hablar"
  const buferRef    = useRef("");      // lo dicho en este turno
  const hablandoRef = useRef(false);   // Jarvis habla: el micro está cerrado (anti-eco)
  const reaperturasRef = useRef(0);    // veces seguidas que se ha reabierto sin oír nada
  // Cada turno de voz lleva número. `speechSynthesis.cancel()` dispara el `onend` de lo
  // que estuviera sonando, así que sin esto el callback de una respuesta ya descartada
  // reabriría el micro justo cuando empieza a sonar la siguiente.
  const vozTurnoRef = useRef(0);
  const [departureMap, setDepartureMap]           = useState({});
  const [departureLoadingId, setDepartureLoadingId] = useState(null);
  const [departurePickingId, setDeparturePickingId] = useState(null);
  const [classEvents, setClassEvents] = useState([]);
  const [classesOpen, setClassesOpen] = useState(false);
  const [showCreateEvent, setShowCreateEvent] = useState(false);
  const [calendarsList, setCalendarsList]     = useState([]);
  const [eventForm, setEventForm] = useState({ subject: "", date: "", startTime: "", endTime: "", location: "", calendarId: "", alud_url: "" });
  const [eventCreating, setEventCreating]     = useState(false);
  const [eventCreateError, setEventCreateError] = useState(null);
  const [editingEventId, setEditingEventId]   = useState(null);
  const [wolModal, setWolModal]       = useState(null);   // entrega seleccionada
  const [wolStatus, setWolStatus]     = useState(null);   // 'loading' | 'ok' | 'error'
  const [pcModal, setPcModal]         = useState(false);  // panel "Streaming PC"
  const [pcStatus, setPcStatus]       = useState(null);   // 'loading' | 'ok' | 'error'
  const [pcPower, setPcPower]         = useState(null);   // feedback apagar/suspender
  const [confirmShutdown, setConfirmShutdown] = useState(false); // confirmación de apagar
  const [weather, setWeather]         = useState(null);
  const [weatherExpanded, setWeatherExpanded] = useState(false);
  // {lat, lon} | false (sin permiso/soporte) | null (pendiente). Arranca en false
  // si el navegador no tiene geolocalización, para no hacer setState síncrono en el efecto.
  const [geo, setGeo] = useState(() =>
    (typeof navigator !== "undefined" && navigator.geolocation) ? null : false);
  const [agentState, setAgentState]   = useState(null);
  const [activeJobId, setActiveJobId] = useState(null);
  const [jobEvents, setJobEvents] = useState([]);
  const [jobTerminal, setJobTerminal] = useState(null);
  const [jobStatus, setJobStatus] = useState(null);
  const [training, setTraining]           = useState(null);
  const [healthData, setHealthData]         = useState(null);
  // Con sesión iniciada, la carga de salud arranca en el mount: empezar ya en "cargando"
  // evita un setState síncrono dentro del efecto.
  const [healthLoading, setHealthLoading]   = useState(() => !!localStorage.getItem("la_token"));
  const [healthLastSync, setHealthLastSync] = useState(null);
  // Qué días estuvo puesto el reloj (lo calcula el backend en /health/metrics). Es la
  // diferencia entre "no hay dato" y "no se pudo medir", que hasta ahora solo sabía el
  // correo de la mañana.
  const [healthReloj, setHealthReloj]       = useState(null);
  // Ajustes de salud: hoy solo la fecha del cambio de dispositivo. Las puntuaciones
  // comparan cada día contra la propia historia, así que sin este corte se estaría
  // midiendo la diferencia entre dos relojes y leyéndola como fisiología.
  const [healthAjustes, setHealthAjustes]   = useState(null);
  // Fecha a partir de la cual los datos son del aparato actual. `null` = nunca se ha
  // cambiado, y entonces todo se comporta igual que antes de que esto existiera.
  const corteDispositivo = healthAjustes?.cambio_dispositivo || null;
  const [dispositivoGuardando, setDispositivoGuardando] = useState(false);
  const [dispositivoFecha, setDispositivoFecha] = useState("");
  const [dispositivoNombre, setDispositivoNombre] = useState("");
  const [wellnessView, setWellnessView]     = useState("weekly");
  const [scoreTooltip, setScoreTooltip]       = useState(false);
  const [sleepScoreTooltip, setSleepScoreTooltip] = useState(false);
  const [sleepExcluding, setSleepExcluding]       = useState(null); // date string being toggled
  // Los tres salen del mismo `la_body_goals`: se lee una vez en vez de parsearlo
  // por separado en cada inicializador.
  const [bodyGoals, setBodyGoals] = useState(() => {
    const g = leerBodyGoals();
    return { targetWeight: g.targetWeight ?? 67, targetBodyFat: g.targetBodyFat ?? null };
  });
  const [bodyGoalWeight, setBodyGoalWeight] = useState(() => leerBodyGoals().targetWeight ?? 67);
  const [bodyGoalFat, setBodyGoalFat]       = useState(() => leerBodyGoals().targetBodyFat ?? "");
  const [showSessionForm, setShowSessionForm] = useState(false);
  const [sessionDate, setSessionDate]     = useState(() => new Date().toISOString().slice(0, 10));
  const [sessionHours, setSessionHours]   = useState("1");
  const [trainingLoading, setTrainingLoading] = useState(false);
  const [showSettings, setShowSettings]   = useState(false);
  const [sysStatus, setSysStatus]         = useState(null);   // panel de estado del sistema
  const [sysLoading, setSysLoading]       = useState(false);
  const [logsAbiertos, setLogsAbiertos]   = useState(false);  // registro del backend, plegado por defecto
  const [avisoPrueba, setAvisoPrueba]     = useState("");     // resultado de "Probar aviso"
  // Interruptor del resumen diario. Vive en el backend (Supabase) y no en localStorage:
  // quien manda el correo es el backend, que no ve el localStorage, y un flag en memoria
  // suya se borraría en el próximo cold start de Fly.
  const [briefCfg, setBriefCfg]           = useState(null);
  const [briefGuardando, setBriefGuardando] = useState(false);
  const [healthModalOpen, setHealthModalOpen] = useState(false);
  // Histórico largo, solo para el panel de patrones del modal (ver efecto de carga).
  const [healthLargo, setHealthLargo]         = useState(null);
  const [healthLargoFallo, setHealthLargoFallo] = useState(false);
  const healthLargoPedido                     = useRef(false);
  const [simpleMode, setSimpleMode]       = useState(() => localStorage.getItem("la_simple_mode") === "1");
  const [simpleHealthTab, setSimpleHealthTab] = useState("health_wellness");
  const [orientation, setOrientation]     = useState(() =>
    (typeof window !== "undefined" && window.matchMedia("(orientation: portrait)").matches) ? "portrait" : "landscape");
  const [trainingSettingsPrice, setTrainingSettingsPrice] = useState("");
  const [trainingSettingsSpp, setTrainingSettingsSpp]     = useState("");
  const [trainingSettingsSaving, setTrainingSettingsSaving] = useState(false);
  const [trainingDays, setTrainingDays] = useState(() => {
    try { return JSON.parse(localStorage.getItem("la_training_days") || "[1,3,4,0]"); } catch { return [1,3,4,0]; }
  });
  // Conteo de ropa (widget temporal). Se persiste en el backend (Supabase); las
  // fotos van como data URL redimensionada en el navegador antes de subirlas.
  const [finanzas, setFinanzas]                 = useState(null);
  const [finanzasCargando, setFinanzasCargando] = useState(false);
  const [finanzasDetalle, setFinanzasDetalle]   = useState(false);   // posiciones desplegadas

  // Cartera manual de ETFs (Revolut, precio real vía Twelve Data).
  const [carteraEtf, setCarteraEtf]                 = useState(null);
  const [carteraEtfCargando, setCarteraEtfCargando] = useState(false);
  // Formulario de "+ Añadir aportación", uno por ticker: { [ticker]: { abierto, fecha, importe, guardando } }
  const [etfAportForm, setEtfAportForm] = useState({});

  const [clothing, setClothing]                 = useState([]);
  const [showClothingForm, setShowClothingForm] = useState(false);
  const [clothingName, setClothingName]         = useState("");
  const [clothingPrice, setClothingPrice]       = useState("");
  const [clothingCurrency, setClothingCurrency] = useState("EUR");
  const [clothingPhoto, setClothingPhoto]       = useState(null);
  const [clothingSaving, setClothingSaving]     = useState(false);
  const [clothingError, setClothingError]       = useState(null); // mensaje de fallo al guardar
  const [clothingZoom, setClothingZoom]         = useState(null); // data URL en pantalla completa
  const [isEditMode, setIsEditMode]       = useState(false);
  const [draggingId, setDraggingId]       = useState(null);
  const [dragPos, setDragPos]             = useState(null);
  const [dragOverId, setDragOverId]       = useState(null);
  const [dragOverSide, setDragOverSide]   = useState("after");
  const [numColumns, setNumColumns] = useState(leerNumColumnas);
  const numColumnsRef               = useRef(leerNumColumnas());
  const [colSplits, setColSplits]   = useState(leerColSplits);
  const colSplitsRef                = useRef(leerColSplits());
  // Dos selecciones de widgets independientes: la del modo completo y la del
  // modo simplificado. El panel de ajustes edita la que corresponde al modo
  // activo, así cada modo recuerda sus propios widgets.
  const [widgetConfig, setWidgetConfig]             = useState(() => loadWidgetConfig("la_widget_config"));
  const [simpleWidgetConfig, setSimpleWidgetConfig] = useState(() => loadWidgetConfig("la_simple_widget_config"));

  const mediaRecorderRef = useRef(null);
  const chunksRef        = useRef([]);
  // Eventos de los que ya se ha lanzado la notificación de "en 15 min".
  const notificadosRef   = useRef(new Set());
  // Cuándo empezó a seguirse el job actual, para el techo de una hora.
  const jobInicioRef     = useRef({ id: null, t: 0 });
  const resizeDragRef    = useRef(null);
  const dragStateRef     = useRef(null);

  useEffect(() => { colSplitsRef.current = colSplits; numColumnsRef.current = numColumns; }, [colSplits, numColumns]);

  // CSS global
  useEffect(() => {
    if (document.getElementById("dashboard-global-css")) return;
    const style = document.createElement("style");
    style.id = "dashboard-global-css";
    style.textContent = GLOBAL_CSS;
    document.head.appendChild(style);
  }, []);

  // Reloj. Se engancha al cambio de minuto en vez de tirar cada 30 s: el reloj muestra
  // HH:MM, así que la mitad de aquellos tics no cambiaba nada y la otra mitad llegaba
  // con hasta 30 s de retraso. Cada tic re-renderiza el dashboard entero (de `now`
  // cuelgan los estados "en curso"/"pasado" de los eventos), así que el ahorro es real
  // y además la hora pasa a cambiar en el segundo exacto.
  useEffect(() => {
    let id;
    const programarSiguienteMinuto = () => {
      const ahora = new Date();
      const restanteMs = 60_000 - (ahora.getSeconds() * 1000 + ahora.getMilliseconds());
      id = setTimeout(() => { setNow(new Date()); programarSiguienteMinuto(); }, restanteMs);
    };
    programarSiguienteMinuto();
    return () => clearTimeout(id);
  }, []);

  // Cerrar ajustes / modal de salud con Escape
  useEffect(() => {
    const handler = e => { if (e.key === "Escape") { setShowSettings(false); setHealthModalOpen(false); } };
    document.addEventListener("keydown", handler);
    return () => document.removeEventListener("keydown", handler);
  }, []);

  // Detectar orientación del dispositivo (para el modo simplificado)
  useEffect(() => {
    const mq = window.matchMedia("(orientation: portrait)");
    const handler = e => setOrientation(e.matches ? "portrait" : "landscape");
    mq.addEventListener?.("change", handler);
    return () => mq.removeEventListener?.("change", handler);
  }, []);

  function toggleSimpleMode() {
    setSimpleMode(v => {
      const nv = !v;
      localStorage.setItem("la_simple_mode", nv ? "1" : "0");
      if (nv) setIsEditMode(false);
      return nv;
    });
  }

  // Cargar eventos. Como el resto de cargas, solo con sesión: sin token la pantalla
  // que se pinta es la de login, y estas llamadas solo servían para despertar la
  // máquina de Fly y recibir un 401.
  function loadEvents() {
    return apiFetch(`${API}/calendar/events`, { headers: authHeaders() })
      .then(r => r.json())
      .then(data => {
        if (data.error) { setAuthNeeded(true); setLoading(false); return; }
        setAllEvents(data.events || []);
        setLoading(false);
      })
      .catch(() => { setAuthNeeded(true); setLoading(false); });
  }
  useEffect(() => { if (token) loadEvents(); }, [token]);

  // El backend (Fly.io) escala a cero: el primer arranque tarda ~10-15s. Si la carga
  // inicial se demora, avisamos de que se está "despertando el servidor".
  useEffect(() => {
    // El aviso solo se pinta dentro del skeleton (gated por `loading`), así que
    // basta con cancelar el timeout al terminar la carga.
    if (!loading) return;
    const id = setTimeout(() => setSlowBoot(true), 4000);
    return () => clearTimeout(id);
  }, [loading]);

  function openCreateEvent() {
    const n = new Date();
    const today = `${n.getFullYear()}-${String(n.getMonth() + 1).padStart(2, "0")}-${String(n.getDate()).padStart(2, "0")}`;
    setEventForm({ subject: "", date: today, startTime: "09:00", endTime: "09:30", location: "", calendarId: "", alud_url: "" });
    setEditingEventId(null);
    setEventCreateError(null);
    setShowCreateEvent(true);
    if (calendarsList.length === 0) {
      apiFetch(`${API}/calendar/calendars`, { headers: authHeaders() })
        .then(r => r.json())
        .then(data => { if (Array.isArray(data)) setCalendarsList(data); })
        .catch(() => {});
    }
  }

  function openEditEvent(ev) {
    const pad = n => String(n).padStart(2, "0");
    const sd = new Date(ev.start);
    const ed = new Date(ev.end);
    const date = `${sd.getFullYear()}-${pad(sd.getMonth() + 1)}-${pad(sd.getDate())}`;
    setEventForm({
      subject: ev.title || "",
      date,
      startTime: `${pad(sd.getHours())}:${pad(sd.getMinutes())}`,
      endTime: `${pad(ed.getHours())}:${pad(ed.getMinutes())}`,
      location: ev.location || "",
      calendarId: "",
      alud_url: ev.alud_url || "",
    });
    setEditingEventId(ev.id);
    setEventCreateError(null);
    setShowCreateEvent(true);
  }

  function closeEventModal() {
    if (eventCreating) return;
    setShowCreateEvent(false);
    setEditingEventId(null);
  }

  async function submitCreateEvent() {
    if (eventCreating) return;
    const { subject, date, startTime, endTime, location, calendarId, alud_url } = eventForm;
    if (!subject.trim() || !date || !startTime || !endTime) {
      setEventCreateError("Completa título, fecha y horas");
      return;
    }
    setEventCreating(true);
    setEventCreateError(null);
    try {
      const payload = {
        subject: subject.trim(),
        start: `${date}T${startTime}:00`,
        end: `${date}T${endTime}:00`,
        location: location.trim() || null,
      };
      if (alud_url && alud_url.trim()) {
        payload.description = `alud_url: ${alud_url.trim()}`;
      }
      let r;
      if (editingEventId) {
        r = await apiFetch(`${API}/calendar/events/${editingEventId}`, {
          method: "PATCH",
          headers: jsonHeaders(),
          body: JSON.stringify(payload),
        });
      } else {
        payload.calendar_id = calendarId || null;
        r = await apiFetch(`${API}/calendar/events`, {
          method: "POST",
          headers: jsonHeaders(),
          body: JSON.stringify(payload),
        });
      }
      const data = await r.json();
      if (data.error) {
        setEventCreateError(data.error);
      } else {
        setShowCreateEvent(false);
        setEditingEventId(null);
        await loadEvents();
      }
    } catch {
      setEventCreateError("Error de conexión con el backend");
    }
    setEventCreating(false);
  }

  // Cargar clases
  useEffect(() => {
    if (!token) return;
    apiFetch(`${API}/calendar/classes`, { headers: authHeaders() })
      .then(r => r.json())
      .then(data => {
        if (Array.isArray(data.events)) setClassEvents(data.events);
      })
      .catch(() => { /* mejor esfuerzo: sin clases si falla */ });
  }, [token]);

  // Cargar resumen entrenamiento
  useEffect(() => { if (token) loadTraining(); }, [token]);

  // Cargar la cartera de Indexa
  useEffect(() => { if (token) loadFinanzas(); }, [token]);

  // Cargar la cartera manual de ETFs
  useEffect(() => { if (token) loadCarteraEtf(); }, [token]);

  // Cargar datos de salud
  useEffect(() => {
    if (!token) return;
    apiFetch(`${API}/health/metrics?days=30`, { headers: authHeaders() })
      .then(r => r.json())
      .then(data => {
        setHealthData(data.metrics || {});
        setHealthLastSync(data.last_sync || null);
        // Qué días estuvo puesto el reloj. `null` si el backend no lo manda (no es lo
        // mismo que "no lo llevaste": es que no se sabe), y las conclusiones lo tratan
        // como tal.
        setHealthReloj(data.reloj || null);
        setHealthAjustes(data.ajustes || null);
        setHealthLoading(false);
      })
      .catch(() => setHealthLoading(false));
  }, [token]);

  // Histórico largo para el panel de patrones. Se pide APARTE y solo al abrir el
  // modal, no en la carga inicial: un año de métricas es bastante más payload que 30
  // días y no hace falta para pintar el dashboard. Se pide una sola vez por sesión.
  //
  // El guard de "ya pedido" va en un ref y no en un estado a propósito: marcarlo con
  // setState obligaría a llamarlo en el cuerpo del efecto, que es justo lo que
  // prohíbe react-hooks. El estado de carga se deriva más abajo, no se guarda.
  useEffect(() => {
    if (!token || !healthModalOpen || healthLargoPedido.current) return;
    healthLargoPedido.current = true;
    apiFetch(`${API}/health/metrics?days=${HEALTH_DIAS_PATRONES}`, { headers: authHeaders() })
      .then(r => r.json())
      .then(data => setHealthLargo(data.metrics || {}))
      .catch(() => setHealthLargoFallo(true));
  }, [token, healthModalOpen]);

  // Cargar ideas
  useEffect(() => {
    if (!token) return;
    apiFetch(`${API}/ideas`, { headers: authHeaders() })
      .then(r => r.json())
      .then(data => Array.isArray(data) && setIdeas(data))
      .catch(() => {});
  }, [token]);

  // Cargar conteo de ropa
  useEffect(() => {
    if (!token) return;
    apiFetch(`${API}/clothing`, { headers: authHeaders() })
      .then(r => r.json())
      .then(data => Array.isArray(data) && setClothing(data))
      .catch(() => {});
  }, [token]);

  // Geolocalización del dispositivo (para clima y origen del cálculo de salida).
  // Solo se pide con sesión iniciada (si no, el prompt saldría en la pantalla de
  // login). Si el usuario no da permiso o no hay soporte, geo = false → se usan los
  // valores fijos de siempre (WEATHER_LAT/LON y HOME_ADDRESS).
  useEffect(() => {
    if (!token || !navigator.geolocation) return;   // geo ya arranca en false
    navigator.geolocation.getCurrentPosition(
      pos => setGeo({ lat: pos.coords.latitude, lon: pos.coords.longitude }),
      () => setGeo(false),
      { timeout: 8000, maximumAge: 600000 },
    );
  }, [token]);

  // Cargar clima — con las coordenadas del dispositivo si las hay, si no las fijas.
  // Espera a que la geolocalización se resuelva (coords o false) para no pedir dos veces.
  useEffect(() => {
    if (!token || geo === null) return;
    const q = geo ? `?lat=${geo.lat}&lon=${geo.lon}` : "";
    apiFetch(`${API}/weather${q}`, { headers: authHeaders() })
      .then(r => r.ok ? r.json() : null)
      .then(data => { if (data && typeof data.temp === "number") setWeather(data); })
      .catch(() => {});
  }, [geo, token]);

  // Estado del agente PC (heartbeat). Solo se sondea con el modal de encendido abierto:
  // es el único sitio donde se pinta (isAgentOnline). Sondear siempre, cada 10s, mantenía
  // despierta la máquina de Fly las 24 h y anulaba su auto_stop_machines / min_machines_running=0.
  const wolModalAbierto = !!wolModal;
  // Cualquiera de los dos modales muestra el progreso del job en vivo.
  const jobModalAbierto = wolModalAbierto || pcModal;
  useEffect(() => {
    if (!token || !wolModalAbierto) return;

    let mounted = true;
    async function loadAgent() {
      try {
        const r = await apiFetch(`${API}/agents/${AGENT_ID}`, { headers: authHeaders() });
        const data = await r.json();
        if (mounted) setAgentState(data);
      } catch {
        if (mounted) setAgentState({ status: "offline", offline: true });
      }
    }

    loadAgent();   // sin esperar los 10s: el modal necesita el estado ya
    const id = setInterval(loadAgent, 10000);
    return () => { mounted = false; clearInterval(id); };
  }, [token, wolModalAbierto]);

  // Notificaciones del navegador — solicitar permiso
  useEffect(() => {
    if (!token || !notificationsEnabled) return;
    if (Notification.permission === "default") {
      Notification.requestPermission().then(perm => {
        if (perm === "granted") {
          localStorage.setItem("la_notifications", "true");
          setNotificationsEnabled(true);
        } else {
          localStorage.setItem("la_notifications", "false");
          setNotificationsEnabled(false);
        }
      });
    }
  }, [token, notificationsEnabled]);

  // Notificaciones — eventos próximos (15 min antes).
  // El registro de "ya avisado" vive en un ref y no dentro del efecto: `allEvents`
  // está en las dependencias (recargar la agenda tras crear un evento lo cambia), y
  // con el Set local eso lo vaciaba y volvía a notificar eventos ya avisados.
  useEffect(() => {
    if (!token || !notificationsEnabled) return;
    const notified = notificadosRef.current;

    function checkUpcoming() {
      const now = new Date();
      const fifteenMin = new Date(now.getTime() + 15 * 60 * 1000);
      for (const ev of allEvents) {
        if (ev.isAllDay) continue;
        const start = new Date(ev.start.replace("Z", "+00:00"));
        if (start > now && start <= fifteenMin) {
          const key = ev.id || ev.start;
          if (!notified.has(key)) {
            notified.add(key);
            try {
              new Notification("Life Assistant — Evento en 15 min", {
                body: ev.title,
                icon: "/favicon.svg",
              });
            } catch { /* mejor esfuerzo: ignorar */ }
          }
        }
      }
    }

    // Chequear cada minuto
    const id = setInterval(checkUpcoming, 60000);
    checkUpcoming();
    return () => clearInterval(id);
  }, [token, notificationsEnabled, allEvents]);

  // Notificaciones — job completado
  useEffect(() => {
    if (!token || !notificationsEnabled) return;
    if (jobTerminal?.status === "done") {
      try {
        new Notification("Life Assistant — Job completado", {
          body: `La entrega se ha completado correctamente.`,
          icon: "/favicon.svg",
        });
      } catch { /* mejor esfuerzo: ignorar */ }
    }
    // Solo debe disparar cuando el job pasa a "done"; añadir token/notificationsEnabled
    // notificaría tarde al activar las notificaciones con un job ya completado.
  }, [jobTerminal?.status]); // eslint-disable-line react-hooks/exhaustive-deps

  useEffect(() => {
    if (!scoreTooltip) return;
    const handler = () => setScoreTooltip(false);
    document.addEventListener("click", handler);
    return () => document.removeEventListener("click", handler);
  }, [scoreTooltip]);

  useEffect(() => {
    if (!sleepScoreTooltip) return;
    const handler = () => setSleepScoreTooltip(false);
    document.addEventListener("click", handler);
    return () => document.removeEventListener("click", handler);
  }, [sleepScoreTooltip]);

  // Audio
  async function startRecording() {
    const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
    const mr = new MediaRecorder(stream);
    chunksRef.current = [];
    mr.ondataavailable = e => chunksRef.current.push(e.data);
    mr.onstop = async () => {
      stream.getTracks().forEach(t => t.stop());
      setProcessing(true);
      const blob = new Blob(chunksRef.current, { type: "audio/webm" });
      const fd = new FormData();
      fd.append("audio", blob, "audio.webm");
      try {
        const res = await apiFetch(`${API}/ideas/audio`, { method: "POST", headers: authHeaders(), body: fd });
        const data = await res.json();
        if (data.ok) {
          setIdeas(prev => [data.idea, ...prev]);
          recogerSugerencia(data);
        }
      } catch { /* mejor esfuerzo: ignorar */ }
      setProcessing(false);
    };
    mr.start();
    mediaRecorderRef.current = mr;
    setRecording(true);
  }
  function stopRecording() { mediaRecorderRef.current?.stop(); setRecording(false); }

  // ── Idea → evento de Outlook ─────────────────────────────────────────────
  // El backend detecta si la nota llevaba una cita ("el martes al dentista") y valida
  // la fecha antes de proponerla. Aquí solo se ofrece: crear un evento en el calendario
  // es una acción hacia fuera, así que la dispara el usuario con un toque, no sola.
  function recogerSugerencia(data) {
    const ev = data?.evento_sugerido;
    if (!ev?.fecha) return;
    setEventoSugerido({ ...ev, ideaId: data.idea?.id });
    setSugerenciaEstado(null);
  }

  async function crearEventoDesdeIdea() {
    if (!eventoSugerido || sugerenciaEstado === "creando") return;
    setSugerenciaEstado("creando");
    // Sin hora concreta se coloca a las 9:00 como marcador del día; con hora, una hora de duración.
    const inicio = eventoSugerido.hora || "09:00";
    const [hh, mm] = inicio.split(":").map(Number);
    const fin = `${String((hh + 1) % 24).padStart(2, "0")}:${String(mm).padStart(2, "0")}`;
    try {
      const r = await apiFetch(`${API}/calendar/events`, {
        method: "POST",
        headers: jsonHeaders(),
        body: JSON.stringify({
          subject: eventoSugerido.titulo,
          start: `${eventoSugerido.fecha}T${inicio}:00`,
          end: `${eventoSugerido.fecha}T${fin}:00`,
        }),
      });
      const data = await r.json();
      if (r.ok && !data.error) {
        setSugerenciaEstado("ok");
        await loadEvents();   // que aparezca ya en la agenda
      } else {
        setSugerenciaEstado("error");
      }
    } catch {
      setSugerenciaEstado("error");
    }
  }

  function openTextIdea() {
    setTextIdeaInput("");
    setTextIdeaError(null);
    setShowTextIdea(true);
  }

  async function submitTextIdea() {
    if (textIdeaSubmitting) return;
    const text = textIdeaInput.trim();
    if (!text) {
      setTextIdeaError("Escribe algo primero");
      return;
    }
    setTextIdeaSubmitting(true);
    setTextIdeaError(null);
    try {
      const res = await apiFetch(`${API}/ideas/text`, {
        method: "POST",
        headers: jsonHeaders(),
        body: JSON.stringify({ text }),
      });
      const data = await res.json();
      if (data.ok) {
        setIdeas(prev => [data.idea, ...prev]);
        recogerSugerencia(data);
        setShowTextIdea(false);
      } else {
        setTextIdeaError("No se pudo guardar la idea");
      }
    } catch {
      setTextIdeaError("Error de conexión con el backend");
    }
    setTextIdeaSubmitting(false);
  }

  // Descarga un backup JSON con todos los datos personales (ideas, entrenamiento,
  // salud, ropa). El backend nunca incluye tokens ni la cola de jobs.
  async function exportData() {
    if (exporting) return;
    setExporting(true);
    try {
      const res = await apiFetch(`${API}/export`, { headers: authHeaders() });
      const data = await res.json();
      const blob = new Blob([JSON.stringify(data, null, 2)], { type: "application/json" });
      const url  = URL.createObjectURL(blob);
      const a    = document.createElement("a");
      a.href     = url;
      a.download = `life-assistant-backup-${new Date().toISOString().slice(0, 10)}.json`;
      document.body.appendChild(a);
      a.click();
      a.remove();
      URL.revokeObjectURL(url);
    } catch { /* mejor esfuerzo: si falla la descarga, no bloquear la UI */ }
    setExporting(false);
  }

  async function fetchDeparture(ev, mode) {
    if (!ev?.loc || !ev?.start) return;
    const key = ev.id || ev.start;
    setDeparturePickingId(null);
    setDepartureLoadingId(key);
    try {
      // Origen = ubicación del dispositivo si hay geolocalización; si no, el backend
      // usa HOME_ADDRESS por defecto (no mandamos 'origin').
      const body = { destination: ev.loc, event_time: ev.start, mode };
      if (geo) body.origin = `${geo.lat},${geo.lon}`;
      const res = await apiFetch(`${API}/maps/departure`, {
        method: "POST",
        headers: jsonHeaders(),
        body: JSON.stringify(body),
      });
      const data = await res.json();
      setDepartureMap(prev => ({ ...prev, [key]: { ...data, mode } }));
    } catch {
      setDepartureMap(prev => ({ ...prev, [key]: { error: "Error al calcular" } }));
    }
    setDepartureLoadingId(null);
  }


  async function wakePC() {
    setWolStatus("loading");
    try {

      // 1. WOL: pone flag en el backend → HA lo recoge en su poll y envía el magic packet
      try {
        await apiFetch(`${API}/wake-pc`, {
          method: "POST",
          headers: authHeaders(),
        });
      } catch {
        // best-effort, no bloquea el flujo
      }

      // 2. Crear job en Supabase via backend — esto sí es crítico
      const jobRes = await apiFetch(`${API}/jobs`, {
        method: "POST",
        headers: jsonHeaders(),
        body: JSON.stringify({
          dedupe_key: `entrega-${wolModal.title}-${Date.now()}`,
          payload: {
            titulo: wolModal.title,
            alud_url: wolModal.alud_url,
          },
        }),
      });
      if (!jobRes.ok) { setWolStatus("error"); return; }
      const jobData = await jobRes.json();
      setActiveJobId(jobData?.job?.id || null);
      setJobEvents([]);
      setJobTerminal(null);
      setJobStatus("pending");

      setWolStatus("ok");
    } catch {
      setWolStatus("error");
    }
  }

  // ── Streaming PC ─────────────────────────────────────────────────────────
  // El agente es efímero: enciende el PC con WOL y encola el job. Al arrancar
  // Windows, el agente ve el job de streaming y lanza Sunshine (que queda
  // corriendo), luego se cierra. Conectas con Moonlight desde el móvil.
  async function abrirStreaming() {
    setPcModal(true);
    setPcStatus("loading");
    setActiveJobId(null);
    setJobEvents([]);
    setJobTerminal(null);
    setJobStatus("pending");
    try {
      // 1. WOL (best-effort): enciende el PC si está apagado.
      try {
        await apiFetch(`${API}/wake-pc`, {
          method: "POST",
          headers: authHeaders(),
        });
      } catch { /* mejor esfuerzo: el job es lo crítico */ }

      // 2. Relanzar agente (best-effort): si el PC ya estaba encendido, el agente
      // efímero ya terminó; HA lo arranca por SSH al ver este flag.
      try {
        await apiFetch(`${API}/relaunch-agent`, {
          method: "POST",
          headers: authHeaders(),
        });
      } catch { /* mejor esfuerzo */ }

      // 3. Job de abrir Sunshine (crítico): el agente lo despacha al arrancar.
      const jobRes = await apiFetch(`${API}/jobs`, {
        method: "POST",
        headers: jsonHeaders(),
        body: JSON.stringify({
          dedupe_key: `abrir_streaming-${Date.now()}`,
          payload: { accion: "abrir_streaming" },
        }),
      });
      if (!jobRes.ok) { setPcStatus("error"); return; }
      const jobData = await jobRes.json();
      setActiveJobId(jobData?.job?.id || null);
      setPcStatus("ok");
    } catch {
      setPcStatus("error");
    }
  }

  // Apagar/suspender: no pasa por el agente (efímero); marca el flag y HA lo
  // ejecuta por SSH. accion: "shutdown" | "suspend".
  async function pcPowerAction(accion) {
    setConfirmShutdown(false);
    setPcPower(accion === "shutdown" ? "shutting" : "suspending");
    try {
      const r = await apiFetch(`${API}/${accion === "shutdown" ? "shutdown-pc" : "suspend-pc"}`, {
        method: "POST",
        headers: authHeaders(),
      });
      setPcPower(r.ok ? (accion === "shutdown" ? "shutdown_sent" : "suspend_sent") : "error");
    } catch {
      setPcPower("error");
    }
  }

  async function excludeSleepNight(date) {
    setSleepExcluding(date);
    try {
      const r = await apiFetch(`${API}/health/sleep/${date}/exclude`, {
        method: "PATCH",
        headers: authHeaders(),
      });
      if (r.ok) {
        const { excluded } = await r.json();
        setHealthData(prev => {
          if (!prev?.sleep_analysis) return prev;
          return {
            ...prev,
            sleep_analysis: prev.sleep_analysis.map(row =>
              row.date === date
                ? { ...row, extra: { ...(row.extra || {}), excluded } }
                : row
            ),
          };
        });
      }
    } finally {
      setSleepExcluding(null);
    }
  }

  async function deleteIdea(id) {
    await apiFetch(`${API}/ideas/${id}`, { method: "DELETE", headers: authHeaders() });
    setIdeas(prev => prev.filter(i => i.id !== id));
  }

  // ── Jarvis ───────────────────────────────────────────────────────────────
  /** Un turno. Devuelve el texto de la respuesta (o null si falló), que es lo que
   *  encadena el modo llamada para leerlo y volver a escuchar. En llamada la lee siempre,
   *  esté como esté el interruptor 🔊: para eso has llamado. */
  async function enviarAJarvis(texto, { voz = false } = {}) {
    const mensaje = (texto || "").trim();
    if (!mensaje || jarvisPensando) return null;
    // El historial se toma ANTES de añadir el turno nuevo: el mensaje va aparte en el
    // cuerpo, y mandarlo también dentro del historial lo duplicaría.
    const historial = jarvisHistorial(jarvisMensajes);
    setJarvisMensajes(prev => [...prev, { rol: "user", texto: mensaje }]);
    setJarvisBorrador("");
    setJarvisPendiente(null);
    setJarvisPensando(true);
    try {
      const r = await apiFetch(`${API}/jarvis`, {
        method: "POST",
        headers: jsonHeaders(),
        body: JSON.stringify({ mensaje, historial, voz }),
      });
      if (!r.ok) throw await motivoJarvis(r);
      const d = await r.json();
      setJarvisMensajes(prev => [...prev, {
        rol: "assistant",
        texto: d.respuesta || "(sin respuesta)",
        herramientas: d.herramientas || [],
      }]);
      setJarvisPendiente(d.pendiente || null);
      // En llamada habla el ciclo de la llamada, para poder encadenar con la escucha.
      if (jarvisHabla && !voz) hablarJarvis(d.respuesta || "");
      return d.respuesta || "";
    } catch (e) {
      // Un fallo no puede parecerse a una respuesta: se marca como aviso, que se pinta
      // distinto y queda fuera del historial que viaja al backend. Y DICE QUÉ PASÓ: un
      // "no he podido responder" a secas mandaba a mirar la red cuando el problema real
      // era un backend sin desplegar. Es el mismo error que tapó el 400 del Watch.
      setJarvisMensajes(prev => [...prev, {
        rol: "aviso",
        texto: e?.explicado ? e.message : jarvisMotivoError(0),
      }]);
      return null;
    } finally {
      setJarvisPensando(false);
    }
  }

  /** Vacía la conversación visible y lo que viaja como contexto en el próximo turno.
   *  No toca la memoria persistente (`jarvis_memoria`): eso es aparte y sigue en pie —
   *  esto solo es el historial de turnos que se manda en cada petición a /jarvis. */
  function nuevaConversacionJarvis() {
    if (jarvisPensando) return;
    setJarvisMensajes([]);
    setJarvisPendiente(null);
    setJarvisBorrador("");
    try { localStorage.removeItem("la_jarvis_chat"); } catch { /* mejor esfuerzo */ }
  }

  async function confirmarAccionJarvis() {
    if (!jarvisPendiente || jarvisConfirmando) return;
    setJarvisConfirmando(true);
    try {
      const r = await apiFetch(`${API}/jarvis/ejecutar`, {
        method: "POST",
        headers: jsonHeaders(),
        body: JSON.stringify(jarvisPendiente),
      });
      if (!r.ok) throw await motivoJarvis(r);
      const d = await r.json();
      const bien = Boolean(d?.ok);
      setJarvisMensajes(prev => [...prev, {
        rol:   bien ? "assistant" : "aviso",
        texto: bien ? "Hecho." : `No se pudo: ${d?.resultado?.motivo || "error del servidor"}`,
      }]);
      if (bien) {
        setJarvisPendiente(null);
        if (jarvisHabla) hablarJarvis("Hecho.");
        loadEvents();   // el evento nuevo tiene que aparecer ya en el resto del dashboard
      }
    } catch (e) {
      setJarvisMensajes(prev => [...prev, {
        rol: "aviso",
        texto: e?.explicado ? e.message : jarvisMotivoError(0),
      }]);
    } finally {
      setJarvisConfirmando(false);
    }
  }

  // El toggle habla DESDE el gesto del usuario a propósito: iOS solo desbloquea el
  // audio de speechSynthesis dentro de un toque, y de paso se oye qué voz va a sonar.
  function alternarVozJarvis() {
    const ahora = !jarvisHabla;
    setJarvisHabla(ahora);
    try { localStorage.setItem("la_jarvis_voz", ahora ? "1" : "0"); } catch { /* mejor esfuerzo */ }
    if (ahora) hablarJarvis("Voz activada.");
    else VOZ_SINTESIS?.cancel();
  }

  // Dictado con el reconocimiento del navegador: no cuesta nada y no sale del
  // dispositivo. Rellena el borrador en vez de enviar solo, para poder corregir antes.
  function dictarAJarvis() {
    if (!VOZ_NAVEGADOR) return;
    if (jarvisVozRef.current) {
      jarvisVozRef.current.stop();
      jarvisVozRef.current = null;
      setJarvisEscuchando(false);
      return;
    }
    try {
      const rec = new VOZ_NAVEGADOR();
      rec.lang = "es-ES";
      rec.interimResults = false;
      rec.onresult = e => {
        const dicho = Array.from(e.results).map(r => r[0].transcript).join(" ").trim();
        if (dicho) setJarvisBorrador(prev => (prev ? `${prev} ${dicho}` : dicho));
      };
      rec.onend = () => { jarvisVozRef.current = null; setJarvisEscuchando(false); };
      rec.onerror = () => { jarvisVozRef.current = null; setJarvisEscuchando(false); };
      rec.start();
      jarvisVozRef.current = rec;
      setJarvisEscuchando(true);
    } catch {
      setJarvisEscuchando(false);   // mejor esfuerzo: si el navegador lo niega, se escribe
    }
  }

  // ── Modo llamada ─────────────────────────────────────────────────────────
  // El ciclo: escuchar → detectar que has terminado → enviar → contestar en voz →
  // escuchar otra vez, hasta que cuelgues. Dos cosas lo sostienen y no son opcionales:
  //
  //   1. EL MICRÓFONO SE CIERRA MIENTRAS JARVIS HABLA. Por altavoz se oye a sí mismo, se
  //      transcribe y se contesta solo: una llamada infinita que además cuesta dinero.
  //   2. EL FIN DE FRASE LO DECIDE EL SILENCIO, no el `isFinal` del navegador, que llega
  //      a la primera pausa y trocearía una frase pensada en tres mensajes sueltos.

  function pararEscucha() {
    if (silencioRef.current) { clearTimeout(silencioRef.current); silencioRef.current = null; }
    const rec = recRef.current;
    recRef.current = null;
    try { rec?.stop(); } catch { /* mejor esfuerzo: ya estaba parado */ }
  }

  function colgarLlamada(aviso) {
    llamadaRef.current  = false;
    hablandoRef.current = false;
    buferRef.current    = "";
    vozTurnoRef.current++;          // invalida los callbacks de voz que estén en vuelo
    pararEscucha();
    try { VOZ_SINTESIS?.cancel(); } catch { /* mejor esfuerzo */ }
    setJarvisLlamada(false);
    setJarvisParcial("");
    if (aviso) setJarvisMensajes(prev => [...prev, { rol: "aviso", texto: aviso }]);
  }

  function finDeFrase() {
    const dicho = buferRef.current.trim();
    if (!dicho) return;             // silencio sin nada dicho: se sigue escuchando
    buferRef.current = "";
    setJarvisParcial("");
    if (esFinDeLlamada(dicho)) { colgarLlamada(); return; }
    pararEscucha();
    cicloRef.current.turno?.(dicho);
  }

  function escucharEnLlamada() {
    if (!llamadaRef.current || hablandoRef.current || recRef.current || !VOZ_NAVEGADOR) return;
    let rec;
    try { rec = new VOZ_NAVEGADOR(); }
    catch { colgarLlamada("Este navegador no sabe escuchar."); return; }
    rec.lang           = "es-ES";
    rec.continuous     = true;   // una llamada es seguida, no frase a frase
    rec.interimResults = true;   // para ir enseñando lo que entiende mientras hablas

    rec.onresult = e => {
      reaperturasRef.current = 0;   // se ha oído algo: la cuenta atrás vuelve a empezar
      let parcial = "";
      for (let i = e.resultIndex; i < e.results.length; i++) {
        const trozo = e.results[i][0]?.transcript || "";
        if (e.results[i].isFinal) buferRef.current = `${buferRef.current} ${trozo}`.trim();
        else parcial += trozo;
      }
      setJarvisParcial(`${buferRef.current} ${parcial}`.trim());
      if (silencioRef.current) clearTimeout(silencioRef.current);
      silencioRef.current = setTimeout(() => cicloRef.current.fin?.(), JARVIS_SILENCIO_MS);
    };
    rec.onend = () => {
      // Chrome cierra la sesión él solo cada pocos segundos. Mientras la llamada siga y
      // no estemos hablando, se reabre: sin esto la llamada se queda sorda sin avisar.
      if (recRef.current !== rec) return;
      recRef.current = null;
      if (!llamadaRef.current || hablandoRef.current) return;
      // Cada reapertura sin haber oído nada suma. Cubre dos cosas a la vez: una llamada
      // olvidada abierta con el micro encendido, y un error que se repite (sin red, el
      // reconocimiento falla y termina en bucle) reabriendo cinco veces por segundo.
      reaperturasRef.current += 1;
      if (reaperturasRef.current > REAPERTURAS_MAX) {
        colgarLlamada("He colgado: llevabas un rato sin decir nada.");
        return;
      }
      setTimeout(() => cicloRef.current.escuchar?.(), 200);
    };
    rec.onerror = ev => {
      if (recRef.current === rec) recRef.current = null;
      const motivo = ev?.error || "";
      // Un permiso denegado no se arregla reintentando, y reintentar en bucle es peor que
      // colgar: se dice qué pasa. Lo transitorio (no-speech, network) lo reabre onend.
      if (motivo === "not-allowed" || motivo === "service-not-allowed") {
        colgarLlamada("No tengo permiso para usar el micrófono.");
      } else if (motivo === "audio-capture") {
        colgarLlamada("No encuentro ningún micrófono.");
      }
    };
    try {
      rec.start();
      recRef.current = rec;
      setJarvisFase("escuchando");
    } catch { /* start() sobre uno que ya arrancó: lo reabre onend */ }
  }

  async function turnoDeLlamada(dicho) {
    setJarvisFase("pensando");
    const respuesta = await enviarAJarvis(dicho, { voz: true });
    if (!llamadaRef.current) return;            // han colgado mientras pensaba
    if (!respuesta) { cicloRef.current.escuchar?.(); return; }
    setJarvisFase("hablando");
    hablandoRef.current = true;
    const miTurno = ++vozTurnoRef.current;
    hablarJarvis(respuesta, () => {
      if (vozTurnoRef.current !== miTurno) return;
      hablandoRef.current = false;
      cicloRef.current.escuchar?.();
    });
  }

  function iniciarLlamada() {
    if (!VOZ_NAVEGADOR || !VOZ_SINTESIS || llamadaRef.current) return;
    llamadaRef.current     = true;
    hablandoRef.current    = true;
    buferRef.current       = "";
    reaperturasRef.current = 0;
    setJarvisLlamada(true);
    setJarvisParcial("");
    setJarvisFase("hablando");
    // Se saluda DESDE el toque a propósito: iOS solo desbloquea el audio de
    // speechSynthesis dentro de un gesto del usuario, y si el primer `speak` llegara
    // después del primer fetch la llamada sería muda en el móvil. De paso confirma que
    // el audio va antes de ponerse a hablar solo.
    const miTurno = ++vozTurnoRef.current;
    hablarJarvis("Dime.", () => {
      if (vozTurnoRef.current !== miTurno) return;
      hablandoRef.current = false;
      cicloRef.current.escuchar?.();
    });
  }

  // Los callbacks del reconocimiento y de la síntesis nacen en un render y siguen vivos
  // muchos renders después. Sin esta indirección leerían el `jarvisMensajes` del momento
  // en que empezó la llamada, y Jarvis perdería el hilo de su propia conversación a
  // partir del segundo turno.
  const cicloRef = useRef({});
  useEffect(() => {
    cicloRef.current = {
      escuchar: escucharEnLlamada, turno: turnoDeLlamada, fin: finDeFrase,
    };
  });

  // Salir del dashboard con una llamada abierta dejaría el micro escuchando y la voz
  // sonando sola. Solo toca refs: nada de estado sobre un componente ya desmontado.
  useEffect(() => () => {
    llamadaRef.current = false;
    if (silencioRef.current) clearTimeout(silencioRef.current);
    try { recRef.current?.stop(); } catch { /* mejor esfuerzo */ }
    try { VOZ_SINTESIS?.cancel(); } catch { /* mejor esfuerzo */ }
  }, []);

  // La conversación sobrevive a una recarga, acotada: guardar el hilo entero llenaría
  // la cuota de localStorage con algo que nadie va a releer.
  useEffect(() => {
    try {
      localStorage.setItem("la_jarvis_chat", JSON.stringify(jarvisMensajes.slice(-40)));
    } catch { /* mejor esfuerzo: cuota llena o modo privado */ }
  }, [jarvisMensajes]);

  useEffect(() => {
    jarvisFinRef.current?.scrollIntoView({ block: "nearest" });
  }, [jarvisMensajes, jarvisPensando]);

  // ── Conteo de ropa (widget temporal, persistido en el backend) ───────────
  // Redimensiona la foto elegida a máx. 600px y la convierte a JPEG en base64,
  // para no subir imágenes de varios MB al backend.
  function onClothingPhoto(file) {
    if (!file) return;
    const reader = new FileReader();
    reader.onload = () => {
      const img = new Image();
      img.onload = () => {
        const max = 600;
        let { width, height } = img;
        if (width > max || height > max) {
          const r = Math.min(max / width, max / height);
          width  = Math.round(width  * r);
          height = Math.round(height * r);
        }
        try {
          const canvas = document.createElement("canvas");
          canvas.width = width; canvas.height = height;
          canvas.getContext("2d").drawImage(img, 0, 0, width, height);
          setClothingPhoto(canvas.toDataURL("image/jpeg", 0.7));
        } catch { setClothingPhoto(reader.result); }
      };
      img.onerror = () => setClothingPhoto(reader.result);
      img.src = reader.result;
    };
    reader.readAsDataURL(file);
  }

  // Cierra el formulario de alta y limpia sus campos (guardado con éxito y Cancelar).
  function closeClothingForm() {
    setShowClothingForm(false);
    setClothingError(null);
    setClothingName(""); setClothingPrice(""); setClothingPhoto(null);
  }

  async function addClothing() {
    if (clothingSaving) return;
    const price = parseFloat(String(clothingPrice).replace(",", "."));
    setClothingSaving(true);
    setClothingError(null);
    try {
      const r = await apiFetch(`${API}/clothing`, {
        method: "POST",
        headers: jsonHeaders(),
        body: JSON.stringify({
          name:     clothingName.trim(),
          price:    Number.isFinite(price) ? price : 0,
          currency: clothingCurrency,
          photo:    clothingPhoto,
        }),
      });
      let data = {};
      try { data = await r.json(); } catch { /* respuesta sin cuerpo JSON */ }
      if (r.ok && data.ok && data.item) {
        setClothing(prev => [data.item, ...prev]);
        closeClothingForm();
      } else {
        // Mostrar el fallo: el código de estado dice qué pasó (404 = backend sin
        // desplegar los endpoints, 502 = problema con la tabla, 401/403 = sesión).
        setClothingError(`No se pudo guardar (error ${r.status})${data.detail ? `: ${data.detail}` : ""}`);
      }
    } catch {
      setClothingError("No se pudo conectar con el servidor.");
    }
    finally { setClothingSaving(false); }
  }

  async function deleteClothing(id) {
    try {
      const r = await apiFetch(`${API}/clothing/${id}`, { method: "DELETE", headers: authHeaders() });
      if (r.ok) setClothing(prev => prev.filter(c => c.id !== id));
    } catch { /* mejor esfuerzo: ignorar */ }
  }

  // ── Estado del sistema ───────────────────────────────────────────────────
  // Las señales de si algo va mal ya existían, pero repartidas: si el backend
  // responde, si la sesión de Outlook sigue viva, cuándo sincronizó el Watch, si el
  // agente contesta. Juntarlas evita tener que abrir logs para saber qué se ha caído.
  // Se refresca al abrir ajustes y con el botón, nunca en bucle.
  async function cargarEstadoSistema() {
    if (sysLoading) return;
    setSysLoading(true);
    const t0 = (typeof performance !== "undefined" ? performance : Date).now();

    // El backend escala a cero: la primera petición tras un rato mide el arranque en frío.
    let backend = { ok: false, ms: null };
    try {
      const r = await fetch(`${API}/`);
      backend = { ok: r.ok, ms: Math.round(((typeof performance !== "undefined" ? performance : Date).now()) - t0) };
    } catch { /* sin red o backend caído: ok=false */ }

    // Independientes entre sí: en serie sumarían dos idas y vueltas a Fly detrás del
    // arranque en frío que acabamos de medir.
    let agente = null;
    let registro = null;
    let presencia = null;
    let avisos = null;
    if (backend.ok) {
      const [rAgente, rLogs, rPresencia, rBrief, rAvisos] = await Promise.all([
        apiFetch(`${API}/agents/${AGENT_ID}`, { headers: authHeaders() }).catch(() => null),
        apiFetch(`${API}/logs?dias=7&limite=50`, { headers: authHeaders() }).catch(() => null),
        apiFetch(`${API}/presencia`, { headers: authHeaders() }).catch(() => null),
        apiFetch(`${API}/brief/ajustes`, { headers: authHeaders() }).catch(() => null),
        apiFetch(`${API}/avisos/estado`, { headers: authHeaders() }).catch(() => null),
      ]);
      try {
        if (rAgente?.ok) agente = await rAgente.json();
      } catch { /* mejor esfuerzo: se muestra como desconocido */ }
      try {
        if (rLogs?.ok) registro = await rLogs.json();
      } catch { /* mejor esfuerzo: se muestra como desconocido */ }
      try {
        if (rPresencia?.ok) presencia = await rPresencia.json();
      } catch { /* mejor esfuerzo: se muestra como desconocido */ }
      try {
        if (rBrief?.ok) setBriefCfg(await rBrief.json());
      } catch { /* mejor esfuerzo: el interruptor se muestra como desconocido */ }
      try {
        if (rAvisos?.ok) avisos = await rAvisos.json();
      } catch { /* mejor esfuerzo: se muestra como desconocido */ }
    }

    setSysStatus({ backend, agente, registro, presencia, avisos, comprobado: Date.now() });
    setSysLoading(false);
  }

  // Enciende, apaga o pausa el resumen diario. La respuesta del PATCH ya trae el estado
  // completo (incluida la pausa vencida, que el backend reporta como si no existiera),
  // así que se pinta lo que diga el backend y no lo que creamos haber puesto.
  async function guardarBriefAjustes(cambios) {
    if (briefGuardando) return;
    setBriefGuardando(true);
    try {
      const r = await apiFetch(`${API}/brief/ajustes`, {
        method: "PATCH", headers: jsonHeaders(), body: JSON.stringify(cambios),
      });
      if (r.ok) setBriefCfg(await r.json());
    } catch { /* mejor esfuerzo: ignorar */ }
    setBriefGuardando(false);
  }

  // Fecha del cambio de dispositivo de salud. Se guarda en el servidor y no en
  // localStorage porque el corte lo necesitan también las líneas base que calcula el
  // backend para el resumen de la mañana, no solo este navegador.
  async function guardarCambioDispositivo(cambios) {
    if (dispositivoGuardando) return;
    setDispositivoGuardando(true);
    try {
      const r = await apiFetch(`${API}/health/ajustes`, {
        method: "PATCH", headers: jsonHeaders(), body: JSON.stringify(cambios),
      });
      if (r.ok) {
        const d = await r.json();
        setHealthAjustes({ cambio_dispositivo: d.cambio_dispositivo, dispositivo: d.dispositivo });
      }
    } catch { /* mejor esfuerzo: ignorar */ }
    setDispositivoGuardando(false);
  }

  // Manda un aviso de prueba por el canal que toque. Lo que se comprueba no es el
  // backend —eso ya lo dice la fila de estado— sino la cadena entera: que HA lo recoja
  // y que el móvil lo enseñe.
  async function probarAviso() {
    setAvisoPrueba("…");
    try {
      const r = await apiFetch(`${API}/avisos/probar`, { method: "POST", headers: authHeaders() });
      const d = await r.json();
      // "Enviado" sería mentira en el caso del móvil: lo único que sabe el backend es
      // que lo ha encolado y que HA está pasando a recoger. Si la automatización de HA
      // falla —el `notify` mal escrito, por ejemplo— el aviso se pierde ahí y aquí no
      // se puede saber. Decirlo es la diferencia entre buscar el fallo en el sitio
      // correcto y darlo por enviado, que es el error de siempre de este proyecto.
      setAvisoPrueba(d.canal === "movil"
        ? "encolado — HA lo recoge en ≤30 s. Si no suena nada, el fallo está en su "
          + "automatización o en el nombre del notify"
        : "enviado por correo (nadie recoge los avisos del móvil)");
    } catch {
      setAvisoPrueba("no se pudo enviar");
    }
  }

  async function vaciarRegistro() {
    try {
      await apiFetch(`${API}/logs`, { method: "DELETE", headers: authHeaders() });
      setSysStatus(s => (s ? { ...s, registro: { entradas: [], errores: 0 } } : s));
    } catch { /* mejor esfuerzo: ignorar */ }
  }

  // La cartera de Indexa. El backend la guarda en memoria unas horas (Indexa valora una
  // vez al día), así que la carga normal no sale a la red; `refrescar` es lo que la
  // obliga a preguntar de verdad, y por eso es un botón y no algo automático.
  async function loadFinanzas({ refrescar = false } = {}) {
    setFinanzasCargando(true);
    try {
      const r = await apiFetch(`${API}/finanzas/resumen${refrescar ? "?refrescar=true" : ""}`,
                               { headers: authHeaders() });
      // Un 502 (Indexa caído) trae `{detail}` y no `{configurado}`: sin mirar el estado,
      // ese cuerpo se pintaba como "no está conectado", que manda a mirar el .env cuando
      // el token está perfectamente puesto.
      if (!r.ok) throw new Error("finanzas");
      setFinanzas(await r.json());
    } catch {
      // Si ya había datos en pantalla se quedan: son de hace unas horas y siguen siendo
      // ciertos. Solo cuando no hay nada que enseñar se dice que falló.
      setFinanzas(previo => previo || { error: true });
    }
    setFinanzasCargando(false);
  }

  // La cartera manual de ETFs (Revolut). Igual que Indexa: el precio actual se cachea
  // unas horas en el backend, `refrescar` es lo que fuerza a preguntar de verdad.
  async function loadCarteraEtf({ refrescar = false } = {}) {
    setCarteraEtfCargando(true);
    try {
      const r = await apiFetch(`${API}/finanzas/etfs${refrescar ? "?refrescar=true" : ""}`,
                               { headers: authHeaders() });
      if (!r.ok) throw new Error("cartera-etf");
      setCarteraEtf(await r.json());
    } catch {
      setCarteraEtf(previo => previo || { error: true });
    }
    setCarteraEtfCargando(false);
  }

  async function submitEtfAportacion(ticker) {
    const form = etfAportForm[ticker];
    if (!form || form.guardando) return;
    setEtfAportForm(f => ({ ...f, [ticker]: { ...f[ticker], guardando: true } }));
    try {
      const r = await apiFetch(`${API}/finanzas/etfs/${ticker}/aportaciones`, {
        method: "POST",
        headers: jsonHeaders(),
        body: JSON.stringify({ fecha: form.fecha, importe_eur: parseFloat(form.importe), hora: form.hora || null }),
      });
      if (!r.ok) throw new Error("aportacion");
      setEtfAportForm(f => ({ ...f, [ticker]: { abierto: false, fecha: "", importe: "", hora: "", guardando: false } }));
      await loadCarteraEtf();
    } catch {
      setEtfAportForm(f => ({ ...f, [ticker]: { ...f[ticker], guardando: false, error: true } }));
    }
  }

  async function loadTraining() {
    try {
      const r = await apiFetch(`${API}/training/summary`, { headers: authHeaders() });
      const data = await r.json();
      setTraining(data);
    } catch { /* mejor esfuerzo: ignorar */ }
  }

  async function submitSession() {
    if (trainingLoading) return;
    setTrainingLoading(true);
    try {
      await apiFetch(`${API}/training/sessions`, {
        method: "POST",
        headers: jsonHeaders(),
        body: JSON.stringify({ date: sessionDate, duration_hours: parseFloat(sessionHours) }),
      });
      setShowSessionForm(false);
      await loadTraining();
    } catch { /* mejor esfuerzo: ignorar */ }
    setTrainingLoading(false);
  }

  async function deleteTrainingSession(sessionId) {
    await apiFetch(`${API}/training/sessions/${sessionId}`, { method: "DELETE", headers: authHeaders() });
    await loadTraining();
  }

  async function updateTrainingClient(patch) {
    if (trainingSettingsSaving) return;
    setTrainingSettingsSaving(true);
    try {
      await apiFetch(`${API}/training/client`, {
        method: "PATCH",
        headers: jsonHeaders(),
        body: JSON.stringify(patch),
      });
      await loadTraining();
    } catch { /* mejor esfuerzo: ignorar */ }
    setTrainingSettingsSaving(false);
  }

  async function submitPayment() {
    if (trainingLoading) return;
    setTrainingLoading(true);
    const today = new Date().toISOString().slice(0, 10);
    try {
      await apiFetch(`${API}/training/payments`, {
        method: "POST",
        headers: jsonHeaders(),
        body: JSON.stringify({ date: today }),
      });
      await loadTraining();
    } catch { /* mejor esfuerzo: ignorar */ }
    setTrainingLoading(false);
  }

  function saveWidgetConfig(cfg) {
    setWidgetConfig(cfg);
    localStorage.setItem("la_widget_config", JSON.stringify(cfg));
  }
  function saveSimpleWidgetConfig(cfg) {
    setSimpleWidgetConfig(cfg);
    localStorage.setItem("la_simple_widget_config", JSON.stringify(cfg));
  }
  // Los ajustes de widgets (activar/desactivar y reordenar) actúan sobre la
  // config del modo activo: en simplificado se edita la selección simple.
  function activeWidgetCtx() {
    return simpleMode
      ? { cfg: simpleWidgetConfig, save: saveSimpleWidgetConfig }
      : { cfg: widgetConfig,       save: saveWidgetConfig };
  }
  function toggleWidget(id) {
    const { cfg, save } = activeWidgetCtx();
    save(cfg.map(w => w.id === id ? { ...w, visible: !w.visible } : w));
  }
  function moveWidget(id, dir) {
    const { cfg, save } = activeWidgetCtx();
    const idx = cfg.findIndex(w => w.id === id);
    if (idx + dir < 0 || idx + dir >= cfg.length) return;
    const next = [...cfg];
    [next[idx], next[idx + dir]] = [next[idx + dir], next[idx]];
    save(next);
  }
  function resetWidgetSize(id) {
    // widthPct también, o el doble clic no devolvía el ancho a su valor por defecto.
    saveWidgetConfig(widgetConfig.map(w => w.id === id
      ? { ...w, width: undefined, height: undefined, widthPct: undefined }
      : w));
  }

  function handleDividerDrag(e, idx) {
    e.preventDefault();
    const containerEl = document.getElementById("widget-grid-container");
    if (!containerEl) return;
    const startX    = e.clientX;
    const containerW = containerEl.offsetWidth;
    const startSplit = colSplitsRef.current[idx];
    const minVal = idx > 0 ? colSplitsRef.current[idx - 1] + 0.08 : 0.08;
    const maxVal = idx < colSplitsRef.current.length - 1 ? colSplitsRef.current[idx + 1] - 0.08 : 0.92;
    document.body.classList.add("resizing");

    function onMouseMove(me) {
      const delta = (me.clientX - startX) / containerW;
      const newVal = Math.max(minVal, Math.min(maxVal, startSplit + delta));
      const updated = [...colSplitsRef.current];
      updated[idx] = newVal;
      colSplitsRef.current = updated;
      setColSplits([...updated]);
    }
    function onMouseUp() {
      document.body.classList.remove("resizing");
      localStorage.setItem("la_col_splits", JSON.stringify(colSplitsRef.current));
      window.removeEventListener("mousemove", onMouseMove);
      window.removeEventListener("mouseup", onMouseUp);
    }
    window.addEventListener("mousemove", onMouseMove);
    window.addEventListener("mouseup", onMouseUp);
  }

  function getColumnAtX(clientX, rect) {
    const splits = colSplitsRef.current;
    const cols   = ACTIVE_COLUMNS[numColumnsRef.current];
    const relX   = (clientX - rect.left) / rect.width;
    for (let i = 0; i < splits.length; i++) {
      if (relX < splits[i]) return cols[i];
    }
    return cols[cols.length - 1];
  }

  function changeNumColumns(n) {
    const newSplits = DEFAULT_SPLITS[n] || [0.65];
    let newConfig;
    if (n > numColumnsRef.current) {
      // 2→3: widgets en "right" pasan a "center"; "right" queda vacía
      newConfig = widgetConfig.map(w => {
        const col = w.column || DEFAULT_COLUMNS[w.id] || "left";
        return col === "right" ? { ...w, column: "center" } : w;
      });
    } else {
      // 3→2: "center" y "right" pasan a "right"
      newConfig = widgetConfig.map(w => {
        const col = w.column || DEFAULT_COLUMNS[w.id] || "left";
        return (col === "center" || col === "right") ? { ...w, column: "right" } : w;
      });
    }
    setNumColumns(n);
    numColumnsRef.current = n;
    setColSplits(newSplits);
    colSplitsRef.current = newSplits;
    saveWidgetConfig(newConfig);
    localStorage.setItem("la_num_columns", String(n));
    localStorage.setItem("la_col_splits", JSON.stringify(newSplits));
  }

  function handleResizeMouseDown(e, widgetId) {
    e.preventDefault();
    e.stopPropagation();
    const wrapEl = document.getElementById(`widget-wrap-${widgetId}`);
    if (!wrapEl) return;
    const startW = wrapEl.offsetWidth;
    const startH = wrapEl.offsetHeight;
    resizeDragRef.current = { widgetId, startX: e.clientX, startY: e.clientY, startW, startH };
    document.body.classList.add("resizing");

    const SNAP_PX = 10;
    const GUIDE_COLOR = "var(--accent2)";

    function computeSnap(wid, rawW, rawH) {
      const el = document.getElementById(`widget-wrap-${wid}`);
      if (!el) return { w: rawW, h: rawH, guides: [] };
      const elRect = el.getBoundingClientRect();
      const pRight  = elRect.left + rawW;
      const pBottom = elRect.top  + rawH;
      let snapW = rawW, snapH = rawH;
      const guides = [];

      const others = Array.from(document.querySelectorAll(".widget-wrap[data-widget-id]"))
        .filter(o => o.dataset.widgetId !== wid);

      for (const other of others) {
        const r = other.getBoundingClientRect();
        // Snap borde derecho a borde izquierdo/derecho del otro
        if (Math.abs(pRight - r.left) < SNAP_PX) {
          snapW = r.left - elRect.left;
          guides.push({ type: "v", x: r.left, y1: Math.min(elRect.top, r.top), y2: Math.max(elRect.top + rawH, r.bottom) });
        } else if (Math.abs(pRight - r.right) < SNAP_PX) {
          snapW = r.right - elRect.left;
          guides.push({ type: "v", x: r.right, y1: Math.min(elRect.top, r.top), y2: Math.max(elRect.top + rawH, r.bottom) });
        }
        // Snap borde inferior a borde superior/inferior del otro
        if (Math.abs(pBottom - r.top) < SNAP_PX) {
          snapH = r.top - elRect.top;
          guides.push({ type: "h", y: r.top, x1: Math.min(elRect.left, r.left), x2: Math.max(pRight, r.right) });
        } else if (Math.abs(pBottom - r.bottom) < SNAP_PX) {
          snapH = r.bottom - elRect.top;
          guides.push({ type: "h", y: r.bottom, x1: Math.min(elRect.left, r.left), x2: Math.max(pRight, r.right) });
        }
      }
      return { w: Math.max(120, snapW), h: Math.max(60, snapH), guides };
    }

    function renderGuides(guides) {
      const c = document.getElementById("snap-guides");
      if (!c) return;
      while (c.firstChild) c.removeChild(c.firstChild);
      for (const g of guides) {
        const d = document.createElement("div");
        d.style.cssText = g.type === "v"
          ? `position:fixed;left:${g.x - 0.5}px;top:${g.y1}px;width:1px;height:${g.y2 - g.y1}px;background:${GUIDE_COLOR};opacity:.9;pointer-events:none;z-index:802;box-shadow:0 0 4px ${GUIDE_COLOR};`
          : `position:fixed;left:${g.x1}px;top:${g.y - 0.5}px;width:${g.x2 - g.x1}px;height:1px;background:${GUIDE_COLOR};opacity:.9;pointer-events:none;z-index:802;box-shadow:0 0 4px ${GUIDE_COLOR};`;
        c.appendChild(d);
      }
    }

    function clearGuides() {
      const c = document.getElementById("snap-guides");
      if (c) while (c.firstChild) c.removeChild(c.firstChild);
    }

    function onMouseMove(me) {
      if (!resizeDragRef.current) return;
      const { startX, startY, startW: sw, startH: sh, widgetId: wid } = resizeDragRef.current;
      const rawW = Math.max(120, sw + me.clientX - startX);
      const rawH = Math.max(60,  sh + me.clientY - startY);
      const { w, h, guides } = computeSnap(wid, rawW, rawH);
      const el = document.getElementById(`widget-wrap-${wid}`);
      if (el) { el.style.width = `${w}px`; el.style.height = `${h}px`; }
      renderGuides(guides);
    }

    function onMouseUp(me) {
      if (!resizeDragRef.current) return;
      const { widgetId: wid, startX, startY, startW: sw, startH: sh } = resizeDragRef.current;
      const rawW = Math.max(120, sw + me.clientX - startX);
      const rawH = Math.max(60,  sh + me.clientY - startY);
      const { w, h } = computeSnap(wid, rawW, rawH);
      resizeDragRef.current = null;
      document.body.classList.remove("resizing");
      clearGuides();
      const el = document.getElementById(`widget-wrap-${wid}`);
      const colW = el?.parentElement?.offsetWidth || w;
      const widthPct = Math.round((w / colW) * 1000) / 1000;
      saveWidgetConfig(widgetConfig.map(c => c.id === wid ? { ...c, widthPct, width: undefined, height: h } : c));
      window.removeEventListener("mousemove", onMouseMove);
      window.removeEventListener("mouseup", onMouseUp);
    }

    window.addEventListener("mousemove", onMouseMove);
    window.addEventListener("mouseup", onMouseUp);
  }

  function handleDragHandleMouseDown(e, widgetId) {
    e.preventDefault();
    e.stopPropagation();
    const cfg = widgetConfig.find(c => c.id === widgetId) || {};
    dragStateRef.current = {
      id: widgetId,
      targetColumn: cfg.column || DEFAULT_COLUMNS[widgetId] || "left",
      targetBefore: null,
    };
    setDraggingId(widgetId);
    setDragPos({ x: e.clientX, y: e.clientY });
    document.body.classList.add("dragging-widget");

    function onMouseMove(me) {
      setDragPos({ x: me.clientX, y: me.clientY });
      const containerEl = document.getElementById("widget-grid-container");
      if (!containerEl) return;
      const rect = containerEl.getBoundingClientRect();
      const targetCol = getColumnAtX(me.clientX, rect);

      let targetBefore = null;
      const colWidgets = Array.from(document.querySelectorAll(`.widget-wrap[data-column="${targetCol}"]`));
      for (const el of colWidgets) {
        if (el.dataset.widgetId === dragStateRef.current?.id) continue;
        const r = el.getBoundingClientRect();
        if (me.clientY < r.top + r.height / 2) { targetBefore = el.dataset.widgetId; break; }
      }

      if (dragStateRef.current) {
        dragStateRef.current.targetColumn = targetCol;
        dragStateRef.current.targetBefore = targetBefore;
      }
      setDragOverId(targetCol);
      setDragOverSide(targetBefore || "__end__");
    }

    function onMouseUp() {
      const ds = dragStateRef.current;
      if (!ds) return;
      dragStateRef.current = null;
      document.body.classList.remove("dragging-widget");
      const { id, targetColumn, targetBefore } = ds;
      const moved = { ...widgetConfig.find(w => w.id === id), column: targetColumn };
      const without = widgetConfig.filter(w => w.id !== id);
      if (targetBefore && targetBefore !== "__end__") {
        const idx = without.findIndex(w => w.id === targetBefore);
        if (idx >= 0) without.splice(idx, 0, moved);
        else without.push(moved);
      } else {
        const lastInCol = without.reduce((last, w, i) =>
          (w.column || DEFAULT_COLUMNS[w.id] || "left") === targetColumn ? i : last, -1);
        without.splice(lastInCol + 1, 0, moved);
      }
      saveWidgetConfig(without);
      setDraggingId(null); setDragPos(null); setDragOverId(null); setDragOverSide(null);
      window.removeEventListener("mousemove", onMouseMove);
      window.removeEventListener("mouseup", onMouseUp);
    }

    window.addEventListener("mousemove", onMouseMove);
    window.addEventListener("mouseup", onMouseUp);
  }

  // Seguimiento del job. El sondeo es solo de lectura: el job ya vive en Supabase y el
  // agente lo recoge consultándola por su cuenta, así que esto no lo empuja ni lo frena
  // — cerrar el modal no cancela nada. Pero sí alimenta `jobTerminal`, de donde cuelga
  // la notificación de "job completado", así que sigue en marcha con el modal cerrado
  // (más despacio) en vez de cortarse ahí. Antes no paraba nunca, ni siquiera al acabar.
  useEffect(() => {
    if (!activeJobId || !token || jobTerminal) return;   // terminal: ya no hay nada que mirar
    // El cronómetro se reinicia por job, no al abrir o cerrar el modal.
    if (jobInicioRef.current.id !== activeJobId) {
      jobInicioRef.current = { id: activeJobId, t: Date.now() };
    }
    let mounted = true;
    const id = setInterval(async () => {
      if (Date.now() - jobInicioRef.current.t > JOB_POLL_MAX_MS) {
        if (mounted) setActiveJobId(null);   // el agente ya no lo va a recoger
        return;
      }
      try {
        const [evRes, jobRes] = await Promise.all([
          apiFetch(`${API}/jobs/${activeJobId}/events`, { headers: authHeaders() }),
          apiFetch(`${API}/jobs/by-id/${activeJobId}`, { headers: authHeaders() }),
        ]);
        const evData = await evRes.json();
        const jobData = await jobRes.json();
        if (!mounted) return;
        setJobEvents(evData?.events || []);
        const st = jobData?.job?.status;
        if (st) setJobStatus(st);
        if (st === "done" || st === "failed") {
          setJobTerminal({ status: st, reason: jobData?.job?.error_reason || "" });
        }
      } catch { /* mejor esfuerzo: ignorar */ }
    }, jobModalAbierto ? JOB_POLL_ACTIVO_MS : JOB_POLL_FONDO_MS);
    return () => { mounted = false; clearInterval(id); };
  }, [activeJobId, token, jobTerminal, jobModalAbierto]);

  const maxStage = jobEvents.reduce((max, ev) => Math.max(max, STAGE_INDEX.get(ev.stage) ?? -1), -1);
  const progressPct = maxStage < 0 ? 0 : Math.round(((maxStage + 1) / STAGES.length) * 100);
  // IP de la VPN para meterla en Moonlight cuando no estás en casa.
  const ipMoonlight = hostStreaming(jobEvents);

  // Derivados
  const todayEvents = allEvents
    .filter(e => isToday(e.start))
    .map(e => ({ ...e, time: formatTime(e.start), title: e.title || "(Sin título)", loc: e.location || "", past: isPast(e.end), active: isActive(e.start, e.end) }));

  const upcomingEvents = allEvents
    .filter(e => !isToday(e.start) && isFuture(e.start) && daysUntil(e.start) <= 7)
    .slice(0, 5)
    .map(e => ({ ...e, time: formatUpcomingTime(e.start), title: e.title || "(Sin título)", loc: e.location || "" }));

  const entregas = [...allEvents, ...classEvents]
    .filter(e => e.title && e.title.includes(ENTREGAS_MARKER) && (isFuture(e.start) || isToday(e.start)))
    .map(e => ({ title: e.title.replace(ENTREGAS_MARKER, "").trim(), subject: e.title, days: daysUntil(e.start), alud_url: e.alud_url || null }))
    .sort((a, b) => a.days - b.days);

  const displayActive = activeEvent || todayEvents.find(e => e.active) || todayEvents[0];
  const todayClasses  = classEvents.filter(e => isToday(e.start));

  // Timeline combinado: eventos normales + nodo de clases, ordenado por hora
  const classesNodeTime = todayClasses.length > 0
    ? todayClasses.reduce((min, e) => e.start < min ? e.start : min, todayClasses[0].start)
    : null;
  const timelineNodes = [
    ...todayEvents.map(ev => ({ type: "event", ev })),
    ...(todayClasses.length > 0 ? [{ type: "classes", start: classesNodeTime }] : []),
  ].sort((a, b) => {
    const ta = a.type === "event" ? a.ev.start : a.start;
    const tb = b.type === "event" ? b.ev.start : b.start;
    return new Date(ta) - new Date(tb);
  });

  const hh      = String(now.getHours()).padStart(2, "0");
  const mm      = String(now.getMinutes()).padStart(2, "0");
  const dateStr = `${DAYS_ES[now.getDay()]}, ${now.getDate()} de ${MONTHS_ES[now.getMonth()]} de ${now.getFullYear()}`;
  const hour    = now.getHours();
  const greeting = hour < 13 ? "Buenos días" : hour < 20 ? "Buenas tardes" : "Buenas noches";

  const isAgentOnline = agentState?.status === "online" && !agentState?.offline;

  // Lo que necesita DepartureWidget, que ahora vive fuera del componente (ver M1).
  const propsSalida = {
    departureMap, departureLoadingId, departurePickingId,
    setDeparturePickingId, setDepartureMap, fetchDeparture,
  };

  // El motor de conclusiones recorre todas las series y cruza varias entre sí. Lo
  // llamaban por separado el widget compacto y el modal, así que se ejecutaba dos
  // veces por render; ahora una vez por cambio de datos y compartido.
  // El día de hoy, estable dentro de la jornada. Las ventanas de las conclusiones van
  // por fecha real, así que el tic del reloj (dos veces por minuto) no debe rehacerlas
  // pero pasar la medianoche sí. A mediodía para que el cambio de hora no lo mueva.
  const diaActual = `${now.getFullYear()}-${now.getMonth()}-${now.getDate()}`;
  const hoyConclusiones = useMemo(() => {
    const [a, m, d] = diaActual.split("-").map(Number);
    return new Date(a, m, d, 12);
  }, [diaActual]);
  const conclusionesSalud = useMemo(
    () => healthConclusions(healthData, hoyConclusiones, { reloj: healthReloj }),
    [healthData, healthReloj, hoyConclusiones],
  );
  // Estado del reloj HOY. Se usa solo como matiz de la puntuación diaria: a media
  // mañana "sin señal todavía" es de lo más normal y no es una conclusión de nada.
  const relojHoy = useMemo(() => {
    const mapa = healthReloj?.dias;
    if (!mapa) return null;
    const p = n => String(n).padStart(2, "0");
    const iso = `${hoyConclusiones.getFullYear()}-${p(hoyConclusiones.getMonth() + 1)}-${p(hoyConclusiones.getDate())}`;
    const estado = mapa[iso] || "sin_datos";
    return { estado, puesto: relojPuesto(estado) };
  }, [healthReloj, hoyConclusiones]);
  const veredictoSalud    = useMemo(() => healthOverall(conclusionesSalud), [conclusionesSalud]);
  // Patrones sobre el histórico largo: mismas fórmulas que las conclusiones, pero
  // exigiendo mucha más muestra por grupo (ver HEALTH_MIN_MUESTRA_PATRONES).
  const patronesLargos = useMemo(
    () => (healthLargo ? healthCorrelations(healthLargo, { minPorGrupo: HEALTH_MIN_MUESTRA_PATRONES }) : []),
    [healthLargo],
  );
  const diasPatrones = useMemo(() => healthCoverageDays(healthLargo), [healthLargo]);

  // Histórico de la puntuación diaria de bienestar, reconstruido de las mismas series
  // (no se guarda nada aparte). Recorre ~30 días con sus quince métricas, así que va
  // memoizado como el resto: solo cambia cuando llega una sincronización nueva.
  const historicoBienestar = useMemo(
    () => wellnessHistory(healthData, { reloj: healthReloj, corte: corteDispositivo }),
    [healthData, healthReloj, corteDispositivo],
  );
  // Componentes que llevan dos semanas sin traer nada: no es un hueco, es que este
  // aparato no los mide. Se sacan del desglose en vez de dejarlos en gris pidiendo
  // cada día un dato que ya no va a llegar.
  const componentesNoMedidos = useMemo(
    () => metricasMuertas(healthData, { corte: corteDispositivo }),
    [healthData, corteDispositivo],
  );
  const tendenciaBienestar = useMemo(
    () => historicoBienestar.length >= 7 ? seriesTrend(historicoBienestar, 7, 30) : null,
    [historicoBienestar],
  );

  // ── Derivación de las métricas de salud (M2) ───────────────────────────
  // Esto son ~17 findMetric, decenas de slice y todas las medias. Antes se rehacía
  // entero en CADA render del Dashboard — o sea dos veces por minuto solo por el tic
  // del reloj — sobre datos que únicamente cambian cuando llega la sincronización.
  // `diaActual` (definido arriba, con las conclusiones) está en las dependencias para
  // que lo que depende del día de hoy (daysSinceWorkout, la semana desde el lunes) se
  // recalcule al pasar la medianoche.
  const datosSalud = useMemo(() => {
          // ── datos base ──
          const wSleepRaw     = findMetric(healthData, "sleep_analysis", "sleep").filter(d => !d.extra?.excluded).map(d => ({ ...d, value: sleepHours(d) }));
          const wStepsRaw     = findMetric(healthData, "step_count", "steps");
          const wHrvRaw       = findMetric(healthData, "heart_rate_variability", "heartRateVariability");
          const wRhrRaw       = findMetric(healthData, "resting_heart_rate");
          const wAeRaw        = findMetric(healthData, "active_energy");
          const wWorkRaw      = findMetric(healthData, "workouts");
          const wExerciseRaw  = findMetric(healthData, "apple_exercise_time", "exercise_time");
          const wStandRaw     = findMetric(healthData, "apple_stand_hour", "stand_hour");
          const wCardioRecRaw = findMetric(healthData, "cardio_recovery");
          const wVo2Raw       = findMetric(healthData, "vo2_max", "cardioFitness");
          const wWalkHrRaw    = findMetric(healthData, "walking_heart_rate_average");
          const wDaylightRaw  = findMetric(healthData, "time_in_daylight");
          const wRespRaw      = findMetric(healthData, "respiratory_rate");
          const wWeightRaw    = findMetric(healthData, "weight_body_mass", "weight");
          const wBodyFatRaw   = findMetric(healthData, "body_fat_percentage");
          const wLeanMassRaw  = findMetric(healthData, "lean_body_mass");
          const wFlightsRaw   = findMetric(healthData, "flights_climbed");

          const avg7 = arr => arr.length ? arr.reduce((s,d)=>s+(d.value||0),0)/arr.length : null;
          const last7Sleep    = wSleepRaw.slice(-7);
          const last7Steps    = wStepsRaw.slice(-7);
          const last7Hrv      = wHrvRaw.slice(-7);
          const last7Rhr      = wRhrRaw.slice(-7);
          const last7Ae       = wAeRaw.slice(-7);
          const last7Exercise = wExerciseRaw.slice(-7);
          const last7Stand    = wStandRaw.slice(-7);
          const last7WalkHr   = wWalkHrRaw.slice(-7);
          const last7Daylight = wDaylightRaw.slice(-7);
          const last7Resp     = wRespRaw.slice(-7);
          const last7Flights  = wFlightsRaw.slice(-7);

          // Semana actual desde el lunes
          const todayMidnight = new Date(); todayMidnight.setHours(0,0,0,0);
          const todayStr = `${todayMidnight.getFullYear()}-${String(todayMidnight.getMonth()+1).padStart(2,'0')}-${String(todayMidnight.getDate()).padStart(2,'0')}`;
          const dayOfWeek = todayMidnight.getDay(); // 0=dom, 1=lun, ..., 6=sab
          const daysToMonday = dayOfWeek === 0 ? 6 : dayOfWeek - 1;
          const weekStart = new Date(todayMidnight); weekStart.setDate(todayMidnight.getDate() - daysToMonday);
          const thisWeekWork = wWorkRaw.filter(d => new Date(d.date + "T00:00:00") >= weekStart);
          const weekWorkoutCount = thisWeekWork.reduce((sum, d) => sum + (d.extra?.workouts?.length || 0), 0);

          // Días de entrenamiento planificados (configurables)
          const trainingDaysSet = new Set(trainingDays);
          let expectedByNow = 0;
          for (let i = 0; i <= daysToMonday; i++) {
            if (trainingDaysSet.has((1 + i) % 7)) expectedByNow++;
          }

          // ── promedios semanales ──
          const avgSleep    = avg7(last7Sleep);
          const avgSteps    = avg7(last7Steps);
          const avgHrv      = avg7(last7Hrv);
          const prevHrv     = wHrvRaw.slice(-14,-7);
          const avgHrvPrev  = avg7(prevHrv);
          const avgRhr      = avg7(last7Rhr);
          const avgAe       = avg7(last7Ae);
          const avgExercise = avg7(last7Exercise);
          const avgStand    = avg7(last7Stand);
          const avgWalkHr   = avg7(last7WalkHr);
          const avgDaylight = avg7(last7Daylight);
          const avgResp     = avg7(last7Resp);
          const avgFlights  = avg7(last7Flights);
          const allWorkoutDates  = wWorkRaw.flatMap(d => (d.extra?.workouts||[]).map(w => (w.start||"").slice(0,10))).filter(Boolean).sort();
          const lastWorkoutDate  = allWorkoutDates[allWorkoutDates.length - 1];
          const daysSinceWorkout = lastWorkoutDate ? Math.floor((new Date() - new Date(lastWorkoutDate + "T12:00:00")) / 86400000) : null;
          // VO2 max y cardio recovery: último valor disponible (actualizan infrecuente)
          const lastVo2      = wVo2Raw.length ? wVo2Raw[wVo2Raw.length - 1].value : null;
          const thisWeekRecov = wCardioRecRaw.filter(d => new Date(d.date + "T00:00:00") >= weekStart);
          const avgCardioRec = thisWeekRecov.length ? avg7(thisWeekRecov) : (wCardioRecRaw.length ? wCardioRecRaw[wCardioRecRaw.length - 1].value : null);

          // ── valores diarios ──
          const latestOrToday = (arr) => arr.find(d => d.date === todayStr) || arr[arr.length - 1];
          const todaySleepEntry   = wSleepRaw[wSleepRaw.length - 1];
          const todaySleep        = todaySleepEntry?.value > 0 ? todaySleepEntry.value : null;
          const todaySteps        = latestOrToday(wStepsRaw)?.value > 0 ? latestOrToday(wStepsRaw).value : null;
          const todayHrv          = latestOrToday(wHrvRaw)?.value > 0 ? latestOrToday(wHrvRaw).value : null;
          const todayRhr          = latestOrToday(wRhrRaw)?.value > 0 ? latestOrToday(wRhrRaw).value : null;
          const todayAe           = latestOrToday(wAeRaw)?.value > 0 ? latestOrToday(wAeRaw).value : null;
          const todayWorkEntry    = wWorkRaw.find(d => d.date === todayStr);
          const todayWorkoutCount = todayWorkEntry?.extra?.workouts?.length || 0;
          const todayExercise     = latestOrToday(wExerciseRaw)?.value > 0 ? latestOrToday(wExerciseRaw).value : null;
          const todayStand        = latestOrToday(wStandRaw)?.value > 0 ? latestOrToday(wStandRaw).value : null;
          const todayFlights      = latestOrToday(wFlightsRaw)?.value > 0 ? latestOrToday(wFlightsRaw).value : null;
          const todayWalkHr       = latestOrToday(wWalkHrRaw)?.value > 0 ? latestOrToday(wWalkHrRaw).value : null;
          const todayDaylight     = latestOrToday(wDaylightRaw)?.value > 0 ? latestOrToday(wDaylightRaw).value : null;
          const todayResp         = latestOrToday(wRespRaw)?.value > 0 ? latestOrToday(wRespRaw).value : null;

          // ── peso y composición corporal ──
          const latestWeight  = wWeightRaw.length ? wWeightRaw[wWeightRaw.length - 1] : null;
          const prevWeight    = wWeightRaw.length >= 2 ? wWeightRaw[wWeightRaw.length - 8] ?? wWeightRaw[0] : null;
          const currentWeight = latestWeight?.value > 0 ? latestWeight.value : null;
          const prevWeightVal = prevWeight?.value > 0 ? prevWeight.value : null;
          const weightDelta   = currentWeight != null && prevWeightVal != null ? currentWeight - prevWeightVal : null;
          const latestBodyFat = wBodyFatRaw.length ? wBodyFatRaw[wBodyFatRaw.length - 1] : null;
          const currentBodyFat = latestBodyFat?.value > 0 ? latestBodyFat.value : null;
          const prevBodyFat   = wBodyFatRaw.length >= 2 ? (wBodyFatRaw[wBodyFatRaw.length - 8] ?? wBodyFatRaw[0]) : null;
          const bodyFatDelta  = currentBodyFat != null && prevBodyFat?.value > 0 ? currentBodyFat - prevBodyFat.value : null;
          const latestLean    = wLeanMassRaw.length ? wLeanMassRaw[wLeanMassRaw.length - 1] : null;
          const currentLean   = latestLean?.value > 0 ? latestLean.value : null;
          const prevLean      = wLeanMassRaw.length >= 2 ? (wLeanMassRaw[wLeanMassRaw.length - 8] ?? wLeanMassRaw[0]) : null;
          const leanDelta     = currentLean != null && prevLean?.value > 0 ? currentLean - prevLean.value : null;
          const targetWeight  = bodyGoals.targetWeight;
          const targetBodyFat = bodyGoals.targetBodyFat;
          const weightToGoal  = currentWeight != null && targetWeight ? currentWeight - targetWeight : null;

          // ── línea base personal de las métricas que se puntúan contra uno mismo ──
          // Anclada a HOY, que es el día que se está puntuando (la vista semanal puntúa
          // la semana que termina hoy). El histórico de la sparkline calcula la suya por
          // día dentro de wellnessHistory, para que cada día puntúe como puntuó entonces.
          const baselines = wellnessBaselines(healthData, todayStr);

    return { avg7, avgAe, avgCardioRec, avgDaylight, avgExercise, avgFlights, avgHrv, avgHrvPrev, avgResp, avgRhr, avgSleep, avgStand, avgSteps, avgWalkHr, baselines, bodyFatDelta, currentBodyFat, currentLean, currentWeight, daysSinceWorkout, daysToMonday, expectedByNow, last7Sleep, lastVo2, leanDelta, targetBodyFat, targetWeight, todayAe, todayDaylight, todayExercise, todayFlights, todayHrv, todayResp, todayRhr, todaySleep, todayStand, todaySteps, todayStr, todayWalkHr, todayWorkoutCount, wAeRaw, wBodyFatRaw, wCardioRecRaw, wDaylightRaw, wExerciseRaw, wFlightsRaw, wHrvRaw, wLeanMassRaw, wRespRaw, wRhrRaw, wSleepRaw, wStandRaw, wStepsRaw, wVo2Raw, wWalkHrRaw, wWeightRaw, wWorkRaw, weekStart, weekWorkoutCount, weightDelta, weightToGoal };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [healthData, trainingDays, bodyGoals, diaActual]);

  function renderWidget(id, cfg = {}) {
    const fixedH = typeof cfg.height === "number";
    const cardStyle = { ...s.card, ...(fixedH ? { height: "100%", overflowY: "auto" } : {}) };

    switch (id) {
      case "timeline": return (
        <div style={cardStyle} data-card={id} key="timeline">
          <div style={s.sectionLabel}>Hoy</div>
          {loading ? (
            <div style={{ color: "var(--muted)", fontSize: 13, padding: "16px 0" }}>Cargando eventos...</div>
          ) : authNeeded ? (
            <div style={{ color: "var(--muted)", fontSize: 13, padding: "8px 0" }}>
              <button
                onClick={conectarOutlook}
                style={{
                  background: "none", border: "none", padding: 0, font: "inherit",
                  color: "var(--accent)", cursor: "pointer",
                }}
              >
                → Conectar Outlook
              </button>
            </div>
          ) : todayEvents.length === 0 && todayClasses.length === 0 ? (
            <div style={{ color: "var(--muted)", fontSize: 13, padding: "8px 0" }}>Sin eventos hoy</div>
          ) : (
            <>
              <div style={s.timelineWrapper}>
                <div style={s.timeline} className="timeline-inner">
                  {timelineNodes.map((node, i) => (
                    <div key={i} style={s.timelineItem} onClick={() => {
                      if (node.type === "event") setActiveEvent(node.ev);
                      else setClassesOpen(true);
                    }}>
                      {i < timelineNodes.length - 1 && <div style={s.connectorLine} />}
                      {node.type === "event" ? (
                        <>
                          <div style={{
                            ...s.node,
                            ...(node.ev.active ? s.nodeActive : {}),
                            ...(node.ev.past   ? s.nodePast   : {}),
                            ...(!node.ev.active && !node.ev.past ? s.nodeFuture : {}),
                          }} />
                          <div style={s.nodeLabel}>
                            <div style={s.nodeTime}>{node.ev.time}</div>
                            <div style={{ ...s.nodeTitle, ...(node.ev.active ? s.nodeTitleActive : {}) }}>{node.ev.title}</div>
                          </div>
                        </>
                      ) : (
                        <>
                          <div style={{ ...s.node, background: "#8bb4d4", border: "1.5px solid #8bb4d4", boxShadow: "0 0 8px rgba(139,180,212,0.5)" }} />
                          <div style={s.nodeLabel}>
                            <div style={s.nodeTime}>🎓</div>
                            <div style={{ ...s.nodeTitle, color: "var(--accent2)" }}>Clases ({todayClasses.length})</div>
                          </div>
                        </>
                      )}
                    </div>
                  ))}
                </div>
              </div>
              {displayActive && (
                <div style={s.eventDetail}>
                  <div style={{ flex: 1 }}>
                    <div style={s.eventDetailTitle}>{displayActive.title}</div>
                    <div style={s.eventDetailSub}>{displayActive.loc}</div>
                    <DepartureWidget ev={displayActive} {...propsSalida} />
                  </div>
                  <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
                    <div style={s.eventDetailTime}>{displayActive.time}</div>
                    <span onClick={() => openEditEvent(displayActive)} title="Editar evento" style={{
                      cursor: "pointer", fontSize: 12, color: "var(--muted)", padding: "2px 4px",
                    }}>✎</span>
                  </div>
                </div>
              )}
            </>
          )}
        </div>
      );
      case "upcoming": return (
        <div style={cardStyle} data-card={id} key="upcoming">
          <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between" }}>
            <div style={s.sectionLabel}>Próximos eventos</div>
            <span onClick={openCreateEvent} title="Crear evento en Outlook" style={{
              cursor: "pointer", fontSize: 14, color: "var(--accent)", lineHeight: 1,
              padding: "2px 8px", borderRadius: 6, border: "0.5px solid rgba(200,169,110,0.3)",
              background: "rgba(200,169,110,0.1)", marginBottom: 12,
            }}>+ Evento</span>
          </div>
          <div style={{ display: "flex", flexDirection: "column", gap: 8, marginTop: 4 }}>
            {upcomingEvents.length === 0 ? (
              <div style={{ color: "var(--muted)", fontSize: 13 }}>Sin eventos próximos</div>
            ) : upcomingEvents.map((ev, i) => (
              <div key={i} style={{ ...s.eventRow, flexWrap: "wrap", alignItems: "flex-start" }}>
                <div style={s.eventDot} />
                <div style={s.eventRowTime}>{ev.time}</div>
                <div style={{ flex: 1 }}>
                  <div style={s.eventRowTitle}>{ev.title}</div>
                  {ev.loc && <div style={s.eventRowLoc}>{ev.loc}</div>}
                  <DepartureWidget ev={ev} {...propsSalida} />
                </div>
                <span onClick={() => openEditEvent(ev)} title="Editar evento" style={{
                  cursor: "pointer", fontSize: 12, color: "var(--muted)", padding: "2px 4px", flexShrink: 0,
                }}>✎</span>
              </div>
            ))}
          </div>
        </div>
      );
      case "entregas": return (
        <div style={cardStyle} data-card={id} key="entregas">
          <div style={s.sectionLabel}>Entregas pendientes</div>
          <div style={{ display: "flex", flexDirection: "column", gap: 8, marginTop: 4 }}>
            {entregas.length === 0 ? (
              <div style={{ color: "var(--muted)", fontSize: 13 }}>{`Sin entregas con ${ENTREGAS_MARKER} en el título`}</div>
            ) : entregas.map((e, i) => {
              const color = urgencyColor(e.days);
              return (
                <div key={i} style={s.entregaRow} onClick={() => { setWolModal(e); setWolStatus(null); }}>
                  <div style={{ ...s.urgencyBar, background: color }} />
                  <div style={{ flex: 1 }}>
                    <div style={s.entregaTitle}>{e.title}</div>
                    <div style={s.entregaSubject}>{e.subject}</div>
                  </div>
                  <div style={s.entregaCountdown}>
                    <div style={{ ...s.daysNum, color }}>{e.days}</div>
                    <span style={s.daysLabel}>días</span>
                  </div>
                </div>
              );
            })}
          </div>
        </div>
      );
      case "training": return (
        <div style={cardStyle} data-card={id} key="training">
          <div style={s.sectionLabel}>Entrenamiento</div>
          {!training?.client ? (
            <div style={{ color: "var(--muted)", fontSize: 13 }}>Sin datos</div>
          ) : (() => {
            const { sessions_since_payment: sess, hours_since_payment: hrs, amount_owed, sessions_per_payment: spp, last_payment_date, last_session_date } = training;
            const pct = Math.min((sess / spp) * 100, 100);
            const warn = sess >= spp;
            const barColor = warn ? "#d4645a" : "var(--accent)";
            return (
              <>
                <div style={{ display: "flex", alignItems: "baseline", gap: 6, marginBottom: 6 }}>
                  <span style={{ fontFamily: "'DM Mono', monospace", fontSize: 31, color: barColor, lineHeight: 1 }}>{sess}</span>
                  <span style={{ fontSize: 14, color: "var(--muted)" }}>/ {spp} sesiones</span>
                  <span style={{ marginLeft: "auto", fontFamily: "'DM Mono', monospace", fontSize: 17, color: warn ? "#d4645a" : "var(--text)" }}>{amount_owed}€</span>
                </div>
                <div style={{ height: 2, background: "var(--border)", borderRadius: 1, marginBottom: 8 }}>
                  <div style={{ height: "100%", borderRadius: 1, background: barColor, width: `${pct}%`, transition: "width 0.4s" }} />
                </div>
                <div style={{ fontSize: 13, color: "var(--muted)", marginBottom: 10, lineHeight: 1.7 }}>
                  {hrs > 0 && <span>{hrs}h acumuladas</span>}
                  {last_session_date && <span style={{ marginLeft: hrs > 0 ? 8 : 0 }}>· Última: {formatShortDate(last_session_date)}</span>}
                  {last_payment_date && <><br />Cobro: {formatShortDate(last_payment_date)}</>}
                </div>
                {showSessionForm ? (
                  <div style={{ display: "flex", gap: 6, alignItems: "center", flexWrap: "wrap" }}>
                    <input type="date" value={sessionDate} onChange={e => setSessionDate(e.target.value)}
                      style={{ flex: 1, minWidth: 120, padding: "6px 8px", background: "var(--surface2)", border: "0.5px solid var(--border2)", borderRadius: 6, color: "var(--text)", fontSize: 12, fontFamily: "'DM Sans', sans-serif" }} />
                    <select value={sessionHours} onChange={e => setSessionHours(e.target.value)}
                      style={{ padding: "6px 8px", background: "var(--surface2)", border: "0.5px solid var(--border2)", borderRadius: 6, color: "var(--text)", fontSize: 12, fontFamily: "'DM Sans', sans-serif" }}>
                      {["0.5","1","1.5","2","2.5","3"].map(h => <option key={h} value={h}>{h}h</option>)}
                    </select>
                    <button onClick={submitSession} disabled={trainingLoading} style={{ padding: "6px 12px", background: "var(--accent)", border: "none", borderRadius: 6, color: "#0e0f11", fontSize: 12, fontWeight: 600, cursor: "pointer", fontFamily: "'DM Sans', sans-serif" }}>✓</button>
                    <button onClick={() => setShowSessionForm(false)} style={{ padding: "6px 10px", background: "transparent", border: "0.5px solid var(--border2)", borderRadius: 6, color: "var(--muted)", fontSize: 12, cursor: "pointer", fontFamily: "'DM Sans', sans-serif" }}>✕</button>
                  </div>
                ) : (
                  <div style={{ display: "flex", gap: 6 }}>
                    <button onClick={() => { setSessionDate(new Date().toISOString().slice(0, 10)); setShowSessionForm(true); }}
                      style={{ flex: 1, padding: "7px 0", background: "rgba(200,169,110,0.12)", border: "0.5px solid rgba(200,169,110,0.3)", borderRadius: 6, color: "var(--accent)", fontSize: 12, cursor: "pointer", fontFamily: "'DM Sans', sans-serif" }}>+ Sesión</button>
                    {sess > 0 && (
                      <button onClick={submitPayment} disabled={trainingLoading}
                        style={{ flex: 1, padding: "7px 0", background: "rgba(106,170,130,0.12)", border: "0.5px solid rgba(106,170,130,0.3)", borderRadius: 6, color: "var(--green)", fontSize: 12, cursor: "pointer", fontFamily: "'DM Sans', sans-serif" }}>Cobrado ({amount_owed}€)</button>
                    )}
                  </div>
                )}
              </>
            );
          })()}
        </div>
      );
      case "finanzas": return (
        <div style={cardStyle} data-card={id} key="finanzas">
          <div style={{ ...s.sectionLabel, display: "flex", alignItems: "center", justifyContent: "space-between" }}>
            <span>Finanzas</span>
            {(finanzas?.configurado || finanzas?.revolut?.configurado || carteraEtf?.etfs?.length > 0) && (
              <button onClick={() => { loadFinanzas({ refrescar: true }); loadCarteraEtf({ refrescar: true }); }}
                disabled={finanzasCargando || carteraEtfCargando}
                title="Volver a preguntar a Indexa, Revolut y los precios de los ETFs (el dato normal es de hace unas horas)"
                style={{
                  padding: "2px 8px", borderRadius: 5, fontSize: 11, textTransform: "none",
                  letterSpacing: 0, border: "0.5px solid var(--border2)", background: "transparent",
                  color: "var(--muted)", cursor: (finanzasCargando || carteraEtfCargando) ? "default" : "pointer",
                  opacity: (finanzasCargando || carteraEtfCargando) ? 0.5 : 1,
                }}>↻</button>
            )}
          </div>
          {!finanzas ? (
            <div style={{ color: "var(--muted)", fontSize: 13, padding: "8px 0" }}>Cargando cartera...</div>
          ) : (
            <>
              {finanzas.error ? (
                <div style={{ color: "var(--muted)", fontSize: 13, padding: "8px 0" }}>No se pudo consultar Indexa</div>
              ) : !finanzas.configurado ? (
                <div style={{ color: "var(--muted)", fontSize: 13, padding: "8px 0", lineHeight: 1.6 }}>
                  Sin conectar. {finanzas.motivo || "Falta el token de Indexa Capital."}
                </div>
              ) : (() => {
            const { total, serie, cuentas = [] } = finanzas;
            const variacion = variacionCartera(serie);
            const positiva  = (total?.plusvalia ?? 0) >= 0;
            const colorPl   = positiva ? "var(--green)" : "#d4645a";
            const tramos    = mezclaCartera(
              cuentas.reduce((acc, c) => {
                for (const [clase, valor] of Object.entries(c.distribucion || {})) {
                  acc[clase] = (acc[clase] || 0) + valor;
                }
                return acc;
              }, {}),
            );
            // La fecha de valoración es la misma para todas las cuentas salvo que a una le
            // falte: se enseña la más antigua, que es hasta dónde llega lo que se sabe.
            const fechaValores = cuentas.map(c => c.fecha_valores).filter(Boolean).sort()[0];
            return (
              <>
                <div style={{ display: "flex", alignItems: "baseline", gap: 8, marginBottom: 4, flexWrap: "wrap" }}>
                  <span style={{ fontFamily: "'DM Mono', monospace", fontSize: 31, color: "var(--text)", lineHeight: 1 }}>
                    {formatoEuros(total?.valor)}
                  </span>
                  <span style={{ marginLeft: "auto", fontFamily: "'DM Mono', monospace", fontSize: 15, color: colorPl }}>
                    {formatoEuros(total?.plusvalia, { signo: true })}
                  </span>
                  <span style={{ fontSize: 13, color: colorPl }}>
                    {formatoPorcentaje(total?.plusvalia_pct, { signo: true })}
                  </span>
                </div>

                <div style={{ fontSize: 12, color: "var(--muted)", marginBottom: 10, lineHeight: 1.7 }}>
                  {variacion && (
                    <span style={{ color: variacion.valor >= 0 ? "var(--green)" : "#d4645a" }}>
                      {formatoEuros(variacion.valor, { signo: true })} desde {formatShortDate(variacion.desde)}
                    </span>
                  )}
                  {total?.aportado != null && (
                    <span style={{ marginLeft: variacion ? 8 : 0 }}>· Aportado {formatoEuros(total.aportado)}</span>
                  )}
                  {/* La rentabilidad anualizada de Indexa (ponderada por tiempo) no es la
                      plusvalía dividida entre los años: descuenta el efecto de cuándo
                      metiste cada aportación. Con una sola cuenta cabe aquí; con varias
                      va en cada fila, que es donde significa algo. */}
                  {cuentas.length === 1 && cuentas[0].rentabilidad_anual != null && (
                    <span style={{ marginLeft: 8 }}>· {formatoRentabilidad(cuentas[0].rentabilidad_anual)} anual</span>
                  )}
                  {/* Que falte el rendimiento de una cuenta cambia lo que significan estos
                      números, así que se dice aquí y no solo en el detalle. */}
                  {total && total.completo === false && (
                    <><br /><span style={{ color: "var(--muted2)" }}>Sin datos de rendimiento de alguna cuenta</span></>
                  )}
                </div>

                {serie?.length > 1 && (
                  <div style={{ marginBottom: 10 }}>
                    <Sparkline data={serie.map(p => ({ value: p.valor }))}
                      color={positiva ? "var(--green)" : "#d4645a"} height={38} relleno />
                  </div>
                )}

                {tramos.length > 0 && (
                  <>
                    <div style={{ display: "flex", height: 6, borderRadius: 3, overflow: "hidden", marginBottom: 6 }}>
                      {tramos.map(t => (
                        <div key={t.clase} title={`${CLASES_CARTERA_LABEL[t.clase] || t.clase}: ${formatoEuros(t.valor)}`}
                          style={{ width: `${t.pct}%`, background: CLASES_CARTERA_COLOR[t.clase] || CLASES_CARTERA_COLOR.otros }} />
                      ))}
                    </div>
                    <div style={{ display: "flex", flexWrap: "wrap", gap: 10, fontSize: 11, color: "var(--muted)", marginBottom: 10 }}>
                      {tramos.map(t => (
                        <span key={t.clase} style={{ display: "flex", alignItems: "center", gap: 4 }}>
                          <span style={{ width: 6, height: 6, borderRadius: 3, background: CLASES_CARTERA_COLOR[t.clase] || CLASES_CARTERA_COLOR.otros }} />
                          {CLASES_CARTERA_LABEL[t.clase] || t.clase} {formatoPorcentaje(t.pct, { decimales: 0 })}
                        </span>
                      ))}
                    </div>
                  </>
                )}

                {cuentas.length > 1 && (
                  <div style={{ display: "flex", flexDirection: "column", gap: 4, marginBottom: 10 }}>
                    {cuentas.map(c => (
                      <div key={c.numero} style={{ display: "flex", alignItems: "baseline", gap: 8, fontSize: 12, minWidth: 0 }}
                        title={c.rentabilidad_anual != null ? `${formatoRentabilidad(c.rentabilidad_anual)} anual` : undefined}>
                        <span style={{ color: "var(--muted)" }}>{CUENTA_INDEXA_LABEL[c.tipo] || c.tipo || c.numero}</span>
                        <span style={{ marginLeft: "auto", fontFamily: "'DM Mono', monospace" }}>{formatoEuros(c.valor)}</span>
                        <span style={{ color: (c.plusvalia ?? 0) >= 0 ? "var(--green)" : "#d4645a", minWidth: 52, textAlign: "right" }}>
                          {formatoPorcentaje(c.plusvalia_pct, { signo: true })}
                        </span>
                      </div>
                    ))}
                  </div>
                )}

                {finanzasDetalle && cuentas.flatMap(c => c.posiciones || []).length > 0 && (
                  <div style={{ display: "flex", flexDirection: "column", gap: 6, marginBottom: 10 }}>
                    {cuentas.flatMap(c => (c.posiciones || []).map(p => ({ ...p, cuenta: c.numero }))).map(p => (
                      <div key={`${p.cuenta}-${p.identificador || p.nombre}`} style={{ fontSize: 12, lineHeight: 1.5 }}>
                        <div style={{ display: "flex", gap: 8, minWidth: 0 }}>
                          {/* minWidth:0 para que el nombre largo se recorte en vez de
                              estirar la tarjeta: un elemento flex no baja de su ancho
                              de contenido si no se le dice. */}
                          <span style={{ flex: 1, minWidth: 0, color: "var(--text)", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
                            {p.nombre}
                          </span>
                          <span style={{ marginLeft: "auto", fontFamily: "'DM Mono', monospace", color: "var(--muted)" }}>
                            {formatoEuros(p.valor)}
                          </span>
                          <span style={{ color: (p.plusvalia ?? 0) >= 0 ? "var(--green)" : "#d4645a", minWidth: 62, textAlign: "right" }}>
                            {formatoEuros(p.plusvalia, { signo: true })}
                          </span>
                        </div>
                      </div>
                    ))}
                  </div>
                )}

                <div style={{ display: "flex", alignItems: "center", gap: 8, fontSize: 11, color: "var(--muted2)" }}>
                  {/* Indexa valora una vez al día y con retraso: sin esta fecha, una cartera
                      del viernes se lee como la de hoy. */}
                  <span>{fechaValores ? `Valores del ${formatShortDate(fechaValores)}` : "Sin fecha de valoración"}</span>
                  {cuentas.some(c => (c.posiciones || []).length > 0) && (
                    <button onClick={() => setFinanzasDetalle(v => !v)}
                      style={{
                        marginLeft: "auto", background: "none", border: "none", padding: 0,
                        font: "inherit", color: "var(--accent)", cursor: "pointer",
                      }}>{finanzasDetalle ? "Ocultar posiciones" : "Ver posiciones"}</button>
                  )}
                </div>
              </>
            );
          })()}

              {/* Revolut y la cartera manual de ETFs son otras dos cuentas, no otra
                  cartera de inversión: se enseñan con la misma fila compacta que ya
                  usan las cuentas de Indexa cuando hay más de una, en vez de cada una
                  con su propia caja y su propio título — es la misma información, solo
                  que antes se veía como tres widgets pegados y ahora como una sola
                  tarjeta. Siguen sin sumarse entre sí: inversión con plusvalía, saldo
                  de cuenta corriente y una cartera llevada a mano no dan un total que
                  signifique nada juntos. */}
              {(finanzas.revolut || (carteraEtf && !carteraEtf.error)) && (
                <div style={{ marginTop: 12, paddingTop: 10, borderTop: "0.5px solid var(--border2)", display: "flex", flexDirection: "column", gap: 10 }}>
                  {finanzas.revolut && (
                    !finanzas.revolut.configurado ? (
                      <div style={{ color: "var(--muted)", fontSize: 12, lineHeight: 1.6 }}>
                        Revolut sin conectar. {finanzas.revolut.motivo}
                      </div>
                    ) : (
                      <div>
                        <div style={{ display: "flex", alignItems: "baseline", gap: 8, fontSize: 12, minWidth: 0 }}>
                          <span style={{ color: "var(--text)" }}>Revolut</span>
                          <span style={{ marginLeft: "auto", fontFamily: "'DM Mono', monospace" }}>
                            {formatoEuros(finanzas.revolut.saldo)}
                          </span>
                        </div>
                        {/* Solo se ve la cuenta corriente: la de ahorro (vault) de Revolut no
                            tiene IBAN propio y no aparece como cuenta separada en el
                            consentimiento — no es un fallo de esta integración, Revolut no
                            la expone por esta vía. */}
                        {finanzas.revolut.cuentas.length > 1 && (
                          <div style={{ display: "flex", flexDirection: "column", gap: 2, marginTop: 2 }}>
                            {finanzas.revolut.cuentas.map((c, i) => (
                              <div key={i} style={{ display: "flex", justifyContent: "space-between", fontSize: 11, color: "var(--muted2)" }}>
                                <span>{c.nombre || "Cuenta"}</span>
                                <span style={{ fontFamily: "'DM Mono', monospace" }}>{formatoEuros(c.saldo)}</span>
                              </div>
                            ))}
                          </div>
                        )}
                      </div>
                    )
                  )}

                  {carteraEtf && !carteraEtf.error && carteraEtf.etfs.map(e => {
                    const form = etfAportForm[e.ticker] || {};
                    const positivaEtf = (e.ganancia_eur ?? 0) >= 0;
                    return (
                      <div key={e.ticker}>
                        <div style={{ display: "flex", alignItems: "baseline", gap: 8, fontSize: 12, minWidth: 0 }}>
                          <span style={{ color: "var(--text)" }}>{e.ticker}</span>
                          <span style={{ marginLeft: "auto", fontFamily: "'DM Mono', monospace" }}>
                            {formatoEuros(e.valor_actual)}
                          </span>
                          <span style={{ color: positivaEtf ? "var(--green)" : "#d4645a", minWidth: 52, textAlign: "right" }}>
                            {formatoRentabilidad(e.ganancia_pct, { signo: true })}
                          </span>
                        </div>
                        <div style={{ fontSize: 11, color: "var(--muted2)", marginTop: 2 }}>
                          {e.precio_actual != null ? `${formatoEuros(e.precio_actual, { decimales: 2 })}/particip.` : "Sin precio actual"}
                          {" · "}Aportado {formatoEuros(e.aportado_eur)}
                        </div>

                        {form.abierto ? (
                          <div style={{ display: "flex", gap: 6, marginTop: 6, flexWrap: "wrap" }}>
                            <input type="date" value={form.fecha || ""}
                              onChange={ev => setEtfAportForm(f => ({ ...f, [e.ticker]: { ...f[e.ticker], fecha: ev.target.value } }))}
                              style={{ flex: 1, minWidth: 120, padding: "6px 8px", background: "var(--surface2)", border: "0.5px solid var(--border2)", borderRadius: 6, color: "var(--text)", fontSize: 12, fontFamily: "'DM Sans', sans-serif" }} />
                            {/* Opcional: con la hora, el backend pide el precio horario de
                                Yahoo Finance (más preciso) en vez del cierre del día. */}
                            <input type="time" value={form.hora || ""} title="Hora de la compra (opcional, más precisión)"
                              onChange={ev => setEtfAportForm(f => ({ ...f, [e.ticker]: { ...f[e.ticker], hora: ev.target.value } }))}
                              style={{ width: 84, padding: "6px 8px", background: "var(--surface2)", border: "0.5px solid var(--border2)", borderRadius: 6, color: "var(--text)", fontSize: 12, fontFamily: "'DM Sans', sans-serif" }} />
                            <input type="number" min="0" step="0.01" placeholder="Importe €" value={form.importe || ""}
                              onChange={ev => setEtfAportForm(f => ({ ...f, [e.ticker]: { ...f[e.ticker], importe: ev.target.value } }))}
                              style={{ width: 90, padding: "6px 8px", background: "var(--surface2)", border: "0.5px solid var(--border2)", borderRadius: 6, color: "var(--text)", fontSize: 12, fontFamily: "'DM Sans', sans-serif" }} />
                            <button onClick={() => submitEtfAportacion(e.ticker)} disabled={form.guardando || !form.fecha || !form.importe}
                              style={{ padding: "6px 12px", background: "var(--accent)", border: "none", borderRadius: 6, color: "#0e0f11", fontSize: 12, fontWeight: 600, cursor: "pointer", fontFamily: "'DM Sans', sans-serif" }}>✓</button>
                            <button onClick={() => setEtfAportForm(f => ({ ...f, [e.ticker]: { abierto: false } }))}
                              style={{ padding: "6px 10px", background: "transparent", border: "0.5px solid var(--border2)", borderRadius: 6, color: "var(--muted)", fontSize: 12, cursor: "pointer", fontFamily: "'DM Sans', sans-serif" }}>✕</button>
                            {form.error && (
                              <div style={{ width: "100%", fontSize: 11, color: "#d4645a" }}>No se pudo guardar la aportación.</div>
                            )}
                          </div>
                        ) : (
                          <button onClick={() => setEtfAportForm(f => ({ ...f, [e.ticker]: { abierto: true, fecha: new Date().toISOString().slice(0, 10), importe: "" } }))}
                            style={{ marginTop: 4, padding: "4px 0", background: "none", border: "none", font: "inherit", fontSize: 11, color: "var(--accent)", cursor: "pointer" }}>
                            + Añadir aportación
                          </button>
                        )}
                      </div>
                    );
                  })}
                  {carteraEtf && !carteraEtf.error && carteraEtf.etfs.length === 0 && (
                    <div style={{ color: "var(--muted)", fontSize: 12 }}>Sin ETFs dados de alta.</div>
                  )}
                </div>
              )}
            </>
          )}
        </div>
      );
      case "jarvis": return (
        <div style={cardStyle} data-card={id} key="jarvis">
          <div style={{ ...s.sectionLabel, display: "flex", alignItems: "center", justifyContent: "space-between" }}>
            <span>Jarvis</span>
            {jarvisMensajes.length > 0 && !jarvisLlamada && (
              <button onClick={nuevaConversacionJarvis} disabled={jarvisPensando}
                title="Empezar una conversación nueva (no borra lo que Jarvis recuerda de ti)"
                style={{
                  padding: "2px 8px", borderRadius: 5, fontSize: 11, textTransform: "none",
                  letterSpacing: 0, border: "0.5px solid var(--border2)", background: "transparent",
                  color: "var(--muted)", cursor: jarvisPensando ? "default" : "pointer",
                  opacity: jarvisPensando ? 0.5 : 1,
                }}>Nueva conversación</button>
            )}
          </div>
          <JarvisChat
            mensajes={jarvisMensajes}
            borrador={jarvisBorrador}
            setBorrador={setJarvisBorrador}
            onEnviar={enviarAJarvis}
            pensando={jarvisPensando}
            pendiente={jarvisPendiente}
            onConfirmar={confirmarAccionJarvis}
            onDescartar={() => setJarvisPendiente(null)}
            confirmando={jarvisConfirmando}
            escuchando={jarvisEscuchando}
            onDictar={dictarAJarvis}
            habla={jarvisHabla}
            onHabla={alternarVozJarvis}
            finRef={jarvisFinRef}
            enLlamada={jarvisLlamada}
            faseLlamada={jarvisFase}
            parcial={jarvisParcial}
            onLlamar={iniciarLlamada}
            onColgar={() => colgarLlamada()}
            // Para traducir el id de una acción propuesta al nombre real de lo que toca:
            // el botón de confirmar no puede fiarse de cómo lo haya redactado el modelo.
            contexto={{ eventos: [...allEvents, ...classEvents], ideas }}
          />
        </div>
      );

      case "ideas": return (
        <div style={cardStyle} data-card={id} key="ideas">
          <div style={s.sectionLabel}>Ideas</div>
          <div style={{ display: "flex", flexDirection: "column", gap: 8, marginTop: 4 }}>
            {ideas.length === 0 && !processing && (
              <div style={{ color: "var(--muted)", fontSize: 13 }}>Sin ideas todavía. ¡Graba una!</div>
            )}
            {processing && (
              <div style={{ color: "var(--accent)", fontSize: 13, padding: "8px 0", animation: "pulse 1.5s infinite" }}>
                Procesando audio...
              </div>
            )}
            {ideas.map((idea, i) => (
              <div key={idea.id || i} style={s.ideaCard} onClick={() => setOpenIdea(openIdea === i ? null : i)}>
                <div style={s.ideaKey}>
                  <span style={{ flex: 1 }}>{idea.key}</span>
                  <div style={{ display: "flex", gap: 6, alignItems: "center", flexShrink: 0 }}>
                    <span style={s.ideaTag}>{idea.tag}</span>
                    <span style={{ fontSize: 10, color: "var(--muted2)", cursor: "pointer", padding: "0 4px" }}
                      onClick={e => { e.stopPropagation(); deleteIdea(idea.id); }}>✕</span>
                    <span style={{ ...s.ideaChevron, transform: openIdea === i ? "rotate(90deg)" : "rotate(0deg)" }}>▶</span>
                  </div>
                </div>
                {openIdea === i && <div style={s.ideaFull}>{idea.full_text}</div>}
              </div>
            ))}
          </div>
          {/* La nota traía una cita: se ofrece pasarla al calendario de un toque */}
          {eventoSugerido && (
            <div style={{
              marginTop: 10, padding: "10px 12px", borderRadius: 8,
              background: "rgba(139,180,212,0.08)", border: "0.5px solid rgba(139,180,212,0.3)",
            }}>
              <div style={{ fontSize: 12, color: "var(--muted)", marginBottom: 2 }}>Esto parece una cita</div>
              <div style={{ fontSize: 14, color: "var(--text)", marginBottom: 8 }}>
                {eventoSugerido.titulo}
                <span style={{ color: "var(--accent2)", fontFamily: "'DM Mono', monospace", marginLeft: 6 }}>
                  {formatShortDate(eventoSugerido.fecha)}{eventoSugerido.hora ? ` · ${eventoSugerido.hora}` : ""}
                </span>
              </div>
              {sugerenciaEstado === "ok" ? (
                <div style={{ fontSize: 12, color: "var(--green)" }}>
                  ✓ Añadido a Outlook
                  <button onClick={() => { setEventoSugerido(null); setSugerenciaEstado(null); }} style={{
                    background: "none", border: "none", color: "var(--muted2)", fontSize: 11,
                    cursor: "pointer", marginLeft: 8, textDecoration: "underline", padding: 0,
                  }}>Cerrar</button>
                </div>
              ) : (
                <div style={{ display: "flex", gap: 8, alignItems: "center" }}>
                  <button onClick={crearEventoDesdeIdea} disabled={sugerenciaEstado === "creando"} style={{
                    padding: "5px 12px", borderRadius: 6, fontSize: 12, cursor: "pointer",
                    background: "rgba(139,180,212,0.15)", border: "0.5px solid var(--accent2)",
                    color: "var(--accent2)", fontFamily: "'DM Sans', sans-serif",
                  }}>{sugerenciaEstado === "creando" ? "Añadiendo…" : "Añadir al calendario"}</button>
                  <button onClick={() => { setEventoSugerido(null); setSugerenciaEstado(null); }} style={{
                    background: "none", border: "none", color: "var(--muted)", fontSize: 12,
                    cursor: "pointer", padding: "5px 4px", fontFamily: "'DM Sans', sans-serif",
                  }}>Ahora no</button>
                  {sugerenciaEstado === "error" && (
                    <span style={{ fontSize: 11, color: "#d4645a" }}>No se pudo crear</span>
                  )}
                </div>
              )}
            </div>
          )}
          <div style={{ display: "flex", gap: 8, marginTop: 10 }}>
            <button style={{ ...s.newIdeaBtn, flex: 1, marginTop: 0, ...(recording ? { borderColor: "#d4645a", color: "#d4645a" } : {}) }}
              onClick={recording ? stopRecording : startRecording} disabled={processing}>
              {processing ? "Procesando..." : recording ? "⏹ Parar grabación" : "● Grabar idea"}
            </button>
            <button style={{ ...s.newIdeaBtn, flex: 1, marginTop: 0 }}
              onClick={openTextIdea} disabled={processing || recording}>
              ✎ Escribir idea
            </button>
          </div>
        </div>
      );
      case "clothing": {
        const totals       = clothingTotals(clothing);
        const totalEntries = Object.entries(totals);
        return (
          <div style={cardStyle} data-card={id} key="clothing">
            <div style={s.sectionLabel}>Conteo ropa</div>
            <div style={{ display: "flex", flexDirection: "column", gap: 8, marginTop: 4 }}>
              {clothing.length === 0 && !showClothingForm && (
                <div style={{ color: "var(--muted)", fontSize: 13 }}>Sin prendas todavía. ¡Añade la primera!</div>
              )}
              {clothing.map(item => (
                <div key={item.id} style={{ ...s.ideaCard, cursor: "default", display: "flex", alignItems: "center", gap: 12 }}>
                  {item.photo ? (
                    <img src={item.photo} alt={item.name || "Prenda"} onClick={() => setClothingZoom(item.photo)}
                      style={{ width: 44, height: 44, objectFit: "cover", borderRadius: 6, flexShrink: 0, cursor: "zoom-in", border: "0.5px solid var(--border2)" }} />
                  ) : (
                    <div style={{ width: 44, height: 44, borderRadius: 6, flexShrink: 0, display: "flex", alignItems: "center", justifyContent: "center", background: "var(--surface)", border: "0.5px solid var(--border2)", fontSize: 20 }}>👕</div>
                  )}
                  <div style={{ flex: 1, minWidth: 0 }}>
                    <div style={{ fontSize: 14, fontWeight: 500, color: item.name ? "var(--text)" : "var(--muted2)", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
                      {item.name || "Sin nombre"}
                    </div>
                    <div style={{ fontFamily: "'DM Mono', monospace", fontSize: 13, color: "var(--accent)", marginTop: 2 }}>
                      {formatMoney(item.price, item.currency)}
                    </div>
                  </div>
                  <span style={{ fontSize: 12, color: "var(--muted2)", cursor: "pointer", padding: "0 4px", flexShrink: 0 }}
                    onClick={() => deleteClothing(item.id)}>✕</span>
                </div>
              ))}
            </div>

            {totalEntries.length > 0 && (
              <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", flexWrap: "wrap", gap: 8, marginTop: 12, paddingTop: 12, borderTop: "0.5px solid var(--border2)" }}>
                <span style={{ fontSize: 12, color: "var(--muted)" }}>
                  {clothing.length} {clothing.length === 1 ? "prenda" : "prendas"}
                </span>
                <div style={{ display: "flex", gap: 12, flexWrap: "wrap" }}>
                  {totalEntries.map(([cur, sum]) => (
                    <span key={cur} style={{ fontFamily: "'DM Mono', monospace", fontSize: 15, color: "var(--text)" }}>
                      {formatMoney(sum, cur)}
                    </span>
                  ))}
                </div>
              </div>
            )}

            {showClothingForm ? (
              <div style={{ marginTop: 12, display: "flex", flexDirection: "column", gap: 10 }}>
                <input style={INPUT_STYLE} placeholder="Nombre (opcional)" value={clothingName}
                  onChange={e => setClothingName(e.target.value)} />
                <div style={{ display: "flex", gap: 8 }}>
                  <input style={{ ...INPUT_STYLE, flex: 1 }} type="text" inputMode="decimal" placeholder="Precio"
                    value={clothingPrice} onChange={e => setClothingPrice(e.target.value)} />
                  <div style={{ display: "flex", gap: 4 }}>
                    {Object.entries(CLOTHING_CURRENCIES).map(([code, sym]) => (
                      <button key={code} type="button"
                        style={{ ...s.newIdeaBtn, marginTop: 0, padding: "0 12px", minWidth: 40,
                          ...(clothingCurrency === code ? { borderStyle: "solid", borderColor: "var(--accent)", color: "var(--accent)" } : {}) }}
                        onClick={() => setClothingCurrency(code)}>
                        {sym}
                      </button>
                    ))}
                  </div>
                </div>
                <label style={{ ...s.newIdeaBtn, marginTop: 0, display: "flex", alignItems: "center", justifyContent: "center", gap: 8, cursor: "pointer" }}>
                  {clothingPhoto ? "✓ Foto añadida" : "📷 Añadir foto (opcional)"}
                  <input type="file" accept="image/*" style={{ display: "none" }}
                    onChange={e => onClothingPhoto(e.target.files?.[0])} />
                </label>
                {clothingPhoto && (
                  <img src={clothingPhoto} alt="Vista previa" style={{ width: "100%", maxHeight: 160, objectFit: "contain", borderRadius: 8, background: "var(--surface)" }} />
                )}
                {clothingError && (
                  <div style={{ fontSize: 12, color: "#d4645a", lineHeight: 1.4 }}>{clothingError}</div>
                )}
                <div style={{ display: "flex", gap: 8 }}>
                  <button style={{ ...s.newIdeaBtn, flex: 1, marginTop: 0 }}
                    onClick={closeClothingForm}>
                    Cancelar
                  </button>
                  <button style={{ ...s.newIdeaBtn, flex: 1, marginTop: 0,
                    ...(String(clothingPrice).trim() ? { borderStyle: "solid", borderColor: "var(--accent)", color: "var(--accent)" } : {}) }}
                    onClick={addClothing} disabled={!String(clothingPrice).trim() || clothingSaving}>
                    {clothingSaving ? "Guardando..." : "Añadir"}
                  </button>
                </div>
              </div>
            ) : (
              <button style={s.newIdeaBtn} onClick={() => { setClothingError(null); setShowClothingForm(true); }}>
                + Añadir prenda
              </button>
            )}
          </div>
        );
      }
      case "acciones_pc": return (
        <div style={cardStyle} data-card={id} key="acciones_pc">
          <div style={s.sectionLabel}>Streaming PC</div>
          <div style={{ fontSize: 12, color: "var(--muted)", marginTop: 4, marginBottom: 12, lineHeight: 1.5 }}>
            Enciende el PC y abre Sunshine para conectar con Moonlight desde el móvil.
          </div>
          <button
            style={{ ...s.newIdeaBtn, width: "100%", marginTop: 0 }}
            onClick={abrirStreaming}
          >
            🎮 Abrir streaming
          </button>
          {/* Apagar / suspender: los ejecuta HA por SSH (el agente es efímero) */}
          <div style={{ display: "flex", gap: 8, marginTop: 8 }}>
            <button
              style={{ ...s.newIdeaBtn, flex: 1, marginTop: 0, fontSize: 12 }}
              onClick={() => pcPowerAction("suspend")}
              disabled={pcPower === "suspending" || pcPower === "shutting"}
            >
              ⏸ Suspender
            </button>
            <button
              style={{
                ...s.newIdeaBtn, flex: 1, marginTop: 0, fontSize: 12,
                ...(confirmShutdown ? { borderColor: "#d4645a", color: "#d4645a" } : {}),
              }}
              onClick={() => confirmShutdown ? pcPowerAction("shutdown") : setConfirmShutdown(true)}
              disabled={pcPower === "suspending" || pcPower === "shutting"}
            >
              {confirmShutdown ? "¿Seguro? Apagar" : "⏻ Apagar"}
            </button>
          </div>
          {pcPower && (
            <div style={{
              fontSize: 11, marginTop: 8, textAlign: "center",
              color: pcPower === "error" ? "#d4645a" : "var(--muted)",
            }}>
              {pcPower === "suspending" ? "Enviando suspensión..."
                : pcPower === "shutting" ? "Enviando apagado..."
                : pcPower === "suspend_sent" ? "Suspensión enviada — HA la ejecutará"
                : pcPower === "shutdown_sent" ? "Apagado enviado — HA lo ejecutará"
                : "No se pudo enviar la orden"}
            </div>
          )}
        </div>
      );
      case "weather": {
        if (!weather) {
          return (
            <div style={cardStyle} data-card={id} key="weather">
              <div style={s.sectionLabel}>Clima</div>
              <div style={{ color: "var(--muted)", fontSize: 13, marginTop: 4 }}>Sin datos de clima</div>
            </div>
          );
        }
        const { emoji, label } = weatherFromCode(weather.code);
        const stats = [];
        if (weather.feels_like != null) stats.push(["Sensación", `${weather.feels_like}°`]);
        if (weather.humidity   != null) stats.push(["Humedad", `${weather.humidity}%`]);
        if (weather.wind       != null) stats.push(["Viento", `${weather.wind} km/h`]);
        const hoyProb = weather.daily?.[0]?.precip_prob;
        if (hoyProb != null) stats.push(["Lluvia", `${hoyProb}%`]);
        return (
          <div style={{ ...cardStyle, cursor: "pointer" }} data-card={id} key="weather"
               onClick={() => setWeatherExpanded(v => !v)}
               title={weatherExpanded ? "Contraer" : "Ver más"}>
            <div style={s.sectionLabel}>Clima</div>
            <div style={{ display: "flex", alignItems: "center", gap: 14, marginTop: 6 }}>
              <span style={{ fontSize: 40, lineHeight: 1 }}>{emoji}</span>
              <div style={{ flex: 1 }}>
                <div style={{ fontFamily: "'DM Mono', monospace", fontSize: 28, color: "var(--text)", lineHeight: 1 }}>
                  {weather.temp}°
                </div>
                <div style={{ fontSize: 13, color: "var(--muted)", marginTop: 2 }}>{label}</div>
              </div>
              <div style={{ textAlign: "right", fontSize: 13, color: "var(--muted)" }}>
                <div>máx <span style={{ color: "var(--text)" }}>{weather.temp_max}°</span></div>
                <div>mín <span style={{ color: "var(--text)" }}>{weather.temp_min}°</span></div>
              </div>
              <span style={{ fontSize: 11, color: "var(--muted2)", flexShrink: 0,
                transform: weatherExpanded ? "rotate(90deg)" : "rotate(0deg)", transition: "transform 0.2s" }}>▶</span>
            </div>

            {weatherExpanded && (
              <>
                {stats.length > 0 && (
                  <div style={{ display: "flex", flexWrap: "wrap", gap: "6px 16px", marginTop: 14, paddingTop: 14, borderTop: "0.5px solid var(--border2)" }}>
                    {stats.map(([k, v]) => (
                      <div key={k} style={{ fontSize: 12, color: "var(--muted)" }}>
                        {k} <span style={{ color: "var(--text)" }}>{v}</span>
                      </div>
                    ))}
                  </div>
                )}
                {weather.daily?.length > 1 && (
                  <div style={{ display: "flex", gap: 10, marginTop: 14, overflowX: "auto", WebkitOverflowScrolling: "touch" }}>
                    {weather.daily.map((d, i) => {
                      const w = weatherFromCode(d.code);
                      return (
                        <div key={d.date} style={{ flexShrink: 0, textAlign: "center", minWidth: 46 }}>
                          <div style={{ fontSize: 11, color: "var(--muted)", marginBottom: 4 }}>{i === 0 ? "Hoy" : weekdayShort(d.date)}</div>
                          <div style={{ fontSize: 22, lineHeight: 1 }}>{w.emoji}</div>
                          <div style={{ fontSize: 12, color: "var(--text)", marginTop: 4 }}>{d.max}°</div>
                          <div style={{ fontSize: 11, color: "var(--muted2)" }}>{d.min}°</div>
                        </div>
                      );
                    })}
                  </div>
                )}
              </>
            )}
          </div>
        );
      }
      case "health_wellness": {
        // Derivado una sola vez por cambio de datos, no por render (ver datosSalud).
        const {
          avgAe,
          avgCardioRec,
          avgDaylight,
          avgExercise,
          avgFlights,
          avgHrv,
          avgHrvPrev,
          avgResp,
          avgRhr,
          avgSleep,
          avgStand,
          avgSteps,
          avgWalkHr,
          baselines,
          bodyFatDelta,
          currentBodyFat,
          currentLean,
          currentWeight,
          daysSinceWorkout,
          expectedByNow,
          last7Sleep,
          lastVo2,
          leanDelta,
          targetBodyFat,
          targetWeight,
          todayAe,
          todayDaylight,
          todayExercise,
          todayFlights,
          todayHrv,
          todayResp,
          todayRhr,
          todaySleep,
          todayStand,
          todaySteps,
          todayWalkHr,
          todayWorkoutCount,
          wWeightRaw,
          weekWorkoutCount,
          weightDelta,
          weightToGoal,
        } = datosSalud;

        const isDaily = wellnessView === "daily";

        // ── valores según vista ──
        const sleepVal    = isDaily ? todaySleep    : avgSleep;
        const stepsVal    = isDaily ? todaySteps    : avgSteps;
        const hrvVal      = isDaily ? todayHrv      : avgHrv;
        const rhrVal      = isDaily ? todayRhr      : avgRhr;
        const aeVal       = isDaily ? todayAe       : avgAe;
        const exerciseVal = isDaily ? todayExercise : avgExercise;
        const standVal    = isDaily ? todayStand    : avgStand;
        const flightsVal  = isDaily ? todayFlights  : avgFlights;
        const walkHrVal   = isDaily ? todayWalkHr   : avgWalkHr;
        const daylightVal = isDaily ? todayDaylight : avgDaylight;
        const respVal     = isDaily ? todayResp     : avgResp;
        const workVal     = isDaily ? todayWorkoutCount : weekWorkoutCount;

        // ── puntuación ──
        // Todos los umbrales viven en wellnessBreakdown (helpers), fuera del render.
        // El desglose es la única fuente de verdad y el total sale de sumarlo, así que
        // no se puede volver a sumar un componente sin que aparezca en el detalle.
        const breakdown = wellnessBreakdown({
          isDaily, expectedByNow,
          sleep:        sleepVal,
          work:         workVal,
          exercise:     exerciseVal,
          steps:        stepsVal,
          activeEnergy: aeVal,
          stand:        standVal,
          flights:      flightsVal,
          hrv:          hrvVal,
          hrvPrev:      avgHrvPrev,
          rhr:          rhrVal,
          cardioRec:    avgCardioRec,
          vo2:          lastVo2,
          walkHr:       walkHrVal,
          bodyFat:      currentBodyFat,
          daylight:     daylightVal,
          resp:         respVal,
          // FC en reposo y FC caminando se puntúan contra los percentiles del propio
          // histórico cuando lo hay (ver "Línea base personal" en helpers): un umbral
          // fijo ahí premia la constitución, no el progreso. El desglose dice en cada
          // fila con cuál de los dos se ha puntuado.
          baselines,
        });

        // Normalizado a 100: la vista diaria puntúa sobre más componentes que la semanal,
        // así que con umbrales fijos "Semana excelente" era casi inalcanzable y "Día
        // excelente" bastante fácil. Sobre 100 las dos vistas significan lo mismo.
        const { pts: scorePts, max: scoreMax, score,
                componentes: scoreComponentes, sinDatos: scoreSinDatos } = scoreFromBreakdown(breakdown);
        const scoreLabel = isDaily
          ? (score >= 80 ? "Día excelente" : score >= 65 ? "Buen día" : score >= 50 ? "Día regular" : "Día flojo")
          : (score >= 80 ? "Semana excelente" : score >= 65 ? "Buena semana" : score >= 50 ? "Semana regular" : "Semana floja");
        const scoreColor = score >= 80 ? "var(--green)" : score >= 65 ? "#6aaa82" : score >= 50 ? "var(--accent)" : "#d4645a";

        // ── potencial: componente con más margen de mejora ──
        // El verbo de "💪 Entreno" depende de la vista, el resto son fijos (POTENTIAL_VERBS).
        const improvable = breakdown.filter(b => b.pts < b.max && !b.sinDatos);
        let potential = null;
        if (improvable.length > 0) {
          const top = improvable.reduce((a, b) => (b.max - b.pts) > (a.max - a.pts) ? b : a);
          const gap = top.max - top.pts;
          if (gap >= 2) {
            const verb = top.label === "💪 Entreno"
              ? (isDaily ? "Entrenando hoy" : "Sumando otra sesión de entreno")
              : POTENTIAL_VERBS[top.label] || `Mejorando ${top.label.replace(/^\S+\s/, "")}`;
            potential = `${verb} podrías sumar hasta ${gap} pts más (ahora ${top.pts}/${top.max} en ${top.label.replace(/^\S+\s/, "")}).`;
          }
        }

        // ── insights ──
        const insights = [];
        if (sleepVal != null) {
          if (isDaily) {
            if      (sleepVal >= 7.5) insights.push({ icon: "😴", color: "var(--green)",   text: `Noche excelente — ${hoursToHM(sleepVal)} de sueño` });
            else if (sleepVal >= 7)   insights.push({ icon: "😴", color: "#6aaa82",         text: `Buena noche — ${hoursToHM(sleepVal)} de sueño` });
            else if (sleepVal >= 6)   insights.push({ icon: "😴", color: "var(--accent)",   text: `Noche justa — ${hoursToHM(sleepVal)}. Intenta acostarte antes` });
            else                      insights.push({ icon: "😴", color: "#d4645a",         text: `Noche corta — ${hoursToHM(sleepVal)}. Prioriza descansar esta noche` });
          } else {
            const goodNights = last7Sleep.filter(d => d.value >= 7).length;
            if      (sleepVal >= 7.5) insights.push({ icon: "😴", color: "var(--green)",   text: `Sueño excelente — media de ${hoursToHM(sleepVal)}, ${goodNights} noches >7h` });
            else if (sleepVal >= 7)   insights.push({ icon: "😴", color: "#6aaa82",         text: `Sueño bueno — media de ${hoursToHM(sleepVal)}` });
            else if (sleepVal >= 6)   insights.push({ icon: "😴", color: "var(--accent)",   text: `Sueño justo — media de ${hoursToHM(sleepVal)}. Intenta acostarte antes` });
            else                      insights.push({ icon: "😴", color: "#d4645a",         text: `Sueño insuficiente — media de ${hoursToHM(sleepVal)}. Prioriza descansar` });
          }
        }
        if (isDaily) {
          if (todayWorkoutCount >= 1) insights.push({ icon: "💪", color: "var(--green)",  text: `${todayWorkoutCount > 1 ? todayWorkoutCount + " entrenamientos hoy" : "Entrenamiento completado hoy"} — objetivo diario cumplido` });
          else if (exerciseVal != null && exerciseVal >= 15) insights.push({ icon: "💪", color: exerciseVal >= 30 ? "#6aaa82" : "var(--muted)", text: `${Math.round(exerciseVal)} min de ejercicio hoy${exerciseVal >= 30 ? " — día activo" : ""}` });
          else if (todayHrv != null && todayHrv >= 70) insights.push({ icon: "💪", color: "var(--muted)", text: `Día de descanso — recuperación buena (HRV ${Math.round(todayHrv)}ms)` });
          else if (daysSinceWorkout != null) insights.push({ icon: "💪", color: daysSinceWorkout >= 3 ? "#d4645a" : "var(--muted)", text: `Sin entrenamiento hoy — llevas ${daysSinceWorkout} día${daysSinceWorkout !== 1 ? "s" : ""} de descanso` });
        } else {
          const remaining = Math.max(0, 4 - workVal);
          if      (workVal >= 5) insights.push({ icon: "💪", color: "var(--green)",   text: `${workVal} entrenamientos esta semana — objetivo superado` });
          else if (workVal === 4) insights.push({ icon: "💪", color: "var(--green)",   text: `4/4 entrenamientos esta semana — objetivo cumplido` });
          else if (workVal === 3) insights.push({ icon: "💪", color: "#6aaa82",        text: `3/4 entrenamientos — te queda ${remaining} para el objetivo` });
          else if (workVal === 2) insights.push({ icon: "💪", color: "var(--accent)",  text: `2/4 entrenamientos — te quedan ${remaining} esta semana` });
          else if (workVal === 1) insights.push({ icon: "💪", color: "#d4645a",        text: `1/4 entrenamientos — te quedan ${remaining} para cumplir el objetivo` });
          else if (daysSinceWorkout != null) insights.push({ icon: "💪", color: "#d4645a", text: `0/4 entrenamientos esta semana — llevas ${daysSinceWorkout} días sin ir al gym` });
        }
        if (stepsVal != null) {
          if (isDaily) {
            if      (stepsVal >= 9000) insights.push({ icon: "🚶", color: "var(--green)",  text: `Muy activo hoy — ${Math.round(stepsVal).toLocaleString("es")} pasos` });
            else if (stepsVal >= 6000) insights.push({ icon: "🚶", color: "#6aaa82",       text: `Actividad moderada — ${Math.round(stepsVal).toLocaleString("es")} pasos` });
            else                       insights.push({ icon: "🚶", color: "var(--accent)", text: `Poca actividad — ${Math.round(stepsVal).toLocaleString("es")} pasos hoy` });
          } else {
            if      (stepsVal >= 9000) insights.push({ icon: "🚶", color: "var(--green)",  text: `Muy activo — ${Math.round(stepsVal).toLocaleString("es")} pasos de media` });
            else if (stepsVal >= 6000) insights.push({ icon: "🚶", color: "#6aaa82",       text: `Actividad moderada — ${Math.round(stepsVal).toLocaleString("es")} pasos de media` });
            else                       insights.push({ icon: "🚶", color: "var(--accent)", text: `Poca actividad — ${Math.round(stepsVal).toLocaleString("es")} pasos. Intenta caminar más` });
          }
        }
        if (hrvVal != null) {
          const hrvTrendUp = avgHrvPrev && hrvVal > avgHrvPrev * 1.03;
          const hrvTrendDn = avgHrvPrev && hrvVal < avgHrvPrev * 0.97;
          if      (hrvTrendUp) insights.push({ icon: "❤️", color: "var(--green)",  text: `HRV en subida (${Math.round(hrvVal)}ms) — buena recuperación` });
          else if (hrvTrendDn) insights.push({ icon: "❤️", color: "#d4645a",       text: `HRV bajando (${Math.round(hrvVal)}ms) — quizás necesitas más descanso` });
          else                 insights.push({ icon: "❤️", color: "var(--muted)",  text: `HRV estable en ${Math.round(hrvVal)}ms` });
        }
        if (rhrVal != null) {
          if      (rhrVal <= 50) insights.push({ icon: "🫀", color: "var(--green)",  text: `FC en reposo excelente — ${Math.round(rhrVal)} lpm` });
          else if (rhrVal <= 60) insights.push({ icon: "🫀", color: "#6aaa82",       text: `FC en reposo buena — ${Math.round(rhrVal)} lpm` });
          else if (rhrVal <= 70) insights.push({ icon: "🫀", color: "var(--muted)",  text: `FC en reposo normal — ${Math.round(rhrVal)} lpm` });
          else                   insights.push({ icon: "🫀", color: "#d4645a",       text: `FC en reposo elevada — ${Math.round(rhrVal)} lpm` });
        }
        if (aeVal != null) {
          if (isDaily) {
            if      (aeVal >= 600) insights.push({ icon: "🔥", color: "var(--green)",  text: `Muy activo — ${Math.round(aeVal)} kcal quemadas hoy` });
            else if (aeVal >= 400) insights.push({ icon: "🔥", color: "#6aaa82",       text: `Buen gasto calórico — ${Math.round(aeVal)} kcal activas` });
            else if (aeVal >= 200) insights.push({ icon: "🔥", color: "var(--muted)",  text: `${Math.round(aeVal)} kcal activas hoy` });
          } else {
            if      (aeVal >= 500) insights.push({ icon: "🔥", color: "var(--green)",  text: `Gasto calórico alto — media de ${Math.round(aeVal)} kcal/día` });
            else if (aeVal >= 350) insights.push({ icon: "🔥", color: "#6aaa82",       text: `Gasto calórico moderado — media de ${Math.round(aeVal)} kcal/día` });
            else                   insights.push({ icon: "🔥", color: "var(--muted)",  text: `Gasto calórico bajo — media de ${Math.round(aeVal)} kcal/día` });
          }
        }

        // Composición corporal: insight de peso
        if (currentWeight != null) {
          const wSign = weightDelta != null ? (weightDelta > 0 ? "+" : "") : "";
          const wTrend = weightDelta != null ? ` (${wSign}${weightDelta.toFixed(1)} kg vs semana pasada)` : "";
          if (weightToGoal != null && Math.abs(weightToGoal) < 0.5) {
            insights.push({ icon: "⚖️", color: "var(--green)", text: `Peso objetivo alcanzado — ${currentWeight.toFixed(1)} kg${wTrend}` });
          } else if (weightToGoal != null && weightToGoal > 0) {
            // En definición: bajar peso es positivo
            const color = weightDelta != null && weightDelta < -0.1 ? "#6aaa82" : weightDelta != null && weightDelta > 0.1 ? "#d4645a" : "var(--muted)";
            insights.push({ icon: "⚖️", color, text: `${currentWeight.toFixed(1)} kg — faltan ${weightToGoal.toFixed(1)} kg para el objetivo${wTrend}` });
          } else if (weightToGoal != null && weightToGoal < 0) {
            insights.push({ icon: "⚖️", color: "var(--accent)", text: `${currentWeight.toFixed(1)} kg — ${Math.abs(weightToGoal).toFixed(1)} kg por debajo del objetivo${wTrend}` });
          } else {
            const color = weightDelta != null && weightDelta < -0.1 ? "#6aaa82" : weightDelta != null && weightDelta > 0.1 ? "#d4645a" : "var(--muted)";
            insights.push({ icon: "⚖️", color, text: `Peso: ${currentWeight.toFixed(1)} kg${wTrend}` });
          }
        }

        // ── recomendación ──
        let rec = null;
        if (daysSinceWorkout != null && daysSinceWorkout >= 2 && hrvVal && hrvVal > 50)
          rec = "Hoy es buen día para entrenar — llevas días de descanso y la recuperación es correcta.";
        else if (hrvVal && hrvVal < 45)
          rec = "Hoy mejor descanso activo — tu HRV indica que el cuerpo necesita recuperarse.";
        else if (sleepVal && sleepVal < 6.5)
          rec = isDaily
            ? "Noche corta. Intenta acostarte 30 min antes esta noche."
            : "Esta semana el sueño ha sido escaso. Intenta acostarte 30 min antes esta noche.";
        else if (!isDaily && workVal >= 4)
          rec = "Semana intensa de entrenamiento. Asegúrate de incluir un día de descanso.";
        else if (daylightVal != null && daylightVal < 15)
          rec = "Muy poca exposición a la luz natural. Salir 20-30 min al día mejora el ritmo circadiano y el estado de ánimo.";

        const hasAnyData = sleepVal != null || stepsVal != null || rhrVal != null || aeVal != null || (isDaily ? todayWorkoutCount > 0 : weekWorkoutCount > 0);

        const toggleStyle = (active) => ({
          padding: "2px 8px", borderRadius: 4, fontSize: 11, cursor: "pointer", border: "none",
          background: active ? "var(--accent)" : "transparent",
          color: active ? "var(--bg)" : "var(--muted)",
          fontFamily: "'DM Mono', monospace", letterSpacing: "0.03em", transition: "background 0.15s, color 0.15s",
        });

        return (
          <div style={cardStyle} data-card={id} key="health_wellness">
            <div style={{ ...s.sectionLabel, display: "flex", alignItems: "center", justifyContent: "space-between" }}>
              <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
                <span>{isDaily ? "Bienestar hoy" : "Bienestar semanal"}</span>
                <div style={{ display: "flex", background: "rgba(255,255,255,0.05)", borderRadius: 5, padding: 2, gap: 2 }}>
                  <button style={toggleStyle(!isDaily)} onClick={() => setWellnessView("weekly")}>Semana</button>
                  <button style={toggleStyle(isDaily)}  onClick={() => setWellnessView("daily")}>Hoy</button>
                </div>
              </div>
              {hasAnyData && (
                <div style={{ position: "relative" }}
                  onClick={e => { e.stopPropagation(); setScoreTooltip(v => !v); }}
                >
                  <span style={{ fontFamily: "'DM Mono', monospace", fontSize: 12, color: scoreColor, letterSpacing: "0.04em", cursor: "pointer", borderBottom: "1px dotted currentColor" }}>
                    {score}/100 — {scoreLabel}
                  </span>
                  {scoreTooltip && (
                    <div style={{
                      position: "absolute", right: 0, top: "calc(100% + 6px)", zIndex: 100,
                      background: "var(--surface2)", border: "0.5px solid var(--border)",
                      borderRadius: 8, padding: "10px 14px", minWidth: 220,
                      boxShadow: "0 4px 16px rgba(0,0,0,0.4)", fontSize: 12,
                      display: "flex", flexDirection: "column", gap: 5,
                    }}>
                      {breakdown.filter(b => !componentesNoMedidos.has(b.label)).map((b, i) => (
                        <div key={i} style={{ display: "flex", justifyContent: "space-between", alignItems: "center", gap: 12, opacity: b.sinDatos ? 0.45 : 1 }}>
                          <span style={{ color: "var(--muted)", whiteSpace: "nowrap" }}>{b.label}</span>
                          <span style={{ display: "flex", alignItems: "center", gap: 6, whiteSpace: "nowrap" }}>
                            <span style={{ color: "var(--text-2)", fontSize: 11 }}>{b.detail}</span>
                            {/* Sin dato no suma ni resta: se marca con — para que las filas visibles cuadren con el total */}
                            <span style={{ fontFamily: "'DM Mono', monospace", color: b.sinDatos ? "var(--muted2)" : b.pts === b.max ? "var(--green)" : b.pts > 0 ? "var(--accent)" : "var(--muted)", minWidth: 36, textAlign: "right" }}>
                              {b.sinDatos ? "—" : `${b.pts}/${b.max}`}
                            </span>
                          </span>
                        </div>
                      ))}
                      <div style={{ borderTop: "0.5px solid var(--border)", marginTop: 3, paddingTop: 5, display: "flex", justifyContent: "space-between", gap: 12 }}>
                        <span style={{ color: "var(--muted)" }}>Total</span>
                        <span style={{ display: "flex", alignItems: "center", gap: 6, whiteSpace: "nowrap" }}>
                          <span style={{ color: "var(--muted2)", fontSize: 11, fontFamily: "'DM Mono', monospace" }}>{scorePts}/{scoreMax}</span>
                          <span style={{ fontFamily: "'DM Mono', monospace", color: scoreColor, fontWeight: 600 }}>{score}/100</span>
                        </span>
                      </div>
                      {/* Normalizar a 100 hace comparables un día con nueve componentes
                          y otro con cuatro, pero también los deja indistinguibles. Esta
                          línea es la que dice sobre cuánto está calculado. */}
                      {scoreSinDatos > 0 && (
                        <div style={{ fontSize: 11, color: "var(--muted2)", lineHeight: 1.4 }}>
                          Calculado sobre {scoreComponentes} de {scoreComponentes + scoreSinDatos} componentes
                          {isDaily && relojHoy && !relojHoy.puesto ? " — hoy sin señal del reloj" : ""}.
                        </div>
                      )}
                    </div>
                  )}
                </div>
              )}
            </div>
            {healthLoading ? (
              <div style={{ color: "var(--muted)", fontSize: 13 }}>Cargando...</div>
            ) : !hasAnyData ? (
              <div style={{ color: "var(--muted)", fontSize: 13 }}>Sin datos todavía — los insights aparecerán cuando haya varios días de datos.</div>
            ) : (
              <>
                {potential && (
                  <div style={{ textAlign: "center", fontSize: 13, color: "var(--muted)", marginBottom: 12 }}>
                    💡 {potential}
                  </div>
                )}
                <div style={{ display: "flex", flexDirection: "column", gap: 8, marginBottom: rec ? 12 : 0 }}>
                  {insights.map((ins, i) => (
                    <div key={i} style={{ display: "flex", alignItems: "flex-start", gap: 10 }}>
                      <span style={{ fontSize: 16, lineHeight: 1.4, flexShrink: 0 }}>{ins.icon}</span>
                      <span style={{ fontSize: 15, color: "var(--text)", lineHeight: 1.5 }}>
                        <span style={{ color: ins.color, fontWeight: 500 }}>
                          {ins.text.split("—")[0]}
                        </span>
                        {ins.text.includes("—") && <span style={{ color: "var(--muted)" }}> — {ins.text.split("—").slice(1).join("—")}</span>}
                      </span>
                    </div>
                  ))}
                </div>
                {/* ── Evolución de la puntuación ──
                    El número de arriba es la foto de hoy (o de la semana); esto dice si
                    el mes va a mejor. Se reconstruye de las mismas series, sin guardar
                    nada aparte. */}
                {historicoBienestar.length >= 3 && (() => {
                  const serie   = historicoBienestar;
                  const primera = serie[0];
                  const ultima  = serie[serie.length - 1];
                  const dir     = tendenciaBienestar ? trendDirection(tendenciaBienestar.deltaPct, true, 3) : null;
                  const tonoDir = dir?.tone === "bien" ? "var(--green)" : dir?.tone === "mal" ? "#d4645a" : "var(--muted2)";
                  return (
                    <div style={{ marginTop: 14, borderTop: "0.5px solid var(--border)", paddingTop: 12 }}>
                      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "baseline", marginBottom: 4 }}>
                        <span style={{ fontFamily: "'DM Mono', monospace", fontSize: 10, color: "var(--muted2)", letterSpacing: "0.1em", textTransform: "uppercase" }}>
                          Evolución · {serie.length} días
                        </span>
                        {tendenciaBienestar && (
                          <span style={{ fontSize: 10, color: tonoDir, fontFamily: "'DM Mono', monospace" }}>
                            {dir.arrow} media 7d {Math.round(tendenciaBienestar.avgShort)} vs {Math.round(tendenciaBienestar.avgLong)} del mes
                          </span>
                        )}
                      </div>
                      <Sparkline data={serie} color="var(--accent2)" height={40} relleno
                        marcar={d => d.sinReloj} />
                      <div style={{ display: "flex", justifyContent: "space-between", fontSize: 10, color: "var(--muted2)", fontFamily: "'DM Mono', monospace", marginTop: 3 }}>
                        <span>{formatShortDate(primera.date)} · {primera.value}</span>
                        <span>{formatShortDate(ultima.date)} · {ultima.value}</span>
                      </div>
                      {/* Un día sin reloj puntúa sobre cuatro componentes en vez de
                          sobre nueve: la línea baja porque falta medida, no porque el
                          día fuera peor. */}
                      {serie.filter(d => d.sinReloj).length > 0 && (
                        <div style={{ fontSize: 10, color: "var(--muted2)", marginTop: 4, lineHeight: 1.4 }}>
                          ● {serie.filter(d => d.sinReloj).length} día(s) puntuados sin el reloj puesto — menos sensores, no peor día.
                        </div>
                      )}
                    </div>
                  );
                })()}
                {/* ── Composición corporal ── */}
                {(currentWeight != null || currentBodyFat != null || currentLean != null) && (
                  <div style={{ marginTop: 14, borderTop: "0.5px solid var(--border)", paddingTop: 12, display: "flex", flexDirection: "column", gap: 8 }}>
                    <div style={{ fontFamily: "'DM Mono', monospace", fontSize: 10, color: "var(--muted2)", letterSpacing: "0.1em", textTransform: "uppercase", marginBottom: 2 }}>Composición corporal</div>
                    <div style={{ display: "flex", gap: 16, flexWrap: "wrap" }}>
                      {currentWeight != null && (() => {
                        // Verde si se acerca al objetivo, rojo si se aleja
                        const goingRight = weightToGoal != null && weightDelta != null
                          ? (weightToGoal > 0 ? weightDelta < -0.05 : weightDelta > 0.05)
                          : weightDelta != null && weightDelta < -0.05;
                        const goingWrong = weightToGoal != null && weightDelta != null
                          ? (weightToGoal > 0 ? weightDelta > 0.05 : weightDelta < -0.05)
                          : weightDelta != null && weightDelta > 0.05;
                        const arrow = weightDelta != null ? (weightDelta < -0.05 ? "↓" : weightDelta > 0.05 ? "↑" : "→") : "";
                        const arrowColor = goingRight ? "var(--green)" : goingWrong ? "#d4645a" : "var(--muted)";
                        return (
                          <div style={{ display: "flex", alignItems: "baseline", gap: 4 }}>
                            <span style={{ fontFamily: "'DM Mono', monospace", fontSize: 15, color: "var(--text-2)" }}>{currentWeight.toFixed(1)}<span style={{ fontSize: 11, color: "var(--muted)", marginLeft: 2 }}>kg</span></span>
                            {weightDelta != null && <span style={{ fontSize: 11, color: arrowColor, fontFamily: "'DM Mono', monospace" }}>{arrow} {Math.abs(weightDelta).toFixed(1)}</span>}
                          </div>
                        );
                      })()}
                      {currentBodyFat != null && (() => {
                        const arrow = bodyFatDelta != null ? (bodyFatDelta < -0.1 ? "↓" : bodyFatDelta > 0.1 ? "↑" : "→") : "";
                        const color = bodyFatDelta != null ? (bodyFatDelta < -0.1 ? "var(--green)" : bodyFatDelta > 0.1 ? "#d4645a" : "var(--muted)") : "var(--muted)";
                        const goalText = targetBodyFat ? (currentBodyFat <= targetBodyFat ? " · obj ✓" : ` · obj ${targetBodyFat}%`) : "";
                        return (
                          <div style={{ display: "flex", alignItems: "baseline", gap: 4 }}>
                            <span style={{ fontFamily: "'DM Mono', monospace", fontSize: 15, color: "var(--text-2)" }}>{currentBodyFat.toFixed(1)}<span style={{ fontSize: 11, color: "var(--muted)", marginLeft: 2 }}>% grasa</span></span>
                            {bodyFatDelta != null && <span style={{ fontSize: 11, color, fontFamily: "'DM Mono', monospace" }}>{arrow} {Math.abs(bodyFatDelta).toFixed(1)}</span>}
                            {goalText && <span style={{ fontSize: 11, color: "var(--muted2)" }}>{goalText}</span>}
                          </div>
                        );
                      })()}
                      {currentLean != null && (() => {
                        const arrow = leanDelta != null ? (leanDelta > 0.1 ? "↑" : leanDelta < -0.1 ? "↓" : "→") : "";
                        const color = leanDelta != null ? (leanDelta > 0.1 ? "var(--green)" : leanDelta < -0.1 ? "#d4645a" : "var(--muted)") : "var(--muted)";
                        return (
                          <div style={{ display: "flex", alignItems: "baseline", gap: 4 }}>
                            <span style={{ fontFamily: "'DM Mono', monospace", fontSize: 15, color: "var(--text-2)" }}>{currentLean.toFixed(1)}<span style={{ fontSize: 11, color: "var(--muted)", marginLeft: 2 }}>kg magra</span></span>
                            {leanDelta != null && <span style={{ fontSize: 11, color, fontFamily: "'DM Mono', monospace" }}>{arrow} {Math.abs(leanDelta).toFixed(1)}</span>}
                          </div>
                        );
                      })()}
                    </div>
                    {/* Mantenimiento MEDIDO, no estimado. Las fórmulas (Mifflin,
                        Katch-McArdle) fallan ±300 kcal según lo musculado que estés;
                        esto sale de tu ingesta contra la pendiente de tu peso, que es
                        lo único que no supone nada. Solo aparece cuando hay datos
                        suficientes, y dice qué falta cuando no. */}
                    {(() => {
                      const m = mantenimientoEstimado(healthData);
                      if (m.kcal == null) {
                        const queFalta = {
                          ingesta:   `registra lo que comes (${m.diasIngesta}/${m.minimos.ingesta} días)`,
                          peso:      `pésate más a menudo (${m.pesadas}/${m.minimos.pesadas} pesadas)`,
                          recorrido: `hacen falta ${m.minimos.recorrido} días entre la primera pesada y la última`,
                          datos:     "los datos dan un resultado imposible: revisa las unidades",
                        }[m.falta];
                        // Sin ingesta registrada no hay nada que enseñar y decirlo cada
                        // día sería ruido: solo se avisa si ya se ha empezado a registrar.
                        if (m.falta === "ingesta" && m.diasIngesta === 0) return null;
                        return (
                          <div style={{ marginTop: 10, fontSize: 11, color: "var(--muted2)", lineHeight: 1.5 }}>
                            Mantenimiento: {queFalta}
                          </div>
                        );
                      }
                      const etiqueta = { alta: "", media: " · confianza media", baja: " · pocos datos aún" }[m.confianza];
                      const kgSem = m.pendienteKgSemana;
                      const rumbo = kgSem == null ? "" :
                        Math.abs(kgSem) < 0.05 ? "peso estable" :
                        `${kgSem < 0 ? "↓" : "↑"} ${Math.abs(kgSem).toFixed(2)} kg/sem`;
                      return (
                        <div style={{ marginTop: 10, paddingTop: 10, borderTop: "0.5px solid var(--border)" }}>
                          <div style={{ fontSize: 10, color: "var(--muted2)", fontFamily: "'DM Mono', monospace", letterSpacing: "0.08em", textTransform: "uppercase", marginBottom: 3 }}>Mantenimiento medido</div>
                          <div style={{ display: "flex", alignItems: "baseline", gap: 6 }}>
                            <span style={{ fontFamily: "'DM Mono', monospace", fontSize: 15, color: "var(--text-2)" }}>
                              {m.kcal.toLocaleString("es")}<span style={{ fontSize: 11, color: "var(--muted)", marginLeft: 2 }}>kcal</span>
                            </span>
                            {rumbo && <span style={{ fontSize: 11, color: "var(--muted)", fontFamily: "'DM Mono', monospace" }}>{rumbo}</span>}
                          </div>
                          <div style={{ fontSize: 10, color: "var(--muted2)", marginTop: 2 }}>
                            {Math.round(m.mediaIngesta).toLocaleString("es")} kcal/día comidos · {m.diasIngesta} días{etiqueta}
                          </div>
                        </div>
                      );
                    })()}

                    {/* Serie de peso con la línea del objetivo: el número de hoy no dice
                        si vas hacia él o te alejas; la curva sí. */}
                    {wWeightRaw.length >= 3 && (() => {
                      const serie   = wWeightRaw.slice(-30);
                      const primera = serie[0];
                      const ultima  = serie[serie.length - 1];
                      return (
                        <div>
                          <div style={{ display: "flex", justifyContent: "space-between", alignItems: "baseline", marginBottom: 4 }}>
                            <span style={{ fontFamily: "'DM Mono', monospace", fontSize: 10, color: "var(--muted2)", letterSpacing: "0.08em", textTransform: "uppercase" }}>
                              Peso · {serie.length} registros
                            </span>
                            {targetWeight && (
                              <span style={{ fontSize: 10, color: "var(--green)", fontFamily: "'DM Mono', monospace" }}>
                                — — objetivo {targetWeight} kg
                              </span>
                            )}
                          </div>
                          <Sparkline data={serie} color="var(--accent)" height={46}
                            objetivo={targetWeight || null} relleno />
                          <div style={{ display: "flex", justifyContent: "space-between", fontSize: 10, color: "var(--muted2)", fontFamily: "'DM Mono', monospace", marginTop: 3 }}>
                            <span>{formatShortDate(primera.date)}</span>
                            <span>{formatShortDate(ultima.date)}</span>
                          </div>
                        </div>
                      );
                    })()}
                    {/* Barra de progreso hacia objetivo de peso */}
                    {weightToGoal != null && currentWeight != null && (() => {
                      const startWeight = Math.max(currentWeight, targetWeight + 5);
                      const pct = Math.min(100, Math.max(0, ((startWeight - currentWeight) / (startWeight - targetWeight)) * 100));
                      const remaining = Math.abs(weightToGoal);
                      const reached = pct >= 100 || remaining < 0.1;
                      // ¿La tendencia reciente acerca o aleja del objetivo?
                      const approaching = weightDelta != null && Math.abs(weightDelta) > 0.05
                        ? (weightToGoal > 0 ? weightDelta < 0 : weightDelta > 0)
                        : null;
                      const barColor = reached ? "var(--green)"
                        : approaching === true  ? "var(--green)"
                        : approaching === false ? "#d4645a"
                        : "var(--accent)";
                      const trendLabel = reached ? "objetivo alcanzado"
                        : approaching === true  ? "acercándote"
                        : approaching === false ? "alejándote"
                        : null;
                      return (
                        <div>
                          <div style={{ display: "flex", justifyContent: "space-between", fontSize: 10, color: "var(--muted2)", marginBottom: 4, fontFamily: "'DM Mono', monospace" }}>
                            <span>objetivo {targetWeight} kg</span>
                            <span style={{ color: barColor }}>
                              {reached ? "✓ objetivo" : `faltan ${remaining.toFixed(1)} kg`}
                              {trendLabel && !reached && <span style={{ color: "var(--muted2)" }}> · {trendLabel}</span>}
                            </span>
                          </div>
                          <div style={{ height: 4, background: "rgba(255,255,255,0.06)", borderRadius: 2, overflow: "hidden" }}>
                            <div style={{ height: "100%", width: `${pct}%`, background: barColor, borderRadius: 2, transition: "width 0.6s ease, background 0.3s" }} />
                          </div>
                        </div>
                      );
                    })()}
                  </div>
                )}
                {rec && (
                  <div style={{
                    marginTop: 4, padding: "10px 14px",
                    background: "rgba(200,169,110,0.06)", borderLeft: "2px solid var(--accent)",
                    borderRadius: "0 8px 8px 0", fontSize: 14, color: "var(--muted)", lineHeight: 1.6,
                  }}>
                    <span style={{ color: "var(--accent)", fontWeight: 500 }}>Hoy → </span>{rec}
                  </div>
                )}
                {healthLastSync && (() => {
                  const diff = Math.floor((Date.now() - new Date(healthLastSync)) / 60000);
                  const label = diff < 2 ? "ahora mismo" : diff < 60 ? `hace ${diff} min` : diff < 1440 ? `hace ${Math.floor(diff/60)}h` : `hace ${Math.floor(diff/1440)}d`;
                  return (
                    <div style={{ marginTop: 10, fontSize: 12, color: "var(--muted2)", textAlign: "right", fontFamily: "'DM Mono', monospace" }}>
                      sync {label}
                    </div>
                  );
                })()}
              </>
            )}
          </div>
        );
      }
      case "health_sleep": {
        const sleepRaw     = findMetric(healthData, "sleep_analysis", "sleep");
        const sleepAllData = sleepRaw.map(d => ({ ...d, value: sleepHours(d) }));
        const sleepData    = sleepAllData.filter(d => !d.extra?.excluded);
        const ultimas7     = sleepAllData.slice(-7);
        const last7        = sleepData.slice(-7);
        const avg7         = last7.length ? last7.reduce((s, d) => s + (d.value || 0), 0) / last7.length : null;
        const latest       = sleepData[sleepData.length - 1];
        const sleepColor = v => v >= 7 ? "var(--green)" : v >= 6 ? "var(--accent)" : "#d4645a";

        // latestDisplay: noche más reciente (para mostrar, incluso si está excluida)
        const latestDisplay = sleepAllData[sleepAllData.length - 1];
        const lvd  = latestDisplay?.value || 0;
        const ldd  = latestDisplay?.extra?.deep  != null ? Number(latestDisplay.extra.deep)  : null;
        const lrd  = latestDisplay?.extra?.rem   != null ? Number(latestDisplay.extra.rem)   : null;
        const lcd  = latestDisplay?.extra?.core  != null ? Number(latestDisplay.extra.core)  : (latestDisplay?.extra?.light != null ? Number(latestDisplay.extra.light) : null);
        const lawd = latestDisplay?.extra?.awake != null ? Number(latestDisplay.extra.awake) : null;
        const latestExcluded = latestDisplay?.extra?.excluded ?? false;

        // latest: noche más reciente no excluida (para score y cálculos)
        const lv  = latest?.value || 0;
        const ld  = latest?.extra?.deep  != null ? Number(latest.extra.deep)  : null;
        const lr  = latest?.extra?.rem   != null ? Number(latest.extra.rem)   : null;
        const law = latest?.extra?.awake != null ? Number(latest.extra.awake) : null;
        const lss = latest?.extra?.sleep_start ?? null;

        // Baselines de recuperación (últimos 30 días, excluyendo hoy)
        const sleepTodayStr  = new Date().toLocaleDateString("sv");
        const hrvAllData     = findMetric(healthData, "heart_rate_variability", "heartRateVariability");
        const rhrAllData     = findMetric(healthData, "resting_heart_rate");
        const respAllData    = findMetric(healthData, "respiratory_rate");
        // Las medias de referencia no cruzan el cambio de dispositivo: comparar la
        // respiración de hoy contra una media hecha a medias con el reloj anterior
        // convierte la diferencia entre dos sensores en una penalización de sueño.
        const baseline30     = arr => { const v = arr.filter(d => d.date !== sleepTodayStr && d.value != null && (!corteDispositivo || String(d.date) >= corteDispositivo)).map(d => Number(d.value)).filter(v => v > 0); return v.length ? v.reduce((a,b) => a+b,0)/v.length : null; };
        const hrvBase        = baseline30(hrvAllData);
        const rhrBase        = baseline30(rhrAllData);
        const respBase       = baseline30(respAllData);
        const metricValForDate = (arr, date) => { const d = arr.find(x => x.date === date); return d?.value != null ? Number(d.value) : null; };
        const todayHrv       = metricValForDate(hrvAllData, sleepTodayStr) ?? (hrvAllData.length ? Number(hrvAllData[hrvAllData.length-1].value) : null);
        const todayRhr       = metricValForDate(rhrAllData, sleepTodayStr) ?? (rhrAllData.length ? Number(rhrAllData[rhrAllData.length-1].value) : null);
        const todayResp      = metricValForDate(respAllData, sleepTodayStr) ?? (respAllData.length ? Number(respAllData[respAllData.length-1].value) : null);
        const recoveryMod    = (hrvBase || rhrBase || respBase) ? calcRecoveryMod(todayHrv, todayRhr, todayResp, hrvBase ?? 0, rhrBase ?? 0, respBase ?? 0) : 0;
        const recovModByDate = date => calcRecoveryMod(
          metricValForDate(hrvAllData, date), metricValForDate(rhrAllData, date), metricValForDate(respAllData, date),
          hrvBase ?? 0, rhrBase ?? 0, respBase ?? 0
        );

        const score = latest ? sleepScore(lv, ld, lr, law, lss, recoveryMod) : null;
        const scoreLabel = score == null ? null : score >= 85 ? "Excelente" : score >= 70 ? "Bueno" : score >= 55 ? "Regular" : "Mejorable";
        const scoreColor = score == null ? null : score >= 85 ? "var(--green)" : score >= 70 ? "#6aaa82" : score >= 55 ? "var(--accent)" : "#d4645a";

        // Desglose del score para el tooltip. Las filas de puntuación salen del mismo
        // helper que calcula el score (única fuente de verdad de los umbrales); aquí
        // solo se añaden las subfilas de recuperación, que dependen de los baselines.
        const desgloseSueno = (() => {
          const base = latest ? sleepBreakdown(lv, ld, lr, law, lss) : null;
          if (!base) return [];
          const rows = [...base.filas];
          // Recuperación fisiológica — una subfila por métrica penalizada
          if (recoveryMod < 0) {
            rows.push({ label: "Recuperación", detail: "", pts: recoveryMod, max: 0 });
            if (todayHrv != null && hrvBase && hrvBase > 0) {
              const p = (() => { const pct = (todayHrv - hrvBase) / hrvBase * 100; return pct < -25 ? -8 : pct < -15 ? -6 : pct < -5 ? -3 : 0; })();
              if (p < 0) rows.push({ label: "HRV", detail: `${Math.round(todayHrv)} vs ${Math.round(hrvBase)} ms`, pts: p, max: 0, indent: true });
            }
            if (todayRhr != null && rhrBase && rhrBase > 0) {
              const p = (() => { const pct = (todayRhr - rhrBase) / rhrBase * 100; return pct > 15 ? -7 : pct > 10 ? -5 : pct > 5 ? -3 : 0; })();
              if (p < 0) rows.push({ label: "FC reposo", detail: `${Math.round(todayRhr)} vs ${Math.round(rhrBase)} bpm`, pts: p, max: 0, indent: true });
            }
            if (todayResp != null && respBase && respBase > 0) {
              const p = (() => { const pct = (todayResp - respBase) / respBase * 100; return pct > 15 ? -5 : pct > 10 ? -3 : pct > 5 ? -2 : 0; })();
              if (p < 0) rows.push({ label: "Freq. resp.", detail: `${todayResp.toFixed(1)} vs ${respBase.toFixed(1)} rpm`, pts: p, max: 0, indent: true });
            }
          }
          // El techo por duración también tiene que verse: con una noche corta y fases
          // buenas recortaba el total sin aparecer en ninguna fila, y el tooltip volvía
          // a no cuadrar consigo mismo (que es justo lo que se acaba de arreglar).
          const bruto = base.filas.reduce((s, f) => s + f.pts, 0) + recoveryMod;
          if (score != null && bruto > score) {
            rows.push({ label: "Techo por duración", detail: `máx ${base.cap} con ${hoursToHM(lv)}`, pts: score - bruto, max: 0 });
          }
          return rows;
        })();

        return (
          <div style={cardStyle} data-card={id} key="health_sleep">
            <div style={{ ...s.sectionLabel, display: "flex", alignItems: "center", justifyContent: "space-between" }}>
              <span>Sueño</span>
              {score != null && (
                <div style={{ position: "relative" }}
                  onClick={e => { e.stopPropagation(); setSleepScoreTooltip(v => !v); }}
                >
                  <span style={{ fontFamily: "'DM Mono', monospace", fontSize: 11, color: scoreColor, letterSpacing: "0.04em", textTransform: "none", cursor: "pointer", borderBottom: "1px dotted currentColor" }}>
                    {score} — {scoreLabel}
                  </span>
                  {sleepScoreTooltip && desgloseSueno.length > 0 && (
                    <div style={{
                      position: "absolute", right: 0, top: "calc(100% + 6px)", zIndex: 100,
                      background: "var(--surface2)", border: "0.5px solid var(--border)",
                      borderRadius: 8, padding: "10px 14px", minWidth: 240,
                      boxShadow: "0 4px 16px rgba(0,0,0,0.4)", fontSize: 12,
                      display: "flex", flexDirection: "column", gap: 4,
                    }}>
                      {desgloseSueno.map((b, i) => (
                        <div key={i} style={{ display: "flex", justifyContent: "space-between", alignItems: "center", gap: 16,
                          paddingLeft: b.indent ? 12 : 0, opacity: b.indent ? 0.85 : 1 }}>
                          <span style={{ color: b.indent ? "var(--muted2)" : "var(--muted)", whiteSpace: "nowrap", fontSize: b.indent ? 11 : 12 }}>{b.label}</span>
                          <span style={{ display: "flex", alignItems: "center", gap: 8, flexShrink: 0 }}>
                            {b.detail && <span style={{ color: "var(--text-2)", fontSize: 11, whiteSpace: "nowrap" }}>{b.detail}</span>}
                            <span style={{ fontFamily: "'DM Mono', monospace", minWidth: 34, textAlign: "right", fontSize: b.indent ? 11 : 12,
                              color: b.pts < 0 ? "#d4645a" : b.pts === b.max && b.max > 0 ? "var(--green)" : b.pts > 0 ? "var(--accent)" : "var(--muted)" }}>
                              {b.pts > 0 ? `${b.pts}/${b.max}` : b.pts || ""}
                            </span>
                          </span>
                        </div>
                      ))}
                      <div style={{ borderTop: "0.5px solid var(--border)", marginTop: 2, paddingTop: 5, display: "flex", justifyContent: "space-between" }}>
                        <span style={{ color: "var(--muted)" }}>Total</span>
                        <span style={{ fontFamily: "'DM Mono', monospace", color: scoreColor, fontWeight: 600 }}>{score}</span>
                      </div>
                    </div>
                  )}
                </div>
              )}
            </div>
            {healthLoading ? (
              <div style={{ color: "var(--muted)", fontSize: 13 }}>Cargando...</div>
            ) : ultimas7.length === 0 ? (
              <div style={{ color: "var(--muted)", fontSize: 13 }}>Sin datos de sueño aún</div>
            ) : (
              <>
                {latestDisplay && (
                  <div style={{ marginBottom: 10 }}>
                    <div style={{ display: "flex", alignItems: "baseline", gap: 8 }}>
                      <span style={{ fontFamily: "'DM Mono', monospace", fontSize: 33, color: latestExcluded ? "var(--muted2)" : sleepColor(lvd), lineHeight: 1, opacity: latestExcluded ? 0.5 : 1, textDecoration: latestExcluded ? "line-through" : "none" }}>
                        {hoursToHM(lvd)}
                      </span>
                      <span style={{ fontSize: 13, color: "var(--muted)" }}>
                        {latestExcluded ? "anoche (anulada)" : "anoche"}
                      </span>
                      {avg7 != null && (
                        <span style={{ marginLeft: "auto", fontSize: 13, color: "var(--muted)", fontFamily: "'DM Mono', monospace" }}>
                          media 7d: {hoursToHM(avg7)}
                        </span>
                      )}
                    </div>
                    <button
                      onClick={() => excludeSleepNight(latestDisplay.date)}
                      disabled={sleepExcluding === latestDisplay.date}
                      style={{ marginTop: 4, fontSize: 11, color: latestExcluded ? "var(--accent)" : "var(--muted2)", background: "none", border: "none", cursor: "pointer", padding: 0, textDecoration: "underline" }}
                    >
                      {sleepExcluding === latestDisplay.date ? "…" : latestExcluded ? "Restaurar noche" : "Anular noche"}
                    </button>
                  </div>
                )}
                {latestDisplay?.extra && (ldd != null || lrd != null || lcd != null) && !latestExcluded && (
                  <div style={{ display: "flex", gap: 10, marginBottom: 12, fontSize: 13, flexWrap: "wrap" }}>
                    {ldd != null && (
                      <SleepStageTooltip label={STAGE_TIPS.deep.label} color={STAGE_TIPS.deep.color} tip={STAGE_TIPS.deep.tip}>
                        <span style={{ color: "var(--muted)" }}>
                          <span style={{ color: "#4a72b0" }}>●</span> Profundo{" "}
                          <b style={{ color: "var(--text)", fontFamily: "'DM Mono', monospace" }}>{hoursToHM(ldd)}</b>
                        </span>
                      </SleepStageTooltip>
                    )}
                    {lrd != null && (
                      <SleepStageTooltip label={STAGE_TIPS.rem.label} color={STAGE_TIPS.rem.color} tip={STAGE_TIPS.rem.tip}>
                        <span style={{ color: "var(--muted)" }}>
                          <span style={{ color: "#8b68c4" }}>●</span> REM{" "}
                          <b style={{ color: "var(--text)", fontFamily: "'DM Mono', monospace" }}>{hoursToHM(lrd)}</b>
                        </span>
                      </SleepStageTooltip>
                    )}
                    {lcd != null && (
                      <SleepStageTooltip label={STAGE_TIPS.core.label} color={STAGE_TIPS.core.color} tip={STAGE_TIPS.core.tip}>
                        <span style={{ color: "var(--muted)" }}>
                          <span style={{ color: "#4f8fa3" }}>●</span> Core{" "}
                          <b style={{ color: "var(--text)", fontFamily: "'DM Mono', monospace" }}>{hoursToHM(lcd)}</b>
                        </span>
                      </SleepStageTooltip>
                    )}
                    {lawd != null && (
                      <SleepStageTooltip label={STAGE_TIPS.awake.label} color={STAGE_TIPS.awake.color} tip={STAGE_TIPS.awake.tip}>
                        <span style={{ color: "var(--muted)" }}>
                          <span style={{ color: "var(--muted2)" }}>●</span> Despierto{" "}
                          <b style={{ color: "var(--text)", fontFamily: "'DM Mono', monospace" }}>{hoursToHM(lawd)}</b>
                        </span>
                      </SleepStageTooltip>
                    )}
                  </div>
                )}
                {ultimas7.length > 1 && (
                  <div style={{ display: "flex", gap: 5, marginTop: 4 }}>
                    {ultimas7.map((d, i) => {
                      const excl = d.extra?.excluded ?? false;
                      const sc = excl ? null : sleepScore(d.value, Number(d.extra?.deep)||0, Number(d.extra?.rem)||0, Number(d.extra?.awake)||0, d.extra?.sleep_start ?? null, recovModByDate(d.date));
                      const c  = excl ? "var(--border2)" : sc == null ? "var(--border2)" : sc >= 85 ? "var(--green)" : sc >= 70 ? "#6aaa82" : sc >= 55 ? "var(--accent)" : "#d4645a";
                      const date = new Date(d.date + "T12:00:00");
                      const day  = DIAS_INICIAL[date.getDay()];
                      const isExcluding = sleepExcluding === d.date;
                      return (
                        <div key={i} style={{ flex: 1, textAlign: "center", position: "relative", cursor: "pointer" }}
                          title={excl ? `${day}: anulada` : `${day}: ${hoursToHM(d.value)}${sc != null ? ` · ${sc}pts` : ""}`}
                          onClick={() => !isExcluding && excludeSleepNight(d.date)}
                        >
                          <div style={{ height: 3, borderRadius: 2, background: c, opacity: excl ? 0.3 : 0.8 }} />
                          <div style={{ fontSize: 9, color: excl ? "var(--muted2)" : "var(--muted2)", marginTop: 3, fontFamily: "'DM Mono', monospace", opacity: excl ? 0.5 : 1 }}>
                            {isExcluding ? "·" : excl ? "×" : day}
                          </div>
                        </div>
                      );
                    })}
                  </div>
                )}
              </>
            )}
          </div>
        );
      }
      case "health_heart": {
        const hrData = findMetric(healthData, "heart_rate", "heartRate", "resting_heart_rate");
        const last30 = hrData.slice(-30);
        const latest = hrData[hrData.length - 1];
        const vals   = last30.map(d => d.value).filter(Boolean);
        const hrMin  = vals.length ? Math.min(...vals) : null;
        const hrMax  = vals.length ? Math.max(...vals) : null;
        return (
          <div style={cardStyle} data-card={id} key="health_heart">
            <div style={s.sectionLabel}>Frecuencia cardíaca</div>
            {healthLoading ? (
              <div style={{ color: "var(--muted)", fontSize: 13 }}>Cargando...</div>
            ) : last30.length === 0 ? (
              <div style={{ color: "var(--muted)", fontSize: 13 }}>Sin datos de FC aún</div>
            ) : (
              <>
                <div style={{ display: "flex", alignItems: "baseline", gap: 8, marginBottom: 8 }}>
                  <span style={{ fontFamily: "'DM Mono', monospace", fontSize: 33, color: "var(--accent)", lineHeight: 1 }}>
                    {latest?.value?.toFixed(0)}
                  </span>
                  <span style={{ fontSize: 13, color: "var(--muted)" }}>bpm</span>
                  {hrMin && hrMax && (
                    <span style={{ marginLeft: "auto", fontSize: 13, color: "var(--muted)", fontFamily: "'DM Mono', monospace" }}>
                      {hrMin}–{hrMax} (30d)
                    </span>
                  )}
                </div>
                <Sparkline data={last30} color="var(--accent)" height={42} />
              </>
            )}
          </div>
        );
      }
      case "health_hrv": {
        const hrvData = findMetric(healthData, "heart_rate_variability", "heartRateVariability", "hrv");
        const last30  = hrvData.slice(-30);
        const last7   = hrvData.slice(-7);
        const latest  = hrvData[hrvData.length - 1];
        const avg7    = last7.length  ? last7.reduce((s, d)  => s + (d.value || 0), 0) / last7.length  : null;
        const avg30   = last30.length ? last30.reduce((s, d) => s + (d.value || 0), 0) / last30.length : null;
        const trend   = avg7 && avg30 ? (avg7 > avg30 * 1.03 ? "↑" : avg7 < avg30 * 0.97 ? "↓" : "→") : null;
        const trendColor = trend === "↑" ? "var(--green)" : trend === "↓" ? "#d4645a" : "var(--muted)";
        return (
          <div style={cardStyle} data-card={id} key="health_hrv">
            <div style={s.sectionLabel}>HRV <span style={{ fontSize: 12, color: "var(--muted2)", textTransform: "none", letterSpacing: 0 }}>variabilidad cardíaca</span></div>
            {healthLoading ? (
              <div style={{ color: "var(--muted)", fontSize: 13 }}>Cargando...</div>
            ) : last30.length === 0 ? (
              <div style={{ color: "var(--muted)", fontSize: 13 }}>Sin datos de HRV aún</div>
            ) : (
              <>
                <div style={{ display: "flex", alignItems: "baseline", gap: 8, marginBottom: 8 }}>
                  <span style={{ fontFamily: "'DM Mono', monospace", fontSize: 33, color: "var(--accent2)", lineHeight: 1 }}>
                    {latest?.value?.toFixed(0)}
                  </span>
                  <span style={{ fontSize: 13, color: "var(--muted)" }}>ms</span>
                  {trend && <span style={{ fontSize: 20, color: trendColor, fontFamily: "'DM Mono', monospace" }}>{trend}</span>}
                  {avg7 != null && (
                    <span style={{ marginLeft: "auto", fontSize: 13, color: "var(--muted)", fontFamily: "'DM Mono', monospace" }}>
                      media 7d: {avg7.toFixed(0)}ms
                    </span>
                  )}
                </div>
                <Sparkline data={last30} color="var(--accent2)" height={42} />
              </>
            )}
          </div>
        );
      }
      case "health_activity": {
        const stepsData   = findMetric(healthData, "step_count", "steps", "stepCount");
        const caloriesData = findMetric(healthData, "active_energy", "activeEnergy");
        const last7       = stepsData.slice(-7);
        const todayStr    = new Date().toLocaleDateString("sv"); // YYYY-MM-DD
        const latest      = stepsData.find(d => d.date === todayStr) || null;
        const latestCal   = caloriesData.find(d => d.date === todayStr) || null;
        const maxSteps    = Math.max(...last7.map(d => d.value || 0), 10000);
        return (
          <div style={cardStyle} data-card={id} key="health_activity">
            <div style={s.sectionLabel}>Actividad</div>
            {healthLoading ? (
              <div style={{ color: "var(--muted)", fontSize: 13 }}>Cargando...</div>
            ) : last7.length === 0 ? (
              <div style={{ color: "var(--muted)", fontSize: 13 }}>Sin datos de actividad aún</div>
            ) : (
              <>
                <div style={{ display: "flex", alignItems: "baseline", gap: 8, marginBottom: 12 }}>
                  <span style={{ fontFamily: "'DM Mono', monospace", fontSize: 29, color: "var(--green)", lineHeight: 1 }}>
                    {(latest?.value || 0).toLocaleString("es")}
                  </span>
                  <span style={{ fontSize: 13, color: "var(--muted)" }}>pasos hoy</span>
                  {latestCal?.value && (
                    <span style={{ marginLeft: "auto", fontSize: 15, color: "var(--muted)", fontFamily: "'DM Mono', monospace" }}>
                      {latestCal.value.toFixed(0)} kcal
                    </span>
                  )}
                </div>
                <div style={{ display: "flex", alignItems: "flex-end", gap: 3, height: 48 }}>
                  {last7.map((d, i) => {
                    const h = Math.max(2, ((d.value || 0) / maxSteps) * 40);
                    const today_ = isToday(d.date + "T12:00:00");
                    const date = new Date(d.date + "T12:00:00");
                    const day = DIAS_INICIAL[date.getDay()];
                    return (
                      <div key={i} style={{ flex: 1, display: "flex", flexDirection: "column", alignItems: "center", gap: 2 }}
                        title={`${d.date}: ${(d.value || 0).toLocaleString("es")} pasos`}>
                        <div style={{ width: "100%", height: h, background: today_ ? "var(--green)" : "rgba(106,170,130,0.4)", borderRadius: "2px 2px 0 0" }} />
                        <div style={{ fontSize: 9, color: "var(--muted2)", fontFamily: "'DM Mono', monospace" }}>{day}</div>
                      </div>
                    );
                  })}
                </div>
              </>
            )}
          </div>
        );
      }
      case "health_workouts": {
        const wData  = findMetric(healthData, "workouts", "workout");
        const recent = wData.flatMap(d => (d.extra?.workouts || []).map(w => ({ ...w, _date: d.date }))).slice(-10).reverse();
        return (
          <div style={cardStyle} data-card={id} key="health_workouts">
            <div style={s.sectionLabel}>Entrenamientos</div>
            {healthLoading ? (
              <div style={{ color: "var(--muted)", fontSize: 13 }}>Cargando...</div>
            ) : recent.length === 0 ? (
              <div style={{ color: "var(--muted)", fontSize: 13 }}>Sin entrenamientos registrados</div>
            ) : (
              <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
                {recent.map((w, i) => {
                  const type = w.name || w.workoutActivityType || w.type || "Entrenamiento";
                  const icon = WORKOUT_ICONS[type] || "💪";
                  const rawDur = Number(w.duration);
                  const mins = !isNaN(rawDur) ? Math.round(rawDur > 300 ? rawDur / 60 : rawDur) : null;
                  const rawCal = w.activeEnergy?.qty ?? w.activeEnergy ?? w.totalEnergyBurned?.qty ?? w.totalEnergyBurned ?? w.activeEnergyBurned?.qty ?? w.activeEnergyBurned;
                  const cal = !isNaN(Number(rawCal)) && rawCal != null ? Number(rawCal) : null;
                  return (
                    <div key={i} style={{ display: "flex", alignItems: "center", gap: 10, padding: "8px 10px", background: "var(--surface2)", borderRadius: 8, border: "0.5px solid var(--border)" }}>
                      <span style={{ fontSize: 18 }}>{icon}</span>
                      <div style={{ flex: 1 }}>
                        <div style={{ fontSize: 13, color: "var(--text)", fontWeight: 500 }}>{type}</div>
                        <div style={{ fontSize: 11, color: "var(--muted)" }}>{formatShortDate((w.start || w._date || "").slice(0, 10))}</div>
                      </div>
                      <div style={{ textAlign: "right" }}>
                        {mins && <div style={{ fontFamily: "'DM Mono', monospace", fontSize: 12, color: "var(--accent)" }}>{mins}min</div>}
                        {cal  && <div style={{ fontSize: 11, color: "var(--muted)" }}>{Math.round(cal)}kcal</div>}
                      </div>
                    </div>
                  );
                })}
              </div>
            )}
          </div>
        );
      }
      case "health_hub": {
        // Widget compacto: veredicto general + top conclusiones. Al pulsar abre el
        // modal con el análisis completo (todas las conclusiones + widgets de detalle).
        const conclusions = conclusionesSalud;
        const overall     = veredictoSalud;
        const dot         = { good: "var(--green)", warn: "var(--accent)", bad: "#d4645a", info: "var(--muted)" };
        return (
          <div style={{ ...cardStyle, cursor: "pointer" }} data-card={id} key="health_hub"
            onClick={() => setHealthModalOpen(true)} title="Ver análisis completo">
            <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between" }}>
              <div style={s.sectionLabel}>Salud</div>
              <span style={{ fontSize: 16, color: "var(--muted2)", lineHeight: 1 }}>›</span>
            </div>
            {healthLoading ? (
              <div style={{ color: "var(--muted)", fontSize: 13 }}>Cargando...</div>
            ) : conclusions.length === 0 ? (
              <div style={{ color: "var(--muted)", fontSize: 13 }}>Sin datos de salud aún</div>
            ) : (
              <>
                <div style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 12 }}>
                  <span style={{ width: 9, height: 9, borderRadius: "50%", background: dot[overall.tone], flexShrink: 0 }} />
                  <span style={{ fontSize: 17, color: dot[overall.tone], fontWeight: 500 }}>{overall.label}</span>
                </div>
                <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
                  {conclusions.slice(0, 3).map((c, i) => (
                    <div key={i} style={{ display: "flex", gap: 8, fontSize: 12.5, color: "var(--text)", lineHeight: 1.45 }}>
                      <span style={{ color: dot[c.tone], flexShrink: 0 }}>•</span>
                      <span>{c.text}</span>
                    </div>
                  ))}
                </div>
                <div style={{ marginTop: 12, fontSize: 11, color: "var(--accent2)" }}>
                  Toca para ver el análisis completo →
                </div>
              </>
            )}
          </div>
        );
      }
      default: return null;
    }
  }

  function wrapResizable(w) {
    const cfg       = widgetConfig.find(c => c.id === w.id) || w;
    const widthPx   = typeof cfg.widthPct === "number" ? `${Math.round(cfg.widthPct * 100)}%` : "100%";
    const heightPx  = typeof cfg.height === "number" ? `${cfg.height}px` : "auto";
    const isDragged = draggingId === w.id;
    const col       = cfg.column || DEFAULT_COLUMNS[w.id] || "left";
    const showIndicator = isEditMode && draggingId && dragOverId === col && dragOverSide === w.id;

    return (
      <div
        key={w.id}
        id={`widget-wrap-${w.id}`}
        data-widget-id={w.id}
        data-column={col}
        className="widget-wrap"
        style={{
          width: widthPx,
          height: heightPx,
          minHeight: 80,
          opacity: isDragged ? 0.3 : 1,
          transition: "opacity 0.15s",
          position: "relative",
        }}
      >
        {showIndicator && (
          <div style={{ position:"absolute", top:-9, left:0, right:0, height:3, background:"var(--accent)", borderRadius:2, zIndex:10 }} />
        )}
        {isEditMode && (
          <div className="drag-handle" onMouseDown={e => handleDragHandleMouseDown(e, w.id)} title="Arrastrar para mover">⠿</div>
        )}
        {renderWidget(w.id, cfg)}
        {isEditMode && (
          <div
            className="resize-handle"
            onMouseDown={e => handleResizeMouseDown(e, w.id)}
            onDoubleClick={() => resetWidgetSize(w.id)}
            title="Arrastrar para cambiar tamaño · doble clic para restablecer"
          >
            <svg width="11" height="11" viewBox="0 0 11 11" fill="none">
              <line x1="10" y1="2" x2="2" y2="10" stroke="var(--accent)" strokeWidth="1.4" strokeLinecap="round"/>
              <line x1="10" y1="6" x2="6" y2="10" stroke="var(--accent)" strokeWidth="1.4" strokeLinecap="round"/>
            </svg>
          </div>
        )}
      </div>
    );
  }

  // ── SKELETON DE CARGA INICIAL ──────────────────────────────────
  // Se muestra mientras llega la primera carga de eventos (cold start de Fly.io).
  function renderBootSkeleton() {
    const line = (w, h = 12, mt = 0) => (
      <div className="la-skel" style={{ width: w, height: h, marginTop: mt }} />
    );
    const skelCard = (rows, key) => (
      <div style={{ ...s.card, display: "flex", flexDirection: "column", gap: 10 }} key={key}>
        {line("40%", 10)}
        {line("70%", 22, 4)}
        {rows > 1 && line("90%", 12, 6)}
        {rows > 2 && line("55%", 12)}
      </div>
    );
    const col = (keys) => (
      <div style={{ flex: "1 1 280px", minWidth: 0, display: "flex", flexDirection: "column", gap: 16 }}>
        {keys.map((k, i) => skelCard((i % 3) + 1, k))}
      </div>
    );
    return (
      <div style={{ flex: 1, display: "flex", flexDirection: "column", gap: 12 }}>
        {slowBoot && (
          <div style={{ display: "flex", alignItems: "center", gap: 8, color: "var(--muted)", fontSize: 12, fontFamily: "'DM Mono', monospace" }}>
            <span style={{ animation: "pulse 1.2s infinite", color: "var(--accent)" }}>●</span>
            Despertando el servidor…
          </div>
        )}
        <div style={{ display: "flex", gap: 16, flex: 1, alignItems: "flex-start", flexWrap: "wrap" }}>
          {col(["sk-l1", "sk-l2"])}
          {col(["sk-r1", "sk-r2", "sk-r3"])}
        </div>
      </div>
    );
  }

  // ── MODO SIMPLIFICADO (móvil) ──────────────────────────────────
  // Muestra los widgets marcados en la selección propia del modo simple
  // (independiente de la del modo completo), en el orden configurado.
  // Vertical: una sola columna. Horizontal: dos columnas según la columna
  // asignada a cada widget.
  function renderSimple() {
    const portrait = orientation === "portrait";

    // Los widgets de salud se colapsan en un único bloque con pestañas
    // (HEALTH_TAB_LABELS) — más navegable en móvil que apilar seis tarjetas grandes.
    const visibleWidgets = simpleWidgetConfig.filter(w => w.visible);
    const healthTabs = visibleWidgets
      .filter(w => w.id in HEALTH_TAB_LABELS)
      .map(w => ({ id: w.id, label: HEALTH_TAB_LABELS[w.id] }));

    // Si la pestaña activa ya no está entre las visibles, cae en la primera.
    const activeHealthTab = healthTabs.some(t => t.id === simpleHealthTab)
      ? simpleHealthTab
      : healthTabs[0]?.id;

    const healthBlock = healthTabs.length ? (
      <div key="simple-health" style={{ display: "flex", flexDirection: "column", gap: 10 }}>
        {healthTabs.length > 1 && (
          <div style={{ display: "flex", gap: 6, overflowX: "auto", paddingBottom: 2, WebkitOverflowScrolling: "touch" }}>
            {healthTabs.map(t => {
              const active = activeHealthTab === t.id;
              return (
                <button
                  key={t.id}
                  onClick={() => setSimpleHealthTab(t.id)}
                  style={{
                    flexShrink: 0, padding: "6px 12px", borderRadius: 999, cursor: "pointer",
                    fontSize: 12, fontFamily: "'DM Sans', sans-serif",
                    background: active ? "rgba(200,169,110,0.15)" : "var(--surface2)",
                    border: `0.5px solid ${active ? "var(--accent)" : "var(--border2)"}`,
                    color: active ? "var(--accent)" : "var(--muted)",
                  }}
                >{t.label}</button>
              );
            })}
          </div>
        )}
        {renderWidget(activeHealthTab)}
      </div>
    ) : null;

    // Lista ordenada de bloques a renderizar. Los widgets de salud se sustituyen
    // por el bloque de pestañas, insertado en la posición del primero visible.
    const items = [];
    let healthInserted = false;
    for (const w of visibleWidgets) {
      const column = w.column || DEFAULT_COLUMNS[w.id] || "left";
      if (w.id in HEALTH_TAB_LABELS) {
        if (!healthInserted) {
          items.push({ key: "simple-health", column, node: healthBlock });
          healthInserted = true;
        }
        continue;
      }
      items.push({ key: w.id, column, node: renderWidget(w.id) });
    }

    if (items.length === 0) {
      return (
        <div style={{ flex: 1, display: "flex", alignItems: "center", justifyContent: "center", padding: 40 }}>
          <div style={{ color: "var(--muted)", fontSize: 13, textAlign: "center", lineHeight: 1.5 }}>
            No hay widgets activos en el modo simple.<br />Actívalos en ajustes ⚙
          </div>
        </div>
      );
    }

    if (portrait) {
      return (
        <div style={{ flex: 1, display: "flex", flexDirection: "column", gap: 16 }}>
          {items.map(it => <React.Fragment key={it.key}>{it.node}</React.Fragment>)}
        </div>
      );
    }

    // Horizontal: dos columnas (la columna "centro" del modo completo cuenta
    // como derecha, porque el modo simple solo maneja izquierda/derecha).
    const leftItems  = items.filter(it => it.column === "left");
    const rightItems = items.filter(it => it.column !== "left");
    return (
      <div style={{ flex: 1, display: "flex", gap: 16, alignItems: "flex-start", flexWrap: "wrap" }}>
        <div style={{ flex: "1 1 300px", minWidth: 0, display: "flex", flexDirection: "column", gap: 16 }}>
          {leftItems.map(it => <React.Fragment key={it.key}>{it.node}</React.Fragment>)}
        </div>
        <div style={{ flex: "1 1 300px", minWidth: 0, display: "flex", flexDirection: "column", gap: 16 }}>
          {rightItems.map(it => <React.Fragment key={it.key}>{it.node}</React.Fragment>)}
        </div>
      </div>
    );
  }

  if (!token) return <LoginScreen />;

  return (
    <>
      {/* ── DASHBOARD PRINCIPAL ── */}
      <div style={s.dashboard} className="dashboard-root">

        {/* HEADER */}
        <div style={s.header}>
          <div>
            <div style={s.clock} className="clock">{hh}:{mm}</div>
            <div style={s.date}>{dateStr}</div>
          </div>
          <div style={{ display: "flex", alignItems: "flex-end", gap: 12 }}>
            <div style={s.greeting} className="header-greeting">
              {greeting}
              <strong style={s.greetingStrong}>Mikel</strong>
            </div>
            <div className="header-controls" style={{ display: "flex", alignItems: "center", gap: 8 }}>
              <button onClick={() => {
                setTrainingSettingsPrice(String(training?.client?.price_per_hour ?? ""));
                setTrainingSettingsSpp(String(training?.client?.sessions_per_payment ?? ""));
                setShowSettings(true);
                cargarEstadoSistema();
              }} style={{
                background: "transparent", border: "0.5px solid rgba(255,255,255,0.12)",
                borderRadius: 7, color: "var(--muted)", fontSize: 14, cursor: "pointer",
                padding: "3px 8px", fontFamily: "inherit", lineHeight: 1,
              }} title="Ajustes de widgets">⚙</button>
            </div>
          </div>
        </div>

        {/* CONTENIDO: skeleton mientras carga · modo simplificado · grid completo */}
        {loading ? renderBootSkeleton() : simpleMode ? renderSimple() : (() => {
          const activeCols = ACTIVE_COLUMNS[numColumns];
          const colWidgetMap = {};
          for (const col of activeCols) {
            colWidgetMap[col] = widgetConfig.filter(w => w.visible && (w.column || DEFAULT_COLUMNS[w.id] || "left") === col);
          }

          function getColFlex(i) {
            const lo = i > 0 ? colSplits[i - 1] : 0;
            const hi = i < colSplits.length ? colSplits[i] : 1;
            return hi - lo;
          }

          return (
            <div
              id="widget-grid-container"
              style={{ display: "flex", gap: 0, flex: 1, alignItems: "stretch", position: "relative" }}
            >
              {activeCols.map((col, i) => (
                <React.Fragment key={col}>
                  {/* COLUMN */}
                  <div
                    className={`col-${col}`}
                    style={{
                      flex: `${getColFlex(i)} 1 0`,
                      minWidth: 0,
                      display: "flex", flexDirection: "column", gap: 16,
                      outline: isEditMode && draggingId && dragOverId === col ? "2px solid rgba(200,169,110,0.5)" : "none",
                      borderRadius: 8, padding: isEditMode && draggingId && dragOverId === col ? 6 : 0,
                      transition: "outline 0.1s, padding 0.1s",
                    }}
                  >
                    {colWidgetMap[col].map(w => wrapResizable(w))}
                    {isEditMode && draggingId && dragOverId === col && dragOverSide === "__end__" && (
                      <div style={{ height: 3, background: "var(--accent)", borderRadius: 2, opacity: 0.7 }} />
                    )}
                  </div>

                  {/* DIVIDER (entre columnas, no tras la última) */}
                  {i < activeCols.length - 1 && (
                    <div
                      key={`divider-${i}`}
                      className="col-divider"
                      onMouseDown={ev => handleDividerDrag(ev, i)}
                      style={{
                        width: 16, flexShrink: 0, cursor: "col-resize",
                        display: "flex", alignItems: "center", justifyContent: "center",
                      }}
                    >
                      <div style={{ width: 3, height: 40, borderRadius: 2, background: "rgba(255,255,255,0.08)", transition: "background 0.15s" }}
                        onMouseEnter={e => e.target.style.background = "rgba(200,169,110,0.4)"}
                        onMouseLeave={e => e.target.style.background = "rgba(255,255,255,0.08)"}
                      />
                    </div>
                  )}
                </React.Fragment>
              ))}

              {/* SNAP ZONE OVERLAY (edit mode drag) */}
              {isEditMode && draggingId && (
                <div style={{
                  position: "absolute", inset: 0, display: "flex",
                  pointerEvents: "none", zIndex: 50, borderRadius: 8, overflow: "hidden",
                }}>
                  {activeCols.map((col, i) => {
                    const isOver = dragOverId === col;
                    const isFirst = i === 0;
                    const isLast  = i === activeCols.length - 1;
                    return (
                      <div key={col} style={{
                        flex: getColFlex(i),
                        background: isOver ? "rgba(200,169,110,0.08)" : "transparent",
                        border: isOver ? "2px solid rgba(200,169,110,0.4)" : "2px solid transparent",
                        borderRadius: isFirst ? "8px 0 0 8px" : isLast ? "0 8px 8px 0" : 0,
                        transition: "all 0.12s",
                        display: "flex", alignItems: "flex-end", justifyContent: "center", paddingBottom: 12,
                      }}>
                        {isOver && (
                          <span style={{ fontSize: 11, color: "var(--accent)", fontFamily: "'DM Mono'", opacity: 0.8 }}>
                            {COLUMN_LABELS[col]}
                          </span>
                        )}
                      </div>
                    );
                  })}
                </div>
              )}
            </div>
          );
        })()}

        {/* GHOST LABEL */}
        {isEditMode && draggingId && dragPos && (
          <div style={{
            position: "fixed", left: dragPos.x + 14, top: dragPos.y + 10,
            zIndex: 901, pointerEvents: "none",
            background: "var(--surface)", border: "1px solid var(--accent)",
            borderRadius: 8, padding: "5px 12px", fontSize: 11,
            color: "var(--accent)", fontFamily: "'DM Mono'", letterSpacing: "0.04em",
            boxShadow: "0 6px 20px rgba(0,0,0,0.5)",
          }}>
            {widgetConfig.find(w => w.id === draggingId)?.label}
          </div>
        )}

        {/* BOTÓN SALIR EDICIÓN */}
        {isEditMode && (
          <div style={{
            position: "fixed", bottom: 20, left: "50%", transform: "translateX(-50%)",
            zIndex: 800, background: "rgba(22,23,25,0.96)", backdropFilter: "blur(8px)",
            border: "0.5px solid rgba(200,169,110,0.4)", borderRadius: 10,
            padding: "10px 20px", display: "flex", gap: 10, alignItems: "center",
            boxShadow: "0 4px 24px rgba(0,0,0,0.4)",
          }}>
            <span style={{ fontSize: 12, color: "var(--muted)", fontFamily: "'DM Sans'" }}>
              ⠿ mover · ◢ altura · arrastra el divisor central para el ancho
            </span>
            <button onClick={() => setIsEditMode(false)} style={{
              padding: "5px 14px", background: "var(--accent)", border: "none",
              borderRadius: 6, color: "#0e0f11", fontSize: 12, fontWeight: 600,
              cursor: "pointer", fontFamily: "'DM Sans'",
            }}>Listo</button>
          </div>
        )}

        {/* FOOTER */}
        <div style={s.footer}>
          <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
            <div style={{ display: "flex", gap: 3 }}>
              <span style={s.appTabActive}>LA</span>
              <span style={s.appTabInactive} onClick={() => { window.top.location.href = HA_URL; }}>HA</span>
            </div>
            <span>
              <span style={s.statusDot} />
              {loading ? "Cargando..." : authNeeded ? "Outlook no conectado" : `${allEvents.length} eventos cargados`}
            </span>
          </div>
          <span>Life Assistant v0.1</span>
        </div>
      </div>

      {/* ── FOTO DE PRENDA A PANTALLA COMPLETA ── */}
      {clothingZoom && (
        <div onClick={() => setClothingZoom(null)} style={{
          position: "fixed", inset: 0, zIndex: 300,
          background: "rgba(0,0,0,0.85)", backdropFilter: "blur(6px)",
          display: "flex", alignItems: "center", justifyContent: "center",
          padding: 24, cursor: "zoom-out", animation: "fadeInOverlay 0.2s ease",
        }}>
          <img src={clothingZoom} alt="Prenda" style={{ maxWidth: "100%", maxHeight: "100%", objectFit: "contain", borderRadius: 12 }} />
        </div>
      )}

      {/* ── MODAL WAKE ON LAN ── */}
      {wolModal && (
        <>
          <div onClick={() => { setWolModal(null); setWolStatus(null); }} style={{
            position: "fixed", inset: 0,
            background: "rgba(0,0,0,0.6)", backdropFilter: "blur(6px)",
            zIndex: 200, animation: "fadeInOverlay 0.2s ease",
          }} />
          <div style={{
            position: "fixed", top: "50%", left: "50%",
            transform: "translate(-50%, -50%)",
            background: "#161719", border: "0.5px solid rgba(255,255,255,0.1)",
            borderRadius: 16, padding: "32px 36px", zIndex: 201,
            width: "min(400px, 90vw)", boxShadow: "0 24px 80px rgba(0,0,0,0.6)",
            animation: "fadeInOverlay 0.2s ease",
          }}>

            {wolStatus === null && (
              <>
                <div style={{ fontSize: 32, marginBottom: 16, textAlign: "center" }}>💻</div>
                <div style={{ fontFamily: "'DM Mono', monospace", fontSize: 15, color: "var(--text)", marginBottom: 6, textAlign: "center" }}>
                  ¿Encender PC?
                </div>
                <div style={{ fontSize: 12, color: "var(--muted)", textAlign: "center", marginBottom: 24, lineHeight: 1.6 }}>
                  {wolModal.title}
                  <br />
                  <span style={{ color: urgencyColor(wolModal.days) }}>{wolModal.days} días restantes</span>
                  <br />
                  <span style={{ color: isAgentOnline ? "var(--green)" : "#d4645a" }}>
                    Agente: {isAgentOnline ? "online" : "offline / no listo"}
                  </span>
                </div>
                <div style={{ display: "flex", gap: 10 }}>
                  <button onClick={() => { setWolModal(null); setWolStatus(null); }} style={{
                    flex: 1, padding: "10px 0", background: "transparent",
                    border: "0.5px solid rgba(255,255,255,0.12)", borderRadius: 8,
                    color: "var(--muted)", fontSize: 13, cursor: "pointer",
                    fontFamily: "'DM Sans', sans-serif",
                  }}>Cancelar</button>
                  <button
                    onClick={!isAgentOnline ? wakePC : undefined}
                    disabled={isAgentOnline}
                    title={isAgentOnline ? "El PC ya está encendido y el agente está online" : "Enviar señal Wake-on-LAN"}
                    style={{
                      flex: 1, padding: "10px 0",
                      background: isAgentOnline ? "rgba(255,255,255,0.08)" : "var(--accent)",
                      border: "none", borderRadius: 8,
                      color: isAgentOnline ? "var(--muted)" : "#0e0f11",
                      fontSize: 13, fontWeight: 600,
                      cursor: isAgentOnline ? "not-allowed" : "pointer",
                      fontFamily: "'DM Sans', sans-serif",
                      opacity: isAgentOnline ? 0.5 : 1,
                      transition: "all 0.2s",
                    }}
                  >{isAgentOnline ? "Ya online" : "Encender"}</button>
                </div>
                {isAgentOnline && (
                  <div style={{ fontSize: 11, color: "var(--muted)", textAlign: "center", marginTop: 8 }}>
                    El agente ya está online — no hace falta encender el PC.
                  </div>
                )}
              </>
            )}

            {wolStatus === "loading" && (
              <div style={{ textAlign: "center", padding: "16px 0" }}>
                <div style={{ fontSize: 32, marginBottom: 12, animation: "pulse 1s infinite" }}>⚡</div>
                <div style={{ fontSize: 13, color: "var(--muted)" }}>Enviando señal WOL...</div>
              </div>
            )}

            {wolStatus === "ok" && (
              <div style={{ textAlign: "center", padding: "16px 0" }}>
                <div style={{ fontSize: 32, marginBottom: 12 }}>
                  {jobTerminal?.status === "done" ? "✅" : jobTerminal?.status === "failed" ? "❌" : "⚡"}
                </div>
                <div style={{ fontSize: 14, color: "var(--green)", fontWeight: 500, marginBottom: 4 }}>
                  {jobTerminal?.status === "done" ? "¡Entrega completada!" : jobTerminal?.status === "failed" ? "El agente ha fallado" : "Job enviado"}
                </div>
                <div style={{
                  display: "inline-block", fontSize: 10, padding: "2px 10px", borderRadius: 99,
                  background: jobStatus === "running" ? "rgba(106,170,130,0.15)" : "rgba(255,255,255,0.06)",
                  color: jobStatus === "running" ? "var(--green)" : "var(--muted)",
                  border: `0.5px solid ${jobStatus === "running" ? "rgba(106,170,130,0.4)" : "rgba(255,255,255,0.1)"}`,
                  marginBottom: 12, letterSpacing: "0.05em",
                }}>
                  {JOB_STATUS_LABEL[jobStatus] || jobStatus || "—"}
                </div>
                <div style={{ width: "100%", height: 6, background: "rgba(255,255,255,0.08)", borderRadius: 999, overflow: "hidden", marginBottom: 10 }}>
                  <div style={{ width: `${progressPct}%`, height: "100%", background: "var(--accent)", transition: "width 0.5s" }} />
                </div>
                <div style={{ fontSize: 11, color: "var(--muted)", marginBottom: 10 }}>
                  {progressPct}%
                </div>
                <div style={{ textAlign: "left", fontSize: 11, color: "var(--muted)", maxHeight: 140, overflowY: "auto" }}>
                  {jobEvents.length === 0
                    ? <span style={{ color: "var(--muted2)", animation: "pulse 1.5s infinite", display: "inline-block" }}>Esperando al agente...</span>
                    : jobEvents.map((ev, i) => (
                      <div key={i} style={{ marginBottom: 5, display: "flex", gap: 6, alignItems: "baseline" }}>
                        <span style={{ color: "var(--accent)", flexShrink: 0 }}>·</span>
                        <span style={{ color: i === jobEvents.length - 1 ? "var(--text)" : "var(--muted)" }}>
                          {STAGE_LABELS[ev.stage] || ev.stage}
                          {ev.message ? <span style={{ color: "var(--muted2)" }}> — {ev.message}</span> : null}
                        </span>
                      </div>
                    ))
                  }
                </div>
                {jobTerminal?.status === "failed" && jobTerminal.reason && (
                  <div style={{ marginTop: 8, fontSize: 11, color: "#d4645a", textAlign: "left" }}>
                    {jobTerminal.reason}
                  </div>
                )}
              </div>
            )}

            {wolStatus === "error" && (
              <div style={{ textAlign: "center", padding: "16px 0" }}>
                <div style={{ fontSize: 32, marginBottom: 12 }}>❌</div>
                <div style={{ fontSize: 14, color: "#d4645a", fontWeight: 500 }}>Error al conectar con Home Assistant</div>
                <div style={{ fontSize: 12, color: "var(--muted)", marginTop: 6, marginBottom: 16 }}>¿Estás conectado a la red local o VPN?</div>
                <button onClick={() => { setWolModal(null); setWolStatus(null); }} style={{
                  padding: "8px 20px", background: "transparent",
                  border: "0.5px solid rgba(255,255,255,0.12)", borderRadius: 8,
                  color: "var(--muted)", fontSize: 12, cursor: "pointer",
                  fontFamily: "'DM Sans', sans-serif",
                }}>Cerrar</button>
              </div>
            )}
          </div>
        </>
      )}

      {/* ── STREAMING PC ── */}
      {pcModal && (
        <>
          <div onClick={() => { setPcModal(false); setPcStatus(null); }} style={{
            position: "fixed", inset: 0,
            background: "rgba(0,0,0,0.6)", backdropFilter: "blur(6px)",
            zIndex: 200, animation: "fadeInOverlay 0.2s ease",
          }} />
          <div style={{
            position: "fixed", top: "50%", left: "50%",
            transform: "translate(-50%, -50%)",
            background: "#161719", border: "0.5px solid rgba(255,255,255,0.1)",
            borderRadius: 16, padding: "32px 36px", zIndex: 201,
            width: "min(400px, 90vw)", boxShadow: "0 24px 80px rgba(0,0,0,0.6)",
            animation: "fadeInOverlay 0.2s ease",
          }}>

            {pcStatus === "loading" && (
              <div style={{ textAlign: "center", padding: "16px 0" }}>
                <div style={{ fontSize: 32, marginBottom: 12, animation: "pulse 1s infinite" }}>⚡</div>
                <div style={{ fontSize: 13, color: "var(--muted)" }}>Encendiendo el PC...</div>
              </div>
            )}

            {pcStatus === "ok" && (
              <div style={{ textAlign: "center", padding: "16px 0" }}>
                <div style={{ fontSize: 32, marginBottom: 12 }}>
                  {jobTerminal?.status === "done" ? "🎮" : jobTerminal?.status === "failed" ? "❌" : "⚡"}
                </div>
                <div style={{ fontSize: 14, color: "var(--green)", fontWeight: 500, marginBottom: 12 }}>
                  {jobTerminal?.status === "done" ? "Sunshine listo — abre Moonlight" : "Abriendo streaming"}
                </div>
                <div style={{
                  display: "inline-block", fontSize: 10, padding: "2px 10px", borderRadius: 99,
                  background: jobStatus === "running" ? "rgba(106,170,130,0.15)" : "rgba(255,255,255,0.06)",
                  color: jobStatus === "running" ? "var(--green)" : "var(--muted)",
                  border: `0.5px solid ${jobStatus === "running" ? "rgba(106,170,130,0.4)" : "rgba(255,255,255,0.1)"}`,
                  marginBottom: 12, letterSpacing: "0.05em",
                }}>
                  {JOB_STATUS_LABEL[jobStatus] || jobStatus || "—"}
                </div>
                {ipMoonlight && (
                  <div style={{
                    marginBottom: 12, padding: "8px 10px", borderRadius: 8,
                    background: "rgba(106,170,130,0.1)", border: "0.5px solid rgba(106,170,130,0.3)",
                  }}>
                    <div style={{ fontSize: 10, color: "var(--muted2)", letterSpacing: "0.08em", textTransform: "uppercase" }}>Host para Moonlight</div>
                    <div style={{ fontSize: 15, fontFamily: "monospace", color: "var(--green)", marginTop: 2 }}>{ipMoonlight}</div>
                  </div>
                )}
                <div style={{ textAlign: "left", fontSize: 11, color: "var(--muted)", maxHeight: 140, overflowY: "auto" }}>
                  {jobEvents.length === 0
                    ? <span style={{ color: "var(--muted2)", animation: "pulse 1.5s infinite", display: "inline-block" }}>El PC se está encendiendo... el agente arrancará con Windows.</span>
                    : jobEvents.map((ev, i) => (
                      <div key={i} style={{ marginBottom: 5, display: "flex", gap: 6, alignItems: "baseline" }}>
                        <span style={{ color: "var(--accent)", flexShrink: 0 }}>·</span>
                        <span style={{ color: i === jobEvents.length - 1 ? "var(--text)" : "var(--muted)" }}>
                          {STAGE_LABELS[ev.stage] || ev.stage}
                          {ev.message ? <span style={{ color: "var(--muted2)" }}> — {ev.message}</span> : null}
                        </span>
                      </div>
                    ))
                  }
                </div>
                {jobTerminal?.status === "failed" && jobTerminal.reason && (
                  <div style={{ marginTop: 8, fontSize: 11, color: "#d4645a", textAlign: "left" }}>
                    {jobTerminal.reason}
                  </div>
                )}

                <button onClick={() => { setPcModal(false); setPcStatus(null); }} style={{
                  width: "100%", marginTop: 12, padding: "10px 0", background: "transparent",
                  border: "0.5px solid rgba(255,255,255,0.12)", borderRadius: 8,
                  color: "var(--muted)", fontSize: 13, cursor: "pointer",
                  fontFamily: "'DM Sans', sans-serif",
                }}>Cerrar</button>
              </div>
            )}

            {pcStatus === "error" && (
              <div style={{ textAlign: "center", padding: "16px 0" }}>
                <div style={{ fontSize: 32, marginBottom: 12 }}>❌</div>
                <div style={{ fontSize: 14, color: "#d4645a", fontWeight: 500 }}>No se pudo completar la acción</div>
                <div style={{ fontSize: 12, color: "var(--muted)", marginTop: 6, marginBottom: 16 }}>¿Estás conectado a la red local o VPN?</div>
                <button onClick={() => { setPcModal(false); setPcStatus(null); }} style={{
                  padding: "8px 20px", background: "transparent",
                  border: "0.5px solid rgba(255,255,255,0.12)", borderRadius: 8,
                  color: "var(--muted)", fontSize: 12, cursor: "pointer",
                  fontFamily: "'DM Sans', sans-serif",
                }}>Cerrar</button>
              </div>
            )}
          </div>
        </>
      )}

      {/* ── CREAR EVENTO ── */}
      {showCreateEvent && (
        <>
          <div onClick={closeEventModal} style={{
            position: "fixed", inset: 0,
            background: "rgba(0,0,0,0.6)", backdropFilter: "blur(6px)",
            zIndex: 200, animation: "fadeInOverlay 0.2s ease",
          }} />
          <div style={{
            position: "fixed", top: "50%", left: "50%",
            transform: "translate(-50%, -50%)",
            background: "#161719", border: "0.5px solid rgba(255,255,255,0.1)",
            borderRadius: 16, padding: "28px 32px", zIndex: 201,
            width: "min(420px, 90vw)", boxShadow: "0 24px 80px rgba(0,0,0,0.6)",
            animation: "fadeInOverlay 0.2s ease",
          }}>
            <div style={{ fontFamily: "'DM Mono', monospace", fontSize: 15, color: "var(--text)", marginBottom: 18, textAlign: "center" }}>
              {editingEventId ? "Editar evento de Outlook" : "Nuevo evento en Outlook"}
            </div>
            <div style={{ display: "flex", flexDirection: "column", gap: 14 }}>
              <input type="text" placeholder="Título" value={eventForm.subject}
                onChange={e => setEventForm(f => ({ ...f, subject: e.target.value }))}
                style={{ ...INPUT_STYLE, fontSize: 15, padding: "11px 12px" }} />

              <div>
                <div style={FIELD_LABEL_STYLE}>Fecha</div>
                <DateInput value={eventForm.date} onChange={v => setEventForm(f => ({ ...f, date: v }))} />
                <div style={{ fontSize: 11, color: "var(--muted2)", marginTop: 5 }}>
                  {eventForm.date ? formatShortDate(eventForm.date) : ""}
                </div>
              </div>

              <div>
                <div style={FIELD_LABEL_STYLE}>Hora</div>
                <div style={{ display: "flex", gap: 8, alignItems: "center" }}>
                  <TimeInput value={eventForm.startTime} onChange={v => setEventForm(f => {
                    const [hh, mm] = v.split(":").map(Number);
                    const total = (hh * 60 + mm + 30) % (24 * 60);
                    const endTime = `${String(Math.floor(total / 60)).padStart(2, "0")}:${String(total % 60).padStart(2, "0")}`;
                    return { ...f, startTime: v, endTime };
                  })} />
                  <span style={{ color: "var(--muted2)", fontSize: 13 }}>→</span>
                  <TimeInput value={eventForm.endTime} onChange={v => setEventForm(f => ({ ...f, endTime: v }))} />
                </div>
              </div>

              <div>
                <div style={FIELD_LABEL_STYLE}>Ubicación</div>
                <input type="text" placeholder="Opcional" value={eventForm.location}
                  onChange={e => setEventForm(f => ({ ...f, location: e.target.value }))}
                  style={INPUT_STYLE} />
              </div>

              {!editingEventId && (
                <div>
                  <div style={FIELD_LABEL_STYLE}>Calendario</div>
                  <select value={eventForm.calendarId}
                    onChange={e => setEventForm(f => ({ ...f, calendarId: e.target.value }))}
                    style={INPUT_STYLE}>
                    <option value="">Por defecto</option>
                    {calendarsList.map(c => <option key={c.id} value={c.id}>{c.name}</option>)}
                  </select>
                </div>
              )}

              <div>
                <div style={FIELD_LABEL_STYLE}>URL de Alud (opcional)</div>
                <input type="url" placeholder="https://alud.deusto.es/mod/assign/view.php?id=XXXXX" value={eventForm.alud_url}
                  onChange={e => setEventForm(f => ({ ...f, alud_url: e.target.value }))}
                  style={INPUT_STYLE} />
              </div>
            </div>
            {eventCreateError && (
              <div style={{ fontSize: 12, color: "#d4645a", marginTop: 10, textAlign: "center" }}>{eventCreateError}</div>
            )}
            <div style={{ display: "flex", gap: 10, marginTop: 20 }}>
              <button onClick={closeEventModal} disabled={eventCreating} style={{
                flex: 1, padding: "10px 0", background: "transparent",
                border: "0.5px solid rgba(255,255,255,0.12)", borderRadius: 8,
                color: "var(--muted)", fontSize: 13, cursor: "pointer",
                fontFamily: "'DM Sans', sans-serif",
              }}>Cancelar</button>
              <button onClick={submitCreateEvent} disabled={eventCreating} style={{
                flex: 1, padding: "10px 0",
                background: "var(--accent)", border: "none", borderRadius: 8,
                color: "#0e0f11", fontSize: 13, fontWeight: 600,
                cursor: eventCreating ? "not-allowed" : "pointer",
                fontFamily: "'DM Sans', sans-serif", opacity: eventCreating ? 0.6 : 1,
                transition: "all 0.2s",
              }}>{eventCreating ? (editingEventId ? "Guardando..." : "Creando...") : (editingEventId ? "Guardar" : "Crear")}</button>
            </div>
          </div>
        </>
      )}

      {/* ── ESCRIBIR IDEA ── */}
      {showTextIdea && (
        <>
          <div onClick={() => !textIdeaSubmitting && setShowTextIdea(false)} style={{
            position: "fixed", inset: 0,
            background: "rgba(0,0,0,0.6)", backdropFilter: "blur(6px)",
            zIndex: 200, animation: "fadeInOverlay 0.2s ease",
          }} />
          <div style={{
            position: "fixed", top: "50%", left: "50%",
            transform: "translate(-50%, -50%)",
            background: "#161719", border: "0.5px solid rgba(255,255,255,0.1)",
            borderRadius: 16, padding: "28px 32px", zIndex: 201,
            width: "min(420px, 90vw)", boxShadow: "0 24px 80px rgba(0,0,0,0.6)",
            animation: "fadeInOverlay 0.2s ease",
          }}>
            <div style={{ fontFamily: "'DM Mono', monospace", fontSize: 15, color: "var(--text)", marginBottom: 18, textAlign: "center" }}>
              Nueva idea por escrito
            </div>
            <textarea
              placeholder="Escribe tu idea..."
              value={textIdeaInput}
              onChange={e => setTextIdeaInput(e.target.value)}
              autoFocus
              rows={5}
              style={{ ...INPUT_STYLE, fontSize: 14, padding: "11px 12px", resize: "vertical", fontFamily: "'DM Sans', sans-serif" }}
            />
            {textIdeaError && (
              <div style={{ fontSize: 12, color: "#d4645a", marginTop: 10, textAlign: "center" }}>{textIdeaError}</div>
            )}
            <div style={{ display: "flex", gap: 10, marginTop: 20 }}>
              <button onClick={() => setShowTextIdea(false)} disabled={textIdeaSubmitting} style={{
                flex: 1, padding: "10px 0", background: "transparent",
                border: "0.5px solid rgba(255,255,255,0.12)", borderRadius: 8,
                color: "var(--muted)", fontSize: 13, cursor: "pointer",
                fontFamily: "'DM Sans', sans-serif",
              }}>Cancelar</button>
              <button onClick={submitTextIdea} disabled={textIdeaSubmitting} style={{
                flex: 1, padding: "10px 0",
                background: "var(--accent)", border: "none", borderRadius: 8,
                color: "#0e0f11", fontSize: 13, fontWeight: 600,
                cursor: textIdeaSubmitting ? "not-allowed" : "pointer",
                fontFamily: "'DM Sans', sans-serif", opacity: textIdeaSubmitting ? 0.6 : 1,
                transition: "all 0.2s",
              }}>{textIdeaSubmitting ? "Guardando..." : "Guardar"}</button>
            </div>
          </div>
        </>
      )}

      {/* ── AJUSTES ── */}
      {healthModalOpen && (() => {
        const conclusions = conclusionesSalud;
        const overall     = veredictoSalud;
        const dot = { good: "var(--green)", warn: "var(--accent)", bad: "#d4645a", info: "var(--muted)" };
        // Agrupar las conclusiones por dominio para leerlas por bloques.
        const byDomain = {};
        for (const c of conclusions) (byDomain[c.domain] ||= []).push(c);
        return (
          <>
            <div onClick={() => setHealthModalOpen(false)} style={{
              position: "fixed", inset: 0, background: "rgba(0,0,0,0.6)", backdropFilter: "blur(6px)", zIndex: 200,
            }} />
            <div style={{
              position: "fixed", top: "50%", left: "50%", transform: "translate(-50%, -50%)",
              background: "#161719", border: "0.5px solid rgba(255,255,255,0.1)",
              borderRadius: 16, padding: "24px 26px", zIndex: 201,
              width: "min(560px, 94vw)", boxShadow: "0 24px 80px rgba(0,0,0,0.6)",
              maxHeight: "90vh", overflowY: "auto",
            }}>
              <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", marginBottom: 18 }}>
                <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
                  <span style={{ width: 10, height: 10, borderRadius: "50%", background: dot[overall.tone] }} />
                  <div>
                    <div style={{ fontFamily: "'DM Mono', monospace", fontSize: 15, color: "var(--text)", letterSpacing: "0.04em" }}>Análisis de salud</div>
                    <div style={{ fontSize: 12, color: dot[overall.tone] }}>{overall.label}</div>
                  </div>
                </div>
                <button onClick={() => setHealthModalOpen(false)} style={{
                  background: "transparent", border: "0.5px solid var(--border2)", borderRadius: 8,
                  color: "var(--muted)", fontSize: 18, lineHeight: 1, cursor: "pointer", padding: "4px 10px",
                }}>×</button>
              </div>

              {conclusions.length === 0 ? (
                <div style={{ color: "var(--muted)", fontSize: 13, padding: "20px 0" }}>
                  Aún no hay datos de salud suficientes para sacar conclusiones. En cuanto el Apple Watch sincronice unos días, esto se irá llenando.
                </div>
              ) : (
                <>
                  {/* ── Conclusiones por dominio ── */}
                  <div style={{ display: "flex", flexDirection: "column", gap: 16, marginBottom: 22 }}>
                    {Object.entries(byDomain).map(([domain, items]) => (
                      <div key={domain}>
                        <div style={{ fontFamily: "'DM Mono', monospace", fontSize: 11, color: "var(--muted2)", letterSpacing: "0.1em", textTransform: "uppercase", marginBottom: 8 }}>{domain}</div>
                        <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
                          {items.map((c, i) => (
                            <div key={i} style={{ display: "flex", gap: 10, alignItems: "flex-start" }}>
                              <span style={{ width: 7, height: 7, borderRadius: "50%", background: dot[c.tone], marginTop: 6, flexShrink: 0 }} />
                              <span style={{ fontSize: 13.5, color: "var(--text)", lineHeight: 1.5 }}>{c.text}</span>
                            </div>
                          ))}
                        </div>
                      </div>
                    ))}
                  </div>

                  {/* ── Patrones sobre el histórico largo ── */}
                  {/* Se separan de las conclusiones de arriba a propósito: aquellas
                      miran los últimos 30 días, estas hasta un año. Al llevar la
                      ventana y la muestra escritas, se ve de un vistazo cuánto
                      respaldo tiene cada patrón. */}
                  <div style={{ borderTop: "0.5px solid var(--border)", paddingTop: 18, marginBottom: 22 }}>
                    <div style={{ display: "flex", alignItems: "baseline", justifyContent: "space-between", marginBottom: 12, gap: 10 }}>
                      <div style={{ fontFamily: "'DM Mono', monospace", fontSize: 11, color: "var(--muted2)", letterSpacing: "0.1em", textTransform: "uppercase" }}>Patrones a largo plazo</div>
                      {diasPatrones > 0 && (
                        <div style={{ fontFamily: "'DM Mono', monospace", fontSize: 10.5, color: "var(--muted2)" }}>
                          {diasPatrones} días de datos
                        </div>
                      )}
                    </div>
                    {!healthLargo && !healthLargoFallo ? (
                      <div style={{ color: "var(--muted)", fontSize: 13 }}>Analizando el histórico…</div>
                    ) : healthLargoFallo ? (
                      <div style={{ color: "var(--muted)", fontSize: 13 }}>No se pudo cargar el histórico largo.</div>
                    ) : patronesLargos.length === 0 ? (
                      <div style={{ color: "var(--muted)", fontSize: 13, lineHeight: 1.5 }}>
                        Todavía no hay un patrón que aguante con el histórico entero. Hacen falta
                        al menos {HEALTH_MIN_MUESTRA_PATRONES} días en cada lado de la comparación
                        para que no sea casualidad.
                      </div>
                    ) : (
                      <div style={{ display: "flex", flexDirection: "column", gap: 10 }}>
                        {patronesLargos.map(p => (
                          <div key={p.id} style={{ display: "flex", gap: 10, alignItems: "flex-start" }}>
                            <span style={{ width: 7, height: 7, borderRadius: "50%", background: dot[p.tone], marginTop: 6, flexShrink: 0 }} />
                            <span style={{ fontSize: 13.5, color: "var(--text)", lineHeight: 1.5 }}>
                              {p.text}{" "}
                              <span style={{ fontFamily: "'DM Mono', monospace", fontSize: 11, color: "var(--muted2)", whiteSpace: "nowrap" }}>
                                n={p.n}
                              </span>
                            </span>
                          </div>
                        ))}
                      </div>
                    )}
                  </div>

                  {/* ── Detalle: reutiliza los widgets de salud existentes ── */}
                  <div style={{ borderTop: "0.5px solid var(--border)", paddingTop: 18 }}>
                    <div style={{ fontFamily: "'DM Mono', monospace", fontSize: 11, color: "var(--muted2)", letterSpacing: "0.1em", textTransform: "uppercase", marginBottom: 14 }}>Detalle</div>
                    <div style={{ display: "flex", flexDirection: "column", gap: 14 }}>
                      {["health_wellness", "health_sleep", "health_hrv", "health_heart", "health_activity", "health_workouts"].map(wid => (
                        <div key={wid}>{renderWidget(wid)}</div>
                      ))}
                    </div>
                  </div>
                </>
              )}
            </div>
          </>
        );
      })()}

      {showSettings && (
        <>
          <div onClick={() => setShowSettings(false)} style={{
            position: "fixed", inset: 0, background: "rgba(0,0,0,0.6)", backdropFilter: "blur(6px)", zIndex: 200,
          }} />
          <div style={{
            position: "fixed", top: "50%", left: "50%", transform: "translate(-50%, -50%)",
            background: "#161719", border: "0.5px solid rgba(255,255,255,0.1)",
            borderRadius: 16, padding: "28px 32px", zIndex: 201,
            width: "min(340px, 90vw)", boxShadow: "0 24px 80px rgba(0,0,0,0.6)",
            maxHeight: "90vh", overflowY: "auto",
          }}>
            <div style={{ marginBottom: 18, paddingBottom: 16, borderBottom: "0.5px solid var(--border)" }}>
              <div style={{ fontSize: 11, color: "var(--muted)", marginBottom: 6 }}>Modo de vista</div>
              <div style={{ display: "flex", gap: 6 }}>
                {[["full", "Completo"], ["simple", "Simple"]].map(([mode, label]) => {
                  const active = mode === "simple" ? simpleMode : !simpleMode;
                  return (
                    <button key={mode} onClick={() => { if (active) return; toggleSimpleMode(); }} style={{
                      flex: 1, padding: "6px 0",
                      background: active ? "rgba(200,169,110,0.15)" : "var(--surface2)",
                      border: `0.5px solid ${active ? "var(--accent)" : "var(--border2)"}`,
                      borderRadius: 6, color: active ? "var(--accent)" : "var(--muted)",
                      fontSize: 12, fontWeight: active ? 600 : 400,
                      cursor: "pointer", fontFamily: "'DM Sans', sans-serif",
                    }}>{label}</button>
                  );
                })}
              </div>
              <div style={{ fontSize: 10, color: "var(--muted2)", marginTop: 6, lineHeight: 1.4 }}>
                Cada modo recuerda sus propios widgets. {simpleMode
                  ? "El modo simple se adapta a la orientación del móvil (vertical / horizontal)."
                  : "Estás editando los del modo completo."}
              </div>
            </div>
            <div style={{ fontFamily: "'DM Mono', monospace", fontSize: 13, color: "var(--text)", marginBottom: 14, letterSpacing: "0.04em" }}>
              Widgets · {simpleMode ? "modo simple" : "modo completo"}
            </div>
            {/* Columnas y distribución solo aplican al grid del modo completo. */}
            {!simpleMode && (
              <div style={{ marginBottom: 14 }}>
                <div style={{ fontSize: 11, color: "var(--muted)", marginBottom: 6 }}>Columnas</div>
                <div style={{ display: "flex", gap: 6 }}>
                  {[2, 3].map(n => (
                    <button key={n} onClick={() => changeNumColumns(n)} style={{
                      flex: 1, padding: "6px 0",
                      background: numColumns === n ? "rgba(200,169,110,0.15)" : "var(--surface2)",
                      border: `0.5px solid ${numColumns === n ? "var(--accent)" : "var(--border2)"}`,
                      borderRadius: 6, color: numColumns === n ? "var(--accent)" : "var(--muted)",
                      fontSize: 12, fontWeight: numColumns === n ? 600 : 400,
                      cursor: "pointer", fontFamily: "'DM Sans', sans-serif",
                    }}>{n}</button>
                  ))}
                </div>
              </div>
            )}
            {!simpleMode && (
              <button onClick={() => { setShowSettings(false); setIsEditMode(true); }} style={{
                width: "100%", marginBottom: 14, padding: "9px 0",
                background: "rgba(200,169,110,0.1)", border: "0.5px solid rgba(200,169,110,0.35)",
                borderRadius: 8, color: "var(--accent)", fontSize: 12, cursor: "pointer",
                fontFamily: "'DM Sans', sans-serif", letterSpacing: "0.03em",
              }}>Editar distribución →</button>
            )}
            <div style={{ display: "flex", flexDirection: "column", gap: 5 }}>
              {(simpleMode ? simpleWidgetConfig : widgetConfig).map((w, i, arr) => (
                <div key={w.id} style={{
                  display: "flex", alignItems: "center", gap: 10,
                  padding: "8px 10px", borderRadius: 8,
                  background: "rgba(255,255,255,0.03)", border: "0.5px solid rgba(255,255,255,0.06)",
                }}>
                  <button onClick={() => toggleWidget(w.id)} style={{
                    width: 16, height: 16, borderRadius: 4,
                    border: `0.5px solid ${w.visible ? "var(--accent)" : "rgba(255,255,255,0.2)"}`,
                    background: w.visible ? "var(--accent)" : "transparent",
                    cursor: "pointer", flexShrink: 0, padding: 0,
                  }} />
                  <span style={{ flex: 1, fontSize: 13, color: w.visible ? "var(--text)" : "var(--muted)", fontFamily: "'DM Sans', sans-serif" }}>{w.label}</span>
                  <div style={{ display: "flex", gap: 0 }}>
                    <button onClick={() => moveWidget(w.id, -1)} disabled={i === 0} style={{
                      background: "transparent", border: "none",
                      color: i === 0 ? "rgba(255,255,255,0.15)" : "var(--muted)",
                      cursor: i === 0 ? "default" : "pointer", fontSize: 13, padding: "2px 6px",
                    }}>↑</button>
                    <button onClick={() => moveWidget(w.id, 1)} disabled={i === arr.length - 1} style={{
                      background: "transparent", border: "none",
                      color: i === arr.length - 1 ? "rgba(255,255,255,0.15)" : "var(--muted)",
                      cursor: i === arr.length - 1 ? "default" : "pointer", fontSize: 13, padding: "2px 6px",
                    }}>↓</button>
                  </div>
                </div>
              ))}
            </div>
            {/* ── Sección entrenamiento ── */}
            <div style={{ borderTop: "0.5px solid var(--border)", marginTop: 16, paddingTop: 16 }}>
              <div style={{ fontFamily: "'DM Mono', monospace", fontSize: 11, color: "var(--muted2)", letterSpacing: "0.1em", textTransform: "uppercase", marginBottom: 12 }}>Entrenamiento</div>

              <div style={{ marginBottom: 12 }}>
                <div style={{ fontSize: 11, color: "var(--muted)", marginBottom: 6 }}>Días de entrenamiento</div>
                <div style={{ display: "flex", gap: 4 }}>
                  {[["L",1],["M",2],["X",3],["J",4],["V",5],["S",6],["D",0]].map(([label, d]) => {
                    const active = trainingDays.includes(d);
                    return (
                      <button key={d} onClick={() => {
                        const next = active ? trainingDays.filter(x => x !== d) : [...trainingDays, d];
                        setTrainingDays(next);
                        localStorage.setItem("la_training_days", JSON.stringify(next));
                      }} style={{
                        width: 30, height: 30, borderRadius: 6, border: "0.5px solid",
                        borderColor: active ? "var(--accent)" : "var(--border2)",
                        background: active ? "rgba(200,169,110,0.15)" : "var(--surface2)",
                        color: active ? "var(--accent)" : "var(--muted)",
                        fontSize: 11, fontWeight: active ? 600 : 400,
                        cursor: "pointer", fontFamily: "'DM Sans', sans-serif",
                      }}>{label}</button>
                    );
                  })}
                </div>
              </div>

              <div style={{ display: "flex", gap: 8, marginBottom: 10 }}>
                <div style={{ flex: 1 }}>
                  <div style={{ fontSize: 11, color: "var(--muted)", marginBottom: 4 }}>€ / hora</div>
                  <input type="number" min="0" step="0.5" value={trainingSettingsPrice}
                    onChange={e => setTrainingSettingsPrice(e.target.value)}
                    style={{ width: "100%", padding: "6px 8px", background: "var(--surface2)", border: "0.5px solid var(--border2)", borderRadius: 6, color: "var(--text)", fontSize: 12, fontFamily: "'DM Sans', sans-serif" }} />
                </div>
                <div style={{ flex: 1 }}>
                  <div style={{ fontSize: 11, color: "var(--muted)", marginBottom: 4 }}>Sesiones / cobro</div>
                  <input type="number" min="1" step="1" value={trainingSettingsSpp}
                    onChange={e => setTrainingSettingsSpp(e.target.value)}
                    style={{ width: "100%", padding: "6px 8px", background: "var(--surface2)", border: "0.5px solid var(--border2)", borderRadius: 6, color: "var(--text)", fontSize: 12, fontFamily: "'DM Sans', sans-serif" }} />
                </div>
                <div style={{ display: "flex", alignItems: "flex-end" }}>
                  <button disabled={trainingSettingsSaving} onClick={() => updateTrainingClient({
                    price_per_hour: parseFloat(trainingSettingsPrice),
                    sessions_per_payment: parseInt(trainingSettingsSpp),
                  })} style={{ padding: "6px 12px", background: "var(--accent)", border: "none", borderRadius: 6, color: "#0e0f11", fontSize: 12, fontWeight: 600, cursor: "pointer", fontFamily: "'DM Sans', sans-serif" }}>
                    Guardar
                  </button>
                </div>
              </div>

              <div style={{ fontSize: 11, color: "var(--muted)", marginBottom: 6 }}>Sesiones recientes</div>
              {(!training?.all_recent_sessions || training.all_recent_sessions.length === 0) ? (
                <div style={{ fontSize: 12, color: "var(--muted2)" }}>Sin sesiones</div>
              ) : training.all_recent_sessions.map((s, i, arr) => (
                <div key={s.id} style={{ display: "flex", alignItems: "center", justifyContent: "space-between", padding: "5px 0", borderBottom: i < arr.length - 1 ? "0.5px solid var(--border)" : "none" }}>
                  <div>
                    <span style={{ fontFamily: "'DM Mono', monospace", fontSize: 12, color: "var(--text)" }}>{formatShortDate(s.date)}</span>
                    <span style={{ fontSize: 11, color: "var(--muted)", marginLeft: 8 }}>{s.duration_hours}h</span>
                  </div>
                  <button onClick={() => deleteTrainingSession(s.id)} style={{
                    background: "transparent", border: "none", color: "var(--muted2)", fontSize: 12,
                    cursor: "pointer", padding: "2px 6px", lineHeight: 1,
                  }}>✕</button>
                </div>
              ))}
            </div>

            {/* ── Sección composición corporal ── */}
            <div style={{ borderTop: "0.5px solid var(--border)", marginTop: 16, paddingTop: 16 }}>
              <div style={{ fontFamily: "'DM Mono', monospace", fontSize: 11, color: "var(--muted2)", letterSpacing: "0.1em", textTransform: "uppercase", marginBottom: 12 }}>Composición corporal</div>
              <div style={{ display: "flex", gap: 8, marginBottom: 10 }}>
                <div style={{ flex: 1 }}>
                  <div style={{ fontSize: 11, color: "var(--muted)", marginBottom: 4 }}>Objetivo peso (kg)</div>
                  <input type="number" min="40" max="150" step="0.1" value={bodyGoalWeight}
                    onChange={e => setBodyGoalWeight(e.target.value)}
                    style={{ width: "100%", padding: "6px 8px", background: "var(--surface2)", border: "0.5px solid var(--border2)", borderRadius: 6, color: "var(--text)", fontSize: 12, fontFamily: "'DM Sans', sans-serif" }} />
                </div>
                <div style={{ flex: 1 }}>
                  <div style={{ fontSize: 11, color: "var(--muted)", marginBottom: 4 }}>Objetivo % grasa</div>
                  <input type="number" min="3" max="40" step="0.1" value={bodyGoalFat} placeholder="—"
                    onChange={e => setBodyGoalFat(e.target.value)}
                    style={{ width: "100%", padding: "6px 8px", background: "var(--surface2)", border: "0.5px solid var(--border2)", borderRadius: 6, color: "var(--text)", fontSize: 12, fontFamily: "'DM Sans', sans-serif" }} />
                </div>
                <div style={{ display: "flex", alignItems: "flex-end" }}>
                  <button onClick={() => {
                    const goals = { targetWeight: parseFloat(bodyGoalWeight) || 67, targetBodyFat: bodyGoalFat !== "" ? parseFloat(bodyGoalFat) : null };
                    setBodyGoals(goals);
                    localStorage.setItem("la_body_goals", JSON.stringify(goals));
                  }} style={{ padding: "6px 12px", background: "var(--accent)", border: "none", borderRadius: 6, color: "#0e0f11", fontSize: 12, fontWeight: 600, cursor: "pointer", fontFamily: "'DM Sans', sans-serif" }}>
                    Guardar
                  </button>
                </div>
              </div>
              <div style={{ fontSize: 11, color: "var(--muted2)", lineHeight: 1.5 }}>Fase de definición: el dashboard prioriza bajar % grasa conservando masa magra.</div>
            </div>

            {/* ── Cambio de dispositivo de salud ── */}
            <div style={{ borderTop: "0.5px solid var(--border)", marginTop: 16, paddingTop: 16 }}>
              <div style={{ fontFamily: "'DM Mono', monospace", fontSize: 11, color: "var(--muted2)", letterSpacing: "0.1em", textTransform: "uppercase", marginBottom: 12 }}>Dispositivo de salud</div>
              {corteDispositivo ? (
                <div style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 8 }}>
                  <div style={{ fontSize: 12, color: "var(--text)" }}>
                    Datos del aparato actual desde <strong>{isoToDdMmYyyy(corteDispositivo)}</strong>
                    {healthAjustes?.dispositivo ? ` · ${healthAjustes.dispositivo}` : ""}
                  </div>
                  <button onClick={() => guardarCambioDispositivo({ cambio_dispositivo: null, dispositivo: null })}
                    disabled={dispositivoGuardando}
                    style={{ marginLeft: "auto", padding: "4px 10px", background: "var(--surface2)", border: "0.5px solid var(--border2)", borderRadius: 6, color: "var(--muted)", fontSize: 11, cursor: "pointer", fontFamily: "'DM Sans', sans-serif" }}>
                    Quitar
                  </button>
                </div>
              ) : (
                <div style={{ display: "flex", gap: 8, marginBottom: 8 }}>
                  <div style={{ flex: 1 }}>
                    <div style={{ fontSize: 11, color: "var(--muted)", marginBottom: 4 }}>Fecha del cambio</div>
                    <input type="date" value={dispositivoFecha} max={new Date().toISOString().slice(0, 10)}
                      onChange={e => setDispositivoFecha(e.target.value)}
                      style={{ width: "100%", padding: "6px 8px", background: "var(--surface2)", border: "0.5px solid var(--border2)", borderRadius: 6, color: "var(--text)", fontSize: 12, fontFamily: "'DM Sans', sans-serif" }} />
                  </div>
                  <div style={{ flex: 1 }}>
                    <div style={{ fontSize: 11, color: "var(--muted)", marginBottom: 4 }}>Aparato</div>
                    <input type="text" value={dispositivoNombre} maxLength={64} placeholder="Amazfit Helio Strap"
                      onChange={e => setDispositivoNombre(e.target.value)}
                      style={{ width: "100%", padding: "6px 8px", background: "var(--surface2)", border: "0.5px solid var(--border2)", borderRadius: 6, color: "var(--text)", fontSize: 12, fontFamily: "'DM Sans', sans-serif" }} />
                  </div>
                  <div style={{ display: "flex", alignItems: "flex-end" }}>
                    <button onClick={() => guardarCambioDispositivo({ cambio_dispositivo: dispositivoFecha, dispositivo: dispositivoNombre })}
                      disabled={dispositivoGuardando || !dispositivoFecha}
                      style={{ padding: "6px 12px", background: dispositivoFecha ? "var(--accent)" : "var(--surface2)", border: "none", borderRadius: 6, color: dispositivoFecha ? "#0e0f11" : "var(--muted2)", fontSize: 12, fontWeight: 600, cursor: dispositivoFecha ? "pointer" : "default", fontFamily: "'DM Sans', sans-serif" }}>
                      Guardar
                    </button>
                  </div>
                </div>
              )}
              <div style={{ fontSize: 11, color: "var(--muted2)", lineHeight: 1.5 }}>
                Las puntuaciones comparan cada día contra tu propia historia (HRV, respiración, FC en reposo).
                Marcar el cambio evita que la referencia se haga con datos del aparato anterior, que mide distinto.
                El histórico no se borra: sigue en las gráficas, solo deja de servir de referencia.
              </div>
            </div>

            {/* ── Notificaciones ── */}
            <div style={{ borderTop: "0.5px solid var(--border)", marginTop: 16, paddingTop: 16 }}>
              <div style={{ fontFamily: "'DM Mono', monospace", fontSize: 11, color: "var(--muted2)", letterSpacing: "0.1em", textTransform: "uppercase", marginBottom: 12 }}>Notificaciones</div>
              <div style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 6 }}>
                <button onClick={() => {
                  if (Notification.permission === "default") {
                    Notification.requestPermission().then(perm => {
                      if (perm === "granted") {
                        localStorage.setItem("la_notifications", "true");
                        setNotificationsEnabled(true);
                      } else {
                        localStorage.setItem("la_notifications", "false");
                        setNotificationsEnabled(false);
                      }
                    });
                  } else if (Notification.permission === "granted") {
                    localStorage.setItem("la_notifications", "false");
                    setNotificationsEnabled(false);
                  }
                }} style={{
                  padding: "6px 12px",
                  background: notificationsEnabled ? "rgba(200,169,110,0.15)" : "var(--surface2)",
                  border: `0.5px solid ${notificationsEnabled ? "var(--accent)" : "var(--border2)"}`,
                  borderRadius: 6,
                  color: notificationsEnabled ? "var(--accent)" : "var(--muted)",
                  fontSize: 12, cursor: "pointer", fontFamily: "'DM Sans', sans-serif",
                }}>
                  {notificationsEnabled ? "Activadas" : "Desactivadas"}
                </button>
                <span style={{ fontSize: 11, color: "var(--muted)" }}>
                  {Notification.permission === "granted" ? "Evento en 15 min, job completado" : Notification.permission === "denied" ? "Permisos denegados" : "Pulsa para solicitar permiso"}
                </span>
              </div>
            </div>

            {/* ── Resumen diario ── */}
            <div style={{ borderTop: "0.5px solid var(--border)", marginTop: 16, paddingTop: 16 }}>
              <div style={{ fontFamily: "'DM Mono', monospace", fontSize: 11, color: "var(--muted2)", letterSpacing: "0.1em", textTransform: "uppercase", marginBottom: 12 }}>Resumen diario</div>
              <div style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 10 }}>
                <button
                  onClick={() => guardarBriefAjustes({ activo: !briefCfg?.activo })}
                  disabled={!briefCfg || briefGuardando}
                  style={{
                    padding: "6px 12px",
                    background: briefCfg?.activo ? "rgba(200,169,110,0.15)" : "var(--surface2)",
                    border: `0.5px solid ${briefCfg?.activo ? "var(--accent)" : "var(--border2)"}`,
                    borderRadius: 6,
                    color: briefCfg?.activo ? "var(--accent)" : "var(--muted)",
                    fontSize: 12, cursor: !briefCfg || briefGuardando ? "default" : "pointer",
                    fontFamily: "'DM Sans', sans-serif",
                  }}>
                  {!briefCfg ? "Comprobando…" : briefCfg.activo ? "Activado" : "Desactivado"}
                </button>
                <span style={{ fontSize: 11, color: "var(--muted)" }}>
                  {!briefCfg ? "abre y actualiza el estado del sistema"
                    : briefCfg.activo ? "El correo con los datos del día sale al despertarte"
                    : "No saldrá ningún correo hasta que lo vuelvas a activar"}
                </span>
              </div>
              {/* La pausa se agota sola: es lo que separa "me voy una semana" de
                  "no lo quiero más", y evita tener que acordarse de reactivarlo. */}
              <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
                <span style={{ fontSize: 12, color: "var(--muted)", whiteSpace: "nowrap" }}>Pausar hasta</span>
                <div style={{ width: 130 }}>
                  <DateInput
                    value={briefCfg?.pausado_hasta || ""}
                    onChange={iso => guardarBriefAjustes({ pausado_hasta: iso })}
                  />
                </div>
                {briefCfg?.pausado && (
                  <button onClick={() => guardarBriefAjustes({ pausado_hasta: null })} disabled={briefGuardando} style={{
                    background: "transparent", border: "none", padding: 0,
                    cursor: briefGuardando ? "default" : "pointer",
                    color: "var(--accent)", fontSize: 11, fontFamily: "'DM Sans', sans-serif",
                  }}>Quitar pausa</button>
                )}
              </div>
              <div style={{ fontSize: 11, color: "var(--muted2)", marginTop: 6 }}>
                Último día sin resumen, incluido. Después vuelve solo.
              </div>
            </div>

            {/* ── Estado del sistema ── */}
            <div style={{ borderTop: "0.5px solid var(--border)", marginTop: 16, paddingTop: 16 }}>
              <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", marginBottom: 12 }}>
                <div style={{ fontFamily: "'DM Mono', monospace", fontSize: 11, color: "var(--muted2)", letterSpacing: "0.1em", textTransform: "uppercase" }}>Estado del sistema</div>
                <button onClick={cargarEstadoSistema} disabled={sysLoading} style={{
                  background: "transparent", border: "0.5px solid var(--border2)", borderRadius: 6,
                  color: "var(--muted)", fontSize: 11, cursor: sysLoading ? "default" : "pointer",
                  padding: "3px 8px", fontFamily: "'DM Sans', sans-serif",
                }}>{sysLoading ? "Comprobando…" : "Actualizar"}</button>
              </div>
              {(() => {
                // tono: green | accent | red | muted. El texto dice siempre qué pasa,
                // para no depender solo del color.
                const filas = [];

                const b = sysStatus?.backend;
                filas.push({
                  nombre: "Backend",
                  tono: !sysStatus ? "muted" : b?.ok ? (b.ms > 3000 ? "accent" : "green") : "red",
                  detalle: !sysStatus ? "sin comprobar"
                    : !b?.ok ? "no responde"
                    : b.ms > 3000 ? `despierto tras ${(b.ms / 1000).toFixed(1)}s (arranque en frío)`
                    : `despierto · ${b.ms} ms`,
                });

                filas.push({
                  nombre: "Outlook",
                  tono: authNeeded ? "red" : allEvents.length ? "green" : "accent",
                  detalle: authNeeded ? "sesión caducada — vuelve a conectar"
                    : `${allEvents.length} eventos cargados`,
                });

                const minutos = healthLastSync ? Math.floor((Date.now() - new Date(healthLastSync)) / 60000) : null;
                filas.push({
                  nombre: "Salud (Watch)",
                  tono: minutos == null ? "muted" : minutos < 120 ? "green" : minutos < 1440 ? "accent" : "red",
                  detalle: minutos == null ? "sin datos aún"
                    : minutos < 2 ? "sincronizado ahora mismo"
                    : minutos < 60 ? `última sync hace ${minutos} min`
                    : minutos < 1440 ? `última sync hace ${Math.floor(minutos / 60)} h`
                    : `última sync hace ${Math.floor(minutos / 1440)} días`,
                });

                // La fila de arriba responde "¿llegan datos?", que es la pregunta del
                // sistema. Esta responde "¿se pudieron medir?", que es la del usuario:
                // sin ella, un mes de HRV plano por tener el reloj en un cajón parece
                // una avería, que es justo como se leyó en su día.
                if (healthReloj) {
                  const cob   = relojCobertura(healthReloj, { dias: 7 });
                  const racha = relojRachaSinReloj(healthReloj);
                  const medibles = cob.dias - cob.sinDatos;
                  filas.push({
                    nombre: "Uso del reloj",
                    tono: !medibles ? "muted" : racha >= 2 ? "red" : cob.noche < medibles ? "accent" : "green",
                    detalle: !medibles ? "sin datos de los que deducirlo"
                      : racha >= 2 ? `${racha} días seguidos sin ponértelo`
                      : `${cob.noche}/${medibles} noches y ${cob.dia}/${medibles} días esta semana`
                        + (cob.sinDatos ? ` · ${cob.sinDatos} día(s) sin datos` : ""),
                  });
                }

                const ag = sysStatus?.agente;
                filas.push({
                  nombre: "Agente PC",
                  tono: !sysStatus ? "muted" : !ag ? "muted" : ag.offline === false ? "green" : "muted",
                  detalle: !sysStatus ? "sin comprobar"
                    : !ag ? "sin respuesta"
                    : ag.exists === false ? "nunca se ha registrado"
                    : ag.offline === false ? `online${ag.hostname ? ` · ${ag.hostname}` : ""}`
                    : `apagado (visto hace ${Math.floor((ag.silence_seconds ?? 0) / 60)} min)`,
                });

                // Presencia (la empuja HA desde el device_tracker del móvil). Un dato
                // caducado se muestra igual pero en gris y diciendo de cuándo es: no
                // saber dónde estás y creer que sigues donde estabas hace seis horas
                // son cosas distintas, y esta fila tiene que dejar claro cuál es.
                const pre = sysStatus?.presencia;
                filas.push({
                  nombre: "Presencia",
                  tono: !sysStatus ? "muted" : !pre?.conocida ? "muted" : pre.vigente ? "green" : "accent",
                  detalle: !sysStatus ? "sin comprobar"
                    // Sin respuesta ≠ sin datos: el backend puede no tener todavía el
                    // endpoint (se despliega a mano, el frontend no) y decir "HA no ha
                    // reportado nunca" mandaría a revisar HA, que no es el problema.
                    : !pre ? "sin respuesta del backend"
                    : !pre.conocida ? "HA no ha reportado nunca"
                    : `${pre.en_casa ? "en casa" : pre.zona || "fuera"} · ${
                        pre.hace_minutos == null ? "sin fecha"
                        : pre.hace_minutos < 2 ? "ahora mismo"
                        : pre.hace_minutos < 60 ? `hace ${pre.hace_minutos} min`
                        : `hace ${Math.floor(pre.hace_minutos / 60)} h`
                      }${pre.vigente ? "" : " (caducado)"}`,
                });

                filas.push({
                  nombre: "Entrenamiento",
                  tono: training?.client ? "green" : "muted",
                  detalle: training?.client
                    ? `${training.sessions_since_payment}/${training.sessions_per_payment} sesiones · ${training.amount_owed}€`
                    : "sin cliente configurado",
                });

                // El resumen diario. Apagado a propósito y roto se parecen mucho desde
                // fuera —en los dos casos el correo no llega—, así que esta fila tiene
                // que decir cuál de los dos es, y si el de hoy ya salió.
                filas.push({
                  nombre: "Resumen diario",
                  tono: !briefCfg ? "muted" : !briefCfg.activo ? "muted" : briefCfg.pausado ? "accent" : "green",
                  detalle: !briefCfg ? "sin comprobar"
                    : !briefCfg.activo ? "desactivado"
                    : briefCfg.pausado ? `pausado hasta el ${isoToDdMmYyyy(briefCfg.pausado_hasta)}`
                    : briefCfg.enviado_hoy === true ? "activo · el de hoy ya ha salido"
                    : briefCfg.enviado_hoy === false ? "activo · hoy aún no ha salido"
                    : "activo",
                });

                // Por dónde salen los avisos. Que el correo funcione y que el aviso
                // llegue A TIEMPO no son la misma pregunta: un "ponte el reloj" de las
                // 21:30 leído al abrir el buzón mañana ya no sirve de nada. Y el canal
                // del móvil se cae en silencio (basta con que HA deje de sondear), así
                // que tiene que verse desde aquí.
                const av = sysStatus?.avisos;
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

                // El registro del backend (app_logs). Las demás filas dicen si algo
                // RESPONDE; esta dice si algo ha FALLADO — que es distinto, y es lo que
                // faltaba: el 409 de la ingesta de salud se registró durante días en el
                // stdout de una máquina que escala a cero y nadie llegó a verlo.
                const reg = sysStatus?.registro;
                filas.push({
                  nombre: "Registro",
                  tono: !reg ? "muted" : reg.errores ? "red" : reg.entradas.length ? "accent" : "green",
                  detalle: !reg ? "sin comprobar"
                    : reg.errores ? `${reg.errores} ${reg.errores === 1 ? "error" : "errores"} en 7 días`
                    : reg.entradas.length ? `${reg.entradas.length} avisos en 7 días`
                    : "sin incidencias en 7 días",
                });

                const color = { green: "var(--green)", accent: "var(--accent)", red: "#d4645a", muted: "var(--muted2)" };
                return (
                  <div style={{ display: "flex", flexDirection: "column", gap: 7 }}>
                    {filas.map(f => (
                      <div key={f.nombre} style={{ display: "flex", alignItems: "baseline", gap: 8 }}>
                        <span style={{ width: 7, height: 7, borderRadius: "50%", background: color[f.tono], flexShrink: 0, alignSelf: "center" }} />
                        <span style={{ fontSize: 12, color: "var(--text)", minWidth: 96 }}>{f.nombre}</span>
                        <span style={{ fontSize: 11, color: "var(--muted)", flex: 1, textAlign: "right" }}>{f.detalle}</span>
                      </div>
                    ))}
                    {/* Instalar el YAML de HA y no saber si funciona hasta que toque un
                        aviso de verdad es la forma más rápida de darlo por puesto sin
                        estarlo: esto recorre la cadena entera. */}
                    <div style={{ display: "flex", alignItems: "center", gap: 10, marginTop: 2 }}>
                      <button onClick={probarAviso} disabled={avisoPrueba === "…"} style={{
                        background: "transparent", border: "none", padding: 0,
                        cursor: avisoPrueba === "…" ? "default" : "pointer",
                        color: "var(--accent)", fontSize: 11, fontFamily: "'DM Sans', sans-serif",
                      }}>Probar aviso</button>
                      {!!avisoPrueba && (
                        <span style={{ fontSize: 11, color: "var(--muted)" }}>{avisoPrueba}</span>
                      )}
                    </div>
                    {!!reg?.entradas.length && (
                      <div style={{ marginTop: 4 }}>
                        <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
                          <button onClick={() => setLogsAbiertos(v => !v)} style={{
                            background: "transparent", border: "none", padding: 0, cursor: "pointer",
                            color: "var(--accent)", fontSize: 11, fontFamily: "'DM Sans', sans-serif",
                          }}>{logsAbiertos ? "Ocultar registro" : "Ver registro"}</button>
                          {logsAbiertos && (
                            <button onClick={vaciarRegistro} style={{
                              background: "transparent", border: "none", padding: 0, cursor: "pointer",
                              color: "var(--muted2)", fontSize: 11, fontFamily: "'DM Sans', sans-serif",
                            }}>Vaciar</button>
                          )}
                        </div>
                        {logsAbiertos && (
                          <div style={{ marginTop: 8, maxHeight: 260, overflowY: "auto", display: "flex", flexDirection: "column", gap: 8 }}>
                            {reg.entradas.map((e, i) => (
                              <div key={`${e.created_at}-${i}`} style={{
                                borderLeft: `2px solid ${e.level === "ERROR" || e.level === "CRITICAL" ? "#d4645a" : "var(--accent)"}`,
                                paddingLeft: 8,
                              }}>
                                <div style={{ fontFamily: "'DM Mono', monospace", fontSize: 10, color: "var(--muted2)" }}>
                                  {formatLogTime(e.created_at)} · {e.level}
                                  {e.context?.peticion ? ` · ${e.context.peticion}` : ""}
                                </div>
                                {/* pre-wrap: los logger.exception() traen traza de varias líneas */}
                                <div style={{ fontSize: 11, color: "var(--muted)", whiteSpace: "pre-wrap", wordBreak: "break-word" }}>
                                  {e.message}
                                </div>
                              </div>
                            ))}
                          </div>
                        )}
                      </div>
                    )}
                  </div>
                );
              })()}
            </div>

            {/* ── Datos ── */}
            <div style={{ borderTop: "0.5px solid var(--border)", marginTop: 16, paddingTop: 16 }}>
              <div style={{ fontFamily: "'DM Mono', monospace", fontSize: 11, color: "var(--muted2)", letterSpacing: "0.1em", textTransform: "uppercase", marginBottom: 12 }}>Datos</div>
              <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
                <button onClick={exportData} disabled={exporting} style={{
                  padding: "6px 12px",
                  background: "var(--surface2)", border: "0.5px solid var(--border2)",
                  borderRadius: 6, color: exporting ? "var(--muted2)" : "var(--muted)",
                  fontSize: 12, cursor: exporting ? "default" : "pointer", fontFamily: "'DM Sans', sans-serif",
                }}>
                  {exporting ? "Exportando…" : "Exportar backup"}
                </button>
                <span style={{ fontSize: 11, color: "var(--muted)" }}>Descarga un JSON con todos tus datos</span>
              </div>
            </div>

            {/* ── Logout ── */}
            <div style={{ borderTop: "0.5px solid var(--border)", marginTop: 16, paddingTop: 16 }}>
              <button onClick={() => {
                localStorage.removeItem("la_token");
                window.location.reload();
              }} style={{
                width: "100%", padding: "9px 0",
                background: "rgba(212,100,90,0.1)", border: "0.5px solid rgba(212,100,90,0.3)",
                borderRadius: 8, color: "#d4645a", fontSize: 13, cursor: "pointer",
                fontFamily: "'DM Sans', sans-serif", fontWeight: 500,
              }}>
                Cerrar sesión
              </button>
            </div>

            <button onClick={() => setShowSettings(false)} style={{
              marginTop: 12, width: "100%", padding: "9px 0",
              background: "transparent", border: "0.5px solid rgba(255,255,255,0.12)",
              borderRadius: 8, color: "var(--muted)", fontSize: 13, cursor: "pointer",
              fontFamily: "'DM Sans', sans-serif",
            }}>Cerrar</button>
          </div>
        </>
      )}

      {/* ── PANEL LATERAL DE CLASES ── */}
      {classesOpen && (
        <>
          <div onClick={() => setClassesOpen(false)} style={{
            position: "fixed", inset: 0,
            background: "rgba(0,0,0,0.55)", backdropFilter: "blur(4px)",
            zIndex: 100, animation: "fadeInOverlay 0.25s ease",
          }} />
          <div style={{
            position: "fixed", top: 0, right: 0, bottom: 0,
            width: "min(420px, 92vw)", background: "#161719",
            borderLeft: "0.5px solid rgba(255,255,255,0.08)",
            zIndex: 101, display: "flex", flexDirection: "column",
            animation: "slideInRight 0.3s cubic-bezier(0.22,1,0.36,1)",
            boxShadow: "-20px 0 60px rgba(0,0,0,0.4)",
          }}>
            {/* Header panel */}
            <div style={{
              display: "flex", alignItems: "center", justifyContent: "space-between",
              padding: "24px 24px 16px", borderBottom: "0.5px solid rgba(255,255,255,0.07)",
            }}>
              <div>
                <div style={{ fontFamily: "'DM Mono', monospace", fontSize: 16, color: "var(--accent2)" }}>
                  🎓 Clases de hoy
                </div>
                <div style={{ fontSize: 11, color: "var(--muted)", marginTop: 2 }}>
                  {todayClasses.length} clases
                </div>
              </div>
              <button onClick={() => setClassesOpen(false)} style={{
                background: "none", border: "none", color: "var(--muted)",
                fontSize: 20, cursor: "pointer", padding: "4px 8px", borderRadius: 6, lineHeight: 1,
              }}
                onMouseEnter={e => e.target.style.color = "var(--text)"}
                onMouseLeave={e => e.target.style.color = "var(--muted)"}
              >×</button>
            </div>

            {/* Timeline clases */}
            <div style={{ flex: 1, overflowY: "auto", padding: "20px 24px" }}>
              <div style={{ display: "flex", flexDirection: "column" }}>
                {todayClasses
                  .sort((a, b) => new Date(a.start) - new Date(b.start))
                  .map((ev, i, arr) => {
                    const past   = isPast(ev.end);
                    const active = isActive(ev.start, ev.end);
                    const nodeColor = active ? "var(--accent2)" : past ? "var(--muted2)" : "#8bb4d4";
                    return (
                      <div key={ev.id || i} style={{ display: "flex", gap: 16, position: "relative", paddingBottom: i < arr.length - 1 ? 24 : 0 }}>
                        {i < arr.length - 1 && (
                          <div style={{ position: "absolute", left: 7, top: 18, width: 1, bottom: 0, background: "rgba(139,180,212,0.2)" }} />
                        )}
                        <div style={{ flexShrink: 0, marginTop: 2 }}>
                          <div style={{
                            width: 15, height: 15, borderRadius: "50%", background: nodeColor,
                            boxShadow: active ? "0 0 10px rgba(139,180,212,0.7)" : "none",
                            animation: active ? "nodeGlow 2s infinite" : "none",
                            border: `1.5px solid ${nodeColor}`,
                          }} />
                        </div>
                        <div style={{ flex: 1 }}>
                          <div style={{ display: "flex", alignItems: "baseline", gap: 8, marginBottom: 4 }}>
                            <span style={{ fontFamily: "'DM Mono', monospace", fontSize: 12, color: active ? "var(--accent2)" : "var(--muted)" }}>
                              {formatTime(ev.start)} – {formatTime(ev.end)}
                            </span>
                            {active && (
                              <span style={{ fontSize: 9, background: "rgba(139,180,212,0.15)", color: "var(--accent2)", borderRadius: 4, padding: "1px 6px", letterSpacing: "0.06em", textTransform: "uppercase" }}>
                                En curso
                              </span>
                            )}
                          </div>
                          <div style={{ fontSize: 14, fontWeight: 500, color: past ? "var(--muted)" : "var(--text)", marginBottom: ev.location ? 2 : 0 }}>
                            {ev.title}
                          </div>
                          {ev.location && (
                            <div style={{ fontSize: 11, color: "var(--muted)", marginBottom: 4 }}>📍 {ev.location}</div>
                          )}
                          <DepartureWidget ev={{ ...ev, loc: ev.location }} {...propsSalida} />
                        </div>
                      </div>
                    );
                  })}
              </div>
            </div>
          </div>
        </>
      )}

      {/* Contenedor de guías de alineación (snap guides) */}
      <div id="snap-guides" style={{ position: "fixed", inset: 0, pointerEvents: "none", zIndex: 801 }} />
    </>
  );
}

// ── ESTILOS ───────────────────────────────────────────────────────
const s = {
  dashboard: { display: "flex", flexDirection: "column", minHeight: "100vh", padding: 20, gap: 16, background: "var(--bg)" },
  header: { display: "flex", justifyContent: "space-between", alignItems: "flex-end", paddingBottom: 16, borderBottom: "0.5px solid var(--border)" },
  clock: { fontFamily: "'DM Mono', monospace", fontSize: 56, fontWeight: 400, letterSpacing: -2, color: "var(--text)", lineHeight: 1 },
  date: { fontSize: 15, color: "var(--muted)", marginTop: 4, letterSpacing: "0.05em", textTransform: "uppercase" },
  greeting: { fontSize: 15, color: "var(--muted)", textAlign: "right", fontFamily: "'DM Sans', sans-serif" },
  greetingStrong: { display: "block", fontSize: 19, color: "var(--accent)", fontWeight: 500, marginTop: 2 },
  card: { background: "var(--surface)", border: "0.5px solid var(--border)", borderRadius: 12, padding: "16px 20px", boxSizing: "border-box", width: "100%" },
  sectionLabel: { fontSize: 12, fontWeight: 500, letterSpacing: "0.15em", textTransform: "uppercase", color: "var(--muted2)", marginBottom: 12 },
  timelineWrapper: { overflowX: "auto", paddingBottom: 4 },
  timeline: { display: "flex", alignItems: "flex-start", minWidth: 500, padding: "8px 0 16px", position: "relative" },
  timelineItem: { display: "flex", flexDirection: "column", alignItems: "center", flex: 1, position: "relative", cursor: "pointer" },
  connectorLine: { position: "absolute", top: 9, left: "50%", width: "100%", height: 0.5, background: "var(--node-line)", zIndex: 0 },
  node: { width: 18, height: 18, borderRadius: "50%", border: "1.5px solid var(--accent)", background: "var(--bg)", zIndex: 1, position: "relative", flexShrink: 0, transition: "all 0.2s", cursor: "pointer" },
  nodeActive: { background: "var(--accent)", animation: "nodeGlow 2s infinite" },
  nodePast: { borderColor: "var(--muted2)", background: "var(--muted2)", width: 12, height: 12, margin: "3px 0" },
  nodeFuture: { borderColor: "var(--border2)" },
  nodeLabel: { marginTop: 10, textAlign: "center", maxWidth: 80 },
  nodeTime:  { fontFamily: "'DM Mono', monospace", fontSize: 12, color: "var(--muted)" },
  nodeTitle: { fontSize: 13, color: "var(--text)", marginTop: 2, lineHeight: 1.3 },
  nodeTitleActive: { color: "var(--accent)", fontWeight: 500 },
  eventDetail: { background: "var(--surface2)", border: "0.5px solid var(--border2)", borderLeft: "2px solid var(--accent)", borderRadius: 8, padding: "12px 16px", marginTop: 4, display: "flex", justifyContent: "space-between", alignItems: "center" },
  eventDetailTitle: { fontSize: 17, fontWeight: 500, color: "var(--text)" },
  eventDetailSub:   { fontSize: 14, color: "var(--muted)", marginTop: 3 },
  eventDetailTime:  { fontFamily: "'DM Mono', monospace", fontSize: 24, color: "var(--accent)" },
  eventRow: { display: "flex", alignItems: "center", gap: 12, padding: "10px 12px", borderRadius: 8, border: "0.5px solid var(--border)", background: "var(--surface2)", cursor: "pointer" },
  eventDot: { width: 6, height: 6, borderRadius: "50%", background: "var(--accent2)", flexShrink: 0 },
  eventRowTime:  { fontFamily: "'DM Mono', monospace", fontSize: 13, color: "var(--muted)", minWidth: 88 },
  eventRowTitle: { fontSize: 15, color: "var(--text)", flex: 1 },
  eventRowLoc:   { fontSize: 13, color: "var(--muted)" },
  entregaRow: { display: "flex", alignItems: "center", gap: 12, padding: "12px 14px", borderRadius: 8, border: "0.5px solid var(--border)", background: "var(--surface2)", cursor: "pointer" },
  urgencyBar: { width: 3, height: 36, borderRadius: 2, flexShrink: 0 },
  entregaTitle:    { fontSize: 15, fontWeight: 500, color: "var(--text)" },
  entregaSubject:  { fontSize: 13, color: "var(--muted)", marginTop: 2 },
  entregaCountdown: { textAlign: "right", flexShrink: 0 },
  daysNum:  { fontFamily: "'DM Mono', monospace", fontSize: 24, fontWeight: 400, lineHeight: 1 },
  daysLabel: { fontSize: 12, color: "var(--muted)", display: "block", marginTop: 1 },
  ideaCard: { background: "var(--surface2)", border: "0.5px solid var(--border)", borderRadius: 8, padding: "12px 14px", cursor: "pointer" },
  ideaKey: { fontSize: 15, fontWeight: 500, color: "var(--text)", display: "flex", alignItems: "center", gap: 8, justifyContent: "space-between" },
  ideaTag: { fontSize: 12, color: "var(--muted)", background: "var(--surface)", padding: "2px 8px", borderRadius: 4, letterSpacing: "0.05em", flexShrink: 0 },
  ideaChevron: { fontSize: 12, color: "var(--muted2)", transition: "transform 0.3s", flexShrink: 0 },
  ideaFull: { fontSize: 14, color: "var(--muted)", marginTop: 8, lineHeight: 1.6 },
  newIdeaBtn: { width: "100%", marginTop: 10, padding: 8, background: "transparent", border: "0.5px dashed rgba(255,255,255,0.12)", borderRadius: 8, color: "#5a5850", fontSize: 14, cursor: "pointer", fontFamily: "'DM Sans', sans-serif", transition: "all 0.2s" },
  footer: { display: "flex", justifyContent: "space-between", alignItems: "center", paddingTop: 12, borderTop: "0.5px solid var(--border)", fontSize: 13, color: "var(--muted2)" },
  statusDot: { display: "inline-block", width: 6, height: 6, borderRadius: "50%", background: "var(--green)", marginRight: 6, animation: "pulse 2s infinite", verticalAlign: "middle" },
  appTabActive: { fontFamily: "'DM Mono', monospace", fontSize: 12, padding: "2px 8px", borderRadius: 4, background: "var(--accent)", color: "#0e0f11", letterSpacing: "0.05em", userSelect: "none" },
  appTabInactive: { fontFamily: "'DM Mono', monospace", fontSize: 12, padding: "2px 8px", borderRadius: 4, border: "0.5px solid var(--border2)", color: "var(--muted)", cursor: "pointer", letterSpacing: "0.05em", transition: "color 0.15s, border-color 0.15s" },
};


