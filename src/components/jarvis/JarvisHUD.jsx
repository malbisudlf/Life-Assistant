// La vista de Jarvis a pantalla completa: el reactor en el centro, la conversación
// debajo y la telemetría a los lados, con el aire del HUD de Iron Man.
//
// Vive en su propio fichero, como la zona dev, porque no es un widget: es otra forma de
// usar la aplicación, se carga en diferido y no comparte nada de la maqueta del
// dashboard. Lo que NO tiene es estado propio de la conversación: los mensajes, el envío,
// la confirmación, el dictado y la llamada son los de la tarjeta de Jarvis (Dashboard.jsx),
// así que lo que hables aquí sigue allí al salir y al revés. La lógica de qué se pinta
// está en src/lib/jarvisHud.js.
import React, { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  estadoHud, TEXTO_ESTADO, motorEsperado, nombreModelo, protocolosUsados,
  nombreProtocolo, trocearRespuesta, duracionTecleo, textoDuracion,
} from "../../lib/jarvisHud";
import { sinMarcaVieja } from "../../lib/voz";
import { API, authHeaders, apiFetch } from "../../lib/api";
import { moverPanel, posicionesRadiales, elegirPorDireccion, centroDelMenu } from "../../lib/gestos";
import { proyectosDelMenu } from "../../lib/proyectos";
import { useCamara } from "./useCamara";
import { PanelCamara } from "./Camara";
import Manos from "./Manos";
import PanelProyectos from "./Proyectos";
import MenuRadial from "./MenuRadial";
import { useProyectos } from "./useProyectos";

const VOZ_NAVEGADOR = typeof window !== "undefined"
  && Boolean(window.SpeechRecognition || window.webkitSpeechRecognition);
const VOZ_SINTESIS  = typeof window !== "undefined" && "speechSynthesis" in window;
const SIN_MOVIMIENTO = typeof window !== "undefined"
  && window.matchMedia?.("(prefers-reduced-motion: reduce)")?.matches;

// El arranque se ve una vez por carga de la página: es una presentación, no un peaje.
let arrancado = false;

// El menú del puño: radio del círculo de burbujas y cuánto se queda abierto si se abre la
// mano sin haber elegido (para pulsar una con un pellizco o con el ratón).
const RADIO_MENU = 175;
const MENU_ESPERA_MS = 6000;

// Dónde ha dejado el señor cada panel (desplazamiento desde su sitio), y si los proyectos
// estaban abiertos. Preferencias de este navegador, nada más.
const CLAVE_PANELES = "la_jarvis_paneles";
function leerPaneles() {
  try {
    const d = JSON.parse(localStorage.getItem(CLAVE_PANELES) || "{}");
    return d && typeof d === "object" ? d : {};
  } catch { return {}; }
}
function guardarPaneles(posiciones) {
  try { localStorage.setItem(CLAVE_PANELES, JSON.stringify(posiciones)); } catch { /* mejor esfuerzo */ }
}

const LINEAS_ARRANQUE = [
  "J.A.R.V.I.S. — inicializando",
  "Enlace con caja ············ OK",
  "Protocolos de herramientas ·· OK",
  "Memoria a largo plazo ······· OK",
  "Bienvenido, señor.",
];

