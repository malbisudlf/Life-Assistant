/**
 * Parche 53: la llamada a tres. Ver telefono/PARCHES.md y docs/LLAMADAS_TERCEROS.md en
 * Life Assistant.
 *
 * Mikel está hablando con Jarvis por teléfono (el modo coche, o una llamada cualquiera) y
 * dice «Jarvis, ponme con Erik». Jarvis llama a Erik por la línea fija de O2 y, cuando
 * descuelga, los dos quedan en una conferencia de FreeSWITCH con Jarvis dentro: Mikel y
 * Erik hablan entre ellos, Jarvis calla, y «Jarvis, ¿tengo libre el jueves?» lo contesta
 * para los dos. Al colgar, el backend resume la conversación y, si quedaron en firme día
 * y hora, deja el botón para apuntarlo.
 *
 * Lo que sostiene todo, y no se toca sin pensarlo:
 *
 *  - **Solo despierta la voz de Mikel.** La escucha pasiva sigue oyendo SOLO su pata (el
 *    fork de su endpoint, `mixType: 'mono'`, es lo que dice él). Lo que dice Erik entra
 *    por OTRO fork, el de la pata de Erik, y nunca busca el nombre: «Jarvis, abre la
 *    puerta» dicho por Erik no despierta a nadie. No hace falta huella de voz: separa el
 *    canal.
 *  - **Lo que dice Erik no llega al Claude con shell.** Se transcribe para el resumen y la
 *    cita, que piensa en el backend un modelo sin herramientas (como en las llamadas a
 *    terceros), y para «Jarvis, apunta eso», que va al backend sin pasar por Claude. A
 *    Claude solo le llega lo que pide Mikel, con un aviso de que le oyen los dos.
 *  - **Solo a quien Mikel ha nombrado.** Claude pone `📞 A TRES: <nombre>`; el backend
 *    busca el nombre en los contactos (las reglas de siempre: solo contactos, solo
 *    números de persona en España) y además exige que el nombre salga en lo que Mikel
 *    acaba de decir. Una marca colada por un dato no llama a nadie.
 *
 * Cómo suena: Jarvis habla para los dos (play de conferencia). La música de espera no
 * entra en la conferencia, y la de Spotify del modo coche tampoco (musica.js). Mientras
 * suena el teléfono de Erik, Mikel oye el tono de llamada.
 *
 * Probado sin teléfonos en el FreeSWITCH de caja el 2026-11-21: el perfil `sla` (16 kHz,
 * sin controles por teclado ni sonidos de entrada), reproducir a todos con su
 * `play-file-done`, parar a mitad, mp3 por shout:// y http://, y sacar una pata con
 * `kick` sin que cuelgue (sigue viva y reproduce). Reproducir a UN miembro no se pudo
 * probar sin RTP de verdad (el fichero no avanza), y por eso aquí no se usa.
 */
'use strict';

const MARCA = /📞\s*A\s*TRES:\s*([^\n]{1,80})/i;
const PERFIL = 'sla';
// Lo que suena mientras llama: el tono de llamada español (425 Hz, 1,5 s sí y 3 s no).
const TONO = 'tone_stream://L=40;%(1500,3000,425)';
const RE_MUSICA = /\/static\/hold-music\.wav$/;

function entero(nombre, porDefecto) {
  const n = parseInt(process.env[nombre], 10);
  return Number.isFinite(n) && n > 0 ? n : porDefecto;
}

const TIMBRE_S = () => entero('A_TRES_TIMBRE_S', 30);
const TOPE_MIN = () => entero('A_TRES_MAX_MIN', 120);
// Lo más que se espera a que acabe una frase en la conferencia (si se pierde el evento).
const PLAY_TOPE_MS = 120000;
const JOIN_TOPE_MS = 8000;
const TURNOS_MAX = 400;

