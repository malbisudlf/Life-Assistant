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
  `POST /ha/entidades`): el backend sigue sin poder llamar a HA, así que se usan los dos
  patrones que ya existen, cada uno para lo que sirve. Las **órdenes** van en una cola en
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
  modelo. El YAML de HA está en `docs/HOME_ASSISTANT_JARVIS.md`.

- **Recordatorios** (`recordarme`, `mis_recordatorios`, `cancelar_recordatorio`, tabla
  `jarvis_recordatorios`): lo único que hace que Jarvis hable sin que le hablen. Las tres
  decisiones son las que ya tomó el resumen diario, por lo mismo: viven en Supabase (Fly
  escala a cero), **el reloj es el tick de HA** (`/ha/brief-tick`, que por eso ya no es
  gratis antes de la hora tope: ~300 SELECT al día contra un índice) y **la reserva es un
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
  - **«No llegas»** (`_regla_no_llegas`): dos citas que no se solapan —así que Outlook las
    da por buenas— pero entre las que no da tiempo a moverse. Se avisa **la noche antes**,
    que es cuando todavía se puede mover algo.
  - **«Mañana empiezas pronto»** (`_regla_madrugon`): cruza el primer evento de mañana con
    tu hora habitual de dormirte (`_hora_habitual_dormir`, **mediana** de `sleep_start` —
    una noche en vela desplaza la media y no dice nada del hábito; y una hora de madrugada
    cuenta como "más tarde", no como dieciocho horas antes). Sin base, no habla.
  - **Firma de malestar** (`_regla_malestar`): las tres señales a la vez. Es el espejo en
    Python de `_firmaMalestar` de `helpers.js` — se acepta la duplicación a propósito
    porque las conclusiones no se portan al backend, y allí solo se ve abriendo el
    dashboard, que es justo lo que no vas a hacer el día que tu cuerpo dice que no.
  - **Hueco para entrenar** (`_regla_hueco_entreno`): la hora concreta libre de mañana.
    Sin histórico de entrenos no se regaña, la regla de siempre.
  - **Al salir de casa** (`_regla_al_salir_de_casa`): se dispara en `POST /ha/presencia` al
    CAMBIAR a fuera, no en el tick — es el único momento en que sirve. **No apaga nada
    por su cuenta**: el catálogo lo empuja HA cada hora y apagar con un dato viejo es
    peor que preguntar. El PC solo si `PC_ENTIDAD` está declarada: adivinar cuál es por
    el nombre acaba apagando otra cosa.
    Su notificación lleva un botón más, **«Apagar»** (`POST /avisos/{id}/apagar`), porque
    un aviso que te obliga a abrir la app para resolverlo no ha terminado el trabajo. Tres
    cosas de ese botón:
    - **Apaga lo que decía el aviso, no lo que hay ahora.** Los `entity_id` se guardan con
      el aviso (columna `entidades`, `20260830_avisos_entidades`) en el momento de
      apuntarlo. Releer el catálogo al pulsar apagaría cosas de las que el aviso no habló
      —llega con hasta una hora de retraso—, y un botón que apaga algo que no te dijo es
      peor que no tenerlo. La regla de "no apagar a ciegas" sigue intacta: ahora lo apagas
      tú.
    - **El PC se nombra pero no se apaga con él.** Cortarle la corriente a un `switch` no
      es apagar un PC, es tirar del cable; para eso está su propio aviso, que ofrece
      suspenderlo por SSH. Se excluye `PC_ENTIDAD` de la lista.
    - **Pulsarlo cuenta como «útil»**, y pasa por `_j_casa_ordenar` como cualquier otra
      orden de la casa: la lista viene de una fila de Supabase, que es escribible con la
      service key, así que tiene que pasar por la lista blanca de dominios y por el
      catálogo igual que si la hubiera pedido el modelo.
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

- **El correo entrante** (`_revisar_correo`, IMAP con la librería estándar): saca del buzón
  lo **accionable con fecha** y lo deja como aviso. **No es resumir el correo** — eso ya lo
  hace la rutina del briefing y hacerlo dos veces sería peor que no hacerlo. Es la
  capacidad más delicada en privacidad del proyecto, así que las restricciones van por
  delante y no como añadido: **apagada** sin `IMAP_HOST`; **solo cabeceras** (asunto,
  remitente, fecha) — el cuerpo no se lee ni viaja a ningún modelo, y lo que no se lee no
  se puede filtrar; **`BODY.PEEK`**, que no marca nada como leído (un asistente que te
  descoloca el buzón deja de usarse en una semana); y **no se guarda nada** en Supabase.
  Lo extraído se **propone como aviso**, nunca se crea en el calendario: lo que sale de un
  asunto interpretado por un modelo no tiene la fiabilidad para tocar la agenda sola, misma
  frontera que `sugerencia_evento()`.

- **Gobierno de los avisos** (`_apuntar_aviso`, el despacho de recordatorios, tabla
  `avisos_reglas` + columnas nuevas en `jarvis_recordatorios`): un asistente proactivo
  tiene **un solo modo de fallo, volverse ruido**, y no falla de golpe — falla porque cada
  regla parece razonable por separado hasta que un día se dejan de leer todos los avisos a
  la vez, buenos incluidos. Tres piezas, y las tres viven en la PUERTA y no en cada regla,
  para que una regla nueva las herede sin poder olvidarse (misma razón que el interruptor
  del resumen dentro de `enviar_brief_si_toca`):
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
    el mismo aviso.
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
  `arreglar_revision`): el issue que deja la revisión de madrugada llega al móvil por la
  mañana con dos botones —«Arreglarlo» y «No hacer nada»—, y el primero lanza otra sesión
  en la nube que lo arregla, abre PR y mergea si el CI pasa. Los botones los decide el
  backend (`_acciones_aviso`) y viajan **dentro del aviso**: HA solo sabe a qué móvil van.
  La decisión vive en Supabase porque entre el aviso y el toque pasan horas y Fly escala a
  cero, y se consume con un **PATCH condicional** para que dos toques no lancen dos
  agentes. El flujo entero, con las dos routines y el YAML, en `docs/REVISION_NOCTURNA.md`.

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

- **Vigilante del sistema** (`_vigilar_sistema()`, mismo tick de HA, tabla
  `vigilante_estado`): el de la ingesta mira UNA cosa —que sigan entrando datos de
  salud—; este mira si el sistema se rompe por cualquier otro sitio. `app_logs` y
  `diagnostico` ya guardaban la respuesta; lo que faltaba era **alguien que hiciera la
  pregunta sin que se lo pidan**, que es lo que convirtió las tres averías grandes en
  semanas de silencio. Tres reglas:
  - **El listón va en CÓDIGO.** Las reglas deciden SI hay avería (hoy: ≥
    `VIGILANTE_MIN_ERRORES` errores del mismo origen en la ventana, y el disparo de la
    rutina fallado); el modelo, si acaso, redacta. Misma frontera que
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


- **Jarvis se diagnostica** (`diagnostico`): fallos de `app_logs` agrupados por origen,
  estado del resumen diario, cuántos días lleva cada métrica sin dato, **quién escribió
  por última vez** (de `/health/diagnostico`, ventana corta: es una lectura de tabla) y
  qué integraciones están configuradas. Es la pregunta más frecuente que se le hace a un asistente que falla
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
  `proactivo`, `correo`, `destilar`, `ideas`). Es una `contextvar` (`_boca_actual`), como
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

