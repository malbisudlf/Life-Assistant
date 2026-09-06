<!-- Parte de la guía del repositorio. El índice y las reglas que aplican
     SIEMPRE están en CLAUDE.md, en la raíz. -->

## Mudanza del backend: de Fly.io al Home Assistant Green

**Estado: preparada, sin ejecutar.** El add-on está escrito (`addon/life-assistant/`)
y Fly sigue en producción hasta el último paso.

### Por qué nos vamos de Fly

En septiembre de 2026 llegó el primer cobro visible de Fly, 6 €, y al mirarlo
resultó que llevaba meses cobrando sin que nadie lo notara.

- **La máquina no escala a cero, y nunca lo hizo.** El backend nació el 06/05.
  El 13/05 entró el primer sensor REST de Home Assistant (`wol-pending`, cada
  30 s) y desde ese día no ha dormido un segundo. Hoy son seis sensores
  solapados: ~13 peticiones/minuto, ~18.700 al día. `min_machines_running = 0`
  y `auto_stop_machines = 'stop'` están puestos y son decorativos.
- **`CLAUDE.md` afirmaba lo contrario** desde mayo. Esa frase es la razón de que
  nadie mirara la factura en cuatro meses. Ya está corregida.
- **1 GB para usar 200 MB.** Medido dentro de la máquina: `MemTotal` 985 MB, uso
  real ~196 MB.
- **Fly ya no tiene tramo gratuito** (lo retiró en octubre de 2024) y esta cuenta
  es de mayo de 2026, así que no es legacy. shared-cpu-1x con 1 GB corriendo
  continuamente son $5.92/mes: exactamente la factura.

### Por qué al Green, y no a otra nube

Se intentó primero **Koyeb**, y duró un día: entre que se preparó la migración y
que se fue a crear la cuenta, **cerró su tramo gratuito a las altas nuevas**
(tras la compra por Mistral, solo admiten Pro o superior). El panel aparece vacío
para cuentas nuevas. Es el mismo movimiento que ya había hecho Fly.

De ahí la conclusión que ordena todo lo demás: **un tramo gratuito de PaaS para
un servicio encendido 24/7 es estructuralmente inestable**. El hobbyista
siempre-encendido es justo lo que estas plataformas están recortando, y este
proyecto ya ha perdido dos en cuatro meses.

Lo medido en el Green el 2026-09-06, por SSH:

| | Green ahora | El backend necesita |
|---|---|---|
| RAM | **2.070 MB disponibles** (de 3.920, 1.850 en uso) | 196 MB |
| Disco | **18 GB libres** de 27,8 (32 % usado) | ~0,7 GB de imagen |
| Carga | **0.05 / 0.09 / 0.09** sobre 4 núcleos | nada: casi todo es espera de red |
| Arquitectura | `aarch64` | `python:3.11-slim` publica arm64 |

Y las tres dependencias compiladas (`cryptography`, `bcrypt`, `pydantic-core`)
publican wheels **manylinux aarch64 para cp311**, así que `pip` baja binarios y
no hay nada que compilar en el RK3566. Se comprobó en PyPI antes de escribir el
add-on.

Además de ser gratis y de nadie: **el sondeo de HA deja de cruzar internet**.
Los seis sensores pasan a hablar con `localhost` por la red local, así que el
problema que originó todo esto no se mitiga, desaparece.

Descartadas: **Render** (750 h/mes por *workspace*, y 24/7 en un mes de 31 días
son 744: margen del 0,8 %, y al agotarlas suspende el servicio hasta el mes
siguiente), **Oracle Always Free** (reclama instancias con CPU p95 < 20 % en 7
días; este backend vive al ~1 %) y **Google Cloud Run** (tramo gratuito solo en
EEUU, y al escalar a cero se pierde el estado en memoria, que aquí es funcional).

---

### Los secretos: léelo antes de tocar nada

**Fly no deja leer el valor de un secreto** desde su almacén: ni `fly secrets
list` (da nombre y digest) ni la API GraphQL (el tipo `Secret` expone
`createdAt`, `digest`, `id`, `name`, `user` — no hay `value`). Se guardan
cifrados y solo se descifran al inyectarlos en la VM.

