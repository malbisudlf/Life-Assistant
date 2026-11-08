/**
 * Parche 34: la tele de la sala (Samsung Q70 de 65", Tizen, 2020), en local y sin nube.
 * Ver «El parche 34» en telefono/PARCHES.md de Life Assistant.
 *
 * Vive en la voice-app y no en el backend por dos motivos: la voice-app está en la red
 * del host, que es la única desde la que el paquete mágico de encender llega a la LAN
 * (desde la red de Docker no sale un broadcast), y así una orden de viva voz tarda
 * milisegundos, sin pasar por Claude (reflejos.js). El backend llega por `POST /api/tele`.
 *
 * Tres puertas de la tele, cada una para lo suyo:
 *  - WebSocket 8002: las teclas del mando. La PRIMERA vez la tele pregunta en pantalla si
 *    deja entrar a «Jarvis» y hay que aceptar con el mando; el token que da entonces se
 *    guarda en config/ y no vuelve a preguntar.
 *  - UPnP 9197: leer el volumen y el silencio (poner, esta tele no deja). No pide emparejar.
 *  - REST 8001: si está encendida, y las aplicaciones. Una vez emparejada, POST abre una
 *    aplicación (la enciende si está en reposo) y GET dice si está en pantalla. La orden
 *    por WebSocket (`ed.apps.launch`) esta tele la ignora, y `ed.installedApp.get` no lo
 *    contesta (comprobado el 2026-11-04): la lista sale de preguntar por las conocidas.
 */

const fs = require('fs');
const path = require('path');
const http = require('http');
const dgram = require('dgram');
const WebSocket = require('ws');

const IP  = process.env.TELE_IP || '';
const MAC = process.env.TELE_MAC || '';
const NOMBRE = Buffer.from(process.env.TELE_NOMBRE || 'Jarvis').toString('base64');
const FICHERO_TOKEN = process.env.TELE_TOKEN_FICHERO || path.join(__dirname, '..', 'config', 'tele-token.json');
const ESPERA_PERMISO_MS = parseInt(process.env.TELE_ESPERA_PERMISO_MS || '30000', 10);
const VOLUMEN_MAX = parseInt(process.env.TELE_VOLUMEN_MAX || '60', 10);
const PASO_VOLUMEN = parseInt(process.env.TELE_PASO_VOLUMEN || '3', 10);
const INACTIVA_MS = 60 * 1000;

// Las teclas que se pueden pedir por su nombre
const TECLAS = {
  pausa: 'KEY_PAUSE', reproducir: 'KEY_PLAY', parar: 'KEY_STOP',
  adelantar: 'KEY_FF', retroceder: 'KEY_REWIND',
  arriba: 'KEY_UP', abajo: 'KEY_DOWN', izquierda: 'KEY_LEFT', derecha: 'KEY_RIGHT',
  ok: 'KEY_ENTER', atras: 'KEY_RETURN', salir: 'KEY_EXIT', inicio: 'KEY_HOME', menu: 'KEY_MENU',
  canal_subir: 'KEY_CHUP', canal_bajar: 'KEY_CHDOWN', fuente: 'KEY_SOURCE',
  hdmi: 'KEY_HDMI', hdmi1: 'KEY_HDMI1', hdmi2: 'KEY_HDMI2', hdmi3: 'KEY_HDMI3', hdmi4: 'KEY_HDMI4',
  guia: 'KEY_GUIDE', info: 'KEY_INFO',
};

