// Los proyectos del programador, para el panel de proyectos y para el menú radial del
// puño: los dos enseñan lo mismo, así que se piden una vez y se comparten. Solo se
// pregunta mientras alguno de los dos puede verse (`activo`), cada `CADA_MS`.
import { useCallback, useEffect, useState } from "react";
import { API, authHeaders, apiFetch } from "../../lib/api";

const CADA_MS = 20000;

export function useProyectos(activo) {
  const [datos, setDatos] = useState(null);

  const recargar = useCallback(() => {
    apiFetch(`${API}/programador/proyectos`, { headers: authHeaders() })
      .then(r => (r.ok ? r.json() : null))
      .then(d => { if (d) setDatos(d); })
      .catch(() => { /* sin red: se queda lo último que se vio */ });
  }, []);

  useEffect(() => {
    if (!activo) return;
    recargar();
    const t = setInterval(recargar, CADA_MS);
    return () => clearInterval(t);
  }, [activo, recargar]);

  return { datos, recargar };
}
