# Jarvis con voz de ElevenLabs — plan de integración

Este fichero es el **plan concreto para este repositorio**: qué se toca, en qué orden y
por qué. El diseño conceptual (agnóstico del proyecto) está en
`docs/JARVIS_real_time_voice_stack.md`; aquí se aterriza sobre `backend/main.py`,
`src/components/Dashboard.jsx` y `src/lib/`.

**Estado: el plan está entero.** Jarvis habla, avisa en voz alta antes de usar cada
herramienta, **empieza a hablar mientras escribe la respuesta**, **se le puede cortar a
media frase** y, desde el 4 de septiembre de 2026, **escucha con Scribe v2 Realtime en
vez de con el reconocimiento del navegador**. El reparto de hoy: **habla Azure**, con voz
nativa de España, y **escucha ElevenLabs**, que es el único de los dos que transcribe en
directo. Ver «La voz se mudó a Azure» y «El micrófono ya no se cierra» más abajo.

Lo que queda no es código: **probar el barge-in por altavoz en el iPhone**, que es el
riesgo que este fichero lleva señalando desde el principio y que ningún test puede
cubrir.

## Dónde retomar

Lo que está hecho y funcionando, con el sitio exacto:

| Pieza | Dónde | Qué hace |
|---|---|---|
| `POST /voz/token` | `backend/main.py`, sección `# ── Jarvis: voz en tiempo real` | Dice con qué voz se habla (`proveedor`) y emite el token de ElevenLabs si toca. Azure va primero. 503 si no hay ninguna |
| `POST /voz/decir` | `backend/main.py`, sección `# ── Azure Speech` | Sintetiza una frase con Azure y la devuelve como MP3. El texto va **escapado** a SSML |
| `src/lib/vozAzure.js` | — | El reproductor de Azure. Misma interfaz que `vozEleven.js` (`decir`/`callar`/`cerrar`) para que el modo llamada no sepa cuál tiene delante. No sabe de red: recibe `pedirAudio` y lo llama |
| `POST /jarvis/voz` | misma sección | El turno de `/jarvis` retransmitido por SSE |
| `_jarvis_turno()` | `backend/main.py`, antes de `/jarvis` | El bucle de siempre, ahora como generador de eventos. **`/jarvis` y `/jarvis/voz` lo comparten**; un test comprueba que dan lo mismo |
| `_JARVIS_RELLENOS` | misma sección de voz | Las frases fijas que se dicen mientras trabaja una herramienta |
| `_pensar_hablando()` | dentro de `_jarvis_turno` | La llamada al modelo con `stream=True`: suelta eventos `texto` según escribe y vuelve a juntar las `tool_calls`, que llegan partidas |
| `_por_decir()` | ídem | Lo que el cierre trae SIN decir. Vacío casi siempre; la respuesta entera cuando el modelo se quedó mudo y el texto lo puso el backend |
| `JARVIS_VOZ_MODELO_DIRECTO` | `backend/main.py`, config de Jarvis | Por voz se abre con el modelo grande y se salta el relevo, que cuesta una llamada entera antes de la primera sílaba |
| `src/lib/voz.js` | — | Puro: `trocearParaVoz`, `textoParaVoz`, `partirEventosSse` |
| `src/lib/vozEleven.js` | — | El WebSocket multi-contexto y el reproductor. Sin clave dentro |
| `src/lib/vozScribe.js` | — | **El micrófono de la llamada.** Scribe v2 Realtime por WebSocket, sin SDK. El micro se abre al descolgar y NO se cierra hasta colgar |
| `pareceEco` | `src/lib/voz.js` | La segunda defensa contra el acople: si lo transcrito se parece a lo que Jarvis está diciendo, no cuenta |
| `parcialDeScribe` / `cerradaDeScribe` | `src/components/Dashboard.jsx` | Lo que llega del transcriptor. **El barge-in vive aquí ahora** |
| `src/lib/vozMicro.js` | — | El medidor de energía del micro. **Solo se usa cuando no hay Scribe** (sin ElevenLabs configurado, sin permiso de micro o si el socket se cae) |
| `detectorDeHabla` | `src/lib/voz.js` | Las reglas del corte: voz sostenida, gracia al empezar, una sola vez |
| `empezarAHablar` / `dejarDeHablar` / `interrumpirAJarvis` | `src/components/Dashboard.jsx` | El cableado del barge-in con el ciclo de la llamada |
| `turnoDeLlamada()` | `src/components/Dashboard.jsx` | Consume el SSE y va hablando |
| Tests | `tests/backend/test_voz.py`, `tests/backend/test_jarvis_voz.py`, `tests/frontend/voz.test.js`, `tests/frontend/vozEleven.test.js`, `tests/frontend/vozMicro.test.js` | El de `vozEleven` prueba solo lo que se rompió de verdad: que al fallar la voz de pago no se pierda nada de lo que quedaba por decir. El de `vozMicro`, que un micrófono negado no tire la llamada y que el medidor quede cerrado antes de avisar |

**Ya se le puede cortar** (agosto de 2026). Mientras Jarvis habla se abre un medidor de
energía del micrófono —no el reconocimiento— y, en cuanto detecta voz sostenida, se calla
a media frase y pasa a escucharte. Lo que hace el corte, además de callar:

- **Guarda en el historial lo que llevaba dicho**, marcado como cortado. Sin esto le
  dirías «no, la otra» y el modelo no tendría ni idea de qué hablas, porque el evento
  `fin` —el que añade su respuesta— no llega nunca cuando se aborta el turno.
- **Aborta el turno en el backend** con un `AbortController`. Si no, el modelo sigue
  dando vueltas de herramientas y escribiendo texto que ya nadie va a oír, y se paga.
- **Se corrige solo si corta en falso.** El miedo de todo barge-in es que el micro oiga
  al altavoz y Jarvis se interrumpa a sí mismo. La primera defensa es
  `echoCancellation` del navegador; la segunda es que, si tras un corte no se oye una
  palabra en 2,5 s, el umbral se endurece para el resto de la sesión.

