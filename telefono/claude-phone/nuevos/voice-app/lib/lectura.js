/**
 * Parches 18, 20, 24, 36 y 37: leer en voz alta lo que no cabe en una respuesta, y con mando.
 *
 * Parche 37 (2026-11-05): también internet, `📖 LEER: internet pregunta=<pregunta>`. Una web
 * la escribe cualquiera y Claude tiene shell: la pregunta la pone él, y la respuesta la da
 * en el backend un modelo que solo tiene la web, y va de ahí al altavoz. Claude sabe qué se
 * preguntó, no qué se contestó. Suena la música mientras busca: son unos segundos.
 *
 * Parche 36 (2026-11-02): también WhatsApp, `📖 LEER: whatsapp` (los que esperan
 * respuesta) o `📖 LEER: whatsapp chat=<chat>` (uno). Un WhatsApp lo escribe cualquiera
 * y Claude tiene shell: por eso no los lee él, sino esto, como el parte del correo.
 * Ver telefono/PARCHES.md en Life Assistant.
 *
 * Cada respuesta de Claude por teléfono son 40 palabras (VOICE_CONTEXT, en
 * claude-api-server) y lo que pase de 60 se tira (extractVoiceLine). El briefing de
 * la mañana son ~15 minutos: Claude solo podía leer un trozo y preguntar «¿sigo?».
 * Y aunque se le dejara, recitar 15.000 caracteres le llevaría más de un minuto de
 * música de espera por turno.
 *
 * Así que Claude no lo lee. Pone en su respuesta una línea
 *
 *   📖 LEER: <qué> [desde=N] [hasta=M] [fecha=YYYY-MM-DD] [seguir]
 *
 * con <qué> = briefing, semana (la agenda), correo (el parte de la noche) o tareas, y
 * la llamada pide el texto ya preparado para la voz al backend de Life Assistant
 * (GET /telefono/lectura) y lo lee ella, trozo a trozo: mientras suena uno se
 * sintetiza el siguiente, y cada trozo se puede cortar hablando (barge-in, parche
 * 16). Si le cortas, a Claude le llega en qué sección iba, para seguir desde ahí.
 *
 * El parche 18 solo sabía leer el briefing; el 20 lee también lo demás. De paso, el
 * texto de terceros (asuntos y remitentes del correo) va del backend al altavoz sin
 * pasar por Claude, que es una sesión con shell.
 *
 * El 24 le da mando, sin pasar por Claude (ControlLectura):
 * - Antes de que suene cada trozo, se le dice al backend por dónde va
 *   (POST /telefono/lectura/posicion). Así, si cuelgas a media lectura, «sigue
 *   leyendo» en otra llamada —o `📖 LEER: briefing seguir`— retoma ese mismo trozo.
 * - Cortándole, entiende una lista cerrada de órdenes: «sigue», «siguiente» o
 *   «sáltate esto» (el bloque siguiente: «IA General», «España»…), «siguiente
 *   sección», «anterior», «repite», «desde el principio», «para», y «ve a la de
 *   economía» o «la sección cuatro» (con el `indice` que manda el backend). La frase
 *   ENTERA tiene que ser la orden, como el «sí» del parche 20: «para, ¿qué hora es?»
 *   no es parar, y va a Claude.
 * - Las órdenes sueltas («sigue», «siguiente», «para») solo valen justo después de
 *   leer: tras un turno de Claude, «sigue» puede contestar a otra cosa. Las que dicen
 *   qué («sigue leyendo», «ve a la de economía») valen siempre, y «sigue leyendo» vale
 *   también en una llamada nueva.
 *
 * Variables: LECTURA_URL (por defecto http://127.0.0.1:8080, el backend en la misma
 * máquina; la voice-app va con network_mode host) y LECTURA_TOKEN (el token del MCP
 * del teléfono, JARVIS_MCP_TELEFONO_TOKEN del backend).
 */
'use strict';

const { decirInterrumpible } = require('./turno-rapido');

const QUE = ['briefing', 'semana', 'correo', 'tareas', 'whatsapp', 'internet'];
const MARCA = new RegExp('📖\\s*LEER:\\s*(' + QUE.join('|') + '|seguir)\\b([^\\n]*)', 'i');
const NOMBRE = { briefing: 'el briefing', semana: 'la agenda de la semana',
                 correo: 'el parte del correo', tareas: 'tus tareas',
                 whatsapp: 'tus WhatsApp', internet: 'la respuesta de internet' };
