<!-- Parte de la guía del repositorio. El índice y las reglas que aplican
     SIEMPRE están en CLAUDE.md, en la raíz. -->

## Bugs históricos (no los reintroduzcas)

- **Un aviso pedido a mano llegaba doce horas tarde, y dos veces.** El síntoma era
  siempre el mismo: un recordatorio de la tarde apareciendo en el móvil a la mañana
  siguiente. Lo que lo hacía difícil es que **el sistema no guardaba en ningún sitio con
  cuánto retraso había salido cada aviso**, así que después no se podía distinguir de la
  otra explicación posible —que el modelo lo hubiera apuntado a la hora equivocada al
  resolver «a las 9»— y las dos se arreglan por sitios distintos. Se diagnosticó a ciegas
  las dos veces. La causa era el presupuesto de avisos: `AVISOS_MAX_DIA` son **tres** al
  día, y todo lo que lleva `regla` y no entra se pospone a `AVISOS_HORA_DIFERIDOS`
  (08:30). La frontera "lo que pediste tú no se gobierna" solo miraba `regla IS NULL`
  (`recordarme`), y las **reglas que aprueba el usuario** (`tuya:*`) llevan `regla` por
  sus estadísticas: una regla tuya de las 20:30 caía en el tope y salía a las 08:30 del
  día siguiente. Tres cosas que dejó:
  - **El presupuesto es para el ruido del SISTEMA.** `_es_tuyo()` deja fuera del tope y
    del aplazamiento a las reglas del usuario, y también las saca del recuento: si
    contaran, tres avisos tuyos callarían a las reglas de verdad el resto del día.
  - **Un aplazamiento se registra.** Posponer de la noche a las 08:30 es retrasar doce
    horas, que desde fuera es idéntico a un reloj parado. Y `_posponer_aviso` ahora mira
    el código de respuesta: un PATCH rechazado dejaba el aviso vencido para siempre,
    ocupando sitio en la ventana del despacho (10 por tick) sin salir nunca.
  - **El retraso de entrega se mide** (`_registrar_retraso`): `warning` a los 15 min,
    `error` a la hora, que es lo que lo lleva a `app_logs`, al panel y al vigilante sin
    abrir un camino nuevo. *Un fallo que no deja medida no se arregla, se adivina.*
  Y de paso salió un segundo agujero por el mismo sitio: **el despacho de recordatorios es
  lo último que evalúa el tick de HA**, detrás de todo lo que apunta avisos, así que una
  excepción suelta en cualquiera de esos pasos no costaba un aviso —costaba TODOS los
  recordatorios vencidos mientras durase la avería, en silencio, porque el 500 del tick
  solo lo veía Home Assistant—. Ahora van todos envueltos.

- **Jarvis se quedaba MUDO justo en las peticiones interesantes.** Pedirle algo de varios
  pasos («busca esto, mira la documentación y dime si hay MCP») devolvía una burbuja
  vacía —el cliente pinta «(sin respuesta)»— con la herramienta ya ejecutada debajo. Las
  preguntas fáciles iban bien, así que parecía cosa del modelo. No lo era: el techo de
  tokens. `JARVIS_MAX_TOKENS` acota la RESPUESTA, pero un modelo de razonamiento
  (`JARVIS_MODEL_ACCION` es uno) cobra su techo contra lo que piensa **más** lo que dice,
  y cuanto más gorda es la petición más piensa — hasta que no le queda nada con que
  hablar y devuelve `content=""` con `finish_reason="length"`. Un techo pensado para que
  no se enrollara le estaba tapando la boca. Tres cosas que dejó:
  - **`_parametros_modelo()` le da a los razonadores el techo de la respuesta MÁS
    `JARVIS_RESERVA_RAZONAMIENTO`.** Un tope solo se paga si se usa; el que costaba
    dinero era el otro, en respuestas perdidas.
  - **Un turno no puede salir vacío**, venga de donde venga el vacío. En el punto único
    de salida (`_texto_garantizado`): queda en el registro —así sale en `app_logs` y en
    el `diagnostico`—, se reintenta el cierre con el modelo pequeño y sitio de sobra y,
    si aun así no dice nada, se contesta con lo que el backend sí sabe (lo que la
    herramienta pidió decir literalmente, o al menos qué se llegó a consultar). *Una
    respuesta pobre pero cierta vale más que un hueco en blanco.*
  - **El aviso accionable moría con la respuesta.** La búsqueda estaba devolviendo su
    error con el arreglo dentro («configura `TAVILY_API_KEY`»), redactado para el
    usuario, y el turno vacío se lo tragaba entero: en pantalla no quedaba ni el motivo.
    Ahora esos textos se apartan al ejecutar la herramienta y son la primera red del
    turno mudo. La moraleja de siempre, por un sitio nuevo: *"no pude" no es "no hay
    nada"* — pero solo si llega a decirse.

