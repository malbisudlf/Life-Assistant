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

## ⚠️ Repo público — reglas de seguridad

El repositorio es **público en GitHub**. Antes de cualquier commit o push:

- **No hardcodear nunca** IPs, direcciones, emails, tokens, contraseñas ni rutas de
  usuario (`C:\Users\<usuario>\...`) en ficheros versionados. Este fichero incluido.
- **Todos los secretos** van en `backend/.env`, `agent/.env` o `HOMEASSISTANT.md` — los
  tres están en `.gitignore`.
- **Valores por defecto de `os.getenv()`**: dejarlos vacíos (`""`) si el valor es
  personal o sensible.
- **Secretos críticos sin fallback**: `SECRET_KEY` y `DASHBOARD_PASSWORD` **no** tienen
  valor por defecto — si faltan, el backend lanza `RuntimeError` al arrancar (fail-fast).
  Nunca volver a poner un fallback tipo `"fallback-secret"`/`"changeme"`: en un repo
  público permitiría forjar JWT válidos si la variable no estuviera configurada en
  producción.
- **Antes de hacer push**: revisar si el diff contiene algún dato personal.
- **`git filter-repo` ya se ejecutó** (2026-05-15) — el historial está limpio desde ahí.
- **Commits**: no añadir línea `Co-Authored-By` — los commits van solo en nombre del
  usuario (ver "Convenciones").
- **`CLAUDE.md` se versiona** (desde julio de 2026). Las notas privadas van en ficheros
  ignorados aparte (`HOMEASSISTANT.md`, `PROJECT_STATE.md`) — no las metas aquí.

## Comandos

```bash
# Frontend
npm install               # una vez
npm run dev               # http://localhost:5173
npm test                  # vitest run (tests/frontend)
npm run lint              # eslint . — debe quedar a CERO errores y CERO warnings
npm run build             # build de producción (verifica que compila)
npm run preview           # sirve el build de producción

# Backend — tests (no necesitan servicios reales, todo va con mocks)
python3 -m venv .venv
.venv/bin/pip install -r backend/requirements.txt pytest
.venv/bin/python -m pytest tests/backend

# Backend — desarrollo local (necesita backend/.env con los secretos)
cd backend && uvicorn main:app --reload   # http://localhost:8000
# En Windows: python -m venv venv && venv\Scripts\activate && pip install -r requirements.txt
```

**El dev server tiene que arrancar en el puerto 5173.** El CORS del backend solo permite
los orígenes de `CORS_ORIGINS` (por defecto `localhost:5173` y el dominio de Vercel). Si
5173 está ocupado, Vite arranca en 5174 y el login falla con un error de CORS
("blocked by CORS policy"), **no** con un error de credenciales — despista mucho. La
solución es liberar el puerto (`netstat -ano | grep 5173` → `taskkill //F //PID <pid>`),
no añadir el puerto nuevo a `allow_origins`.

**Verificación obligatoria antes de cada commit**:

```bash
npm run lint && npm test && .venv/bin/python -m pytest tests/backend -q && npm run build
```

Además hay CI (`.github/workflows/ci.yml`): ejecuta esos cuatro pasos en cada push a
`main` y en cada PR, en **tres jobs paralelos** (frontend / backend / E2E). No
despliega nada — el deploy de Vercel sigue siendo el check aparte que ya había, y
el del backend sigue siendo manual (ver "Qué NO hacer").

```bash
npm run test:e2e          # Playwright: navegador real contra el build + backend real
```

El E2E no entra en la verificación obligatoria de arriba porque tarda bastante más
(construye, levanta dos servidores y abre un navegador). En CI sí corre siempre.

## Arquitectura

```
Browser (React 19 + Vite 8, Vercel)
    │  JWT en localStorage("la_token") + fetch REST
    ▼
backend/main.py (FastAPI + Uvicorn, Fly.io región cdg, UN SOLO FICHERO ~3.000 líneas)
    ├── Microsoft Graph API ── calendario Outlook (tokens OAuth persistidos en Supabase)
    ├── Google Maps Distance Matrix ── hora de salida con tráfico
    ├── Open-Meteo ── clima (gratis, sin API key)
    ├── OpenAI ── Whisper (transcripción) + GPT-4o-mini (extracción de ideas)
    ├── Supabase REST ── ideas, clothing, jobs, pc_agents, training_*, health_metrics,
    │                    oauth_tokens, login_attempts, app_logs
    └── Home Assistant ── HA sondea al backend (WOL/eventos y flags de relanzado y
                          apagado/suspensión del PC, que HA ejecuta por SSH)

Apple Watch → Health Auto Export / iOS Shortcuts → POST /health/ingest[/simple]
agent/agent.py → agente Windows efímero + despachador (Playwright + pyautogui + Sunshine)
```

Ficheros clave:

| Fichero | Qué es |
|---|---|
| `src/components/Dashboard.jsx` | TODA la UI (~4.800 líneas, un componente principal + subcomponentes en el mismo fichero) |
| `src/lib/helpers.js` | Helpers puros del frontend (fechas, `sleepHours`/`sleepBreakdown`/`sleepScore`, recovery). **La lógica pura nueva va aquí, no en Dashboard.jsx** |
| `backend/main.py` | Toda la API. Secciones marcadas con banners `# ── NOMBRE ──` |
| `agent/agent.py` | Agente PC. Solo funciona en Windows real (Edge, pyautogui, Claude Desktop). **No tiene tests ni puede tenerlos en CI** |
| `supabase/migrations/*.sql` | Esquema de BD. Se aplican a mano en Supabase, no hay tooling de migraciones. **Toda tabla nueva lleva `enable row level security` sin policies**: solo el backend entra, con la service key, que la salta por diseño. Sin RLS, la anon key (pública por diseño) da acceso al REST de Supabase desde internet |
| `tests/backend/conftest.py` | Entorno simulado completo del backend (léelo antes de escribir tests) |
| `tests/frontend/setup.js` | Stubs de `matchMedia` y `Notification` que jsdom no implementa |
| `tests/e2e/servidor_pruebas.py` | Backend REAL con los servicios externos simulados, para el E2E. Importa `main.py` tal cual y solo sustituye `main.http` |
| `HOMEASSISTANT.md` | **Ignorado por git.** Credenciales SSH, token de HA, IP local, estructura de ficheros de HA y workflow completo |
| `PROJECT_STATE.md` | **Ignorado por git.** Notas de estado personales |
| `docs/DESPLIEGUE.md` | Guía de despliegue del kit para terceros |
| `backend/.env.example` | Todas las variables del backend, documentadas una a una |
| `backend/check_config.py` | Comprueba que la configuración del backend está completa |

## Backend: modelo de seguridad (invariantes — no las relajes nunca)

1. **Sin secretos por defecto.** `main.py` lanza `RuntimeError` al arrancar si faltan
   `SECRET_KEY` o `DASHBOARD_PASSWORD`. Nunca añadas un fallback tipo `"dev-secret"`:
   el repo es público y permitiría forjar JWTs.
