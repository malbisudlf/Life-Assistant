# Jarvis y la casa (Home Assistant)

Para que Jarvis pueda encender una luz hay que dar de alta dos cosas en Home Assistant.
Ninguna lleva datos personales: la URL del backend y el token van en `secrets.yaml`.

## Por qué así y no llamando a HA directamente

El backend vive en Fly y HA en tu LAN, sin exponer. El backend **no puede llamar a HA**
—es el mismo muro que obligó a que el Wake-on-LAN pasara por aquí—, así que se usan los
dos patrones que ya funcionan en el proyecto, cada uno para lo suyo:

| Qué | Dirección | Dónde vive | Por qué |
|---|---|---|---|
| Órdenes ("enciende la luz") | HA **sondea** `GET /ha/ordenes-pending` | Memoria del backend | Son órdenes pendientes: perderlas en un cold start solo cuesta volver a pedirlas, igual que el WOL |
| Catálogo de dispositivos | HA **empuja** a `POST /ha/entidades` | Supabase | Es estado, y el que lo sabe es HA. Igual que la presencia |
| Avisos al móvil | HA **sondea** `GET /ha/avisos-pending` | Memoria del backend | Son órdenes también: "díselo al móvil". El backend no sabe a qué móvil — lo decide el `notify.*` de aquí |

Sin el catálogo, Jarvis no sabe qué hay en casa y se niega a actuar en vez de inventarse
nombres de entidades.

## 1. Recoger las órdenes

En `configuration.yaml`:

```yaml
rest:
  - resource: "https://TU-BACKEND/ha/ordenes-pending"
    headers:
      X-Auth-Token: !secret ha_poll_token
    scan_interval: 15
    sensor:
      - name: "Life Assistant Casa Ordenes"
        value_template: "{{ value_json.ordenes | length }}"
        json_attributes:
          - ordenes
```

El token va en **cabecera**, no en `params`: por la query acaba en los logs de URLs del
backend (la query solo sigue soportada por las integraciones antiguas).

**Ojo: leer ese endpoint VACÍA la cola** (igual que `/ha/wol-pending`). Es a propósito —
así una orden no se ejecuta dos veces— pero significa que el sensor es el único que puede
consumirla: no lo consultes desde otro sitio.

La automatización que las ejecuta (créala por la UI o por la API, como `la_wol_poll`).
**El `entity_id` del trigger tiene que ser el que HA le haya dado de verdad al sensor**
—`name: "Life Assistant Casa Ordenes"` produce `sensor.life_assistant_casa_ordenes`—:
míralo en Herramientas para desarrolladores → Estados antes de copiar, porque una
automatización que escucha a una entidad que no existe no falla, simplemente no se
dispara nunca.

```yaml
alias: Life Assistant - Ejecutar ordenes de la casa
mode: queued
max: 10
trigger:
  # Sin `to`/`from` dispara también cuando solo cambian los atributos: dos lecturas
  # seguidas con una orden cada una dejan el estado en "1" y aun así hay que ejecutarlas.
  - platform: state
    entity_id: sensor.life_assistant_casa_ordenes
condition:
  - condition: template
    value_template: "{{ trigger.to_state.state | int(0) > 0 }}"
action:
  - repeat:
      for_each: "{{ state_attr('sensor.life_assistant_casa_ordenes', 'ordenes') | default([], true) }}"
      sequence:
        - service: "{{ repeat.item.servicio }}"
          target:
            entity_id: "{{ repeat.item.entidad }}"
          data: "{{ repeat.item.datos | default({}, true) }}"
```

El backend ya filtra el servicio contra una lista blanca de dominios (`light`, `switch`,
`climate`, `cover`, `lock`…) y descarta las órdenes de más de `CASA_ORDEN_TTL` segundos,
así que esta automatización puede ejecutar lo que reciba sin volver a validarlo.

## 2. Mandar el catálogo

En `configuration.yaml`:

```yaml
rest_command:
  jarvis_entidades:
    url: "https://TU-BACKEND/ha/entidades"
    method: POST
    headers:
      X-Auth-Token: !secret ha_poll_token
    content_type: "application/json"
    timeout: 30
    payload: >-
      {%- set dominios = ['light','switch','fan','cover','climate','media_player',
                          'lock','scene','script','input_boolean','vacuum'] -%}
      {%- set lista = (states | selectattr('domain','in',dominios) | list)[:400] -%}
      {"entidades": [
      {%- for e in lista -%}
      {%- if not loop.first %},{% endif -%}
      {"id": {{ e.entity_id | to_json }}, "nombre": {{ e.name | to_json }},
       "estado": {{ e.state | to_json }}}
      {%- endfor -%}
      ]}
```

Los valores van con `| to_json` y no entre comillas a mano: un nombre de dispositivo con
comillas o acentos raros rompería el JSON entero, y ahí se pierde el catálogo completo.
El `[:400]` es el mismo tope que impone el backend.

Y una automatización que lo llame al arrancar HA y cada hora — al arrancar porque el
catálogo puede haber cambiado mientras estaba apagado, y cada hora para que los estados
(`on`/`off`) no envejezcan demasiado:

```yaml
alias: Jarvis - mandar catalogo de la casa
trigger:
  - platform: homeassistant
    event: start
  - platform: time_pattern
    hours: "/1"
action:
  - service: rest_command.jarvis_entidades
```

Si añades un dominio a la lista de arriba, añádelo también a `_CASA_DOMINIOS` en
`backend/main.py` o el backend rechazará las órdenes que lo usen.

## 3. Comprobar que va

```bash
# ¿Llega el catálogo? (debería responder guardadas: N)
curl -X POST https://TU-BACKEND/ha/entidades \
     -H "X-Auth-Token: TU_HA_POLL_TOKEN" -H "Content-Type: application/json" \
     -d '{"entidades":[{"id":"light.prueba","nombre":"Prueba","estado":"off"}]}'
```

Y en el dashboard: «Jarvis, ¿qué luces tengo?». Si contesta que Home Assistant no ha
mandado el catálogo, el `rest_command` no está llegando.

## 4. Avisos al móvil

Es el canal que hace que un recordatorio llegue **cuando toca** y no cuando abres el
buzón. Mientras nadie recoja esta cola, todo sigue saliendo por correo exactamente como
antes: el canal se enciende solo cuando alguien empieza a sondear, no hay nada que
activar en el backend.

En `configuration.yaml`, junto al sensor de las órdenes:

```yaml
rest:
  - resource: "https://TU-BACKEND/ha/avisos-pending"
    headers:
      X-Auth-Token: !secret ha_poll_token
    scan_interval: 30
    sensor:
      - name: "Life Assistant Avisos"
        value_template: >
          {{ (value_json.avisos | default([], true) | length)
             + (value_json.borrar | default([], true) | length) }}
        json_attributes:
          - avisos
          - borrar
```

**El estado suma los avisos y los borrados a propósito.** `borrar` son los `tag` de
notificaciones que hay que RETIRAR del móvil porque su pregunta ya está contestada, y
viajan por esta misma cola. Si el estado contara solo los avisos, una lectura que trajera
un borrado y ningún aviso dejaría el sensor en `0`, la condición de la automatización
(`> 0`) no pasaría y ese borrado se perdería — y como leer vacía la cola, se perdería para
siempre.

**Leerlo VACÍA la cola**, igual que las órdenes y el WOL: solo puede consumirlo este
sensor. Y ese sondeo es además lo que declara vivo el canal — si HA deja de sondear más
de `AVISO_MOVIL_VIVO` segundos (5 min por defecto), el backend vuelve al correo solo.

La automatización que los manda al móvil (aquí sí va el nombre de tu dispositivo, que por
eso no está en el backend):

