/**
 * Parche 20: confirmar de viva voz lo que Jarvis propone por teléfono. Ver
 * telefono/PARCHES.md y «El sí dicho por teléfono» en docs/JARVIS.md, en Life Assistant.
 *
 * Lo que se confirma (crear una cita, una tarea…) llega al móvil con un botón «Sí,
 * hazlo», y en el coche no se puede pulsar. Ahora Claude pone en su respuesta
 *
 *   ✅ CONFIRMAR: <id>
 *
 * y la llamada hace el resto, SIN Claude:
 *   1. Pide al backend la frase de lo que se hará (GET /telefono/confirmar/<id>), que la
 *      escribió el backend a partir de lo guardado, no el modelo, y la lee: «Crear
 *      Dentista mañana de 10 a 11. ¿Lo hago? Di sí o no.»
 *   2. Lo siguiente que digas lo decide `siONo`, con una lista cerrada: la frase ENTERA
 *      tiene que ser un sí («sí», «vale», «hazlo») o un no. «Sí, pero a las 11» no es
 *      ninguna de las dos y va a Claude como siempre, con la propuesta todavía pendiente.
 *   3. Con un sí o un no, se lo dice al backend (POST, con TELEFONO_CONFIRMAR_TOKEN, que
 *      no tiene Claude) y lee lo que contesta: «Hecho. Creado Dentista mañana.»
 *
 * El backend vuelve a comprobarlo todo: solo lo que se deshace fácil, recién propuesto
 * y sin contestar. Si ya lo pulsaste en el móvil, el «sí» hablado no hace nada más.
 *
 * Parche 35: «Sí, créalo, anda, venga» también es un sí. Vale la frase hecha SOLO de
 * palabras de sí y de relleno (ver siONo); «Sí, pero a las 11» sigue yendo a Claude. Y si
 * suena a sí con alguna palabra mal oída («Sí, sí, audio, venga»), se pregunta otra vez.
 *
 * Variables: LECTURA_URL (el backend, como la lectura), CONFIRMAR_TOKEN y
 * CONFIRMAR_ESPERA_MS.
 */
'use strict';

const { decirInterrumpible } = require('./turno-rapido');

const MARCA = /✅\s*CONFIRMAR:\s*([0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})/i;

// Las mismas listas que el modo llamada del dashboard (esConfirmacionHablada, en
// src/lib/helpers.js de Life Assistant). Órdenes, no opiniones: «perfecto» o «eso es»
// se dicen al oír una propuesta sin haber decidido nada todavía.
const SI = new Set([
  'si', 'si si', 'si claro', 'si vale', 'si adelante', 'si hazlo', 'si dale',
  'vale', 'venga', 'venga va', 'va', 'dale', 'adelante', 'hazlo', 'hazlo ya',
  'confirmo', 'confirmado', 'ok', 'okey', 'oka', 'de acuerdo', 'procede', 'tira'
]);
const NO = new Set([
  'no', 'no no', 'no gracias', 'dejalo', 'dejalo estar', 'deja', 'cancela',
  'cancelalo', 'olvidalo', 'mejor no', 'no lo hagas', 'no hagas nada', 'para',
  'quita', 'anula'
]);

// Parche 35: palabra a palabra. Las de sí y las de no deciden; el relleno, solo, no dice nada
// («perfecto» o «anda» sueltos siguen sin ser un sí), y mezclar sí y no es «no lo sé».
const PALABRAS_SI = new Set([
  'si', 'sip', 'vale', 'venga', 'va', 'dale', 'adelante', 'claro', 'hazlo', 'confirmo',
  'confirmado', 'ok', 'okey', 'oka', 'procede', 'tira', 'mandalo', 'mandaselo', 'envialo',
  'enviaselo', 'crealo', 'apuntalo', 'ponlo', 'pidelo', 'reservalo', 'programalo', 'guardalo'
]);
const PALABRAS_NO = new Set([
  'no', 'dejalo', 'cancela', 'cancelalo', 'olvidalo', 'anula', 'anulalo', 'quita', 'para'
]);
const RELLENO = new Set([
  'anda', 'ando', 'tio', 'tia', 'hombre', 'joder', 'hostia', 'ostia', 'cono', 'ya', 'pues',
  'eh', 'ah', 'oye', 'mira', 'bueno', 'perfecto', 'que', 'senor', 'ahora', 'mismo'
]);
// Lo que convierte un sí en otra cosa: esto nunca se vuelve a preguntar, va a Claude.
const MATIZA = new Set(['pero', 'mejor', 'espera', 'cambia', 'aunque', 'antes', 'despues', 'nunca', 'nada']);

