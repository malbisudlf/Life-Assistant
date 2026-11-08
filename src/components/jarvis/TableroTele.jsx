import { useEffect, useState } from "react";
import { API } from "../../lib/api";
import { CLAVE_TELE, llaveDelFragmento, lineaTiempo, maquinas, textoWhatsapp } from "../../lib/tablero";

// El tablero de la tele de la sala (2026-11-08): la vista J.A.R.V.I.S. para mirar desde el
// sofá. Va aparte del dashboard porque no tiene login: usa la llave de solo lectura de
// GET /tele/tablero (ver src/lib/tablero.js). Letra grande, nada que pulsar, y se refresca
// sola cada minuto. Ver «El tablero de la tele» en docs/JARVIS.md.

const CADA_MS = 60000;

function leerLlave() {
  const delFragmento = llaveDelFragmento(window.location.hash);
  try {
    if (delFragmento) {
      localStorage.setItem(CLAVE_TELE, delFragmento);
      // Fuera de la barra: la pantalla la ve toda la casa.
      window.history.replaceState(null, "", window.location.pathname + "#tele");
      return delFragmento;
    }
    return localStorage.getItem(CLAVE_TELE) || "";
  } catch {
    return delFragmento;
  }
}

export default function TableroTele() {
  const [llave] = useState(leerLlave);
  const [datos, setDatos] = useState(null);
  const [error, setError] = useState(llave ? "" : "Falta la llave del tablero (#tele=…).");

  useEffect(() => {
    if (!llave) return undefined;
    let vivo = true;
    const pedir = async () => {
      try {
        const r = await fetch(`${API}/tele/tablero`, { headers: { "X-Auth-Token": llave } });
        if (!vivo) return;
        if (r.status === 401) { setError("La llave del tablero no vale."); return; }
        if (!r.ok) { setError("El backend no contesta."); return; }
        setDatos(await r.json());
        setError("");
      } catch {
        if (vivo) setError("Sin conexión con caja.");
      }
    };
    pedir();
    const reloj = setInterval(pedir, CADA_MS);
    return () => { vivo = false; clearInterval(reloj); };
  }, [llave]);

  const agenda = datos?.agenda || [];
  return (
    <div className="tt">
      <style>{CSS}</style>
      <header className="tt-cabecera">
        <div className="tt-marca"><span className="tt-punto" />J.A.R.V.I.S.</div>
        <div className="tt-dia">{datos ? `${datos.dia} ${Number(datos.fecha.slice(8, 10))}` : ""}</div>
      </header>
      <main className="tt-cuerpo">
        <section className="tt-reloj">
          <div className="tt-hora">{datos?.hora || "--:--"}</div>
          {datos?.saludo && <div className="tt-saludo">{datos.saludo}</div>}
          <div className="tt-tiempo">{lineaTiempo(datos?.tiempo)}</div>
          {datos?.alarma && <div className="tt-alarma">{datos.alarma}</div>}
        </section>
        <section className="tt-panel">
          <h2>Hoy</h2>
          {agenda.length === 0 && <p className="tt-tenue">{datos ? "Nada más en la agenda." : ""}</p>}
          <ul>
            {agenda.map((e, i) => (
              <li key={i} className={e.en_curso ? "tt-ahora" : ""}>
                <span className="tt-h">{e.hora}</span>{e.titulo}
              </li>
            ))}
          </ul>
          {datos?.manana && (
            <p className="tt-manana"><span className="tt-h">Mañana</span>{datos.manana.hora} · {datos.manana.titulo}</p>
          )}
        </section>
        <section className="tt-lateral">
          <div className="tt-panel">
            <h2>Sistemas</h2>
            <ul className="tt-fila">
              {maquinas(datos?.maquinas).map((m) => (
                <li key={m.nombre}><span className={`tt-led tt-${m.estado}`} />{m.nombre}</li>
              ))}
            </ul>
            {textoWhatsapp(datos?.whatsapp_pendientes) && (
              <p><span className="tt-etiqueta">WhatsApp</span>{textoWhatsapp(datos.whatsapp_pendientes)}</p>
            )}
          </div>
          {(datos?.entreno || datos?.sueno) && (
            <div className="tt-panel">
              <h2>Cuerpo</h2>
              {datos?.entreno && <p><span className="tt-etiqueta">Hoy</span>{datos.entreno.hoy}</p>}
              {datos?.entreno?.semana && <p className="tt-tenue tt-peq">{datos.entreno.semana.join(" · ")}</p>}
              {datos?.sueno && <p><span className="tt-etiqueta">Anoche</span>{datos.sueno}</p>}
            </div>
          )}
        </section>
      </main>
      {error && <footer className="tt-error">{error}</footer>}
    </div>
  );
}

