import React, { useState, useEffect, useRef } from "react";
import {
  isToday, isFuture, isPast, isActive, daysUntil, formatTime, formatUpcomingTime,
  urgencyColor, formatShortDate, DAYS_ES, MONTHS_ES, isoToDdMmYyyy,
  hoursToHM, sleepScore, calcRecoveryMod, findMetric, weatherFromCode, weekdayShort,
  formatMoney, clothingTotals, CLOTHING_CURRENCIES,
} from "../lib/helpers";

// Configuración de instancia (kit self-hosted): se personaliza con variables VITE_* en Vercel/.env
const API = import.meta.env.VITE_API_URL || "https://backend-tender-glow-160.fly.dev";
const HA_URL = (import.meta.env.VITE_HA_URL || "http://192.168.1.200:8123") +
               (import.meta.env.VITE_HA_DASHBOARD_PATH || "/lovelace/tablet");
// Marcador en el título del evento que lo convierte en "entrega" para el widget de entregas
const ENTREGAS_MARKER = import.meta.env.VITE_ENTREGAS_MARKER || "📚";

async function apiFetch(url, options = {}) {
  const res = await fetch(url, options);
  if (res.status === 401 && localStorage.getItem("la_token")) {
    localStorage.removeItem("la_token");
    window.location.reload();
    await new Promise(resolve => setTimeout(resolve, 1000));
  }
  return res;
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

function Sparkline({ data, color = "var(--accent)", height = 40 }) {
  const pts = data.filter(d => d.value != null);
  if (pts.length < 2) return (
    <div style={{ height, display: "flex", alignItems: "center", justifyContent: "center" }}>
      <span style={{ fontSize: 11, color: "var(--muted2)" }}>—</span>
    </div>
  );
  const vals = pts.map(d => d.value);
  const min = Math.min(...vals), max = Math.max(...vals), range = max - min || 1;
  const W = 200, H = height;
  const points = pts.map((d, i) => {
    const x = (i / (pts.length - 1)) * (W - 4) + 2;
    const y = H - 4 - ((d.value - min) / range) * (H - 8);
    return `${x.toFixed(1)},${y.toFixed(1)}`;
  }).join(" ");
  return (
    <svg viewBox={`0 0 ${W} ${H}`} width="100%" height={height} preserveAspectRatio="none" style={{ display: "block" }}>
      <polyline points={points} fill="none" stroke={color} strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" />
    </svg>
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

const DEFAULT_COLUMNS = {
  timeline:          "left",
  upcoming:          "left",
  entregas:          "right",
  training:          "right",
  ideas:             "right",
  clothing:          "right",
  health_wellness:   "left",
  health_sleep:      "right",
  health_heart:      "right",
  health_hrv:        "right",
  health_activity:   "right",
  health_workouts:   "right",
};

const ALL_DEFAULT_WIDGETS = [
  { id: "timeline",          label: "Hoy",              visible: true,  column: "left"  },
  { id: "weather",           label: "Clima",             visible: true,  column: "left"  },
  { id: "upcoming",          label: "Próximos eventos",  visible: true,  column: "left"  },
  { id: "entregas",          label: "Entregas",          visible: true,  column: "right" },
  { id: "training",          label: "Entrenamiento",     visible: true,  column: "right" },
  { id: "ideas",             label: "Ideas",             visible: true,  column: "right" },
  { id: "clothing",          label: "Conteo ropa",       visible: true,  column: "right" },
  { id: "acciones_pc",       label: "Streaming PC",      visible: true,  column: "right" },
  { id: "health_wellness",   label: "Bienestar semanal", visible: true,  column: "left"  },
  { id: "health_sleep",      label: "Sueño",             visible: true,  column: "right" },
  { id: "health_heart",      label: "Freq. cardíaca",    visible: false, column: "right" },
  { id: "health_hrv",        label: "HRV",               visible: false, column: "right" },
  { id: "health_activity",   label: "Actividad",         visible: false, column: "right" },
  { id: "health_workouts",   label: "Entrenamientos AW", visible: false, column: "right" },
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
      }));
      for (const def of ALL_DEFAULT_WIDGETS) {
        if (!savedIds.has(def.id)) merged.push({ ...def });
      }
      return merged;
    }
  } catch { /* mejor esfuerzo: ignorar */ }
  return ALL_DEFAULT_WIDGETS.map(w => ({ ...w }));
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
  const [activeEvent, setActiveEvent] = useState(null);
  const [openIdea, setOpenIdea]       = useState(null);
  const [allEvents, setAllEvents]     = useState([]);
  const [loading, setLoading]         = useState(true);
  const [slowBoot, setSlowBoot]       = useState(false);
  const [authNeeded, setAuthNeeded]   = useState(false);
  const [ideas, setIdeas]             = useState([]);
  const [recording, setRecording]     = useState(false);
  const [processing, setProcessing]   = useState(false);
  const [showTextIdea, setShowTextIdea]     = useState(false);
  const [textIdeaInput, setTextIdeaInput]   = useState("");
  const [textIdeaSubmitting, setTextIdeaSubmitting] = useState(false);
  const [textIdeaError, setTextIdeaError]   = useState(null);
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
  const [wellnessView, setWellnessView]     = useState("weekly");
  const [scoreTooltip, setScoreTooltip]       = useState(false);
  const [sleepScoreTooltip, setSleepScoreTooltip] = useState(false);
  const [sleepExcluding, setSleepExcluding]       = useState(null); // date string being toggled
  const [bodyGoals, setBodyGoals] = useState(() => {
    try { const s = localStorage.getItem("la_body_goals"); return s ? JSON.parse(s) : { targetWeight: 67, targetBodyFat: null }; }
    catch { return { targetWeight: 67, targetBodyFat: null }; }
  });
  const [bodyGoalWeight, setBodyGoalWeight] = useState(() => {
    try { const s = localStorage.getItem("la_body_goals"); return s ? (JSON.parse(s).targetWeight ?? 67) : 67; }
    catch { return 67; }
  });
  const [bodyGoalFat, setBodyGoalFat] = useState(() => {
    try { const s = localStorage.getItem("la_body_goals"); return s ? (JSON.parse(s).targetBodyFat ?? "") : ""; }
    catch { return ""; }
  });
  const [showSessionForm, setShowSessionForm] = useState(false);
  const [sessionDate, setSessionDate]     = useState(() => new Date().toISOString().slice(0, 10));
  const [sessionHours, setSessionHours]   = useState("1");
  const [trainingLoading, setTrainingLoading] = useState(false);
  const [showSettings, setShowSettings]   = useState(false);
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
  const [numColumns, setNumColumns]       = useState(() => {
    try { const s = localStorage.getItem("la_num_columns"); return s ? parseInt(s, 10) : 2; }
    catch { return 2; }
  });
  const numColumnsRef = useRef((() => {
    try { const s = localStorage.getItem("la_num_columns"); return s ? parseInt(s, 10) : 2; }
    catch { return 2; }
  })());
  const [colSplits, setColSplits]         = useState(() => {
    try {
      const n = parseInt(localStorage.getItem("la_num_columns") || "2", 10);
      const s = localStorage.getItem("la_col_splits");
      if (s) { const p = JSON.parse(s); if (Array.isArray(p) && p.length === n - 1) return p; }
      // migrar clave antigua
      const old = localStorage.getItem("la_column_split");
      if (old && n === 2) return [parseFloat(old)];
      return DEFAULT_SPLITS[n] || [0.65];
    }
    catch { return [0.65]; }
  });
  const colSplitsRef = useRef((() => {
    try {
      const n = parseInt(localStorage.getItem("la_num_columns") || "2", 10);
      const s = localStorage.getItem("la_col_splits");
      if (s) { const p = JSON.parse(s); if (Array.isArray(p) && p.length === n - 1) return p; }
      const old = localStorage.getItem("la_column_split");
      if (old && n === 2) return [parseFloat(old)];
      return DEFAULT_SPLITS[n] || [0.65];
    }
    catch { return [0.65]; }
  })());
  // Dos selecciones de widgets independientes: la del modo completo y la del
  // modo simplificado. El panel de ajustes edita la que corresponde al modo
  // activo, así cada modo recuerda sus propios widgets.
  const [widgetConfig, setWidgetConfig]             = useState(() => loadWidgetConfig("la_widget_config"));
  const [simpleWidgetConfig, setSimpleWidgetConfig] = useState(() => loadWidgetConfig("la_simple_widget_config"));

  const inputStyle = { padding: "9px 12px", background: "var(--surface2)", border: "0.5px solid var(--border2)", borderRadius: 8, color: "var(--text)", fontSize: 13, fontFamily: "'DM Sans', sans-serif", width: "100%" };
  const fieldLabelStyle = { fontSize: 11, letterSpacing: "0.1em", textTransform: "uppercase", color: "var(--muted2)", marginBottom: 6 };

  const mediaRecorderRef = useRef(null);
  const chunksRef        = useRef([]);
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

  // Reloj
  useEffect(() => {
    const id = setInterval(() => setNow(new Date()), 30_000);
    return () => clearInterval(id);
  }, []);

  // Cerrar ajustes con Escape
  useEffect(() => {
    const handler = e => { if (e.key === "Escape") setShowSettings(false); };
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

  // Cargar eventos
  function loadEvents() {
    const t = localStorage.getItem("la_token") || "";
    return apiFetch(`${API}/calendar/events`, { headers: { "Authorization": `Bearer ${t}` } })
      .then(r => r.json())
      .then(data => {
        if (data.error) { setAuthNeeded(true); setLoading(false); return; }
        setAllEvents(data.events || []);
        setLoading(false);
      })
      .catch(() => { setAuthNeeded(true); setLoading(false); });
  }
  useEffect(() => { loadEvents(); }, []);

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
      const t = localStorage.getItem("la_token") || "";
      apiFetch(`${API}/calendar/calendars`, { headers: { "Authorization": `Bearer ${t}` } })
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
    const t = localStorage.getItem("la_token") || "";
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
          headers: { "Authorization": `Bearer ${t}`, "Content-Type": "application/json" },
          body: JSON.stringify(payload),
        });
      } else {
        payload.calendar_id = calendarId || null;
        r = await apiFetch(`${API}/calendar/events`, {
          method: "POST",
          headers: { "Authorization": `Bearer ${t}`, "Content-Type": "application/json" },
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
    const t = localStorage.getItem("la_token") || "";
    if (!t) return;
    apiFetch(`${API}/calendar/classes`, { headers: { "Authorization": `Bearer ${t}` } })
      .then(r => r.json())
      .then(data => {
        if (Array.isArray(data.events)) setClassEvents(data.events);
      })
      .catch(() => { /* mejor esfuerzo: sin clases si falla */ });
  }, []);

  // Cargar resumen entrenamiento
  useEffect(() => { loadTraining(); }, []);

  // Cargar datos de salud
  useEffect(() => {
    const t = localStorage.getItem("la_token") || "";
    if (!t) return;
    apiFetch(`${API}/health/metrics?days=30`, { headers: { "Authorization": `Bearer ${t}` } })
      .then(r => r.json())
      .then(data => { setHealthData(data.metrics || {}); setHealthLastSync(data.last_sync || null); setHealthLoading(false); })
      .catch(() => setHealthLoading(false));
  }, []);

  // Cargar ideas
  useEffect(() => {
    const t = localStorage.getItem("la_token") || "";
    apiFetch(`${API}/ideas`, { headers: { "Authorization": `Bearer ${t}` } })
      .then(r => r.json())
      .then(data => Array.isArray(data) && setIdeas(data))
      .catch(() => {});
  }, []);

  // Cargar conteo de ropa
  useEffect(() => {
    const t = localStorage.getItem("la_token") || "";
    if (!t) return;
    apiFetch(`${API}/clothing`, { headers: { "Authorization": `Bearer ${t}` } })
      .then(r => r.json())
      .then(data => Array.isArray(data) && setClothing(data))
      .catch(() => {});
  }, []);

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
    const t = localStorage.getItem("la_token") || "";
    if (!t || geo === null) return;
    const q = geo ? `?lat=${geo.lat}&lon=${geo.lon}` : "";
    apiFetch(`${API}/weather${q}`, { headers: { "Authorization": `Bearer ${t}` } })
      .then(r => r.ok ? r.json() : null)
      .then(data => { if (data && typeof data.temp === "number") setWeather(data); })
      .catch(() => {});
  }, [geo]);

  // Estado del agente PC (heartbeat)
  useEffect(() => {
    if (!token) return;

    let mounted = true;
    async function loadAgent() {
      try {
        const r = await apiFetch(`${API}/agents/pc-mikel`, { headers: { "Authorization": `Bearer ${token}` } });
        const data = await r.json();
        if (mounted) setAgentState(data);
      } catch {
        if (mounted) setAgentState({ status: "offline", offline: true });
      }
    }

    loadAgent();
    const id = setInterval(loadAgent, 10000);
    return () => { mounted = false; clearInterval(id); };
  }, [token]);

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

  // Notificaciones — eventos próximos (15 min antes)
  useEffect(() => {
    if (!token || !notificationsEnabled) return;
    const notified = new Set();

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
        const t = localStorage.getItem("la_token") || "";
        const res = await apiFetch(`${API}/ideas/audio`, { method: "POST", headers: { "Authorization": `Bearer ${t}` }, body: fd });
        const data = await res.json();
        if (data.ok) setIdeas(prev => [data.idea, ...prev]);
      } catch { /* mejor esfuerzo: ignorar */ }
      setProcessing(false);
    };
    mr.start();
    mediaRecorderRef.current = mr;
    setRecording(true);
  }
  function stopRecording() { mediaRecorderRef.current?.stop(); setRecording(false); }

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
      const t = localStorage.getItem("la_token") || "";
      const res = await apiFetch(`${API}/ideas/text`, {
        method: "POST",
        headers: { "Authorization": `Bearer ${t}`, "Content-Type": "application/json" },
        body: JSON.stringify({ text }),
      });
      const data = await res.json();
      if (data.ok) {
        setIdeas(prev => [data.idea, ...prev]);
        setShowTextIdea(false);
      } else {
        setTextIdeaError("No se pudo guardar la idea");
      }
    } catch {
      setTextIdeaError("Error de conexión con el backend");
    }
    setTextIdeaSubmitting(false);
  }

  async function fetchDeparture(ev, mode) {
    if (!ev?.loc || !ev?.start) return;
    const key = ev.id || ev.start;
    setDeparturePickingId(null);
    setDepartureLoadingId(key);
    try {
      const t = localStorage.getItem("la_token") || "";
      // Origen = ubicación del dispositivo si hay geolocalización; si no, el backend
      // usa HOME_ADDRESS por defecto (no mandamos 'origin').
      const body = { destination: ev.loc, event_time: ev.start, mode };
      if (geo) body.origin = `${geo.lat},${geo.lon}`;
      const res = await apiFetch(`${API}/maps/departure`, {
        method: "POST",
        headers: { "Authorization": `Bearer ${t}`, "Content-Type": "application/json" },
        body: JSON.stringify(body),
      });
      const data = await res.json();
      setDepartureMap(prev => ({ ...prev, [key]: { ...data, mode } }));
    } catch {
      setDepartureMap(prev => ({ ...prev, [key]: { error: "Error al calcular" } }));
    }
    setDepartureLoadingId(null);
  }

  function DepartureWidget({ ev }) {
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

  async function wakePC() {
    setWolStatus("loading");
    try {
      const t = localStorage.getItem("la_token") || "";

      // 1. WOL: pone flag en el backend → HA lo recoge en su poll y envía el magic packet
      try {
        await apiFetch(`${API}/wake-pc`, {
          method: "POST",
          headers: { "Authorization": `Bearer ${t}` },
        });
      } catch {
        // best-effort, no bloquea el flujo
      }

      // 2. Crear job en Supabase via backend — esto sí es crítico
      const jobRes = await apiFetch(`${API}/jobs`, {
        method: "POST",
        headers: { "Authorization": `Bearer ${t}`, "Content-Type": "application/json" },
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
    const t = localStorage.getItem("la_token") || "";
    setActiveJobId(null);
    setJobEvents([]);
    setJobTerminal(null);
    setJobStatus("pending");
    try {
      // 1. WOL (best-effort): enciende el PC si está apagado.
      try {
        await apiFetch(`${API}/wake-pc`, {
          method: "POST",
          headers: { "Authorization": `Bearer ${t}` },
        });
      } catch { /* mejor esfuerzo: el job es lo crítico */ }

      // 2. Relanzar agente (best-effort): si el PC ya estaba encendido, el agente
      // efímero ya terminó; HA lo arranca por SSH al ver este flag.
      try {
        await apiFetch(`${API}/relaunch-agent`, {
          method: "POST",
          headers: { "Authorization": `Bearer ${t}` },
        });
      } catch { /* mejor esfuerzo */ }

      // 3. Job de abrir Sunshine (crítico): el agente lo despacha al arrancar.
      const jobRes = await apiFetch(`${API}/jobs`, {
        method: "POST",
        headers: { "Authorization": `Bearer ${t}`, "Content-Type": "application/json" },
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
    const t = localStorage.getItem("la_token") || "";
    try {
      const r = await apiFetch(`${API}/${accion === "shutdown" ? "shutdown-pc" : "suspend-pc"}`, {
        method: "POST",
        headers: { "Authorization": `Bearer ${t}` },
      });
      setPcPower(r.ok ? (accion === "shutdown" ? "shutdown_sent" : "suspend_sent") : "error");
    } catch {
      setPcPower("error");
    }
  }

  async function excludeSleepNight(date) {
    const t = localStorage.getItem("la_token") || "";
    setSleepExcluding(date);
    try {
      const r = await apiFetch(`${API}/health/sleep/${date}/exclude`, {
        method: "PATCH",
        headers: { "Authorization": `Bearer ${t}` },
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
    const t = localStorage.getItem("la_token") || "";
    await apiFetch(`${API}/ideas/${id}`, { method: "DELETE", headers: { "Authorization": `Bearer ${t}` } });
    setIdeas(prev => prev.filter(i => i.id !== id));
  }

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

  async function addClothing() {
    if (clothingSaving) return;
    const price = parseFloat(String(clothingPrice).replace(",", "."));
    setClothingSaving(true);
    setClothingError(null);
    const t = localStorage.getItem("la_token") || "";
    try {
      const r = await apiFetch(`${API}/clothing`, {
        method: "POST",
        headers: { "Authorization": `Bearer ${t}`, "Content-Type": "application/json" },
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
        setClothingName(""); setClothingPrice(""); setClothingPhoto(null);
        setShowClothingForm(false);
      } else {
        // Surfacer el fallo: el código de estado dice qué pasó (404 = backend sin
        // desplegar los endpoints, 502 = problema con la tabla, 401/403 = sesión).
        setClothingError(`No se pudo guardar (error ${r.status})${data.detail ? `: ${data.detail}` : ""}`);
      }
    } catch {
      setClothingError("No se pudo conectar con el servidor.");
    }
    finally { setClothingSaving(false); }
  }

  async function deleteClothing(id) {
    const t = localStorage.getItem("la_token") || "";
    try {
      const r = await apiFetch(`${API}/clothing/${id}`, { method: "DELETE", headers: { "Authorization": `Bearer ${t}` } });
      if (r.ok) setClothing(prev => prev.filter(c => c.id !== id));
    } catch { /* mejor esfuerzo: ignorar */ }
  }

  async function loadTraining() {
    const t = localStorage.getItem("la_token") || "";
    try {
      const r = await apiFetch(`${API}/training/summary`, { headers: { "Authorization": `Bearer ${t}` } });
      const data = await r.json();
      setTraining(data);
    } catch { /* mejor esfuerzo: ignorar */ }
  }

  async function submitSession() {
    if (trainingLoading) return;
    setTrainingLoading(true);
    const t = localStorage.getItem("la_token") || "";
    try {
      await apiFetch(`${API}/training/sessions`, {
        method: "POST",
        headers: { "Authorization": `Bearer ${t}`, "Content-Type": "application/json" },
        body: JSON.stringify({ date: sessionDate, duration_hours: parseFloat(sessionHours) }),
      });
      setShowSessionForm(false);
      await loadTraining();
    } catch { /* mejor esfuerzo: ignorar */ }
    setTrainingLoading(false);
  }

  async function deleteTrainingSession(sessionId) {
    const t = localStorage.getItem("la_token") || "";
    await apiFetch(`${API}/training/sessions/${sessionId}`, { method: "DELETE", headers: { "Authorization": `Bearer ${t}` } });
    await loadTraining();
  }

  async function updateTrainingClient(patch) {
    if (trainingSettingsSaving) return;
    setTrainingSettingsSaving(true);
    const t = localStorage.getItem("la_token") || "";
    try {
      await apiFetch(`${API}/training/client`, {
        method: "PATCH",
        headers: { "Authorization": `Bearer ${t}`, "Content-Type": "application/json" },
        body: JSON.stringify(patch),
      });
      await loadTraining();
    } catch { /* mejor esfuerzo: ignorar */ }
    setTrainingSettingsSaving(false);
  }

  async function submitPayment() {
    if (trainingLoading) return;
    setTrainingLoading(true);
    const t = localStorage.getItem("la_token") || "";
    const today = new Date().toISOString().slice(0, 10);
    try {
      await apiFetch(`${API}/training/payments`, {
        method: "POST",
        headers: { "Authorization": `Bearer ${t}`, "Content-Type": "application/json" },
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
    saveWidgetConfig(widgetConfig.map(w => w.id === id ? { ...w, width: undefined, height: undefined } : w));
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

  useEffect(() => {
    if (!activeJobId || !token) return;
    let mounted = true;
    const t = localStorage.getItem("la_token") || "";
    const id = setInterval(async () => {
      try {
        const [evRes, jobRes] = await Promise.all([
          apiFetch(`${API}/jobs/${activeJobId}/events`, { headers: { "Authorization": `Bearer ${t}` } }),
          apiFetch(`${API}/jobs/by-id/${activeJobId}`, { headers: { "Authorization": `Bearer ${t}` } }),
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
    }, 2000);
    return () => { mounted = false; clearInterval(id); };
  }, [activeJobId, token]);

  const STAGES = ["heartbeat_online","job_claimed","login_ok","assignment_opened","enunciado_extracted","solver_started","result_saved","job_done"];
  const STAGE_LABELS = {
    "heartbeat_online":     "Agente online",
    "job_claimed":          "Job recogido",
    "login_ok":             "Login en Alud OK",
    "assignment_opened":    "Entrega abierta",
    "enunciado_extracted":  "Enunciado extraído",
    "solver_started":       "Cowork iniciado",
    "result_saved":         "Instrucción enviada",
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
  const stageIndex = new Map(STAGES.map((st, i) => [st, i]));
  const maxStage = jobEvents.reduce((max, ev) => Math.max(max, stageIndex.get(ev.stage) ?? -1), -1);
  const progressPct = maxStage < 0 ? 0 : Math.round(((maxStage + 1) / STAGES.length) * 100);

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
              <a href={`${API}/auth/login`} target="_blank" rel="noreferrer" style={{ color: "var(--accent)", textDecoration: "none" }}>
                → Conectar Outlook
              </a>
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
                    <DepartureWidget ev={displayActive} />
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
                  <DepartureWidget ev={ev} />
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
                <input style={inputStyle} placeholder="Nombre (opcional)" value={clothingName}
                  onChange={e => setClothingName(e.target.value)} />
                <div style={{ display: "flex", gap: 8 }}>
                  <input style={{ ...inputStyle, flex: 1 }} type="text" inputMode="decimal" placeholder="Precio"
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
                    onClick={() => { setShowClothingForm(false); setClothingError(null); setClothingName(""); setClothingPrice(""); setClothingPhoto(null); }}>
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
        // ── datos base ──
        const wSleepEff = d => {
          if (d.value && d.value > 0) return d.value;
          if (d.extra?.asleep > 0) return Number(d.extra.asleep);
          return (Number(d.extra?.deep)||0)+(Number(d.extra?.rem)||0)+(Number(d.extra?.light)||0)+(Number(d.extra?.core)||0);
        };
        const wSleepRaw     = findMetric(healthData, "sleep_analysis", "sleep").filter(d => !d.extra?.excluded).map(d => ({ ...d, value: wSleepEff(d) }));
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
        // Sueño 25 | Actividad 32 (entreno 15 + pasos 8 + AE 5 + stand 2 + pisos 2) | Recuperación 25 (HRV 12 + RHR 8 + cardio 5) | Forma 14 (VO2 6 + walkHR 4 + %grasa 4, solo diario) | Estilo de vida 10 (luz 5 + resp 5, solo diario)
        let score = 0;
        const breakdown = []; // [{label, pts, max, detail}]

        // Sueño (25 pts)
        let sPts = 0;
        if (sleepVal != null) {
          if      (sleepVal >= 7.5) sPts = 25;
          else if (sleepVal >= 7)   sPts = 21;
          else if (sleepVal >= 6.5) sPts = 15;
          else if (sleepVal >= 6)   sPts = 9;
          else                      sPts = 4;
          score += sPts;
        }
        breakdown.push({ label: "😴 Sueño", pts: sPts, max: 25, detail: sleepVal != null ? hoursToHM(sleepVal) : "sin datos" });

        // Actividad: entreno/ejercicio (15 pts)
        let wPts = 0;
        if (isDaily) {
          if      (workVal >= 1)                                 wPts = 15;
          else if (exerciseVal != null && exerciseVal >= 30)     wPts = 9;
          else if (exerciseVal != null && exerciseVal >= 15)     wPts = 5;
          else if (todayHrv != null && todayHrv >= 70)           wPts = 3;
          else if (todayHrv != null && todayHrv >= 50)           wPts = 2;
          else                                                   wPts = 1;
        } else {
          const scaledWork = expectedByNow > 0 ? Math.min(4, (workVal / expectedByNow) * 4) : workVal;
          if      (scaledWork >= 4) wPts = 15;
          else if (scaledWork >= 3) wPts = 11;
          else if (scaledWork >= 2) wPts = 7;
          else if (scaledWork >= 1) wPts = 3;
        }
        score += wPts;
        breakdown.push({ label: "💪 Entreno", pts: wPts, max: 15, detail: isDaily ? (workVal >= 1 ? `${workVal} entreno` : exerciseVal != null ? `${Math.round(exerciseVal)}min ejercicio` : "descanso") : `${workVal}/4 ses.` });

        // Actividad: pasos (8 pts)
        let stPts = 0;
        if (stepsVal != null) {
          if      (stepsVal >= 10000) stPts = 8;
          else if (stepsVal >= 8000)  stPts = 6;
          else if (stepsVal >= 6000)  stPts = 4;
          else if (stepsVal >= 4000)  stPts = 2;
          else                        stPts = 1;
          score += stPts;
        }
        breakdown.push({ label: "🚶 Pasos", pts: stPts, max: 8, detail: stepsVal != null ? `${Math.round(stepsVal).toLocaleString("es")}` : "sin datos" });

        // Actividad: energía activa (5 pts)
        let aePts = 0;
        if (aeVal != null) {
          if      (aeVal >= 600) aePts = 5;
          else if (aeVal >= 400) aePts = 4;
          else if (aeVal >= 250) aePts = 3;
          else if (aeVal >= 100) aePts = 1;
          score += aePts;
        }
        breakdown.push({ label: "🔥 Energía", pts: aePts, max: 5, detail: aeVal != null ? `${Math.round(aeVal)} kcal` : "sin datos" });

        // Actividad: horas de pie (2 pts)
        let sdPts = 0;
        if (standVal != null) {
          if      (standVal >= 12) sdPts = 2;
          else if (standVal >= 8)  sdPts = 1;
          score += sdPts;
        }
        breakdown.push({ label: "🧍 De pie", pts: sdPts, max: 2, detail: standVal != null ? `${Math.round(standVal)}h` : "sin datos" });

        // Actividad: pisos subidos (2 pts)
        let flPts = 0;
        if (flightsVal != null) {
          if      (flightsVal >= 10) flPts = 2;
          else if (flightsVal >= 5)  flPts = 1;
          score += flPts;
        }
        breakdown.push({ label: "🪜 Pisos", pts: flPts, max: 2, detail: flightsVal != null ? `${Math.round(flightsVal)} pisos` : "sin datos" });

        // Recuperación: HRV (12 pts)
        let hrvPts = 0;
        if (hrvVal != null && avgHrvPrev != null) {
          if      (hrvVal >= avgHrvPrev * 1.05) hrvPts = 12;
          else if (hrvVal >= avgHrvPrev * 0.95) hrvPts = 8;
          else                                   hrvPts = 4;
        } else if (hrvVal != null) hrvPts = 6;
        score += hrvPts;
        breakdown.push({ label: "❤️ HRV", pts: hrvPts, max: 12, detail: hrvVal != null ? `${Math.round(hrvVal)}ms${avgHrvPrev != null ? ` (ref ${Math.round(avgHrvPrev)}ms)` : ""}` : "sin datos" });

        // Recuperación: FC reposo (8 pts)
        let rhrPts = 0;
        if (rhrVal != null) {
          if      (rhrVal <= 50) rhrPts = 8;
          else if (rhrVal <= 55) rhrPts = 7;
          else if (rhrVal <= 60) rhrPts = 6;
          else if (rhrVal <= 65) rhrPts = 4;
          else if (rhrVal <= 70) rhrPts = 3;
          else if (rhrVal <= 80) rhrPts = 1;
          score += rhrPts;
        }
        breakdown.push({ label: "🫀 FC reposo", pts: rhrPts, max: 8, detail: rhrVal != null ? `${Math.round(rhrVal)} lpm` : "sin datos" });

        // Recuperación: cardio recovery (5 pts — solo si hay dato)
        let crPts = 0;
        if (avgCardioRec != null) {
          if      (avgCardioRec >= 30) crPts = 5;
          else if (avgCardioRec >= 20) crPts = 4;
          else if (avgCardioRec >= 15) crPts = 3;
          else if (avgCardioRec >= 10) crPts = 1;
          score += crPts;
        }
        if (avgCardioRec != null) breakdown.push({ label: "💓 Recuperación cardio", pts: crPts, max: 5, detail: `${Math.round(avgCardioRec)} lpm/min` });

        // Forma física (solo vista diaria): VO2 max (6 pts) + walking HR avg (4 pts)
        let vo2Pts, whrPts = 0;
        if (isDaily) {
          if (lastVo2 != null) {
            if      (lastVo2 >= 50) vo2Pts = 6;
            else if (lastVo2 >= 45) vo2Pts = 5;
            else if (lastVo2 >= 40) vo2Pts = 4;
            else if (lastVo2 >= 35) vo2Pts = 3;
            else                    vo2Pts = 1;
            score += vo2Pts;
          }
          if (walkHrVal != null) {
            if      (walkHrVal <= 70)  whrPts = 4;
            else if (walkHrVal <= 80)  whrPts = 3;
            else if (walkHrVal <= 90)  whrPts = 2;
            else if (walkHrVal <= 100) whrPts = 1;
            score += whrPts;
            breakdown.push({ label: "🏃 FC caminando", pts: whrPts, max: 4, detail: `${Math.round(walkHrVal)} lpm` });
          }
          if (currentBodyFat != null) {
            let bfPts = 0;
            if      (currentBodyFat < 12) bfPts = 4;
            else if (currentBodyFat < 18) bfPts = 3;
            else if (currentBodyFat < 25) bfPts = 2;
            else if (currentBodyFat < 30) bfPts = 1;
            score += bfPts;
            breakdown.push({ label: "⚖️ % Grasa", pts: bfPts, max: 4, detail: `${currentBodyFat.toFixed(1)}%` });
          }

          // Estilo de vida (solo vista diaria): luz natural (5 pts) + resp rate (5 pts)
          let dlPts = 0, respPts;
          if (daylightVal != null) {
            if      (daylightVal >= 60) dlPts = 5;
            else if (daylightVal >= 30) dlPts = 4;
            else if (daylightVal >= 15) dlPts = 2;
            else if (daylightVal >= 5)  dlPts = 1;
            score += dlPts;
          }
          if (respVal != null) {
            if      (respVal >= 12 && respVal <= 16) respPts = 5;
            else if (respVal > 16 && respVal <= 18)  respPts = 4;
            else if (respVal > 18 && respVal <= 20)  respPts = 3;
            else if (respVal < 12)                   respPts = 4;
            else                                     respPts = 1;
            score += respPts;
            breakdown.push({ label: "🌬️ Resp.", pts: respPts, max: 5, detail: `${respVal.toFixed(1)} rpm` });
          }
        }

        const scoreLabel = isDaily
          ? (score >= 80 ? "Día excelente" : score >= 65 ? "Buen día" : score >= 50 ? "Día regular" : "Día flojo")
          : (score >= 80 ? "Semana excelente" : score >= 65 ? "Buena semana" : score >= 50 ? "Semana regular" : "Semana floja");
        const scoreColor = score >= 80 ? "var(--green)" : score >= 65 ? "#6aaa82" : score >= 50 ? "var(--accent)" : "#d4645a";

        // ── potencial: componente con más margen de mejora ──
        const POTENTIAL_VERBS = {
          "😴 Sueño": "Durmiendo más",
          "💪 Entreno": isDaily ? "Entrenando hoy" : "Sumando otra sesión de entreno",
          "🚶 Pasos": "Caminando más pasos",
          "🔥 Energía": "Quemando más calorías activas",
          "🧍 De pie": "Pasando más horas de pie",
          "🪜 Pisos": "Subiendo más pisos",
          "❤️ HRV": "Mejorando tu recuperación (HRV)",
          "🫀 FC reposo": "Bajando tu FC en reposo",
          "💓 Recuperación cardio": "Mejorando tu recuperación cardio",
          "🏃 FC caminando": "Bajando tu FC al caminar",
          "⚖️ % Grasa": "Bajando tu % de grasa",
          "🌬️ Resp.": "Estabilizando tu frecuencia respiratoria",
        };
        const improvable = breakdown.filter(b => b.pts < b.max && b.detail !== "sin datos");
        let potential = null;
        if (improvable.length > 0) {
          const top = improvable.reduce((a, b) => (b.max - b.pts) > (a.max - a.pts) ? b : a);
          const gap = top.max - top.pts;
          if (gap >= 2) {
            const verb = POTENTIAL_VERBS[top.label] || `Mejorando ${top.label.replace(/^\S+\s/, "")}`;
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
                    {score} — {scoreLabel}
                  </span>
                  {scoreTooltip && (
                    <div style={{
                      position: "absolute", right: 0, top: "calc(100% + 6px)", zIndex: 100,
                      background: "var(--surface2)", border: "0.5px solid var(--border)",
                      borderRadius: 8, padding: "10px 14px", minWidth: 220,
                      boxShadow: "0 4px 16px rgba(0,0,0,0.4)", fontSize: 12,
                      display: "flex", flexDirection: "column", gap: 5,
                    }}>
                      {breakdown.map((b, i) => (
                        <div key={i} style={{ display: "flex", justifyContent: "space-between", alignItems: "center", gap: 12 }}>
                          <span style={{ color: "var(--muted)", whiteSpace: "nowrap" }}>{b.label}</span>
                          <span style={{ display: "flex", alignItems: "center", gap: 6, whiteSpace: "nowrap" }}>
                            <span style={{ color: "var(--text-2)", fontSize: 11 }}>{b.detail}</span>
                            <span style={{ fontFamily: "'DM Mono', monospace", color: b.pts === b.max ? "var(--green)" : b.pts > 0 ? "var(--accent)" : "var(--muted)", minWidth: 36, textAlign: "right" }}>
                              {b.pts}/{b.max}
                            </span>
                          </span>
                        </div>
                      ))}
                      <div style={{ borderTop: "0.5px solid var(--border)", marginTop: 3, paddingTop: 5, display: "flex", justifyContent: "space-between" }}>
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
        const sleepEff = d => {
          if (d.value && d.value > 0) return d.value;
          if (d.extra?.asleep && d.extra.asleep > 0) return Number(d.extra.asleep);
          return (Number(d.extra?.deep) || 0) + (Number(d.extra?.rem) || 0)
               + (Number(d.extra?.light) || 0) + (Number(d.extra?.core) || 0);
        };
        const sleepRaw     = findMetric(healthData, "sleep_analysis", "sleep");
        const sleepAllData = sleepRaw.map(d => ({ ...d, value: sleepEff(d) }));
        const sleepData    = sleepAllData.filter(d => !d.extra?.excluded);
        const last14       = sleepAllData.slice(-7);
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
        const lc  = latest?.extra?.core  != null ? Number(latest.extra.core)  : (latest?.extra?.light != null ? Number(latest.extra.light) : null);
        const law = latest?.extra?.awake != null ? Number(latest.extra.awake) : null;
        const lss = latest?.extra?.sleep_start ?? null;

        // Baselines de recuperación (últimos 30 días, excluyendo hoy)
        const sleepTodayStr  = new Date().toLocaleDateString("sv");
        const hrvAllData     = findMetric(healthData, "heart_rate_variability", "heartRateVariability");
        const rhrAllData     = findMetric(healthData, "resting_heart_rate");
        const respAllData    = findMetric(healthData, "respiratory_rate");
        const baseline30     = arr => { const v = arr.filter(d => d.date !== sleepTodayStr && d.value != null).map(d => Number(d.value)).filter(v => v > 0); return v.length ? v.reduce((a,b) => a+b,0)/v.length : null; };
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

        const score = latest ? sleepScore(lv, ld, lr, lc, law, lss, recoveryMod) : null;
        const scoreLabel = score == null ? null : score >= 85 ? "Excelente" : score >= 70 ? "Bueno" : score >= 55 ? "Regular" : "Mejorable";
        const scoreColor = score == null ? null : score >= 85 ? "var(--green)" : score >= 70 ? "#6aaa82" : score >= 55 ? "var(--accent)" : "#d4645a";

        // Desglose del score para tooltip
        const sleepBreakdown = (() => {
          if (!latest) return [];
          const rows = [];
          // Duración
          const durPts = lv >= 8 && lv <= 9.5 ? 40 : lv >= 7.5 ? 34 : lv >= 7 ? 26 : lv >= 6 ? 16 : 6;
          rows.push({ label: "Duración", detail: hoursToHM(lv), pts: durPts, max: 40 });
          // Profundo
          const dp = ld && lv ? (ld / lv) * 100 : null;
          const deepPts = dp == null ? 12 : dp >= 13 && dp <= 23 ? 25 : dp >= 10 ? 19 : dp >= 7 ? 13 : 6;
          rows.push({ label: "Sueño profundo", detail: ld != null ? `${Math.round(dp ?? 0)}% · ${hoursToHM(ld)}` : "–", pts: deepPts, max: 25 });
          // REM
          const rp = lr && lv ? (lr / lv) * 100 : null;
          const remPts = rp == null ? 12 : rp >= 20 && rp <= 25 ? 25 : rp >= 15 ? 19 : rp >= 10 ? 13 : 6;
          rows.push({ label: "REM", detail: lr != null ? `${Math.round(rp ?? 0)}% · ${hoursToHM(lr)}` : "–", pts: remPts, max: 25 });
          // Tiempo despierto
          const ap = law && lv ? (law / lv) * 100 : 0;
          const awakePts = ap < 5 ? 10 : ap < 10 ? 7 : ap < 15 ? 4 : 0;
          rows.push({ label: "Tiempo despierto", detail: law != null ? `${Math.round(ap)}% · ${hoursToHM(law)}` : "–", pts: awakePts, max: 10 });
          // Hora de acostarse
          if (lss) {
            const h = parseInt(lss.slice(0, 2), 10);
            const latePen = h >= 2 && h < 6 ? -15 : h >= 1 ? -10 : h >= 0 && h < 1 ? -5 : 0;
            if (latePen < 0) rows.push({ label: "Hora de acostarse", detail: lss.slice(0, 5), pts: latePen, max: 0 });
          }
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
          return rows;
        })();

        const STAGE_TIPS = {
          deep: { label: "Sueño profundo (N3)", color: "#4a72b0", tip: "Restaura el cuerpo, consolida la memoria muscular y libera hormona del crecimiento. Es el más reparador. Óptimo: 13–23% del total (≈1–2h en 8h de sueño). Disminuye con la edad." },
          rem:  { label: "Sueño REM", color: "#8b68c4", tip: "Procesa emociones, consolida recuerdos y favorece la creatividad. Los sueños ocurren aquí. Óptimo: 20–25% del total (≈1.5–2h en 8h). Se acumula en la segunda mitad de la noche." },
          core: { label: "Sueño ligero (N1/N2)", color: "#4f8fa3", tip: "Fase de transición y procesamiento de información. Ocupa la mayor parte del sueño. Normal: 50–60% del total. Necesario para consolidar el ciclo de sueño." },
          awake:{ label: "Tiempo despierto", color: "var(--muted)", tip: "Microdespertares durante la noche. Normal: 10–30 min. Más de 45 min puede indicar apnea, estrés o mala higiene del sueño." },
        };

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
                  {sleepScoreTooltip && sleepBreakdown.length > 0 && (
                    <div style={{
                      position: "absolute", right: 0, top: "calc(100% + 6px)", zIndex: 100,
                      background: "var(--surface2)", border: "0.5px solid var(--border)",
                      borderRadius: 8, padding: "10px 14px", minWidth: 240,
                      boxShadow: "0 4px 16px rgba(0,0,0,0.4)", fontSize: 12,
                      display: "flex", flexDirection: "column", gap: 4,
                    }}>
                      {sleepBreakdown.map((b, i) => (
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
            ) : last14.length === 0 ? (
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
                {last14.length > 1 && (
                  <div style={{ display: "flex", gap: 5, marginTop: 4 }}>
                    {last14.map((d, i) => {
                      const excl = d.extra?.excluded ?? false;
                      const sc = excl ? null : sleepScore(d.value, Number(d.extra?.deep)||0, Number(d.extra?.rem)||0, Number(d.extra?.core)||Number(d.extra?.light)||0, Number(d.extra?.awake)||0, d.extra?.sleep_start ?? null, recovModByDate(d.date));
                      const c  = excl ? "var(--border2)" : sc == null ? "var(--border2)" : sc >= 85 ? "var(--green)" : sc >= 70 ? "#6aaa82" : sc >= 55 ? "var(--accent)" : "#d4645a";
                      const date = new Date(d.date + "T12:00:00");
                      const day  = ["D","L","M","X","J","V","S"][date.getDay()];
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
                    const day = ["D","L","M","X","J","V","S"][date.getDay()];
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
        const ICONS  = { Running:"🏃", Walking:"🚶", Cycling:"🚴", Swimming:"🏊", "Strength Training":"🏋️", HIIT:"⚡", Yoga:"🧘", Basketball:"🏀", Soccer:"⚽", Tennis:"🎾", Hiking:"🥾" };
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
                  const icon = ICONS[type] || "💪";
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

    // Los widgets de salud se colapsan en un único bloque con pestañas — más
    // navegable en móvil que apilar seis tarjetas grandes.
    const HEALTH_TAB_LABELS = {
      health_wellness: "Bienestar",
      health_sleep:    "Sueño",
      health_activity: "Actividad",
      health_hrv:      "HRV",
      health_heart:    "FC",
      health_workouts: "Entrenos",
    };

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
                style={{ ...inputStyle, fontSize: 15, padding: "11px 12px" }} />

              <div>
                <div style={fieldLabelStyle}>Fecha</div>
                <DateInput value={eventForm.date} onChange={v => setEventForm(f => ({ ...f, date: v }))} />
                <div style={{ fontSize: 11, color: "var(--muted2)", marginTop: 5 }}>
                  {eventForm.date ? formatShortDate(eventForm.date) : ""}
                </div>
              </div>

              <div>
                <div style={fieldLabelStyle}>Hora</div>
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
                <div style={fieldLabelStyle}>Ubicación</div>
                <input type="text" placeholder="Opcional" value={eventForm.location}
                  onChange={e => setEventForm(f => ({ ...f, location: e.target.value }))}
                  style={inputStyle} />
              </div>

              {!editingEventId && (
                <div>
                  <div style={fieldLabelStyle}>Calendario</div>
                  <select value={eventForm.calendarId}
                    onChange={e => setEventForm(f => ({ ...f, calendarId: e.target.value }))}
                    style={inputStyle}>
                    <option value="">Por defecto</option>
                    {calendarsList.map(c => <option key={c.id} value={c.id}>{c.name}</option>)}
                  </select>
                </div>
              )}

              <div>
                <div style={fieldLabelStyle}>URL de Alud (opcional)</div>
                <input type="url" placeholder="https://alud.deusto.es/mod/assign/view.php?id=XXXXX" value={eventForm.alud_url}
                  onChange={e => setEventForm(f => ({ ...f, alud_url: e.target.value }))}
                  style={inputStyle} />
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
              style={{ ...inputStyle, fontSize: 14, padding: "11px 12px", resize: "vertical", fontFamily: "'DM Sans', sans-serif" }}
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
                          <DepartureWidget ev={{ ...ev, loc: ev.location }} />
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
  mainGrid: { display: "grid", gridTemplateColumns: "1fr 320px", gap: 16, alignItems: "start", flex: 1 },
  leftCol:  { display: "flex", flexDirection: "column", gap: 16 },
  rightCol: { display: "flex", flexDirection: "column", gap: 16 },
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


