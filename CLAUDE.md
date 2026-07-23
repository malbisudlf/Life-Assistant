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

**Verificación obligatoria antes de cada commit** (no hay CI de tests; el único
check de GitHub es el deploy de Vercel, que solo valida que el frontend compila):

```bash
npm run lint && npm test && .venv/bin/python -m pytest tests/backend -q && npm run build
```

## Arquitectura

```
Browser (React 19 + Vite, Vercel)
    │  JWT en localStorage("la_token") + fetch REST
    ▼
backend/main.py (FastAPI, Fly.io, UN SOLO FICHERO ~1500 líneas)
    ├── Microsoft Graph API ── calendario Outlook (tokens OAuth persistidos en Supabase)
    ├── Google Maps Distance Matrix ── hora de salida con tráfico
    ├── OpenAI ── Whisper (transcripción) + GPT-4o-mini (extracción de ideas)
    ├── Supabase REST ── ideas, jobs, pc_agents, training_*, health_metrics, oauth_tokens
    └── Home Assistant ── HA sondea al backend (flag WOL cada 30s, eventos cada 60s)

Apple Watch → Health Auto Export / iOS Shortcuts → POST /health/ingest[/simple]
agent/agent.py → agente Windows (Playwright + pyautogui); consume la cola de jobs
```

Ficheros clave:

| Fichero | Qué es |
|---|---|
| `src/components/Dashboard.jsx` | TODA la UI (~3.600 líneas, un componente principal + subcomponentes en el mismo fichero) |
| `src/lib/helpers.js` | Helpers puros del frontend (fechas, sleepScore, recovery). **La lógica pura nueva va aquí, no en Dashboard.jsx** |
| `backend/main.py` | Toda la API. Secciones marcadas con banners `# ── NOMBRE ──` |
| `agent/agent.py` | Agente PC. Solo funciona en Windows real (Edge, pyautogui, Claude Desktop). **No tiene tests ni puede tenerlos en CI** |
| `supabase/migrations/*.sql` | Esquema de BD. Se aplican a mano en Supabase, no hay tooling de migraciones |
| `tests/backend/conftest.py` | Entorno simulado completo del backend (léelo antes de escribir tests) |
| `tests/frontend/setup.js` | Stubs de `matchMedia` y `Notification` que jsdom no implementa |

## Backend: modelo de seguridad (invariantes — no las relajes nunca)

1. **Sin secretos por defecto.** `main.py` lanza `RuntimeError` al arrancar si faltan
   `SECRET_KEY` o `DASHBOARD_PASSWORD`. Nunca añadas un fallback tipo `"dev-secret"`:
   el repo es público y permitiría forjar JWTs.
2. **Dos niveles de auth:**
   - *Usuario*: `POST /auth/password` (contraseña → JWT HS256, 30 días). Los endpoints
     de usuario llevan `Depends(verify_token)`.
   - *Servicio* (máquinas: HA, Health Auto Export, iOS Shortcuts): tokens dedicados
     `HA_POLL_TOKEN` / `HEALTH_INGEST_TOKEN` comparados con `_token_ok()`
     (tiempo constante, y **falso si el token esperado no está configurado**).
     Orden de extracción: header `X-Auth-Token` → `Authorization: Bearer` → query string
     (la query solo existe por compatibilidad con integraciones ya desplegadas).
3. **Rate limiting del login**: 5 intentos / 5 min por IP, en memoria (`_login_attempts`).
   Se resetea en cold start de Fly, y eso es aceptable para este caso.
4. **Comparaciones de credenciales siempre con `hmac.compare_digest`**, nunca `==`.
5. **Errores de Supabase**: usa `_supabase_error(r)` — loguea el detalle real en el
   servidor y devuelve un 502 genérico. Nunca reenvíes `r.text` de Supabase al cliente.
6. **Validación de parámetros**: los path params de recursos usan patrones regex
   (UUID para jobs/ideas/sesiones, `[a-zA-Z0-9_-]{1,64}` para worker/agent ids,
   `\d{4}-\d{2}-\d{2}` para fechas). Mantén esto en endpoints nuevos: los valores
   se interpolan en URLs de Supabase.

