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
   agentes, tokens OAuth, ideas, entrenamiento y salud, con RLS activado.
3. Apunta de **Settings → API**: la `URL` del proyecto y la **`service_role` key**
   (no la `anon`; la service key solo vivirá en el backend).
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
  TIMEZONE=Europe/Madrid \
  HOME_ADDRESS="Tu dirección, Ciudad" \
  CLASSES_CALENDAR=clases \
  WEATHER_LAT=40.4168 WEATHER_LON=-3.7038 \
  CORS_ORIGINS="http://localhost:5173,https://TU-APP.vercel.app"
fly deploy
```

Notas:
- `DASHBOARD_PASSWORD` **numérica**: el input del login es un teclado numérico.
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

## 7. Checklist de verificación

- [ ] `python backend/check_config.py` sin errores bloqueantes
- [ ] `https://TU-BACKEND.fly.dev/` responde `{"status": "Life Assistant API running"}`
- [ ] Login en el dashboard con tu contraseña
- [ ] `/auth/login` completado una vez → los eventos de Outlook aparecen en el timeline
- [ ] «¿A qué hora salir?» calcula ruta (Maps configurado)
- [ ] Grabar una idea por voz la transcribe y guarda (OpenAI configurado)
- [ ] (Opcional) Llega una métrica de salud tras un export del Watch
- [ ] (Opcional) Los sensores `la_*` de HA se actualizan

## Referencia rápida de variables

Backend (`backend/.env.example` documenta cada una): `SECRET_KEY`*,
`DASHBOARD_PASSWORD`*, `SUPABASE_URL`, `SUPABASE_KEY`, `CLIENT_ID`, `TENANT_ID`,
`CLIENT_SECRET`, `REDIRECT_URI`, `GOOGLE_MAPS_API_KEY`, `OPENAI_API_KEY`,
`HA_POLL_TOKEN`, `HEALTH_INGEST_TOKEN`, `TIMEZONE`, `HOME_ADDRESS`,
`CLASSES_CALENDAR`, `WEATHER_LAT`, `WEATHER_LON`, `CORS_ORIGINS`.
(* = obligatoria para arrancar.)

Frontend: `VITE_API_URL`, `VITE_HA_URL`, `VITE_HA_DASHBOARD_PATH`,
`VITE_ENTREGAS_MARKER`.
