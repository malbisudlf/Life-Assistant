<!-- Parte de la guía del repositorio. El índice y las reglas que aplican
     SIEMPRE están en CLAUDE.md, en la raíz. -->

## Backend: Jarvis y la proactividad

El asistente, sus herramientas y todo lo que el sistema dice sin que le hablen
(reglas, avisos, vigilantes). El correo de la mañana está en `docs/BRIEF.md` y
el resto de patrones del backend en `docs/BACKEND_PATRONES.md`.

- **Jarvis** (`POST /jarvis`, `POST /jarvis/ejecutar`): un cerebro, muchas bocas. Entra
  lenguaje natural y sale una respuesta, habiendo consultado o actuado por el camino. El
  cliente solo manda texto: **la decisión de qué herramienta usar vive entera en el
  backend**, para que el día que se le hable desde otro sitio (el PC, un altavoz) no haya
  que reimplementarla. No metas lógica de herramientas en `Dashboard.jsx`.
  Las herramientas **no son integraciones nuevas**: son envoltorios de los endpoints que
  ya existen, llamados igual que en `construir_brief()` (`credentials=None`), para heredar
  su normalización y su manejo de errores. `_JARVIS_HERRAMIENTAS` es la única fuente de
  verdad — de ahí salen el esquema que ve el modelo, el despachador y la puerta de
  confirmación. Añadir una capacidad es añadir una entrada.
  Tres cosas que no se pueden relajar:
  - **La frontera de confirmación.** Las consultas y las acciones que ya tienen un botón
    en el dashboard (encender el PC, guardar una idea) las ejecuta el modelo; pedir
    permiso para lo que se hace con un clic solo estorba. Lo que toca el calendario va
    marcado `confirmar: True`: el modelo **propone** y devuelve `pendiente`, y solo
    `/jarvis/ejecutar` lo crea. Es la misma regla que ya rige `sugerencia_evento()`. Y ese
    endpoint **solo admite las herramientas marcadas** — abrirlo al registro entero lo
    convertiría en un ejecutor de herramientas arbitrarias por HTTP.
  - **El despachador filtra los argumentos a los declarados en el esquema.** Los redacta
    un modelo a partir de texto: sin el filtro, un nombre inventado llegaría como kwarg a
    la función envuelta (`credentials`, `days`…) y decidiría cosas que no le tocan.
  - **Una herramienta que revienta no tumba la conversación**: el fallo vuelve al modelo
    como resultado, que puede decirlo. Un `except` que devolviera `None` repetiría el bug
    del agente PC — "no pude preguntar" no es "no hay nada".
  - **Una herramienta con `confirmar` verdadero (fijo o dinámico) nunca se ejecuta desde
    el servidor MCP del teléfono** (`POST /mcp/telefono`, `docs/LLAMADAS.md`): se rechaza
    con un error, igual que en el chat se queda `pendiente` — solo que aquí no hay botón
    de confirmar al otro lado de una llamada, así que no hay ejecución posible en ningún
    caso. El gate es literalmente `_jarvis_confirma()`, sin excepción ni atajo por venir
    de una sesión de Claude Code con `--dangerously-skip-permissions`.
  **Lo que deja trabajo para el PC despierta al agente, y siempre DESPUÉS del job**
  (`_despertar_agente()`: WOL + relanzado, por `caja` o por los flags de HA). Lo usan
  `lanzar_streaming`, `encargar_al_pc` y `reintentar_job`. Hasta septiembre de 2026 las
  dos primeras solo creaban el job: el agente es efímero, así que con el PC encendido nadie
  lo recogía hasta el siguiente arranque — y Jarvis contestaba que el streaming estaba en
  marcha. El orden importa desde que manda `caja`, que actúa en el acto: un agente que
  arranca antes de que exista el job mira la cola vacía y se cierra. Es lo mismo que hace
  el botón del dashboard (`abrirStreaming`).
  **Dos modelos, y la diferencia entre ellos es la que separa hablar de actuar.** El
  pequeño (`JARVIS_MODEL`) acierta bien decidiendo SI hace falta una herramienta y falla
  eligiendo CUÁL en cuanto hay muchas parecidas — está medido contra el MCP de GitHub:
  pidiéndole leer issues escogía `add_issue_comment`, y ese fallo crece con el catálogo,
  que aquí no para de crecer. Así que la primera vuelta la tira el pequeño y, **en cuanto
  pide una herramienta, esa misma vuelta se relanza con `JARVIS_MODEL_ACCION`** (lo que
  pidiera el pequeño se descarta sin ejecutarse) y el resto del bucle va con el grande. El
  cierre vuelve al pequeño: para redactar con los datos delante, sobra. Una conversación
  que no toca nada no le paga al grande ni una llamada.
  **Y se relanza también cuando el pequeño se NIEGA** (`_suena_a_negativa`), que es el
  agujero que tenía el reparto: al decidir que no hacía falta ninguna herramienta cerraba
  el turno y el grande no llegaba a entrar nunca. *Negarse es la única respuesta que no
  puede darse sin haberla comprobado*, así que la revisa el grande. La detección es por
  frase hecha y se peca de generosa a propósito: un falso positivo cuesta una llamada, un
  falso negativo devuelve el bug. Igualar las dos variables desactiva
  el reparto sin tocar código — es lo que hace `conftest.py`, porque si no cada vuelta con
  herramienta consumiría dos respuestas del guion del modelo simulado.
  **Por voz cambia el prompt, no el cerebro** (`voz: true` en el cuerpo): frases cortas,
  sin listas ni markdown ni URLs, y `JARVIS_MAX_TOKENS_VOZ` en vez del techo normal. Lo
  que se escucha no se puede ojear ni saltar, y un párrafo que se lee en dos segundos
  tarda medio minuto en sonar.
  **Un turno NUNCA sale vacío, y el techo de tokens no es el mismo número para todos.**
  Los dos son la misma historia: `JARVIS_MAX_TOKENS` acota la respuesta, pero un modelo de
  razonamiento cobra su techo contra lo que piensa MÁS lo que dice, así que con el techo a
  secas se lo gastaba pensando y devolvía `content=""` — y las peticiones grandes, que son
  las que más piensa, eran justo las que se quedaban en blanco. De ahí
  `JARVIS_RESERVA_RAZONAMIENTO` (sitio para pensar por encima del techo de la respuesta;
  un tope solo se paga si se usa) y, por si acaso, la garantía en el punto único de salida
  (`_texto_garantizado`): un vacío se **registra** —es una avería, y sale en `app_logs` y
  en el `diagnostico`—, se reintenta el cierre con el pequeño y sitio de sobra, y si aun
  así no hay nada se contesta con lo que el backend sabe: lo que alguna herramienta pidió
  decir LITERALMENTE (`dile_al_usuario_literalmente`, el error que trae su arreglo dentro)
  o, en su defecto, qué se llegó a consultar. *Una respuesta pobre pero cierta vale más que
  un hueco en blanco*, y el cliente pintando «(sin respuesta)» dejaba al usuario sin saber
  ni si la herramienta había funcionado. Por lo mismo, **agotar `JARVIS_MAX_VUELTAS` no es
  silencioso**: se registra y se le dice al modelo antes del cierre, porque si no redactaba
  la respuesta como si hubiera terminado la tarea.
  **El modelo se elige por env, así que el código no puede dar por hecha su familia.**
  Los de razonamiento (`gpt-5*`, `o3`, `o4`…) rechazan con un 400 los dos parámetros que
  usa el resto: `temperature` (solo admiten el valor por defecto) y `max_tokens` (para
  ellos es `max_completion_tokens`). `_parametros_modelo()` los separa; sin eso, cambiar
  a la familia barata de hoy tumbaba Jarvis con un error de parámetro, y solo al
  hablarle, no al desplegar. Va con `reasoning_effort: minimal` a propósito: aquí el
  trabajo lo hacen las herramientas, y los tokens de razonamiento se pagan a precio de
  salida y se notan en el modo llamada.
  **Lo que cambia a cada minuto va al FINAL** (`_jarvis_ahora`, un mensaje aparte tras el
  historial). El caché de la API se calcula sobre el PREFIJO del prompt, así que la hora
  metida en el system invalidaba en cada minuto los ~4.800 tokens estables —reglas más el
  esquema de las 41 herramientas— que viajan en TODAS las llamadas. Si añades algo que
  cambie a menudo, no lo pongas delante.
  El coste es la otra restricción de diseño, y conviene medirlo en vez de estimarlo.
  **Medido contra la API con las 41 herramientas: 3.667 tokens de entrada por llamada, de
  los que se cachean 3.456 (el 94%)** — el esquema entra en el prefijo cacheable, así que
  se paga a una décima parte. Por eso recortar el esquema NO es una palanca de coste
  (ahorrarlo entero son céntimos al año); si algún día hay que adelgazarlo será por
  PRECISIÓN, que es el problema real de tener muchas opciones parecidas juntas. Lo que sí
  cuesta es la salida y el caché frío: OpenAI lo mantiene unos minutos, así que el primer
  turno del día se paga entero. `JARVIS_MAX_VUELTAS` es un
  cortacircuitos de gasto (un modelo atascado pediría la misma herramienta sin avanzar) y
  `JARVIS_MAX_HISTORIAL` es lo único que hace crecer el coste conforme avanza la
  conversación — **si lo cambias, cambia también el de `helpers.js`**, o el cliente mandará
  más de lo que acepta el backend y recibirá un 422 a media conversación.
  El backend **no guarda conversaciones**: el historial viaja en cada petición y vive en
  `localStorage`. Menos estado que mantener y nada que purgar, el mismo criterio que con
  el histórico de presencia.

- **Jarvis en la muñeca** (`POST /jarvis/atajo`): la segunda boca del mismo cerebro. Un
  Atajo de iOS —«Oye Siri, dile a Jarvis…»— dicta, llama a este endpoint y lee la
  respuesta en alto; desde el reloj, sin desbloquear el móvil ni esperar a que cargue el
  dashboard. Es lo que hace que la decisión de diseño de siempre (la elección de
  herramienta vive ENTERA en el backend) por fin cobre: hasta aquí había un solo cliente.
  - **Auth con `JARVIS_TOKEN`, token de servicio, nunca un JWT** (`verify_jarvis`). Un
    Atajo se dispara solo y no sabe volver a hacer login: con un JWT de 30 días se
    quedaría mudo el día que caducara, sin avisar a nadie. Es exactamente como se rompió
    el agente PC, y por eso esta regla ya está en `CLAUDE.md`. Se lee **solo de
    cabeceras** (`X-Auth-Token`): aquí no hay integración desplegada que migrar, así que
    no se hereda la excepción de la query que arrastran HA y el Atajo de salud.
  - **Sin historial.** El historial vive en `localStorage` del navegador y un Atajo no
    tiene dónde guardarlo: cada petición es una conversación entera. La alternativa
    —inventarse una sesión en el servidor— rompería que el backend no guarda
    conversaciones, y sería el primer sitio donde habría que purgarlas.
  - **`voz: true` siempre**, con el mismo prompt que el modo llamada: frases cortas, sin
    listas, sin markdown y sin URLs.
  - **Lo pendiente se DICE.** La frontera de confirmación no se relaja —lo marcado
    `confirmar: True` sigue devolviendo `pendiente` sin ejecutarse—, pero por aquí no hay
    botón que pulsar. Callarlo dejaría al usuario creyendo que su cita está creada, así
    que la respuesta añade que hace falta confirmarlo en el dashboard.
  - **El Atajo, paso a paso** (app Atajos de iOS; se sincroniza al Apple Watch solo).
    Antes de nada, lo que NO funciona como uno espera: **Siri no aprende frases nuevas y
    no sabe pasarle a un atajo el texto que va detrás del nombre**. No hay «Oye Siri, dile
    a Jarvis que mire mi agenda». Lo que hay es que **el nombre del atajo ES la frase que
    lo lanza**, y el texto se dicta después, ya dentro del atajo. Así que se llama
    `Jarvis`, se dice «Oye Siri, Jarvis», suena el tono y entonces hablas.
    1. *Dictar texto* — idioma español, detener «tras una pausa».
    2. *Obtener contenido de URL*: `https://<tu-backend>/jarvis/atajo`, método `POST`,
       cabeceras `X-Auth-Token: <JARVIS_TOKEN>` y `Content-Type: application/json`,
       cuerpo JSON `{"mensaje": <Texto dictado>}`.
    3. *Obtener valor del diccionario* → clave `texto`.
    4. *Hablar texto*.
    El campo `mensaje` del cuerpo JSON tiene que ser de tipo **Text**; con cualquier otro,
    el backend responde 422.
    Nombre corto y pronunciable, que es lo que habrá que decirle a Siri cada vez. En el
    reloj aparece en la app Atajos y puede ponerse como complicación de la esfera.
    Y una cosa que NO hay que buscar: *Obtener contenido de URL* **no tiene ajuste de
    tiempo de espera**. No hace falta — su límite propio ronda el minuto y el arranque en
    frío de Fly son 10–15 s la primera vez del día. Si el atajo falla, no es por ahí.

- **Jarvis por Telegram** (`POST /telegram/webhook`, desde el 2026-10-24): la tercera boca
  escrita, con texto y notas de voz. Mismo cerebro (`_jarvis_chat`), boca `telegram` en
  `jarvis_gasto`, y lo `confirmar: True` llega con dos botones (✅ Sí / ❌ No) que ejecutan
  por el mismo camino que `/jarvis/ejecutar` (`_jarvis_ejecutar_confirmado`). Lo que tiene
  de distinto —la ventana corta de conversación EN MEMORIA, la excepción meditada a «el
  backend no guarda conversaciones»— está en `docs/TELEGRAM.md`.

- **Jarvis en internet** (`buscar_en_internet`, `leer_pagina`): dos invariantes, y las dos
  son de seguridad, no de comodidad.
  - **SSRF.** `leer_pagina` recibe una URL que en el mejor caso sale de un buscador y en
    el peor la ha redactado un modelo leyendo una web. El backend vive donde
    `169.254.169.254` son las credenciales de la instancia y `127.0.0.1` es él mismo, así
    que `url_web_permitida()` resuelve el host y exige que **todas** sus IPs sean públicas.
    Se revalida **en cada salto de redirección** (`_descargar` las sigue a mano con
    `allow_redirects=False`): sin eso, un 302 a loopback se salta la comprobación entera.
    Y el error **no dice por qué** se rechazó — distinguir "host inexistente" de "host
    interno" convierte la herramienta en un escáner de la red. Hay tests de los dos.
  - **Inyección de prompt.** Lo que vuelve de la web lo ha escrito un desconocido, y este
    modelo tiene herramientas que encienden el PC. Va envuelto en `_AVISO_WEB` y
    etiquetado como DATO NO FIABLE, igual que el enunciado de Alud en
    `build_cowork_instruction()`. No es una garantía —contra la inyección no hay ninguna—
    pero es la diferencia entre ponérselo difícil y servírselo en bandeja. Si añades una
    herramienta que traiga contenido de fuera, envuélvela igual.

  El buscador es enchufable (Brave → Tavily → DuckDuckGo, por clave configurada). **La
  búsqueda gratuita no funciona en la práctica**: a agosto de 2026 DDG devuelve captcha a
  las peticiones automatizadas, y los SearXNG públicos que se probaron dan 403/429. Por eso
  existe `BuscadorBloqueado`, que separa "no hay resultados" de "no he podido buscar" y
  devuelve un error **con el arreglo dentro** (configurar `TAVILY_API_KEY`) para que el
  modelo se lo diga al usuario en vez de insistir gastando vueltas. Es la misma moraleja
  del agente PC: *"no pude preguntar" no es "no hay nada que hacer"*.

