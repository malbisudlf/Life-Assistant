# Life Assistant

Dashboard personal que centraliza calendario, salud, entrenamientos, hogar inteligente y un agente PC autónomo — todo en una sola pantalla.

**Demo:** [life-assistant-smoky.vercel.app](https://life-assistant-smoky.vercel.app)

---

## Funcionalidades

### Agenda y tiempo
- **Timeline de hoy** — mezcla eventos de Outlook y calendario de clases, con indicador de evento activo y cálculo de hora de salida con tráfico real (Google Maps)
- **Próximos 7 días** — vista rápida de lo que viene
- **Entregas** — detecta eventos con 📚 en el título y los ordena por urgencia con semáforo de colores; busca en ambos calendarios (general y clases)
- **Clases** — panel lateral con el horario semanal universitario

### Salud (Apple Watch)
Los datos llegan automáticamente desde Apple Watch via Health Auto Export e iOS Shortcuts:

- **Bienestar** — puntuación 0–100 con dos vistas:
  - *Semana*: promedios de los últimos 7 días + entrenamientos desde el lunes
  - *Hoy*: valores del día actual
  - Score: sueño 25 pts · actividad 30 pts · recuperación 25 pts · forma física 10 pts · estilo de vida 10 pts
  - Insights automáticos y recomendación diaria

- **Sueño** — duración total, fases (profundo / REM / core / despierto) con tooltips explicativos, puntuación 0–100 y resumen de las últimas 7 noches. Permite **anular noches** con datos incorrectos (p.ej. Watch en carga) para que no afecten a las métricas

- **Frecuencia cardíaca** — sparkline 30 días
- **HRV** — sparkline con tendencia vs semana anterior
- **Actividad** — pasos, calorías y barras de los últimos 7 días
- **Entrenamientos AW** — lista de entrenamientos sincronizados desde Hevy → Apple Health

### Entrenamiento personal
- Contador de sesiones desde el último cobro, horas acumuladas e importe pendiente
- Formulario para añadir sesiones y registrar cobros
- Configuración de precio/hora y sesiones por cobro

### Ideas por voz
Graba audio → Whisper transcribe → GPT-4o-mini extrae título, categoría y resumen → se guarda en Supabase

### Hogar inteligente
- **Wake-on-LAN** — enciende el PC físico desde el dashboard a través de Home Assistant, sin conexión directa desde el browser
- **Notificaciones Alexa** — anuncia el nombre del evento 15 minutos antes en voz alta

### Agente PC autónomo
El agente recibe un job desde el dashboard y ejecuta la entrega universitaria de forma semiautónoma:

1. El dashboard manda señal WOL → Home Assistant enciende el PC
2. El PC arranca y el agente inicia heartbeat
3. Playwright abre Edge con el perfil real del usuario (cookies persistidas), navega a Alud (Moodle de Deusto) y extrae el enunciado
4. Abre Claude Desktop en modo Cowork y le pega el enunciado con instrucciones
5. El usuario revisa y envía la entrega manualmente

El dashboard muestra la barra de progreso en tiempo real con las etapas del agente.

---

## Stack

| Capa | Tecnología |
|---|---|
| Frontend | React 19 + Vite, desplegado en Vercel |
| Backend | FastAPI (Python 3.11), desplegado en Fly.io |
| Base de datos | Supabase (PostgreSQL) |
| Calendario | Microsoft Graph API (Outlook) |
| Mapas | Google Maps Distance Matrix API |
| IA | OpenAI Whisper + GPT-4o-mini |
| Salud | Apple Watch → Health Auto Export → iOS Shortcuts |
| Smart home | Home Assistant (REST API + SSH) |
| Agente | Playwright (Edge) + pyautogui + Claude Desktop |

---

## Arquitectura

```
Browser (Vercel)
    │  JWT auth + REST
    ▼
Backend FastAPI (Fly.io)
    ├── Microsoft Graph API  ─── Calendario Outlook
    ├── Google Maps API      ─── Tiempos de salida con tráfico
    ├── OpenAI API           ─── Whisper + GPT-4o-mini
    ├── Supabase REST        ─── Ideas, jobs, agentes, entrenamiento, salud
    └── Home Assistant API   ─── Flag WOL + eventos próximos

Apple Watch
    └── Health Auto Export + iOS Shortcuts → POST /health/ingest → Supabase

Home Assistant (red local)
    └── Sondea el backend cada 30s (WOL) y cada 60s (próximos eventos)

Agente PC (Windows, red local)
    ├── Playwright + Edge    ─── Automatización web (Alud/Moodle)
    ├── pyautogui            ─── Control de UI (Claude Desktop)
    └── Supabase             ─── Cola de jobs (polling)
```

### Layout del dashboard

Dos columnas redimensionables arrastrando el divisor central. Cada widget es configurable (visible/oculto, columna, orden, tamaño) desde el panel ⚙. La configuración se persiste en `localStorage`.

---

## Configuración

### Requisitos previos
- Node.js 20+
- Python 3.11+
- Cuenta de Microsoft con Outlook y app registrada en Azure AD
- Proyecto en Supabase
- API keys: Google Maps, OpenAI
- *(Opcional)* Home Assistant, Apple Watch con Health Auto Export

### Frontend

```bash
npm install
npm run dev        # http://localhost:5173
npm run build
```

### Backend

```bash
cd backend
python -m venv venv
venv\Scripts\activate   # Windows
# source venv/bin/activate   # macOS/Linux
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

# Salud (Apple Watch)
HEALTH_INGEST_TOKEN=

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

Crear `agent/.env`:
```env
LA_TOKEN=          # JWT del dashboard (F12 → Application → Local Storage → la_token)
LA_API_BASE=https://tu-backend.fly.dev
SUPABASE_URL=
SUPABASE_KEY=
ALUD_ACCOUNT=tu.email@universidad.es
EDGE_PROFILE_DIR=  # opcional, por defecto usa el perfil Default de Edge
```

### Ingesta de salud (Apple Watch)

El backend expone `POST /health/ingest?token=HEALTH_INGEST_TOKEN` compatible con [Health Auto Export](https://www.healthexportapp.com/) (formato JSON v2). Configurar dos automatizaciones en la app: una para métricas y otra para workouts, apuntando a la URL del backend.

---

## Despliegue

**Frontend** — push a `main` despliega automáticamente en Vercel.

**Backend (Fly.io)**:
```bash
cd backend
fly deploy
```

Los secrets se configuran con `fly secrets set KEY=value` y no se incluyen en el repositorio.

---

## Estructura del proyecto

```
├── src/
│   └── components/
│       └── Dashboard.jsx      # UI completa (~1800 líneas)
├── backend/
│   └── main.py                # API FastAPI (~1250 líneas)
├── agent/
│   └── agent.py               # Agente PC autónomo
└── public/
```