~~**El principio de tu frase se pierde.**~~ Arreglado el 4 de septiembre de 2026 al
poner el micrófono continuo: ya no hay un instante en que el reconocimiento esté cerrado,
así que cuando la llamada decide que le has cortado, tu primera palabra ya está
transcrita. Ver «El micrófono ya no se cierra».

~~**Scribe v2 Realtime sigue sin usarse.**~~ Ya se usa. Ojo con lo que decía este punto y
sigue siendo verdad: **si sale un `auth_error` o un error de tier al abrir el socket, es
el plan y no el código.**

**La fase 8 ya se midió** (septiembre de 2026), y el resultado está abajo.

## La voz se mudó a Azure (septiembre de 2026)

**El problema no era el modelo, era el idioma.** En plan gratuito las voces españolas de
ElevenLabs están en la Voice Library, que está cerrada, así que lo que se oía era George
—una voz **británica**— leyendo español con `eleven_flash_v2_5`, que además es el modelo
optimizado para latencia y el peor de los tres en calidad. Ningún ajuste dentro de
ElevenLabs arreglaba eso sin pagar.

Azure da voces nativas de España (`es-ES-SaulNeural` es la puesta) y **500.000 caracteres
al mes gratis para siempre** en el nivel F0. Una llamada corta al día no llega a unos
pocos miles: es gratis de verdad, no gratis hasta que lo uses.

**Y aquí el audio SÍ pasa por el backend**, al revés que con ElevenLabs. Es una revisión
deliberada de la decisión de la fase 2, no un descuido:

- El argumento en contra era el **arranque en frío**: 10–15 s de Fly cayendo justo en la
  primera palabra. Pero no aplica al camino real — para cuando hay algo que sintetizar,
  el backend acaba de escribir ese texto él mismo en `/jarvis/voz`. Lleva despierto todo
  el turno. El frío se paga al descolgar, una vez, y se pagaba igual antes.
- El otro era **el salto a París**. Fly está en `cdg` y el recurso de Azure en
  `francecentral`: la misma ciudad. Medido desde dentro de la máquina, **0,7 s** por
  frase entera.
- A cambio desaparecen un WebSocket propietario, un SDK de un mega en el bundle (la norma
  del proyecto es no añadir dependencias) y hasta la necesidad de un token. Menos sitios
  donde volver a tener un **fallo mudo**, que es el que ha costado dos tardes.

Lo que se conserva de `vozEleven.js` es el diseño, no el código: cola de frases en orden,
`alFallar` que devuelve **todo lo que quedó sin decir con su `alFinal`**, y el corte que
no rescata nada (si le has hablado encima, lo que tenía preparado ya no viene a cuento).
`vozAzure.js` añade una cosa que el otro no necesitaba: **va pidiendo la frase siguiente
mientras suena la actual**, que es lo que quita la costura entre frases cuando cada una
es una petición aparte.

### La latencia, medida (fase 8)

Desde dentro de la máquina de Fly, o sea **sin la red del móvil y sin la síntesis**:

| Turno | Primer byte | Completo |
|---|---|---|
| «Hola» (sin herramientas) | 1,63 s | 1,72 s |
| «¿Qué hay pendiente de desplegar?» (con herramientas) | 2,67 s | 9,69 s |

Los ocho segundos de diferencia **no son el modelo pensando**: `reasoning_effort` ya está
en `minimal`. Son el bucle — pedir la herramienta es una llamada entera, ejecutarla es un
viaje a Supabase, y redactar la respuesta con el resultado es otra llamada entera. Subir
de modelo no lo arregla; lo encarece.

Lo que sí lo arregla es **no tener que ir a buscar el dato**. Cuando Jarvis llama por un
despliegue, el backend ya sabe cuál es, así que `_jarvis_sistema(voz=True)` se lo mete en
el contexto ya mirado, con la orden de no llamar a ninguna herramienta para eso. La
pregunta más probable de esa llamada pasa de 9,7 s a 1,7 s. Por escrito no se hace: ahí
los segundos no se notan y solo se pagaría la consulta.

Y la regla vieja **sigue en pie**: el reconocimiento se cierra mientras Jarvis habla. Lo
que se abre en su lugar no transcribe, así que no puede oírle a él y contestarse solo. Y
se abre y se cierra en cada turno para que nunca haya dos capturas del micrófono a la
vez, que es lo que se rompe en iOS y en los WebView.

Tres cosas del texto en streaming que conviene saber antes de tocarlo:

- **El backend manda los deltas TAL CUAL, sin trocear.** Dónde se corta una frase lo
  decide el navegador (`trocearParaVoz`), que es el único que sabe qué lleva dicho y qué
  tiene en la cola. El backend no puede saberlo y trocear en los dos sitios sería cortar
  dos veces.
- **`por_decir` en el evento `fin` es lo que evita oír la respuesta dos veces.** El
  cliente dice los deltas según llegan; si al cerrar dijera `respuesta` entera, la
  repetiría. Y no basta con "no digas nada al cerrar": cuando el modelo acaba sin decir
  nada, la respuesta la pone `_texto_garantizado` y ESA no ha salido por ningún altavoz.
  `por_decir` distingue los dos casos, que desde el cliente son indistinguibles.
- **No todo modelo deja retransmitir.** OpenAI exige la organización verificada para
  hacerlo con la familia gpt-5, que es justo de donde sale `JARVIS_MODEL_ACCION`. Si la
  llamada con `stream=True` falla, se repite sin él: se pierde el adelanto de la primera
  frase y nada más. Sale en el registro como «no retransmite»; si aparece a diario, o se
  verifica la cuenta o se baja `JARVIS_MODEL_ACCION` a un modelo que lo permita.
- **No se retransmite lo que puede acabar en la basura.** Con el reparto de dos modelos
  en juego (`JARVIS_VOZ_MODELO_DIRECTO=0`), lo que diga el pequeño se descarta si entra
  el grande: decirlo en voz alta sería contradecirse dos segundos después. Por eso la
  vuelta solo se retransmite cuando ya no puede haber relevo.

