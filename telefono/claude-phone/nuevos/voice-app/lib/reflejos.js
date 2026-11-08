/**
 * Parche 34: lo que la llamada cumple sola, sin pasar por Claude. Hoy, la tele: «baja el
 * volumen», «apaga la tele», «pon Netflix». Claude tarda de 1,5 a 3 s en decidir lo que
 * aquí son 200 ms, y para esto no hay nada que pensar.
 *
 * El criterio es de frase ENTERA, a propósito: «apaga la tele» es una orden, y «apaga la
 * tele cuando acabe la película» no. Todo lo que no encaje del todo sigue su camino hacia
 * Claude, que tiene la herramienta `tele` para lo que sea más raro. Un falso positivo aquí
 * es peor que uno de menos.
 *
 * interpretar() es pura, para poder probarla sin tele (test/parche34.test.js).
 */

const { decirInterrumpible } = require('./turno-rapido');
const tele = require('./tele');

const N = tele.normalizar;

const NUMEROS = {
  un: 1, una: 1, uno: 1, dos: 2, tres: 3, cuatro: 4, cinco: 5, seis: 6, siete: 7, ocho: 8, nueve: 9, diez: 10,
  once: 11, doce: 12, trece: 13, catorce: 14, quince: 15, dieciseis: 16, diecisiete: 17, dieciocho: 18,
  diecinueve: 19, veinte: 20, veinticinco: 25, treinta: 30, cuarenta: 40, cincuenta: 50, sesenta: 60,
};

function numero(s) {
  const t = String(s || '').trim();
  if (/^\d+$/.test(t)) return parseInt(t, 10);
  if (NUMEROS[t] !== undefined) return NUMEROS[t];
  const m = /^(veinti|treinta y |cuarenta y |cincuenta y )(\w+)$/.exec(t);
  if (m && NUMEROS[m[2]] !== undefined) {
    return ({ 'veinti': 20, 'treinta y ': 30, 'cuarenta y ': 40, 'cincuenta y ': 50 })[m[1]] + NUMEROS[m[2]];
  }
  return null;
}

// Lo que se dice de más al pedir algo, por delante y por detrás
const DELANTE = /^(?:(?:oye|mira|venga|vale|hola|buenas|eh|em|ah|jarvis|harvis|senor|bueno|pues|y|ya|por favor|porfa|ahora|anda|a ver)\b ?)+/;
const PETICION = /^(?:(?:puedes|podrias|quiero que|me gustaria que|necesito que|haz el favor de|hazme el favor de)\b ?)+/;
const DETRAS = /(?: (?:por favor|porfa|jarvis|harvis|senor|ya|ahora|ahora mismo|anda|gracias))+$/;

const TELE = '(?:la )?(?:tele|television|tv)(?: (?:de|del|de la) (?:la )?(?:sala|salon))?';
const OBRA = '(?:la (?:peli|pelicula|serie|tele|television|tv)|el (?:video|contenido|capitulo|programa|partido|episodio)|esto|eso)';
const APPS_VOZ = 'netflix|youtube|you tube|prime video|amazon prime|prime|amazon|disney plus|disney|hbo max|hbo|max|apple tv plus|apple tv|spotify|dazn|plex|jellyfin|movistar plus|movistar|twitch|el tablero|tablero|el dashboard|dashboard';

const EN_TELE = '(?: (?:en|de|a) ' + TELE + ')?';

// La casa. Solo lo común y el cuarto de Mikel: en los cuartos de los demás, que piense Claude.
const INTERRUPTORES = [
  ['(?:las? )?(?:luz|luces) del jardin|el jardin', 'switch.luces_jardin'],
  ['(?:las? )?(?:luz|luces) de (?:la )?mesa|(?:las? )?(?:luz|luces) de mi (?:cuarto|habitacion)|mi luz', 'light.luces_mesa'],
  ['el ventilador', 'switch.fan'],
  ['el altavoz', 'switch.speaker'],
  ['el enchufe del pasillo', 'switch.enchufe_pasillo'],
];
const ZONAS = [
  ['mi cuarto|mi habitacion', 'climate.hab_mikel', 'Su cuarto'],
  ['(?:el )?salon', 'climate.salon', 'El salón'],
  ['(?:la )?cocina', 'climate.cocina', 'La cocina'],
  ['(?:el )?atico', 'climate.atico', 'El ático'],
  ['(?:la )?planta baja', 'climate.planta_baja', 'La planta baja'],
  ['(?:el )?pasillo', 'climate.pasillo_habitaciones', 'El pasillo'],
  ['(?:el )?txoko', 'climate.txoko', 'El txoko'],
  ['(?:el )?recibidor', 'climate.recibidor', 'El recibidor'],
];
const GRADOS_MIN = 15;
const GRADOS_MAX = 25;

