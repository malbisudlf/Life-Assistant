<!-- Parte de la guía del repositorio. El índice y las reglas que aplican
     SIEMPRE están en CLAUDE.md, en la raíz. -->

# Jarvis por Telegram

## Parte de la noche (del 24 al 25 de octubre de 2026)

**Lo que tiene que hacer usted, señor**, por orden de lo que más vale:

1. **La copia de n8n** (encargo 5), que es la única que protege datos: HomeLab,
   `caja/n8n/copia/INSTALAR.md`. La frase de cifrado (**también a su gestor de
   contraseñas**), instalar, primera copia a mano, el timer, rclone a OneDrive y la
   restauración de prueba en un n8n de usar y tirar. No necesita desplegar nada.
2. **Desplegar el backend** con las variables de lo que quiera encender: sin ellas, lo
   nuevo de esta noche se queda apagado y ni se anuncia. Telegram, en «Lo hace Mikel»
   aquí debajo (bot, tres variables, y después del despliegue el `setWebhook`); Jellyfin,
   en `docs/JELLYFIN.md` (clave, id de usuario y comprobar que el contenedor llega a
   `http://172.17.0.1:8096`).
3. **El programador** (encargo 2), lo más largo: HomeLab, `caja/programador/INSTALAR.md`
   (dos tokens, construir la imagen, el servicio y los dos encargos de prueba), y sus
   cuatro `PROGRAMADOR_*` en el backend.
4. **HomeLab en este PC**: commitear lo que hay sin commitear (abajo) y juntarlo con `main`.

No he desplegado, ni instalado, ni entrado en `caja`.

| Encargo | Estado | Commits |
|---|---|---|
| 1. Jarvis por Telegram | Hecho, 54 tests con la Bot API simulada | `6067094` |
| 3. Jellyfin en Jarvis | Hecho, 23 tests con Jellyfin simulado | `6e8a926` |
| 2. El programador | Escrito; 33 tests en el backend y 40 de la lógica del puente. Nada ha corrido contra Docker, Claude Code ni GitHub | `188fbac` y HomeLab `046285d` |
| 5. Copia de n8n | Escrita; 25 comprobaciones contra un directorio de prueba en el PC | HomeLab `33c4e83`, y este (`docs/N8N.md` y el parte) |

CI en verde en los tres de Life Assistant antes de pasar al siguiente. HomeLab no tiene CI.

**Lo que salió distinto de lo previsto:**

- **Telegram**: `sendVoice` acepta OGG/Opus, MP3 y M4A. Se pide OGG/Opus (la nota con su
  onda): Azure lo da tal cual; Fish da `opus` sin documentar el contenedor, así que se mira
  la firma `OggS` y si no, MP3; `sendAudio`, de último recurso.
- **El botón de confirmar del dashboard solo sale si `jarvisEtiquetaAccion` sabe describir
  la herramienta**: `jellyfin_reproducir` y `encargar_proyecto` han necesitado su línea en
  `src/lib/helpers.js`. Como el título de Jellyfin lo redacta el modelo, el backend
  comprueba al ejecutar que casa con el elemento real.
- **El programador**: el git que empuja vive **fuera** del contenedor (si no, un hook
  plantado se ejecutaría en `caja`) y el commit lo escribe el puente con su identidad, así
  que ningún `Co-Authored-By` llega a sus repos. `hablar_con_el_programador` va sin botón,
  como pidió: un mensaje a un encargo ya terminado lo reabre sin confirmar. La red aislada
  del contenedor (`red.sh`) está escrita **sin probar**.
- **n8n, con su CLI en caliente y no el volumen en frío**: en frío habría que parar n8n
  cada noche, y n8n es el reloj de los programados. Se pierde el usuario y el historial de
  ejecuciones, que no hacen falta. El destino fuera de `caja` (OneDrive) queda propuesto y
  pendiente de su `rclone config`: hasta entonces, una sola copia en el mismo disco.
- **HomeLab no estaba limpio**: la copia de este PC está en la rama vieja
  `claude/wol-caja`, con `caja/vigias/`, `caja/copias-ha/` y cambios en `CLAUDE.md`,
  `DECISIONES.md` y `RUNBOOK.md` **sin commitear en ninguna rama**, y `caja/pelis/` solo en
  `origin/claude/eager-gates-tre7f5`; OneDrive dejó además copias de conflicto
  `*-PC-MIKEL.md`. No la he tocado: lo de esta noche fue a `main` desde un worktree aparte.
  Al juntarlo, `DECISIONES.md` y `RUNBOOK.md` tendrán entradas nuevas en los dos lados (se
  quedan las dos). Por eso el aviso de fallo de la copia de n8n lleva su propio
  `avisar-fallo.sh` en vez de usar el de `caja/vigias/`, que en `main` no existe.