Y los `.env` locales **no** son una copia completa: `backend/.env` tiene 33
variables y en producción hay 54. Faltaban 29, entre ellas `AGENT_TOKEN`,
`SMTP_PASSWORD`, `INDEXA_TOKEN`, `HA_TOKEN`, `DEPLOY_GITHUB_TOKEN` y
`ENABLE_BANKING_PRIVATE_KEY`. La `DASHBOARD_PASSWORD` del `.env` local tampoco
es la desplegada. Migrar copiando ese fichero habría arrancado un backend sin
correo, sin cartera, sin agente y sin casa.

Sí se pueden leer de un sitio: **el proceso vivo**, que es donde están
descifradas.

```bash
fly ssh console -a <app> -C "python -c \"import os,json;print(json.dumps(dict(os.environ)))\""
```

El volcado está en **`~/.life-assistant/backend.env.produccion`** (permisos 600),
**fuera del repositorio a propósito**, porque el repo es público. **Es la única
copia completa que existe.** Esa vía solo funciona mientras la máquina siga
viva: el día que hagas `fly apps destroy`, el almacén se va con la app y no hay
proceso al que entrar. Por eso apagar Fly es el último paso y no el primero.

`ENABLE_BANKING_PRIVATE_KEY` es una clave PEM **multilínea** y va entrecomillada
en el fichero. `run.sh` lo lee con `.` en vez de parsearlo línea a línea
justamente para que sobreviva entera.

`.gitignore` cubre `backend/.env.*` con excepción para `.env.example`: antes, un
`backend/.env.produccion` **no** estaba cubierto y habría entrado en un repo
público con los 54 secretos dentro.

**21 variables del `.env.example` no están en producción** y funcionan con el
valor por defecto del código (`TIMEZONE`, `CORS_ORIGINS`, `WEATHER_LAT/LON`,
`ALUD_ALLOWED_HOSTS`…). No hay que inventarlas. De ahí salió además que
`LLAMADAS`, `BACKEND_URL` y las cuatro `TWILIO_*` tampoco están: **el canal de
teléfono de `docs/LLAMADAS.md` no está activo en producción hoy.**

---

### Los pasos

Se puede hacer sin cortar el servicio: los dos backends conviven hasta el 6.

**1. Copiar el add-on al Green.** La carpeta `addon/life-assistant/` de este
repositorio va a `/addons/life-assistant` del Green, por el Samba que ya está
instalado (`\\<ip-del-green>\addons`). Está vacía hoy: no hay ningún otro add-on
local que romper.

**2. Poner el fichero de entorno.** Copia
`~/.life-assistant/backend.env.produccion` a `/config/life_assistant.env` (por
Samba, `\\<ip-del-green>\config`). Es la ruta que espera `config.yaml`; si la
cambias, cámbiala también en las opciones del add-on. Queda en texto plano en el
Green, como `secrets.yaml` de HA — es tu aparato, en tu casa, y no sale de ahí.

**3. Instalar.** Ajustes → Add-ons → Tienda → ⋮ → *Buscar actualizaciones*. El
add-on aparece bajo «Local add-ons». Instálalo (la primera construcción tarda
varios minutos: clona el repo e instala las dependencias) y arráncalo. Si algo
falla, el log del add-on lo dice: `run.sh` comprueba a mano que existan
`SECRET_KEY` y `DASHBOARD_PASSWORD` y aborta con un mensaje legible en vez de
dejar que el backend reviente al importar.

**4. Exponerlo a internet.** Hace falta porque el frontend de Vercel, el Atajo
de iOS, Health Auto Export y los workflows de GitHub llaman desde fuera. Ya
tienes el add-on de **Tailscale** instalado, así que la vía corta es **Tailscale
Funnel** sobre el puerto 8080; da una URL `https://<host>.<tailnet>.ts.net`
válida y con TLS. Dos avisos: hay que **habilitar Funnel en la ACL del tailnet**
desde la consola de Tailscale (no basta con el add-on), y Funnel solo publica en
los puertos 443, 8443 y 10000, así que el mapeo va de uno de esos al 8080. Si no
quieres depender de Tailscale, el add-on de **Cloudflare Tunnel** hace lo mismo
con un dominio propio.

