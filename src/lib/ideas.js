// ── IDEAS: BÚSQUEDA, ETIQUETAS Y PARECIDAS ───────────────────────
// Lógica pura del widget de Ideas. Todo trabaja sobre lo que ya devuelve `GET /ideas`
// (`id`, `key`, `full_text`, `tag`, `created_at`): no hay endpoint, columna ni llamada
// de pago detrás, y por eso nada de esto puede borrar ni fusionar una idea. Agrupar es
// una forma de ENSEÑAR la lista, no de cambiarla.

import { MONTHS_ES } from "./helpers";

// Cuántas ideas se enseñan antes del «Ver N más». Con la lista entera abierta, el widget
// crecía sin fondo y empujaba a los de debajo fuera de la pantalla del móvil.
export const IDEAS_VISIBLES = 10;

// Por debajo de esto dos ideas no se juntan aunque el Jaccard dé alto: dos notas de tres
// palabras que comparten una sola («gimnasio») salen parecidísimas en proporción y no
// tienen nada que ver.
export const MIN_PALABRAS_COMUNES = 2;

// PROVISIONAL: sale de probar con redacciones inventadas, no con las ideas reales. Se
// afina mirando qué agrupa de verdad. Equivocarse aquí cuesta poco a propósito: un falso
// positivo solo pinta dos ideas bajo la misma marca, nunca borra ni fusiona nada.
export const UMBRAL_PARECIDAS = 0.35;

// Escrita con su código y no con el carácter: una marca combinante suelta en el fuente
// no se ve, y parecería que la expresión busca una «n» a secas.
const N_CON_VIRGULILLA = new RegExp("n" + String.fromCharCode(0x0303), "g");

// Lo mismo que hace `esFinDeLlamada` en helpers.js (sin tildes, en minúsculas), con una
// excepción: la «ñ» se conserva. NFD la parte en «n» + virgulilla y quitar la marca la
// convertiría en «n», y «año»/«ano» o «caña»/«cana» no son la misma palabra.
function sinTildes(texto) {
  return texto
    .normalize("NFD")
    .replace(N_CON_VIRGULILLA, "ñ")
    .replace(/\p{Diacritic}/gu, "");
}

/** Texto comparable: minúsculas, sin tildes (salvo la ñ) y con los espacios colapsados.
 *  Acepta cualquier cosa, porque una idea puede llegar sin `tag` o sin `full_text`. */
export function normalizar(texto) {
  return sinTildes(String(texto ?? "").toLowerCase())
    .replace(/\s+/g, " ")
    .trim();
}