```yaml
alias: Life Assistant - Avisos al movil
mode: queued
max: 10
trigger:
  # Sin `to`/`from`, igual que las órdenes: dos lecturas con un aviso cada una dejan el
  # estado en "1" y las dos hay que mandarlas.
  - platform: state
    entity_id: sensor.life_assistant_avisos
condition:
  - condition: template
    value_template: "{{ trigger.to_state.state | int(0) > 0 }}"
action:
  - repeat:
      for_each: "{{ state_attr('sensor.life_assistant_avisos', 'avisos') | default([], true) }}"
      sequence:
        - service: notify.mobile_app_TU_MOVIL   # ← SUSTITÚYELO (ver abajo)
          data:
            title: "{{ repeat.item.titulo }}"
            message: "{{ repeat.item.texto }}"
            data:
              # Los botones los decide el BACKEND y vienen dentro del propio aviso,
              # porque los decide quien hace la pregunta. Casi siempre son los de
              # valoración (útil / no útil), que es la señal que hace que una regla que
              # no sirve se calle sola; el aviso de la revisión nocturna trae los suyos
              # («Arreglarlo» / «No hacer nada»), que no se valoran, se responden.
              actions: "{{ repeat.item.acciones | default([], true) }}"
              # El `tag` hace que una notificación del mismo aviso REEMPLACE a la
              # anterior en vez de apilarse, y es lo que permite retirarla después. Lo
              # pone el backend y nunca viene vacío: un tag vacío uniría todos los
              # avisos sin id en una sola notificación que se va pisando a sí misma.
              tag: "{{ repeat.item.tag }}"
              # Y si el aviso viene marcado como crítico, que suene AUNQUE el móvil esté
              # en silencio o en modo concentración. Quién lo marca lo decide el backend
              # y hoy es una sola cosa —el permiso de despliegue—, por la misma regla que
              # el teléfono: solo lo que se queda bloqueado hasta que contestes. Requiere
              # dar permiso de "notificaciones críticas" a la app en el iPhone; sin él la
              # notificación llega igual, pero callada.
              push: >-
                {{ {'sound': {'name': 'default', 'critical': 1, 'volume': 1.0}}
                   if repeat.item.critico | default(false) else {} }}
        # Y si el aviso pide voz (estás en casa), que además se oiga.
        - if:
            - condition: template
              value_template: "{{ repeat.item.voz | default(false) }}"
          then:
            - service: notify.alexa_media_TU_ALTAVOZ   # ← SUSTITÚYELO
              data:
                message: "{{ repeat.item.texto }}"
                data:
                  type: announce
  # Y las notificaciones que ya no preguntan nada, fuera del móvil. Va en la MISMA
  # automatización y después del bloque de arriba para que un borrado no pueda adelantar
  # al aviso que borra.
  - repeat:
      for_each: "{{ state_attr('sensor.life_assistant_avisos', 'borrar') | default([], true) }}"
      sequence:
        - service: notify.mobile_app_TU_MOVIL   # ← SUSTITÚYELO, el mismo de arriba
          data:
            message: clear_notification
            data:
              tag: "{{ repeat.item }}"
```

**Por qué hace falta retirarlas.** Una notificación con botones sobrevive a la decisión
que preguntaba: si contestas «Arreglarlo» por teléfono o desde el dashboard, la del móvil
se queda ahí preguntando algo ya respondido. Pulsarla otra vez no rompe nada —las
transiciones son PATCH condicionales— pero un botón que no hace nada enseña a desconfiar
del canal, y éste es el canal por el que llegan las averías.

**Si no instalas este último `repeat`**, todo lo demás sigue funcionando: los borrados se
recogen y se tiran, que es exactamente lo que pasaba antes.

Y la automatización que recoge la respuesta a los botones:

```yaml
alias: Life Assistant - Valoracion de avisos
mode: queued
trigger:
  - platform: event
    event_type: mobile_app_notification_action
condition:
  - condition: template
    value_template: "{{ trigger.event.data.action is match('LA_(NO)?UTIL_') }}"
action:
  - service: rest_command.la_valorar_aviso
    data:
      aviso: "{{ trigger.event.data.action.split('_')[-1] }}"
      util: "{{ 'NOUTIL' not in trigger.event.data.action }}"
```

```yaml
rest_command:
  la_valorar_aviso:
    url: "https://TU-BACKEND/avisos/{{ aviso }}/util"
    method: POST
    headers:
      X-Auth-Token: !secret ha_poll_token
      Content-Type: application/json
    payload: '{"util": {{ util | lower }}}'
```

Y la de los botones de la **revisión nocturna**, que son otra pregunta distinta: no se
valora el aviso, se decide si se arregla el código (ver `docs/REVISION_NOCTURNA.md`).