**5. Verificar, con Fly todavía en marcha:**

```bash
set -a && . ~/.life-assistant/backend.env.produccion && set +a
python scripts/verificar_backend.py https://<host>.<tailnet>.ts.net
```

Comprueba que responde, el preflight de CORS, el login con la contraseña real y
que los endpoints de servicio dan 200 con token y 403 sin él. Lo que no puede
probar sin credenciales lo marca **SALTADA**, nunca OK. No sigas hasta que salga
limpio.

**6. Cambiar los apuntadores.** Es donde se tuerce una migración: basta olvidar
uno. Están en 14 ficheros del repo, y **tres los oculta `.gitignore`**, que es
justo por lo que se olvidan.

| Dónde | Qué |
|---|---|
| Vercel | `VITE_API_URL` |
| Home Assistant | los 6 sensores REST y sus `rest_command`. **Aquí van a la IP local del Green, no a la URL pública**: es el punto de todo esto |
| **`agent/.env`** | `LA_API_BASE` — **ignorado por git**; el `.env.example` es solo la plantilla y cambiarlo no cambia nada en tu PC |
| **`backend/.env`** | por coherencia — **ignorado por git** |
| **`PROJECT_STATE.md`** | notas — **ignorado por git** |
| iPhone | el Atajo de iOS y Health Auto Export |
| claude.ai | las rutinas que llaman al backend |
| GitHub | `revision-aviso.yml` y los workflows que apunten al backend |
| Azure | **`REDIRECT_URI` está registrado en el App Registration**: añade el nuevo antes de probar el login de Microsoft, o el OAuth falla con un error de redirect que no dice nada útil |
| Código | `src/components/Dashboard.jsx:31` y `agent/agent.py:43`, que llevan la URL de Fly por defecto |
| Docs | `CLAUDE.md`, `docs/DESPLIEGUE.md`, `docs/SALUD.md`, `docs/AVISAME.md`, `agent/README.md`, `agent/PUESTA_A_PUNTO.md`, `backend/corregir_energia_kj.py` |

**7. Apagar Fly, y no antes.** Deja pasar unos días y mira `fly logs`: si no
llega tráfico, no queda nada apuntando ahí. Es mejor detector de olvidos que
releer la tabla. Cuando esté mudo: `fly apps destroy <app>` y quita el método de
pago. Después, retirar `backend/fly.toml` y
`.github/workflows/deploy-backend.yml`.

### Cómo se despliega a partir de ahora

No hay workflow: **el add-on se reconstruye desde la interfaz de HA**. El
`Dockerfile` clona el repositorio público en cada construcción, así que
desplegar una versión nueva es *Reconstruir* en la página del add-on. Sigue
cumpliéndose la regla de siempre: **el backend no se despliega solo al hacer
push**, y quien lo despliega es una persona.

Ventaja lateral: no hay que volver a pasar código por Samba nunca más, y la
copia del Green no se puede quedar atrás en silencio — el fallo que sí tiene el
prompt de la rutina del briefing.

### Qué vigilar

- **La eMMC.** `disk_life_time: 10` — está al 10 % de su vida. Es memoria flash
  no reemplazable y sin ranura M.2: el día que se gaste, se gasta el aparato. El
  backend no escribe datos (todo va a Supabase), pero sus **logs sí**. Si algún
  día se pone verboso, baja `nivel_log` en las opciones del add-on.
- **El acoplamiento.** Hasta ahora, si el backend caía, la casa seguía. Ahora
  comparten aparato: un backend que se descontrole se lleva por delante la
  domótica. Los 2 GB libres dan mucho margen, pero si aparece algo que consuma
  memoria de verdad, la primera señal a mirar es HA yendo lento.
- **La luz y la línea de casa.** Si se van, se va el backend. Antes solo se iba
  media función; ahora se va entera. A cambio, HA ya dependía de eso.
- **El sondeo, que ahora es local.** Si un día vuelve a apuntar a la URL pública
  por error, el tráfico sale a internet y vuelve, y todo seguirá funcionando —
  peor y sin avisar. Al tocar los sensores, mira que la URL sea la IP local.
