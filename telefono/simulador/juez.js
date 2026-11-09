/**
 * El juez del simulador: qué tenía que pasar en una llamada y si pasó. Ver
 * docs/SIMULADOR.md.
 *
 * Todo lo que se comprueba aquí se comprueba sin modelo: qué herramienta se usó, qué se
 * propuso, si el sí llegó, cuántas palabras dijo y cuánto tardó. No gasta nada y no opina,
 * que es lo que hace que un rojo signifique algo.
 *
 * La traza que juzga:
 *   { turnos: [{ dicho, oido, voz: [frases de Claude], llamada: [frases de la llamada],
 *                propuso: bool, segundos }],
 *     herramientas: [{ nombre, args }], propuestas: [{ herramienta, args, respuesta }] }
 */
'use strict';

// Lo que no se le pide a ningún caso porque vale para todos (telefono/RUNBOOK.md).
const MAX_PALABRAS = 40;          // «Menos de 40 palabras por turno»
const MAX_PALABRAS_AL_PROPONER = 4;  // parche 44: al proponer, solo «De acuerdo.»

function palabras(texto) {
  return String(texto || '').split(/\s+/).filter(Boolean).length;
}

function casa(patron, texto) {
  return new RegExp(patron, 'i').test(String(texto || ''));
}

function evaluar(caso, traza) {
  const espera = caso.espera || {};
  const fallos = [];
  const usadas = (traza.herramientas || []).map(function (h) { return h.nombre; });
  const todoLoDicho = (traza.turnos || []).map(function (t) {
    return (t.voz || []).concat(t.llamada || []).join(' ');
  }).join(' ');

  (espera.herramientas || []).forEach(function (h) {
    if (usadas.indexOf(h) < 0) fallos.push('no usó `' + h + '` (usó: ' + (usadas.join(', ') || 'ninguna') + ')');
  });
  (espera.sin_herramientas || []).forEach(function (h) {
    if (usadas.indexOf(h) >= 0) fallos.push('usó `' + h + '`, y no tenía que usarla');
  });
  Object.keys(espera.argumentos || {}).forEach(function (h) {
    const pedidos = espera.argumentos[h];
    const alguna = (traza.herramientas || []).some(function (u) {
      return u.nombre === h && Object.keys(pedidos).every(function (k) {
        return casa(pedidos[k], (u.args || {})[k]);
      });
    });
    if (!alguna) fallos.push('ninguna llamada a `' + h + '` lleva ' + JSON.stringify(pedidos));
  });

  if (espera.propone) {
    const hay = (traza.propuestas || []).some(function (p) { return p.herramienta === espera.propone; });
    if (!hay) fallos.push('no propuso `' + espera.propone + '` para que se confirme');
  }
  if (espera.confirmado !== undefined) {
    const sies = (traza.propuestas || []).filter(function (p) { return p.respuesta === 'si'; }).length;
    if (espera.confirmado && !sies) fallos.push('el sí no llegó a confirmarse');
    if (!espera.confirmado && sies) fallos.push('se confirmó algo que no tenía que confirmarse');
  }

  (espera.dice || []).forEach(function (p) {
    if (!casa(p, todoLoDicho)) fallos.push('no dijo nada que case con /' + p + '/');
  });
  (espera.no_dice || []).forEach(function (p) {
    if (casa(p, todoLoDicho)) fallos.push('dijo algo que casa con /' + p + '/');
  });

  const tope = espera.max_palabras || MAX_PALABRAS;
  (traza.turnos || []).forEach(function (t, i) {
    const n = palabras((t.voz || []).join(' '));
    if (n > tope) fallos.push('turno ' + (i + 1) + ': ' + n + ' palabras (tope ' + tope + ')');
    if (t.propuso && espera.pregunta_larga !== true && n > MAX_PALABRAS_AL_PROPONER) {
      fallos.push('turno ' + (i + 1) + ': al proponer dijo ' + n + ' palabras («' +
                  (t.voz || []).join(' ').slice(0, 80) + '»); tenía que ser solo «De acuerdo.»');
    }
    if (espera.max_segundos && t.segundos > espera.max_segundos) {
      fallos.push('turno ' + (i + 1) + ': ' + t.segundos.toFixed(1) + ' s (tope ' + espera.max_segundos + ')');
    }
    if (t.error) fallos.push('turno ' + (i + 1) + ': ' + t.error);
  });

  return { ok: fallos.length === 0, fallos: fallos };
}

/** Los nombres de herramienta de un caso que el catálogo no tiene: un caso mal escrito. */
function herramientasQueNoExisten(caso, catalogo) {
  if (!catalogo || !catalogo.length) return [];
  const hay = new Set(catalogo.map(function (h) { return h.name; }));
  const e = caso.espera || {};
  const nombradas = [].concat(e.herramientas || [], e.sin_herramientas || [], Object.keys(e.argumentos || {}),
                              e.propone ? [e.propone] : [], Object.keys(caso.mundo || {}));
  return Array.from(new Set(nombradas)).filter(function (n) { return !hay.has(n); });
}

module.exports = { evaluar, herramientasQueNoExisten, palabras, MAX_PALABRAS, MAX_PALABRAS_AL_PROPONER };
