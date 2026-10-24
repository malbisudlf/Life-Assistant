# Los parches de claude-phone

[claude-phone](https://github.com/theNetworkChuck/claude-phone) se instaló en `caja` el
2026-09-20 desde el repositorio original, y **no funciona tal cual para lo que hace aquí**.
Estos son los doce cambios que hubo que hacerle (el 12, aplicado el 2026-09-27), con el
síntoma que resuelve cada uno, más un decimotercero que no toca su código sino el
`docker-compose.yml` que genera (ver «El parche 13» abajo), un decimocuarto, aplicado el
2026-10-06, que reintenta el registro de la extensión si se pierde (ver «El parche 14»),
y el 15 y el 16, aplicados el 2026-10-13: Claude piensa mientras suena la frase de
espera, y se le puede interrumpir mientras habla (ver «Los parches 15 y 16»). El 17
(2026-10-15) deja de adivinar el orden de los bytes del audio, que en el coche se
adivinaba mal y Jarvis dejaba de saber cuándo hablabas (ver «El parche 17»). Y el 18, el
mismo día: la llamada lee el briefing entero de un tirón (ver «El parche 18»). Y el 19,
también el 2026-10-15: un solo proceso de Claude por llamada en vez de uno por turno, y lo
que ya está mirado (agenda, tareas, recordatorios) metido al descolgar (ver «El parche 19»).
Y el 20 (2026-10-17): la llamada lee también la semana, el correo y las tareas, y lo que
Jarvis propone se confirma diciendo sí o no, sin que lo decida Claude (ver «El parche 20»).

> **Viven en `~/.claude-phone-cli/`, que es un clon del repositorio de
> NetworkChuck, no de éste. No están versionados en ningún sitio.** Un
> `claude-phone update` —o borrar y reinstalar— se los lleva todos por delante, y el
> síntoma no es un error: es que Jarvis vuelve a hablar en inglés y deja de contestarte.
> Este fichero existe para poder rehacerlos. Si algún día hay que tocar mucho más, lo que
> toca es un *fork*, no seguir parcheando a mano.

## Los doce

| # | Fichero | Qué se cambió | Sin el parche |
|---|---|---|---|
| 1 | `cli/lib/docker.js` | Escribe `SIP_AUTH_PASSWORD` y `SIP_AUTH_USERNAME`, no solo `SIP_PASSWORD` | La voice-app lee `SIP_AUTH_PASSWORD`, no lo encuentra y **se registra con las credenciales de ejemplo del repositorio original** |
| 2 | `claude-api-server/server.js` | `CLAUDE_MODEL` pasa a `claude-sonnet-5-5` (era `claude-sonnet-5` hasta el 2026-10-12; ver «El parche 2» abajo) | Invocaba `claude-sonnet-4-20250514`, **retirado en junio de 2026**: toda respuesta era un error |
| 3 | `voice-app/lib/{tts-service,conversation-loop,sip-handler}.js` | Las URLs de audio usan `HTTP_PORT` en vez de `3000` a fuego | Aquí el 3000 lo ocupa Grafana: FreeSWITCH le pedía los audios a Grafana y la llamada **descolgaba en silencio** |
| 4 | `voice-app/lib/*` | Todo el texto al español, Whisper con `language: 'es'`, despedidas en español y TTS con `eleven_flash_v2_5` | Jarvis saludaba en inglés, `eleven_turbo_v2` es **solo inglés**, y Whisper intentaba entender el español como si fuera inglés |
| 5 | `voice-app/lib/audio-fork.js` | Detector de fin de frase por percentil sobre ventana deslizante | El umbral fijo (RMS 650) daba por voz el ruido de la línea (3.300-4.700): **el turno no se cerraba nunca** y Jarvis no contestaba salvo que silenciaras el micro |
| 6 | `voice-app/lib/outbound-handler.js` | Separa el dominio SIP (`SIP_TRUNK_HOST`) del sitio al que se manda el INVITE (`SIP_PROXY`) | La llamada saliente usaba la IP del SBC como dominio SIP y el PBX respondía **503** |
| 7 | `voice-app/lib/{outbound-handler,outbound-routes,outbound-session}.js` | Cuelga a los `timeoutSeconds`, responde de verdad a `GET /api/call/{id}` y acepta `delaySeconds` (detalle abajo) | Si no coges, el 3CX desvía a tu buzón, el buzón descuelga y **Jarvis se pone a hablar con él con su línea ocupada**. El backend no puede saber que no lo cogiste, así que ni vuelve a llamar ni deja el mensaje |
| 8 | `voice-app/lib/conversation-loop.js` | Cuelga tras dos turnos seguidos sin oír a nadie | Una llamada sin nadie al otro lado repetía «¿sigues ahí?» **hasta 20 veces** (~12 minutos) con la extensión de Jarvis ocupada: devolverle la llamada daba comunicando |
| 9 | `voice-app/lib/claude-bridge.js` | Los tres mensajes que se dicen cuando Claude falla, al español, y uno propio para la sesión caducada | Con la sesión OAuth de Claude Code caducada, Jarvis descolgaba y a todo contestaba **«I encountered an unexpected error»**: en inglés y sin decir qué pasaba |
| 10 | `voice-app/lib/audio-fork.js` | Dentro de una frase, compara con **tu nivel de voz**, no solo con el ruido; turno máximo de 25 s (`VAD_MAX_UTTERANCE_MS`) (detalle abajo) | En un sitio ruidoso el ruido picaba por encima del suelo del parche 5, reiniciaba la cuenta de silencio y **Jarvis no dejaba de escucharte** aunque hubieras terminado, hasta el tope de 60 s |
| 11 | `claude-api-server/{server,bitacora}.js` y `voice-app/lib/outbound-session.js` | Memoria entre llamadas: una bitácora de las llamadas recientes que Claude recibe al empezar cada sesión (detalle abajo) | Cada llamada era una sesión nueva: si Jarvis te llamaba, no lo cogías y le devolvías la llamada, **no sabía para qué te había llamado** |
| 12 | `voice-app/lib/{outbound-handler,outbound-session,outbound-routes,conversation-loop}.js`, `voice-app/test/parche12.test.js` y `claude-api-server/bitacora.js` | Distingue el buzón de una persona por el `Contact` del 200 OK, cuenta cuántas veces habla alguien, **cuelga siempre** una llamada descolgada que falla y no deja que un final se reescriba (detalle abajo). **Aplicado el 2026-09-27**; la bitácora nueva, pendiente de reiniciar `claude-phone-api` | Si el buzón descuelga antes que el timbre del backend, para él la llamada está cogida: ni segunda llamada ni mensaje. Y si la voz falla tras descolgar, **la pata SIP se queda abierta** con el buzón grabando silencio hasta que cuelga él |

### El parche 2: el modelo

Lo único que cambia es una línea de `server.js`, y por eso es el que más se olvida al
actualizar: el modelo **no** sale de la configuración de Claude Code, sale de ahí. Para
pasar a otro (el 2026-10-12, de Sonnet 5 a Sonnet 5.5):

```bash
cd ~/.claude-phone-cli/claude-api-server
grep -n "CLAUDE_MODEL" server.js                 # lo que hay ahora
sed -i "s/claude-sonnet-5'/claude-sonnet-5-5'/; s/claude-sonnet-5\"/claude-sonnet-5-5\"/" server.js
grep -n "CLAUDE_MODEL" server.js                 # tiene que decir claude-sonnet-5-5
curl -s localhost:3010/api/calls                 # sin llamada en curso antes de reiniciar
sudo systemctl restart claude-phone-api
```

Y comprobarlo de verdad: una llamada a la extensión de Jarvis que conteste. Un modelo mal
escrito no falla al arrancar, falla en la primera respuesta («he tenido un problema»).
El chat escrito usa el mismo modelo por su cuenta (`JARVIS_CLAUDE_MODELO` en
`chat/env.example`): si se cambia uno, se cambian los dos.

### Los parches 7 y 8, en detalle

Salen del 2026-09-25: Jarvis llamó, no se cogió, y al devolverle la llamada su extensión
estaba ocupada. El backend ya sabe insistir (`_insistir` en `backend/main.py`: otra
llamada y, si tampoco, el mensaje en el buzón; ver «Si no lo coges» en
`docs/LLAMADAS.md`), pero **sin estos dos parches no hace nada** —ve cada llamada como
contestada y se queda como antes—, porque el original tiene tres fallos que se lo impiden:

- **`timeoutSeconds` se valida y no se usa.** Llega a `initiateOutboundCall` y nadie lo
  mira: el INVITE suena hasta que el 3CX decide, y lo que decide es tu buzón.
- **`GET /api/call/{id}` contesta 404 siempre.** `OutboundSession` se registra con
  `activeSessions.set(callId, this)` usando el parámetro, que las rutas pasan como `null`,
  en vez de `this.callId`. Y `getInfo()` no incluye el `reason`, así que aunque la
  encontrara no diría si fue `no_answer` o `busy`.
- **El `endpoint` de FreeSWITCH se pierde** cuando la llamada no se contesta: se crea
  antes del INVITE y solo se destruye si alguien cuelga una llamada contestada.

**7a — `outbound-session.js`:**

```js
// constructor
activeSessions.set(this.callId, this);          // era: activeSessions.set(callId, this)

// transition(newState, reason), justo tras this.state = newState
if (reason) this.reason = reason;

// getInfo(), dentro de `info`
reason: this.reason || null,
```

**7b — `outbound-handler.js`**, en `initiateOutboundCall`. `endpoint` sale del `try`
para poder destruirlo en el `catch`, y el INVITE se cancela a los `timeoutSeconds`:

```js
let endpoint = null;
let invite = null;
let agotado = false;
// ... dentro del try:
endpoint = await mediaServer.createEndpoint();   // era: const endpoint = ...
// ...
const temporizador = setTimeout(function() {
  agotado = true;
  if (invite) invite.cancel();
}, timeoutSeconds * 1000);
let uac;
try {
  uac = await srf.createUAC(sipUri, uacOptions, {
    cbRequest: function(err, req) {
      invite = req;
      if (agotado && req) req.cancel();
      // ... el log de siempre
    },
    cbProvisional: /* sin cambios */
  });
} finally {
  clearTimeout(temporizador);
}
// ... y en el catch, antes de traducir los códigos SIP:
if (endpoint) endpoint.destroy().catch(function() {});
if (agotado) throw new Error('no_answer');
// y junto a los demás códigos:
} else if (status === 603) {
  throw new Error('declined');
```

**7c — `outbound-routes.js`**: un `delaySeconds` opcional (0-30) que espera entre
descolgar y hablar. Es para el buzón: sin él, el mensaje se dice ENCIMA del saludo del
buzón y se graba a medias. Y que `declined` llegue como motivo:

```js
var delaySeconds = Math.min(Math.max(Number(req.body.delaySeconds) || 0, 0), 30);
// ... tras session.transition('PLAYING'):
if (delaySeconds) await new Promise(function(r) { setTimeout(r, delaySeconds * 1000); });
// ... en el catch final, con los demás motivos:
else if (error.message === 'declined') reason = 'declined';
```

**8 — `conversation-loop.js`**: un contador de turnos sin nadie hablando.

```js
let silencios = 0;                    // junto a turnCount
// ... en el bloque `if (!utterance) {`, lo primero:
silencios++;
if (silencios >= 2) {
  logger.info('Dos turnos sin oír a nadie, cuelgo', { callUuid });
  break;
}
// ... y justo después del bloque (hay utterance):
silencios = 0;
```

Tras aplicarlos: `docker compose -f ~/.claude-phone/docker-compose.yml up -d --build
voice-app` (o el nombre de servicio que tenga), y comprobarlo sin gastar nada con
`curl http://localhost:3010/api/calls`, que debe listar la última llamada con su `callId`
en vez de una clave `null`.

Y un fichero que el repositorio original referencia y **nunca trae**:
`voice-app/static/hold-music.wav`, el tono que suena mientras Jarvis piensa. Sin él,
FreeSWITCH responde `File Not Found` y ese hueco de 6-15 segundos se oye como silencio
absoluto, que por teléfono no se distingue de que se haya cortado la llamada. El que hay
son dos pulsos graves cada dos segundos al 8 % de volumen, generados con el `wave` de
Python.

### Los parches 9 y 10, en detalle

Salen del 2026-09-26, de las primeras llamadas de prueba tras aplicar el 7 y el 8.

**9 — `claude-bridge.js`**, en el `catch` de la consulta a Claude: las tres frases en
inglés (servidor inalcanzable, tiempo agotado y error genérico) pasan al español, y antes
del genérico:

```js
if (/authenticate|OAuth|login/i.test(error.message || '')) {
  return "No puedo pensar: la sesión de Claude Code en caja ha caducado. ...";
}
```

La causa de fondo de aquel día era esa: `~/.claude/.credentials.json` de `malbisudlf`
caducó y no se pudo refrescar. Se arregla entrando en `caja` como `malbisudlf`, `claude`
y `/login`; no hace falta reiniciar nada, el puente lee las credenciales en cada llamada.

**10 — `audio-fork.js`**, en `_onMessage`, tras empezar la frase. El parche 5 decide
«voz» si la energía supera el suelo de ruido por un factor; en un sitio ruidoso el ruido
también lo supera a ratos, y cada pico reinicia `_silenceMs`. Ahora, con ~300 ms de voz
ya oídos, un trozo solo cuenta como voz si su RMS llega a una fracción
(`VAD_VOICE_RATIO`, 0,3 por defecto) del percentil 80 de lo que llevas dicho:

```js
// _startUtteranceWithPreRoll: this._rmsVoz = [];   _isSpeech: this._ultimoRms = stats.rms;
if (isSpeech) {
  const voz = this._rmsVoz;
  if (voz.length >= 15) {
    const ordenada = voz.slice().sort(function (a, b) { return a - b; });
    const nivel = ordenada[Math.floor(ordenada.length * 0.8)];
    const ratio = parseFloat(process.env.VAD_VOICE_RATIO) || 0.3;
    if (this._ultimoRms < nivel * ratio) isSpeech = false;
  }
  if (isSpeech) { voz.push(this._ultimoRms); if (voz.length > 500) voz.shift(); }
}
```

Funciona porque tu voz, pegada al micro, suena bastante más fuerte que lo de alrededor.
Si el ruido es tan fuerte como tu voz no hay umbral que lo separe: para eso está el tope
del turno, que baja de 60 a 25 s (`maxUtteranceMs`, o `VAD_MAX_UTTERANCE_MS`). Y siempre
queda la almohadilla (`#`), que cierra el turno al momento.

### El parche 11, en detalle

`bitacora.js` **sí está versionado**: es `telefono/bitacora.js` de este repositorio, y se
copia a mano a `~/.claude-phone-cli/claude-api-server/`. Guarda en
`~/telefono-jarvis/llamadas-recientes.json` (72 h, 40 llamadas como mucho) cada llamada:
las de Jarvis cogidas o no, lo que dejó en el buzón, las que le haces tú y lo que se
habló. Con el servicio reiniciado sigue ahí, que es el caso que importa: la llamada que
más hay que recordar es la anterior.

En `server.js`, tres enganches:

```js
const bitacora = require('./bitacora');
// en /ask, entre VOICE_CONTEXT y el prompt: solo al abrir sesión
if (callId && !sessions.has(callId)) fullPrompt += bitacora.contexto(callId);
fullPrompt += prompt;
const esAvisoSaliente = bitacora.apuntarConsulta(callId, prompt);
// ... tras la respuesta:
if (callId && !esAvisoSaliente) bitacora.apuntarTurno(callId, prompt, response);
// y una ruta nueva:
app.post('/bitacora', (req, res) => { bitacora.apuntarSaliente(req.body); res.json({ success: true }); });
```

Y en `outbound-session.js`, al llegar a `COMPLETED` o `FAILED`, un `fetch` sin esperar a
`${CLAUDE_API_URL}/bitacora` con `this.getInfo()`, que ahora incluye `message`. Hace
falta porque las llamadas no cogidas y las del buzón **no pasan por `/ask`**: sin ese
aviso, Jarvis no sabría que te llamó.

Jarvis recibe las últimas 12 y solo las saca si le preguntas. Probado el 2026-09-26: tres
llamadas de prueba, se le devolvió la llamada y contó las tres. Para que olvide (p. ej.,
tras unas pruebas): `echo "[]" > ~/telefono-jarvis/llamadas-recientes.json`.

### El parche 12, en detalle

**Aplicado en `caja` el 2026-09-27**: `git apply` del diff versionado aquí mismo
(`telefono/parche-12.diff`), imagen reconstruida con los 15 tests en verde dentro de ella
y `voice-app` cambiado sin ninguna llamada en curso. La imagen anterior sigue etiquetada
como `claude-phone-voice-app:antes-p12` para volver atrás en un minuto. Falta solo la
bitácora (`telefono/bitacora.js` → `~/.claude-phone-cli/claude-api-server/bitacora.js` y
reiniciar `claude-phone-api`, que pide `sudo`).

Sale del 2026-09-27. Con la web caída desde la madrugada, Jarvis llamó a las 07:00 (al
acabar la franja nocturna). El primer intento sonó sus 14 s y colgó (`no_answer`). En el
segundo **descolgó el buzón a los 7,5 s** —muy por debajo de los 40 del desvío; lo
probable es que el móvil rechazara o silenciara la llamada (modo dormir) y el 3CX la
mandara al buzón en el acto, sin que llegue nunca un 603—. claude-phone pasó a `PLAYING`,
la voz falló (el contenedor no tenía DNS tras el reinicio de `caja`) y la llamada quedó
en `FAILED`… **sin colgar**: el buzón estuvo grabando silencio 2 min 35 s, hasta que
colgó él. Y el backend no insistió ni dejó el mensaje, porque para él aquella llamada ya
había sido contestada. Los parches 7 y 8 y el timbre de 14 s daban por hecho que el buzón
tarda en descolgar; ese día tardó menos que el timbre.

**Quién descuelga.** El 3CX pone el nombre de la extensión en el `Contact` del 200 OK
cuando descuelga una persona (`"Nombre" <sip:ext@...>`) y no lo pone cuando descuelga el
buzón (`<sip:ext@...>`). Acertó en las 14 salientes contestadas del 20 al 27/09 (10
personas, 4 buzones). El tiempo hasta descolgar **no sirve**: el buzón cogió entre 7,5 y
41,5 s, y la persona entre 4,1 y 11,4. `quienContesta()` en `outbound-handler.js` devuelve
`person`, `voicemail` o, sin `<...>` en la cabecera, `unknown` (y entonces todo sigue
como antes). Cada llamada contestada deja una línea `Quién descuelga` en
`docker logs voice-app` con el `Contact` en bruto: es lo que permite comprobar la
heurística llamada a llamada.

**Lo que cambia, fichero a fichero:**

- `outbound-handler.js`: el diálogo (`uac`) sale del `try` como ya hizo el 7 con el
  `endpoint`, y si algo falla **después** de descolgar (`endpoint.modify`), el `catch`
  lo cuelga y lanza `unplayed`. Antes solo destruía el endpoint.
- `outbound-session.js`: `answeredBy` (null hasta que descuelgan) y `userTurns` (0), que
  `getInfo()` —o sea, `GET /api/call/{id}`— devuelve **siempre**, también a null: que la
  clave exista es lo que le dice al backend que habla con un claude-phone con el 12.
  `transition()` ignora cualquier salida de `COMPLETED` o `FAILED` (un final es final:
  antes el BYE del buzón podía convertir un `FAILED` en `COMPLETED` minutos después, y
  avisaba dos veces a la bitácora). El temporizador que borra la sesión a los 60 s lleva
  `.unref()`.
- `outbound-routes.js`: tres campos opcionales en `POST /api/outbound-call`.
  `detectVoicemail` (boolean), `voicemailMessage` (texto, 1000 caracteres como mucho) y
  `voicemailDelaySeconds` (0-30, 8 por defecto). Si se pide la detección y descuelga el
  buzón, no se conversa: con recado, se espera al saludo, se dice y la llamada acaba en
  `COMPLETED`/`voicemail_message`; sin recado, se cuelga en el acto con
  `FAILED`/`voicemail`. Tras la conversación, el motivo dice cómo acabó: `no_speech` si
  fueron los dos turnos de silencio del parche 8, `conversation_error` si falló el audio.
  Y en el `catch` final, si la llamada estaba descolgada, `FAILED`/`unplayed` **y se
  cuelga**.
- `conversation-loop.js`: una opción `onUserTurn`, que se llama con cada transcripción
  de 2 caracteres o más (así cuenta `userTurns`), y devuelve `{ endReason }`:
  `silence`, `goodbye`, `max_turns`, `hangup`, `no_audio` o `error`.

**Lo que lee el backend** (`GET /api/call/{id}` → `data`): `state`, `reason`,
`answeredBy` y `userTurns`. Los motivos nuevos y lo que significan para él:

| Estado / motivo | Qué pasó | Para el backend |
|---|---|---|
| `FAILED` / `voicemail` | Descolgó el buzón, se colgó sin recado | No cogida: la serie sigue |
| `COMPLETED` / `voicemail_message` | Descolgó el buzón y se le dejó el recado | En el buzón: la serie acaba |
| `COMPLETED` / `no_speech` | Dos turnos sin oír a nadie | Con `userTurns` 0: cogida si `answeredBy` es `person`; si no, no cogida |
| `COMPLETED` / `conversation_error` | Falló el audio de la conversación | Sin voz si `userTurns` es 0 |
| `FAILED` / `unplayed` | Descolgada, pero Jarvis no pudo decir nada; se cuelga | Sin voz: no se insiste, y queda un ERROR en el log |

Con `userTurns` mayor que 0 la llamada está cogida en cuanto se ve, sin esperar al final.
Y si descolgó una persona (`answeredBy: 'person'`) está cogida aunque no llegue a hablar:
pudo contestar encima del primer mensaje, cuando todavía no se escucha, o con un «sí» tan
bajo que el detector de voz no lo pilló. `no_speech` solo cuenta como no cogida cuando el
Contact dice buzón o no se entiende: es el respaldo de la heurística, no su rival. La
heurística acertó con las 10 personas; volver a llamar a quien ya lo cogió son dos
llamadas más, la segunda y la del buzón.

**Compatibilidad**, en los dos sentidos: un claude-phone sin el 12 ignora los campos
nuevos (su validador no rechaza lo desconocido) y no manda `answeredBy`, así que el
backend decide exactamente como antes. Un backend viejo contra el 12 tampoco cambia:
`no_speech` y `conversation_error` son `COMPLETED`, y `unplayed` es `FAILED`, como lo que
ya conocía. El interruptor de la detección está en el backend:
`TELEFONO_DETECTAR_BUZON=0`.

**La bitácora** (`telefono/bitacora.js`, versionada aquí y copiada a mano como en el
11): `voicemail_message` se apunta como mensaje en el buzón, y una saliente **no** cuenta
como cogida si contestó el buzón (y nadie habló), si fue `no_speech` sin turnos y sin
una persona al otro lado (`answeredBy` distinto de `person`) o si fue `unplayed`. Jarvis lo recuerda como «y NO lo cogió: contestó su buzón» o «no pudo
hablar».

**Cómo se prueba sin llamar a nadie**: `voice-app/test/parche12.test.js` (node:test, sin
dependencias) engancha dobles de la centralita, FreeSWITCH, la voz y el oído antes de
cargar `lib/`, y recorre 15 casos, entre ellos el del 27/09 (buzón y voz rota → la pata
se cuelga) y el de la persona que descuelga y no dice nada. Contra el código de antes
fallan los 15. Se lanza dentro de la imagen recién
construida y sin red, antes de cambiar el contenedor:

```bash
docker compose -f ~/.claude-phone/docker-compose.yml build voice-app
docker run --rm --network none --entrypoint node claude-phone-voice-app --test test/parche12.test.js
# 15 pass → sin llamada en curso (curl -s localhost:3010/api/calls):
docker compose -f ~/.claude-phone/docker-compose.yml up -d voice-app
```

Se le da el fichero: con el directorio (`test/`), Node no lo encuentra.

**Lo que no resuelve**: la heurística sale de 14 llamadas. Si un día el 3CX manda el
nombre también desde el buzón, se conversa con él como antes (el parche 8 cuelga a los
~70-90 s, en `no_speech` sin turnos) y, como el Contact dijo persona, cuenta como cogida:
ni segunda llamada ni recado, igual que sin el 12. Es el precio de no volver a llamar a
quien sí lo cogió; la línea `Quién descuelga` es lo que dirá si pasa. Si al revés una
persona llega sin nombre, oye el recado; no se le cuelga sin más. Y Whisper puede
«oír» frases en el ruido de un buzón grabando: si pasa, esa llamada contaría con un
turno.

## El parche 13: drachtio espera a la red antes de arrancar

Sale del 2026-09-29. Jarvis llevaba desde el reinicio de `caja` del día anterior **sin
recibir una sola llamada**, con todo en verde: contenedores arriba, SBC conectado y la
extensión `Registered`. El fallo no estaba en ningún log, estaba en `ss -lun`:

- `--contact "sip:*:5070"` no escucha en «todas las interfaces» como `0.0.0.0`: drachtio
  **enumera las IP que existen al arrancar** y abre un socket en cada una.
- Tras el reinicio, drachtio arrancó 11 s después del arranque del sistema, antes de que
  el DHCP diera IP a la red de casa. Se enganchó a `127.0.0.1` y a los puentes de Docker,
  y a la IP de la LAN no.
- La voice-app, en cambio, anuncia en el `Contact` del REGISTER la `EXTERNAL_IP` del
  `.env` —la de la LAN—, así que el registro sale bien y el 3CX manda cada INVITE a un
  puerto donde no escucha nadie. Tú oyes que suena y no contesta; aquí no queda rastro.

El arreglo va en `~/.claude-phone/docker-compose.yml` (copia del original al lado, en
`docker-compose.yml.antes-parche-13`): el servicio `drachtio` pasa a
`entrypoint: ["/bin/sh", "-c"]` y su `command` espera, hasta 2 minutos, a que
`${EXTERNAL_IP}` aparezca en `/proc/net/fib_trie` antes de hacer `exec /entrypoint.sh
drachtio ...` con los mismos argumentos de antes (el `--secret` incluido). Pasados los 2
minutos arranca igualmente, que nunca es peor que no esperar. Los `$` de la variable del
bucle van como `$$` para que Compose no los interpole.

Como `claude-phone setup` regenera ese fichero, **tras un `setup` hay que rehacerlo**. Y si
alguna vez vuelve a pasar, lo que lo delata es:

```bash
ss -lun | grep :5070    # tiene que salir la IP de la LAN, no solo 127.0.0.1 y 172.x
```

Para salir del paso basta `docker compose -f ~/.claude-phone/docker-compose.yml restart
drachtio voice-app`.

## El parche 14: el registro se reintenta si se pierde

Sale del 2026-10-06. La extensión de Jarvis salía **«Not registered»** en el 3CX y
llamarle iba directo al buzón, mientras que **las llamadas que hace Jarvis seguían
saliendo bien** (un INVITE se autentica por su cuenta con el 407 y no necesita el
registro). Contenedores arriba, SBC y `claude-phone-api` activos, y el 5070 en la IP de
la LAN: el parche 13 había hecho su trabajo. Llevaba así desde el reinicio de `caja` de
dos días antes.

- Al arrancar, la voice-app mandó su único REGISTER **antes de que drachtio tuviera un
  solo socket SIP** (el primer `DRACHTIO Connected at` del log sale vacío: es el parche 13
  esperando a la red) **y antes de que arrancara el SBC**, que lo hizo 2 s después.
- `voice-app/lib/multi-registrar.js` solo reintentaba si la petición daba error o si
  llegaba una respuesta de fallo. Un REGISTER que se perdía sin respuesta **no dejaba
  ningún temporizador**: ni reintento ni refresco, y el log no volvía a decir nada.

**El arreglo** (`telefono/parche-14.diff`, sobre `~/.claude-phone-cli/`): cada REGISTER
lleva un vigilante. Si en `REGISTER_TIMEOUT_SECONDS` (30 por defecto) no ha llegado una
respuesta final —tampoco tras un reto 401/407—, se manda otro, y en el log sale
`sin respuesta al REGISTER en 30s, reintento`. Cada intento lleva su número y la
respuesta de uno viejo que llegue tarde se ignora: si no, dos intentos contestados
programarían dos refrescos que se irían duplicando. Por la misma razón cada extensión
tiene un solo temporizador vivo (el vigilante, el reintento o el refresco), y `stop()`
los para todos; antes no paraba ninguno. Si `srf.request` lanza en vez de llamar al
callback, también se reintenta.

`voice-app/test/parche14.test.js` (node:test, drachtio de mentira) recorre seis casos;
contra el código de antes falla el del 2026-10-06, el del reto sin respuesta final y el
de la excepción. Se aplicó igual que el 12: imagen anterior etiquetada como
`claude-phone-voice-app:antes-p14`, construir, pasar los tests dentro sin red (los 15 del
12 siguen en verde) y cambiar el contenedor sin llamada en curso:

```bash
docker compose -f ~/.claude-phone/docker-compose.yml build voice-app
docker run --rm --network none --entrypoint node claude-phone-voice-app --test test/parche14.test.js
docker compose -f ~/.claude-phone/docker-compose.yml up -d voice-app
```

Si vuelve a salir «Not registered», mira el log de la voice-app desde su último arranque:
con el registro bien hay un `Refreshing` cada 27 minutos, y con el parche un REGISTER
perdido deja la línea del reintento.

```bash
docker logs voice-app 2>&1 | grep MULTI-REGISTRAR | tail -5
```

Para salir del paso, o si el parche se ha perdido con un `claude-phone update`:
`docker compose -f ~/.claude-phone/docker-compose.yml restart voice-app`, sin llamada en
curso (`curl -s localhost:3010/api/calls`).

## Los parches 15 y 16: más rápido, y se le puede cortar

Salen del 2026-10-13, de «¿por qué va Jarvis tan lento?» tras pasar a Sonnet 5.5. **No
era el modelo**: medido en los logs, Sonnet 5.5 contestaba antes que Sonnet 5 (mediana
~6,6 s frente a ~9 s), y con `--effort low` el resultado y el tiempo eran los mismos que
por defecto (115 tokens, 4,4-5,1 s de modelo). Lo que pesaba estaba alrededor:

- **El arranque de Claude Code en cada turno.** Cada turno es un `claude -p` nuevo
  (`--resume`); con «Responde solo: hola» el modelo tardaba 1,7 s y el proceso entero
  8,1 s. ~2,1 s eran conectar **todos los conectores de la cuenta de claude.ai** (Gmail,
  Drive, Figma, Canva, Zapier…) en cada turno, y ~0,6 s tráfico no esencial. Se arregla
  sin tocar el código: el drop-in de systemd de abajo. Quedan ~3,5 s fijos de arrancar
  Node, que solo se quitarían con una sesión viva durante toda la llamada.
- **La frase de espera se decía entera ANTES de preguntar a Claude** (~1,5-2 s por turno
  sin hacer nada). Es el parche 15.
- **En un sitio ruidoso el detector tardó ~10 s** en dar por acabado «Dime, ¿qué puedes
  hacer?» (RMS de fondo 5.000-7.000; en casa ~500). No se ha tocado: es el parche 10
  haciendo lo que puede.

**Los dos bucles.** Las entrantes (las que haces tú) van por `voice-app/lib/sip-handler.js`
y las salientes por `voice-app/lib/conversation-loop.js`, que es una copia del primero:
cambiar uno no cambia el otro. Por eso los dos parches viven en un módulo nuevo,
`voice-app/lib/turno-rapido.js`, y los dos bucles lo llaman.

- **15 — `pensar()`**: lanza la consulta a Claude, y *mientras* dice la frase de espera y
  pone la música. Si Claude ya ha contestado al acabar la frase, no suena la música. Un
  error de Claude se sigue lanzando igual que antes.
- **16 — barge-in, `decirInterrumpible()`**: mientras Jarvis dice la respuesta, el oído
  sigue abierto (`session.armarBargeIn()` en `audio-fork.js`). Con `BARGE_IN_MS` (500)
  de voz seguida, la sesión emite `barge`, el bucle hace `uuid_break` y Jarvis se calla.
  El turno siguiente **no pita** y espera la frase que ya está entrando, con su principio
  (si acaba antes de volver a escuchar, la sesión la guarda en `_sinRecoger`). A Claude
  le llega con `AVISO_INTERRUPCION` delante, para que sepa que puede que no oyeras el
  final. Solo la respuesta es interrumpible: ni el saludo, ni la frase de espera, ni la
  música.
- **Por qué la voz de Jarvis no se corta a sí misma**: el audio que llega al detector es
  solo tu lado de la línea (`forkAudioStart` con `mixType: 'mono'`). Lo que sí puede
  colarse es el eco acústico del altavoz de tu móvil o un ruido fuerte de medio segundo;
  si pasa, sube `BARGE_IN_MS` o apágalo con `BARGE_IN=0`, las dos en el `.env` de
  `~/.claude-phone/` y con `docker compose -f ~/.claude-phone/docker-compose.yml up -d
  voice-app` (un `restart` no relee el `.env`). Lo que delata un corte es
  `BARGE-IN: te pones a hablar` en el log.

`telefono/parche-15-16.diff` (sobre `~/.claude-phone-cli/`), con
`voice-app/test/parche15y16.test.js`: 13 casos, el detector de verdad con audio
sintético y los dos bucles enteros con dobles. Contra el código de antes fallan los
cinco del detector y de los bucles. Se aplicó igual que el 14: imagen anterior etiquetada
como `claude-phone-voice-app:antes-p15`, construir, pasar los tests dentro sin red (los
15 del 12 y los 6 del 14 siguen en verde) y cambiar el contenedor sin llamada en curso:

```bash
docker compose -f ~/.claude-phone/docker-compose.yml build voice-app
docker run --rm --network none --entrypoint node claude-phone-voice-app --test test/parche15y16.test.js
docker compose -f ~/.claude-phone/docker-compose.yml up -d voice-app
```

Volver atrás: `docker tag claude-phone-voice-app:antes-p15 claude-phone-voice-app` y el
mismo `up -d`.

## El parche 17: el orden de los bytes no se adivina

Sale del 2026-10-15, de «la llamada de Jarvis no funciona bien cuando el móvil está
conectado al coche». **No era el ruido del coche.** Las dos llamadas que fallaron el
14/10 a las 09:08 tienen el mismo log: el primer trozo de audio con algo de ruido
(RMS 53 y 160, el Bluetooth no manda silencio digital) y justo después
`Detected endian: BE`. A partir de ahí el detector leía **toda la llamada** en un RMS de
~19.000 con picos de 32.767, sin un solo trozo en silencio: no podía saber cuándo
hablabas ni cuándo callabas. La tercera llamada, un minuto después, funcionó porque su
primer trozo era un cero exacto (`LE score=2, BE score=2` → empate → LE).

**La causa, en `audio-fork.js` del original**: `_detectEndian` se quedaba con la lectura
que daba **más** volumen (`maxAbs + rms`). Leído al revés, el audio siempre da más
volumen: los bytes bajos, que son ruido, pasan a mandar. Así que con cualquier cosa que no
fuera silencio exacto en los primeros 20 ms, elegía mal. Whisper no se enteraba porque
`whisper-client.js` lee el audio por su cuenta como LE (`Int16Array` en x86), y por eso
la transcripción salía bien y lo único roto era decidir cuándo has terminado de hablar.

El parche fija LE y deja de adivinar. `AUDIO_FORK_ENDIAN=BE` lo fuerza al revés, y
`=auto` adivina con un criterio que sí vale: el audio de verdad cambia poco de una
muestra a la siguiente, y el leído al revés no. En `caja` no hace falta ponerla.

**Sospecha que queda abierta**: los niveles con los que se afinaron los parches 5 y 10
(«ruido de la línea 3.300-4.700, voz 16.000-20.000», «sitio ruidoso RMS 5.000-7.000») son
justo los de un audio leído al revés. Si aquellas llamadas también salieron BE, parte de
los «problemillas» del turno de palabra eran esto. Desde el 17, el registro enseña los
niveles de verdad (en casa, voz de unos pocos miles y silencio de cientos): si el detector
vuelve a fallar, mira primero los `VAD:` del log antes de tocar umbrales.

`telefono/parche-17.diff` (sobre `~/.claude-phone-cli/`), con
`voice-app/test/parche17.test.js`: tres casos. El del coche (silencio con ruido, una frase
y otra vez silencio, que tiene que leerse LE y cerrarse por `end_silence`) y el de `auto`
fallan contra el código de antes. Se aplicó igual que el 15 y el 16: imagen anterior
etiquetada `claude-phone-voice-app:antes-p17`, construir, pasar los tests dentro sin red
(los 15 del 12, los 6 del 14 y los 13 del 15-16 siguen en verde) y cambiar el contenedor
sin llamada en curso. Volver atrás: `docker tag claude-phone-voice-app:antes-p17
claude-phone-voice-app` y `up -d voice-app`.

## El parche 18: el briefing, leído de un tirón

Sale del 2026-10-15: «arregla lo de que me lea el briefing diario, no es capaz de leerlo
todo del tirón». El 14/10 se le pidió en el coche y Jarvis leía un trozo, preguntaba
«¿sigo?» y había que contestarle cada vez («Todas», «Sí, no pidas permiso, solamente
sigue»). No era el modelo: **claude-phone no deja otra cosa**. El `VOICE_CONTEXT` de
`claude-api-server` le pide a Claude 40 palabras por respuesta, y `extractVoiceLine`, en
los dos bucles, tira cualquier `VOICE_RESPONSE` de más de 60. Quitar los topes tampoco
servía: el briefing son ~15.000 caracteres, y que Claude los recitara serían más de un
minuto de música de espera por turno.

Así que **Claude no lo lee**. Pone una línea `📖 LEER: briefing` (con `desde=`, `hasta=`
y `fecha=` opcionales; ver `telefono/RUNBOOK.md`) y la voice-app hace el resto,
`voice-app/lib/lectura.js`:

1. Pide el texto al backend, `GET /telefono/briefing` (`backend/main.py`, «El briefing,
   leído en voz alta por teléfono»), que lo devuelve **preparado para la voz**: sin
   enlaces, emojis, viñetas ni la sección de incidencias, «20 M$» dicho «20 millones de
   dólares», y por secciones en trozos de ~700 caracteres.
2. Lo lee trozo a trozo con `decirInterrumpible` (parche 16): **mientras suena uno se
   sintetiza el siguiente**, así que no hay silencios entre trozos, y cada uno se puede
   cortar hablando.
3. Si le cortas, a Claude le llega en qué sección iba (`[Le estabas leyendo el briefing y
   te ha cortado en la sección 2 de 6 …]`), y si le dices «sigue», vuelve a poner la línea
   con ese `desde=`. Si acaba, le llega que ha terminado. Si el backend no puede (no hay
   briefing, Outlook caído), dice por qué en voz alta.

De paso, el texto de terceros del briefing (newsletters, titulares) va del correo al
altavoz **sin pasar por la sesión con shell**, que es lo que pedía `_AVISO_BRIEFING`.

**Lo que cuesta**: cada lectura entera son ~15.000 caracteres de ElevenLabs. Cortar a
mitad solo gasta el trozo que estaba sonando y el siguiente, ya pedido.

**Variables en `~/.claude-phone/.env`**: `LECTURA_TOKEN`, el mismo valor que
`JARVIS_MCP_TELEFONO_TOKEN` del backend (y que el `Authorization` de
`~/telefono-jarvis/.mcp.json`), y `LECTURA_URL` si el backend no está en
`http://127.0.0.1:8080` (la voice-app va con `network_mode: host`). Sin el token, la
llamada dice «No he podido traer el briefing para leértelo».

`telefono/parche-18.diff` (sobre `~/.claude-phone-cli/`), con `voice-app/lib/lectura.js`
y `voice-app/test/parche18.test.js`: siete casos, la lectura entera en orden, el corte
con su aviso a Claude, el backend caído y los dos bucles enteros (saliente que lee hasta
el final, entrante al que se le corta a media lectura). Se aplicó como los anteriores:
imagen `claude-phone-voice-app:antes-p18`, construir, todos los tests dentro sin red y
`up -d voice-app` sin llamada en curso. El `RUNBOOK.md` nuevo se copia a
`~/telefono-jarvis/CLAUDE.md`: sin él, Claude no sabe que existe la línea y sigue leyendo
a trozos de 40 palabras.

## El parche 19: un Claude por llamada, y lo ya mirado al descolgar

Sale del 2026-10-15, de «dale más capacidad al Jarvis de voz»: lo que más se notaba no
era lo que sabía hacer, sino lo que tardaba. Los dos cambios viven en
`claude-api-server/` (que es un servicio de systemd, no un contenedor) y no tocan la
voice-app.

- **Sesión viva** (`claude-api-server/sesion-viva.js`). Cada turno era un `claude -p
  --resume` nuevo, con ~3,5 s fijos de arrancar Node antes de pensar nada (ver «Los
  parches 15 y 16»). Ahora la primera pregunta de la llamada abre **un** proceso con
  `--input-format stream-json --output-format stream-json`, que se queda leyendo
  mensajes por stdin y suelta un `result` por turno. Mismos argumentos de siempre
  (permisos, modelo, `--session-id`/`--resume`), así que la sesión sigue guardándose en
  disco. Medido en `caja` con el servidor parcheado: turnos de 2,4, 4,4 y 1,6 s, contra
  los ~8 s de antes.
  - **Si el proceso falla, el turno no se pierde**: muere, se cuelga más de
    `SESION_VIVA_TURNO_MS` (120 s, y entonces se mata) o hay ya `SESION_VIVA_MAX` (3)
    abiertas → ese turno va por el camino viejo, un proceso con `--resume`, que retoma
    la misma conversación desde el disco. En el registro sale `SESION-VIVA: falló (…)`.
  - **Nada vivo al colgar**: `/end-session`, que la voice-app ya llamaba al colgar, cierra
    el proceso; y si nadie lo cierra (la voice-app reiniciada a media llamada), se cierra
    solo tras `SESION_VIVA_INACTIVA_MS` (10 min) sin turnos.
  - **Apagarlo**: `SESION_VIVA=0` en el entorno del servicio (un drop-in como
    `rapido.conf`, que necesita `sudo`) vuelve exactamente al camino de antes.
- **Contexto al descolgar** (`claude-api-server/contexto.js`). Al abrir sesión —en la
  primera pregunta, la misma en la que entra la bitácora del parche 11— pide al backend
  `GET /telefono/contexto` y se lo mete a Claude: lo que queda de hoy y lo de mañana en
  la agenda, las tareas que vencen, los recordatorios y dónde estás. Es el
  truco del permiso de despliegue (9,7 s → 1,7 s) aplicado a «¿qué tengo hoy?». La
  consulta va **a la vez** que el arranque del proceso, con un tope de 2,5 s
  (`CONTEXTO_ESPERA_MS`): si el backend no contesta, la llamada sigue sin él. El token es
  el del MCP del teléfono y se lee del `.mcp.json` del directorio de trabajo
  (`CONTEXTO_TOKEN` lo sustituye), así que no hay otro sitio donde rotarlo. Lo que dice y
  por qué, en «Lo que ya está mirado al descolgar» de `docs/JARVIS.md`.

`telefono/parche-19.diff` (sobre `~/.claude-phone-cli/`, `patch -p1`), con
`claude-api-server/test/parche19.test.js`: siete casos con un Claude de mentira que
contesta stream-json (turnos en orden, error marcado, proceso que muere, turno colgado,
cerrar, el token del `.mcp.json` y el backend caído). Se aplicó así:

```bash
cd ~/.claude-phone-cli
cp claude-api-server/server.js claude-api-server/server.js.bak-20261015-p19
patch -p1 < parche-19.diff
(cd claude-api-server && node --test test/parche19.test.js)
curl -s localhost:3010/api/calls                     # sin llamada en curso
kill "$(systemctl show -p MainPID --value claude-phone-api)"   # Restart=always lo levanta
```

`kill` en vez de `systemctl restart` porque no hace falta `sudo`: el servicio corre con tu
usuario (`User=` de la unidad) y systemd lo vuelve a levantar a los 10 s. Volver atrás: copiar el `.bak` y
el mismo `kill`. Lo que delata que funciona es `SESION-VIVA: nueva` en
`journalctl -u claude-phone-api` y que no salga `[CONTEXTO]` con un aviso.

## El parche 20: leer más cosas, y el «sí» de viva voz

Sale del 2026-10-17, de dos de las propuestas del análisis del Jarvis de voz: que la
lectura del parche 18 sirva para más que el briefing, y que lo que se confirma por
teléfono no obligue a coger el móvil (en el coche no se puede). Los dos viven en la
voice-app, en los dos bucles (entrante y saliente), igual que el 18.

- **Leer más cosas** (`voice-app/lib/lectura.js`, generalizado). La línea es ahora
  `📖 LEER: <qué>` con `briefing`, `semana`, `correo` o `tareas`, y todo se pide a
  `GET /telefono/lectura?que=…` del backend (el briefing incluido; `/telefono/briefing`
  sigue existiendo). El correo es el parte de la noche, y va del backend al altavoz sin
  pasar por Claude, que no tiene herramienta para leerlo. Los avisos a Claude («le estabas
  leyendo X y te ha cortado en la sección N») dicen qué se estaba leyendo.
- **El «sí» de viva voz** (`voice-app/lib/confirmacion.js`, nuevo). Si la respuesta de
  Claude trae `✅ CONFIRMAR: <id>` (la propuesta del backend se la da hecha), la llamada:
  1. pide `GET /telefono/confirmar/<id>` y, si se puede confirmar hablando, lee la frase
     que escribió el backend y pregunta «¿Lo hago? Di sí o no.»;
  2. lo siguiente que digas lo decide `siONo`, con las mismas listas cerradas que el
     dashboard: la frase **entera** tiene que ser un sí o un no, y el no gana;
  3. con un sí o un no, `POST /telefono/confirmar/<id>` y lee lo que contesta el backend
     («Hecho. Creado Dentista mañana.»). Ese turno no pasa por Claude; en el siguiente le
     llega entre corchetes qué contestaste y qué pasó. Con cualquier otra cosa, lo dicho
     va a Claude como siempre, con la propuesta todavía pendiente en el móvil.
  El backend lo vuelve a comprobar todo (solo lo reversible, recién propuesto y sin
  contestar; ver «El sí dicho por teléfono» en `docs/JARVIS.md`).

**Variables**: `CONFIRMAR_TOKEN` en `~/.claude-phone/.env`, el mismo valor que
`TELEFONO_CONFIRMAR_TOKEN` en `~/stack/backend.env`. Es **otro** token que el del MCP a
propósito: ese lo tiene la configuración de Claude, y este solo la voice-app. Sin él, la
llamada no pregunta nada y todo se confirma con el botón, como antes. La lectura sigue
usando `LECTURA_TOKEN`.

`telefono/parche-20.diff` (sobre `~/.claude-phone-cli/`, `patch -p1`), con
`voice-app/test/parche20.test.js`: once casos (las marcas, el sí o el no, sin token, el
backend que dice «botón», y los dos bucles enteros: el saliente confirma sin preguntar a
Claude y el entrante pasa la respuesta ambigua a Claude). Cambia dos aserciones de
`parche18.test.js`, porque el pedido trae ahora `que` y la URL es `/telefono/lectura`. Se
aplicó como el 17 y el 18:

```bash
cd ~/.claude-phone-cli
docker tag claude-phone-voice-app claude-phone-voice-app:antes-p20
patch -p1 < parche-20.diff
docker compose -f ~/.claude-phone/docker-compose.yml build voice-app
docker run --rm --network none --entrypoint node claude-phone-voice-app --test test/parche20.test.js
curl -s localhost:3010/api/calls                     # sin llamada en curso
docker compose -f ~/.claude-phone/docker-compose.yml up -d voice-app
```

Dentro de la imagen y sin red pasan el 20 (11), el 18 (7), el 15-16 (13), el 12 (15), el
14 (6) y el 17 (3). Volver atrás: `docker tag claude-phone-voice-app:antes-p20
claude-phone-voice-app` y el mismo `up -d`. Lo que delata que funciona es
`CONFIRMAR: pregunto` y `LECTURA: semana` en `docker logs voice-app`.

## El parche 21: el `claude-api-server`, solo en local

Sale del 2026-10-23, del vigía de seguridad de `caja` (repositorio HomeLab,
`caja/vigias/seguridad.sh`), que encontró el puerto 3333 escuchando en `0.0.0.0`. El
original hace `app.listen(PORT, '0.0.0.0')` a mano, y `POST /ask` **no pide ninguna
credencial** y lanza Claude Code con `--dangerously-skip-permissions` como el usuario de
`caja`, que está en el grupo `docker`: equivale a root. Cualquier aparato de la wifi o del
tailnet podía mandar en la máquina. El riesgo aceptado en `docs/LLAMADAS.md` era el 3010
de la voice-app, no este.

El arreglo es una línea: escucha en `HOST`, que por defecto es `127.0.0.1`. Nada lo pierde:
la voice-app corre con la red del host y llega por `CLAUDE_API_URL=http://localhost:3333`,
y nadie más lo usa (ni n8n, ni el backend; el `POST /ask-structured` «para n8n» del original
no tiene ningún flujo que lo llame, comprobado el mismo día). Si algún día hiciera falta
desde fuera, se pone `Environment=HOST=…` en el servicio, pero entonces con una credencial
delante, no así.

`telefono/parche-21.diff` (sobre `~/.claude-phone-cli/`, `patch -p1`). El fichero no pasa por
ninguna imagen: lo lee `node` directamente desde el servicio de systemd, así que basta con
reiniciarlo (con sudo, es un servicio del sistema):

```bash
cd ~/.claude-phone-cli/claude-api-server
cp -p server.js server.js.bak-AAAAMMDD-antes-p21
cd .. && patch -p1 < parche-21.diff
node --check claude-api-server/server.js
sudo systemctl restart claude-phone-api
ss -tlnp | grep 3333                                 # 127.0.0.1:3333, no 0.0.0.0
curl -s localhost:3333/health
```

Volver atrás: copiar el `.bak` encima y el mismo `restart`. En `caja` la copia es
`server.js.bak-20261023-antes-p21`.

## El parche 22: escucha pasiva («modo coche»)

Sale del 2026-10-24, de «que en el coche esté siempre escuchando, aunque no le diga nada,
y que se active con un comando, tipo Alexa». Un iPhone no deja a ninguna app esperar una
palabra en segundo plano, así que la escucha va dentro de la llamada: la línea abierta,
Jarvis callado, y solo lo que va detrás de «Jarvis» llega a Claude. Cómo se usa y cómo se
dispara desde CarPlay, en «Modo coche» de `docs/LLAMADAS.md`.

- **`voice-app/lib/escucha-pasiva.js`** (nuevo): la palabra (`buscarPalabra`, con las
  formas en que Whisper escribe «Jarvis» en español: yarvis, charvis, jarbis…; se cambia
  con `ESCUCHA_PASIVA_PALABRA`), las órdenes («modo coche», «modo normal», «gracias») y
  `esperarPalabra`, que escucha sin contestar. De cada frase oída dormido transcribe solo
  los primeros `ESCUCHA_PASIVA_VENTANA_MS` (4 s) si es larga, y la frase entera solo si el
  principio trae el nombre. Lo que no lleva el nombre no se registra, ni el texto.
- **Los dos bucles** (`sip-handler.js` y `conversation-loop.js`): dormido, el turno no
  empieza hasta que le nombran; despierto, el turno siguiente espera
  `ESCUCHA_PASIVA_SEGUIMIENTO_MS` (8 s) en vez de 30 y, si nadie habla, se vuelve a dormir
  sin «¿sigues ahí?» ni contar silencios (el parche 8 no aplica: el silencio es lo normal).
  La pregunta llega a Claude con `[Modo coche: …]` delante. Tope por tiempo,
  `ESCUCHA_PASIVA_MAX_MIN` (180).
- **`outbound-routes.js`**: `escuchaPasiva: true` en `POST /api/outbound-call` (solo con
  `mode: 'conversation'`) empieza la llamada ya dormida. Es lo que pide el backend en
  `POST /telefono/modo-coche`. Un claude-phone sin el parche ignora el campo.
- **`whisper-client.js`**: acepta `prompt`, y la escucha le pasa «Jarvis.» para que escriba
  bien el nombre.
- De paso, el personaje (`docs/JARVIS_PERSONA.md`): la entrante de Jarvis saluda «A su
  servicio, señor.» y las frases de espera dicen «señor». La despedida no cambia (la mira
  el test del 16).

`telefono/parche-22.diff` (sobre `~/.claude-phone-cli/`, `patch -p1`), con
`voice-app/test/parche22.test.js`: nueve casos (la palabra y sus falsos amigos —Travis,
Gervasio—, las órdenes, la ventana de 4 s, colgar y el tope, y los dos bucles enteros:
la saliente del coche que solo contesta a «Jarvis» y la entrante que pasa a modo coche y
vuelve). **Aplicado en `caja` el 2026-10-24**, como el 20: imagen anterior etiquetada
`claude-phone-voice-app:antes-p22`, construir, y dentro, sin red, pasan el 22 (9), el 20
(11), el 18 (7), el 17 (3), el 15-16 (13), el 14 (6) y el 12 (15); `up -d voice-app` sin
llamada en curso y la extensión registrada a la primera. El `CLAUDE.md` anterior del
teléfono quedó en `~/telefono-jarvis/CLAUDE.md.bak-20261024-antes-p22`. Los pasos:

```bash
cd ~/.claude-phone-cli
docker tag claude-phone-voice-app claude-phone-voice-app:antes-p22
patch -p1 < parche-22.diff
docker compose -f ~/.claude-phone/docker-compose.yml build voice-app
docker run --rm --network none --entrypoint node claude-phone-voice-app --test test/parche22.test.js
curl -s localhost:3010/api/calls                     # sin llamada en curso
docker compose -f ~/.claude-phone/docker-compose.yml up -d voice-app
```

Y el `RUNBOOK.md` nuevo a `~/telefono-jarvis/CLAUDE.md` (trae el personaje y cómo
contestar en modo coche). Volver atrás: `docker tag claude-phone-voice-app:antes-p22
claude-phone-voice-app` y el mismo `up -d`. Lo que delata que funciona es
`ESCUCHA-PASIVA: a la escucha` y `me llaman` en `docker logs voice-app`.

## El parche 23, en espera: la huella de voz (y por qué se va a jacobo)

Pedido el 2026-10-24: que la escucha pasiva del 22 solo se despierte cuando quien dice
«Jarvis» es Mikel, no un pasajero ni la radio. **Se paró a medias a petición suya**: la
transcripción va a mudarse de OpenAI a un Whisper local en **jacobo** (el PC de casa con
el i5-9400F y la RX 580 de 8 GB, en cuanto tenga fuente), y la huella tiene que vivir
allí, junto a él. **Nada está aplicado**: la voice-app sigue en el 22 y no hay ningún
servicio nuevo corriendo.

### Lo que hay hecho (`telefono/huella-voz/`, sin aplicar)

- `servidor.py`: el servicio de la huella. HTTP de la biblioteca estándar y
  [sherpa-onnx](https://github.com/k2-fsa/sherpa-onnx) (2.0.0, ~4 MB más su núcleo; trae
  su propio onnxruntime). `GET /salud`, `POST /verificar` (PCM 16 kHz de una frase →
  `{es_el, similitud, umbral}`) y `POST /alta` (las frases seguidas, con sus largos en la
  cabecera `X-Frases`; descarta las que no se parecen al resto y guarda la anterior en
  `huella.anterior.json`). Escucha en `127.0.0.1` y **fuera de local no arranca sin
  `HUELLA_TOKEN`**, que es lo que permite moverlo a jacobo. Ni audio ni texto en disco:
  solo el vector y sus números.
- `huella-voz.js`: lo que iría en `voice-app/lib/`. `comprobarVoz()` (con
  `HUELLA_VOZ_MODO=medir`, que apunta la similitud pero despierta siempre, para fijar el
  umbral con llamadas reales; y `HUELLA_VOZ_SI_FALLA=despertar|dormir`, por defecto
  despertar) y `aprenderVoz()`, el alta por teléfono: «Jarvis, aprende mi voz», ocho
  frases que empiezan por «Jarvis» y una libre, ~30 s.
- `banco.py`: el banco de abajo.

**Lo que falta**: restar la media del canal en `servidor.py` (ver abajo), su `Dockerfile`
y su `compose.yml`, los tests de los dos lados, el enganche en `esperarPalabra` (comprobar
la voz cuando el principio trae el nombre y **antes** de transcribir la frase entera, para
que lo que dice un pasajero no salga a Whisper) y en los dos bucles («aprende mi voz»
justo después de las órdenes del 22), y el `parche-23.diff`.

### Lo medido

- **La línea es G.711 μ-law (PCMU, 8 kHz).** El SBC contesta `m=audio … RTP/AVP 0 101`
  (logs de drachtio): 300-3.400 Hz. El canal cambia la huella más que el ruido, así que
  el alta tiene que hacerse **por la misma línea** que la comprobación, nunca con el micro
  del PC.
- **Banco** (`banco.py`, en `caja` el 2026-10-24): LibriSpeech test-clean, 40 hablantes,
  ~30 s de alta y 12 pruebas de 1,5-4 s por hablante, todo por un G.711 simulado; «coche»
  es además ruido marrón a 10 dB de SNR. EER (falsos rechazos = falsos aceptados) y tiempo
  por frase en el i7-8650U de `caja`:

  | Modelo | ms/frase | tel | tel + coche | tel, − media | tel + coche, − media | Umbral (− media) |
  |---|---|---|---|---|---|---|
  | **3D-Speaker ERes2Net (VoxCeleb)** | 94 | 3,2 % | 3,8 % | **2,3 %** | **2,7 %** | ~0,33-0,36 |
  | NeMo TitaNet large | 98 | 3,8 % | 6,0 % | 2,5 % | 4,6 % | ~0,32 |
  | NeMo TitaNet small | 48 | 3,1 % | 7,9 % | 2,3 % | 6,4 % | ~0,26 |
  | 3D-Speaker CAM++ (zh/en) | 51 | 5,2 % | 9,8 % | 3,8 % | 5,9 % | ~0,34 |
  | WeSpeaker ResNet34 / CAM++ | 81 / 52 | 22 % / 48 % | — | — | — | inservibles |

  «− media» es restar a cada vector, antes del coseno, la media de **otras** voces por el
  mismo canal: el G.711 empuja todas las huellas hacia un mismo sitio y con eso se
  compensa. En producción sería un vector guardado junto al modelo, sacado de LibriSpeech
  por el canal simulado; no es la cohorte real, así que ayudará algo menos que aquí. Los
  WeSpeaker dan resultados de azar con sherpa-onnx 2.0.0 (se sospecha de las
  características de entrada); no usarlos sin averiguar por qué.
- **Lo que el banco no dice**: es inglés leído, no español dicho en un coche, y el canal es
  simulado. El umbral bueno sale de llamadas reales desde el coche con
  `HUELLA_VOZ_MODO=medir`, contando falsos rechazos, y no antes. El banco y sus datos
  siguen en `caja`, en `~/tmp-huella/` (con un `LEEME.txt`), para repetirlo en jacobo.

### El diseño para jacobo

Una sola pieza, el «oído», en jacobo: **transcripción y huella sobre el mismo audio**, y
la voice-app de `caja` le habla por la LAN.

- **Transcribir mientras se habla.** Whisper no es de flujo: transcribe trozos enteros.
  Lo de hoy es esperar a que acabes, subir la frase y esperar a OpenAI. En jacobo, la
  voice-app le manda el audio por WebSocket según llega del audio fork (trozos de 20 ms),
  y jacobo vuelve a transcribir la frase en curso cada ~0,5-1 s, dando por fijo lo que
  coincide en dos pasadas seguidas (la técnica *LocalAgreement* de
  [whisper_streaming](https://github.com/ufal/whisper_streaming)). Al acabar la frase
  solo queda el último trozo, así que el texto está casi en el acto. El precio es
  decodificar la misma frase varias veces: hace falta la GPU, o un modelo pequeño.
- **En el modo coche, lo mejor.** El nombre se ve en el primer parcial (~1 s): la charla
  que no empieza por «Jarvis» se deja de transcribir ahí (lo que hoy hace la ventana de
  4 s del 22), y la huella se calcula sobre ese primer trozo mientras sigue hablando. Y el
  audio ya no sale de casa.
- **La RX 580 es Polaris (gfx803)**: el ROCm actual no la soporta, así que PyTorch y
  faster-whisper (CTranslate2, que solo acelera con CUDA) no la usan. El camino con GPU
  es [whisper.cpp](https://github.com/ggml-org/whisper.cpp) con su backend Vulkan. Sin
  GPU, faster-whisper en los 6 núcleos del i5-9400F con un modelo `small` o `medium`.
  **Nada de esto está medido**: antes de prometer latencias, el banco de tiempos en
  jacobo con frases de las llamadas.
- **La huella no necesita GPU**: ~100 ms por frase en CPU. Va dentro del oído, con la
  misma API que `servidor.py` (o como su parte), la llave obligatoria por estar en la LAN
  (`HUELLA_TOKEN`) y la regla del parche 21: nada que escuche fuera de local sin
  credencial.
- **El fin de frase sigue en la voice-app** (parches 5, 10 y 17), y **si jacobo no
  contesta** (apagado, reiniciando) la voice-app vuelve a OpenAI Whisper como hoy y la
  huella hace lo que diga `HUELLA_VOZ_SI_FALLA`. Jarvis no puede quedarse sordo porque un
  PC de sobremesa esté apagado.
- **openWakeWord, descartado de momento** (se pidió valorarlo): ahorraba Whisper de pago
  con la radio puesta, y con Whisper local ese ahorro desaparece. Además su modelo es «hey
  jarvis» en inglés y a 16 kHz de banda ancha, no «Jarvis» en español por un G.711. No se
  ha medido.

## Lo que además NO está en el repositorio original

- **El servicio de systemd** `claude-phone-api` (`/etc/systemd/system/`), que levanta el
  `claude-api-server` al arrancar. Sin él, los contenedores vuelven solos tras un
  reinicio y el puente con Claude Code no, así que la llamada entra y no contesta nadie.
- **Su drop-in `claude-phone-api.service.d/rapido.conf`** (2026-10-13), con
  `ENABLE_CLAUDEAI_MCP_SERVERS=false` y `CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC=1`:
  ~2,8 s menos por turno (ver «Los parches 15 y 16»). De paso, la sesión del teléfono ya
  no carga los conectores de la cuenta de claude.ai (Gmail, Drive…), solo el MCP de
  Jarvis de `~/telefono-jarvis/.mcp.json`. Como el `server.js` hereda el entorno del
  servicio, sobrevive a un `claude-phone update`.
- Su `WorkingDirectory` es `~/telefono-jarvis/`, y el `CLAUDE.md` de ahí
  es la copia de `telefono/RUNBOOK.md` de este repositorio. **También se copia a mano.**
- **No uses `claude-phone start`**: intentaría levantar su propio `claude-api-server`
  contra el puerto 3333 que ya ocupa systemd. Los contenedores se levantan con
  `docker compose -f ~/.claude-phone/docker-compose.yml up -d`.

## Lo que hay que saber del 3CX

- El **SBC** está instalado en `caja` desde el paquete Debian (`3cxsbc`), no desde la ISO
  —que es para un equipo dedicado—, provisionado con la URL y la Authentication Key que
  da el panel al añadir un SBC. Su configuración se **reescribe en cada arranque** desde
  esa URL: lo que haya que fijar a mano va en `/etc/3cxsbc.conf.local`.
- El SBC ocupa el **5060** y los RTP **20000-20099**, así que drachtio va al **5070** y
  FreeSWITCH a **30000-30100**.
- La centralita tiene dos extensiones: la de Mikel y la de Jarvis. Los datos concretos
  (números, credenciales SIP, URL de aprovisionamiento) **no van aquí**: este repositorio
  es público. Están en `HOMEASSISTANT.md`.
- **El desvío a buzón de tu extensión tiene que caer entre los dos timbres del backend**:
  más tarde que `TELEFONO_TIMBRE_SEG` y antes que `TELEFONO_BUZON_TIMBRE_SEG` (90 s).
  En el panel: tu extensión → *Call Forwarding* → *Available* → *No Answer Timeout* 40 →
  *Voicemail* (el 3CX trae 20). Si el buzón coge la primera llamada antes de que Jarvis
  cuelgue, el backend la da por contestada: ni segunda llamada ni mensaje, y Jarvis se
  queda conversando con el buzón. Si no hay desvío a buzón, la llamada del buzón suena
  90 s y se pierde.
- **Aun con el desvío a 40, el buzón llegó a descolgar a los 17 s** (2026-09-26; la
  siguiente vez tardó 42). No se averiguó por qué —el perfil *Away* desvía al buzón sin
  esperar, y la app del móvil puede influir—, así que en `caja` `backend.env` lleva
  **`TELEFONO_TIMBRE_SEG=14`**: Jarvis cuelga antes de que el buzón pueda coger. Con
  14 s se probó la serie entera sin cogerlo: dos `no_answer` y el mensaje en el buzón.
  Desde el parche 12 eso ya no depende del timbre: el buzón se reconoce al descolgar. El
  2026-09-27 descolgó a los 7,5 s, por debajo incluso de los 14. Cuando la línea
  `Quién descuelga` haya acertado un par de buzones de verdad, `TELEFONO_TIMBRE_SEG` puede
  volver a 25.
- El plan gratuito cubre llamadas entre extensiones. Llamar a un teléfono de la red
  telefónica normal necesitaría un troncal con número, que es de pago — y para eso ya
  está el camino de Twilio, escrito y apagado en `docs/LLAMADAS.md`.