## Backend: patrones que hay que conocer

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
- **Cola de jobs** (máquina de estados estricta, transiciones vía PATCH condicional de
  Supabase para que sean atómicas):
  `pending → claimed → running → done | failed`, y `failed → pending` con `retry`
  (incrementa `attempt`, máx. `MAX_JOB_ATTEMPTS=3`). El claim usa
  `?status=eq.pending` como guard: si devuelve 0 filas, otro worker ganó la carrera.
  `dedupe_key` es único: el upsert con `resolution=merge-duplicates` devuelve 0 filas
  en conflicto y entonces se recupera el job existente.
- **Ingesta de salud**: las métricas acumulativas (`step_count`, `active_energy`,
  `basal_energy`, `resting_energy`) solo se sobreescriben si el valor nuevo es MAYOR
  (llegan snapshots parciales a lo largo del día). Energía en kJ se convierte a kcal
  (÷ 4.184). `sleep_analysis` guarda `sleep_start` ("HH:MM") en `extra` y respeta el
  flag `excluded` (noches anuladas por el usuario). El patrón de escritura es
  POST → si 409, PATCH.
- **WOL**: `_wol_pending` es un flag global en memoria. `/wake-pc` lo marca, HA lo
  recoge en `/ha/wol-pending` (que lo limpia al leerlo). No lo conviertas en estado
  persistente sin pensar en el poll de HA.

## Frontend: cómo está organizado Dashboard.jsx

Un solo fichero, navegable por sus banners (`grep "── " src/components/Dashboard.jsx`):
LOGIN SCREEN → HELPERS → ESTILOS GLOBALES (`GLOBAL_CSS`, variables CSS `--bg`,
`--accent`...) → `DateInput`/`TimeInput` → COMPONENTE PRINCIPAL (estados, efectos,
`renderWidget`, skeleton, modo simplificado móvil, modales, panel de clases).

- **Widgets**: definidos en `ALL_DEFAULT_WIDGETS` (ids: `timeline`, `upcoming`,
  `entregas`, `training`, `ideas`, `health_wellness`, `health_sleep`, `health_heart`,
  `health_hrv`, `health_activity`, `health_workouts`). Cada uno se renderiza en
  `renderWidget(id)`. La configuración (visibilidad, columna, orden, tamaño, splits)
  se persiste en `localStorage`.
- **Claves de localStorage** (prefijo `la_`): `la_token` (JWT), `la_widget_config`,
  `la_num_columns`, `la_col_splits`, `la_notifications`, `la_simple_mode`,
  `la_body_goals`, `la_training_days`. Si añades una, mantén el prefijo y el
  `try/catch` al parsear.
- **`apiFetch()`**: wrapper de `fetch` que, ante un 401 con sesión activa, borra
  `la_token` y recarga. Úsalo para toda llamada autenticada al backend.
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
- Los `catch { /* mejor esfuerzo: ignorar */ }` son deliberados (notificaciones,
  parseo de localStorage, llamadas fire-and-forget). Si añades uno, pon el comentario
  dentro o la regla `no-empty` fallará.
- El lint debe quedar a **cero errores y cero warnings**. Se limpió por completo en
  julio de 2026; no dejes que se vuelva a degradar.

## Tests: cómo funcionan y sus trampas

### Backend (`tests/backend`, 104 tests)

`conftest.py` define las variables de entorno **antes** de importar `main` (si no,
el import revienta por los secretos obligatorios) y monkeypatchea `requests` con un
`MockRouter`: registras respuestas por `(método, fragmento de URL)` y las rutas se
resuelven **en orden de registro** — registra primero la más específica
(`/calendars/cal-x/calendarView` antes que `/me/calendars`, porque la primera URL
contiene a la segunda). Fixtures: `client`, `auth_headers` (JWT válido),
`mock_requests`, `graph_token` (simula sesión de Graph). El rate limiter y el flag
WOL se resetean entre tests automáticamente.

Valores del entorno de test: contraseña `1234`, `SECRET_KEY=test-secret-key`,
`HA_POLL_TOKEN=ha-poll-token`, `HEALTH_INGEST_TOKEN=health-token`.

### Frontend (`tests/frontend`, 21 tests)

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
- No hagas deploy del backend salvo que se pida: `fly deploy` es manual y afecta a
  producción real.
