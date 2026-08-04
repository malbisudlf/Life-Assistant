# Life Assistant — Agente PC

Script Python que arranca automáticamente cuando el PC se enciende vía Wake-on-LAN
desde el dashboard. No usa la API de Anthropic — controla el PC con pyautogui.

## Qué hace

Es efímero y despacha por `payload["accion"]`: drena la cola de jobs y se cierra.

### `abrir_streaming` (Sunshine/Apollo para Moonlight)

1. Arranca el **servicio de Tailscale** (que está en manual: en el día a día el PC
   no tiene la VPN encendida) y levanta el túnel, reportando la IP de la tailnet al
   dashboard — el PC arranca por WOL sin VPN, y desde fuera de casa es la única forma
   de que Moonlight lo alcance. Si falla, avisa y sigue: en la LAN funciona igual
2. Lanza Sunshine (o Apollo) en modo DETACHED, para que sobreviva al agente

Arrancar el servicio necesita privilegios: la tarea del Programador debe estar
marcada como "Ejecutar con los privilegios más altos".

Puesta a punto completa (Tailscale desatendido, autoarranque de Sunshine, WOL):
`PUESTA_A_PUNTO.md`.

### `resolver_alud`

1. Arranca con Windows (Task Scheduler), heartbeat → "online"
2. Recoge el primer job pendiente de Supabase
3. Abre Alud con Playwright, gestiona login + Okta push si es necesario
4. Navega a la URL de la entrega y extrae el enunciado
5. Deja el navegador abierto en la página de la entrega
6. Abre Claude Desktop → Ctrl+2 (Cowork)
7. Escribe la instrucción completa con el enunciado
8. Cowork resuelve y rellena el campo — sin pulsar submit
9. Heartbeat → "offline", se para

**El agente nunca pulsa enviar.** El usuario revisa y entrega manualmente.

---

## Instalación (una sola vez)

### 1. Dependencias

```bash
cd agent/
pip install -r requirements.txt
playwright install chromium
```

### 2. Variables de entorno

Crea un archivo `.env` en la carpeta `agent/` con este contenido:

```
AGENT_TOKEN=
LA_API_BASE=https://backend-tender-glow-160.fly.dev
```

- `AGENT_TOKEN`: token de servicio, el **mismo valor** que la variable `AGENT_TOKEN` del
  backend (genéralo con `python -c "import secrets; print(secrets.token_urlsafe(32))"`).
  No caduca, que es justo el motivo de que exista: antes aquí iba `LA_TOKEN`, el JWT del
  dashboard, y a los 30 días expiraba — el backend empezaba a responder 401 y el agente
  se cerraba en cada arranque diciendo "No hay jobs pendientes". Se sigue aceptando
  `LA_TOKEN` como respaldo, pero el agente avisa por el log de que va a caducar.
- Ya **no** hacen falta `SUPABASE_URL`/`SUPABASE_KEY`: los jobs pendientes se piden al
  backend (`GET /jobs/pending`)
- Opcionales de streaming: `SUNSHINE_EXE`, `VPN_TIPO`, `TAILSCALE_EXE`, `VPN_TIMEOUT`
  (ver `.env.example`)

### 3. Migración Supabase (solo si no se ha ejecutado ya)

En el SQL Editor de Supabase, ejecutar el contenido de:
`supabase/migrations/20260511_job_results.sql`

### 4. Task Scheduler — arranque automático con Windows

1. Abre el **Programador de tareas** de Windows
2. Crear tarea básica:
   - **Nombre:** Life Assistant Agent
   - **Desencadenador:** Al iniciar sesión (tu usuario)
   - **Acción:** Iniciar un programa
     - Programa: ruta a `python.exe` (encuéntrala con `where python` en la terminal)
     - Argumentos: ruta completa a `agent.py`
     - Iniciar en: ruta completa a la carpeta `agent/`
3. En **Condiciones**: desmarcar "Solo si conectado a corriente"
4. En **Configuración**: marcar "Si ya se ejecuta, no iniciar otra instancia"

---

## Añadir la URL de Alud al evento del calendario

El agente necesita saber a qué actividad ir. Cuando crees el evento de entrega
en Outlook, añade en la **descripción** del evento:

```
alud_url: https://alud.deusto.es/mod/assign/view.php?id=XXXXX
```

El dashboard leerá ese campo y lo incluirá automáticamente en el payload del job.

---

## Logs

El agente escribe en `agent/agent.log`. Si algo falla, mira ahí primero.