// Por si la tele no da la lista de lo instalado. Se usa la de la tele si la hay.
const APPS_CONOCIDAS = {
  netflix: '3201907018807', youtube: '111299001912', 'prime video': '3201910019365',
  'disney+': '3201901017640', max: '3201601007230', 'apple tv': '3201807016597',
  spotify: '3201606009684', dazn: '3201806016381', plex: '3201512006963',
  jellyfin: 'AprZAARz4r.Jellyfin', 'movistar plus+': '3201707014489', twitch: '3202203026841',
  tiktok: '3202008021577', filmin: '3201703012079', rtve: '3201909019175', atresplayer: '3201710014981',
  mitele: '3201710015037', pluto: '3201808016802', 'samsung tv plus': '3201707014361',
  // Parche 40: la app «Jarvis» de Life Assistant (tele/tablero-tizen/), que abre el tablero.
  // La tele ignora «abre esta URL», pero obedece «abre esta app»: por eso es una app.
  jarvis: 'JarvisTabl.Tablero',
};
// Lo que se dice → el nombre con el que se busca
const ALIAS = {
  hbo: 'max', 'hbo max': 'max', disney: 'disney+', 'disney plus': 'disney+',
  prime: 'prime video', amazon: 'prime video', 'amazon prime': 'prime video',
  apple: 'apple tv', 'apple tv plus': 'apple tv', movistar: 'movistar plus+', 'movistar plus': 'movistar plus+',
  'you tube': 'youtube', yutub: 'youtube',
  tablero: 'jarvis', 'el tablero': 'jarvis', dashboard: 'jarvis', 'el dashboard': 'jarvis', panel: 'jarvis', 'el panel': 'jarvis',
};

function normalizar(s) {
  return String(s || '').normalize('NFD').replace(/[̀-ͯ]/g, '').toLowerCase()
    .replace(/[^a-z0-9+ ]/g, ' ').replace(/\s+/g, ' ').trim();
}

function dormir(ms) { return new Promise(function (r) { setTimeout(r, ms); }); }

// ── El token ────────────────────────────────────────────────────────────────────────

function leerToken() {
  if (process.env.TELE_TOKEN) return process.env.TELE_TOKEN;
  try { return JSON.parse(fs.readFileSync(FICHERO_TOKEN, 'utf8')).token || ''; } catch (e) { return ''; }
}

function guardarToken(token) {
  try {
    fs.writeFileSync(FICHERO_TOKEN, JSON.stringify({ token: String(token) }), { mode: 0o600 });
  } catch (e) {
    console.warn('[TELE] No se pudo guardar el token: ' + e.message);
  }
}

function emparejada() { return !!leerToken(); }

// ── REST: cómo está ─────────────────────────────────────────────────────────────────

function pedirHttp(opciones, cuerpo, msTope) {
  return new Promise(function (resolve, reject) {
    // Parche 42: una conexión por petición (`agent: false`). Node 20 reutiliza la conexión
    // (keep-alive) y esta tele la cierra al contestar: la petición siguiente moría al instante
    // con «socket hang up», una de cada dos (medido el 2026-11-08). De ahí las listas de apps
    // a medias y el «no encuentro el tablero».
    const r = http.request(Object.assign({ host: IP, agent: false }, opciones), function (res) {
      let d = '';
      res.setEncoding('utf8');
      res.on('data', function (t) { d += t; });
      res.on('end', function () { resolve({ status: res.statusCode, cuerpo: d }); });
    });
    r.setTimeout(msTope, function () { r.destroy(new Error('sin respuesta en ' + msTope + ' ms')); });
    r.on('error', reject);
    if (cuerpo) r.write(cuerpo);
    r.end();
  });
}

/** 'on' | 'standby' | 'apagada' (apagada = ni contesta). Nunca lanza. */
async function estado(msTope) {
  try {
    const r = await pedirHttp({ port: 8001, path: '/api/v2/', method: 'GET' }, null, msTope || 2500);
    const d = JSON.parse(r.cuerpo);
    const p = String((d.device && d.device.PowerState) || 'on').toLowerCase();
    return p === 'on' ? 'on' : 'standby';
  } catch (e) {
    return 'apagada';
  }
}

/**
 * El estado sin los engaños del momento. `standby` NO es apagada: es un paso de unos segundos
 * al apagarse o encenderse (medido el 2026-11-04: on → standby a los 3 s → sin conexión a los
 * 12 s). Creérselo hizo contestar «ya está apagada» con la tele encendida, sin pulsar nada. Y
 * un tiempo agotado suelto tampoco dice nada: pasa con la tele encendida. Así que:
 * 'on' vale a la primera, 'apagada' con dos seguidas, y 'standby' solo si sigue pasados `ms`.
 */
async function estadoFirme(ms) {
  const hasta = Date.now() + (ms || 15000);
  let fallos = 0;
  for (;;) {
    const e = await estado(1500);
    if (e === 'on') return 'on';
    fallos = e === 'apagada' ? fallos + 1 : 0;
    if (fallos >= 2) return 'apagada';
    if (Date.now() >= hasta) return e;
    await dormir(400);
  }
}

