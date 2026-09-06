<!-- Parte de la guía del repositorio. El índice y las reglas que aplican
     SIEMPRE están en CLAUDE.md, en la raíz. -->

## Mudanza del backend: de Fly.io a Koyeb

**Estado: preparada, sin ejecutar.** Todo lo que no necesita la cuenta de Koyeb
está hecho y mergeado; lo que queda son los pasos manuales de abajo. Fly sigue
en producción hasta el paso 7.

### Por qué nos vamos

En septiembre de 2026 llegó el primer cobro visible de Fly, 6 €, y al mirarlo
resultó que llevaba meses cobrando sin que nadie lo notara. El diagnóstico:

- **La máquina no escala a cero, y nunca lo hizo.** El backend nació el 06/05.
  El 13/05 entró el primer sensor REST de Home Assistant (`wol-pending`, cada
  30 s) y desde ese día no ha dormido un solo segundo. Escaló a cero durante la
  primera semana de su vida y ninguna más. Hoy son seis sensores solapados
  (~13 peticiones/minuto, ~18.700 al día): `min_machines_running = 0` y
  `auto_stop_machines = 'stop'` están puestos y son decorativos.
- **`CLAUDE.md` afirmaba lo contrario** («escala a cero cuando no hay tráfico, de
  ahí el arranque en frío de 10-15s»). Esa frase es la razón de que nadie mirara
  la factura durante cuatro meses. Ya está corregida.
- **1 GB para usar 200 MB.** Medido dentro de la máquina: `MemTotal` 985 MB, uso
  real ~196 MB. `fly.toml` pide `memory = '1gb'` desde el commit inicial.
- **Fly ya no tiene tramo gratuito.** Retiró los planes Hobby/Launch/Scale en
  octubre de 2024; las cuentas legacy conservan su allowance, pero esta es de
  mayo de 2026 y no lo es. shared-cpu-1x con 1 GB corriendo continuamente son
  $5.92/mes, que es exactamente la factura.

No hay nada que arreglar en el código: es el precio de lista de lo que estamos
usando. Y bajar la RAM solo lo abarataría, no lo haría gratis.

### Por qué Koyeb

