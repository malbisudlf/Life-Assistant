// Los proyectos de la vista J.A.R.V.I.S.: lo que tiene entre manos el programador
// (docs/PROGRAMADOR.md), cómo va cada uno, y desde aquí mismo crear uno nuevo o decirle
// algo al que esté en marcha.
//
// No hay lógica nueva detrás: verlos es `ver_proyectos`, hablarle es
// `hablar_con_el_programador` (los dos por `/programador/...`) y crear es
// `encargar_proyecto` por `/jarvis/ejecutar`, donde pulsar «Encargar» es el «sí» que esa
// herramienta pide, igual que el botón de confirmar de la tarjeta. Lo que cuenta el
// programador lo escribe un modelo que ha leído repositorios: se pinta como texto, nunca
// como HTML, y el enlace al PR solo si es de GitHub.
import { useState } from "react";
import { API, jsonHeaders, apiFetch } from "../../lib/api";
import { porcentajeDe } from "../../lib/gestos";
import { ESTADOS, prDeConfianza, recorta } from "../../lib/proyectos";

/** Los datos los trae `useProyectos` (los comparte con el menú del puño). `abrir` es lo
 *  que se eligió en ese menú: `{ id, vez }`, con `id` el del proyecto o "nuevo". */
export default function PanelProyectos({ asa, datos, recargar, abrir }) {
  const cargar = recargar;
  const [abierto, setAbierto]   = useState(null);
  const [nuevo, setNuevo]       = useState(false);
  const [titulo, setTitulo]     = useState("");
  const [encargo, setEncargo]   = useState("");
  const [repo, setRepo]         = useState("");
  const [mensaje, setMensaje]   = useState("");
  const [enviando, setEnviando] = useState(false);
  const [aviso, setAviso]       = useState("");
  // Lo elegido con el puño abre aquí su proyecto (o el formulario de uno nuevo). Se ajusta
  // durante el render, no en un efecto: es estado que sigue a una prop.
  const [abrirVisto, setAbrirVisto] = useState(null);
  if (abrir && abrir !== abrirVisto) {
    setAbrirVisto(abrir);
    if (abrir.id === "nuevo") { setNuevo(true); setAviso(""); }
    else { setNuevo(false); setAbierto(abrir.id); }
  }

  async function encargar(e) {
    e.preventDefault();
    if (!titulo.trim() || !encargo.trim() || enviando) return;
    setEnviando(true);
    setAviso("");
    try {
      const r = await apiFetch(`${API}/jarvis/ejecutar`, {
        method: "POST", headers: jsonHeaders(),
        body: JSON.stringify({ herramienta: "encargar_proyecto",
                               argumentos: { titulo: titulo.trim(), encargo: encargo.trim(), repo: repo.trim() } }),
      });
      const d = await r.json().catch(() => ({}));
      if (r.ok && d?.ok) {
        setAviso(d.resultado?.nota || "Encargado.");
        setTitulo(""); setEncargo(""); setRepo(""); setNuevo(false);
        cargar();
      } else {
        setAviso(d?.resultado?.error || d?.detail || "No se ha podido encargar.");
      }
    } catch {
      setAviso("Sin conexión con el backend.");
    } finally {
      setEnviando(false);
    }
  }

  async function hablar(e, proyecto) {
    e.preventDefault();
    if (!mensaje.trim() || enviando) return;
    setEnviando(true);
    setAviso("");
    try {
      const r = await apiFetch(`${API}/programador/mensaje`, {
        method: "POST", headers: jsonHeaders(),
        body: JSON.stringify({ mensaje: mensaje.trim(), proyecto }),
      });
      const d = await r.json().catch(() => ({}));
      setAviso(d?.ok ? (d.como || "Se lo he dicho.") : (d?.error || d?.detail || "No se ha podido."));
      if (d?.ok) { setMensaje(""); cargar(); }
    } catch {
      setAviso("Sin conexión con el backend.");
    } finally {
      setEnviando(false);
    }
  }

  const proyectos = datos?.proyectos || [];
  return (
    <>
      <div className="jh-panel-titulo jh-asa" {...asa}>
        Proyectos
        {datos?.configurado && (
          <button type="button" className="jh-mini" onClick={() => { setNuevo(v => !v); setAviso(""); }}
                  aria-expanded={nuevo}>{nuevo ? "Cancelar" : "+ Nuevo"}</button>
        )}
      </div>

      {datos && !datos.configurado && (
        <div className="jh-nota">El programador no está configurado en caja.</div>
      )}
      {datos?.configurado && datos.ok === false && (
        <div className="jh-nota">{datos.error || "El programador no contesta."}</div>
      )}

      {nuevo && (
        <form className="jh-proy-form" onSubmit={encargar}>
          <input className="jh-campo" value={titulo} onChange={e => setTitulo(e.target.value)} maxLength={120}
                 placeholder="Título («web: lista de la compra»)" aria-label="Título del proyecto" />
          <textarea className="jh-campo" value={encargo} onChange={e => setEncargo(e.target.value)} rows={4}
                    maxLength={6000} placeholder="Qué quiere, con detalle" aria-label="Descripción del proyecto" />
          <input className="jh-campo" value={repo} onChange={e => setRepo(e.target.value)} maxLength={150}
                 placeholder="Repositorio de GitHub (opcional: usuario/nombre)" aria-label="Repositorio" />
          <button type="submit" className="jh-boton jh-boton-si" disabled={enviando || !titulo.trim() || !encargo.trim()}>
            {enviando ? "Encargando…" : "Encargar"}
          </button>
        </form>
      )}

      {aviso && <div className="jh-proy-aviso">{aviso}</div>}

      {datos?.configurado && !nuevo && proyectos.length === 0 && datos.ok !== false && (
        <div className="jh-nota">Ningún proyecto todavía. «+ Nuevo» para encargar el primero.</div>
      )}

      {!nuevo && proyectos.map(p => {
        const id = p.id || p.proyecto;
        const pct = porcentajeDe(p.progreso);
        const abiertoAqui = abierto === id;
        const pr = prDeConfianza(p.pr);
        return (
          <div key={id} className={`jh-proy${abiertoAqui ? " abierto" : ""}`}>
            <button type="button" className="jh-proy-cab" onClick={() => setAbierto(abiertoAqui ? null : id)}
                    aria-expanded={abiertoAqui}>
              <span className="jh-proy-titulo">{recorta(p.titulo || p.proyecto, 60)}</span>
              <span className={`jh-proy-estado e-${p.estado}`}>{ESTADOS[p.estado] || p.estado}</span>
            </button>
            {pct != null && (
              <div className="jh-proy-barra" role="progressbar" aria-valuenow={pct} aria-valuemin={0} aria-valuemax={100}>
                <span style={{ width: `${pct}%` }} />
              </div>
            )}
            {p.ahora && <div className="jh-proy-ahora">{recorta(p.ahora, 110)}</div>}
            {abiertoAqui && (
              <div className="jh-proy-detalle">
                {(p.respuesta || p.resumen || p.motivo) && (
                  <div className="jh-proy-texto">{recorta(p.respuesta || p.resumen || p.motivo, 600)}</div>
                )}
                {pr && <a className="jh-proy-pr" href={pr} target="_blank" rel="noopener noreferrer">Ver el PR ↗</a>}
                {p.se_puede_hablar !== false && (
                  <form className="jh-proy-hablar" onSubmit={e => hablar(e, p.proyecto || p.id)}>
                    <input className="jh-campo" value={mensaje} onChange={e => setMensaje(e.target.value)}
                           maxLength={4000} placeholder="Decirle al programador…" aria-label="Mensaje al programador" />
                    <button type="submit" className="jh-mini" disabled={enviando || !mensaje.trim()}>Enviar</button>
                  </form>
                )}
              </div>
            )}
          </div>
        );
      })}
    </>
  );
}
