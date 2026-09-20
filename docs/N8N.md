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
| En el repo | El `compose.yml` y su `.env.example`, en `docker/n8n/` |
| Los flujos | **En el repositorio HomeLab**, en `caja/n8n/flujos/` — no aquí |

Es un proyecto compose **aparte** de `~/stack` a propósito: así un `docker compose` en el
stack —que lleva el backend y el túnel— no puede pararlo por error ni contarlo como
huérfano. El precio es acordarse de que existe; para eso está este fichero y la fila de
`CLAUDE.md`.

**El compose del repositorio es la copia buena, pero no se despliega solo.** Igual que
los ficheros del add-on, se copia a mano a la máquina. Si lo cambias aquí, cópialo allí.

## Los flujos

> **Los `.json` de los flujos viven en el repositorio HomeLab** (`caja/n8n/flujos/`),
> desde el 2026-09-20. Estuvieron un día en éste y se movieron por la misma regla que
> todo lo demás de infraestructura de `caja`: la fuente de verdad de la máquina es
> HomeLab. Aquí se queda lo que explica **qué hacen y por qué**, que es lo que le
> interesa a una sesión que venga a tocar el backend.


| Flujo | Qué hace | Estado |
|---|---|---|
| **Vigilante del Green** | Cada 5 min pregunta a Home Assistant y cuenta lo que ve a `POST /vigilancia/estado` | Activo desde el 2026-09-20, 19:23 |
| **Traductor de averías** | Cada 15 min busca runs fallidos de GitHub Actions (menos el CI), se baja el registro, se lo da a Gemini y abre un issue con el diagnóstico | Activo desde el 2026-09-20 |
| **Primera pasada de PRs** | Cada 10 min coge un PR abierto sin revisar, se lo da a Gemini y comenta solo si encuentra algo | Activo desde el 2026-09-20 |
| **Vigilante de la web** | Cada 5 min sondea la web de Vercel. Cuenta lo que ve a `POST /vigilancia/estado`, vivo o muerto | Activo desde el 2026-09-20, 19:23 |
| **Vigilante del backend** | Cada 5 min sondea el backend. Si lleva tres sondeos caído, **llama al móvil por la centralita**, sin pasar por el backend | Activo desde el 2026-09-20, 19:23 |
| **Hablarlo, por teléfono** | Webhook `/hablarlo`: recibe el botón «Hablarlo» de un hallazgo de revisión/vigilante o de un aviso de sesión (reenviado por HA), decide de qué tabla es por el prefijo y llama a `POST /revision/{id}/accion` o `POST /sesion/{id}/accion` con `{"accion":"hablar"}` | Pendiente de montar |

> **Los tres vigilantes se activaron el 2026-09-20 a las 19:23**, y hasta ese momento
> ninguno lo estaba: la tabla de aquí arriba llevaba una tarde diciendo que el del Green
> corría cuando no corría, que es la trampa de más abajo aplicada a su propia
> documentación. Comprobado ya funcionando a las 19:25: los tres ejecutan con éxito,
> llegan dos `POST /vigilancia/estado` por vuelta (Green y web) y el del backend termina
> en tres nodos sin llamar, que es lo correcto con el backend vivo.

> **`n8n update:workflow --active=true` no basta.** Avisa él mismo («Changes will not
> take effect if n8n is running») y no miente: la fila de la base de datos queda activa,
> `list:workflow --active=true` los lista, y los disparadores **no están registrados**.
> Hace falta `docker restart n8n`, y la prueba de que ha entrado son las líneas
> `Activated workflow "<nombre>"` del arranque, no lo que diga el listado.

> **Hay dos «Vigilante del Green» en n8n.** El viejo (`xignTTiDief1EA6T`, manda a
> `/programado/roto`) sigue **inactivo y sin borrar**; el que corre es
> `y0DPIpDI7fVDEblR`, el de `/vigilancia/estado`. Por el nombre no se distinguen: por el
> id sí.

El del Green cambió el 2026-09-20: ya no manda a `/programado/roto` sino a
`/vigilancia/estado`, y manda **en cada sondeo**, no solo cuando falla. El sondeo bueno
no sobra: es lo que pone el contador a cero y lo que permite decir «ya ha vuelto». Un
vigilante que solo hablara de lo malo dejaría la avería marcada para siempre.

**Por qué son tres flujos y no uno.** Cada uno tiene disparador, credencial y lógica
propias: el del Green habla por el nodo de Home Assistant y distingue el Green caído de un
token caducado; el de la web hace un `GET` y poco más; el del backend es el único que
decide. Y hay una razón de fondo para no juntar los dos últimos: **la API no se puede
vigilar contra sí misma**. Estuvo un rato así —una sonda a la API dentro del vigilante de
la web— y era decorativa: mientras la API vive, el informe llega y no hace falta; cuando
cae, el informe cae con ella. El único aviso que importaba era justo el que no podía
salir.