---

## Lo hace Mikel

Nada de esto lo puede hacer una sesión: el bot es de su cuenta de Telegram y el backend
de producción solo se despliega a mano.

1. **Crear el bot.** En Telegram, habla con **@BotFather**: `/newbot`, un nombre
   («Jarvis») y un usuario que acabe en `bot`. Te da el **token** (`123456:ABC…`).
   Después, en el mismo chat, `/setjoingroups` → tu bot → **Disable**: así nadie puede
   meterlo en un grupo (el backend no atendería ahí de todas formas, pero mejor que ni
   esté).
2. **Tu id.** Escríbele cualquier cosa a tu bot y, **antes** de poner el webhook
   (`getUpdates` no funciona con uno puesto):

   ```bash
   curl -s "https://api.telegram.org/bot<TOKEN>/getUpdates"
   ```

   El número de `message.from.id` es tu id (y el de `message.chat.id`, que en el chat
   privado es el mismo).
3. **El secreto del webhook.**

   ```bash
   python -c "import secrets; print(secrets.token_urlsafe(48))"
   ```

4. **Las tres variables**, en el `.env` del backend en `caja` (el de siempre):

   ```
   TELEGRAM_BOT_TOKEN=<token de BotFather>
   TELEGRAM_WEBHOOK_SECRET=<el secreto del paso 3>
   TELEGRAM_CHAT_ID=<tu id del paso 2>
   ```

   Para que conteste con voz a las notas hace falta al menos una voz: `FISH_AUDIO_API_KEY`
   (va delante en las notas) o Azure (`AZURE_SPEECH_KEY`/`AZURE_SPEECH_REGION`). Sin
   ninguna, contesta por escrito.
5. **Desplegar** (botón *Desplegar* de la zona dev, o `cd ~/stack && ./desplegar.sh`) y
   comprobar que `GET /` devuelve como `version` el commit de Telegram o uno posterior.
6. **Poner el webhook**, con el secreto y solo los dos tipos de mensaje que se atienden:

   ```bash
   curl -s -X POST "https://api.telegram.org/bot<TOKEN>/setWebhook" \
     -H "Content-Type: application/json" \
     -d '{"url": "https://api.lifeassistantbackend.bid/telegram/webhook",
          "secret_token": "<SECRETO>",
          "allowed_updates": ["message", "callback_query"],
          "drop_pending_updates": true}'
   curl -s "https://api.telegram.org/bot<TOKEN>/getWebhookInfo"
   ```

   `getWebhookInfo` no debe traer `last_error_message`. Si trae «401», el secreto del
   `setWebhook` y el del `.env` no son el mismo.
7. **Probarlo**, en este orden:
   - `/start` → «A su servicio, señor…».
   - «¿Qué tengo mañana?» → la agenda, con formato.
   - Una nota de voz → contesta con otra nota, y en el pie lo que ha entendido y lo que
     dice.
   - «Apúntame "prueba de Telegram" mañana a las 10» → mensaje con **✅ Sí / ❌ No**. Pulsa
     **No**: el mensaje dice «Cancelado» y no se crea nada. Repítelo y pulsa **Sí**: dice
     «Confirmado. Hecho.» y la cita está en Outlook (bórrala después).
   - `GET /gasto?dias=1` (o el gasto del panel ⚙): aparece la boca `telegram`.

---

## Cómo funciona

```
Telegram ──▶ POST /telegram/webhook ──▶ 200 al momento
                     │
                     └─▶ hilo «telegram» ─▶ _jarvis_chat (el mismo cerebro) ─▶ Bot API
```

Una boca nueva para el mismo cerebro, como el teléfono o el Atajo: la conversación y las
herramientas siguen en el backend, y Telegram solo es la puerta. Todo el código está en
la sección «TELEGRAM» al final de `backend/main.py`; los tests, en
`tests/backend/test_telegram.py`, con la Bot API simulada.

### Las tres llaves

- **El secreto del webhook.** Telegram manda en cada petición la cabecera
  `X-Telegram-Bot-Api-Secret-Token` con el `secret_token` que se le dio en `setWebhook`.
  Se compara con `TELEGRAM_WEBHOOK_SECRET` por `_token_ok()`: **sin secreto configurado,
  401 a todo** (fail-closed, invariante 2 de `CLAUDE.md`). El cuerpo se lee acotado
  (`_leer_cuerpo_limitado`) después de mirar el secreto.
