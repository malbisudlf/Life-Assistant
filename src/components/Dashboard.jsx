import { useState, useEffect, useRef } from "react";

const API = "https://backend-tender-glow-160.fly.dev";

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

function isFuture(dateStr) {
  return new Date(dateStr) > new Date();
}

function isPast(dateStr) {
  return new Date(dateStr) < new Date();
}

function isActive(startStr, endStr) {
  const now = new Date();
  return new Date(startStr) <= now && new Date(endStr) >= now;
}

function daysUntil(dateStr) {
  const diff = new Date(dateStr) - new Date();
  return Math.ceil(diff / (1000 * 60 * 60 * 24));
}

function formatTime(dateStr) {
  const d = new Date(dateStr);
  return `${String(d.getHours()).padStart(2,"0")}:${String(d.getMinutes()).padStart(2,"0")}`;
}

function formatUpcomingTime(dateStr) {
  const d = new Date(dateStr);
  const now = new Date();
  const tomorrow = new Date(); tomorrow.setDate(now.getDate() + 1);
  const DAYS = ["Dom","Lun","Mar","Mié","Jue","Vie","Sáb"];
  if (isToday(dateStr)) return formatTime(dateStr);
  if (d.toDateString() === tomorrow.toDateString()) return `Mañana ${formatTime(dateStr)}`;
  return `${DAYS[d.getDay()]} ${formatTime(dateStr)}`;
}

const IDEAS_DEFAULT = [];

// ── HELPERS ──────────────────────────────────────────────────────
function urgencyColor(days) {
  if (days <= 3) return "#d4645a";
  if (days <= 7) return "#c8a45a";
  return "#6aaa82";
}

const DAYS_ES   = ["Domingo","Lunes","Martes","Miércoles","Jueves","Viernes","Sábado"];
const MONTHS_ES = ["enero","febrero","marzo","abril","mayo","junio","julio","agosto","septiembre","octubre","noviembre","diciembre"];

// ── ESTILOS GLOBALES (inyectados una sola vez) ────────────────────
const GLOBAL_CSS = `
  @import url('https://fonts.googleapis.com/css2?family=DM+Mono:wght@400;500&family=DM+Sans:wght@300;400;500&display=swap');

  *, *::before, *::after { box-sizing: border-box; margin: 0; padding: 0; }

  input, button, textarea, select { outline: none !important; box-shadow: none !important; -webkit-appearance: none; }

  :root {
    --bg:       #0e0f11;
    --surface:  #161719;
    --surface2: #1e1f22;
    --border:   rgba(255,255,255,0.07);
    --border2:  rgba(255,255,255,0.12);
    --text:     #e8e6e0;
    --muted:    #7a7870;
    --muted2:   #5a5850;
    --accent:   #c8a96e;
    --accent2:  #8bb4d4;
    --green:    #6aaa82;
    --node-line: rgba(200,169,110,0.3);
  }

  html, body, #root { height: 100%; background: var(--bg); }

  body {
    font-family: 'DM Sans', sans-serif;
    color: var(--text);
  }

  /* scrollbar */
  ::-webkit-scrollbar { width: 4px; height: 4px; }
  ::-webkit-scrollbar-track { background: transparent; }
  ::-webkit-scrollbar-thumb { background: var(--border2); border-radius: 2px; }

  @keyframes slideInRight {
    from { transform: translateX(100%); opacity: 0; }
    to   { transform: translateX(0);    opacity: 1; }
  }

  @keyframes fadeInOverlay {
    from { opacity: 0; }
    to   { opacity: 1; }
  }

  @keyframes pulse {
    0%, 100% { opacity: 1; }
    50%       { opacity: 0.4; }
  }

  @keyframes nodeGlow {
    0%, 100% { box-shadow: 0 0 8px rgba(200,169,110,0.4); }
    50%       { box-shadow: 0 0 16px rgba(200,169,110,0.7); }
  }

  @media (max-width: 640px) {
    .dashboard-grid { grid-template-columns: 1fr !important; }
    .clock { font-size: 36px !important; letter-spacing: -1px !important; }
    .dashboard-root { padding: 12px !important; gap: 12px !important; }
    .header-greeting { display: none !important; }
    .timeline-inner { min-width: 280px !important; }
  }
`;