2. **Dos niveles de auth:**
   - *Usuario*: `POST /auth/password` (contraseña → JWT HS256, 30 días,
     `TOKEN_EXPIRE_DAYS`). Los endpoints de usuario llevan `Depends(verify_token)`.
   - *Servicio* (máquinas: HA, Health Auto Export, iOS Shortcuts, el disparador del
     resumen diario, el agente PC): tokens dedicados `HA_POLL_TOKEN` /
     `HEALTH_INGEST_TOKEN` / `BRIEF_TOKEN` / `AGENT_TOKEN` comparados con `_token_ok()`
     (tiempo constante, y **falso si el token esperado no está configurado**).
     **Nada que arranque solo puede autenticarse con un JWT de usuario**: caduca a los
     30 días y el cliente se queda mudo sin avisar a nadie. Ya pasó dos veces — se
     previó para `BRIEF_TOKEN` y se pasó por alto en el agente PC, que llevaba el JWT
     del dashboard copiado a mano en su `.env`: cuando expiró, `/jobs/pending` empezó a
     responder 401 y el agente se cerraba en cada arranque diciendo que no había jobs.
     Orden de extracción (`_extract_service_token`): header `X-Auth-Token` →
     `Authorization: Bearer` → query string (la query solo existe por compatibilidad
     con integraciones ya desplegadas — HA y el Shortcut de iOS; migrarlas a cabecera
     cuando se pueda, para dejar de exponer el token en los logs de URLs).
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
     fallo de infraestructura poco probable. 5 intentos / 5 min por defecto
     (`LOGIN_MAX_ATTEMPTS` / `LOGIN_WINDOW_SECONDS`), con bloqueo progresivo que dobla
     su duración hasta `LOGIN_BLOQUEO_MAX_SECONDS`. Devuelve `429` con `Retry-After`.
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
   Mismo criterio con Graph: los errores de crear/editar evento se loguean sin
   devolver `r.json()`.
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
9. **Sin inyección en el agente**: el enunciado extraído de Alud **nunca** se interpola
   en un comando de PowerShell. Se escribe a un fichero temporal UTF-8 (ruta generada
   por el SO) y `Set-Clipboard -Value (Get-Content -Raw -Encoding UTF8 -LiteralPath ...)`
   lo lee de ahí. Antes se usaba un here-string `@'...'@`, vulnerable si el texto
   contenía `'@`.

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
  frontend lo ofrece como chip — crear el evento lo dispara el usuario. `/ideas/audio`
  (Whisper) y `/ideas/text` comparten la extracción y el guardado.
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
  (`supabase/migrations/20260607_oauth_tokens.sql`). Antes se guardaban en
  `backend/.token`, pero ese fichero se perdía en cada `fly deploy` (el filesystem del
  contenedor se reconstruye desde la imagen) → forzaba reautenticación constante y
  desconexiones del calendario "cada dos por tres". `backend/.dockerignore` excluye
  `.env`/`.token`/`venv`/`__pycache__` de la imagen para que nunca se cuele un fichero
  local de desarrollo en producción. `get_valid_token()` renueva con el refresh token
  de forma transparente. Además hay una **copia en memoria** (`_token_cache`): antes
  cada endpoint de calendario leía la tabla, así que una carga del dashboard gastaba
  dos viajes de red en releer un token que no había cambiado, y el sondeo de HA sumaba
  otro por minuto. La copia se rellena al leer, se actualiza en `save_token_data()` y
  se tira si el refresh falla. Si tocas la escritura del token, mantén esa invalidación
  (y resetéala en `reset_state` de los tests, como el resto de estado de módulo).
  **`SCOPES` incluye `Calendars.ReadWrite`** (necesario para crear/editar eventos): si
  cambias los scopes hay que **reautenticar** pasando otra vez por `/auth/login` →
  `/auth/callback`, porque el refresh token guardado está ligado al consentimiento
  anterior.
- **Cliente MSAL compartido** (`_msal_app()`, perezoso): construir un
  `ConfidentialClientApplication` descubre la autoridad por red, y antes se construía
  de cero en `/auth/login`, `/auth/callback` y en cada renovación de token.
- **Cola de jobs** (máquina de estados estricta, transiciones vía PATCH condicional de
  Supabase para que sean atómicas):
  `pending → claimed → running → done | failed`, y `failed → pending` con `retry`
  (incrementa `attempt`, máx. `MAX_JOB_ATTEMPTS=3`). El claim usa
  `?status=eq.pending` como guard: si devuelve 0 filas, otro worker ganó la carrera.
  `dedupe_key` es único: el upsert con `resolution=merge-duplicates` devuelve 0 filas
  en conflicto y entonces se recupera el job existente. `GET /jobs/pending` es
  lo que sondea `agent.py`: por eso el agente NO tiene `SUPABASE_KEY` en su `.env` — es
  la única consulta que se lo exigía, y la service_role key salta toda la RLS de la
  base. Si añades un endpoint nuevo que el agente necesite, que pase por el backend
  en vez de darle más alcance de Supabase directo.
  Los seis endpoints del ciclo de vida de un job (`/jobs/pending`, `claim`, `start`,
  `finish`, `POST .../events` y `/agents/heartbeat`) van con `Depends(verify_agente)`:
  aceptan `AGENT_TOKEN` **o** el JWT del usuario (el dashboard también los consulta).
  Los demás siguen con `verify_token` a propósito — el alcance de ese token es la cola
  de jobs, no la sesión entera, y vive en un `.env` de un PC que arranca solo. Si
  amplías `verify_agente` a un endpoint nuevo, añádelo a
  `TestAuthAgente::test_cubre_todo_lo_que_usa_el_agente`.
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
  La URL del upsert sale de `HEALTH_UPSERT_URL` y **lleva
  `?on_conflict=metric_date,metric_name`**: PostgREST resuelve `merge-duplicates`
  contra la CLAVE PRIMARIA salvo que se le nombre otra restricción, y aquí la primaria
  es `id` (uuid nuevo en cada inserción, que no colisiona nunca), así que sin ese
  parámetro cualquier fila repetida acaba en un 409 que tumba el lote entero. Mismo
  criterio para cualquier tabla cuya unicidad real no sea su clave primaria.
  Y un fallo de escritura **corta con 502**: los clientes son máquinas (Health Auto
  Export, un Shortcut de iOS) que no miran el cuerpo de la respuesta, así que un 200
  `{"ok": true}` con el error escondido dentro es indistinguible de haber sincronizado.
  Por lo mismo, **una sincronización de la que no se reconoce nada responde `ok: false`**
  con `_resumen_cuerpo()` (claves recibidas y tamaños, nunca valores) en el cuerpo y en
  el registro: un JSON bien formado con la estructura equivocada —un `{}`, el envoltorio
  de otro exportador— pasaba todas las validaciones y salía como `200 {"upserted": 0}`.
  Ojo con la condición: se mira lo RECONOCIDO (`grouped_metrics`/`samples`), no lo
  escrito, porque un lote de acumulativas que ya tenían un valor mayor escribe cero y es
  correcto.
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
- **Registro persistente (`app_logs`)**: `logger.error()`/`warning()` van a stdout Y a
  Supabase, porque el stdout se lo lleva la máquina de Fly al escalar a cero — que es
  justo por lo que el 409 de la ingesta de salud estuvo días registrándose sin que nadie
  lo viera. Lo hace `RegistroSupabase`, un `logging.Handler` enganchado al logger que ya
  existía: **para que algo nuevo quede registrado basta con llamar a `logger.error()`,
  no hay que tocar nada más**. Reglas que no se pueden relajar, todas por lo mismo
  (registrar no puede tumbar ni frenar una petición): la petición solo encola en memoria
  y escribe un hilo de fondo en lotes; la cola está acotada (`LOG_QUEUE_MAX`, tira las
  viejas y deja constancia de cuántas); y un fallo escribiendo el registro **se avisa por
  `stderr`, nunca por `logger`** — por `logger` se realimentaría con el error de escribir
  el error. Se persiste WARNING+ (`LOG_PERSIST_LEVEL`); bajar a INFO llena la tabla de
  ruido. En los tests va desactivado (`LOG_PERSIST=0` en `conftest.py`): encendido, el
  hilo colaría POSTs a `app_logs` en el `MockRouter` de cualquier test que registre algo.