- **El chat.** Solo se atiende a `TELEGRAM_CHAT_ID`, y tiene que serlo a la vez el chat y
  el remitente: en el chat privado con el bot los dos coinciden. Un grupo no cuela aunque
  Mikel esté dentro, y otra persona escribiendo tampoco. Lo demás recibe **un 200 mudo**:
  contestar otra cosa le diría a quien prueba que ahí hay alguien, y Telegram reintentaría.
- **El token del bot**, que es el que permite contestar. **Va en la URL de la Bot API**
  (`/bot<token>/…`), no hay otra forma, así que la regla es que el backend no registra
  nunca una URL de Telegram ni el texto de una excepción de `requests` (la lleva dentro):
  solo el método, el código y la `description` que da Telegram. Hay un test que lo mira.

### Segundo plano, orden y duplicados

- **200 enseguida.** Telegram reintenta si tarda la respuesta, y un turno con
  herramientas puede tardar decenas de segundos. El webhook es `async` solo para leer el
  cuerpo; el trabajo va a `_telegram_pool`, **un solo hilo**: es un solo chat, y dos
  mensajes seguidos tienen que contestarse en orden y con la ventana del anterior ya
  escrita. (Un endpoint `async` que hiciera el turno dentro congelaría el backend entero:
  `docs/BUGS_HISTORICOS.md`.)
- **Deduplicado por `update_id`**, en memoria (los últimos mil). Tras un reinicio solo
  podría repetirse lo que estaba en vuelo.
- **«Escribiendo…» mientras piensa** (`_TelegramOcupado`): `sendChatAction` cada 4 s
  hasta que sale la respuesta, porque Telegram lo quita solo a los ~5 s. Con una nota de
  voz es «grabando audio» (`record_voice`). Cosmético: si falla, no toca nada.
- La boca es `telegram` (`_boca_actual`): así sale en `jarvis_gasto` y en el origen de
  las órdenes de la casa. El hilo la fija él, porque una `contextvar` no viaja sola a otro
  hilo.

### La conversación: una ventana corta en memoria, sin tabla

Guardar el historial de Jarvis en el backend **se descartó a propósito**
(`docs/IDEAS.md`, «Descartadas»): menos estado que mantener y nada que purgar. El
dashboard lo guarda en `localStorage` y el Atajo no tiene historial. Telegram no tiene
dónde guardarlo de su lado —el bot no puede leer el chat hacia atrás—, y un chat sin
memoria de un mensaje al siguiente no sirve («¿y pasado?» no significa nada).

Lo que se ha hecho es lo mínimo que no rompe aquella decisión:

- **En memoria y nada más**: `_telegram_ventana`, los últimos `JARVIS_MAX_HISTORIAL`
  mensajes (el mismo tope que acepta el turno). Sin tabla, sin migración, sin nada que
  purgar. Un reinicio se la lleva, y es aceptable: se pierde el hilo, no un dato.
- **Con caducidad**: tras `TELEGRAM_CONTEXTO_MIN` (30) minutos sin hablar se empieza de
  cero. Una conversación de por la mañana no tiene que colarse en una de por la noche.
- `/nuevo` la vacía a mano.
- Lo que se confirma o se cancela con los botones también entra («(Confirmado por el
  usuario: …)»), para que Jarvis sepa en el turno siguiente que se hizo.

Lo duradero sigue yendo a la memoria de siempre (`jarvis_memoria`, `recordar`), que el
turno destila igual que en el chat.

### Notas de voz

- Se baja con **tope** (`MAX_AUDIO_BYTES`: se mira el tamaño que declara Telegram antes de
  pedir nada, y se cuenta lo que se lee). La ruta que devuelve `getFile` se valida antes
  de pegarla a la URL.
- **Whisper pasa por el limitador** (`_check_rate("telegram_audio", …)`, con
  `AUDIO_MAX_REQUESTS`): es de pago. El turno de texto, por el mismo cubo que `/jarvis` y
  el Atajo.
- Si te hablaron por voz, **se contesta con voz**: el turno va con `voz: true` (frases
  cortas, sin markdown) y la respuesta sale como nota, con lo que entendió y lo que dice
  en el pie. Si no hay voz configurada o Telegram la rechaza, por escrito.