### La excepción: el vigilante del backend SÍ decide

Es el único flujo que se salta la frontera de arriba, y la razón es que no hay otra:
**el sujeto que vigila es quien decidiría**. Cuando el backend está caído, `/vigilancia/estado`
está caído con él, así que o decide el flujo o no se entera nadie. Por eso repite en
pequeño las mismas tres reglas (tres sondeos, una llamada por avería, silencio nocturno)
y por eso su contador vive en `staticData` y no en memoria: en memoria empezaría de cero
en cada ejecución y llamaría al primer parpadeo.

Que esas reglas estén escritas dos veces es deuda consciente, no un descuido. Si algún
día cambian en `main.py`, hay que cambiarlas aquí también — y nada lo comprueba.

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

### El primer flujo por webhook: «Hablarlo»

Todos los flujos de arriba disparan por `Schedule trigger`. Este es el primero por
`Webhook`, porque lo que lo dispara no es un reloj sino que Mikel pulse un botón en el
móvil — y ese evento (`mobile_app_notification_action`) solo existe dentro de Home
Assistant, así que **no hay forma de evitar que HA sea quien lo entregue**: la única
automatización que queda en HA para esto es un reenvío en crudo del `action` a este
webhook (`docs/HOME_ASSISTANT_JARVIS.md`, sección «Hablarlo: el reenvío a n8n»). Todo lo
demás —de qué tabla es el id, a qué endpoint llamar— vive aquí, no en YAML.

Forma del flujo:

```
Webhook (/hablarlo) → Code (parsea prefijo y id) → IF (revisión / sesión) → HTTP Request
```

- El `Code` separa `LA_HABLAR_REV_<id>` de `LA_HABLAR_SES_<id>`: el prefijo dice la tabla,
  el resto del string es el id.
- El `HTTP Request` llama a `POST /revision/{id}/accion` o `POST /sesion/{id}/accion` con
  `{"accion": "hablar"}` y el token de servicio en cabecera (`X-Auth-Token`, el mismo que
  usan las automatizaciones de HA para los demás botones — `_auth_boton` en el backend
  acepta cualquiera de los dos).
- No decide nada que no decidiera ya HA con un `rest_command`: es pegamento, no un
  segundo cerebro. La decisión de qué se dice por teléfono la sigue tomando el backend
  (`_llamar`, `_jarvis_contexto_llamada`) — n8n solo hace de enrutador.

El webhook de n8n no sale de la LAN (mismo criterio que su panel), así que no lleva
credencial propia — el token va en la llamada de n8n al backend, no en la de HA a n8n.

## La IA de los flujos: Gemini en el plan gratuito

Los dos flujos que piensan usan **Gemini** por la API, con la credencial
`Google Gemini(PaLM) Api` de n8n. La regla de reparto es la que decide qué va a dónde:

> **Lo gratis hace el pegamento; la cuota de Claude Max se reserva para lo que de verdad
> piensa.** Clasificar, resumir, diagnosticar y cazar erratas es Gemini. Las revisiones
> de fondo y los arreglos siguen siendo la revisión nocturna con Claude Code.

**Por qué el plan gratuito vale aquí y no valdría en otro sitio**: el tier gratuito de
Google usa lo que le mandas para entrenar, **salvo en el EEE**, donde se aplican los
términos de los servicios de pago. Estando en España sale gratis sin ese peaje. Es la
razón por la que se eligió Gemini y no Mistral, cuyo tier generoso **exige** aceptar el
entrenamiento con tus datos.

**No actives la facturación en ese proyecto de Google Cloud.** En cuanto hay una cuenta
de facturación asociada, el proyecto pasa a tier de pago y los límites gratuitos dejan de
aplicar sin que nadie lo diga.

### Trampas de Gemini, descubiertas montando esto

- **Los modelos se retiran para cuentas nuevas sin avisar.** `gemini-2.5-flash` devuelve
  un 404 con el texto «is no longer available to new users. Please update your code to use
  models/gemini-3.6-flash». O sea que el 404 no significa que te hayas equivocado de
  nombre. Hoy se usa **`gemini-3.6-flash`**, fijado a propósito: un alias como
  `gemini-flash-latest` cambia de modelo debajo sin que cambie nada aquí.

- **El plan gratuito se satura a ratos**, y devuelve `UNAVAILABLE` con «This model is
  currently experiencing high demand». No es tu cuota: es la de todos. Pasó tres veces en
  una tarde. De ahí que los nodos lleven **5 reintentos cada 20 s**, y sobre todo que
  ningún flujo dependa de que el modelo conteste:
  - En **averías**, el issue se abre igual aunque Gemini falle, porque lleva el registro
    dentro. Un diagnóstico sin registro no se puede comprobar; un registro sin
    diagnóstico sigue sirviendo.
  - En **PRs** no se marca el PR como revisado si el modelo no contestó: vuelve a
    intentarlo a la vuelta siguiente. Ahí no hay prisa.

