<!-- Parte de la guía del repositorio. El índice y las reglas que aplican
     SIEMPRE están en CLAUDE.md, en la raíz. -->

## Alarmas de respaldo

El despertador lo sigues poniendo donde quieras (el iPhone, normalmente). Esto es la
**red que hay debajo**: a la hora apuntada llega un aviso al móvil con un botón «Estoy
despierto», y si no lo pulsas se da por hecho que sigues dormido y se despierta la casa
—el altavoz del cuarto habla, pone música y se encienden las luces—, insistiendo cada
`ALARMA_ESPERA_MIN` hasta que confirmes o hasta que se rinda.

**Por qué no lee la alarma del iPhone.** No se puede: iOS no expone la próxima alarma a
Home Assistant. La app companion sí publica un `sensor.*_next_alarm` en **Android** (de
hecho existe uno de la tablet, parada desde mayo), pero del iPhone no hay ninguno. De ahí
que la alarma haya que **decirla**: a Jarvis («tengo alarma mañana a las 8:30») o
apuntarla en el widget. Es el precio de que el despertador siga siendo el del móvil.

### La máquina de estados

```
armada ──(llega la hora)──► avisada ──(2 min sin confirmar)──► escalada ──┐
   │                            │                                 ▲      │ (cada 2 min)
   │                            └──────────► confirmada ◄─────────┴──────┘
   │                                                                │
   └──► cancelada                          rendida ◄────(30 min sin confirmar)
```

Y si la alarma se repite, `confirmada` y `rendida` no son el final: vuelve sola a
`armada` con la fecha de la próxima vez (ver «Las que se repiten»).

- **`armada`**: puesta y esperando su hora.
- **`avisada`**: sonó el aviso al móvil, con el botón. Aquí es donde se **prepara el
  altavoz** (ver abajo).
- **`escalada`**: se despertó a la casa. `intentos` cuenta cuántas veces.
- **`confirmada`**: dijiste que estás despierto, por cualquiera de los **cuatro caminos**:
  el botón de la notificación, el dashboard, Jarvis («estoy despierto», herramienta
  `estoy_despierto`, sin id) o **desenchufar el cargador** (el Atajo de `POST /despertar`
  calla lo que esté sonando). Se para la música y, si vino por el botón o el dashboard,
  llega la notificación de vuelta que dice que ha entrado. Y confirmar es además **la
  señal de despertar del resumen diario**, la misma que el cargador (`docs/BRIEF.md`).
- **`rendida`**: pasaron `ALARMA_MAX_MIN` sin respuesta. **Se avisa de que se rinde**: una
  alarma que deja de sonar sola y no lo cuenta es indistinguible de una que nunca se armó,
  y eso es lo que hace que dejes de fiarte del respaldo.
- **`cancelada`**: la quitaste. Cancelar **cambia el estado, no borra la fila** — una
  alarma que sonó y escaló es parte de por qué la casa hizo ruido a las 8:32.

### Las que se repiten («todos los lunes»)

Una alarma semanal es **una sola fila** con la columna `repetir` (texto: los días ISO
separados por comas, `"1,3,5"`, donde 1 es lunes). Vacío = suena una vez, que es lo que
había antes. Cuando la alarma termina —la confirmes (`confirmada`) o se rinda
(`rendida`)— se **rearma sola**: `_alarma_reprogramar` la vuelve a poner en `armada` con
la fecha de la próxima vez y los contadores a cero.

Las tres decisiones que la sostienen:

- **Una fila que vuelve al principio, no una fila por ocurrencia.** Generar las próximas
  N semanas obligaría a decidir cuántas y a limpiarlas después, para no ganar nada: solo
  se puede estar sonando una vez. Y el precio está aceptado: el historial de una alarma
  semanal es el de la última vez, no el de todos los lunes del año.
- **El rearme usa el mismo PATCH condicional que todo lo demás** (`_alarma_reservar` con
  el estado previo). Si mientras tanto la cancelaste, el PATCH no se lleva la fila y la
  alarma **no resucita**. Sin esa condición, cancelar una alarma que estaba sonando la
  habría vuelto a armar dos líneas después.
