# CLAUDE.md

Guía para trabajar en este repositorio. Léela entera antes de tocar código: casi
todos los errores que se pueden cometer aquí ya los hemos cometido antes y están
documentados abajo.

## Qué es este proyecto

Dashboard personal de un único usuario (Mikel) que centraliza calendario de Outlook,
salud del Apple Watch, entrenamientos personales, ideas por voz, hogar inteligente
(Home Assistant) y un agente PC autónomo. **Todo el proyecto está en español**:
comentarios, commits, strings de UI y mensajes de error de la API.

- **Producción frontend**: https://life-assistant-smoky.vercel.app (Vercel, deploy automático al hacer push a `main`)
- **Producción backend**: https://backend-tender-glow-160.fly.dev (Fly.io, deploy manual con `fly deploy`, escala a cero)
- **Base de datos**: Supabase (PostgreSQL vía REST), solo accesible desde el backend con la service key

## Comandos

```bash
# Frontend
npm install               # una vez
npm run dev               # http://localhost:5173
npm test                  # vitest run (tests/frontend)
npm run lint              # eslint . — debe quedar a CERO errores y CERO warnings
npm run build             # build de producción (verifica que compila)

# Backend — tests (no necesitan servicios reales, todo va con mocks)
python3 -m venv .venv
.venv/bin/pip install -r backend/requirements.txt pytest
.venv/bin/python -m pytest tests/backend

# Backend — desarrollo local (necesita backend/.env con los secretos)
cd backend && uvicorn main:app --reload   # http://localhost:8000
```

**Verificación obligatoria antes de cada commit**:

```bash
npm run lint && npm test && .venv/bin/python -m pytest tests/backend -q && npm run build
```

Además hay CI (`.github/workflows/ci.yml`): ejecuta exactamente estos cuatro pasos
en cada push a `main` y en cada PR, en dos jobs paralelos (frontend / backend). No
despliega nada — el deploy de Vercel sigue siendo el check aparte que ya había, y
el del backend sigue siendo manual (ver "Qué NO hacer").

## Arquitectura

```
Browser (React 19 + Vite, Vercel)
    │  JWT en localStorage("la_token") + fetch REST
    ▼
backend/main.py (FastAPI, Fly.io, UN SOLO FICHERO ~2600 líneas)
    ├── Microsoft Graph API ── calendario Outlook (tokens OAuth persistidos en Supabase)
    ├── Google Maps Distance Matrix ── hora de salida con tráfico
    ├── Open-Meteo ── clima (gratis, sin API key)
    ├── OpenAI ── Whisper (transcripción) + GPT-4o-mini (extracción de ideas)
    ├── Supabase REST ── ideas, clothing, jobs, pc_agents, training_*, health_metrics, oauth_tokens
    └── Home Assistant ── HA sondea al backend (WOL/eventos y flags de relanzado y
                          apagado/suspensión del PC, que HA ejecuta por SSH)

Apple Watch → Health Auto Export / iOS Shortcuts → POST /health/ingest[/simple]
agent/agent.py → agente Windows efímero + despachador (Playwright + pyautogui + Sunshine)
```

Ficheros clave:

| Fichero | Qué es |
|---|---|
| `src/components/Dashboard.jsx` | TODA la UI (~4.575 líneas, un componente principal + subcomponentes en el mismo fichero) |
| `src/lib/helpers.js` | Helpers puros del frontend (fechas, `sleepHours`/`sleepBreakdown`/`sleepScore`, recovery). **La lógica pura nueva va aquí, no en Dashboard.jsx** |
| `backend/main.py` | Toda la API. Secciones marcadas con banners `# ── NOMBRE ──` |
| `agent/agent.py` | Agente PC. Solo funciona en Windows real (Edge, pyautogui, Claude Desktop). **No tiene tests ni puede tenerlos en CI** |
| `supabase/migrations/*.sql` | Esquema de BD. Se aplican a mano en Supabase, no hay tooling de migraciones. **Toda tabla nueva lleva `enable row level security` sin policies**: solo el backend entra, con la service key, que la salta por diseño. Sin RLS, la anon key (pública por diseño) da acceso al REST de Supabase desde internet |
| `tests/backend/conftest.py` | Entorno simulado completo del backend (léelo antes de escribir tests) |
| `tests/frontend/setup.js` | Stubs de `matchMedia` y `Notification` que jsdom no implementa |