```yaml
alias: Life Assistant - Revision nocturna
mode: queued
trigger:
  - platform: event
    event_type: mobile_app_notification_action
condition:
  - condition: template
    value_template: "{{ trigger.event.data.action is match('LA_(ARREGLAR|NADA)_') }}"
action:
  - service: rest_command.la_revision_accion
    data:
      aviso: "{{ trigger.event.data.action.split('_')[-1] }}"
      accion: "{{ 'arreglar' if 'ARREGLAR' in trigger.event.data.action else 'nada' }}"
```

```yaml
rest_command:
  la_revision_accion:
    url: "https://TU-BACKEND/revision/{{ aviso }}/accion"
    method: POST
    headers:
      X-Auth-Token: !secret ha_poll_token
      Content-Type: application/json
    payload: '{"accion": "{{ accion }}"}'
    # Arrancar la sesión que arregla tarda: la máquina de Fly puede estar dormida y
    # además hay que llamar a la API de Anthropic. Con el timeout por defecto (10 s) HA
    # da el rest_command por fallido aunque el arreglo se haya lanzado.
    timeout: 60
```

**«Arreglarlo» te contesta con otra notificación** («Voy a ello», con el enlace de la
sesión). Si pulsas y no llega nada, el problema está en este `rest_command` o en el
`notify` de arriba, no en el backend: él contesta siempre por el mismo canal.

Y **«Hablarlo»** del mismo aviso (revisión nocturna o vigilante): desde que existe la
centralita, este botón ya no abre el dashboard —eso era un `action: "URI"` y no
necesitaba automatización—, ahora hace sonar el teléfono con Jarvis-Claude al otro lado
(`docs/LLAMADAS.md`). A diferencia del resto de botones de este fichero, **este no lleva
su propia automatización de HA**: el enrutado (de qué tabla es, a qué endpoint del
backend llamar) se hace en n8n. HA solo reenvía el evento en crudo — ver «Hablarlo: el
reenvío a n8n», más abajo, y el flujo en `docs/N8N.md`.

Y la del botón **«Apagar»** del aviso de salir de casa, que es la tercera pregunta
distinta: no se valora el aviso ni se decide nada de código, se apaga lo que te dejaste
encendido (el backend encola las órdenes y las recoge el sondeo de `ordenes-pending` que
ya tienes puesto, así que no hace falta nada más).

```yaml
alias: Life Assistant - Apagar al salir
mode: queued
trigger:
  - platform: event
    event_type: mobile_app_notification_action
condition:
  - condition: template
    value_template: "{{ trigger.event.data.action is match('LA_APAGAR_') }}"
action:
  - service: rest_command.la_apagar_aviso
    data:
      aviso: "{{ trigger.event.data.action.split('_')[-1] }}"
```

```yaml
rest_command:
  la_apagar_aviso:
    url: "https://TU-BACKEND/avisos/{{ aviso }}/apagar"
    method: POST
    headers:
      X-Auth-Token: !secret ha_poll_token
```

Y la del botón **«Desplegar»**, que es la cuarta y la única que toca **producción**: el
backend detectó que algo se rompió, ya lo ha arreglado y el PR está en verde esperando
tu permiso (ver `docs/AVERIAS.md`). Va a un endpoint distinto del de la revisión
nocturna a propósito, aunque el patrón sea idéntico — así se puede revocar este sin
tocar aquél.

```yaml
alias: Life Assistant - Desplegar el arreglo
mode: queued
trigger:
  - platform: event
    event_type: mobile_app_notification_action
condition:
  - condition: template
    value_template: "{{ trigger.event.data.action is match('LA_(DESPLEGAR|ESPERAR)_') }}"
action:
  - service: rest_command.la_despliegue_accion
    data:
      aviso: "{{ trigger.event.data.action.split('_')[-1] }}"
      accion: "{{ 'desplegar' if 'DESPLEGAR' in trigger.event.data.action else 'nada' }}"
```

```yaml
rest_command:
  la_despliegue_accion:
    url: "https://TU-BACKEND/despliegue/{{ aviso }}/accion"
    method: POST
    headers:
      X-Auth-Token: !secret ha_poll_token
      Content-Type: application/json
    payload: '{"accion": "{{ accion }}"}'
    # Mergear el PR y disparar el workflow son dos llamadas a la API de GitHub detrás de
    # un posible arranque en frío de Fly. Con el timeout por defecto (10 s), HA daría el
    # despliegue por fallido cuando en realidad ya está en marcha — y ese es justo el
    # error que hace pulsar el botón dos veces.
    timeout: 60
```

