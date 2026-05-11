# Life Assistant — Agente PC

Script Python que arranca automáticamente cuando el PC se enciende vía Wake-on-LAN
desde el dashboard. No usa la API de Anthropic — controla el PC con pyautogui.

## Qué hace

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
LA_TOKEN=
LA_API_BASE=https://backend-tender-glow-160.fly.dev
SUPABASE_URL=
SUPABASE_KEY=
```

- `LA_TOKEN`: abre el dashboard en el navegador → F12 → Application → Local Storage → `la_token`
- `SUPABASE_URL` y `SUPABASE_KEY`: están en `backend/.env`

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