- **El primer aviso al móvil se perdió entero y el dashboard dijo que había salido.** Al
  estrenar el canal, la automatización de HA llevaba `notify.mobile_app_TU_MOVIL` — el
  hueco de la plantilla de `docs/HOME_ASSISTANT_JARVIS.md`, copiado tal cual. Ese servicio
  no existe, así que la automatización se disparaba y reventaba al mandar. Y aquí está lo
  que importa: **desde el backend eso es indistinguible del éxito**. HA había pasado a
  recoger la cola, que es la única señal que hay, así que el panel decía "enviado al
  móvil" mientras el aviso moría dentro de HA. Tres cosas que dejó:
  - **Recoger no es entregar.** El botón de prueba ahora dice "encolado" y nombra los dos
    sospechosos (la automatización y el `notify`), en vez de afirmar una entrega que no ha
    comprobado. Es el mismo error que el `streaming_ready` del agente sobre un Sunshine
    que no estaba abierto: *lanzar algo no es comprobar que funciona*.
  - **El punto ciego sigue abierto**: un aviso recogido por HA y no entregado no lo
    rescata nadie, porque el rescate solo cubre lo que NADIE recoge. Cerrarlo pide un ack
    de HA — está propuesto en `docs/IDEAS.md`, sin hacer.
  - Y una del lado de fuera: los errores de HA **no** están en `/config/home-assistant.log`
    con Supervisor; se leen con `ha core logs`. Buscarlos donde no estaban fue lo que
    alargó el diagnóstico.

- **Jarvis dijo que no sabía hacer justo lo que sabía hacer.** A «quiero que aprendas a
  hacer reservas en restaurantes, aprende esa skill o importa mcps, como sea» contestó
  «no puedo aprender nuevas habilidades ni importar capacidades de manera autónoma» — el
  turno en que se estrenaba `mcp_conectar`, que hace exactamente eso. No fue el prompt:
  las dos reglas estaban ahí («puedes AMPLIARTE tú mismo», «antes de decir que no, mira
  `mis_capacidades`»). Fue el **reparto de modelos**: el pequeño decidió que no hacía
  falta ninguna herramienta, y como el relanzamiento al grande solo se disparaba al PEDIR
  una, el que sabe elegir no llegó a ver la petición. El sesgo de asistente («no puedo
  hacer eso de forma autónoma») pesa más que cualquier instrucción cuando el modelo
  contesta sin mirar. Moraleja doble: **delegar en el modelo pequeño la decisión de si
  hace falta una herramienta le regala también la de rendirse**, y —la de siempre en este
  proyecto, otra vez por el mismo sitio— *"no pude" no es "no hay nada que hacer"*.
  Arreglado relanzando también las negativas, con test.