// ── UPnP: el volumen ────────────────────────────────────────────────────────────────

const RC = 'urn:schemas-upnp-org:service:RenderingControl:1';

async function soap(accion, dentro) {
  const cuerpo = '<?xml version="1.0" encoding="utf-8"?><s:Envelope xmlns:s="http://schemas.xmlsoap.org/soap/envelope/" ' +
    's:encodingStyle="http://schemas.xmlsoap.org/soap/encoding/"><s:Body><u:' + accion + ' xmlns:u="' + RC + '">' +
    '<InstanceID>0</InstanceID><Channel>Master</Channel>' + dentro + '</u:' + accion + '></s:Body></s:Envelope>';
  const r = await pedirHttp({
    port: 9197, path: '/upnp/control/RenderingControl1', method: 'POST',
    headers: { 'Content-Type': 'text/xml; charset="utf-8"', SOAPAction: '"' + RC + '#' + accion + '"', 'Content-Length': Buffer.byteLength(cuerpo) },
  }, cuerpo, 2500);
  if (r.status !== 200) throw new Error('UPnP ' + accion + ' devolvió ' + r.status);
  return r.cuerpo;
}

async function leerVolumen() {
  const m = /<CurrentVolume>(\d+)<\/CurrentVolume>/.exec(await soap('GetVolume', ''));
  if (!m) throw new Error('la tele no dice el volumen');
  return parseInt(m[1], 10);
}

async function ponerVolumen(n) {
  await soap('SetVolume', '<DesiredVolume>' + n + '</DesiredVolume>');
  return leerVolumen();
}

async function leerSilencio() {
  const m = /<CurrentMute>(\d)<\/CurrentMute>/.exec(await soap('GetMute', ''));
  return !!(m && m[1] === '1');
}

// ── WebSocket: el mando y las aplicaciones ──────────────────────────────────────────

let canal = null;       // { ws, listo: Promise }
let apagarCanal = null;
let appsCache = null;   // { hasta, lista: [{id, nombre, tipo}] }

class SinPermiso extends Error {}

function cerrarCanal() {
  if (canal && canal.ws) { try { canal.ws.terminate(); } catch (e) { /* ya cerrado */ } }
  canal = null;
}

function abrirCanal(alPedirPermiso) {
  if (canal) {
    clearTimeout(apagarCanal);
    apagarCanal = setTimeout(cerrarCanal, INACTIVA_MS);
    return canal.listo;
  }
  const token = leerToken();
  const url = 'wss://' + IP + ':8002/api/v2/channels/samsung.remote.control?name=' + NOMBRE +
    (token ? '&token=' + encodeURIComponent(token) : '');
  const ws = new WebSocket(url, { rejectUnauthorized: false, handshakeTimeout: 5000 });
  const este = { ws: ws };
  canal = este;
  este.listo = new Promise(function (resolve, reject) {
    // Sin token la tele se queda callada hasta que aceptan en pantalla: se avisa una vez.
    const espera = token ? 6000 : ESPERA_PERMISO_MS;
    const reloj = setTimeout(function () {
      cerrarCanal();
      reject(token ? new Error('la tele no contesta') : new SinPermiso('nadie ha aceptado en la pantalla'));
    }, espera);
    ws.on('open', function () { if (!token && alPedirPermiso) alPedirPermiso(); });
    ws.on('message', function (datos) {
      let m;
      try { m = JSON.parse(datos.toString()); } catch (e) { return; }
      if (m.event === 'ms.channel.connect') {
        clearTimeout(reloj);
        const nuevo = m.data && m.data.token;
        if (nuevo && String(nuevo) !== token) {
          guardarToken(nuevo);
          console.log('[TELE] Emparejada: token guardado');
        }
        resolve(ws);
      } else if (m.event === 'ms.channel.unauthorized') {
        clearTimeout(reloj);
        if (canal === este) canal = null;
        reject(new SinPermiso('la tele ha rechazado a Jarvis'));
      }
    });
    ws.on('error', function (e) {
      clearTimeout(reloj);
      if (canal === este) canal = null;
      reject(e);
    });
    ws.on('close', function () {
      clearTimeout(reloj);
      if (canal === este) canal = null;
      reject(new Error('la tele ha cerrado la conexión'));
    });
  });
  este.listo.catch(function () {});
  clearTimeout(apagarCanal);
  apagarCanal = setTimeout(cerrarCanal, INACTIVA_MS);
  return este.listo;
}

