/**
 * Dónde rozó una llamada: lo que el repaso nocturno busca en las transcripciones. Ver
 * docs/SIMULADOR.md.
 *
 * Todo aquí es lógica pura y no gasta nada: lee la transcripción que Claude Code deja de
 * cada sesión del teléfono (un JSONL por llamada) y marca los turnos donde Mikel tuvo que
 * repetirse, corregir o cortar, donde Jarvis tardó, se alargó o dijo que no podía, y donde
 * una herramienta falló. Es lo que hasta ahora solo se sabía si él lo contaba al día
 * siguiente («es demasiado redundante, repito todo muchísimo»).
 */
'use strict';

const SEGUNDOS_LENTO = 8;       // un turno con una herramienta ronda los 5 s (parche 34)
const PALABRAS_LARGO = 40;      // telefono/RUNBOOK.md: «menos de 40 palabras por turno»
const PARECIDO_REPITE = 0.6;

const VACIAS = new Set(['el', 'la', 'los', 'las', 'de', 'del', 'que', 'a', 'al', 'un', 'una', 'y', 'o', 'en',
                        'por', 'para', 'me', 'te', 'se', 'lo', 'le', 'jarvis', 'favor', 'porfa']);

function normalizar(texto) {
  return String(texto || '').toLowerCase().normalize('NFD').replace(/\p{Diacritic}/gu, '')
    .replace(/[^a-z0-9ñ\s]/g, ' ').replace(/\s+/g, ' ').trim();
}

function fichas(texto) {
  return normalizar(texto).split(' ').filter(function (p) { return p && !VACIAS.has(p); });
}

/**
 * Cuánto se parecen dos frases, de 0 a 1: las palabras en común sobre las de la más corta.
 * Sobre la más corta y no sobre el total, porque quien repite añade («pon una alarma a las
 * siete» → «que pongas una alarma a las siete de la mañana») y cambia el verbo.
 */
function parecido(a, b) {
  const A = new Set(fichas(a));
  const B = new Set(fichas(b));
  if (A.size < 2 || B.size < 2) return 0;
  let comunes = 0;
  A.forEach(function (p) { if (B.has(p)) comunes++; });
  return comunes < 2 ? 0 : comunes / Math.min(A.size, B.size);
}

function extraerVoz(respuesta) {
  const m = String(respuesta || '').match(/🗣️\s*VOICE_RESPONSE:\s*([^\n]+)/im);
  return (m ? m[1] : String(respuesta || '')).replace(/\*+/g, '').replace(/\s+/g, ' ').trim();
}

/**
 * Lo que Mikel dijo de verdad en un turno, sin lo que el puente y la llamada le ponen
 * delante: `{ dicho, avisos }`, o null si el turno no es suyo (el precalentado, el aviso de
 * una llamada saliente).
 */
function separarPrompt(prompt) {
  const texto = String(prompt || '');
  const ahora = texto.lastIndexOf('[Ahora: ');
  if (ahora < 0) return null;
  let resto = texto.slice(texto.indexOf('] ', ahora) + 2);
  const avisos = [];
  for (;;) {
    const m = resto.match(/^\[([^\]]{1,2000})\]\s*/);
    if (!m) break;
    avisos.push(m[1]);
    resto = resto.slice(m[0].length);
  }
  if (avisos.some(function (a) { return /^SYSTEM CONTEXT/.test(a); })) return null;
  return { dicho: resto.trim(), avisos: avisos };
}

/** De las líneas de un JSONL de Claude Code a los turnos de la llamada. */
function leerSesion(lineas, id) {
  const turnos = [];
  let actual = null;
  (lineas || []).forEach(function (linea) {
    let d;
    try { d = typeof linea === 'string' ? JSON.parse(linea) : linea; } catch { return; }
    if (!d || !d.message) return;
    const contenido = d.message.content;
    const cuando = d.timestamp ? Date.parse(d.timestamp) : NaN;
    if (d.type === 'user' && typeof contenido === 'string') {
      const p = separarPrompt(contenido);
      actual = p ? { cuando: cuando, dicho: p.dicho, avisos: p.avisos, voz: '', herramientas: [], errores: [], fin: cuando } : null;
      if (actual) turnos.push(actual);
      return;
    }
    if (!actual || !Array.isArray(contenido)) return;
    contenido.forEach(function (b) {
      if (d.type === 'assistant' && b.type === 'text' && b.text) actual.voz = extraerVoz(b.text);
      if (d.type === 'assistant' && b.type === 'tool_use') actual.herramientas.push(String(b.name || '').replace(/^mcp__.+?__/, ''));
      if (d.type === 'user' && b.type === 'tool_result') {
        const texto = Array.isArray(b.content) ? b.content.map(function (x) { return x.text || ''; }).join(' ') : String(b.content || '');
        if (b.is_error || /"ok":\s*false|"error":/.test(texto)) actual.errores.push(texto.replace(/\s+/g, ' ').slice(0, 160));
      }
    });
    if (!isNaN(cuando)) actual.fin = cuando;
  });
  turnos.forEach(function (t) {
    t.segundos = (isNaN(t.cuando) || isNaN(t.fin)) ? 0 : Math.max(0, (t.fin - t.cuando) / 1000);
    delete t.fin;
  });
  const primero = turnos.find(function (t) { return !isNaN(t.cuando); });
  return { id: id || '', inicio: primero ? new Date(primero.cuando).toISOString() : '', turnos: turnos };
}