// ── COMPONENTE PRINCIPAL ─────────────────────────────────────────
export default function Dashboard() {
  const [token, setToken]               = useState(() => localStorage.getItem("la_token") || "");
  const [now, setNow]                   = useState(new Date());
  const [activeEvent, setActiveEvent]   = useState(null);
  const [openIdea, setOpenIdea]         = useState(null);
  const [allEvents, setAllEvents]       = useState([]);
  const [loading, setLoading]           = useState(true);
  const [authNeeded, setAuthNeeded]     = useState(false);
  const [ideas, setIdeas]               = useState([]);
  const [recording, setRecording]       = useState(false);
  const [processing, setProcessing]     = useState(false);
  const [departureMap, setDepartureMap] = useState({});
  const [departureLoadingId, setDepartureLoadingId] = useState(null);
  const [classEvents, setClassEvents]   = useState([]);
  const [classesOpen, setClassesOpen]   = useState(false);
  const mediaRecorderRef                = useRef(null);
  const chunksRef                       = useRef([]);

  if (!token) return <LoginScreen onLogin={setToken} />;

  // Reloj
  useEffect(() => {
    const id = setInterval(() => setNow(new Date()), 30_000);
    return () => clearInterval(id);
  }, []);

  // Cargar eventos reales
  useEffect(() => {
    fetch(`${API}/calendar/events`, {
      headers: { "Authorization": `Bearer ${token}` },
    })
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
    fetch(`${API}/calendar/classes`, { headers: { "Authorization": `Bearer ${token}` } })
      .then(r => r.json())
      .then(data => Array.isArray(data.events) && setClassEvents(data.events))
      .catch(() => {});
  }, []);

  // Cargar ideas
  useEffect(() => {
    fetch(`${API}/ideas`, { headers: { "Authorization": `Bearer ${token}` } })
      .then(r => r.json())
      .then(data => Array.isArray(data) && setIdeas(data))
      .catch(() => {});
  }, []);

  // Grabación de audio
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
        const res = await fetch(`${API}/ideas/audio`, {
          method: "POST",
          headers: { "Authorization": `Bearer ${token}` },
          body: fd,
        });
        const data = await res.json();
        if (data.ok) setIdeas(prev => [data.idea, ...prev]);
      } catch {}
      setProcessing(false);
    };
    mr.start();
    mediaRecorderRef.current = mr;
    setRecording(true);
  }

  function stopRecording() {
    mediaRecorderRef.current?.stop();
    setRecording(false);
  }

  async function fetchDeparture(ev) {
    if (!ev?.loc || !ev?.start) return;
    const key = ev.id || ev.start;
    setDepartureLoadingId(key);
    try {
      const res = await fetch(`${API}/maps/departure`, {
        method: "POST",
        headers: { "Authorization": `Bearer ${token}`, "Content-Type": "application/json" },
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
    const loading = departureLoadingId === key;
    return (
      <div style={{ marginTop: 6 }}>
        {!info && !loading && (
          <button
            onClick={() => fetchDeparture(ev)}
            style={{
              background: "rgba(200,169,110,0.12)", border: "0.5px solid rgba(200,169,110,0.3)",
              borderRadius: 6, color: "var(--accent)", fontSize: 11, padding: "4px 10px",
              cursor: "pointer", fontFamily: "'DM Sans', sans-serif", letterSpacing: "0.04em",
            }}
          >
            ¿A qué hora salir?
          </button>
        )}
        {loading && <div style={{ fontSize: 11, color: "var(--muted)" }}>Calculando ruta...</div>}
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

  async function deleteIdea(id) {
    await fetch(`${API}/ideas/${id}`, {
      method: "DELETE",
      headers: { "Authorization": `Bearer ${token}` },
    });
    setIdeas(prev => prev.filter(i => i.id !== id));
  }

  // Eventos de hoy
  const todayEvents = allEvents
    .filter(e => isToday(e.start))
    .map(e => ({
      ...e,
      time: formatTime(e.start),
      title: e.title || "(Sin título)",
      loc: e.location || "",
      past: isPast(e.end),
      active: isActive(e.start, e.end),
    }));

  // Próximos eventos (no hoy, próximos 7 días)
  const upcomingEvents = allEvents
    .filter(e => !isToday(e.start) && isFuture(e.start) && daysUntil(e.start) <= 7)
    .slice(0, 5)
    .map(e => ({
      ...e,
      time: formatUpcomingTime(e.start),
      title: e.title || "(Sin título)",
      loc: e.location || "",
    }));

  // Entregas (📚 en el título)
  const entregas = allEvents
    .filter(e => e.title && e.title.includes("📚") && isFuture(e.start))
    .map(e => ({
      title: e.title.replace("📚", "").trim(),
      subject: e.title,
      days: daysUntil(e.start),
    }))
    .sort((a, b) => a.days - b.days);

  // Evento activo (o el primero de hoy)
  const displayActive = activeEvent || todayEvents.find(e => e.active) || todayEvents[0];

  // Inyectar CSS global una sola vez
  useEffect(() => {
    if (document.getElementById("dashboard-global-css")) return;
    const style = document.createElement("style");
    style.id = "dashboard-global-css";
    style.textContent = GLOBAL_CSS;
    document.head.appendChild(style);
  }, []);

  const hh      = String(now.getHours()).padStart(2, "0");
  const mm      = String(now.getMinutes()).padStart(2, "0");
  const dateStr = `${DAYS_ES[now.getDay()]}, ${now.getDate()} de ${MONTHS_ES[now.getMonth()]} de ${now.getFullYear()}`;
  const hour    = now.getHours();
  const greeting = hour < 13 ? "Buenos días" : hour < 20 ? "Buenas tardes" : "Buenas noches";

  return (
    <div style={s.dashboard} className="dashboard-root">

      {/* ── HEADER ── */}
      <div style={s.header}>
        <div>
          <div style={s.clock} className="clock">{hh}:{mm}</div>
          <div style={s.date}>{dateStr}</div>
        </div>
        <div style={s.greeting} className="header-greeting">
          {greeting}
          <strong style={s.greetingStrong}>Mikel</strong>
        </div>
      </div>

      {/* ── MAIN GRID ── */}
      <div style={s.mainGrid} className="dashboard-grid">

        {/* COL IZQUIERDA */}
        <div style={s.leftCol}>

          {/* Timeline */}
          <div style={s.card}>
            <div style={s.sectionLabel}>Hoy</div>
            {loading ? (
              <div style={{ color: "var(--muted)", fontSize: 13, padding: "16px 0" }}>Cargando eventos...</div>
            ) : authNeeded ? (
              <div style={{ color: "var(--muted)", fontSize: 13, padding: "8px 0" }}>
                <a href="http://localhost:8000/auth/login" target="_blank" rel="noreferrer"
                  style={{ color: "var(--accent)", textDecoration: "none" }}>
                  → Conectar Outlook
                </a>
              </div>
            ) : todayEvents.length === 0 ? (
              <div style={{ color: "var(--muted)", fontSize: 13, padding: "8px 0" }}>Sin eventos hoy</div>
            ) : (
              <>
                <div style={s.timelineWrapper}>
                  <div style={s.timeline} className="timeline-inner">
                    {todayEvents.map((ev, i) => (
                      <div key={i} style={s.timelineItem} onClick={() => setActiveEvent(ev)}>
                        {i < todayEvents.length - 1 && <div style={s.connectorLine} />}
                        <div style={{
                          ...s.node,
                          ...(ev.active ? s.nodeActive : {}),
                          ...(ev.past   ? s.nodePast   : {}),
                          ...(!ev.active && !ev.past ? s.nodeFuture : {}),
                        }} />
                        <div style={s.nodeLabel}>
                          <div style={s.nodeTime}>{ev.time}</div>
                          <div style={{ ...s.nodeTitle, ...(ev.active ? s.nodeTitleActive : {}) }}>
                            {ev.title}
                          </div>
                        </div>
                      </div>
                    ))}
                    {/* Nodo especial de Clases */}
                    {classEvents.filter(e => isToday(e.start)).length > 0 && (
                      <div style={s.timelineItem} onClick={() => setClassesOpen(true)}>
                        <div style={{
                          ...s.node,
                          background: "#8bb4d4",
                          boxShadow: "0 0 8px rgba(139,180,212,0.5)",
                          cursor: "pointer",
                        }} />
                        <div style={s.nodeLabel}>
                          <div style={s.nodeTime}>🎓</div>
                          <div style={{ ...s.nodeTitle, color: "var(--accent2)" }}>
                            Clases ({classEvents.filter(e => isToday(e.start)).length})
                          </div>
                        </div>
                      </div>
                    )}
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

          {/* Próximos eventos */}
          <div style={s.card}>
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
        </div>

        {/* COL DERECHA */}
        <div style={s.rightCol}>

          {/* Entregas */}
          <div style={s.card}>
            <div style={s.sectionLabel}>Entregas pendientes</div>
            <div style={{ display: "flex", flexDirection: "column", gap: 8, marginTop: 4 }}>
              {entregas.length === 0 ? (
                <div style={{ color: "var(--muted)", fontSize: 13 }}>Sin entregas con 📚 en el título</div>
              ) : entregas.map((e, i) => {
                const color = urgencyColor(e.days);
                return (
                  <div key={i} style={s.entregaRow}>
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

          {/* Ideas */}
          <div style={s.card}>
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
                <div
                  key={idea.id || i}
                  style={s.ideaCard}
                  onClick={() => setOpenIdea(openIdea === i ? null : i)}
                >
                  <div style={s.ideaKey}>
                    <span style={{ flex: 1 }}>{idea.key}</span>
                    <div style={{ display: "flex", gap: 6, alignItems: "center", flexShrink: 0 }}>
                      <span style={s.ideaTag}>{idea.tag}</span>
                      <span
                        style={{ fontSize: 10, color: "var(--muted2)", cursor: "pointer", padding: "0 4px" }}
                        onClick={e => { e.stopPropagation(); deleteIdea(idea.id); }}
                      >✕</span>
                      <span style={{
                        ...s.ideaChevron,
                        transform: openIdea === i ? "rotate(90deg)" : "rotate(0deg)",
                      }}>▶</span>
                    </div>
                  </div>
                  {openIdea === i && (
                    <div style={s.ideaFull}>{idea.full_text}</div>
                  )}
                </div>
              ))}
            </div>

            <button
              style={{
                ...s.newIdeaBtn,
                ...(recording ? { borderColor: "#d4645a", color: "#d4645a" } : {}),
              }}
              onClick={recording ? stopRecording : startRecording}
              disabled={processing}
            >
              {processing ? "Procesando..." : recording ? "⏹ Parar grabación" : "● Grabar idea"}
            </button>
          </div>
        </div>
      </div>

      {/* ── FOOTER ── */}
      <div style={s.footer}>
        <span>
          <span style={s.statusDot} />
          {loading ? "Cargando..." : authNeeded ? "Outlook no conectado" : `${allEvents.length} eventos cargados`}
        </span>
        <span>Life Assistant v0.1</span>
      </div>
    </div>

    {/* ── PANEL LATERAL DE CLASES ── */}
    {classesOpen && (
      <>
        {/* Overlay */}
        <div
          onClick={() => setClassesOpen(false)}
          style={{
            position: "fixed", inset: 0,
            background: "rgba(0,0,0,0.55)",
            backdropFilter: "blur(4px)",
            zIndex: 100,
            animation: "fadeInOverlay 0.25s ease",
          }}
        />
        {/* Panel */}
        <div style={{
          position: "fixed", top: 0, right: 0, bottom: 0,
          width: "min(420px, 92vw)",
          background: "#161719",
          borderLeft: "0.5px solid rgba(255,255,255,0.08)",
          zIndex: 101,
          display: "flex", flexDirection: "column",
          animation: "slideInRight 0.3s cubic-bezier(0.22,1,0.36,1)",
          boxShadow: "-20px 0 60px rgba(0,0,0,0.4)",
        }}>
          {/* Header del panel */}
          <div style={{
            display: "flex", alignItems: "center", justifyContent: "space-between",
            padding: "24px 24px 16px",
            borderBottom: "0.5px solid rgba(255,255,255,0.07)",
          }}>
            <div>
              <div style={{ fontFamily: "'DM Mono', monospace", fontSize: 16, color: "var(--accent2)" }}>
                🎓 Clases de hoy
              </div>
              <div style={{ fontSize: 11, color: "var(--muted)", marginTop: 2 }}>
                {classEvents.filter(e => isToday(e.start)).length} clases
              </div>
            </div>
            <button
              onClick={() => setClassesOpen(false)}
              style={{
                background: "none", border: "none", color: "var(--muted)",
                fontSize: 20, cursor: "pointer", padding: "4px 8px",
                borderRadius: 6, lineHeight: 1,
                transition: "color 0.15s",
              }}
              onMouseEnter={e => e.target.style.color = "var(--text)"}
              onMouseLeave={e => e.target.style.color = "var(--muted)"}
            >×</button>
          </div>

          {/* Timeline de clases */}
          <div style={{ flex: 1, overflowY: "auto", padding: "20px 24px" }}>
            <div style={{ display: "flex", flexDirection: "column", position: "relative" }}>
              {classEvents
                .filter(e => isToday(e.start))
                .sort((a, b) => new Date(a.start) - new Date(b.start))
                .map((ev, i, arr) => {
                  const past   = isPast(ev.end);
                  const active = isActive(ev.start, ev.end);
                  const nodeColor = active ? "var(--accent2)" : past ? "var(--muted2)" : "#8bb4d4";
                  return (
                    <div key={ev.id || i} style={{ display: "flex", gap: 16, position: "relative", paddingBottom: i < arr.length - 1 ? 24 : 0 }}>
                      {/* Línea vertical */}
                      {i < arr.length - 1 && (
                        <div style={{
                          position: "absolute", left: 7, top: 18,
                          width: 1, bottom: 0,
                          background: "rgba(139,180,212,0.2)",
                        }} />
                      )}
                      {/* Nodo */}
                      <div style={{ flexShrink: 0, marginTop: 2 }}>
                        <div style={{
                          width: 15, height: 15, borderRadius: "50%",
                          background: nodeColor,
                          boxShadow: active ? "0 0 10px rgba(139,180,212,0.7)" : "none",
                          animation: active ? "nodeGlow 2s infinite" : "none",
                          border: `1.5px solid ${nodeColor}`,
                        }} />
                      </div>
                      {/* Contenido */}
                      <div style={{ flex: 1 }}>
                        <div style={{ display: "flex", alignItems: "baseline", gap: 8, marginBottom: 4 }}>
                          <span style={{
                            fontFamily: "'DM Mono', monospace", fontSize: 12,
                            color: active ? "var(--accent2)" : "var(--muted)",
                          }}>{formatTime(ev.start)} – {formatTime(ev.end)}</span>
                          {active && (
                            <span style={{
                              fontSize: 9, background: "rgba(139,180,212,0.15)",
                              color: "var(--accent2)", borderRadius: 4, padding: "1px 6px",
                              letterSpacing: "0.06em", textTransform: "uppercase",
                            }}>En curso</span>
                          )}
                        </div>
                        <div style={{
                          fontSize: 14, fontWeight: 500,
                          color: past ? "var(--muted)" : "var(--text)",
                          marginBottom: ev.location ? 2 : 0,
                        }}>{ev.title}</div>
                        {ev.location && (
                          <div style={{ fontSize: 11, color: "var(--muted)", marginBottom: 4 }}>
                            📍 {ev.location}
                          </div>
                        )}
                        <DepartureWidget ev={{ ...ev, loc: ev.location, start: ev.start }} />
                      </div>
                    </div>
                  );
                })}
            </div>
          </div>
        </div>
      </>
    )}
  );
}

// ── ESTILOS JS ───────────────────────────────────────────────────
const s = {
  dashboard: {
    display: "flex",
    flexDirection: "column",
    minHeight: "100vh",
    padding: 20,
    gap: 16,
    background: "var(--bg)",
  },
  header: {
    display: "flex",
    justifyContent: "space-between",
    alignItems: "flex-end",
    paddingBottom: 16,
    borderBottom: "0.5px solid var(--border)",
  },
  clock: {
    fontFamily: "'DM Mono', monospace",
    fontSize: 48,
    fontWeight: 400,
    letterSpacing: -2,
    color: "var(--text)",
    lineHeight: 1,
  },
  date: {
    fontSize: 13,
    color: "var(--muted)",
    marginTop: 4,
    letterSpacing: "0.05em",
    textTransform: "uppercase",
  },
  greeting: {
    fontSize: 13,
    color: "var(--muted)",
    textAlign: "right",
    fontFamily: "'DM Sans', sans-serif",
  },
  greetingStrong: {
    display: "block",
    fontSize: 16,
    color: "var(--accent)",
    fontWeight: 500,
    marginTop: 2,
  },
  mainGrid: {
    display: "grid",
    gridTemplateColumns: "1fr 320px",
    gap: 16,
    alignItems: "start",
    flex: 1,
  },
  leftCol:  { display: "flex", flexDirection: "column", gap: 16 },
  rightCol: { display: "flex", flexDirection: "column", gap: 16 },
  card: {
    background: "var(--surface)",
    border: "0.5px solid var(--border)",
    borderRadius: 12,
    padding: "16px 20px",
  },
  sectionLabel: {
    fontSize: 10,
    fontWeight: 500,
    letterSpacing: "0.15em",
    textTransform: "uppercase",
    color: "var(--muted2)",
    marginBottom: 12,
  },

  // Timeline
  timelineWrapper: { overflowX: "auto", paddingBottom: 4 },
  timeline: {
    display: "flex",
    alignItems: "flex-start",
    minWidth: 500,
    padding: "8px 0 16px",
    position: "relative",
  },
  timelineItem: {
    display: "flex",
    flexDirection: "column",
    alignItems: "center",
    flex: 1,
    position: "relative",
    cursor: "pointer",
  },
  connectorLine: {
    position: "absolute",
    top: 9,
    left: "50%",
    width: "100%",
    height: 0.5,
    background: "var(--node-line)",
    zIndex: 0,
  },
  node: {
    width: 18,
    height: 18,
    borderRadius: "50%",
    border: "1.5px solid var(--accent)",
    background: "var(--bg)",
    zIndex: 1,
    position: "relative",
    flexShrink: 0,
    transition: "all 0.2s",
    cursor: "pointer",
  },
  nodeActive: {
    background: "var(--accent)",
    animation: "nodeGlow 2s infinite",
  },
  nodePast: {
    borderColor: "var(--muted2)",
    background: "var(--muted2)",
    width: 12,
    height: 12,
    margin: "3px 0",
  },
  nodeFuture: {
    borderColor: "var(--border2)",
  },
  nodeLabel: { marginTop: 10, textAlign: "center", maxWidth: 80 },
  nodeTime:  { fontFamily: "'DM Mono', monospace", fontSize: 10, color: "var(--muted)" },
  nodeTitle: { fontSize: 11, color: "var(--text)", marginTop: 2, lineHeight: 1.3 },
  nodeTitleActive: { color: "var(--accent)", fontWeight: 500 },

  // Event detail
  eventDetail: {
    background: "var(--surface2)",
    border: "0.5px solid var(--border2)",
    borderLeft: "2px solid var(--accent)",
    borderRadius: 8,
    padding: "12px 16px",
    marginTop: 4,
    display: "flex",
    justifyContent: "space-between",
    alignItems: "center",
  },
  eventDetailTitle: { fontSize: 15, fontWeight: 500, color: "var(--text)" },
  eventDetailSub:   { fontSize: 12, color: "var(--muted)", marginTop: 3 },
  eventDetailTime:  { fontFamily: "'DM Mono', monospace", fontSize: 20, color: "var(--accent)" },

  // Event rows
  eventRow: {
    display: "flex",
    alignItems: "center",
    gap: 12,
    padding: "10px 12px",
    borderRadius: 8,
    border: "0.5px solid var(--border)",
    background: "var(--surface2)",
    cursor: "pointer",
  },
  eventDot:      { width: 6, height: 6, borderRadius: "50%", background: "var(--accent2)", flexShrink: 0 },
  eventRowTime:  { fontFamily: "'DM Mono', monospace", fontSize: 11, color: "var(--muted)", minWidth: 80 },
  eventRowTitle: { fontSize: 13, color: "var(--text)", flex: 1 },
  eventRowLoc:   { fontSize: 11, color: "var(--muted)" },

  // Entregas
  entregaRow: {
    display: "flex",
    alignItems: "center",
    gap: 12,
    padding: "12px 14px",
    borderRadius: 8,
    border: "0.5px solid var(--border)",
    background: "var(--surface2)",
    cursor: "pointer",
  },
  urgencyBar:      { width: 3, height: 36, borderRadius: 2, flexShrink: 0 },
  entregaTitle:    { fontSize: 13, fontWeight: 500, color: "var(--text)" },
  entregaSubject:  { fontSize: 11, color: "var(--muted)", marginTop: 2 },
  entregaCountdown: { textAlign: "right", flexShrink: 0 },
  daysNum:  { fontFamily: "'DM Mono', monospace", fontSize: 20, fontWeight: 400, lineHeight: 1 },
  daysLabel: { fontSize: 10, color: "var(--muted)", display: "block", marginTop: 1 },

  // Ideas
  ideaCard: {
    background: "var(--surface2)",
    border: "0.5px solid var(--border)",
    borderRadius: 8,
    padding: "12px 14px",
    cursor: "pointer",
  },
  ideaKey: {
    fontSize: 13,
    fontWeight: 500,
    color: "var(--text)",
    display: "flex",
    alignItems: "center",
    gap: 8,
    justifyContent: "space-between",
  },
  ideaTag: {
    fontSize: 10,
    color: "var(--muted)",
    background: "var(--surface)",
    padding: "2px 8px",
    borderRadius: 4,
    letterSpacing: "0.05em",
    flexShrink: 0,
  },
  ideaChevron: {
    fontSize: 10,
    color: "var(--muted2)",
    transition: "transform 0.3s",
    flexShrink: 0,
  },
  ideaFull: {
    fontSize: 12,
    color: "var(--muted)",
    marginTop: 8,
    lineHeight: 1.6,
  },
  newIdeaBtn: {
    width: "100%",
    marginTop: 10,
    padding: 8,
    background: "transparent",
    border: "0.5px dashed rgba(255,255,255,0.12)",
    borderRadius: 8,
    color: "#5a5850",
    fontSize: 12,
    cursor: "pointer",
    fontFamily: "'DM Sans', sans-serif",
    transition: "all 0.2s",
  },

  // Footer
  footer: {
    display: "flex",
    justifyContent: "space-between",
    alignItems: "center",
    paddingTop: 12,
    borderTop: "0.5px solid var(--border)",
    fontSize: 11,
    color: "var(--muted2)",
  },
  statusDot: {
    display: "inline-block",
    width: 6,
    height: 6,
    borderRadius: "50%",
    background: "var(--green)",
    marginRight: 6,
    animation: "pulse 2s infinite",
    verticalAlign: "middle",
  },
};
