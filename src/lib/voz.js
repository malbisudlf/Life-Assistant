// Lógica pura del modo llamada. Aquí no se toca ni el DOM ni el audio: lo que necesita
// un WebSocket o un AudioContext vive en vozEleven.js. Esta separación es lo que permite
// probar en vitest la parte que de verdad tiene reglas (dónde se corta una frase, cuándo
// se da por terminada) sin levantar un navegador.

// El troceado que alimenta al TTS. El texto llega del modelo a chorros irregulares —a
// veces media palabra— y mandarlo tal cual daría una voz entrecortada, porque el
// sintetizador entona por trozo: cada corte es una pausa y un cambio de melodía.
//
// Los dos límites tienen motivos opuestos. Por debajo del mínimo la voz suena picada y
// se paga más (cada trozo se factura por su cuenta); por encima del máximo se retrasa la
// primera palabra, que es justo lo que se venía a arreglar. Entre medias, se corta donde
// cortaría una persona: final de frase mejor que coma, y coma mejor que un espacio
// cualquiera.
const CORTES_FUERTES = ".!?…\n";
const CORTES_FLOJOS  = ",;:—";

/** Parte lo acumulado en trozos decibles. Devuelve `{ trozos, resto }`: el resto es lo
 *  que todavía no da para un trozo digno y vuelve al buffer a esperar más texto.
 *
 *  `fin: true` cuando el modelo ya terminó — entonces no hay más texto que esperar y lo
 *  que quede sale como está, aunque sea corto. Sin esto, la última frase de cada
 *  respuesta se quedaba sin decir. */
export function trocearParaVoz(texto, { min = 40, minFrase = 25, max = 140, fin = false } = {}) {
  const trozos = [];
  let resto = texto || "";

  for (;;) {
    if (resto.length < minFrase) break;

    const ventana = resto.slice(0, max);
    // El PRIMER corte que pase del mínimo, no el último: lo que se busca es empezar a
    // hablar cuanto antes. Esperar al último punto de la ventana para mandar dos frases
    // juntas retrasa la primera por nada.
    //
    // Y una frase TERMINADA vale con menos texto que una coma: "Mañana tienes dos clases
    // por la mañana." se dice entera y bien aunque no llegue al mínimo largo, mientras
    // que cortar por una coma tan pronto deja un jirón que suena a tartamudeo.
    let corte = primerIndiceDe(ventana, CORTES_FUERTES, minFrase);
    if (corte < 0 && resto.length >= min) corte = primerIndiceDe(ventana, CORTES_FLOJOS, min);
    // Ni un punto ni una coma en toda la ventana: alguien está dictando una parrafada.
    // Se corta en el último espacio antes del máximo — a mitad de palabra, nunca.
    if (corte < 0 && resto.length > max) corte = ventana.lastIndexOf(" ");
    if (corte < 0) break;

    const trozo = resto.slice(0, corte + 1).trim();
    if (trozo) trozos.push(trozo);
    resto = resto.slice(corte + 1);
  }

  if (fin) {
    const ultimo = resto.trim();
    if (ultimo) { trozos.push(ultimo); resto = ""; }
  }
  return { trozos, resto };
}

function primerIndiceDe(texto, caracteres, desde) {
  for (let i = Math.max(0, desde - 1); i < texto.length; i++) {
    if (caracteres.includes(texto[i])) return i;
  }
  return -1;
}

/** Lo que se le manda al sintetizador no es lo que se pinta en pantalla. Un asterisco de
 *  markdown o una URL se leen LITERALMENTE, y "hache te te pe dos puntos barra barra" en
 *  mitad de una respuesta es de lo más desconcertante que puede pasarte por teléfono. */
