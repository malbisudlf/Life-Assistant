# REVISION_PROYECTO

Review de la carpeta completa del proyecto (sin contar `main.py`, ya revisado por separado).

---

## `agent/agent.py`

### `api_headers()` expone el token en cada request (media)

```python
def api_headers():
    return {"Authorization": f"Bearer {API_TOKEN}", "Content-Type": "application/json"}
```

El token viaja en cabecera `Authorization` en cada llamada. Eso significa que aparece:
- En los logs de acceso del backend (si los hay)
- En los logs de red del agente (`agent.log`)
- En `agent/.env`

El backend soporta `X-Auth-Token` como cabecera prioritaria (ver `main.py:750-762`),
pero el agente usa `Authorization: Bearer`. No es un bug — el agente acepta ambos —
pero es inconsistente con la política del backend.

**Arreglo:** Cambiar a `X-Auth-Token` en `api_headers()`.

### `AGENT_ID` hardcodeado (baja)

```python
AGENT_ID = "pc-mikel"
```

Debería leerse de `.env` (ya existe `PC_AGENT_ID` en el backend y `VITE_AGENT_ID`
en el frontend). Si alguien clona el proyecto y lo usa, le tocaría editar el código.

**Arreglo:** `AGENT_ID = os.getenv("AGENT_ID", "pc-mikel")`

### `EDGE_DEBUG_PORT` aleatorio pero no validado (baja)

```python
EDGE_DEBUG_PORT = random.randint(49200, 49900)
```

`random.randint` usa el generador por defecto de Python, que es Mersenne Twister
(no criptográfico). Para un puerto de depuración no importa, pero si alguien
reemplaza `EDGE_DEBUG_PORT` por otro uso, debería usar `secrets` en vez de `random`.

No es un riesgo actual.

### `subprocess.run` con `check=True` en `_focus_claude_window` (baja)

```python
result = subprocess.run(
    ["powershell", "-Command", """..."""],
    capture_output=True, text=True,
)
```

No usa `check=True`, así que si PowerShell falla, el agente lo ignora y sigue.
Esto es intencionado (la función devuelve `False` si no encuentra Claude), pero
el log no distingue entre "Claude no está abierto" y "PowerShell reventó".

**Sugerencia:** Loggear `result.returncode` cuando no es "OK".

---

## `agent/.env`

### `AGENT_TOKEN` en el fichero (correcto)

`agent/.env` está en `.gitignore`, que es justo donde tiene que vivir el token de
servicio del agente. Nada que arreglar ahí.