- **Un mes de métricas nocturnas a n=3, y no había ningún bug: el reloj estaba en un
  cajón.** El correo del 07/08 traía sueño, HRV, FC en reposo y respiración con tres
  observaciones, y los pasos con 29. Parece una ingesta rota y no lo era: los pasos los
  cuenta el iPhone él solo, y todo lo demás necesita el Watch puesto. Los tres días eran
  los tres desde que volvió a llevarse. **Antes de buscar el fallo en el código,
  comprueba si la métrica que falta necesita un sensor que estuviera puesto** — la
  asimetría "pasos sí, todo lo demás no" es la huella de eso, no de un endpoint roto.
  El `n` de cada media hizo justo su trabajo (avisar de que no hay base), y aun así se
  leyó como avería: el resumen no puede distinguir "no se midió" de "no llegó", y quien
  lo lee tampoco.
  **Ya sí puede** (agosto de 2026): la sección `## RELOJ` dice qué días estuvo puesto y
  cada media del Watch viaja con el denominador de los días en que se pudo medir, así que
  `n=3/3` (no falta ni un día de los que hubo) se distingue de `n=3/29` (ahí sí falta
  ingesta) sin tener que reconocer la asimetría a ojo.
  De diagnosticarlo salieron tres arreglos reales, ninguno causante de aquello:
  - El Atajo manda `value` **vacío** cuando su "Find Health Samples" no encuentra nada
    —cada día sin reloj—, y eso se guardaba como un `0` (`if v == "": v = 0`). Mientras
    no hay medida solo ocupa sitio, pero el día que la haya, si el Atajo corre después,
    ese 0 la **pisa**: el upsert resuelve por `(metric_date, metric_name)`. **Un hueco
    no es un cero** — la misma regla que impide dar por vigente la presencia caducada.
    Y como un cliente que manda huecos no falla nunca, si de un envío no llega ni una
    muestra con medida se registra (`logger.warning`).
  - El resumen leía cada métrica **del primer nombre que tuviera filas**, así que un día
    suelto de `apple_exercise_time` tapaba meses de `exercise_time`. Ahora fusiona por
    fecha (`_filas_por_alias`), como ya hacía `findMetric` en el frontend.
  - Y descartaba las filas con `value` a null aunque llevaran la medida dentro de `extra`
    (las que dejó el bug del `Avg`): histórico real que estaba guardado y no se leía.
- **El Watch dejó de sincronizar otra vez, y esta vez el registro decía "400" y nada
  más.** `POST /health/ingest` rechazaba todos los envíos de Health Auto Export porque
  el cuerpo llegaba como una LISTA de lotes (lo que manda con "Batch requests"
  activado) y el endpoint solo aceptaba el `{"data": {...}}` suelto. Se perdía la
  sincronización entera por el envoltorio, no por los datos. Lo que lo hizo durar
  semanas no fue el 400: fue que **el detalle del error solo viajaba en la respuesta
  HTTP**, y el cliente es una app del móvil que no la enseña — en `app_logs` constaba
  `POST /health/ingest → 400 (1 ms)` repetido cientos de veces, sin una sola pista de
  qué llegaba. Ahora el 400 registra la FORMA del cuerpo (tipo, tamaño, content-type;
  los primeros bytes solo si ni siquiera era JSON, que es cuando no son datos de
  salud). Moraleja, la misma del 409 pero por el otro lado: **un error que solo sabe
  contarlo el cliente equivale a no haberlo registrado**.
- **El correo del brief daba medias de 7 y 30 días que eran el mismo dato repetido.**
  `_media` promediaba los últimos N **registros**, no los de los últimos N **días**: con
  el histórico agujereado (por el 400 de arriba), la "media de 7d" abarcaba meses, y una
  métrica con una sola observación salía con último, 7d y 30d idénticos. La rutina que
  lee el correo lo interpretaba como estabilidad perfecta y escribía conclusiones sobre
  desviaciones que no existían. Ahora las ventanas son por fecha real y **cada media
  viaja con su `n`**. Moraleja: **una media sin el número de muestras detrás no es un
  dato, es una afirmación sin respaldo** — y el que la lee no tiene forma de saberlo.
  Relacionado: una fila con `metric_date` en el futuro (hay un `heart_rate` fechado en
  diciembre) entraba en la ventana de 30 días, porque el filtro es `gte`, y se convertía
  en "el último valor" de su métrica. `_brief_salud` descarta ahora las fechas futuras.