## Backend: modelo de seguridad (invariantes — no las relajes nunca)

1. **Sin secretos por defecto.** `main.py` lanza `RuntimeError` al arrancar si faltan
   `SECRET_KEY` o `DASHBOARD_PASSWORD`. Nunca añadas un fallback tipo `"dev-secret"`:
   el repo es público y permitiría forjar JWTs.
2. **Dos niveles de auth:**
   - *Usuario*: `POST /auth/password` (contraseña → JWT HS256, 30 días). Los endpoints
     de usuario llevan `Depends(verify_token)`.
   - *Servicio* (máquinas: HA, Health Auto Export, iOS Shortcuts, el disparador del
     resumen diario): tokens dedicados `HA_POLL_TOKEN` / `HEALTH_INGEST_TOKEN` /
     `BRIEF_TOKEN` comparados con `_token_ok()`
     (tiempo constante, y **falso si el token esperado no está configurado**).
     Orden de extracción: header `X-Auth-Token` → `Authorization: Bearer` → query string
     (la query solo existe por compatibilidad con integraciones ya desplegadas).
   - *OAuth de Microsoft* (`/auth/login` → `/auth/callback`): `/auth/login` exige
     `Depends(verify_token)` y genera un `state` firmado con `SECRET_KEY`
     (`_create_oauth_state()`, 10 min de vida). `/auth/callback` no puede exigir JWT —
     lo llama Microsoft por redirect, sin cabeceras propias — así que en su lugar
     verifica ese `state` (`_verify_oauth_state()`) antes de canjear el código. Sin
     esto, cualquiera que supiera la URL del backend (no es secreta: está en este
     mismo fichero) podía completar SU PROPIO login de Microsoft y sus tokens pisaban
     los del usuario en `oauth_tokens` (una sola fila, clave `provider`). El frontend
     pide la `auth_url` con fetch autenticado (`conectarOutlook()` en Dashboard.jsx) y
     navega a lo que devuelve — no uses un `<a href>` directo al backend, no manda el
     JWT.
3. **Rate limiting**: dos contadores distintos y no intercambiables.
   - **Login** (`_check_login_rate`, `_register_login_failure`, `_reset_login_attempts`):
     cuenta solo los intentos **fallidos**, porque protege una credencial. Es
     **global, no por IP** — esto es una app de un solo usuario, así que limitar por
     IP solo daba una vía de escape gratis (rotarla, trivial en IPv6) sin proteger
     nada a cambio. Vive en Supabase (tabla `login_attempts`), no en memoria: un
     contador en memoria se borraba en cada cold start de Fly, y bastaba esperar a
     que la máquina se durmiera entre tandas para resetear el límite. Si Supabase no
     responde, se deja pasar (fail-open): es el único endpoint que hoy no depende de
     Supabase para nada más, y esa propiedad vale más que blindar una ventana de
     fallo de infraestructura poco probable. 5 intentos / 5 min por defecto.
   - **Genérico** (`_rate_buckets`, `_check_rate`, en memoria): cuenta **todas** las
     peticiones, porque protege un recurso caro — hoy `/ideas/audio`, que es una
     llamada de pago a Whisper por petición. Este SÍ es por IP (`_client_ip()`, ver
     abajo) porque no hay una credencial de por medio que proteger de fuerza bruta,
     solo gasto por IP abusiva. Al añadir un endpoint costoso, usa este.
   - `_client_ip()` (compartida por los dos) **solo usa fuentes que el cliente no
     controla**: `Fly-Client-IP` (y solo si `FLY_APP_NAME` confirma que estamos en
     Fly) o el socket. Nunca fiarse de `X-Forwarded-For` por defecto: coger su
     primera entrada dejaba el límite a merced de quien rotara la cabecera.
     `TRUST_FORWARDED_FOR=1` es el opt-in para proxies propios.
4. **Comparaciones de credenciales siempre con `hmac.compare_digest`**, nunca `==`.
5. **Errores de Supabase**: usa `_supabase_error(r)` — loguea el detalle real en el
   servidor y devuelve un 502 genérico. Nunca reenvíes `r.text` de Supabase al cliente.
