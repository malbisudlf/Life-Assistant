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

**Flujo WOL** (funcionando): frontend → `POST /wake-pc` (Fly) → flag `_wol_pending` en
memoria → HA sondea `GET /ha/wol-pending` cada 30s vía
`sensor.life_assistant_wol_pending` → la automatización `la_wol_poll` detecta el cambio a
`true` → pulsa `button.pc_mikel`.

**Flujo del relanzado del agente**: el agente es efímero y al PC lo despierta el WOL,
pero con el PC ya encendido no arranca nadie. Para eso está `POST /relaunch-agent` →
flag `_agent_relaunch_pending` → `GET /ha/agent-relaunch-pending`, que el dashboard llama
al abrir el streaming y (desde 2026-09-03) también al encolar una entrega.

**La mitad de HA vive en `/config/packages/life_assistant_pc.yaml`**, no en
`configuration.yaml` — por eso no aparece buscando en los sitios de siempre y es fácil
darla por inexistente. Ese package define:

- `shell_command.la_relanzar_agente`, `la_apagar_pc` y `la_suspender_pc`: SSH con
  `/config/.ssh/id_pc` a `malbi@mikel.local`, y el relanzado dispara
  `schtasks /run /tn LifeAssistantAgent` (la misma tarea del Programador que arranca el
  agente al encender el PC).
- Los sensores REST `Life Assistant Agent Relaunch Pending` y
  `Life Assistant PC Power Action`, ambos con `scan_interval: 30`.

La automatización que los une es `la_agent_relaunch`, en `automations.yaml`.

**Se usa el hostname `mikel.local`, no la IP, y con motivo**: la IP del PC cambió por
DHCP (a 2026-09-03, `mikel.local` resuelve a una IP distinta de la que había cableada
antes, y en la vieja ya responde otra máquina). Si el relanzado deja de funcionar, mira
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

El periódico no es redundancia: sin él, un dato se quedaría vigente durante horas sin
que nadie confirme que HA sigue vivo, y `PRESENCE_TTL_MINUTES` no podría distinguir
"sigues en casa" de "HA se cayó". Es el que hace que el silencio signifique algo. El
intervalo del periódico tiene que ser **menor** que el TTL, o el dato caducará entre
avisos. El `rest_command` manda el token en la cabecera `X-Auth-Token`, no en la query
string (el soporte de query solo existe por compatibilidad con integraciones ya
desplegadas y expone el token en los logs de URLs).

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