- **El mismo bug de las medias del correo estaba también en el dashboard, y ahí
  afirmaba.** `seriesTrend` y las medias de `healthConclusions` cogían los últimos N
  REGISTROS (`slice(-7)`, `slice(-30)`), no los de los últimos N días. Con el histórico
  agujereado por el mes sin reloj, la "media de 7 días" podía abarcar dos meses y la de
  30 el histórico entero: las dos ventanas acababan siendo casi el mismo conjunto de
  medidas y de compararlas salía una tendencia que no existía. El correo, con el mismo
  fallo, solo daba una cifra sin base; aquí el resultado era una frase: *"tu HRV está un
  12% por debajo de tu media de 30 días"*. Lo mismo hacía el peso, que comparaba con el
  octavo registro hacia atrás llamándolo "hace ~1 semana" cuando uno no se pesa a diario.
  Arreglado con ventanas por fecha real contra un `hoy` inyectable, exigiendo fondo a los
  dos lados antes de hablar de tendencia, y con tests. Moraleja, la de siempre: **un
  arreglo que no se busca en los demás sitios donde vive el mismo patrón está a medias.**

- **Un percentil calculado "a día de hoy" habría hecho el histórico irreproducible.** Al
  meter líneas base personales, la tentación es calcular los percentiles con todo lo que
  hay hasta ahora. Con eso, el mismo día del histórico puntúa distinto cada vez que se
  abre el dashboard —y la sparkline de evolución deja de ser comparable consigo misma— sin
  que nada parezca roto. La regla es la que ya había puesto `_refHrv` y que ahora está
  escrita: **toda referencia se ancla a la fecha que se puntúa, no a hoy.**

- **El streaming tardaba 45 segundos "en negro" tras encender el PC.** No era la red,
  ni el WOL, ni Sunshine: era la primera invocación de `powershell.exe` del arranque,
  que agotaba el timeout de 40 s del agente antes de devolver un simple
  `Get-Service`. Con el PC ya caliente el mismo job tardaba 5 s, así que desde fuera
  parecía "a veces va lento". Ver "Nada de PowerShell en el camino crítico".
  Moraleja: **en el arranque en frío, el coste de arrancar un intérprete supera con
  mucho al del trabajo que va a hacer** — para preguntas de sistema simples, la
  herramienta nativa.
- **Un lote vacío del Watch se registraba como fallo.** La protección que detecta
  "cuerpo con la estructura equivocada" (la del 409) también atrapaba los
  `{"data": {}}` que Health Auto Export manda varias veces al día cuando no hay nada
  nuevo que exportar, que es su funcionamiento normal. Resultado: 49 avisos en una
  semana tapando en `app_logs` los que sí importaban, que es justo lo contrario de
  para lo que se creó esa tabla. Ahora `_lote_vacio()` los separa: estructura
  reconocida y sin muestras → INFO y `ok: true`; cualquier otra cosa (un `{}` pelado,
  otro envoltorio, o muestras que no se reconocen) sigue siendo WARNING y `ok: false`.
  Moraleja: **"no tengo nada que darte" y "te estoy hablando en otro idioma" no pueden
  compartir nivel de log**, o el registro deja de ser señal.
- **`/ha/events/soon` devolvía 500 si Graph no llegaba a contestar.** `_graph_fallo()`
  cubría las respuestas CON error, pero un fallo de red (conexión cortada, DNS,
  timeout) sale como excepción, se salta ese manejo y acaba en un 500 — y HA solo sabe
  leer `{"event": None}`. Pasó el 2026-08-04 durante un reinicio de Home Assistant.
  Al proteger un endpoint de un servicio externo, cubre los dos: el que responde mal
  y el que no responde.

- **El job de streaming decía "Sunshine abierto" con Sunshine sin abrir.** El agente
  hacía `subprocess.Popen([SUNSHINE_EXE])` y reportaba `streaming_ready` acto seguido.
  Pero `Popen` sin excepción solo dice que Windows aceptó *crear* el proceso, no que
  siga vivo un segundo después: al agente lo lanza el Programador de tareas fuera del
  escritorio del usuario, y Sunshine desde ahí se cierra al instante (ni proceso, ni
  puertos escuchando, `SunshineService` en `Stopped`). El log del agente terminaba con
  "✅ Sunshine lanzado" y el job en `done`. La tercera vez que aparece el mismo patrón
  del proyecto —el 409 del Watch, el 401 del agente, esto—: **lanzar algo no es
  comprobar que funciona**, y un job solo se marca `done` tras verificar el efecto.
  Arreglado arrancando el servicio (como Tailscale) y esperando a ver el proceso vivo.
  (El host pasó después a Apollo y los símbolos se llaman hoy `APOLLO_EXE`,
  `arrancar_apollo()` y `apollo_vivo()`; el fallo y su moraleja son los mismos, y el
  binario sigue llamándose `sunshine.exe` porque Apollo no lo renombró.)