- **La nota la piensa Claude**, igual que el texto, si es el motor del chat
  (`JARVIS_MOTOR_CHAT=claude`): `_jarvis_chat(..., voz_con_claude=True)`, con el prompt
  de voz en `_sistema_chat(voz=True)`. Es la excepción a «la voz va a OpenAI», que existe
  porque arrancar Claude Code cuesta segundos y en una llamada se oyen; aquí nadie espera
  en directo. Pedido por Mikel el 2026-10-25. Lo que sigue en OpenAI es la
  **transcripción** (Whisper): Claude Code no escucha audio.
- **El orden es el de las notas** (`_VOZ_ORDEN_NOTAS`): **Fish delante y Azure detrás**,
  al revés que en la llamada, porque aquí nadie espera en directo y la calidad se nota (ver
  «Fish Audio, de reserva» en `docs/JARVIS_VOZ.md`).
- **El formato**: `sendVoice` acepta OGG/Opus, MP3 y M4A (Bot API, comprobado el
  2026-10-24), pero solo el OGG/Opus sale como nota con su onda. Se pide así: Azure con
  `ogg-24khz-16bit-mono-opus` y Fish con `format: "opus"`. Fish **no documenta** en qué
  contenedor da el opus, así que se mira la firma (`OggS`); si no lo es, esa misma voz se
  pide en MP3. Y si un cliente rechazara el MP3 como nota, va como audio (`sendAudio`).

### Lo que se confirma: los botones

- Lo que el turno deja `pendiente` (lo `confirmar: True`) llega como mensaje con
  **✅ Sí / ❌ No**. La frase la escribe el backend con los argumentos guardados: para el
  calendario, las tareas y las notas, la misma que el móvil (`_describir_accion`, que
  además valida: un «sí» a algo que luego falla es un botón que miente, y entonces no se
  propone); para el resto, la herramienta y sus argumentos tal cual, como el dashboard.
- **El botón solo lleva un id** (`si:<id>` / `no:<id>`). Lo que se ejecuta es lo que se
  guardó al proponerlo (`_telegram_pendientes`, en memoria), así que un callback inventado
  no puede traer argumentos.
- **El «sí» va por el mismo camino que `/jarvis/ejecutar`** (`_jarvis_ejecutar_confirmado`):
  solo lo confirmable, venga de donde venga. La frontera de confirmación no cambia por
  entrar por Telegram.
- El callback comprueba el chat, **contesta con `answerCallbackQuery` antes de ejecutar**
  (si no, el botón se queda girando mientras la herramienta trabaja) y edita el mensaje
  para que diga «Confirmado» (con lo que salió) o «Cancelado», quitando los botones.
- **La primera respuesta vale**: el id se saca de la lista antes de hacer nada, y dos
  toques no ejecutan dos veces. **Caduca** a los `TELEGRAM_BOTON_MIN` (30), como un botón
  del móvil (`PREGUNTA_ACCION_VIGENCIA_MIN`). Un botón de antes de un reinicio dice «ya no
  está pendiente».

### El formato

`_md_a_telegram` es una función pura Markdown → el HTML que admite
`parse_mode: "HTML"`: escapa `&`, `<` y `>`, negrita, cursiva (la de `_` no rompe
`mis_capacidades`), tachado, código en línea y en bloque (con su lenguaje), enlaces (solo
`http(s)`), títulos en negrita, viñetas, citas y **tablas en `<pre>` alineadas**, que
Telegram no tiene. `_partir_telegram` trocea lo que pase del tope (4096) por líneas, y
cierra y reabre un bloque de código partido. Si Telegram rechaza el HTML (un 400), **ese
trozo se reenvía en texto plano**: mejor feo que callado.

### Lo que no hace, a propósito

- **No avisa de nada por su cuenta.** Es una boca, no un canal de avisos: todo lo
  proactivo sigue saliendo por `_apuntar_aviso` y su gobierno (presupuesto, silenciado,
  memoria) hacia el móvil o el correo. Si algún día Telegram fuera un canal más, se añade
  en `_notificar()` y lo heredan todos; no aquí.
- Fotos, documentos, mensajes editados y grupos: no se atienden (los grupos, ni siquiera
  se reconocen).

### Coste

Lo mismo que el chat: los turnos van por OpenAI, o por Claude Code con
`JARVIS_MOTOR_CHAT=claude` (también las notas de voz), y se apuntan con boca `telegram`.
Con Claude Code los paga la suscripción, y cuentan contra el mismo límite que el teléfono,
el chat del dashboard y el programador.
Una nota de voz suma Whisper (~0,006 €/min) y la síntesis (Fish o Azure, dentro de sus
niveles gratuitos para este uso).
