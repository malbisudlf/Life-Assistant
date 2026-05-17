import { useState, useEffect, useRef } from "react";

const API = "https://backend-tender-glow-160.fly.dev";
const CLASS_DESTINATION = "Universidad de Deusto, Bilbao";
const HA_URL = (import.meta.env.VITE_HA_URL || "http://192.168.1.200:8123") + "/lovelace/tablet";

// ── LOGIN SCREEN ─────────────────────────────────────────────────
function LoginScreen({ onLogin }) {
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

// ── HELPERS DE FECHA ─────────────────────────────────────────────
function isToday(dateStr) {
  const d = new Date(dateStr);
  const t = new Date();
  return d.getFullYear() === t.getFullYear() && d.getMonth() === t.getMonth() && d.getDate() === t.getDate();
}
function isFuture(dateStr) { return new Date(dateStr) > new Date(); }
function isPast(dateStr) { return new Date(dateStr) < new Date(); }
function isActive(startStr, endStr) {
  const now = new Date();
  return new Date(startStr) <= now && new Date(endStr) >= now;
}
function daysUntil(dateStr) {
  return Math.ceil((new Date(dateStr) - new Date()) / (1000 * 60 * 60 * 24));
}
function formatTime(dateStr) {
  const d = new Date(dateStr);
  return `${String(d.getHours()).padStart(2,"0")}:${String(d.getMinutes()).padStart(2,"0")}`;
}
function formatUpcomingTime(dateStr) {
  const d = new Date(dateStr);
  const tomorrow = new Date(); tomorrow.setDate(tomorrow.getDate() + 1);
  const DAYS = ["Dom","Lun","Mar","Mié","Jue","Vie","Sáb"];
  if (isToday(dateStr)) return formatTime(dateStr);
  if (d.toDateString() === tomorrow.toDateString()) return `Mañana ${formatTime(dateStr)}`;
  return `${DAYS[d.getDay()]} ${formatTime(dateStr)}`;
}
function urgencyColor(days) {
  if (days <= 3) return "#d4645a";
  if (days <= 7) return "#c8a45a";
  return "#6aaa82";
}
function formatShortDate(dateStr) {
  if (!dateStr) return "";
  const [, m, d] = dateStr.split("-").map(Number);
  return `${d} ${MONTHS_ES[m - 1].slice(0, 3)}`;
}

const DAYS_ES   = ["Domingo","Lunes","Martes","Miércoles","Jueves","Viernes","Sábado"];
const MONTHS_ES = ["enero","febrero","marzo","abril","mayo","junio","julio","agosto","septiembre","octubre","noviembre","diciembre"];

// ── HELPERS DE SALUD ─────────────────────────────────────────────
function hoursToHM(h) {
  if (h == null || isNaN(h)) return "—";
  const hrs  = Math.floor(h);
  const mins = Math.round((h - hrs) * 60);
  if (mins === 0) return `${hrs}h`;
  return `${hrs}h ${mins}m`;
}

function sleepScore(total, deep, rem, core, awake) {
  if (!total || total < 0.5) return null;
  let s = 0;
  // Duración (40 pts)
  if      (total >= 7 && total <= 9) s += 40;
  else if (total >= 6.5)             s += 34;
  else if (total >= 6)               s += 26;
  else if (total >= 5)               s += 16;
  else                               s += 6;
  // Sueño profundo (25 pts)
  const dp = deep ? (deep / total) * 100 : null;
  if      (dp == null)            s += 12;
  else if (dp >= 13 && dp <= 23)  s += 25;
  else if (dp >= 10)              s += 19;
  else if (dp >= 7)               s += 13;
  else                            s += 6;
  // REM (25 pts)
  const rp = rem ? (rem / total) * 100 : null;
  if      (rp == null)            s += 12;
  else if (rp >= 20 && rp <= 25)  s += 25;
  else if (rp >= 15)              s += 19;
  else if (rp >= 10)              s += 13;
  else                            s += 6;
  // Tiempo despierto (10 pts)
  const ap = awake ? (awake / total) * 100 : 0;
  if      (ap < 5)   s += 10;
  else if (ap < 10)  s += 7;
  else if (ap < 15)  s += 4;
  return Math.min(100, Math.round(s));
}

function SleepStageTooltip({ label, color, tip, children }) {
  const [show, setShow] = useState(false);
  const [pos,  setPos]  = useState({ x: 0, y: 0 });
  return (
    <span style={{ position: "relative", cursor: "default" }}
      onMouseEnter={e => { setShow(true); setPos({ x: e.clientX, y: e.clientY }); }}
      onMouseMove={e  => setPos({ x: e.clientX, y: e.clientY })}
      onMouseLeave={() => setShow(false)}
    >
      {children}
      {show && (
        <div style={{
          position: "fixed", left: pos.x + 14, top: pos.y + 10,
          background: "#1a1b1e", border: "0.5px solid rgba(255,255,255,0.15)",
          borderLeft: `2px solid ${color}`,
          borderRadius: 8, padding: "10px 14px", zIndex: 2000,
          maxWidth: 260, fontSize: 12, color: "#c8c6c0", lineHeight: 1.6,
          boxShadow: "0 8px 32px rgba(0,0,0,0.6)", pointerEvents: "none",
        }}>
          <div style={{ fontWeight: 600, color: "#e8e6e0", marginBottom: 4 }}>{label}</div>
          {tip}
        </div>
      )}
    </span>
  );
}

function findMetric(metrics, ...names) {
  if (!metrics) return [];
  for (const name of names) {
    if (metrics[name]?.length) return metrics[name];
  }
  return [];
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

function SleepBars({ data }) {
  const maxVal = Math.max(...data.map(d => d.value || 0), 9);
  return (
    <div style={{ display: "flex", alignItems: "flex-end", gap: 4, height: 64 }}>
      {data.map((d, i) => {
        const total = d.value || 0;
        const h     = Math.max(3, (total / maxVal) * 54);
        const deep  = Number(d.extra?.deep)  || 0;
        const rem   = Number(d.extra?.rem)   || 0;
        const core  = Number(d.extra?.core)  || Number(d.extra?.light) || 0;
        const stagesKnown = deep > 0 || rem > 0 || core > 0;
        const stageSum = deep + rem + core || total;
        const date = new Date(d.date + "T12:00:00");
        const day  = ["D","L","M","X","J","V","S"][date.getDay()];
        const fallColor = total >= 7 ? "#6aaa82" : total >= 6 ? "#c8a45a" : "#d4645a";
        return (
          <div key={i} style={{ flex: 1, display: "flex", flexDirection: "column", alignItems: "center", gap: 3 }}
            title={`${d.date}: ${hoursToHM(total)}`}>
            <div style={{ width: "100%", height: h, borderRadius: "3px 3px 0 0", overflow: "hidden", display: "flex", flexDirection: "column-reverse" }}>
              {stagesKnown ? (
                <>
                  {deep > 0 && <div style={{ flex: deep / stageSum, background: "#4a72b0", minHeight: 1 }} />}
                  {rem  > 0 && <div style={{ flex: rem  / stageSum, background: "#8b68c4", minHeight: 1 }} />}
                  {core > 0 && <div style={{ flex: core / stageSum, background: "#4f8fa3", minHeight: 1 }} />}
                </>
              ) : (
                <div style={{ flex: 1, background: fallColor, opacity: 0.85 }} />
              )}
            </div>
            <div style={{ fontSize: 9, color: "var(--muted2)", fontFamily: "'DM Mono', monospace" }}>{day}</div>
          </div>
        );
      })}
    </div>
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
    --text: #e8e6e0; --muted: #7a7870; --muted2: #5a5850;
    --accent: #c8a96e; --accent2: #8bb4d4; --green: #6aaa82;
    --node-line: rgba(200,169,110,0.3);
  }
  html, body, #root { height: 100%; background: var(--bg); }
  body { font-family: 'DM Sans', sans-serif; color: var(--text); }
  ::-webkit-scrollbar { width: 4px; height: 4px; }
  ::-webkit-scrollbar-track { background: transparent; }
  ::-webkit-scrollbar-thumb { background: var(--border2); border-radius: 2px; }
  @keyframes slideInRight { from { transform: translateX(100%); opacity: 0; } to { transform: translateX(0); opacity: 1; } }
  @keyframes fadeInOverlay { from { opacity: 0; } to { opacity: 1; } }
  @keyframes pulse { 0%, 100% { opacity: 1; } 50% { opacity: 0.4; } }
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
    .clock { font-size: 36px !important; letter-spacing: -1px !important; }
    .dashboard-root { padding: 12px !important; gap: 12px !important; }
    .header-greeting { display: none !important; }
    .timeline-inner { min-width: 280px !important; }
    .widget-wrap { width: 100% !important; }
    .col-left, .col-right { width: 100% !important; min-width: 0 !important; }
    .col-divider { display: none !important; }
  }
`;

const DEFAULT_COLUMN_SPLIT = 0.65;

const DEFAULT_COLUMNS = {
  timeline:          "left",
  upcoming:          "left",
  entregas:          "right",
  training:          "right",
  ideas:             "right",
  health_wellness:   "left",
  health_sleep:      "right",
  health_heart:      "right",
  health_hrv:        "right",
  health_activity:   "right",
  health_workouts:   "right",
};

const ALL_DEFAULT_WIDGETS = [
  { id: "timeline",          label: "Hoy",              visible: true,  column: "left"  },
  { id: "upcoming",          label: "Próximos eventos",  visible: true,  column: "left"  },
  { id: "entregas",          label: "Entregas",          visible: true,  column: "right" },
  { id: "training",          label: "Entrenamiento",     visible: true,  column: "right" },
  { id: "ideas",             label: "Ideas",             visible: true,  column: "right" },
  { id: "health_wellness",   label: "Bienestar semanal", visible: true,  column: "left"  },
  { id: "health_sleep",      label: "Sueño",             visible: true,  column: "right" },
  { id: "health_heart",      label: "Freq. cardíaca",    visible: false, column: "right" },
  { id: "health_hrv",        label: "HRV",               visible: false, column: "right" },
  { id: "health_activity",   label: "Actividad",         visible: false, column: "right" },
  { id: "health_workouts",   label: "Entrenamientos AW", visible: false, column: "right" },
];

// ── COMPONENTE PRINCIPAL ─────────────────────────────────────────
export default function Dashboard() {
  const [token]               = useState(() => localStorage.getItem("la_token") || "");
  const [now, setNow]         = useState(new Date());
  const [activeEvent, setActiveEvent] = useState(null);
  const [openIdea, setOpenIdea]       = useState(null);
  const [allEvents, setAllEvents]     = useState([]);
  const [loading, setLoading]         = useState(true);
  const [authNeeded, setAuthNeeded]   = useState(false);
  const [ideas, setIdeas]             = useState([]);
  const [recording, setRecording]     = useState(false);
  const [processing, setProcessing]   = useState(false);
  const [departureMap, setDepartureMap]           = useState({});
  const [departureLoadingId, setDepartureLoadingId] = useState(null);
  const [classEvents, setClassEvents] = useState([]);
  const [classesOpen, setClassesOpen] = useState(false);
  const [wolModal, setWolModal]       = useState(null);   // entrega seleccionada
  const [wolStatus, setWolStatus]     = useState(null);   // 'loading' | 'ok' | 'error'
  const [agentState, setAgentState]   = useState(null);
  const [wolStartedAt, setWolStartedAt] = useState(null);
  const [activeJobId, setActiveJobId] = useState(null);
  const [jobEvents, setJobEvents] = useState([]);
  const [jobTerminal, setJobTerminal] = useState(null);
  const [jobStatus, setJobStatus] = useState(null);
  const [training, setTraining]           = useState(null);
  const [healthData, setHealthData]       = useState(null);
  const [healthLoading, setHealthLoading] = useState(false);
  const [showSessionForm, setShowSessionForm] = useState(false);
  const [sessionDate, setSessionDate]     = useState(() => new Date().toISOString().slice(0, 10));
  const [sessionHours, setSessionHours]   = useState("1");
  const [trainingLoading, setTrainingLoading] = useState(false);
  const [showSettings, setShowSettings]   = useState(false);
  const [showTrainingSettings, setShowTrainingSettings] = useState(false);
  const [trainingSettingsPrice, setTrainingSettingsPrice] = useState("");
  const [trainingSettingsSpp, setTrainingSettingsSpp]     = useState("");
  const [trainingSettingsSaving, setTrainingSettingsSaving] = useState(false);
  const [isEditMode, setIsEditMode]       = useState(false);
  const [draggingId, setDraggingId]       = useState(null);
  const [dragPos, setDragPos]             = useState(null);
  const [dragOverId, setDragOverId]       = useState(null);
  const [dragOverSide, setDragOverSide]   = useState("after");
  const [colSplit, setColSplit]           = useState(() => {
    try { const s = localStorage.getItem("la_column_split"); return s ? parseFloat(s) : DEFAULT_COLUMN_SPLIT; }
    catch { return DEFAULT_COLUMN_SPLIT; }
  });
  const colSplitRef = useRef((() => {
    try { const s = localStorage.getItem("la_column_split"); return s ? parseFloat(s) : DEFAULT_COLUMN_SPLIT; }
    catch { return DEFAULT_COLUMN_SPLIT; }
  })());
  const [widgetConfig, setWidgetConfig]   = useState(() => {
    try {
      const saved = localStorage.getItem("la_widget_config");
      if (saved) {
        const parsed = JSON.parse(saved).filter(w => w.id !== "__split__");
        const savedIds = new Set(parsed.map(w => w.id));
        const merged = parsed.map(w => ({
          id: w.id,
          label: ALL_DEFAULT_WIDGETS.find(d => d.id === w.id)?.label || w.label,
          visible: w.visible !== false,
          column: w.column || DEFAULT_COLUMNS[w.id] || "left",
          width:  typeof w.width  === "number" ? w.width  : undefined,
          height: typeof w.height === "number" ? w.height : undefined,
        }));
        for (const def of ALL_DEFAULT_WIDGETS) {
          if (!savedIds.has(def.id)) merged.push(def);
        }
        return merged;
      }
    } catch {}
    return ALL_DEFAULT_WIDGETS;
  });

  const mediaRecorderRef = useRef(null);
  const chunksRef        = useRef([]);
  const resizeDragRef    = useRef(null);
  const dragStateRef     = useRef(null);

  useEffect(() => { colSplitRef.current = colSplit; }, [colSplit]);

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

  // Cargar eventos
  useEffect(() => {
    const t = localStorage.getItem("la_token") || "";
    fetch(`${API}/calendar/events`, { headers: { "Authorization": `Bearer ${t}` } })
      .then(r => r.json())
      .then(data => {
        if (data.error) { setAuthNeeded(true); setLoading(false); return; }
        setAllEvents(data.events || []);
        setLoading(false);
      })
      .catch(() => { setAuthNeeded(true); setLoading(false); });
  }, []);

  // Cargar clases
  useEffect(() => {
    const t = localStorage.getItem("la_token") || "";
    if (!t) return;
    fetch(`${API}/calendar/classes`, { headers: { "Authorization": `Bearer ${t}` } })
      .then(r => r.json())
      .then(data => {
        console.log("[CLASES] respuesta raw:", data);
        if (Array.isArray(data.events)) {
          console.log("[CLASES] total:", data.events.length, "hoy:", data.events.filter(e => isToday(e.start)).length);
          setClassEvents(data.events);
        } else {
          console.warn("[CLASES] no es array:", data);
        }
      })
      .catch(e => console.error("[CLASES] error:", e));
  }, []);

  // Cargar resumen entrenamiento
  useEffect(() => { loadTraining(); }, []); // eslint-disable-line react-hooks/exhaustive-deps

  // Cargar datos de salud
  useEffect(() => {
    const t = localStorage.getItem("la_token") || "";
    if (!t) return;
    setHealthLoading(true);
    fetch(`${API}/health/metrics?days=30`, { headers: { "Authorization": `Bearer ${t}` } })
      .then(r => r.json())
      .then(data => { setHealthData(data.metrics || {}); setHealthLoading(false); })
      .catch(() => setHealthLoading(false));
  }, []);

  // Cargar ideas
  useEffect(() => {
    const t = localStorage.getItem("la_token") || "";
    fetch(`${API}/ideas`, { headers: { "Authorization": `Bearer ${t}` } })
      .then(r => r.json())
      .then(data => Array.isArray(data) && setIdeas(data))
      .catch(() => {});
  }, []);

  // Estado del agente PC (heartbeat)
  useEffect(() => {
    if (!token) return;

    let mounted = true;
    async function loadAgent() {
      try {
        const r = await fetch(`${API}/agents/pc-mikel`, { headers: { "Authorization": `Bearer ${token}` } });
        const data = await r.json();
        console.log("[AGENT] estado:", data);
        if (mounted) setAgentState(data);
      } catch (e) {
        console.error("[AGENT] error:", e);
        if (mounted) setAgentState({ status: "offline", offline: true });
      }
    }

    loadAgent();
    const id = setInterval(loadAgent, 10000);
    return () => { mounted = false; clearInterval(id); };
  }, [token]);

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
        const res = await fetch(`${API}/ideas/audio`, { method: "POST", headers: { "Authorization": `Bearer ${t}` }, body: fd });
        const data = await res.json();
        if (data.ok) setIdeas(prev => [data.idea, ...prev]);
      } catch {}
      setProcessing(false);
    };
    mr.start();
    mediaRecorderRef.current = mr;
    setRecording(true);
  }
  function stopRecording() { mediaRecorderRef.current?.stop(); setRecording(false); }

  async function fetchDeparture(ev) {
    if (!ev?.loc || !ev?.start) return;
    const key = ev.id || ev.start;
    setDepartureLoadingId(key);
    try {
      const t = localStorage.getItem("la_token") || "";
      const res = await fetch(`${API}/maps/departure`, {
        method: "POST",
        headers: { "Authorization": `Bearer ${t}`, "Content-Type": "application/json" },
        body: JSON.stringify({ destination: ev.loc, event_time: ev.start }),
      });
      const data = await res.json();
      setDepartureMap(prev => ({ ...prev, [key]: data }));
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
    return (
      <div style={{ marginTop: 6 }}>
        {!info && !isLoading && (
          <button onClick={e => { e.stopPropagation(); fetchDeparture(ev); }} style={{
            background: "rgba(200,169,110,0.12)", border: "0.5px solid rgba(200,169,110,0.3)",
            borderRadius: 6, color: "var(--accent)", fontSize: 11, padding: "4px 10px",
            cursor: "pointer", fontFamily: "'DM Sans', sans-serif", letterSpacing: "0.04em",
          }}>¿A qué hora salir?</button>
        )}
        {isLoading && <div style={{ fontSize: 11, color: "var(--muted)" }}>Calculando ruta...</div>}
        {info && !info.error && (
          <div style={{ fontSize: 12, color: "var(--text)", lineHeight: 1.6 }}>
            <span style={{ color: "var(--accent)", fontFamily: "'DM Mono', monospace", fontSize: 13 }}>
              Salir a las {info.departure_time}
            </span>
            <span style={{ color: "var(--muted)", marginLeft: 8 }}>
              {info.duration_text} · {info.distance_text}
            </span>
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
        await fetch(`${API}/wake-pc`, {
          method: "POST",
          headers: { "Authorization": `Bearer ${t}` },
        });
      } catch {
        // best-effort, no bloquea el flujo
      }

      // 2. Crear job en Supabase via backend — esto sí es crítico
      const jobRes = await fetch(`${API}/jobs`, {
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
      setWolStartedAt(Date.now());
    } catch {
      setWolStatus("error");
    }
  }

  async function deleteIdea(id) {
    const t = localStorage.getItem("la_token") || "";
    await fetch(`${API}/ideas/${id}`, { method: "DELETE", headers: { "Authorization": `Bearer ${t}` } });
    setIdeas(prev => prev.filter(i => i.id !== id));
  }

  async function loadTraining() {
    const t = localStorage.getItem("la_token") || "";
    try {
      const r = await fetch(`${API}/training/summary`, { headers: { "Authorization": `Bearer ${t}` } });
      const data = await r.json();
      setTraining(data);
    } catch {}
  }

  async function submitSession() {
    if (trainingLoading) return;
    setTrainingLoading(true);
    const t = localStorage.getItem("la_token") || "";
    try {
      await fetch(`${API}/training/sessions`, {
        method: "POST",
        headers: { "Authorization": `Bearer ${t}`, "Content-Type": "application/json" },
        body: JSON.stringify({ date: sessionDate, duration_hours: parseFloat(sessionHours) }),
      });
      setShowSessionForm(false);
      await loadTraining();
    } catch {}
    setTrainingLoading(false);
  }

  async function deleteTrainingSession(sessionId) {
    const t = localStorage.getItem("la_token") || "";
    await fetch(`${API}/training/sessions/${sessionId}`, { method: "DELETE", headers: { "Authorization": `Bearer ${t}` } });
    await loadTraining();
  }

  async function updateTrainingClient(patch) {
    if (trainingSettingsSaving) return;
    setTrainingSettingsSaving(true);
    const t = localStorage.getItem("la_token") || "";
    try {
      await fetch(`${API}/training/client`, {
        method: "PATCH",
        headers: { "Authorization": `Bearer ${t}`, "Content-Type": "application/json" },
        body: JSON.stringify(patch),
      });
      await loadTraining();
    } catch {}
    setTrainingSettingsSaving(false);
  }

  async function submitPayment() {
    if (trainingLoading) return;
    setTrainingLoading(true);
    const t = localStorage.getItem("la_token") || "";
    const today = new Date().toISOString().slice(0, 10);
    try {
      await fetch(`${API}/training/payments`, {
        method: "POST",
        headers: { "Authorization": `Bearer ${t}`, "Content-Type": "application/json" },
        body: JSON.stringify({ date: today }),
      });
      await loadTraining();
    } catch {}
    setTrainingLoading(false);
  }

  function saveWidgetConfig(cfg) {
    setWidgetConfig(cfg);
    localStorage.setItem("la_widget_config", JSON.stringify(cfg));
  }
  function toggleWidget(id) {
    saveWidgetConfig(widgetConfig.map(w => w.id === id ? { ...w, visible: !w.visible } : w));
  }
  function moveWidget(id, dir) {
    const idx = widgetConfig.findIndex(w => w.id === id);
    if (idx + dir < 0 || idx + dir >= widgetConfig.length) return;
    const cfg = [...widgetConfig];
    [cfg[idx], cfg[idx + dir]] = [cfg[idx + dir], cfg[idx]];
    saveWidgetConfig(cfg);
  }
  function resetWidgetSize(id) {
    saveWidgetConfig(widgetConfig.map(w => w.id === id ? { ...w, width: undefined, height: undefined } : w));
  }

  function handleDividerDrag(e) {
    e.preventDefault();
    const containerEl = document.getElementById("widget-grid-container");
    if (!containerEl) return;
    const startX = e.clientX;
    const containerW = containerEl.offsetWidth;
    const startSplit = colSplitRef.current;
    document.body.classList.add("resizing");

    function onMouseMove(me) {
      const delta = (me.clientX - startX) / containerW;
      const newSplit = Math.max(0.08, Math.min(0.92, startSplit + delta));
      colSplitRef.current = newSplit;
      setColSplit(newSplit);
    }
    function onMouseUp() {
      document.body.classList.remove("resizing");
      localStorage.setItem("la_column_split", String(colSplitRef.current));
      window.removeEventListener("mousemove", onMouseMove);
      window.removeEventListener("mouseup", onMouseUp);
    }
    window.addEventListener("mousemove", onMouseMove);
    window.addEventListener("mouseup", onMouseUp);
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
      saveWidgetConfig(widgetConfig.map(c => c.id === wid ? { ...c, width: w, height: h } : c));
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
      const dividerX = rect.left + rect.width * colSplitRef.current;
      const targetCol = me.clientX < dividerX ? "left" : "right";

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
          fetch(`${API}/jobs/${activeJobId}/events`, { headers: { "Authorization": `Bearer ${t}` } }),
          fetch(`${API}/jobs/by-id/${activeJobId}`, { headers: { "Authorization": `Bearer ${t}` } }),
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
      } catch {}
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

  const entregas = allEvents
    .filter(e => e.title && e.title.includes("📚") && isFuture(e.start))
    .map(e => ({ title: e.title.replace("📚", "").trim(), subject: e.title, days: daysUntil(e.start), alud_url: e.alud_url || null }))
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
  const wolEtaSeconds = wolStartedAt ? Math.max(0, 90 - Math.floor((Date.now() - wolStartedAt) / 1000)) : null;

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
                  <div style={s.eventDetailTime}>{displayActive.time}</div>
                </div>
              )}
            </>
          )}
        </div>
      );
      case "upcoming": return (
        <div style={cardStyle} data-card={id} key="upcoming">
          <div style={s.sectionLabel}>Próximos eventos</div>
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
              <div style={{ color: "var(--muted)", fontSize: 13 }}>Sin entregas con 📚 en el título</div>
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
                  <span style={{ fontFamily: "'DM Mono', monospace", fontSize: 26, color: barColor, lineHeight: 1 }}>{sess}</span>
                  <span style={{ fontSize: 12, color: "var(--muted)" }}>/ {spp} sesiones</span>
                  <span style={{ marginLeft: "auto", fontFamily: "'DM Mono', monospace", fontSize: 15, color: warn ? "#d4645a" : "var(--text)" }}>{amount_owed}€</span>
                </div>
                <div style={{ height: 2, background: "var(--border)", borderRadius: 1, marginBottom: 8 }}>
                  <div style={{ height: "100%", borderRadius: 1, background: barColor, width: `${pct}%`, transition: "width 0.4s" }} />
                </div>
                <div style={{ fontSize: 11, color: "var(--muted)", marginBottom: 10, lineHeight: 1.7 }}>
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
          <button style={{ ...s.newIdeaBtn, ...(recording ? { borderColor: "#d4645a", color: "#d4645a" } : {}) }}
            onClick={recording ? stopRecording : startRecording} disabled={processing}>
            {processing ? "Procesando..." : recording ? "⏹ Parar grabación" : "● Grabar idea"}
          </button>
        </div>
      );
      case "health_wellness": {
        // ── datos base ──
        const wSleepEff = d => {
          if (d.value && d.value > 0) return d.value;
          if (d.extra?.asleep > 0) return Number(d.extra.asleep);
          return (Number(d.extra?.deep)||0)+(Number(d.extra?.rem)||0)+(Number(d.extra?.light)||0)+(Number(d.extra?.core)||0);
        };
        const wSleepRaw  = findMetric(healthData, "sleep_analysis", "sleep").map(d => ({ ...d, value: wSleepEff(d) }));
        const wStepsRaw  = findMetric(healthData, "step_count", "steps");
        const wHrvRaw    = findMetric(healthData, "heart_rate_variability", "heartRateVariability");
        const wWorkRaw   = findMetric(healthData, "workouts");

        const last7Sleep  = wSleepRaw.slice(-7);
        const last7Steps  = wStepsRaw.slice(-7);
        const last7Hrv    = wHrvRaw.slice(-7);
        const last7Work   = wWorkRaw.filter(d => {
          const daysAgo = (new Date() - new Date(d.date + "T12:00:00")) / 86400000;
          return daysAgo <= 7;
        });

        const avgSleep   = last7Sleep.length  ? last7Sleep.reduce((s,d)=>s+(d.value||0),0)/last7Sleep.length  : null;
        const avgSteps   = last7Steps.length  ? last7Steps.reduce((s,d)=>s+(d.value||0),0)/last7Steps.length  : null;
        const avgHrv     = last7Hrv.length    ? last7Hrv.reduce((s,d)=>s+(d.value||0),0)/last7Hrv.length      : null;
        const prevHrv    = wHrvRaw.slice(-14,-7);
        const avgHrvPrev = prevHrv.length     ? prevHrv.reduce((s,d)=>s+(d.value||0),0)/prevHrv.length        : null;

        // Entrenamientos: contar workouts únicos de los últimos 7 días
        const weekWorkoutCount = last7Work.reduce((sum, d) => sum + (d.extra?.workouts?.length || 0), 0);
        const allWorkoutDates  = wWorkRaw.flatMap(d => (d.extra?.workouts||[]).map(w => (w.start||"").slice(0,10))).filter(Boolean).sort();
        const lastWorkoutDate  = allWorkoutDates[allWorkoutDates.length - 1];
        const daysSinceWorkout = lastWorkoutDate ? Math.floor((new Date() - new Date(lastWorkoutDate + "T12:00:00")) / 86400000) : null;

        // ── puntuación semanal ──
        let score = 0;
        // Sueño (35 pts)
        if (avgSleep != null) {
          if      (avgSleep >= 7.5) score += 35;
          else if (avgSleep >= 7)   score += 30;
          else if (avgSleep >= 6.5) score += 22;
          else if (avgSleep >= 6)   score += 14;
          else                      score += 6;
        }
        // Entrenamientos (35 pts) — objetivo: 4/semana
        if      (weekWorkoutCount >= 4) score += 35;
        else if (weekWorkoutCount === 3) score += 24;
        else if (weekWorkoutCount === 2) score += 14;
        else if (weekWorkoutCount === 1) score += 6;
        // Pasos (20 pts)
        if (avgSteps != null) {
          if      (avgSteps >= 10000) score += 20;
          else if (avgSteps >= 8000)  score += 16;
          else if (avgSteps >= 6000)  score += 11;
          else if (avgSteps >= 4000)  score += 6;
          else                        score += 2;
        }
        // HRV (10 pts)
        if (avgHrv != null && avgHrvPrev != null) {
          if      (avgHrv >= avgHrvPrev * 1.05) score += 10;
          else if (avgHrv >= avgHrvPrev * 0.95) score += 7;
          else                                   score += 3;
        } else if (avgHrv != null) score += 5;

        const scoreLabel = score >= 80 ? "Semana excelente" : score >= 65 ? "Buena semana" : score >= 50 ? "Semana regular" : "Semana floja";
        const scoreColor = score >= 80 ? "var(--green)" : score >= 65 ? "#6aaa82" : score >= 50 ? "var(--accent)" : "#d4645a";

        // ── insights ──
        const insights = [];
        if (avgSleep != null) {
          const goodNights = last7Sleep.filter(d => d.value >= 7).length;
          if      (avgSleep >= 7.5) insights.push({ icon: "😴", color: "var(--green)", text: `Sueño excelente — media de ${hoursToHM(avgSleep)}, ${goodNights} noches >7h` });
          else if (avgSleep >= 7)   insights.push({ icon: "😴", color: "#6aaa82",     text: `Sueño bueno — media de ${hoursToHM(avgSleep)}` });
          else if (avgSleep >= 6)   insights.push({ icon: "😴", color: "var(--accent)", text: `Sueño justo — media de ${hoursToHM(avgSleep)}. Intenta acostarte antes` });
          else                      insights.push({ icon: "😴", color: "#d4645a",     text: `Sueño insuficiente — media de ${hoursToHM(avgSleep)}. Prioriza descansar` });
        }
        if (weekWorkoutCount > 0 || daysSinceWorkout != null) {
          const remaining = Math.max(0, 4 - weekWorkoutCount);
          if      (weekWorkoutCount >= 5) insights.push({ icon: "💪", color: "var(--green)",   text: `${weekWorkoutCount} entrenamientos esta semana — objetivo superado` });
          else if (weekWorkoutCount === 4) insights.push({ icon: "💪", color: "var(--green)",   text: `4/4 entrenamientos esta semana — objetivo cumplido` });
          else if (weekWorkoutCount === 3) insights.push({ icon: "💪", color: "#6aaa82",        text: `3/4 entrenamientos — te queda ${remaining} para llegar al objetivo` });
          else if (weekWorkoutCount === 2) insights.push({ icon: "💪", color: "var(--accent)",  text: `2/4 entrenamientos — te quedan ${remaining} esta semana` });
          else if (weekWorkoutCount === 1) insights.push({ icon: "💪", color: "#d4645a",        text: `1/4 entrenamientos — te quedan ${remaining} para cumplir el objetivo` });
          else if (daysSinceWorkout != null) insights.push({ icon: "💪", color: "#d4645a",      text: `0/4 entrenamientos esta semana — llevas ${daysSinceWorkout} días sin ir al gym` });
        }
        if (avgSteps != null) {
          if      (avgSteps >= 9000) insights.push({ icon: "🚶", color: "var(--green)",  text: `Muy activo — ${Math.round(avgSteps).toLocaleString("es")} pasos de media` });
          else if (avgSteps >= 6000) insights.push({ icon: "🚶", color: "#6aaa82",       text: `Actividad moderada — ${Math.round(avgSteps).toLocaleString("es")} pasos de media` });
          else                       insights.push({ icon: "🚶", color: "var(--accent)", text: `Poca actividad — ${Math.round(avgSteps).toLocaleString("es")} pasos. Intenta caminar más` });
        }
        if (avgHrv != null) {
          const hrvTrendUp = avgHrvPrev && avgHrv > avgHrvPrev * 1.03;
          const hrvTrendDn = avgHrvPrev && avgHrv < avgHrvPrev * 0.97;
          if      (hrvTrendUp) insights.push({ icon: "❤️", color: "var(--green)",  text: `HRV en subida (${Math.round(avgHrv)}ms) — buena recuperación` });
          else if (hrvTrendDn) insights.push({ icon: "❤️", color: "#d4645a",     text: `HRV bajando (${Math.round(avgHrv)}ms) — quizás necesitas más descanso` });
          else                 insights.push({ icon: "❤️", color: "var(--muted)", text: `HRV estable en ${Math.round(avgHrv)}ms` });
        }

        // ── recomendación de hoy ──
        let rec = null;
        if (daysSinceWorkout != null && daysSinceWorkout >= 2 && avgHrv && avgHrv > 50)
          rec = "Hoy es buen día para entrenar — llevas días de descanso y la recuperación es correcta.";
        else if (avgHrv && avgHrv < 45)
          rec = "Hoy mejor descanso activo — tu HRV indica que el cuerpo necesita recuperarse.";
        else if (avgSleep && avgSleep < 6.5)
          rec = "Esta semana el sueño ha sido escaso. Intenta acostarte 30 min antes esta noche.";
        else if (weekWorkoutCount >= 4)
          rec = "Semana intensa de entrenamiento. Asegúrate de incluir un día de descanso.";

        const hasAnyData = avgSleep != null || avgSteps != null || weekWorkoutCount > 0;

        return (
          <div style={cardStyle} data-card={id} key="health_wellness">
            <div style={{ ...s.sectionLabel, display: "flex", alignItems: "center", justifyContent: "space-between" }}>
              <span>Bienestar semanal</span>
              {hasAnyData && (
                <span style={{ fontFamily: "'DM Mono', monospace", fontSize: 12, color: scoreColor, letterSpacing: "0.04em", textTransform: "none" }}>
                  {score} — {scoreLabel}
                </span>
              )}
            </div>
            {healthLoading ? (
              <div style={{ color: "var(--muted)", fontSize: 13 }}>Cargando...</div>
            ) : !hasAnyData ? (
              <div style={{ color: "var(--muted)", fontSize: 13 }}>Sin datos todavía — los insights aparecerán cuando haya varios días de datos.</div>
            ) : (
              <>
                <div style={{ display: "flex", flexDirection: "column", gap: 8, marginBottom: rec ? 12 : 0 }}>
                  {insights.map((ins, i) => (
                    <div key={i} style={{ display: "flex", alignItems: "flex-start", gap: 10 }}>
                      <span style={{ fontSize: 16, lineHeight: 1.4, flexShrink: 0 }}>{ins.icon}</span>
                      <span style={{ fontSize: 13, color: "var(--text)", lineHeight: 1.5 }}>
                        <span style={{ color: ins.color, fontWeight: 500 }}>
                          {ins.text.split("—")[0]}
                        </span>
                        {ins.text.includes("—") && <span style={{ color: "var(--muted)" }}> — {ins.text.split("—").slice(1).join("—")}</span>}
                      </span>
                    </div>
                  ))}
                </div>
                {rec && (
                  <div style={{
                    marginTop: 4, padding: "10px 14px",
                    background: "rgba(200,169,110,0.06)", borderLeft: "2px solid var(--accent)",
                    borderRadius: "0 8px 8px 0", fontSize: 12, color: "var(--muted)", lineHeight: 1.6,
                  }}>
                    <span style={{ color: "var(--accent)", fontWeight: 500 }}>Hoy → </span>{rec}
                  </div>
                )}
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
        const sleepRaw  = findMetric(healthData, "sleep_analysis", "sleep");
        const sleepData = sleepRaw.map(d => ({ ...d, value: sleepEff(d) }));
        const last14    = sleepData.slice(-7);
        const last7     = sleepData.slice(-7);
        const avg7      = last7.length ? last7.reduce((s, d) => s + (d.value || 0), 0) / last7.length : null;
        const latest    = sleepData[sleepData.length - 1];
        const sleepColor = v => v >= 7 ? "var(--green)" : v >= 6 ? "var(--accent)" : "#d4645a";

        const lv  = latest?.value || 0;
        const ld  = latest?.extra?.deep  != null ? Number(latest.extra.deep)  : null;
        const lr  = latest?.extra?.rem   != null ? Number(latest.extra.rem)   : null;
        const lc  = latest?.extra?.core  != null ? Number(latest.extra.core)  : (latest?.extra?.light != null ? Number(latest.extra.light) : null);
        const law = latest?.extra?.awake != null ? Number(latest.extra.awake) : null;
        const score = latest ? sleepScore(lv, ld, lr, lc, law) : null;
        const scoreLabel = score == null ? null : score >= 85 ? "Excelente" : score >= 70 ? "Bueno" : score >= 55 ? "Regular" : "Mejorable";
        const scoreColor = score == null ? null : score >= 85 ? "var(--green)" : score >= 70 ? "#6aaa82" : score >= 55 ? "var(--accent)" : "#d4645a";

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
                <span style={{ fontFamily: "'DM Mono', monospace", fontSize: 11, color: scoreColor, letterSpacing: "0.04em", textTransform: "none" }}>
                  {score} — {scoreLabel}
                </span>
              )}
            </div>
            {healthLoading ? (
              <div style={{ color: "var(--muted)", fontSize: 13 }}>Cargando...</div>
            ) : last14.length === 0 ? (
              <div style={{ color: "var(--muted)", fontSize: 13 }}>Sin datos de sueño aún</div>
            ) : (
              <>
                {latest && (
                  <div style={{ display: "flex", alignItems: "baseline", gap: 8, marginBottom: 10 }}>
                    <span style={{ fontFamily: "'DM Mono', monospace", fontSize: 28, color: sleepColor(lv), lineHeight: 1 }}>
                      {hoursToHM(lv)}
                    </span>
                    <span style={{ fontSize: 11, color: "var(--muted)" }}>anoche</span>
                    {avg7 != null && (
                      <span style={{ marginLeft: "auto", fontSize: 11, color: "var(--muted)", fontFamily: "'DM Mono', monospace" }}>
                        media 7d: {hoursToHM(avg7)}
                      </span>
                    )}
                  </div>
                )}
                {latest?.extra && (ld != null || lr != null || lc != null) && (
                  <div style={{ display: "flex", gap: 10, marginBottom: 12, fontSize: 11, flexWrap: "wrap" }}>
                    {ld != null && (
                      <SleepStageTooltip label={STAGE_TIPS.deep.label} color={STAGE_TIPS.deep.color} tip={STAGE_TIPS.deep.tip}>
                        <span style={{ color: "var(--muted)" }}>
                          <span style={{ color: "#4a72b0" }}>●</span> Profundo{" "}
                          <b style={{ color: "var(--text)", fontFamily: "'DM Mono', monospace" }}>{hoursToHM(ld)}</b>
                        </span>
                      </SleepStageTooltip>
                    )}
                    {lr != null && (
                      <SleepStageTooltip label={STAGE_TIPS.rem.label} color={STAGE_TIPS.rem.color} tip={STAGE_TIPS.rem.tip}>
                        <span style={{ color: "var(--muted)" }}>
                          <span style={{ color: "#8b68c4" }}>●</span> REM{" "}
                          <b style={{ color: "var(--text)", fontFamily: "'DM Mono', monospace" }}>{hoursToHM(lr)}</b>
                        </span>
                      </SleepStageTooltip>
                    )}
                    {lc != null && (
                      <SleepStageTooltip label={STAGE_TIPS.core.label} color={STAGE_TIPS.core.color} tip={STAGE_TIPS.core.tip}>
                        <span style={{ color: "var(--muted)" }}>
                          <span style={{ color: "#4f8fa3" }}>●</span> Core{" "}
                          <b style={{ color: "var(--text)", fontFamily: "'DM Mono', monospace" }}>{hoursToHM(lc)}</b>
                        </span>
                      </SleepStageTooltip>
                    )}
                    {law != null && (
                      <SleepStageTooltip label={STAGE_TIPS.awake.label} color={STAGE_TIPS.awake.color} tip={STAGE_TIPS.awake.tip}>
                        <span style={{ color: "var(--muted)" }}>
                          <span style={{ color: "var(--muted2)" }}>●</span> Despierto{" "}
                          <b style={{ color: "var(--text)", fontFamily: "'DM Mono', monospace" }}>{hoursToHM(law)}</b>
                        </span>
                      </SleepStageTooltip>
                    )}
                  </div>
                )}
                {last14.length > 1 && (
                  <div style={{ display: "flex", gap: 5, marginTop: 4 }}>
                    {last14.map((d, i) => {
                      const sc = sleepScore(d.value, Number(d.extra?.deep)||0, Number(d.extra?.rem)||0, Number(d.extra?.core)||Number(d.extra?.light)||0, Number(d.extra?.awake)||0);
                      const c  = sc == null ? "var(--border2)" : sc >= 85 ? "var(--green)" : sc >= 70 ? "#6aaa82" : sc >= 55 ? "var(--accent)" : "#d4645a";
                      const date = new Date(d.date + "T12:00:00");
                      const day  = ["D","L","M","X","J","V","S"][date.getDay()];
                      return (
                        <div key={i} style={{ flex: 1, textAlign: "center" }} title={`${day}: ${hoursToHM(d.value)}${sc != null ? ` · ${sc}pts` : ""}`}>
                          <div style={{ height: 3, borderRadius: 2, background: c, opacity: 0.8 }} />
                          <div style={{ fontSize: 9, color: "var(--muted2)", marginTop: 3, fontFamily: "'DM Mono', monospace" }}>{day}</div>
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
                  <span style={{ fontFamily: "'DM Mono', monospace", fontSize: 28, color: "var(--accent)", lineHeight: 1 }}>
                    {latest?.value?.toFixed(0)}
                  </span>
                  <span style={{ fontSize: 11, color: "var(--muted)" }}>bpm</span>
                  {hrMin && hrMax && (
                    <span style={{ marginLeft: "auto", fontSize: 11, color: "var(--muted)", fontFamily: "'DM Mono', monospace" }}>
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
            <div style={s.sectionLabel}>HRV <span style={{ fontSize: 10, color: "var(--muted2)", textTransform: "none", letterSpacing: 0 }}>variabilidad cardíaca</span></div>
            {healthLoading ? (
              <div style={{ color: "var(--muted)", fontSize: 13 }}>Cargando...</div>
            ) : last30.length === 0 ? (
              <div style={{ color: "var(--muted)", fontSize: 13 }}>Sin datos de HRV aún</div>
            ) : (
              <>
                <div style={{ display: "flex", alignItems: "baseline", gap: 8, marginBottom: 8 }}>
                  <span style={{ fontFamily: "'DM Mono', monospace", fontSize: 28, color: "var(--accent2)", lineHeight: 1 }}>
                    {latest?.value?.toFixed(0)}
                  </span>
                  <span style={{ fontSize: 11, color: "var(--muted)" }}>ms</span>
                  {trend && <span style={{ fontSize: 18, color: trendColor, fontFamily: "'DM Mono', monospace" }}>{trend}</span>}
                  {avg7 != null && (
                    <span style={{ marginLeft: "auto", fontSize: 11, color: "var(--muted)", fontFamily: "'DM Mono', monospace" }}>
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
        const latest      = stepsData[stepsData.length - 1];
        const latestCal   = caloriesData[caloriesData.length - 1];
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
                  <span style={{ fontFamily: "'DM Mono', monospace", fontSize: 24, color: "var(--green)", lineHeight: 1 }}>
                    {(latest?.value || 0).toLocaleString("es")}
                  </span>
                  <span style={{ fontSize: 11, color: "var(--muted)" }}>pasos hoy</span>
                  {latestCal?.value && (
                    <span style={{ marginLeft: "auto", fontSize: 13, color: "var(--muted)", fontFamily: "'DM Mono', monospace" }}>
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
    const widthPx   = typeof cfg.width  === "number" ? `${cfg.width}px`  : "100%";
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

  if (!token) return <LoginScreen onLogin={() => window.location.reload()} />;

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
          <div style={s.greeting} className="header-greeting">
            {greeting}
            <strong style={s.greetingStrong}>Mikel</strong>
            <button onClick={() => {
              setTrainingSettingsPrice(String(training?.client?.price_per_hour ?? ""));
              setTrainingSettingsSpp(String(training?.client?.sessions_per_payment ?? ""));
              setShowSettings(true);
            }} style={{
              marginLeft: 14, background: "transparent", border: "0.5px solid rgba(255,255,255,0.12)",
              borderRadius: 7, color: "var(--muted)", fontSize: 14, cursor: "pointer",
              padding: "3px 8px", fontFamily: "inherit", lineHeight: 1,
            }} title="Ajustes de widgets">⚙</button>
          </div>
        </div>

        {/* GRID */}
        {(() => {
          const leftWidgets  = widgetConfig.filter(w => w.visible && (w.column || DEFAULT_COLUMNS[w.id] || "left") === "left");
          const rightWidgets = widgetConfig.filter(w => w.visible && (w.column || DEFAULT_COLUMNS[w.id] || "left") === "right");
          const leftPct  = Math.round(colSplit * 100);
          const rightPct = 100 - leftPct;
          return (
            <div
              id="widget-grid-container"
              style={{ display: "flex", gap: 0, flex: 1, alignItems: "stretch", position: "relative" }}
            >
              {/* LEFT COLUMN */}
              <div
                className="col-left"
                style={{
                  width: `calc(${leftPct}% - 8px)`,
                  display: "flex", flexDirection: "column", gap: 16,
                  outline: isEditMode && draggingId && dragOverId === "left" ? "2px solid rgba(200,169,110,0.5)" : "none",
                  borderRadius: 8, padding: isEditMode && draggingId && dragOverId === "left" ? 6 : 0,
                  transition: "outline 0.1s, padding 0.1s",
                }}
              >
                {leftWidgets.map(w => wrapResizable(w))}
                {isEditMode && draggingId && dragOverId === "left" && dragOverSide === "__end__" && (
                  <div style={{ height: 3, background: "var(--accent)", borderRadius: 2, opacity: 0.7 }} />
                )}
              </div>

              {/* DIVIDER */}
              <div
                className="col-divider"
                onMouseDown={handleDividerDrag}
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

              {/* RIGHT COLUMN */}
              <div
                className="col-right"
                style={{
                  width: `calc(${rightPct}% - 8px)`,
                  display: "flex", flexDirection: "column", gap: 16,
                  outline: isEditMode && draggingId && dragOverId === "right" ? "2px solid rgba(200,169,110,0.5)" : "none",
                  borderRadius: 8, padding: isEditMode && draggingId && dragOverId === "right" ? 6 : 0,
                  transition: "outline 0.1s, padding 0.1s",
                }}
              >
                {rightWidgets.map(w => wrapResizable(w))}
                {isEditMode && draggingId && dragOverId === "right" && dragOverSide === "__end__" && (
                  <div style={{ height: 3, background: "var(--accent)", borderRadius: 2, opacity: 0.7 }} />
                )}
              </div>

              {/* SNAP ZONE OVERLAY (edit mode drag) */}
              {isEditMode && draggingId && (
                <div style={{
                  position: "absolute", inset: 0, display: "flex",
                  pointerEvents: "none", zIndex: 50, borderRadius: 8, overflow: "hidden",
                }}>
                  <div style={{
                    flex: colSplit, background: dragOverId === "left" ? "rgba(200,169,110,0.08)" : "transparent",
                    border: dragOverId === "left" ? "2px solid rgba(200,169,110,0.4)" : "2px solid transparent",
                    borderRadius: "8px 0 0 8px", transition: "all 0.12s",
                    display: "flex", alignItems: "flex-end", justifyContent: "center", paddingBottom: 12,
                  }}>
                    {dragOverId === "left" && <span style={{ fontSize: 11, color: "var(--accent)", fontFamily: "'DM Mono'", opacity: 0.8 }}>← columna izquierda</span>}
                  </div>
                  <div style={{
                    flex: 1 - colSplit, background: dragOverId === "right" ? "rgba(200,169,110,0.08)" : "transparent",
                    border: dragOverId === "right" ? "2px solid rgba(200,169,110,0.4)" : "2px solid transparent",
                    borderRadius: "0 8px 8px 0", transition: "all 0.12s",
                    display: "flex", alignItems: "flex-end", justifyContent: "center", paddingBottom: 12,
                  }}>
                    {dragOverId === "right" && <span style={{ fontSize: 11, color: "var(--accent)", fontFamily: "'DM Mono'", opacity: 0.8 }}>columna derecha →</span>}
                  </div>
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
          }}>
            <div style={{ fontFamily: "'DM Mono', monospace", fontSize: 13, color: "var(--text)", marginBottom: 14, letterSpacing: "0.04em" }}>Widgets</div>
            <button onClick={() => { setShowSettings(false); setIsEditMode(true); }} style={{
              width: "100%", marginBottom: 14, padding: "9px 0",
              background: "rgba(200,169,110,0.1)", border: "0.5px solid rgba(200,169,110,0.35)",
              borderRadius: 8, color: "var(--accent)", fontSize: 12, cursor: "pointer",
              fontFamily: "'DM Sans', sans-serif", letterSpacing: "0.03em",
            }}>Editar distribución →</button>
            <div style={{ display: "flex", flexDirection: "column", gap: 5 }}>
              {widgetConfig.map((w, i) => (
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
                    <button onClick={() => moveWidget(w.id, 1)} disabled={i === widgetConfig.length - 1} style={{
                      background: "transparent", border: "none",
                      color: i === widgetConfig.length - 1 ? "rgba(255,255,255,0.15)" : "var(--muted)",
                      cursor: i === widgetConfig.length - 1 ? "default" : "pointer", fontSize: 13, padding: "2px 6px",
                    }}>↓</button>
                  </div>
                </div>
              ))}
            </div>
            {/* ── Sección entrenamiento ── */}
            <div style={{ borderTop: "0.5px solid var(--border)", marginTop: 16, paddingTop: 16 }}>
              <div style={{ fontFamily: "'DM Mono', monospace", fontSize: 11, color: "var(--muted2)", letterSpacing: "0.1em", textTransform: "uppercase", marginBottom: 12 }}>Entrenamiento</div>

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

            <button onClick={() => setShowSettings(false)} style={{
              marginTop: 18, width: "100%", padding: "9px 0",
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
  clock: { fontFamily: "'DM Mono', monospace", fontSize: 48, fontWeight: 400, letterSpacing: -2, color: "var(--text)", lineHeight: 1 },
  date: { fontSize: 13, color: "var(--muted)", marginTop: 4, letterSpacing: "0.05em", textTransform: "uppercase" },
  greeting: { fontSize: 13, color: "var(--muted)", textAlign: "right", fontFamily: "'DM Sans', sans-serif" },
  greetingStrong: { display: "block", fontSize: 16, color: "var(--accent)", fontWeight: 500, marginTop: 2 },
  mainGrid: { display: "grid", gridTemplateColumns: "1fr 320px", gap: 16, alignItems: "start", flex: 1 },
  leftCol:  { display: "flex", flexDirection: "column", gap: 16 },
  rightCol: { display: "flex", flexDirection: "column", gap: 16 },
  card: { background: "var(--surface)", border: "0.5px solid var(--border)", borderRadius: 12, padding: "16px 20px", boxSizing: "border-box", width: "100%" },
  sectionLabel: { fontSize: 10, fontWeight: 500, letterSpacing: "0.15em", textTransform: "uppercase", color: "var(--muted2)", marginBottom: 12 },
  timelineWrapper: { overflowX: "auto", paddingBottom: 4 },
  timeline: { display: "flex", alignItems: "flex-start", minWidth: 500, padding: "8px 0 16px", position: "relative" },
  timelineItem: { display: "flex", flexDirection: "column", alignItems: "center", flex: 1, position: "relative", cursor: "pointer" },
  connectorLine: { position: "absolute", top: 9, left: "50%", width: "100%", height: 0.5, background: "var(--node-line)", zIndex: 0 },
  node: { width: 18, height: 18, borderRadius: "50%", border: "1.5px solid var(--accent)", background: "var(--bg)", zIndex: 1, position: "relative", flexShrink: 0, transition: "all 0.2s", cursor: "pointer" },
  nodeActive: { background: "var(--accent)", animation: "nodeGlow 2s infinite" },
  nodePast: { borderColor: "var(--muted2)", background: "var(--muted2)", width: 12, height: 12, margin: "3px 0" },
  nodeFuture: { borderColor: "var(--border2)" },
  nodeLabel: { marginTop: 10, textAlign: "center", maxWidth: 80 },
  nodeTime:  { fontFamily: "'DM Mono', monospace", fontSize: 10, color: "var(--muted)" },
  nodeTitle: { fontSize: 11, color: "var(--text)", marginTop: 2, lineHeight: 1.3 },
  nodeTitleActive: { color: "var(--accent)", fontWeight: 500 },
  eventDetail: { background: "var(--surface2)", border: "0.5px solid var(--border2)", borderLeft: "2px solid var(--accent)", borderRadius: 8, padding: "12px 16px", marginTop: 4, display: "flex", justifyContent: "space-between", alignItems: "center" },
  eventDetailTitle: { fontSize: 15, fontWeight: 500, color: "var(--text)" },
  eventDetailSub:   { fontSize: 12, color: "var(--muted)", marginTop: 3 },
  eventDetailTime:  { fontFamily: "'DM Mono', monospace", fontSize: 20, color: "var(--accent)" },
  eventRow: { display: "flex", alignItems: "center", gap: 12, padding: "10px 12px", borderRadius: 8, border: "0.5px solid var(--border)", background: "var(--surface2)", cursor: "pointer" },
  eventDot: { width: 6, height: 6, borderRadius: "50%", background: "var(--accent2)", flexShrink: 0 },
  eventRowTime:  { fontFamily: "'DM Mono', monospace", fontSize: 11, color: "var(--muted)", minWidth: 80 },
  eventRowTitle: { fontSize: 13, color: "var(--text)", flex: 1 },
  eventRowLoc:   { fontSize: 11, color: "var(--muted)" },
  entregaRow: { display: "flex", alignItems: "center", gap: 12, padding: "12px 14px", borderRadius: 8, border: "0.5px solid var(--border)", background: "var(--surface2)", cursor: "pointer" },
  urgencyBar: { width: 3, height: 36, borderRadius: 2, flexShrink: 0 },
  entregaTitle:    { fontSize: 13, fontWeight: 500, color: "var(--text)" },
  entregaSubject:  { fontSize: 11, color: "var(--muted)", marginTop: 2 },
  entregaCountdown: { textAlign: "right", flexShrink: 0 },
  daysNum:  { fontFamily: "'DM Mono', monospace", fontSize: 20, fontWeight: 400, lineHeight: 1 },
  daysLabel: { fontSize: 10, color: "var(--muted)", display: "block", marginTop: 1 },
  ideaCard: { background: "var(--surface2)", border: "0.5px solid var(--border)", borderRadius: 8, padding: "12px 14px", cursor: "pointer" },
  ideaKey: { fontSize: 13, fontWeight: 500, color: "var(--text)", display: "flex", alignItems: "center", gap: 8, justifyContent: "space-between" },
  ideaTag: { fontSize: 10, color: "var(--muted)", background: "var(--surface)", padding: "2px 8px", borderRadius: 4, letterSpacing: "0.05em", flexShrink: 0 },
  ideaChevron: { fontSize: 10, color: "var(--muted2)", transition: "transform 0.3s", flexShrink: 0 },
  ideaFull: { fontSize: 12, color: "var(--muted)", marginTop: 8, lineHeight: 1.6 },
  newIdeaBtn: { width: "100%", marginTop: 10, padding: 8, background: "transparent", border: "0.5px dashed rgba(255,255,255,0.12)", borderRadius: 8, color: "#5a5850", fontSize: 12, cursor: "pointer", fontFamily: "'DM Sans', sans-serif", transition: "all 0.2s" },
  footer: { display: "flex", justifyContent: "space-between", alignItems: "center", paddingTop: 12, borderTop: "0.5px solid var(--border)", fontSize: 11, color: "var(--muted2)" },
  statusDot: { display: "inline-block", width: 6, height: 6, borderRadius: "50%", background: "var(--green)", marginRight: 6, animation: "pulse 2s infinite", verticalAlign: "middle" },
  appTabActive: { fontFamily: "'DM Mono', monospace", fontSize: 10, padding: "2px 8px", borderRadius: 4, background: "var(--accent)", color: "#0e0f11", letterSpacing: "0.05em", userSelect: "none" },
  appTabInactive: { fontFamily: "'DM Mono', monospace", fontSize: 10, padding: "2px 8px", borderRadius: 4, border: "0.5px solid var(--border2)", color: "var(--muted)", cursor: "pointer", letterSpacing: "0.05em", transition: "color 0.15s, border-color 0.15s" },
};


