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

Sin el catálogo, Jarvis no sabe qué hay en casa y se niega a actuar en vez de inventarse
nombres de entidades.

## 1. Recoger las órdenes

En `configuration.yaml`:

```yaml
rest:
  - resource: !secret la_url_ordenes        # https://TU-BACKEND/ha/ordenes-pending
    scan_interval: 15
    headers:
      X-Auth-Token: !secret ha_poll_token
    sensor:
      - name: "Jarvis ordenes"
        value_template: "{{ value_json.ordenes | length }}"
        json_attributes:
          - ordenes
```

**Ojo: leer ese endpoint VACÍA la cola** (igual que `/ha/wol-pending`). Es a propósito —
así una orden no se ejecuta dos veces— pero significa que el sensor es el único que puede
consumirla: no lo consultes desde otro sitio.

La automatización que las ejecuta (créala por la UI o por la API, como `la_wol_poll`):

```yaml
alias: Jarvis - ejecutar ordenes de la casa
mode: queued
trigger:
  # Sin `to`/`from` dispara también cuando solo cambian los atributos: dos lecturas
  # seguidas con una orden cada una dejan el estado en "1" y aun así hay que ejecutarlas.
  - platform: state
    entity_id: sensor.jarvis_ordenes
condition:
  - condition: template
    value_template: "{{ trigger.to_state.state | int(0) > 0 }}"
action:
  - repeat:
      for_each: "{{ state_attr('sensor.jarvis_ordenes', 'ordenes') | default([], true) }}"
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
    url: !secret la_url_entidades           # https://TU-BACKEND/ha/entidades
    method: POST
    content_type: "application/json"
    headers:
      X-Auth-Token: !secret ha_poll_token
    payload: >-
      {"entidades": [
      {%- set ns = namespace(coma = false) -%}
      {%- for dominio in ['light','switch','fan','cover','climate','media_player',
                          'lock','scene','script','input_boolean','vacuum'] -%}
        {%- for e in states[dominio] -%}
          {%- if ns.coma %},{% endif -%}
          {"id": "{{ e.entity_id }}",
           "nombre": "{{ e.name | replace('"', '') }}",
           "estado": "{{ e.state }}"}
          {%- set ns.coma = true -%}
        {%- endfor -%}
      {%- endfor -%}
      ]}
```

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

## Recordatorios: el mismo reloj

Los recordatorios (`recordarme`) los despacha `POST /ha/brief-tick`, la automatización que
ya existe para el resumen diario (`la_brief_tick`, cada 5 minutos). No hay que añadir
nada: si ese tick funciona, los avisos salen. Si HA está apagado, no salen — es el mismo
compromiso que el resumen diario, y por eso el reloj vive en la casa y no en Fly, que
escala a cero.
