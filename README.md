# Life Assistant

Dashboard personal que integra calendario, entregas universitarias, control del hogar y un agente PC autónomo.

**Demo:** [life-assistant-smoky.vercel.app](https://life-assistant-smoky.vercel.app)

---

## Stack

| Capa | Tecnología |
|---|---|
| Frontend | React 19 + Vite, desplegado en Vercel |
| Backend | FastAPI (Python), desplegado en Fly.io |
| Base de datos | Supabase (PostgreSQL) |
| Calendario | Microsoft Graph API (Outlook) |
| Mapas | Google Maps Distance Matrix API |
| IA | OpenAI Whisper + GPT-4o-mini |
| Smart home | Home Assistant (REST API + SSH) |

---

## Funcionalidades

### Dashboard
- **Timeline de hoy** — eventos de Outlook ordenados por hora, con indicador de evento activo
- **¿A qué hora salir?** — calcula la hora de salida con tráfico real via Google Maps, con 10 min de margen
- **Próximos eventos** — vista de los próximos 7 días
- **Entregas** — detecta eventos con 📚 en el título, ordenados por urgencia con semáforo de colores
- **Clases universitarias** — calendario separado en Outlook, panel lateral con horario del día
- **Ideas por voz** — graba audio → Whisper transcribe → GPT-4o-mini extrae título, categoría y resumen → Supabase
- **Entrenamiento personal** — contador de sesiones, horas acumuladas e importe pendiente de cobro

### Agente PC autónomo
El agente recibe un job desde el dashboard, enciende el PC via Wake-on-LAN, y ejecuta la entrega universitaria de forma autónoma:

1. El dashboard detecta la entrega y manda señal WOL a través de Home Assistant
2. El PC arranca, el agente inicia heartbeat
3. Playwright abre Edge con el perfil real del usuario (cookies persistidas), navega a Alud (Moodle de Deusto) y extrae el enunciado de la entrega
4. Abre Claude Desktop en modo Cowork y le pega el enunciado con instrucciones
5. Cowork resuelve la entrega y la rellena en el formulario — el usuario la revisa y envía manualmente

El dashboard muestra la barra de progreso en tiempo real con las etapas del agente.

### Home Assistant
- **Notificaciones Alexa** — 15 min antes de cualquier evento del calendario, Alexa lo anuncia en voz alta
- **Wake-on-LAN** — el dashboard activa el PC físico a través de HA, sin conexión directa desde el browser

---

## Arquitectura

```
Browser (Vercel)
    │  JWT auth + REST
    ▼
Backend FastAPI (Fly.io)
    ├── Microsoft Graph API  ─── Calendario Outlook
    ├── Google Maps API      ─── Tiempos de salida
    ├── OpenAI API           ─── Whisper + GPT-4o-mini
    ├── Supabase REST        ─── Ideas, jobs, agentes, entrenamiento
    └── Home Assistant API   ─── WOL flag + eventos próximos

Home Assistant (local, 192.168.1.x)
    └── Sondea el backend cada 30s (WOL) y cada 60s (eventos)

Agente PC (Windows, local)
    ├── Playwright + Edge    ─── Automatización web (Alud/Moodle)
    ├── pyautogui            ─── Control de UI (Claude Desktop)
    └── Supabase             ─── Cola de jobs (polling directo)
```

---

## Configuración

### Requisitos previos
- Node.js 20+
- Python 3.11+
- Cuenta de Microsoft con Outlook
- App registrada en Azure AD (para Microsoft Graph)
- Proyecto en Supabase
- API keys: Google Maps, OpenAI

### Frontend

```bash
npm install
npm run dev        # http://localhost:5173
npm run build
```

Variables de entorno (opcional):
```
VITE_HA_URL=http://192.168.1.x:8123   # URL de Home Assistant para el toggle LA/HA
```

### Backend

```bash
cd backend
python -m venv venv
venv\Scripts\activate   # Windows
pip install -r requirements.txt
uvicorn main:app --reload   # http://localhost:8000
```

Crear `backend/.env`:
```env
# Microsoft Graph (Azure AD)
CLIENT_ID=
TENANT_ID=
CLIENT_SECRET=
REDIRECT_URI=http://localhost:8000/auth/callback

# Dashboard
DASHBOARD_PASSWORD=
SECRET_KEY=

# Servicios externos
GOOGLE_MAPS_API_KEY=
SUPABASE_URL=
SUPABASE_KEY=
OPENAI_API_KEY=

# Home Assistant
HA_URL=http://192.168.1.x:8123
HA_TOKEN=
HA_POLL_TOKEN=

# Dirección de origen para cálculo de rutas
HOME_ADDRESS=Tu dirección, Ciudad, País
```

Autenticar con Outlook (primera vez):
1. Visitar `http://localhost:8000/auth/login`
2. Completar el flujo OAuth de Microsoft
3. El refresh token se guarda en `backend/.token`

### Agente PC

```bash
cd agent
pip install -r requirements.txt
```

Crear `agent/.env` (ver `agent/.env.example`):
```env
LA_TOKEN=          # JWT del dashboard (F12 → Application → Local Storage → la_token)
LA_API_BASE=https://tu-backend.fly.dev
SUPABASE_URL=
SUPABASE_KEY=
ALUD_ACCOUNT=tu.email@universidad.es
EDGE_PROFILE_DIR=  # opcional, por defecto usa el perfil Default de Edge
```

---

## Despliegue

**Frontend** — push a `main` despliega automáticamente en Vercel.

**Backend (Fly.io)**:
```bash
cd backend
fly deploy
```

Los secrets se configuran en Fly.io y no se incluyen en el repositorio.
