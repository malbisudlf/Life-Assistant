<!-- Parte de la guía del repositorio. El índice y las reglas que aplican
     SIEMPRE están en CLAUDE.md, en la raíz. -->

## Home Assistant

**Las credenciales, el token, la IP local y la estructura de ficheros están en
`HOMEASSISTANT.md`, que está en `.gitignore`.** No los copies aquí: este fichero se
versiona en un repo público.

- Acceso por SSH con `paramiko` (Python) — `sshpass` no está disponible en Windows.
- **Escritura de ficheros**: SFTP no está disponible; hay que usar `sudo tee` por el canal
  SSH:
  ```python
  channel = client.get_transport().open_session()
  channel.exec_command("sudo tee /config/archivo.yaml > /dev/null")
  channel.sendall(contenido.encode())
  channel.shutdown_write()
  ```
- **Automatizaciones vía API**: se crean/actualizan con
  `POST /api/config/automation/config/{id}` — no hace falta tocar `automations.yaml`.
- Tras cambiar `configuration.yaml` → reiniciar HA. Tras cambiar `automations.yaml` →
  basta con recargar las automatizaciones.

**El PC ya no lo gobierna Home Assistant, sino `caja`** (fase 4 del HomeLab). Encender,
relanzar el agente, suspender y apagar los hace `caja`, que está en la misma LAN que el
PC: el backend deja un pedido en `PC_DIR/pedidos/<orden>` y `pc.path` (systemd) lo
convierte en `pc.sh`, que manda el paquete mágico o entra por SSH al PC y escribe cómo le
ha ido en `estado.json` (lo enseña `GET /pc/estado`). Las unidades, el script y su
configuración viven en el repositorio HomeLab. Se hizo porque este camino se rompió en
silencio al renombrar el PC (`docs/BUGS_HISTORICOS.md`) y porque los flags viven en
memoria del backend.

**Lo que sigue aquí es el respaldo.** Los flags y los sondeos de HA no se han quitado: si el
backend no tiene `PC_DIR`, o no puede escribir el pedido, pone el flag de siempre y el
Green lo ejecuta como antes. Nunca los dos a la vez — con `caja` el flag no se pone, y los
sondeos de HA devuelven siempre «nada pendiente». Mientras el Green conserve el
`shell_command` apuntando al nombre viejo del PC, el respaldo encenderá (el WOL no depende
del nombre) pero no relanzará, suspenderá ni apagará.

**Flujo WOL** (respaldo): frontend → `POST /wake-pc` → flag `_wol_pending` en
memoria → HA sondea `GET /ha/wol-pending` cada 30s vía
`sensor.life_assistant_wol_pending` → la automatización `la_wol_poll` detecta el cambio a
`true` → pulsa `button.pc_mikel`.

**Flujo del relanzado del agente** (respaldo): el agente es efímero y al PC lo despierta
el WOL, pero con el PC ya encendido no arranca nadie. Para eso está
`POST /relaunch-agent` → flag `_agent_relaunch_pending` → `GET /ha/agent-relaunch-pending`,
que el dashboard llama al abrir el streaming y al encolar una entrega, siempre **después**
de crear el job.

**La mitad de HA vive en `/config/packages/life_assistant_pc.yaml`**, no en
`configuration.yaml` — por eso no aparece buscando en los sitios de siempre y es fácil
darla por inexistente. Ese package define:

- `shell_command.la_relanzar_agente`, `la_apagar_pc` y `la_suspender_pc`: por SSH (ver
  `HOMEASSISTANT.md` para la clave, el usuario y el host), y el relanzado dispara
  `schtasks /run /tn LifeAssistantAgent` (la misma tarea del Programador que arranca el
  agente al encender el PC).
- Los sensores REST `Life Assistant Agent Relaunch Pending` y
  `Life Assistant PC Power Action`, ambos con `scan_interval: 30`.

La automatización que los une es `la_agent_relaunch`, en `automations.yaml`.

**Se usa el hostname del PC, no la IP, y con motivo** (el hostname concreto está en
`HOMEASSISTANT.md`): la IP cambia por DHCP, así que apuntar a una IP fija se rompe en
cuanto el router se la reasigna a otra cosa. Si el relanzado deja de funcionar, mira
primero a dónde resuelve el nombre; el PC no contesta a ping (firewall de Windows), así
que la prueba buena es abrir SSH contra él, no hacerle ping.