- **Middleware `registrar_peticiones`**: la otra mitad de "logs para todo", la que no se
  puede escribir a mano en 60 endpoints. Registra 5xx, 4xx (menos el 401, que es el JWT
  caducando y el frontend ya lo resuelve), excepciones no controladas con su traza y las
  peticiones que pasan de `LOG_SLOW_MS`. Guarda `"MÉTODO /ruta"` **sin query string**: por
  ahí viajan `HEALTH_INGEST_TOKEN` y `HA_POLL_TOKEN` (soportados por compatibilidad con
  las integraciones ya desplegadas) y no pueden acabar en una tabla. Esa ruta viaja en un
  `ContextVar` hasta el handler, así que cada entrada dice en qué petición pasó.
- **`GET /logs`** (JWT) lo consume el panel de ajustes. Vuelca la cola antes de leer: se
  abre el panel PORQUE algo acaba de fallar, y si no, lo recién ocurrido tardaría
  `LOG_FLUSH_SECONDS` en aparecer. `nivel` va con lista blanca (`NIVELES_LOG`), no con
  regex: se interpola en la URL de Supabase (invariante 6).

## Backend: referencia de endpoints

`backend/main.py` es un FastAPI monolítico. Auth: **JWT** = `Depends(verify_token)`,
**agente** = `verify_agente` (AGENT_TOKEN o JWT), **servicio** = token dedicado.

| Ruta | Auth | Descripción |
|---|---|---|
| `GET /` | — | Estado del backend (salud del servicio, sesión de Graph) |
| `POST /auth/password` | — | Contraseña → JWT. Rate limiting global (`429` + `Retry-After`) |
| `GET /auth/login` | JWT | Devuelve la `auth_url` del flujo OAuth de Microsoft Graph, con `state` firmado |
| `GET /auth/callback` | `state` | Callback OAuth de Microsoft (lo llama Microsoft, verifica el `state`) |
| `GET /calendar/events` | JWT | Eventos de los próximos 30 días (Graph). Extrae `alud_url` del cuerpo HTML |
| `POST /calendar/events` | JWT | Crea evento en Outlook — `subject`, `start`, `end` (ISO sin zona, se asume `TIMEZONE`), `location?`, `is_all_day?`, `calendar_id?` |
| `PATCH /calendar/events/{event_id}` | JWT | Edita un evento — mismos campos salvo `calendar_id` (no se puede mover de calendario); solo manda los campos presentes en el body |
| `GET /calendar/classes` | JWT | Eventos del calendario de clases (`CLASSES_CALENDAR`) — 60 días, máx. 200 |
| `GET /calendar/calendars` | JWT | Lista de calendarios disponibles |
| `POST /maps/departure` | JWT | Hora de salida (Google Maps Distance Matrix). `mode: "driving"` (con tráfico) o `"walking"` |
| `GET /weather` | JWT | Clima (Open-Meteo). `?lat&lon` opcionales; si no, `WEATHER_LAT/LON` |
| `GET /ideas` | JWT | Lista de ideas |
| `POST /ideas/audio` | JWT | Audio → Whisper → GPT-4o-mini → Supabase. Rate limit por IP (llamada de pago) |
| `POST /ideas/text` | JWT | Texto escrito → GPT-4o-mini → Supabase (mismo procesado, sin transcripción) |
| `DELETE /ideas/{idea_id}` | JWT | Elimina una idea |
| `GET /export` | JWT | Exportación de datos |
| `GET/POST /clothing`, `DELETE /clothing/{item_id}` | JWT | Widget **temporal** de conteo de ropa (ver "Frontend") |
| `GET /ha/events/soon` | servicio | Próximos eventos para las notificaciones de Alexa |
| `POST /wake-pc` | JWT | Marca `_wol_pending` |
| `GET /ha/wol-pending` | servicio | HA sondea cada 30s: devuelve y limpia el flag WOL |
| `POST /relaunch-agent` | JWT | Marca `_agent_relaunch_pending` |
| `GET /ha/agent-relaunch-pending` | servicio | HA lo recoge y relanza el agente por SSH |
| `POST /shutdown-pc` · `POST /suspend-pc` | JWT | Marcan `_pc_power_action` |
| `GET /ha/pc-power-pending` | servicio | HA lo recoge y apaga/suspende el PC por SSH |
| `POST /jobs` | JWT | Crea job en cola (valida `alud_url`, `dedupe_key` único) |
| `GET /jobs/pending` | agente | Lo que sondea `agent.py`. **El corte temporal va como `Z`, nunca `+00:00`** |
| `GET /jobs/by-id/{job_id}` | JWT | Job por ID |
| `POST /jobs/{job_id}/claim` · `/start` · `/finish` | agente | Transiciones de estado (PATCH condicional, atómicas) |
| `POST /jobs/{job_id}/events` | agente | Evento de progreso (stages) |
| `GET /jobs/{job_id}/events` | JWT | Eventos de un job (lo consume la barra de progreso) |
| `POST /jobs/{job_id}/retry` | JWT | Reintenta un job fallido (máx. `MAX_JOB_ATTEMPTS`) |
| `POST /agents/heartbeat` | agente | El agente reporta que está vivo |
| `GET /agents/{agent_id}` | JWT | Estado de un agente (p. ej. `pc-mikel`) |
| `GET /training/summary` | JWT | Sesiones pendientes, horas, dinero, fechas |
| `POST /training/sessions` · `DELETE /training/sessions/{session_id}` | JWT | Añadir/borrar sesión `{date, duration_hours}` |
| `PATCH /training/client` | JWT | Precio/hora y sesiones por cobro |
| `POST /training/payments` | JWT | Marca cobro de hoy (calcula el importe automáticamente) |
| `POST /health/ingest` | servicio | Webhook de Health Auto Export (métricas + workouts) |
| `POST /health/ingest/simple` | servicio | iOS Shortcut — acepta dict único o NDJSON |
| `GET /health/metrics?days=30` | JWT | Métricas de los últimos N días agrupadas por nombre + `last_sync` |
| `GET /health/latest` | JWT | Último valor de cada métrica |
| `PATCH /health/sleep/{date}/exclude` | JWT | Alterna `extra.excluded`: anula/restaura una noche |
| `GET /brief` | JWT | Datos del día en crudo (sin interpretar) |
| `POST /brief/send` | `BRIEF_TOKEN` | Envía el resumen diario por SMTP |
| `GET /logs` · `DELETE /logs` | JWT | Registro persistente para el panel de ajustes |

