<!-- Parte de la guía del repositorio. El índice y las reglas que aplican
     SIEMPRE están en CLAUDE.md, en la raíz. -->

## Frontend: cómo está organizado Dashboard.jsx

Un solo fichero, navegable por sus banners (`grep "── " src/components/Dashboard.jsx`):
LOGIN SCREEN → HELPERS → ESTILOS GLOBALES (`GLOBAL_CSS`, variables CSS `--bg`,
`--accent`...) → `DateInput`/`TimeInput` → COMPONENTE PRINCIPAL (estados, efectos,
`renderWidget`, skeleton, modo simplificado móvil, modales, panel de clases).

No hay router ni gestor de estado: es un componente con `useState`/`useEffect`.

### Autenticación en el cliente

Login por contraseña (input con `inputMode="numeric"` → teclado numérico en móvil) →
JWT en `localStorage` (`la_token`, 30 días) → cabecera `Bearer` en todas las llamadas.

- **Dónde vive**: `src/lib/api.js`. Estaba dentro de `Dashboard.jsx` y se sacó cuando la
  zona dev (`docs/ZONA_DEV.md`) necesitó lo mismo: duplicarlo habría dejado DOS sitios
  que saben cómo se autentica el cliente, y el día que cambie el esquema uno se queda
  atrás sin avisar.
- **`apiFetch()`**: wrapper de `fetch` que, ante un 401 con sesión activa, borra
  `la_token` y recarga. Úsalo para toda llamada autenticada al backend.
  **Solo recarga si había token**: muchos `useEffect` de carga inicial se ejecutan al
  montar aunque no haya `la_token` y reciben un 401; cuando `apiFetch` recargaba siempre,
  eso era un bucle infinito de recargas (pantalla de login parpadeando, sin poder pulsar
  nada — visible sobre todo en móvil).
- **`apiFetch()` no lanza con un 4xx ni con un 5xx**: devuelve la respuesta y ya. Un
  `try/catch` alrededor no se entera de que el backend ha dicho que no: mira `r.ok` (y en
  los borrados, `borradoConfirmado()`, que también mira el `{ok: false}` con que
  respondían 200 antes de pasar a 502). Qué frase
  merece cada fallo está en `src/lib/respuestas.js` (`textoErrorApi`, `mensajeErrorLogin`,
  `leerCalendario`). Un fallo al cargar un widget se pinta como fallo, con su «Reintentar»,
  nunca como lista vacía (ver `docs/BUGS_HISTORICOS.md`).
- **`authHeaders()` / `jsonHeaders()`**: única forma de construir las cabeceras de
  una llamada autenticada (la segunda añade `Content-Type: application/json`). No
  vuelvas a escribir `localStorage.getItem("la_token")` suelto en un handler — por
  eso había 28 lecturas repetidas del mismo valor.
- **URL del backend**: `VITE_API_URL` o el default de `src/lib/api.js`, que es el
  dominio del backend en `caja` (tras el Cloudflare Tunnel). En local, apunta
  `VITE_API_URL` a `http://localhost:8000` (recuerda que el CORS del backend solo
  permite `localhost:5173` y el dominio de Vercel).

### PWA y carga inicial

- **PWA**: instalable en la pantalla de inicio y arranca sin barra del navegador
  (`display: standalone`). Ficheros en `public/`: `manifest.webmanifest`, `sw.js`
  (service worker network-first para el shell del mismo origen; **ignora la API en otro
  dominio** y las peticiones no-GET), `icon.svg` + PNG `icon-192`/`icon-512` y
  `apple-touch-icon` (180). El SW se registra en `src/main.jsx` **solo en producción**
  (`import.meta.env.PROD`) para no interferir con `npm run dev`. Los PNG se generan
  rasterizando `icon.svg`: regenéralos si cambia el icono.
- **Skeletons**: mientras llega la primera carga se muestra `renderBootSkeleton()`
  (cards con shimmer, clase `.la-skel`); si tarda más de 4s aparece el aviso
  "Despertando el servidor…" (`slowBoot`). Nació para el arranque en frío de Fly, que
  ya no existe: el backend vive en `caja` desde el 2026-09-20 y no se duerme. Hoy lo que
  lo dispara es un despliegue en curso (`desplegar.sh` para el backend 1-2 minutos) o
  la red y el túnel lentos. No afines el umbral pensando en un arranque en frío.

### Widgets

Definidos en `ALL_DEFAULT_WIDGETS`. Ids: `timeline`, `weather`, `upcoming`, `entregas`,
`training`, `ideas`, `clothing` (Conteo ropa), `acciones_pc` (Streaming PC),
`health_wellness`, `health_sleep`, `health_heart`, `health_hrv`, `health_activity`,
`health_workouts`, `health_hub` (Salud), `jarvis`, `siguiente` (Lo siguiente, ver su
sección más abajo), `dia_linea` (El día, también con sección propia), `finanzas`,
`casa`, `alarmas` y `noche` (Anoche). Cada uno se renderiza en `renderWidget(id)`, y
**todo id nuevo va también en `DEFAULT_COLUMNS`**: si falta, reaparece en la izquierda
al reconstruir una config guardada.
La configuración (visibilidad, columna, orden, tamaño, splits) se persiste en
`localStorage`, con selección independiente en modo completo (`la_widget_config`) y
simple (`la_simple_widget_config`).

**Un widget nuevo entra en su sitio, no al final** (`fusionarConfigWidgets`, en
`helpers.js`, con tests). La config guardada no lo conoce, así que al cargarla se inserta
**después del id más cercano que le precede en `ALL_DEFAULT_WIDGETS` y ya está en la
config** (o al principio si no hay ninguno). Antes se añadía al final: un widget pensado
para ir arriba acababa al fondo de la columna para cualquiera con una config guardada, que
es todo el mundo. Así que el orden de `ALL_DEFAULT_WIDGETS` importa también para quien ya
tiene la suya: ahí es donde aparecerá lo nuevo.

Qué hace cada uno:

0. **Jarvis (`jarvis`)** — chat con el asistente. El componente es tonto a propósito
   (`JarvisChat`, a nivel de módulo): pinta mensajes y avisa hacia arriba; toda la
   decisión vive en el backend. El botón 🎙 usa el reconocimiento de voz del NAVEGADOR
   (`SpeechRecognition`), que es gratis y no sale del dispositivo — no Whisper, que se
   paga por minuto y no compensa para dictar una frase. Donde no exista, el botón no
   aparece y se escribe; no hay respaldo de pago. La voz de SALIDA es el espejo: el
   botón 🔊 (`la_jarvis_voz`) lee las respuestas con `speechSynthesis` del navegador
   (`elegirVozEspanola`/`textoHablable` en helpers), no con un TTS de pago. El toggle
   habla desde el propio toque a propósito: iOS solo desbloquea el audio dentro de un
   gesto del usuario. Las acciones que Jarvis propone pero
   no ejecuta salen como un botón de confirmar cuya etiqueta la construye
   `jarvisEtiquetaAccion` con los ARGUMENTOS reales, no con lo que el modelo haya
   redactado: hay que poder ver qué se aprueba. Cuando la acción va contra un id (borrar
   un evento, una nota), la etiqueta lo **traduce al nombre real** con lo que el
   dashboard ya tiene cargado (`contexto`): un id de Graph es ilegible, y el nombre no
   puede venir del modelo, que es justo de quien hay que desconfiar ahí. Si el id no está
   en lo cargado, se dice — no se calla. Una etiqueta puede ocupar varias líneas
   (`reservar_bloques`, una por bloque), por eso el recuadro va con `white-space:
   pre-line`. Al confirmar, el chat (y la voz) dicen `dile_al_usuario_literalmente` si la
   herramienta lo trae, con «Hecho.» de respaldo: una reserva a medias tiene que decir
   qué no entró.

   **Modo llamada (📞)**: hablar seguido, sin pulsar enviar. Escucha en continuo →
   detecta el fin de frase → manda → contesta en voz → vuelve a escuchar, hasta que
   cuelgas (botón, o decir "adiós"/"cuelga": `esFinDeLlamada`). Cuatro cosas lo sostienen
   y ninguna es opcional:
   - **El micro se cierra mientras Jarvis habla** (`hablandoRef`). Por altavoz se oye a sí
     mismo, se transcribe y se contesta solo: una llamada infinita que además se paga.
   - **El fin de frase lo decide el SILENCIO** (`JARVIS_SILENCIO_MS`), no el `isFinal` del
     navegador, que llega a la primera pausa y trocearía una frase pensada en tres.
   - **La sesión se reabre sola en `onend`**: Chrome la corta cada pocos segundos y sin
     eso la llamada se queda sorda sin avisar. Un permiso denegado, en cambio, cuelga con
     el motivo: reintentar en bucle no lo arregla.
   - **El ciclo se invoca a través de `cicloRef`**, un ref al último render. Los callbacks
     del reconocimiento nacen una vez y viven muchos renders: sin esa indirección leerían
     el `jarvisMensajes` de cuando empezó la llamada y Jarvis perdería el hilo de su
     propia conversación a partir del segundo turno.
   El saludo inicial se dice DENTRO del toque del botón (iOS solo desbloquea
   `speechSynthesis` dentro de un gesto) y el cliente manda `voz: true`, que es lo que
   hace al backend contestar en dos frases.
