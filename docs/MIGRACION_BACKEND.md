<!-- Parte de la guía del repositorio. El índice y las reglas que aplican
     SIEMPRE están en CLAUDE.md, en la raíz. -->

## Mudanza del backend: de Fly.io al Home Assistant Green

**Estado (2026-09-06): el backend YA CORRE en el Green.** El add-on está
instalado, arrancado y verificado con `scripts/verificar_backend.py` contra la IP
local: responde, CORS, login y auth de servicio, las cuatro en verde. **Fly sigue
en producción** y no se ha cambiado ningún apuntador todavía.

**Y ya está publicado en internet**: `https://api.lifeassistantbackend.bid`, por
Cloudflare Tunnel, sin abrir un solo puerto del router. Verificado también desde
fuera, las cuatro comprobaciones en verde.

Lo que falta: **los apuntadores** (paso 6) y apagar Fly (paso 7).

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

**TODO valor va entre comillas simples, no solo los multilínea.** El fichero se
lee con `source`, así que un valor con espacios sin comillas hace que bash intente
ejecutar la segunda palabra como un comando. La primera versión solo entrecomilló
`ENABLE_BANKING_PRIVATE_KEY` (multilínea) y el add-on murió en el arranque con
`line 87: Astigar: command not found` — la segunda palabra de `HOME_ADDRESS`. Se
generan así:

```python
def citar(v):
    # Dentro de comillas simples bash no interpreta NADA: ni espacios, ni $, ni
    # saltos de línea. Solo hay que escapar la propia comilla simple.
    return "'" + v.replace("'", "'\''") + "'"
```

Y se valida **antes** de subirlo: `bash -n <fichero>`, y un `source` de prueba
comprobando que las variables cargan enteras. `run.sh` lo lee con `.` en vez de
parsearlo línea a línea por la misma razón: para que la PEM sobreviva.

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

Los pasos 1 a 3 **ya están hechos** (2026-09-06). Se dejan escritos porque
ninguno salió a la primera y las trampas son reutilizables.

**1. Copiar el add-on al Green.** La carpeta `addon/life-assistant/` va a
`/addons/life-assistant`. Dos cosas que cuestan un rato descubrir:

- **`/addons` pertenece a `root` y el add-on de SSH entra como `hassio`.** Sin
  `sudo` la escritura falla con `Permission denied`, y si el script no comprueba
  el código de salida se queda tan tranquilo diciendo «copiado» sobre ficheros
  que no existen. Pasó exactamente eso. Usa `sudo tee` y **verifica con
  `sha256sum` a los dos lados**.
- **El add-on de SSH no tiene subsistema SFTP** (`paramiko.open_sftp()` falla con
  `Channel closed`). Se escribe con `exec_command("sudo tee <ruta>")` +
  `sendall`, que es el patrón que ya documenta `HOMEASSISTANT.md`.

**2. Poner el fichero de entorno.** `~/.life-assistant/backend.env.produccion` va
a `/config/life_assistant.env`, con `chmod 600` y `chown root:root` (el add-on
corre como root; nadie más necesita leerlo). Es la ruta que espera `config.yaml`.
Queda en texto plano en el Green, como `secrets.yaml` de HA — es tu aparato, en
tu casa, y no sale de ahí. **Léete antes la sección de los secretos**: las
comillas simples no son un detalle de estilo.

**3. Instalar.** Y aquí la trampa mayor:

- **Home Assistant renombró los add-ons a «apps» en 2026.2.** El comando para que
  el Supervisor detecte un add-on local **no** es `ha addons reload` (que existe,
  no falla y no hace lo que crees) sino **`ha store reload`**.
- **`ha apps` lista los INSTALADOS, no los disponibles.** Para ver si el
  Supervisor ha detectado el add-on local hay que mirar **`ha store apps`**. Se
  perdió un buen rato creyendo que el `config.yaml` estaba mal cuando ya estaba
  bien: solo se estaba mirando la lista equivocada.
- El slug queda como `local_life-assistant`. Instalar con
  `ha apps install local_life-assistant`; la construcción tardó **2 minutos** en
  el Green.
- Si algo falla, `ha apps logs local_life-assistant` lo dice: `run.sh` comprueba a
  mano `SECRET_KEY` y `DASHBOARD_PASSWORD` y aborta con un mensaje legible en vez
  de dejar que el backend reviente al importar.