**CORS**: los orígenes permitidos salen de `CORS_ORIGINS` (por defecto
`http://localhost:5173` y el dominio de Vercel). Si añades otro origen de producción,
va ahí — no en `allow_origins` hardcodeado.

## Variables de entorno

`backend/.env.example` es la referencia completa y comentada; `backend/check_config.py`
verifica que la configuración está bien. Resumen:

**Obligatorias** (sin ellas el backend no arranca): `SECRET_KEY`, `DASHBOARD_PASSWORD`.

**Supabase**: `SUPABASE_URL`, `SUPABASE_KEY` (service_role, **nunca** la anon key).

**Microsoft Graph**: `CLIENT_ID`, `TENANT_ID`, `CLIENT_SECRET`, `REDIRECT_URI`.

**Servicios externos**: `GOOGLE_MAPS_API_KEY`, `OPENAI_API_KEY` (opcional de verdad:
sin ella el backend arranca y `/ideas/*` responde 503).

**Tokens de servicio** (valores aleatorios distintos entre sí): `HA_POLL_TOKEN`,
`HEALTH_INGEST_TOKEN`, `BRIEF_TOKEN`, `AGENT_TOKEN`.

**Resumen diario**: `BRIEF_TO`, `BRIEF_FROM`, `SMTP_HOST`, `SMTP_PORT`, `SMTP_USER`,
`SMTP_PASSWORD` (con Gmail y 2FA: una contraseña de aplicación), `ENTREGAS_MARKER`.

**Personalización**: `TIMEZONE`, `HOME_ADDRESS`, `CLASSES_CALENDAR`, `CORS_ORIGINS`,
`WEATHER_LAT`/`WEATHER_LON`, `ALUD_ALLOWED_HOSTS`.

**Opcionales**: `MAX_JOB_ATTEMPTS`, `LOGIN_MAX_ATTEMPTS`, `LOGIN_WINDOW_SECONDS`,
`LOGIN_BLOQUEO_MAX_SECONDS`, `HTTP_TIMEOUT`, `MAX_AUDIO_BYTES`, `MAX_INGEST_BYTES`,
`AUDIO_MAX_REQUESTS`, `AUDIO_WINDOW_SECONDS`, `TRUST_FORWARDED_FOR`, y las de registro
(`LOG_PERSIST`, `LOG_PERSIST_LEVEL`, `LOG_QUEUE_MAX`, `LOG_FLUSH_SECONDS`,
`LOG_RETENTION_DAYS`, `LOG_SLOW_MS`).

**Frontend** (Vercel): `VITE_API_URL`, `VITE_HA_URL`, `VITE_HA_DASHBOARD_PATH`,
`VITE_ENTREGAS_MARKER`. Ojo: el backend no ve las `VITE_*`, por eso `ENTREGAS_MARKER`
está duplicado en los dos lados y **tienen que coincidir**.

**Agente** (`agent/.env`): `AGENT_TOKEN` (mismo valor que en el backend), `LA_API_BASE`,
`LA_TOKEN` (solo respaldo — caduca), `EDGE_PROFILE_DIR`, `ALUD_ACCOUNT`,
`ALUD_ALLOWED_HOSTS`, `SUNSHINE_EXE`/`SUNSHINE_SERVICIO`/`SUNSHINE_TIMEOUT`,
`VPN_TIPO`/`TAILSCALE_EXE`/`TAILSCALE_SERVICIO`/`VPN_TIMEOUT`, `ARRANQUE_ESPERA_RED`.
**Ya no lleva `SUPABASE_URL`/`SUPABASE_KEY`**: se quitaron a propósito (ver "Cola de jobs").

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
`health_workouts`, `health_hub` (Salud). Cada uno se renderiza en `renderWidget(id)`.
La configuración (visibilidad, columna, orden, tamaño, splits) se persiste en
`localStorage`, con selección independiente en modo completo (`la_widget_config`) y
simple (`la_simple_widget_config`).

Qué hace cada uno:

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
5. **Entrenamiento (`training`)** — sesiones desde el último cobro, euros pendientes,
   formulario de añadir sesión, botón de cobro.