- **`/jobs/pending` era un 502 fijo por un `+` en la query string.** El corte de "última
  hora" se formateaba como `...T05:10:01+00:00` y se pegaba a la URL de Supabase; en una
  query string el `+` significa espacio, así que PostgREST leía `...T05:10:01 00:00` y
  devolvía 400 (`22007`, timestamp inválido). Estuvo tapado detrás del 401 del token
  caducado del agente: solo se vio al arreglar la auth. **Los timestamps que viajan en
  una URL van con sufijo `Z`, nunca con `+00:00`** (o `quote()`-ados). Hay test. El mismo
  fallo se había dado antes con el `created_at` del último pago en `/training/summary`,
  donde la solución fue `urllib.parse.quote`.
- **El agente PC se cerraba en cada arranque diciendo "No hay jobs pendientes".** El
  `LA_TOKEN` de su `.env` era un JWT del dashboard y caducó a los 30 días, así que
  `GET /jobs/pending` devolvía 401. Pero `poll_pending_job()` capturaba *todo* con un
  `except Exception` y devolvía `None`, el mismo valor que "la cola está vacía": el
  agente registraba un WARNING y salía con código 0, con lo que la tarea del Programador
  también lo daba por bueno. Desde fuera parecía que el WOL funcionaba y que
  simplemente no había trabajo. Dos moralejas, las mismas que dejó el 409 del Watch:
  **"no pude preguntar" no es "no hay nada que hacer"**, y **lo que arranca solo no
  puede depender de una credencial que caduca** (ver `AGENT_TOKEN`). El caso está
  cubierto por `TestAuthAgente::test_jwt_caducado_da_401`.
- **El Watch dejó de sincronizar sin que nada diera error.** El upsert en bloque de la
  ingesta de salud (`resolution=merge-duplicates`) no llevaba `on_conflict`, así que
  PostgREST lo resolvía contra la clave primaria (`id`) en vez de contra
  `unique(metric_date, metric_name)`: en cuanto el lote traía una métrica que ya
  existía para ese día, Supabase devolvía 409 y **no se guardaba nada**, ni siquiera lo
  nuevo. Antes esto no se veía porque cada métrica se escribía por separado con un
  `POST → si 409, PATCH`; el paso al lote se llevó por delante ese respaldo y dejó el
  POST tal cual. Dos cosas lo mantuvieron invisible durante días: el endpoint respondía
  `200 {"ok": true}` metiendo el fallo en una clave `errors` que nadie lee, y el único
  síntoma visible era el "sync hace Nd" del dashboard. Los mocks de los tests no lo
  cogían porque simulan Supabase, no PostgREST. Moraleja doble: **nombra la restricción
  en todo upsert cuya unicidad no sea la clave primaria**, y **un fallo de escritura no
  puede salir por una clave del cuerpo con un 200 delante**.
- **Bucle infinito de recargas en el login móvil.** `apiFetch` recargaba la página ante
  cualquier 401, pero los `useEffect` de carga inicial se ejecutan al montar aunque no
  haya sesión y devuelven 401: la pantalla de login parpadeaba sin dejar pulsar nada.
  Ahora solo borra el token y recarga **si `la_token` existía** (sesión caducada).
- **Eventos creados con la fecha equivocada** por el locale del SO en
  `<input type="date">`: en un Windows con locale americano `08/06/2026` se leía como
  mes/día. De ahí vienen `DateInput`/`TimeInput`, que parsean siempre `DD/MM/AAAA` y 24h.
  Relacionado: calcular la fecha por defecto con `toISOString()` la desplaza un día atrás
  en `Europe/Madrid` — usa componentes locales.