**Si no instalas esta automatización no pasa nada malo**: el aviso sigue llegando y el
permiso se puede dar hablando con Jarvis («despliega el arreglo»). Lo único que no
funciona es el botón.

Y la del botón **«Vale»**, que es la quinta y la más tonta de todas: una sesión de Claude
Code te ha dejado un aviso (`docs/AVISAME.md`), lo has leído y no hay nada que contestar.
Cierra el aviso y ya está. Existe para que un aviso leído deje de estar pendiente — si
no, seguiría siendo lo que Jarvis anuncia al descolgar por cualquier otra cosa, y el
canal se convertiría en un contestador que repite el mismo mensaje.

```yaml
alias: Life Assistant - Vale, aviso leído
mode: queued
trigger:
  - platform: event
    event_type: mobile_app_notification_action
condition:
  - condition: template
    value_template: "{{ trigger.event.data.action is match('LA_VALE_') }}"
action:
  - service: rest_command.la_sesion_accion
    data:
      aviso: "{{ trigger.event.data.action.split('_')[-1] }}"
```

```yaml
rest_command:
  la_sesion_accion:
    url: "https://TU-BACKEND/sesion/{{ aviso }}/accion"
    method: POST
    headers:
      X-Auth-Token: !secret ha_poll_token
      Content-Type: application/json
    payload: '{"accion": "vale"}'
```

El otro botón de ese aviso, **«Hablarlo»**, hace sonar el teléfono igual que el de la
revisión nocturna — antes era un `action: "URI"` sin automatización, ahora pasa por el
mismo reenvío a n8n de la sección siguiente.

### Hablarlo: el reenvío a n8n

`LA_HABLAR_REV_<id>` (revisión/vigilante) y `LA_HABLAR_SES_<id>` (aviso de sesión) son
los dos únicos botones de este fichero cuya lógica **no vive en una automatización de
HA**: el enrutado (de qué tabla es el id, a qué endpoint del backend llamar) está en un
flujo de n8n — decisión de Mikel, para no seguir acumulando YAML por cada botón nuevo.
El flujo entero, con capturas de cómo está montado, en `docs/N8N.md`.

**Instalado y probado de punta a punta el 2026-09-22** (`id: la_hablar_n8n` en
`automations.yaml`, `la_hablar_a_n8n` en `configuration.yaml`). La comprobación no fue
pulsar el botón: se dispara el evento a mano contra la API de HA
(`POST /api/events/mobile_app_notification_action` con
`{"action": "LA_HABLAR_REV_<uuid inventado>"}`) y se mira que el backend conteste
**404 «No hay esa revisión pendiente»**. Ese 404 es la señal de éxito: significa que el
evento recorrió HA, n8n y la autenticación del backend, y solo falló al buscar un id que
nunca existió. Un 403 ahí es la credencial de n8n, no el YAML.

Lo único que sigue en HA es el reenvío en crudo del evento, porque **eso no se puede
evitar**: el botón lo pulsa la app del móvil, que solo sabe hablar con Home Assistant, así
que HA es el único que puede ver ese evento y pasárselo a n8n. Una sola automatización
genérica para los dos botones:

```yaml
alias: Life Assistant - Hablarlo, reenviar a n8n
mode: queued
trigger:
  - platform: event
    event_type: mobile_app_notification_action
condition:
  - condition: template
    value_template: "{{ trigger.event.data.action is match('LA_HABLAR_') }}"
action:
  - service: rest_command.la_hablar_a_n8n
    data:
      accion: "{{ trigger.event.data.action }}"
```

```yaml
rest_command:
  la_hablar_a_n8n:
    url: "http://TU-CAJA:5678/webhook/hablarlo"   # IP de LAN de `caja`, nunca localhost
    method: POST
    content_type: "application/json"
    payload: '{"accion": "{{ accion }}"}'
```

**Sin credencial**: el webhook de n8n solo es alcanzable dentro de la LAN (mismo criterio
que su panel, `docs/N8N.md`), así que no lleva token — igual que el vigilante del backend
llama a la centralita sin pasar por credenciales del backend.