const FRASES = {
  sinLinea:  'La línea fija no está lista, señor.',
  fallo:     'No he podido hacer la llamada, señor.',
  yaEnUna:   'Ya estamos en una llamada a tres, señor.',
  noCoge:    function (n) { return n + ' no lo coge, señor.'; },
  comunica:  function (n) { return n + ' comunica, señor.'; },
  haColgado: function (n) { return n + ' ha colgado, señor. Sigo a la escucha.'; },
  colgado:   'Colgado, señor. Sigo a la escucha.',
  solos:     'Les dejo solos, señor.',
  soloNombre: 'En la llamada a tres solo le escucho cuando me nombra, señor.',
  tope:      'Llevamos mucho rato, señor. Cuelgo la llamada a tres.'
};

let deps = { srf: null, mediaServer: null, lineaO2: null, marcar: null };

/** index.js: lo que hace falta para marcar. Valen valores o funciones que los devuelven. */
function configurar(d) {
  deps = Object.assign({}, deps, d || {});
}

function dep(nombre) {
  const v = deps[nombre];
  return typeof v === 'function' && nombre !== 'marcar' ? v() : v;
}

function marcador() {
  return deps.marcar || require('./outbound-handler').initiateOutboundCall;
}

function noop() {}

function cuerpoDe(r) {
  return String((r && r.body) || r || '').trim();
}

/** El nombre de `📞 A TRES: <nombre>` en la respuesta de Claude, o null. */
function pideATres(respuesta) {
  const m = MARCA.exec(String(respuesta || ''));
  if (!m) return null;
  const nombre = m[1].replace(/[«»"`*]/g, '').replace(/\s+/g, ' ').trim();
  return nombre.length >= 2 ? nombre.slice(0, 60) : null;
}

/**
 * Lo que la conversación usa como endpoint. Fuera de la conferencia es el endpoint tal
 * cual; dentro, `play` suena para todos (y espera a que acabe), `uuid_break` para lo que
 * esté sonando y la música de espera no suena. Lo demás pasa al endpoint de verdad.
 */
class Salida {
  constructor(endpoint, log) {
    this.ep = endpoint;
    this.log = log || noop;
    this.conf = null;
    this._esperas = new Set();
  }

  get uuid() { return this.ep.uuid; }
  get local() { return this.ep.local; }
  get enConferencia() { return Boolean(this.conf); }

  on() { return this.ep.on.apply(this.ep, arguments); }
  off() { return this.ep.off.apply(this.ep, arguments); }
  removeListener() { return this.ep.removeListener.apply(this.ep, arguments); }
  forkAudioStart() { return this.ep.forkAudioStart.apply(this.ep, arguments); }
  forkAudioStop() { return this.ep.forkAudioStop.apply(this.ep, arguments); }
  set() { return this.ep.set.apply(this.ep, arguments); }
  modify() { return this.ep.modify.apply(this.ep, arguments); }
  destroy() { return this.ep.destroy.apply(this.ep, arguments); }

  api(comando, args) {
    if (this.conf && comando === 'uuid_break') return this.parar();
    return this.ep.api(comando, args);
  }

  play(url) {
    if (!this.conf) return this.ep.play(url);
    if (RE_MUSICA.test(String(url))) return Promise.resolve();
    return this._aTodos(String(url));
  }

  entrar(conf) {
    this.conf = conf;
  }

  /** Fuera de la conferencia: lo que esperaba a que acabase una frase deja de esperar. */
  salir() {
    this.conf = null;
    for (const fin of this._esperas) fin();
    this._esperas.clear();
  }

  async parar() {
    const conf = this.conf;
    if (!conf) return;
    try { await this.ep.api('conference', conf.name + ' stop all'); } catch (e) { /* nada sonaba */ }
  }

  async _aTodos(url) {
    const conf = this.conf;
    let fin;
    const hecho = new Promise(function (r) { fin = r; });
    const alAcabar = function (evt) {
      if (evt && typeof evt.getHeader === 'function' && evt.getHeader('File') === url) fin();
    };
    conf.on('playFileDone', alAcabar);
    this._esperas.add(fin);
    const tope = setTimeout(fin, PLAY_TOPE_MS);
    try {
      const r = await this.ep.api('conference', conf.name + ' play ' + url);
      if (!/^\+OK/.test(cuerpoDe(r))) {
        this.log('A-TRES: la conferencia no reproduce (' + cuerpoDe(r).slice(0, 80) + ')');
        fin();
      }
      await hecho;
    } finally {
      clearTimeout(tope);
      conf.removeListener('playFileDone', alAcabar);
      this._esperas.delete(fin);
    }
  }
}

function envolver(endpoint, log) {
  return endpoint instanceof Salida ? endpoint : new Salida(endpoint, log);
}

function urlBase() {
  return String(process.env.LECTURA_URL || 'http://127.0.0.1:8080').replace(/\/+$/, '');
}

async function pedir(ruta, cuerpo, fetchImpl, ms) {
  const r = await (fetchImpl || fetch)(urlBase() + ruta, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json',
               'X-Auth-Token': process.env.TELEFONO_TERCEROS_TOKEN || '' },
    body: JSON.stringify(cuerpo),
    signal: AbortSignal.timeout(ms || 10000)
  });
  if (!r.ok) throw new Error('backend ' + r.status);
  return (await r.json()) || {};
}