- **La próxima vez se calcula desde ahora, no desde su hora original**
  (`_alarma_proxima`). Si el backend estuvo dos semanas apagado, la alarma vuelve el
  próximo lunes. Rearmada en el pasado no llegaría tarde: vencería en el acto y se
  rearmaría otra vez, una vez por semana perdida. Y el cálculo se hace sobre hora local
  **naive**, volviendo a poner la zona al final: sumar días a un datetime con zona
  arrastra el desfase viejo y la semana del cambio de hora sonaría sesenta minutos antes
  o después.

Al rendirse, el aviso dice cuándo vuelve. Una alarma que se rearma sin contarlo se da por
perdida, que es el mismo motivo por el que se avisa de la rendición.

Lo que sigue **sin** hacerse es armar el respaldo de una alarma recurrente y que suene un
festivo: eso lo decides tú al marcar los días. Marcar el domingo y olvidarlo es un
despertador que suena el domingo, no un fallo.

### Las decisiones que no son obvias

- **El reloj es propio, no el tick del resumen diario.** Aquel pasa cada 5 minutos, y una
  alarma que puede sonar cuatro minutos tarde no es una alarma. Un sensor REST de HA llama
  a `GET /ha/alarma-tick` cada **60 s**, que es la resolución mínima de algo que se mide
  en minutos.
- **Y aun así el tick es barato.** `_alarma_siguiente` recuerda en memoria cuándo hay algo
  que hacer; hasta entonces el endpoint no toca Supabase. Las ~1.400 veces al día en que
  no hay nada puesto no cuestan una consulta. Es la misma economía que se le exige al
  brief-tick, y hay un test que la protege.
- **`GET` con efectos, a propósito.** Un sensor REST de HA solo sabe hacer GET, y en este
  proyecto el sondeo de HA *es* el reloj. Mismo patrón que `/ha/avisos-pending` y
  `/ha/ordenes-pending`, que además vacían su cola al leerla.
- **`escalar` es un ESTADO, no un aviso** (`_alarma_sonando`). Mientras la alarma siga
  escalada, el tick repite el número de intento en pie en **cada** sondeo —también en los
  que no consultan Supabase— y solo vuelve a 0 al confirmar, cancelar, editar o rendirse.
  La primera versión lo devolvía solo en la respuesta del tick que escalaba, y eso es un
  aviso viajando por un canal de sondeo: bastaba que HA se perdiera ese sondeo (un
  timeout, un reinicio en ese minuto) para que la casa no se enterase nunca, porque el
  siguiente ya devolvía 0. Con el estado, un sondeo perdido cuesta un minuto. Vive en
  memoria: perderlo en un reinicio del add-on cuesta que la siguiente escalada lo reponga.
- **Si la casa no va a sonar, el móvil dice por qué.** Cuando la presencia dice que
  estás fuera, la insistencia lleva «No despierto la casa: Home Assistant dice que estás
  fuera (zona X, hace N min)», y queda a WARNING en `app_logs`. Desde la cama, «aviso 3»
  sin música es una alarma rota; con la frase es una decisión que se puede corregir
  (casi siempre un `person` en `not_home` por un GPS desviado de madrugada).
- **La reserva es un PATCH condicional** (`&estado=eq.armada`), no un GET seguido de un
  PATCH. La condición *es* la pregunta atómica: con dos ticks solapados, un GET previo
  dejaría avisar dos veces. Misma trampa y misma solución que en el despachador de
  recordatorios.
- **Quitar la alarma pasa ENTERO de fondo, y el botón no abre nada.** Pulsas «Estoy
  despierto» en la notificación, el móvil manda `mobile_app_notification_action`, Home
  Assistant lo recoge y llama a `POST /alarmas/{id}/despierto`. No hay pantalla, ni
  navegador, ni app que se abra: son las seis de la mañana y lo único que has pedido es
  que aquello deje de sonar. Un botón que además te planta una web delante convierte un
  gesto de medio segundo en un trámite despierto.
- **Y de vuelta llega otra notificación, «⏰ Alarma quitada».** No es cortesía: el salto
  móvil → Home Assistant es el único del camino que **no escribe en ningún log**, y si se
  pierde —pasa, ver abajo— pulsar el botón no hace nada y nada lo dice. El acuse es lo que
  convierte ese silencio en una señal: si has pulsado y en unos segundos no llega, no ha
  entrado, y te quedan el widget y Jarvis. Va **efímero** (`_notificar(..., efimero=True)`):
  al móvil o a ningún sitio. Por correo no vale — se lee a mediodía, cuando ya no dice
  nada y encima hace dudar de si la alarma se quitó o se rindió sola.
