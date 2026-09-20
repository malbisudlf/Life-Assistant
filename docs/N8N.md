# n8n: el pegamento hacia fuera

n8n es automatización visual autoalojada. Vive en `caja` desde el 2026-09-18 y sirve
para lo que el backend no debería tener que saber hacer: hablar con servicios de fuera
sin escribir una integración a mano en `main.py` por cada uno.

**Este fichero existe porque el contenedor no se documenta solo.** Durante dos días n8n
corrió en `caja` sin aparecer en el repositorio ni en ningún índice: una sesión que
buscara «n8n» aquí concluía que no existía, que es exactamente lo que pasó el
2026-09-20 antes de escribir esto.

## La frontera, y es la que sostiene todo lo demás

> **n8n observa y avisa. No decide, no guarda estado y no es un segundo cerebro.**

Lo que descubre acaba en un endpoint del backend, igual que lo que descubre Home
Assistant. El motivo es el mismo que impide tener dos asistentes de voz distintos según
por dónde entres: la lógica que vive en un lienzo visual no tiene tests, no sale en el
diff de un PR y no la revisa el CI. Todo lo que pueda estar en `main.py`, en `main.py`.

Lo que sí le toca a n8n: los ~500 nodos de servicios externos, los disparadores por
tiempo y el pegamento. Ahí gana de calle.

## Dónde vive

| | |
|---|---|
| Máquina | `caja` (ver `docs/MIGRACION_BACKEND.md`) |
| Directorio | `/home/malbisudlf/docker/n8n/` |
| Panel | `http://<caja>:5678` — **solo LAN**, el router no reenvía el puerto. La IP está en `HOMEASSISTANT.md` |
| Imagen | `docker.n8n.io/n8nio/n8n:2.39.8`, versión fija |
| Datos | volumen `n8n_n8n_data` (flujos, credenciales, ejecuciones) |
| En el repo | `docker/n8n/compose.yml` y `.env.example` |

Es un proyecto compose **aparte** de `~/stack` a propósito: así un `docker compose` en el
stack —que lleva el backend y el túnel— no puede pararlo por error ni contarlo como
huérfano. El precio es acordarse de que existe; para eso está este fichero y la fila de
`CLAUDE.md`.

**El compose del repositorio es la copia buena, pero no se despliega solo.** Igual que
los ficheros del add-on, se copia a mano a la máquina. Si lo cambias aquí, cópialo allí.

## Los flujos

| Flujo | Qué hace | Estado |
|---|---|---|
| **Vigilante del Green** | Cada 5 min pregunta a Home Assistant. Si no contesta, `POST /programado/roto` → aviso al móvil | Activo desde el 2026-09-20 |

El patrón que fija ese flujo, y que conviene repetir:

```
Schedule trigger → nodo del servicio → Code (normaliza) → IF → HTTP Request al backend
```

Con dos detalles que no son casuales:

- **El silencio es la señal.** HA no puede decir que está caído: para contestar `up: 0`
  tendría que estar vivo. Cuando cae no llega un cero, no llega **nada**. El nodo `Code`
  existe para convertir esa ausencia en un `0`; sin él el `IF` nunca dispara y el
  vigilante es decorativo.
- **El token va en cabecera** (`httpHeaderAuth`), nunca en la query. Es la misma regla
  que `CLAUDE.md` impone a las integraciones: por la query el token acaba escrito en el
  registro de peticiones.

## Trampas conocidas

- **Un flujo inactivo no avisa de que está inactivo.** El Vigilante del Green nació
  `active: false` y estuvo así dos días. Es el mismo fallo que la copia de seguridad de
  Supabase, que estuvo meses fallando sin que nadie se enterara: un vigilante apagado es
  peor que no tenerlo, porque ocupa el sitio del que sí correría. **Al crear un flujo,
  actívalo y comprueba que ha corrido de verdad.**

- **`n8n execute` desde la CLI no funciona con el contenedor arriba.** Da
  `Task Broker's port 5679 is already in use`. Se esquiva con
  `docker exec -e N8N_RUNNERS_BROKER_PORT=5699 n8n n8n <comando>`.

- **`update:workflow --active` no surte efecto hasta reiniciar el contenedor.** Lo dice
  en su propia salida y es fácil pasarlo por alto: la base de datos queda cambiada y el
  proceso en marcha sigue con lo viejo, así que el panel y la realidad discrepan.

- **El volumen no entra en ninguna copia de seguridad.** `scripts/copia_supabase.py`
  solo mira tablas de Supabase. Los flujos y las credenciales de n8n existen en **una
  sola copia**, dentro de `caja`. Pendiente.

- **1 GB de memoria, no 512 MB.** Medido el 2026-09-20: ~446 MiB **en reposo**. Con
  512m, el primer flujo que haga algo de verdad se lo lleva por delante con un OOM.

- **n8n no puede vigilar a `caja`.** Vive dentro. Lo mismo que Grafana y Prometheus, y
  por eso el 2026-09-19 `caja` estuvo apagada toda la noche sin que nadie se enterara.
  Ese vigilante tiene que correr en el Green, como automatización de HA.

## Añadir un flujo

1. Constrúyelo en el panel (puerto 5678 de `caja`).
2. Actívalo y **comprueba que ha corrido**, no que está en verde.
3. Expórtalo y tráelo al repositorio:
   `docker exec -e N8N_RUNNERS_BROKER_PORT=5699 n8n n8n export:workflow --id=<id> --output=/tmp/w.json`
4. Añádelo a la tabla de flujos de arriba.

El punto 3 no es burocracia: sin él, el flujo existe en una sola copia y este fichero
vuelve a mentir.