const REGLAS_CASA = [];
for (const [dicho, entidad] of INTERRUPTORES) {
  const dominio = entidad.split('.')[0];
  REGLAS_CASA.push([new RegExp('^(?:enciende(?:me)?|encender|prende|pon(?:me)?) (?:' + dicho + ')$'),
    function () { return { casa: { servicio: dominio + '.turn_on', entidad: entidad } }; }]);
  REGLAS_CASA.push([new RegExp('^(?:apaga(?:me)?|apagar|quita(?:me)?) (?:' + dicho + ')$'),
    function () { return { casa: { servicio: dominio + '.turn_off', entidad: entidad } }; }]);
}
for (const [dicho, entidad, nombre] of ZONAS) {
  REGLAS_CASA.push([new RegExp('^(?:pon(?:me)?|sube|baja|deja|ajusta)(?: la)?(?: calefaccion)?(?: de| del| en)? (?:' + dicho + ') (?:a|en) (\\w+(?: y \\w+)?)(?: grados)?$'),
    function (m) {
      const n = numero(m[1]);
      if (n === null || n < GRADOS_MIN || n > GRADOS_MAX) return null;
      return { casa: { servicio: 'climate.set_temperature', entidad: entidad, datos: { temperature: n } },
        frase: nombre + ' a ' + n + ' grados, señor.' };
    }]);
}

/** Por la ruta del backend, que aplica la misma frontera que a Claude. Nunca lanza. */
async function ordenCasa(o) {
  const hecho = 'ordenar ' + o.casa.servicio + ' en ' + o.casa.entidad;
  try {
    const base = (process.env.LECTURA_URL || 'http://127.0.0.1:8080').replace(/\/+$/, '');
    const r = await fetch(base + '/telefono/casa', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', 'X-Auth-Token': process.env.LECTURA_TOKEN || '' },
      body: JSON.stringify(o.casa),
      signal: AbortSignal.timeout(8000),
    });
    const d = await r.json();
    if (d && d.ok) return { ok: true, frase: o.frase || 'Hecho, señor.', hecho: hecho };
    return { ok: false, frase: 'No se ha podido, señor: ' + String((d && (d.motivo || d.nota)) || 'la casa no contesta'), hecho: '' };
  } catch (e) {
    return { ok: false, frase: 'La casa no contesta, señor.', hecho: '' };
  }
}