function conTope(promesa, ms, que) {
  let reloj;
  return Promise.race([
    promesa,
    new Promise(function (_, rechazar) {
      reloj = setTimeout(function () { rechazar(new Error(que + ': sin respuesta en ' + ms + ' ms')); }, ms);
    })
  ]).finally(function () { clearTimeout(reloj); });
}

// «Jarvis, cuelga», «cuélgale», «corta»: fuera Erik, Mikel sigue con Jarvis.
const RE_COLGAR = /\b(cuelga|cu[eé]lga(le|la|lo)|corta(le|la)?|termina la llamada|ya est[aá] con [eé]l|ya est[aá] con ella)\b/i;
// «Déjanos solos», «vete», «adiós»: Jarvis sale; Mikel y Erik siguen hablando.
const RE_SOLOS = /\b(d[eé]ja(nos|me) solos?|d[eé]janos hablar|vete|sal de la llamada|no escuches|deja de escuchar|adi[oó]s|hasta luego)\b/i;
const RE_NORMAL = /\b(modo normal|sal (del modo|de la escucha))\b/i;

class LlamadaATres {
  /**
   * @param {Object} o
   * @param {string} o.tid, o.nombre, o.pila, o.telefono  - lo que devuelve el backend
   * @param {Object} o.c                                  - el contexto de la conversación
   */
  constructor(o) {
    this.tid = o.tid;
    this.nombre = o.nombre;
    this.pila = o.pila || String(o.nombre || '').split(' ')[0];
    this.telefono = o.telefono;
    this.c = o.c;
    this.log = this.c.log || noop;
    this.activa = false;
    this.privado = false;
    this.turnos = [];
    this.conf = null;
    this.miembroA = null;
    this.dB = null;
    this.eB = null;
    this.idB = String(this.c.callUuid) + '-a-tres';
    this._conLinea = false;
    this._cerrado = null;
    this._alAcabar = [];
    this._tope = null;
  }

  sigue() {
    return !this.c.sigueActiva || this.c.sigueActiva();
  }

  /** Lo que se dice en la llamada, para el resumen. Nada si Mikel pidió quedarse solos. */
  anotar(quien, texto) {
    if (!this.activa || this.privado) return;
    const t = String(texto || '').replace(/\s+/g, ' ').trim();
    if (t.length < 2) return;
    this.turnos.push({ quien: quien, texto: t.slice(0, 1000) });
    if (this.turnos.length > TURNOS_MAX) this.turnos.shift();
  }

  /** Lo que se antepone a lo que Mikel le pide a Claude. */
  aviso() {
    return '[Llamada a tres con ' + this.pila + ': Mikel está hablando por teléfono con ' +
      this.pila + ' y tú estás dentro, callado, hasta que te nombra. Lo que contestes lo oyen ' +
      'los dos: una o dos frases, y nada privado de Mikel que no te haya pedido él. A ' +
      this.pila + ' no le oyes, a propósito: si Mikel te pregunta qué ha dicho, dile que solo ' +
      'le escuchas a él y que al colgar le llega el resumen.] ';
  }