**4. Exponerlo a internet.** Hace falta porque el frontend de Vercel, el Atajo de
iOS, Health Auto Export y los workflows de GitHub llaman desde fuera.

**Tailscale NO sirve para esto, aunque lo parezca.** El add-on ofrece dos cosas y
ninguna es lo que se necesita:

- `share_homeassistant: funnel` publica **la interfaz de Home Assistant** en
  internet. No es nuestro backend, y activarlo expone la casa entera.
- La lista `services` son *Tailscale Services*, que por debajo ejecutan
  `tailscale serve`, **no `funnel`**: publican dentro del tailnet, no en
  internet. Además exigen que el nodo esté **etiquetado** (`service hosts must be
  tagged nodes`), lo que obliga a definir `tagOwners` en la ACL y
  `advertise_tags` en el add-on, y a **declarar el servicio en la consola antes
  de anunciarlo** (el orden es Define → Advertise → Approve; al revés no aparece
  nada). Se llegó hasta el final de ese camino y lo que da es acceso por VPN, que
  no vale si quieres que la web sea pública.

Si lo que quieres es acceso por tailnet, sirve y es más seguro. Si quieres URL
pública, la vía es **Cloudflare Tunnel** (add-on `9074a9fa_cloudflared`, ya
instalado): no abre ningún puerto del router porque el túnel sale de dentro
hacia fuera. Necesita **un dominio propio en Cloudflare** — hay TLDs desde 1-3
€/año, y comprarlo en Cloudflare Registrar ahorra el trámite de los nameservers.
El backend se publica con `additional_hosts`. **El destino NO es
`http://127.0.0.1:8080`**, y esto cuesta un 502 descubrirlo: a diferencia del
add-on de Tailscale, cloudflared **no corre en la red del host** (su log delata
una IP `172.30.x`), así que su `localhost` es él mismo. El destino correcto es el
hostname interno del add-on:

```yaml
additional_hosts:
  - hostname: api.lifeassistantbackend.bid
    service: http://local-life-assistant:8080
```

Valen también `http://172.30.32.1:8080` (la pasarela) y la IP LAN del Green, pero
el hostname es el único que sobrevive a un cambio de DHCP.

**`external_hostname` se deja vacío a propósito**: esa opción publicaría la
interfaz de Home Assistant en internet, y aquí solo queremos el backend.

Dos cosas más del montaje real:

- **Los «prechecks» de cloudflared avisan de fallos y el túnel funciona igual.**
  Dicen `SUMMARY: Environment has critical failures` porque `region2` está
  bloqueada (cosa de la operadora), pero `region1` pasa y las cuatro conexiones
  se registran. No persigas ese aviso.
- **Cloudflare responde 403 al User-Agent `Python-urllib`**, que está en sus
  reglas de bots. `scripts/verificar_backend.py` daba por caído un backend que
  respondía 200 a curl, a `requests` y a un navegador; ahora manda un User-Agent
  propio. Si algún cliente nuevo empieza a recibir 403 sin explicación, mira su
  User-Agent antes que nada.

Descartadas por el camino: **ngrok** (regala un dominio estático permanente, pero
desde febrero de 2026 corta las sesiones **a las 2 horas**), **DuckDNS** (gratis y
estable, pero obliga a abrir el 443 del router y el Green lleva también la casa) y
**`.eu.org`** (gratis, pero la aprobación es manual y tarda semanas).

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
| GitHub | `revision-aviso.yml` y los workflows que apunten al backend, **y la variable de Actions `BACKEND_URL`**, que no está en ningún fichero y por eso se olvidó |
| Azure | **`REDIRECT_URI` está registrado en el App Registration**: añade el nuevo antes de probar el login de Microsoft, o el OAuth falla con un error de redirect que no dice nada útil |
| Código | `src/components/Dashboard.jsx:31` y `agent/agent.py:43`, que llevan la URL de Fly por defecto |
| Docs | `CLAUDE.md`, `docs/DESPLIEGUE.md`, `docs/SALUD.md`, `docs/AVISAME.md`, `agent/README.md`, `agent/PUESTA_A_PUNTO.md`, `backend/corregir_energia_kj.py` |

**7. Apagar Fly, y no antes.** Deja pasar unos días y mira `fly logs`: si no
llega tráfico, no queda nada apuntando ahí. Es mejor detector de olvidos que
releer la tabla. Cuando esté mudo: `fly apps destroy <app>` y quita el método de
pago.