**Medido en local** (agosto de 2026, backend en el portátil, no en Fly):

| Pregunta | Modelo | TTS | Antes de oír nada |
|---|---|---|---|
| "hola qué tal" | 1,4 s | 0,7 s | ~2,1 s |
| "qué tiempo hace" (usa herramienta) | 4,9 s | 0,7 s | ~5,6 s |

Eso era **antes del streaming del texto**: los tiempos se sumaban porque la síntesis no
empezaba hasta que el modelo terminaba. El relleno hablado tapó el caso de las
herramientas y el streaming quita los dos segundos de la charla — ahora el TTS arranca
con la primera frase hecha, no con la última. **Está sin volver a medir**: hacerlo es la
fase 8 y sigue pendiente.

## El micrófono ya no se cierra (septiembre de 2026)

Hasta aquí, el modo llamada **cerraba el micrófono mientras Jarvis hablaba**. No por
ahorrar: por altavoz se oía a sí mismo, se transcribía y se contestaba solo. Para poder
cortarle se abría en su lugar un medidor de energía que no transcribía nada
(`vozMicro.js`), y por eso el corte necesitaba ~300 ms de voz sostenida antes de decidir
que eras tú y no un portazo. Funcionaba, y tenía un precio conocido y documentado: **se
comía el principio de tu frase**.

Ahora escucha **Scribe v2 Realtime** y el micrófono está abierto de punta a punta de la
llamada. Lo que eso cambia:

- **El barge-in deja de ser una pieza aparte.** Quien avisa de que te has puesto a hablar
  es el mismo que transcribe: llega un `partial_transcript` mientras Jarvis habla y eso ya
  es la interrupción, con el texto dentro. «Te has puesto a hablar» y «esto es lo que has
  dicho» pasan a ser el mismo evento en vez de dos piezas que pueden no coincidir.
- **El VAD lo hace ElevenLabs** (`commit_strategy=vad`), así que aquí no hay umbrales que
  calibrar. Lo que sí se conserva es que **el fin de frase lo decide el silencio de este
  lado** (`JARVIS_SILENCIO_MS`) y no el `committed` del transcriptor, por la misma razón
  por la que no se usaba el `isFinal` del navegador: cierra a la primera pausa y trocearía
  una frase pensada en tres mensajes sueltos.
- **`vozMicro.js` no se borra: se queda de respaldo.** Sin ElevenLabs configurado, sin
  permiso de micrófono o si el socket se cae a media llamada, se vuelve al reconocimiento
  del navegador con su medidor de energía — que es como funcionaba antes, y es gratis.

### Las tres cosas que lo sostienen, y ninguna es opcional

1. **`echoCancellation` del navegador.** Es la que hace posible tener micro y altavoz
   abiertos a la vez. Sin ella, la voz de Jarvis entra por el micro con energía de sobra.
2. **`pareceEco()`** (`src/lib/voz.js`), la segunda defensa: si lo transcrito se parece a
   lo que Jarvis está diciendo en ese momento, se ignora. **Ante la duda decide que NO es
   eco**, y eso es deliberado: tragarse una interrupción de verdad se nota mucho más que
   cortar de más, que además la llamada ya sabe corregir sola. Por eso exige un mínimo de
   tres palabras — «sí», «vale» y «no» son justo lo que dirías para cortarle.
3. **Cerrar al colgar, siempre.** Scribe **cobra micrófono abierto**, silencios incluidos:
   un socket que sobreviva a la llamada es dinero corriendo que no aparece en ninguna
   pantalla. Se cierra en `colgarLlamada`, que es el único sitio por el que pasan todas
   las formas de terminar una llamada, y también al desmontar el dashboard.

### Detalles de implementación que conviene no deshacer

- **Sin SDK.** La documentación cliente de ElevenLabs enseña su paquete; el protocolo
  crudo son cuatro mensajes y la norma del proyecto es no añadir dependencias. Es lo mismo
  que ya se hizo con el TTS en `vozEleven.js`.
- **`createScriptProcessor` está deprecado y aun así es lo que hay**: es lo único que
  funciona igual en todos los Safari a los que va esto, y un AudioWorklet obligaría a
  servir un módulo aparte. El trabajo por muestra son cuatro operaciones sobre audio mono
  a 16 kHz. Si algún día se oyen cortes en la captura, ese es el sitio.
- **El AudioContext se pide ya a 16 kHz** en vez de remuestrear a mano: lo hace el
  navegador, mejor y gratis.
- **Lo capturado antes de que el socket abra se guarda y se manda al abrir.** Son las
  primeras décimas, o sea justo el «hola»: perderlas sería el mismo fallo de siempre
  cambiado de sitio. Con tope, para que un socket que no abre nunca no se coma la memoria.
- **Un `onclose` inesperado es un fallo, no el final de nada.** Aquí no hay turnos que
  terminen. Es literalmente la lección que costó una tarde con el TTS.
- **Dos tokens distintos y por separado.** El de hablar y el de escuchar son tokens de un
  solo uso independientes, y hoy van a proveedores distintos (Azure habla, ElevenLabs
  escucha). Los dos se renuevan con el mismo reloj de 15 minutos, y **uno pasado de fecha
  no se estrena**: el socket lo aceptaría y lo cerraría con `invalid_token`, que es el
  fallo mudo que ya costó una tarde.

### Lo que esto cuesta

**0,39 $/hora de micrófono abierto**, y el micrófono ahora está abierto toda la llamada
—silencios incluidos—, que antes no lo estaba. Una llamada de diez minutos son ~0,07 $ de
transcripción. Aprobado explícitamente el 4 de septiembre de 2026 sabiendo esto.

Frente a ello, **Azure da 5 horas de STT al mes gratis para siempre** en el nivel F0 y la
clave ya está configurada. Se descartó porque desde el navegador pide su SDK (~1 MB en el
bundle) o implementar un protocolo bastante más feo, y porque Scribe trae el VAD hecho y
va a ~150 ms. Si algún día la factura molesta, ese es el camino de vuelta y está medido.

### La limitación que queda