export function textoParaVoz(texto) {
  return (texto || "")
    .replace(/```[\s\S]*?```/g, " ")            // bloques de código: impronunciables
    .replace(/`([^`]*)`/g, "$1")
    .replace(/!?\[([^\]]*)\]\([^)]*\)/g, "$1")  // enlaces: se dice el texto, no la URL
    .replace(/https?:\/\/\S+/g, " ")
    .replace(/[*_#>|]/g, " ")
    .replace(/\s+/g, " ")
    .trim();
}

/** Saca los eventos completos de lo que lleve leído del stream SSE de `/jarvis/voz`.
 *
 *  Devuelve `{ eventos, resto }`. El resto importa: un `read()` no respeta las fronteras
 *  de los eventos, así que lo normal es acabar con medio evento colgando. Intentar
 *  parsear eso tira el turno entero por un trozo que iba a completarse en el siguiente
 *  read. Un evento está completo cuando aparece la línea en blanco que lo cierra. */
export function partirEventosSse(buffer) {
  const eventos = [];
  const partes  = (buffer || "").split("\n\n");
  const resto   = partes.pop() ?? "";
  for (const bloque of partes) {
    let tipo = "", datos = "";
    for (const linea of bloque.split("\n")) {
      if (linea.startsWith("event: ")) tipo  = linea.slice(7).trim();
      else if (linea.startsWith("data: ")) datos += linea.slice(6);
    }
    if (!tipo) continue;
    try { eventos.push([tipo, JSON.parse(datos || "{}")]); }
    catch { /* un evento ilegible se salta: mejor perder uno que el turno */ }
  }
  return { eventos, resto };
}

/** Cuánto audio queda por sonar, en segundos. El reproductor programa los trozos por
 *  adelantado sobre el reloj del AudioContext, así que "queda algo" no es "la cola tiene
 *  elementos": es que el final programado está por delante del reloj. */
export function segundosPendientes(finProgramado, ahora) {
  return Math.max(0, (finProgramado || 0) - (ahora || 0));
}

/** ¿Esta carga de la página viene de contestar al aviso del móvil?
 *
 *  El aviso de «hay un arreglo esperando permiso» abre el dashboard con `?llamada=1`, y
 *  eso es lo que convierte una pestaña en una llamada entrante. Se mira la query y no el
 *  hash porque el hash se lo come el `scrollRestoration` de algunos navegadores al
 *  volver atrás, y una llamada que aparece sola al navegar es peor que una que no
 *  aparece. */
export function llamadaEntranteDeUrl(busqueda) {
  try {
    return new URLSearchParams(busqueda || "").get("llamada") === "1";
  } catch {
    return false;   // una query rota no abre una llamada
  }
}

/** La primera frase al descolgar.
 *
 *  La escribe el backend (`_apertura_despliegue` o `_apertura_sesion`, según por qué
 *  suene), que es quien sabe qué hay pendiente; aquí solo se decide el respaldo para
 *  cuando la pantalla se abre sin nada que anunciar — el aviso llegó tarde, ya se
 *  decidió desde otro sitio, o alguien guardó el enlace. Descolgar y oír silencio
 *  parecería que la llamada se ha roto.
 *
 *  El respaldo no nombra el despliegue aunque ése fuera el primer motivo por el que esto
 *  existió: desde que el canal admite avisos de sesión, decir «ya no hay nada esperando
 *  permiso» sería contestar por un motivo que igual no era el de esta llamada. */
export function aperturaDeLlamada(pendiente) {
  const dicha = (pendiente?.apertura || "").trim();
  if (dicha) return dicha;
  return "Ya no hay nada pendiente. ¿Te ayudo con otra cosa?";
}

/** El juez del barge-in: decide, mirando la energía del micrófono, si te has puesto a
 *  hablar encima de Jarvis. Puro y con el reloj por parámetro para poder probarlo sin
 *  micrófono ni temporizadores; quien lo alimenta es `vigilarInterrupcion` en
 *  vozMicro.js.
 *
 *  Las tres reglas salen del mismo miedo, que es cortar a Jarvis cuando NADIE ha
 *  hablado:
 *
 *  - **Sostenido, no instantáneo.** Una puerta, una tos o un golpe en la mesa pasan el
 *    umbral durante una muestra. Se exige voz seguida (`msSostenidos`) y cualquier
 *    muestra por debajo reinicia la cuenta, que es justo lo que una sílaba suelta no
 *    aguanta.
 *  - **Con gracia al empezar.** Las primeras décimas tras arrancar la voz no cuentan: el
 *    micro se abre con la cola de tu propia frase todavía en el aire y el eco del
 *    altavoz aún sin domar por la cancelación del navegador.
 *  - **Una sola vez.** En cuanto dispara se da por gastado. Quien lo usa corta la voz y
 *    tira el detector; que volviera a disparar solo serviría para cortar dos veces.
 *
 *  El umbral es la pieza delicada y por eso entra por parámetro: si la cancelación de
 *  eco del dispositivo no da abasto, Jarvis se oye a sí mismo y se interrumpe solo, y el
 *  remedio es subirlo (lo hace la llamada sola, ver `interrumpirAJarvis`). */
export function detectorDeHabla({ umbral = 0.055, msSostenidos = 300, msGracia = 400 } = {}) {
  let arranque  = null;   // primera muestra: la gracia se cuenta desde aquí
  let desde     = null;   // principio del tramo por encima del umbral
  let gastado   = false;

  return {
    /** `true` la única vez que decide que estás hablando. */
    mira(rms, ahora) {
      if (gastado) return false;
      if (arranque === null) arranque = ahora;
      if (!(rms >= umbral)) { desde = null; return false; }   // NaN incluido
      if (desde === null) desde = ahora;
      if (ahora - arranque < msGracia) return false;
      if (ahora - desde < msSostenidos) return false;
      gastado = true;
      return true;
    },
  };
}

/** La energía de un trozo de audio, entre 0 y 1. Es la misma media cuadrática que usa el
 *  VAD del backend para el teléfono (`_rms`), aquí sobre muestras ya normalizadas. */
export function rmsDeMuestras(muestras) {
  if (!muestras || !muestras.length) return 0;
  let suma = 0;
  for (let i = 0; i < muestras.length; i++) suma += muestras[i] * muestras[i];
  return Math.sqrt(suma / muestras.length);
}