6. **Ideas (`ideas`)** — grabación de audio (Whisper) **o** texto escrito ("✎ Escribir
   idea") → extracción con GPT-4o-mini → Supabase. Si la nota señala una cita, ofrece un
   chip para crear el evento (nunca lo crea solo).
7. **Conteo ropa (`clothing`)** — **TEMPORAL**, ver abajo.
8. **Streaming PC (`acciones_pc`)** — encender el PC (WOL), lanzar el job de streaming,
   apagar/suspender. Barra de progreso con polling cada 2s y badge de estado
   (pending/claimed/running) con los stages en nombres legibles.
9. **Bienestar (`health_wellness`)** — toggle "Semana | Hoy". Puntuación 0–100 +
   insights + recomendación + hora de la última sync. Al final, el mini-apartado
   **Composición corporal**: peso (`weight_body_mass`), % grasa y masa magra en la misma
   fila, cada uno con flecha ↑↓ coloreada. La del peso se colorea según si te acercas o
   alejas del objetivo configurado en ⚙; la barra de progreso indica la **distancia real**
   ("faltan X.X kg", no solo un %) y se colorea según la tendencia reciente
   (`weightDelta`): verde si te acercas, rojo si te alejas.
10. **Sueño (`health_sleep`)** — noche anterior: duración, fases (profundo/REM/core/
    despierto) con tooltips, puntuación 0–100 y resumen de las últimas 7 noches. Botón
    **"Anular noche"** para excluir noches con datos malos (p. ej. el Watch en carga);
    las anuladas se omiten de todos los cálculos. Cada barra del historial es clickable
    para excluir/restaurar. El flag vive en `extra.excluded` de Supabase.
11. **Freq. cardíaca / HRV / Actividad / Entrenamientos AW** — sparklines y listas de
    detalle (ocultos por defecto; el hub de salud los reutiliza).
12. **Salud (`health_hub`)** — widget compacto con veredicto general + top conclusiones;
    al pulsar abre el modal `healthModalOpen` con TODAS las conclusiones por dominio + los
    widgets de salud de detalle reutilizados vía `renderWidget`.

**Motor de conclusiones**: lógica pura y testeada en `helpers.js` —
`healthConclusions` (exprime todas las métricas del Watch y devuelve conclusiones
`{domain, tone, text}`) y `healthOverall` (veredicto), apoyándose en
`seriesTrend`/`trendDirection`/`bedtimeHrvInsight` y en `pairByDate`/`splitCompare`
para los cruces entre series.

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

- **`Sparkline`** acepta `objetivo` (dibuja una línea discontinua de referencia,
  metiéndolo en el rango vertical para que nunca quede fuera del gráfico) y
  `relleno` (área bajo la curva). Se usa en el bloque de composición corporal
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
- **Panel de estado del sistema**: backend, sesión de Outlook, última sincronización del
  Watch, agente PC, entrenamiento y **Registro** (los errores del backend, de `GET /logs`),
  todo en un mismo sitio. Se recarga al abrir ajustes y con su botón — nunca en un
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
`la_simple_widget_config`. Si añades una, mantén el prefijo y el `try/catch` al parsear.

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

## Módulo Salud (Apple Watch)

### Flujo de datos

Dos fuentes de ingesta en paralelo:

1. **Health Auto Export** (app) → `POST /health/ingest` → Supabase — incluye workouts y
   sueño con fases detalladas.
2. **iOS Shortcut "Run Custom Automation"** → `POST /health/ingest/simple` → Supabase —
   métricas del día en tiempo real.

### Configuración de Health Auto Export

- Dos automatizaciones REST API: una para **Health Metrics** y otra para **Workouts**.
- Export Format: JSON v2, Summarize Data: ON, **Batch requests activado** (manda todas
  las métricas en un POST en vez de uno por métrica).
- Sync Cadence: 5 min (pero iOS no garantiza la ejecución — el workaround es un Atajo de
  iOS con 3 horarios fijos al día).
- El sync en segundo plano requiere: Ajustes → General → Actualización en segundo plano →
  Health Auto Export → ON.
- Para datos históricos: cambiar Date Range a "Last 30 Days" y hacer Export Now manual.

Métricas del bulk export: `active_energy`, `apple_exercise_time`, `apple_stand_hour`,
`flights_climbed`, `heart_rate`, `heart_rate_variability`, `resting_heart_rate`,
`respiratory_rate`, `sleep_analysis`, `step_count`, `vo2_max`,
`walking_running_distance`, `walking_heart_rate_average`, `cardio_recovery`,
`time_in_daylight`, `weight_body_mass`, `body_fat_percentage`, `lean_body_mass`,
`resting_energy`, `physical_effort`.

**Nombres reales en Supabase** (el que usa Health Auto Export puede diferir del lógico):
el peso es `weight_body_mass` (NO `weight`); `body_fat_percentage` y `lean_body_mass`
sí coinciden.

### iOS Shortcut "Run Custom Automation"

- **Métricas**: `step_count`, `active_energy`, `exercise_time`, `resting_heart_rate`,
  `heart_rate_variability`, `respiratory_rate`, `vo2_max`, `sleep_analysis`.
- **Formato del body**: iOS Shortcuts serializa las listas como NDJSON (un dict por línea)
  dentro de un único campo `{"metric": "..."}`. El backend lo parsea automáticamente.
- **Filtros de fecha**: `step_count`, `active_energy`, `exercise_time` → *Start Date is
  today*; métricas nocturnas (HRV, FC en reposo, respiración, sueño) → *in the last 2
  days*; `vo2_max` → *in the last 7 days*.
- **Bug conocido**: `respiratory_rate` puede acabar con el mismo valor que
  `heart_rate_variability` si el paso "Get Value from Item from List" queda DESPUÉS del
  Dictionary. Verificar que va antes.

#### Pendientes del Shortcut

**1. Sueño con fases** — sustituir el paso actual de `sleep_analysis` por un bucle:

1. *Find Health Samples*: Sleep Analysis, Yesterday 20:00 → Today 12:00, **sin Group by**.
2. Variables iniciales: `deep=0`, `rem=0`, `core=0`, `awake=0`.
3. *Repeat with each* item:
   - Get Details → **Value** → fase (Core/Deep/REM/Awake).
   - Get Details → **Duration** (segundos) → /3600 → horas.
   - Si la fase es "Deep" → `deep += horas`; "REM" → `rem += horas`; "Core" →
     `core += horas`; "Awake" → `awake += horas`.
4. `total = deep + rem + core`.
5. Dictionary: `metric=sleep_analysis`, `date=fecha_hoy`, `value=total`, `unit=hr`,
   `extra={deep, rem, core, awake}`.

El backend ya soporta `extra` en `/health/ingest/simple` (sin cambios de servidor) y el
frontend ya usa `extra.deep`/`extra.rem`/`extra.core` para el score y el widget.

**2. Workouts** — añadir después del bucle de sueño:

1. *Find Workouts*: Yesterday 04:00 → Now.
2. `workout_list=[]`.
3. *Repeat with each* workout: Name (tipo), Duration (segundos), Start Date →
   `yyyy-MM-dd`, Active Calories → dict `{name, duration, start, activeEnergy}` → add.
4. Dictionary final: `metric=workouts`, `date=fecha_entreno`, `value=count(workout_list)`,
   `unit=count`, `extra={workouts: workout_list}`.

El widget de bienestar cuenta con `d.extra?.workouts?.length` y "Entrenamientos AW" usa
`w.name`, `w.duration` y `w.start` — la estructura es compatible con ambos.

### Tabla Supabase `health_metrics`

```sql
metric_date  date        -- fecha de la métrica (YYYY-MM-DD)
metric_name  text        -- sleep_analysis, heart_rate, heart_rate_variability,
                         -- step_count, active_energy, workouts...
value        numeric     -- valor principal (horas de sueño, bpm, pasos...)
unit         text        -- unidad
extra        jsonb       -- datos adicionales (fases de sueño, workouts del día...)
UNIQUE(metric_date, metric_name)
```

### Notas técnicas

- **Workouts** llegan en `data.workouts` (no en `data.metrics`) — se guardan como una
  fila por día con `extra.workouts = [array]`. La duración viene en segundos en v2
  (dividir entre 60 para minutos) y las calorías pueden ser `activeEnergy.qty` (objeto)
  o un número directo según la versión.
- **Sleep**: `value` puede ser 0 si Health Auto Export no rellena el campo principal; el
  frontend calcula la duración real desde `extra.asleep` o sumando las fases.
- **Extracción de valor acumulativo**: se toma el `max()` de todos los campos no-None
  (`qty`, `sum`, `value`) del punto JSON. Health Auto Export v2 usa `qty` para el total
  diario; `sum` puede llegar como 0 y no debe usarse como valor principal.
- **Métricas acumulativas**: nunca se sobreescriben con un valor menor (previene que un
  sync parcial del día borre el total). Sí se sobreescribe si el valor existente es 0.
- **Upsert en lote con `on_conflict`**: ver "Ingesta de salud" en los patrones del
  backend, y el bug histórico del 409. *(Esto sustituye al esquema antiguo de
  GET + POST/PATCH por métrica, que se retiró al pasar a lotes.)*
- **`last_sync` en `/health/metrics`**: como el upsert no actualiza `created_at`, si hay
  cualquier fila con `metric_date = hoy` se devuelve `datetime.now()` como `last_sync` en
  vez del `created_at` real.
- **Reenvíos de varios días soportados**: el Shortcut puede mandar `sleep_analysis` (y el
  resto) de los últimos N días en cada sync — cada muestra se procesa con su propio
  `metric_date`, así que cada día es una fila independiente y no pisa otras fechas. Para
  `sleep_analysis` concretamente, antes de escribir se comprueba si la fila existente
  tenía `extra.excluded=true` y, si es así, se preserva — evita que un reenvío "resucite"
  una noche que el usuario había anulado a mano.
- **Scripts de mantenimiento en Supabase**: `backend/.env` local **no contiene**
  `SUPABASE_URL`/`SUPABASE_KEY` (solo están en los secrets de Fly). Para ejecutar un
  script contra la BD: mételo en `backend/` (se copia al contenedor en `fly deploy`) y
  lánzalo con
  `fly ssh console -a backend-tender-glow-160 -C "python3 /app/script.py"`.
  `fly sftp put` no funciona bien en Windows (problema de rutas).

### Puntuaciones (bienestar y sueño)

**`helpers.js` es la única fuente de verdad de estos umbrales.** Los números de abajo son
una referencia de lectura: si no cuadran con el código, manda el código. No los copies a
ningún otro sitio (así se reintrodujo el bug del tooltip de sueño).

**Bienestar (`wellnessBreakdown` + `scoreFromBreakdown`, normalizado a 100)**:

| Componente | Máx. | Notas |
|---|---|---|
| 😴 Sueño | 25 | ≥7.5h = 25 · ≥7h = 21 · ≥6.5h = 15 · ≥6h = 9 · resto 4 |
| 💪 Entreno | 15 | Diario: gym = 15; si no, ejercicio ≥30min = 9, ≥15min = 5, HRV alta = 3/2/1. Semanal: escalado por `expectedByNow` |
| 🚶 Pasos | 8 | ≥10.000 = 8 · ≥8.000 = 6 · ≥6.000 = 4 · ≥4.000 = 2 |
| 🔥 Energía activa | 5 | ≥600 kcal = 5 · ≥400 = 4 · ≥250 = 3 · ≥100 = 1 |
| 🧍 De pie | 2 | ≥12h = 2 · ≥8h = 1 |
| 🪜 Pisos | 2 | ≥10 = 2 · ≥5 = 1 |
| ❤️ HRV | 12 | Contra la referencia de la semana anterior: ≥105% = 12 · ≥95% = 8 · resto 4 |
| 🫀 FC en reposo | 8 | ≤50 = 8 · ≤55 = 7 · ≤60 = 6 · ≤65 = 4 · ≤70 = 3 · ≤80 = 1 |
| 💓 Recuperación cardio | 5 | Solo si el Watch la reporta |
| 🫁 VO₂max | 6 | **Solo vista diaria** |
| 🏃 FC caminando | 4 | **Solo vista diaria** |
| ⚖️ % Grasa | 4 | **Solo vista diaria** |
| ☀️ Luz natural | 5 | **Solo vista diaria** |
| 🌬️ Respiración | 5 | **Solo vista diaria** |

Las cinco últimas solo entran en la vista diaria porque el Watch las actualiza de forma
esporádica y promediarlas por semana no dice nada. Un componente `sinDatos` queda fuera
de la fracción: no tener un sensor no puntúa como tenerlo y sacar un cero. El score tiene
un tooltip con el desglose por componente (pts obtenidos / máximo + valor). Los entrenos
de la semana se cuentan **desde el lunes**, no en una ventana rodante de 7 días.

**Sueño (`sleepBreakdown` + `sleepScore`)**: duración 40 + profundo 25 + REM 25 +
tiempo despierto 10, más una penalización por hora de acostarse (02:00–05:59 = −15,
01:00 = −10, 00:00 = −5) y un **techo por duración**: ≥8h → 100, ≥7.5h → 82, ≥7h → 68,
resto 52 (dormir poco no puede dar nota alta por muy buenas que sean las fases).
`respiratory_rate` penaliza indirectamente vía `calcRecoveryMod` (hasta −5 pts si la
frecuencia sube >5% sobre la baseline de 30 días).

**Objetivo del usuario**: 4 entrenamientos de gimnasio por semana (registrados en Hevy →
Apple Health).

## Módulo Entrenamiento

El usuario entrena a personas y cobra 16 €/hora, generalmente cada 4 sesiones.

### Tablas de Supabase

- `training_clients` — `price_per_hour=16`, `sessions_per_payment=4`. **No hardcodees
  estos valores**: salen de la tabla.
- `training_sessions` — sesiones (42 históricas importadas, sep 2025 – may 2026).
- `training_payments` — cobros (6 importados, ene–may 2026).

### Notas técnicas

- **El filtro de sesiones pendientes va por `created_at`, no por `date`**: antes la query
  usaba `date=gt.{last_payment_date}` (comparando solo la fecha) — si se cobraba hoy y
  luego se entrenaba hoy, la sesión nueva tenía la misma `date` que el cobro y el `gt` la
  excluía (no aparecía en el widget, aunque sí en "sesiones recientes" de Ajustes, que no
  filtra). Ahora `/training/summary` y `POST /training/payments` comparan el `created_at`
  del último pago contra el `created_at` de las sesiones.
- **Codifica `created_at` con `urllib.parse.quote` al meterlo en la query de Supabase**:
  el timestamp lleva `+00:00` y el `+` sin codificar se lee como un espacio en una query
  string, rompiendo el filtro `gt.` contra PostgREST (devolvía 0 filas, sin error visible)
  — no aparecía **ninguna** sesión pendiente. Es el mismo fallo que tumbó
  `/jobs/pending`; ver "Bugs históricos".
- El último pago se obtiene con `order=created_at.desc` (no `order=date.desc`), para que
  sea el cobro más reciente en el tiempo y no solo por fecha.
- El importe se calcula al marcar el cobro (horas desde el último cobro × precio).

## Home Assistant

**Las credenciales, el token, la IP local y la estructura de ficheros están en
`HOMEASSISTANT.md`, que está en `.gitignore`.** No los copies aquí: este fichero se
versiona en un repo público.

- Acceso por SSH con `paramiko` (Python) — `sshpass` no está disponible en Windows.
- **Escritura de ficheros**: SFTP no está disponible; hay que usar `sudo tee` por el canal
  SSH:
  ```python
  channel = client.get_transport().open_session()
  channel.exec_command("sudo tee /config/archivo.yaml > /dev/null")
  channel.sendall(contenido.encode())
  channel.shutdown_write()
  ```
- **Automatizaciones vía API**: se crean/actualizan con
  `POST /api/config/automation/config/{id}` — no hace falta tocar `automations.yaml`.
- Tras cambiar `configuration.yaml` → reiniciar HA. Tras cambiar `automations.yaml` →
  basta con recargar las automatizaciones.

**Flujo WOL** (funcionando): frontend → `POST /wake-pc` (Fly) → flag `_wol_pending` en
memoria → HA sondea `GET /ha/wol-pending` cada 30s vía
`sensor.life_assistant_wol_pending` → la automatización `la_wol_poll` detecta el cambio a
`true` → pulsa `button.pc_mikel`.

Problemas ya resueltos por el camino (no los reintroduzcas):

- *Mixed content* (HTTPS→HTTP): el navegador no puede llamar a HA directamente → por eso
  el backend hace de intermediario.
- `rest_command` en la automatización fallaba al parsear el JSON en la plantilla → la
  solución fue un REST sensor + trigger de estado.
- El sensor está definido en `configuration.yaml` (`scan_interval: 30`); la automatización
  `la_wol_poll` se creó por la REST API y **no** está en `automations.yaml`.

Además, HA anuncia por Alexa el **nombre** del evento 15 minutos antes (no solo "evento en
15 minutos"), usando `/ha/events/soon`.

## Agente PC (`agent/agent.py`)

Agente Windows **efímero**: arranca con Windows (vía WOL), drena la cola de jobs y se
cierra. Se registra en el backend con heartbeat. **Solo funciona en un PC Windows real**
(Edge, pyautogui, Claude Desktop): no tiene tests ni puede tenerlos en CI.

### Ciclo de vida

- Se autentica con `AGENT_TOKEN` (`LA_TOKEN`, el JWT, solo como respaldo y avisando por
  el log de que caduca).
- **Un fallo al consultar la cola no puede parecerse a una cola vacía**:
  `pedir_job_pendiente()` lanza `ErrorAuth` o `ErrorTransitorio` en vez de devolver
  `None`, y `main()` sale con código 2 (auth) o 3 (red) para que el Programador de tareas
  lo marque como error en vez de dejar "Last Result: 0" en un arranque que no hizo nada.
- El primer sondeo se reintenta durante `ARRANQUE_ESPERA_RED` (90 s): el agente corre a la
  vez que Windows y tras un WOL la tarjeta puede no tener IP todavía — el intento moría
  con un fallo de DNS a los 200 ms y se perdía justo el arranque que traía el job.
- Según `payload["accion"]` despacha a `ACCIONES` (`resolver_alud`, `abrir_streaming`).
  Compatibilidad: jobs sin `accion` pero con `alud_url` → `resolver_alud`.
  `resolver_accion()` + guard `attempted` (cada job se intenta una vez por ejecución para
  no repetir en bucle si falla el claim por red).

### Acción `abrir_streaming`

- **Levanta la VPN antes de lanzar Sunshine** (`conectar_vpn()`, Tailscale): el PC lo
  enciende un WOL sin nadie delante, así que el túnel no está arriba y desde fuera de casa
  Moonlight no llega. Mismo criterio que con Sunshine: el servicio de Tailscale va en
  arranque MANUAL para que el PC no tenga la VPN encendida en el día a día, y lo arranca
  el agente (`arrancar_servicio()`, que necesita que la tarea del Programador corra con
  privilegios elevados). El estado del servicio se consulta con `Get-Service`, no con
  `sc query`: este último traduce el estado y en un Windows en español devuelve
  "EN EJECUCIÓN". La IP de la tailnet viaja al modal en el mensaje del stage `vpn_ready`,
  de donde la saca `hostStreaming()` (helpers) — no se guarda en ningún sitio. Un fallo de
  VPN **no tumba el job**: se reporta `vpn_error` y se abre Sunshine igual, que en la LAN
  sigue sirviendo.
- **Sunshine se arranca por su servicio** (`SUNSHINE_SERVICIO`, mismo `arrancar_servicio()`
  que Tailscale), no ejecutando `sunshine.exe`: al agente lo lanza el Programador de tareas
  fuera del escritorio del usuario, y el binario arrancado desde ahí muere al instante. El
  `Popen` del exe queda solo como respaldo para instalaciones sin servicio. Y **el job no
  se da por hecho sin comprobarlo**: `arrancar_sunshine()` espera hasta `SUNSHINE_TIMEOUT`
  a ver el proceso vivo (`sunshine_vivo()`) y si no aparece lanza, de modo que el job cae a
  `failed` en vez de reportar `streaming_ready` sobre un PC sin nada abierto.

### Acción `resolver_alud` — notas de Edge, Playwright y Claude Desktop

Flujo: Edge (proceso detached) → CDP → login en Alud → extracción del enunciado →
Claude Desktop → Ctrl+2 (Cowork) → Win+V → Enter → Enter.

- **Edge se lanza como proceso DETACHED**
  (`subprocess.Popen(..., creationflags=DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP)`) con
  `--remote-debugging-port=<aleatorio 49200–49900>` (`EDGE_DEBUG_PORT = random.randint(...)`,
  ya no un `9222` fijo: Chromium solo lo expone en loopback, pero randomizarlo reduce la
  ventana frente a sondeos del puerto conocido). Al ser DETACHED, Edge no es hijo de Python
  y sobrevive cuando el agente termina.
- **Playwright se conecta con `connect_over_cdp(f"http://localhost:{EDGE_DEBUG_PORT}")`**,
  que devuelve un `Browser`, NO un `BrowserContext`. Hay que usar `browser.contexts[0]`
  para quedarse con el contexto del perfil real (cookies, sesión de Alud/Okta). Al final se
  cierra solo la conexión de Playwright; Edge queda abierto a propósito.
- El perfil sale de `EDGE_PROFILE_DIR` (por defecto el perfil de usuario de Edge).
- **`ALUD_ACCOUNT`** debe estar en `agent/.env`: si está vacío, aparece el selector de
  cuentas y el agente no sabe en cuál pulsar (deja un WARNING en el log).
- **Claude Desktop** está instalado como app de la Microsoft Store: se lanza con
  `explorer.exe shell:AppsFolder\<APPID>` — **no** con el exe `claude.exe`, que es el CLI.
- **Foco de la ventana**: `_focus_claude_window()` usa PowerShell + win32
  (`SetForegroundWindow`, `ShowWindow`) buscando el proceso `claude` por `MainWindowHandle`.
  No uses `AppActivate` por título: falla si el título no coincide exactamente.
- **Clipboard**: el enunciado se escribe a un fichero temporal UTF-8 y
  `Set-Clipboard -Value (Get-Content -Raw -Encoding UTF8 -LiteralPath ...)` lo carga →
  `Win+V` + Enter (historial) + Enter (enviar). **Nunca interpoles el enunciado** (texto de
  una web externa) dentro del comando de PowerShell — ver invariante 9.
- El log del agente se escribe en el working directory del proceso, que puede no ser el
  directorio del script cuando lo lanza el Programador de tareas.

## Tests: cómo funcionan y sus trampas

### Backend (`tests/backend`, 293 tests)

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

### Frontend (`tests/frontend`, 81 tests)

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

### E2E (`tests/e2e`, Playwright)

`npm run test:e2e`. Navegador real contra el **build de producción** servido por
`vite preview` y el **backend de verdad** — no una imitación:
`tests/e2e/servidor_pruebas.py` importa `backend/main.py` tal cual y solo sustituye
`main.http` por respuestas fijas (mismo truco que `conftest.py`, pero servido por
uvicorn). Por eso este job pilla lo que los otros dos no: que el bundle compilado
arranque, que el contrato entre frontend y backend siga cuadrando, y que no haya
errores de runtime al montar. Los tests fallan si el navegador registra **cualquier**
excepción o error de consola, no solo si falta un texto.

- `playwright.config.js` arranca y apaga los dos servidores solo. `VITE_API_URL` se
  hornea en el bundle, así que el build se hace apuntando ya al backend de pruebas.
- **Los datos del simulador no son de adorno**: llevan una correlación plantada
  (pasos ↔ sueño) para que el motor de patrones tenga algo que encontrar y el test
  compruebe que el widget de salud llega a conclusiones, no solo que se pinta.
- En `_RouterSimulado.RUTAS` **el orden importa**: gana la primera coincidencia y la
  URL de `calendarView` del calendario de clases contiene `/me/calendars`. Ponerlas al
  revés hacía que `/calendar/classes` recibiera calendarios donde espera eventos y
  acabara en un 500 (que además el navegador reporta como error de CORS, porque una
  excepción sin capturar se salta el middleware que pone las cabeceras).
- `PLAYWRIGHT_CHROMIUM_PATH` apunta a un Chromium ya instalado en entornos que traen
  el suyo y no coincide con la versión de Playwright. En CI no se usa: se descarga el
  que toca.

## Bugs históricos (no los reintroduzcas)

- **El job de streaming decía "Sunshine abierto" con Sunshine sin abrir.** El agente
  hacía `subprocess.Popen([SUNSHINE_EXE])` y reportaba `streaming_ready` acto seguido.
  Pero `Popen` sin excepción solo dice que Windows aceptó *crear* el proceso, no que
  siga vivo un segundo después: al agente lo lanza el Programador de tareas fuera del
  escritorio del usuario, y Sunshine desde ahí se cierra al instante (ni proceso, ni
  puertos escuchando, `SunshineService` en `Stopped`). El log del agente terminaba con
  "✅ Sunshine lanzado" y el job en `done`. La tercera vez que aparece el mismo patrón
  del proyecto —el 409 del Watch, el 401 del agente, esto—: **lanzar algo no es
  comprobar que funciona**, y un job solo se marca `done` tras verificar el efecto.
  Arreglado arrancando el servicio (como Tailscale) y esperando a ver el proceso vivo.
- **`/jobs/pending` era un 502 fijo por un `+` en la query string.** El corte de "última
  hora" se formateaba como `...T05:10:01+00:00` y se pegaba a la URL de Supabase; en una
  query string el `+` significa espacio, así que PostgREST leía `...T05:10:01 00:00` y
  devolvía 400 (`22007`, timestamp inválido). Estuvo tapado detrás del 401 del token
  caducado del agente: solo se vio al arreglar la auth. **Los timestamps que viajan en
  una URL van con sufijo `Z`, nunca con `+00:00`** (o `quote()`-ados). Hay test. El mismo
  fallo se había dado antes con el `created_at` del último pago en `/training/summary`,
  donde la solución fue `urllib.parse.quote`.
- **El agente PC se cerraba en cada arranque diciendo "No hay jobs pendientes".** El
  `LA_TOKEN` de su `.env` era un JWT del dashboard y caducó a los 30 días, así que
  `GET /jobs/pending` devolvía 401. Pero `poll_pending_job()` capturaba *todo* con un
  `except Exception` y devolvía `None`, el mismo valor que "la cola está vacía": el
  agente registraba un WARNING y salía con código 0, con lo que la tarea del Programador
  también lo daba por bueno. Desde fuera parecía que el WOL funcionaba y que
  simplemente no había trabajo. Dos moralejas, las mismas que dejó el 409 del Watch:
  **"no pude preguntar" no es "no hay nada que hacer"**, y **lo que arranca solo no
  puede depender de una credencial que caduca** (ver `AGENT_TOKEN`). El caso está
  cubierto por `TestAuthAgente::test_jwt_caducado_da_401`.
- **El Watch dejó de sincronizar sin que nada diera error.** El upsert en bloque de la
  ingesta de salud (`resolution=merge-duplicates`) no llevaba `on_conflict`, así que
  PostgREST lo resolvía contra la clave primaria (`id`) en vez de contra
  `unique(metric_date, metric_name)`: en cuanto el lote traía una métrica que ya
  existía para ese día, Supabase devolvía 409 y **no se guardaba nada**, ni siquiera lo
  nuevo. Antes esto no se veía porque cada métrica se escribía por separado con un
  `POST → si 409, PATCH`; el paso al lote se llevó por delante ese respaldo y dejó el
  POST tal cual. Dos cosas lo mantuvieron invisible durante días: el endpoint respondía
  `200 {"ok": true}` metiendo el fallo en una clave `errors` que nadie lee, y el único
  síntoma visible era el "sync hace Nd" del dashboard. Los mocks de los tests no lo
  cogían porque simulan Supabase, no PostgREST. Moraleja doble: **nombra la restricción
  en todo upsert cuya unicidad no sea la clave primaria**, y **un fallo de escritura no
  puede salir por una clave del cuerpo con un 200 delante**.
- **Bucle infinito de recargas en el login móvil.** `apiFetch` recargaba la página ante
  cualquier 401, pero los `useEffect` de carga inicial se ejecutan al montar aunque no
  haya sesión y devuelven 401: la pantalla de login parpadeaba sin dejar pulsar nada.
  Ahora solo borra el token y recarga **si `la_token` existía** (sesión caducada).
- **Eventos creados con la fecha equivocada** por el locale del SO en
  `<input type="date">`: en un Windows con locale americano `08/06/2026` se leía como
  mes/día. De ahí vienen `DateInput`/`TimeInput`, que parsean siempre `DD/MM/AAAA` y 24h.
  Relacionado: calcular la fecha por defecto con `toISOString()` la desplaza un día atrás
  en `Europe/Madrid` — usa componentes locales.
- **Sesiones de entrenamiento que no aparecían** al entrenar el mismo día que se cobraba
  (filtro por `date` en vez de `created_at`) y, más grave, **ninguna** sesión pendiente
  cuando el `+00:00` del timestamp viajaba sin codificar en la query de Supabase.
- **El token de Graph se perdía en cada `fly deploy`** cuando vivía en `backend/.token`:
  el filesystem del contenedor se reconstruye desde la imagen. Ahora está en
  `oauth_tokens` (Supabase) y `.dockerignore` excluye `.env`/`.token` de la imagen.
- **El login fallaba con error de CORS, no de credenciales**, cuando Vite arrancaba en
  5174 porque 5173 estaba ocupado. Libera el puerto; no añadas el nuevo a `allow_origins`.
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

## Despliegue

**Frontend**: push a `main` → Vercel despliega automáticamente.

**Backend (Fly.io)** — manual, nunca en automático:

```bash
cd backend && fly deploy
```

También está el workflow `Deploy backend (Fly.io)`
(`.github/workflows/deploy-backend.yml`, `workflow_dispatch`, usa el secret
`FLY_API_TOKEN`). El backend escala a cero cuando no hay tráfico
(`min_machines_running = 0`), de ahí el arranque en frío de 10–15s.

**Migraciones de Supabase**: se aplican a mano desde el editor SQL. Las que hay:
`20260508_jobs_queue`, `20260511_job_events`, `20260511_job_results`,
`20260607_oauth_tokens`, `20260707_esquema_base`, `20260724_clothing`,
`20260729_rls_jobs`, `20260730_login_attempts`, `20260802_app_logs`.

## Convenciones

- **Idioma**: todo en español (código nuevo incluido: comentarios, strings, tests).
- **Commits**: minúscula, estilo `área: descripción` (ej. `tests: ...`, `lint: ...`,
  `seguridad: ...`, `bienestar: ...`). `main` mantiene historial lineal (squash merge).
- **Autoría: los commits NO llevan trailer `Co-Authored-By` de Claude.** Esto es un
  repositorio de una sola persona y la coautoría solo mete un avatar de más en cada
  commit sin aportar nada. Aplica **aunque las instrucciones por defecto de la
  herramienta pidan añadirlo**: esta norma manda sobre ellas. Tampoco se firman con
  ningún otro trailer de atribución automática.
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
- No metas datos personales (IPs, direcciones, rutas de usuario, tokens) en ficheros
  versionados — este incluido. Van a `HOMEASSISTANT.md` o a un `.env`.
- No hagas deploy del backend salvo que se pida: afecta a producción real. El deploy
  es manual — `fly deploy` desde `backend/`, o el workflow `Deploy backend (Fly.io)`
  (`.github/workflows/deploy-backend.yml`, `workflow_dispatch`; usa el secret
  `FLY_API_TOKEN`). Nunca en automático al hacer push.