// Palabras que no dicen de QUÉ va una idea. Van ya normalizadas (sin tildes).
//
// Además de lo gramatical (artículos, preposiciones, pronombres, auxiliares), lleva el
// relleno típico de GPT-4o-mini: los `full_text` los redacta el modelo, no Mikel, y lo
// hace con las mismas muletillas en todas («La idea es crear una forma de…», «Sería
// importante…», «El usuario quiere…»). Sin quitarlas, dos ideas cualesquiera comparten
// media docena de palabras y todo se parece a todo.
export const PALABRAS_VACIAS = new Set([
  // Artículos y contracciones
  "el", "la", "los", "las", "un", "una", "unos", "unas", "lo", "al", "del",
  // Preposiciones
  "a", "ante", "bajo", "con", "contra", "de", "desde", "durante", "en", "entre", "hacia",
  "hasta", "mediante", "para", "por", "segun", "sin", "sobre", "tras",
  // Conjunciones y nexos
  "y", "e", "ni", "o", "u", "pero", "sino", "que", "porque", "como", "cuando", "donde",
  "si", "aunque", "pues", "mientras", "tambien", "tampoco", "ademas", "incluso", "asi",
  // Pronombres, posesivos y demostrativos
  "yo", "tu", "ella", "ello", "ellos", "ellas", "nosotros", "nosotras", "vosotros",
  "me", "te", "se", "nos", "os", "le", "les", "mi", "mis", "tus", "su", "sus",
  "nuestro", "nuestra", "nuestros", "nuestras", "suyo", "suya", "mio", "mia",
  "este", "esta", "esto", "estos", "estas", "ese", "esa", "eso", "esos", "esas",
  "aquel", "aquella", "aquello", "aquellos", "aquellas",
  "algo", "alguien", "algun", "alguno", "alguna", "algunos", "algunas",
  "nada", "nadie", "ningun", "ninguno", "ninguna", "otro", "otra", "otros", "otras",
  "todo", "toda", "todos", "todas", "mismo", "misma", "mismos", "mismas",
  "cual", "cuales", "quien", "quienes", "cuyo", "cuya", "cada", "varios", "varias",
  // Verbos auxiliares y copulativos
  "ser", "es", "son", "era", "eran", "fue", "fueron", "sea", "sean", "siendo", "sido",
  "estar", "estan", "estaba", "estaban", "estado", "estoy",
  "haber", "ha", "han", "he", "has", "hay", "habia", "habian", "habra", "hubo",
  "puede", "pueden", "poder", "podria", "podrian", "debe", "deben", "deberia", "deberian",
  "va", "van", "voy", "ir",
  // Adverbios comodín
  "muy", "mas", "menos", "ya", "aun", "todavia", "solo", "bien", "mal", "aqui", "alli",
  "ahi", "entonces", "luego", "siempre", "nunca", "casi", "tan", "tanto", "tanta",
  "poco", "poca", "mucho", "mucha", "muchos", "muchas", "bastante", "etc", "vez", "veces",
  // Relleno de los resúmenes de GPT-4o-mini
  "idea", "hacer", "tener", "tiene", "tienen", "quiero", "quiere", "querer", "seria",
  "posible", "posibilidad", "forma", "manera", "usuario", "importante", "necesario",
  "necesita", "necesidad", "considerar", "crear", "realizar", "cosa", "tipo", "nota",
  "menciona", "mencionar", "sugiere", "propone", "plantea", "hablar", "habla",
  "respecto", "relacionado", "relacionada", "principal", "general",
]);

// Una palabra que cuenta: con fondo (3 letras o más) y que no esté en la lista de vacías,
// ni antes ni después de quitarle el plural (si no, «ideas» → «idea» se colaba).
function palabraUtil(palabra) {
  if (palabra.length < 3 || PALABRAS_VACIAS.has(palabra)) return null;
  // Plural ligero: basta para que «viajes» y «viaje» cuenten como la misma palabra sin
  // meter un lematizador. Solo a partir de 5 letras, para no mutilar «mes» o «gas».
  const raiz = palabra.length > 4 && palabra.endsWith("s") ? palabra.slice(0, -1) : palabra;
  return PALABRAS_VACIAS.has(raiz) ? null : raiz;
}

/** Las palabras con significado de un texto, como `Set`. */
export function tokens(texto) {
  const salida = new Set();
  for (const palabra of normalizar(texto).split(/[^a-z0-9ñ]+/)) {
    const util = palabraUtil(palabra);
    if (util) salida.add(util);
  }
  return salida;
}

// Las palabras de una consulta de búsqueda. Aquí NO se quitan las vacías: quien escribe
// «de» en el buscador quiere encontrar «de», y buscar es por subcadena.
function palabrasConsulta(consulta) {
  return normalizar(consulta).split(" ").filter(Boolean);
}

function textoBuscable(idea) {
  return normalizar(`${idea?.key ?? ""} ${idea?.full_text ?? ""}`);
}

/** La etiqueta con la que se agrupa en los chips. «Trabajo», «trabajo» y « trabajo » son
 *  la misma: el `tag` lo pone GPT al extraer y no es constante con las mayúsculas. */
export function etiquetaDe(idea) {
  return normalizar(idea?.tag) || "sin etiqueta";
}

