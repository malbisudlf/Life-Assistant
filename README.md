# Life Assistant

Dashboard personal que centraliza calendario, salud, entrenamientos, ideas, hogar inteligente y un agente PC autónomo — con un asistente encima que consulta, actúa y avisa sin que se lo pidan.

**Demo:** [life-assistant-smoky.vercel.app](https://life-assistant-smoky.vercel.app)

> **¿Quieres el tuyo?** El proyecto es replicable: cada instancia corre con tus
> propias cuentas (Outlook, Supabase, API keys) sobre free tiers de Vercel y
> Fly.io. Guía completa paso a paso en [`docs/DESPLIEGUE.md`](docs/DESPLIEGUE.md).

![Dashboard](public/screenshot.png)

> Si quieres entender el proyecto entero —qué hace y **por qué está construido así**—
> el recorrido largo está en [`docs/EL_PROYECTO_EXPLICADO.md`](docs/EL_PROYECTO_EXPLICADO.md).

---

## Funcionalidades

### Agenda y tiempo
- **Timeline de hoy** — mezcla eventos de Outlook y calendario de clases, con indicador de evento activo y cálculo de hora de salida con tráfico real (Google Maps)
- **Crear y editar eventos** en Outlook desde el propio panel, con selectores de fecha y hora propios (los nativos dependen del locale del SO y creaban eventos en la fecha equivocada)
- **Próximos 7 días** — vista rápida de lo que viene
- **Entregas** — detecta eventos con 📚 en el título y los ordena por urgencia con semáforo de colores; busca en ambos calendarios (general y clases)
- **Clases** — panel lateral con el horario semanal universitario
- **Clima** — Open-Meteo (gratis, sin API key), con la ubicación del navegador o la que reporte Home Assistant

### Salud (Apple Watch)
Los datos llegan automáticamente desde Apple Watch por dos vías en paralelo: Health Auto Export (métricas, entrenos y fases de sueño) y un Atajo de iOS (las métricas del día en tiempo real).

- **Bienestar** — puntuación 0–100 con dos vistas (*Semana* y *Hoy*), desglose por componente en un tooltip, insights automáticos, recomendación diaria y sparkline de evolución
- **Sueño** — duración, fases (profundo / REM / core / despierto), puntuación 0–100 y resumen de las últimas 7 noches. Permite **anular noches** con datos incorrectos (p. ej. el Watch en carga) para que no afecten a las métricas
- **Conclusiones y patrones** — motor que deriva frases de los datos: tendencias, cruces entre series (¿duermes peor los días que andas menos?) y una **firma de malestar** que solo salta cuando coinciden FC en reposo alta, HRV baja y respiración alta a la vez
- **Línea base personal** — en las métricas de fisiología el listón sale de los percentiles de tu propio histórico, no de un umbral fijo: con una FC basal de 62, los puntos de «≤50» no se sacan nunca por mucho que mejores
- **Uso del reloj** — el sistema sabe qué días lo llevaste puesto, y distingue *lo llevabas*, *no lo llevabas pero el móvil sí midió* y *no llegó nada*. Sin ese denominador, un mes sin reloj se lee como un mes de empeoramiento
- **Frecuencia cardíaca, HRV, actividad y entrenamientos** — sparklines, tendencias y listas de detalle
- **Composición corporal** — peso, % grasa y masa magra con objetivo configurable

### Jarvis — el asistente
- **51 herramientas** sobre los endpoints que ya existen: agenda, salud, entrenamiento, ideas, la casa, el PC, el resumen diario, diagnóstico del propio sistema
- **La decisión de qué herramienta usar vive entera en el backend** — el cliente solo manda texto
- **Frontera de confirmación**: lo que ya tiene un botón en el dashboard lo ejecuta él; lo que toca el calendario, conecta un servidor nuevo o abre una cerradura se **propone** y espera a que lo apruebes, con los argumentos reales a la vista
- **Voz de entrada y salida** con el reconocimiento del navegador (gratis, sin salir del dispositivo) y **modo llamada** para hablar seguido sin pulsar enviar
- **Memoria persistente**, **búsqueda y lectura web** (con defensa SSRF y contenido externo etiquetado como no fiable) y **cliente MCP** con lista blanca del usuario

### Proactividad
Todo lo que el sistema dice sin que se le hable, gobernado por un presupuesto de avisos al día, botones de útil / no útil que hacen que una regla inútil se calle sola, y memoria de lo ya dicho.

- «Sal ya» con el tráfico calculado, «no llegas» entre dos citas, «mañana empiezas pronto», «ponte el reloj» antes de dormir, huecos libres para entrenar
- **Recordatorios** y **vigilancia de páginas** (¿ha cambiado?, ¿ya aparece esto?), creados hablando
- **Reglas que Jarvis propone y tú apruebas** — el modelo no escribe reglas, rellena plantillas: las condiciones siguen en Python, revisables en un diff
- Los avisos salen por la app del móvil vía Home Assistant, con el correo como red de seguridad

### Resumen diario e informe semanal
- Correo con los **datos del día en crudo**, sin interpretarlos: quien los consume es una rutina externa que redacta el briefing
- Sale **al despertarte**, no a una hora fija: tres disparadores distintos y una única puerta idempotente
- Cada media va con su `n`, las series con los huecos marcados, y se señalan los **días atípicos**
- **Informe semanal** los domingos con medias por semana de los últimos meses
- Interruptor y pausa con fecha desde el panel ⚙

### Entrenamiento personal
- Contador de sesiones desde el último cobro, horas acumuladas e importe pendiente
- Formulario para añadir sesiones y registrar cobros
- Configuración de precio/hora, sesiones por cobro y días de entrenamiento

### Ideas por voz
Graba audio → Whisper transcribe → GPT-4o-mini extrae título, categoría y resumen → se guarda en Supabase. Si la nota señala una cita, ofrece un chip para crear el evento (nunca lo crea solo). También admite texto escrito.

### Hogar inteligente
- **Wake-on-LAN** — enciende el PC físico desde el dashboard a través de Home Assistant, sin conexión directa desde el browser
- **Apagar / suspender** el PC por SSH, y relanzar el agente
- **Luces, enchufes y persianas** hablando con Jarvis, con lista blanca de dominios y confirmación para lo que no es un interruptor
- **Notificaciones Alexa** — anuncia el nombre del evento 15 minutos antes en voz alta
- **Presencia** — la app companion de HA empuja dónde estás; alimenta el clima, el cálculo de rutas y una serie diaria de horas en casa (solo horas, nunca lugares)

### Agente PC autónomo
El agente recibe un job desde el dashboard y lo ejecuta de forma semiautónoma:

1. El dashboard manda señal WOL → Home Assistant enciende el PC
2. El PC arranca y el agente inicia heartbeat
3. Playwright abre Edge con el perfil real del usuario (cookies persistidas), navega a Alud (Moodle de Deusto) y extrae el enunciado
4. Abre Claude Desktop en modo Cowork y le pega el enunciado con instrucciones
5. El usuario revisa y envía la entrega manualmente

También lanza el **streaming del PC** (Sunshine + VPN) para jugar desde fuera de casa. El dashboard muestra la barra de progreso en tiempo real con las etapas del agente.

### El sistema se vigila a sí mismo
- **Registro persistente** de errores (la salida estándar se la lleva la máquina de Fly al escalar a cero) y panel de estado en ⚙
- **Vigilante de la ingesta** — si dejan de entrar datos de salud, avisa
- **Vigilante del sistema** — detecta averías, repara lo poco que puede verificar (y dice cuántas veces lleva) y abre un issue con el resto
- **Revisión nocturna** — si entraron commits en `main`, de madrugada una sesión de Claude Code los revisa y abre un issue; por la mañana llega al móvil con dos botones, y «Arreglarlo» lanza otra sesión que lo arregla, abre PR y mergea si el CI pasa

---

## Stack

| Capa | Tecnología |
|---|---|
| Frontend | React 19 + Vite, desplegado en Vercel |
| Backend | FastAPI (Python 3.11), desplegado en Fly.io |
| Base de datos | Supabase (PostgreSQL vía REST) |
| Calendario | Microsoft Graph API (Outlook) |
| Mapas | Google Maps Distance Matrix API |
| Clima | Open-Meteo (sin API key) |
| IA | OpenAI Whisper + GPT-4o-mini |
| Salud | Apple Watch → Health Auto Export + Atajos de iOS |
| Smart home | Home Assistant (sondeo REST + SSH) |
| Agente | Playwright (Edge) + pyautogui + Claude Desktop |
| Tests | Vitest + Testing Library · pytest · Playwright |

---

## Arquitectura

```
Browser (Vercel)
    │  JWT auth + REST
    ▼
Backend FastAPI (Fly.io, escala a cero)
    ├── Microsoft Graph API  ─── Calendario Outlook (tokens OAuth en Supabase)
    ├── Google Maps API      ─── Hora de salida con tráfico
    ├── Open-Meteo           ─── Clima
    ├── OpenAI API           ─── Whisper + GPT-4o-mini (ideas y cerebro de Jarvis)
    ├── Supabase REST        ─── Ideas, jobs, salud, entrenamiento, memoria, avisos…
    └── Colas en memoria     ─── Órdenes pendientes para Home Assistant

Apple Watch
    └── Health Auto Export + Atajos de iOS → POST /health/ingest → Supabase

Home Assistant (red local, siempre encendido)
    ├── SONDEA el backend ─── WOL, órdenes de la casa, avisos al móvil,
    │                         y el tick cada 5 min que hace de reloj del sistema
    └── EMPUJA al backend ─── presencia y catálogo de dispositivos

Agente PC (Windows, efímero)
    ├── Playwright + Edge    ─── Automatización web (Alud/Moodle)
    ├── pyautogui            ─── Control de UI (Claude Desktop)
    └── Backend REST         ─── Cola de jobs (nunca Supabase directo)
```

El backend **no puede llamar a la red local** (el navegador habla HTTPS y Home Assistant
HTTP en la LAN), así que deja las órdenes en una cola y HA viene a por ellas. Y como Fly
escala a cero, tampoco hay ningún proceso vivo dentro capaz de mirar la hora: el reloj lo
pone el tick de HA.

### Layout del dashboard

Dos o tres columnas redimensionables arrastrando los divisores. Cada widget es configurable
(visible/oculto, columna, orden, tamaño) desde el panel ⚙, con modo edición y guías de
alineación. La configuración se persiste en `localStorage`. Hay además un **modo simple**
para el móvil, que reutiliza los mismos widgets con otra distribución, y la app es una
**PWA** instalable.

---

## Puesta en marcha

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

> El dev server **tiene que arrancar en el 5173**: el CORS del backend solo permite los
> orígenes de `CORS_ORIGINS`. Si el puerto está ocupado, Vite salta al 5174 y el login
> falla con un error de CORS, no de credenciales.

### Backend

```bash
cd backend
python -m venv venv
venv\Scripts\activate       # Windows
# source venv/bin/activate  # macOS/Linux
pip install -r requirements.txt
uvicorn main:app --reload   # http://localhost:8000
```

### Configuración

Los ficheros de ejemplo son la referencia completa y están comentados variable a variable:

| Fichero | Qué configura |
|---|---|
| [`backend/.env.example`](backend/.env.example) | Todo el backend. Solo `SECRET_KEY` y `DASHBOARD_PASSWORD` son obligatorias — sin ellas no arranca (fail-fast a propósito) |
| [`agent/.env.example`](agent/.env.example) | El agente PC |
| Variables `VITE_*` en Vercel | `VITE_API_URL`, `VITE_HA_URL`, `VITE_HA_DASHBOARD_PATH`, `VITE_ENTREGAS_MARKER` |

```bash
python backend/check_config.py   # comprueba que no falta nada
```

Las migraciones de Supabase están en [`supabase/migrations/`](supabase/migrations) y se
aplican a mano desde el editor SQL, en orden de fecha.

### Conectar Outlook (primera vez)

Desde el dashboard, con la sesión ya iniciada: botón **Conectar Outlook** → flujo OAuth de
Microsoft. El refresh token se guarda en la tabla `oauth_tokens` de Supabase, así que
sobrevive a los redeploys.

> `GET /auth/login` exige JWT y devuelve la URL con un `state` firmado — **no abras esa
> ruta a pelo en el navegador ni la enlaces con un `<a href>`**: sin la cabecera de
> autenticación no funciona, y el `state` es lo que impide que otra persona complete su
> propio login de Microsoft contra tu backend.

### Ingesta de salud (Apple Watch)

El backend expone `POST /health/ingest`, compatible con
[Health Auto Export](https://www.healthexportapp.com/) (JSON v2, con *Batch requests*
activado), y `POST /health/ingest/simple` para los Atajos de iOS. El paso a paso —qué
automatizaciones crear, qué métricas manda cada una y las trampas conocidas de Atajos—
está en [`docs/SALUD.md`](docs/SALUD.md).

### Agente PC

```bash
cd agent
pip install -r requirements.txt
```

Copia `agent/.env.example` a `agent/.env`. La credencial es **`AGENT_TOKEN`**, un token de
servicio que no caduca y que debe valer lo mismo que en el backend; `LA_TOKEN` (el JWT del
dashboard) solo queda como respaldo y **caduca a los 30 días** — cuando expiró, el agente
se cerraba en cada arranque diciendo que no había trabajo.

La instalación (dependencias, tarea del Programador con privilegios elevados, logs) está en
[`agent/README.md`](agent/README.md), y la puesta a punto del streaming remoto —Sunshine
desatendido, Tailscale, WOL— en [`agent/PUESTA_A_PUNTO.md`](agent/PUESTA_A_PUNTO.md).

---

## Tests

```bash
npm run lint      # eslint — cero errores y cero warnings
npm test          # vitest (tests/frontend)
npm run build     # verifica que compila

python3 -m venv .venv
.venv/bin/pip install -r backend/requirements.txt pytest
.venv/bin/python -m pytest tests/backend

npm run test:e2e  # Playwright contra el build + el backend real
```

Más de mil tests entre las tres suites. El E2E no usa un backend de mentira: importa
`backend/main.py` tal cual y solo sustituye el cliente HTTP saliente, así que comprueba
también que el contrato entre frontend y backend sigue cuadrando. Los tests fallan si el
navegador registra **cualquier** excepción o error de consola.

CI en [`.github/workflows/ci.yml`](.github/workflows/ci.yml): los mismos pasos en tres
jobs paralelos (frontend / backend / E2E) en cada push a `main` y en cada PR. No despliega
nada.

---

## Despliegue

**Frontend** — push a `main` despliega automáticamente en Vercel.

**Backend (Fly.io)** — manual, nunca en automático:

```bash
cd backend
fly deploy
```

También está el workflow `Deploy backend (Fly.io)` (`workflow_dispatch`). Los secrets se
configuran con `fly secrets set KEY=value` y no se incluyen en el repositorio. El backend
escala a cero cuando no hay tráfico, de ahí el arranque en frío de 10–15 s.

---

## Estructura del proyecto

```
├── src/
│   ├── components/Dashboard.jsx   # UI completa (~5.600 líneas)
│   └── lib/helpers.js             # lógica pura y testeada (~1.560 líneas)
├── backend/
│   ├── main.py                    # API FastAPI (~10.700 líneas, 73 endpoints)
│   └── check_config.py            # verifica la configuración
├── agent/agent.py                 # agente PC autónomo (~1.000 líneas)
├── supabase/migrations/           # esquema de la BD
├── tests/                         # backend · frontend · e2e
├── docs/                          # la guía por áreas
└── public/                        # PWA (manifest, service worker, iconos)
```

## Documentación

[`CLAUDE.md`](CLAUDE.md) es el índice: seguridad del repo, comandos, arquitectura,
invariantes del backend y convenciones. El detalle de cada área vive en
[`docs/`](docs) — backend, frontend, Jarvis, salud, entrenamiento, Home Assistant,
agente PC, tests, despliegue y un fichero entero de bugs históricos con su moraleja.

Todo el proyecto está en español: comentarios, commits, strings de UI y mensajes de error.
