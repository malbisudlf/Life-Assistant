/**
 * Parche 38: el cronómetro de cada turno. Ver telefono/PARCHES.md en Life Assistant.
 *
 * La métrica que importa a Mikel es una: desde que deja de hablar hasta que oye a
 * Jarvis. Hasta aquí se sacaba a mano de los registros, cruzando cuatro líneas por
 * turno, y cada optimización se decidía con dos o tres llamadas. Ahora cada turno
 * marca sus tramos y deja:
 *  - una línea en el registro: «[TURNO] 4,6 s = cierre 1,0 + oído 0,7 + Claude 2,1 + voz 0,6»;
 *  - los últimos turnos en GET /turnos (JSON);
 *  - histogramas en GET /metrics, que lee el Prometheus de caja (panel de Grafana).
 *
 * Los tramos, en el orden en que pasan:
 *  cierre  de que deja de hablar a que el detector da la frase por acabada
 *  oido    de ahí a tener el texto (lo que no tapó el anticipo)
 *  antes   reflejos, lectura, confirmación: lo que se mira antes de preguntar a Claude
 *  claude  la consulta a Claude, de preguntar a tener la respuesta
 *  frase   lo que la frase de espera retrasa la respuesta ya lista (si sonaba al llegar)
 *  voz     de la respuesta a que la voz empieza a sonar (Fish en directo: su primer byte)
 *  total   la suma, de punta a punta
 *
 * Un tramo que no se pudo medir (sin marca) no se inventa: no sale ni en la línea ni en
 * los histogramas. Medir no puede tumbar la llamada: todo va en try/catch.
 */

const MAX_TURNOS = 100;
const TRAMOS = ['cierre', 'oido', 'antes', 'claude', 'frase', 'voz', 'total'];
// En segundos. De 0,25 a 15: por debajo no se oye la diferencia y por encima ya es avería.
const CUBOS = [0.25, 0.5, 0.75, 1, 1.5, 2, 2.5, 3, 3.5, 4, 5, 6, 8, 10, 15];

const recientes = [];
const histos = {};
let turnosContados = 0;

function nuevoHisto() {
  return { cubos: CUBOS.map(function () { return 0; }), suma: 0, cuenta: 0 };
}

function observar(clave, segundos) {
  if (!histos[clave]) histos[clave] = nuevoHisto();
  const h = histos[clave];
  for (let i = 0; i < CUBOS.length; i++) if (segundos <= CUBOS[i]) h.cubos[i]++;
  h.suma += segundos;
  h.cuenta++;
}

function seg(ms) {
  return (Math.round(ms / 100) / 10).toFixed(1).replace('.', ',');
}

class Turno {
  /**
   * @param {string} llamada  - callUuid
   * @param {string} sentido  - 'entrante' | 'saliente'
   */
  constructor(llamada, sentido) {
    this.llamada = llamada;
    this.sentido = sentido || 'entrante';
    this.marcas = {};
    this.tipo = null;
    this.cerrado = false;
  }

  /** Marca un instante (ms de Date.now()); sin `en`, ahora. La primera marca gana. */
  marca(nombre, en) {
    try {
      if (this.marcas[nombre] === undefined) this.marcas[nombre] = typeof en === 'number' ? en : Date.now();
    } catch (e) { /* medir no puede tumbar la llamada */ }
    return this;
  }

  /** Del detector: lo que trae la frase sobre cuándo dejó de hablar. */
  frase(utterance) {
    try {
      if (utterance && typeof utterance.finHabla === 'number') this.marca('finHabla', utterance.finHabla);
      this.marca('cierre');
    } catch (e) { /* idem */ }
    return this;
  }