/** Las ideas que casan con la búsqueda y la etiqueta, en el MISMO orden en que llegan.
 *  Cada palabra de la consulta tiene que aparecer (Y lógico) en el título o en el texto.
 *  La etiqueta se compara con `etiquetaDe`, para que el chip «sin etiqueta» también
 *  filtre. */
export function filtrarIdeas(ideas, { consulta = "", etiqueta = null } = {}) {
  if (!Array.isArray(ideas)) return [];
  const palabras = palabrasConsulta(consulta);
  const etq = etiqueta == null ? null : normalizar(etiqueta);
  return ideas.filter(idea => {
    if (!idea) return false;
    if (etq && etiquetaDe(idea) !== etq) return false;
    if (palabras.length === 0) return true;
    const texto = textoBuscable(idea);
    return palabras.every(p => texto.includes(p));
  });
}

/** Si la búsqueda se explica con el título solo. Cuando no (alguna palabra está solo en
 *  el texto), la tarjeta se enseña desplegada: si no, aparece una idea cuyo título no
 *  tiene nada que ver con lo buscado y no se sabe por qué. */
export function coincideEnTitulo(idea, consulta) {
  const palabras = palabrasConsulta(consulta);
  if (palabras.length === 0) return true;
  const titulo = normalizar(idea?.key);
  return palabras.every(p => titulo.includes(p));
}

/** `[{ etiqueta, cuenta }]`, de la más usada a la menos, y a igual cuenta por orden
 *  alfabético (si no, los chips bailarían de sitio entre cargas). */
export function etiquetasConCuenta(ideas) {
  const cuentas = new Map();
  for (const idea of Array.isArray(ideas) ? ideas : []) {
    if (!idea) continue;
    const etq = etiquetaDe(idea);
    cuentas.set(etq, (cuentas.get(etq) || 0) + 1);
  }
  return [...cuentas]
    .map(([etiqueta, cuenta]) => ({ etiqueta, cuenta }))
    .sort((a, b) => b.cuenta - a.cuenta || a.etiqueta.localeCompare(b.etiqueta, "es"));
}

/** Parte `texto` en tramos marcados y sin marcar para resaltar lo buscado CONSERVANDO el
 *  original: se busca «japon» y se resalta «Japón», con su tilde.
 *
 *  La normalización se hace CARÁCTER A CARÁCTER a propósito. Aplicada a la cadena
 *  entera, NFD cambia la longitud («ó» pasa a ser dos caracteres) y los índices de lo
 *  encontrado ya no apuntan al mismo sitio del original. Así cada carácter normalizado
 *  sabe de qué trozo del original viene. */
export function tramosCoincidencia(texto, consulta) {
  const original = String(texto ?? "");
  const palabras = palabrasConsulta(consulta);
  if (palabras.length === 0 || !original) return [{ texto: original, marca: false }];

  let normal = "";
  const desde = [];   // desde[k]/hasta[k]: el trozo del original del carácter k normalizado
  const hasta = [];
  let pos = 0;
  for (const car of original) {
    const fin = pos + car.length;
    const n = /\s/.test(car) ? " " : sinTildes(car.toLowerCase());
    if (n.length === 0 && hasta.length > 0) {
      // Una marca suelta (texto ya en NFD): se pega al carácter anterior, para que la
      // tilde se resalte con su letra y no se quede sola fuera de la marca. Si es la
      // virgulilla de una «n», vuelve a ser «ñ», igual que en `normalizar`.
      hasta[hasta.length - 1] = fin;
      if (car.charCodeAt(0) === 0x0303 && normal.endsWith("n")) normal = normal.slice(0, -1) + "ñ";
    }
    for (const c of n) {
      normal += c;
      desde.push(pos);
      hasta.push(fin);
    }
    pos = fin;
  }

  const rangos = [];
  for (const palabra of palabras) {
    let i = normal.indexOf(palabra);
    while (i !== -1) {
      rangos.push([desde[i], hasta[i + palabra.length - 1]]);
      i = normal.indexOf(palabra, i + 1);
    }
  }
  if (rangos.length === 0) return [{ texto: original, marca: false }];

  // Los tramos que se tocan o se solapan («viaje» y «aje» dentro de «viaje») se funden:
  // dos <mark> pegados se ven como uno cortado.
  rangos.sort((a, b) => a[0] - b[0]);
  const fundidos = [rangos[0].slice()];
  for (const [a, b] of rangos.slice(1)) {
    const ultimo = fundidos[fundidos.length - 1];
    if (a <= ultimo[1]) ultimo[1] = Math.max(ultimo[1], b);
    else fundidos.push([a, b]);
  }

  const tramos = [];
  let cursor = 0;
  for (const [a, b] of fundidos) {
    if (a > cursor) tramos.push({ texto: original.slice(cursor, a), marca: false });
    tramos.push({ texto: original.slice(a, b), marca: true });
    cursor = b;
  }
  if (cursor < original.length) tramos.push({ texto: original.slice(cursor), marca: false });
  return tramos;
}