export default function JarvisHUD({
  mensajes, borrador, setBorrador, onEnviar, pensando,
  etiquetaPendiente, onConfirmar, onDescartar, confirmando,
  escuchando, onDictar, habla, onHabla, hablando,
  enLlamada, faseLlamada, parcial, onLlamar, onColgar,
  potente, onPotente, onNueva, onSalir, briefing, host, onCapturador,
}) {
  const [arranque, setArranque] = useState(!arrancado && !SIN_MOVIMIENTO);
  const [ahora, setAhora]       = useState(() => new Date());
  const [segundos, setSegundos] = useState(0);      // lo que lleva el turno en curso
  const inputRef = useRef(null);
  const finRef   = useRef(null);
  // Solo se «teclea» lo que llega con la vista abierta: lo de antes ya se leyó.
  const [vistos] = useState(mensajes.length);

  const estado = estadoHud({
    enLlamada, faseLlamada, pensando, pendiente: Boolean(etiquetaPendiente), escuchando, hablando,
  });
  const ultimo = useMemo(
    () => [...mensajes].reverse().find(m => m.rol === "assistant" && (m.motor || m.ms)),
    [mensajes],
  );
  const motor      = motorEsperado({ potente, ultimo });
  // Si Spotify está conectado. Lo pregunta la vista y no el dashboard: es el único sitio
  // donde se conecta, y así no cuesta nada a quien no la abre.
  const [spotify, setSpotify] = useState(null);
  useEffect(() => {
    apiFetch(`${API}/spotify/estado`, { headers: authHeaders() })
      .then(r => (r.ok ? r.json() : null))
      .then(setSpotify)
      .catch(() => { /* sin backend: el panel no dice nada de la música */ });
  }, []);
  async function conectarSpotify() {
    try {
      const r = await apiFetch(`${API}/auth/spotify/login`, { headers: authHeaders() });
      const d = await r.json();
      if (d.auth_url) window.open(d.auth_url, "_blank", "noopener,noreferrer");
    } catch { /* mejor esfuerzo: se puede pulsar otra vez */ }
  }
  const protocolos = useMemo(() => protocolosUsados(mensajes), [mensajes]);

  // ── Cámara, manos y proyectos ──
  const [camaraOn, setCamaraOn]   = useState(false);
  const [jarvisVe, setJarvisVe]   = useState(true);
  const [manosOn, setManosOn]     = useState(false);
  const [estadoManos, setEstadoManos] = useState("apagada");
  const [proyectosOn, setProyectosOn] = useState(false);
  // Los proyectos se piden si se pueden ver: el panel abierto o las manos puestas (el
  // puño los saca en el menú).
  const proyectos = useProyectos(proyectosOn || manosOn);
  const [abrirProyecto, setAbrirProyecto] = useState(null);

  // ── El menú del puño ──
  // `radial`: { centro, clave (qué mano), sujeto (el puño sigue cerrado), elegido }.
  const [radial, setRadial] = useState(null);
  const radialRef = useRef(null);
  useEffect(() => { radialRef.current = radial; }, [radial]);
  const itemsMenu = useMemo(() => {
    const d = proyectos.datos;
    const lista = proyectosDelMenu(d?.proyectos || []);
    return d?.configurado ? [...lista, { id: "nuevo" }] : lista;
  }, [proyectos.datos]);
  const itemsRef = useRef(itemsMenu);
  useEffect(() => { itemsRef.current = itemsMenu; }, [itemsMenu]);
  const posicionesMenu = useMemo(() => posicionesRadiales(itemsMenu.length, RADIO_MENU), [itemsMenu.length]);

  const elegirDelMenu = useCallback((id) => {
    setRadial(null);
    if (!id) return;
    setProyectosOn(true);
    setAbrirProyecto({ id, vez: Date.now() });
  }, []);
  const onPuno = useCallback((fase, punto, clave) => {
    const r = radialRef.current;
    if (fase === "cierra") {
      if (r?.sujeto && r.clave !== clave) return;   // la otra mano ya lo tiene abierto
      setRadial({ clave, sujeto: true, elegido: -1,
                  centro: centroDelMenu(punto, RADIO_MENU, { width: window.innerWidth, height: window.innerHeight }) });
      return;
    }
    if (!r || r.clave !== clave || !r.sujeto) return;
    if (fase === "mueve") {
      const elegido = elegirPorDireccion({ x: punto.x - r.centro.x, y: punto.y - r.centro.y }, itemsRef.current.length);
      if (elegido !== r.elegido) setRadial({ ...r, elegido });
    } else if (fase === "abre") {
      if (r.elegido >= 0 && itemsRef.current[r.elegido]) elegirDelMenu(itemsRef.current[r.elegido].id);
      else setRadial({ ...r, sujeto: false });
    } else if (fase === "perdida") {
      // La mano ha salido del fotograma con el puño cerrado: no se elige nada a ciegas.
      setRadial({ ...r, sujeto: false, elegido: -1 });
    }
  }, [elegirDelMenu]);
  // Abierta la mano sin elegir, el menú espera un poco a un pellizco o un clic.
  useEffect(() => {
    if (!radial || radial.sujeto) return;
    const t = setTimeout(() => setRadial(null), MENU_ESPERA_MS);
    return () => clearTimeout(t);
  }, [radial]);
  const camara = useCamara(camaraOn);
  const { capturar } = camara;
  // El fotograma viaja con cada mensaje solo con la cámara en directo y «Jarvis ve».
  // Al cerrar la vista o apagar la cámara, el dashboard deja de tener a quién pedírselo.
  useEffect(() => {
    onCapturador?.(camaraOn && jarvisVe ? capturar : null);
    return () => onCapturador?.(null);
  }, [camaraOn, jarvisVe, capturar, onCapturador]);

  // ── Paneles que se mueven ──
  const [posiciones, setPosiciones] = useState(leerPaneles);
  // El último panel movido queda por encima de los demás.
  const [delante, setDelante] = useState(null);
  // Los arrastres en curso, uno por panel: con las dos manos se llevan dos a la vez.
  // `quien` es la mano (o el ratón) que lo cogió; la otra no puede moverlo mientras tanto.
  const arrastres = useRef({});
  const onArrastre = useCallback((id, fase, punto, quien = "raton") => {
    if (fase === "empieza") {
      if (arrastres.current[id]) return;
      const el = document.querySelector(`[data-panel="${id}"]`);
      if (!el) return;
      const inicio = posiciones[id] || { x: 0, y: 0 };
      const r = el.getBoundingClientRect();
      arrastres.current[id] = { quien, inicio, desde: punto,
                                caja: { left: r.left - inicio.x, top: r.top - inicio.y, width: r.width, height: r.height } };
      el.classList.add("jh-arrastrando");
      setDelante(id);
      return;
    }
    const a = arrastres.current[id];
    if (!a || a.quien !== quien) return;
    if (fase === "mueve") {
      const nueva = moverPanel(a.inicio, { x: punto.x - a.desde.x, y: punto.y - a.desde.y }, a.caja,
                               { width: window.innerWidth, height: window.innerHeight });
      setPosiciones(prev => ({ ...prev, [id]: nueva }));
    } else if (fase === "suelta") {
      document.querySelector(`[data-panel="${id}"]`)?.classList.remove("jh-arrastrando");
      delete arrastres.current[id];
      setPosiciones(prev => { guardarPaneles(prev); return prev; });
    }
  }, [posiciones]);
  // El ratón mueve los paneles igual que la mano: por el mismo camino.
  const asaDe = useCallback((id) => ({
    "data-arrastre": id,
    title: "Arrastre para mover el panel",
    onPointerDown: (e) => {
      if (e.button !== 0 || e.target.closest("button, input, textarea, a")) return;
      e.preventDefault();
      onArrastre(id, "empieza", { x: e.clientX, y: e.clientY });
      const mueve = (ev) => onArrastre(id, "mueve", { x: ev.clientX, y: ev.clientY });
      const suelta = (ev) => {
        onArrastre(id, "suelta", { x: ev.clientX, y: ev.clientY });
        window.removeEventListener("pointermove", mueve);
        window.removeEventListener("pointerup", suelta);
      };
      window.addEventListener("pointermove", mueve);
      window.addEventListener("pointerup", suelta);
    },
  }), [onArrastre]);
  const estiloPanel = (id) => (posiciones[id]
    ? { transform: `translate(${posiciones[id].x}px, ${posiciones[id].y}px)`, zIndex: delante === id ? 6 : 5 }
    : undefined);
  const hayMovidos = Object.keys(posiciones).length > 0;

  useEffect(() => {
    if (!arranque) return;
    arrancado = true;
    const t = setTimeout(() => setArranque(false), 1700);
    return () => clearTimeout(t);
  }, [arranque]);

  useEffect(() => {
    const t = setInterval(() => setAhora(new Date()), 1000);
    return () => clearInterval(t);
  }, []);

  // El contador del turno: con Opus un turno con herramientas pasa de los veinte
  // segundos, y un reactor que gira sin cifra parece colgado.
  useEffect(() => {
    if (!pensando) return;
    const inicio = Date.now();
    const t = setInterval(() => setSegundos(Math.floor((Date.now() - inicio) / 1000)), 1000);
    return () => { clearInterval(t); setSegundos(0); };
  }, [pensando]);

  useEffect(() => {
    finRef.current?.scrollIntoView({ block: "end", behavior: SIN_MOVIMIENTO ? "auto" : "smooth" });
  }, [mensajes, pensando, etiquetaPendiente]);

  useEffect(() => {
    if (!arranque && !enLlamada) inputRef.current?.focus();
  }, [arranque, enLlamada, pensando]);

  useEffect(() => {
    function tecla(e) {
      if (e.key !== "Escape") return;
      // Primero se cierra el menú del puño, si está; luego, la vista.
      if (radialRef.current) { e.preventDefault(); setRadial(null); return; }
      if (!enLlamada) { e.preventDefault(); onSalir(); }
    }
    document.addEventListener("keydown", tecla);
    return () => document.removeEventListener("keydown", tecla);
  }, [enLlamada, onSalir]);

  const puedeEnviar = borrador.trim() && !pensando;
  const hh = String(ahora.getHours()).padStart(2, "0");
  const mm = String(ahora.getMinutes()).padStart(2, "0");
  const ss = String(ahora.getSeconds()).padStart(2, "0");
  const fecha = ahora.toLocaleDateString("es-ES", { weekday: "long", day: "numeric", month: "long" });

  return (
    <div className="jh" data-estado={estado} role="dialog" aria-modal="true" aria-label="Jarvis">
      <style>{CSS}</style>
      <div className="jh-fondo" aria-hidden="true" />
      <div className="jh-barrido" aria-hidden="true" />

      {arranque && (
        <div className="jh-arranque" onClick={() => setArranque(false)} aria-hidden="true">
          {LINEAS_ARRANQUE.map((l, i) => (
            <div key={l} className="jh-arranque-linea" style={{ animationDelay: `${i * 0.26}s` }}>{l}</div>
          ))}
        </div>
      )}

      {/* ── Cabecera ── */}
      <header className="jh-cabecera">
        <div className="jh-marca">
          <span className="jh-marca-punto" />
          J.A.R.V.I.S.
          <span className="jh-marca-sub">Just A Rather Very Intelligent System</span>
        </div>
        <div className="jh-cabecera-acciones">
          {hayMovidos && (
            <button type="button" className="jh-boton-fino" onClick={() => { setPosiciones({}); guardarPaneles({}); }}
                    title="Devolver los paneles a su sitio">Recolocar</button>
          )}
          <button type="button" className={`jh-boton-fino${proyectosOn ? " activo" : ""}`}
                  onClick={() => setProyectosOn(v => !v)} aria-pressed={proyectosOn}>Proyectos</button>
          {mensajes.length > 0 && !enLlamada && (
            <button type="button" className="jh-boton-fino" onClick={onNueva} disabled={pensando}
                    title="Empezar una conversación nueva (no borra lo que Jarvis recuerda de usted)">
              Nueva sesión
            </button>
          )}
          <button type="button" className="jh-boton-fino" onClick={onSalir} disabled={enLlamada}
                  title={enLlamada ? "Cuelgue antes de salir" : "Volver al dashboard (Esc)"}
                  aria-label="Cerrar Jarvis">✕</button>
        </div>
      </header>

      <div className="jh-cuerpo">
        {/* ── Telemetría izquierda: el sistema ── */}
        <div className="jh-columna jh-columna-izq">
        <section className="jh-panel" data-panel="sistema" style={estiloPanel("sistema")} aria-label="Estado del sistema">
          <Esquinas />
          <div className="jh-panel-titulo jh-asa" {...asaDe("sistema")}>Sistema</div>
          <Dato etiqueta="Motor" valor={`Claude · ${motor.nombre}`} acento={potente} />
          {motor.nota && <div className="jh-nota">{motor.nota}</div>}
          <Dato etiqueta="Potencia" valor={potente ? "Máxima" : "Estándar"} acento={potente} />
          {ultimo && (
            <Dato etiqueta="Último turno"
                  valor={[nombreModelo(ultimo.modelo) || (ultimo.motor === "openai" ? "Respaldo" : ""),
                          textoDuracion(ultimo.ms)].filter(Boolean).join(" · ") || "—"} />
          )}
          <Dato etiqueta="Enlace" valor={host} />
          {spotify?.configurado && (spotify.conectado
            ? <Dato etiqueta="Música" valor="Spotify conectado" />
            : (
              <div className="jh-dato">
                <div className="jh-dato-etiqueta">Música</div>
                <button type="button" className="jh-boton-fino" style={{ marginTop: 4 }} onClick={conectarSpotify}>
                  Conectar Spotify
                </button>
              </div>
            ))}
          <Dato etiqueta="Sesión" valor={`${mensajes.filter(m => m.rol !== "aviso").length} mensajes`} />

          <div className="jh-panel-titulo" style={{ marginTop: 18 }}>Protocolos</div>
          {protocolos.length === 0
            ? <div className="jh-nota">Ninguno en esta sesión</div>
            : protocolos.map(p => (
              <div key={p.nombre} className="jh-protocolo">
                <span className="jh-protocolo-punto" />
                <span className="jh-protocolo-nombre">{nombreProtocolo(p.nombre)}</span>
                {p.veces > 1 && <span className="jh-protocolo-veces">×{p.veces}</span>}
              </div>
            ))}
        </section>
        {camaraOn && (
          <section className="jh-panel" data-panel="camara" style={estiloPanel("camara")} aria-label="Cámara">
            <Esquinas />
            <PanelCamara videoRef={camara.videoRef} estado={camara.estado} error={camara.error}
                         jarvisVe={jarvisVe} onJarvisVe={() => setJarvisVe(v => !v)}
                         manos={manosOn} onManos={() => setManosOn(v => !v)} estadoManos={estadoManos}
                         asa={asaDe("camara")} />
          </section>
        )}
        </div>

        {/* ── Centro: el reactor y la conversación ── */}
        <main className="jh-centro">
          <div className="jh-reactor-zona">
            <Reactor estado={estado} />
            <div className="jh-estado" aria-live="polite">
              {TEXTO_ESTADO[estado]}
              {estado === "pensando" && segundos > 0 && <span className="jh-estado-cifra"> · {segundos} s</span>}
            </div>
            {/* En móvil los paneles no caben: lo imprescindible, en una línea. */}
            <div className="jh-estado-movil">
              {hh}:{mm} · Claude {motor.nombre}
            </div>
          </div>

          <div className="jh-conversacion" role="log" aria-label="Conversación con Jarvis">
            {mensajes.length === 0 && !pensando && (
              <div className="jh-vacio">
                <div className="jh-vacio-titulo">¿En qué puedo ayudarle, señor?</div>
                <div className="jh-sugerencias">
                  {["¿Qué tengo hoy?", "¿Cómo he dormido?", "Enciende el PC", "¿Qué tiempo hará mañana?"].map(s => (
                    <button key={s} type="button" className="jh-sugerencia" onClick={() => onEnviar(s)}>{s}</button>
                  ))}
                </div>
              </div>
            )}
            {mensajes.map((m, i) => (
              <Mensaje key={i} m={m} teclear={i >= vistos && m.rol === "assistant"} />
            ))}
            {pensando && (
              <div className="jh-msg jh-msg-jarvis">
                <div className="jh-msg-cab"><span>Jarvis</span></div>
                <div className="jh-pensando"><span /><span /><span /></div>
              </div>
            )}
            {etiquetaPendiente && (
              <div className="jh-autorizacion" role="alert">
                <div className="jh-autorizacion-titulo">⚠ Autorización requerida</div>
                <div className="jh-autorizacion-texto">{etiquetaPendiente}</div>
                <div className="jh-autorizacion-botones">
                  <button type="button" className="jh-boton jh-boton-si" onClick={onConfirmar} disabled={confirmando}>
                    {confirmando ? "Ejecutando…" : "Autorizar"}
                  </button>
                  <button type="button" className="jh-boton" onClick={onDescartar} disabled={confirmando}>Descartar</button>
                </div>
              </div>
            )}
            <div ref={finRef} />
          </div>

          {/* ── La consola ── */}
          {enLlamada ? (
            <div className="jh-consola jh-consola-llamada">
              <span className="jh-llamada-punto" />
              <div className="jh-llamada-texto">
                <div className="jh-llamada-fase">{TEXTO_ESTADO[estado]}</div>
                {parcial && <div className="jh-llamada-parcial">{parcial}</div>}
              </div>
              <button type="button" className="jh-boton jh-boton-colgar" onClick={onColgar}>Colgar</button>
            </div>
          ) : (
            <form className="jh-consola" onSubmit={e => { e.preventDefault(); if (puedeEnviar) onEnviar(borrador); }}>
              <Esquinas />
              <button type="button" className={`jh-icono jh-potencia${potente ? " activo" : ""}`} onClick={onPotente}
                      aria-pressed={potente} aria-label="Potencia máxima"
                      title={potente
                        ? "Potencia máxima: piensa Opus 5.5 (más lento, gasta más límite). Pulse para volver a Sonnet"
                        : "Activar la potencia máxima: Opus 5.5"}>⚡</button>
              <button type="button" className={`jh-icono${camaraOn ? " activo jh-icono-vivo" : ""}`}
                      onClick={() => { setCamaraOn(v => !v); if (camaraOn) setManosOn(false); }}
                      aria-pressed={camaraOn} aria-label="Cámara"
                      title={camaraOn ? "Apagar la cámara" : "Encender la cámara: Jarvis le ve y puede usar las manos"}>📷</button>
              <span className="jh-prompt" aria-hidden="true">›</span>
              <input
                ref={inputRef}
                value={borrador}
                onChange={e => setBorrador(e.target.value)}
                placeholder={escuchando ? "Escuchando…" : "Hable con Jarvis"}
                aria-label="Mensaje para Jarvis"
                disabled={pensando}
                className="jh-input"
              />
              {VOZ_NAVEGADOR && (
                <button type="button" className={`jh-icono${escuchando ? " activo" : ""}`} onClick={onDictar}
                        aria-pressed={escuchando} aria-label="Dictar" title="Dictar">🎙</button>
              )}
              {VOZ_NAVEGADOR && VOZ_SINTESIS && (
                <button type="button" className="jh-icono" onClick={onLlamar}
                        aria-label="Hablar como en una llamada" title="Conversación por voz (modo llamada)">◉</button>
              )}
              {VOZ_SINTESIS && (
                <button type="button" className={`jh-icono${habla ? " activo" : ""}`} onClick={onHabla}
                        aria-pressed={habla} aria-label="Que Jarvis conteste en voz alta"
                        title={habla ? "Silenciar a Jarvis" : "Que Jarvis conteste en voz alta"}>{habla ? "🔊" : "🔇"}</button>
              )}
              <button type="submit" className="jh-enviar" disabled={!puedeEnviar} aria-label="Enviar">
                <span className="jh-enviar-texto">Enviar</span><span className="jh-enviar-icono" aria-hidden="true">➤</span>
              </button>
            </form>
          )}
        </main>

        {/* ── Telemetría derecha: el día ── */}
        <div className="jh-columna jh-columna-der">
        <section className="jh-panel" data-panel="dia" style={estiloPanel("dia")} aria-label="El día">
          <Esquinas />
          <div className="jh-asa jh-asa-reloj" {...asaDe("dia")}><div className="jh-reloj">{hh}<span className="jh-reloj-sep">:</span>{mm}<span className="jh-reloj-seg">{ss}</span></div></div>
          <div className="jh-fecha">{fecha}</div>
          {briefing?.frase && <div className="jh-briefing-frase">{briefing.frase}</div>}
          {briefing?.clima && <Dato etiqueta="Exterior" valor={briefing.clima} />}
          {briefing?.lineas?.length > 0 && (
            <>
              <div className="jh-panel-titulo" style={{ marginTop: 14 }}>En el radar</div>
              {briefing.lineas.map(l => <div key={l} className="jh-radar">{l}</div>)}
            </>
          )}
        </section>
        {proyectosOn && (
          <section className="jh-panel jh-panel-proyectos" data-panel="proyectos" style={estiloPanel("proyectos")}
                   aria-label="Proyectos">
            <Esquinas />
            <PanelProyectos asa={asaDe("proyectos")} datos={proyectos.datos} recargar={proyectos.recargar}
                            abrir={abrirProyecto} />
          </section>
        )}
        </div>
      </div>

      {/* Las manos van por encima de todo, y sin atrapar el ratón: el clic de un pellizco
          tiene que caer en lo que hay debajo. */}
      <MenuRadial centro={radial?.centro} items={itemsMenu} posiciones={posicionesMenu}
                  elegido={radial?.elegido ?? -1} sujeto={radial?.sujeto}
                  onElegir={elegirDelMenu} onCerrar={() => setRadial(null)} />
      <Manos videoRef={camara.videoRef} activa={camaraOn && manosOn && camara.estado === "en_directo"}
             onPuno={onPuno}
             onArrastre={onArrastre} onEstado={setEstadoManos} />
    </div>
  );
}