`iniciarLlamada` sigue exigiendo `SpeechRecognition` para arrancar, aunque con Scribe ya
no haría falta: es la garantía de que siempre hay un respaldo gratis al que caer. En la
práctica no se nota (iOS Safari y Chrome lo tienen), pero significa que en **Firefox no se
puede llamar** aunque Scribe funcionaría perfectamente. Quitarlo pide decidir antes qué
pasa cuando el socket se cae y no hay respaldo ninguno.

## Lo que se aprendió probándolo de verdad

Cosas que no estaban en el plan y costaron encontrar. **Léelas antes de tocar nada.**

- **El plan gratuito no deja usar por API las voces de la Voice Library.** Solo las
  voces por defecto. Y el modo en que falla es el peor posible: por HTTP devuelve
  `402 paid_plan_required`, pero **por el WebSocket contesta `isFinal` con cero bytes de
  audio y ningún error**. Jarvis se queda mudo y no hay nada en ninguna parte que diga
  por qué. Por eso `vozEleven.js` detecta "turno terminado sin una sola muestra" y se
  cae a la voz del navegador avisando en el chat. Si algún día no suena, **prueba
  primero por HTTP**: ahí sí sale el motivo.
  De 22 voces por defecto probadas, 14 funcionan en gratuito y **ninguna es española**;
  todas son anglosajonas hablando español con acento. La voz nativa que se quería es lo
  que compra pagar. La puesta ahora es George (`JBFqnCBsd6RMkjVDRZzb`).
  **Y volvió a pasar, en producción y solo en producción** (agosto de 2026): el secret
  `ELEVENLABS_VOICE_ID` de Fly tenía la voz española de la biblioteca, mientras el `.env`
  local tenía George. En local sonaba; en el móvil la llamada llevaba semanas cayendo a
  la voz del navegador, sin una línea en los logs de Fly, porque el WebSocket no dice
  nada. La moraleja es que **la configuración de la voz hay que comprobarla donde corre,
  no donde se desarrolla**: `fly ssh console -C "..."` o, desde local,
  `python backend/check_config.py --probar-voz`, que sintetiza una palabra por HTTP y
  dice el motivo exacto en vez de dejarte adivinando.
- **El token de `/voz/token` dura 15 minutos, y en el móvil eso se agota siempre.** Se
  pedía UNA vez, al cargar el dashboard. En el ordenador da igual; en el teléfono lo
  normal es abrir la app, guardárselo en el bolsillo y llamar media hora después — con el
  token muerto. Y el fallo era otra vez de los mudos: ElevenLabs **acepta el socket** y
  acto seguido manda `{"error":"invalid_token","message":"Token not found or has
  expired."}` y lo cierra con código 1008. Ese mensaje no lleva `audio` ni `isFinal`, así
  que el cliente lo tiraba sin mirarlo, y el `onclose` se trataba como el final normal de
  un turno: la frase siguiente se "arrancaba" contra un socket cerrado, `enviar` la
  descartaba sin ruido y **nadie volvía a llamar a `alTerminar`**, con lo que la llamada
  se quedaba colgada oyendo el silencio. Ni voz de pago, ni voz del navegador, ni aviso.
  Ahora: el token se renueva al volver a la pestaña (que es justo lo que pasa al
  desbloquear el móvil) y cada diez minutos mientras esté a la vista; uno de más de
  catorce minutos ni se estrena; y cualquier mensaje de error o cierre inesperado del
  socket se trata como fallo de la voz, no como fin de turno.
- **Lo que importa no es que llegue audio, sino que suene.** La detección de "turno mudo"
  miraba si habían llegado bytes; ahora mira si se llegó a programar una muestra en el
  `AudioContext`. Cubre de paso el caso de los trozos MP3 que llegan y no hay manera de
  decodificar, que antes daba silencio sin aviso.
- **Al rendirse se devuelve la cola entera, no solo la frase en el aire.** Un turno son
  varias frases seguidas (el relleno y luego la respuesta); rescatar solo una dejaba a
  Jarvis diciendo "déjame mirar el calendario" y comiéndose lo que había encontrado.
- **Los avisos rojos del chat ya no se guardan en `localStorage`.** Cuentan algo de la
  sesión en curso, y al restaurar el hilo se leían como si estuviera pasando ahora: al
  abrir el dashboard en el móvil lo primero que se veía era el error de una llamada de
  anteayer. El síntoma parecía "la voz falla al entrar" cuando ni siquiera había llamada.
- **`eleven_multilingual_v2` pronuncia algo mejor que Flash, pero no lo bastante para
  pagar su latencia.** Probado y descartado; si se retoma, hay que medirlo.
- **`decir()` encola, no pisa.** Un turno son varias frases seguidas (el relleno y luego
  la respuesta) y la segunda no puede cortar a la primera. Cortar es trabajo de
  `callar()`, que es lo del barge-in. Si esto se toca sin pensar, el relleno vuelve a
  oírse como media palabra atropellada.
- **Cuidado con `apiFetch` y las cabeceras.** Está en `docs/BUGS_HISTORICOS.md`: una
  llamada sin `jsonHeaders()` provoca un 401, y `apiFetch` responde a cualquier 401
  borrando la sesión y recargando. El síntoma es "la contraseña no funciona", que no se
  parece en nada a la causa.

## Cómo levantar esto en local

Esto ya está **desplegado en producción** (backend en Fly y frontend en Vercel, el
26 de agosto de 2026), así que se puede probar entrando al dashboard de siempre. Aun así
lo normal es desarrollar contra el backend local, con el frontend apuntando a él:

```bash
cd backend && ../.venv/Scripts/python -m uvicorn main:app --reload --port 8000
# en otra terminal, desde la raíz:
VITE_API_URL=http://localhost:8000 npm run dev
```

Dos trampas, las dos ya pisadas:

- **`VITE_API_URL` va en el comando, no en un `.env` de la raíz.** Sin ella el frontend
  habla con el backend de Fly y estarías probando contra producción sin enterarte. Y no
  se crea un `.env` en la raíz porque **no está en `.gitignore`** (sí lo está
  `backend/.env`): sería una trampa en un repo público.