function tokensDeIdea(idea) {
  return tokens(`${idea?.key ?? ""} ${idea?.full_text ?? ""}`);
}

function jaccard(a, b) {
  let comunes = 0;
  for (const t of a) if (b.has(t)) comunes++;
  if (comunes < MIN_PALABRAS_COMUNES) return 0;
  return comunes / (a.size + b.size - comunes);
}

/** Cuánto se parecen dos ideas, de 0 a 1: Jaccard de sus palabras con significado
 *  (título y texto). Léxico y a propósito: unos embeddings entenderían sinónimos, pero
 *  cuestan dinero por idea y piden una columna nueva, y esto es para ver de un vistazo
 *  que algo ya se dijo, no para un buscador semántico. */
export function similitud(a, b) {
  return jaccard(tokensDeIdea(a), tokensDeIdea(b));
}

function instante(idea) {
  const t = Date.parse(idea?.created_at);
  return Number.isNaN(t) ? -Infinity : t;
}

/** Junta las ideas que dicen casi lo mismo: `[{ cabeza, miembros, primera }]`.
 *
 *  Union-find sobre todos los pares, así que es TRANSITIVO: si A se parece a B y B a C,
 *  van las tres juntas aunque A y C no lleguen al umbral entre sí — es lo que pasa
 *  cuando una idea se va reformulando con los meses. `cabeza` es la más reciente,
 *  `miembros` van de la más reciente a la más antigua y `primera` es el `created_at` de
 *  la más antigua. Los grupos salen en el orden de su cabeza en la lista, y una idea sin
 *  parecidas es un grupo de una.
 *
 *  Compara todos los pares (O(n²)): con cientos de ideas va sobrado, pero en el
 *  componente va dentro de un `useMemo` para no repetirlo en cada render. */
export function agruparParecidas(ideas, { umbral = UMBRAL_PARECIDAS } = {}) {
  const lista = (Array.isArray(ideas) ? ideas : []).filter(Boolean);
  const conjuntos = lista.map(tokensDeIdea);
  const padre = lista.map((_, i) => i);
  const raiz = i => {
    while (padre[i] !== i) { padre[i] = padre[padre[i]]; i = padre[i]; }
    return i;
  };
  for (let i = 0; i < lista.length; i++) {
    for (let j = i + 1; j < lista.length; j++) {
      const sim = jaccard(conjuntos[i], conjuntos[j]);
      if (sim > 0 && sim >= umbral) {
        const ri = raiz(i), rj = raiz(j);
        if (ri !== rj) padre[rj] = ri;
      }
    }
  }

  const porRaiz = new Map();
  lista.forEach((idea, i) => {
    const r = raiz(i);
    if (!porRaiz.has(r)) porRaiz.set(r, []);
    porRaiz.get(r).push(i);
  });

  const grupos = [];
  for (const indices of porRaiz.values()) {
    // A igual fecha (o sin ella) manda el orden de la lista: sort es estable.
    const ordenados = [...indices].sort((a, b) => instante(lista[b]) - instante(lista[a]));
    const miembros = ordenados.map(i => lista[i]);
    const conFecha = miembros.filter(m => instante(m) !== -Infinity);
    grupos.push({
      cabeza: miembros[0],
      miembros,
      primera: conFecha.length ? conFecha[conFecha.length - 1].created_at : null,
      _pos: ordenados[0],
    });
  }
  return grupos
    .sort((a, b) => a._pos - b._pos)
    .map(({ cabeza, miembros, primera }) => ({ cabeza, miembros, primera }));
}