  async _decirDirecto(texto) {
    if (!this.sigue()) return;
    try {
      await this.c.endpoint.play(await this.c.ttsService.generateSpeech(texto, this.c.voiceId));
    } catch (e) { /* un aviso no tumba la llamada */ }
  }

  async _decir(texto) {
    if (!this.sigue()) return;
    try {
      await this.c.salida.play(await this.c.ttsService.generateSpeech(texto, this.c.voiceId));
    } catch (e) { /* un aviso no tumba la llamada */ }
  }

  /** Marca, y si descuelga, mete a los dos en la conferencia. true si ya están hablando. */
  async marcar() {
    const c = this.c;
    const ms = dep('mediaServer');
    const linea = dep('lineaO2');
    let razon = '';
    try {
      // Mikel entra primero, solo, y oye el tono mientras suena: al descolgar solo falta
      // meter a Erik, y su «¿Sí?» no se pierde.
      this.conf = await ms.createConference('a-tres-' + String(c.callUuid).slice(0, 36), { profile: PERFIL });
      const ja = await conTope(c.endpoint.join(this.conf, { profile: PERFIL }), JOIN_TOPE_MS, 'entrar Mikel');
      this.miembroA = ja.memberId;
      c.salida.entrar(this.conf);
      c.endpoint.api('conference', this.conf.name + ' play ' + TONO).catch(noop);

      await linea.usar();
      this._conLinea = true;
      const r = await marcador()(dep('srf'), ms, {
        to: this.telefono, message: '', timeoutSeconds: TIMBRE_S(), lineaO2: linea
      });
      this.dB = r.dialog;
      this.eB = r.endpoint;
    } catch (e) {
      razon = (e && e.message) || 'error';
      this.log('A-TRES: no sale la llamada (' + razon + ')');
    }

    if (this.conf) await c.salida.parar();
    if (!this.eB || !this.sigue()) {
      const sinContestar = /no_answer|busy|declined|not_found|unavailable|auth/.test(razon);
      await this._cerrar(this.eB ? 'colgo_mikel' : (sinContestar ? 'sin_contestar:' + razon : 'error'), true);
      if (/busy/.test(razon)) await this._decirDirecto(FRASES.comunica(this.pila));
      else if (sinContestar) await this._decirDirecto(FRASES.noCoge(this.pila));
      else if (this.sigue()) await this._decirDirecto(FRASES.fallo);
      return false;
    }

    try {
      await conTope(this.eB.join(this.conf, { profile: PERFIL }), JOIN_TOPE_MS, 'entrar ' + this.pila);
      // Sin puerta de ruido: que pase todo, como en una llamada normal.
      await c.endpoint.api('conference', this.conf.name + ' energy all 0').catch(noop);
    } catch (e) {
      this.log('A-TRES: ' + e.message);
      await this._cerrar('error', true);
      await this._decirDirecto(FRASES.fallo);
      return false;
    }

    this.activa = true;
    this.log('A-TRES: en conferencia con ' + this.pila);
    const yo = this;
    this.dB.on('destroy', function () { yo._seFue(); });
    if (c.pasiva) {
      c.pasiva.activa = true;
      c.pasiva.dormir();
      c.pasiva.oyente = function (texto) { yo.anotar('mikel', texto); };
    }
    this._tope = setTimeout(function () { yo._porTope(); }, TOPE_MIN() * 60000);
    this._oirAlOtro().catch(function (e) { yo.log('A-TRES: el oído de la otra pata falló (' + e.message + ')'); });
    return true;
  }

