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
        value_template: "{{ value_json.avisos | length }}"
        json_attributes:
          - avisos
```

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
              # Botones de valoración. Es la señal que hace que una regla que no sirve
              # se calle sola: sin ella, la única forma de que un aviso inútil
              # desaparezca es dejar de mirarlos todos.
              actions:
                - action: "LA_UTIL_{{ repeat.item.id }}"
                  title: "Útil"
                - action: "LA_NOUTIL_{{ repeat.item.id }}"
                  title: "No"
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
```

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