1. **Hoy (`timeline`)** — mezcla eventos de Outlook + calendario de clases, ordenados
   por hora, con nodos activos/pasados/futuros y calculador de hora de salida por Google
   Maps. Al pulsar "¿A qué hora salir?" aparece un selector inline 🚗/🚶 antes de
   calcular; el resultado muestra el icono del modo elegido y un botón ↺ para recalcular.
2. **Clima (`weather`)** — Open-Meteo, con la geolocalización del navegador si la hay.
3. **Próximos eventos (`upcoming`)** — próximos 7 días (máx. 5). "+ Evento" abre un modal
   para crear un evento en Outlook vía Graph.
   - **Edición**: el icono ✎ junto a cada evento (y junto al evento activo del timeline)
     abre el mismo modal precargado (`openEditEvent`), en modo edición. El selector de
     calendario se oculta al editar (el `PATCH` no soporta mover de calendario).
   - **Selector de fecha y hora 100% custom** (`DateInput`/`TimeInput`): los
     `<input type="date">`/`<input type="time">` nativos dependen del locale del SO (en
     un Windows con locale americano, `08/06/2026` se interpretaba como mes/día → eventos
     creados en la fecha equivocada). Los componentes propios parsean siempre
     `DD/MM/AAAA` y formato 24h, independientes del navegador.
     `TimeInput` es un combobox editable (texto libre + lista de 30 en 30 min,
     `TIME_OPTIONS`), regex `/^(\d{1,2})[:hH]?(\d{2})?$/`. `DateInput` valida fechas
     reales con round-trip por `new Date()` y convierte a/desde ISO internamente.
   - La fecha sugerida por defecto se calcula con componentes locales
     (`getFullYear()/getMonth()/getDate()`) — `toISOString()` aquí desplaza un día hacia
     atrás en `Europe/Madrid` por la conversión a UTC.
   - Al cambiar la hora de inicio, la de fin se autoactualiza a inicio + 30 min.
4. **Entregas (`entregas`)** — eventos con el marcador `VITE_ENTREGAS_MARKER` (📚) en el
   título, buscados en **ambos** calendarios (`allEvents` + `classEvents`). Incluye los
   de hoy y los futuros.
   Desde octubre de 2026 esos eventos los crea la sincronización con Moodle
   (`docs/MOODLE.md`), y al entregar pasan de 📚 a ✅, que es lo que los saca del widget:
   el widget no sabe nada de Moodle, y así tiene que seguir.
5. **Finanzas (`finanzas`)** — la cartera de Indexa Capital: valor total, plusvalía en
   euros y en porcentaje, cuánto se movió desde el último día con dato, la gráfica del
   valor frente a lo aportado (`GraficaAportado`, con rango, tooltip, reparto del cambio y
   hitos), barra de mezcla por clase de activo y el detalle de posiciones plegado. El ↻
   salta la caché del backend. Un dato que Indexa no dio sale como `—`, nunca como 0 €
   (ver `docs/FINANZAS.md`).
6. **Entrenamiento (`training`)** — sesiones desde el último cobro, euros pendientes,
   formulario de añadir sesión, botón de cobro.
