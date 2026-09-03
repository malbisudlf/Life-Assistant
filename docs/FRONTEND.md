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

- **`apiFetch()`**: wrapper de `fetch` que, ante un 401 con sesión activa, borra
  `la_token` y recarga. Úsalo para toda llamada autenticada al backend.
  **Solo recarga si había token**: muchos `useEffect` de carga inicial se ejecutan al
  montar aunque no haya `la_token` y reciben un 401; cuando `apiFetch` recargaba siempre,
  eso era un bucle infinito de recargas (pantalla de login parpadeando, sin poder pulsar
  nada — visible sobre todo en móvil).
- **`authHeaders()` / `jsonHeaders()`**: única forma de construir las cabeceras de
  una llamada autenticada (la segunda añade `Content-Type: application/json`). No
  vuelvas a escribir `localStorage.getItem("la_token")` suelto en un handler — por
  eso había 28 lecturas repetidas del mismo valor.
- **URL del backend**: `VITE_API_URL` o el default de Fly. En local, apunta
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
  "Despertando el servidor…" (`slowBoot`), porque Fly escala a cero y el arranque en
  frío tarda 10–15s.

### Widgets

Definidos en `ALL_DEFAULT_WIDGETS`. Ids: `timeline`, `weather`, `upcoming`, `entregas`,
`training`, `ideas`, `clothing` (Conteo ropa), `acciones_pc` (Streaming PC),
`health_wellness`, `health_sleep`, `health_heart`, `health_hrv`, `health_activity`,
`health_workouts`, `health_hub` (Salud), `jarvis`. Cada uno se renderiza en
`renderWidget(id)`.
La configuración (visibilidad, columna, orden, tamaño, splits) se persiste en
`localStorage`, con selección independiente en modo completo (`la_widget_config`) y
simple (`la_simple_widget_config`).

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
   en lo cargado, se dice — no se calla.

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
5. **Finanzas (`finanzas`)** — la cartera de Indexa Capital: valor total, plusvalía en
   euros y en porcentaje, cuánto se movió desde el último día con dato, sparkline de la
   serie, barra de mezcla por clase de activo y el detalle de posiciones plegado. El ↻
   salta la caché del backend. Un dato que Indexa no dio sale como `—`, nunca como 0 €
   (ver `docs/FINANZAS.md`).
6. **Entrenamiento (`training`)** — sesiones desde el último cobro, euros pendientes,
   formulario de añadir sesión, botón de cobro.
7. **Ideas (`ideas`)** — grabación de audio (Whisper) **o** texto escrito ("✎ Escribir
   idea") → extracción con GPT-4o-mini → Supabase. Si la nota señala una cita, ofrece un
   chip para crear el evento (nunca lo crea solo).
8. **Conteo ropa (`clothing`)** — **TEMPORAL**, ver abajo.
9. **Streaming PC (`acciones_pc`)** — encender el PC (WOL), lanzar el job de streaming,
   apagar/suspender. Barra de progreso con polling cada 2s y badge de estado
   (pending/claimed/running) con los stages en nombres legibles.
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
móvil** (cuando el ⚙ estaba dentro de `.header-greeting`, que se oculta a ≤640px, en
móvil no había forma de abrir los ajustes). `Escape` lo cierra; tiene `maxHeight: 90vh`
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
  `renderWidget(id)`** → misma estética (fuentes, colores, cards).
- **Se adapta a la orientación** vía `matchMedia("(orientation: portrait)")` (estado
  `orientation`, con listener al girar):
  - **Vertical**: una columna — Entrenamiento (card completa) + "Lo siguiente" (card
    compacta con el próximo evento) + Entregas (solo si hay) + bloque de salud.
  - **Horizontal**: dos columnas — izquierda Entrenamiento + Entregas + salud, derecha
    Hoy (timeline) + Próximos eventos.
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

### Claves de localStorage

Prefijo `la_`: `la_token` (JWT), `la_widget_config`, `la_num_columns`, `la_col_splits`,
`la_notifications`, `la_simple_mode`, `la_body_goals`, `la_training_days`,
`la_simple_widget_config`, `la_jarvis_chat` (la conversación con Jarvis: el backend no
guarda ninguna), `la_jarvis_voz` (si Jarvis contesta en voz alta). Si añades una,
mantén el prefijo y el `try/catch` al parsear.

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
- Los `catch { /* mejor esfuerzo: ignorar */ }` son deliberados (notificaciones,
  parseo de localStorage, llamadas fire-and-forget). Si añades uno, pon el comentario
  dentro o la regla `no-empty` fallará.
- El lint debe quedar a **cero errores y cero warnings**. Se limpió por completo en
  julio de 2026; no dejes que se vuelva a degradar.

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
  hoy**, así que al retroceder el carril de eventos es `parcial`; la presencia da horas al
  día pero no tramos (el histórico de presencia está descartado a propósito); y de la casa
  no hay histórico ninguno — `/ha/entidades` es POST-only y su contenido es una foto del
  ahora sin marcas de tiempo. Los avisos SÍ tienen horas desde `GET /avisos/enviados`.

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

