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
- **`confirmada`**: pulsaste el botón (o lo hiciste desde el dashboard, o se lo dijiste a
  Jarvis). Se para la música.
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
- **La reserva es un PATCH condicional** (`&estado=eq.armada`), no un GET seguido de un
  PATCH. La condición *es* la pregunta atómica: con dos ticks solapados, un GET previo
  dejaría avisar dos veces. Misma trampa y misma solución que en el despachador de
  recordatorios.
- **El aviso va `critico=True`.** Un despertador que no suena con el móvil en silencio no
  despierta. Es la segunda cosa del proyecto que se permite esto, y por el mismo criterio
  que la primera (el permiso de despliegue): sin respuesta, se queda bloqueado. **Requiere
  el permiso de "notificaciones críticas" de la app en el iPhone** — el mismo que ya pedía
  `docs/AVERIAS.md`. Sin él la notificación llega igual, pero callada, que para una alarma
  es como no llegar.
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
la secuencia entera: quitar el "no molestar", subir el volumen, anunciar por
`notify.alexa_media_*`, lanzar la canción y encender las luces.

**No es una preferencia de estilo, es una necesidad**: una de las luces del cuarto («led
mesa») solo obedece hablándole a Alexa, así que se enciende con
`alexa_devices.send_text_command` — un servicio que **no cabe en la cola de órdenes** del
backend, porque `alexa_devices` no es un dominio de `_CASA_DOMINIOS` y además apunta a un
`device_id`, no a una entidad. Lo que sí cabe (volumen, "no molestar", parar la música) va
por la cola de siempre.

El YAML completo está en `docs/HOME_ASSISTANT_JARVIS.md`.

### Los endpoints

| Ruta | Auth | Qué hace |
|---|---|---|
| `GET /ha/alarma-tick` | servicio (`HA_POLL_TOKEN`) | El reloj. Devuelve `escalar` (nº de intento, 0 = no toca), `id` y `texto` |
| `POST /alarmas/{id}/despierto` | servicio **o** JWT | «Estoy despierto». Lo llama el botón de la notificación o el dashboard |
| `GET /alarmas` | JWT | Las alarmas activas, en hora local |
| `POST /alarmas` | JWT | Poner una: `{fecha?, hora, etiqueta?, repetir?}`. Con `repetir` (días ISO, 1 = lunes) la fecha sobra: la primera vez es el próximo día marcado |
| `DELETE /alarmas/{id}` | JWT | Cancelarla (no la borra) |

`escalar` es lo que HA usa como **estado** del sensor y no un simple `true`: cambia en
cada escalada, así que la automatización se dispara aunque dos escaladas seguidas dejaran
el mismo texto. Es el mismo cuidado que ya llevan los triggers de órdenes y avisos.

### Jarvis

Tres herramientas, ninguna pide confirmación: `poner_alarma` (con `repetir` para las
semanales: «todos los lunes» es `[1]`, «entre semana» es `[1,2,3,4,5]`), `mis_alarmas` y
`cancelar_alarma`. Poner una no toca nada del mundo real, y cancelarla es justo lo que
quieres poder hacer deprisa cuando está sonando.

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

**La hora va siempre en 24h**, y eso hay que pedirlo en dos sitios: `<html lang="es">` en
`index.html` (estaba en `en`, y por eso el `<input type="time">` pintaba AM/PM en una app
entera en español) y `lang="es-ES"` en el propio input. Chrome mira el `lang` del elemento
para los campos de fecha y hora; **Firefox no** — ese usa el idioma del navegador y no hay
nada que hacer sin escribir un selector propio. Y en el texto, la hora lleva sus dos
dígitos (`08:05`, no `8:05`): «las 8:30» a secas se lee como «las ocho y media» sin saber
de cuál de las dos, y esa duda en un despertador se paga durmiendo doce horas de más.

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