- **El botón llevó un `uri` al dashboard justo un día** (2026-09-14 → 2026-09-15), como
  segundo camino para cubrir ese evento perdido: abría el dashboard con `?despierto=<id>`
  y confirmaba desde ahí, sin pasar por HA. Funcionaba, y aun así fue peor que el fallo
  que arreglaba, porque el precio lo pagaban **todas** las veces que el botón sí funciona:
  una web abriéndose en la cara cada mañana para apagar un despertador. La moraleja no es
  que un segundo camino sobre, es **dónde puede ir**: la redundancia no puede cobrarse en
  el camino feliz de un gesto que se hace medio dormido. El acuse de recibo cubre lo
  mismo sin cobrar nada — no arregla el salto frágil, lo hace visible.
- **Los segundos caminos que sí valen son los que ya haces.** Desenchufar el cargador es
  algo que pasa todas las mañanas sin que nadie lo pida, y es la prueba de que estás
  despierto: por eso `POST /despertar` calla la alarma que esté sonando. No cuesta nada
  cuando el botón funciona (no hay nada que callar) y para la alarma cuando su evento se
  pierde. Y decírselo a Jarvis es lo mismo desde el reloj: la herramienta
  `estoy_despierto` **no pide id** —a las siete de la mañana y por voz no se tiene—,
  calla lo que suene y ya. Antes solo había `cancelar_alarma`, que necesita el id (dos
  vueltas de herramienta) y, para una semanal, la mata: decir «estoy despierto» acababa
  en nada o en quedarse sin alarma el lunes que viene.
- **El aviso va `critico=False`: es una notificación normal.** Lo fue `critico=True` al
  principio, con el razonamiento de que un despertador que no suena con el móvil en
  silencio no despierta; en la práctica saltarse el silencio del móvil resultó excesivo
  para lo que es una red de debajo. Si el móvil está callado y no confirmas, quien
  despierta es la escalada por el altavoz — que es exactamente para lo que está. Así que
  el permiso de "notificaciones críticas" del iPhone ya **no** hace falta para las alarmas
  (sigue haciendo falta para el permiso de despliegue, ver `docs/AVERIAS.md`), y la
  escalada deja de ser el plan B para pasar a ser el que de verdad te levanta.
- **Una alarma no pasa por el gobierno de avisos** (`_apuntar_aviso`, presupuesto diario,
  silenciado, huella). La has pedido tú y con hora exacta, y la regla del proyecto es que
  lo que pides tú no se gobierna. Un despertador que no suena porque hoy ya se habían
  gastado los tres avisos sería exactamente el fallo que esto viene a cubrir.
- **El volumen es 0,35 y no más**, probado despertándose de verdad: el Echo del cuarto
  está a un metro de la cama y al 70 % no despierta, sobresalta. Lo que hace levantarse es
  que suene *algo*, no que suene fuerte.
- **El altavoz se prepara al AVISAR, no al escalar.** Quitar el "no molestar" y subir el
  volumen se encolan en el primer toque, dos minutos antes de que haga falta. El motivo es
  que las órdenes de la casa y los avisos del móvil son **dos colas distintas**, con
  sondeos de 15 y 30 segundos: mandarlo todo en el mismo instante no garantiza que el
  volumen esté puesto cuando el altavoz vaya a hablar.
- **Fuera de casa no se toca la casa.** Si la presencia dice que no estás, el aviso al
  móvil se repite igual pero el altavoz no suena: ahí duerme más gente. Lo que **no** hace
  es callarse por no saber — un dato de presencia caducado no es un "no estás", y este
  respaldo existe justo para cuando lo demás falla.
- **El tope existe.** Sin `ALARMA_MAX_MIN`, una alarma se quedaría sonando en una casa
  vacía si te fuiste sin el móvil. En algún momento hay que aceptar que nadie va a
  contestar.

### El ritual vive en Home Assistant, no en el backend