const CORRIGE = /^(no\b|que no\b|te he dicho|te digo que|eso no|asi no|otra vez\b|repito\b|he dicho\b|no te he)/;

/** Los roces de una llamada: [{ tipo, turno, detalle }], con `turno` empezando en 1. */
function fricciones(sesion) {
  const roces = [];
  const turnos = sesion.turnos || [];
  turnos.forEach(function (t, i) {
    const n = i + 1;
    const anterior = turnos[i - 1];
    if (anterior && parecido(t.dicho, anterior.dicho) >= PARECIDO_REPITE) {
      roces.push({ tipo: 'se_repite', turno: n, detalle: 'dijo casi lo mismo que en el turno ' + i });
    } else if (anterior && CORRIGE.test(normalizar(t.dicho)) && !/\?["»”]?\s*$/.test(anterior.voz)) {
      // Si Jarvis acababa de preguntar, un «no» es la respuesta, no una corrección.
      roces.push({ tipo: 'corrige', turno: n, detalle: 'empieza corrigiendo' });
    }
    if (t.avisos.some(function (a) { return /Te ha interrumpido/.test(a); })) {
      roces.push({ tipo: 'le_corta', turno: n, detalle: 'cortó a Jarvis a media frase' });
    }
    if (t.avisos.some(function (a) { return /no ha contestado sí o no|no ha\s+contestado/.test(a); })) {
      roces.push({ tipo: 'si_no_entendido', turno: n, detalle: 'contestó a una confirmación y no se entendió como sí o no' });
    }
    if (t.segundos > SEGUNDOS_LENTO) {
      roces.push({ tipo: 'lento', turno: n, detalle: t.segundos.toFixed(1) + ' s' + (t.herramientas.length ? ' (' + t.herramientas.join(', ') + ')' : '') });
    }
    if (t.errores.length) {
      roces.push({ tipo: 'herramienta_fallo', turno: n, detalle: (t.herramientas.join(', ') || '?') });
    }
    const palabras = t.voz.split(/\s+/).filter(Boolean).length;
    if (palabras > PALABRAS_LARGO) roces.push({ tipo: 'largo', turno: n, detalle: palabras + ' palabras' });
    if (/\bno (puedo|he podido|soy capaz|tengo forma)\b/i.test(t.voz)) {
      roces.push({ tipo: 'no_puede', turno: n, detalle: 'dijo que no podía' });
    }
  });
  return roces;
}

/**
 * La llamada, como caso del simulador: lo que dijo, tal cual se oyó. Sin `espera`: solo se
 * le piden las reglas de siempre (corto, rápido, «De acuerdo.» al proponer) hasta que
 * alguien escriba qué tenía que haber pasado.
 */
function casoDe(sesion, roces) {
  return {
    id: 'real-' + (sesion.inicio || '').slice(0, 10) + '-' + String(sesion.id).slice(0, 8),
    de: sesion.inicio,
    roces: Array.from(new Set((roces || []).map(function (r) { return r.tipo; }))),
    modo: sesion.turnos.some(function (t) { return t.avisos.some(function (a) { return /^Modo coche/.test(a); }); }) ? 'coche' : undefined,
    turnos: sesion.turnos.map(function (t) { return t.dicho; }).filter(Boolean),
    espera: {},
  };
}

const NOMBRES = {
  se_repite: 'tuvo que repetirse', corrige: 'le corrigió', le_corta: 'le cortó', si_no_entendido: 'no se le entendió el sí o el no',
  lento: 'turno lento', herramienta_fallo: 'falló una herramienta', largo: 'respuesta larga', no_puede: 'dijo que no podía',
};

/** «2 veces tuvo que repetirse, 1 turno lento», para el aviso: sin nada de lo hablado. */
function resumen(todos) {
  const cuenta = {};
  (todos || []).forEach(function (r) { cuenta[r.tipo] = (cuenta[r.tipo] || 0) + 1; });
  return Object.keys(cuenta).sort(function (a, b) { return cuenta[b] - cuenta[a]; })
    .map(function (t) { return cuenta[t] + ' × ' + (NOMBRES[t] || t); }).join(', ');
}

module.exports = { leerSesion, separarPrompt, fricciones, casoDe, resumen, parecido, extraerVoz, NOMBRES,
                   SEGUNDOS_LENTO, PALABRAS_LARGO };
