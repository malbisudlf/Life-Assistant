# Life Assistant — Agente PC

Script Python que se ejecuta en el PC de casa cuando el dashboard envía una entrega vía Wake-on-LAN.

## Qué hace

1. Arranca con Windows (Task Scheduler)
2. Hace heartbeat al backend → dashboard ve "online"
3. Recoge el primer job pendiente de Supabase
4. Abre Alud con Playwright (gestiona login + Okta push si es necesario)
5. Extrae el enunciado de la actividad
6. Llama a Claude API y genera una solución
7. Guarda título + enunciado + solución en Supabase
8. Se para

**El agente nunca toca el formulario de entrega.** El usuario revisa la solución y envía manualmente.

---

## Instalación (una sola vez)

### 1. Python y dependencias

```bash
cd agent/
pip install -r requirements.txt
playwright install chromium
```

### 2. Variables de entorno

```bash
cp .env.example .env
```

Edita `.env` y rellena:

- `LA_TOKEN` — el JWT del dashboard. Cópialo desde las DevTools del navegador:
  `F12 → Application → Local Storage → https://life-assistant-smoky.vercel.app → la_token`
- `SUPABASE_URL` y `SUPABASE_KEY` — los mismos que en `backend/.env`
- `ANTHROPIC_API_KEY` — tu clave de Anthropic

### 3. Migración de Supabase

Ejecuta en el SQL Editor de Supabase:

```sql
-- contenido de supabase/migrations/20260511_job_results.sql
```

### 4. Task Scheduler (arranque automático con Windows)

Abre el Programador de tareas de Windows y crea una tarea nueva:

- **Nombre:** Life Assistant Agent
- **Desencadenador:** Al iniciar sesión (tu usuario)
- **Acción:** Iniciar un programa
  - Programa: `C:\ruta\a\python.exe`
  - Argumentos: `C:\ruta\a\Life-Assistant\agent\agent.py`
  - Iniciar en: `C:\ruta\a\Life-Assistant\agent\`
- **Condiciones:** desmarcar "Solo si el equipo está conectado a la red eléctrica"
- **Configuración:** marcar "Si la tarea ya se está ejecutando, no iniciar una nueva instancia"

> Para encontrar la ruta de Python: abre una terminal y ejecuta `where python`

---

## Añadir la URL de Alud al evento del calendario

Para que el agente sepa a qué actividad ir, el evento de Outlook debe tener la URL de Alud en el campo **Descripción** o **Ubicación**, con este formato:

```
alud_url: https://alud.deusto.es/mod/assign/view.php?id=XXXXX
```

El dashboard leerá ese campo y lo incluirá en el payload del job al hacer click en la entrega.

---

## Logs

El agente escribe en `agent/agent.log`. Si algo falla, mira ahí primero.
