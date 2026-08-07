# Despliega tu propio Life Assistant

Guía para levantar una instancia propia desde cero. Al terminar tendrás el
dashboard corriendo con **tus** cuentas: tu Outlook, tu Supabase, tus API keys.
Coste de infraestructura: ~0 €/mes (free tiers de Vercel, Fly.io y Supabase);
las APIs de Google Maps y OpenAI son de pago por uso (céntimos al mes para un
solo usuario).

> **Qué es replicable y qué no.** El dashboard completo (calendario, hora de
> salida, ideas por voz, salud del Apple Watch, entrenamientos) funciona en
> cualquier instancia. La integración con Home Assistant es opcional y requiere
> tu propio HA. El agente PC (`agent/`) automatiza el Moodle de Deusto en un
> Windows concreto: trátalo como ejemplo, no como parte del kit.

## 0. Requisitos

- Cuentas: [GitHub](https://github.com), [Vercel](https://vercel.com),
  [Fly.io](https://fly.io), [Supabase](https://supabase.com), una cuenta
  Microsoft con Outlook, [Google Cloud](https://console.cloud.google.com)
  (Maps) y [OpenAI](https://platform.openai.com).
- Local: Node 20+, Python 3.11+, `flyctl` instalado.
- Haz **fork** de este repositorio: el deploy de Vercel y tus ajustes viven en tu fork.

## 1. Supabase (base de datos)

1. Crea un proyecto nuevo.
2. En **SQL Editor**, ejecuta los ficheros de `supabase/migrations/` **en orden
   cronológico** (el nombre empieza por la fecha). Crean las tablas de jobs,
   agentes, tokens OAuth, ideas, ropa, entrenamiento, salud, intentos de login y
   el registro del backend (`app_logs`), con RLS activado.
3. Apunta de **Settings → API**: la `URL` del proyecto y la **`service_role` key**
   (no la `anon`; la service key solo vivirá en el backend — el agente PC ya no la
   necesita, ver `agent/.env.example`).
4. (Entrenamiento personal) Si usas el widget de entrenamiento, inserta tu cliente:
   ```sql
   insert into training_clients (name, price_per_hour, sessions_per_payment)
   values ('Mi cliente', 20, 10);
   ```

## 2. Azure AD (calendario de Outlook)

1. [Portal de Azure](https://portal.azure.com) → **App registrations → New registration**.
   - Supported account types: *Accounts in any organizational directory and personal Microsoft accounts*.
   - Redirect URI (Web): `https://TU-BACKEND.fly.dev/auth/callback`
     (y `http://localhost:8000/auth/callback` para desarrollo).
2. **API permissions** → Microsoft Graph → *Delegated* → `Calendars.ReadWrite`, `User.Read`.
3. **Certificates & secrets** → crea un client secret (apunta el *value*, no el id).
4. Apunta: `CLIENT_ID` (Application ID), `TENANT_ID` (Directory ID) y `CLIENT_SECRET`.

## 3. Backend en Fly.io

```bash
cd backend
cp .env.example .env        # rellena los valores (guíate por los comentarios)
python ../backend/check_config.py   # te dice qué falta, agrupado por funcionalidad

fly launch --no-deploy      # crea TU app (nombre propio); reutiliza el Dockerfile
fly secrets set \
  SECRET_KEY="$(openssl rand -hex 32)" \
  DASHBOARD_PASSWORD=... \
  SUPABASE_URL=... SUPABASE_KEY=... \
  CLIENT_ID=... TENANT_ID=... CLIENT_SECRET=... \
  REDIRECT_URI=https://TU-BACKEND.fly.dev/auth/callback \
  GOOGLE_MAPS_API_KEY=... OPENAI_API_KEY=... \
  HA_POLL_TOKEN="$(openssl rand -hex 24)" \
  HEALTH_INGEST_TOKEN="$(openssl rand -hex 24)" \
  AGENT_TOKEN="$(openssl rand -hex 24)" \
  TIMEZONE=Europe/Madrid \
  HOME_ADDRESS="Tu dirección, Ciudad" \
  CLASSES_CALENDAR=clases \
  WEATHER_LAT=40.4168 WEATHER_LON=-3.7038 \
  ALUD_ALLOWED_HOSTS=alud.deusto.es \
  CORS_ORIGINS="http://localhost:5173,https://TU-APP.vercel.app"
fly deploy
```

Notas:
- `DASHBOARD_PASSWORD` **numérica**: el input del login es un teclado numérico.
- `ALUD_ALLOWED_HOSTS` acota a qué hosts puede apuntar el `alud_url` de un evento.
  Esa URL la acaba abriendo el agente en un navegador con la sesión iniciada, así que
  solo se aceptan `https` y los hosts de esta lista (o sus subdominios). Si no usas el
  agente PC, déjalo como está. **Pon el mismo valor en `agent/.env`**: se comprueba en
  los dos sitios porque un job puede llegar a Supabase sin pasar por el backend.
- `AGENT_TOKEN` es con lo que el agente PC sondea y cierra jobs. **Mismo valor en
  `agent/.env`**; si no usas el agente, déjalo sin poner. Es un token de servicio y no
  uno de usuario por lo mismo que `BRIEF_TOKEN`: el agente arranca solo, sin nadie
  delante, y un JWT del dashboard caduca a los 30 días y lo deja mudo sin avisar.
- `CLASSES_CALENDAR` es el nombre de un calendario de Outlook aparte para clases
  con horario; si no lo usas, ignora el panel de clases.
- `WEATHER_LAT`/`WEATHER_LON` son las coordenadas del widget de clima (Open-Meteo,
  gratis y sin API key). Por defecto Madrid.
- Google Maps: activa **Distance Matrix API** en tu proyecto de Google Cloud y
  restringe la key a esa API.

**Primer login con Outlook**: visita `https://TU-BACKEND.fly.dev/auth/login`,
abre la `auth_url` que devuelve y completa el OAuth. El refresh token queda en
Supabase (`oauth_tokens`) y se renueva solo.

## 4. Frontend en Vercel

1. Importa tu fork en Vercel (framework: Vite; build `npm run build`, output `dist`).
2. **Environment variables**:

   | Variable | Valor | Obligatoria |
   |---|---|---|
   | `VITE_API_URL` | `https://TU-BACKEND.fly.dev` | Sí |
   | `VITE_HA_URL` | URL de tu Home Assistant | No |
   | `VITE_HA_DASHBOARD_PATH` | Ruta del dashboard de HA (default `/lovelace/tablet`) | No |
   | `VITE_ENTREGAS_MARKER` | Marcador de entregas en títulos de eventos (default `📚`) | No |

3. Deploy. Añade el dominio resultante a `CORS_ORIGINS` del backend (paso 3) y
   redespliega el backend si lo cambiaste.

## 5. Salud desde el Apple Watch (opcional)

Con [Health Auto Export](https://www.healthexportapp.com/) (formato JSON v2),
crea una automatización REST hacia:

```
https://TU-BACKEND.fly.dev/health/ingest
Cabecera: X-Auth-Token: <HEALTH_INGEST_TOKEN>
```

Para iOS Shortcuts existe el endpoint simplificado `POST /health/ingest/simple`
(acepta un array `[{metric, date, value, unit}]` o NDJSON).

## 6. Home Assistant (opcional)

HA **sondea al backend** (no al revés: el backend no puede entrar en tu red
local). En `configuration.yaml`:

```yaml
rest:
  # Wake-on-LAN pendiente (el dashboard marca, HA enciende el PC)
  - resource: https://TU-BACKEND.fly.dev/ha/wol-pending
    headers: { X-Auth-Token: !secret la_poll_token }
    scan_interval: 30
    sensor:
      - name: la_wol_pending
        value_template: "{{ value_json.pending }}"

  # Próximo evento (~15 min antes) para anunciarlo por voz
  - resource: https://TU-BACKEND.fly.dev/ha/events/soon
    headers: { X-Auth-Token: !secret la_poll_token }
    scan_interval: 60
    sensor:
      - name: la_event_soon
        value_template: "{{ value_json.event.title if value_json.event else 'none' }}"

automation:
  - alias: "Life Assistant: WOL"
    trigger: [{ platform: state, entity_id: sensor.la_wol_pending, to: "True" }]
    action: [{ service: wake_on_lan.send_magic_packet, data: { mac: "AA:BB:CC:DD:EE:FF" } }]

  - alias: "Life Assistant: aviso de evento"
    trigger: [{ platform: state, entity_id: sensor.la_event_soon }]
    condition: "{{ trigger.to_state.state not in ['none', 'unknown', 'unavailable'] }}"
    action:
      - service: notify.alexa_media   # o tu servicio de TTS/notificación
        data: { message: "En 15 minutos: {{ trigger.to_state.state }}" }
```

Guarda `HA_POLL_TOKEN` como `la_poll_token` en `secrets.yaml`.

### Presencia (opcional, requiere la app companion de HA)

Es lo único que va en sentido contrario: aquí HA **empuja** el dato, porque el que sabe
dónde estás es él. Con esto, `/weather` y `/maps/departure` dejan de calcular siempre
desde casa, el resumen diario gana contexto y se guarda una serie diaria de horas en
casa (métrica `time_at_home`) que el motor de correlaciones cruza con el sueño y la HRV.
**No se guarda histórico de ubicación**: solo la posición actual, que se sobreescribe, y
horas por día — nunca lugares.

```yaml
rest_command:
  la_presencia:
    url: https://TU-BACKEND.fly.dev/ha/presencia
    method: POST
    headers: { X-Auth-Token: !secret la_poll_token }
    content_type: "application/json"
    payload: >-
      {"zona": "{{ zona }}", "en_casa": {{ en_casa }},
       "lat": {{ lat }}, "lon": {{ lon }}}

automation:
  - alias: "Life Assistant: presencia"
    mode: single
    max_exceeded: silent
    trigger:
      # 1) Cuando cambias de zona. `not_to` lo convierte en un trigger de ESTADO: sin
      #    él saltaría también con cada refresco de coordenadas del GPS, que son
      #    cambios de atributo y llegan constantemente.
      - platform: state
        entity_id: device_tracker.TU_MOVIL
        not_to: ["unknown", "unavailable"]
      # 2) Aviso periódico. No es redundante: es lo que hace que el silencio
      #    signifique algo. Sin él, el backend no puede distinguir "sigue en casa" de
      #    "HA se ha caído", y seguiría dando por buena una ubicación de hace horas.
      #    El intervalo tiene que ser MENOR que PRESENCE_TTL_MINUTES (45 por defecto).
      - platform: time_pattern
        minutes: "/15"
    action:
      - service: rest_command.la_presencia
        data:
          zona: "{{ states('device_tracker.TU_MOVIL') }}"
          en_casa: "{{ 'true' if states('device_tracker.TU_MOVIL') == 'home' else 'false' }}"
          lat: "{{ state_attr('device_tracker.TU_MOVIL', 'latitude') | default('null', true) }}"
          lon: "{{ state_attr('device_tracker.TU_MOVIL', 'longitude') | default('null', true) }}"
```

Sin coordenadas (un `device_tracker` por presencia en la red, por ejemplo) también
funciona: `lat`/`lon` viajan como `null` y se sigue registrando la zona y la serie
diaria, pero el clima y la hora de salida se quedan en sus valores por defecto.

## 7. Resumen diario por correo (opcional)

Cada mañana el backend puede mandarte a tu propio buzón los datos del día —agenda,
clases, entregas próximas, clima, métricas del Watch y estado del entrenamiento— **en
crudo, sin interpretarlos**. Está pensado para que lo recoja de ahí una rutina que ya
lea tu correo y componga tu resumen diario: quien redacta es esa rutina, no el backend.
Por eso no hay ninguna llamada a un LLM aquí, ni coste asociado.

El envío es por SMTP con la librería estándar de Python: sin dependencias nuevas y sin
darse de alta en ningún servicio de envío.

**1. Configura el correo** (`fly secrets set`):

```bash
fly secrets set \
  BRIEF_TO=tu@correo.com \
  SMTP_HOST=smtp.gmail.com SMTP_PORT=587 \
  SMTP_USER=tu@gmail.com \
  SMTP_PASSWORD="tu-contraseña-de-aplicacion" \
  BRIEF_TOKEN="$(openssl rand -hex 24)" \
  ENTREGAS_MARKER=📚
```

Con Gmail y 2FA activado hace falta una [contraseña de
aplicación](https://myaccount.google.com/apppasswords) — la normal no sirve.
`ENTREGAS_MARKER` debe coincidir con `VITE_ENTREGAS_MARKER` del frontend: el backend no
ve las variables `VITE_*`.

**2. Configura el disparador** en tu fork de GitHub:

- **Settings → Secrets and variables → Actions → Variables**: `BACKEND_URL` =
  `https://TU-BACKEND.fly.dev`
- **Secrets**: `BRIEF_TOKEN`, el mismo valor que pusiste en Fly

**3. Decide cuándo sale el correo.** Por defecto no sale a una hora fija, sino cuando
te despiertas: quien avisa es `POST /despertar` (con `BRIEF_TOKEN`), que puedes llamar
desde una automatización de Atajos de iOS, desde Home Assistant o desde donde quieras.
Si nadie avisa, sale igual a `BRIEF_HORA_TOPE` (10:00 por defecto) — de eso se encarga
el sondeo de HA a `POST /ha/brief-tick`, que basta con llamar cada pocos minutos.
Manda **un solo correo al día** pase lo que pase: la tabla `brief_envios` lo garantiza,
así que puedes enchufar tantos disparadores como quieras sin coordinarlos.

Si prefieres la hora fija de siempre, no configures ninguna señal: el workflow de
Actions sigue disparando por su cuenta. Su cron va en **UTC** y no entiende de zonas
horarias, así que hay que retocarlo en los cambios de hora (`0 9 * * *` son las 11:00
en Madrid en verano y las 10:00 en invierno). Ten en cuenta que los cron de Actions se
retrasan cuando GitHub está cargado, a veces 10-15 min: por eso aquí es la red de
seguridad y no el disparador.

**4. Pruébalo sin esperar a mañana**: Actions → *Resumen diario por correo* → *Run
workflow*, o `POST /brief/send?forzar=1` con tu `BRIEF_TOKEN`, que se salta la
comprobación de "ya se envió hoy". Para ver qué se enviaría sin mandar nada, `GET /brief` con tu JWT devuelve
los mismos datos en JSON.

## 8. Checklist de verificación

- [ ] `python backend/check_config.py` sin errores bloqueantes
- [ ] `https://TU-BACKEND.fly.dev/` responde `{"status": "Life Assistant API running"}`
- [ ] Login en el dashboard con tu contraseña
- [ ] `/auth/login` completado una vez → los eventos de Outlook aparecen en el timeline
- [ ] «¿A qué hora salir?» calcula ruta (Maps configurado)
- [ ] Grabar una idea por voz la transcribe y guarda (OpenAI configurado)
- [ ] (Opcional) Llega una métrica de salud tras un export del Watch
- [ ] (Opcional) Los sensores `la_*` de HA se actualizan
- [ ] (Opcional) Ajustes → Estado del sistema muestra la presencia como vigente
- [ ] (Opcional) *Run workflow* del resumen diario deja el correo en tu buzón

## Referencia rápida de variables

Backend (`backend/.env.example` documenta cada una): `SECRET_KEY`*,
`DASHBOARD_PASSWORD`*, `SUPABASE_URL`, `SUPABASE_KEY`, `CLIENT_ID`, `TENANT_ID`,
`CLIENT_SECRET`, `REDIRECT_URI`, `GOOGLE_MAPS_API_KEY`, `OPENAI_API_KEY`,
`HA_POLL_TOKEN`, `HEALTH_INGEST_TOKEN`, `AGENT_TOKEN`, `TIMEZONE`, `HOME_ADDRESS`,
`CLASSES_CALENDAR`, `WEATHER_LAT`, `WEATHER_LON`, `CORS_ORIGINS`, `HTTP_TIMEOUT`,
`TRUST_FORWARDED_FOR`, `ALUD_ALLOWED_HOSTS`, `MAX_AUDIO_BYTES`, `MAX_INGEST_BYTES`,
`AUDIO_MAX_REQUESTS`, `AUDIO_WINDOW_SECONDS`, `JARVIS_MODEL`, `JARVIS_MAX_VUELTAS`,
`JARVIS_MAX_HISTORIAL`, `JARVIS_MAX_MENSAJE`, `JARVIS_MAX_TOKENS`, `JARVIS_MAX_REQUESTS`,
`JARVIS_WINDOW_SECONDS`, `PC_AGENT_ID`, `BRIEF_TOKEN`, `BRIEF_TO`, `BRIEF_FROM`,
`SMTP_HOST`, `SMTP_PORT`, `SMTP_USER`, `SMTP_PASSWORD`, `ENTREGAS_MARKER`,
`BRIEF_DIAS_ENTREGAS`, `BRIEF_DESPERTAR_DESDE`, `BRIEF_DESPERTAR_HASTA`,
`BRIEF_HORA_TOPE`,
`BRIEF_DISPARA_SUENO`, `PRESENCE_TTL_MINUTES`, `PRESENCE_MAX_GAP_HOURS`.
(* = obligatoria para arrancar.)

Frontend: `VITE_API_URL`, `VITE_HA_URL`, `VITE_HA_DASHBOARD_PATH`,
`VITE_ENTREGAS_MARKER`, `VITE_AGENT_ID`.