El backend decide **cuándo**; HA sabe **cómo**. La automatización `la_alarma_escalar` hace
la secuencia entera: encender las luces, quitar el "no molestar", subir el volumen,
anunciar por `notify.alexa_media_*` y lanzar la canción.

**No es una preferencia de estilo, es una necesidad**: una de las luces del cuarto («led
mesa») solo obedece hablándole a Alexa, así que se enciende con
`alexa_devices.send_text_command` — un servicio que **no cabe en la cola de órdenes** del
backend, porque `alexa_devices` no es un dominio de `_CASA_DOMINIOS` y además apunta a un
`device_id`, no a una entidad. Lo que sí cabe (volumen, "no molestar", parar la música) va
por la cola de siempre.

**Las luces van primero y cada paso lleva `continue_on_error`.** Una automatización de HA
se para en el primer paso que falla, y los que fallan son los de Alexa (la integración
pierde la sesión con Amazon y el "no molestar" queda `unavailable`). Con el "no molestar"
el primero, un fallo de Alexa se llevaba las luces por delante, que no tienen nada que
ver con Alexa — y eso, desde la cama, es «no se encendió nada».

El YAML completo está en `docs/HOME_ASSISTANT_JARVIS.md`, con una sección «Cuando no
suena, dónde mirar» que dice qué huella deja cada pieza (el estado del widget, el texto de
la insistencia, la traza de la automatización).

### Los endpoints

| Ruta | Auth | Qué hace |
|---|---|---|
| `GET /ha/alarma-tick` | servicio (`HA_POLL_TOKEN`) | El reloj. Devuelve `escalar` (nº de intento en pie, 0 = no suena nada; se repite en cada tick mientras suene), `id` y `texto` |
| `POST /alarmas/{id}/despierto` | servicio **o** JWT | «Estoy despierto». Lo llama el botón de la notificación o el dashboard. Si se lleva la fila, contesta al móvil con «⏰ Alarma quitada» y cuenta como señal de despertar del resumen |
| `POST /despertar` | servicio (`BRIEF_TOKEN`) | El Atajo del cargador. Es del resumen diario, pero de paso calla la alarma que esté sonando (sin id: todas las que suenen) |
| `GET /alarmas` | JWT | Las alarmas activas, en hora local |
| `POST /alarmas` | JWT | Poner una: `{fecha?, hora, etiqueta?, repetir?}`. Con `repetir` (días ISO, 1 = lunes) la fecha sobra: la primera vez es el próximo día marcado |
| `PATCH /alarmas/{id}` | JWT | Editarla (mismo cuerpo que el POST). La deja `armada` con los contadores a cero |
| `DELETE /alarmas/{id}` | JWT | Cancelarla (no la borra) |

`escalar` es lo que HA usa como **estado** del sensor y no un simple `true`: cambia en
cada escalada, así que la automatización se dispara aunque dos escaladas seguidas dejaran
el mismo texto. Es el mismo cuidado que ya llevan los triggers de órdenes y avisos.

### Jarvis

Cuatro herramientas, ninguna pide confirmación: `poner_alarma` (con `repetir` para las
semanales: «todos los lunes» es `[1]`, «entre semana» es `[1,2,3,4,5]`), `mis_alarmas`,
`cancelar_alarma` (para una que **aún no ha sonado**; a una semanal la deja de repetir) y
`estoy_despierto` (**sin parámetros**: calla la que esté sonando y cuenta como señal de
despertar del resumen). Poner una no toca nada del mundo real, y callarla es justo lo que
quieres poder hacer deprisa cuando está sonando. Las dos últimas están separadas a
propósito: «estoy despierto» y «quita la alarma de mañana» son gestos distintos, y con
una sola herramienta el modelo callaba una que sonaba matando su repetición, o no hacía
nada por no tener el id. Sus casos están en `evals/casos.json`.

### El widget

`case "alarmas"` en `Dashboard.jsx`, columna izquierda. Poner hora, ver las puestas con su
estado y quitarlas. Mientras una está sonando, el botón «Estoy despierto» se come el
widget: es lo único que quieres de esa pantalla en ese momento. Se recarga solo cada
minuto mientras haya algo vivo (sin nada vivo no hay temporizador), porque una alarma que
empieza a insistir tiene que verse moverse en una pantalla ya abierta.

