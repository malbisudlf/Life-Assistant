# Los parches de claude-phone

[claude-phone](https://github.com/theNetworkChuck/claude-phone) se instaló en `caja` el
2026-09-20 desde el repositorio original, y **no funciona tal cual para lo que hace aquí**.
Estos son los ocho cambios que hubo que hacerle, con el síntoma que resuelve cada uno.

> **Viven en `/home/malbisudlf/.claude-phone-cli/`, que es un clon del repositorio de
> NetworkChuck, no de éste. No están versionados en ningún sitio.** Un
> `claude-phone update` —o borrar y reinstalar— se los lleva todos por delante, y el
> síntoma no es un error: es que Jarvis vuelve a hablar en inglés y deja de contestarte.
> Este fichero existe para poder rehacerlos. Si algún día hay que tocar mucho más, lo que
> toca es un *fork*, no seguir parcheando a mano.

## Los ocho

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

## Lo que además NO está en el repositorio original

- **El servicio de systemd** `claude-phone-api` (`/etc/systemd/system/`), que levanta el
  `claude-api-server` al arrancar. Sin él, los contenedores vuelven solos tras un
  reinicio y el puente con Claude Code no, así que la llamada entra y no contesta nadie.
- Su `WorkingDirectory` es `/home/malbisudlf/telefono-jarvis/`, y el `CLAUDE.md` de ahí
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
  más tarde que `TELEFONO_TIMBRE_SEG` (25 s) y antes que `TELEFONO_BUZON_TIMBRE_SEG`
  (90 s). En el panel: tu extensión → *Forwarding rules* → «si no contesto en N
  segundos» → buzón de voz, con N en torno a 40. Si N es menor que 25 (el 3CX suele
  traer 20), el buzón coge la primera llamada antes de que Jarvis cuelgue y el backend
  la da por contestada: ni segunda llamada ni mensaje. Si no hay desvío a buzón, la
  llamada del buzón suena 90 s y se pierde.
- El plan gratuito cubre llamadas entre extensiones. Llamar a un teléfono de la red
  telefónica normal necesitaría un troncal con número, que es de pago — y para eso ya
  está el camino de Twilio, escrito y apagado en `docs/LLAMADAS.md`.
