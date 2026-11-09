/**
 * El oído del simulador: lo que le llega a Jarvis de lo que dijo Mikel, que no es lo
 * mismo. Ver docs/SIMULADOR.md.
 *
 * La llamada simulada va en texto (sin voz ni transcripción: eso cuesta dinero y tiempo, y
 * lo que se prueba aquí es el cerebro). Pero un cerebro que solo ha oído frases limpias no
 * se ha probado: en el coche llegan sin tildes, sin signos, con palabras comidas y con
 * «Jarvis» mal oído. Esto estropea la frase como la estropea el oído de verdad, y siempre
 * igual para el mismo caso (la semilla sale del propio caso): un fallo se puede repetir.
 */
'use strict';

/** Generador con semilla (mulberry32): mismos números para la misma semilla. */
function azar(semilla) {
  let a = semilla >>> 0;
  return function () {
    a = (a + 0x6D2B79F5) >>> 0;
    let t = a;
    t = Math.imul(t ^ (t >>> 15), t | 1);
    t ^= t + Math.imul(t ^ (t >>> 7), t | 61);
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}

function semillaDe(texto) {
  let h = 2166136261;
  const s = String(texto);
  for (let i = 0; i < s.length; i++) { h ^= s.charCodeAt(i); h = Math.imul(h, 16777619); }
  return h >>> 0;
}

// Lo que Whisper oye en el coche, sacado de los fallos que ya están en telefono/PARCHES.md.
const MAL_OIDAS = {
  jarvis: ['yarvis', 'harvis', 'charvis'],
  garaje: ['garage'],
  whatsapp: ['guasap', 'wasap'],
  recuerdame: ['recuerda me'],
  enciende: ['en ciende'],
};
// Las que se caen sin que la frase deje de entenderse.
const SE_CAEN = new Set(['el', 'la', 'los', 'las', 'de', 'que', 'a', 'un', 'una', 'por', 'me']);

function sinTildes(t) {
  return t.normalize('NFD').replace(/\p{Diacritic}/gu, '');
}

/**
 * `nivel`: 'limpio' (tal cual), 'coche' (lo de todos los días) o 'malo' (cobertura mala:
 * además se pierde el final de la frase).
 */
function oir(texto, nivel, semilla) {
  const frase = String(texto || '');
  if (!nivel || nivel === 'limpio') return frase;
  const r = azar(semilla === undefined ? semillaDe(frase) : semilla);
  const pCae = nivel === 'malo' ? 0.3 : 0.15;
  const pMal = nivel === 'malo' ? 0.6 : 0.35;
  let palabras = sinTildes(frase.toLowerCase()).replace(/[.,;:!?¡¿"«»]/g, ' ').split(/\s+/).filter(Boolean);
  palabras = palabras.filter(function (p, i) {
    // La primera y la última no se caen por esta vía: decidirían ellas solas el sentido.
    if (i === 0 || i === palabras.length - 1) return true;
    return !(SE_CAEN.has(p) && r() < pCae);
  }).map(function (p) {
    const otras = MAL_OIDAS[p];
    return (otras && r() < pMal) ? otras[Math.floor(r() * otras.length)] : p;
  });
  if (nivel === 'malo' && palabras.length > 4 && r() < 0.5) palabras = palabras.slice(0, -1);
  return palabras.join(' ');
}

module.exports = { oir, azar, semillaDe };