> **Aquí sí hubo una fuga, y era esta misma sección.** La revisión original pegó el
> valor real del token dentro de este fichero —que **sí** se versiona— para ilustrar
> que en `agent/.env` estaba bien guardado. El token quedó publicado en un repo
> público durante once días (issue #95, 2026-08-23 → arreglado el 2026-09-03) y hubo
> que rotarlo. La moraleja no es sobre `.gitignore`: **al documentar un secreto no se
> copia su valor jamás, ni siquiera para decir que está a salvo.** Se nombra la
> variable y se acabó.

---

## `agent/requirements.txt`

### Versiones no fijas (baja)

```
playwright>=1.44.0
python-dotenv>=1.0.0
requests>=2.31.0
pyautogui>=0.9.54
```

A diferencia del backend (versiones fijas), aquí se usan versiones mínimas.
Esto puede causar comportamientos distintos entre máquinas. Para un script que
corre en un PC específico no es crítico, pero si algún día se automatiza el
despliegue, conviene fijar versiones.

**Arreglo:** Fijar versiones con `==`.

---

## `tests/`

### `conftest.py`: contraseña `1234` en tests (informativo)

```python
os.environ.setdefault("DASHBOARD_PASSWORD", "1234")
```

La misma contraseña débil que en `.env` de desarrollo. No es un riesgo (es un
valor de test), pero es consistente con la nota en `REVISION_BACKEND.md`.

### `servidor_pruebas.py`: duplicación de lógica de mocking (baja)

`tests/backend/conftest.py` y `tests/e2e/servidor_pruebas.py` tienen dos
implementaciones similares de `MockRouter` / `_RouterSimulado`. Ambas enrutan
requests simulados pero con detalles distintos (una usa `FakeResponse`, la otra
`_Respuesta`).

**Sugerencia:** Extraer un módulo compartido `tests/mock_http.py` con las clases
base y importarlo desde ambos sitios.

### `helpers.test.js`: 1474 líneas (baja)

El fichero de tests del frontend es enorme. Cubre todo `helpers.js` pero es
difícil de navegar. No es un bug, pero merece fraccionarse en ficheros por
dominio (health, date, jarvis, etc.).

### Tests del agente: ninguno (documentado)

Correcto: `agent/agent.py` requiere Windows real. Está documentado en
`tests/README.md`.

---

## `supabase/migrations/`

### 23 migraciones sin tooling (documentado)

Todas se aplican a mano desde el editor SQL de Supabase. Está documentado en
`CLAUDE.md` y no es un bug, pero merece nota:

- Sin versionado automático: si se pierde el historial de migraciones aplicadas,
  no hay forma de saber qué falta.
- Sin rollback: si una migración rompe algo, no hay `undo` automático.
- Sin diff: no hay forma de ver qué cambió entre dos versiones del esquema.

**Sugerencia:** Mantener un fichero `supabase/APLICADAS.md` con la lista de
migraciones ya aplicadas y la fecha.

---

## `.github/workflows/`

### `ci.yml`: sin `--max-warnings` en lint del backend (baja)

El job de frontend usa `npm run lint -- --max-warnings 0`, pero el job de
backend no tiene un paso de lint. `backend/requirements.txt` no incluye `ruff`
ni `flake8`.

**Arreglo:** Añadir `ruff` a `requirements.txt` y un paso de lint en CI.

### `deploy-backend.yml`: deploy manual correcto (OK)

`workflow_dispatch` — no se despliega automáticamente. Correcto.

### `revision-nocturna.yml`: bien documentado (OK)

Comentarios extensos explicando el cron, los retrasos de Actions, la etiqueta
de seguimiento. Todo bien pensado.

### `resumen-diario.yml`: red de seguridad (OK)

Cron a las 09:00 UTC (11:00 CEST / 10:00 CET), después de la hora tope.
Idempotente: si el correo ya salió, no lo manda de nuevo.

---

## `src/`

### `App.jsx`: 7 líneas (OK)

Un wrapper mínimo que importa `Dashboard`. Correcto para un proyecto de una
sola persona.

### `main.jsx`: PWA registration (informativo)

```javascript
if ('serviceWorker' in navigator && import.meta.env.PROD) {
  window.addEventListener('load', () => {
    navigator.serviceWorker.register('/sw.js').catch(() => {})
  })
}
```

Registra el service worker solo en producción. El `.catch(() => {})` silencia
errores de registro — si `/sw.js` no existe o falla, el usuario no se entera.

**Sugerencia:** Al menos loguear el error en consola (no en logger, es frontend):
`.catch(e => console.warn('SW registration failed:', e))`.

### `vite.config.js`: test config (OK)

Configura jsdom, setup files y directorio de tests. Correcto.

---

## `eslint.config.js`

### Config limpia (OK)

Flat config con plugins de React hooks y Refresh. Incluye globals de browser
y node para Playwright. Correcto.

---

## `.gitignore`

### Bien estructurado (OK)

Cubre `.env`, `venv/`, `.local`, datos personales, editor, notas internas,
skills de terceros. El `.gitignore` es sólido.

### `import_training.py` ignorado (OK)

Fichero con datos personales ignorado correctamente.

---

## `package.json`

### Sin `pydantic` explícito (informativo)

El backend lo usa vía FastAPI (transitivo), pero como ya se mencionó en
`REVISION_BACKEND.md`, si en el futuro se usa `pydantic` directamente fuera
de FastAPI, habría que añadirlo.

### Versiones fijas en devDependencies (OK)

Todo fijado con `^` para compatibilidad. Correcto.

---

## `playwright.config.js`

### Bien configurado (OK)

`retries: 0` — no oculta races. `trace: retain-on-failure` — solo artefactos
al fallar. `webServer` arranca y espera al backend y al preview. Todo bien
pensado.

### Puerto del API configurable (OK)

```javascript
const PUERTO_API = Number(process.env.E2E_PUERTO_API) || 8000
```

Permite override por variable de entorno. Correcto.

---

## Resumen de hallazgos

| Archivo | Severidad | Cuánto arreglar |
|---|---|---|
| `agent/agent.py` `api_headers()` | Media | 1 línea |
| `agent/agent.py` `AGENT_ID` hardcode | Baja | 1 línea |
| `agent/requirements.txt` versiones | Baja | 4 líneas |
| `tests/e2e/servidor_pruebas.py` duplicación | Baja | Extraer módulo |
| `tests/frontend/helpers.test.js` tamaño | Baja | Fraccionar |
| `main.jsx` SW error silencioso | Baja | 1 línea |
| `ci.yml` sin lint backend | Baja | 3 líneas |
| `supabase/migrations/` sin versionado | Info | 1 fichero nuevo |

Total: ~10 líneas de cambio + 1 fichero nuevo.