// El chat de `📖 LEER: whatsapp chat=…`: su número o su grupo, como los da el backend.
const CHAT = '[\\d-]{5,40}@(?:s\\.whatsapp\\.net|g\\.us)';
// Lo que el backend admite en `pregunta`.
const PREGUNTA_MAX = 300;
// Buscar y leer una página tarda más que traer un texto ya hecho (20 s).
const LECTURA_MS = 20000;
const BUSCAR_MS = 45000;

// Lo que dice la propia llamada al obedecer una orden.
const FRASES = {
  parar: 'Lo dejo aquí, señor. Cuando quiera, dígame «sigue».',
  fin:   'Ya no queda nada más, señor.'
};

function urlBase() {
  return (process.env.LECTURA_URL || 'http://127.0.0.1:8080').replace(/\/+$/, '');
}

/** El pedido de lectura que trae la respuesta de Claude, o null si no lo trae. */
function pedidoDeLectura(respuesta) {
  const m = String(respuesta || '').match(MARCA);
  if (!m) return null;
  let resto = m[2] || '';
  // La pregunta va la última y es texto libre: se quita antes de mirar lo demás, para que
  // «cómo seguir a un equipo» no sea `seguir` ni «desde=2» un número de sección.
  let pregunta = '';
  if (m[1].toLowerCase() === 'internet') {
    const p = resto.match(/pregunta\s*=\s*(.*)$/i);
    if (p) {
      pregunta = p[1];
      resto = resto.slice(0, p.index);
    } else if (resto.indexOf('=') < 0 && !/^\s*seguir\s*$/i.test(resto)) {
      pregunta = resto;          // «📖 LEER: internet qué tiempo hace», sin la clave
      resto = '';
    }
    pregunta = pregunta.replace(/^[\s"'«“]+|[\s"'»”]+$/g, '').slice(0, PREGUNTA_MAX);
  }
  const valor = function (clave, patron) {
    const r = resto.match(new RegExp(clave + '\\s*=\\s*(' + patron + ')'));
    return r ? r[1] : '';
  };
  const que = m[1].toLowerCase();
  const pedido = {
    que: que === 'seguir' ? '' : que,
    fecha: valor('fecha', '\\d{4}-\\d{2}-\\d{2}'),
    desde: parseInt(valor('desde', '\\d+'), 10) || 1,
    hasta: parseInt(valor('hasta', '\\d+'), 10) || 0
  };
  const trozo = parseInt(valor('trozo', '\\d+'), 10) || 0;
  if (trozo) pedido.trozo = trozo;
  const chat = que === 'whatsapp' ? valor('chat', CHAT) : '';
  if (chat) pedido.chat = chat;
  if (pregunta) pedido.pregunta = pregunta;
  if (que === 'seguir' || /(^|\s)seguir\b/i.test(resto)) pedido.seguir = true;
  return pedido;
}

function noPuedo(que) {
  return 'No he podido traer ' + (NOMBRE[que] || 'eso') + ' para leértelo.';
}

async function traerLectura(pedido, fetchImpl) {
  const que = pedido.que || '';
  const q = new URLSearchParams();
  if (que) q.set('que', que);
  q.set('desde', String(pedido.desde || 1));
  q.set('hasta', String(pedido.hasta || 0));
  if (pedido.fecha) q.set('fecha', pedido.fecha);
  if (pedido.trozo) q.set('trozo', String(pedido.trozo));
  if (pedido.seguir) q.set('seguir', 'true');
  if (pedido.chat) q.set('chat', pedido.chat);
  if (pedido.pregunta) q.set('pregunta', pedido.pregunta);
  try {
    const r = await (fetchImpl || fetch)(urlBase() + '/telefono/lectura?' + q.toString(), {
      headers: { Authorization: 'Bearer ' + (process.env.LECTURA_TOKEN || '') },
      signal: AbortSignal.timeout(pedido.pregunta ? BUSCAR_MS : LECTURA_MS)
    });
    if (!r.ok) return { ok: false, frase: noPuedo(que), motivo: 'HTTP ' + r.status };
    const datos = await r.json();
    if (!datos || !datos.ok) return { ok: false, frase: (datos && datos.frase) || noPuedo(que) };
    return datos;
  } catch (e) {
    return { ok: false, frase: noPuedo(que), motivo: e.message };
  }
}

/**
 * Le dice al backend por dónde va, sin esperar: es lo que retoma «sigue leyendo» si se
 * cuelga. Un fallo aquí no puede parar la lectura; como mucho, se pierde el sitio.
 */
function apuntarPosicion(lectura, item, terminada, c) {
  if (!lectura.que) return;
  const log = c.log || function () {};
  const cuerpo = { que: lectura.que, fecha: lectura.fecha || '', n: item.n,
                   trozo: item.trozo, titulo: item.titulo || '', terminada: !!terminada };
  try {
    const p = (c.fetchImpl || fetch)(urlBase() + '/telefono/lectura/posicion', {
      method: 'POST',
      headers: { Authorization: 'Bearer ' + (process.env.LECTURA_TOKEN || ''),
                 'Content-Type': 'application/json' },
      body: JSON.stringify(cuerpo),
      signal: AbortSignal.timeout(5000)
    });
    Promise.resolve(p).catch(function (e) {
      log('LECTURA: no se pudo apuntar por dónde va (' + e.message + ')');
    });
  } catch (e) {
    log('LECTURA: no se pudo apuntar por dónde va (' + e.message + ')');
  }
}

function listaDeSecciones(indice) {
  return (indice || []).map(function (s) { return (s.etiqueta || s.n) + ' ' + s.titulo; }).join('; ');
}

/**
 * Lee lo que diga `pedido`. Devuelve { interrumpio, aviso, estado }: `interrumpio` como
 * decirInterrumpible (el oído queda abierto con lo que estás diciendo), `aviso`, lo que
 * hay que anteponer a lo siguiente que se le pregunte a Claude ('' si nada), y `estado`,
 * por dónde se quedó (para ControlLectura), o null si no se leyó nada.
 */
async function leer(pedido, c) {
  const log = c.log || function () {};
  const sigueActiva = c.sigueActiva || function () { return true; };
  log('LECTURA: ' + (pedido.que || 'lo último') + ' desde=' + pedido.desde +
      ' hasta=' + (pedido.hasta || 'fin') + (pedido.trozo ? ' trozo=' + pedido.trozo : '') +
      (pedido.seguir ? ' seguir' : '') + (pedido.fecha ? ' fecha=' + pedido.fecha : ''));

  // La pregunta no va al registro: es lo que ha dicho Mikel.
  const buscando = !!(pedido.pregunta && c.musicaUrl && sigueActiva());
  if (buscando) {
    Promise.resolve().then(function () { return c.endpoint.play(c.musicaUrl); }).catch(function () {});
  }
  const datos = await traerLectura(pedido, c.fetchImpl);
  if (buscando && sigueActiva()) {
    try { await c.endpoint.api('uuid_break', c.endpoint.uuid); } catch (e) { /* ya parada */ }
  }
  const que = datos.que || pedido.que || '';
  const nombre = datos.nombre || NOMBRE[que] || 'lo que te estaba leyendo';
  if (!datos.ok) {
    log('LECTURA: no se puede (' + (datos.motivo || datos.frase) + ')');
    if (!sigueActiva()) return { interrumpio: false, aviso: '', estado: null };
    const url = await c.ttsService.generateSpeech(datos.frase, c.voiceId);
    const cortado = await decirInterrumpible(c.endpoint, c.session, url, log);
    return { interrumpio: cortado, estado: null,
             aviso: '[La lectura ' + (que ? 'de ' + nombre : 'a medias que te pidió seguir') +
                    ' no se pudo hacer: «' + datos.frase + '»] ' };
  }

  const lectura = { que: que, fecha: datos.fecha || pedido.fecha || '', nombre: nombre,
                    indice: datos.indice || [] };
  const cola = [];
  for (const s of datos.secciones || []) {
    const base = s.primer_trozo || 0;
    (s.trozos || []).forEach(function (t, i) {
      cola.push({ n: s.n, titulo: s.titulo, trozo: base + i, texto: t });
    });
  }
  if (!cola.length) return { interrumpio: false, aviso: '', estado: null };
  const total = (lectura.indice.length || (datos.secciones || []).length);
  const primero = cola[0];
  const ultimo = cola[cola.length - 1];
  // Retomar otra llamada sin decir dónde deja a quien escucha sin saber qué oye.
  if (pedido.seguir) {
    cola.unshift({ n: primero.n, titulo: primero.titulo, entrada: true,
                   texto: 'Sigo con ' + nombre + ', en «' + primero.titulo + '».' });
  }
  // Una respuesta no se cierra con «Eso es todo»: se contesta y ya.
  const respuesta = que === 'internet';
  if (!respuesta) {
    cola.push({ n: ultimo.n, titulo: ultimo.titulo, trozo: ultimo.trozo, final: true,
                texto: que === 'briefing' ? 'Hasta aquí el briefing.' : 'Eso es todo.' });
  }

  const estado = Object.assign({}, lectura, { n: primero.n, trozo: primero.trozo,
                                              titulo: primero.titulo, fin: false, recien: true });
  // El siguiente trozo se sintetiza mientras suena el actual: así no hay silencio entre
  // uno y otro. Un fallo de la voz se guarda como null y corta la lectura ahí.
  const sintetizar = function (texto) {
    return c.ttsService.generateSpeech(texto, c.voiceId).catch(function (e) {
      log('LECTURA: falló la voz (' + e.message + ')');
      return null;
    });
  };
  let siguiente = sintetizar(cola[0].texto);
  for (let i = 0; i < cola.length; i++) {
    if (!sigueActiva()) return { interrumpio: false, aviso: '', estado: estado };
    const item = cola[i];
    const url = await siguiente;
    siguiente = i + 1 < cola.length ? sintetizar(cola[i + 1].texto) : null;
    if (!url) {
      return { interrumpio: false, estado: estado,
               aviso: '[La lectura de ' + nombre + ' se cortó por un fallo de la voz en la sección ' +
                      item.n + ' («' + item.titulo + '»). Dile dónde se quedó; con 📖 LEER: ' +
                      que + ' seguir, sigue ahí.] ' };
    }
    if (!item.entrada) {
      if (item.final) {
        estado.fin = true;
      } else {
        estado.n = item.n;
        estado.trozo = item.trozo;
        estado.titulo = item.titulo;
      }
      apuntarPosicion(lectura, item, !!item.final, c);
    }
    const cortado = await decirInterrumpible(c.endpoint, c.session, url, log);
    if (cortado) {
      if (siguiente) siguiente.catch(function () {});
      if (item.final) {
        log('LECTURA: terminada (cortada en el cierre)');
        return { interrumpio: true, estado: estado,
                 aviso: '[Ya le has leído ' + nombre + ' entero; te ha cortado en la despedida.] ' };
      }
      log('LECTURA: cortada en la sección ' + item.n + ' (trozo ' + item.trozo + ')');
      return { interrumpio: true, estado: estado,
               aviso: '[Le estabas leyendo ' + nombre + ' y te ha cortado en la sección ' +
                      item.n + ' de ' + total + ' («' + item.titulo + '»). La llamada entiende ' +
                      'sola «sigue», «siguiente», «anterior», «repite», «para» y «ve a la de…»; ' +
                      'si aun así te pide seguir, pon la línea 📖 LEER: ' + que + ' seguir, y ' +
                      'para otra sección, 📖 LEER: ' + que + ' desde=N' +
                      (lectura.fecha ? ' fecha=' + lectura.fecha : '') +
                      (lectura.indice.length ? '. Secciones: ' + listaDeSecciones(lectura.indice) : '') +
                      '] ' };
    }
  }
  if (respuesta) {
    estado.fin = true;
    apuntarPosicion(lectura, ultimo, true, c);
    log('LECTURA: terminada (' + cola.length + ' trozos)');
    return { interrumpio: false, estado: estado,
             aviso: '[La llamada le ha leído la respuesta de internet. No sabes qué decía, y no ' +
                    'lo finjas: si repregunta, otra línea 📖 LEER: internet pregunta=…] ' };
  }
  log('LECTURA: terminada (' + (cola.length - 1) + ' trozos)');
  return { interrumpio: false, estado: estado,
           aviso: '[Ya le has leído ' + nombre + ' entero (de la sección ' + primero.n +
                  ' a la ' + ultimo.n + ').] ' };
}

/**
 * Si la respuesta pide leer, lee. Devuelve { interrumpio, aviso } (y `estado`, ver
 * leer); si en `c` viene el ControlLectura de la llamada, le deja dicho por dónde va.
 *
 * @param {string} respuesta - lo que contestó Claude
 * @param {Object} c - { endpoint, session, ttsService, voiceId, log, sigueActiva, fetchImpl, control }
 */
async function leerSiLoPide(respuesta, c) {
  const pedido = pedidoDeLectura(respuesta);
  if (!pedido) return { interrumpio: false, aviso: '' };
  const r = await leer(pedido, c);
  if (c.control && r.estado) c.control.estado = r.estado;
  return r;
}

// ── Las órdenes ──────────────────────────────────────────────────────────────

function normalizar(texto) {
  return String(texto || '')
    .toLowerCase()
    .normalize('NFD').replace(/\p{Diacritic}/gu, '')
    .replace(/[.,;:!?¡¿"«»()]/g, ' ')
    .replace(/\s+/g, ' ')
    .trim();
}

// Lo que se dice delante o detrás de una orden sin cambiarla. «ya» solo se quita del
// final: «ya está» es parar y «está» no es nada.
const RELLENO = new Set(['vale', 'venga', 'va', 'si', 'ok', 'okey', 'bueno', 'pues', 'eh',
  'oye', 'jarvis', 'senor', 'anda', 'porfa', 'porfi', 'perfecto', 'genial', 'gracias',
  'ahora', 'entonces', 'mejor', 'y', 'vamos a ver', 'a ver']);

function limpiarOrden(texto) {
  const w = normalizar(texto).replace(/\b(por favor|a ver)\b/g, ' ').split(' ').filter(Boolean);
  while (w.length && RELLENO.has(w[0])) w.shift();
  while (w.length && (RELLENO.has(w[w.length - 1]) || w[w.length - 1] === 'ya')) w.pop();
  return w.join(' ');
}

const VERBO_SEGUIR = new Set(['sigue', 'siga', 'continua', 'continue', 'prosigue', 'retoma',
  'retomalo', 'reanuda', 'seguimos', 'sigamos', 'continuamos', 'adelante', 'dale']);
const PALABRA_LECTURA = new Set(['leyendo', 'leyendome', 'leyendomelo', 'leyendolo', 'leer',
  'lectura', 'resto', 'donde']);
const NEXO = new Set(['con', 'el', 'la', 'las', 'los', 'lo', 'de', 'del', 'me', 'por', 'desde',
  'que', 'estabas', 'ibas', 'iba', 'ibamos', 'dejaste', 'dejamos', 'quedaste', 'quedamos',
  'has', 'dejado', 'a', 'al', 'te', 'estabamos', 'nos', 'eso', 'ello', 'esto', 'queda',
  'falta', 'sigue']);
const QUE_PALABRA = { briefing: 'briefing', brifing: 'briefing', briefin: 'briefing',
  breafing: 'briefing', agenda: 'semana', semana: 'semana', correo: 'correo',
  correos: 'correo', parte: 'correo', tareas: 'tareas', pendientes: 'tareas',
  whatsapp: 'whatsapp', whatsapps: 'whatsapp', wasap: 'whatsapp', wasaps: 'whatsapp',
  guasap: 'whatsapp', guasaps: 'whatsapp', mensajes: 'whatsapp' };

/** «sigue», «sigue leyendo», «sigue con el briefing», «léeme el resto»… o null. */
function ordenSeguir(t) {
  const p = t.split(' ');
  let resto;
  if (VERBO_SEGUIR.has(p[0])) {
    resto = p.slice(1);
  } else if (/^(leeme|lee|leete|cuentame)$/.test(p[0]) && /\b(resto|lo que (queda|falta))\b/.test(t)) {
    resto = p.slice(1);
  } else {
    return null;
  }
  let que = '';
  let explicita = false;
  for (const w of resto) {
    if (QUE_PALABRA[w]) { que = QUE_PALABRA[w]; explicita = true; }
    else if (PALABRA_LECTURA.has(w)) explicita = true;
    else if (!NEXO.has(w)) return null;          // «sigue buscando» no es seguir leyendo
  }
  return { que: que, explicita: explicita };
}

const VERBO_IR = '(?:(?:pasa|salta|saltate|ve|vete|vamos|sigue|vuelve|regresa|pon|ponme|lee|leeme)' +
  '(?: a| al| con| hasta)? )?';
const COSA = '(?:noticia|bloque|tema|parte|cosa|seccion|apartado)';
function direccion(palabra) {
  return new RegExp('^' + VERBO_IR + '(?:(?:la|lo|el) )?(?:' + palabra + '(?: ' + COSA + ')?|' +
                    COSA + ' ' + palabra + ')$');
}
const SIGUIENTE = direccion('(?:siguiente|proxima|proximo|otra|otro)');
const ANTERIOR = direccion('anterior');
const SALTAR = /^(?:salta|saltala|saltalo|saltatela|saltatelo|saltate|pasa|pasala|pasalo|omite|omitela|next)(?: (?:de )?(?:esta|esto|eso|esa|este|ese)(?: (?:seccion|parte|noticia|bloque|tema))?)?$/;
const NO_INTERESA = /^(?:(?:esto|eso|esta|esa) )?no me interesa(?: (?:nada|esto|eso))?$/;
const ATRAS = /^(?:(?:vuelve|ve|vete|regresa)(?: hacia)? )?atras$/;
const REPETIR = /^(?:repite|repitelo|repitela|repitemelo|repitemela|otra vez|de nuevo|vuelve a leer(?:lo|la|melo|mela)?|(?:lee|leeme)(?:lo|la)? otra vez|leemelo otra vez|vuelve a empezar)(?: (?:esta|esa|la|el|este|ese) (?:seccion|parte|noticia|bloque|apartado))?$/;
const PARAR = /^(?:para|pare|paralo|parala|basta|stop|calla|callate|pausa|detente|dejalo|deja de leer|ya esta|ya basta|suficiente|es suficiente|(?:para|dejalo) (?:ahi|aqui|de leer|un momento|un segundo|para luego|para despues|para mas tarde)|luego (?:sigues|seguimos|me lo sigues|continuamos))$/;
const PRINCIPIO = /^(?:(?:empieza|empiezalo|vuelve|ve|vete|lee|leeme|leemelo|leelo|repite|repitelo|vuelve a empezar|empieza otra vez|empieza de nuevo|lee otra vez|otra vez)(?: (?:desde|por|al|a))?(?: (?:el|la))? )?(?:desde el |por el |al )?(?:principio|inicio|comienzo)(?: (?:de (?:todo|la seccion|esta seccion)|del (?:todo|briefing)))?$/;
// «Ve a la de economía», «léeme lo del Financial Times», «la sección cuatro». «Salta» y
// «pasa» solo con «a»: «sáltate la palabra del día» es saltársela, no ir a ella.
const PREFIJO_IR = /^(?:(?:(?:ve|vete|ir|pasa|salta|vamos|vuelve|regresa)(?: (?:a|al|hasta|hasta el|hasta la|directamente a|directo a))|(?:lee|leeme|leete|cuentame|pon|ponme|quiero oir)(?: con)?)(?: (?:la|el|lo|las|los))?(?: (?:seccion|parte|apartado|bloque|noticias?))?(?: (?:de|del|sobre|numero))?|(?:la|el|lo|las) (?:(?:seccion|parte|apartado)(?: (?:de|del|sobre|numero))?|de|del|sobre|numero)|(?:seccion|apartado|parte) (?:de |del |sobre |numero )?)\s+(.+)$/;

const NUMEROS = { uno: 1, una: 1, primera: 1, primero: 1, dos: 2, segunda: 2, segundo: 2,
  tres: 3, tercera: 3, tercero: 3, cuatro: 4, cuarta: 4, cuarto: 4, cinco: 5, quinta: 5,
  quinto: 5, seis: 6, sexta: 6, sexto: 6, siete: 7, septima: 7, septimo: 7, setima: 7,
  ocho: 8, octava: 8, octavo: 8, nueve: 9, novena: 9, noveno: 9, diez: 10, decima: 10,
  decimo: 10 };
const VACIAS = new Set(['de', 'del', 'la', 'el', 'los', 'las', 'y', 'e', 'a', 'al', 'en',
  'sobre', 'que', 'lo', 'con', 'mas', 'un', 'una', 'tu', 'mi', 'su', 'para', 'por', 'seccion',
  'parte', 'apartado', 'bloque', 'noticia', 'noticias', 'es', 'esto', 'eso']);
// Cómo se pide una sección sin decir su título tal cual.
const SINONIMOS = { ia: 'inteligencia artificial', ai: 'inteligencia artificial',
  tiempo: 'clima', ft: 'financial times', salud: 'estado fisico', sueno: 'estado fisico',
  uni: 'entregas', universidad: 'entregas', tech: 'tecnologia', mercados: 'economia',
  bolsa: 'economia', mundo: 'resto mundo', internacional: 'resto mundo' };

function palabras(texto) {
  const salida = [];
  for (const w of normalizar(texto).split(' ')) {
    if (!w || VACIAS.has(w)) continue;
    for (const s of (SINONIMOS[w] || w).split(' ')) salida.push(s);
  }
  return salida;
}

function seParecen(a, b) {
  if (a === b) return true;
  const corta = Math.min(a.length, b.length);
  if (corta >= 4 && (a.startsWith(b) || b.startsWith(a))) return true;
  return corta >= 6 && a.slice(0, 6) === b.slice(0, 6);
}

/** Todas las secciones y sus bloques, en orden, desde el `indice` del backend. */
function entradasDe(indice) {
  const lista = [];
  for (const s of indice || []) {
    lista.push({ n: s.n, trozo: 0, titulo: s.titulo, seccion: true,
                 etiqueta: String(s.etiqueta || s.n) });
    for (const b of s.bloques || []) {
      lista.push({ n: s.n, trozo: b.trozo || 0, titulo: b.titulo, seccion: false });
    }
  }
  return lista;
}

/** Las paradas para moverse: una por sitio (un bloque al principio de su sección es la sección). */
function paradasDe(entradas) {
  const vistas = new Set();
  return entradas.filter(function (e) {
    const clave = e.n + ':' + e.trozo;
    if (vistas.has(clave)) return false;
    vistas.add(clave);
    return true;
  });
}

function dondeEstoy(paradas, n, trozo) {
  let i = 0;
  paradas.forEach(function (p, j) {
    if (p.n < n || (p.n === n && p.trozo <= trozo)) i = j;
  });
  return i;
}

function numeroDe(destino) {
  const d = destino.replace(/^(?:la|el|numero|seccion|parte) /, '').replace(/^(?:la|el|numero|seccion|parte) /, '');
  let m = d.match(/^(\d{1,2})(?:[ .,](\d))?$/);
  if (m) return m[2] ? m[1] + '.' + m[2] : m[1];
  m = d.match(/^([a-z]+) (?:y media|y medio|coma cinco|punto cinco)$/);
  if (m && NUMEROS[m[1]]) return NUMEROS[m[1]] + '.5';
  if (NUMEROS[d]) return String(NUMEROS[d]);
  if (d === 'ultima' || d === 'ultimo') return 'ultima';
  return null;
}

/** La entrada a la que se refiere «economía», «la palabra del día», «la cuatro»… o null. */
function buscarDestino(entradas, destino, estricto) {
  const secciones = entradas.filter(function (e) { return e.seccion; });
  const num = numeroDe(destino);
  if (num === 'ultima') return secciones[secciones.length - 1] || null;
  if (num) {
    return secciones.find(function (s) { return s.etiqueta === num; }) ||
           secciones.find(function (s) { return String(s.n) === num; }) || null;
  }
  const buscadas = palabras(destino);
  if (!buscadas.length || (estricto && buscadas.every(function (w) { return w.length < 3; }))) return null;
  let mejor = null;
  let empate = false;
  for (const e of entradas) {
    const suyas = palabras(e.titulo);
    if (!suyas.length) continue;
    const aciertos = buscadas.filter(function (w) {
      return suyas.some(function (s) { return seParecen(w, s); });
    }).length;
    // Todas las palabras dichas; con tres o más, vale fallar una (Whisper y los nombres propios).
    const basta = buscadas.length >= 3 && !estricto ? buscadas.length - 1 : buscadas.length;
    if (aciertos < basta) continue;
    const cubre = aciertos / suyas.length;
    const puntos = aciertos * 10 + cubre + (e.seccion ? 0.01 : 0);
    if (!mejor || puntos > mejor.puntos) {
      mejor = { puntos: puntos, entrada: e };
      empate = false;
    } else if (puntos === mejor.puntos && (mejor.entrada.n !== e.n || mejor.entrada.trozo !== e.trozo)) {
      empate = true;
    }
  }
  return mejor && !empate ? mejor.entrada : null;
}

/**
 * La orden que es `texto` para la lectura de `estado` (o sin lectura en esta llamada),
 * o null si no es una orden y tiene que ir a Claude. Pura: no lee ni dice nada.
 *
 * Devuelve { tipo: 'seguir'|'ir'|'parar'|'nada', n, trozo, que, backend }: 'ir' y
 * 'seguir' con n/trozo leen desde ahí; 'seguir' con `backend` pide al backend la última
 * lectura a medias (la de `que`, si se dijo); 'nada' dice FRASES.fin.
 */
function ordenDeLectura(texto, estado) {
  const t = limpiarOrden(texto);
  if (!t) return null;
  const e = estado;
  const suelta = !!(e && e.recien);

  const s = ordenSeguir(t);
  if (s && (s.explicita || suelta)) {
    if (e && !e.fin && (!s.que || s.que === e.que)) return { tipo: 'seguir', n: e.n, trozo: e.trozo };
    if (s.explicita) return { tipo: 'seguir', backend: true, que: s.que };
    return null;
  }
  if (!e) return null;
  if (suelta && PARAR.test(t)) return { tipo: 'parar' };

  const entradas = entradasDe(e.indice);
  const paradas = paradasDe(entradas);
  if (!paradas.length) return null;                 // un backend sin índice: que lo vea Claude
  const i = dondeEstoy(paradas, e.n, e.trozo);
  const ir = function (p) { return p ? { tipo: 'ir', n: p.n, trozo: p.trozo, titulo: p.titulo } : { tipo: 'nada' }; };
  const deSeccion = /\b(seccion|apartado)\b/.test(t);

  if (SIGUIENTE.test(t) || (suelta && (SALTAR.test(t) || NO_INTERESA.test(t)))) {
    if (deSeccion) return ir(paradas.find(function (p) { return p.seccion && p.n > e.n; }));
    return suelta ? ir(paradas[i + 1]) : null;
  }
  if (ANTERIOR.test(t) || (suelta && ATRAS.test(t))) {
    if (!deSeccion && !suelta) return null;
    if (deSeccion) {
      const previas = paradas.filter(function (p) { return p.seccion && p.n < e.n; });
      return ir(previas.length ? previas[previas.length - 1] : paradas.find(function (p) { return p.n === e.n; }));
    }
    return ir(paradas[Math.max(0, i - 1)]);
  }
  if (PRINCIPIO.test(t)) {
    if (/\bseccion\b/.test(t)) return ir(paradas.find(function (p) { return p.n === e.n; }));
    return ir(paradas[0]);
  }
  // «Repite» a secas es lo que estaba sonando; «repite esta noticia», el bloque entero.
  if (REPETIR.test(t) && (suelta || deSeccion)) {
    if (deSeccion) return ir(paradas.find(function (p) { return p.n === e.n; }));
    if (/\b(noticia|bloque|parte|tema)\b/.test(t)) return ir(paradas[i]);
    return { tipo: 'ir', n: e.n, trozo: e.trozo, titulo: e.titulo };
  }

  const m = t.match(PREFIJO_IR);
  const destino = m ? m[1].replace(/^(?:la|el|lo|las|los) /, '') : (suelta ? t : '');
  if (!destino) return null;
  const encontrada = buscarDestino(entradas, destino, !m);
  return encontrada ? ir(encontrada) : null;
}

/**
 * El mando de la lectura en una llamada. Uno por llamada: guarda por dónde va la última
 * lectura y atiende las órdenes antes de que lleguen a Claude.
 */
class ControlLectura {
  constructor() {
    this.estado = null;
  }

  /** Tras un turno de Claude, las órdenes sueltas («sigue», «para») ya no son para la lectura. */
  turnoDeClaude() {
    if (this.estado) this.estado.recien = false;
  }

  /**
   * Si `transcript` es una orden de la lectura, la cumple y devuelve { interrumpio, aviso }
   * (como leerSiLoPide); si no, null y lo dicho va a Claude.
   */
  async atender(transcript, c) {
    const orden = ordenDeLectura(transcript, this.estado);
    if (!orden) return null;
    const log = c.log || function () {};
    const e = this.estado;
    log('LECTURA: orden «' + String(transcript).trim() + '» → ' + orden.tipo +
        (orden.n ? ' sección ' + orden.n + ' trozo ' + orden.trozo : ''));
    if (orden.tipo === 'parar' || orden.tipo === 'nada') {
      const url = await c.ttsService.generateSpeech(FRASES[orden.tipo === 'parar' ? 'parar' : 'fin'], c.voiceId);
      const cortado = await decirInterrumpible(c.endpoint, c.session, url, log);
      const aviso = orden.tipo === 'parar'
        ? '[Le estabas leyendo ' + e.nombre + ' y te ha pedido que pares en la sección ' + e.n +
          ' («' + e.titulo + '»). Si luego te pide que sigas, pon la línea 📖 LEER: ' + e.que + ' seguir.] '
        : '[Le has dicho que no queda nada más de ' + e.nombre + '.] ';
      return { interrumpio: cortado, aviso: aviso };
    }
    const pedido = orden.backend
      ? { que: orden.que || '', desde: 1, hasta: 0, fecha: '', seguir: true }
      : { que: e.que, fecha: e.fecha, desde: orden.n, hasta: 0, trozo: orden.trozo };
    const r = await leer(pedido, Object.assign({}, c, { control: this }));
    if (r.estado) this.estado = r.estado;
    return { interrumpio: r.interrumpio, aviso: r.aviso };
  }
}

// `traerBriefing` se queda por compatibilidad con lo que lo importara (parche 18).
module.exports = { leerSiLoPide, pedidoDeLectura, traerLectura, traerBriefing: traerLectura,
                   ControlLectura, ordenDeLectura, limpiarOrden, FRASES };