Debajo del formulario hay siete círculos (L M X J V S D). Marcar uno convierte la alarma
en semanal y **esconde el selector de fecha**, que ya no se manda. Se pintan siempre,
también sin marcar: detrás de un interruptor, la mitad de las veces se pondría una alarma
suelta sin saber que se podía repetir.

La lógica pura vive en `src/lib/helpers.js`: `alarmaCuandoTexto` (que para una semanal
dice «todos los lunes a las 07:00» — de una alarma que se repite, qué lunes concreto es
la próxima vez no dice nada), `alarmaEnPalabras` (que compara **por día de calendario y
no por horas de diferencia** — a las 23:00, las 00:30 son mañana aunque queden noventa
minutos), `alarmaRepeticionTexto`, `alarmaEstadoTexto` y `alarmaSonando`.

**La hora va siempre en 24h**, y para eso el widget **no usa `<input type="time">`**: usa
`TimeInput` y `DateInput`, los campos propios que ya tenía el formulario de eventos. El
input del navegador pinta AM/PM (y `mm/dd/aaaa`) en cuanto el navegador va en inglés, y
desde la página no hay forma de obligarle: Chrome hace caso al `lang` del documento y del
elemento, **Firefox lo ignora del todo**. El `lang="es"` de `index.html` sigue puesto —
estaba en `en` en una app entera en español, y arregla los demás campos de fecha del
dashboard—, pero aquí la hora la escribimos nosotros y no se le pregunta a nadie.

En el texto, la hora lleva sus dos dígitos (`08:05`, no `8:05`): «las 8:30» a secas se lee
como «las ocho y media» sin saber de cuál de las dos, y esa duda en un despertador se paga
durmiendo doce horas de más.

**Editar una alarma puesta** es pinchar su fila (o el ✎): se carga en el mismo formulario
y el botón pasa a decir «Guardar». Un solo formulario para poner y para editar, y una sola
validación detrás (`_alarma_momento`), porque dos caminos que validan una hora acaban
divergiendo y entonces editar acepta lo que poner rechazaba.

Guardar **rearma**: la fila vuelve a `armada` con los contadores a cero, así que editar
una que está sonando la calla. La música se para **solo si estaba sonando** — por eso el
PATCH se intenta primero con `estado=eq.armada` y solo si no se lleva la fila se reintenta
con los estados vivos: un `media_stop` en cada edición callaría lo que estuvieras
escuchando por cambiar la hora de mañana. Y solo se edita lo vivo: una alarma confirmada o
rendida es historia, y cambiarla reescribiría por qué la casa hizo ruido a las 8:32.

### Variables

| Variable | Por defecto | Qué hace |
|---|---|---|
| `ALARMA_ESPERA_MIN` | `2` | Minutos sin confirmar antes de escalar, y entre insistencias |
| `ALARMA_MAX_MIN` | `30` | Tope: pasado esto se rinde |
| `ALARMA_VOLUMEN` | `0.35` | A cuánto se pone el altavoz antes de hablar |
| `ALARMA_ALTAVOZ` | — | El `media_player` del cuarto. Vacío: no se prepara el altavoz |
| `ALARMA_NO_MOLESTAR` | — | El `switch` de "no molestar" de ese altavoz |

Las dos últimas van vacías por defecto porque son entidades de una casa concreta y este
repositorio es público. Sin ellas la alarma suena igual, solo que puede pillar el altavoz
en silencio: se oye poco, que es mejor que sonar donde no toca.

### Lo que no se hace y por qué

- **Repetir por fecha** («cada día 1», «cada dos semanas»). La repetición es solo por día
  de la semana, que es como se levanta uno. Lo demás son casos de calendario, y para eso
  ya está el calendario.
- **Leer `sensor.mikel_proxima_alarma_2`** (la alarma del Echo) para armar el respaldo
  solo. Se puede y quizá se haga, pero obligaría a poner siempre la alarma hablándole a
  Alexa, que es justo lo que no se hace hoy.
- **La llamada de teléfono como tercer escalón.** El canal existe (`docs/LLAMADAS.md`)
  pero está apagado, y cuesta dinero por llamada.
