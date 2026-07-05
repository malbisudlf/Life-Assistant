# Tests de Life Assistant

## Backend (FastAPI + pytest)

Los tests no tocan servicios reales: Supabase, Microsoft Graph, Google Maps y
OpenAI se simulan con un router de mocks (`tests/backend/conftest.py`), y las
variables de entorno obligatorias (`SECRET_KEY`, `DASHBOARD_PASSWORD`, …) se
definen ahí antes de importar `backend/main.py`.

| Fichero | Cubre |
|---|---|
| `test_main.py` | `/auth/password` (JWT + rate limiting), protección Bearer, helpers puros (`normalize_graph_dt`, `_token_ok`, …), `/maps/departure`, ideas (`/ideas/text`, borrado, extracción con GPT simulado) |
| `test_calendar.py` | `/calendar/events` (normalización de zonas horarias, extracción de `alud_url`), `/calendar/classes`, crear/editar eventos |
| `test_ha.py` | `/ha/events/soon` (ventana de 15 min, tokens de servicio), flujo Wake-on-LAN |
| `test_jobs.py` | Cola de jobs: create/claim/start/finish/retry, eventos de job, heartbeat y estado de agentes |
| `test_health.py` | Ingesta de salud (`/health/ingest` y `/simple`): métricas acumulativas, kJ→kcal, sueño, workouts; métricas agregadas y entrenamiento |

```bash
# Instalar dependencias (una vez)
python3 -m venv .venv
.venv/bin/pip install -r backend/requirements.txt pytest

# Ejecutar
.venv/bin/python -m pytest tests/backend
```

## Frontend (Vitest + Testing Library)

| Fichero | Cubre |
|---|---|
| `helpers.test.js` | Helpers puros de `src/lib/helpers.js`: fechas (`daysUntil`, `formatUpcomingTime`, …), `sleepScore`, `calcRecoveryMod`, `hoursToHM`, `findMetric` |
| `login.test.jsx` | `Dashboard` sin sesión: render de la pantalla de login, login correcto/incorrecto y error de red (con `fetch` simulado) |

`setup.js` añade los stubs de `matchMedia` y `Notification` que jsdom no implementa.

```bash
npm install   # una vez
npm test      # vitest run
```

## El agente de PC (`agent/agent.py`)

No tiene tests automatizados: es automatización de escritorio Windows
(pyautogui, Edge, Claude Desktop) que requiere una máquina real para ejecutarse.
