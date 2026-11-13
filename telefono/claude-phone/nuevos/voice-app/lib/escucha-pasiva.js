/**
 * Parche 22: la escucha pasiva («modo coche»). Ver telefono/PARCHES.md en Life Assistant.
 *
 * La llamada se queda abierta y Jarvis callado: oye todo lo que pasa, pero no contesta
 * hasta que alguien dice su nombre, como un altavoz de los que se despiertan con una
 * palabra. «Jarvis, ¿qué tengo hoy?» es una pregunta; lo que se hable en el coche sin
 * nombrarle no sale de la voice-app (ni llega a Claude ni se guarda en la bitácora).
 *
 * - Se enciende diciendo «modo coche» (o «escucha pasiva», «quédate escuchando») en
 *   cualquier llamada, o desde el principio con `escuchaPasiva: true` en
 *   POST /api/outbound-call, que es lo que pide el backend cuando el iPhone se conecta
 *   al coche.
 * - Despierto, contesta y deja ESCUCHA_PASIVA_SEGUIMIENTO_MS (8 s) para seguir hablando
 *   sin repetir el nombre. Si nadie dice nada, o se le dice «gracias» o «eso es todo»,
 *   vuelve a dormirse en silencio. «Cuelga» o «adiós» cuelgan, como siempre.
 * - «Modo normal» lo apaga y la llamada sigue como cualquier otra.
 * - Dormido no hay «¿sigues ahí?» ni cuenta de silencios (parche 8): el silencio es lo
 *   normal. El tope es de tiempo, ESCUCHA_PASIVA_MAX_MIN (180 min).
 *
 * Lo que cuesta: cada frase que oye dormido se transcribe, pero solo sus primeros
 * ESCUCHA_PASIVA_VENTANA_MS (4 s) si es larga; la frase entera solo cuando el
 * principio trae el nombre. Por eso, en una frase larga, «Jarvis» tiene que ir al
 * principio. Con la radio puesta todo el viaje son unos 8 minutos de Whisper por hora.
 *
 * Parche 46: despertar tardaba ~8,5 s (llamada del 2026-11-12) frente a los ~4 de un
 * turno normal, porque dormido transcribía dos veces seguidas (el principio y luego la
 * frase entera) y sin anticipo. Con el oído de jacobo disponible:
 *  - a los ESCUCHA_PASIVA_TEMPRANA_MS (1200 y 2500) de voz, `small` mira si lo que va
 *    dicho trae el nombre ('hablando' de audio-fork.js). Si lo trae suena el tono
 *    (`alNombrar`) mientras aún hablas, y esa frase se anticipa dure lo que dure.
 *    Medido en jacobo el 2026-11-12 con voz de Piper por banda de teléfono: `small`
 *    solo vio el nombre en 1 de 4 frases (se lo come al principio) y ninguna vez donde
 *    no estaba. El tono es, pues, un extra que a veces no suena; lo que decide es turbo;
 *  - una frase de hasta ESCUCHA_PASIVA_ANTICIPO_MS (10 s) se transcribe en su pausa, no
 *    al cerrarse (`anticipar`): al cerrarse, el texto ya está;
 *  - la frase se transcribe una sola vez, entera: en casa la ventana no ahorra nada.
 * Sin jacobo (OpenAI) todo sigue como en el 22. ESCUCHA_PASIVA_TEMPRANA_MS=0 lo apaga.
 *
 * Parche 47: lo transcrito dormido se recuerda ESCUCHA_PASIVA_MEMORIA_S (90 s) en
 * memoria, para «Jarvis, apunta eso» (lib/apunte.js). Sigue sin salir de la voice-app
 * salvo que lo pidas, y sin escribirse en ningún sitio.
 */
'use strict';

const { setTimeout: dormirMs } = require('node:timers/promises');

// Cómo transcribe Whisper «Jarvis» en español: jarvis, yarvis, charvis, jarbis, yervis,
// harvis, llarvis, javis… Con «oye», «hey» o «eh» delante, opcional.
const PALABRA_POR_DEFECTO =
  '(?:(?:oye|hey|ey|eh|hola)[\\s,]+)?(?:j|y|ch|g|h|ll|sh|dj)[aei]r?[bv]is';

const LETRA = 'a-záéíóúüñ';

// Lo que se dice al despertarle sin pregunta, al encender, al apagar y al dormirse.
const FRASES = {
  activada:  'Escucha pasiva activada, señor. Diga «Jarvis» cuando me necesite.',
  despierta: '¿Señor?',
  dormir:    'A su disposición.',
  normal:    'Modo normal, señor. Le escucho.',
  tope:      'Llevo mucho rato a la escucha, señor. Cuelgo; llámeme cuando quiera.'
};

