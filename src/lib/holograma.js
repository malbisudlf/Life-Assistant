// Lógica pura de la maqueta de la casa en la vista J.A.R.V.I.S.
// (src/components/jarvis/Holograma.jsx). Las plantas y las habitaciones las da el backend
// (`/hud/datos?fuente=casa`, de Home Assistant); aquí se decide dónde va cada habitación
// en su planta, cómo se gira la maqueta y qué se dice de cada habitación.

/** Píxeles entre una planta y la de encima. */
export const SEPARACION_PISOS = 46;
/** El giro de partida: vista de tres cuartos, desde arriba. */
export const GIRO_INICIAL = { x: 58, z: -32 };
const HUECO = 3;   // entre habitaciones, en unidades del plano (0-100)

/** Dónde va cada habitación de una planta, en un cuadrado de 100×100. Si el backend da su
 *  caja (`CASA_PLANO`), esa; si no, una rejilla lo más cuadrada posible, en el orden de
 *  Home Assistant. Devuelve las habitaciones con `x, y, w, h`. */
export function planoPiso(areas = []) {
  const sinCaja = areas.filter(a => !Array.isArray(a.caja));
  const cols = Math.max(1, Math.ceil(Math.sqrt(sinCaja.length)));
  const filas = Math.max(1, Math.ceil(sinCaja.length / cols));
  const ancho = 100 / cols;
  const alto = 100 / filas;
  let i = 0;
  return areas.map(a => {
    if (Array.isArray(a.caja)) {
      const [x, y, w, h] = a.caja;
      return { ...a, x, y, w: Math.max(4, w), h: Math.max(4, h) };
    }
    const c = i % cols;
    const f = Math.floor(i / cols);
    i += 1;
    return { ...a, x: c * ancho + HUECO / 2, y: f * alto + HUECO / 2, w: ancho - HUECO, h: alto - HUECO };
  });
}

/** El giro tras arrastrar `dx`, `dy` píxeles: horizontal da vueltas, vertical inclina (y
 *  no deja ponerla de canto ni boca abajo). */
export function girar(giro, dx, dy) {
  const x = Math.max(15, Math.min(80, giro.x - dy * 0.3));
  return { x: Math.round(x * 10) / 10, z: Math.round((giro.z + dx * 0.4) * 10) / 10 };
}

/** «1/3 luces · 21,4 °C · alguien», lo que se cuenta de una habitación. */
export function resumenArea(a = {}) {
  if (a.privado) return "Privado";
  const partes = [];
  if (a.luces?.length) partes.push(`${a.luces_on || 0}/${a.luces.length} luces`);
  if (Number.isFinite(a.temp)) partes.push(`${String(a.temp).replace(".", ",")} °C`);
  if (Number.isFinite(a.hum)) partes.push(`${Math.round(a.hum)} %`);
  if (a.presencia) partes.push("alguien");
  if (a.abiertas) partes.push(a.abiertas === 1 ? "algo abierto" : `${a.abiertas} abiertos`);
  if (a.sonando) partes.push("sonando");
  return partes.join(" · ") || "Sin sensores";
}

/** Cómo se pinta: privada, con luz, apagada o sin luces que tocar. */
export function claseArea(a = {}) {
  if (a.privado) return "privado";
  if (!a.luces?.length) return "sin-luces";
  return a.luces_on > 0 ? "encendida" : "apagada";
}

/** Lo que pasa al tocarla: encender si está apagada, apagar si hay alguna encendida. null
 *  si no se puede tocar. */
export function alTocar(a = {}) {
  if (a.privado || !a.luces?.length) return null;
  return { area: a.id, encender: !(a.luces_on > 0) };
}

/** La habitación tras tocarla, antes de que conteste la casa: lo que se ve mientras la
 *  orden viaja (como en el widget «Casa»). */
export function trasTocar(a, encender) {
  const luces = (a.luces || []).map(l => ({ ...l, on: encender }));
  return { ...a, luces, luces_on: encender ? luces.length : 0 };
}

/** Lo de toda la casa: cuántas luces encendidas y en cuántas habitaciones hay alguien. */
export function resumenCasa(pisos = []) {
  const areas = pisos.flatMap(p => p.areas || []).filter(a => !a.privado);
  return {
    luces: areas.reduce((n, a) => n + (a.luces_on || 0), 0),
    gente: areas.filter(a => a.presencia).length,
  };
}
