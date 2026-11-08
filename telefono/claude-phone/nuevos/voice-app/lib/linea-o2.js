/**
 * Parche 32: la línea fija de casa (O2/Telefónica) por SIP, para que Jarvis llame a
 * otras personas. Ver telefono/PARCHES.md y docs/LLAMADAS_TERCEROS.md en Life Assistant.
 *
 * El router de O2 registra la línea en un proxy SIP de Telefónica que se alcanza desde la
 * LAN, y ese proxy acepta también el registro de `caja` con el mismo usuario y sin
 * contraseña (probado el 2026-10-31). Lo que se sabe y lo que no:
 *
 *   - **El registro se hace solo para llamar, y se quita al colgar.** Mientras `caja` está
 *     registrada, una llamada al fijo suena aquí además de en el Gigaset del router. Se
 *     rechaza (`esSuya` + 480 en index.js), pero mejor que ni llegue: por eso no se queda
 *     registrada de fondo.
 *   - **Al quitarlo se quita SOLO nuestro Contact**, nunca `Contact: *`: el asterisco
 *     borraría también el registro del router y el fijo dejaría de recibir llamadas.
 *   - Que el INVITE necesite el registro previo es la hipótesis más fuerte (el primero, sin
 *     registro, dio 403; tras registrar, sonó), no algo demostrado. Registrar antes es
 *     inofensivo, así que se hace.
 *   - Nada personal aquí: el usuario de la línea y la dirección del proxy van en el .env
 *     (`O2_SIP_USUARIO`, `O2_PROXY`). El usuario no se escribe nunca en el log.
 */

const DOMINIO_DEFECTO = 'telefonica.net';
const REFRESCO_MIN_SEG = 20;
// Lo que Telefónica da a la línea (el router se registra cada 70 s). Si el 200 OK no dice
// cuánto nos concede, se supone esto y no lo pedido: renovar a destiempo deja la línea
// sin registro a mitad de una llamada.
const CONCEDIDO_SI_NO_DICE = 70;

class LineaO2 {
  /**
   * @param {Object} srf - drachtio SRF
   * @param {Object} o
   * @param {string} o.usuario   - el Auth Username del router (O2_SIP_USUARIO)
   * @param {string} o.proxy     - "ip:puerto" del proxy SIP (O2_PROXY)
   * @param {string} [o.dominio] - telefonica.net
   * @param {string} o.ipLocal   - la IP de caja en la LAN (la de drachtio)
   * @param {number} o.puertoLocal - el puerto SIP de drachtio (5070)
   * @param {number} [o.expira]  - segundos que se piden al registrar
   * @param {Function} [o.log]
   */
  constructor(srf, o) {
    o = o || {};
    this.srf = srf;
    this.usuario = String(o.usuario || '').trim();
    this.proxy = String(o.proxy || '').trim();
    this.dominio = o.dominio || DOMINIO_DEFECTO;
    this.ipLocal = o.ipLocal;
    this.puertoLocal = o.puertoLocal || 5070;
    this.expira = o.expira || 120;
    this.log = o.log || function () {};
    this.usos = 0;
    this.registrada = false;
    this.temporizador = null;
    this.pendiente = null;
  }

  configurada() {
    return Boolean(this.usuario && /^[\d.]+:\d+$/.test(this.proxy) && this.ipLocal);
  }

  ipProxy() {
    return this.proxy.split(':')[0];
  }

  /** La URI del destino tal como la aceptó Telefónica: sip:+34…@telefonica.net:5060. */
  destino(e164) {
    return 'sip:' + e164 + '@' + this.dominio + ':5060';
  }

  cabeceras(e164) {
    const yo = '"' + this.usuario + '" <sip:' + this.usuario + '@' + this.dominio + ':5070>';
    const h = {
      'From': yo,
      'Contact': '<' + this.contacto() + '>',
      'Route': '<sip:' + this.proxy + ';lr>',
      'User-Agent': 'Jarvis-LA/1.0'
    };
    if (e164) h['To'] = '<' + this.destino(e164) + '>';
    else h['To'] = yo;
    return h;
  }

  contacto() {
    return 'sip:' + this.usuario + '@' + this.ipLocal + ':' + this.puertoLocal + ';transport=udp';
  }