// Lo que se espera un sí o un no. Los 8 s de seguir hablando en el modo coche se acababan
// con la respuesta a medias y se dormía sin oírla (2026-11-05).
const ESPERA_RESPUESTA_MS = 20000;

function normalizar(texto) {
  return String(texto || '')
    .toLowerCase()
    .normalize('NFD').replace(/\p{Diacritic}/gu, '')
    .replace(/[.,;:!?¡¿"«»]/g, ' ')
    .replace(/\b(por favor|porfa|porfi|gracias|jarvis)\b/g, ' ')
    .replace(/\s+/g, ' ')
    .trim();
}

/** 'si', 'no' o null. Null es «no lo sé», y entonces no se confirma nada. */
function siONo(texto) {
  const t = normalizar(texto);
  if (NO.has(t)) return 'no';
  if (SI.has(t)) return 'si';
  const palabras = t ? t.split(' ') : [];
  const conocida = function (p) { return PALABRAS_SI.has(p) || PALABRAS_NO.has(p) || RELLENO.has(p); };
  if (!palabras.every(conocida)) return null;
  const si = palabras.some(function (p) { return PALABRAS_SI.has(p); });
  const no = palabras.some(function (p) { return PALABRAS_NO.has(p); });
  if (si === no) return null;
  return si ? 'si' : 'no';
}

/** Casi todo es un sí y nada lo matiza: una palabra mal oída, no otra idea. */
function pareceSi(texto) {
  const palabras = normalizar(texto).split(' ').filter(Boolean);
  if (!palabras.some(function (p) { return PALABRAS_SI.has(p); })) return false;
  if (palabras.some(function (p) { return PALABRAS_NO.has(p) || MATIZA.has(p); })) return false;
  const buenas = palabras.filter(function (p) { return PALABRAS_SI.has(p) || RELLENO.has(p); }).length;
  return buenas / palabras.length >= 0.6;
}

/**
 * El tiempo que espera el turno. Con una pregunta en el aire, el oído admite un «sí» suelto
 * y espera a que conteste, también en el modo coche.
 */
function turnoDeRespuesta(session, pendiente, normalMs) {
  if (!pendiente) return normalMs;
  if (typeof session.esperarRespuestaCorta === 'function') session.esperarRespuestaCorta();
  return parseInt(process.env.CONFIRMAR_ESPERA_MS || String(ESPERA_RESPUESTA_MS), 10);
}

/** El id que trae la respuesta de Claude, o null. */
function pedidoDeConfirmacion(respuesta) {
  const m = String(respuesta || '').match(MARCA);
  return m ? m[1].toLowerCase() : null;
}

function base() {
  return (process.env.LECTURA_URL || 'http://127.0.0.1:8080').replace(/\/+$/, '');
}

function cabeceras() {
  return { Authorization: 'Bearer ' + (process.env.CONFIRMAR_TOKEN || ''),
           'Content-Type': 'application/json' };
}

async function decir(c, texto) {
  const url = await c.ttsService.generateSpeech(texto, c.voiceId);
  return decirInterrumpible(c.endpoint, c.session, url, c.log || function () {});
}

/**
 * Si la respuesta trae `✅ CONFIRMAR`, lee lo que se hará y pregunta. Devuelve
 * { pendiente, interrumpio }: `pendiente` es lo que espera respuesta ({ id, frase }) o
 * null si no hay nada que preguntar (sin marca, o el backend dice que esto va con
 * botón: entonces Claude ya ha dicho que le ha llegado al móvil, y no se añade nada).
 */
async function preguntarSiLoPide(respuesta, c) {
  const id = pedidoDeConfirmacion(respuesta);
  if (!id) return { pendiente: null, interrumpio: false };
  const log = c.log || function () {};
  if (!process.env.CONFIRMAR_TOKEN) {
    log('CONFIRMAR: sin CONFIRMAR_TOKEN, se queda en el botón del móvil');
    return { pendiente: null, interrumpio: false };
  }
  let datos;
  try {
    const r = await (c.fetchImpl || fetch)(base() + '/telefono/confirmar/' + id, {
      headers: cabeceras(), signal: AbortSignal.timeout(10000)
    });
    datos = r.ok ? await r.json() : { ok: false, motivo: 'HTTP ' + r.status };
  } catch (e) {
    datos = { ok: false, motivo: e.message };
  }
  if (!datos || !datos.ok) {
    log('CONFIRMAR: ' + id + ' va con botón (' + ((datos && datos.motivo) || '?') + ')');
    return { pendiente: null, interrumpio: false };
  }
  if (c.sigueActiva && !c.sigueActiva()) return { pendiente: null, interrumpio: false };
  log('CONFIRMAR: pregunto ' + id);
  const interrumpio = await decir(c, datos.frase + ' ¿Lo hago? Di sí o no.');
  return { pendiente: { id: id, frase: datos.frase }, interrumpio: interrumpio };
}

/**
 * Lo que has dicho después de la pregunta. Devuelve { resuelta, interrumpio, aviso }:
 * con un sí o un no, `resuelta` (ya está dicho y hecho, no hace falta Claude para este
 * turno); si no, lo dicho sigue su camino a Claude con `aviso` delante.
 */
async function resolverConfirmacion(pendiente, transcript, c) {
  const log = c.log || function () {};
  const respuesta = siONo(transcript);
  if (!respuesta && !pendiente.repetida && pareceSi(transcript)) {
    log('CONFIRMAR: ' + pendiente.id + ' suena a sí pero no está claro, lo pregunto otra vez');
    const cortada = await decir(c, 'Perdone, señor, no le he oído bien. ¿Lo hago? Diga sí o no.');
    return { resuelta: true, interrumpio: cortada, aviso: '',
             pendiente: { id: pendiente.id, frase: pendiente.frase, repetida: true } };
  }
  if (!respuesta) {
    log('CONFIRMAR: ' + pendiente.id + ' sin un sí o un no claro, sigue pendiente');
    return { resuelta: false, interrumpio: false,
             aviso: '[Le has preguntado de viva voz si hacías «' + pendiente.frase + '» y no ha ' +
                    'contestado sí o no: sigue pendiente en el móvil, no lo des por hecho. Un sí hablado ' +
                    'sí vale: si quiere hacerlo, pon otra vez la línea ✅ CONFIRMAR: ' + pendiente.id +
                    ' y la llamada se lo volverá a preguntar. No le mandes al botón.] ' };
  }
  let datos;
  try {
    const r = await (c.fetchImpl || fetch)(base() + '/telefono/confirmar/' + pendiente.id, {
      method: 'POST', headers: cabeceras(), body: JSON.stringify({ respuesta: respuesta }),
      signal: AbortSignal.timeout(20000)
    });
    datos = r.ok ? await r.json() : { ok: false, frase: 'No he podido confirmarlo. Tienes el botón en el móvil.' };
  } catch (e) {
    datos = { ok: false, frase: 'No he podido confirmarlo. Tienes el botón en el móvil.' };
  }
  const frase = (datos && datos.frase) || 'No he podido confirmarlo. Tienes el botón en el móvil.';
  log('CONFIRMAR: ' + pendiente.id + ' → ' + respuesta + ' → ' + frase);
  const interrumpio = await decir(c, frase);
  return { resuelta: true, interrumpio: interrumpio,
           aviso: '[Has preguntado de viva voz por «' + pendiente.frase + '» y ha contestado «' +
                  (respuesta === 'si' ? 'sí' : 'no') + '». Resultado, ya dicho en voz alta: «' +
                  frase + '». No lo repitas.] ' };
}

module.exports = { preguntarSiLoPide, resolverConfirmacion, siONo, pareceSi, turnoDeRespuesta,
                   pedidoDeConfirmacion };