function Dato({ etiqueta, valor, acento }) {
  return (
    <div className="jh-dato">
      <div className="jh-dato-etiqueta">{etiqueta}</div>
      <div className={`jh-dato-valor${acento ? " acento" : ""}`}>{valor}</div>
    </div>
  );
}

function Esquinas() {
  return (
    <>
      <span className="jh-esq jh-esq-1" aria-hidden="true" />
      <span className="jh-esq jh-esq-2" aria-hidden="true" />
      <span className="jh-esq jh-esq-3" aria-hidden="true" />
      <span className="jh-esq jh-esq-4" aria-hidden="true" />
    </>
  );
}

const Mensaje = React.memo(function Mensaje({ m, teclear }) {
  if (m.rol === "aviso") return <div className="jh-aviso">⚠ {m.texto}</div>;
  if (m.rol === "user") {
    return (
      <div className="jh-msg jh-msg-usuario">
        <div className="jh-msg-cab"><span>Señor</span></div>
        <div className="jh-msg-texto">{m.texto}</div>
      </div>
    );
  }
  const modelo = nombreModelo(m.modelo);
  return (
    <div className="jh-msg jh-msg-jarvis">
      <div className="jh-msg-cab">
        <span>Jarvis</span>
        {(modelo || m.ms) && (
          <span className="jh-msg-meta">{[modelo, textoDuracion(m.ms)].filter(Boolean).join(" · ")}</span>
        )}
      </div>
      <Tecleado texto={sinMarcaVieja(m.texto)} activo={teclear && !SIN_MOVIMIENTO} />
      {m.herramientas?.length > 0 && (
        <div className="jh-chips">
          {m.herramientas.map(h => <span key={h} className="jh-chip">▸ {nombreProtocolo(h)}</span>)}
        </div>
      )}
    </div>
  );
});