// A Claude, para que sepa por qué le llega una pregunta de repente y que debe ser breve.
const AVISO_PASIVA =
  '[Modo coche: estabas a la escucha en silencio y te ha llamado por tu nombre. ' +
  'Contesta breve; después vuelves a escuchar sin hablar.] ';

function entero(nombre, porDefecto) {
  const n = parseInt(process.env[nombre], 10);
  return Number.isFinite(n) && n > 0 ? n : porDefecto;
}

function expresionPalabra() {
  const propia = process.env.ESCUCHA_PASIVA_PALABRA;
  return new RegExp('(^|[^' + LETRA + '])(' + (propia || PALABRA_POR_DEFECTO) + ')(?![' + LETRA + '])', 'i');
}

function limpiar(texto) {
  return String(texto || '').replace(/^[\s,.;:!?¡¿…-]+/, '').replace(/[\s,;:-]+$/, '').trim();
}

/**
 * ¿Le han llamado? Devuelve null, o { resto } con lo que hay que contestar: lo que va
 * detrás del nombre («Jarvis, pon música» → «pon música») o, si el nombre va al final
 * («¿qué hora es, Jarvis?»), la frase que lo lleva. `resto` vacío es que solo le han
 * nombrado: toca preguntar «¿Señor?» y escuchar.
 */
function buscarPalabra(texto) {
  const t = String(texto || '');
  const m = expresionPalabra().exec(t);
  if (!m) return null;
  const inicio = m.index + m[1].length;
  const despues = limpiar(t.slice(inicio + m[2].length));
  if (/[a-záéíóúüñ0-9]{2,}/i.test(despues)) return { resto: despues };
  // Nada detrás: vale la última frase de delante (lo anterior puede ser otra conversación).
  const antes = t.slice(0, inicio).split(/[.!?…]+\s/).pop();
  return { resto: limpiar(antes) };
}

/** Parche 47: lo dicho ANTES del nombre en la misma frase («…y pan. Jarvis, apunta eso»). */
function antesDelNombre(texto) {
  const t = String(texto || '');
  const m = expresionPalabra().exec(t);
  if (!m) return '';
  return limpiar(t.slice(0, m.index + m[1].length));
}

function pideEscuchaPasiva(texto) {
  return /\b(modo (coche|pasivo|escucha|copiloto)|escucha pasiva|qu[eé]date (escuchando|a la escucha))\b/i
    .test(String(texto || ''));
}

function pideModoNormal(texto) {
  return /\b(modo normal|sal (del modo|de la escucha)|deja de escuchar|desactiva (el modo|la escucha))\b/i
    .test(String(texto || ''));
}

// «Gracias», «eso es todo», «nada más»… dicho SOLO (la frase entera): vuelve a dormirse.
function esFinDeTurno(texto) {
  const t = String(texto || '').toLowerCase().replace(/[¡!¿?.,]/g, ' ').replace(/\s+/g, ' ').trim()
    .replace(/\s*\b(jarvis|señor)\b\s*/g, ' ').trim();
  return /^(vale |ok |perfecto )?(muchas gracias|gracias|eso es todo|nada m[aá]s|ya est[aá]|perfecto|vale)( gracias)?$/.test(t);
}

class EscuchaPasiva {
  /**
   * @param {Object} [o]
   * @param {Function} [o.log]
   * @param {boolean}  [o.activa] - empezar ya a la escucha (la llamada del coche)
   */
  constructor(o) {
    const op = o || {};
    this.log = op.log || function () {};
    this.activa = Boolean(op.activa);
    this.despierta = false;
    this.seguimientoMs = entero('ESCUCHA_PASIVA_SEGUIMIENTO_MS', 8000);
    this.ventanaMs = entero('ESCUCHA_PASIVA_VENTANA_MS', 4000);
    this.topeMs = entero('ESCUCHA_PASIVA_MAX_MIN', 180) * 60000;
    this.desde = this.activa ? Date.now() : null;
    // Parche 46: lo que `small` ha visto de la frase que está entrando, y la última
    // que despertó (para el cronómetro: cuándo calló y cuándo se cerró).
    this.temprana = String(process.env.ESCUCHA_PASIVA_TEMPRANA_MS || '') !== '0';
    // Hasta cuánto de frase se transcribe en su pausa estando dormido: lo que dura una
    // pregunta. Más larga es charla o la radio, y espera a cerrarse.
    this.anticipoMs = entero('ESCUCHA_PASIVA_ANTICIPO_MS', 10000);
    this._nombrada = false;
    this.ultimaFrase = null;
    // Parche 47: lo transcrito hace poco, para «Jarvis, apunta eso». Solo en memoria:
    // ni al registro ni a disco, y se va con la llamada. 0 lo apaga.
    const memoria = parseInt(process.env.ESCUCHA_PASIVA_MEMORIA_S, 10);
    this.memoriaMs = (Number.isFinite(memoria) && memoria >= 0 ? memoria : 90) * 1000;
    this._reciente = [];
  }