- **Probar qué modelos responden es barato**: un flujo con un nodo HTTP por modelo y
  `neverError`, y se ve de un vistazo cuál está saturado. De ocho probados, siete
  contestaron.

### Las dos reglas que gobiernan estos flujos

- **La IA propone, el sistema dispone.** Ninguno de los dos actúa: uno abre un issue y el
  otro deja un comentario. Las dos cosas son proponer, y las dos se borran en un clic.
- **Silencio cuando no hay nada que decir.** La primera pasada de PRs **no comenta** si no
  encuentra nada. Un bot que escribe «todo bien» en cada PR es un bot que se acaba
  ignorando, y con él se va el aviso que sí importaba. Es la misma regla que impide que el
  teléfono suene por cualquier cosa.

## Trampas conocidas

- **La interfaz importa UN objeto de flujo; la línea de comandos, una lista.** Los
  `.json` que salen de `n8n export:workflow` son `[ { ... } ]`, y el *Import from File*
  del navegador los rechaza. Si un flujo «no se deja importar», mira eso antes que nada:
  se arregla quedarse con el objeto de dentro y quitarle los campos internos de la base
  de datos (`id`, `versionId`, `shared`, `meta`) y los `id` de cada nodo, que si chocan
  con los de un flujo existente tumban la importación.

- **n8n también corre en un contenedor, así que `127.0.0.1` es el propio n8n.** Cualquier
  nodo que llame a algo de la máquina —el backend, la centralita del teléfono— lleva la
  IP de LAN de `caja`, nunca `localhost`. Es el mismo fallo que se comía las llamadas del
  backend (ver `backend/.env.example`), y en n8n es peor porque el nodo falla en una
  ejecución que nadie mira.

- **Importar no es sustituir.** Importar una versión nueva de un flujo que ya existe crea
  un **segundo flujo con el mismo nombre**, no lo reemplaza. Hay que desactivar y borrar
  el viejo a mano; si no, dentro de un mes nadie sabe cuál de los dos es el que corre. Se
  distinguen por dentro: el Vigilante del Green viejo tiene 5 nodos y un `IF`, y termina
  en `/programado/roto`; el nuevo tiene 4, no tiene `IF` y termina en
  `/vigilancia/estado`.

- **Las credenciales no viajan en el `.json`.** Un flujo recién importado tiene los nodos
  con la credencial en blanco, y activarlo así no da un error visible: da una ejecución
  fallida cada cinco minutos, en silencio.


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

- **GitHub no sirve el registro de un job: redirige.** `/actions/jobs/{id}/logs` responde
  302 a una URL firmada de Azure, y n8n —al contrario que curl— **reenvía la cabecera
  `Authorization` al cambiar de dominio**, que es justo lo que Azure rechaza con un 401.
  Hay que pedirlo en dos pasos: primero sin seguir el redirect para leer la `Location`, y
  luego esa URL **sin credencial ninguna**.

- **Un flujo que mira «lo que ha fallado» encuentra primero lo que falló hace meses.**
  `?status=failure` devuelve los últimos fallos, no los recientes. Sin un filtro por fecha,
  la primera vuelta empieza a abrir un issue de una avería vieja cada 15 minutos hasta
  vaciar la lista. El primero que salió al probarlo fue una copia de Supabase de semanas
  atrás. De ahí el corte a 24 horas.

- **No marques algo como «ya visto» antes de haber hecho el trabajo.** La primera versión
  del traductor apuntaba el run nada más cogerlo, así que si Gemini fallaba a mitad esa
  avería se perdía **para siempre**: la vuelta siguiente ya no la veía. Se marca al final.

- **La CLI de n8n no tiene `delete:workflow`** (en la 2.39.8). Para borrar un flujo, la
  interfaz — o `sqlite3` sobre el volumen con el contenedor parado y copia previa.

- **`n8n execute` necesita un disparador manual.** Un flujo que solo tiene
  `scheduleTrigger` falla con «Missing node to start execution», así que para probarlo por
  CLI hay que añadirle un `manualTrigger` temporal.

## Añadir un flujo

1. Constrúyelo en el panel (puerto 5678 de `caja`).
2. Actívalo y **comprueba que ha corrido**, no que está en verde.
3. Expórtalo y tráelo al repositorio:
   `docker exec -e N8N_RUNNERS_BROKER_PORT=5699 n8n n8n export:workflow --id=<id> --output=/tmp/w.json`
4. Añádelo a la tabla de flujos de arriba.

El punto 3 no es burocracia: sin él, el flujo existe en una sola copia y este fichero
vuelve a mentir.