- **Tiene que arrancar en el 5173.** Si está ocupado, Vite se va al 5174 y el login
  falla por CORS con un error que parece de credenciales. `netstat -ano | grep 5173` →
  `taskkill //F //PID <pid>`.
- La contraseña del backend local es la de `DASHBOARD_PASSWORD` en `backend/.env`, que
  **no es la de producción**.

## Qué se quiere y qué falta para tenerlo

| Objetivo | Hoy | Con esto |
|---|---|---|
| Voz de Jarvis | `speechSynthesis` del navegador (robótica, distinta en cada dispositivo) | ElevenLabs Flash v2.5, voz fija masculina en español de España |
| Empezar a hablar | ~~Cuando el turno entero ha terminado~~ ya hecho | Con el primer trozo de frase que suelta el modelo |
| Interrumpirle | No se puede: el micro **se cierra** mientras habla | Barge-in: hablas encima y calla al instante |
| Reconocimiento | Web Speech API (gratis, no da acceso al audio) | Scribe v2 Realtime (~150 ms, partials y committed) |
| Coste | 0 € | ~1,6 $ por hora de conversación (ver "Coste") |

Las tres cosas que pediste —hablar mientras genera, poder cortarle y que suene bien—
dependen unas de otras: sin acceso al audio crudo no hay VAD propio, sin VAD no hay
barge-in, y sin streaming de texto no hay nada que interrumpir a mitad. Por eso el plan
va entero y no por piezas sueltas.

## Decisiones tomadas

### 1. El audio va del navegador a ElevenLabs directo, no por el backend

La regla del proyecto es que las claves no llegan al cliente, y **se mantiene**:
ElevenLabs tiene un endpoint pensado exactamente para esto.

```
POST https://api.elevenlabs.io/v1/single-use-token/{tipo}
     xi-api-key: <la clave, solo en el backend>
     tipo ∈ { realtime_scribe, tts_websocket }
  → { "token": "sutkn_…" }        caduca a los 15 min y se consume al usarse
```

El backend emite el token; el navegador abre los dos WebSockets con él. La clave real
nunca sale de Fly.

Lo contrario —proxiar el audio por `backend/main.py`— se descartó por tres motivos, y
el tercero es el que decide: mete un salto a París en cada trozo de audio en ambos
sentidos; obliga a `min_machines_running = 1`, es decir, a pagar la máquina encendida
las 24 horas y renunciar a la escala a cero; y **el arranque en frío de 10–15 s haría
que la primera palabra de cada llamada llegase con la máquina todavía despertando**.
Una llamada no tolera eso.

> El backend sigue siendo quien manda: el LLM, las herramientas, la memoria y la
> confirmación de acciones no se mueven de `/jarvis`. Lo que se saca fuera es solo el
> transporte del audio.

### 2. El texto de Jarvis viaja por SSE desde el backend

El navegador necesita los trozos de respuesta **según se generan** para írselos pasando
al TTS. Endpoint nuevo `POST /jarvis/voz`, `text/event-stream`, con el mismo cuerpo que
`/jarvis` y estos eventos:

```
event: estado       data: {"fase":"pensando"}
event: estado       data: {"fase":"herramienta","nombre":"proximos_eventos"}
event: texto        data: {"delta":"Mañana tienes tres cosas. "}
event: texto        data: {"delta":"La primera es a las nueve."}
event: fin          data: {"herramientas":[…],"pendiente":null,"respuesta":"…"}
event: error        data: {"motivo":"…"}
```

Detalles que no son opcionales:

- **`EventSource` no vale**: no admite POST ni cabecera `Authorization`. Se consume con
  `fetch` + `response.body.getReader()`, como cualquier otro `apiFetch`. El JWT sigue
  yendo en la cabecera; nada de token en la query.
- **El endpoint se queda síncrono** (`def`, no `async def`), como el resto de
  `main.py`: `StreamingResponse` sobre un generador normal, que FastAPI corre en el
  threadpool. No se introduce asyncio en un fichero que no lo usa.
- **`fin` lleva la respuesta entera** aunque ya se hayan mandado los deltas: es lo que
  se guarda en el historial del cliente y lo que se pinta en el chat.
- `/jarvis` sigue existiendo tal cual para el chat escrito. El endpoint nuevo es un
  camino paralelo, no un reemplazo — si el streaming falla, se cae a `/jarvis`.

### 3. Se habla mientras se piensa, y eso choca con dos cosas del bucle actual

Esto es lo más delicado del plan y conviene entenderlo antes de programar.

**Problema A: con herramientas, el modelo no dice nada hasta el final.** El bucle de
`/jarvis` da hasta `JARVIS_MAX_VUELTAS` vueltas; en las intermedias la salida son
`tool_calls`, no texto. Si Jarvis tiene que mirar el calendario, entre tu pregunta y su
primera palabra hay una llamada al modelo, una consulta a Graph y otra llamada al
modelo. Diez segundos de silencio.