/** La idea ya guardada que más se parece a `nueva`, o `null` si ninguna llega al umbral.
 *  La propia `nueva` no cuenta (por `id`). En empate gana la MÁS ANTIGUA: el aviso dice
 *  cuándo lo dijiste por primera vez, no la última. */
export function parecidaA(nueva, ideas, { umbral = UMBRAL_PARECIDAS } = {}) {
  if (!nueva || !Array.isArray(ideas)) return null;
  const propia = tokensDeIdea(nueva);
  let mejor = null;
  let mejorSim = 0;
  for (const idea of ideas) {
    if (!idea || (idea.id != null && idea.id === nueva.id)) continue;
    const sim = jaccard(propia, tokensDeIdea(idea));
    if (sim <= 0 || sim < umbral) continue;
    if (!mejor || sim > mejorSim || (sim === mejorSim && instante(idea) < instante(mejor))) {
      mejor = idea;
      mejorSim = sim;
    }
  }
  return mejor;
}

// ── Fechas del widget ────────────────────────────────────────────
// `created_at` es un timestamptz completo («2026-08-03T10:00:00+00:00»): `formatShortDate`
// espera «YYYY-MM-DD» y con esto devolvería «—». Todo va en hora LOCAL.

function fechaValida(fecha) {
  if (fecha == null || fecha === "") return null;   // new Date(null) es 1970, no «sin fecha»
  const d = fecha instanceof Date ? fecha : new Date(fecha);
  return Number.isNaN(d.getTime()) ? null : d;
}

function diasEntre(desde, hasta) {
  const a = new Date(desde.getFullYear(), desde.getMonth(), desde.getDate());
  const b = new Date(hasta.getFullYear(), hasta.getMonth(), hasta.getDate());
  // Redondeo y no truncado: un día de cambio de hora dura 23 o 25 horas.
  return Math.round((b - a) / 86400000);
}

/** «hoy», «ayer», «hace 12 días», «hace 1 mes», «hace 4 meses», «hace 2 años». Cuenta
 *  días de calendario, no horas: algo de anoche a las 23:50 es «ayer» a las 00:10. */
export function haceCuanto(fecha, ahora = new Date()) {
  const d = fechaValida(fecha);
  if (!d) return "";
  const dias = diasEntre(d, ahora);
  if (dias <= 0) return "hoy";
  if (dias === 1) return "ayer";
  if (dias < 30) return `hace ${dias} días`;
  if (dias < 365) {
    const meses = Math.floor(dias / 30);
    return meses === 1 ? "hace 1 mes" : `hace ${meses} meses`;
  }
  const anios = Math.floor(dias / 365);
  return anios === 1 ? "hace 1 año" : `hace ${anios} años`;
}

/** «3 de agosto», con el año solo si no es el de `ahora`. */
export function fechaLarga(fecha, ahora = new Date()) {
  const d = fechaValida(fecha);
  if (!d) return "";
  const base = `${d.getDate()} de ${MONTHS_ES[d.getMonth()]}`;
  return d.getFullYear() === ahora.getFullYear() ? base : `${base} de ${d.getFullYear()}`;
}

/** «3 ago», con el año solo si no es el de `ahora`. Para las filas de un grupo. */
export function fechaCorta(fecha, ahora = new Date()) {
  const d = fechaValida(fecha);
  if (!d) return "";
  const base = `${d.getDate()} ${MONTHS_ES[d.getMonth()].slice(0, 3)}`;
  return d.getFullYear() === ahora.getFullYear() ? base : `${base} ${d.getFullYear()}`;
}
