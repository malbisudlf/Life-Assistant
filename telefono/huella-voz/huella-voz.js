/**
 * Parche 23: la huella de voz. Ver telefono/PARCHES.md y telefono/huella-voz/ en Life
 * Assistant.
 *
 * BORRADOR SIN ENGANCHAR: va a `voice-app/lib/huella-voz.js` de claude-phone, pero no
 * está enganchado ni probado. El servicio al que llama ya corre en «jacobo» desde el
 * 2026-10-28 (ver «El parche 23» en telefono/PARCHES.md).
 *
 * En el modo coche (parche 22) cualquiera que diga «Jarvis» le despierta: un pasajero, o
 * la radio. Ahora, cuando la frase trae el nombre y ANTES de despertar, se pregunta al
 * servicio de la huella (un contenedor aparte, en jacobo) si esa voz es la de Mikel.
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
 *
 * Varias voces: «aprende mi voz del coche» o «…con el altavoz» guarda una aparte con ese
 * nombre (`coche`, `altavoz`), y basta con parecerse a una. Hay que grabar cada una DONDE
 * se va a usar: la del coche, en el coche y en marcha. «Olvida mi voz del coche» la
 * quita. Sin sitio, es la `general`. El servicio tiene tope (3) y lo dice al grabar.
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
  const s = fx(datos.similitud) + ' / umbral ' + fx(datos.umbral) +
    (datos.perfil ? ', con «' + datos.perfil + '»' : '');
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

const PERFIL_GENERAL = 'general';

function paraPerfil(perfil) {
  return perfil === PERFIL_GENERAL ? '' : ' para «' + perfil.replace(/-/g, ' ') + '»';
}

const FRASES_HUELLA = {
  sinServicio: 'No tengo dónde guardar su voz, señor: el servicio de la huella no está configurado.',
  empezar:     'Voy a aprender su voz, señor. Repita cada frase después de mí, con naturalidad, ' +
               'como si me hablara en el coche.',
  libre:       'Y para terminar, cuénteme en unas frases qué tal le ha ido el día.',
  pocaVoz:     'No le he oído lo suficiente, señor. Lo intentamos en otro momento.',
  fallo:       'No he podido guardar su voz, señor: el servicio de la huella no responde.',
  hecha:       function (p) { return 'Hecho, señor. Ya conozco su voz' + paraPerfil(p) + '.'; },
  llenas:      function (perfiles) {
    return 'Ya tengo ' + perfiles.length + ' voces suyas guardadas, señor: ' +
      perfiles.map(function (p) { return p.replace(/-/g, ' '); }).join(', ') +
      '. Dígame «olvida mi voz de» y cuál, para hacer sitio.';
  },
  olvidada:    function (p) { return 'Hecho, señor. He olvidado su voz' + paraPerfil(p) + '.'; },
  noEstaba:    function (p) { return 'No tenía guardada su voz' + paraPerfil(p) + ', señor.'; },
  falloOlvido: 'No he podido olvidar su voz, señor: el servicio de la huella no responde.'
};

function normaliza(texto) {
  return String(texto || '').toLowerCase()
    .normalize('NFD').replace(/\p{Diacritic}/gu, '')
    .replace(/[.,;:!?¡¿"«»]/g, ' ')
    .replace(/\b(jarvis|por favor|venga|oye)\b/g, ' ')
    .replace(/\s+/g, ' ').trim();
}

// «… mi voz [del coche | con el altavoz | en casa]»: el sitio, si lo hay, da el nombre.
const SITIO = '(?: (?:de|del|en|con|para|desde)(?: (?:el|la|los|las|mi))? (.+))?';
const APRENDER = new RegExp('^(?:aprende|aprendete|graba|memoriza|registra|guarda)(?: a reconocer)? ' +
  '(?:mi (?:huella de )?voz|mi huella)' + SITIO + '$');
const OLVIDAR = new RegExp('^(?:olvida|olvidate de|borra|elimina) ' +
  '(?:mi (?:huella de )?voz|mi huella)' + SITIO + '$');

function aPerfil(sitio) {
  if (!sitio) return PERFIL_GENERAL;
  const nombre = sitio.split(' ')
    .filter(function (p) { return !/^(el|la|los|las|mi|de|del)$/.test(p); })
    .join('-').replace(/[^a-z0-9-]/g, '').slice(0, 32).replace(/-+$/, '');
  return nombre || PERFIL_GENERAL;
}

/** «Jarvis, aprende mi voz del coche» → `coche`; sin sitio → `general`; otra cosa → null. */
function pideAprenderVoz(texto) {
  const m = APRENDER.exec(normaliza(texto));
  return m ? aPerfil(m[1]) : null;
}