**Si no instalas esta automatización** el botón «Hablarlo» de revisión/vigilante y de
sesión deja de hacer nada visible — a diferencia de antes, ya no tiene un `uri` de
respaldo que abra el dashboard. El permiso de despliegue no se toca: su «Hablarlo» sigue
siendo `action: "URI"` sin automatización.

**Apaga lo que decía el aviso, no lo que hay encendido al pulsar.** Las entidades viajan
guardadas con el aviso desde que se apuntó, porque el catálogo que empujas cada hora
puede ir muy por detrás: un botón que apaga algo de lo que el aviso no habló es peor que
no tener botón. Y **el PC no entra**, aunque el aviso lo nombre: cortarle la corriente a
un enchufe no es apagarlo. Para eso está su propio aviso.

Todas estas automatizaciones pueden convivir sin pisarse: cada una filtra por su prefijo.

**No contestar no cuenta como "no útil"**: el backend solo apunta lo que llega. El
silencio no vota, ni a favor ni en contra — es la misma regla de siempre, "no lo sé" no
puede disfrazarse de dato.

**La voz es opcional y falla hacia el lado bueno**: si no tienes Alexa configurada, borra
ese bloque `if` y todo lo demás sigue igual. El backend no sabe si se oyó — como con el
móvil, solo sabe que HA vino a recogerlo.

Tres trampas de este paso, las tres pisadas ya:

- **`TU_MOVIL` hay que sustituirlo**, y si se queda tal cual el fallo es de los peores:
  la automatización SÍ se dispara y revienta al mandar, así que el backend ve que HA
  recogió el aviso, el panel dice "al móvil" y no llega nada. El nombre real es
  `notify.mobile_app_` + el nombre del dispositivo en minúsculas, sin acentos y con
  guiones bajos. Si no lo sabes, sale de tu propia automatización de presencia:
  `grep -n "device_tracker\." /config/automations.yaml` — el mismo trozo detrás del
  punto es el que va aquí.
- **Si el YAML se quedó con los botones fijos de útil / no útil** (la versión anterior a
  `repeat.item.acciones`), el aviso de la revisión nocturna llega con los botones
  equivocados: pulsarlos manda una valoración de una regla en vez de una decisión, y el
  informe se queda sin arreglar. El backend no puede detectarlo — desde aquí solo se ve
  que HA recogió la cola, como siempre. Lo mismo con el «Apagar» del aviso de salir de
  casa: sin `repeat.item.acciones` el botón no llega a pintarse, y sin la automatización
  de abajo se pinta pero no hace nada.
- **Si tocas la acción por el editor visual, se vacían `message` y `title`.** Al elegir
  el servicio en el desplegable, HA rehace la acción y se lleva por delante las
  plantillas `{{ repeat.item.* }}`. Vuelve a ponerlas, o edita en YAML (los tres puntos
  de la PÁGINA, no los de la acción) y pega el bloque entero.
- **Los errores de HA no están en `/config/home-assistant.log`** en una instalación con
  Supervisor: se leen con `ha core logs`. Buscarlos en el fichero que no existe fue lo
  que dejó esto a oscuras un buen rato.

Para comprobarlo, el panel ⚙ del dashboard tiene una fila **Avisos** (dice por dónde
están saliendo y cuánto hace que HA los recogió) y un botón **«Probar aviso»** que
recorre la cadena entera. Si dice "enviado al móvil" y no llega nada, el problema está en
esta automatización o en el nombre del `notify.*`.

**Si el YAML se queda a medias** —el sensor puesto y la automatización no, por ejemplo—
los avisos encolados se rescatan por correo pasados `AVISO_MOVIL_RESCATE` segundos (10
min). El canal puede fallar; lo que no puede es tragarse avisos en silencio.

## Recordatorios: el mismo reloj

Los recordatorios (`recordarme`) los despacha `POST /ha/brief-tick`, la automatización que
ya existe para el resumen diario (`la_brief_tick`, cada 5 minutos). No hay que añadir
nada: si ese tick funciona, los avisos salen (por el móvil si el punto 4 está puesto, y
si no por correo). Si HA está apagado, no salen — es el mismo
compromiso que el resumen diario, y por eso el reloj vive en la casa y no en Fly, que
escala a cero.