const REGLAS = [
  // Encender y apagar
  [new RegExp('^(?:enciende(?:me)?|encender|prende|pon|ponme) ' + TELE + '$'), function () { return { accion: 'encender' }; }],
  [new RegExp('^(?:apaga(?:me)?|apagar|quita) ' + TELE + '$'), function () { return { accion: 'apagar' }; }],

  // El volumen
  [new RegExp('^(?:sube(?:me|le)?|subir)(?: un poco| un poquito)?(?: el)? (?:volumen|sonido)' + EN_TELE + '(?: un poco| un poquito)?$'), function () { return { accion: 'volumen_subir' }; }],
  [new RegExp('^(?:baja(?:me|le)?|bajar)(?: un poco| un poquito)?(?: el)? (?:volumen|sonido)' + EN_TELE + '(?: un poco| un poquito)?$'), function () { return { accion: 'volumen_bajar' }; }],
  [new RegExp('^(?:sube(?:me|le)?|subir) ' + TELE + '(?: un poco| un poquito)?$'), function () { return { accion: 'volumen_subir' }; }],
  [new RegExp('^(?:baja(?:me|le)?|bajar) ' + TELE + '(?: un poco| un poquito)?$'), function () { return { accion: 'volumen_bajar' }; }],
  [new RegExp('^(?:sube(?:me|le)?|subir)(?: el)?(?: (?:volumen|sonido))?' + EN_TELE + ' (\\w+)(?: puntos?| rayas?| niveles?)?$'), function (m) {
    const n = numero(m[1]);
    return n ? { accion: 'volumen_subir', valor: n } : null;
  }],
  [new RegExp('^(?:baja(?:me|le)?|bajar)(?: el)?(?: (?:volumen|sonido))?' + EN_TELE + ' (\\w+)(?: puntos?| rayas?| niveles?)?$'), function (m) {
    const n = numero(m[1]);
    return n ? { accion: 'volumen_bajar', valor: n } : null;
  }],
  [new RegExp('^(?:pon|ponme|deja|dejame|cambia|sube|baja)(?: el)? (?:volumen|sonido)' + EN_TELE + ' (?:a|al|en) (\\w+(?: y \\w+)?)$'), function (m) {
    const n = numero(m[1]);
    return n !== null ? { accion: 'volumen_poner', valor: n } : null;
  }],

  // El silencio
  [new RegExp('^(?:silencia(?:me)?|mutea|silenciar|pon en silencio|quita(?:me)? (?:el )?(?:sonido|volumen)' + EN_TELE + ')(?: ' + TELE + ')?$'), function () { return { accion: 'silenciar' }; }],
  [new RegExp('^(?:quita(?:le)?(?: el)? silencio|pon(?:le)?(?: el)? sonido|devuelvele el sonido)' + EN_TELE + '$'), function () { return { accion: 'quitar_silencio' }; }],

  // «Enciende la tele y pon Netflix»: abrir ya la enciende si hace falta.
  [new RegExp('^(?:enciende(?:me)?|prende|pon(?:me)?) ' + TELE + ' (?:y|e) (?:abre(?:me)?|pon(?:me)?|lanza|arranca|entra en)(?: (?:la )?(?:app|aplicacion)(?: de)?)? (' + APPS_VOZ + ')$'), function (m) { return { accion: 'abrir', valor: m[1] }; }],

  // Reproducción. «para» y «sigue» a secas son del lector: aquí necesitan objeto.
  [new RegExp('^(?:pausa|pausar|pausame|pon(?:me)? pausa|pon en pausa)(?: (?:a )?' + OBRA + ')?$'), function () { return { accion: 'pausa' }; }],
  [new RegExp('^(?:para|parame) ' + OBRA + '$'), function () { return { accion: 'pausa' }; }],
  [new RegExp('^(?:reanuda(?:me)?|reanudar|play|dale al play|dale a play|quita(?:le)? (?:la )?pausa)(?: (?:a )?' + OBRA + ')?$'), function () { return { accion: 'reproducir' }; }],
  [new RegExp('^(?:sigue con|continua con|continua|sigue|vuelve a poner) ' + OBRA + '$'), function () { return { accion: 'reproducir' }; }],

  // Aplicaciones
  [new RegExp('^(?:abre(?:me)?|abrir|pon(?:me)?|lanza|arranca|entra en)(?: (?:la )?(?:app|aplicacion)(?: de)?)? (' + APPS_VOZ + ')' + EN_TELE + '$'), function (m) { return { accion: 'abrir', valor: m[1] }; }],

  // Por dónde va
  [new RegExp('^(?:vuelve al inicio|ve al inicio|pulsa inicio)' + EN_TELE + '$'), function () { return { accion: 'inicio' }; }],
  [new RegExp('^(?:sube|siguiente|cambia(?: de)?)(?: el)? canal' + EN_TELE + '$'), function () { return { accion: 'canal_subir' }; }],
  [new RegExp('^(?:baja|anterior)(?: el)? canal' + EN_TELE + '$'), function () { return { accion: 'canal_bajar' }; }],
  [new RegExp('^(?:pon|ponme|cambia al|cambia a)(?: el)? canal (\\w+)' + EN_TELE + '$'), function (m) {
    const n = numero(m[1]);
    return n !== null ? { accion: 'canal', valor: n } : null;
  }],
];

