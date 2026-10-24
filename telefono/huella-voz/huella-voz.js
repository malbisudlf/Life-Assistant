/**
 * Parche 23: la huella de voz. Ver telefono/PARCHES.md y telefono/huella-voz/ en Life
 * Assistant.
 *
 * BORRADOR EN ESPERA (2026-10-24): va a `voice-app/lib/huella-voz.js` de claude-phone,
 * pero no está enganchado ni probado. Se paró porque la huella se muda a «jacobo» junto
 * al Whisper local (ver «El parche 23, en espera» en telefono/PARCHES.md).
 *
 * En el modo coche (parche 22) cualquiera que diga «Jarvis» le despierta: un pasajero, o
 * la radio. Ahora, cuando la frase trae el nombre y ANTES de despertar, se pregunta al
 * servicio de la huella (un contenedor aparte, en 127.0.0.1) si esa voz es la de Mikel.
 * Si no lo es, sigue dormido y en el registro queda solo que se rechazó y cuánto se
 * parecía, nunca lo que se dijo. Y como la frase rechazada ya no se transcribe entera,
 * lo que dice un pasajero tampoco sale a Whisper más allá de sus primeros 4 s.
 *
 * - HUELLA_VOZ_URL: el servicio. Sin ella, todo como en el parche 22.
 * - HUELLA_VOZ_MODO: `filtrar` (por defecto) o `medir`, que pregunta y lo apunta pero
 *   despierta siempre. Es para fijar el umbral con llamadas de verdad desde el coche.
 * - HUELLA_VOZ_SI_FALLA: qué hacer si el servicio no contesta, no tiene huella o el
 *   audio es demasiado corto: `despertar` (por defecto, para no dejarle sin Jarvis) o
 *   `dormir`.
 * - HUELLA_VOZ_TIMEOUT_MS (2000) y HUELLA_VOZ_TOKEN (solo si el servicio vive fuera de
 *   esta máquina; ver HUELLA_TOKEN en servidor.py).
 *
 * El alta, hablando: «Jarvis, aprende mi voz» en cualquier llamada. Jarvis le pide que
 * repita unas frases (~30 s de voz en total) y manda el audio, tal cual llega por la
 * línea, a POST /alta. Se graba por teléfono a propósito: el canal G.711 cambia la
 * huella más que el ruido del coche.
 */
'use strict';

function entero(nombre, porDefecto) {
  const n = parseInt(process.env[nombre], 10);
  return Number.isFinite(n) && n > 0 ? n : porDefecto;
}

function config() {
  return {
    url: (process.env.HUELLA_VOZ_URL || '').replace(/\/+$/, ''),
    medir: process.env.HUELLA_VOZ_MODO === 'medir',
    siFallaDuerme: process.env.HUELLA_VOZ_SI_FALLA === 'dormir',
    timeoutMs: entero('HUELLA_VOZ_TIMEOUT_MS', 2000),
    token: process.env.HUELLA_VOZ_TOKEN || ''
  };
}

function cabeceras(cfg, extra) {
  const h = Object.assign({ 'Content-Type': 'application/octet-stream' }, extra || {});
  if (cfg.token) h['X-Auth-Token'] = cfg.token;
  return h;
}

function fx(n) {
  return typeof n === 'number' ? n.toFixed(2) : '?';
}

/**
 * ¿Despierta? Devuelve { despertar, motivo, similitud }. `motivo`: `apagada` (sin
 * servicio configurado), `su_voz`, `otra_voz`, `medir` (no parecía él, pero se mide) o
 * `fallo`. Lo apunta en `log` sin el texto, que aquí ni llega.
 *
 * @param {Buffer} audio - la frase entera, PCM 16 kHz
 * @param {Object} [o] - { log, fetchImpl }
 */
async function comprobarVoz(audio, o) {
  const op = o || {};
  const log = op.log || function () {};
  const cfg = config();
  if (!cfg.url) return { despertar: true, motivo: 'apagada' };
  let r;
  let datos;
  try {
    r = await (op.fetchImpl || fetch)(cfg.url + '/verificar', {
      method: 'POST', headers: cabeceras(cfg), body: audio,
      signal: AbortSignal.timeout(cfg.timeoutMs)
    });
    datos = await r.json().catch(function () { return {}; });
  } catch (err) {
    r = null;
    datos = { motivo: err.name === 'TimeoutError' ? 'sin_respuesta' : 'inalcanzable' };
  }
  if (!r || !r.ok || typeof datos.es_el !== 'boolean') {
    const despertar = !cfg.siFallaDuerme;
    log('ESCUCHA-PASIVA: la huella no contesta (' + (datos.motivo || (r && r.status)) + '), ' +
      (despertar ? 'despierto' : 'sigo dormido'));
    return { despertar: despertar, motivo: 'fallo' };
  }
  const s = fx(datos.similitud) + ' / umbral ' + fx(datos.umbral);
  if (datos.es_el) {
    log('ESCUCHA-PASIVA: es su voz (' + s + ')');
    return { despertar: true, motivo: 'su_voz', similitud: datos.similitud };
  }
  if (cfg.medir) {
    log('ESCUCHA-PASIVA: no parece su voz (' + s + '), despierto igual: modo medir');
    return { despertar: true, motivo: 'medir', similitud: datos.similitud };
  }
  log('ESCUCHA-PASIVA: me nombran, pero no es su voz (' + s + '): sigo dormido');
  return { despertar: false, motivo: 'otra_voz', similitud: datos.similitud };
}