  tramos() {
    const m = this.marcas;
    const d = function (a, b) {
      return (typeof m[a] === 'number' && typeof m[b] === 'number' && m[b] >= m[a]) ? m[b] - m[a] : null;
    };
    const t = {
      cierre: d('finHabla', 'cierre'),
      oido: d('cierre', 'texto'),
      antes: d('texto', 'consulta'),
      // Sin claudeListo (versiones viejas de pensar), Claude es todo hasta la respuesta.
      claude: d('consulta', 'claudeListo') !== null ? d('consulta', 'claudeListo') : d('consulta', 'respuesta'),
      frase: d('claudeListo', 'respuesta'),
      voz: d('respuesta', 'suena'),
      total: d('finHabla', 'suena'),
    };
    // Sin finHabla (DTMF, escucha pasiva), el total cuenta desde el cierre.
    if (t.total === null) t.total = d('cierre', 'suena');
    return t;
  }

  /**
   * Cierra el turno: escribe la línea, lo guarda y lo suma a los histogramas.
   * @param {string} tipo - 'claude' | 'reflejo' | 'lectura' | 'confirmacion' | 'pasiva'
   * @returns {Object|null} el resumen, o null si ya estaba cerrado
   */
  cerrar(tipo, log) {
    if (this.cerrado) return null;
    this.cerrado = true;
    try {
      this.tipo = tipo || 'claude';
      const t = this.tramos();
      const resumen = { en: new Date().toISOString(), llamada: this.llamada, sentido: this.sentido, tipo: this.tipo, ms: t };
      recientes.push(resumen);
      while (recientes.length > MAX_TURNOS) recientes.shift();
      turnosContados++;
      for (const k of TRAMOS) {
        if (typeof t[k] === 'number') observar(this.tipo + '|' + k, t[k] / 1000);
      }
      const partes = ['cierre', 'oido', 'antes', 'claude', 'frase', 'voz']
        .filter(function (k) { return typeof t[k] === 'number' && ((k !== 'antes' && k !== 'frase') || t[k] >= 50); })
        .map(function (k) { return (k === 'oido' ? 'oído' : k === 'claude' ? 'Claude' : k) + ' ' + seg(t[k]); });
      const linea = '[TURNO] ' + this.tipo + ': ' + (typeof t.total === 'number' ? seg(t.total) + ' s' : '¿? s') +
        (partes.length ? ' = ' + partes.join(' + ') : '');
      (log || console.log)(linea);
      return resumen;
    } catch (e) {
      return null;
    }
  }
}

function turno(llamada, sentido) {
  return new Turno(llamada, sentido);
}

function ultimos(n) {
  return recientes.slice(-(n || 20));
}

/** Texto de Prometheus (formato 0.0.4). */
function metricas() {
  const l = [];
  l.push('# HELP jarvis_turno_tramo_segundos Lo que tarda cada tramo de un turno de la llamada.');
  l.push('# TYPE jarvis_turno_tramo_segundos histogram');
  for (const clave of Object.keys(histos).sort()) {
    const [tipo, tramo] = clave.split('|');
    const h = histos[clave];
    const et = 'tipo="' + tipo + '",tramo="' + tramo + '"';
    for (let i = 0; i < CUBOS.length; i++) {
      l.push('jarvis_turno_tramo_segundos_bucket{' + et + ',le="' + CUBOS[i] + '"} ' + h.cubos[i]);
    }
    l.push('jarvis_turno_tramo_segundos_bucket{' + et + ',le="+Inf"} ' + h.cuenta);
    l.push('jarvis_turno_tramo_segundos_sum{' + et + '} ' + h.suma.toFixed(3));
    l.push('jarvis_turno_tramo_segundos_count{' + et + '} ' + h.cuenta);
  }
  l.push('# HELP jarvis_turnos_total Turnos medidos desde que arrancó la voice-app.');
  l.push('# TYPE jarvis_turnos_total counter');
  l.push('jarvis_turnos_total ' + turnosContados);
  return l.join('\n') + '\n';
}

/** Solo para los tests. */
function _reiniciar() {
  recientes.length = 0;
  for (const k of Object.keys(histos)) delete histos[k];
  turnosContados = 0;
}

module.exports = { turno, ultimos, metricas, Turno, TRAMOS, CUBOS, _reiniciar };
