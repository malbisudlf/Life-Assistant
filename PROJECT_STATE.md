# Life Assistant — Estado del Proyecto

> **INSTRUCCIÓN PARA CLAUDE:** Lee este archivo al inicio de cada sesión en lugar de buscar conversaciones anteriores. Actualízalo al final de cada sesión.

---

## Stack

| Capa | Tecnología | URL / Ruta |
|------|-----------|------------|
| Frontend | React + Vite | https://life-assistant-smoky.vercel.app |
| Backend | FastAPI (Python) | https://backend-tender-glow-160.fly.dev |
| Base de datos | Supabase (PostgreSQL) | variable `SUPABASE_URL` en Fly.io secrets |
| Calendario | Microsoft Graph API (Outlook) | OAuth2 con refresh token en `.token` |
| Auth dashboard | JWT con contraseña única | `DASHBOARD_PASSWORD` en Fly.io secrets |
| Home Assistant | http://192.168.1.200:8123 | Token largo hardcodeado en Dashboard.jsx (~línea 175) |
| Repo | GitHub privado | https://github.com/malbisudlf/Life-Assistant |
| GitHub token | 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 | Para clonar el repo |

---

## Estructura del proyecto

```
Life-Assistant/
├── backend/
│   ├── main.py           ← API principal (FastAPI)
│   └── .env              ← Solo tiene CLIENT_ID, TENANT_ID, CLIENT_SECRET, REDIRECT_URI (Microsoft)
│                            SUPABASE_URL y SUPABASE_KEY están en Fly.io secrets, no en .env local
├── agent/
│   ├── agent.py          ← Agente PC (Playwright + pyautogui)
│   ├── requirements.txt
│   ├── .env.example
│   └── README.md
├── src/components/
│   └── Dashboard.jsx     ← Componente principal (todo el UI)
├── supabase/migrations/
│   ├── 20260508_jobs_queue.sql   ← Tablas: jobs, pc_agents
│   └── 20260511_job_results.sql  ← Tabla: job_results (PENDIENTE ejecutar en Supabase)
└── PROJECT_STATE.md
```

---

## Funcionalidades implementadas ✅

- **Auth JWT** — Login por contraseña + token 30 días
- **Timeline de eventos** — Eventos del día de Outlook ordenados por hora
- **Calendario de clases** — Calendario separado "Clases" en Outlook, nodo azul en timeline
- **Panel lateral de clases** — Click en nodo abre panel derecho con horario
- **Próximos eventos** — Vista 7 días, máx 5 eventos
- **Entregas** — Filtra eventos con 📚 en el título, ordenadas por urgencia
- **¿A qué hora salir?** — Google Maps API, origen GPS móvil o fallback Astigarraga 35 Durango
- **Módulo de ideas** — Whisper STT + GPT-4o mini + Supabase
- **Wake on LAN** — Click en entrega → modal → Home Assistant (`button.pc_mikel`) → WOL
- **Heartbeat agente** — Dashboard consulta `/agents/pc-mikel` cada 10s, muestra estado
- **Guard WOL real** — Botón "Encender" deshabilitado si agente ya online, bloqueado si offline
- **Responsive móvil**

---

## Agente PC ✅ (código listo, pendiente configurar en el PC)

**Flujo completo:**
1. Arranca con Windows (Task Scheduler) al iniciar sesión
2. Heartbeat → "online"
3. Espera job pendiente en Supabase (máx 5 min, polling cada 5s)
4. Claim atómico del job
5. Playwright abre Alud (Chrome), gestiona login:
   - Click en "@deusto | @opendeusto"
   - Selecciona cuenta `mikel.albisudela@opendeusto.es`
   - Si pide Okta push → espera hasta 120s a que el usuario apruebe desde el móvil
6. Navega a la URL de la entrega, extrae el enunciado
7. Deja el navegador ABIERTO en la página de la entrega
8. Abre Claude Desktop (`C:\Users\malbi\.local\bin\claude.exe`)
9. Ctrl+2 → Cowork
10. Pega instrucción completa (título + enunciado + URL) via portapapeles PowerShell
11. Enter → Cowork ejecuta (rellena respuesta, NO envía)
12. Heartbeat → "offline", se para

**Pasos pendientes para activar el agente:**
1. ✅ `pip install -r requirements.txt && playwright install chromium` — HECHO
2. ⬜ Crear `agent/.env` con credenciales (ver abajo)
3. ⬜ Ejecutar migración `20260511_job_results.sql` en Supabase SQL Editor
4. ⬜ Configurar Task Scheduler en Windows
5. ⬜ Cuando se creen eventos de entrega en Outlook, añadir en la descripción: `alud_url: https://alud.deusto.es/mod/assign/view.php?id=XXXXX`

**Cómo obtener SUPABASE_URL y SUPABASE_KEY:**
Están en Fly.io secrets (no en backend/.env local).
```powershell
# En PowerShell, con flyctl instalado y autenticado:
flyctl ssh console --app backend-tender-glow-160
# Dentro de la consola:
printenv | grep SUPABASE
```
El usuario estaba en proceso de hacer esto cuando se cerró la sesión.
Fly.io puede estar en cold start — si da error, abrir primero:
https://backend-tender-glow-160.fly.dev/

**Contenido del agent/.env una vez obtenidas las keys:**
```
LA_TOKEN=<copiar de DevTools → Application → Local Storage → la_token>
LA_API_BASE=https://backend-tender-glow-160.fly.dev
SUPABASE_URL=<obtener de Fly.io>
SUPABASE_KEY=<obtener de Fly.io>
```

---

## Pendiente 📋

Por orden de prioridad:

1. **Terminar configuración agente** — obtener SUPABASE_URL/KEY de Fly.io y crear agent/.env
2. **Dashboard: leer alud_url del evento** — el dashboard debe leer el campo descripción del evento de Outlook, extraer `alud_url:` y meterlo en el payload del job al hacer click en la entrega
3. **BMW Connected Drive** — click en evento con ubicación → enviar navegación al BMW X3 20d
4. **Home Assistant / Alexa** — sensor presencia en cuarto + evento en 30 min → aviso Alexa
5. **Raspberry Pi** — pantalla siempre encendida mostrando el dashboard

---

## Notas técnicas importantes

- **Refresh token Outlook** — en `backend/.token` (JSON). Fly.io lo persiste en volumen. Si se pierde, re-autenticar via `/auth/login`.
- **HA_TOKEN** — hardcodeado en `Dashboard.jsx` (~línea 175). Pendiente mover a variable de entorno Vercel.
- **Entregas** — detectadas por emoji 📚 en el título del evento de Outlook.
- **Clases** — calendario Outlook separado llamado "Clases". Endpoint `/calendar/classes`.
- **Fly.io cold start** — ~5s. Secrets: `DASHBOARD_PASSWORD`, `SECRET_KEY`, `CLIENT_ID`, `TENANT_ID`, `CLIENT_SECRET`, `GOOGLE_MAPS_API_KEY`, `SUPABASE_URL`, `SUPABASE_KEY`, `OPENAI_API_KEY`.
- **job_results** — tabla Supabase para guardar soluciones del agente. Migración pendiente de ejecutar.

---

## Última actualización

**11/05/2026** — Agente PC reescrito (pyautogui + Cowork, sin Claude API). Guard WOL real implementado y mergeado. Pendiente: obtener credenciales Supabase de Fly.io para configurar agent/.env.
