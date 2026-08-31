# El teléfono: que Jarvis te llame y puedas contestarle

Todos los canales del proyecto tienen el mismo techo: **hace falta que mires**. Un correo
espera a que abras el buzón; una notificación, a que desbloquees el móvil. Los dos valen
para casi todo, y no valen para lo único que se queda de verdad parado: un arreglo ya
hecho esperando tu permiso para desplegarse.

La llamada es el único canal que no espera a nadie, y en el coche suena por el manos
libres. Este fichero es el canal: qué se evaluó, qué se descartó y por qué, cómo está
montado, qué costó descubrir y qué le falta. **Quién llama y cuándo** vive en
`docs/AVERIAS.md`, que es el flujo que hoy lo usa.

## La regla que sostiene todo esto

> **Solo llama lo que se queda parado hasta que contestes.** No lo urgente, no lo
> importante: lo BLOQUEADO. Hoy eso es exactamente una cosa, el permiso de despliegue.

Es el canal más caro que hay aquí: cuesta dinero por llamada y te interrumpe de verdad.
Si algún día llama una segunda cosa, tiene que estar justificada en este fichero. El día
que el teléfono suene por algo que podía haber esperado, dejarás de cogerlo — y con él se
irá también el aviso que sí importaba. Es el mismo fallo que el presupuesto de avisos
previene en el canal de al lado, con la factura más alta.

Y la frontera de siempre: **la llamada informa y pregunta, pero no decide**. Lo que se
hable por teléfono acaba en `_despliegue_decidir` como cualquier botón, con su PATCH
condicional. Quien llama no se salta la puerta, la usa.

## Lo que se evaluó (agosto de 2026)

La pregunta de partida era si esto se podía hacer gratis. **Se puede, pero solo en un
sentido**: que te lea un mensaje y cuelgue. Poder contestar hablando no tiene versión
gratuita seria.

| Opción | Llama de verdad | Puedes contestar | Coste | Veredicto |
|---|---|---|---|---|
| **CallMeBot** por Telegram | Sí, llamada de Telegram | **No** | Gratis | Descartada por unidireccional. Era la mejor opción gratis |
| **CallMeBot** por teléfono (`call.php`) | Sí | No | ~1 $/mes por 5 llamadas | Descartada: paga y encima unidireccional |
| **Twilio** | Sí | **Sí** | Número ~1-2 €/mes + céntimos/min | **Elegida** |
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

## Coste

- **Twilio**: el número son un par de euros al mes y la llamada, céntimos por minuto. A
  dos o tres avisos por semana no llega a un café al mes. La tarifa exacta a móvil español
  varía por operador: mírala en su calculadora, no la des por sabida.
- **Lo de dentro es lo que se dispara si se descuida**: cada turno de la llamada es una
  transcripción de Whisper, una vuelta de Jarvis (con sus herramientas) y una síntesis de
  ElevenLabs. De ahí `LLAMADA_MAX_SEG`, que es un **tope duro**: una llamada que no se
  cierra sigue cobrando por minuto y sigue teniendo un modelo al otro lado.

## Configurarlo

En [twilio.com](https://www.twilio.com): compra un número con voz y apunta el Account SID
y el Auth Token. En `backend/.env`:

```bash
LLAMADAS=1                  # nace APAGADO: hace sonar un teléfono de pago
TWILIO_ACCOUNT_SID=AC...
TWILIO_AUTH_TOKEN=...       # firma los webhooks; sin él no vale ninguna firma
TWILIO_NUMERO=+34...        # el número que compras
TWILIO_MI_NUMERO=+34...     # tu móvil
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

- **Interrumpirle (barge-in).** Mientras Jarvis piensa o habla, el audio que entra se
  tira. Es exactamente lo que también le falta al modo llamada del navegador
  (`docs/JARVIS_VOZ.md`, fases 5 a 7) y **se resolverá en los dos sitios a la vez o en
  ninguno**: hacerlo aquí aparte sería mantener dos micrófonos distintos.

- **El puente entero no se ha probado contra Twilio real.** Están probados todos los
  trozos que se pueden probar sin él —μ-law, VAD, cabecera WAV, firma, contexto firmado,
  `_sio_no`—, pero el bucle del WebSocket necesita a Twilio al otro lado mandando tramas.
  **La primera llamada real es la prueba que falta.**

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