  /** Lo que dice Erik, transcrito para el resumen. Nunca busca el nombre de Jarvis. */
  async _oirAlOtro() {
    const c = this.c;
    if (!c.audioForkServer || !c.whisperClient) return;
    const esperando = c.audioForkServer.expectSession(this.idB, { timeoutMs: 10000 });
    await this.eB.forkAudioStart({
      wsUrl: 'ws://127.0.0.1:' + c.wsPort + '/' + encodeURIComponent(this.idB),
      mixType: 'mono', sampling: '16k'
    });
    const sesion = await esperando;
    this.sesionB = sesion;
    while (this.activa && !this.privado) {
      sesion.setCaptureEnabled(true);
      let u = null;
      try {
        u = await sesion.waitForUtterance({ timeoutMs: 60000 });
      } catch (e) {
        if (/closed/i.test((e && e.message) || '')) break;
        continue;
      }
      if (!this.activa || this.privado) break;
      try {
        const texto = await c.whisperClient.transcribe(u.audio, { format: 'pcm', sampleRate: 16000, language: 'es' });
        const t = String(texto || '').trim();
        if (t.length < 2) continue;
        this.anotar('otro', t);
        // «Jarvis, apunta eso» también se lleva lo que ha dicho el otro.
        if (c.pasiva && typeof c.pasiva.recordar === 'function') c.pasiva.recordar('(' + this.pila + ') ' + t);
      } catch (e) { /* una frase sin transcribir no para el resto */ }
    }
  }

  /**
   * Las órdenes de la llamada a tres (solo llegan las que llevan el nombre de Jarvis):
   * colgar a Erik, dejarles solos. Devuelve true si la ha atendido.
   */
  async orden(texto) {
    if (!this.activa) return false;
    const t = String(texto || '');
    if (RE_COLGAR.test(t)) {
      this.log('A-TRES: Mikel pide colgar a ' + this.pila);
      await this._cerrar('colgamos', true);
      await this._decirDirecto(FRASES.colgado);
      return true;
    }
    if (RE_SOLOS.test(t)) {
      this.log('A-TRES: Mikel pide quedarse solos');
      await this._decir(FRASES.solos);
      this.privado = true;
      this.turnos = [];
      if (this.c.pasiva) {
        this.c.pasiva.oyente = null;
        if (typeof this.c.pasiva.loReciente === 'function') this.c.pasiva.loReciente();
      }
      if (this.eB) this.eB.forkAudioStop().catch(noop);
      return true;
    }
    if (RE_NORMAL.test(t)) {
      await this._decir(FRASES.soloNombre);
      return true;
    }
    return false;
  }

  /** Con Jarvis fuera («déjanos solos»), espera a que cuelgue uno de los dos. */
  esperarFin() {
    if (!this.activa) return Promise.resolve();
    const yo = this;
    return new Promise(function (r) { yo._alAcabar.push(r); });
  }

  async _seFue() {
    if (!this.activa) return;
    this.log('A-TRES: ' + this.pila + ' ha colgado');
    await this._cerrar('colgada', false);
    await this._decirDirecto(FRASES.haColgado(this.pila));
  }

  async _porTope() {
    if (!this.activa) return;
    await this._decir(FRASES.tope);
    await this._cerrar('tope', true);
  }

  /** Mikel ha colgado o la conversación ha acabado: fuera todo. */
  terminar() {
    return this._cerrar('colgo_mikel', true);
  }