**`last_reported` de un sensor NO dice cuándo se sondeó por última vez.** En HA 2026.7
solo avanza cuando el valor **cambia**, así que un sensor sano que lleva días valiendo
`false` muestra una fecha antigua y parece muerto. Se cayó en esa trampa el 2026-09-03:
`agent_relaunch_pending` marcaba 22 h y `pc_power_action` dos días, y se dieron por
congelados; tras reiniciar el core, los tres reportaron a la vez y volvieron a quedarse
quietos un minuto y medio después — que es exactamente lo que hacen cuando funcionan.
**Para saber si la cadena va, la prueba es de extremo a extremo**: pulsar el botón del
dashboard y mirar si avanza el `last_triggered` de la automatización `la_agent_relaunch`.

Y tras editar un fichero de `packages/` hay que recargar la config (`ha core check` y
luego reiniciar): editarlo a mano no basta para que el cambio entre. Es lo único que
hacía falta de verdad ese día — el `shell_command` había pasado de la IP al hostname
esa misma mañana y podía seguir cargado el valor viejo.

Problemas ya resueltos por el camino (no los reintroduzcas):

- *Mixed content* (HTTPS→HTTP): el navegador no puede llamar a HA directamente → por eso
  el backend hace de intermediario.
- `rest_command` en la automatización fallaba al parsear el JSON en la plantilla → la
  solución fue un REST sensor + trigger de estado.
- El sensor está definido en `configuration.yaml` (`scan_interval: 30`); la automatización
  `la_wol_poll` se creó por la REST API y **no** está en `automations.yaml`.