Se resuelve con un **relleno hablado**: al emitir `estado: herramienta`, el backend
manda además una frase corta y fija según la herramienta ("Déjame mirar el
calendario.", "Voy a consultarlo."), que el navegador envía al TTS de inmediato. Es
texto del backend, no del modelo: cuesta ~30 caracteres, no añade latencia de LLM y
tapa el hueco exacto que hay que tapar. **No se usa un modelo para redactarlo**: sería
pagar una llamada más justo en el momento en que sobra la latencia.

**Problema B: el reparto de dos modelos añade un turno entero antes de hablar.** Hoy
abre `JARVIS_MODEL` (pequeño) y, si hay que actuar o si se niega, **repite la misma
vuelta** con `JARVIS_MODEL_ACCION`. Por voz eso es una llamada completa de latencia
antes de la primera sílaba. Por voz se va **directo a `JARVIS_MODEL_ACCION`**, saltando
el reparto. Cuesta algo más por turno; a cambio Jarvis empieza a hablar un par de
segundos antes, que es justo lo que se está comprando aquí. Interruptor propio:
`JARVIS_VOZ_MODELO_DIRECTO` (por defecto activo).

**Y una tercera, que ya está resuelta y no hay que tocar:** las acciones que piden
confirmación (`_jarvis_confirma`) siguen pidiéndola. Por voz Jarvis dice lo que va a
hacer y el botón sigue apareciendo en el chat. **Nada se ejecuta por hablar**, igual
que hoy. El modo llamada no relaja la frontera de confirmación.

### 4. El TTS va por el WebSocket multi-contexto

```
wss://api.elevenlabs.io/v1/text-to-speech/{voice_id}/multi-stream-input
    ?model_id=eleven_flash_v2_5
    &output_format=pcm_24000
    &language_code=es
    &auto_mode=true
```

Se usa la variante **multi-contexto** (no `stream-input` a secas) por una razón muy
concreta: `close_context` **cancela lo que quedara por sintetizar sin cerrar el
socket**. Eso es exactamente el barge-in: cortas a Jarvis, se cierra el contexto de ese
turno, se abre otro para la respuesta siguiente y no se paga audio que nadie va a oír.
Con un socket de un solo contexto habría que cerrarlo y reabrirlo en cada
interrupción, sumando el apretón de manos a la latencia del turno nuevo.

- Los contextos **caducan a los 20 s de inactividad**: hay que mandar `flush: true` al
  cerrar cada frase y abrir contexto nuevo por turno.
- **`output_format=pcm_24000`, no MP3.** El PCM entra directo en un `AudioContext` como
  cola de buffers, y cortar es vaciar la cola: instantáneo. Con MP3 haría falta
  `MediaSource`, que en Safari/iOS es un campo de minas y no corta limpio.
- **Pero el formato es una variable, no una constante** (`ELEVENLABS_FORMATO`). Los
  formatos PCM tienen restricción por plan y la cuenta arranca en el gratuito, así que
  la reproducción se escribe capaz de las dos cosas: PCM por la cola de buffers cuando
  está disponible, y MP3 por `HTMLAudioElement` cuando no. Con MP3 el corte no es
  instantáneo — se nota una coleta de audio al interrumpir — pero el resto funciona
  igual. Cambiar de uno a otro al pasar a un plan de pago debe ser cambiar la variable,
  no reescribir el reproductor.

### 5. El STT es Scribe v2 Realtime, y el micro no se cierra nunca

```
Scribe.connect({ token, modelId: "scribe_v2_realtime",
                 audioFormat: PCM_16000, sampleRate: 16000 })
  → SESSION_STARTED · PARTIAL_TRANSCRIPT · COMMITTED_TRANSCRIPT · ERROR · CLOSE
```

Hoy el micrófono **se cierra mientras Jarvis habla**, y el comentario del código
explica por qué: por altavoz se oía a sí mismo, se transcribía y se contestaba solo.
Esa protección se retira, y lo que ocupa su lugar es:

1. **`getUserMedia({ audio: { echoCancellation: true, noiseSuppression: true } })`** —
   la cancelación de eco del navegador resta lo que sale por el altavoz de lo que entra
   por el micro. Es la pieza que hace posible tener los dos abiertos a la vez.
2. **Un umbral de energía con histéresis** sobre el stream: se exige voz sostenida
   (≈250 ms por encima del umbral) antes de declarar barge-in. Un carraspeo o un portazo
   no le cortan.
3. **Descartar la transcripción que llegue con eco reconocido**: si el texto entrante se
   parece a lo que Jarvis está diciendo en ese momento, se ignora. Red de seguridad por
   si la cancelación de eco falla en algún dispositivo.

> **La primera prueba, con auriculares.** Si el bucle de realimentación se cuela por el
> altavoz, con auriculares no puede ocurrir y sabes que el resto de la máquina funciona.
> Después ya se prueba a altavoz, que es donde de verdad se juega esto.

## Arquitectura resultante

```
  ┌─ NAVEGADOR ────────────────────────────────────────────────┐
  │                                                            │
  │  getUserMedia (echoCancellation)                           │
  │       │                                                    │
  │       ├──► VAD (energía + histéresis) ──► barge-in         │
  │       │                                                    │
  │       └──► WS ──► ElevenLabs Scribe v2 ──► transcripción   │
  │                                              │             │
  │                          POST /jarvis/voz ◄──┘             │
  │                                 │  (SSE: estado + deltas)  │
  │                                 ▼                          │
  │                          Chunker (40–100 car.)             │
  │                                 │                          │
  │                                 ▼                          │
  │                   WS multi-context ──► Flash v2.5          │
  │                                 │                          │
  │                                 ▼  PCM 24 kHz              │
  │                          AudioContext ──► 🔊               │
  └────────────────────────────────────────────────────────────┘
                                    ▲
                POST /voz/token ────┘   (backend, con la API key)
```

## Qué se toca en el repositorio

### `backend/main.py`

Sección nueva `# ── Jarvis: voz en tiempo real ──`, después de la de Jarvis.

| Pieza | Qué hace |
|---|---|
| `POST /voz/token` | `Depends(verify_token)`. Cuerpo `{"tipo": "realtime_scribe"\|"tts_websocket"}` validado con `Literal` — nada de interpolar en la URL de ElevenLabs lo que mande el cliente. Devuelve `{token, expira_en, voice_id, model_id}`. **Con el limitador genérico por IP** (`_check_rate`), que es el que protege recursos caros, igual que `/ideas/audio`. Nunca loguea el token. |
| `POST /jarvis/voz` | El SSE de arriba. Reutiliza el bucle de `/jarvis` extraído a una función generadora; el endpoint viejo pasa a consumirla entera. **No se duplica el bucle**: duplicarlo garantiza que la memoria, la confirmación o las herramientas se arreglen en un sitio y no en el otro. |
| `_relleno_herramienta(nombre)` | La frase fija de cada herramienta. Diccionario, sin modelo detrás. |
| `_eleven_token(tipo)` | La llamada saliente, con `main.http` (el cliente compartido) para que los tests la puedan sustituir. Errores con el criterio de siempre: detalle al registro, mensaje genérico al cliente. |

Variables nuevas, todas documentadas en `backend/.env.example` y comprobadas en
`backend/check_config.py`:

```env
ELEVENLABS_API_KEY=            # solo en el backend. En producción: fly secrets set
ELEVENLABS_VOICE_ID=           # la voz elegida (ver "Lo que tienes que hacer tú")
ELEVENLABS_MODEL=eleven_flash_v2_5
ELEVENLABS_STT_MODEL=scribe_v2_realtime
ELEVENLABS_FORMATO=pcm_24000
JARVIS_VOZ_ELEVENLABS=0        # el interruptor: apagado por defecto
JARVIS_VOZ_MODELO_DIRECTO=1    # salta el reparto de dos modelos en las llamadas
JARVIS_VOZ_MAX_MINUTOS=20      # corta la llamada sola: es dinero por minuto
```

**`JARVIS_VOZ_ELEVENLABS=0` por defecto y sin fallback de clave.** Sin clave o con el
interruptor apagado, `/voz/token` devuelve 503 con un motivo claro y **el frontend se
queda con el modo llamada actual**, que sigue funcionando gratis. Lo que hay hoy no se
borra hasta que lo nuevo esté probado en el móvil.

### `src/lib/voz.js` (nuevo)

Lógica pura, testeable con vitest, fuera de `Dashboard.jsx` según la norma del
proyecto:

- `trocearParaVoz(buffer)` — el chunker. Acumula deltas y suelta trozos de 40–100
  caracteres **cortando en límite lingüístico** (`. ! ? …` primero, coma o conjunción
  después, y solo por longitud como último recurso). Lo que devuelve es lo que suena:
  cortar por la mitad de un sintagma se oye fatal.
- `vozDetectada(muestras, estado)` — el VAD: energía RMS con histéresis y los dos
  umbrales (entrada/salida). Puro: entra un array de números, sale un booleano y el
  estado nuevo.
- `pareceEco(dicho, hablando)` — la red de seguridad del punto 5.3.
- `siguienteEstado(estado, evento)` — la máquina de estados (`IDLE`, `ESCUCHANDO`,
  `PENSANDO`, `HABLANDO`, `INTERRUMPIDO`) como reducer puro. Que sea puro es lo que
  permite probar el barge-in en un test sin navegador.

### `src/components/Dashboard.jsx`

El modo llamada actual (`iniciarLlamada`, `escucharEnLlamada`, `turnoDeLlamada`,
`finDeFrase`, `colgarLlamada`) se convierte en **dos implementaciones tras la misma
interfaz**: la de Web Speech que ya está, y la de ElevenLabs. Elige una u otra según lo
que responda `/voz/token`. La UI (botón de llamar, fases, transcripción parcial) no
cambia de sitio; se le añade el indicador de que Jarvis está siendo interrumpido.

Trampas conocidas que hay que respetar, todas con precedente en este repo:

- **iOS solo desbloquea el audio dentro de un gesto**: el `AudioContext` se crea y se
  hace `resume()` en el propio toque del botón de llamar, igual que hoy se hace el
  primer `speak()`. Si el primer audio llega después de un `fetch`, la llamada es muda
  en el móvil.
- **Los callbacks nacen en un render y viven muchos más**: sigue haciendo falta la
  indirección por `cicloRef`, o Jarvis pierde el hilo a partir del segundo turno.
- **Desmontar con la llamada abierta** deja el micro grabando y pagando: el `useEffect`
  de limpieza tiene que cerrar los dos WebSockets y el `AudioContext`, no solo parar el
  reconocimiento.
- **Colgar tiene que cerrar el contexto de TTS**, no solo silenciar el altavoz. Si no,
  se sigue sintetizando (y pagando) audio que ya no oye nadie.

### Tests

- `tests/backend/test_voz.py` — `/voz/token` sin clave da 503; con el interruptor
  apagado da 503; el `tipo` inválido da 422; el token no aparece en los logs; el
  limitador salta. El SSE: que emite `estado` antes que `texto`, que `fin` lleva la
  respuesta completa, y que una herramienta pendiente de confirmar **sigue quedando
  pendiente** por este camino.
- `tests/frontend/voz.test.js` — el chunker (que no parte sintagmas, que respeta el
  rango, que vacía el resto al final), el VAD (histéresis, que un pico corto no
  dispara) y la máquina de estados (que `INTERRUMPIDO` desde `HABLANDO` va a
  `ESCUCHANDO` y cancela).
- **E2E: no.** Playwright no tiene micrófono ni va a hablar con ElevenLabs. El modo
  llamada actual tampoco está cubierto por E2E, por lo mismo.

## Orden de trabajo

Cada fase deja algo que se puede probar y que no rompe lo anterior.

| # | Fase | Se prueba con |
|---|---|---|
| 1 | ✅ `/voz/token` + `.env.example` + `check_config.py` + tests | curl: sale un `sutkn_…` |
| 2 | ✅ TTS: WS multi-contexto y reproducción (PCM o MP3) | Jarvis dice "hola" con su voz nueva |
| 3 | ✅ `/jarvis/voz` (SSE) con el texto en streaming, cableado al modo llamada | Jarvis empieza a hablar antes de terminar de generar |
| 4 | ✅ Relleno hablado en las herramientas | pregunta con calendario: ya no hay diez segundos mudos |
| 5 | STT con Scribe: micro → transcripción → turno | la llamada entera, todavía sin cortarle |
| 6 | VAD + barge-in + `close_context` | le hablas encima y calla |
| 7 | Límites: minutos máximos, reconexión, red caída | desenchufar el wifi a media frase |
| 8 | Medir: tiempo hasta la primera palabra, coste por llamada | una semana de uso real |

Fases 1–4 son el 80 % de lo que se nota (voz buena y respuesta inmediata) y no tocan el
micrófono para nada. Si en algún punto hay que parar, ese es el sitio.

## Coste

Precios PAYG verificados en agosto de 2026 (**vuelve a mirarlos antes de desplegar**,
cambian):

| Concepto | Precio |
|---|---|
| Flash v2.5 (TTS) | 0,05 $ / 1.000 caracteres |
| Scribe v2 Realtime (STT) | 0,39 $ / hora de audio |

Una llamada de diez minutos, con `JARVIS_MAX_TOKENS_VOZ=160` (unos 600 caracteres por
respuesta como mucho) y unos diez turnos:

```
STT   10 min                    → 0,065 $
TTS   ~4.000 caracteres         → 0,200 $
                                  ───────
                                  ~0,27 $     ≈ 1,6 $/hora de conversación
```

El STT cobra **micrófono abierto**, no palabras dichas: los silencios se pagan. De ahí
`JARVIS_VOZ_MAX_MINUTOS` y el colgado automático que ya existe cuando llevas un rato sin
decir nada. Y de ahí también que el barge-in cierre el contexto: cada interrupción sin
cancelar es audio pagado y tirado.

Frente a esto, el modo llamada actual cuesta 0 € porque lo hace el dispositivo. Merece
la pena tener claro que se está cambiando gratis por bueno.

### El punto de partida es el plan gratuito

La cuenta empieza sin pagar, y eso **no bloquea el trabajo pero sí acota la prueba**:

- La cuota gratuita se mide en créditos al mes y da del orden de **minutos**, no de
  horas. Sirve para comprobar que la voz suena bien y que el texto sale mientras se
  genera; no para usar el modo llamada a diario. Una sola conversación larga se come
  la asignación del mes.
- **PCM y Scribe v2 Realtime pueden estar restringidos por plan.** Si al abrir el
  WebSocket sale un 401 de permisos o un error de tier, es eso y no un fallo del
  código. Por eso el formato es configurable y por eso el orden de fases pone el
  micrófono al final.
- El plan gratuito de ElevenLabs **exige atribución y no permite uso comercial**. Para
  un dashboard personal de un solo usuario da igual, pero conviene saberlo.

Consecuencia práctica: las fases 1–4 se pueden construir y probar ya. Las fases 5–6
(micrófono e interrupciones) se escriben igual, pero puede que no se puedan *probar*
hasta meter saldo. No merece la pena pagar antes de que la parte de hablar funcione.

## Seguridad

Aplican las invariantes de `CLAUDE.md` sin excepción, y dos añadidas:

- **`ELEVENLABS_API_KEY` solo en el backend.** En `backend/.env` en local y en
  `fly secrets set` en producción. Nunca en `VITE_*`: todo lo que empieza por `VITE_`
  acaba dentro del bundle público.
- **El token de un solo uso no se registra en ningún sitio** — ni en `app_logs` ni en el
  `logger`. Vale 15 minutos, pero 15 minutos bastan para gastar dinero de la cuenta.
- **`/voz/token` es de usuario, no de servicio**: `Depends(verify_token)`. Nada que
  arranque solo necesita voz, así que no hay motivo para darle un token de servicio.
- El `tipo` del token se valida con `Literal`, no se interpola tal cual en la URL
  saliente (misma regla que los path params del punto 6 de `CLAUDE.md`).

## Lo que tienes que hacer tú

Ya hecho (agosto de 2026): cuenta creada, API key con permisos solo de *text-to-speech*
y *speech-to-text*, y `ELEVENLABS_API_KEY` / `ELEVENLABS_VOICE_ID` /
`JARVIS_VOZ_ELEVENLABS=1` puestos en `backend/.env`.

Lo que queda pendiente de la persona, no del código:

1. **Meter saldo o subir de plan**, si se quiere una voz española de verdad (las de la
   Voice Library están cerradas en gratuito) o usar esto más de unos minutos al mes.
2. ~~Poner los secretos en Fly y desplegar.~~ Hecho el 26 de agosto de 2026:
   `ELEVENLABS_API_KEY`, `ELEVENLABS_VOICE_ID` y `JARVIS_VOZ_ELEVENLABS=1` están puestos
   y aplicados. Si algún día hay que rehacerlo: `fly secrets set --stage …` (con
   `--stage` para no reiniciar las máquinas por una variable que el código desplegado
   todavía no lee) y `fly deploy` desde `backend/`, que sigue siendo manual.
3. **Decidir auriculares o altavoz** para la primera prueba del barge-in, cuando llegue
   la fase 6. Con auriculares primero, que es la que no depende de la cancelación de eco.

## Lo que sigue sin resolverse

Honestamente, y para que no sorprenda después:

- **El barge-in por altavoz en iOS es el riesgo real del plan.** La cancelación de eco
  de Safari con `AudioContext` y `getUserMedia` simultáneos no se comporta igual que en
  Chrome de escritorio. Si no sale, el plan B es mantener el micro cerrado mientras
  habla **en iOS solamente** y detectar la interrupción por un toque en pantalla.
- **Fly escala a cero.** La primera petición de una llamada despierta la máquina: 10–15 s.
  Ya está tapado en parte: `/voz/token` se pide al montar el dashboard, no al pulsar
  llamar, así que la máquina suele estar despierta cuando hace falta. Pero **las medidas
  de arriba son con el backend en el portátil**: contra Fly, ya desplegado, están sin
  repetir. Eso es la fase 8.
- **El MP3 troceado no está garantizado.** Cada trozo que llega por el WebSocket se
  decodifica suelto, y eso solo funciona si vienen alineados a frames. El que falla se
  guarda y se reintenta pegado al siguiente. En las pruebas ha ido bien (el primer trozo
  llega con cabecera `ID3`), pero con PCM el problema no existe: al pasar a un plan de
  pago, `ELEVENLABS_FORMATO=pcm_24000` quita esta clase de fallo entera.
- **Los tests no cubren el navegador.** Lo puro de `src/lib/voz.js` sí; el WebSocket, el
  `AudioContext` y el cableado del modo llamada no los cubre nada, y el E2E tampoco
  puede (Playwright no tiene micrófono ni altavoz). Todo lo de `vozEleven.js` se ha
  comprobado a mano.
