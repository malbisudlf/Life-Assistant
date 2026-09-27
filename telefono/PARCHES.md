# Los parches de claude-phone

[claude-phone](https://github.com/theNetworkChuck/claude-phone) se instaló en `caja` el
2026-09-20 desde el repositorio original, y **no funciona tal cual para lo que hace aquí**.
Estos son los doce cambios que hubo que hacerle (el 12, aplicado el 2026-09-27), con el
síntoma que resuelve cada uno.

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
| 2 | `claude-api-server/server.js` | `CLAUDE_MODEL` pasa a `claude-sonnet-5` | Invocaba `claude-sonnet-4-20250514`, **retirado en junio de 2026**: toda respuesta era un error |
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

## Lo que además NO está en el repositorio original

- **El servicio de systemd** `claude-phone-api` (`/etc/systemd/system/`), que levanta el
  `claude-api-server` al arrancar. Sin él, los contenedores vuelven solos tras un
  reinicio y el puente con Claude Code no, así que la llamada entra y no contesta nadie.
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