async function tecla(nombre, veces, alPedirPermiso, tipo) {
  const ws = await abrirCanal(alPedirPermiso);
  for (let i = 0; i < (veces || 1); i++) {
    ws.send(JSON.stringify({
      method: 'ms.remote.control',
      params: { Cmd: tipo || 'Click', DataOfCmd: nombre, Option: 'false', TypeOfRemote: 'SendRemoteKey' },
    }));
    if (i + 1 < (veces || 1)) await dormir(130);
  }
}

/** Lo que dice la tele de una aplicación ({name, running, visible}), o null si no la tiene. */
async function estadoApp(id, msTope) {
  try {
    const r = await pedirHttp({ port: 8001, path: '/api/v2/applications/' + encodeURIComponent(id), method: 'GET' }, null, msTope || 2500);
    return r.status === 200 ? JSON.parse(r.cuerpo) : null;
  } catch (e) {
    return null;
  }
}

/** Las conocidas que la tele dice tener. Solo responde con el token puesto (emparejada). */
async function apps() {
  if (appsCache && appsCache.hasta > Date.now()) return appsCache.lista;
  const ids = Object.values(APPS_CONOCIDAS);
  const datos = await Promise.all(ids.map(function (id) { return estadoApp(id); }));
  const lista = [];
  datos.forEach(function (d, i) {
    if (d && d.name) lista.push({ id: ids[i], nombre: d.name, tipo: 2 });
  });
  if (lista.length) appsCache = { hasta: Date.now() + 10 * 60 * 1000, lista: lista };
  return lista;
}

/**
 * Parche 41: una app conocida que no salió en la lista se pregunta sola, con más tiempo.
 * La lista se hace preguntando por todas a la vez y esta tele, con veinte peticiones juntas,
 * deja algunas sin contestar a tiempo: el 2026-11-08 salieron 5 de 8 (faltaban Netflix,
 * Jellyfin y el tablero) y la lista se guardaba diez minutos así. Si la encuentra, la lista se
 * tira para que la próxima vez se vuelva a hacer.
 */
async function appConocidaSuelta(dicho) {
  const q = normalizar(dicho);
  const id = APPS_CONOCIDAS[ALIAS[q] || q];
  if (!id) return null;
  const d = await estadoApp(id, 6000);
  if (!d || !d.name) return null;
  appsCache = null;
  return { id: id, nombre: d.name, tipo: 2 };
}

/** Busca una aplicación por lo que se ha dicho. null si no hay ninguna que se parezca. */
function buscarApp(lista, dicho) {
  let q = normalizar(dicho);
  q = ALIAS[q] || q;
  if (q === 'max' && lista.some(function (a) { return normalizar(a.nombre) === 'hbo max'; })) q = 'hbo max';
  const instaladas = lista.map(function (a) { return Object.assign({}, a, { n: normalizar(a.nombre) }); });
  const exacta = instaladas.find(function (a) { return a.n === q; });
  if (exacta) return exacta;
  const empieza = instaladas.find(function (a) { return a.n.startsWith(q) || q.startsWith(a.n); });
  if (empieza) return empieza;
  const contiene = instaladas.find(function (a) { return a.n.includes(q); });
  if (contiene) return contiene;
  if (instaladas.length) return null;
  // Sin lista de la tele, las de siempre.
  const id = APPS_CONOCIDAS[q];
  return id ? { id: id, nombre: dicho, tipo: 2 } : null;
}

/** Si lo que se ha dicho es el nombre de una aplicación que conocemos, sin tocar la tele. */
function esAppConocida(dicho) {
  const q = normalizar(dicho);
  const clave = ALIAS[q] || q;
  if (APPS_CONOCIDAS[clave]) return true;
  return !!(appsCache && buscarApp(appsCache.lista, dicho));
}

/**
 * Abre la aplicación y COMPRUEBA que ha salido en pantalla: true solo si la tele lo dice.
 * Si está en reposo, el POST la enciende; entonces tarda unos segundos en contestar.
 */