6. **Validación de parámetros**: los path params de recursos usan patrones regex
   (UUID para jobs/ideas/sesiones, `[a-zA-Z0-9_-]{1,64}` para worker/agent ids,
   `\d{4}-\d{2}-\d{2}` para fechas). Mantén esto en endpoints nuevos: los valores
   se interpolan en URLs de Supabase. Los ids de Graph (`event_id`, `calendar_id`)
   no tienen forma fija que se pueda validar con un patrón sin rechazar ids reales:
   ahí la regla es `quote(..., safe='')` al construir la URL, más un `max_length`.
7. **`alud_url` solo puede apuntar a `ALUD_ALLOWED_HOSTS`, y siempre por https.**
   Esa URL sale del cuerpo HTML de un evento de Outlook (dato que escribe quien crea
   el evento, no necesariamente el usuario) y acaba en `page.goto()` del agente, en un
   Edge con la sesión de Alud/Okta ya iniciada, cuyo texto se le pasa después a Cowork
   como instrucción. Se valida con `alud_url_permitida()` en **tres** sitios a
   propósito: al extraerla en `/calendar/events`, al dar de alta el job en `POST /jobs`
   y en el propio `agent.py` — la tabla `jobs` es escribible con la service key, así
   que un payload puede llegar sin haber pasado por el backend. No quites ninguna de
   las tres. El enunciado extraído va delimitado como DATO en la instrucción de Cowork
   (`build_cowork_instruction`), no mezclado con las órdenes.
8. **Cuerpos acotados**: nada de `await request.body()` ni `UploadFile.read()` sin
   tope — cargan en memoria lo que mande el cliente y la VM de Fly tiene 1 GB. Usa
   `_leer_cuerpo_limitado(request, limite)` (mira `Content-Length` y además cuenta el
   stream, porque con `Transfer-Encoding: chunked` no hay cabecera que mirar).
   Límites: `MAX_AUDIO_BYTES`, `MAX_INGEST_BYTES`.

## Backend: patrones que hay que conocer

- **Cliente HTTP saliente**: TODO lo que sale del backend va por `http` (la sesión de
  módulo), nunca por `requests.get` suelto. Impone `HTTP_TIMEOUT` por defecto y
  reutiliza conexiones. Sin timeout, una llamada colgada retiene un hilo del pool de
  FastAPI para siempre. Los tests mockean `main.http`, no `main.requests`.
- **Dependencias opcionales**: lo que la documentación llame opcional no puede
  impedir arrancar. El cliente de OpenAI se crea de forma perezosa y devuelve 503
  si falta la configuración, nunca revienta el import.
- **Ideas → evento sugerido**: `extract_idea_from_text()` le pasa al modelo la fecha
  de hoy (si no, no puede resolver "el martes" o "mañana") y le pide también
  `fecha`/`hora` cuando la nota señala una cita. Lo que devuelve el LLM **nunca** se
  manda a Graph sin pasar por `sugerencia_evento()`, que valida que la fecha/hora
  tengan forma real (descarta cosas como `2026-02-30`) y exige un título no vacío.
  El evento no se crea solo: el endpoint solo devuelve `evento_sugerido` y el
  frontend lo ofrece como chip — crear el evento lo dispara el usuario.
- **Zonas horarias**: Microsoft Graph devuelve fechas con nombres de zona de Windows
  ("Romance Standard Time"). `normalize_graph_dt()` + `WINDOWS_TZ_MAP` las convierten
  SIEMPRE a ISO UTC con sufijo `Z`. La zona del usuario es `TIMEZONE`/`LOCAL_TZ`
  (env, default `Europe/Madrid`) — úsala en vez de hardcodear zonas. Cualquier
  fecha nueva que salga de la API debe ser UTC-Z.
- **Kit self-hosted**: la instancia se personaliza por env — `TIMEZONE`,
  `CLASSES_CALENDAR`, `CORS_ORIGINS`, `HOME_ADDRESS`, `WEATHER_LAT`/`WEATHER_LON`
  (backend, ver `backend/.env.example` y `backend/check_config.py`) y `VITE_API_URL`,
  `VITE_HA_URL`, `VITE_HA_DASHBOARD_PATH`, `VITE_ENTREGAS_MARKER` (frontend).
  La guía de despliegue para terceros es `docs/DESPLIEGUE.md`: si añades una
  variable o migración, actualízala. No reintroduzcas valores personales
  hardcodeados en el código.
