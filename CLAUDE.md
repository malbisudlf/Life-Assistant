# CLAUDE.md

Guía para trabajar en este repositorio. **Este fichero es el índice y lo que aplica
siempre**; el detalle de cada área vive en `docs/` (ver "Dónde está el resto de la
guía"). Antes de tocar un área, lee su fichero entero: casi todos los errores que se
pueden cometer aquí ya los hemos cometido antes y están documentados.

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

Y hay un workflow nocturno (`revision-nocturna.yml`) que, si ese día entraron
commits en `main`, lanza una sesión de Claude Code que los revisa y abre un issue
con los hallazgos. Si lo abre, `revision-aviso.yml` se lo cuenta al backend y por la
mañana llega al móvil una notificación con dos botones: «Arreglarlo» —que lanza otra
sesión que lo arregla, abre PR y mergea si el CI pasa— y «No hacer nada». Todo en
`docs/REVISION_NOCTURNA.md`.

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
    ├── OpenAI ── Whisper (transcripción), GPT-4o-mini (extracción de ideas
    │              y cerebro de Jarvis, con herramientas sobre el resto de endpoints)
    ├── Supabase REST ── ideas, clothing, jobs, pc_agents, training_*, health_metrics,
    │                    oauth_tokens, login_attempts, app_logs, presence, brief_envios
    └── Home Assistant ── HA sondea al backend (WOL/eventos, flags de relanzado y
                          apagado/suspensión del PC que ejecuta por SSH, y el reloj de
                          respaldo del resumen diario) y EMPUJA la presencia
                          (POST /ha/presencia, único sentido inverso)

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
| `docs/` | El resto de la guía, por áreas (ver "Dónde está el resto de la guía") |
| `docs/DESPLIEGUE.md` | Guía de despliegue del kit para terceros |
| `backend/.env.example` | Todas las variables del backend, documentadas una a una |
| `backend/check_config.py` | Comprueba que la configuración del backend está completa |

## Dónde está el resto de la guía

La guía se partió en piezas para que una sesión no cargue 2.300 líneas cuando va a
tocar una sola área. **Lo que hay aquí aplica siempre**: seguridad del repo, comandos,
arquitectura, invariantes del backend, despliegue y convenciones. Lo demás:

| Fichero | Cuándo leerlo |
|---|---|
| `docs/BACKEND_PATRONES.md` | **Antes de tocar `backend/main.py`.** El núcleo: cliente HTTP saliente, ideas, zonas horarias, tokens de Graph, cola de jobs, ingesta de salud, flags del PC, presencia, clima, consultas en paralelo y registro persistente |
| `docs/BRIEF.md` | El resumen diario por correo y el informe semanal: qué va dentro, cuándo sale, la idempotencia y el interruptor |
| `docs/JARVIS.md` | Jarvis (herramientas, confirmación, memoria, MCP, web, la casa) y todo lo proactivo: recordatorios, avisos al móvil, reglas, vigilancias, correo entrante y los vigilantes |
| `docs/BACKEND_REFERENCIA.md` | Referencia de endpoints (ruta → auth → qué hace) y catálogo de variables de entorno |
| `docs/FRONTEND.md` | Antes de tocar `src/components/Dashboard.jsx` o `src/lib/helpers.js`: organización, auth en el cliente, PWA, widgets, layout, panel ⚙, modo simple, motor de conclusiones de salud y reglas de React/ESLint |
| `docs/SALUD.md` | Módulo del Apple Watch: flujo de ingesta, Health Auto Export, el Atajo de iOS, tabla `health_metrics` y las puntuaciones de bienestar y sueño |
| `docs/ENTRENAMIENTO.md` | Módulo de entrenamiento personal (sesiones, cobros y sus trampas de query) |
| `docs/HOME_ASSISTANT_FLUJOS.md` | Los flujos entre HA y el backend (WOL, presencia, avisos al móvil, la casa, el tick del resumen) |
| `docs/AGENTE_PC.md` | `agent/agent.py`: ciclo de vida, por qué no hay PowerShell en el camino crítico, streaming y Alud |
| `docs/TESTS.md` | Antes de escribir tests: cómo está montado cada suite y sus trampas conocidas |
| `docs/BUGS_HISTORICOS.md` | **Antes de dar por nuevo un fallo raro.** Cada bug con su moraleja; no los reintroduzcas |
| `docs/HOME_ASSISTANT_JARVIS.md` | El YAML que va instalado en Home Assistant |
| `docs/DESPLIEGUE.md` | Guía de despliegue del kit para terceros |
| `docs/REVISION_NOCTURNA.md` | La revisión nocturna del código: la routine de Claude Code, la skill con el checklist y el workflow que la dispara |
| `docs/IDEAS.md` | Ideas propuestas y sin hacer |
| `docs/JARVIS_PROACTIVO.md` | Ideas para que Jarvis actúe sin que se lo pidan, más allá de lo ya implementado en `docs/JARVIS.md` |
| `docs/EL_PROYECTO_EXPLICADO.md` | Explicación del proyecto entero para alguien de fuera: qué es, qué hace y por qué está construido así. No es guía de trabajo |

**Al añadir documentación, va al fichero de su área, no aquí.** Este solo crece si lo
nuevo aplica a todo el repositorio. Si creas un fichero nuevo en `docs/`, añádelo a
esta tabla — un fichero que no está en el índice no lo lee nadie.

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
   - **La firma no basta para distinguir un token de otro.** Todos se firman con la
     misma `SECRET_KEY`, así que validar solo la firma hacía que el `state` de OAuth
     valiera como sesión completa del dashboard durante sus 10 minutos — y ese state
     viaja como query param en el redirect de vuelta de Microsoft, o sea que queda en
     la barra de direcciones, en el historial y en los logs de Microsoft. Los JWT de
     usuario se validan con `_jwt_de_usuario()`, que **rechaza todo token con claim
     `purpose`**. Si añades un JWT firmado para cualquier otra cosa, dale su `purpose`:
     es lo que impide que sirva como credencial de usuario.
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
     (`LOGIN_MAX_ATTEMPTS` / `LOGIN_WINDOW_SECONDS`), con bloqueo progresivo: cada
     tanda completa de fallos dobla la espera (300s, 600s, 1.200s…) hasta
     `LOGIN_BLOQUEO_MAX_SECONDS`, contada **desde el último fallo**, no desde el
     primero. Devuelve `429` con `Retry-After`. El doblado estuvo documentado aquí
     sin existir en el código hasta agosto de 2026: la ventana era plana, así que
     esperar cinco minutos devolvía otros cinco intentos indefinidamente. Un login
     correcto borra la tabla, de modo que el castigo acumulado no sobrevive a acertar.
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
`20260729_rls_jobs`, `20260730_login_attempts`, `20260802_app_logs`,
`20260804_presence`, `20260804_brief_envios`, `20260807_jarvis_memoria`,
`20260808_jarvis_mcp_servidores`, `20260808_ha_entidades`,
`20260808_jarvis_recordatorios`, `20260813_brief_ajustes`,
`20260816_brief_instantanea`, `20260816_informe_envios`,
`20260816_health_fuente`, `20260817_vigilante_estado`,
`20260818_avisos_gobierno`, `20260819_vigilancias`,
`20260820_reglas_usuario`, `20260820_revision_hallazgos`.

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
