// Cómo se habla con el backend. Estaba dentro de Dashboard.jsx y se saca aquí porque la
// zona de desarrollo (src/components/dev/) necesita lo mismo: duplicarlo habría dejado
// DOS sitios que saben cómo se autentica el cliente, y el día que cambie el esquema uno
// de los dos se queda atrás sin avisar.

// Configuración de instancia (kit self-hosted): se personaliza con variables VITE_* en Vercel/.env
export const API = import.meta.env.VITE_API_URL || "https://api.lifeassistantbackend.bid";

// Cabeceras de una llamada autenticada. El token se lee en el momento y no se captura
// en un closure: si la sesión se renueva a mitad de una pantalla, la siguiente llamada
// ya usa el nuevo. Único sitio que toca el esquema de autenticación.
export function authHeaders(extra = {}) {
  const token = localStorage.getItem("la_token") || "";
  return { "Authorization": `Bearer ${token}`, ...extra };
}

// Atajo para las llamadas que mandan JSON, que son casi todas las de escritura.
export function jsonHeaders() {
  return authHeaders({ "Content-Type": "application/json" });
}

// Ante un 401 con sesión activa, borra el token y recarga. SOLO si había token: muchos
// useEffect de carga inicial se ejecutan al montar aunque no haya sesión y reciben un
// 401; cuando esto recargaba siempre, era un bucle infinito de recargas (pantalla de
// login parpadeando, sin poder pulsar nada — visible sobre todo en móvil).
export async function apiFetch(url, options = {}) {
  const res = await fetch(url, options);
  if (res.status === 401 && localStorage.getItem("la_token")) {
    localStorage.removeItem("la_token");
    window.location.reload();
    await new Promise(resolve => setTimeout(resolve, 1000));
  }
  return res;
}
