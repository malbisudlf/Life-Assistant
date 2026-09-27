// Cómo se pide y se resume el registro del backend para el semáforo «Registro». Va
// aparte de `dev.js` porque lo usan los dos lados: la zona dev y el panel ⚙ del
// dashboard, que no puede importar `dev.js` de forma estática sin meterlo entero en el
// chunk principal (ver el comentario de los imports de Dashboard.jsx).

// El semáforo «Registro» se pide en dos consultas y no en una. `/logs` cuenta `errores`
// sobre las filas que devuelve, y esas son las `LIMITE_REGISTRO` más recientes, no la
// semana: con cincuenta WARNING encima, un ERROR del martes quedaba fuera, la fila salía
// en ámbar y el panel ⚙ no avisaba justo de lo que esa fila existe para enseñar. Los
// errores se cuentan aparte, solo ERROR y sin la lista de fuentes, que aquí no hace falta.
export const LIMITE_REGISTRO     = 50;
export const RUTA_REGISTRO       = `/logs?dias=7&limite=${LIMITE_REGISTRO}`;
export const RUTA_ERRORES_SEMANA = "/logs?dias=7&nivel=ERROR&limite=500&fuentes=false";

export function juntarRegistro(registro, soloErrores) {
  if (!registro) return null;
  const deLaSemana = soloErrores?.entradas?.length || 0;
  return {
    ...registro,
    // El máximo y no la suma: los ERROR de la muestra también están en la otra consulta,
    // y los CRITICAL (que la segunda no pide) solo pueden estar en la muestra.
    errores:   Math.max(registro.errores || 0, deLaSemana),
    recortado: (registro.entradas?.length || 0) >= LIMITE_REGISTRO,
  };
}