- **Jarvis: memoria persistente** (`recordar`, `olvidar`, tabla `jarvis_memoria`): los
  HECHOS destilados de las conversaciones (preferencias, objetivos, nombres, decisiones)
  se guardan con clave y se inyectan en el prompt de cada turno; el HISTORIAL sigue
  viviendo en el cliente y el backend sigue sin guardar conversaciones — son datos
  distintos con reglas distintas. El modelo guarda por iniciativa propia (se le pide en
  el prompt de sistema), y por eso la clave se **normaliza a slug** en `_clave_recuerdo()`
  antes de interpolarse en la URL de Supabase (invariante 6 de `CLAUDE.md`): el modelo la redacta con
  espacios y acentos, y rebotarle el formato le gastaría una vuelta. El upsert lleva
  `on_conflict=clave` explícito (la lección del 409) y un fallo leyendo la memoria **no
  tumba el turno**: se sigue sin recuerdos, con `warning` en el registro. Los topes
  (`JARVIS_MAX_RECUERDOS`, `JARVIS_RECUERDO_MAX`) existen porque los recuerdos viajan
  dentro del prompt y se pagan por token en cada turno.
- **Jarvis: cliente MCP** (`mcp_servidores`, `mcp_herramientas`, `mcp_usar`): conexión a
  cualquier servidor MCP por Streamable HTTP (JSON-RPC sobre POST, sin dependencias
  nuevas), con la sesión negociada en memoria (`_mcp_sesiones`, mismo criterio que
  `_token_cache`). Tres invariantes de seguridad:
  - **La lista blanca es del usuario** (`JARVIS_MCP_SERVERS`, env). El modelo elige
    ENTRE los servidores aprobados, nunca añade uno: un modelo que decide sus propios
    endpoints es un canal de exfiltración con tus datos como argumentos. Jarvis puede
    proponer añadir un servidor; conectarlo es editar la variable.
  - **La frontera de confirmación se decide por llamada** (`_mcp_pide_confirmar()`), en
    tres niveles: `confiar` → nada pregunta; por defecto (`lectura_directa`) → se
    ejecutan solas las herramientas que el servidor declara de solo lectura
    (`annotations.readOnlyHint`, del protocolo) y lo que escribe se propone; y
    `lectura_directa: false` → todo se propone. Ante la duda (servidor que no anota, o
    que no se pudo listar) **se pide confirmación**: falla hacia el lado seguro. La
    anotación la da el propio servidor —contenido externo— y se acepta porque la
    frontera de confianza real es la lista blanca que el usuario aprobó a mano, con un
    token que él emitió.
    **Que las consultas se ejecuten dentro del bucle no es comodidad, es lo que hace que
    funcione**: al quedar pendiente, la llamada corta el bucle, así que el modelo nunca
    veía que se había equivocado de herramienta y no podía corregirse. Contra el
    servidor real de GitHub (47 herramientas) esa era la diferencia entre acertar a la
    quinta y no acertar nunca.
    Para todo esto `confirmar` en el registro puede ser una **función de los argumentos**
    (`_jarvis_confirma()`), y la puerta de `/jarvis/ejecutar` admite lo confirmable fijo
    o dinámico. El botón del dashboard enseña servidor, herramienta y argumentos REALES
    (`jarvisEtiquetaAccion`), no lo que el modelo haya redactado.
  - **`mcp_herramientas` se filtra con `buscar`**: volcar el catálogo entero cuesta
    tokens en cada turno y, sobre todo, un modelo pequeño elige peor cuantas más
    opciones parecidas ve juntas (probado: pidiéndole LEER issues escogía
    `add_issue_comment`). Un filtro sin coincidencias devuelve los NOMBRES de todas, para
    que pueda reintentar con otra palabra en vez de quedarse sin nada que mirar.
  - **Lo que devuelve un servidor es contenido externo**: resultados y descripciones de
    herramientas van envueltos en `_AVISO_WEB`, como la web y el enunciado de Alud.
  Sin servidores configurados, las herramientas que **operan sobre uno** (`mcp_usar`,
  `mcp_herramientas`, `mcp_desconectar`) no se anuncian en el esquema — herramientas
  muertas se pagan por token en cada turno. Las que sirven para conectar el primero
  (`mcp_catalogo`, `mcp_conectar`) se anuncian siempre: son justo las que hacen falta
  entonces. La palanca es `requiere_mcp` en el registro, no el prefijo del nombre.
  Hay tests del flujo completo con sesión, del parseo SSE y de las dos fronteras.

- **Jarvis: conectar servidores MCP en caliente** (`mcp_conectar`, `mcp_desconectar`,
  `mcp_catalogo`, tabla `jarvis_mcp_servidores`): **la regla de fondo no cambia — un
  servidor entra en la lista blanca porque lo aprueba una PERSONA, nunca porque lo decida
  el modelo.** Lo que cambia es el trámite: antes era editar un secret de Fly y
  redesplegar, ahora es el mismo botón de confirmar que ya gobierna `crear_evento`, porque
  `mcp_conectar` está marcada `confirmar: True`. `_mcp_config()` es la unión del env y la
  tabla, y **el env manda** en caso de conflicto de nombre: lo que el usuario escribió a
  mano no lo puede pisar algo aprobado de pasada en una conversación (ni desconectar —
  `mcp_desconectar` se niega y dice dónde está). Tres cosas que lo sostienen:
  - **La URL pasa por `url_web_permitida()` y exige https.** "Conéctate a este MCP" con
    una URL sacada de una web es una forma muy educada de pedirle al backend que hable con
    `169.254.169.254`. Y el rechazo **no dice por qué**, como en `leer_pagina`.
  - **Se prueba la conexión antes de guardar** (`_mcp_probar`: initialize + tools/list). Un
    alta que no se comprueba repetiría el bug del agente PC: *lanzar algo no es comprobar
    que funciona*. De paso, el número de herramientas es la señal de que fue bien.
  - **El botón enseña nombre y URL reales, nunca el token** (`jarvisEtiquetaAccion`).
  La copia en memoria (`_mcp_guardados_cache`) existe porque `_mcp_config()` se consulta
  varias veces por turno; se tira al escribir con `_mcp_invalidar()`, que **también limpia
  sesiones y anotaciones** (podrían ser de una URL que ya no es esa). Resetéala en
  `conftest.py` como el resto de estado de módulo.

- **Jarvis: conciencia de sí mismo** (`mis_capacidades`): qué sabe hacer, qué tiene
  apagado **y por qué**, y cómo puede crecer. Se deriva de `_jarvis_esquema()`, no del
  registro entero, porque lo que importa es lo que puede usar EN ESTE TURNO. La mitad útil
  es la segunda lista: un asistente que no sabe de lo que es capaz falla de las dos
  maneras a la vez —dice que no puede lo que sí puede e inventa lo que no—, y un "no
  puedo" sin el motivo detrás no se puede accionar. El prompt le manda mirarla antes de
  negarse, y le da dos vías para crecer: conectar un servidor MCP (al momento) o, si eso
  no lo arregla, **proponer la mejora como issue en su propio repositorio** (`JARVIS_REPO`
  + un MCP de GitHub conectado), que es crecer por el camino revisable.

- **La casa** (`casa_dispositivos`, `casa_ordenar`, `GET /ha/ordenes-pending`,
  `POST /ha/entidades`): mientras vivió en Fly, el backend no podía llamar a HA, así que se
  usan los dos patrones que ya existen, cada uno para lo que sirve (hoy, además, el directo
  de más abajo). Las **órdenes** van en una cola en
  memoria que HA recoge al sondear (son ÓRDENES, como el WOL: perderlas en un cold start
  solo cuesta volver a pedirlas) y el **catálogo de dispositivos** lo empuja HA a Supabase
  (es ESTADO, como la presencia: el que lo sabe es HA). Tres reglas:
  - **Lista blanca de dominios** (`_CASA_DOMINIOS`): la orden acaba en un `service call`
    de HA, donde `hassio.*` o `shell_command.*` son bastante más que una luz.
  - **La frontera de confirmación es por dominio** (`_casa_pide_confirmar`): una luz o un
    enchufe equivalen a pulsar el interruptor y se ejecutan solos; cerraduras, persianas y
    alarmas las aprueba el usuario. Un dominio desconocido se confirma: se falla al lado
    seguro.
  - **Una orden vieja no se ejecuta** (`CASA_ORDEN_TTL`). Si HA estuvo caído dos horas, al
    volver no puede ponerse a encender lo que pediste al mediodía — la misma regla que hace
    caducar la presencia.
  Con catálogo cargado, una entidad que no está en él se rechaza: es una invención del
  modelo. Y el servicio tiene que ser del dominio de la entidad (o el genérico
  `homeassistant.*`): `light.turn_on` sobre un `switch` no enciende nada y descuadra la
  frontera de confirmación, que razona con los dos dominios. El YAML de HA está en
  `docs/HOME_ASSISTANT_JARVIS.md`.
  **En directo, desde que el backend vive en `caja`**: con `HA_URL` y `HA_TOKEN`,
  `_j_casa_ordenar` —después de todas esas validaciones, y la confirmación ya dada— le manda
  la orden a HA por su API (`_ha_llamar_servicio`). La respuesta lleva `estado` con lo que
  pasó: `hecha` (con `estado_entidad` si HA dice al contestar cómo quedó, que es lo que
  Jarvis puede contar —«ya está encendido»—; si no, `null` y no un «apagado» leído
  demasiado pronto), `rechazada` (`ok: false`: HA dijo que no, ni se hizo ni se encoló) o
  `sin_confirmar` (HA la recibió y no contestó: puede haberse hecho, y la nota y la
  descripción de la herramienta le dicen al modelo que **no la repita** sin mirar antes).
  Solo si HA no aceptó ni la conexión va a la cola, sin `estado`, como siempre. Lo que HA
  recibió no se encola nunca: el Green lo repetiría, o lo ejecutaría con sus privilegios
  después de que HA lo rechazara. De `homeassistant.*` solo pasan `turn_on`, `turn_off` y
  `toggle`. La tabla completa, en `docs/HOME_ASSISTANT_FLUJOS.md`. `casa_dispositivos` lee los
  estados de HA en el acto (`_casa_entidades_al_dia`) y dice de dónde salen (`estados`), para
  que el modelo no dé por seguro un «encendido» del catálogo de hace una hora. Todo lo que
  ordena a la casa (alarmas, el «Apagar» del aviso de salir) pasa por la misma puerta y gana
  lo mismo sin tocarlo. El detalle, en `docs/HOME_ASSISTANT_FLUJOS.md`.
  **El dashboard encola por la MISMA puerta.** El widget «Casa» (`POST /casa/orden`) no
  tiene cola propia: llama a `_j_casa_ordenar` con `_boca_actual` a `dashboard`, que es el
  origen que queda apuntado en `casa_acciones`. Lo único que cambia es la entrada: el
  widget manda una acción de una lista cerrada y el servicio lo fija el backend
  (`_CASA_ACCIONES_WIDGET`), así que un toque no puede pedir nada que no sea encender,
  apagar, abrir, bloquear o activar. Cada orden, venga de quien venga, lleva un `id` y deja
  su acuse en `_ha_ordenes_hist`: por eso el widget también enseña «HA la recogió» en una
  luz que encendió Jarvis.

- **Recordatorios** (`recordarme`, `mis_recordatorios`, `cancelar_recordatorio`, tabla
  `jarvis_recordatorios`): lo único que hace que Jarvis hable sin que le hablen. Las tres
  decisiones son las que ya tomó el resumen diario, por lo mismo: viven en Supabase (Fly
  escala a cero), **el reloj es el tick de HA** (`/ha/brief-tick`, que por eso ya no es
  gratis antes de la hora tope: ~300 SELECT al día contra un índice; lo que pides con
  `recordarme` sale además por el tick de alarmas, al minuto, ver «Sale al minuto» en
  `docs/LLAMADAS.md`) y **la reserva es un
  PATCH condicional, no un GET previo** — es lo que hace la pregunta atómica, y con un GET
  dos ticks solapados mandan el mismo aviso dos veces. Si el correo falla **se libera la
  reserva**, o un error transitorio de SMTP se come el recordatorio. Un fallo despachando
  **nunca** tumba el resumen diario: va aparte y se registra.

- **Avisos al móvil** (`_notificar`, `GET /ha/avisos-pending`): todo lo que Jarvis dice sin
  que le hablen salía por correo, que es el único canal que llega con la web cerrada — y
  se lee al abrir el buzón, así que un "ponte el reloj" de las 21:30 leído al día
  siguiente no es un aviso. El canal nuevo es la app companion de HA, por el patrón de
  siempre: **cola en memoria que HA sondea** (son ÓRDENES, como el WOL). El backend **no
  sabe a qué móvil** se manda, eso lo decide el `notify.mobile_app_*` del YAML de HA: un
  nombre de dispositivo personal no entra en un repo público. Tres reglas:
  - **`_notificar()` es la única puerta**, y elige canal por sí sola. Nada manda un aviso
    llamando a `enviar_correo` directamente; si mañana hay un canal más, se añade aquí y
    lo heredan todos.
  - **El canal se enciende solo: la señal es el propio sondeo.** Mientras nadie recoja la
    cola, todo sale por correo exactamente como antes (así es el despliegue: el YAML se
    instala cuando se instale, y hasta entonces no se pierde nada), y si HA deja de
    sondear más de `AVISO_MOVIL_VIVO`, se vuelve al correo solo. No hay que configurar
    nada en el backend, ni queda un interruptor que se olvide encendido apuntando a un HA
    muerto.
  - **Cambiar de canal no puede perder avisos** (`_rescatar_avisos`, en el mismo tick): un
    aviso encolado que nadie recoge en `AVISO_MOVIL_RESCATE` se manda por correo. Cubre el
    fallo realista —el YAML a medias: HA sigue con su tick y nadie lee la cola—, que sin
    esto dejaría de entregar avisos que antes llegaban y **en silencio**. Si el rescate
    falla, el aviso se queda en la cola para el siguiente tick; tirarlo ahí sería justo lo
    que el rescate viene a evitar. Por lo mismo la cola **no caduca** como la de la casa:
    encender una luz media hora tarde es peor que no encenderla, pero un aviso tarde sigue
    valiendo.
  El panel ⚙ tiene una fila **Avisos** (por dónde salen y cuánto hace del último sondeo) y
  un botón «Probar aviso»: instalar el YAML y esperar a que toque un aviso de verdad para
  saber si funciona es la forma más rápida de darlo por puesto sin estarlo. Lo que ese
  botón **no** puede decir es que el aviso llegara al bolsillo — desde aquí solo se ve que
  HA vino a recogerlo, y si su automatización falla el aviso muere allí (ya pasó, ver
  "Bugs históricos"). Por eso dice "encolado" y nombra a los sospechosos, en vez de
  "enviado".