- **Tokens OAuth de Graph** se persisten en la tabla `oauth_tokens` de Supabase
  (sobreviven a los redeploys de Fly; la mención a `backend/.token` en el README está
  obsoleta). `get_valid_token()` renueva con el refresh token de forma transparente.
  Además hay una **copia en memoria** (`_token_cache`): antes cada endpoint de
  calendario leía la tabla, así que una carga del dashboard gastaba dos viajes de red
  en releer un token que no había cambiado, y el sondeo de HA sumaba otro por minuto.
  La copia se rellena al leer, se actualiza en `save_token_data()` y se tira si el
  refresh falla. Si tocas la escritura del token, mantén esa invalidación (y resetéala
  en `reset_state` de los tests, como el resto de estado de módulo).
- **Cliente MSAL compartido** (`_msal_app()`, perezoso): construir un
  `ConfidentialClientApplication` descubre la autoridad por red, y antes se construía
  de cero en `/auth/login`, `/auth/callback` y en cada renovación de token.
- **Cola de jobs** (máquina de estados estricta, transiciones vía PATCH condicional de
  Supabase para que sean atómicas):
  `pending → claimed → running → done | failed`, y `failed → pending` con `retry`
  (incrementa `attempt`, máx. `MAX_JOB_ATTEMPTS=3`). El claim usa
  `?status=eq.pending` como guard: si devuelve 0 filas, otro worker ganó la carrera.
  `dedupe_key` es único: el upsert con `resolution=merge-duplicates` devuelve 0 filas
  en conflicto y entonces se recupera el job existente. `GET /jobs/pending` (JWT) es
  lo que sondea `agent.py`: por eso el agente NO tiene `SUPABASE_KEY` en su `.env` — es
  la única consulta que se lo exigía, y la service_role key salta toda la RLS de la
  base. Si añades un endpoint nuevo que el agente necesite, que pase por el backend
  con JWT en vez de darle más alcance de Supabase directo.
- **Ingesta de salud**: las métricas acumulativas (`step_count`, `active_energy`,
  `basal_energy`, `resting_energy`, definidas en `CUMULATIVE_METRICS`, constante de
  módulo compartida por las dos rutas de ingesta) solo se sobreescriben si el valor
  nuevo es MAYOR (llegan snapshots parciales a lo largo del día). Energía en kJ se
  convierte a kcal (÷ 4.184, `ENERGY_METRICS`). `sleep_analysis` guarda `sleep_start`
  ("HH:MM") en `extra` y respeta el flag `excluded` (noches anuladas por el usuario).
  Escritura en **dos viajes por lote**, no uno por métrica: `_existentes_por_clave()`
  trae de golpe lo ya guardado para las fechas/nombres del lote y `_guardar_metricas()`
  hace un único upsert (`resolution=merge-duplicates`, aprovechando el
  `unique(metric_date, metric_name)` de la tabla) con el resto. Un GET+POST por
  métrica aquí son 60-90 viajes secuenciales a Supabase por sincronización del
  Watch — no lo reintroduzcas.
- **Flags de control del PC (poll de HA, mismo patrón que WOL)**: son flags globales
  en memoria que el dashboard marca y HA limpia al sondearlos. Se resetean en cold
  start de Fly (aceptable). No los conviertas en estado persistente sin pensar en el
  poll de HA.
  - `_wol_pending` → `/wake-pc` marca, `/ha/wol-pending` recoge (magic packet).
  - `_agent_relaunch_pending` → `/relaunch-agent` marca, `/ha/agent-relaunch-pending`
    recoge. Para relanzar el agente efímero por SSH cuando el PC ya está encendido.
  - `_pc_power_action` (`"shutdown"|"suspend"|None`) → `/shutdown-pc` / `/suspend-pc`
    marcan, `/ha/pc-power-pending` recoge. Apagar/suspender no pasa por el agente: HA
    lo ejecuta por SSH directo (el agente es efímero y ya terminó).
- **Agente PC efímero + despachador**: `agent/agent.py` arranca con Windows (vía WOL),
  drena la cola y se cierra. Según `payload["accion"]` despacha a `ACCIONES`
  (`resolver_alud`, `abrir_streaming`). Compatibilidad: jobs sin `accion` pero con
  `alud_url` → `resolver_alud`. `resolver_accion()` + guard `attempted` (cada job se
  intenta una vez por ejecución para no repetir en bucle si falla el claim por red).