Además, HA anuncia por Alexa el **nombre** del evento 15 minutos antes (no solo "evento en
15 minutos"), usando `/ha/events/soon`.

**Flujo de presencia** (el único que va de HA hacia el backend): el `device_tracker` de
la app companion → automatización `la_presencia` → `rest_command` que hace
`POST /ha/presencia`. Se dispara con **dos triggers**, y los dos hacen falta:

- cambio de estado del `device_tracker` (te mueves de zona), y
- un `time_pattern` cada 15 min (aviso periódico).

**Las zonas del gimnasio y de la uni** se crean en HA como cualquier zona, con un nombre
de `ZONAS_GIMNASIO` / `ZONAS_UNI`, y no piden nada más: la automatización ya manda el
estado del `device_tracker`, que es el nombre de la zona. El backend las traduce a lugares
y decide qué hacer al llegar y al salir (ver «Lugares» en `docs/JARVIS.md`). Ojo con el
radio: el campus entero, no la puerta de la facultad; y el del gimnasio, lo justo para no
coger la calle de al lado.

El periódico no es redundancia: sin él, un dato se quedaría vigente durante horas sin
que nadie confirme que HA sigue vivo, y `PRESENCE_TTL_MINUTES` no podría distinguir
"sigues en casa" de "HA se cayó". Es el que hace que el silencio signifique algo. El
intervalo del periódico tiene que ser **menor** que el TTL, o el dato caducará entre
avisos. El `rest_command` manda el token en la cabecera `X-Auth-Token`, no en la query
string (el soporte de query solo existe por compatibilidad con integraciones ya
desplegadas y expone el token en los logs de URLs).

**Y desde el 2026-09-10 eso vale para TODO lo que HA le manda al backend.** Hasta ese
día, seis sondeos —`events/soon`, `wol-pending`, `agent-relaunch-pending`,
`pc-power-pending` y el `rest_command` `la_wol_check`— seguían llevando el token en la
query, tres de ellos escondidos en `packages/life_assistant_pc.yaml` y no en
`configuration.yaml`. Se descubrió leyendo el log del add-on para otra cosa: el token
estaba ahí en claro, línea tras línea. Se rotó `HA_POLL_TOKEN` (en `secrets.yaml` y en
el fichero de entorno del backend, que son los dos sitios donde vive) y se pasaron todos
a cabecera. **Si añades un sondeo nuevo, en cabecera desde el primer día.**

**Flujo de los avisos al móvil**: HA sondea `GET /ha/avisos-pending` cada 30 s y manda lo
que salga con `notify.mobile_app_*`. Mismo patrón que el WOL (órdenes en memoria, leerlas
las consume), y el nombre del dispositivo vive **solo** en el YAML de HA. El YAML completo
está en `docs/HOME_ASSISTANT_JARVIS.md`.

Los **botones** de esa notificación van dentro del propio aviso (`acciones`), no fijos en
el YAML: los decide quien hace la pregunta, que es el backend. Por defecto son útil / no
útil (`POST /avisos/{id}/util`, la señal que hace que una regla inútil se calle sola) y el
aviso de la revisión nocturna trae los suyos, «Arreglarlo» / «No hacer nada»
(`POST /revision/{id}/accion`, ver `docs/REVISION_NOCTURNA.md`). HA solo pinta lo que le
llega y devuelve la respuesta por el `rest_command` que toque.

**Flujo de la casa** (los dos sentidos a la vez, y cada uno por su motivo): HA **sondea**
`GET /ha/ordenes-pending` cada 15 s y ejecuta lo que salga (órdenes: mismo patrón que el
WOL), y **empuja** su catálogo de dispositivos a `POST /ha/entidades` al arrancar y cada
hora (estado: mismo patrón que la presencia). Leer las órdenes las CONSUME, así que solo
puede haber un consumidor. El YAML completo está en `docs/HOME_ASSISTANT_JARVIS.md`.

Hay **dos productores** de órdenes y un solo consumidor: Jarvis (y lo que cuelga de él:
alarmas, el botón «Apagar» del aviso de salir de casa) y el widget «Casa» del dashboard
(`POST /casa/orden`). Los dos entran por `_j_casa_ordenar`, y HA no distingue unas de
otras. Lo que sí sale de aquí es el **acuse**: por la cola, el backend no sabe si HA
ejecutó algo, pero sabe cuándo HA le vació la cola, y eso es «HA la recogió» en la ficha.
La confirmación de verdad llega con el siguiente estado leído: si es posterior a la
recogida y dice el estado esperado, la orden sale como confirmada.

**En directo** (desde que el backend vive en `caja`, en la misma LAN que el Green): con
`HA_URL` y `HA_TOKEN` el backend **llama a la API REST de HA**, el sentido que durante años
no existió. Dos cosas:

- **El estado**: `GET /casa/estado` (y `casa_dispositivos` de Jarvis, y el aviso de salir
  de casa) le preguntan a HA cómo está cada entidad del catálogo (`GET /api/states`, una
  sola petición, 3 s de timeout y 3 s de caché para que varios clientes no la multipliquen).
  Si HA no contesta, se sirve el catálogo y la respuesta lo dice (`fuente: "catalogo"`).
- **Las órdenes**: `_j_casa_ordenar` manda el servicio a `POST /api/services/<dominio>/<servicio>`
  con la misma lista blanca, la misma validación y la misma confirmación de siempre
  (cerraduras, garaje y alarma se confirman por los dos caminos). Lo que pase después
  depende solo de lo que conteste HA:

  | HA… | La orden queda | ¿A la cola del Green? |
  |---|---|---|
  | contesta 2xx | **hecha**: la caché de estados se olvida entera y el estado que se devuelve es el que HA dice que cambió durante la llamada (o ninguno: una lectura de justo después puede ser la de antes) | No |
  | contesta 4xx (401/403: el usuario sin admin no puede; 400: datos que no valen) | **rechazada**: no se ha hecho, se dice, y el widget la pinta así | **Nunca** |
  | no aceptó la conexión (timeout de conexión, conexión rechazada, DNS) | **en cola**: HA no la vio | Sí, es el respaldo |
  | la recibió y no contestó (timeout de lectura, conexión cortada tras mandar, 5xx, cualquier otra cosa) | **sin confirmar**: puede haberse hecho; el refresco siguiente dice qué pasó | **Nunca** |

  La cola solo recibe lo que HA SEGURO que no vio. Encolar lo demás era que el Green
  repitiera lo que HA ya estaba haciendo (su API no contesta hasta que el servicio termina,
  y no lo cancela si el cliente se va: un script largo, el pulso del garaje) o que
  ejecutara, con sus privilegios de administrador, lo que HA acababa de negarle al usuario
  sin admin. Y de `homeassistant.*` solo pasan `turn_on`, `turn_off` y `toggle`, por los dos
  caminos: `restart` o `reload_*` administran HA, no la casa.

  Una orden **hecha** retira de la cola lo que esperaba sobre la misma entidad y la misma
  familia (encender/apagar, bloquear/desbloquear, abrir/cerrar/parar, play/pausa,
  armar/desarmar la alarma), o que sea el mismo servicio (la temperatura, el volumen): si el
  Green lo recogiera después, desharía lo que HA acaba de hacer. Los servicios de recarga
  (`*.reload`) no pasan por ningún camino, y un 401/403 al leer el estado apaga el directo 10 minutos
  (ver `docs/HOME_ASSISTANT_JARVIS.md`, sección 3 bis). Sin directo no se retira
  nada: hay un solo motor y el Green ejecuta en orden, como siempre.

**Lo que sigue haciendo el Green, con o sin directo**: empujar la presencia
(`POST /ha/presencia`) y el catálogo (`POST /ha/entidades`) —el catálogo dice QUÉ entidades
hay y cómo se llaman, y sin él el backend no sabe qué preguntarle a HA ni puede rechazar una
entidad que Jarvis se haya inventado—, y sondear la cola de órdenes, que con el directo
funcionando casi siempre sale vacía. No se quita nada: es el camino de vuelta, y el mismo
criterio que las órdenes al PC por `caja` (nunca los dos motores a la vez).

**Reloj de respaldo del resumen diario**: automatización `la_brief_tick`, un
`time_pattern` cada 5 min → `rest_command` a `POST /ha/brief-tick`. Ese mismo tick es el
que despacha los recordatorios de Jarvis: si funciona, los avisos salen solos — y **si esa
automatización se para, los avisos se quedan quietos aunque HA siga sondeando el resto**,
que son dos cosas distintas y se caen por separado. Por eso el despacho registra con
cuánto retraso sale cada aviso (`AVISO_RETRASO_AVERIA_MIN`): es la única forma de ver
desde dentro que el reloj se paró. HA pone el reloj
porque está siempre encendido y es puntual al minuto, las dos cosas que el cron de
GitHub Actions no garantiza (se retrasa 10-15 min cuando su cola va cargada). Un hilo
dentro del backend no valdría: Fly escala a cero y sin nadie que llame no hay proceso
vivo que mire la hora. Sondear cada 5 min es barato a propósito — antes de
`BRIEF_HORA_TOPE` el endpoint no toca Supabase ni construye nada.

**Flujo de las alarmas de respaldo**: un sensor REST propio sondea `GET /ha/alarma-tick`
cada **60 s** — el tick del resumen es de 5 minutos y una alarma que suena cuatro minutos
tarde no es una alarma. Mientras una alarma está escalada el backend contesta el número
de intento en pie **en cada tick**, no solo en el que escaló: es un estado, y así un
sondeo perdido no deja a la casa sin enterarse. Cada cambio de ese número dispara la
automatización `la_alarma_escalar`, que hace el ritual entero (encender las luces, quitar
el "no molestar", subir el volumen, anunciar por Alexa, poner la canción). El ritual vive
**aquí y no en la cola de órdenes del backend** porque una de las luces solo obedece
hablándole a Alexa, y `alexa_devices.send_text_command` no es un dominio de esa cola ni
apunta a una entidad. El botón «Estoy despierto» de la notificación vuelve por el molde de
siempre y **de fondo**: nada se abre en el móvil al pulsarlo. Lo que sí llega es otra
notificación —«⏰ Alarma quitada»— porque ese camino se pierde en silencio cuando la app
no alcanza a HA, y ya dejó una alarma sonando (`docs/BUGS_HISTORICOS.md`). Los otros dos
caminos para callarla no pasan por HA: el Atajo del cargador (`POST /despertar`) y
decírselo a Jarvis. Todo en `docs/ALARMAS.md`.