- **Aviso de "ponte el reloj"** (`_avisar_reloj_si_toca()`, mismo tick de HA): si hoy no
  hay ni un dato del reloj —o si se acumulan `RELOJ_AVISO_NOCHES` noches sin medir—, deja
  un recordatorio a partir de `RELOJ_AVISO_HORA` (21:30). Sale **antes de dormir o no
  sale**: el dato de una noche sin medir no se recupera al día siguiente, así que un aviso
  por la mañana solo sirve para dar la mala noticia. Cuatro cosas:
  - **No hay camino de correo nuevo**: se apunta como recordatorio normal y lo manda el
    despachador que ya existe, con su liberación de reserva si el SMTP falla.
  - **La idempotencia es un INSERT con id determinista** (`uuid5` de la fecha) contra la
    clave primaria de `jarvis_recordatorios`: el 409 es la pregunta atómica, igual que
    `brief_envios`. `_reloj_avisado_dia` es solo una caché para no repetir la CONSULTA en
    cada tick (el tick pasa cada 5 min); quien impide el duplicado es el INSERT.
  - **Un día "sin_datos" no dispara nada.** Si no llegó nada, no se sabe si el reloj
    estaba en un cajón o falló la sincronización, y un aviso que regaña por algo que no ha
    pasado deja de leerse a la tercera.
  - Antes de la hora no consulta nada: el tick tiene que seguir siendo barato.

- **Vigilante de la ingesta** (`_vigilar_ingesta()`, mismo tick de HA): si no entra ni un
  dato de salud en `INGESTA_AVISO_HORAS` (24), un `logger.error`; pasadas
  `INGESTA_CORREO_HORAS` (48), además un recordatorio. Es el complemento del aviso del
  reloj, no un duplicado: aquel salta cuando llegan datos del móvil y ninguno del Watch, y
  **se calla a propósito cuando no llega NADA** porque entonces no se sabe qué falló. Este
  cubre exactamente ese hueco, que es donde vivieron las tres averías grandes del proyecto
  (el 409 del upsert, el 400 del envoltorio, el JWT caducado del agente): las tres son la
  misma historia —los datos dejaron de llegar y el sistema siguió diciendo que todo iba
  bien—, y **nadie vigila una ausencia salvo que se le pida**. Cuatro cosas:
  - **Va por `logger.error`, no por un camino nuevo**: así sale en `app_logs`, en el panel
    de ajustes y en el `diagnostico` de Jarvis sin tocar nada más.
  - **Si no se puede preguntar, se calla** (`logger.warning` y fuera). Avisar ahí
    convertiría un Supabase lento en "el Watch no sincroniza", que es mentira — la regla
    de siempre, esta vez por el lado contrario.
  - **El correo es un recordatorio normal**, con la misma idempotencia (`uuid5` del día
    contra la clave primaria) para no mandar uno por hora.
  - **Una consulta por hora como mucho** (`INGESTA_VIGILA_CADA_MIN`): el tick pasa cada 5
    minutos. En memoria a propósito — perderlo en un cold start cuesta una consulta.