/** «Jarvis, olvida mi voz del coche» → `coche`; sin sitio → `general`; otra cosa → null. */
function pideOlvidarVoz(texto) {
  const m = OLVIDAR.exec(normaliza(texto));
  return m ? aPerfil(m[1]) : null;
}

/**
 * La conversación del alta. Devuelve { hecha, motivo, ...lo que contestó el servicio }.
 *
 * @param {Object} c - { endpoint, session, ttsService, voiceId, log, sigueActiva, fetchImpl }
 * @param {string} [perfil] - lo que devolvió pideAprenderVoz (`general` si no va)
 */
async function aprenderVoz(c, perfil) {
  const log = c.log || function () {};
  const sigue = c.sigueActiva || function () { return true; };
  const cfg = config();
  perfil = perfil || PERFIL_GENERAL;
  const objetivoMs = entero('HUELLA_VOZ_ALTA_SEGUNDOS', 30) * 1000;
  const decir = async function (texto) {
    if (sigue()) await c.endpoint.play(await c.ttsService.generateSpeech(texto, c.voiceId));
  };
  if (!cfg.url) {
    await decir(FRASES_HUELLA.sinServicio);
    return { hecha: false, motivo: 'sin_servicio' };
  }
  log('HUELLA: alta de voz «' + perfil + '»');
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
      headers: cabeceras(cfg, {
        'X-Frases': frases.map(function (f) { return f.length; }).join(','),
        'X-Perfil': perfil
      }),
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
    log('HUELLA: guardada «' + perfil + '» (' + datos.frases + ' frases, ' + datos.segundos + ' s, ' +
      datos.descartadas + ' descartadas, consistencia ' + datos.consistencia + ')');
    await decir(FRASES_HUELLA.hecha(perfil));
    return Object.assign({ hecha: true }, datos);
  }
  log('HUELLA: no guardada «' + perfil + '» (' + (datos.motivo || r.status) + ')');
  await decir(datos.motivo === 'demasiados_perfiles' ? FRASES_HUELLA.llenas(datos.perfiles || [])
    : datos.motivo === 'poca_voz' || !frases.length ? FRASES_HUELLA.pocaVoz : FRASES_HUELLA.fallo);
  return Object.assign({ hecha: false }, datos, { motivo: datos.motivo || 'fallo' });
}

/**
 * «Olvida mi voz del coche»: quita ese perfil. Devuelve { hecha, motivo }.
 *
 * Mejor preguntar ANTES de grabar si ya están las tres: el servicio rechaza la cuarta
 * después de los 30 s de frases, y eso se lo dice `aprenderVoz` al final.
 *
 * @param {Object} c - { endpoint, ttsService, voiceId, log, sigueActiva, fetchImpl }
 * @param {string} perfil - lo que devolvió pideOlvidarVoz
 */
async function olvidarVoz(c, perfil) {
  const log = c.log || function () {};
  const sigue = c.sigueActiva || function () { return true; };
  const cfg = config();
  const decir = async function (texto) {
    if (sigue()) await c.endpoint.play(await c.ttsService.generateSpeech(texto, c.voiceId));
  };
  if (!cfg.url) {
    await decir(FRASES_HUELLA.sinServicio);
    return { hecha: false, motivo: 'sin_servicio' };
  }
  let r;
  try {
    r = await (c.fetchImpl || fetch)(cfg.url + '/perfil/' + encodeURIComponent(perfil), {
      method: 'DELETE', headers: cabeceras(cfg), signal: AbortSignal.timeout(cfg.timeoutMs)
    });
  } catch (err) {
    log('HUELLA: el servicio no contesta al olvidar (' + err.message + ')');
    await decir(FRASES_HUELLA.falloOlvido);
    return { hecha: false, motivo: 'fallo' };
  }
  log('HUELLA: olvidar «' + perfil + '» → ' + r.status);
  if (r.ok) {
    await decir(FRASES_HUELLA.olvidada(perfil));
    return { hecha: true };
  }
  await decir(r.status === 404 ? FRASES_HUELLA.noEstaba(perfil) : FRASES_HUELLA.falloOlvido);
  return { hecha: false, motivo: r.status === 404 ? 'sin_perfil' : 'fallo' };
}

module.exports = {
  comprobarVoz, aprenderVoz, olvidarVoz, pideAprenderVoz, pideOlvidarVoz, FRASES_ALTA, FRASES_HUELLA
};