const CSS = `
@import url('https://fonts.googleapis.com/css2?family=Rajdhani:wght@500;600;700&display=swap');
.tt { --c: #5ee7ff; --c2: rgba(94,231,255,.55); --c3: rgba(94,231,255,.16); --texto: #d9f6ff;
  --tenue: rgba(190,235,250,.55); --amb: #ffb547; --rojo: #ff5f57;
  position: fixed; inset: 0; background: #02060b; color: var(--texto);
  font-family: 'Rajdhani', 'DM Sans', sans-serif; display: flex; flex-direction: column;
  padding: 3vh 4vw; box-sizing: border-box; overflow: hidden; }
.tt-cabecera { display: flex; justify-content: space-between; align-items: center;
  font-size: 2.4vh; letter-spacing: .3em; color: var(--c); text-transform: uppercase; }
.tt-marca { display: flex; align-items: center; gap: 1vh; }
.tt-punto { width: 1.2vh; height: 1.2vh; border-radius: 50%; background: var(--c); box-shadow: 0 0 1.5vh var(--c); animation: ttLatido 3s ease-in-out infinite; }
@keyframes ttLatido { 50% { opacity: .35; box-shadow: 0 0 .4vh var(--c); } }
.tt-dia { color: var(--tenue); letter-spacing: .15em; }
.tt-cuerpo { flex: 1; display: grid; grid-template-columns: 1.1fr 1.4fr .8fr; gap: 3vw; align-items: center; }
.tt-hora { font-size: 18vh; font-weight: 600; line-height: 1; color: var(--c); text-shadow: 0 0 4vh rgba(94,231,255,.35); }
.tt-saludo { font-size: 3vh; margin-top: 2.2vh; color: var(--c); opacity: .85; line-height: 1.3; max-width: 30vw; }
.tt-tiempo { font-size: 3.6vh; margin-top: 2vh; }
.tt-alarma { font-size: 2.6vh; margin-top: 2vh; color: var(--amb); }
.tt-panel { border: 1px solid var(--c3); border-radius: 1vh; padding: 3vh 2vw;
  background: linear-gradient(180deg, rgba(94,231,255,.06), rgba(94,231,255,0) 60%); }
.tt-panel h2 { margin: 0 0 1.5vh; font-size: 2.2vh; letter-spacing: .3em; color: var(--c2); text-transform: uppercase; font-weight: 600; }
.tt-panel ul { list-style: none; margin: 0 0 3vh; padding: 0; }
.tt-panel li { font-size: 3.2vh; padding: .8vh 0; border-bottom: 1px solid rgba(94,231,255,.07); display: flex; align-items: center; gap: 1.5vw; }
.tt-panel p { font-size: 3vh; margin: 0 0 1vh; }
.tt-lateral { display: flex; flex-direction: column; gap: 3vh; }
.tt-lateral .tt-panel { padding: 2.4vh 1.6vw; }
.tt-lateral ul { margin-bottom: 1.5vh; }
.tt-fila li { font-size: 2.8vh; padding: .5vh 0; }
.tt-etiqueta { color: var(--c2); font-size: 2vh; letter-spacing: .2em; text-transform: uppercase; margin-right: 1vw; }
.tt-peq { font-size: 2.3vh !important; }
.tt-manana .tt-h { margin-right: 1.2vw; }
.tt-manana { margin-top: 2vh !important; color: var(--tenue); font-size: 2.6vh !important; }
.tt-h { color: var(--c); min-width: 6.5vw; font-variant-numeric: tabular-nums; }
.tt-ahora { color: var(--c); }
.tt-tenue { color: var(--tenue); }
.tt-led { width: 1.4vh; height: 1.4vh; border-radius: 50%; display: inline-block; }
.tt-ok { background: #3ddc84; box-shadow: 0 0 1vh #3ddc84; }
.tt-caida { background: var(--rojo); box-shadow: 0 0 1vh var(--rojo); }
.tt-nose { background: var(--tenue); }
.tt-error { text-align: center; color: var(--amb); font-size: 2.4vh; }
`;