Lo que hunde a Fly es lo que aquí sale gratis. El [free tier de
Koyeb](https://www.koyeb.com/docs/faqs/pricing) da una Free Instance de **512 MB
de RAM, 0.1 vCPU y 2 GB de SSD**, y **escala a cero tras 1 hora sin tráfico**,
sin poder desactivarlo. Como HA sondea cada pocos segundos, nunca va a haber una
hora de silencio: la instancia se queda viva permanentemente y no se factura,
porque el free tier no cobra tiempo encendido. **El sondeo pasa de ser el
problema a ser lo que sostiene el servicio.**

Encaja en lo demás: 512 MB > los 196 MB medidos; el `Dockerfile` no tenía nada
propio de Fly; es europeo (París, de Mistral AI desde febrero de 2026), así que
la latencia con HA es buena y los datos de salud se quedan en la UE; y —esto
descarta media lista de alternativas— **el estado en memoria sigue funcionando**
(`_wol_pending`, `_rate_buckets`, la caché de Indexa) porque la instancia no se
recicla entre peticiones.

Descartadas, y por qué:

- **Oracle Cloud Always Free** — reclama las instancias cuyo percentil 95 de CPU
  baje del 20 % en 7 días. Este backend vive al ~1 %: es el perfil exacto que
  desalojan, y te enterarías el día que la casa deje de responder. Además el
  15/06/2026 recortaron el ARM a la mitad y apagaron las instancias de quien no
  reajustó a mano. Y es una VM: SO, TLS y uptime a tu cargo. Queda como plan B.
- **Google Cloud Run** — los números salen, pero el tramo gratuito es solo en
  regiones de EEUU (latencia, y datos de salud fuera de la UE) y al escalar a
  cero se pierde el estado en memoria, que aquí es funcional.
- **Render** — 750 h/mes y un servicio continuo gasta 720. Cabe por un 4 %:
  demasiado justo para algo que no quieres volver a mirar.

**Lo que no hay que olvidar:** un tramo gratuito puede morir, y este proyecto ya
ha perdido uno. La protección no es acertar con la plataforma, es que la
siguiente mudanza sea barata. Por eso el `Dockerfile` es portable y todo lo
demás son variables de entorno.

---

### Los secretos: léelo antes de tocar nada

**Fly no deja leer el valor de un secreto.** `fly secrets list` da los nombres y
un digest, nunca el contenido. Y los `.env` locales **no** son una copia
completa: `backend/.env` tiene 33 variables y en producción hay 54. Faltaban 29,
entre ellas `AGENT_TOKEN`, `SMTP_PASSWORD`, `INDEXA_TOKEN`, `HA_TOKEN`,
`DEPLOY_GITHUB_TOKEN` y `ENABLE_BANKING_PRIVATE_KEY`. Migrar copiando el `.env`
local habría arrancado un backend sin correo, sin cartera, sin agente y sin
casa.

Se recuperaron del único sitio donde estaban: el proceso vivo.

```bash
fly ssh console -a <app> -C "python -c \"import os,json;print(json.dumps(dict(os.environ)))\""
```

El volcado está en **`~/.life-assistant/backend.env.produccion`** (permisos 600),
**fuera del repositorio a propósito**, porque el repo es público. Es la única
copia completa que existe: si se pierde y Fly ya está apagado, esos 54 valores
no se recuperan de ningún sitio.

`ENABLE_BANKING_PRIVATE_KEY` es una clave PEM **multilínea** y va entrecomillada
en el fichero. Al pegarla en el panel de Koyeb, comprueba que conserva los saltos
de línea: pegada en una sola línea, el backend arranca igual y Enable Banking
falla en la primera llamada.

`.gitignore` se blindó en esta misma tanda (`backend/.env.*` con excepción para
`.env.example`): antes, un `backend/.env.produccion` **no** estaba cubierto y
habría entrado en un repo público con los 54 secretos dentro.

**21 variables del `.env.example` no están en producción** y funcionan con el
valor por defecto del código (`TIMEZONE`, `CORS_ORIGINS`, `WEATHER_LAT/LON`,
`ALUD_ALLOWED_HOSTS`…). No hay que inventarlas. Un aviso que salió de aquí:
`LLAMADAS`, `BACKEND_URL` y las cuatro `TWILIO_*` **tampoco están**, así que el
canal de teléfono de `docs/LLAMADAS.md` no está activo en producción hoy.

---

### Los pasos

Se puede hacer sin cortar el servicio: los dos backends conviven hasta el 7.

**1. Crear el servicio en Koyeb.** Repo de GitHub, Dockerfile en `backend/`,
región de la UE (Frankfurt o París), instancia **Free**. El `Dockerfile` ya
respeta `$PORT`, que es lo que Koyeb inyecta, y cae al 8080 si no está — así
sigue valiendo para Fly y para un `docker run` a pelo.

**2. Pegar las 54 variables** desde `~/.life-assistant/backend.env.produccion`.
Cuidado con la PEM multilínea. `SECRET_KEY` y `DASHBOARD_PASSWORD` no tienen
valor por defecto: si faltan, el backend lanza `RuntimeError` al arrancar. Es
fail-fast deliberado y aquí juega a favor — te enteras en el primer despliegue.

**3. Ajustar `CORS_ORIGINS`** para incluir el dominio de Vercel. Un CORS mal
puesto **no** falla como un error de CORS en la UI: el login dice «credenciales
incorrectas». Ha costado dos depuraciones largas en este proyecto.

**4. Verificar, con Fly todavía en marcha:**

```bash
set -a && . ~/.life-assistant/backend.env.produccion && set +a
python scripts/verificar_backend.py https://<servicio>.koyeb.app
```

Comprueba que responde, el preflight de CORS, el login con contraseña real y que
los endpoints de servicio dan 200 con token y 403 sin él. Lo que no puede probar
sin credenciales se marca **SALTADA**, nunca OK. No sigas hasta que salga limpio.

**5. Cambiar los apuntadores.** Es donde se tuerce una migración: basta olvidar
uno. Están en 14 ficheros del repo, y tres de ellos **los oculta `.gitignore`**,
que es justo por lo que se olvidan:

| Dónde | Qué |
|---|---|
| Vercel | `VITE_API_URL` |
| Home Assistant | los 6 sensores REST (`configuration.yaml` y `/config/packages/life_assistant_pc.yaml`) y sus `rest_command` |
| **`agent/.env`** | `LA_API_BASE` — **ignorado por git**; el `.env.example` es solo la plantilla y cambiarlo no cambia nada en tu PC |
| **`backend/.env`** | por coherencia — **ignorado por git** |
| **`PROJECT_STATE.md`** | notas — **ignorado por git** |
| iPhone | el Atajo de iOS y Health Auto Export |
| claude.ai | las rutinas que llaman al backend |
| GitHub | `revision-aviso.yml` y los workflows que apunten al backend |
| Azure | **`REDIRECT_URI` está registrado en el App Registration**: añade el nuevo antes de probar el login de Microsoft, o el OAuth falla con un error de redirect que no dice nada útil |
| Código | `src/components/Dashboard.jsx:31` y `agent/agent.py:43`, que llevan la URL de Fly como valor por defecto |
| Docs | `CLAUDE.md`, `docs/DESPLIEGUE.md`, `docs/SALUD.md`, `docs/AVISAME.md`, `agent/README.md`, `agent/PUESTA_A_PUNTO.md`, `backend/corregir_energia_kj.py` |

Si algún día se activa el teléfono, `BACKEND_URL` alimenta los callbacks de
Twilio y el `wss://` del puente de audio: cambia también la configuración del
número en Twilio.

**6. Configurar el despliegue.** Secrets de GitHub `KOYEB_TOKEN`,
`KOYEB_SERVICIO` (`<app>/<servicio>`) y `KOYEB_URL` para
`.github/workflows/deploy-koyeb.yml`. Sigue siendo `workflow_dispatch`: **el
backend no se despliega solo al hacer push**, ni aquí ni en ningún sitio.

**7. Apagar Fly, y no antes.** Deja pasar unos días y mira `fly logs`: si no
llega tráfico, no queda nada apuntando ahí. Es el mejor detector de olvidos que
hay — mejor que releer la tabla de arriba. Cuando esté mudo:
`fly apps destroy <app>`, y borra el método de pago. Después, retirar
`backend/fly.toml` y `.github/workflows/deploy-backend.yml`.

### Qué vigilar las primeras semanas

- **0.1 vCPU es poco.** El backend casi siempre espera a APIs externas (es I/O),
  pero `construir_brief()` lanza consultas en paralelo y Whisper y Jarvis mueven
  datos. Si algo va lento, es lo primero a mirar.
- **Si HA se apaga más de una hora** (viaje, corte de luz), la instancia duerme y
  la siguiente petición paga un arranque en frío. No es un fallo.
- **Una Free Instance por organización.** No hay sitio para un entorno de
  pruebas al lado.
