// La vista de Jarvis a pantalla completa: el reactor en el centro, la conversación
// debajo y la telemetría a los lados, con el aire del HUD de Iron Man.
//
// Vive en su propio fichero, como la zona dev, porque no es un widget: es otra forma de
// usar la aplicación, se carga en diferido y no comparte nada de la maqueta del
// dashboard. Lo que NO tiene es estado propio de la conversación: los mensajes, el envío,
// la confirmación, el dictado y la llamada son los de la tarjeta de Jarvis (Dashboard.jsx),
// así que lo que hables aquí sigue allí al salir y al revés. La lógica de qué se pinta
// está en src/lib/jarvisHud.js.
import React, { useEffect, useMemo, useRef, useState } from "react";
import {
  estadoHud, TEXTO_ESTADO, motorEsperado, nombreModelo, protocolosUsados,
  nombreProtocolo, trocearRespuesta, duracionTecleo, textoDuracion,
} from "../../lib/jarvisHud";

const VOZ_NAVEGADOR = typeof window !== "undefined"
  && Boolean(window.SpeechRecognition || window.webkitSpeechRecognition);
const VOZ_SINTESIS  = typeof window !== "undefined" && "speechSynthesis" in window;
const SIN_MOVIMIENTO = typeof window !== "undefined"
  && window.matchMedia?.("(prefers-reduced-motion: reduce)")?.matches;

// El arranque se ve una vez por carga de la página: es una presentación, no un peaje.
let arrancado = false;

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
  potente, onPotente, onNueva, onSalir, briefing, host,
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
  const protocolos = useMemo(() => protocolosUsados(mensajes), [mensajes]);

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
      if (e.key === "Escape" && !enLlamada) { e.preventDefault(); onSalir(); }
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
        <aside className="jh-panel jh-panel-izq" aria-label="Estado del sistema">
          <Esquinas />
          <div className="jh-panel-titulo">Sistema</div>
          <Dato etiqueta="Motor" valor={`Claude · ${motor.nombre}`} acento={potente} />
          {motor.nota && <div className="jh-nota">{motor.nota}</div>}
          <Dato etiqueta="Potencia" valor={potente ? "Máxima" : "Estándar"} acento={potente} />
          {ultimo && (
            <Dato etiqueta="Último turno"
                  valor={[nombreModelo(ultimo.modelo) || (ultimo.motor === "openai" ? "Respaldo" : ""),
                          textoDuracion(ultimo.ms)].filter(Boolean).join(" · ") || "—"} />
          )}
          <Dato etiqueta="Enlace" valor={host} />
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
        </aside>

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
        <aside className="jh-panel jh-panel-der" aria-label="El día">
          <Esquinas />
          <div className="jh-reloj">{hh}<span className="jh-reloj-sep">:</span>{mm}<span className="jh-reloj-seg">{ss}</span></div>
          <div className="jh-fecha">{fecha}</div>
          {briefing?.frase && <div className="jh-briefing-frase">{briefing.frase}</div>}
          {briefing?.clima && <Dato etiqueta="Exterior" valor={briefing.clima} />}
          {briefing?.lineas?.length > 0 && (
            <>
              <div className="jh-panel-titulo" style={{ marginTop: 14 }}>En el radar</div>
              {briefing.lineas.map(l => <div key={l} className="jh-radar">{l}</div>)}
            </>
          )}
        </aside>
      </div>
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
      <Tecleado texto={m.texto} activo={teclear && !SIN_MOVIMIENTO} />
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
.jh-panel {
  position: relative; align-self: start; margin-top: 30px;
  border: 1px solid var(--jh-c3); background: linear-gradient(180deg, rgba(94,231,255,.04), transparent);
  padding: 16px 16px 18px; border-radius: 2px; transition: border-color .6s;
  clip-path: polygon(0 0, calc(100% - 16px) 0, 100% 16px, 100% 100%, 16px 100%, 0 calc(100% - 16px));
  animation: jhPanel .6s ease-out;
}
.jh-panel-titulo {
  font-family: 'Rajdhani', sans-serif; font-weight: 700; font-size: 12px; letter-spacing: .3em;
  text-transform: uppercase; color: var(--jh-c); margin-bottom: 10px; display: flex; align-items: center; gap: 8px;
}
.jh-panel-titulo::after { content: ""; flex: 1; height: 1px; background: linear-gradient(90deg, var(--jh-c2), transparent); }
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
  .jh-panel-der { display: none; }
}
@media (max-width: 820px) {
  .jh-cuerpo { grid-template-columns: minmax(0, 1fr); padding: 0 12px max(12px, env(safe-area-inset-bottom)); gap: 0; }
  .jh-panel { display: none; }
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
@keyframes jhAlerta { 0%, 100% { box-shadow: 0 0 0 rgba(255,95,87,0); } 50% { box-shadow: 0 0 24px rgba(255,95,87,.25); } }

@media (prefers-reduced-motion: reduce) {
  .jh *, .jh *::before, .jh { animation: none !important; transition: none !important; }
  .jh-barras rect { opacity: .3; }
}
`;