## Alarmas de respaldo

Tres piezas. El detalle de por qué está montado así —y por qué el ritual vive aquí y no en
el backend— está en `docs/ALARMAS.md`.

**El reloj.** Un sensor REST a 60 s: el tick del resumen diario pasa cada 5 minutos y una
alarma que suena cuatro minutos tarde no es una alarma.

```yaml
rest:
  - resource: "https://TU-BACKEND/ha/alarma-tick"
    headers:
      X-Auth-Token: !secret ha_poll_token
    scan_interval: 60
    sensor:
      - name: "Life Assistant Alarma"
        # El estado es el NÚMERO de intento, no un true/false: cambia en cada escalada,
        # así que dos escaladas seguidas se ven como dos cambios y no como uno. Y es un
        # ESTADO: mientras la alarma suene, el backend lo repite en cada sondeo («1»
        # dos minutos, luego «2»…) y solo vuelve a «0» al confirmar. Un sondeo perdido
        # no se lleva la escalada por delante.
        value_template: "{{ value_json.escalar | int(0) }}"
        json_attributes:
          - id
          - texto
```

**El ritual.** Todo en una sola secuencia, en este orden y con `continue_on_error` en
cada paso. Las dos cosas vienen de una mañana en que «ni se encendieron las luces ni sonó
la música ni nada» (2026-09-17): una automatización de HA **se para en el primer paso que
falla**, y los pasos de Alexa son los que fallan (la integración pierde la sesión con
Amazon cada cierto tiempo, y entonces el interruptor de "no molestar" está
`unavailable`). Con el "no molestar" el primero y sin `continue_on_error`, un fallo de
Alexa se lleva también las luces, que no tienen nada que ver con Alexa. Ahora las luces
van primero —son lo que más despierta y lo que menos falla— y cada paso cae por su
cuenta. Sustituye el altavoz, las luces y el `device_id` por los tuyos.

```yaml
alias: Life Assistant - Alarma, despertar
mode: single
trigger:
  # Sin `to`/`from`, igual que las órdenes y los avisos.
  - platform: state
    entity_id: sensor.life_assistant_alarma
condition:
  - condition: template
    value_template: "{{ trigger.to_state.state | int(0) > 0 }}"
action:
  # Las luces PRIMERO: no dependen de Alexa y son lo que de verdad despierta. Y una
  # luz POR PASO, no las dos en el mismo `entity_id`: si una está `unavailable` —a la
  # tira led le pasa— el paso entero puede fallar y llevarse la otra por delante, que
  # es el mismo error que arreglan los `continue_on_error`, un nivel más abajo.
  - service: light.turn_on
    target: { entity_id: light.luces_mesa }   # ← SUSTITÚYELA
    data: { brightness_pct: 100 }
    continue_on_error: true
  - service: light.turn_on
    target: { entity_id: light.tira_led }     # ← SUSTITÚYELA
    data: { brightness_pct: 100 }
    continue_on_error: true
  - service: switch.turn_off
    target: { entity_id: switch.TU_ALTAVOZ_no_molestar }   # ← SUSTITÚYELO
    continue_on_error: true
  - service: media_player.volume_set
    target: { entity_id: media_player.TU_ALTAVOZ }         # ← SUSTITÚYELO
    data: { volume_level: 0.35 }
    continue_on_error: true
  - service: notify.alexa_media_TU_ALTAVOZ                 # ← SUSTITÚYELO
    data:
      message: "{{ state_attr('sensor.life_assistant_alarma', 'texto') | default('Despierta', true) }}. Despierta."
      data:
        type: announce
    continue_on_error: true
  # La canción va como COMANDO DE VOZ y no como `media_content_id` de una lista: así
  # funciona con lo que tengas vinculado (Amazon Music, Spotify) sin depender de que un
  # identificador de playlist siga existiendo dentro de seis meses.
  - service: media_player.play_media
    target: { entity_id: media_player.TU_ALTAVOZ }         # ← SUSTITÚYELO
    data:
      media_content_type: custom
      media_content_id: "pon la canción Weltita de Bad Bunny"
    continue_on_error: true
  # La tercera luz solo obedece hablándole a Alexa, así que se enciende como comando de
  # texto. Este paso es la razón por la que el ritual es YAML y no una lista de órdenes
  # del backend: `alexa_devices` no es un dominio de la cola y va por device_id.
  - service: alexa_devices.send_text_command
    data:
      device_id: TU_DEVICE_ID                              # ← SUSTITÚYELO
      text_command: "Enciende led mesa"
    continue_on_error: true
```