// ── El alta ──────────────────────────────────────────────────────────────────

// Empiezan por «Jarvis» porque así empiezan las frases que luego se comprueban.
const FRASES_ALTA = [
  'Jarvis, ¿qué tengo hoy en la agenda?',
  'Jarvis, ¿a qué hora tengo que salir para llegar a tiempo?',
  'Jarvis, recuérdame comprar pan cuando llegue a casa.',
  'Jarvis, ¿qué tiempo va a hacer mañana por la mañana?',
  'Jarvis, léeme el correo de hoy.',
  'Jarvis, apaga las luces del salón y enciende la calefacción.',
  'Jarvis, pon algo de música tranquila para el viaje.',
  'Jarvis, ¿cuántas tareas me quedan pendientes esta semana?'
];

const FRASES_HUELLA = {
  sinServicio: 'No tengo dónde guardar su voz, señor: el servicio de la huella no está configurado.',
  empezar:     'Voy a aprender su voz, señor. Repita cada frase después de mí, con naturalidad, ' +
               'como si me hablara en el coche.',
  libre:       'Y para terminar, cuénteme en unas frases qué tal le ha ido el día.',
  pocaVoz:     'No le he oído lo suficiente, señor. Lo intentamos en otro momento.',
  fallo:       'No he podido guardar su voz, señor: el servicio de la huella no responde.',
  hecha:       'Hecho, señor. Ya conozco su voz.'
};

function pideAprenderVoz(texto) {
  const t = String(texto || '').toLowerCase()
    .normalize('NFD').replace(/\p{Diacritic}/gu, '')
    .replace(/[.,;:!?¡¿"«»]/g, ' ')
    .replace(/\b(jarvis|por favor|venga|oye)\b/g, ' ')
    .replace(/\s+/g, ' ').trim();
  return /^(aprende|aprendete|graba|memoriza|registra|guarda)( a reconocer)? (mi (huella de )?voz|mi huella)$/.test(t);
}

/**
 * La conversación del alta. Devuelve { hecha, motivo, ...lo que contestó el servicio }.
 *
 * @param {Object} c - { endpoint, session, ttsService, voiceId, log, sigueActiva, fetchImpl }
 */
async function aprenderVoz(c) {
  const log = c.log || function () {};
  const sigue = c.sigueActiva || function () { return true; };
  const cfg = config();
  const objetivoMs = entero('HUELLA_VOZ_ALTA_SEGUNDOS', 30) * 1000;
  const decir = async function (texto) {
    if (sigue()) await c.endpoint.play(await c.ttsService.generateSpeech(texto, c.voiceId));
  };
  if (!cfg.url) {
    await decir(FRASES_HUELLA.sinServicio);
    return { hecha: false, motivo: 'sin_servicio' };
  }
  log('HUELLA: alta de voz');
  await decir(FRASES_HUELLA.empezar);
  const frases = [];
  let ms = 0;
  let sinOir = 0;
  const pedidos = FRASES_ALTA.concat([FRASES_HUELLA.libre]);
  for (let i = 0; i < pedidos.length && ms < objetivoMs; i++) {
    if (!sigue()) return { hecha: false, motivo: 'colgada' };
    const libre = i === pedidos.length - 1;
    await decir(pedidos[i]);
    c.session.setCaptureEnabled(true);
    let u = null;
    try {
      u = await c.session.waitForUtterance({ timeoutMs: libre ? 30000 : 10000 });
    } catch (err) {
      if (/closed/i.test(err.message || '')) return { hecha: false, motivo: 'colgada' };
    }
    c.session.setCaptureEnabled(false);
    if (!u) {
      if (++sinOir >= 2) break;
      continue;
    }
    sinOir = 0;
    frases.push(u.audio);
    ms += u.audio.length / 32;                    // 16 kHz, 16 bits: 32 bytes por ms
  }
  if (!sigue()) return { hecha: false, motivo: 'colgada' };
  log('HUELLA: ' + frases.length + ' frases, ' + (ms / 1000).toFixed(1) + ' s; las mando');
  let r;
  let datos;
  try {
    r = await (c.fetchImpl || fetch)(cfg.url + '/alta', {
      method: 'POST',
      headers: cabeceras(cfg, { 'X-Frases': frases.map(function (f) { return f.length; }).join(',') }),
      body: Buffer.concat(frases),
      signal: AbortSignal.timeout(60000)          // ~10 frases por el modelo: unos segundos
    });
    datos = await r.json().catch(function () { return {}; });
  } catch (err) {
    log('HUELLA: el servicio no contesta (' + err.message + ')');
    await decir(FRASES_HUELLA.fallo);
    return { hecha: false, motivo: 'fallo' };
  }
  if (r.ok && datos.ok) {
    log('HUELLA: guardada (' + datos.frases + ' frases, ' + datos.segundos + ' s, ' +
      datos.descartadas + ' descartadas, consistencia ' + datos.consistencia + ')');
    await decir(FRASES_HUELLA.hecha);
    return Object.assign({ hecha: true }, datos);
  }
  log('HUELLA: no guardada (' + (datos.motivo || r.status) + ')');
  await decir(datos.motivo === 'poca_voz' || !frases.length ? FRASES_HUELLA.pocaVoz : FRASES_HUELLA.fallo);
  return Object.assign({ hecha: false }, datos, { motivo: datos.motivo || 'fallo' });
}

module.exports = { comprobarVoz, aprenderVoz, pideAprenderVoz, FRASES_ALTA, FRASES_HUELLA };
