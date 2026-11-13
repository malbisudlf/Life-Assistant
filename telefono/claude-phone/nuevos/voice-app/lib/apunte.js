/**
 * Parche 47: «Jarvis, apunta eso». Ver telefono/PARCHES.md en Life Assistant.
 *
 * En la escucha pasiva, lo que se dice sin nombrarle no sale de la voice-app. Pero a
 * veces lo que querías era justo eso: has dicho algo en voz alta, o te lo han dicho, y
 * dos segundos después quieres que conste. La escucha guarda EN MEMORIA lo transcrito
 * en los últimos ESCUCHA_PASIVA_MEMORIA_S (90 s) —nunca en el registro ni en disco, y se
 * va con la llamada— y «Jarvis, apunta eso» lo manda al backend, que lo guarda como una
 * idea. Lo que no se pide apuntar se olvida solo.
 *
 * No pasa por Claude, a propósito: lo que hay en esa memoria lo ha podido decir la radio
 * o quien vaya al lado, y el Claude del teléfono tiene shell. Va de la voice-app al
 * backend (`POST /telefono/apunte`) y de vuelta solo llega un sí o un no.
 *
 * El criterio es de frase ENTERA, como en reflejos.js: «apunta eso» es la orden, y
 * «apunta que mañana tengo dentista» es una nota que ya sabe tomar Claude.
 */
'use strict';

const QUITAR = /[¡!¿?.,;:«»"']/g;
const DELANTE = /^(?:(?:oye|vale|venga|eh|jarvis|por favor|porfa|y)\b ?)+/;
const DETRAS = /(?: (?:por favor|porfa|jarvis|senor|anda|gracias))+$/;
const ORDEN = new RegExp(
  '^(?:apunta(?:me|lo)?|anota(?:me|lo)?|guarda(?:me|lo)?|toma nota de|quedate con|recuerda)' +
  '(?: (?:eso|esto|eso ultimo|lo ultimo|lo de antes|lo anterior|' +
  'lo que (?:he|hemos|ha|han|acabo de|acabamos de|acaba de|acaban de|se ha|estaba|estabamos|estaban) ?' +
  '(?:dicho|decir|diciendo|hablado|hablar|hablando|comentado|comentar|comentando)?|' +
  'lo ultimo que (?:he|hemos|ha|han|se ha) dicho))?$');

function normalizar(texto) {
  return String(texto || '').toLowerCase().normalize('NFD').replace(/[̀-ͯ]/g, '')
    .replace(QUITAR, ' ').replace(/\s+/g, ' ').trim()
    .replace(DELANTE, '').replace(DETRAS, '').trim();
}

/** ¿Es la orden de apuntar lo que se acaba de decir? */
function pideApuntar(texto) {
  const t = normalizar(texto);
  // «apunta», «guarda» a secas no: demasiado fácil de decir sin querer.
  return ORDEN.test(t) && / /.test(t) || /^(?:apuntalo|anotalo|apuntamelo|anotamelo)$/.test(t);
}

const FRASES = {
  hecho:  'Apuntado, señor.',
  nada:   'No he oído nada que apuntar, señor.',
  fallo:  'No he podido apuntarlo, señor.'
};

function urlBase() {
  return String(process.env.LECTURA_URL || 'http://127.0.0.1:8080').replace(/\/+$/, '');
}

async function mandar(texto, fetchImpl) {
  const r = await (fetchImpl || fetch)(urlBase() + '/telefono/apunte', {
    method: 'POST',
    headers: { Authorization: 'Bearer ' + (process.env.LECTURA_TOKEN || ''), 'Content-Type': 'application/json' },
    body: JSON.stringify({ texto: texto }),
    signal: AbortSignal.timeout(8000)
  });
  if (!r.ok) throw new Error('HTTP ' + r.status);
  const d = await r.json();
  if (!d || !d.ok) throw new Error('el backend no lo ha guardado');
}

/**
 * Si la frase es «apunta eso», lo hace y lo dice. Devuelve true si era eso.
 * @param {string} transcript
 * @param {Object} c
 * @param {Object} c.pasiva      - EscuchaPasiva (su memoria)
 * @param {Object} c.endpoint
 * @param {Object} c.ttsService
 * @param {string} [c.voiceId]
 * @param {Function} [c.log]
 * @param {Function} [c.sigueActiva]
 * @param {Function} [c.fetch]   - para los tests
 */
async function atender(transcript, c) {
  if (!c.pasiva || !c.pasiva.activa || !pideApuntar(transcript)) return false;
  const log = c.log || function () {};
  const dicho = c.pasiva.loReciente();
  let frase = FRASES.nada;
  if (dicho) {
    try {
      await mandar(dicho, c.fetch);
      frase = FRASES.hecho;
      // Ni el texto ni su principio: solo cuánto.
      log('APUNTE: guardado (' + dicho.length + ' caracteres)');
    } catch (e) {
      frase = FRASES.fallo;
      log('APUNTE: falló (' + e.message + ')');
    }
  } else {
    log('APUNTE: nada en la memoria');
  }
  if (!c.sigueActiva || c.sigueActiva()) {
    await c.endpoint.play(await c.ttsService.generateSpeech(frase, c.voiceId));
  }
  return true;
}

module.exports = { atender, pideApuntar, normalizar, FRASES };
