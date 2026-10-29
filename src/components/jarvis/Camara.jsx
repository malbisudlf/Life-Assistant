// El panel de la cámara en la vista J.A.R.V.I.S. La cámara en sí (abrirla, el
// fotograma) está en useCamara.js; aquí solo se pinta.

/** El panel con el vídeo. En espejo, como un espejo: es como uno espera verse. En el
 *  modo inmersivo (`inmersivo`) el vídeo está de fondo en la pantalla entera y aquí solo
 *  quedan los mandos, con el «EN DIRECTO» siempre a la vista. */
export function PanelCamara({ ponVideo, estado, error, jarvisVe, onJarvisVe, manos, onManos, estadoManos, asa,
                              inmersivo, onInmersivo }) {
  return (
    <>
      <div className="jh-panel-titulo jh-asa" {...asa}>
        Visión
        <span className={`jh-directo${estado === "en_directo" ? " vivo" : ""}`}>
          {estado === "en_directo" ? "● EN DIRECTO" : estado === "error" ? "SIN SEÑAL" : "CONECTANDO"}
        </span>
      </div>
      {!inmersivo && (
        <div className="jh-camara">
          <video ref={ponVideo} muted playsInline autoPlay className="jh-camara-video" />
          <span className="jh-camara-reticula" aria-hidden="true" />
          {estado !== "en_directo" && <div className="jh-camara-aviso">{error || "Abriendo la cámara…"}</div>}
        </div>
      )}
      {inmersivo && estado !== "en_directo" && <div className="jh-nota">{error || "Abriendo la cámara…"}</div>}
      <div className="jh-camara-botones">
        <button type="button" className={`jh-boton-fino${jarvisVe ? " activo" : ""}`} onClick={onJarvisVe}
                aria-pressed={jarvisVe}
                title="Con esto encendido, cada mensaje lleva lo que ve la cámara en ese momento">
          {jarvisVe ? "Jarvis le ve" : "Jarvis no mira"}
        </button>
        <button type="button" className={`jh-boton-fino${manos ? " activo" : ""}`} onClick={onManos}
                aria-pressed={manos}
                title="Mover el cursor con el índice, pellizcar para pulsar y pellizcar y arrastrar para mover los paneles">
          {manos ? (estadoManos === "cargando" ? "Cargando manos…" : estadoManos === "error" ? "Manos: error" : "Manos activas") : "Usar las manos"}
        </button>
        <button type="button" className={`jh-boton-fino${inmersivo ? " activo" : ""}`} onClick={onInmersivo}
                aria-pressed={inmersivo}
                title="La cámara a pantalla completa con los paneles flotando encima: cada dedo pulsa al empujarlo hacia la pantalla">
          {inmersivo ? "Salir del inmersivo" : "Modo inmersivo"}
        </button>
      </div>
    </>
  );
}