async function lanzarApp(app, msTope) {
  const hasta = Date.now() + (msTope || 12000);
  let abierta = false;
  while (Date.now() < hasta) {
    if (!abierta) {
      try {
        const r = await pedirHttp({ port: 8001, path: '/api/v2/applications/' + encodeURIComponent(app.id), method: 'POST' }, null, 3000);
        abierta = r.status < 300;
      } catch (e) { /* despertándose: se reintenta */ }
    }
    if (abierta) {
      const d = await estadoApp(app.id, 1500);
      if (d && d.visible) return true;
    }
    await dormir(700);
  }
  return false;
}

/**
 * Deja el volumen en `n` y devuelve en cuánto ha quedado. Esta tele deja LEERLO por UPnP,
 * pero SetVolume contesta 501 (comprobado el 2026-11-04): se intenta por si otra lo admite,
 * y si no, se pulsa la tecla las veces que falten.
 */
async function llevarVolumen(n, alPedirPermiso) {
  try {
    return await ponerVolumen(n);
  } catch (e) { /* a las teclas */ }
  const antes = await leerVolumen();
  const falta = n - antes;
  if (falta !== 0) await tecla(falta > 0 ? 'KEY_VOLUP' : 'KEY_VOLDOWN', Math.abs(falta), alPedirPermiso);
  await dormir(300);
  return leerVolumen();
}

// ── Encender y apagar ───────────────────────────────────────────────────────────────

function paqueteMagico() {
  const mac = Buffer.from(MAC.replace(/[^0-9a-f]/gi, ''), 'hex');
  const paquete = Buffer.alloc(102, 0xff);
  for (let i = 0; i < 16; i++) mac.copy(paquete, 6 + i * 6);
  return paquete;
}

function mandarWol() {
  return new Promise(function (resolve) {
    const s = dgram.createSocket('udp4');
    const destinos = [process.env.TELE_BROADCAST || IP.replace(/\.\d+$/, '.255'), '255.255.255.255', IP];
    s.on('error', function () { try { s.close(); } catch (e) { /* ya cerrado */ } resolve(); });
    s.bind(function () {
      s.setBroadcast(true);
      const p = paqueteMagico();
      let faltan = destinos.length * 2;
      destinos.forEach(function (d) {
        [9, 7].forEach(function (puerto) {
          s.send(p, puerto, d, function () {
            if (--faltan === 0) { try { s.close(); } catch (e) { /* ya cerrado */ } resolve(); }
          });
        });
      });
    });
  });
}

async function esperarEstado(buscado, ms) {
  const hasta = Date.now() + ms;
  while (Date.now() < hasta) {
    if ((await estado(1500)) === buscado) return true;
    await dormir(500);
  }
  return false;
}

async function encender(alPedirPermiso) {
  const antes = await estadoFirme(6000);
  if (antes === 'on') return true;
  cerrarCanal();
  // En reposo contesta y la tecla la despierta; apagada del todo, solo el paquete mágico.
  if (antes === 'standby') {
    try { await tecla('KEY_POWER', 1, alPedirPermiso); } catch (e) { /* queda el paquete */ }
    if (await esperarEstado('on', 5000)) return true;
  }
  await mandarWol();
  if (await esperarEstado('on', 8000)) return true;
  await mandarWol();
  return esperarEstado('on', 6000);
}

/** `desde` es el estado firme: 'on', o 'standby' si la tele se ha quedado en ese paso. */
async function apagar(alPedirPermiso, desde) {
  await tecla('KEY_POWER', 1, alPedirPermiso);
  if (desde !== 'on') {
    // Pulsada a ciegas: solo vale ver que deja de contestar. Si no, quizá la haya encendido.
    const hecho = (await estadoFirme(15000)) === 'apagada';
    cerrarCanal();
    return hecho;
  }
  if (await esperarNoOn(6000)) { cerrarCanal(); return true; }
  // Algunas Samsung solo se apagan del todo con la tecla mantenida.
  try {
    await tecla('KEY_POWER', 1, alPedirPermiso, 'Press');
    await dormir(3000);
    await tecla('KEY_POWER', 1, alPedirPermiso, 'Release');
  } catch (e) { /* lo dirá el estado */ }
  const hecho = await esperarNoOn(3000);
  cerrarCanal();
  return hecho;
}