  /** Si un INVITE entrante viene del proxy de O2 (una llamada al fijo). */
  esSuya(req) {
    if (!this.configurada() || !req) return false;
    return req.source_address === this.ipProxy();
  }

  /**
   * Pide la línea para una llamada. La primera petición registra; las siguientes, si
   * llegara a haber dos a la vez, reutilizan el registro. Lanza si no se registra.
   */
  async usar() {
    if (!this.configurada()) throw new Error('linea_o2_sin_configurar');
    this.usos++;
    try {
      if (!this.registrada) await this._registrar(this.expira);
    } catch (e) {
      this.usos--;
      throw e;
    }
  }

  /** Devuelve la línea. Con el último uso, quita el registro. Nunca lanza. */
  async soltar() {
    this.usos = Math.max(0, this.usos - 1);
    if (this.usos > 0) return;
    if (this.temporizador) clearTimeout(this.temporizador);
    this.temporizador = null;
    if (!this.registrada) return;
    this.registrada = false;
    try {
      await this._registrar(0);
      this.log('O2: registro quitado');
    } catch (e) {
      this.log('O2: no se pudo quitar el registro (' + e.message + '); caduca solo');
    }
  }

  _registrar(segundos) {
    if (this.pendiente && segundos > 0) return this.pendiente;
    const h = this.cabeceras(null);
    h['Contact'] = '<' + this.contacto() + '>;expires=' + segundos;
    h['Expires'] = String(segundos);
    h['Allow'] = 'INVITE, ACK, CANCEL, BYE, OPTIONS, INFO, UPDATE';
    h['Supported'] = 'path, gruu';
    const self = this;
    const promesa = new Promise(function (resolver, rechazar) {
      const vigia = setTimeout(function () { rechazar(new Error('o2_register_timeout')); }, 8000);
      try {
        self.srf.request('sip:' + self.dominio, {
          method: 'REGISTER',
          proxy: 'sip:' + self.proxy,
          headers: h
        }, function (err, req) {
          if (err) { clearTimeout(vigia); rechazar(err); return; }
          req.on('response', function (res) {
            if (res.status < 200) return;
            clearTimeout(vigia);
            if (res.status !== 200) {
              rechazar(new Error('o2_register_' + res.status));
              return;
            }
            resolver(res);
          });
        });
      } catch (e) {
        clearTimeout(vigia);
        rechazar(e);
      }
    }).then(function (res) {
      if (segundos > 0) {
        self.registrada = true;
        const concedido = self._concedido(res, segundos);
        self.log('O2: registrada (' + concedido + ' s)');
        self._programarRefresco(concedido);
      }
      return res;
    });
    if (segundos > 0) {
      this.pendiente = promesa;
      promesa.then(function () { self.pendiente = null; }, function () { self.pendiente = null; });
    }
    return promesa;
  }

  /** Los segundos concedidos a NUESTRO Contact (Telefónica devuelve también los demás);
   *  si no lo dice ahí, la cabecera Expires; si tampoco, CONCEDIDO_SI_NO_DICE. */
  _concedido(res, pedido) {
    const leer = function (h) { return (res && typeof res.get === 'function' && res.get(h)) || ''; };
    const nuestro = String(leer('Contact')).split(/,(?=\s*<)/).find(function (c) {
      return c.indexOf('@' + this.ipLocal + ':' + this.puertoLocal) >= 0;
    }, this);
    const m = nuestro && nuestro.match(/expires=(\d+)/i);
    if (m) return parseInt(m[1], 10);
    const cabecera = parseInt(leer('Expires'), 10);
    if (cabecera > 0) return cabecera;
    return Math.min(pedido, CONCEDIDO_SI_NO_DICE);
  }

  _programarRefresco(concedido) {
    if (this.temporizador) clearTimeout(this.temporizador);
    const self = this;
    const seg = Math.max(REFRESCO_MIN_SEG, Math.floor(concedido * 0.6));
    this.temporizador = setTimeout(function () {
      if (self.usos <= 0) return;
      self._registrar(self.expira).catch(function (e) {
        self.log('O2: falló el refresco del registro (' + e.message + ')');
      });
    }, seg * 1000);
    if (this.temporizador.unref) this.temporizador.unref();
  }
}

module.exports = { LineaO2 };