  _cerrar(motivo, colgarOtro) {
    if (this._cerrado) return this._cerrado;
    const yo = this;
    this._cerrado = (async function () {
      const c = yo.c;
      yo.activa = false;
      clearTimeout(yo._tope);
      const conf = yo.conf;
      if (c.pasiva && c.pasiva.oyente) c.pasiva.oyente = null;
      // Mikel fuera de la conferencia primero: vuelve a su llamada con Jarvis, viva.
      if (conf && yo.miembroA !== null && yo.sigue()) {
        try { await c.endpoint.api('conference', conf.name + ' kick ' + yo.miembroA); } catch (e) { /* ya fuera */ }
      }
      c.salida.salir();
      if (yo.sesionB && yo.eB) { try { await yo.eB.forkAudioStop(); } catch (e) { /* ya parado */ } }
      if (c.audioForkServer && c.audioForkServer.cancelExpectation) c.audioForkServer.cancelExpectation(yo.idB);
      if (colgarOtro && yo.dB) { try { await yo.dB.destroy(); } catch (e) { /* ya colgado */ } }
      if (yo.eB) { try { await yo.eB.destroy(); } catch (e) { /* ya destruido */ } }
      if (conf) { try { await conf.destroy(); } catch (e) { /* ya cerrada */ } }
      if (yo._conLinea) {
        yo._conLinea = false;
        try { await dep('lineaO2').soltar(); } catch (e) { yo.log('A-TRES: no se pudo soltar la línea (' + e.message + ')'); }
      }
      for (const r of yo._alAcabar) r();
      yo._alAcabar = [];
      yo.log('A-TRES: terminada (' + motivo + ', ' + yo.turnos.length + ' frases)');
      try {
        await pedir('/telefono/a-tres/' + encodeURIComponent(yo.tid) + '/fin', {
          fin: motivo, turnos: yo.privado ? [] : yo.turnos
        }, c.fetch);
      } catch (e) {
        yo.log('A-TRES: el backend no ha recibido el final (' + e.message + ')');
      }
    })();
    return this._cerrado;
  }
}

/**
 * Si la respuesta de Claude pide la llamada a tres, la hace. Devuelve la LlamadaATres ya
 * en conferencia, o null (y Mikel ya ha oído por qué no).
 *
 * @param {string} respuesta  - lo que contestó Claude
 * @param {string} dicho      - lo que dijo Mikel en ese turno (el backend comprueba el nombre)
 * @param {Object} c
 * @param {Salida} c.salida   - lo que usa la conversación como endpoint
 * @param {Object} c.endpoint - el endpoint de verdad de Mikel
 * @param {string} c.callUuid
 * @param {Object} c.ttsService, c.whisperClient, c.audioForkServer
 * @param {number} c.wsPort
 * @param {string} [c.voiceId]
 * @param {Object} [c.pasiva] - EscuchaPasiva de la conversación
 * @param {Function} [c.log], [c.sigueActiva], [c.fetch]
 */
async function empezarSiLoPide(respuesta, dicho, c) {
  const nombre = pideATres(respuesta);
  if (!nombre) return null;
  const log = c.log || noop;
  const decir = async function (texto) {
    if (c.sigueActiva && !c.sigueActiva()) return;
    try { await c.salida.play(await c.ttsService.generateSpeech(texto, c.voiceId)); } catch (e) { /* aviso */ }
  };
  if (c.salida.enConferencia) { await decir(FRASES.yaEnUna); return null; }
  const linea = dep('lineaO2');
  if (!dep('srf') || !dep('mediaServer') || !linea || !linea.configurada()) {
    log('A-TRES: sin línea O2 o sin FreeSWITCH');
    await decir(FRASES.sinLinea);
    return null;
  }
  let destino;
  try {
    destino = await pedir('/telefono/a-tres', { nombre: nombre, dicho: String(dicho || '').slice(0, 2000),
                                                call_id: String(c.callUuid || '').slice(0, 80) }, c.fetch);
  } catch (e) {
    log('A-TRES: el backend no contesta (' + e.message + ')');
    await decir(FRASES.fallo);
    return null;
  }
  if (!destino.ok || !/^\+34\d{9}$/.test(String(destino.telefono || '')) || !destino.tid) {
    log('A-TRES: el backend no deja (' + String(destino.frase || '').slice(0, 80) + ')');
    await decir(destino.frase || FRASES.fallo);
    return null;
  }
  const tres = new LlamadaATres({ tid: destino.tid, nombre: destino.nombre, pila: destino.pila,
                                  telefono: destino.telefono, c: c });
  log('A-TRES: llamando a un contacto (' + destino.tid + ')');
  return (await tres.marcar()) ? tres : null;
}

module.exports = {
  configurar, envolver, empezarSiLoPide, pideATres, Salida, LlamadaATres, FRASES,
  RE_COLGAR, RE_SOLOS
};