// Dos lecturas seguidas: una sola puede ser un tiempo agotado con la tele encendida.
async function esperarNoOn(ms) {
  const hasta = Date.now() + ms;
  let seguidas = 0;
  while (Date.now() < hasta) {
    seguidas = (await estado(1500)) !== 'on' ? seguidas + 1 : 0;
    if (seguidas >= 2) return true;
    await dormir(400);
  }
  return false;
}

// ── La orden ────────────────────────────────────────────────────────────────────────

const AVISO_PERMISO = 'La tele me pide permiso, señor. Acéptelo en la pantalla con el mando.';
const FRASE_SIN_PERMISO = 'Nadie ha aceptado en la pantalla de la tele, señor. Sin eso no puedo manejarla.';
const FRASE_NO_RESPONDE = 'La tele no responde, señor.';

/**
 * Cumple una orden. Nunca lanza.
 * @param {{accion: string, valor: (string|number|undefined)}} o
 * @param {{avisar: Function}} [p] avisar(frase): para decir algo si va a tardar
 * @returns {Promise<{ok: boolean, frase: string, hecho: string, estado: (string|undefined)}>}
 */
async function orden(o, p) {
  const accion = String((o && o.accion) || '').trim().toLowerCase();
  const valor = o ? o.valor : undefined;
  const avisar = (p && p.avisar) || function () {};
  let avisado = false;
  const pedirPermiso = function () {
    if (avisado) return;
    avisado = true;
    try { avisar(AVISO_PERMISO); } catch (e) { /* no puede tumbar la orden */ }
  };
  const bien = function (frase, hecho, extra) { return Object.assign({ ok: true, frase: frase, hecho: hecho }, extra || {}); };
  const mal = function (frase) { return { ok: false, frase: frase, hecho: '' }; };
  if (!IP) return mal('La tele no está configurada, señor: falta TELE_IP.');

  try {
    if (accion === 'estado') {
      const e = await estadoFirme(15000);
      const extra = { estado: e };
      if (e === 'on') {
        try {
          extra.volumen = await leerVolumen();
          extra.silencio = await leerSilencio();
        } catch (err) { /* lo principal es si está encendida */ }
        return bien('La tele está encendida, señor' + (extra.volumen !== undefined ? ', con el volumen a ' + extra.volumen : '') + '.', 'mirar la tele', extra);
      }
      return bien('La tele está apagada, señor.', 'mirar la tele', extra);
    }

    if (accion === 'encender') {
      if ((await estadoFirme(6000)) === 'on') return bien('Ya está encendida, señor.', 'comprobar que la tele está encendida');
      avisar('Encendiendo la tele, señor.');
      const r = await encender(pedirPermiso);
      return r ? bien('Encendida, señor.', 'encender la tele') : mal('La tele no se ha encendido, señor. Puede que tenga desactivado el encendido por red.');
    }

    if (accion === 'apagar') {
      const ahora = await estadoFirme(15000);
      if (ahora === 'apagada') return bien('Ya está apagada, señor.', 'comprobar que la tele está apagada');
      const r = await apagar(pedirPermiso, ahora);
      return r ? bien('Apagada, señor.', 'apagar la tele') : mal('La tele sigue encendida, señor. No me ha hecho caso.');
    }

    if (accion === 'volumen_subir' || accion === 'volumen_bajar') {
      const paso = Math.max(1, Math.min(30, parseInt(valor, 10) || PASO_VOLUMEN));
      const signo = accion === 'volumen_subir' ? 1 : -1;
      let antes = null;
      try { antes = await leerVolumen(); } catch (e) { /* sin saberlo, se pulsa igual */ }
      if (antes === null) {
        await tecla(signo > 0 ? 'KEY_VOLUP' : 'KEY_VOLDOWN', paso, pedirPermiso);
        return bien('Hecho, señor.', (signo > 0 ? 'subir' : 'bajar') + ' el volumen de la tele');
      }
      const queda = await llevarVolumen(Math.max(0, Math.min(VOLUMEN_MAX, antes + signo * paso)), pedirPermiso);
      return bien('Volumen a ' + queda + ', señor.', 'poner el volumen de la tele a ' + queda, { volumen: queda });
    }

    if (accion === 'volumen_poner') {
      const n = parseInt(valor, 10);
      if (!Number.isFinite(n) || n < 0 || n > 100) return mal('¿A cuánto lo pongo, señor? Del cero al cien.');
      if (n > VOLUMEN_MAX) return mal('Por encima de ' + VOLUMEN_MAX + ' no lo pongo a ciegas, señor. Se oiría en toda la casa.');
      const queda = await llevarVolumen(n, pedirPermiso);
      return bien('Volumen a ' + queda + ', señor.', 'poner el volumen de la tele a ' + queda, { volumen: queda });
    }

    if (accion === 'silenciar' || accion === 'quitar_silencio') {
      const quiere = accion === 'silenciar';
      let ahora = null;
      try { ahora = await leerSilencio(); } catch (e) { /* entonces, la tecla */ }
      if (ahora !== quiere) {
        try {
          await soap('SetMute', '<DesiredMute>' + (quiere ? 1 : 0) + '</DesiredMute>');
        } catch (e) {
          await tecla('KEY_MUTE', 1, pedirPermiso);
        }
      }
      return bien(quiere ? 'Silenciada, señor.' : 'Con sonido, señor.', quiere ? 'silenciar la tele' : 'devolverle el sonido a la tele');
    }

    if (accion === 'abrir') {
      const dicho = String(valor || '').trim();
      if (!dicho) return mal('¿Qué aplicación abro, señor?');
      if (!emparejada()) {
        // Sin token la tele no deja abrir nada: esto saca el permiso en pantalla.
        await abrirCanal(pedirPermiso);
      }
      const e = await estadoFirme(4000);
      if (e === 'apagada') {
        avisar('Enciendo la tele, señor, y abro ' + dicho + '.');
        if (!(await encender(pedirPermiso))) return mal('La tele no se ha encendido, señor.');
      } else if (e === 'standby') {
        avisar('Enciendo la tele, señor, y abro ' + dicho + '.');
      }
      let app = buscarApp(await apps(), dicho);
      if (!app) app = await appConocidaSuelta(dicho);
      if (!app) return mal('No encuentro ' + dicho + ' en la tele, señor.');
      const nombre = String(app.nombre || dicho).split(' - ')[0];
      if (await lanzarApp(app)) return bien(nombre + ' en pantalla, señor.', 'abrir ' + nombre + ' en la tele', { visible: true });
      return mal('He pedido abrir ' + nombre + ', señor, pero la tele no me confirma que esté en pantalla.');
    }

    if (accion === 'apps') {
      const lista = await apps();
      return bien('Tiene ' + lista.length + ' aplicaciones instaladas, señor.', 'mirar las aplicaciones de la tele',
        { apps: lista.map(function (a) { return a.nombre; }) });
    }

    if (accion === 'canal') {
      const n = String(parseInt(valor, 10));
      if (n === 'NaN') return mal('¿Qué canal, señor?');
      for (const c of n) { await tecla('KEY_' + c, 1, pedirPermiso); await dormir(150); }
      await tecla('KEY_ENTER', 1, pedirPermiso);
      return bien('Canal ' + n + ', señor.', 'poner el canal ' + n);
    }

    if (accion === 'tecla') {
      const k = String(valor || '').trim().toUpperCase();
      if (!/^KEY_[A-Z0-9_]+$/.test(k)) return mal('Esa tecla no la conozco, señor.');
      await tecla(k, 1, pedirPermiso);
      return bien('Hecho, señor.', 'pulsar ' + k + ' en la tele');
    }

    if (TECLAS[accion]) {
      const veces = Math.max(1, Math.min(10, parseInt(valor, 10) || 1));
      await tecla(TECLAS[accion], veces, pedirPermiso);
      return bien('Hecho, señor.', accion.replace('_', ' ') + ' en la tele');
    }

    return mal('Eso no sé hacerlo con la tele, señor.');
  } catch (e) {
    console.warn('[TELE] ' + accion + ': ' + e.message);
    if (e instanceof SinPermiso) return mal(FRASE_SIN_PERMISO);
    return mal(FRASE_NO_RESPONDE);
  }
}

module.exports = {
  orden, estado, emparejada, buscarApp, esAppConocida, normalizar, leerVolumen,
  TECLAS, VOLUMEN_MAX, AVISO_PERMISO,
};
