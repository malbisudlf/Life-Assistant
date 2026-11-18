/**
 * Parche 50: música en la escucha pasiva. Ver telefono/PARCHES.md y telefono/musica/ en
 * Life Assistant.
 *
 * Mikel, el 2026-11-18: «quiero tener a Jarvis en modo de escucha pasiva mientras escucho
 * música, música que yo puedo controlar desde el móvil o el coche, y que en cualquier
 * momento diga "Jarvis…" y me conteste». Con la llamada abierta iOS para la música del
 * iPhone, así que la música suena DENTRO de la llamada: el servicio `musica` de caja es un
 * altavoz de Spotify («Jarvis») y sirve lo que suena en MP3; FreeSWITCH lo mezcla en lo que
 * oye el que llama (`uuid_displace … mux`, hacia él: el oído no lo recibe, va por el otro
 * sentido).
 *
 * - Suena SOLO mientras Jarvis duerme. Al oír su nombre se corta (deja de pedirla, y el
 *   servicio, sin nadie escuchando, deja la canción parada donde iba); al dormirse otra vez
 *   vuelve por el mismo sitio. Lo que se dice con Jarvis despierto no tiene música debajo.
 * - Qué suena, pasar, pausar y el volumen: en la app de Spotify, eligiendo «Jarvis» como
 *   altavoz. Si no hay nada puesto, el servicio manda silencio y no se nota nada.
 * - Sin MUSICA_URL, nada de esto existe y la llamada es la de siempre.
 */
'use strict';

function ruta() {
  const base = String(process.env.MUSICA_URL || '').trim();
  if (!base) return null;
  return 'shout://' + base.replace(/^[a-z]+:\/\//i, '').replace(/\/+$/, '') + '/musica.mp3';
}

function fallo(respuesta) {
  const texto = typeof respuesta === 'string' ? respuesta
    : (respuesta && (respuesta.body || respuesta.msg)) || '';
  return /^-ERR/.test(String(texto).trim()) ? String(texto).trim() : '';
}

class MusicaPasiva {
  constructor(endpoint, log) {
    this.endpoint = endpoint;
    this.log = log || function () {};
    this.sonando = false;
  }

  /** Empieza a sonar debajo de la llamada, si hay servicio. Nunca lanza. */
  async sonar() {
    const r = ruta();
    if (!r) return false;
    if (this.sonando) return true;
    try {
      const res = await this.endpoint.api('uuid_displace', this.endpoint.uuid + ' start ' + r + ' 0 mux');
      const error = fallo(res);
      if (error) {
        this.log('MUSICA: no suena (' + error + ')');
        return false;
      }
      this.sonando = true;
      this.log('MUSICA: suena');
    } catch (e) {
      this.log('MUSICA: no suena (' + e.message + ')');
    }
    return this.sonando;
  }

  /** Deja de sonar: al despertar, al colgar o al pasar a modo normal. Nunca lanza. */
  async callar() {
    if (!this.sonando) return;
    this.sonando = false;
    try {
      await this.endpoint.api('uuid_displace', this.endpoint.uuid + ' stop ' + ruta());
      this.log('MUSICA: callada');
    } catch (e) {
      // La llamada ya se ha ido, y la música con ella.
    }
  }
}

module.exports = { MusicaPasiva, ruta };