- **Sesiones de entrenamiento que no aparecían** al entrenar el mismo día que se cobraba
  (filtro por `date` en vez de `created_at`) y, más grave, **ninguna** sesión pendiente
  cuando el `+00:00` del timestamp viajaba sin codificar en la query de Supabase.
- **El token de Graph se perdía en cada `fly deploy`** cuando vivía en `backend/.token`:
  el filesystem del contenedor se reconstruye desde la imagen. Ahora está en
  `oauth_tokens` (Supabase) y `.dockerignore` excluye `.env`/`.token` de la imagen.
- **El login fallaba con error de CORS, no de credenciales**, cuando Vite arrancaba en
  5174 porque 5173 estaba ocupado. Libera el puerto; no añadas el nuevo a `allow_origins`.
- `sleepScore`: la penalización por hora de acostarse usa `h === 1` / `h === 0` para
  distinguir la 01:00 y las 00:00. Un `h >= 1` "equivalente" penalizaba también las
  22:00–23:00 (cualquier hora antes de medianoche). Hay test que lo cubre.
  **Este bug se reintrodujo** en el tooltip del widget de sueño, que llevaba su propia
  copia de los umbrales: enseñaba -10 pts por acostarse a las 22:00 que la puntuación
  real no aplicaba, así que las filas no cuadraban con su propio total. Arreglado con
  el mismo patrón que bienestar: `sleepBreakdown` (helpers) es la única fuente de
  verdad de los umbrales y `sleepScore` se limita a sumarlo. **No vuelvas a escribir
  esos umbrales fuera de `helpers.js`.**
- `sleepScore` NO recibe `core`: era un parámetro muerto que nadie usaba pero que los
  dos sitios que lo llaman se molestaban en calcular. Firma actual:
  `sleepScore(total, deep, rem, awake, sleepStart, recoveryMod)`.
- Los path params UUID del backend salen de `_uuid_path()`, que es una **fábrica**, no
  una constante: FastAPI asocia cada objeto `Path()` al nombre del parámetro que lo
  usa, así que compartir una instancia entre endpoints con nombres distintos
  (`idea_id`, `item_id`, `session_id`…) hace que todos hereden el último nombre
  registrado y devuelvan 422. Hay tests que lo cubren.
- Extracción de `alud_url` en `/calendar/events`: los cuerpos de Graph son HTML y la
  URL suele venir pegada a la etiqueta de cierre (`...id=99</p>`). El patrón debe
  excluir `<>"'` — un `\S+` se traga la etiqueta y rompe el enlace. Hay test.
- **Documentación que describe una defensa inexistente** (revisión de agosto de 2026).
  `LOGIN_BLOQUEO_MAX_SECONDS` y su "bloqueo progresivo que dobla su duración" estaban
  escritos en `CLAUDE.md`, en `backend/.env.example` y en `docs/BACKEND_REFERENCIA.md`.
  En el código no existía: `grep LOGIN_BLOQUEO backend/main.py` no devolvía nada y
  `_check_login_rate` solo tenía una ventana plana. Poner la variable no hacía nada y
  eran 1.440 intentos al día contra la contraseña, para siempre. Ya está implementado.
  La moraleja no es el bug: es que **tres documentos coincidiendo no son evidencia de
  que el código haga eso**. Cuando la guía describa una defensa, compruébala con un
  grep antes de fiarte, sobre todo si vas a apoyarte en ella para decidir otra cosa.
- **Un JWT firmado no dice para qué es.** `verify_token` validaba solo la firma, así que
  el `state` de OAuth — firmado con la misma `SECRET_KEY` y expuesto en la URL de vuelta
  de Microsoft — servía como sesión completa del dashboard durante diez minutos. Ahora
  `_jwt_de_usuario()` rechaza todo token con claim `purpose`. Se rechaza por presencia y
  no exigiendo `purpose: "dashboard"` a propósito: los tokens ya emitidos duran 30 días
  y no lo llevan, así que exigirlo habría echado al usuario de la sesión al desplegar.