7. **Ideas (`ideas`)** — grabación de audio (Whisper) **o** texto escrito ("✎ Escribir
   idea") → extracción con GPT-4o-mini → Supabase. Si la nota señala una cita, ofrece un
   chip para crear el evento (nunca lo crea solo).

   Para que no sea una lista sin fondo, todo en el cliente con lo que ya devuelve
   `GET /ideas` —sin endpoint, columna ni llamada de pago—. La lógica pura vive en
   `src/lib/ideas.js` (tests en `tests/frontend/ideas.test.js` y el widget montado en
   `ideasWidget.test.jsx`):
   - **Buscador** (a partir de 5 ideas): sin tildes ni mayúsculas, busca en título y
     texto, y exige todas las palabras. La «ñ» NO se pliega a «n» («año» no es «ano»).
     Resalta lo encontrado conservando el original (`tramosCoincidencia` normaliza
     carácter a carácter: NFD sobre la cadena entera cambia la longitud y los índices
     dejan de cuadrar). Si el acierto está solo en el texto, la tarjeta sale desplegada:
     si no, aparece una idea cuyo título no explica por qué está ahí.
   - **Chips de etiqueta** con su cuenta (a partir de 2 etiquetas). El `tag` lo pone GPT
     y no es constante con las mayúsculas: «Trabajo» y «trabajo» son el mismo chip. Con
     filtro activo se ve «X de Y ideas», y sin resultados «Nada coincide…» con «Quitar
     filtros».
   - **Agrupar parecidas** (interruptor, `la_ideas_agrupar`): Jaccard léxico sobre
     `key` + `full_text`, quitando palabras vacías y el relleno típico de los resúmenes de
     GPT (sin eso, dos ideas cualesquiera se parecen), con un mínimo de
     `MIN_PALABRAS_COMUNES` en común y `UMBRAL_PARECIDAS` (provisional, se afina con las
     ideas reales). Es transitivo (union-find): A~B y B~C son un grupo. **Solo cambia cómo
     se ve**: nunca borra ni fusiona, y apagado la lista es exactamente la de `GET /ideas`.
     No son embeddings a propósito: costarían dinero por idea y pedirían una columna nueva.
   - **«Ya lo dijiste»**: al capturar (voz o texto) algo que se parece a una idea ya
     guardada, una franja encima del chip de cita lo dice con la fecha de la anterior.
     «Ver» abre su grupo; «Vale» la cierra. Se compara contra la lista de ANTES de añadir
     la nueva, leída de `ideasRef` (el `onstop` del grabador vive desde que empezó a grabar
     y leería un `ideas` viejo).
   - Se ven **10** (`IDEAS_VISIBLES`) y un «Ver N más»; cambiar búsqueda o etiqueta vuelve
     al recorte. `openIdea` guarda el **id**, no el índice: con un filtro, el índice
     abría otra tarjeta.
   - **Borrado en dos toques**: el ✕ pasa a «¿Borrar?» y el segundo toque borra; se
     cancela a los 4 s o tocando fuera. Con los grupos desplegados hay varias ✕ juntas.
   - **Estados**: «Cargando ideas…», y si `GET /ideas` falla, «No he podido cargar las
     ideas.» con «Reintentar» — nunca «Sin ideas todavía», que es lo que decía antes
     cuando el backend no contestaba.
8. **Conteo ropa (`clothing`)** — **TEMPORAL**, ver abajo.
9. **Streaming PC (`acciones_pc`)** — encender el PC (WOL), lanzar el job de streaming,
   apagar/suspender. Barra de progreso con polling cada 2s y badge de estado
   (pending/claimed/running) con los stages en nombres legibles. `abrirStreaming()` crea
   el job **primero** y pide el WOL y el relanzado **después** (con `caja` el agente
   arranca en el acto y, si lo hiciera antes que el job, vería la cola vacía), mira el
   `r.ok` de cada llamada y enseña el `detail` del backend si algo falla; una referencia
   impide que un doble toque cree dos jobs. Mientras espera, sondea `GET /pc/estado` cada
   4 s y pinta una línea con lo que ha hecho `caja` («caja: agente lanzado», «caja no
   llega al PC: …»). Esa línea cruza el estado con el `motor` que devolvieron
   `/wake-pc` y `/relaunch-agent` (`despertarAgente()` los guarda): si el estado dice
   `caja_sin_montar`, o alguna respuesta dijo `"ha"` con el estado diciendo `caja`, el
   pedido no llegó a `caja` y se dice en rojo, no «trabajando en el pedido…». Pasados `AGENTE_ARRANQUE_MAX_MS` sin que el agente reclame el job,
   lo dice en vez de seguir «encendiendo». El motivo de un fallo sale del mensaje de la
   etapa `job_done` (`cierreDeJob`/`motivoFalloJob`, helpers): el job no guarda ningún
   `error_reason`. La lógica de esas líneas está en `src/lib/helpers.js`, con sus tests en
   `tests/frontend/streamingPc.test.js`.
10. **Bienestar (`health_wellness`)** — toggle "Semana | Hoy". Puntuación 0–100 +
    insights + recomendación + hora de la última sync. Al final, el mini-apartado
    **Composición corporal**: peso (`weight_body_mass`), % grasa y masa magra en la misma
    fila, cada uno con flecha ↑↓ coloreada. La del peso se colorea según si te acercas o
    alejas del objetivo configurado en ⚙; la barra de progreso indica la **distancia real**
    ("faltan X.X kg", no solo un %) y se colorea según la tendencia reciente
    (`weightDelta`): verde si te acercas, rojo si te alejas.
11. **Sueño (`health_sleep`)** — noche anterior: duración, fases (profundo/REM/core/
    despierto) con tooltips, puntuación 0–100 y resumen de las últimas 7 noches. Botón
    **"Anular noche"** para excluir noches con datos malos (p. ej. el Watch en carga);
    las anuladas se omiten de todos los cálculos. Cada barra del historial es clickable
    para excluir/restaurar. El flag vive en `extra.excluded` de Supabase.
12. **Freq. cardíaca / HRV / Actividad / Entrenamientos AW** — sparklines y listas de
    detalle (ocultos por defecto; el hub de salud los reutiliza).
13. **Salud (`health_hub`)** — widget compacto con veredicto general + top conclusiones;
    al pulsar abre el modal `healthModalOpen` con TODAS las conclusiones por dominio + los
    widgets de salud de detalle reutilizados vía `renderWidget`.

**Motor de conclusiones**: lógica pura y testeada en `helpers.js` —
`healthConclusions` (exprime todas las métricas del Watch y devuelve conclusiones
`{domain, tone, text}`) y `healthOverall` (veredicto), apoyándose en
`seriesTrend`/`trendDirection`/`bedtimeHrvInsight` y en `pairByDate`/`splitCompare`
para los cruces entre series.

- **Todas las ventanas van por FECHA REAL, nunca por número de registros.**
  `seriesTrend` y las medias de `healthConclusions` filtran por rango de fechas contra
  un `hoy` inyectable. Con la serie agujereada —lo que deja un mes sin llevar el reloj—
  `slice(-7)` no da los últimos 7 días: da las últimas 7 MEDIDAS, que pueden abarcar
  meses, y `slice(-30)` puede abarcar el histórico entero, con lo que la "media de 7d" y
  la de "30d" acaban siendo casi el mismo dato y sale una tendencia de comparar algo
  consigo mismo. Es el bug que ya se corrigió en el correo (`_media`), aquí un piso más
  arriba y peor, porque estas frases AFIRMAN. Una serie sin fechas utilizables mantiene
  el conteo por registros, que es lo único que se puede hacer sin fechas.
- **Una tendencia necesita fondo a los dos lados** (`nCorto >= 3` y `nLargo >= 7`). Con
  menos, se dice el valor y sobre cuántas noches se apoya, en vez de un porcentaje.
- **Las conclusiones saben cuándo NO se pudo medir**: `healthConclusions(datos, now,
  { reloj })` recibe el `reloj` de `/health/metrics` y añade un dominio "Reloj" que dice
  cuántas noches de la semana se llevó puesto, avisa de la racha y —aparte— de los días
  en que no llegó nada, que no son lo mismo. La CLASIFICACIÓN de métricas (qué necesita
  reloj de día y qué de noche) **se queda en el backend** y viaja en `reloj.fuentes`:
  repetirla aquí daría dos listas que se desincronizan a la primera métrica nueva. Los
  helpers del lado JS son `relojPuesto`/`relojCobertura`/`relojRachaSinReloj`.

- **Cruces entre series**: todos salen del catálogo `_CRUCES` y los ejecuta
  `healthCorrelations()`. No los escribas a mano sueltos: el mismo cruce se usa con
  DOS ventanas —los últimos 30 días para las conclusiones del día a día, y hasta un
  año para el panel "Patrones a largo plazo" del modal— y tenerlos en un solo sitio
  es lo que evita que las dos versiones se desincronicen y lleguen a decir cosas
  contrarias en la misma pantalla. La palanca que las separa es `minPorGrupo` (3
  para el día a día; `HEALTH_MIN_MUESTRA_PATRONES` para la ventana larga, mucho más
  exigente porque con un año de datos un grupo de 3 días es casualidad, no
  hallazgo). El histórico largo se pide APARTE y solo al abrir el modal
  (`HEALTH_DIAS_PATRONES`): un año de métricas no debe pagarlo la carga inicial.
  Cada cruce lleva su propio `minEfecto` porque no comparten escala: un 3% en la FC
  en reposo es mucho y un 3% en sueño profundo es ruido.

- **Línea base personal** (`baselinePersonal`, `wellnessBaselines`, `BASELINE_DIAS`/
  `BASELINE_MIN_DIAS`): los umbrales fijos premian la constitución, no el progreso — con
  una FC basal de 62 los 8 puntos de "≤50" no se sacan nunca por mucho que se mejore, y
  con 48 se sacan durmiendo mal. Donde eso pasa, el listón sale de los percentiles del
  propio histórico. Cuatro reglas:
  - **Solo en métricas de FISIOLOGÍA** (FC en reposo y FC caminando). Sueño, pasos,
    energía, pisos y de pie son CONDUCTA: puntuarlas contra la propia media es calificar
    en curva, y premiaría a quien lleva un mes en el sofá por un día algo menos sedentario.
    7,5 h de sueño son 7,5 h para cualquiera. La HRV ya iba contra su referencia y no se
    toca; la respiración se queda fuera porque su desviación ya la mide `calcRecoveryMod`
    y meterla aquí dejaría dos reglas para la misma señal.
  - **La ventana se ancla al día QUE SE PUNTÚA, nunca a hoy**, y termina en D-1. Es la
    misma invariante que `_refHrv`, y es lo que hace que `wellnessHistory` sea
    reproducible: sin ella, un día ya puntuado cambiaría de nota cada vez que llegan datos
    nuevos.
  - **Sin `BASELINE_MIN_DIAS` días de medida se cae al umbral fijo**: un p25 sacado de
    cinco medidas no es una línea base, es la más baja de cinco. Los 0 no cuentan (son
    días sin reloj).
  - **El desglose DICE contra cuál se ha puntuado** (`tu rango 55–62 (n=45)` frente a
    `umbral general`). Si añades un componente con baseline, mantén esa distinción: quien
    mira el tooltip tiene que poder saber contra qué se le mide. Los `max` no cambian, así
    que la escala normalizada sigue siendo comparable.

- **Firma de "algo va mal"** (`_firmaMalestar`, `_FIRMA`): FC en reposo arriba + HRV abajo
  + respiración arriba, las tres a la vez. Por separado cada una se mueve por ruido; juntas
  y en la misma dirección son la señal más fiable que da el Watch. Sus umbrales de entrada
  son **más bajos** que los que cada métrica exige para hablar sola: que coincidan es la
  evidencia que a cada una le falta. Tres cosas:
  - **Va en `healthConclusions`, no en `_CRUCES`.** Aquel catálogo describe HÁBITOS
    estables entre dos series y lo ejecuta también el panel de patrones con ventana larga,
    donde esto no significaría nada: una firma de hace ocho meses no es un hallazgo, es una
    gripe que ya se pasó. Esto es un ESTADO de ahora. **Esa es la frontera para señales
    nuevas.**
  - **No afirma sin base**: si alguna tendencia no pasa el listón de fondo o el reloj
    estuvo puesto menos de 3 noches, sale como "no hay base", sin porcentajes. Las noches
    que declara son el mínimo de las tres y de las noches con reloj — no puede presumir del
    respaldo de la métrica mejor medida.
  - Si la firma salta, **se calla el aviso suelto de respiración**: dice lo mismo con menos
    contexto. Los de HRV y FC en reposo se mantienen, porque cada uno aporta su valor real.

La puntuación de bienestar también vive allí: `wellnessBreakdown` construye el desglose y
`scoreFromBreakdown` deriva de él el total normalizado a 100 — **el desglose es la
única fuente de verdad, nunca sumes al score por separado**.
`wellnessHistory` reconstruye la puntuación DIARIA de cada día del histórico con
esas mismas dos funciones (modo diario) a partir de las series que ya sirve
`/health/metrics`: **no hay tabla ni endpoint de histórico, se deriva de lo que ya
hay**. Alimenta la sparkline de "Evolución" del widget de bienestar. Si añades un
componente a `wellnessBreakdown`, añádelo también al mapa de series de
`wellnessHistory` o los días antiguos puntuarán sobre menos componentes que hoy.
Las métricas esporádicas (VO₂max, % grasa, recuperación cardio) arrastran su último
valor conocido hasta cada fecha, y la referencia de HRV se ancla a la ventana
D-14..D-8 de ese día, no a hoy: así cada día puntúa como habría puntuado entonces.
**Cada punto lleva además con qué se midió** (`cobertura`, `sinDatos`, `estadoReloj`,
`sinReloj`, pasándole el `reloj`): normalizar a 100 hace comparables un día de nueve
componentes y otro de cuatro, pero también los deja indistinguibles, y en la sparkline
un día medido a medias se pinta igual que un día malo. `scoreFromBreakdown` devuelve la
`cobertura` por lo mismo, y el tooltip la enseña cuando falta algún componente.
`estadoReloj` es `null` —no `"sin_datos"`— si no hay información de uso del reloj: no
saber es distinto de saber que no llegó nada.

- **`Sparkline`** acepta `objetivo` (dibuja una línea discontinua de referencia,
  metiéndolo en el rango vertical para que nunca quede fuera del gráfico),
  `relleno` (área bajo la curva) y `marcar` (un predicado que señala puntos con un punto
  gris: hoy, los días puntuados sin el reloj puesto). Se usa en el bloque de composición corporal
  para la serie de peso con el objetivo encima.
- **`DonutPatrimonio`** es el donut del reparto del widget de finanzas: una porción por
  sitio donde hay dinero, cada una un `<circle>` con `stroke-dasharray` en vez de un
  `<path>` con arcos. La lógica (qué porciones hay y cuánto pesa cada una) es pura y vive
  en `repartoPatrimonio()`; el detalle de las decisiones está en `docs/FINANZAS.md`.
- **`GraficaAportado`** es la gráfica de la cartera de Indexa en el mismo widget: valor y
  aportado neto con el hueco relleno, eje X por tiempo, selector de rango y tooltip anclado
  arriba. No usa `Sparkline` (que siguen usando salud y bienestar): necesita dos líneas,
  cortes donde falta el dato y un eje que no sea el índice. La lógica es pura
  (`recortarSerie`, `tramosRelleno`, `escalaGrafica`…); el detalle, en `docs/FINANZAS.md`.
- **`alarmas`** es el widget de las alarmas de respaldo: poner hora, ver las puestas con
  su estado y quitarlas. Mientras una suena, el botón «Estoy despierto» se come el widget
  —es lo único que quieres de esa pantalla en ese momento— y se recarga solo cada minuto
  mientras haya algo vivo. La lógica pura (`alarmaEnPalabras`, `alarmaEstadoTexto`,
  `alarmaSonando`) está en `helpers.js`; el resto, en `docs/ALARMAS.md`.
- **`casa`** es el mando de la casa: una línea de estado (presencia y de dónde sale lo que se ve),
  una fila con las escenas y scripts (ocho como mucho) y una rejilla de fichas de los
  favoritos que se tocan para encender, apagar, abrir o bloquear. Pide
  `GET /casa/estado` (una sola petición: catálogo, sugeridos, órdenes recientes y
  presencia) y manda `POST /casa/orden`. La lógica pura está en `src/lib/casa.js`, con
  tests. Lo que conviene saber antes de tocarlo:
  - **De dónde sale lo que se ve** (`fuente` de `/casa/estado`). Con Home Assistant en
    directo (`HA_URL`/`HA_TOKEN` en el backend, ver `docs/HOME_ASSISTANT_FLUJOS.md`) el
    estado es el de HA de hace unos segundos y la línea dice «estado de la casa en
    directo». Si no hay directo, sale del catálogo, que llega cada hora: la línea dice su
    edad y pasa a color de aviso con «puede no ser el real» a partir de hora y media. Si
    hay directo y HA no contesta, lo dice siempre («Home Assistant no contesta: estado de
    la casa de hace…»), aunque el catálogo sea reciente. Todo eso, en `textoFuenteCasa`.
  - **Se manda lo contrario de lo que se VE, nunca `toggle`.** Aunque haya directo, el dato
    puede ser del catálogo (HA no contesta), y el «encendida» de la ficha tener cincuenta
    minutos; si la luz ya estaba apagada, un toggle la encendería justo cuando querías
    apagarla. Con `turn_on`/`turn_off` el peor caso es pedir lo que ya estaba. El cliente
    tampoco manda servicios: manda una acción (`encender`, `abrir`…) y el backend fija el
    servicio.
  - **La ficha dice cómo va su orden**: «pedido…» al instante (el pedido optimista se
    marca antes del fetch). Con directo, la respuesta de `POST /casa/orden` ya trae la
    orden `hecha`. Durante `HECHA_GRACIA_MS` manda **lo pedido**, diga lo que diga la
    lectura: la de justo después de la orden puede ser todavía la de antes (integraciones
    que tardan en reflejar el cambio), y darle prioridad devolvía la ficha a «apagada» con
    el ventilador encendido. `estado_entidad` solo cuenta cuando no hay nada pedido que
    esperar (escenas, play/pausa). Después manda lo que traiga el refresco, que es lo que se
    entera si alguien lo apaga a mano; y la gracia se mide con la hora de la **última
    lectura** (`casa.leidoMs`), no con el reloj del minuto, para que la cierre una lectura
    posterior. Por la cola: «HA la recogió» cuando HA la vacía, nada cuando el estado confirma
    la orden, y «no se ejecutó» —volviendo al estado de antes— si caduca. Los otros dos
    finales del directo, en rojo y en color de aviso (`tonoFase`):
    - **«HA la rechazó»** (`rechazada`, un 502 de `POST /casa/orden` con su `detail` bajo la
      ficha unos segundos, y luego la marca): HA dijo que no, no se ha hecho ni va a
      hacerse. La ficha enseña lo que hay.
    - **«sin confirmar: mira en unos segundos»** (`sin_confirmar`): HA la recibió y no
      contestó. **Sin optimismo** —lo pedido podría ser mentira— y sin reintentar: la ficha
      enseña la lectura, que el backend ha forzado a ser nueva, y si esa lectura dice lo
      pedido el backend la pasa a `confirmada` y la marca se va sola. En una escena, el
      acuse dice «HA no la confirmó» en vez de «✓ enviada» (`acuseActivar`).
  - **Cuándo pregunta** (`intervaloRefrescoCasa`): cada 5 s mientras hay algo en cola o
    recogido o sin confirmar hace menos de dos minutos, y también mientras una orden hecha en directo esté
    en su gracia o acabe de salir de ella (`hayHechaReciente`); cada 10 s con directo configurado (la pregunta no
    sale de la LAN de casa y es lo que hace que el mando no mienta; también si HA no
    contesta, para que el aviso se quite solo cuando vuelva); y cada minuto si solo hay
    catálogo, que no cambia más que cada hora. Siempre **solo con la pestaña a la vista y
    el widget puesto**: oculto no pregunta nada.
  - **Persianas y cerraduras se confirman dentro del widget** («¿Abrir Garaje?»), no con
    `window.confirm`. Un 409 del backend abre la misma confirmación: si el backend exige
    algo que el cliente no había previsto, se pregunta igual.
  - **El PC es de solo lectura** (`PC_ENTIDAD`): cortarle la corriente al switch es tirar
    del cable. Se pinta, atenuado, y no se toca; se suspende por su propio camino.
  - **Los favoritos van en `la_casa_favoritos`** (array de ids), siempre en try/catch. Son
    una comodidad de quien mira, no estado compartido. Sin nada guardado —o si ya no
    existe ninguno— se usan los sugeridos del backend (`SALIR_CASA_ENTIDADES`, o luces y
    ventiladores; nunca `switch` por dominio). «Volver a los sugeridos» borra la clave.
  - Estados: «Cargando…»; «No se pudo leer la casa.» con «Reintentar» (un refresco que
    falla no borra lo que ya se veía); sin catálogo, que HA todavía no lo ha mandado; y con
    catálogo pero sin favoritos, «Elige qué quieres tener a mano».
- **`libros` (Libros)**: una fila por lectura en la tabla `libros`; el estado
  (leyendo / pendiente / terminado) **no se guarda**, sale de `empezado`/`terminado`
  (`estadoLibro` en `src/lib/libros.js`). El título se autocompleta con
  `GET /libros/buscar` (tus libros + Open Library, con espera de 350 ms al escribir); si no
  aparece, se escribe a mano y ya. Tocar la línea de fechas de un libro abre su editor;
  `PATCH /libros/{id}` con `null` borra una fecha.
- **`clothing` (Conteo ropa) es TEMPORAL**: lleva la cuenta de ropa comprada
  hasta saldar el gasto. Cuando ya no haga falta, se quita entero: el `case
  "clothing"` de `renderWidget`, su entrada en `ALL_DEFAULT_WIDGETS`/`DEFAULT_COLUMNS`,
  los estados `clothing*`, el efecto de carga, las funciones `onClothingPhoto`/
  `addClothing`/`deleteClothing`, el overlay de foto, los endpoints `/clothing`
  del backend, los helpers `formatMoney`/`clothingTotals` (+ sus tests) y la tabla
  `clothing` de Supabase (`drop table public.clothing;`).

### Layout de 2 o 3 columnas con resize libre

- 2 columnas (left/right) o 3 (left/center/right) — configurable desde ⚙ → "Columnas".
- `ACTIVE_COLUMNS = { 2: ["left","right"], 3: ["left","center","right"] }` — el número de
  divisores es `numColumns - 1`.
- Cada divisor es arrastrable; las posiciones se guardan en `la_col_splits` (array JSON,
  p. ej. `[0.65]` para 2 columnas o `[0.33,0.67]` para 3). El número de columnas va en
  `la_num_columns`; migra automáticamente la clave antigua `la_column_split`.
- Las columnas usan `flex: (hi-lo) 1 0` (fracción entre splits adyacentes) — **no**
  `width: calc(X%)` — para que la proporción escale con cualquier zoom del navegador.
- Cada widget tiene `column: "left"|"center"|"right"`. Al pasar de 2→3, los de "right"
  van a "center" y la derecha queda vacía; de 3→2, "center" y "right" se fusionan.
- En **modo edición** (Ajustes → "Editar distribución →") aparecen los handles ⠿ (mover
  entre columnas arrastrando) y ◢ (redimensionar ancho y alto del widget). El ◢ solo
  cambia ese widget; el resto de la columna se queda con el espacio libre.
- **Snap guides**: al redimensionar, si un borde se acerca a ≤10px de otro widget aparece
  una línea azul (`--accent2`) y el widget encaja exactamente.
- Config en `la_widget_config` como array `[{id, label, visible, column, widthPct?, height?}]`.
  `widthPct` es una fracción 0–1 relativa al ancho de la columna (no px absolutos), para
  que escale con el zoom.

### Panel ⚙ de ajustes

Botón en el header, dentro del contenedor `.header-controls`, que **sí es visible en
móvil** (cuando el ⚙ estaba dentro de `.header-greeting`, que se ocultaba a ≤640px, en
móvil no había forma de abrir los ajustes; ese bloque ya no existe, el saludo vive en el
momento del día). `Escape` lo cierra; tiene `maxHeight: 90vh`
+ scroll interno para funcionar bien con zoom.

- **Modo de vista** — [Completo] [Simple].
- **Columnas** — [2] [3].
- Mostrar/ocultar widgets (checkbox) y reordenarlos con ↑↓.
- "Editar distribución →" — activa el modo edición del layout.
- Ajustes de entrenamiento: precio/hora, sesiones por cobro, **días de entrenamiento**
  (selector L M X J V S D) e historial de sesiones.
- **Resumen diario** — el interruptor del correo de la mañana ([Activado]/[Desactivado])
  y la pausa con fecha. No va a `localStorage` como el resto de esta lista, y no puede
  ir: quien manda el correo es el backend, que no lo ve (`GET`/`PATCH /brief/ajustes`).
  El estado que se pinta es siempre el que devuelve el backend, nunca el que creíamos
  haber puesto — es él quien decide si una pausa sigue viva.
- **Panel de estado del sistema**: backend, sesión de Outlook, última sincronización del
  Watch, **uso del reloj** (la fila de sync responde "¿llegan datos?", que es la pregunta
  del sistema; esta responde "¿se pudieron medir?", que es la del usuario), agente PC,
  entrenamiento, **Resumen diario** (apagado a propósito y roto se
  parecen mucho desde fuera: en los dos casos el correo no llega) y **Registro** (los
  errores del backend, de `GET /logs`), todo en un mismo sitio. Se recarga al abrir ajustes y con su botón — nunca en un
  intervalo. Las demás filas dicen si algo RESPONDE; la del registro dice si algo ha
  FALLADO, que es distinto y es lo que faltaba. El listado va plegado y se despliega con
  "Ver registro".

**Días de entrenamiento configurables**: en `la_training_days` (array de números 0–6,
`getDay()` de JS: 0=dom … 6=sáb). Default `[1,3,4,0]` (lun/mié/jue/dom). Escalan el score
semanal de entreno: el denominador es `expectedByNow` (entrenos planificados desde el
lunes hasta hoy inclusive), no el objetivo total de 4.

### Modo simplificado (móvil)

Vista alternativa pensada para registrar entrenamientos rápido desde el móvil. Se activa
en ⚙ → "Modo de vista" → [Simple] y se guarda en `la_simple_mode` (`"1"`/`"0"`).

- Reemplaza la grid de widgets por un layout propio (`renderSimple()`) que **reutiliza
  `renderWidget(id)`** → misma estética (fuentes, colores, cards). Pinta los widgets
  visibles de `simpleWidgetConfig` en su orden.
- **«Lo siguiente» es un widget real** (`siguiente`), el mismo del modo completo, y cae
  arriba (justo debajo de Jarvis) también en una config simple ya guardada, por
  `fusionarConfigWidgets`. Antes aquí se describía una "card compacta con el próximo
  evento" que no existía.
- **Se adapta a la orientación** vía `matchMedia("(orientation: portrait)")` (estado
  `orientation`, con listener al girar):
  - **Vertical**: una columna, en el orden de la config, con los de salud reunidos en
    el bloque de pestañas.
  - **Horizontal**: dos columnas — izquierda Entrenamiento + Entregas + salud, derecha
    Hoy (timeline) + Próximos eventos.
- **En la uni y en el gimnasio cambia el orden** (`ordenarPorLugar`, `src/lib/lugares.js`):
  lo de ese sitio sube (en la uni, «Lo siguiente», Hoy y Entregas; en el gimnasio,
  Entrenamiento) y lo de casa baja, con Jarvis siempre el primero. El lugar sale de
  `GET /presencia` (solo en modo simple, cada 5 min con la pestaña visible) y caducado no
  cuenta. Arriba sale «📍 En la uni» con un botón para volver al orden de siempre, que se
  recuerda (`la_orden_por_lugar`): un orden que cambia solo sin decirlo parece un fallo.
  **Solo el modo simple**: el completo es una distribución hecha a mano con arrastrar, y
  moverla sola pelearía con quien la editó.
- **Bloque de salud con pestañas**: en vez de un scroll largo, una barra de pestañas
  (Bienestar · Sueño · Actividad · HRV · FC · Entrenos) que hace
  `renderWidget(simpleHealthTab)`. El estado arranca en `health_wellness`.
- El toggle vive **solo dentro del panel ⚙** (no hay botón en el header). Al entrar en
  modo simple se fuerza `setIsEditMode(false)` para no dejar flotando los controles del
  modo edición.

### Otros elementos fijos (no configurables)

- **Panel de Clases** — sidebar lateral con el horario completo de la semana.
- **Toggle HA/LA** — alterna entre el dashboard y Home Assistant (`VITE_HA_URL` +
  `VITE_HA_DASHBOARD_PATH`).

### El momento del día (cabecera)

Debajo del reloj, una fila que contesta a «¿qué me toca ahora?»: el saludo, una frase y
hasta tres chips que llevan a su widget. Sustituye al «Buenos días / Mikel» que había a
la derecha (y que en móvil se ocultaba). Lo decide **código, no un modelo**:
`momentoDelDia()` en `src/lib/momento.js`, con tests en `tests/frontend/momento.test.js`.
El componente `MomentoDelDia` (a nivel de módulo, como `DepartureWidget`) solo pinta.

- **Nada de llamadas nuevas.** Sale de lo que el dashboard ya tiene cargado (eventos,
  clases, alarmas, parte de noche, salud, reloj, clima y `departureMap`). Se recalcula
  en un `useMemo` que depende de `now`, así que se refresca con el tic del minuto que ya
  existía, sin intervalo propio.
- **`ahora` va siempre por parámetro.** Por eso `momento.js` no usa
  `isActive`/`isFuture`/`isToday`, que leen el reloj real: con ellos no se podrían probar
  los bordes de franja ni el cruce de medianoche.

| Franja | Horas | Qué se dice cuando no hay nada en curso ni pendiente hoy |
|---|---|---|
| mañana | 06:00–12:59 | «No te queda nada más hoy.» / «Hoy no tienes nada en la agenda.» |
| tarde | 13:00–19:59 | Lo mismo, más un chip con el primer evento de mañana |
| noche | 20:00–05:59 | «Mañana empiezas a las 08:00 con …» (de 00:00 a 05:59, «Hoy empiezas…»), o «… no tienes nada en la agenda.» |

El saludo conserva los cortes de siempre (días < 13, tardes < 20, noches). La «jornada
objetivo» de la noche es mañana hasta medianoche y hoy de madrugada.

**Prioridad de la frase** (gana la primera que aplica):

1. **Alarma sonando** (`avisada`/`escalada`): «La alarma está sonando…», en rojo y con un
   único chip «⏰ Estoy despierto». Tapa todo lo demás, chips incluidos.
2. **Agenda cargando**: sin frase, solo el saludo.
3. **`authNeeded`**: «Outlook sin conectar: no sé qué tienes hoy.» y chip a `timeline`,
   donde está el botón de conectar.
4. **Evento en curso**: «Ahora: X hasta las HH:MM.» y chip «Luego …» si hay otro hoy.
5. **Siguiente de hoy** (salvo de madrugada): «X en 25 min» o «X a las 17:00», con
   « · sal a las HH:MM» si la hora de salida ya está calculada.
6. **Noche** y 7. **Mañana/tarde sin nada pendiente**: la tabla de arriba.

Cuentan como «algo a lo que vas» los eventos de Outlook y las clases, **sin** los de todo
el día ni los que llevan el marcador de entregas (son plazos, ya tienen su widget).
**Lo que está en curso y lo siguiente no se calculan aquí**: salen de
`proximoCompromiso()` (`agenda.js`), el mismo cálculo del widget «Lo siguiente», con el
mismo marcador. Cada uno tenía el suyo, con un desempate de solapes distinto (la cabecera
elegía el que empezó el último; el widget, el que acaba antes), y con los dos en pantalla
la cabecera decía «Ahora: A» encima de un widget que decía «Ahora: B». `momento.js` solo
calcula aparte lo que el widget no mira: el primero de la jornada objetivo y de mañana.

**Chips secundarios**, detrás del de la frase y nunca más de tres en total: parte de la
noche con pendientes (`noche`), el sueño de anoche por la mañana (`health_sleep`), lluvia
≥ 50 % en la jornada objetivo (`weather`) y, de noche, la alarma armada más temprana
(`alarmas`). No se avisa de «no tienes alarma»: es el estado de casi todos los días.

Reglas que no se deben romper:

- **Nunca afirma sobre una fuente sin cargar.** «No lo sé» y «no hay nada» se dicen
  distinto: mientras carga la agenda no hay frase, `alarmas === null` no da chip,
  `parteNoche` `null` o `{}` tampoco, y la salud cargando o `sin_datos` no da chip de
  sueño (`sin_reloj` sí: es un hecho). **`authNeeded` también lo pone un error de red en
  `loadEvents`**, así que se trata como «no sé tu agenda», nunca como «día libre».
- **No hay puntuación de sueño aquí.** El chip dice las horas (`sleepHours`) y nada más:
  la puntuación del widget lleva los modificadores de recuperación, y una copia en la
  cabecera acabaría enseñando un número distinto del de abajo.
- **`departureMap` es de solo lectura.** La hora de salida sale si ya la calculaste en el
  widget; la cabecera jamás llama a `fetchDeparture` ni a `/maps/departure`, que es
  Google Maps de pago y se recalcularía cada minuto.
- **Los chips saltan a `[data-card="…"]`**, no a `#widget-wrap-*`, que solo existe en el
  modo completo. En modo simple un chip de salud cambia antes la pestaña
  (`setSimpleHealthTab`) y salta en el frame siguiente. El card destella 1,2 s
  (`.momento-destello`); con `prefers-reduced-motion` el scroll es instantáneo y el
  destello es un borde fijo. `destinoDeWidget()` decide si el widget se está pintando: si
  no (oculto en ⚙, o durante el skeleton), el chip es un `<span>`, no un botón que no hace
  nada.
- **`document.title` dice lo siguiente**: «HH:MM · X — Life Assistant», «Ahora · X — …»,
  «⏰ Alarma — …» o «Life Assistant», y vuelve a este último al desmontar. Así la pestaña
  en segundo plano sirve de recordatorio.
- **Una excepción no tumba el dashboard**: `momentoDelDia` va envuelto en `try` y, si algo
  revienta, devuelve solo el saludo.
- En móvil la frase va en **una** línea con elipsis (el texto completo queda en `title`) y
  los chips se desplazan en horizontal dentro de su fila, sin scroll de página. Para eso
  `.header-momento` pasa a columna **con `flex-wrap: nowrap`**: con el `wrap` de escritorio
  la columna es multilínea, la línea mide lo que la frase entera y la elipsis no llega a
  actuar. Se vio de noche, cuando la frase dice «Mañana empiezas a las…» (ver
  `docs/BUGS_HISTORICOS.md`).

### Derivación de datos de salud

**`datosSalud` (memo)**: toda la derivación de las métricas de salud (~17
`findMetric`, medias, valores de hoy vs. semana) vive en un único `useMemo` justo
antes de `renderWidget`, con `diaActual` en las dependencias además de
`healthData`/`trainingDays`/`bodyGoals` — sin eso, lo que depende del día de hoy
(días desde el último entreno, semana desde el lunes) se quedaría congelado al
pasar la medianoche con el dashboard abierto. Si un widget de salud nuevo
necesita un valor derivado, añádelo al `return` del memo y a su destructuring en
`case "health_wellness"`, no lo recalcules aparte. `healthConclusions`/
`healthOverall` están memorizados aparte (`conclusionesSalud`/`veredictoSalud`):
antes se llamaban dos veces por render, una por el widget compacto y otra por el
modal.

**Nota de sueño: una sola fuente, anclada a su fecha.** `sleepHistory()` (helpers) da una
entrada por noche con su nota ya calculada, y de ahí leen la cabecera del widget de sueño,
sus siete barras (memo `historicoSueno`) y el mapa del año. La penalización de
recuperación compara la HRV/FC en reposo/respiración de la noche contra
`refRecuperacion()`: la media de **D-30..D-1 de esa noche**, respetando el corte de
dispositivo. Antes el widget la calculaba con un `baseline30` que promediaba **todo lo
cargado**, días posteriores incluidos, así que la misma noche puntuaba distinto con 30
días de datos que con 365, y la barra de la última noche podía no coincidir con el número
de la cabecera (cada una tenía su cálculo; el respaldo de "último valor conocido" solo lo
tenía la cabecera). Ese respaldo sigue, dentro de `sleepHistory({ hoy })` y solo para la
fila de hoy. El desglose del tooltip sale de `desgloseNoche()`, que también usa el mapa.

**Colores de las notas: `tramo()` + `TRAMOS_*`.** `TRAMOS_SUENO` (85/70/55),
`TRAMOS_BIENESTAR` (80/65/50) y `TRAMOS_PASOS` (10.000/8.000/6.000) viven en helpers;
`tramo(valor, cortes)` devuelve 0 (mejor) … 3 (peor) y `COLOR_TRAMO`, en Dashboard.jsx,
el color de cada tramo. No vuelvas a escribir `score >= 85 ? … : …` en un widget: así
había tres copias de los mismos cortes. Los dos primeros colores coinciden (`--green` es
`#6aaa82`); en el mapa del año se separan con opacidad (`OPACIDAD_TRAMO_MAPA`).

### Tu año (mapa del modal de salud)

Sección del modal «Análisis de salud», entre «Patrones a largo plazo» y «Detalle»:
dos rachas, un conmutador [Bienestar · Sueño · Pasos], un mapa de 53 semanas × 7 días
(lunes arriba, la última columna es la semana de hoy, lo futuro no se dibuja) y el
desglose del día que se toca. Componente `AnioEnCuadritos`, a nivel de módulo; la lógica
es pura y está en helpers con tests. **No hace ninguna petición**: usa el histórico largo
que ya pide el panel de patrones (`healthLargo`) y el `reloj` de esa misma respuesta
(`healthLargoReloj`), así que comparte sus estados de carga y de fallo.

- **La rejilla no sabe de valores** (`rejillaCalendario`): fechas por `_sumarDias`, nunca
  `Date` local, para que los domingos de cambio de hora no dupliquen ni se coman un día.
- **Cuatro estados de celda** (`estadoCelda`): `medido` (color de su tramo), `sin_reloj`
  (rayado: el valor se conserva y sale en el desglose, pero un día medido con menos
  sensores no se pinta como un día malo), `anulada` (aspa) y `vacio` (solo el borde). En
  sueño, una noche sin fila solo es `sin_reloj` si consta que llegó algo ese día y nada de
  noche; `sin_datos` es no saber y se queda en vacío. En pasos, sin mapa de reloj (o sin
  entrada ese día) se da por medido: no se inventa un «solo con el móvil».
- **El corte de dispositivo se ve y no esconde nada**: una línea «aparato nuevo» en la
  columna del corte; los días anteriores se siguen pintando (el corte solo afecta a las
  referencias, como en todo el módulo).
- **Rachas que no mienten** (`racha`, `rachaSueno`, `rachaPasos`): se recorren por fecha
  real. Un día neutro (sin reloj, noche anulada, sin datos) ni suma ni rompe, y la línea
  dice cuántos hay dentro de la racha actual. Un día medido que no cumple la rompe. Más de
  `RACHA_HUECO_MAX` (7) neutros seguidos también la cortan: tras una semana sin datos no se
  puede afirmar que seguía. Un hoy que aún no cumple es neutro en pasos (la jornada está a
  medias); en sueño no, porque la fila de hoy es una noche ya cerrada — pero un hoy sin
  fila todavía no cuenta para nada. En pasos, un día sin reloj que llega a 8.000 suma (el
  móvil cuenta de menos: si aun así llega, llegó) y uno que no llega es neutro.
- **Un solo `onClick` en el `<svg>`** que elige la celda más cercana al toque, pasando
  `clientX/clientY` a unidades del viewBox. En un móvil de 375 px la celda mide unos 5 px:
  exigir acertar dentro de cada `<rect>` lo haría inusable con el dedo, y partir el mapa
  para agrandarla rompería el año de un vistazo. Cada `<rect>` lleva además su `<title>`
  como tooltip de escritorio.

### Claves de localStorage

Prefijo `la_`: `la_token` (JWT), `la_widget_config`, `la_num_columns`, `la_col_splits`,
`la_notifications`, `la_simple_mode`, `la_body_goals`, `la_training_days`,
`la_simple_widget_config`, `la_jarvis_chat` (la conversación con Jarvis: el backend no
guarda ninguna), `la_jarvis_voz` (si Jarvis contesta en voz alta), `la_ideas_agrupar`
(«Agrupar parecidas» del widget de Ideas, `"1"`/`"0"`), `la_finanzas_rango` (el rango
elegido en la gráfica de finanzas), `la_anio_modo` (el modo del mapa «Tu año»:
`bienestar`/`sueno`/`pasos`), `la_salida_modo` (coche o andando para la hora de salida:
`{porEvento: {clave: modo}, ultimo}`, podado a 50 eventos con `recordarModo`; sin ella, o
si localStorage lanza, se calcula en coche), `la_casa_favoritos` (las fichas del widget
«Casa»), `la_orden_por_lugar` (`"0"` si quitaste el orden del modo simple en la uni o el
gimnasio). Si añades una, mantén el prefijo y el `try/catch` al parsear.

### Reglas de React/ESLint que aplican aquí (plugin react-hooks v7)

- **Nada de `setState` síncrono dentro de `useEffect`.** Para sincronizar estado con
  una prop usa el patrón de ajuste durante el render (así están `DateInput` y
  `TimeInput`):
  ```jsx
  const [prevValue, setPrevValue] = useState(value);
  if (value !== prevValue) { setPrevValue(value); setText(derive(value)); }
  ```
- **`Dashboard.jsx` no puede exportar nada que no sea componente** (regla
  react-refresh). Por eso los helpers puros viven en `src/lib/helpers.js`. Si
  necesitas testear una función del Dashboard, extráela allí.
- **Ningún componente se define dentro del cuerpo de `Dashboard`** (como sí puede
  hacerse con una función auxiliar normal). `DepartureWidget` estaba así y cada
  render de `Dashboard` creaba un TIPO de componente nuevo, así que React
  desmontaba y remontaba todo su subárbol en vez de actualizarlo — con el reloj
  cambiando cada 30s, dos veces por minuto. Los componentes van a nivel de módulo
  (junto a `Sparkline`, `SleepStageTooltip`) y reciben lo que necesitan por props.
- **Cualquier cambio de estado repinta el dashboard entero**, y hay estados que cambian
  mucho: cada tecla del borrador de Jarvis y cada transcripción parcial de una llamada.
  Por eso `JarvisMensaje` y `LineaDelDia` (lo más pesado que no depende de lo que se
  escribe) van en `React.memo`. **Un `memo` solo sirve si sus props mantienen la
  identidad**: `datosLinea` va en un `useMemo` y `cardStyle` sale de `estilosTarjeta`,
  que se crea una vez. Si le pasas a un componente memorizado un objeto o una función
  creados en el render (`datos={{ ... }}`, `onX={() => ...}`), el `memo` deja de hacer
  nada sin avisar. Medido en jsdom con 40 mensajes en el historial, el render por tecla
  bajó de ~28 ms a ~20 ms.
- Los `catch { /* mejor esfuerzo: ignorar */ }` son deliberados (notificaciones,
  parseo de localStorage, llamadas fire-and-forget). Si añades uno, pon el comentario
  dentro o la regla `no-empty` fallará.
- El lint debe quedar a **cero errores y cero warnings**. Se limpió por completo en
  julio de 2026; no dejes que se vuelva a degradar.

### Accesibilidad: teclado y nombres

- **Todo botón que solo enseña un icono lleva `aria-label`** (✕, ↑, →, ⚙…). El `title`
  no basta: el nombre accesible de un botón sale de su contenido, y el `title` solo se
  usa si está vacío, así que un lector de pantalla decía «flecha arriba» veinte veces en
  el panel ⚙. `tests/frontend/accesibilidad.test.jsx` monta el dashboard con sesión y
  falla si aparece un botón cuyo nombre sea solo símbolos. Si el botón es un
  interruptor, `aria-pressed`; si pinta una casilla, `role="checkbox"` + `aria-checked`.
- **Un `<span>` o `<div>` clicable se hace pulsable con `comoBoton()`** (`src/lib/teclado.js`):
  le da `role="button"`, `tabIndex` y Enter/Espacio, sin tocar su aspecto. Cambiarlo por
  un `<button>` movería el estilo (fondo, borde y fuente propios del navegador).
- **El foco del teclado se ve**: `GLOBAL_CSS` quita el `outline` a todos los controles
  (con `!important`), y una regla `:focus-visible` lo devuelve solo a botones y a
  `[role="button"]`. `:focus-visible` no salta con el ratón ni con el dedo, así que eso se
  ve igual que antes. Los E2E buscan los botones por su nombre accesible
  (`getByRole('button', { name })`): si cambias un `aria-label`, búscalo también allí.

## El panel ⚙ y la zona dev

El panel de ajustes tenía dentro el estado del sistema entero (backend, agente,
presencia, avisos, registro, gasto). Eso vive ahora en la zona de desarrollo
(`src/components/dev/`, ver `docs/ZONA_DEV.md`) y en ⚙ queda **una sola línea**: lo peor
que haya, o «todo responde», con un enlace que abre la zona dev.

Lo que hay que saber al tocarlo:

- La zona dev se enciende con un `useState` del propio `Dashboard` y se pinta **en lugar**
  del dashboard, no encima: es una vista, no un modal. El estado del dashboard sigue vivo
  mientras tanto, y por eso puede pasarle por props las filas del semáforo que solo él
  conoce (`filasEstadoDelDashboard`: Outlook, el Watch, el uso del reloj, entrenamiento).
  Las demás se las pide la zona dev por su cuenta con `leerEstadoSistema()`, y la línea
  de ⚙ con **la misma función** (`cargarEstadoSistema`). Vive en
  `src/lib/estadoSistema.js`, aparte de `dev.js` por la regla del chunk de abajo, igual
  que `registro.js`. Hubo una copia a mano en `Dashboard.jsx` que no guardaba `brief`, y
  ⚙ decía «todo responde» con el resumen diario pausado.
- **El resumen y las filas son la misma función** (`filasDeEstado`/`resumenEstado`, en
  `src/lib/dev.js`, con tests). Si añades una señal nueva, sale en los dos sitios sin
  tocar nada más — que es justo lo que evita que el semáforo del móvil y el de la zona
  dev digan cosas distintas.
- **`src/lib/dev.js` no se importa de forma estática en `Dashboard.jsx`.** Con un import
  estático, Rollup mete el módulo entero —casi todo lógica de la zona dev— en el chunk
  principal, aunque el dashboard solo use `resumenEstado`: eran ~14 kB (4 kB con gzip)
  en cada carga. `resumenEstado` se pide con `import()` al abrir ⚙
  (`cargarResumenEstado`), y el módulo comparte chunk con la zona dev. Hay un test que
  lo vigila (`tests/frontend/rendimiento.test.jsx`).

## El widget «Lo siguiente» (`siguiente`)

Responde siempre a lo mismo: qué es lo próximo con hora, cuánto falta y, si hay que
desplazarse, a qué hora salir y cuánto margen queda. Va debajo de Jarvis. La lógica pura
está en `src/lib/agenda.js` (con tests en `tests/frontend/agenda.test.js`); el componente,
`SiguienteCompromiso`, a nivel de módulo junto a `DepartureWidget` y sin estado propio que
dependa del reloj.

- **Qué pinta**: si hay algo en curso, una fila «Ahora · título · acaba en N min»; debajo,
  lo siguiente (título, horas, sitio, etiqueta «clase» si viene del calendario de clases),
  la cuenta atrás grande y, si hay algo en curso, el hueco entre los dos («te quedan 40 min
  libres», «justo después», «se solapa con lo actual»). Los eventos de todo el día, los
  que no tienen hora y las entregas (`marcadorEntregas`, el mismo `VITE_ENTREGAS_MARKER`
  del widget Entregas) nunca son «lo siguiente»: una entrega a las 23:59 es un plazo, y
  como «siguiente» tapaba la reunión de mañana. Con dos en curso, el que acaba antes.
  Mira 7 días (`HORIZONTE_DIAS`), lo mismo que `/calendar/events`. **La cabecera usa este
  mismo cálculo** (ver «El momento del día»): si cambias una regla aquí, cambia las dos.
- **La salida**: «Sal a las HH:MM · duración · distancia · desde …» (el «desde» sale del
  campo `origen` de `/maps/departure`), con una barra fina del margen de la última hora y
  la fase: holgada en el acento, ámbar en los últimos 15 min, «sal ya» y «vas N min
  tarde» en rojo. Una ubicación de Teams, Zoom, un enlace… (`esUbicacionOnline`) dice «En
  línea: no hay que salir» y **no pide nada a Maps**; `DepartureWidget` tampoco lo ofrece
  para esas ubicaciones en «Hoy» y «Próximos eventos». Debajo va `DepartureWidget` en modo
  `compacto`: el botón para calcular fuera de la ventana, el cambio de coche/andando y ↺.
- **Cuándo pide la salida solo**: cuando el siguiente entra en la ventana de 180 min
  (`VENTANA_SALIDA_MIN`, espejo de `SALIR_VENTANA_MIN` del backend, que calcula la misma
  salida para el aviso de «sal ya»; con la caché del backend las dos son una sola petición
  a Google). **Una vez por evento y modo** (`salidaIntentosRef`, un Set de `clave|modo` que
  cuenta también lo pedido a mano), **solo si el widget está visible** en el modo activo,
  después de resolverse la geolocalización (como el clima, para no calcular dos veces) y
  nunca con ubicaciones online. **El tic del reloj no vuelve a pedir**: la fase avanza sola
  con `ahora`, y la hora de salida solo cambia con ↺ o al recargar (que dentro de 10 min
  acierta en la caché del backend). Distance Matrix se paga por petición: un efecto que
  pidiera con cada tic serían dos llamadas de pago por minuto con la pestaña abierta.
- **El resultado va al `departureMap` de siempre** con la clave `ev.id || ev.start`, así
  que «Hoy» y «Próximos eventos» enseñan la misma hora sin volver a pedirla.
- **Error ≠ vacío**: sin Outlook o con `/calendar/events` fallando, la card va con borde
  discontinuo y dice «No sé qué viene…», nunca «Nada con hora en los próximos 7 días». Si
  solo fallan las clases (`clasesFallo`), una nota lo dice. Un 400/502 de Maps se guarda
  como `{error}` y se pinta «No se pudo calcular la ruta a «…»» (`textoErrorRuta`); antes
  `fetchDeparture` guardaba el `{detail}` como si fuera una ruta y salía «Salir a las
  undefined».
- **El modo se recuerda** por evento y como último elegido (`la_salida_modo`); el
  automático usa `modoPara`, y solo lo que elige el usuario se escribe.

## El widget «El día» (`dia_linea`)

Una línea de tiempo con todo lo que le pasó a un día sobre el mismo eje: eventos, sueño,
entrenos, presencia, avisos y casa, un carril por familia. Existe porque el motor de
conclusiones cruza **series** (dos métricas a lo largo de semanas) y esto cruza
**momentos**, que es justo lo que un cruce estadístico no puede ver: que se duerme mal las
noches después de una cita tarde, que los días con el PC encendido hasta las dos el sueño
se hunde.

La lógica pura vive en `src/lib/lineaTiempo.js` (normalizar cada fuente a tramos, repartir
los solapes en subfilas, recortar lo que cruza la medianoche, pasar horas a porcentajes);
el componente, dentro de `Dashboard.jsx` como todos. Lo que conviene saber antes de
tocarlo:

- **El eje mide el día REAL, no 24 h fijas.** Se calcula entre dos medianoches locales
  (1.380 / 1.440 / 1.500 min). Con 1.440 clavado, media jornada de los dos domingos de
  cambio de hora se pintaría corrida.
- **El sueño va a caballo entre dos días.** La fila de `sleep_analysis` se guarda con la
  fecha del DESPERTAR y `extra.sleep_start` es hora de pared: si es ≥ 12:00 la noche
  empezó el día anterior. Para pintar un día se miran **dos** filas, y los cortes se
  marcan (`←` / `→`) en vez de disimularse.
- **«Sin hora» no es «a medianoche».** Lo que ocurrió sin momento conocido (eventos de
  todo el día, sesiones de entrenamiento —la tabla solo guarda `date`—, noches sin
  `sleep_start`) sale como chip debajo del carril, nunca colocado en el eje. Un evento de
  todo el día pintado de 00:00 a 24:00 taparía el carril entero.
- **Fuente ausente ≠ fuente vacía.** Cada carril lleva estado (`ok` / `cargando` /
  `error` / `parcial` / `ausente`): con fuente `ok` y sin datos dice «Nada este día»; en
  cualquier otro caso, borde discontinuo y «no lo sé». La cabecera dice cuántos carriles
  de seis tienen datos, porque un día con dos carriles conocidos no es un día tranquilo.
- **Lo que hoy no se puede pintar, y por qué**: `/calendar/events` solo consulta **desde
  ahora** (no desde la medianoche, a diferencia de `/calendar/classes`), así que al
  retroceder el carril de eventos es `parcial`, y el de HOY va como `ok` con
  `parcial: true`: dibuja lo que hay, pero si no hay nada no dice «Nada este día» —las
  reuniones de la mañana que ya terminaron no han llegado—, dice «no lo sé». Los demás ya tienen
  horas: los avisos desde `GET /avisos/enviados`, la presencia desde
  `GET /presencia/tramos` y la casa desde `GET /casa/acciones`.

### Presencia y casa: los dos carriles que estaban siempre vacíos

Nacieron sin poder dibujar nada y se arreglaron el 2026-09-17, cada uno por un motivo
distinto que conviene no volver a crear:

- **Presencia.** Solo existía el total diario (`time_at_home`), así que el carril se
  quedaba en blanco con una línea de texto debajo — que es exactamente la confusión que
  este widget existe para no crear. Ahora hay tramos con hora
  (`presencia_tramos`, `GET /presencia/tramos`) y se dibujan: en casa en color, fuera
  atenuado, porque estar fuera es el hueco y no un acontecimiento. **Lo que se guarda es
  el CUÁNDO, nunca el DÓNDE**: un booleano y dos horas, sin zona ni coordenadas. (Desde
  octubre de 2026, con una excepción acotada: los tramos del gimnasio y de la uni llevan
  esa categoría y se pintan como sitios, «Gimnasio» / «Uni», no atenuados; ver «Lugares»
  en `docs/JARVIS.md`.) Eso
  acota la reversión de lo que `docs/IDEAS.md` había descartado. El total diario se
  mantiene como resumen debajo: responde otra pregunta (cuánto) y cubre los días
  anteriores a que los tramos existieran.
- **Casa.** No tenía fuente de ninguna clase: la cola de órdenes vive **en memoria y se
  vacía en cuanto Home Assistant se la lleva**, así que media hora después de encender
  una luz no quedaba rastro de que se hubiera encendido. Ahora cada orden se apunta en
  `casa_acciones` al encolarla, y el carril las pinta como instantes —no como tramos: lo
  que consta es lo que se **pidió**, no cuánto estuvo encendida la luz, que es un dato que
  el backend no tiene—. El estado del carril era un `FUENTE_AUSENTE` escrito a mano en el
  componente: si un carril vuelve a nacer así, la pregunta es qué fuente le falta, no qué
  texto poner.

La lección común: **un carril que nunca puede dibujar nada no se lee como «no hay datos»,
se lee como «esto está roto»** — y las dos veces la causa era que el dato se tiraba antes
de llegar a ninguna parte, no que fuera imposible de obtener.

## Panel ⚙: coste y por qué

Dos añadidos al bloque de estado del sistema, los dos con el mismo criterio de siempre —
que lo que no se sabe se diga:

- **Fila «Coste del modelo»** (`GET /gasto?dias=30`): euros del mes, llamadas y % cacheado,
  con desglose por boca al desplegar. Si algún modelo no tiene tarifa configurada, el
  total se marca y se dice cuál falta: un número que no incluye todo el gasto y no lo
  advierte engaña más que no darlo.
- **Los avisos de hoy** (`GET /avisos/enviados`), cada uno con un «¿Por qué?» que pide
  `GET /avisos/{id}/porque` y enseña los valores crudos con los que se disparó. Se piden
  **solo al abrir uno**: son una consulta más y casi nunca se miran. Y «no se ha podido
  consultar» se pinta distinto de «este aviso no guardó con qué se disparó».