- **Clima**: `/weather` (Open-Meteo, gratis, sin API key) usa `WEATHER_LAT/LON`, o las
  coordenadas que mande el dispositivo (`?lat&lon`, geolocalización del navegador). El
  cálculo de salida (`/maps/departure`) también usa esa ubicación como `origin` si la
  hay, con fallback a `HOME_ADDRESS`.
- **Resumen diario por correo** (`/brief`, `POST /brief/send`): manda a tu propio buzón
  los datos del día **en crudo, sin interpretarlos**, porque quien los consume es una
  rutina externa que lee el correo y redacta el resumen — ya es un modelo, así que aquí
  **no hay ninguna llamada a un LLM** y no debe haberla. Tampoco hay conclusiones:
  `healthConclusions` y compañía viven en `helpers.js`, son JavaScript y son la única
  fuente de verdad de esa lógica; portarlas a Python la duplicaría. Lo único que se
  replica es `_horas_sueno()` (equivalente a `_sleepHours`), que es forma del dato y no
  regla — si cambia cómo llegan los datos del Watch, hay que tocar los dos.
  `construir_brief()` llama a las funciones de los endpoints existentes con
  `credentials=None` (ninguna usa ese parámetro; lo resuelve FastAPI solo por HTTP) para
  heredar su normalización y manejo de errores en vez de duplicar consultas, y las lanza
  en paralelo. Cada sección cae por su cuenta: un fallo de Graph deja la agenda vacía
  pero el resto del correo sigue siendo útil. Envío por `smtplib` (librería estándar, sin
  dependencias nuevas). El disparador es
  `.github/workflows/resumen-diario.yml` (cron en UTC — ajústalo en los cambios de hora)
  y usa `BRIEF_TOKEN`, token de servicio: un JWT de usuario caducaría a los 30 días y el
  correo dejaría de llegar sin avisar.
- **Peticiones a Supabase en paralelo**: cuando dos consultas no dependen entre sí
  (`/training/summary` pide el último pago y las sesiones a la vez con
  `ThreadPoolExecutor`), lánzalas en paralelo en vez de en serie — se ejecuta en cada
  carga del dashboard, con el arranque en frío de Fly por delante. Si una depende del
  resultado de otra, en serie.

## Frontend: cómo está organizado Dashboard.jsx

Un solo fichero, navegable por sus banners (`grep "── " src/components/Dashboard.jsx`):
LOGIN SCREEN → HELPERS → ESTILOS GLOBALES (`GLOBAL_CSS`, variables CSS `--bg`,
`--accent`...) → `DateInput`/`TimeInput` → COMPONENTE PRINCIPAL (estados, efectos,
`renderWidget`, skeleton, modo simplificado móvil, modales, panel de clases).

- **Widgets**: definidos en `ALL_DEFAULT_WIDGETS` (ids: `timeline`, `weather`,
  `upcoming`, `entregas`, `training`, `ideas`, `clothing` (Conteo ropa), `acciones_pc` (Streaming PC),
  `health_wellness`, `health_sleep`, `health_heart`, `health_hrv`, `health_activity`,
  `health_workouts`, `health_hub` (Salud: widget compacto con veredicto general +
  top conclusiones; al pulsar abre el modal `healthModalOpen` con TODAS las
  conclusiones por dominio + los widgets de salud de detalle reutilizados vía
  `renderWidget`)). El motor de conclusiones es lógica pura y testeada en
  `helpers.js`: `healthConclusions` (exprime todas las métricas del Watch y
  devuelve conclusiones `{domain, tone, text}`), `healthOverall` (veredicto),
  apoyándose en `seriesTrend`/`trendDirection`/`bedtimeHrvInsight` y en
  `pairByDate`/`splitCompare` para los cruces entre series. La puntuación de
  bienestar también vive allí: `wellnessBreakdown` construye el desglose y
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
  Cada uno se renderiza en `renderWidget(id)`. La configuración
  (visibilidad, columna, orden, tamaño, splits) se persiste en `localStorage`, con
  selección independiente en modo completo (`la_widget_config`) y simple
  (`la_simple_widget_config`).
  - **`Sparkline`** acepta `objetivo` (dibuja una línea discontinua de referencia,
    metiéndolo en el rango vertical para que nunca quede fuera del gráfico) y
    `relleno` (área bajo la curva). Se usa en el bloque de composición corporal
    para la serie de peso con el objetivo encima.
  - **Panel de estado del sistema** (en ajustes): backend, sesión de Outlook,
    última sincronización del Watch, agente PC y entrenamiento, todo en un mismo
    sitio. Se recarga al abrir ajustes y con su botón — nunca en un intervalo.
  - **`clothing` (Conteo ropa) es TEMPORAL**: lleva la cuenta de ropa comprada
    hasta saldar el gasto. Cuando ya no haga falta, se quita entero: el `case
    "clothing"` de `renderWidget`, su entrada en `ALL_DEFAULT_WIDGETS`/`DEFAULT_COLUMNS`,
    los estados `clothing*`, el efecto de carga, las funciones `onClothingPhoto`/
    `addClothing`/`deleteClothing`, el overlay de foto, los endpoints `/clothing`
    del backend, los helpers `formatMoney`/`clothingTotals` (+ sus tests) y la tabla
    `clothing` de Supabase (`drop table public.clothing;`).