- **Un error de otro sistema, tal cual, dentro de una notificación.** El botón
  «Arreglarlo» de la revisión nocturna llegó al móvil con
  `{"type":"error","error":{"type":"authentication_error","message":"OAuth access token
  has been revoked."}}` y un «puedes reintentarlo» detrás (24 de agosto de 2026). El
  disparo estaba bien hecho —la decisión se liberó y el aviso salió—, pero el motivo era
  el cuerpo crudo de la API de Anthropic: nada ahí dice que lo que toca es regenerar el
  token del trigger en claude.ai y volver a ponerlo con `fly secrets set`, y reintentar
  el botón no podía funcionar hasta hacerlo. Ahora los dos disparos de rutina
  (`_disparar_rutina` y `_disparar_arreglo`) pasan por `_motivo_disparo()`, que traduce
  los fallos con arreglos distintos —credencial, trigger que ya no está, rutina pausada,
  cupo agotado— y deja crudo el resto. La moraleja: **si un error de un tercero va a
  acabar delante del usuario, tradúcelo al arreglo**; el cuerpo entero se registra en el
  log, que es donde sirve.
- **La energía activa del Watch iba inflada x4,184 desde siempre, y el fallo se
  autobloqueaba.** Salió al intentar estimar las calorías de mantenimiento: la media de
  `active_energy` daba 1.712 «kcal»/día para alguien de 71 kg que hace 7.000 pasos y
  cuatro sesiones de gimnasio. Eran kilojulios (1.712 / 4,184 = 409 kcal). Tres fallos
  distintos por el mismo sitio:
  - `unit == "kJ"`, un **igual exacto** contra una cadena que elige el exportador. Ni
    Health Auto Export ni el Atajo garantizan capitalización ni si mandan el nombre
    corto o el largo.
  - **`unit` se reasignaba a `"kcal"` dentro del bucle de puntos**, y ese bucle es el de
    DENTRO: `unit` pertenece al de fuera, el de métricas. Convertido el primer día, la
    condición fallaba para todos los demás puntos de esa métrica. Con un punto por lote
    no se nota — y el test que había mandaba exactamente un punto. Con el export de 30
    días que recomienda `docs/SALUD.md`, entraban 29 de 30 filas en kJ crudo,
    **etiquetadas como kcal**, con lo que la columna `unit` deja de servir para
    detectarlas después.
  - `/health/ingest/simple` **no convertía nada en absoluto**. La conversión vivía solo
    en la ruta de Health Auto Export.
  Lo que lo hace grave no es el factor, es que `active_energy` está en
  `CUMULATIVE_METRICS`: una fila solo se pisa si el valor nuevo es **MAYOR**, y un
  número en kJ es siempre 4,184 veces mayor que el mismo dato en kcal. El valor malo
  gana a la medida buena para siempre y ninguna sincronización posterior lo corrige;
  hizo falta `backend/corregir_energia_kj.py` para reescribir el histórico. La moraleja
  es doble: **una normalización de unidades no se compara con `==`**, y **cuando una
  métrica es de tipo "solo se pisa si es mayor", cualquier fallo que infle el valor es
  permanente, no transitorio**. Además: el dato malo no lo destapó ningún test ni ningún
  panel, lo destapó alguien mirando el número y pensando «esto no puede ser» — un
  widget que pinta lo que le den no valida nada, y el score de bienestar llevaba
  regalando los 5 puntos de energía activa (umbral ≥600) todos los días.
- **Un `useEffect` sin la guarda de sesión pide datos desde la pantalla de login.**
  Hermano del de abajo y de la misma tanda de la voz: `pedirPermisoVoz()` colgaba de
  un `useEffect(..., [])`, y `Dashboard` **se monta también sin sesión** — devuelve
  `<LoginScreen/>` en la última línea, pero para entonces todos los hooks ya han
  corrido. Resultado: un 401 en la consola del navegador en cada carga de la pantalla
  de login. No rompía nada visible (`apiFetch` solo cierra la sesión si había token,
  y ahí no lo hay), así que no lo encontró nadie mirando: lo encontró el E2E, que
  exige **cero errores de consola** y por eso existe esa aserción. La moraleja:
  **todo efecto que llame a la API lleva `if (!token) return;`** — el resto de
  efectos de datos de `Dashboard.jsx` ya la llevan, a este se le olvidó.
