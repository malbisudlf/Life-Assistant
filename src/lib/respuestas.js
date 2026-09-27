// Cómo se lee lo que devuelve el backend cuando NO ha ido bien. Lógica pura, sin fetch.
//
// Existe porque el dashboard tenía la misma costumbre repetida en media docena de
// sitios: mirar solo el camino bueno y dar cualquier otra respuesta por buena o por
// vacía. Así un 429 del login se leía como «contraseña incorrecta», un 502 de /export se
// descargaba como si fuera la copia, y una caída de Graph se pintaba como sesión
// caducada. Lo que se decide aquí es qué FRASE merece cada fallo; qué hacer con ella
// sigue siendo de la pantalla.

/** El `detail` de FastAPI en texto. Un 422 de validación lo trae como LISTA de errores
 *  (`[{msg, loc, …}]`), no como string: pintarlo tal cual sale `[object Object]`, y
 *  descartarlo deja el fallo sin explicar. */
export function detalleDeError(cuerpo) {
  const d = cuerpo?.detail;
  if (typeof d === "string") return d.trim();
  if (Array.isArray(d)) {
    return d.map(e => (typeof e === "string" ? e : e?.msg))
            .filter(Boolean)
            .map(m => String(m).replace(/^Value error, /, ""))
            .join("; ");
  }
  return "";
}

/** La frase para una escritura que el backend ha rechazado. Si el backend explica por
 *  qué, se usa su explicación; si no, al menos el código, que es lo que distingue «lo
 *  que has mandado no vale» (4xx, se arregla cambiándolo) de «el backend está mal»
 *  (5xx, se arregla reintentando más tarde). */
export function textoErrorApi(status, cuerpo) {
  const detalle = detalleDeError(cuerpo);
  if (status === 422) return `Datos no válidos${detalle ? `: ${detalle}` : ""}`;
  if (detalle) return detalle;
  if (status >= 500) return `El backend ha fallado (error ${status})`;
  return `No se ha podido guardar (error ${status})`;
}

/** Qué decir cuando /auth/password no devuelve token.
 *
 *  Antes todo era «Contraseña incorrecta», y el caso que más engaña es el 429: el límite
 *  de intentos es GLOBAL (no por IP, ver CLAUDE.md), así que bastan cinco fallos de un
 *  tercero para que la contraseña buena reciba un 429 sin que el backend la mire
 *  siquiera. Quien lee «incorrecta» prueba variantes, y cada fallo tras el bloqueo
 *  cuenta para la siguiente tanda, que dobla la espera. `retryAfter` es la cabecera
 *  `Retry-After` en segundos, si llegó. */
export function mensajeErrorLogin(status, cuerpo, retryAfter) {
  if (status === 429) {
    const seg = parseInt(retryAfter, 10);
    if (Number.isFinite(seg) && seg > 0) {
      const espera = seg < 60 ? `${seg} s` : `${Math.ceil(seg / 60)} min`;
      return `Demasiados intentos. Espera ${espera} y vuelve a probar`;
    }
    return detalleDeError(cuerpo) || "Demasiados intentos. Espera un poco y vuelve a probar";
  }
  if (status >= 500) return `Error del servidor (${status})`;
  return "Contraseña incorrecta";
}

/** Lo que dice /calendar/events, separado en las tres cosas que la pantalla necesita:
 *  los eventos, si hay que ofrecer reconectar Outlook y el error que no es de sesión.
 *
 *  Solo un error de SESIÓN se arregla reconectando; una caída de Graph (5xx, 429) o del
 *  backend se pasa sola, y pintarla como «Conectar Outlook» mandaba a rehacer el
 *  consentimiento de Microsoft sin necesidad. El backend marca los de sesión con
 *  `reconectar`. Un backend anterior a ese campo no lo manda: mientras no se despliegue,
 *  se reconoce por su texto, que es lo único que había. */
export function leerCalendario(data) {
  if (!data || typeof data !== "object") {
    return { eventos: null, reconectar: false, error: "Respuesta inesperada del calendario" };
  }
  if (data.error) {
    const reconectar = data.reconectar ?? /caducada|no autenticado/i.test(String(data.error));
    return { eventos: null, reconectar: !!reconectar, error: reconectar ? "" : String(data.error) };
  }
  return { eventos: Array.isArray(data.events) ? data.events : [], reconectar: false, error: "" };
}

/** Si una respuesta de borrado dice de verdad que ha borrado. Los endpoints de borrado
 *  (`DELETE /ideas/{id}`, `DELETE /training/sessions/{id}`) respondían 200 con
 *  `{ok: false}` cuando fallaba Supabase: mirar solo `r.ok` daba por borrado lo que
 *  seguía en la base de datos y volvía a salir al recargar. Hoy los dos dan 502, y
 *  mirar también `ok` sigue cubriendo a un backend anterior. */
export function borradoConfirmado(status, cuerpo) {
  return status >= 200 && status < 300 && cuerpo?.ok !== false;
}