**Cuando no suena, dónde mirar.** Hay tres piezas y cada una deja su huella:

1. El **widget de alarmas del dashboard** (o `mis_alarmas` de Jarvis). Si la alarma está
   en `escalada` con N intentos, el backend ha hecho su parte: decidió escalar y lo ha
   contestado al sensor. Si sigue en `avisada` pasados los dos minutos, el fallo está en
   el sondeo (el sensor REST no llama o el token no vale: mira el historial de
   `sensor.life_assistant_alarma`, que tiene que ir cambiando de número).
2. La **notificación de insistencia** («aviso 2», «aviso 3»). Si dice «No despierto la
   casa: Home Assistant dice que estás fuera», la casa no suena a propósito, porque la
   presencia que HA empuja al backend dice que no estás. Suele ser un `person` en
   `not_home` por un GPS desviado de madrugada; mira `GET /presencia` y la zona. Queda
   además a WARNING en `app_logs`.

   **Y una presencia reciente no quiere decir una presencia cierta.** El backend
   caduca la presencia por su `updated_at` (`PRESENCE_TTL_MINUTES`) y se calla cuando
   no sabe, que es lo correcto; pero la automatización `Life Assistant - Presencia`
   reenvía el estado del `device_tracker` **cada 15 minutos aunque el tracker lleve un
   día sin reportar**, así que el dato llega siempre fresco y el TTL no llega a
   dispararse nunca. Eso fue lo que pasó el 2026-09-17: el iPhone dejó de mandar
   ubicación el día anterior a las 09:24, se quedó clavado en `not_home` a 26 km de
   casa, y la alarma de las 08:30 escaló sin tocar la casa mientras Mikel dormía en
   ella. Antes de culpar al ritual, mira el `last_reported` del `device_tracker`, no
   solo su estado.
3. La **traza de la automatización** (Ajustes → Automatizaciones → «Life Assistant -
   Alarma, despertar» → Trazas). Si el `last_triggered` es de hoy, HA se disparó y el
   fallo está en un paso concreto del ritual: la traza dice cuál. Si no se disparó
   aunque el sensor cambió, la condición o el trigger están mal copiados.

**El botón.** Mismo molde que los otros cinco, y sin `uri`: pulsarlo no abre nada en el
móvil, que es la mitad del sentido de este botón. Este salto —la app companion entregando
el evento a HA— es el único del camino que no deja huella en ningún log, así que el
backend contesta con otra notificación («⏰ Alarma quitada») para que se note cuando se
pierde. Y hay dos caminos más que **no pasan por HA**: desenchufar el cargador (el Atajo
de `POST /despertar` calla lo que esté sonando) y decirle a Jarvis «estoy despierto». Ver
`docs/ALARMAS.md`.

```yaml
alias: Life Assistant - Alarma, estoy despierto
mode: queued
trigger:
  - platform: event
    event_type: mobile_app_notification_action
condition:
  - condition: template
    value_template: "{{ trigger.event.data.action is match('LA_DESPIERTO_') }}"
action:
  - service: rest_command.la_alarma_despierto
    data:
      alarma: "{{ trigger.event.data.action.split('_')[-1] }}"
```

```yaml
rest_command:
  la_alarma_despierto:
    url: "https://TU-BACKEND/alarmas/{{ alarma }}/despierto"
    method: POST
    headers:
      X-Auth-Token: !secret ha_poll_token
      Content-Type: application/json
    payload: '{}'
```

El aviso de la alarma va como notificación **normal**, no crítica (ver `docs/ALARMAS.md`):
si el móvil está en silencio y no confirmas, quien te despierta es la escalada por el
altavoz. El permiso de notificaciones críticas sigue haciendo falta solo para el permiso
de despliegue.