- **Reglas proactivas** (`_REGLAS`, `_correr_reglas()`, en el tick de HA): lo que Jarvis
  dice sin que le hablen, aparte del aviso agrupado de `_motivos_proactivos`. Todas dejan
  su aviso por `_apuntar_aviso`, así que heredan el presupuesto, el silenciado y la
  memoria **sin poder olvidarse de mirarlos**; añadir una regla es escribir la función y
  meterla en `_REGLAS`. Ninguna puede llevarse por delante a las demás ni al tick.
  - **«Sal ya»** (`_regla_sal_ya`): el aviso se **PROGRAMA, no se manda** — la salida se
    calcula UNA vez, cuando el evento entra en la ventana, y se apunta con `cuando` a su
    hora. Calcularla en cada tick serían decenas de llamadas de pago a Maps por evento, y
    por eso la huella se comprueba **antes** de llamar a Maps. Con `voz` si estás en casa:
    el móvil puede estar en otra habitación y este es justo el aviso que no vale leído
    diez minutos tarde. Si la hora de salir ya pasó **no se apunta**.
    **La huella es por cita y por hora** (`_huella_salir`: `salir:<hash del id>:<inicio>`).
    Antes era el id de Graph recortado a 60 caracteres, y los ids de Graph comparten unos
    90 de prefijo (buzón y carpeta): todas las citas tenían la misma huella y el «Sal ya»
    de la segunda se callaba cinco días. La hora va dentro para que una cita movida vuelva
    a tener aviso, y para poder comprobar al soltarlo que sigue en pie (ver **Vigencia**
    en el gobierno de los avisos).
  - **«No llegas»** (`_regla_no_llegas`): dos citas que no se solapan —así que Outlook las
    da por buenas— pero entre las que no da tiempo a moverse. Se avisa **la noche antes**,
    que es cuando todavía se puede mover algo.
  - **«Mañana empiezas pronto»** (`_regla_madrugon`): cruza el primer evento de mañana con
    tu hora habitual de dormirte (`_hora_habitual_dormir`, **mediana** de `sleep_start` —
    una noche en vela desplaza la media y no dice nada del hábito; y una hora de madrugada
    cuenta como "más tarde", no como dieciocho horas antes). Sin base, no habla. La hora
    habitual se ancla a la **noche anterior al evento**, no al día de la hora recomendada:
    con un evento a las 08:30 la recomendada es las 00:00, y anclar ahí un hábito de las
    23:00 lo ponía casi 24 h tarde y avisaba a quien ya se duerme antes de tiempo.
  - **Firma de malestar** (`_regla_malestar`): las tres señales a la vez. Es el espejo en
    Python de `_firmaMalestar` de `helpers.js` — se acepta la duplicación a propósito
    porque las conclusiones no se portan al backend, y allí solo se ve abriendo el
    dashboard, que es justo lo que no vas a hacer el día que tu cuerpo dice que no.
  - **Hueco para entrenar** (`_regla_hueco_entreno`): la hora concreta libre de mañana.
    Sin histórico de entrenos no se regaña, la regla de siempre. **Caduca a la medianoche
    que abre ese día**, como «No llegas»: si el presupuesto lo pospone a las 08:30, diría
    «Mañana tienes libre…» cuando ese mañana ya es hoy.
    **Y solo con los entrenos al día** (`_entrenos_al_dia`, también en el aviso diario):
    si Health Auto Export no ha mandado nada en `ENTRENOS_FRESCOS_HORAS` (3), se calla.
    Los entrenos solo llegan por ahí y el móvil los manda cuando le da: el 2026-10-12
    entrenaste por la tarde, el envío llegó a las 00:42, y a las 19:00 y a las 21:30 te
    dijo que llevabas cuatro días sin entrenar. El momento del envío vive en memoria; tras
    un reinicio no se sabe, y no saberlo es no regañar hasta el siguiente.
  - **«Vas tarde»** (`_regla_vas_tarde`): pasada la hora de salir en más de
    `VAS_TARDE_MIN` (10) y sigues en casa, te ofrece mover la cita lo que vas tarde (en
    tramos de 15 min) con un botón «Moverla». La salida es la que ya calculó «Sal ya»
    (`_salida_apuntada`, del `cuando` de su aviso): no vuelve a pagar Maps, y sin ese
    aviso se calla. **Solo citas tuyas y sin invitados** (`organizo`, `invitados`, que
    `get_events` trae desde entonces): la de otro no se puede mover, y mover una con gente
    les manda la actualización a todos por un toque. «No, llego» es `LA_UTIL_`, no un voto
    en contra. Cómo el botón sabe qué mover: «Lo que se confirma en el móvil», abajo.
  - **Al salir de casa** (`_regla_al_salir_de_casa`): se dispara en `POST /ha/presencia` al
    CAMBIAR a fuera, no en el tick — es el único momento en que sirve. **Por defecto no
    apaga nada por su cuenta** y pregunta con un botón. **Con `SALIR_CASA_APAGAR=1` apaga
    sin preguntar** (encendido en `caja` desde el 2026-09-28, pedido así: el aviso se leía,
    se pulsaba «Apagar» y ya) y solo avisa de lo que no pudo apagar, con el botón para
    reintentarlo. Nace apagado en el código porque la presencia es la de un móvil: a
    quien despliegue el kit le apagaría las luces a quien se quede en casa. El PC nunca
    entra en ese apagado (su aviso ofrece suspenderlo), y solo si `PC_ENTIDAD` está
    declarada: adivinar cuál es por el nombre acaba apagando otra cosa.
    **Qué cuenta como "encendido" lo decide `SALIR_CASA_ENTIDADES`**, una lista blanca de
    entity_ids. Antes miraba los dominios `light` y `switch` enteros, y ahí estaba el
    fallo: un catálogo real de una casa con Alexas trae 166 switches, y casi ninguno es un
    aparato — son AJUSTES ("No molestar", "Repetir", "Barajar", "Anuncios", "Auto-off
    enabled", "LED"), varios de ellos en `on` por definición. El aviso los listaba y ahí
    se perdía lo único que importaba. Es lista blanca y no lista negra de patrones porque
    lo enumerable es lo tuyo (cinco cosas), no lo que inventa cada integración nueva: con
    lista negra, la siguiente Alexa de la casa devolvería el ruido sola. Vacía, cae a
    `light` y `fan` — **nunca `switch`**, que es donde vive esa basura.
    Su notificación lleva un botón más, **«Apagar»** (`POST /avisos/{id}/apagar`), porque
    un aviso que te obliga a abrir la app para resolverlo no ha terminado el trabajo. Lo
    que hay que saber de ese botón, y del aviso que lo trae:
    - **Apaga lo que decía el aviso, no lo que hay ahora.** Los `entity_id` se guardan con
      el aviso (columna `entidades`, `20260830_avisos_entidades`) en el momento de
      apuntarlo. Releer el catálogo al pulsar apagaría cosas de las que el aviso no habló
      —llega con hasta una hora de retraso—, y un botón que apaga algo que no te dijo es
      peor que no tenerlo. La regla de "no apagar a ciegas" sigue intacta: ahora lo apagas
      tú.
    - **El PC se nombra pero no se apaga con él.** Cortarle la corriente a un `switch` no
      es apagar un PC, es tirar del cable; para eso está su propio aviso
      (`REGLA_PC_ENCENDIDO`, «Te has ido con el PC encendido. ¿Lo suspendo?»), que trae
      los botones **[Suspender, Útil, No]**. «Suspender» reutiliza a propósito el prefijo
      `LA_APAGAR_`, así que la automatización y el `rest_command` de HA que ya existían
      sirven sin tocar el YAML: es `POST /avisos/{id}/apagar` quien mira la regla del aviso
      y, en `pc_encendido`, encola la suspensión por el mismo camino que
      `POST /suspend-pc` (`_pedir_al_pc`: el pedido para `caja`, o de respaldo
      `_pc_power_action` → `/ha/pc-power-pending` → SSH desde HA).
      Cuenta como «útil», igual que apagar. Se excluye `PC_ENTIDAD` de la lista.
    - **Pulsarlo cuenta como «útil»**, y pasa por `_j_casa_ordenar` como cualquier otra
      orden de la casa: la lista viene de una fila de Supabase, que es escribible con la
      service key, así que tiene que pasar por la lista blanca de dominios y por el
      catálogo igual que si la hubiera pedido el modelo. Los dominios que acepta
      (`light`, `switch`, `fan`) tienen que ir **a la par de los que mira la regla**:
      cuando la regla cambió `switch` por `fan`, el botón se quedó atrás y ofrecía apagar
      un ventilador que luego se negaba a tocar.
    - **La huella lleva el día.** Cada salida es un suceso, no un estado que dura: con la
      huella hecha solo de nombres, dejarte la misma luz el lunes y el martes era «lo
      mismo» y `_ya_dicho` callaba el aviso cinco días.
  Las reglas que necesitan salud reciben la FUNCIÓN que la lee, no el dato: pasando el
  dato, el tick de cada 5 minutos traía 30 días de métricas aunque la regla fuera a
  salirse por su guarda de hora.

- **Reglas que Jarvis propone y tú apruebas** (`_PLANTILLAS_REGLA`, `proponer_regla`,
  tabla `reglas_usuario`): las de `_REGLAS` son condiciones escritas a mano y crecer así
  cuesta un despliegue por idea. Esto deja crecer hablando **sin mover el listón al
  criterio del modelo**, y lo que lo reconcilia es una sola decisión: **el modelo no
  escribe reglas, RELLENA plantillas**. Las condiciones siguen en Python, revisables en un
  diff; en la tabla solo se guarda cuál y con qué parámetros. Un modelo que pudiera
  definir la condición sería un modelo decidiendo cuándo interrumpirte, que es lo que el
  proyecto lleva evitando desde el principio. Tres cosas más:
  - **El alta pasa por el botón de confirmar** (`confirmar: True`), como `mcp_conectar`.
  - **Los parámetros se filtran a los campos que declara la plantilla**: los redacta un
    modelo, y sin el filtro un nombre inventado quedaría guardado y evaluándose como si
    significara algo. Misma regla que el despachador de herramientas.
  - **Las plantillas que leen salud se evalúan una vez por hora**, no en cada tick: traen
    30 días de métricas. Y una plantilla que ya no exista en el código se ignora en vez de
    reventar.
  - **La huella es por día, salvo en `antes_de_evento`, que es por evento**: esa
    plantilla devuelve un par (texto, identidad) por cada evento en la ventana. Con la
    huella `clave:día` de las demás, la segunda clase del mismo día daba con la de la
    primera en `_ya_dicho` y se callaba.

- **La hora del aviso del reloj se aprende** (`_hora_aviso_reloj`): `RELOJ_AVISO_HORA` era
  una constante elegida a ojo, y este aviso tiene una condición dura —o llega antes de que
  te duermas o no sirve—. Sale de la mediana de tus `sleep_start`, una hora antes. Tres
  cosas: la barrera barata (la hora configurada) se comprueba ANTES, porque la aprendida
  nunca es anterior y así el tick de cada 5 min no paga una consulta; se cachea por día; y
  si la hora calculada **cruza la medianoche se acota a `RELOJ_AVISO_TOPE`** (23:30),
  porque 00:30 ya no es "antes de dormir" y además, en una comparación `(hora, minuto)`
  del mismo día, es MENOR que las 21:30 y el aviso saldría a media tarde.

- **Informe de utilidad** (`_informe_avisos`, sección `## AVISOS` del informe semanal):
  cuántos avisos mandó cada regla y cuántos sirvieron. Va en el semanal y no en el diario
  porque es una pregunta de tendencia: en un día no se ve si una regla ha dejado de valer.

- **Vigilar una página** (`vigilar_pagina`, `_revisar_vigilancias`, tabla `vigilancias`):
  la capacidad proactiva **genérica**. Las reglas de `_REGLAS` son condiciones escritas a
  mano; esto es una que las cubre todas para lo de fuera (un precio, una plaza, una nota
  publicada) y **se crea hablando**, sin tocar código. Cuatro cosas:
  - **Dos preguntas distintas, no una**: "¿ha cambiado?" (huella del contenido) y "¿ya
    aparece esto?" (`buscar`). Mezclarlas daría un aviso cada vez que cambia un banner.
  - **La huella se guarda al dar de alta**, bajando la página en ese momento: si no, la
    primera revisión avisaría de un cambio que no ha habido. De paso comprueba que la
    página se puede leer — *dar por buena un alta que no funciona* es el bug del agente PC.
  - **El aviso lleva la URL, no un trozo de la página.** El contenido lo controla un
    desconocido y no se le pasa a ningún modelo para redactar nada.
  - La URL pasa por `url_web_permitida()` (SSRF) y el rechazo **no dice por qué**, como en
    `leer_pagina`.

- **El correo entrante** (`_revisar_correo`, el Outlook del usuario por Microsoft Graph):
  saca del buzón lo **accionable con fecha** y lo deja como aviso. **No es resumir el
  correo** — eso ya lo hace la rutina del briefing y hacerlo dos veces sería peor que no
  hacerlo. Es la capacidad más delicada en privacidad del proyecto, así que las
  restricciones van por delante y no como añadido: **apagada** sin `CORREO_LEER=1`; **solo
  cabeceras** (asunto, remitente, fecha) — el cuerpo no se lee ni viaja a ningún modelo, y
  lo que no se lee no se puede filtrar; **no se marca nada como leído**, porque leer por
  Graph no toca `isRead` y aquí no hay ningún `PATCH` (un asistente que te descoloca el
  buzón deja de usarse en una semana); y **no se guarda nada** en Supabase. Va por Graph y
  no por IMAP porque el IMAP de Outlook anuncia `LOGINDISABLED`: la contraseña no vale
  desde que Microsoft retiró la autenticación básica (`docs/TURNO_NOCHE.md`).
  Lo extraído se **propone como aviso**, nunca se crea en el calendario: lo que sale de un
  asunto interpretado por un modelo no tiene la fiabilidad para tocar la agenda sola, misma
  frontera que `sugerencia_evento()`.
  **La huella es el correo, no la frase**: cada asunto va con un número `n` y el modelo
  dice de cuál sale cada acción, y la huella es un hash del `internetMessageId` (o del id
  de Graph) más la fecha. Un no leído vuelve a entrar en cada revisión durante
  `CORREO_HORAS`, y con la frase del modelo de huella bastaba que la redactara distinto
  para avisar dos veces de lo mismo. Si el modelo no dice el `n`, se vuelve a la frase.

- **Gobierno de los avisos** (`_apuntar_aviso`, el despacho de recordatorios, tabla
  `avisos_reglas` + columnas nuevas en `jarvis_recordatorios`): un asistente proactivo
  tiene **un solo modo de fallo, volverse ruido**, y no falla de golpe — falla porque cada
  regla parece razonable por separado hasta que un día se dejan de leer todos los avisos a
  la vez, buenos incluidos. Cuatro piezas, y las cuatro viven en la PUERTA (al apuntar o
  al despachar) y no en cada regla, para que una regla nueva las herede sin poder
  olvidarse (misma razón que el interruptor del resumen dentro de `enviar_brief_si_toca`):
  - **Presupuesto**: los avisos compiten en vez de sumarse. `AVISOS_MAX_DIA` al día, el
    despacho ordena **por prioridad y no por fecha** (con el orden por fecha, un "sal ya"
    se quedaba fuera por tres avisos de la noche anterior) y lo que no entra **se pospone**
    a `AVISOS_HORA_DIFERIDOS` en vez de perderse. Lo urgente (`PRIO_SIN_TOPE`) se salta el
    tope: si el presupuesto pudiera con lo que caduca en minutos, el aviso que más corre
    sería el primero en caerse. Un aviso con `caduca` vencida **no se manda**: llegar tarde
    no es llegar, es mentir, y enseña a no fiarse del canal.
  - **Utilidad** (`_valorar_regla`, `POST /avisos/{id}/util`): botones en la notificación
    de HA. Es lo ÚNICO que hace que el sistema mejore sin que nadie lo toque — sin esa
    señal, la única forma de que una regla mala desaparezca es dejar de mirar los avisos,
    que se lleva por delante a los buenos. El contador de "no útil" es **consecutivo** y un
    "útil" lo pone a cero (se busca una regla que dejó de valer, no una que tuvo un mal
    día), y **no contestar no vota**. Silenciar es **visible**: se avisa al hacerlo, con
    cómo revertirlo, y sale en `GET /avisos/estado`.
  - **Memoria** (`_ya_dicho`, columna `huella`): la idempotencia vieja era por DÍA, así que
    "llevas 3 días sin entrenar" salía el jueves, el viernes y el sábado y solo el primero
    informaba. La huella es la SITUACIÓN, no el texto: en el proactivo son los motivos en
    crudo, antes de que el modelo los redacte, porque dos redacciones del mismo hecho son
    el mismo aviso. **Un id opaco no se recorta para meterlo en una huella, se resume con
    un hash** (`_id_evento_corto`): ver «La huella de "Sal ya" recortaba el id de Graph»
    en `docs/BUGS_HISTORICOS.md`.
  - **Vigencia** (`_sigue_en_pie`, `_voz_al_despachar`, en el despacho): un aviso
    PROGRAMADO se comprueba contra la realidad justo antes de salir, no solo al apuntarlo.
    `caduca` resuelve el aviso que llega tarde; esto, el que llega a tiempo a algo que ya
    no es así. Hoy solo lo necesita el «Sal ya», que se programa hasta una hora antes: con
    su huella (`salir:<hash>:<inicio>`) el despachador busca la cita en el calendario y,
    si se ha movido o cancelado, **lo cierra sin mandarlo** (`enviado=True` y
    `enviado_at` vacío, como un caducado, para que no cuente como enviado; sin
    notificar, sin contar un envío de la regla y sin votar; la salida del tick dice
    `avisos_retirados`). Va antes del presupuesto, para que lo que ya no vale ni se
    posponga ni gaste hueco. Los eventos se leen **una vez por pasada**, y ninguna si no
    hay ningún «Sal ya» vencido. **Ante la duda se habla**: con Graph caído, con una
    huella antigua (sin la hora, de antes de esta pieza) o ante cualquier fallo, sale.
    Callar un «Sal ya» bueno cuesta la cita; repetir uno malo, un vistazo.
    La **voz** del «Sal ya» también se decide al soltarlo, con la presencia vigente: si
    entretanto has salido, Alexa no se lo dice a una casa vacía, y si has vuelto, sí te lo
    dice. Con la presencia caducada no se sabe dónde estás y se respeta lo que se decidió
    al apuntar. Estar fuera **quita la voz pero no retira el aviso**: puedes estar fuera y
    tener que ir igual.
    En el gimnasio y en clase, además, lo que no corre prisa **espera** a que salgas, y
    lo que ya no es verdad allí se retira: ver «Lugares: casa, gimnasio y uni», abajo.
    Y al **volver a casa** (`_retirar_avisos_de_salida`, desde `POST /ha/presencia` al
    pasar de fuera a en casa), las notificaciones de hoy de `al_salir` y `pc_encendido`
    que siguen sin valorar se **retiran del móvil** por su id (su `tag`), nunca por regla,
    y **sin votar**: no haber pulsado nada antes de volver no dice que el aviso no
    sirviera. Sin móvil vivo no se consulta nada, y un fallo ahí no toca la respuesta de
    la presencia.
  Y la frontera que no se relaja: **lo que pediste tú no se gobierna**. Un recordatorio sin
  `regla` (`recordarme`) no cuenta contra el tope ni se puede silenciar — la misma regla
  que hace que el interruptor del resumen no tape un envío pedido a mano.
  **Y "pediste tú" incluye tus propias reglas** (`tuya:*`, `_es_tuyo()`). Esto se escribió
  pensando solo en `recordarme`, y las reglas que TÚ apruebas llevan `regla` por sus
  estadísticas: caían dentro del presupuesto (que son **tres** avisos al día por defecto)
  y se posponían a `AVISOS_HORA_DIFERIDOS`, así que una regla tuya de las 20:30 llegaba
  a las 08:30 — **doce horas tarde y sin dejar rastro de por qué**. El presupuesto existe
  para que las reglas del SISTEMA compitan entre ellas, no para racionar lo que has pedido
  a mano. Tampoco cuentan para el tope, o tres avisos tuyos callarían al sistema el resto
  del día.
  Los fallos caen hacia HABLAR: si no se puede comprobar el silenciado o la huella, se
  avisa igual. Repetir un aviso molesta; callarlo puede costar el dato.

- **El retraso de un aviso se registra** (`_registrar_retraso`, `_posponer_aviso`): un
  aviso que llega tarde y uno que se apuntó a la hora equivocada son **indistinguibles
  después**, y sin poder distinguirlos no se arregla ninguno de los dos — ese diagnóstico
  se hizo a ciegas dos veces. El reloj es el tick de HA cada 5 minutos, así que un aviso
  normal sale con menos de cinco de retraso; a partir de `AVISO_RETRASO_AVISA_MIN` (15) va
  un `warning` y a partir de `AVISO_RETRASO_AVERIA_MIN` (60) un `error`, que es lo que lo
  lleva a `app_logs`, al panel, al `diagnostico` y al vigilante **sin abrir un camino
  nuevo**. Un aplazamiento por presupuesto no pasa por ahí —reescribe `cuando`, así que su
  retraso medido es cero— y por eso lo registra `_posponer_aviso`, que es quien sabe que
  fue una decisión y no una avería.
  Del mismo diagnóstico salió otra cosa: **el despacho es lo ÚLTIMO que evalúa el tick**,
  detrás de todo lo que apunta avisos, así que una excepción suelta en cualquiera de esos
  pasos no costaba un aviso, costaba TODOS los recordatorios vencidos mientras durase (el
  tick devolvía un 500 que solo veía HA). Ahora todos van envueltos (`_avisar_reloj_seguro`,
  `_correr_reglas_seguro`); si añades algo al tick que apunte avisos, envuélvelo igual.

- **La revisión nocturna, accionable** (`POST /revision/hallazgos`,
  `POST /revision/{id}/accion`, tabla `revision_hallazgos`, herramienta
  `arreglar_revision`, `contar_revision`): el issue que deja la revisión de madrugada
  llega al móvil por la mañana con tres botones —«Arreglarlo», «No hacer nada» y
  «Hablarlo»—, y el primero lanza otra sesión en la nube que lo arregla, abre PR y mergea
  si el CI pasa. **«Hablarlo» hace sonar el teléfono por la centralita** (`accion:
  "hablar"`, que no toca `estado` y se puede pulsar varias veces) y contesta
  **Jarvis-Claude**, con el **issue entero** ya armado por `_jarvis_contexto_llamada`
  (`contar_revision` hace lo mismo por escrito, y no confirma nada porque solo lee). Antes
  de la centralita este botón abría el dashboard con Jarvis-GPT; ese camino sigue vivo
  como vía manual (`?llamada=1&aviso=<id>&tipo=revision`) pero ya no es el botón por
  defecto — ver `docs/LLAMADAS.md`. Los botones los decide el
  backend (`_acciones_aviso`) y viajan **dentro del aviso**: HA solo sabe a qué móvil van.
  La decisión vive en Supabase porque entre el aviso y el toque pasan horas y Fly escala a
  cero, y se consume con un **PATCH condicional** para que dos toques no lancen dos
  agentes. El flujo entero, con las dos routines y el YAML, en `docs/REVISION_NOCTURNA.md`.

  **Y pulsar «Hablarlo» ya no deja el aviso sin dónde contestarse.** La app del móvil
  descarta la notificación en cuanto pulsas cualquier botón, y éste es el único que no
  decide nada: el aviso seguía pendiente en la tabla y mudo en el móvil, así que si no
  cogías la llamada —o la cogías y no decidías— no te quedaba dónde responder y el aviso
  solo reaparecía al descolgar por otra cosa. Ahora `_reponer_tras_hablar` programa una
  reposición a los `HABLAR_REPONER_SEG` (360 s: el tope de una llamada más un minuto) y,
  **solo si el aviso sigue pendiente**, lo devuelve al móvil con sus botones. Se espera en
  vez de reponer en el acto porque el acto es justo cuando está sonando el teléfono, y
  porque esa espera es lo que permite no reponer nada cuando sí decidiste hablando. El
  reloj es un temporizador y no el fin de la llamada porque **la centralita no le cuenta
  al backend que has colgado**; el día que lo haga, este temporizador es lo que sobra.

  El camino inverso lo cierra `_retirar_del_movil`: cuando el aviso SÍ se resuelve —por
  teléfono, por el dashboard o por el botón— su `tag` se encola en `borrar` y HA retira la
  notificación del móvil (`clear_notification`). Sin eso quedaba un botón preguntando algo
  ya contestado, que no rompe nada pero enseña a desconfiar del canal por el que llegan
  las averías.

- **El arreglo que pide permiso para desplegarse** (`POST /averia`,
  `POST /revision/pr-listo`, `POST /despliegue/{id}/accion`, herramienta `desplegar`): el
  camino inverso al de arriba. Cuando el CI se rompe en `main` no se pregunta nada — se
  lanza el arreglo en el momento — y la pregunta llega DESPUÉS, cuando hay un PR con el
  CI en verde: «he detectado un fallo, ya lo he corregido, ¿lo despliego?». Va al móvil
  con botones **y hace sonar el teléfono**, que es el único canal que no espera a que
  mires. La frontera es la de siempre en este fichero, aplicada a lo más caro que hay:
  **arreglar solo, sí; desplegar solo, no** — abrir un PR es reversible, tocar producción
  no. El flujo entero en `docs/AVERIAS.md`; el teléfono —con Jarvis al otro lado,
  contestándote— en `docs/LLAMADAS.md`.

- **El aviso que deja una sesión de Claude Code** (`POST /sesion/aviso`, tabla
  `sesion_avisos`, `GET /llamada/pendiente`, herramienta `responder_a_la_sesion`): el
  mismo canal que el de arriba, pero hablando de otra cosa. Una sesión que ha estado
  trabajando en el repositorio deja «esto me pediste, esto he hecho, esto ha quedado a
  medias»; su botón **«Hablarlo» hace sonar el teléfono por la centralita**
  (`LA_HABLAR_SES_<id>` → `POST /sesion/{id}/accion` `{"accion":"hablar"}`) y contesta
  **Jarvis-Claude**, que ya lo sabe (el contexto viaja armado por
  `_jarvis_contexto_llamada`, delimitado como dato) y lo que contestes hablando dispara
  una sesión NUEVA que sigue el trabajo (vía la herramienta `responder_a_la_sesion`, que
  sigue estando solo en Jarvis-GPT/dashboard, no en el MCP del teléfono). Dos cosas que no
  son detalles: **solo avisa si lo pediste o si la sesión se quedó
  bloqueada** —nunca por terminar algo sin más, que es lo que llenaría el canal de ruido—
  y **solo lo bloqueado atraviesa el silencio del móvil**, por la misma regla que decide
  quién puede llamarte por teléfono. El flujo entero en `docs/AVISAME.md`.

- **Por qué suena la llamada, y por qué eso no se adivina.** Los tres avisos de arriba
  comparten la pantalla de llamada, y Jarvis descuelga con lo que espera ya mirado y
  metido en el prompt: es una optimización de latencia (1,7 s contra 9,7 s si tiene que
  pedir una herramienta), no de capacidad. Cuál de los tres cuenta lo decide, por este
  orden, `_jarvis_contexto_llamada`:
  1. **El motivo que traiga el botón.** «Hablarlo» abre `?llamada=1&aviso=<id>&tipo=<cuál>`,
     el dashboard lo arrastra en el cuerpo de **cada** turno —el prompt se arma de cero en
     cada uno— y eso manda sobre todo lo demás. `tipo` no es redundante: los permisos de
     despliegue y las decisiones de revisión son la misma tabla con distinto `estado`.
  2. **Y si no, el orden de siempre**: despliegue, aviso de sesión, decisión sin contestar.
     Primero el que tiene trabajo verificado PARADO esperando permiso.

  Ese orden **solo decide cuando no se sabe por qué se ha descolgado**. Que decidiera
  siempre es lo que hacía que Jarvis te contestara que no había ningún issue con el issue
  delante; está contado en `docs/BUGS_HISTORICOS.md`, y costó dos intentos.

  **Por escrito no se consulta nada de esto.** El chat casi nunca va de lo que hay
  pendiente y ahí los segundos no se notan, así que pagar la consulta en cada turno solo
  sería pagarla. Si le escribes a Jarvis «¿qué issue?» en vez de descolgar, no lo sabe y
  tiene que ir a buscarlo con `contar_revision` — no está roto, está sin pagar.

- **Vigilante del sistema** (`_vigilar_sistema()`, mismo tick de HA, tabla
  `vigilante_estado`): el de la ingesta mira UNA cosa —que sigan entrando datos de
  salud—; este mira si el sistema se rompe por cualquier otro sitio. `app_logs` y
  `diagnostico` ya guardaban la respuesta; lo que faltaba era **alguien que hiciera la
  pregunta sin que se lo pidan**, que es lo que convirtió las tres averías grandes en
  semanas de silencio. Tres reglas:
  - **El listón va en CÓDIGO.** Las reglas deciden SI hay avería (hoy: ≥
    `VIGILANTE_MIN_ERRORES` errores de código del mismo origen en la ventana, ≥
    `VIGILANTE_MIN_ERRORES_RED` si son de red, y el disparo de la rutina fallado); el
    modelo, si acaso, redacta. Misma frontera que
    `_motivos_proactivos`: dejarle decidir a él qué es un problema acaba en un aviso
    diario porque sí.
  - **Reparar en silencio TAPA la avería.** Lo reparado se dice, y se dice **cuántas
    veces lleva** (`vigilante_estado.veces`): un fallo que se arregla solo todos los días
    no está arreglado, está escondido.
  - **Solo se repara lo que se puede verificar.** La lista blanca es cerrada y hoy tiene
    UNA entrada, el disparo de la rutina, porque su 2xx ES la comprobación del efecto —
    *lanzar algo no es comprobar que funciona*. Lo que necesita un cambio de código no se
    repara: se abre un **issue** en `JARVIS_REPO` por el MCP de GitHub que haya conectado
    (`_vigilante_abrir_issue`, solo la primera vez de cada avería: uno por día del mismo
    fallo convierte el repo en el ruido del que esto viene a salvarte). Las herramientas
    se buscan por nombre EXACTO (`create_issue`/`issue_write`, que piden argumentos
    distintos): inventarle argumentos a una herramienta que ESCRIBE es peor que no abrir
    el issue. **Lo que autoriza esta llamada es esa lista cerrada, no `confiar`**, y ese
    matiz costó dos semanas de nada: hasta septiembre de 2026 se exigía `confiar: true`
    porque el vigilante corre sin usuario delante (`_mcp_pide_confirmar()`, la frontera de
    confirmación de más arriba), y como el único servidor dado de alta es el de GitHub y
    está —correctamente— sin confiar, **la función no llegó a ejecutarse ni una vez**: 281
    avisos del mismo fallo, cero issues, `issue_url` a null desde el primer día. *Un
    interruptor de seguridad que nadie enciende no protege, esconde.* Lo que hay ahora es
    más estrecho, no más ancho: dos nombres de herramienta nuestros y unos argumentos que
    se escriben aquí, sin elegir nada por parecido. Y `_mcp_pide_confirmar` no se toca:
    Jarvis escribiendo desde el chat sigue pasando por ti.
  Lo que queda fuera **a propósito**: la rutina PAUSADA (es una decisión del usuario, no
  una avería), el silencio de la ingesta (ya tiene vigilante, y dos avisos de lo mismo se
  dejan de leer los dos), y los envíos fallidos del resumen/informe y los avisos que el
  móvil no recoge — **ya se reintentan solos** en cada tick (`_liberar_envio`,
  `_rescatar_avisos`). Y lo que **no se puede** detectar desde aquí: que HA deje de
  sondear, porque a este código lo ejecuta ese mismo tick; si HA muere, el vigilante
  muere con él y solo lo ve algo de fuera (el workflow de Actions de respaldo).
  Un fallo leyendo el registro **calla** (la regla de siempre: "no he podido preguntar" no
  es "está roto") y un fallo de `vigilante_estado` **no calla el aviso**: sale sin cifras
  y sin issue. Si la migración no se aplica, lo único degradado es el vigilante.

  **El aviso es una PREGUNTA con tres botones, no una noticia** (desde el 2026-09-12; el
  tercero, desde el 2026-09-14). Los mismos que la revisión nocturna —«Arreglarlo» / «No
  hacer nada» / «Hablarlo»— y a propósito: la pregunta es la misma, la contesta el mismo
  endpoint (`POST /revision/{id}/accion`) y reusar los ids `LA_ARREGLAR_` / `LA_NADA_`
  significa que esto **no necesitó ni una línea nueva de YAML en Home Assistant**.
  «Arreglarlo» ya no abre el dashboard (lo hizo del 2026-09-14 al 2026-09-26, tras
  perderse cinco decisiones seguidas en el salto móvil → HA): lo que avisa de que se ha
  perdido es que no llegue el acuse «🔧 Arreglando». «Hablarlo» hace sonar el teléfono por la centralita (`LA_HABLAR_REV_<id>`,
  `accion: "hablar"`) con el issue entero delante, y contesta Jarvis-Claude, no el
  dashboard. Los dos, explicados en `docs/REVISION_NOCTURNA.md`. La decisión se apunta en `revision_hallazgos` con
  `origen='vigilante'` —la misma tabla que ya guarda las otras dos clases de decisión de
  este proyecto, así que tampoco hizo falta migración— y **la sesión que lanza ese botón
  abre PR y NO mergea**, igual que el camino de las averías (`docs/AVERIAS.md`): arreglar
  solo, sí; desplegar solo, no. Si no hay rutina de arreglo configurada, o si la decisión
  no se puede escribir, el aviso sale **sin botones** (regla `vigilante_solo`) en vez de
  con uno que al pulsarlo no encontraría su fila — pulsar algo y que no pase nada es la
  avería clásica de este canal.

  **Y la avería se identifica por QUÉ errores son, no solo por de dónde salen.** La clave
  era `errores:<origen>`, el origen siempre es `life-assistant`, y como el issue solo se
  abre mientras `issue_url` sea nulo, **el primer issue valía para siempre**: el
  2026-09-12 el vigilante llevaba 317 detecciones desde el 21 de agosto apuntando a un
  issue del 3 de septiembre que hablaba de otros errores y que, encima, decía «8 errores
  en life-assistant» **sin listar ni uno**. Ahora la clave lleva una huella de las formas
  de error que la componen (`_firma_error`, que sustituye las cifras por `#` para que el
  mismo fallo con otro tiempo de respuesta no cuente como otro), así que un conjunto
  nuevo es una avería nueva: issue nuevo, y aviso el mismo día. Y tanto el aviso como el
  issue **los nombran** (`VIGILANTE_MAX_DETALLES`): «8 errores» no se puede arreglar
  porque no dice cuáles, ni por una persona ni por la sesión que lance el botón.

  **Pero la huella del conjunto, sola, abría un issue por día de la misma avería.** Al
  vaciar los issues abiertos el 2026-09-16 había **siete** del vigilante y ninguno se
  arreglaba tocando código. #179 y #180 son la misma caída de DNS del Green en dos días
  (200 y 196 errores, casi las mismas cinco líneas) y #182 su cola: una caída que dura
  tres días no repite el conjunto exacto de formas —pierde una un día, gana otra al
  siguiente—, así que cada día era una avería nueva. La memoria es ahora de **dos
  niveles**: la clave de la avería sigue llevando la huella del conjunto (eso es lo que
  hace que un conjunto nuevo hable el mismo día, y no se toca) y además cada FORMA de
  error tiene la suya (`_vigilante_clave_firma` → `firma:<origen>:<hash>`, mismo
  `vigilante_estado`). Antes de abrir un issue se mira si alguna de esas formas ya tiene
  el suyo (`_vigilante_issue_de_firmas`): si lo tiene, **se reaprovecha** y el aviso dice
  «ya hay un issue abierto por esto» en vez de abrir otro. Se reaprovecha en vez de
  comentar en él a propósito — esto corre cada hora, y un comentario por hora es otra
  forma del mismo ruido. No poder mirarlo **no calla nada**: se abre el issue igual, que
  es lo que pasaba antes; callar una avería por no poder deduplicarla sería cambiar un
  ruido molesto por un silencio peligroso.

  **Y un fallo de red no es «un cambio de código».** Los siete issues terminaban con «no
  se puede reparar desde el backend, así que necesita un cambio de código» y en los siete
  era falso: timeouts, DNS y `Gateway Timeout` de Supabase. *Esa frase* es la que los
  hacía parecer accionables y la que los dejó abiertos semanas. Ahora cada forma de error
  se clasifica (`_error_de_red`, sobre el mensaje **crudo**: `_firma_error` ya ha
  sustituido las cifras por `#` y se ha quedado con la primera línea, mientras que el
  nombre de la excepción vive al final del traceback), y una avería es de red cuando
  **todas** sus formas lo son. Lo que cambia para esas:
  - **Otro umbral** (`VIGILANTE_MIN_ERRORES_RED`, 25 frente a 3): un puñado de timeouts
    sueltos es la vida normal de internet. #183 y #184 fueron cuatro y cinco `Gateway
    Timeout` sueltos y abrieron issue.
  - **Ni issue ni botón «Arreglarlo».** Lo segundo es lo que más importa: ese botón lanza
    una sesión de Claude Code contra el repositorio, y con `NOCHE_ARREGLA` encendido eso
    es mandarla a cambiar código que no está roto. El aviso al móvil **sale igual** —para
    eso se ha detectado—, diciendo que es de red y que no hay código que cambiar.
  - **Se cuentan aparte de las de código**, aunque compartan origen: juntas, doscientos
    timeouts arrastraban por encima del umbral a los tres errores de código que iban en
    medio y encima copaban los `VIGILANTE_MAX_DETALLES` del aviso y el `detalle` que lee
    la sesión de arreglo.

  **Una credencial rechazada es una tercera clase** (`_error_de_servicio`, hoy
  `SMTPAuthenticationError`). Tampoco es código —#244 lo abrió el vigilante como issue, y
  ninguna sesión arregla una contraseña de aplicación revocada—, pero tampoco es la red,
  porque no pasa sola. Va **sin issue ni botón**, como la red, pero **con el listón de
  código** (3): con el de red (25), y ahora que el correo deja de insistir tras el primer
  rechazo (`docs/BRIEF.md`, «Cuando el envío falla»), no llegaría nunca. Los cortes del
  servidor SMTP (`SMTPServerDisconnected`, `SMTPConnectError`) sí son red.

  La clasificación es deliberadamente **tímida**: lo que no se reconoce cuenta como
  código. Un falso negativo abre un issue de más —lo que ya pasaba—; un falso positivo se
  callaría una avería real. Y los códigos de estado se exigen en contexto (`devolvió 504`,
  `→ 502`, `(504)`) y no sueltos, porque un `504` a secas casa con el «line 504» de
  cualquier traceback.


- **Jarvis se diagnostica** (`diagnostico`): fallos de `app_logs` agrupados por origen,
  estado del resumen diario, cuántos días lleva cada métrica sin dato, **quién escribió
  por última vez** (de `/health/diagnostico`, ventana corta: es una lectura de tabla) y
  qué integraciones están configuradas. Con un cambio de aparato apuntado, las métricas
  que llevan más de `METRICA_RETIRADA_DIAS` (7) días sin dato van marcadas
  `ya_no_la_mide_tu_aparato`, con una `nota` que lo explica: sin la marca, a «¿por qué no
  llegan mis horas de pie?» contestaba con una ingesta parada, cuando es que la pulsera no
  las mide. Misma regla que la zona dev (`docs/SALUD.md`, «Lo que vigila la frescura»). Es la pregunta más frecuente que se le hace a un asistente que falla
  de vez en cuando —no "qué tiempo hace", sino "¿por qué no me llegó el correo?"— y toda
  la información existía sin forma de preguntarla hablando. **No devuelve cuerpos de error
  ni contextos**: nivel, origen, recuento y fecha. El detalle se queda en el servidor (la
  regla de `_supabase_error()`), y aquí además acabaría dentro del prompt de un modelo.

- **Jarvis destila su memoria solo** (`_quizas_destilar`, colgado del punto único de
  salida `_responder`): al cerrar un turno de una conversación ya larga, una llamada
  aparte saca los HECHOS duraderos y los guarda con `_j_recordar`. Guardar por iniciativa
  propia (lo pide el prompt) funciona a ratos: el modelo se acuerda cuando el hecho es
  evidente y se olvida cuando está metido en otra cosa, que es justo cuando aparecen los
  hechos que valen. Dos frenos de coste, porque es una llamada de más:
  `JARVIS_DESTILAR_DESDE` turnos y como mucho una vez cada `JARVIS_DESTILAR_MINUTOS`. Ese
  segundo freno vive en memoria a propósito — perderlo en un cold start cuesta una
  llamada, no un dato. Un fallo o una respuesta ilegible no tumban el turno.

- **Jarvis habla primero** (`_motivos_proactivos`, `_hablar_si_hay_algo`, en el tick de
  HA): una vez al día, si alguna regla se cumple, deja un aviso. Un asistente que solo
  contesta obliga a acordarse de preguntar, que es lo que no funciona. Es la idea con más
  potencial de volverse insoportable de todo el proyecto, así que:
  - **El listón está en el CÓDIGO, no en el criterio del modelo.** Las reglas deciden SI
    hay algo que decir (entrega hoy o mañana, sesiones sin cobrar por encima del punto de
    cobro, días seguidos sin entrenar); el modelo solo REDACTA lo ya decidido. Dejarle
    decidir a él cuándo hablar acaba en un aviso diario porque sí.
  - **Si el modelo falla, sale en crudo**: la información es lo que vale, la redacción es
    el adorno.
  - **Sin histórico de entrenos no se regaña**: sin él no se sabe si es una racha o es que
    el Watch nunca los registró. La regla de siempre.
  - **El reloj no entra aquí**: ya tiene su propio aviso, y dos correos por lo mismo es la
    forma más rápida de que se dejen de leer los dos.
  - Idempotencia con el mismo `uuid5` de la fecha contra la clave primaria de
    `jarvis_recordatorios`, y apagado (`JARVIS_PROACTIVO=0`) no cuesta ni una consulta.

## Lugares: casa, gimnasio y uni

Hasta octubre de 2026 la presencia solo decía «en casa» o «fuera», y todo lo proactivo
hablaba a ciegas: «llevas tres días sin entrenar» llegaba estando en el gimnasio, y lo que
no corría prisa sonaba en mitad de clase. Ahora dos sitios más tienen nombre. El código
está en la sección «Lugares» de `backend/main.py`, y la lógica pura del dashboard en
`src/lib/lugares.js`.

- **Cómo sabe dónde estás.** Igual que antes: HA empuja la zona del `device_tracker` a
  `POST /ha/presencia` (ver `docs/HOME_ASSISTANT_FLUJOS.md`). Lo nuevo es la traducción
  de la zona a un **lugar**, que es una lista cerrada: `casa` (lo de siempre, `en_casa`),
  `gimnasio` (zonas de `ZONAS_GIMNASIO`, por defecto `gimnasio,gym`), `uni`
  (`ZONAS_UNI`, por defecto `uni,universidad`) y `fuera` para todo lo demás. Una zona que
  no está en ninguna lista no se adivina por su nombre. **Para que funcione hay que crear
  las dos zonas en HA** con uno de esos nombres; sin ellas todo se comporta como antes.
- **Un lugar no cuenta hasta que llevas un rato** (`LUGAR_ESTABLE_MIN`, 5 min). Hay dos
  estados en memoria: el *crudo* (lo último que dijo HA) y el *firme* (el que ha aguantado
  ese rato). Las llegadas y las salidas son cambios del firme, así que pasar andando por
  delante del gimnasio no calla nada, y un parpadeo del GPS a «fuera» durante un minuto no
  es una salida. Las procesa `_procesar_lugar`, desde el aviso de presencia **y desde el
  tick**: sin el tick, una llegada no contaría hasta el siguiente aviso de HA (15 min).
  Tras un reinicio, el estado se reconstruye de los tramos guardados
  (`_desde_recuperado`); tras un hueco de HA más largo que el TTL, se empieza de cero y
  **no hay salida que procesar**: lo de entre medias no lo sabe nadie.
  **Lo de casa NO espera**: apagar lo que te dejaste encendido sigue saltando con el
  primer aviso de «fuera», sin el listón de estabilidad.
- **El despacho espera en el gimnasio y en clase** (`_espera_por_lugar`, en
  `_despachar_recordatorios`). Lo que no corre prisa del SISTEMA se queda pendiente con
  `cuando` = ahora (para que al salir el retraso medido sea el real y no dispare la
  alarma de retraso) y sale en el primer tick después de irte o de que termine la clase.
  «En clase» es la uni como lugar firme **y** una clase del calendario de clases en curso:
  una clase a la que no has ido no te tiene en un aula, y la uni entre clases no es una
  clase. Las fronteras son las del presupuesto: lo que pediste tú (sin regla o `tuya:*`)
  y lo urgente (`PRIO_SIN_TOPE`) salen siempre, y lo que se dice precisamente allí
  (`_REGLAS_DEL_LUGAR`: el cobro al llegar al gimnasio) también. Va **antes** del
  presupuesto: un aviso que solo tenía que esperar una hora no se manda a mañana. Sin
  presencia vigente se habla, como siempre. En clase, además, lo `critico` sale pero sin
  atravesar el silencio del móvil, y **el teléfono no suena** (`_telefono_puede_sonar`:
  el lugar sale de lo que hay en memoria, sin consultar nada, y solo en la uni se mira el
  calendario de clases, con diez minutos de caché).
- **Lo que ya no es verdad allí se retira** (`_sigue_en_pie`): el «Llevas N días sin
  entrenar» (`hueco_entreno`) en el gimnasio, y el «Sal ya» cuando ya estás donde es la
  cita. Este último se recalcula solo estando en la uni o el gimnasio (desde casa el
  cálculo de la regla ya era el bueno), con la caché de Maps de siempre, y se retira si el
  trayecto es menor que `SALIR_YA_ESTAS_MIN`. Ante la duda (sin Maps, sin dirección) sale.
- **No se regaña el día del gimnasio** (`_estuvo_en_gimnasio_hoy`): ni el motivo de días
  sin entrenar del aviso diario ni `_regla_hueco_entreno` hablan si estás en el gimnasio
  o hoy has pasado allí al menos `GIMNASIO_SESION_MIN`. El Watch no siempre registra el
  entreno, o aún no lo ha sincronizado. Ante la duda, NO cuenta como ido: esto solo calla
  un reproche.
- **Lo que se dispara al llegar y al salir** (todo por `_apuntar_aviso`, detrás de
  `REGLAS_PROACTIVAS`):
  - **Al llegar al gimnasio** (`cobro_gimnasio`): sesiones sin cobrar por encima del punto
    de cobro, dicho donde ves a quien entrenas. Huella `cobro:<n>`, la misma que mira el
    aviso diario para no repetirlo.
  - **Al salir del gimnasio** tras `GIMNASIO_SESION_MIN` (`sesion_gimnasio`): «¿Diste una
    sesión?», con «Apuntar sesión» (`GIMNASIO_SESION_HORAS`, con la fecha del aviso, y
    sin duplicar si ya hay una ese día) y «Entrené yo». **Estar allí no dice si
    entrenabas tú o entrenabas a alguien**, así que no se apunta nada solo; lo que sí se
    sabe es cuándo no preguntar: ya hay una sesión apuntada hoy, o el Watch tiene un
    entreno tuyo que empezó en ese rato. «Entrené yo» manda `LA_UTIL_`, no un «No»: es
    una buena respuesta a una buena pregunta, y votarla en contra silenciaría la regla.
    Caduca a medianoche.
  - **Al salir de la uni** (`entrega_uni`): una entrega (`ENTREGAS_MARKER`) para hoy o
    mañana, de los dos calendarios. Comparte huella con el aviso diario de las 19:00.
  - **Al salir de la uni o del gimnasio** (`vuelta_casa`): «¿Vuelves a casa? Puedo
    encender…», solo si has declarado qué (`VUELTA_CASA_ENTIDADES`, `VUELTA_CASA_PC`) y
    está apagado. Nunca enciende solo: no se sabe si vas a casa. Caduca en una hora.
  Los dos botones que actúan («Apuntar sesión», «Encender») reutilizan `LA_APAGAR_`, como
  el «Suspender» del PC: ni una línea nueva de YAML en HA; `POST /avisos/{id}/apagar`
  decide qué hacer por la regla del aviso.
- **Recordatorios por lugar** (`recordarme_en_un_lugar`, tabla `recordatorios_lugar`):
  «recuérdame al llegar a casa…», «…al salir del gimnasio». Tabla aparte porque no tienen
  hora y el despachador pregunta por `cuando`. Al llegar o salir (firme) se reservan con un
  PATCH condicional y se convierten en un recordatorio normal **sin regla** —lo pediste
  tú—, que entrega el despachador de siempre. Solo saltan si se apuntaron **antes** de
  esa llegada o salida: si no, un «al llegar a casa» dicho en casa sonaría al momento, y un
  reinicio que reprocesa la llegada los sonaría todos. `mis_recordatorios` y
  `cancelar_recordatorio` cubren los dos tipos.
- **Jarvis lo sabe sin preguntar** (`_jarvis_contexto_lugar`, en el prompt de sistema):
  dónde estás, desde cuándo y, en la uni, si estás en clase. Va en el prompt y no solo en
  `donde_estoy` porque cambia CÓMO contestar: en clase o entre dos series una respuesta de
  diez líneas no se lee.
- **Qué se guarda del dónde.** Los tramos de `presencia_tramos` llevan `lugar` (`gimnasio`
  o `uni`) y nada más: ni el nombre de la zona, ni coordenadas, ni ningún sitio que no
  hayas declarado. Es la frontera de `docs/IDEAS.md` movida un paso, a propósito. Sin la
  migración `20261005_lugares`, los tramos se escriben y se leen sin esa columna
  (`_tramos_sin_lugar`) y queda un error en el registro diciendo qué falta.
- **Lo que se descartó**: callar la firma de malestar por la FC del gimnasio. Mira la FC
  en reposo, la HRV y la respiración de cada día, que no se mueven por estar entrenando.

## El programador

`encargar_proyecto` (con botón), `ver_proyectos` y `hablar_con_el_programador`: Jarvis le
encarga a Claude Code, en un contenedor de `caja`, un proyecto entero y lo sigue. No es
`encargar_a_una_sesion`: aquel es para el código de este repositorio y corre en la nube;
este, para cualquier otro proyecto. Todo en `docs/PROGRAMADOR.md`.

## Jellyfin

`jellyfin_seguir`, `jellyfin_novedades` y `jellyfin_buscar` (directas, también por
teléfono) y `jellyfin_reproducir` (con botón, y el título del botón se comprueba contra el
elemento real al ejecutar). Todo en `docs/JELLYFIN.md`.

## Moodle: las entregas

`moodle_entregas` (consulta, directa, también en el MCP del teléfono) pregunta a Moodle lo
que sigue pendiente; para notas, materiales o foros está el servidor MCP `moodle`. La
sincronización con el calendario y sus avisos (`moodle_vence`, `moodle_nueva`) están en
`docs/MOODLE.md`.

## Tareas: Microsoft To Do

Lo que hay que hacer **sin hora**. Una cita va al calendario; «pásale el contrato a Luis
cuando puedas» metido en la agenda es ruido, y en Ideas se queda olvidado. Es la 7.2 de
`docs/IDEAS.md` (antes, la 2.3 de `docs/JARVIS_PROACTIVO.md`).

- **Mismo token de Graph que el calendario**, con un permiso más (`SCOPES_TAREAS`,
  `Tasks.ReadWrite`). Nace apagado (`TAREAS_TODO=0`) porque encenderlo obliga a volver a
  conectar Outlook una vez. Encendido sin reconectar no rompe nada: la renovación prueba
  antes quitando SOLO el permiso de tareas (`_scopes_de_repuesto()`), así que el buzón, si
  estaba consentido, sigue funcionando. Con un único repuesto —los permisos de siempre—,
  encender las tareas se llevaba también el correo hasta reconectar.
- **Una sola lista, la de por defecto** («Tareas», `wellknownListName: defaultList`).
  Elegir lista sería otra cosa en la que el modelo se puede equivocar. Su id se recuerda
  una hora (`_todo_lista_cache`) y un 404 lo vuelve a buscar.
- **Las fechas, en tu zona.** To Do guarda el vencimiento como la medianoche del día en la
  zona en que se puso y lo devuelve en UTC: una tarea para el 1 de octubre vuelve como las
  22:00 del 30 de septiembre. `_todo_fecha_local()` la devuelve a `LOCAL_TZ` antes de
  quedarse con el día. Al crear se manda la medianoche con `timeZone` = `TIMEZONE`.
- **Herramientas**: `tareas` (consulta, `confirmar: False`) y `crear_tarea` (acción,
  `confirmar: True`: la propone el modelo y la aprueba una persona, como `crear_evento`).
  No se anuncian con `TAREAS_TODO` apagado (`requiere_tareas`): anunciarlas para que
  fallen es pagar su descripción en cada turno. No hay «completar tarea» a propósito: el
  botón de confirmar tendría que enseñar un id de Graph, que no se puede leer, y el nombre
  no puede salir del modelo (ver `jarvisEtiquetaAccion`). Se marca como hecha en To Do.
- **`GET /tareas`** (JWT) devuelve las pendientes. Apagado o sin Outlook, 200 con
  `activo: false` y el motivo, no un error: es un estado, no una avería.

## El chat con Claude Code

El chat escrito del dashboard puede pensarlo una **sesión normal de Claude Code** en
`caja` —tu suscripción, Sonnet 5.5, la misma familia que contesta el teléfono— en vez
del bucle de OpenAI. Se enciende con `JARVIS_MOTOR_CHAT=claude` (por defecto `openai`).
Solo el chat: el modo llamada del navegador y el Atajo siguen con OpenAI, porque
arrancar Claude Code cuesta unos segundos por turno y hablando se notan.

```
/jarvis ──▶ chat/jarvis_claude.py (caja) ──▶ claude -p ──▶ /mcp/chat ──▶ las herramientas
```

- **Sin terminal, a propósito.** Es la diferencia con el Claude Code del teléfono. El
  servicio lanza `claude -p` con `--tools ""` (ni shell, ni ficheros, ni web propia),
  `--strict-mcp-config` (solo el MCP de Jarvis; los que tenga la máquina, el del teléfono
  incluido, no se cargan), `--permission-mode dontAsk` + `--allowedTools mcp__jarvis` y
  `--restricted` si la versión lo tiene. Al chat llegan correos, páginas y documentos que
  ha escrito cualquiera: con una terminal, uno bien escrito acabaría en un comando en la
  máquina que lo aloja todo. Los argumentos los monta el servicio, no el backend, y sin
  `--tools` en la CLI el servicio **no arranca**.
- **Las mismas herramientas que el chat de OpenAI** (`/mcp/chat` anuncia
  `_jarvis_esquema()`, con sus `requiere_*`), no la lista cerrada del teléfono: aquí hay
  botón de confirmar. Lo que lo necesita **no se ejecuta**: se apunta como pendiente del
  turno y vuelve al dashboard como el botón de siempre (`/jarvis/ejecutar`).
- **El turno viaja en la URL del MCP** (`/mcp/chat?turno=<uuid>`): es lo que ata las
  herramientas usadas y lo pendiente a la respuesta de ESE turno. No es una credencial
  —la credencial es `JARVIS_MCP_CHAT_TOKEN`, distinto del del teléfono—; un turno
  desconocido solo hace que lo pendiente no se pueda proponer.
- **Cada turno es una sesión nueva** con la conversación entera en el mensaje
  (`--no-session-persistence`): el historial sigue viviendo en el dashboard, como con
  OpenAI, y en `caja` no hay sesiones que guardar ni purgar. El prompt es el de siempre
  (`_jarvis_sistema`) y **sustituye** al de Claude Code, que es el de un programador.
- **Si no contesta, contesta OpenAI, y lo dice.** Caja apagada, la sesión OAuth de Claude
  Code caducada, un turno de más de `JARVIS_CLAUDE_TIMEOUT`: el backend lo registra,
  contesta con el bucle de siempre y la respuesta lleva `motor_aviso`, que el chat pinta
  como aviso. Una respuesta peor sin saber por qué es justo lo que esto viene a quitar.
- **La memoria se sigue destilando** con `_quizas_destilar`, igual que con OpenAI: lo que
  cuentas en el chat acaba en la misma memoria, piense quien piense.
- **Coste:** lo paga la suscripción, no la API. Lo que sí cuenta es su límite de uso,
  compartido con el teléfono y con lo que hagas con Claude Code en `caja`.

**Montarlo en `caja`** (lo hace Mikel; nada de esto sale del repositorio solo):

```bash
mkdir -p ~/jarvis-chat ~/.config/systemd/user
cp chat/jarvis_claude.py ~/jarvis-chat/
cp chat/env.example ~/jarvis-chat/.env && chmod 600 ~/jarvis-chat/.env   # y rellenarlo
cp chat/jarvis-claude.service ~/.config/systemd/user/
loginctl enable-linger "$USER"        # para que corra sin sesión abierta
systemctl --user daemon-reload && systemctl --user enable --now jarvis-claude
curl -s http://172.17.0.1:3340/salud  # {"ok": true, "modelo": "claude-sonnet-5-5"}
```

Y en `backend/.env`: `JARVIS_MOTOR_CHAT=claude`, `JARVIS_CLAUDE_URL`,
`JARVIS_CLAUDE_TOKEN` y `JARVIS_MCP_CHAT_TOKEN` (los dos tokens, iguales en los dos
`.env`). Si el contenedor no llega a la IP del puente de Docker, la otra salida es
`extra_hosts: ["host.docker.internal:host-gateway"]` en el compose de HomeLab. El
registro del servicio: `journalctl --user -u jarvis-claude`.

## Documentos: OneDrive

«¿Dónde está el contrato del piso?», «¿qué dice la póliza del coche sobre la grúa?». Es
la 7.4 de `docs/IDEAS.md`, y la primera fuente que Jarvis **consulta** en vez de vigilar.

- **Mismo token de Graph, un permiso más y de lectura** (`SCOPES_ARCHIVOS`,
  `Files.Read`). Nace apagado (`ONEDRIVE=0`) y encenderlo obliga a volver a conectar
  Outlook una vez. Escribir en OneDrive no se pide nunca.
- **Dos herramientas, las dos directas** (`requiere_onedrive`): `buscar_documentos`
  (`/me/drive/root/search`, por nombre y por contenido; solo ficheros, nunca carpetas) y
  `leer_documento` (por el id que dio la búsqueda). El id lo escribe un modelo y va en la
  ruta de Graph: se valida con `_DRIVE_ID_RE` antes de llamar.
- **Lo que se sabe leer**: PDF (`pypdf`, hasta `ONEDRIVE_MAX_PAGINAS`), Word y
  PowerPoint (son un zip de XML: se leen sin librería y con tope de descompresión, por si
  es una bomba de zip), texto, Markdown, CSV, JSON y HTML. Una hoja de cálculo no: sin su
  estructura, las celdas sueltas son peores que no contestar. Lo que no se lee —formato
  desconocido, más de `ONEDRIVE_MAX_BYTES`, un PDF cifrado o escaneado— vuelve como
  `error` **con el enlace**, para que el modelo diga «ábrelo aquí» en vez de inventarse lo
  que pone.
- **El texto de un documento es un dato, no una orden.** Llega con `_AVISO_DOCUMENTO`
  delante, igual que una página web con `_AVISO_WEB`: un PDF que te mandaron puede llevar
  instrucciones escritas para un modelo. Por eso mismo las dos herramientas **no están en
  la lista blanca del teléfono** (`_MCP_SERVIDOR_SOLO_LECTURA`): al otro lado de la llamada
  hay una sesión con shell en `caja`, y ahí ese texto podría torcer un comando y no solo
  una respuesta.
- La descarga va con `stream=True` y `_descarga_acotada`: el tamaño que declara Graph se
  mira antes, pero el tope de verdad es lo que se lee.

## Cumpleaños

Un aviso el día antes, y Jarvis sabiendo cuáles vienen. Es la 7.3 de `docs/IDEAS.md`.

- **Dos fuentes**: la fecha de nacimiento en la ficha de los contactos de Outlook
  (`Contacts.Read`, `SCOPES_CONTACTOS`) y los eventos del calendario. Del calendario por
  defecto, los que dicen «cumple», «cumpleaños» o «birthday» en el asunto; del calendario
  de cumpleaños de Outlook.com («Birthdays»/«Cumpleaños»), todos. Los demás calendarios
  —las clases— no se miran.
- **Todo bajo `CUMPLES=0`**, que nace apagado y pide el permiso de contactos. Los eventos
  no lo necesitan, pero van con él para que haya un solo interruptor.
- **El día no se corre.** Outlook guarda la fecha de nacimiento como un instante (a
  mediodía UTC, o a medianoche de tu zona): pasada a `LOCAL_TZ` el día es el bueno en los
  dos casos. Un evento de todo el día se lee por su fecha tal cual, sin pasar por UTC. Sin
  año (Outlook pone 1604) no se dice la edad. El 29 de febrero se celebra el 28 los años
  que no lo tienen.
- **El mismo cumpleaños no sale dos veces**: la ficha dice «Ane Etxeberria» y el
  calendario de cumpleaños «Ane»; mismo día y un nombre dentro del otro es el mismo.
- **Una fuente caída se dice** (`incompleto`): «no hay cumpleaños» y «no he podido mirar
  los contactos» no pueden sonar igual. Con las dos caídas es un fallo.
- **El aviso** es la regla `cumples` de `_REGLAS` (necesita `REGLAS_PROACTIVAS`): una vez
  al día a `CUMPLES_HORA` (10:00), del DÍA ANTES, que es cuando todavía se puede comprar
  algo. Todos los de mañana en **un** aviso, con huella `cumples:<fecha>` y caducidad a
  medianoche: pasado ese momento diría «mañana» de algo que ya es hoy. Está en
  `REGLAS_LLAMABLES`, así que también puede llamar si lo pides desde la zona dev.
- **Herramienta `cumpleanos`** (directa, `requiere_cumples`, también por teléfono) y
  `GET /cumpleanos?dias=`. Para «¿cuándo es el cumple de X?» el modelo pide 366 días.

## Organizar el día: `huecos_libres` y `reservar_bloques`

«Organízame mañana: dos horas de TFG e ir al gimnasio» son dos pasos, y cada uno es una
herramienta con su lado de la frontera de confirmación:

- **`huecos_libres`** (consulta, `confirmar: False`, también en el MCP del teléfono como
  solo lectura): los tramos libres de UN día, Outlook y clases juntos, con sus minutos.
  Cada evento se ensancha `HUECOS_MARGEN_MIN` por los dos lados (salir de clase a las
  11:00 y tener «libre desde las 11:00» no es un plan), los solapados y los que se tocan
  se funden, y lo que viene de la noche anterior ocupa las primeras horas del día. Los
  eventos de todo el día **no bloquean**: salen aparte, en `todo_el_dia`, para que el
  modelo los mencione. Solo mira de hoy a dentro de `HUECOS_DIAS_MAX` (14) días, porque
  `get_events` no trae más de 30.
- **`reservar_bloques`** (acción, `confirmar: True`): varios bloques (máximo
  `RESERVAR_BLOQUES_MAX`, 6) en Outlook con un solo botón. La etiqueta del botón
  (`jarvisEtiquetaAccion`) pinta una línea por bloque sacada de los argumentos, y marca
  como «no se reservará» lo que no tenga forma válida. No está en el MCP del teléfono en
  ninguna de sus dos listas: es confirmable y allí se rechazaría siempre. Solo reserva
  hasta `HUECOS_DIAS_MAX` días, lo mismo que mira `huecos_libres`, y su descripción lo dice.

Lo que se repite **no** es cosa de `reservar_bloques`. «El pádel todos los viernes de 10
a 12 hasta año nuevo» es UN `crear_evento` con `repetir_hasta` (YYYY-MM-DD): una serie
semanal en Outlook (`recurrence` de Graph, `repeat_weekly_until` en
`POST /calendar/events`) que se repite el día de la semana de `fecha`, como mucho un año
(`REPETIR_DIAS_MAX`). Es una serie de verdad y no N eventos sueltos, porque se mueve o se
borra entera desde Outlook. El botón dice el día, las dos fechas y cuántas veces son
(«cada viernes del 23/10 al 25/12 (10 veces) de 10:00 a 12:00»): «hasta el 25/12» no
dice si se aprueban tres eventos o treinta. Nació el 2026-10-22: sin recurrencia, Jarvis
partió diez pádel en dos tandas de `reservar_bloques`, y las dos fallaron al pulsar por
el tope de 14 días.

**Lo que se rechazaría al pulsar se rechaza al proponer** (`_propuesta_invalida`, en el
bucle de OpenAI y en `/mcp/chat`). Para `crear_evento` y `reservar_bloques`, que se
pueden validar enteras sin salir a la red, se pasa la misma validación que la frase del
móvil (`_describir_accion`). Si falla, no queda nada pendiente y el modelo recibe el
motivo como fallo de la herramienta en el mismo turno, con la pista de `repetir_hasta`
si lo que falló fue el tope de días. Antes salía el botón y el «no» llegaba después del
«sí». Editar y borrar no entran porque validarlas es leer el evento de Graph.

Lo que no se puede relajar, y por qué:

- **Es UNA herramienta con una lista, no varios `crear_evento`.** El dashboard solo
  admite un pendiente por turno: el bucle corta en cuanto el modelo propone algo, así
  que tres `crear_evento` seguidos acababan en uno solo propuesto y los otros dos
  perdidos sin que nadie lo dijera. El prompt de sistema lo pide expresamente (huecos
  primero y UNA propuesta).
- **Al confirmar se vuelve a leer el calendario.** Entre que Jarvis propone y pulsas
  pueden pasar horas, y en ese rato puede entrar una reunión. Cada bloque se compara con
  lo que hay AHORA (solape estricto y **sin** margen: acabar a las 10:00 y empezar a las
  10:00 no es chocar, y el margen es para proponer, no para rechazar lo que tú has
  pedido). Esa misma lectura evita los duplicados: un bloque idéntico a un evento que ya
  existe (mismo título sin mirar mayúsculas y mismas horas) sale como «Ya estaba
  reservado», así que confirmar dos veces no crea dos.
- **No poder leer el calendario nunca es un día libre.** `_j_ocupados` no usa
  `_sin_error`: si Outlook falla o revienta, `huecos_libres` devuelve `ok: false` con la
  frase literal («…No te digo que tengas el día libre porque no lo he podido
  comprobar.») y **sin** clave `huecos`, y `reservar_bloques` no crea nada. La única
  excepción es que el calendario de clases no exista (`available` en el error): es
  configuración ausente y se sigue, pero con un aviso explícito de que los huecos no
  tienen en cuenta las clases.
- **No hay rollback.** Los bloques se crean en serie y en orden, reutilizando
  `_j_crear_evento`; si Graph falla en uno, los demás siguen. La respuesta dice
  cuáles entraron y cuáles no con su motivo (`_frase_reserva`, pensada para decirse en
  voz alta), y `ok` es verdadero si entró al menos uno. Deshacer a medias sería peor:
  un borrado que también puede fallar deja un estado que ya nadie sabe describir.
- **Los límites del día dicen de dónde salen** (`limites` en la respuesta). El inicio es
  `HUECOS_DIA_DESDE` (hoy, desde ahora redondeado al cuarto siguiente) y el fin, una
  hora antes de tu hora habitual de dormirte (`_hora_habitual_dormir()`, la misma
  mediana que usa la regla del madrugón), recortado a la medianoche; sin cinco noches
  medidas, `HUECOS_FIN_POR_DEFECTO`. Si pides horas concretas, mandan las tuyas y no se
  consulta el sueño.

`_regla_hueco_entreno` (el aviso proactivo de «mañana tienes libre de…») usa las mismas
dos piezas, `_j_ocupados` + `_huecos`. Tenía su propio cálculo: no miraba el calendario
de clases, no aplicaba margen, no veía lo que venía de la noche anterior y, como
`_eventos_con_fecha` devuelve `[]` cuando Outlook falla, **un Outlook caído le parecía un
día entero libre**. Ahora, sin calendario, se calla.

## Colores en el iPhone: `ordenar_calendario`

«Ordena mi calendario por colores» lleva cada evento a su calendario por tipo (Deporte,
Uni), que es lo único que el widget del iPhone sabe colorear. Cómo y por qué está en
«Calendarios por tipo» de `docs/BACKEND_PATRONES.md`; aquí, lo de Jarvis:

- **Solo se anuncia con `CALENDARIOS_POR_TIPO`** (`requiere_calendarios`), como las tareas
  o los cumpleaños: apagada no puede hacer nada.
- **`confirmar` depende del argumento.** `simular=true` es leer y va directa: devuelve
  `se_moverian` (en hora local, para enseñárselo) y `se_quedan` con su motivo.
  `simular=false` mueve, y eso se aprueba con el botón. La descripción le pide simular
  primero y proponer solo si dices que sí. No está en el MCP del teléfono ni en lo que se
  confirma en el móvil: cambia ids y calendarios, y se mira mejor en una pantalla.
- **Lo nuevo no necesita esto**: `crear_evento` y `reservar_bloques` ya crean cada evento
  en el calendario de su tipo.

## Preguntas al móvil: `mandar_notificacion` y `respuesta_notificacion`

Jarvis te puede mandar una notificación **ahora**, y si lleva opciones, contestarle con un
botón —igual que «Estoy despierto» / «5 min más» de la alarma—. Nació el 2026-10-11: el
teléfono sonó por un permiso de despliegue, Jarvis-Claude dijo «pulsa Desplegar en la
notificación que te acabo de mandar», y no había llegado nada. El teléfono hablaba de un
canal que no era suyo.

Tres herramientas, las tres directas y las tres también en el MCP del teléfono:

| Herramienta | Qué hace |
|---|---|
| `mandar_notificacion` | Manda la notificación al momento (`_notificar`, sin pasar por la cola). Con `opciones` («Sí\|No\|Luego», hasta 3) llega con un botón por opción y guarda la pregunta en `jarvis_preguntas` |
| `respuesta_notificacion` | Lo que has pulsado. Sin id, la última pregunta. Con `esperar` (hasta 20 s) se queda mirando hasta que pulses |
| `reenviar_permiso` | Vuelve a sacar al móvil la notificación del arreglo que espera permiso, con su botón «Desplegar». Para cuando dices «no me ha llegado» |

Las reglas que la sostienen:

- **Pulsar un botón no ejecuta nada: lo apunta.** Lo que se pregunta es texto libre que
  redacta un modelo, y un botón cuyo efecto decidiera un modelo sería una puerta trasera a
  la confirmación de todo lo demás. El botón deja escrita la respuesta y Jarvis hace con
  ella lo mismo que si se la dijeras hablando, con sus mismas fronteras. La primera
  respuesta es la que vale (PATCH condicional, `respuesta=is.null`).
- **Sin YAML nuevo en Home Assistant.** Los botones van por `LA_APAGAR_`, que ya está
  instalado: HA manda lo que va tras el último `_` a `POST /avisos/{id}/apagar`, y el
  prefijo `resp<n>-` delante del id le dice al backend que es la respuesta n a una
  pregunta. Mismo truco que el `posponer-` de la alarma. El acuse («🤖 Contestado: «Sí»»)
  es lo que te deja saber que el salto del móvil a HA no se ha perdido.
- **Nunca botones que no encuentran su pregunta.** Si no se puede guardar la pregunta
  (por ejemplo, la migración `20261011_jarvis_preguntas` sin aplicar), no se manda y la
  herramienta lo dice.
- **La herramienta dice por dónde salió** (`canal`). Si el móvil no recoge avisos va por
  correo, sin botones, y el correo dice cómo se contesta; Jarvis no puede decirte «púlsalo»
  en ese caso.
- **Tope: `PREGUNTAS_MAX_HORA` (6) por hora.** Un modelo en bucle con algo que hace
  vibrar el móvil es la forma más rápida de enseñarte a ignorar el canal.
- No pasa por el gobierno de avisos (presupuesto, silenciado): Jarvis te la manda porque
  estáis hablando, como un `recordarme` que pides tú.

## Lo que se confirma en el móvil: el calendario por teléfono

La excepción a «pulsar un botón no ejecuta nada», y por qué no la rompe. Nació de las
ideas que Jarvis apuntó en la llamada del 2026-10-12 («dale acceso al calendario para
crear eventos», «que mueva las citas si llego tarde»): por teléfono no había forma de
confirmar nada, así que el calendario solo se podía leer.

- **El modelo propone una acción, no escribe la pregunta.** `crear_evento`,
  `editar_evento` y las cuatro de más abajo (`PREGUNTAS_ACCIONES`) entran en el catálogo del
  teléfono, pero al llamarlas no se hacen: `_proponer_en_movil` guarda herramienta y
  argumentos en `jarvis_preguntas.accion` (solo los parámetros que la herramienta declara),
  **escribe el backend** la frase a partir de esos argumentos (`_describir_accion`:
  «Crear «Dentista» mañana de 10:00 a 11:00») y la manda al móvil con «Sí, hazlo» / «No».
  El «sí» ejecuta lo guardado (`_ejecutar_accion_guardada`): lo que lees es lo que se hace.
  Es el botón de confirmar del dashboard llevado al móvil.
- **Un «sí» dicho en voz alta no vale**: lo oye un modelo. Quien confirma es una persona
  pulsando algo que dice exactamente qué va a pasar.
- **Se valida antes de proponer** lo mismo que al ejecutar (fecha que existe, fecha y hora
  juntas para mover, el evento existe en Graph): un «sí» a algo que luego falla es un botón
  que miente.
- **Se vuelve a comprobar al ejecutar**: que la herramienta esté en `PREGUNTAS_ACCIONES`
  (la tabla se puede escribir con la service key) y que siga vigente:
  `PREGUNTA_ACCION_VIGENCIA_MIN` (30) desde que se propuso, o la `caduca` que traiga la
  acción («vas tarde» caduca al empezar la cita).
- **La primera respuesta vale** (PATCH condicional, como todas): dos toques no crean dos
  eventos. El resultado se escribe en `resultado`, y `respuesta_notificacion` devuelve
  `accion_hecha`: Jarvis no dice «hecho» hasta verlo. El acuse dice lo hecho en pasado
  («📅 Hecho: Movida a hoy, a las 10:00»), o por qué no.
- **Sin móvil no se manda**: por correo no hay botón, y sin botón no hay confirmación. La
  herramienta lo dice y remite al chat del dashboard.
- **Desde el 2026-10-15 entran cuatro más**, porque Mikel pidió «más permisos al Jarvis de
  la llamada, quitar eventos y tal»: `borrar_evento`, `reservar_bloques`, `crear_tarea` y
  `borrar_idea`. Las cuatro ya se confirmaban con botón en el chat. La frontera se movió
  de «crear o mover una cita como mucho» a «tu calendario, tus tareas y tus notas»: siguen
  fuera desplegar, mandar correos, cobrar y lanzar sesiones. Lo que cuida cada frase:
  - **Borrar un evento** dice cuál y cuándo, y si es una reunión tuya con invitados,
    que **les llegará la cancelación** (eso sale de casa). No es para siempre: Graph lo deja
    en Elementos eliminados de Outlook, y el acuse lo recuerda.
  - **Borrar una nota** sí es para siempre (no hay papelera), así que la frase lleva el
    texto de la nota (140 caracteres), no solo el título que le puso un modelo.
  - **Reservar bloques** se valida bloque a bloque como al ejecutar; si uno no vale, no
    se propone ninguno. Al pulsar vuelve a mirar choques, y el acuse dice cuáles entraron.
    `_args_de` guarda la lista como lista (antes lo pasaba todo por `str()`).
- Necesita la migración `20261013_preguntas_con_accion` (columnas `accion` y
  `resultado`). Sin ella, proponer falla y lo dice; las preguntas sin acción siguen igual
  porque la tabla se lee con `select=*`.

## El resumen, contado: `resumen_del_dia`

Los datos del correo de la mañana (`construir_brief`) para que Jarvis te los cuente
hablando, **solo cuando lo pides** («léeme el resumen», conduciendo): esa fue la condición
al aprobar la idea, así que no hay regla que lo dispare. Va sin la economía —titulares de
feeds de terceros, y la herramienta también está en el teléfono, que tiene shell al otro
lado— y sin las series de 30 días, que son para el correo.

## El briefing, leído: `leer_briefing`

El **briefing** no es lo anterior: es el correo «🌅 Buenos días Mikel — Briefing del
dd/mm/aaaa» que redacta y envía la rutina de Claude (`RUTINA_BRIEFING.md`), con noticias,
newsletters y la palabra del día. Desde el 2026-10-13 Jarvis lo lee cuando se lo pides
(«léeme el briefing», «la parte de IA»), por escrito y **por teléfono**.

- **Se busca en Enviados**, por el asunto exacto del día (`BRIEFING_ASUNTO` + la fecha),
  no en la bandeja de entrada: ahí solo está lo que salió de tu cuenta, así que un correo
  de fuera con el mismo asunto no puede colarse como briefing.
- **Sigue siendo texto de terceros resumido** (titulares, newsletters), y el teléfono
  tiene shell al otro lado: es justo lo que dejó la economía fuera de `resumen_del_dia`.
  Entra igualmente porque lo pediste expreso, con dos defensas: la procedencia de arriba
  y su aviso de dato (`_AVISO_BRIEFING`), como `leer_documento` y la web. Si algún día
  se quiere cerrar, basta con sacarla de `_MCP_SERVIDOR_SOLO_LECTURA`.
- **No depende de `CORREO_LEER`**: ese interruptor es para vigilar el buzón, y leer un
  correo concreto que se pide no es vigilar nada.
- Ronda las 3.000 palabras: la herramienta le dice a Jarvis que cuente las secciones y lo
  destacado, y lea entera la que pidas. Tope: `BRIEFING_MAX_CHARS`. Trae `secciones`
  (número y título), que son los números que entiende la lectura por teléfono.
- **Por teléfono, leerlo no lo hace Jarvis** (desde el 2026-10-15): claude-phone deja 40
  palabras por respuesta, y leía un trozo y preguntaba «¿sigo?». Ahora Jarvis pone la
  línea `📖 LEER: briefing` y la propia llamada pide `GET /telefono/briefing` (el texto ya
  preparado para la voz, por secciones y trozos) y lo lee de un tirón; se le puede cortar
  hablando. Parche 18 en `telefono/PARCHES.md`.
- Sin briefing ese día, lo dice (sale después del correo de datos, que espera a que te
  despiertes) en vez de leer el de ayer.

**El mismo día entraron en el teléfono** las que no tenían motivo para faltar: `tareas`,
`estado_resumen_diario`, `recordar`, `olvidar` y `dejar_de_vigilar`. Las que siguen
fuera lo están a propósito (ver el comentario sobre `_MCP_SERVIDOR_SOLO_LECTURA`).

**Desde el 2026-10-17 la llamada lee igual otras tres cosas** (parche 20,
`GET /telefono/lectura`): `📖 LEER: semana` (la agenda de siete días), `📖 LEER: correo`
(el último parte de la noche) y `📖 LEER: tareas`. El correo no tiene herramienta en el
teléfono a propósito (`turno_de_noche` trae asuntos y remitentes de desconocidos y al otro
lado hay una shell) y **no la necesita**: así, ese texto va del backend al altavoz sin
pasar por Claude, que solo sabe que se ha leído. Un Outlook caído no se lee como «no
tienes nada»: se dice que no se ha podido mirar.

## El «sí» dicho por teléfono

La excepción que faltaba en «Lo que se confirma en el móvil»: en el coche no se pulsa un
botón. Desde el 2026-10-17 (parche 20) lo propuesto por teléfono también se puede
confirmar de viva voz, y la regla de que **un «sí» dicho en voz alta no vale porque lo oye
un modelo** no se rompe, porque aquí no lo oye un modelo:

- Claude pone `✅ CONFIRMAR: <id>` (la propuesta le devuelve la línea hecha,
  `linea_para_la_llamada`) y se aparta. La **voice-app** pide `GET /telefono/confirmar/<id>`,
  lee la frase que escribió el backend (`_describir_accion`, la misma del botón) y decide
  ella si lo siguiente que dices es un sí o un no: lista cerrada, **la frase entera** («sí»,
  «vale», «hazlo»; el no gana), las mismas listas que `esConfirmacionHablada` del dashboard.
  Cualquier otra cosa («sí, pero a las once») va a Claude con la propuesta todavía
  pendiente en el móvil.
- `POST /telefono/confirmar/<id>` con **su propio token** (`TELEFONO_CONFIRMAR_TOKEN`, que
  vive en la voice-app y no en la configuración de Claude) responde exactamente como el
  botón (`_responder_pregunta`, PATCH condicional: la primera respuesta vale) y retira la
  notificación del móvil.
- **Solo lo reversible** (`PREGUNTAS_HABLADAS`): crear una cita, reservar bloques, apuntar
  una tarea y mover una cita tuya **sin invitados** (`_evento_graph` dice `organizo` y
  `asistentes`). Borrar algo, o mover una reunión con gente, sigue siendo solo botón.
- **Solo recién propuesto** (`PREGUNTA_HABLADA_SEG`, 180 s): es la respuesta a lo que se
  acaba de decir, no a una notificación de hace media hora.
- Lo que **no** protege: la sesión del teléfono tiene shell en `caja` y ya puede leer
  `backend.env` entero. El token aparte separa el camino normal; contra una sesión que se
  saltara el RUNBOOK no protege nada que no estuviera ya expuesto. La separación de verdad
  sería un Jarvis sin terminal para lo cotidiano (propuesta 4 del análisis del 2026-10-15),
  que no está hecha.

## Lo que ya está mirado al descolgar: `_contexto_de_voz`

Por voz, una pregunta con herramienta son tres pasos en serie (pedirla, ejecutarla y
redactar con el resultado), que es lo que separa los 1,7 s de los 9,7 s de
`docs/JARVIS_VOZ.md`. Y las preguntas de una llamada son casi siempre las mismas:
«¿qué tengo hoy?», «¿a qué hora es…?», «¿qué me queda pendiente?». Desde el 2026-10-15 el
backend se las da ya miradas, que es el truco del permiso de despliegue aplicado a lo
cotidiano:

- **Qué lleva**: lo que queda de hoy y lo de mañana en la agenda (Outlook y clases, hasta
  `CONTEXTO_VOZ_EVENTOS` por día, con lo que está en curso marcado), las tareas
  que vencen ya o mañana (si To Do está encendido) y los recordatorios hasta mañana. Por
  teléfono, además, dónde estás; el dashboard ya lo lleva en el prompt. **El tiempo no**:
  entró y se quitó el mismo día, porque no se pregunta y cada línea se paga en todos los
  turnos de voz; para eso está la herramienta `clima`.
- **Quién lo usa**: la llamada del dashboard y el Atajo (todo turno con `voz: true`), en
  el mismo mensaje de sistema que la hora, **al final**: cambia cada cinco minutos y no
  puede romper el caché del prefijo. Y el teléfono, que lo pide una vez al abrir cada
  llamada (`GET /telefono/contexto`, con el token del MCP del teléfono; parche 19 de
  `telefono/PARCHES.md`). Por escrito no va: ahí los segundos no se notan.
- **No poder mirar algo se dice.** La agenda no pasa por `_sin_error`: con Outlook caído
  el texto dice que no se ha podido mirar y que no diga que no tiene nada, igual que
  `_j_ocupados`. Cada parte va por separado, y una que revienta solo se cambia por su
  «no lo he podido mirar».
- **Dice de qué hora es** («a las 09:12»), y el modelo tiene la orden de ir a la
  herramienta para cualquier cosa que no esté ahí o necesite más detalle. Se guarda
  `CONTEXTO_VOZ_SEG` (300) en memoria: un turno de voz no paga Graph cada vez.
- **Coste**: unos cientos de tokens sin cachear por turno de voz. `JARVIS_VOZ_CONTEXTO=0`
  lo apaga en el dashboard y el Atajo; en el teléfono, sin el endpoint la llamada
  simplemente empieza sin él.

## Por qué te dije eso: la instantánea de cada aviso

La señal de utilidad (`avisos_reglas`, el botón «me sirvió / no me sirvió») dice **qué**
reglas se ignoran. No dice **por qué** fallan, y esa es la única información con la que
una regla mala se puede arreglar en vez de silenciarse. Hasta aquí un aviso era una frase
redactada por un modelo: cuando se equivocaba, no había forma de reconstruir de dónde
había salido, porque los datos que lo dispararon ya eran otros al día siguiente.

- `_apuntar_aviso(..., motivo={...})` acepta los **valores crudos** con los que se
  decidió: las medias contra las que se comparó, el listón, cuántos días de fondo había.
  Los números, no la frase — la frase ya está en el aviso.
- Se guardan en **`avisos_motivos`, una tabla aparte** (migración `20260903_avisos_motivo`)
  y no en una columna de `jarvis_recordatorios`. El motivo es el mismo que llevó a
  `informe_envios` a tener tabla propia, pero aquí es más grave: una columna nueva haría
  que el insert del aviso devolviera 400 mientras la migración no estuviera aplicada, o
  sea que **añadir una función de diagnóstico dejaría al sistema sin avisos**.
- Por lo mismo, `_guardar_motivo()` **solo registra sus fallos**: guardar el porqué nunca
  puede impedir el aviso. Se llama después de que el aviso ya esté apuntado.
- El aviso lleva ahora **siempre un `id` puesto por el backend** (antes lo generaba
  Supabase salvo en el del reloj). Sin conocerlo no hay de qué colgar la instantánea, y
  el insert va con `return=minimal`: pedir la fila de vuelta solo para leer el id
  costaría una respuesta en cada aviso.
- Se consulta con `GET /avisos/{id}/porque`, y los avisos del día con
  `GET /avisos/enviados?dia=AAAA-MM-DD` (ventana construida desde la medianoche **local**:
  la tabla guarda UTC y los avisos de la noche caerían en el día que no es). Los dos son
  endpoints de usuario: esto es para mirarlo, no para que lo consuma una automatización.
  Salen en el panel ⚙, bajo el bloque de avisos.
- Un aviso sin motivo guardado responde `motivo: null` con **200, no 404**: los avisos
  anteriores a esto no tienen explicación, y un 404 diría que el aviso no existe, que es
  otra cosa.

Reglas que ya lo rellenan: `salir` (la hora que dio Maps, el destino, la antelación),
`no_llegas` (las dos citas y la hora de salida), `madrugon` (tu hora habitual de dormir y
la recomendada), `malestar` (los tres pares semana/mes con su factor y su fondo),
`hueco_entreno` (días sin entrenar y el hueco encontrado) y el de salir de casa (qué
quedaba encendido y cuántas entidades tenía el catálogo — que distingue «no había nada
más» de «el catálogo llegó a medias»).

## Lo que cuesta: la contabilidad del modelo

Los números de más arriba (3.667 tokens de entrada, 94% cacheado) se midieron **una vez y
a mano**. Después entraron el streaming, las frases de relleno, el modo llamada y el
teléfono, cada uno con un patrón de gasto distinto, y la única alarma de coste que quedaba
era la factura. Ahora se mide solo (tabla `jarvis_gasto`, migración `20260903_gasto_modelo`):

- **Una fila por LLAMADA, no por turno.** Un turno con tres vueltas de herramientas y un
  relevo de modelo son cuatro llamadas de precios distintos; agregarlas antes de
  guardarlas perdería justo lo que se quiere mirar.
- **Se guardan tokens, no euros.** Las tarifas cambian y una cifra en euros escrita hoy
  sería mentira dentro de seis meses sin que nadie se entere. El precio vive en
  `MODELO_TARIFAS` y se aplica **al leer**, en `GET /gasto`.
- **Un modelo sin tarifa sale con `euros: null` y sus tokens contados**, y su nombre en
  `sin_tarifa`. No saber lo que cuesta algo no es que sea gratis, y un total que no
  incluye todo el gasto se marca como `euros_incompleto` en vez de callarlo.
- **`boca`** es por dónde entró la petición (`chat`, `voz`, `atajo`, `telefono`,
  `telegram`, `proactivo`, `correo`, `destilar`, `ideas`). Es una `contextvar` (`_boca_actual`), como
  `_peticion_actual` en el registro, porque el alternativa era pasarla por seis funciones
  que no pintan nada en esto. Es la pregunta que no se podía responder: **por dónde se va
  el dinero**.
- **Se apunta en memoria y lo escribe el hilo de fondo del registro**, que ya existía y
  ya resuelve el mismo problema (Fly duerme la máquina y se lleva lo encolado). Esto
  cuelga del camino crítico de la voz: una escritura a Supabase por llamada al modelo se
  oiría. Y un fallo apuntando el gasto **nunca toca la respuesta**: es contabilidad, no
  funcionalidad.
- **Por streaming el `usage` hay que pedirlo** (`stream_options: {include_usage: true}`):
  sin eso, el modo llamada —el que más gasta— sería justo el único que no se puede medir.
  Llega en un trozo final sin `choices`, que el bucle ya sabía saltarse.
- El **% cacheado** es la palanca de coste real: si se hunde, algo que cambia a menudo se
  ha colado delante del prompt. Sale en el panel ⚙ al lado del total.