- **Una petición sin cabecera de auth echa al usuario de la sesión entera.** Al cablear
  la voz de ElevenLabs (agosto de 2026), `pedirPermisoVoz()` llamaba a `/voz/token` con
  `headers: { "Content-Type": "application/json" }` en vez de `jsonHeaders()`. El
  síntoma no se parecía en nada a la causa: metías la contraseña, entrabas, y medio
  segundo después estabas otra vez en la pantalla de login, en bucle. El motivo es que
  `apiFetch` **borra `la_token` y recarga la página ante cualquier 401**, que es lo
  correcto cuando la sesión caduca de verdad; una llamada que se olvida las cabeceras
  entra por ese mismo camino y es indistinguible desde ahí. Y como el permiso se pide en
  un `useEffect` al montar, se disparaba solo, sin que el usuario tocara nada.
  La moraleja: **en este frontend, un endpoint nuevo con `Depends(verify_token)` se pide
  con `jsonHeaders()` o `authHeaders()`, nunca construyendo el objeto a mano**. Y si un
  fallo de sesión aparece justo después de añadir una llamada, mira los 401 del log del
  backend antes de sospechar de la contraseña.
- Doble conteo de entrenos semanales y fugas de detalles de error ya se arreglaron
  en commits anteriores; si tocas bienestar o manejo de errores, revisa el historial.
- **El campo que un endpoint no pide, no existe — aunque su hermano sí lo saque.**
  `/calendar/events` extraía `alud_url` del cuerpo del evento desde el principio, pero
  `/calendar/classes` ni siquiera pedía `body` en su `$select`. Y las entregas se crean
  en el calendario **Clases**, que es donde las mete la rutina de ALUD: llegaban al
  dashboard con `alud_url: null`, el widget de entregas las pintaba igual (solo mira el
  📚 del título) y el botón «Encender» encolaba un job con un payload sin `accion` ni
  `alud_url`. El agente lo recogía en el PC y lo cerraba con `failed: acción desconocida
  'None'` — un mensaje que no menciona ni el calendario ni la URL, que es donde estaba
  el fallo. Dos agravantes que lo tapaban: el dashboard mandaba el job **sin `accion`
  explícita** (el agente solo deduce `resolver_alud` a partir de la propia `alud_url`,
  por compatibilidad con jobs viejos), y `POST /jobs` aceptaba ese payload sin rechistar.
  Arreglado en las tres capas, con la extracción ya compartida en `_extraer_alud_url()`.
  Moraleja: **cuando dos endpoints devuelven la misma clase de objeto, la normalización
  va en una función común**, no copiada en uno de los dos.
- **Outlook web convierte en enlace la URL que pegas en la descripción.** El texto pasa
  a ser `alud_url: <a href="https://...">…</a>`, y el regex —que busca un `http` justo
  detrás de los dos puntos— dejaba de encontrar nada. Mismo síntoma que el anterior y
  ninguna pista de por qué: el evento «tenía» su URL a la vista. Ahora hay un segundo
  patrón que la rescata del `href`, con la misma lista blanca después.
- **El agente es efímero: encolar un job no lo despierta.** Con el PC ya encendido, el
  agente de su último arranque terminó hace rato y el WOL no despierta a nadie.
  `abrirStreaming()` lo tenía en cuenta y llamaba a `/relaunch-agent`; el camino de las
  entregas no, así que pulsar el botón con el PC encendido no hacía absolutamente nada.
  Y una moraleja de la propia investigación: **que algo no esté en la documentación no
  prueba que no exista**. Se dio por no montada la mitad de HA de este flujo (sensor +
  automatización + `shell_command`) y estaba entera desde hacía semanas, solo que en
  `/config/packages/life_assistant_pc.yaml` en vez de en `configuration.yaml`. Y de propina, la
  segunda conclusión precipitada del mismo día: sus sensores parecían congelados porque
  `last_reported` llevaba un día sin moverse, cuando ese campo solo avanza si el valor
  **cambia** (ver `docs/HOME_ASSISTANT_FLUJOS.md`).
