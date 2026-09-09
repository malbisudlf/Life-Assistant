// Piezas visuales compartidas por las pestañas de la zona de desarrollo.
//
// La paleta es la misma del dashboard (las variables CSS de GLOBAL_CSS): lo que cambia es
// la densidad. Aquí se mira un registro de doscientas líneas y una tabla de veinte ideas,
// así que la tipografía de datos es monoespaciada y cabe mucho más por pantalla.
//
// Solo componentes: los estilos y los helpers están en src/lib/dev.js, porque un .jsx que
// exporta otra cosa rompe el refresco en caliente (regla react-refresh).
import { botonStyle } from "../../lib/dev";

export function Boton({ children, onClick, disabled, tono = "normal", title }) {
  const colores = {
    normal:  { color: "var(--muted)",  border: "var(--border2)" },
    acento:  { color: "var(--accent)", border: "rgba(200,169,110,0.35)" },
    peligro: { color: "#c9736b",       border: "rgba(201,115,107,0.35)" },
  }[tono];
  return (
    <button
      type="button"
      onClick={onClick}
      disabled={disabled}
      title={title}
      style={{
        ...botonStyle,
        color:  colores.color,
        border: `0.5px solid ${colores.border}`,
        opacity: disabled ? 0.4 : 1,
        cursor:  disabled ? "default" : "pointer",
      }}
    >
      {children}
    </button>
  );
}

// Lo que se enseña cuando no hay nada que enseñar. Nunca un cero suelto: "no lo sé" y "no
// hay" son cosas distintas, y esa distinción sostiene medio proyecto.
export function Vacio({ children }) {
  return (
    <div style={{ padding: "28px 12px", textAlign: "center", color: "var(--muted2)", fontSize: 12 }}>
      {children}
    </div>
  );
}