  /** Parche 47: guarda lo oído (dormido, sin nombrarle) durante `memoriaMs`. */
  recordar(texto) {
    const t = String(texto || '').replace(/\s+/g, ' ').trim();
    if (!this.memoriaMs || t.length < 2) return;
    const ahora = Date.now();
    this._reciente.push({ en: ahora, texto: t.slice(0, 1000) });
    this._reciente = this._reciente.filter((x) => ahora - x.en <= this.memoriaMs).slice(-30);
  }

  /** Parche 47: lo dicho en los últimos `memoriaMs`, de un tirón; y lo olvida. */
  loReciente() {
    const ahora = Date.now();
    const texto = this._reciente.filter((x) => ahora - x.en <= this.memoriaMs)
      .map(function (x) { return x.texto; }).join(' ').slice(-2000).trim();
    this._reciente = [];
    return texto;
  }

  /** Parche 46: ¿ha oído ya su nombre en la frase que está entrando? */
  nombrada() {
    return this.dormida() && this._nombrada;
  }

  /**
   * Parche 46: ¿se transcribe esta pausa aunque esté dormido? Sí si ya le han nombrado,
   * o si lo dicho es corto y contesta jacobo: es la misma pasada que se haría al cerrar
   * la frase, solo que antes. Una frase larga sin nombre (la radio) no se anticipa.
   */
  anticipar(pausa, whisperClient) {
    if (!this.dormida()) return true;
    if (!this.temprana) return false;
    if (this._nombrada) return true;
    const corta = pausa && pausa.audio && pausa.audio.length <= this.anticipoMs * 32;
    return Boolean(corta && whisperClient && typeof whisperClient.oidoDisponible === 'function' &&
      whisperClient.oidoDisponible());
  }

  /** ¿Toca esperar a que le nombren antes de escuchar el turno? */
  dormida() {
    return this.activa && !this.despierta;
  }

  activar() {
    if (!this.activa) this.desde = Date.now();
    this.activa = true;
    this.despierta = false;
    this.log('ESCUCHA-PASIVA: activada');
  }

  dormir() {
    if (this.activa && this.despierta) this.log('ESCUCHA-PASIVA: vuelvo a escuchar en silencio');
    this.despierta = false;
  }

  /**
   * Las órdenes de la propia escucha, antes de que la frase vaya a Claude. Devuelve null
   * o { frase } con lo que hay que decir (el estado ya cambiado).
   */
  orden(texto) {
    if (!this.activa) {
      if (pideEscuchaPasiva(texto)) { this.activar(); return { frase: FRASES.activada }; }
      return null;
    }
    if (pideModoNormal(texto)) {
      this.activa = false;
      this.despierta = false;
      this._reciente = [];
      this.log('ESCUCHA-PASIVA: apagada');
      return { frase: FRASES.normal };
    }
    if (pideEscuchaPasiva(texto)) { this.dormir(); return { frase: FRASES.activada }; }
    if (esFinDeTurno(texto)) { this.dormir(); return { frase: FRASES.dormir }; }
    return null;
  }

  /** El tiempo que espera el turno siguiente: corto si es seguir hablando tras despertar. */
  esperaTurnoMs(normal) {
    return this.activa ? this.seguimientoMs : normal;
  }

  async _transcribir(whisperClient, audio) {
    return whisperClient.transcribe(audio, {
      format: 'pcm', sampleRate: 16000, language: 'es', prompt: 'Jarvis.'
    });
  }