/** La respuesta aparece «escribiéndose». Se recorta el texto plano y se trocea lo que
 *  hay, así que a mitad del tecleo una negrita puede verse abierta un instante. */
function Tecleado({ texto, activo }) {
  const [hasta, setHasta] = useState(activo ? 0 : Infinity);
  useEffect(() => {
    if (!activo) return;
    const total = duracionTecleo(texto);
    const inicio = performance.now();
    let id;
    const paso = t => {
      const f = total ? Math.min(1, (t - inicio) / total) : 1;
      setHasta(Math.ceil(texto.length * f));
      if (f < 1) id = requestAnimationFrame(paso);
    };
    id = requestAnimationFrame(paso);
    return () => cancelAnimationFrame(id);
  }, [texto, activo]);
  const visible = hasta >= texto.length ? texto : texto.slice(0, hasta);
  const bloques = trocearRespuesta(visible);
  return (
    <div className="jh-msg-texto">
      {bloques.map((b, i) => {
        if (b.tipo === "lista") {
          return <ul key={i}>{b.items.map((it, j) => <li key={j}><Trozos trozos={it} /></li>)}</ul>;
        }
        if (b.tipo === "titulo") return <div key={i} className="jh-msg-titulo"><Trozos trozos={b.trozos} /></div>;
        return <p key={i}><Trozos trozos={b.trozos} /></p>;
      })}
      {hasta < texto.length && <span className="jh-cursor" />}
    </div>
  );
}

function Trozos({ trozos }) {
  return trozos.map((t, i) => (t.fuerte ? <strong key={i}>{t.texto}</strong> : <React.Fragment key={i}>{t.texto}</React.Fragment>));
}

// ── El reactor ─────────────────────────────────────────────────────────────────
// Anillos concéntricos que giran a velocidades distintas; el color, la velocidad y las
// barras de voz cambian con `data-estado` en el contenedor (ver el CSS de abajo).
const MARCAS = Array.from({ length: 72 }, (_, i) => i);
const BARRAS = Array.from({ length: 48 }, (_, i) => i);

function arco(r, desde, hasta) {
  const a = (desde - 90) * Math.PI / 180;
  const b = (hasta - 90) * Math.PI / 180;
  const x1 = 200 + r * Math.cos(a), y1 = 200 + r * Math.sin(a);
  const x2 = 200 + r * Math.cos(b), y2 = 200 + r * Math.sin(b);
  return `M ${x1.toFixed(2)} ${y1.toFixed(2)} A ${r} ${r} 0 ${hasta - desde > 180 ? 1 : 0} 1 ${x2.toFixed(2)} ${y2.toFixed(2)}`;
}

function Reactor({ estado }) {
  return (
    <div className="jh-reactor" aria-hidden="true">
      <svg viewBox="0 0 400 400">
        <defs>
          <radialGradient id="jh-nucleo" cx="50%" cy="50%" r="50%">
            {/* El color en `style`: un atributo de presentación no resuelve var(). */}
            <stop offset="0%"   style={{ stopColor: "#ffffff", stopOpacity: 1 }} />
            <stop offset="35%"  style={{ stopColor: "var(--jh-c)", stopOpacity: 0.95 }} />
            <stop offset="70%"  style={{ stopColor: "var(--jh-c)", stopOpacity: 0.25 }} />
            <stop offset="100%" style={{ stopColor: "var(--jh-c)", stopOpacity: 0 }} />
          </radialGradient>
          <filter id="jh-brillo" x="-50%" y="-50%" width="200%" height="200%">
            <feGaussianBlur stdDeviation="3" result="b" />
            <feMerge><feMergeNode in="b" /><feMergeNode in="SourceGraphic" /></feMerge>
          </filter>
        </defs>

        {/* Anillo exterior de marcas */}
        <g className="jh-giro jh-giro-lento">
          {MARCAS.map(i => (
            <line key={i} x1="200" y1="14" x2="200" y2={i % 6 === 0 ? 30 : 22}
                  transform={`rotate(${i * 5} 200 200)`}
                  className={i % 6 === 0 ? "jh-marca-larga" : "jh-marca-corta"} />
          ))}
        </g>

        {/* Arcos discontinuos, en sentido contrario */}
        <g className="jh-giro jh-giro-inverso" filter="url(#jh-brillo)">
          <path d={arco(166, 10, 80)}   className="jh-arco" />
          <path d={arco(166, 130, 200)} className="jh-arco" />
          <path d={arco(166, 250, 320)} className="jh-arco" />
        </g>
        <circle cx="200" cy="200" r="150" className="jh-anillo-fino" />

        {/* Barras de voz alrededor del núcleo */}
        <g className="jh-barras">
          {/* El giro va en el <g>: la animación del <rect> es un transform de CSS, y
              puesta en el mismo elemento pisaría el atributo. */}
          {BARRAS.map(i => (
            <g key={i} transform={`rotate(${i * 7.5} 200 200)`}>
              <rect x="198.5" y="62" width="3" height="26" rx="1.5"
                    style={{ animationDelay: `${((i * 37) % 48) * -0.031}s` }} />
            </g>
          ))}
        </g>

        {/* Anillo de segmentos */}
        <g className="jh-giro jh-giro-medio">
          {Array.from({ length: 10 }, (_, i) => (
            <path key={i} d={arco(112, i * 36 + 4, i * 36 + 30)} className="jh-segmento" />
          ))}
        </g>

        <g className="jh-giro jh-giro-rapido" filter="url(#jh-brillo)">
          <path d={arco(92, 0, 110)}   className="jh-arco-interior" />
          <path d={arco(92, 180, 290)} className="jh-arco-interior" />
        </g>

        {/* Núcleo */}
        <circle cx="200" cy="200" r="86" fill="url(#jh-nucleo)" className="jh-halo" />
        <circle cx="200" cy="200" r="58" className="jh-nucleo-borde" />
        <g className="jh-giro jh-giro-nucleo">
          {Array.from({ length: 3 }, (_, i) => (
            <path key={i} d={`M 200 200 L ${200 + 50 * Math.cos((i * 120 - 90) * Math.PI / 180)} ${200 + 50 * Math.sin((i * 120 - 90) * Math.PI / 180)}`}
                  className="jh-radio" />
          ))}
        </g>
        <circle cx="200" cy="200" r="30" className="jh-nucleo" />
        <text x="200" y="205" textAnchor="middle" className="jh-nucleo-texto">{estado === "alerta" ? "!" : "J"}</text>
      </svg>
    </div>
  );
}

