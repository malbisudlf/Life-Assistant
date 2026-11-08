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
    // 16 kHz, 16 bits, mono: 32 bytes por milisegundo.
    const ventana = this.ventanaMs * 32;
    let oidas = 0;
    this.log('ESCUCHA-PASIVA: a la escucha');
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
      if (!sigueActiva()) return null;
      oidas++;
      let texto = '';
      const larga = u.audio.length > ventana * 1.5;
      try {
        texto = await this._transcribir(p.whisperClient, larga ? u.audio.subarray(0, ventana) : u.audio);
      } catch (err) {
        this.log('ESCUCHA-PASIVA: Whisper falló (' + err.message + ')');
        await dormirMs(1000);
        continue;
      }
      let hallada = buscarPalabra(texto);
      // Lo que se habla sin nombrarle no se registra: ni el texto, solo que no era.
      if (!hallada) continue;
      if (larga) {
        try {
          hallada = buscarPalabra(await this._transcribir(p.whisperClient, u.audio)) || hallada;
        } catch (err) { /* vale con lo del principio */ }
      }
      p.session.setCaptureEnabled(false);
      this.despierta = true;
      this.log('ESCUCHA-PASIVA: me llaman (tras ' + oidas + ' frases sin mí)');
      return hallada;
    }
    return null;
  }
}

module.exports = {
  EscuchaPasiva, buscarPalabra, pideEscuchaPasiva, pideModoNormal, esFinDeTurno,
  FRASES, AVISO_PASIVA
};