`backend/fly.toml` y `.github/workflows/deploy-backend.yml` **ya están retirados**
(2026-09-07), junto con el botón que disparaba aquel workflow: ver
`docs/AVERIAS.md`, «El último paso lo das tú». Queda destruir la app y quitar la
tarjeta, que son los dos pasos que solo se pueden dar desde la web de Fly.

**Y un apuntador que la tabla de arriba no cazó**, porque no está en ningún
fichero del repositorio: la **variable de Actions `BACKEND_URL`** seguía apuntando
a la URL vieja de Fly. La usan `ci-averiado.yml`,
`revision-aviso.yml` y `pr-listo.yml`, así que **todo el canal de averías y el
aviso de la revisión nocturna llevaban desde la mudanza hablándole a la máquina
equivocada**. Corregida el 2026-09-07. La moraleja para la próxima mudanza: los
apuntadores no viven solo en ficheros — hay variables y secrets en GitHub, en
Vercel y en claude.ai que ningún `grep` encuentra.

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
- **`Protection mode` del add-on de SSH.** Está activado, y eso bloquea el acceso
  a Docker desde la sesión SSH (`docker exec` responde con un aviso, no con un
  error claro). Es una buena defensa y no hay que desactivarla a la ligera: casi
  todo se puede hacer con el CLI `ha` y la API del Supervisor, que sí funcionan.
- **La API del Supervisor REEMPLAZA las opciones de un add-on, no las fusiona.**
  Mandar solo el campo que quieres cambiar falla con `Missing option '...'`. Hay
  que leer las opciones actuales, modificar la clave y devolver el objeto entero.
- **Publicar el puerto en el host no es opcional.** `ports: 8080/tcp: 8080` en
  `config.yaml` es lo que permite que Cloudflared (y Tailscale) lleguen al backend
  por `http://127.0.0.1:8080`: sus validaciones solo aceptan `127.0.0.1`, no la IP
  de la red local ni el nombre del contenedor.
- **El sondeo, que ahora es local.** Si un día vuelve a apuntar a la URL pública
  por error, el tráfico sale a internet y vuelve, y todo seguirá funcionando —
  peor y sin avisar. Al tocar los sensores, mira que la URL sea la IP local.

## Reconstruir y comprobar que ha servido

`Reconstruir` en la página del add-on clona `main` y levanta la imagen de nuevo. Es el
único paso del despliegue del backend, y **no da ninguna señal de haber traído código
nuevo**: termina igual tanto si lo ha traído como si no.

Por eso, después de reconstruir:

```bash
curl -s https://api.lifeassistantbackend.bid/
# {"status":"Life Assistant API running","version":"<sha del commit clonado>"}
```

Ese `version` sale de `/app/VERSION`, que se escribe al construir con el `rev-parse` del
clon. Si no coincide con el `main` de GitHub, el add-on está corriendo código viejo.
Durante meses fue así sin que se notara: ver «Reconstruir no reconstruía» en
`docs/BUGS_HISTORICOS.md`.

### Los ficheros del add-on NO salen de git

`Dockerfile`, `config.yaml` y `run.sh` están en `/addons/life-assistant/` del Green
porque se copiaron a mano por Samba. De git sale solo el contenido de `backend/`, que
es lo que clona el `RUN git clone`. **Cambiar `addon/` en el repositorio y mergear a
`main` no cambia nada en el Green**: hay que volver a poner el fichero en el aparato.

Comprobar si alguno se ha quedado atrás:

```bash
md5sum /addons/life-assistant/{Dockerfile,config.yaml,run.sh}   # en el Green
```

y comparar con los del repo. Para subir uno por SSH — `/addons` es de root, y el
add-on de SSH no tiene subsistema SFTP, así que ni `scp` ni `sftp` valen:

```bash
cat > /tmp/Dockerfile.nuevo        # el contenido va por el stdin del comando
sudo cp /addons/life-assistant/Dockerfile /addons/life-assistant/Dockerfile.bak-<fecha>
sudo cp /tmp/Dockerfile.nuevo /addons/life-assistant/Dockerfile
```

Después, *Reconstruir*. Si has tocado el `Dockerfile`, esa reconstrucción tarda varios
minutos: la caché queda invalidada y vuelve a instalar las dependencias enteras.
