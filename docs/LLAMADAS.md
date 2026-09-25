# El teléfono: que Jarvis te llame y puedas contestarle

Todos los canales del proyecto tienen el mismo techo: **hace falta que mires**. Un correo
espera a que abras el buzón; una notificación, a que desbloquees el móvil. Los dos valen
para casi todo, y no valen para lo único que se queda de verdad parado: un arreglo ya
hecho esperando tu permiso para desplegarse.

La llamada es el único canal que no espera a nadie, y en el coche suena por el manos
libres. Este fichero es el canal: qué se evaluó, qué se descartó y por qué, cómo está
montado, qué costó descubrir y qué le falta. **Quién llama y cuándo** vive en
`docs/AVERIAS.md`, que es el flujo que hoy lo usa.

## Estado: el teléfono SUENA, y no por Twilio

Desde el **2026-09-20** el teléfono está vivo, y por un camino que no es el que este
fichero describía. Twilio sigue escrito y apagado (`LLAMADAS=0`); lo que llama hoy es una
**centralita 3CX gratuita** con [claude-phone](https://github.com/theNetworkChuck/claude-phone)
corriendo en `caja`.

Lo que cambia respecto a todo lo que hay debajo en este fichero:

| | Twilio (agosto, nunca encendido) | La centralita (hoy) |
|---|---|---|
| Coste | céntimos por minuto + cuota del número | **cero**: es tráfico interno de la centralita |
| A quién llama | a un teléfono de verdad | a tu extensión en la app de 3CX |
| Quién habla | Jarvis por el puente de voz del backend | **Claude Code corriendo en `caja`** |
| Qué puede hacer | usar las herramientas de Jarvis | mirar la máquina y actuar sobre ella |

Ese tercer punto es el que cambia la naturaleza del canal. Antes la llamada informaba y
preguntaba; ahora al otro lado hay una sesión con acceso real a la máquina que hospeda el
backend, el túnel, la base de datos y n8n. Lo que puede y no puede hacer está escrito en
`telefono/RUNBOOK.md`, que es literalmente el `CLAUDE.md` de su directorio de trabajo.

**El precio de eso es que el canal ya no es solo un canal**: quien alcance
`http://caja:3010` en la LAN puede hacer que Claude Code ejecute lo que quiera en esa
máquina, porque `claude-api-server` lo invoca con `--dangerously-skip-permissions`. Hoy lo
único que lo protege es que ese puerto no sale de la LAN. Ver «Seguridad», abajo.

### Qué motivo suena por dónde

Desde que existe la centralita, no todos los «Hablarlo» suenan por el mismo sitio:

| Motivo | Quién contesta | Botón/disparo |
|---|---|---|
| Permiso de despliegue | Jarvis-GPT, dashboard | «Hablarlo» abre `PantallaLlamada` (`?llamada=1&tipo=despliegue`) |
| Avería de infraestructura (vigilancia) | Jarvis-Claude, centralita | Automática, `_llamar()` desde `/vigilancia/estado` |
| Hallazgo de revisión nocturna / vigilante | Jarvis-Claude, centralita | Botón «Hablarlo» → `POST /revision/{id}/accion` `{"accion":"hablar"}` |
| Aviso de una sesión de Claude Code | Jarvis-Claude, centralita | Botón «Hablarlo» → `POST /sesion/{id}/accion` `{"accion":"hablar"}` |

Los dos últimos son nuevos: antes «Hablarlo» abría el dashboard con GPT igual que el
despliegue. La razón del cambio es que esos dos motivos son justo los que Claude Code
puede investigar de verdad (un issue del propio repo, el estado de una sesión anterior),
mientras que el permiso de despliegue sigue siendo una pregunta de sí/no que no necesita
tocar la máquina. El deep-link al dashboard para `revision`/`sesion` sigue existiendo por
debajo (`_MOTIVOS_LLAMADA`, `GET /llamada/pendiente`) como vía manual si la centralita
está caída — solo se retiró el botón que la ofrecía por defecto.

Los dos nuevos `_llamar()` reusan `_jarvis_contexto_llamada()` tal cual para armar el
`contexto` (el issue entero, o el resumen de la sesión) — es la misma función que ya usaba
la pantalla del navegador, ahora también aprovechada por la centralita.

**Para que Jarvis-Claude tenga las herramientas MCP hace falta un paso manual en `caja`**,
fuera de este repositorio (como el resto de la config de esa máquina): dar de alta
`https://<host-público-del-backend>/mcp/telefono` como servidor MCP remoto en la
configuración de Claude Code de `~/telefono-jarvis/` (fichero de proyecto de
`claude-api-server`), con `Authorization: Bearer <JARVIS_MCP_TELEFONO_TOKEN>` en las
cabeceras — el mismo token que lleva `backend/.env`. Sin esa alta, la llamada suena igual
(el `context` no depende de ello) pero Jarvis-Claude no tiene ninguna herramienta, solo
la máquina.

**Y una cosa que este canal no puede hacer, por construcción:** la centralita vive en
`caja`, la misma máquina que vigila. Puede contarte que el Green está caído, que la web
falla o que el backend murió con la máquina viva. De lo que no puede avisarte nunca es de
que `caja` esté apagada — el teléfono está dentro de lo que vigila. Es el mismo agujero
que ya tenían Grafana y Prometheus, y sigue abierto.

### Quién decide que suene

```
Vigilantes de n8n / sondeos de HA
        │  (en CADA sondeo, vivo o muerto)
        ▼
POST /vigilancia/estado   ◀── aquí están las reglas, en main.py y con tests
        │
        ├─ menos de 3 sondeos fallidos ──▶ silencio
        ├─ 3 seguidos ──▶ aviso al móvil
        └─ 3 seguidos + no es de noche ──▶ _llamar() ──▶ claude-phone ──▶ 3CX ──▶ tu móvil
```

Las tres reglas, y por qué existen las tres:

1. **Un parpadeo no es una avería.** Tres sondeos seguidos, que con un cron de 5 minutos
   son ~15 minutos caído. Un corte de red de 30 segundos no llama.
2. **Una llamada por avería, no una por sondeo.** Sonar cada cinco minutos mientras algo
   sigue roto no añade información y garantiza que dejes de cogerlo.
3. **De noche (00:00–07:00) no suena**, salvo lo marcado `critico`, que hoy son las
   alarmas de respaldo — lo único que tiene que despertarte. El aviso al móvil sí sale
   igual; lo que espera es la llamada. **No hace falta ningún reloj para eso**: como los
   sondeos siguen entrando, el primero de después de las siete encuentra la avería todavía
   viva y llama entonces.

Y la recuperación se cuenta igual que la caída: el vigilante habla en **cada** sondeo,
también cuando todo va bien. Ese sondeo bueno no sobra — es lo que pone el contador a
cero y lo que permite decir «ya ha vuelto». Un vigilante que solo hablara de lo malo
dejaría la avería marcada para siempre y no volvería a llamar por ella nunca.

**La excepción: el backend caído.** Ese sondeo no puede pasar por `/vigilancia/estado`,
porque el sujeto vigilado es quien decidiría. Lo lleva un flujo de n8n que **sí decide**
y llama a la centralita directamente, repitiendo esas tres reglas en pequeño. Es la única
grieta consciente en la frontera de `docs/N8N.md`, y está explicada allí.

### La pantalla de llamada sigue viva

Lo de abajo sobre la pantalla de llamada del dashboard (el botón «Hablarlo» del aviso de
despliegue) **no se sustituye**: es otro canal, lo lanza el usuario y no gasta nada. La
centralita es el canal que empieza la máquina; la pantalla, el que empiezas tú.

## La regla que sostiene todo esto

> **Solo llama lo que no se resuelve sin ti.** No lo urgente, no lo importante: lo que
> se queda parado. Hoy son dos cosas, y ninguna más: el permiso de despliegue y una
> avería que lleva un cuarto de hora sin arreglarse sola.
>
> **Con una excepción que pediste tú (2026-09-23): las llamadas cotidianas**, abajo.

Ya no es el canal más caro en euros —por la centralita no cuesta nada—, pero sigue
siendo el más caro en lo que de verdad escasea: te interrumpe de verdad. Que se haya
vuelto gratis es exactamente el momento en el que hay que apretar más esta regla, no
relajarla: lo único que la mantenía estrecha antes era la factura.
Si algún día llama una segunda cosa, tiene que estar justificada en este fichero. El día
que el teléfono suene por algo que podía haber esperado, dejarás de cogerlo — y con él se
irá también el aviso que sí importaba. Es el mismo fallo que el presupuesto de avisos
previene en el canal de al lado, con la factura más alta.

Y la frontera de siempre: **la llamada informa y pregunta, pero no decide**. Lo que se
hable por teléfono acaba en `_despliegue_decidir` como cualquier botón, con su PATCH
condicional. Quien llama no se salta la puerta, la usa.

### Las llamadas cotidianas (desde el 2026-09-23)

Tras la primera llamada de prueba, Mikel pidió que el teléfono sonara también por cosas
del día a día: *«oye, que sepas que llevas un día sin mandar nada al LA»*. Es justo lo
que la regla de arriba excluye, y se hizo igualmente porque la decisión es suya — pero
con los frenos que sostienen esa regla, para que lo cotidiano no gaste el teléfono:

- **Va detrás del aviso, nunca en su lugar.** Primero sale la notificación de siempre y,
  si la regla lo pide, además suena. Si la llamada falla, lo que había que decir ya ha
  llegado (`_llamada_cotidiana_segura`, que no puede liberar el aviso ya entregado).
- **Tú eliges qué reglas**, una a una, en la pestaña Avisos de la zona dev (columna
  `avisos_reglas.llamar`). Solo pueden las del catálogo `REGLAS_LLAMABLES` (ingesta,
  reloj, salir, no_llegas, madrugón, malestar, hueco para entrenar, al salir de casa, PC
  encendido). Nacieron encendidas las siete que se eligieron; `al_salir` y
  `pc_encendido`, apagadas.
- **Tope diario** (`LLAMADAS_COTIDIANAS_DIA`, 2 por defecto), contado en
  `avisos_llamadas`. Las averías no lo gastan. Sin poder contar, no se llama.
- **Nunca de noche ni pasada `AVISOS_HORA_SILENCIO`** (22:00). No se aplaza: una llamada
  de las 23:00 dicha a las 07:00 ya habla de otra cosa, y el aviso ya salió.
- **Una llamada por aviso**: la reserva en `avisos_llamadas` va por el id del aviso, y el
  409 contra la clave es la respuesta a «¿ya se llamó?».
- **Solo por la centralita**, nunca Twilio: lo cotidiano no justifica pagar por minuto.
- El `contexto` le dice a Jarvis-Claude que **no es una avería** y que no toque nada en
  la máquina: sin eso, quien descuelga con acceso de shell se pondría a buscar qué
  arreglar.

Si en unas semanas dejas de coger estas llamadas, la solución no es bajar el tope: es
apagar las reglas que no aportan, porque el coste de verdad es que dejes de coger
también la de la avería.

### Si no lo coges (desde el 2026-09-25)

Ese día Jarvis llamó, no se cogió, y al devolverle la llamada **su extensión daba
comunicando**. La causa, en claude-phone: acepta `timeoutSeconds` pero no lo usa, así
que la llamada sonaba hasta que el 3CX la desviaba a tu buzón; el buzón «descuelga», y
Jarvis se ponía a conversar con él —hasta 20 turnos de «¿sigues ahí?», ~12 minutos—
con la línea cogida. Para el backend, además, eso era una llamada contestada.

Lo que queda grabado en el buzón lo confirma: **la hora que dice el propio 3CX y después
silencio**, salpicado de «no te he oído». El mensaje de Jarvis no está: lo dijo nada más
descolgar, encima del saludo del buzón, antes de que empezara a grabar. De ahí el
`delaySeconds` de la llamada del buzón.

Mikel pidió entonces lo que hace un humano: **si no lo coges, vuelve a llamar; y si
tampoco, deja el mensaje en el buzón.** Queda así:

```
llamada 1 (conversación, suena TELEFONO_TIMBRE_SEG = 25 s y cuelga)
   │ no cogida (no_answer o comunicando)
   ▼  espera TELEFONO_REINTENTO_SEG = 60 s
llamada 2 (igual que la 1)            ← TELEFONO_INTENTOS = 2 en total
   │ no cogida
   ▼  espera 60 s
llamada 3 al buzón: modo announce, suena 90 s (TELEFONO_BUZON_TIMBRE_SEG) para que el
3CX la desvíe, espera 8 s (TELEFONO_BUZON_ESPERA_SEG) al saludo del buzón, dice el
mensaje —«te he llamado 2 veces y no lo has cogido…» + lo que te iba a decir— y cuelga
```

Lo lleva `_insistir` (`backend/main.py`), en un hilo aparte, preguntándole a claude-phone
cómo acabó cada llamada (`GET /api/call/{id}`). Vale para **todo** lo que llama por la
centralita: averías, «Hablarlo» y cotidianas. Las reglas de este fichero siguen
contando la serie como **una** llamada: una por avería, una por aviso, y el tope diario
de las cotidianas no se gasta en reintentos.

**Cuándo NO insiste**, a propósito:

- **La has cogido** (aunque sea a la segunda): se acabó.
- **La has rechazado** (`declined`, el 603): colgarle a quien ha rechazado para volver a
  llamarle es lo que hace que se deje de coger el teléfono.
- **Falla la centralita** (SIP sin registrar, 503…): insistir no lo arregla.
- **No se sabe cómo acabó** (404, o el sondeo no ve el final): ante la duda, no.
  Es también lo que pasa sin los parches de abajo, así que sin ellos todo se queda
  exactamente como antes.

**Tres cosas fuera de este repositorio que tienen que estar, o nada de esto funciona:**

1. **Los parches 7 y 8 de claude-phone** (`telefono/PARCHES.md`): colgar a los
   `timeoutSeconds`, que `GET /api/call/{id}` encuentre la llamada (hoy da 404 siempre
   por un fallo del original) y diga el motivo, `delaySeconds`, y colgar tras dos turnos
   sin oír a nadie — este último es lo que evita que la línea de Jarvis se quede
   comunicando aunque algo más falle.
2. **El desvío a buzón de tu extensión en el 3CX entre 25 y 90 s** (en torno a 40). Si
   salta antes de que Jarvis cuelgue, el buzón coge la primera y cuenta como contestada.
3. **El flujo de n8n del backend caído** llama a la centralita por su cuenta y no pasa por
   aquí: no insiste. Si se quiere lo mismo ahí, va en el flujo (repositorio HomeLab).

## Lo que se evaluó (agosto de 2026)

La pregunta de partida era si esto se podía hacer gratis. **Se puede, pero solo en un
sentido**: que te lea un mensaje y cuelgue. Poder contestar hablando no tiene versión
gratuita seria.

| Opción | Llama de verdad | Puedes contestar | Coste | Veredicto |
|---|---|---|---|---|
| **CallMeBot** por Telegram | Sí, llamada de Telegram | **No** | Gratis | Descartada por unidireccional. Era la mejor opción gratis |
| **CallMeBot** por teléfono (`call.php`) | Sí | No | ~1 $/mes por 5 llamadas | Descartada: paga y encima unidireccional |
| **Twilio** | Sí | **Sí** | Céntimos/min (sin número: ver abajo) | **Elegida** |
| Plivo / Telnyx | Sí | Sí | Algo más barato por minuto | Equivalentes; Twilio gana por documentación |
| Bot API de Telegram / WhatsApp | — | — | Gratis | **No permiten** llamadas de voz a un bot |
| Asterisk / FreeSWITCH autoalojado | Sí | Sí | Licencia gratis, pero hace falta un proveedor SIP igual | Descartada: mantener una centralita para dos avisos por semana |
| Notificación crítica de HA | No (suena aunque esté en silencio) | No | Gratis | Es lo que ya había. Buena red de seguridad, no sustituye |

Detalles útiles de CallMeBot por si algún día compensa como respaldo gratuito: endpoint
`https://api.callmebot.com/start.php?user=@usuario&text=...&lang=es-ES-Standard-A`,
activación mandando `/start` a [@CallMeBot_txtbot](https://t.me/CallMeBot_txtbot), y dos
límites duros del plan gratuito: **256 caracteres** de texto y **30 segundos** de llamada.

### Los dos niveles de Twilio, y por qué se fue al segundo

- **Nivel 1 — `<Gather>`**: la llamada dice el aviso y pregunta «di *sí* o pulsa 1». La
  respuesta llega a un webhook. Son ~100 líneas y funciona en el coche.
- **Nivel 2 — Media Streams**: Twilio abre un WebSocket con el audio crudo y se enchufa a
  Whisper + Jarvis + ElevenLabs, que ya estaban montados en el proyecto. Es una
  conversación de verdad.

Se eligió el 2. El argumento que lo decidió no es la fidelidad: es que **el nivel 1 es un
callejón**. Un `<Gather>` solo sabe responder la pregunta que ya venía hecha, y en el
momento en que quieras preguntar «¿y qué has cambiado exactamente?» hay que tirarlo y
empezar de nuevo. El nivel 2 reutiliza el cerebro que ya existía.

## Cómo está montado

```
Twilio  ──WebSocket (μ-law 8 kHz, tramas de 20 ms)──▶  WS /telefono/media
                                                            │
                                                ┌───────────┴───────────┐
                                                │  VAD por energía      │  ¿has terminado?
                                                │  Whisper              │  audio → texto
                                                │  _jarvis_turno        │  el cerebro de siempre
                                                │  ElevenLabs (ulaw)    │  texto → audio
                                                └───────────┬───────────┘
                                                            ▼
                                                 vuelve por el mismo WebSocket
```

Al otro lado está **el Jarvis de siempre**: el mismo `_jarvis_turno`, las mismas
herramientas y la misma frontera de confirmación que en el chat y en el modo llamada del
navegador. No hay un asistente nuevo, hay un **transporte** nuevo, y eso es deliberado:
dos asistentes que responden distinto según por dónde entres son dos asistentes que
mantener.

Todo vive en `backend/main.py`, sección `# ── El puente de voz del teléfono ──`, más
`# ── El teléfono: cuando el aviso no puede esperar ──` (el canal de salida, `_llamar`).

### Las cuatro decisiones que hay que entender antes de tocarlo

- **Es la única parte asíncrona del backend.** El resto de `main.py` no usa `asyncio`, y
  no es un descuido: los endpoints hacen E/S de bloque y viven mejor en el pool de hilos
  de FastAPI. Un WebSocket no se puede servir así. Todo lo síncrono que se llama desde
  dentro del puente va envuelto en `asyncio.to_thread`; llamarlo directo bloquearía el
  bucle de eventos y con él el audio de la llamada, que **se oye como un corte**.

- **El audio del teléfono es μ-law a 8 kHz**, que no es lo que come ninguno de los dos
  extremos. Se convierte a mano (`_ulaw_a_pcm16`, tabla G.711) en vez de con `audioop`.
  A la vuelta no hace falta convertir nada: a ElevenLabs se le pide `ulaw_8000`
  directamente, que además lo hace mejor porque tiene la señal sin comprimir delante.

- **Quién habla lo decide el silencio.** No hay «pulsa para hablar» en una llamada: se
  mide la energía de lo que entra y se da el turno por terminado tras `VOZ_SILENCIO_MS`
  de calma. Es un VAD pobre a propósito — el bueno vive en ElevenLabs y cuesta, y para
  «sí, despliégalo» éste llega de sobra. `VOZ_MIN_HABLA_MS` filtra la tos y el golpe al
  móvil, que si no abren un turno entero contra Whisper.

- **Un «sí» no lo interpreta el modelo.** Antes de pasarle nada a Jarvis se mira si lo
  que has dicho es la respuesta a la pregunta que motivó la llamada (`_sio_no`, lista
  cerrada). Hacer que el permiso de despliegue dependa de que el modelo elija bien la
  herramienta metería un fallo posible justo en la puerta que toca producción. **Ante la
  duda no se despliega**: de los dos errores, ése es el único que se puede deshacer solo.
  Por eso `_sio_no` mira solo las tres primeras palabras y el «no» gana al «sí» — «no,
  despliega luego» es un no.

## La pantalla de llamada (el canal que está vivo)

```
POST /revision/pr-listo
      │
      ├─ deja el aviso en el móvil con TRES botones:
      │     «Desplegar»  «Ahora no»  «Hablarlo» ──┐
      │                                            │ abre
      ▼                                            ▼
  (y llama por teléfono, si LLAMADAS=1)     dashboard/?llamada=1
                                                   │
                                          PantallaLlamada (pantalla completa)
                                                   │ botón verde = el gesto que
                                                   │ desbloquea el audio en iOS
                                                   ▼
                                          iniciarLlamada(apertura)
                                                   │
                                       el modo llamada de siempre
```

Las piezas:

| Pieza | Dónde | Qué hace |
|---|---|---|
| Botón «Hablarlo» | `_acciones_aviso`, `backend/main.py` | El tercer botón del aviso. `action: "URI"` es el nombre reservado de la app de HA para «esto abre un enlace» |
| `FRONTEND_URL` | config del backend | La URL del dashboard. Vacía, el botón no sale y el aviso sigue teniendo los otros dos |
| `GET /despliegue/pendiente` | `backend/main.py` | Qué anunciar al descolgar. **Solo lee**: la decisión sigue pasando por `POST /despliegue/{id}/accion` |
| `_apertura_despliegue()` | `backend/main.py` | La frase de apertura, **compartida con el teléfono** |
| `llamadaEntranteDeUrl`, `aperturaDeLlamada` | `src/lib/voz.js` | Lógica pura: si esta carga es una llamada, y qué se dice si no hay nada pendiente |
| `PantallaLlamada` | `src/components/Dashboard.jsx` | La pantalla de descolgar |
| `iniciarLlamada(apertura)` | ídem | El modo llamada de siempre, ahora con primera frase opcional |

### Las tres decisiones que hay que entender antes de tocarlo

- **El botón verde no es decoración: es un requisito del navegador convertido en UX.**
  iOS solo desbloquea el audio dentro de un gesto del usuario, así que la llamada **no
  puede** arrancar sola al cargar la página. Hacía falta un toque de todas formas, y
  pedirlo con un botón de descolgar es lo que hace que esto se parezca a coger el
  teléfono en vez de a abrir una web. Por eso `contestarLlamada()` no tiene un solo
  `await` antes de hablar — igual que `iniciarLlamada` saluda desde dentro del toque.

- **La frase de apertura la escribe el backend, no el navegador.** `_apertura_despliegue`
  la comparten el teléfono y la pantalla. Escrita en cada sitio, Jarvis contaría lo mismo
  de dos maneras distintas según por dónde le cogieras, que es exactamente lo que evita
  tener un solo cerebro detrás de varios transportes.

- **La apertura entra en el historial.** Es Jarvis diciendo algo, y sin meterla, tu «sí,
  despliégalo» llegaría al modelo **sin la pregunta a la que contesta**.

- **No se puede descolgar hasta que llega el permiso de voz**, y por eso el botón verde
  nace en «Conectando…». Esto costó una sesión entera de buscar donde no era: la voz de
  ElevenLabs «no funcionaba» —siempre sonaba la del navegador— y **no había nada roto**.
  El backend escala a cero, el aviso llega cuando hace horas que nadie lo toca, y la
  primera petición despierta la máquina: 10-15 segundos. Tú descuelgas en uno.
  `iniciarLlamada` mira el permiso **una sola vez y dentro del gesto** (no puede esperar
  sin romper el desbloqueo de audio de iOS), no lo encuentra, y la llamada entera sale con
  la voz del navegador. Sin error, sin log y sin nada que mirar. Se espera en la pantalla
  de llamada, que es donde esperar no molesta —un teléfono también tarda en dar línea— con
  un tope de `VOZ_ESPERA_MAX_MS`: quedarse sin poder contestar sería peor que contestar con
  la voz fea.

  **Moraleja para la próxima**: cuando la voz de pago «no funciona», comprueba primero
  **cuándo** se pide el permiso, no si ElevenLabs responde. Aquí ElevenLabs respondía
  perfectamente por HTTP y por WebSocket; lo que fallaba era el reloj.

Y una que se hereda del teléfono y no se relaja: **la pantalla informa y pregunta, pero
no decide.** `GET /despliegue/pendiente` solo lee; el «sí» acaba en `_despliegue_decidir`
con su PATCH condicional, como el botón.

### Lo que le falta

- **El aviso caducado.** Si decides desde el botón y luego abres «Hablarlo», la pantalla
  se abre con la frase de respaldo («ya no hay nada esperando permiso»). Correcto pero
  pobre: podría decir qué se decidió.
- **La primera prueba en el coche.** Está probado el enlace, la pantalla y la apertura,
  pero **nadie lo ha usado conduciendo**, que es el único sitio donde se sabrá si el
  volumen, el Bluetooth y los turnos por silencio aguantan con ruido de carretera.
- **Barge-in**: sigue pendiente, y sigue siendo el mismo micrófono que el del teléfono
  (`docs/JARVIS_VOZ.md`, fases 5 a 7). No se ha movido.

## Lo que cerró el teléfono (agosto de 2026)

Tres cosas, ninguna del código. Se dejan escritas porque cada una costó una tarde y
porque las tres seguirán siendo verdad dentro de un año.

- **La cuenta de prueba de Twilio es un callejón sin salida en España.** Para llamar hace
  falta un `From` válido, y para tener uno sin comprar número hay que verificar el móvil
  como *Verified Caller ID*. Las dos únicas vías de verificación están cerradas a la vez:
  **por llamada** no lo permiten las cuentas trial (hay que pagar antes), y **por SMS**
  España es país restringido. Además el trial bloquea el saldo, los permisos geográficos
  de voz y —lo que más duele para depurar el puente— **el registro de alertas**, que es
  donde se leerían los fallos del media stream. Las tres consultas devuelven el mismo
  `20003: This feature is not available on a Trial account`.

- **El regulador español prohíbe usar móviles 6XY y 71Y–74Y como Caller ID** en llamadas
  hacia España, y los operadores pueden bloquear las que no cumplan. O sea que el plan de
  «no compres número, usa el tuyo como `From`» —el único que bajaba de un euro al mes—
  puede quedar bloqueado por el operador aunque pagues el upgrade. La norma persigue
  llamadas comerciales y esto es llamarte a ti mismo, pero el bloqueo va por patrón de
  prefijo, no por intención.

- **Comprar número no cabe en el presupuesto.** La cuota sola (~1-2 €/mes) ya se lleva el
  límite de un euro, antes de gastar un solo minuto.

### Las alternativas gratuitas, y por qué ninguna sirve

Se buscaron a fondo antes de rendirse. La conclusión es una sola frase, y es la que hay
que recordar: **nada hace sonar un teléfono gratis sin obligarte a pagar infraestructura
encendida.**

| Alternativa | Por qué no |
|---|---|
| **Telegram** | Los bots no pueden llamar. La única vía es un *userbot* con `tgcalls`, y su propio README dice que las llamadas privadas uno a uno **no están en la versión publicada**: solo hay voice chats de grupo, y unirse a uno **no hace sonar el teléfono**. Además pide una segunda cuenta con su número y compilar WebRTC en el contenedor |
| **WhatsApp** | La Calling API existe, pero exige una cuenta de empresa con verificación de Meta y cobra las salientes por minuto igual que Twilio. Montar una empresa para llamarte a ti mismo. Dato que sí sirvió: **las entrantes son gratis** |
| **SIP (Linphone)** | La mejor idea de todas y la que peor acaba. SIP-a-SIP no toca la red telefónica y no cuesta nada; Linphone da cuentas gratis y soporta CallKit, o sea pantalla de llamada de verdad. Pero SIP y RTP van por **UDP**, y en Fly.io UDP **exige una IPv4 dedicada** (~2 $/mes) y no funciona sobre IPv6 público, más un registro persistente que pelea con `min_machines_running = 0`. Sale **más caro que Twilio** y con diez veces más piezas |

Y de ahí la moraleja que explica por qué Twilio encajaba en su día: **este backend escala
a cero y solo habla HTTP y WebSocket sobre el 443.** Twilio cabía porque la llamada la
despierta una petición HTTP y el audio viaja por un WebSocket normal. Cualquier
alternativa gratuita necesita UDP y una conexión siempre viva, y lo que ahorras en
minutos lo pagas en máquina. Si algún día se reabre esto, **empieza por ahí**: la
pregunta no es cuánto cuesta el minuto, es qué exige el transporte.

## Lo que costó descubrir

Cosas que no estaban en ningún sitio y que costaría volver a averiguar.

- **`JarvisTurno.rol` valida `user`/`assistant`, no `usuario`/`asistente`.** Es la única
  parte del proyecto donde el español no manda, porque son los roles de la API de OpenAI.
  El puente los escribía en español y habría reventado **en la segunda frase de cada
  llamada** — la primera va sin historial, así que el fallo esperaba a que la conversación
  fuese bien. Corregido, con un comentario en el sitio para que no vuelva.

- **`audioop` desaparece en Python 3.13.** Está en la stdlib de la 3.11 que usa el
  Dockerfile y habría sido lo cómodo, pero ata el backend a una versión por treinta
  líneas de tabla. Está escrita a mano y **verificada contra `audioop`: cero
  discrepancias en los 256 valores**. El test lleva los valores fijos, no una comparación
  en vivo, justo para que sobreviva a la actualización.

- **`uvicorn` sin extras NO trae WebSockets.** `requirements.txt` fijaba `uvicorn==0.46.0`
  a secas, así que `/telefono/media` habría respondido 404 en producción con todo lo
  demás funcionando igual — el peor de los fallos posibles: silencioso y solo en el camino
  nuevo. Añadido `websockets==15.0.1` con esa explicación al lado.

- **La firma de Twilio se puede probar de verdad.** Su documentación publica un vector de
  ejemplo (URL, campos, token `12345`, firma `RSOYDt4T1cUTdK1PDd93/VVr8B8=`) y el test lo
  usa. Comprobar mi HMAC contra mi HMAC no habría probado nada más que que la función es
  determinista.

- **No hay que configurar nada en la consola de Twilio.** El webhook viaja en la propia
  petición que crea la llamada (parámetro `Url`), así que el número comprado no necesita
  tener nada asociado. Esto no es obvio leyendo su documentación, que empuja a
  configurarlo en el número.

- **El teléfono es lo que hace útil el trabajo a medias de la voz.** `docs/JARVIS_VOZ.md`
  lleva las fases 1-4 hechas y el micrófono pendiente desde hace semanas. Este camino no
  necesita ese micrófono: el audio lo trae Twilio.

## Seguridad

Dos superficies nuevas expuestas a internet. Ninguna puede llevar nuestros tokens, porque
quien las llama es Twilio.

- **`POST /telefono/voz`** es público —lo llama Twilio sin cabeceras nuestras— y lo que
  devuelve abre un puente de voz contra Jarvis. Lo protege la **firma de Twilio**
  (HMAC-SHA1 sobre la URL más los campos del formulario en orden alfabético,
  `_firma_twilio_ok`), comparada con `hmac.compare_digest` como todas las credenciales
  del proyecto. Sin el token configurado no vale ninguna firma: fail-closed, igual que
  `_token_ok`.

- **`WS /telefono/media`** no puede llevar token en cabecera —un WebSocket que abre
  Twilio no trae las nuestras—, así que lo autentica un **JWT firmado en la query**
  (`_contexto_llamada`) que dice qué se va a decir y sobre qué decisión va. Caduca en
  cinco minutos y solo vale para una llamada.

  Lleva `purpose: "llamada"` porque lo exige la invariante 2 de `CLAUDE.md`: todos los
  JWT se firman con la misma `SECRET_KEY`, y es ese claim lo que impide que este token
  valga como sesión de usuario — y, al revés, que el token del dashboard o el `state` del
  OAuth de Microsoft (que viaja en la barra de direcciones) abran el teléfono. Hay tests
  para las dos direcciones.

El texto que se dice por teléfono sale de `detalle`, que lo escribe un workflow nuestro.
**Si algún día una avería la reporta algo de fuera**, ese texto acabará en el prompt de un
modelo con herramientas: habrá que envolverlo como DATO, igual que el enunciado de Alud
en `build_cowork_instruction`.

- **`POST /mcp/telefono`** es el servidor MCP (Streamable HTTP, JSON-RPC 2.0) que
  Jarvis-Claude consume desde `caja` para tener las mismas herramientas de consulta que
  Jarvis-GPT, más un puñado de acciones de bajo riesgo (`telefono/RUNBOOK.md` tiene la
  lista exacta). Protegido con `JARVIS_MCP_TELEFONO_TOKEN` (`Authorization: Bearer`,
  fail-closed como todo token de servicio). La lista blanca de herramientas es cerrada
  (`_MCP_SERVIDOR_HERRAMIENTAS` en `backend/main.py`) y deja fuera a propósito todo lo que
  toca producción, el repositorio o el calendario (`desplegar`, `mcp_*`,
  `encargar_a_una_sesion`, `responder_a_la_sesion`, `arreglar_revision`, `crear_evento`,
  `cobrar_entrenamiento`...). La confirmación hablada reusa `_jarvis_confirma()` tal cual:
  si una herramienta la exige con los argumentos que se han pedido (por ejemplo
  `casa_ordenar` sobre una cerradura), el servidor la RECHAZA con un error — no hay botón
  de confirmar al otro lado de una llamada, así que no se ejecuta solo por venir de ahí.

## Coste

- **Twilio, sin comprar número**: el presupuesto de este canal es **menos de un euro al
  mes**, y comprar un número (~1-2 €/mes solo la cuota) ya se lo come. La salida es no
  comprarlo: Twilio permite verificar tu propio móvil como **Verified Caller ID** y
  usarlo como `From`, así que la llamada sale «de tu propio número» y solo pagas los
  minutos. **El presupuesto depende de que llamar siga siendo raro**, y ése es justo el
  motivo de la regla de arriba: a ~4 llamadas al mes de dos minutos (que es el ritmo real
  de un CI que se rompe en `main`) salen unos 0,70-1 €/mes; a dos o tres por semana se
  va a ~2 €/mes y se sale del presupuesto. El código no distingue los dos modos —
  `TWILIO_NUMERO` es el `From`,
  sea comprado o verificado. La contrapartida: en la pantalla del móvil la llamada
  aparece como si te llamaras tú mismo, no como un número identificable de Jarvis. La
  tarifa exacta a móvil español varía por operador: mírala en su calculadora, no la des
  por sabida.
- **Lo de dentro es lo que se dispara si se descuida**: cada turno de la llamada es una
  transcripción de Whisper, una vuelta de Jarvis (con sus herramientas) y una síntesis de
  ElevenLabs. De ahí `LLAMADA_MAX_SEG`, que es un **tope duro**: una llamada que no se
  cierra sigue cobrando por minuto y sigue teniendo un modelo al otro lado.

## Configurarlo

En [twilio.com](https://www.twilio.com): crea la cuenta, apunta el Account SID y el Auth
Token, y **verifica tu móvil como Verified Caller ID** (*Phone Numbers → Verified Caller
IDs*: metes tu número, te llaman con un código, listo). Ese número verificado hace de
`From` y te ahorra comprar uno. En `backend/.env`:

```bash
LLAMADAS=1                  # nace APAGADO: hace sonar un teléfono de pago
TWILIO_ACCOUNT_SID=AC...
TWILIO_AUTH_TOKEN=...       # firma los webhooks; sin él no vale ninguna firma
TWILIO_NUMERO=+34...        # el From: tu propio móvil verificado (o un número comprado)
TWILIO_MI_NUMERO=+34...     # tu móvil (sí, puede ser el mismo de arriba)
BACKEND_URL=https://...     # la URL pública del backend, para que Twilio vuelva.
                            # No se deduce de la petición: la llamada la empieza el backend
```

Ajustes finos (`LLAMADA_TTL`, `LLAMADA_MAX_SEG`, `VOZ_SILENCIO_MS`, `VOZ_UMBRAL_RMS`,
`VOZ_MIN_HABLA_MS`) documentados uno a uno en `backend/.env.example`.

## Probarlo

```bash
# Hace sonar el teléfono de verdad, sin romper el CI ni desplegar nada
curl -X POST "$BACKEND_URL/revision/pr-listo" -H "X-Auth-Token: $REVISION_TOKEN" \
     -H "Content-Type: application/json" -d '{"pr":122}'
```

Para probar el aviso sin gastar una llamada, apaga `LLAMADAS`.

## Lo que le falta

- **El routing de `revision`/`sesion` hacia la centralita no se ha probado en producción.**
  El código está cubierto por tests (`tests/backend/test_revision_hablar.py`,
  `test_sesion_hablar.py`, `test_mcp_telefono.py`), pero la primera vez que suene de
  verdad por un hallazgo de la revisión nocturna o un aviso de sesión es la prueba que
  falta — igual que pasó con el canal de averías antes de confirmarse. Y el servidor MCP
  (`/mcp/telefono`) solo se ha probado con `curl` a mano: falta que Claude Code en `caja`
  lo conecte de verdad y llame a una herramienta en caliente.

- **Interrumpirle (barge-in).** Mientras Jarvis piensa o habla, el audio que entra se
  tira. Es exactamente lo que también le falta al modo llamada del navegador
  (`docs/JARVIS_VOZ.md`, fases 5 a 7) y **se resolverá en los dos sitios a la vez o en
  ninguno**: hacerlo aquí aparte sería mantener dos micrófonos distintos.

- **El puente entero no se ha probado contra Twilio real.** Están probados todos los
  trozos que se pueden probar sin él —μ-law, VAD, cabecera WAV, firma, contexto firmado,
  `_sio_no`—, pero el bucle del WebSocket necesita a Twilio al otro lado mandando tramas.
  **La primera llamada real es la prueba que falta.** Y con el modo sin número hay una
  incógnita más: el `From` y el `To` son el mismo número (te llamas a ti mismo), y algún
  operador podría tratarlo raro — mandarlo al buzón, no hacerlo sonar. Si pasa, el plan B
  es verificar como caller ID otro número propio distinto (el fijo de casa, una segunda
  SIM), y el plan C, comprar el número y asumir la cuota.

- **Latencia sin medir.** Cada turno son Whisper + Jarvis + ElevenLabs en serie. Con los
  tiempos medidos del modo llamada del navegador (~2 s charlando, ~5 s con herramienta)
  esto debería quedarse alrededor de esos números más la ida y vuelta de Twilio, pero
  está **sin medir**. El puente no retransmite el texto según se genera, como sí hace
  `/jarvis/voz`: se espera al turno completo antes de sintetizar. Ahí hay un segundo o
  dos que ganar el día que moleste.

- **No hay llamada entrante.** Hoy solo llama el backend. Que puedas llamar tú al número
  y que te conteste Jarvis es casi gratis desde aquí (el mismo `/telefono/voz` sin `ctx`,
  con un TwiML que no diga nada al empezar), pero abre una superficie nueva: cualquiera
  que marque ese número hablaría con un asistente que tiene herramientas. Haría falta
  filtrar por el número que llama, como mínimo.
