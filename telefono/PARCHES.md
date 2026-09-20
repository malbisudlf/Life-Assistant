# Los parches de claude-phone

[claude-phone](https://github.com/theNetworkChuck/claude-phone) se instaló en `caja` el
2026-09-20 desde el repositorio original, y **no funciona tal cual para lo que hace aquí**.
Estos son los seis cambios que hubo que hacerle, con el síntoma que resuelve cada uno.

> **Viven en `/home/malbisudlf/.claude-phone-cli/`, que es un clon del repositorio de
> NetworkChuck, no de éste. No están versionados en ningún sitio.** Un
> `claude-phone update` —o borrar y reinstalar— se los lleva todos por delante, y el
> síntoma no es un error: es que Jarvis vuelve a hablar en inglés y deja de contestarte.
> Este fichero existe para poder rehacerlos. Si algún día hay que tocar mucho más, lo que
> toca es un *fork*, no seguir parcheando a mano.

## Los seis

| # | Fichero | Qué se cambió | Sin el parche |
|---|---|---|---|
| 1 | `cli/lib/docker.js` | Escribe `SIP_AUTH_PASSWORD` y `SIP_AUTH_USERNAME`, no solo `SIP_PASSWORD` | La voice-app lee `SIP_AUTH_PASSWORD`, no lo encuentra y **se registra con las credenciales de ejemplo del repositorio original** |
| 2 | `claude-api-server/server.js` | `CLAUDE_MODEL` pasa a `claude-sonnet-5` | Invocaba `claude-sonnet-4-20250514`, **retirado en junio de 2026**: toda respuesta era un error |
| 3 | `voice-app/lib/{tts-service,conversation-loop,sip-handler}.js` | Las URLs de audio usan `HTTP_PORT` en vez de `3000` a fuego | Aquí el 3000 lo ocupa Grafana: FreeSWITCH le pedía los audios a Grafana y la llamada **descolgaba en silencio** |
| 4 | `voice-app/lib/*` | Todo el texto al español, Whisper con `language: 'es'`, despedidas en español y TTS con `eleven_flash_v2_5` | Jarvis saludaba en inglés, `eleven_turbo_v2` es **solo inglés**, y Whisper intentaba entender el español como si fuera inglés |
| 5 | `voice-app/lib/audio-fork.js` | Detector de fin de frase por percentil sobre ventana deslizante | El umbral fijo (RMS 650) daba por voz el ruido de la línea (3.300-4.700): **el turno no se cerraba nunca** y Jarvis no contestaba salvo que silenciaras el micro |
| 6 | `voice-app/lib/outbound-handler.js` | Separa el dominio SIP (`SIP_TRUNK_HOST`) del sitio al que se manda el INVITE (`SIP_PROXY`) | La llamada saliente usaba la IP del SBC como dominio SIP y el PBX respondía **503** |

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
- El plan gratuito cubre llamadas entre extensiones. Llamar a un teléfono de la red
  telefónica normal necesitaría un troncal con número, que es de pago — y para eso ya
  está el camino de Twilio, escrito y apagado en `docs/LLAMADAS.md`.