const CSS = `
@import url('https://fonts.googleapis.com/css2?family=Rajdhani:wght@500;600;700&display=swap');

.jh {
  --jh-bg: #02060b;
  --jh-c: #5ee7ff;
  --jh-c2: rgba(94, 231, 255, 0.55);
  --jh-c3: rgba(94, 231, 255, 0.16);
  --jh-texto: #d9f6ff;
  --jh-tenue: rgba(190, 235, 250, 0.55);
  --jh-amb: #ffb547;
  --jh-rojo: #ff5f57;
  --jh-vel: 1;
  position: fixed; inset: 0; z-index: 95;
  background: var(--jh-bg); color: var(--jh-texto);
  font-family: 'DM Sans', sans-serif;
  display: flex; flex-direction: column;
  overflow: hidden;
  animation: jhEntrada .45s ease-out;
}
.jh[data-estado="pensando"]   { --jh-c: #ffc061; --jh-c2: rgba(255,192,97,.55); --jh-c3: rgba(255,192,97,.16); --jh-vel: .35; }
.jh[data-estado="escuchando"] { --jh-c: #7dffc4; --jh-c2: rgba(125,255,196,.55); --jh-c3: rgba(125,255,196,.16); --jh-vel: .8; }
.jh[data-estado="hablando"]   { --jh-vel: .6; }
.jh[data-estado="alerta"]     { --jh-c: #ff6b5e; --jh-c2: rgba(255,107,94,.55); --jh-c3: rgba(255,107,94,.16); --jh-vel: 1.6; }

.jh *, .jh *::before, .jh *::after { box-sizing: border-box; }
.jh button { font-family: inherit; }

.jh-fondo {
  position: absolute; inset: 0; pointer-events: none;
  background:
    radial-gradient(ellipse 60% 50% at 50% 32%, var(--jh-c3), transparent 70%),
    linear-gradient(rgba(94,231,255,.045) 1px, transparent 1px) 0 0 / 44px 44px,
    linear-gradient(90deg, rgba(94,231,255,.045) 1px, transparent 1px) 0 0 / 44px 44px;
  transition: background 0.6s;
  mask-image: radial-gradient(ellipse 90% 90% at 50% 40%, #000 40%, transparent 100%);
}
.jh-barrido {
  position: absolute; inset: 0; pointer-events: none; opacity: .5;
  background: linear-gradient(180deg, transparent 0%, rgba(94,231,255,.06) 50%, transparent 100%);
  background-size: 100% 220px; background-repeat: no-repeat;
  animation: jhBarrido 7s linear infinite;
}

/* Arranque */
.jh-arranque {
  position: absolute; inset: 0; z-index: 10; background: var(--jh-bg);
  display: flex; flex-direction: column; justify-content: center; align-items: center; gap: 8px;
  font-family: 'DM Mono', monospace; font-size: 14px; color: var(--jh-c); letter-spacing: .06em;
  animation: jhSalida .35s ease-in 1.4s forwards; cursor: pointer;
}
.jh-arranque-linea { opacity: 0; animation: jhLinea .3s ease-out forwards; white-space: pre; }
.jh-arranque-linea:last-child { font-family: 'Rajdhani', sans-serif; font-size: 22px; font-weight: 600; margin-top: 10px; }

/* Cabecera */
.jh-cabecera {
  position: relative; z-index: 2; display: flex; align-items: center; justify-content: space-between;
  padding: max(14px, env(safe-area-inset-top)) 22px 8px;
}
.jh-marca {
  font-family: 'Rajdhani', sans-serif; font-weight: 700; font-size: 20px; letter-spacing: .32em;
  color: var(--jh-c); display: flex; align-items: center; gap: 10px; text-shadow: 0 0 12px var(--jh-c2);
  transition: color .6s;
}
.jh-marca-punto { width: 8px; height: 8px; border-radius: 50%; background: var(--jh-c); box-shadow: 0 0 10px var(--jh-c); animation: jhLatido 2s infinite; }
.jh-marca-sub { font-family: 'DM Mono', monospace; font-weight: 400; font-size: 10px; letter-spacing: .14em; color: var(--jh-tenue); text-shadow: none; }
.jh-cabecera-acciones { display: flex; gap: 8px; }
.jh-boton-fino {
  background: transparent; border: 1px solid var(--jh-c3); color: var(--jh-tenue);
  font-family: 'Rajdhani', sans-serif !important; font-weight: 600; letter-spacing: .14em; text-transform: uppercase;
  font-size: 12px; padding: 6px 12px; border-radius: 4px; cursor: pointer; transition: all .2s;
}
.jh-boton-fino:hover:not(:disabled) { color: var(--jh-c); border-color: var(--jh-c2); box-shadow: 0 0 12px var(--jh-c3); }
.jh-boton-fino:disabled { opacity: .35; cursor: default; }

/* Cuerpo */
.jh-cuerpo {
  position: relative; z-index: 1; flex: 1; min-height: 0;
  display: grid; grid-template-columns: 250px minmax(0, 1fr) 250px; gap: 22px;
  padding: 6px 22px max(18px, env(safe-area-inset-bottom));
}
.jh-columna {
  align-self: start; margin-top: 30px; min-width: 0;
  display: flex; flex-direction: column; gap: 16px;
  max-height: calc(100vh - 110px); overflow: visible;
}
.jh-panel {
  position: relative;
  border: 1px solid var(--jh-c3);
  /* Opaco: un panel movido encima de otro no puede dejar ver lo de debajo. */
  background: linear-gradient(180deg, rgba(94,231,255,.05), rgba(94,231,255,0) 60%), rgba(3,10,17,.94);
  padding: 16px 16px 18px; border-radius: 2px; transition: border-color .6s;
  clip-path: polygon(0 0, calc(100% - 16px) 0, 100% 16px, 100% 100%, 16px 100%, 0 calc(100% - 16px));
  animation: jhPanel .6s ease-out;
}
.jh-panel-titulo {
  font-family: 'Rajdhani', sans-serif; font-weight: 700; font-size: 12px; letter-spacing: .3em;
  text-transform: uppercase; color: var(--jh-c); margin-bottom: 10px; display: flex; align-items: center; gap: 8px;
}
.jh-panel-titulo::after { content: ""; flex: 1; height: 1px; background: linear-gradient(90deg, var(--jh-c2), transparent); order: 1; }
.jh-panel-titulo > .jh-mini, .jh-panel-titulo > .jh-directo { order: 2; }

/* Lo que se arrastra: el título de cada panel (con el ratón o con un pellizco). */
.jh-asa { cursor: grab; user-select: none; touch-action: none; }
.jh-arrastrando { z-index: 20; box-shadow: 0 0 30px var(--jh-c2); animation: none !important; }
.jh-arrastrando .jh-asa { cursor: grabbing; }
.jh-asa-reloj { margin-bottom: 0; }

.jh-boton-fino.activo { color: var(--jh-c); border-color: var(--jh-c2); background: var(--jh-c3); }
.jh-mini {
  font-family: 'DM Mono', monospace !important; font-size: 10px; letter-spacing: .08em; text-transform: none;
  background: transparent; border: 1px solid var(--jh-c3); color: var(--jh-c); padding: 3px 8px; border-radius: 3px; cursor: pointer;
}
.jh-mini:disabled { opacity: .4; cursor: default; }

/* La cámara */
.jh-directo { font-family: 'DM Mono', monospace; font-size: 9.5px; letter-spacing: .12em; color: var(--jh-tenue); }
.jh-directo.vivo { color: var(--jh-rojo); animation: jhLatido 1.6s infinite; }
.jh-camara {
  position: relative; aspect-ratio: 16 / 10; overflow: hidden; border: 1px solid var(--jh-c3);
  background: #000; border-radius: 2px;
}
.jh-camara-video { width: 100%; height: 100%; object-fit: cover; transform: scaleX(-1); display: block; filter: saturate(.85) contrast(1.05); }
.jh-camara-reticula {
  position: absolute; inset: 0; pointer-events: none;
  background:
    linear-gradient(var(--jh-c) 0 0) center / 18px 1px no-repeat,
    linear-gradient(var(--jh-c) 0 0) center / 1px 18px no-repeat,
    linear-gradient(transparent 49.5%, rgba(94,231,255,.07) 50%, transparent 50.5%) 0 0 / 100% 6px;
  opacity: .55; mix-blend-mode: screen;
}
.jh-camara-aviso { position: absolute; inset: 0; display: grid; place-items: center; text-align: center; padding: 10px; font-size: 12px; color: var(--jh-tenue); }
.jh-camara-botones { display: flex; gap: 6px; margin-top: 8px; flex-wrap: wrap; }
.jh-camara-botones .jh-boton-fino { font-size: 10.5px; padding: 5px 8px; letter-spacing: .1em; }
.jh-icono-vivo { box-shadow: 0 0 0 1px rgba(255,95,87,.5), 0 0 12px rgba(255,95,87,.35); }

/* Las manos */
.jh-manos-lienzo { position: fixed; inset: 0; width: 100vw; height: 100vh; pointer-events: none; z-index: 40; }
.jh-manos-cursor {
  position: fixed; left: 0; top: 0; z-index: 41; pointer-events: none; opacity: 0;
  width: 0; height: 0; transition: opacity .2s; --fuerza: 0;
}
.jh-manos-cursor span {
  position: absolute; left: -18px; top: -18px; width: 36px; height: 36px; border-radius: 50%;
  border: 2px solid var(--jh-c); box-shadow: 0 0 16px var(--jh-c2), inset 0 0 calc(var(--fuerza) * 18px) var(--jh-c);
  transform: scale(calc(1 - var(--fuerza) * .45)); transition: transform .08s;
}
.jh-manos-cursor.cerrado span { background: var(--jh-c3); border-color: #fff; }
.jh-manos-cursor.pulso span { animation: jhPulso .26s ease-out; }
.jh-mano-encima { outline: 2px solid var(--jh-c) !important; outline-offset: 2px; box-shadow: 0 0 18px var(--jh-c2) !important; }

/* El menú del puño */
.jh-radial { position: fixed; inset: 0; z-index: 38; pointer-events: none; animation: jhEntrada .25s ease-out; }
/* El velo: la vista de detrás se apaga alrededor del puño para que el menú se lea. */
.jh-radial::before {
  content: ""; position: absolute; inset: 0;
  background: radial-gradient(circle at var(--cx) var(--cy), rgba(2,6,11,.92) 0, rgba(2,6,11,.86) 300px, rgba(2,6,11,.55) 520px, rgba(2,6,11,.35) 100%);
}
.jh-radial-radios { position: absolute; inset: 0; width: 100%; height: 100%; }
.jh-radial-radios line { stroke: var(--jh-c); stroke-width: 1; opacity: .25; stroke-dasharray: 3 5; }
.jh-radial-radios line.elegido { opacity: .9; stroke-width: 2; stroke-dasharray: none; filter: drop-shadow(0 0 6px var(--jh-c)); }
.jh-radial-nucleo {
  position: absolute; width: 220px; height: 220px; margin: -110px 0 0 -110px; border-radius: 50%;
  pointer-events: auto; cursor: pointer; background: radial-gradient(circle, rgba(94,231,255,.14), rgba(2,8,14,.55) 62%, transparent 72%);
  border: none; color: var(--jh-texto); display: flex; flex-direction: column; align-items: center; justify-content: center; gap: 4px;
}
.jh-radial-anillo {
  position: absolute; inset: 0; border-radius: 50%; border: 2px solid var(--jh-c); box-shadow: 0 0 24px var(--jh-c2), inset 0 0 24px var(--jh-c3);
  border-top-color: transparent; border-bottom-color: transparent; animation: jhGiro 6s linear infinite;
}
.jh-radial-anillo.dos { inset: 14px; border-width: 1px; border-style: dashed; animation-duration: 14s; animation-direction: reverse; opacity: .6; border-top-color: var(--jh-c); }
.jh-radial-titulo { font-family: 'Rajdhani', sans-serif; font-weight: 700; letter-spacing: .32em; text-transform: uppercase; font-size: 15px; color: var(--jh-c); text-shadow: 0 0 12px var(--jh-c2); }
.jh-radial-cuenta { font-family: 'DM Mono', monospace; font-size: 9.5px; color: var(--jh-tenue); max-width: 140px; text-align: center; line-height: 1.4; }
.jh-burbuja {
  position: absolute; width: 112px; height: 112px; margin: -56px 0 0 -56px; border-radius: 50%; pointer-events: auto; cursor: pointer;
  display: flex; flex-direction: column; align-items: center; justify-content: center; gap: 4px; padding: 12px; text-align: center;
  background: radial-gradient(circle, rgba(3,16,26,.96) 60%, rgba(94,231,255,.12)); color: var(--jh-texto);
  border: 1px solid var(--jh-c2); box-shadow: 0 0 18px var(--jh-c3);
  animation: jhBurbuja .38s cubic-bezier(.2,1.4,.4,1) both; transition: transform .15s, box-shadow .15s, border-color .15s;
}
.jh-burbuja-progreso {
  position: absolute; inset: -4px; border-radius: 50%; pointer-events: none;
  background: conic-gradient(var(--jh-c) calc(var(--pct) * 1%), transparent 0);
  -webkit-mask: radial-gradient(circle, transparent 61px, #000 62px); mask: radial-gradient(circle, transparent 61px, #000 62px);
  opacity: .85;
}
.jh-burbuja-nombre { font-family: 'Rajdhani', sans-serif; font-weight: 600; font-size: 14px; line-height: 1.15; }
.jh-burbuja-estado { font-family: 'DM Mono', monospace; font-size: 9px; color: var(--jh-tenue); text-transform: uppercase; letter-spacing: .06em; }
.jh-burbuja-pct { display: block; margin-top: 2px; font-size: 11px; color: var(--jh-texto); letter-spacing: .04em; }
.jh-burbuja.e-trabajando { border-color: rgba(255,192,97,.7); }
.jh-burbuja.e-trabajando .jh-burbuja-estado { color: var(--jh-amb); }
.jh-burbuja.nueva { border-style: dashed; }
.jh-burbuja.nueva .jh-burbuja-nombre { color: var(--jh-c); }
.jh-burbuja.elegida, .jh-burbuja:hover { transform: scale(1.14); border-color: #fff; box-shadow: 0 0 30px var(--jh-c), inset 0 0 18px var(--jh-c3); }
.jh-manos-cursor.puno span { border-radius: 30%; border-color: var(--jh-amb); box-shadow: 0 0 20px rgba(255,181,71,.6); }

/* Los proyectos */
.jh-panel-proyectos { max-height: 56vh; overflow-y: auto; scrollbar-width: thin; scrollbar-color: var(--jh-c3) transparent; }
.jh-proy { border-top: 1px dashed var(--jh-c3); padding: 7px 0; }
.jh-proy-cab { width: 100%; display: flex; align-items: baseline; gap: 8px; background: none; border: none; color: var(--jh-texto); cursor: pointer; padding: 0; text-align: left; }
.jh-proy-titulo { flex: 1; font-size: 13px; line-height: 1.35; }
.jh-proy-estado { font-family: 'DM Mono', monospace; font-size: 9.5px; letter-spacing: .08em; text-transform: uppercase; color: var(--jh-tenue); white-space: nowrap; }
.jh-proy-estado.e-trabajando { color: var(--jh-amb); }
.jh-proy-estado.e-terminado { color: #7dffc4; }
.jh-proy-estado.e-fallido { color: var(--jh-rojo); }
.jh-proy-barra { height: 3px; background: var(--jh-c3); margin-top: 6px; border-radius: 2px; overflow: hidden; }
.jh-proy-barra span { display: block; height: 100%; background: var(--jh-c); box-shadow: 0 0 8px var(--jh-c); }
.jh-proy-ahora { font-size: 11.5px; color: var(--jh-tenue); margin-top: 4px; line-height: 1.4; }
.jh-proy-detalle { margin-top: 8px; }
.jh-proy-texto { font-size: 12.5px; line-height: 1.5; color: var(--jh-texto); white-space: pre-line; }
.jh-proy-pr { display: inline-block; margin-top: 6px; font-size: 12px; color: var(--jh-c); }
.jh-proy-hablar { display: flex; gap: 6px; margin-top: 8px; }
.jh-proy-form { display: flex; flex-direction: column; gap: 6px; margin-bottom: 8px; }
.jh-proy-aviso { font-size: 12px; color: var(--jh-amb); margin: 4px 0 8px; line-height: 1.4; }
.jh-campo {
  width: 100%; min-width: 0; background: rgba(2,12,20,.8); border: 1px solid var(--jh-c3); color: var(--jh-texto);
  font-family: 'DM Sans', sans-serif; font-size: 12.5px; padding: 7px 9px; border-radius: 3px; resize: vertical; outline: none;
}
.jh-campo:focus { border-color: var(--jh-c2); }
.jh-dato { margin-bottom: 9px; }
.jh-dato-etiqueta { font-family: 'DM Mono', monospace; font-size: 9.5px; letter-spacing: .16em; text-transform: uppercase; color: var(--jh-tenue); }
.jh-dato-valor { font-family: 'Rajdhani', sans-serif; font-weight: 600; font-size: 16px; color: var(--jh-texto); overflow-wrap: anywhere; }
.jh-dato-valor.acento { color: var(--jh-amb); text-shadow: 0 0 10px rgba(255,181,71,.5); }
.jh-nota { font-size: 11px; color: var(--jh-tenue); margin: -4px 0 9px; line-height: 1.4; }
.jh-protocolo { display: flex; align-items: center; gap: 8px; font-family: 'DM Mono', monospace; font-size: 11px; padding: 3px 0; color: var(--jh-texto); }
.jh-protocolo-punto { width: 5px; height: 5px; background: var(--jh-c); box-shadow: 0 0 6px var(--jh-c); flex-shrink: 0; }
.jh-protocolo-nombre { flex: 1; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.jh-protocolo-veces { color: var(--jh-tenue); }
.jh-esq { position: absolute; width: 10px; height: 10px; border-color: var(--jh-c); border-style: solid; opacity: .9; pointer-events: none; transition: border-color .6s; }
.jh-esq-1 { top: -1px; left: -1px; border-width: 2px 0 0 2px; }
.jh-esq-2 { top: -1px; right: -1px; border-width: 2px 2px 0 0; display: none; }
.jh-esq-3 { bottom: -1px; right: -1px; border-width: 0 2px 2px 0; }
.jh-esq-4 { bottom: -1px; left: -1px; border-width: 0 0 2px 2px; display: none; }

.jh-reloj { font-family: 'Rajdhani', sans-serif; font-weight: 600; font-size: 46px; line-height: 1; color: var(--jh-texto); text-shadow: 0 0 18px var(--jh-c3); letter-spacing: .04em; }
.jh-reloj-sep { animation: jhLatido 1s steps(2) infinite; color: var(--jh-c); }
.jh-reloj-seg { font-size: 18px; color: var(--jh-c); margin-left: 6px; }
.jh-fecha { font-family: 'DM Mono', monospace; font-size: 11px; text-transform: uppercase; letter-spacing: .12em; color: var(--jh-tenue); margin: 6px 0 14px; }
.jh-briefing-frase { font-size: 13.5px; line-height: 1.5; color: var(--jh-texto); margin-bottom: 12px; padding-left: 10px; border-left: 2px solid var(--jh-c2); }
.jh-radar { font-size: 12.5px; line-height: 1.4; color: var(--jh-texto); padding: 5px 0; border-bottom: 1px dashed var(--jh-c3); }
.jh-radar:last-child { border-bottom: none; }

/* Centro */
.jh-centro { display: flex; flex-direction: column; min-height: 0; min-width: 0; }
.jh-reactor-zona { display: flex; flex-direction: column; align-items: center; flex-shrink: 0; }
.jh-reactor { width: min(300px, 34vh); aspect-ratio: 1; position: relative; transition: width .4s; }
.jh-centro:has(.jh-msg) .jh-reactor { width: min(230px, 26vh); }
.jh-reactor svg { width: 100%; height: 100%; overflow: visible; }
.jh-reactor::before {
  content: ""; position: absolute; inset: 18%; border-radius: 50%;
  background: radial-gradient(circle, var(--jh-c2), transparent 65%); filter: blur(28px); opacity: .55;
  animation: jhRespira calc(3.2s * var(--jh-vel)) ease-in-out infinite; transition: background .6s;
}
.jh-giro { transform-origin: 200px 200px; transform-box: view-box; }
.jh-giro-lento   { animation: jhGiro calc(60s * var(--jh-vel)) linear infinite; }
.jh-giro-inverso { animation: jhGiro calc(24s * var(--jh-vel)) linear infinite reverse; }
.jh-giro-medio   { animation: jhGiro calc(16s * var(--jh-vel)) linear infinite; }
.jh-giro-rapido  { animation: jhGiro calc(6s * var(--jh-vel)) linear infinite reverse; }
.jh-giro-nucleo  { animation: jhGiro calc(9s * var(--jh-vel)) linear infinite; }
.jh-marca-larga { stroke: var(--jh-c); stroke-width: 2; opacity: .85; }
.jh-marca-corta { stroke: var(--jh-c); stroke-width: 1; opacity: .35; }
.jh-arco { fill: none; stroke: var(--jh-c); stroke-width: 3; stroke-linecap: round; opacity: .9; }
.jh-anillo-fino { fill: none; stroke: var(--jh-c); stroke-width: .8; opacity: .3; stroke-dasharray: 2 5; }
.jh-segmento { fill: none; stroke: var(--jh-c); stroke-width: 10; opacity: .32; }
.jh-arco-interior { fill: none; stroke: var(--jh-c); stroke-width: 2.5; opacity: .95; }
.jh-halo { animation: jhRespira calc(3.2s * var(--jh-vel)) ease-in-out infinite; transform-origin: 200px 200px; transform-box: view-box; }
.jh-nucleo-borde { fill: none; stroke: var(--jh-c); stroke-width: 2; opacity: .8; }
.jh-radio { stroke: var(--jh-c); stroke-width: 1.5; opacity: .5; }
.jh-nucleo { fill: #f4feff; filter: drop-shadow(0 0 14px var(--jh-c)); }
.jh-nucleo-texto { font-family: 'Rajdhani', sans-serif; font-weight: 700; font-size: 18px; fill: #02060b; }
.jh-reactor circle, .jh-reactor path, .jh-reactor line { transition: stroke .6s; }
.jh-barras rect { fill: var(--jh-c); opacity: 0; transform-box: fill-box; transform-origin: center bottom; }
.jh[data-estado="hablando"] .jh-barras rect,
.jh[data-estado="escuchando"] .jh-barras rect { animation: jhBarra .62s ease-in-out infinite alternate; }
.jh[data-estado="escuchando"] .jh-barras rect { animation-duration: 1.4s; }
.jh[data-estado="pensando"] .jh-barras rect { opacity: .25; }

.jh-estado {
  font-family: 'Rajdhani', sans-serif; font-weight: 700; font-size: 15px; letter-spacing: .42em; text-transform: uppercase;
  color: var(--jh-c); text-shadow: 0 0 12px var(--jh-c2); margin-top: 2px; transition: color .6s; text-align: center;
}
.jh-estado-cifra { font-family: 'DM Mono', monospace; letter-spacing: .08em; font-size: 12px; }
.jh-estado-movil { display: none; font-family: 'DM Mono', monospace; font-size: 10.5px; color: var(--jh-tenue); letter-spacing: .1em; margin-top: 4px; text-transform: uppercase; }

/* Conversación */
.jh-conversacion {
  /* La columna de lectura, del ancho de la consola: el padding la centra sin quitarle
     la barra de desplazamiento al borde. */
  flex: 1; min-height: 0; overflow-y: auto; margin-top: 6px;
  padding: 14px max(6px, calc((100% - 820px) / 2)) 10px;
  display: flex; flex-direction: column; gap: 14px;
  mask-image: linear-gradient(180deg, transparent 0, #000 22px, #000 calc(100% - 8px), transparent 100%);
  scrollbar-width: thin; scrollbar-color: var(--jh-c3) transparent;
}
.jh-vacio { margin: auto; text-align: center; padding: 10px; }
.jh-vacio-titulo { font-family: 'Rajdhani', sans-serif; font-weight: 600; font-size: 22px; letter-spacing: .06em; color: var(--jh-texto); margin-bottom: 16px; }
.jh-sugerencias { display: flex; flex-wrap: wrap; gap: 8px; justify-content: center; max-width: 560px; }
.jh-sugerencia {
  background: rgba(94,231,255,.05); border: 1px solid var(--jh-c3); color: var(--jh-texto);
  font-size: 13px; padding: 8px 14px; border-radius: 999px; cursor: pointer; transition: all .2s;
}
.jh-sugerencia:hover { border-color: var(--jh-c2); color: var(--jh-c); box-shadow: 0 0 14px var(--jh-c3); }

.jh-msg { max-width: min(760px, 92%); animation: jhMsg .35s ease-out; }
.jh-msg-cab { display: flex; align-items: baseline; gap: 10px; margin-bottom: 4px; font-family: 'Rajdhani', sans-serif; font-weight: 700; font-size: 11px; letter-spacing: .3em; text-transform: uppercase; }
.jh-msg-meta { font-family: 'DM Mono', monospace; font-weight: 400; letter-spacing: .06em; font-size: 10px; color: var(--jh-tenue); text-transform: none; }
.jh-msg-texto { font-size: 15px; line-height: 1.6; overflow-wrap: anywhere; }
.jh-msg-texto p { margin: 0 0 6px; }
.jh-msg-texto p:last-child { margin-bottom: 0; }
.jh-msg-texto ul { margin: 4px 0 8px 2px; padding: 0; list-style: none; }
.jh-msg-texto li { position: relative; padding-left: 16px; margin: 3px 0; }
.jh-msg-texto li::before { content: ""; position: absolute; left: 2px; top: .62em; width: 6px; height: 6px; border: 1px solid var(--jh-c); transform: rotate(45deg); }
.jh-msg-texto strong { color: #fff; font-weight: 600; }
.jh-msg-titulo { font-family: 'Rajdhani', sans-serif; font-weight: 700; letter-spacing: .08em; font-size: 16px; margin: 6px 0 4px; color: var(--jh-c); }
.jh-msg-jarvis { align-self: flex-start; padding: 2px 0 2px 14px; border-left: 2px solid var(--jh-c2); }
.jh-msg-jarvis .jh-msg-cab { color: var(--jh-c); }
.jh-msg-usuario { align-self: flex-end; text-align: right; }
.jh-msg-usuario .jh-msg-cab { justify-content: flex-end; color: var(--jh-tenue); }
.jh-msg-usuario .jh-msg-texto {
  display: inline-block; text-align: left; background: rgba(94,231,255,.07); border: 1px solid var(--jh-c3);
  padding: 8px 14px; border-radius: 12px 12px 2px 12px; color: var(--jh-texto);
}
.jh-cursor { display: inline-block; width: 8px; height: 1em; vertical-align: -2px; margin-left: 2px; background: var(--jh-c); animation: jhLatido .7s steps(2) infinite; }
.jh-chips { display: flex; flex-wrap: wrap; gap: 6px; margin-top: 8px; }
.jh-chip { font-family: 'DM Mono', monospace; font-size: 10px; letter-spacing: .08em; color: var(--jh-c); border: 1px solid var(--jh-c3); background: rgba(94,231,255,.05); padding: 2px 8px; border-radius: 2px; }
.jh-aviso { align-self: center; font-size: 12.5px; color: var(--jh-amb); border: 1px solid rgba(255,181,71,.3); background: rgba(255,181,71,.06); padding: 6px 12px; border-radius: 4px; max-width: 92%; text-align: center; }
.jh-pensando { display: flex; gap: 6px; padding: 8px 0; }
.jh-pensando span { width: 7px; height: 7px; background: var(--jh-c); transform: rotate(45deg); animation: jhPunto 1s ease-in-out infinite; box-shadow: 0 0 8px var(--jh-c); }
.jh-pensando span:nth-child(2) { animation-delay: .15s; }
.jh-pensando span:nth-child(3) { animation-delay: .3s; }

.jh-autorizacion {
  align-self: stretch; max-width: 760px; margin: 0 auto; width: 100%;
  border: 1px solid rgba(255,107,94,.55); background: linear-gradient(180deg, rgba(255,107,94,.1), rgba(255,107,94,.03));
  padding: 14px 16px; border-radius: 3px; animation: jhAlerta 1.8s ease-in-out infinite;
}
.jh-autorizacion-titulo { font-family: 'Rajdhani', sans-serif; font-weight: 700; font-size: 13px; letter-spacing: .3em; text-transform: uppercase; color: var(--jh-rojo); margin-bottom: 8px; }
.jh-autorizacion-texto { font-size: 14.5px; line-height: 1.5; white-space: pre-line; margin-bottom: 12px; }
.jh-autorizacion-botones { display: flex; gap: 10px; }
.jh-boton {
  font-family: 'Rajdhani', sans-serif !important; font-weight: 700; letter-spacing: .2em; text-transform: uppercase; font-size: 13px;
  padding: 9px 18px; border-radius: 3px; cursor: pointer; border: 1px solid var(--jh-c3); background: transparent; color: var(--jh-tenue); transition: all .2s;
}
.jh-boton:disabled { opacity: .5; cursor: default; }
.jh-boton-si { background: var(--jh-rojo); color: #1a0503; border-color: var(--jh-rojo); flex: 1; box-shadow: 0 0 18px rgba(255,95,87,.35); }
.jh-boton-si:hover:not(:disabled) { box-shadow: 0 0 26px rgba(255,95,87,.6); }
.jh-boton-colgar { background: var(--jh-rojo); color: #1a0503; border-color: var(--jh-rojo); }

/* Consola */
.jh-consola {
  position: relative; flex-shrink: 0; display: flex; align-items: center; gap: 6px; margin-top: 8px;
  max-width: 820px; width: 100%; align-self: center;
  border: 1px solid var(--jh-c2); background: rgba(2, 12, 20, .85); padding: 6px 6px 6px 8px; border-radius: 3px;
  box-shadow: 0 0 0 1px rgba(0,0,0,.4), 0 0 26px var(--jh-c3), inset 0 0 20px rgba(94,231,255,.04);
  transition: border-color .6s, box-shadow .6s;
}
.jh-consola:focus-within { box-shadow: 0 0 0 1px rgba(0,0,0,.4), 0 0 34px var(--jh-c2), inset 0 0 20px rgba(94,231,255,.06); }
.jh-consola .jh-esq { opacity: 1; }
.jh-prompt { font-family: 'DM Mono', monospace; color: var(--jh-c); font-size: 18px; padding: 0 2px 2px 4px; }
.jh-input { flex: 1; min-width: 0; background: transparent; border: none; color: var(--jh-texto); font-size: 15px; padding: 10px 4px; font-family: 'DM Sans', sans-serif; outline: none; }
.jh-input::placeholder { color: var(--jh-tenue); }
.jh-icono {
  width: 38px; height: 38px; flex-shrink: 0; display: grid; place-items: center; font-size: 15px;
  background: transparent; border: 1px solid transparent; color: var(--jh-tenue); border-radius: 3px; cursor: pointer; transition: all .2s;
}
.jh-icono:hover { border-color: var(--jh-c3); color: var(--jh-c); }
.jh-icono.activo { border-color: var(--jh-c2); background: var(--jh-c3); color: var(--jh-c); }
.jh-potencia { font-size: 16px; filter: grayscale(1) brightness(.9); }
.jh-potencia.activo { filter: none; border-color: rgba(255,181,71,.6); background: rgba(255,181,71,.12); box-shadow: 0 0 14px rgba(255,181,71,.3); }
.jh-enviar {
  font-family: 'Rajdhani', sans-serif !important; font-weight: 700; letter-spacing: .22em; text-transform: uppercase; font-size: 13px;
  height: 38px; padding: 0 16px; border: none; border-radius: 2px; cursor: pointer; flex-shrink: 0;
  background: var(--jh-c); color: #02121a; box-shadow: 0 0 16px var(--jh-c2); transition: all .2s;
}
.jh-enviar:disabled { opacity: .3; cursor: default; box-shadow: none; }
.jh-enviar-icono { display: none; }
.jh-consola-llamada { gap: 14px; padding: 12px 12px 12px 18px; }
.jh-llamada-punto { width: 12px; height: 12px; border-radius: 50%; background: var(--jh-c); box-shadow: 0 0 14px var(--jh-c); animation: jhLatido 1.2s infinite; flex-shrink: 0; }
.jh-llamada-texto { flex: 1; min-width: 0; }
.jh-llamada-fase { font-family: 'Rajdhani', sans-serif; font-weight: 700; letter-spacing: .3em; text-transform: uppercase; color: var(--jh-c); font-size: 14px; }
.jh-llamada-parcial { font-size: 14px; color: var(--jh-tenue); font-style: italic; margin-top: 2px; }

/* El campo de texto no: el foco ya lo dice el brillo de la consola entera. */
.jh :focus-visible:not(input) { outline: 2px solid var(--jh-c) !important; outline-offset: 2px; }

/* Móvil y pantallas estrechas: sin paneles laterales */
@media (max-width: 1080px) {
  .jh-cuerpo { grid-template-columns: 210px minmax(0, 1fr); }
  .jh-columna-der { display: none; }
}
@media (max-width: 820px) {
  .jh-cuerpo { grid-template-columns: minmax(0, 1fr); padding: 0 12px max(12px, env(safe-area-inset-bottom)); gap: 0; }
  .jh-columna { display: none; }
  .jh-cabecera { padding-left: 16px; padding-right: 12px; }
  .jh-marca { font-size: 16px; letter-spacing: .26em; }
  .jh-marca-sub { display: none; }
  .jh-estado-movil { display: block; }
  .jh-reactor { width: min(200px, 30vh); }
  .jh-centro:has(.jh-msg) .jh-reactor { width: min(120px, 18vh); }
  .jh-centro:has(.jh-msg) .jh-estado-movil { display: none; }
  .jh-estado { font-size: 13px; letter-spacing: .32em; }
  .jh-msg { max-width: 100%; }
  .jh-msg-texto { font-size: 15px; }
  /* En un móvil el campo de texto es lo que no puede quedarse sin sitio. */
  .jh-consola { gap: 2px; padding: 4px 4px 4px 4px; }
  .jh-prompt { display: none; }
  .jh-enviar { padding: 0; width: 38px; }
  .jh-enviar-texto { display: none; }
  .jh-enviar-icono { display: inline; font-size: 15px; }
  .jh-icono { width: 32px; }
}

@keyframes jhEntrada { from { opacity: 0; transform: scale(1.015); } to { opacity: 1; transform: none; } }
@keyframes jhSalida { to { opacity: 0; visibility: hidden; } }
@keyframes jhLinea { from { opacity: 0; transform: translateY(4px); } to { opacity: 1; transform: none; } }
@keyframes jhBarrido { from { background-position: 0 -220px; } to { background-position: 0 calc(100vh + 220px); } }
@keyframes jhGiro { to { transform: rotate(360deg); } }
@keyframes jhRespira { 0%, 100% { opacity: .55; transform: scale(.96); } 50% { opacity: .95; transform: scale(1.04); } }
@keyframes jhLatido { 0%, 100% { opacity: 1; } 50% { opacity: .25; } }
@keyframes jhBarra { from { opacity: .25; transform: scaleY(.25); } to { opacity: .95; transform: scaleY(1); } }
@keyframes jhPunto { 0%, 100% { opacity: .25; transform: rotate(45deg) scale(.7); } 50% { opacity: 1; transform: rotate(45deg) scale(1); } }
@keyframes jhMsg { from { opacity: 0; transform: translateY(6px); } to { opacity: 1; transform: none; } }
@keyframes jhPanel { from { opacity: 0; transform: translateY(8px); } to { opacity: 1; transform: none; } }
@keyframes jhBurbuja { from { opacity: 0; transform: translate(var(--dx), var(--dy)) scale(.3); } to { opacity: 1; transform: none; } }
@keyframes jhPulso { from { transform: scale(.4); box-shadow: 0 0 0 0 var(--jh-c); } to { transform: scale(1.3); box-shadow: 0 0 0 14px transparent; } }
@keyframes jhAlerta { 0%, 100% { box-shadow: 0 0 0 rgba(255,95,87,0); } 50% { box-shadow: 0 0 24px rgba(255,95,87,.25); } }

@media (prefers-reduced-motion: reduce) {
  .jh *, .jh *::before, .jh { animation: none !important; transition: none !important; }
  .jh-barras rect { opacity: .3; }
}
`;
