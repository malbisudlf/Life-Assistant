# Life Assistant — Estado del Proyecto

> **INSTRUCCIÓN PARA CLAUDE:** Lee este archivo al inicio de cada sesión en lugar de buscar conversaciones anteriores. Actualízalo al final de cada sesión.

---

## Stack

| Capa | Tecnología | URL / Ruta |
|------|-----------|------------|
| Frontend | React + Vite | https://life-assistant-smoky.vercel.app |
| Backend | FastAPI (Python) | https://backend-tender-glow-160.fly.dev |
| Base de datos | Supabase (PostgreSQL) | variable `SUPABASE_URL` en .env |
| Calendario | Microsoft Graph API (Outlook) | OAuth2 con refresh token en `.token` |
| Audio/IA | Whisper-1 + GPT-4o mini (OpenAI) | variable `OPENAI_API_KEY` |
| Auth dashboard | JWT con contraseña única | `DASHBOARD_PASSWORD` en .env |
| Home Assistant | http://192.168.1.200:8123 | Token largo en `HA_TOKEN` hardcoded en Dashboard.jsx |
| Repo | GitHub privado | Life-Assistant |

---

## Estructura del proyecto

```
Life Assistant/
├── backend/
│   ├── main.py          ← API principal (FastAPI)
│   └── .env             ← Credenciales (no en git)
├── src/
│   └── components/
│       └── Dashboard.jsx ← Componente principal (todo el UI)
├── PROJECT_STATE.md      ← Este archivo
└── package.json
```

---

## Funcionalidades implementadas ✅

- **Auth JWT** — Login por contraseña + token con 30 días de validez
- **Timeline de eventos** — Eventos del día de Outlook ordenados por hora con nodos interactivos
- **Calendario de clases** — Calendario separado "Clases" en Outlook, nodo especial azul en timeline
- **Panel lateral de clases** — Click en nodo "Clases" abre panel derecho con horario detallado
- **Próximos eventos** — Vista de 7 días, máx 5 eventos
- **Entregas** — Filtra eventos con 📚 en el título, ordenadas por urgencia (verde/naranja/rojo)
- **¿A qué hora salir?** — Botón en eventos con ubicación → Google Maps API → calcula hora de salida con tráfico + 10 min margen
  - Origen: GPS del móvil si hay permiso, fallback a `Astigarraga 35, Durango`
  - Las clases usan `Universidad de Deusto, Bilbao` como destino (ignorando el campo `location` que tiene el aula)
- **Módulo de ideas** — Grabar audio → Whisper STT → GPT-4o mini extrae idea clave + resumen → Supabase → UI expandible
- **Wake on LAN** — Click en entrega → modal "¿Encender PC?" → llama a Home Assistant (`button.pc_mikel`) → WOL
- **Responsive móvil** — CSS media queries para pantallas < 640px
- **Timezone fix** — `normalize_graph_dt()` convierte correctamente fechas de Windows TZ (Romance Standard Time, etc.) a UTC

---

## Pendiente 📋

Por orden de prioridad:

1. **BMW Connected Drive** — Click en evento con ubicación → enviar navegación al BMW X3 20d
2. **Home Assistant / Alexa** — Si sensor de presencia activo en cuarto y evento en 30 min → aviso por Alexa
3. **Agente WOL fase 2** — Tras encender PC: agente Python escucha Supabase Realtime, abre Alud, pasa enunciado a Claude API, ejecuta entrega
4. **Raspberry Pi** — Pantalla siempre encendida mostrando el dashboard

---

## Notas técnicas importantes

- **Refresh token de Outlook** se guarda en `backend/.token` (JSON). Fly.io lo persiste en el volumen. Si se pierde, hay que re-autenticar via `/auth/login`.
- **HA_TOKEN** está hardcodeado en `Dashboard.jsx` (línea ~185). Pendiente moverlo a variable de entorno de Vercel.
- **Entregas** se detectan por el emoji 📚 en el título del evento de Outlook (no por `[ENTREGA]` como estaba antes).
- **Clases** vienen de un calendario Outlook separado llamado "Clases". El endpoint es `/calendar/classes`.
- **Fly.io** puede hacer cold start (~5s). El backend tiene `DASHBOARD_PASSWORD`, `SECRET_KEY`, `CLIENT_ID`, `TENANT_ID`, `CLIENT_SECRET`, `GOOGLE_MAPS_API_KEY`, `SUPABASE_URL`, `SUPABASE_KEY`, `OPENAI_API_KEY` como secrets.

---

## Última actualización

**08/05/2026** — Archivo creado. WOL implementado y funcionando vía Home Assistant.
