// Lógica pura de los lugares en el dashboard: casa, gimnasio y uni.
//
// El backend sabe dónde estás (la zona que manda Home Assistant, ya traducida a uno de
// estos tres sitios en `GET /presencia` → `lugar`). Aquí solo se decide qué hace el
// dashboard con eso: cómo se llama cada sitio y qué widgets suben en el modo simple.
//
// Solo el modo simple se reordena. El completo es una distribución hecha a mano, con
// arrastrar y soltar: moverla sola según dónde estés pelearía con quien la editó, y en
// el escritorio de casa no hace falta.

export const NOMBRES_LUGAR = {
  casa:     "En casa",
  gimnasio: "En el gimnasio",
  uni:      "En la uni",
};

// Qué sube y qué baja en cada sitio. `arriba` va en ese orden, justo detrás de Jarvis (que
// se queda el primero: es la entrada a todo lo demás). `abajo`, al final. Lo que no se
// nombra conserva su orden.
const ORDEN_POR_LUGAR = {
  uni: {
    arriba: ["siguiente", "timeline", "entregas", "upcoming"],
    abajo:  ["casa", "acciones_pc", "clothing", "finanzas"],
  },
  gimnasio: {
    arriba: ["training", "health_workouts", "siguiente"],
    abajo:  ["casa", "acciones_pc", "entregas", "finanzas"],
  },
};

const PRIMERO_SIEMPRE = "jarvis";

/** El lugar con nombre de una respuesta de `/presencia`, o null si no se sabe.
 *  Caducada no cuenta: «hace seis horas en la uni» no es estar en la uni. */
export function lugarDePresencia(p) {
  if (!p || !p.conocida || !p.vigente) return null;
  return Object.prototype.hasOwnProperty.call(NOMBRES_LUGAR, p.lugar) ? p.lugar : null;
}

/** Si en ese lugar el modo simple cambia de orden. */
export function reordenaEn(lugar) {
  return Object.prototype.hasOwnProperty.call(ORDEN_POR_LUGAR, lugar);
}

/** Los ids en el orden que toca en `lugar`. Estable: lo que no se nombra no se mueve
 *  entre sí, y sin lugar (o en casa) se devuelve tal cual. */
export function ordenarPorLugar(ids, lugar) {
  const reglas = ORDEN_POR_LUGAR[lugar];
  if (!reglas) return [...ids];
  const presentes = new Set(ids);
  const arriba = reglas.arriba.filter(id => presentes.has(id) && id !== PRIMERO_SIEMPRE);
  const abajo  = reglas.abajo.filter(id => presentes.has(id) && id !== PRIMERO_SIEMPRE);
  const movidos = new Set([...arriba, ...abajo]);
  const resto = ids.filter(id => id !== PRIMERO_SIEMPRE && !movidos.has(id));
  const cabeza = presentes.has(PRIMERO_SIEMPRE) ? [PRIMERO_SIEMPRE] : [];
  return [...cabeza, ...arriba, ...resto, ...abajo];
}

/** La etiqueta de un tramo del carril de presencia. */
export function etiquetaTramo(t) {
  if (t?.en_casa) return "En casa";
  if (t?.lugar === "gimnasio") return "Gimnasio";
  if (t?.lugar === "uni") return "Uni";
  return "Fuera";
}

/** La nota del carril para el día en curso: «ahora en el gimnasio», «ahora fuera»… */
export function notaPresenciaAhora(p) {
  if (!p?.conocida) return "";
  const lugar = lugarDePresencia(p);
  if (lugar) return `ahora ${NOMBRES_LUGAR[lugar].toLowerCase()}`;
  return p.en_casa ? "ahora en casa" : "ahora fuera";
}
