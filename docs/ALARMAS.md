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
| `POST /alarmas` | JWT | Poner una: `{fecha, hora, etiqueta?}` |
| `DELETE /alarmas/{id}` | JWT | Cancelarla (no la borra) |

`escalar` es lo que HA usa como **estado** del sensor y no un simple `true`: cambia en
cada escalada, así que la automatización se dispara aunque dos escaladas seguidas dejaran
el mismo texto. Es el mismo cuidado que ya llevan los triggers de órdenes y avisos.

### Jarvis

Tres herramientas, ninguna pide confirmación: `poner_alarma`, `mis_alarmas` y
`cancelar_alarma`. Poner una no toca nada del mundo real, y cancelarla es justo lo que
quieres poder hacer deprisa cuando está sonando.

### El widget

`case "alarmas"` en `Dashboard.jsx`, columna izquierda. Poner hora, ver las puestas con su
estado y quitarlas. Mientras una está sonando, el botón «Estoy despierto» se come el
widget: es lo único que quieres de esa pantalla en ese momento. Se recarga solo cada
minuto mientras haya algo vivo (sin nada vivo no hay temporizador), porque una alarma que
empieza a insistir tiene que verse moverse en una pantalla ya abierta.

La lógica pura vive en `src/lib/helpers.js`: `alarmaEnPalabras` (que compara **por día de
calendario y no por horas de diferencia** — a las 23:00, las 00:30 son mañana aunque
queden noventa minutos), `alarmaEstadoTexto` y `alarmaSonando`.

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

- **Alarmas recurrentes** («todos los martes»). Se apunta una a una. Una alarma repetida
  que se te olvida quitar acaba sonando un domingo, y el coste de que suene cuando no toca
  es mucho mayor aquí que en cualquier otro aviso del sistema.
- **Leer `sensor.mikel_proxima_alarma_2`** (la alarma del Echo) para armar el respaldo
  solo. Se puede y quizá se haga, pero obligaría a poner siempre la alarma hablándole a
  Alexa, que es justo lo que no se hace hoy.
- **La llamada de teléfono como tercer escalón.** El canal existe (`docs/LLAMADAS.md`)
  pero está apagado, y cuesta dinero por llamada.