- **Claves de localStorage** (prefijo `la_`): `la_token` (JWT), `la_widget_config`,
  `la_num_columns`, `la_col_splits`, `la_notifications`, `la_simple_mode`,
  `la_body_goals`, `la_training_days`, `la_simple_widget_config`. Si añades una, mantén el prefijo y el
  `try/catch` al parsear.
- **`apiFetch()`**: wrapper de `fetch` que, ante un 401 con sesión activa, borra
  `la_token` y recarga. Úsalo para toda llamada autenticada al backend.
- **`authHeaders()` / `jsonHeaders()`**: única forma de construir las cabeceras de
  una llamada autenticada (la segunda añade `Content-Type: application/json`). No
  vuelvas a escribir `localStorage.getItem("la_token")` suelto en un handler — por
  eso había 28 lecturas repetidas del mismo valor.
- **`datosSalud` (memo)**: toda la derivación de las métricas de salud (~17
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
- **URL del backend**: `VITE_API_URL` o el default de Fly. En local, apunta
  `VITE_API_URL` a `http://localhost:8000` (recuerda que el CORS del backend solo
  permite `localhost:5173` y el dominio de Vercel).

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

## Tests: cómo funcionan y sus trampas

### Backend (`tests/backend`, 250 tests)

`conftest.py` define las variables de entorno **antes** de importar `main` (si no,
el import revienta por los secretos obligatorios) y monkeypatchea `requests` con un
`MockRouter`: registras respuestas por `(método, fragmento de URL)` y las rutas se
resuelven **en orden de registro** — registra primero la más específica
(`/calendars/cal-x/calendarView` antes que `/me/calendars`, porque la primera URL
contiene a la segunda). Fixtures: `client`, `auth_headers` (JWT válido),
`mock_requests`, `graph_token` (simula sesión de Graph), `login_attempts_mock`
(simula la tabla `login_attempts` de Supabase con una lista en memoria — sin esto,
cualquier test que llame a `/auth/password` intentaría una llamada de red real). El
limitador genérico (`_rate_buckets`) y los flags WOL se resetean entre tests
automáticamente; los intentos de login NO, porque ya no viven en memoria — cada test
que los necesite los mockea con el fixture de arriba.

Valores del entorno de test: contraseña `1234`, `SECRET_KEY=test-secret-key`,
`HA_POLL_TOKEN=ha-poll-token`, `HEALTH_INGEST_TOKEN=health-token`,
`BRIEF_TOKEN=brief-token`.

### Frontend (`tests/frontend`, 71 tests)

Vitest + jsdom + Testing Library, configurado en `vite.config.js` (bloque `test`).
Trampas conocidas de jsdom:

- **El input de contraseña tiene `pattern="[0-9]*"`**: jsdom aplica la validación
  de formulario, así que escribir una contraseña con letras en un test **bloquea el
  submit silenciosamente**. Usa contraseñas numéricas en los tests.
- `matchMedia` y `Notification` no existen en jsdom → los stubs están en `setup.js`.
- `window.location.reload` no está implementado: el flujo de login lo llama y jsdom
  imprime "Not implemented: navigation" en la consola. **Es ruido esperado, no un
  fallo** — asegura el comportamiento comprobando `localStorage` en su lugar.
- El test de login renderiza el `Dashboard` completo: cualquier error de runtime en
  el camino de montaje del componente hará fallar esos tests. Es intencionado.

## Bugs históricos (no los reintroduzcas)

- `sleepScore`: la penalización por hora de acostarse usa `h === 1` / `h === 0` para
  distinguir la 01:00 y las 00:00. Un `h >= 1` "equivalente" penalizaba también las
  22:00–23:00 (cualquier hora antes de medianoche). Hay test que lo cubre.
  **Este bug se reintrodujo** en el tooltip del widget de sueño, que llevaba su propia
  copia de los umbrales: enseñaba -10 pts por acostarse a las 22:00 que la puntuación
  real no aplicaba, así que las filas no cuadraban con su propio total. Arreglado con
  el mismo patrón que bienestar: `sleepBreakdown` (helpers) es la única fuente de
  verdad de los umbrales y `sleepScore` se limita a sumarlo. **No vuelvas a escribir
  esos umbrales fuera de `helpers.js`.**
- `sleepScore` NO recibe `core`: era un parámetro muerto que nadie usaba pero que los
  dos sitios que lo llaman se molestaban en calcular. Firma actual:
  `sleepScore(total, deep, rem, awake, sleepStart, recoveryMod)`.
- Los path params UUID del backend salen de `_uuid_path()`, que es una **fábrica**, no
  una constante: FastAPI asocia cada objeto `Path()` al nombre del parámetro que lo
  usa, así que compartir una instancia entre endpoints con nombres distintos
  (`idea_id`, `item_id`, `session_id`…) hace que todos hereden el último nombre
  registrado y devuelvan 422. Hay tests que lo cubren.
- Extracción de `alud_url` en `/calendar/events`: los cuerpos de Graph son HTML y la
  URL suele venir pegada a la etiqueta de cierre (`...id=99</p>`). El patrón debe
  excluir `<>"'` — un `\S+` se traga la etiqueta y rompe el enlace. Hay test.
- Doble conteo de entrenos semanales y fugas de detalles de error ya se arreglaron
  en commits anteriores; si tocas bienestar o manejo de errores, revisa el historial.

## Convenciones

- **Idioma**: todo en español (código nuevo incluido: comentarios, strings, tests).
- **Commits**: minúscula, estilo `área: descripción` (ej. `tests: ...`, `lint: ...`,
  `seguridad: ...`, `bienestar: ...`). `main` mantiene historial lineal (squash merge).
- **Ramas de trabajo**: `claude/...`; PR contra `main`.
- **Estilo de código**: el existente. Comentarios que explican *por qué* (restricciones,
  decisiones), no *qué*. Alineación vertical de asignaciones donde ya la haya.
- **No añadas dependencias** sin necesidad clara; el proyecto es deliberadamente simple
  (sin router, sin gestor de estado, sin ORM, sin framework de CSS).

## Qué NO hacer

- No crees componentes en ficheros nuevos "por organizar": el proyecto es una sola
  persona y un solo fichero de UI a propósito. Extrae solo lógica pura a `src/lib/`.
- No toques `agent/agent.py` esperando poder probarlo: requiere un PC Windows real.
- No conviertas los endpoints de servicio (HA/salud) a JWT: los clientes son
  integraciones ya desplegadas (HA, iOS Shortcuts) que solo saben mandar un token fijo.
- No borres el soporte de token por query string en `_extract_service_token` sin
  migrar antes esas integraciones.
- No subas `.env`, tokens ni el directorio `.venv` (ya están en `.gitignore`).
- No hagas deploy del backend salvo que se pida: afecta a producción real. El deploy
  es manual — `fly deploy` desde `backend/`, o el workflow `Deploy backend (Fly.io)`
  (`.github/workflows/deploy-backend.yml`, `workflow_dispatch`; usa el secret
  `FLY_API_TOKEN`). Nunca en automático al hacer push.

comentario importante: tienes que hacer los PR y los comits sin meterte a ti como coeditor o lo que sea. solo debo aparecer yo.