  /**
   * Escucha en silencio hasta que alguien le nombra. Devuelve { resto } (ver
   * buscarPalabra), { tope: true } si se acabó el tiempo, o null si se ha colgado.
   *
   * @param {Object}   p
   * @param {Object}   p.session        - AudioForkSession
   * @param {Object}   p.whisperClient
   * @param {Function} [p.sigueActiva]  - () => boolean
   */
  async esperarPalabra(p) {
    const sigueActiva = p.sigueActiva || function () { return true; };
    const w = p.whisperClient;
    // 16 kHz, 16 bits, mono: 32 bytes por milisegundo.
    const ventana = this.ventanaMs * 32;
    let oidas = 0;
    this.log('ESCUCHA-PASIVA: a la escucha');
    const conOido = function () {
      return typeof w.oidoDisponible === 'function' && w.oidoDisponible();
    };
    // Parche 46: mientras hablas, `small` busca el nombre en lo que va dicho.
    let serie = 0;
    const alHablar = (trozo) => {
      if (!this.temprana || this._nombrada || !conOido()) return;
      const mia = serie;
      w.transcribe(trozo.audio, { format: 'pcm', sampleRate: 16000, language: 'es', soloOido: true, rapido: true })
        .then((texto) => {
          if (mia !== serie || this._nombrada || !buscarPalabra(texto)) return;
          this._nombrada = true;
          this.log('ESCUCHA-PASIVA: oigo mi nombre mientras habla');
          if (p.alNombrar) { try { p.alNombrar(); } catch (e) { /* el tono no puede cortar nada */ } }
        }, function () {});
    };
    const conEventos = typeof p.session.on === 'function' && typeof p.session.off === 'function';
    if (conEventos) p.session.on('hablando', alHablar);
    try {
      while (sigueActiva()) {
        if (Date.now() - this.desde > this.topeMs) {
          this.log('ESCUCHA-PASIVA: tope de tiempo');
          return { tope: true };
        }
        p.session.setCaptureEnabled(true);
        let u = null;
        try {
          u = await p.session.waitForUtterance({ timeoutMs: 60000 });
        } catch (err) {
          if (/closed/i.test(err.message || '')) return null;
          continue;                                 // un minuto en silencio: a seguir
        }
        const cierreEn = Date.now();
        const nombrada = this._nombrada;
        this._nombrada = false;
        serie++;
        if (!sigueActiva()) return null;
        oidas++;
        let hallada = null;
        let texto = '';
        const anticipada = u.pausa && u.pausa.transcripcion;
        try {
          if (anticipada) {
            // Ya transcrita, entera, durante el silencio que la cerró.
            texto = await anticipada;
            hallada = buscarPalabra(texto);
          } else if (this.temprana && conOido()) {
            texto = await this._transcribir(w, u.audio);
            hallada = buscarPalabra(texto);
          } else {
            const larga = u.audio.length > ventana * 1.5;
            texto = await this._transcribir(w, larga ? u.audio.subarray(0, ventana) : u.audio);
            hallada = buscarPalabra(texto);
            if (hallada && larga) {
              try {
                const entera = await this._transcribir(w, u.audio);
                const otra = buscarPalabra(entera);
                if (otra) { hallada = otra; texto = entera; }
              } catch (err) { /* vale con lo del principio */ }
            }
          }
        } catch (err) {
          let salvada = false;
          if (anticipada) {
            // Falló la del anticipo: la frase entera, como siempre.
            try { texto = await this._transcribir(w, u.audio); hallada = buscarPalabra(texto); salvada = true; } catch (e) { /* abajo */ }
          }
          if (!salvada) {
            this.log('ESCUCHA-PASIVA: Whisper falló (' + err.message + ')');
            if (!nombrada) { await dormirMs(1000); continue; }
          }
        }
        // Lo que se habla sin nombrarle no se registra: ni el texto, solo que no era.
        // Si el tono ya sonó y el texto final no trae el nombre, mejor preguntar que callar.
        if (!hallada && nombrada) hallada = { resto: '' };
        // Parche 47: lo oído se recuerda un rato, en memoria, por si pide apuntarlo.
        this.recordar(hallada ? antesDelNombre(texto) : texto);
        if (!hallada) continue;
        p.session.setCaptureEnabled(false);
        this.despierta = true;
        this.ultimaFrase = { finHabla: u.finHabla, cierreEn: cierreEn, textoEn: Date.now(), tono: nombrada };
        this.log('ESCUCHA-PASIVA: me llaman (tras ' + oidas + ' frases sin mí' + (nombrada ? ', tono dado' : '') + ')');
        return hallada;
      }
      return null;
    } finally {
      this._nombrada = false;
      if (conEventos) p.session.off('hablando', alHablar);
    }
  }
}

module.exports = {
  EscuchaPasiva, buscarPalabra, antesDelNombre, pideEscuchaPasiva, pideModoNormal, esFinDeTurno,
  FRASES, AVISO_PASIVA
};
