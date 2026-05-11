# Life Assistant — Estado del Proyecto

> **INSTRUCCIÓN PARA CLAUDE:** Lee este archivo al inicio de cada sesión en lugar de buscar conversaciones anteriores. Actualízalo al final de cada sesión.
> **GitHub token:** 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 — clonar con: `git clone https://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@github.com/malbisudlf/Life-Assistant`

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

---

## Estructura del proyecto

```
Life-Assistant/
├── backend/
│   ├── main.py           ← API principal (FastAPI)
│   └── .env              ← Solo tiene CLIENT_ID, TENANT_ID, CLIENT_SECRET, REDIRECT_URI (Microsoft)
│                            SUPABASE_URL y SUPABASE_KEY están en Fly.io secrets, no en .env local
├── agent/
│   ├── agent.py          ← Agente PC (Playwright + pyautogui + Cowork)
│   ├── requirements.txt
│   ├── .env              ← YA CONFIGURADO con LA_TOKEN, LA_API_BASE, SUPABASE_URL, SUPABASE_KEY
│   └── README.md
├── src/components/
│   └── Dashboard.jsx     ← Componente principal (todo el UI)
├── supabase/migrations/
│   ├── 20260508_jobs_queue.sql   ← Tablas: jobs, pc_agents (YA EJECUTADA)
│   └── 20260511_job_results.sql  ← Tabla: job_results (YA EJECUTADA)
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
- **Heartbeat agente** — Dashboard consulta `/agents/pc-mikel` cada 10s
- **Guard WOL real** — Botón "Encender" deshabilitado si agente ya online
- **Responsive móvil**
- **alud_url en eventos** — Backend extrae `alud_url:` de bodyPreview/body del evento Outlook
- **Job creation al hacer WOL** — Al pulsar "Encender", crea job en Supabase con `{ titulo, alud_url }`
- **Migraciones Supabase** — Tablas `jobs`, `pc_agents`, `job_results` creadas y operativas
- **Task Scheduler** — Agente arranca automáticamente al iniciar sesión en Windows

---

## Agente PC ✅ (configurado y funcionando)

**Flujo completo:**
1. Arranca con Windows (Task Scheduler) al iniciar sesión
2. Heartbeat → "online"
3. Espera job pendiente en Supabase (máx 5 min, polling cada 5s)
4. Claim atómico del job
5. Playwright abre Alud (Chrome), gestiona login:
   - Click en "@deusto | @opendeusto"
   - Selecciona cuenta `mikel.albisudela@opendeusto.es`
   - Si pide Okta push → espera hasta 120s a que el usuario apruebe desde el móvil
6. Navega a la URL de la entrega (`alud_url` del payload), extrae el enunciado
7. Deja el navegador ABIERTO en la página de la entrega
8. Abre Claude Desktop (`C:\Users\malbi\.local\bin\claude.exe`)
9. Ctrl+2 → Cowork
10. Pega instrucción completa (título + enunciado + URL) via portapapeles PowerShell
11. Enter → Cowork ejecuta (rellena respuesta, NO envía)
12. Heartbeat → "offline", se para

**Estado:** ✅ Listo para prueba end-to-end. Pendiente verificar que el job llega al agente y ejecuta el flujo completo.

---

## Pendiente 📋

Por orden de prioridad:

1. **Prueba end-to-end del flujo WOL→job→agente** — Pulsar "Encender" en el modal de la entrega "ACTIVITY 6: PRESCRIPTIVE DSS CHALLENGE" y verificar que el agente recibe el job, abre Alud y arranca Cowork
2. **Indicador visual agente en dashboard** — El texto "Agente: online/offline" no aparece en el modal (bug pendiente, baja prioridad)
3. **BMW Connected Drive** — Click en evento con ubicación → enviar navegación al BMW X3 20d
4. **Home Assistant / Alexa** — Sensor presencia en cuarto + evento en 30 min → aviso Alexa
5. **Raspberry Pi** — Pantalla siempre encendida mostrando el dashboard

---

## Notas técnicas importantes

- **Refresh token Outlook** — en `backend/.token` (JSON). Fly.io lo persiste en volumen. Si se pierde, re-autenticar via `/auth/login`.
- **HA_TOKEN** — hardcodeado en `Dashboard.jsx` (~línea 175). Pendiente mover a variable de entorno Vercel.
- **Entregas** — detectadas por emoji 📚 en el título del evento de Outlook.
- **alud_url** — se añade en la descripción del evento de Outlook como: `alud_url: https://alud.deusto.es/mod/assign/view.php?id=XXXXX`
- **Clases** — calendario Outlook separado llamado "Clases". Endpoint `/calendar/classes`.
- **Fly.io cold start** — ~5s. Secrets: `DASHBOARD_PASSWORD`, `SECRET_KEY`, `CLIENT_ID`, `TENANT_ID`, `CLIENT_SECRET`, `GOOGLE_MAPS_API_KEY`, `SUPABASE_URL`, `SUPABASE_KEY`, `OPENAI_API_KEY`.
- **Deploy backend** — siempre desde `/backend`: `flyctl deploy --app backend-tender-glow-160`
- **Deploy frontend** — automático via Vercel al hacer push a main.
- **Git pull antes de deploy** — hacer siempre `git pull origin main` antes de `flyctl deploy` para coger los últimos cambios.

---

## Última actualización

**11/05/2026** — Migraciones Supabase ejecutadas (jobs, pc_agents, job_results). Task Scheduler configurado. alud_url extraído de bodyPreview del evento Outlook y pasado en el payload del job al hacer WOL. Pendiente: prueba end-to-end completa del flujo.