function limpiar(texto) {
  let t = N(texto);
  let antes;
  do {
    antes = t;
    t = t.replace(DELANTE, '').replace(PETICION, '').replace(DETRAS, '').trim();
  } while (t !== antes);
  return t;
}

/** La orden que hay en lo dicho, o null si no es (del todo) una orden para la tele. */
function interpretar(texto) {
  const t = limpiar(texto);
  if (!t || t.length > 70) return null;
  for (const [patron, hacer] of REGLAS.concat(REGLAS_CASA)) {
    const m = patron.exec(t);
    if (m) {
      const o = hacer(m);
      if (o) return o;
    }
  }
  return null;
}

/**
 * Las órdenes que hay en lo dicho: una, o varias unidas por «y» («baja el volumen y abre
 * Jellyfin»; con Claude eran 11 s). Con el mismo criterio de frase entera: si UNA de las
 * partes no es una orden clara, no se hace ninguna y lo piensa Claude.
 */
function interpretarVarias(texto) {
  const una = interpretar(texto);
  if (una) return [una];
  const t = limpiar(texto);
  if (t.length > 120) return null;
  const partes = t.split(/ (?:y|e) (?:luego |despues |tambien )?|, (?:y )?/).filter(Boolean);
  if (partes.length < 2 || partes.length > 3) return null;
  const ordenes = partes.map(interpretar);
  return ordenes.every(Boolean) ? ordenes : null;
}

/**
 * Si lo dicho es un reflejo, lo cumple y lo dice. null si no lo era y debe pensarlo Claude.
 * @returns {Promise<null|{interrumpio: boolean, aviso: string}>}
 */
async function atender(transcript, p) {
  if (process.env.REFLEJOS === '0') return null;
  const ordenes = interpretarVarias(transcript);
  if (!ordenes) return null;
  const t0 = Date.now();
  const log = p.log || function () {};
  // Lo que se dice mientras la orden tarda (encender, el permiso en pantalla) va en fila
  // y sin solaparse: la respuesta espera a que acabe.
  let hablando = Promise.resolve();
  const avisar = function (frase) {
    hablando = hablando.then(async function () {
      const url = await p.ttsService.generateSpeech(frase, p.voiceId);
      if (p.sigueActiva()) await p.endpoint.play(url);
    }).catch(function () {});
  };
  const resultados = [];
  for (const o of ordenes) {
    const un = o.casa ? await ordenCasa(o) : await tele.orden(o, { avisar: avisar });
    resultados.push(un);
    if (!un.ok) break;   // lo siguiente solía depender de esto
  }
  await hablando;
  const r = {
    ok: resultados.every(function (x) { return x.ok; }),
    // «Volumen a 8. Jellyfin en pantalla, señor.»: el «señor», solo una vez.
    frase: resultados.map(function (x, i) {
      return i + 1 < resultados.length ? x.frase.replace(/, señor\.$/, '.') : x.frase;
    }).filter(function (f, i, todas) { return todas.indexOf(f) === i; }).join(' '),
    hecho: resultados.map(function (x) { return x.hecho; }).filter(Boolean).join(' y '),
  };
  log('REFLEJO ' + JSON.stringify(ordenes) + ' → ' + (r.ok ? 'hecho' : 'falló') + ' en ' + (Date.now() - t0) + ' ms: «' + r.frase + '»');
  let interrumpio = false;
  if (p.sigueActiva()) {
    const url = await p.ttsService.generateSpeech(r.frase, p.voiceId);
    interrumpio = await decirInterrumpible(p.endpoint, p.session, url, log);
  }
  // Para que Claude no se pierda: en su turno siguiente sabe qué se ha hecho sin él.
  const aviso = r.ok
    ? '[Mientras tanto, la llamada acaba de ' + r.hecho + ' sin pasar por ti, y ya se lo ha dicho.] '
    : '[Mikel ha pedido algo de la tele y ha fallado; ya se lo ha dicho: «' + r.frase + '».] ';
  return { interrumpio: interrumpio, aviso: aviso };
}

module.exports = { interpretar, interpretarVarias, atender, limpiar, numero };
