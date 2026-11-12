// Las recetas de los paneles que Jarvis ha dibujado (ver PanelesVivos.jsx): cuáles hay en
// el backend, quitarlas, y reponerlas tras un despliegue (allí viven en memoria).
import { useCallback, useEffect, useState } from "react";
import { API, authHeaders, jsonHeaders, apiFetch } from "../../lib/api";
import { guardar, leerGuardados, tocaReponer } from "../../lib/hudPaneles";

/** Las recetas que hay en el backend, al día: al abrir, al acabar cada turno de Jarvis
 *  (es cuando puede haber puesto o quitado una) y cada minuto, por si lo hizo hablando
 *  por teléfono. */
export function usePanelesVivos(pensando) {
  const [paneles, setPaneles] = useState(() => leerGuardados().paneles);

  const cargar = useCallback(async () => {
    try {
      const r = await apiFetch(`${API}/hud/paneles`, { headers: authHeaders() });
      if (!r.ok) return;
      let remoto = await r.json();
      const guardados = leerGuardados();
      if (tocaReponer(remoto, guardados)) {
        const rr = await apiFetch(`${API}/hud/paneles`, {
          method: "PUT", headers: jsonHeaders(), body: JSON.stringify({ paneles: guardados.paneles }),
        });
        if (rr.ok) remoto = { ...remoto, ...(await rr.json()) };
      }
      const lista = Array.isArray(remoto.paneles) ? remoto.paneles : [];
      guardar(String(remoto.instancia || ""), lista);
      setPaneles(lista);
    } catch { /* sin backend se quedan los que había */ }
  }, []);

  useEffect(() => {
    if (pensando) return undefined;
    const ya = setTimeout(cargar, 0);
    const t = setInterval(cargar, 60_000);
    return () => { clearTimeout(ya); clearInterval(t); };
  }, [pensando, cargar]);

  const quitar = useCallback(async (id) => {
    setPaneles(ps => ps.filter(p => p.id !== id));
    try {
      await apiFetch(`${API}/hud/paneles/${encodeURIComponent(id)}`, { method: "DELETE", headers: authHeaders() });
    } catch { /* la próxima carga dirá lo que hay de verdad */ }
    cargar();
  }, [cargar]);

  return { paneles, quitar };
}
