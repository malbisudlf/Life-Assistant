<!-- Parte de la guía del repositorio. El índice y las reglas que aplican
     SIEMPRE están en CLAUDE.md, en la raíz. -->

## Bugs históricos (no los reintroduzcas)

- **La cabecera desbordaba en el móvil, pero solo de noche (2026-09-27).** El E2E de
  móvil pasó a las 17:31 y falló a las 23:22 con un commit que solo tocaba docs: la
  página hacía scroll horizontal. El evento de prueba es «dentro de dos horas», y a esa
  hora cae ya mañana, así que la frase del momento pasa a ser «Mañana empiezas a las
  01:43 con…» y mide más que la pantalla. La elipsis de `.momento-frase` no actuaba porque
  `.header-momento` pasaba a columna en móvil **conservando el `flex-wrap: wrap`** de
  escritorio: una columna multilínea mide cada línea por su hijo más ancho, y el stretch
  estiraba la frase hasta su ancho entero.
  - Arreglo: `flex-wrap: nowrap` en la regla de móvil.
  - Moraleja: **un test que depende de la hora pilla lo que depende de la hora**. No es
    un flaky que haya que fijar, es cobertura que llegó sin buscarla: antes de «fijar el
    reloj» de un test que falla solo a ciertas horas, mira qué cambia a esas horas.

- **Gmail rechazó la contraseña y el correo de la mañana lo intentó cada cinco minutos
  todo el día (#244, 2026-09-27).** A la hora tope, `ha_brief_tick` montaba el correo
  entero —Graph, Supabase, clima, titulares— para fallar en el `login` con un 535, y
  volvía a empezar en el tick siguiente: nueve `SMTPAuthenticationError` en un día. El
  vigilante lo abrió como issue de «cambio de código», porque no sabía que un rechazo de
  credencial no lo arregla ninguna sesión. Y detrás había dos fallos más que no se veían
  porque el SMTP nunca había estado caído mucho rato: la hora tope **olvidaba la espera
  antes de intentar el envío** (si fallaba, el siguiente tick lo mandaba como «tope», sin
  hora de despertar), y la señal de despertar con la noche ya sincronizada **no dejaba
  nada que reintentar**: un fallo en ese minuto esperaba a las diez.
  - Arreglo: `_fallo_de_correo` distingue credencial, conexión y rechazo; tras un rechazo
    de credencial lo automático deja de intentarlo (`_correo_espera`, 30 min que se doblan
    hasta 4 h) y lo pedido a mano no espera. `_causa` añade el código SMTP. El vigilante
    trata los cortes SMTP como red y la credencial rechazada como una clase propia: aviso
    con el listón de código, sin issue ni botón. La espera se olvida solo cuando el envío
    fue definitivo, y la señal directa deja una apuntada si falla. Ver «Cuando el envío
    falla» en `docs/BRIEF.md`.
  - Moralejas: **reintentar solo lo que puede salir distinto**: un corte de conexión sí,
    una contraseña revocada no, y confundirlos es martillear la puerta que luego se cierra
    también a la buena. Y **no borres el estado antes de saber si la acción salió**:
    «olvidar y luego intentar» es correcto justo hasta el primer fallo.

- **Jarvis llamó a las 07:00 con Mikel dormido, y el buzón contó como cogida
  (2026-09-27).** La web estuvo caída de 03:30 a 11:33 (reinicio semanal de `caja`: túnel
  parado y contenedores sin DNS). El vigilante aplazó la llamada por la franja nocturna y
  a las 07:00:32, acabada la franja, llamó. El primer intento sonó 14 s y no se cogió; el
  segundo lo «contestó» a los 7,5 s el buzón (el móvil, en modo dormir, la rechazó y el
  3CX la desvió en el acto, sin llegar nunca un 603). claude-phone pasó a PLAYING, el TTS
  falló por el DNS, la sesión quedó en FAILED **sin colgar la línea**, y el buzón grabó
  silencio tres minutos. Para el backend la llamada estaba contestada: ni reintento ni
  recado, y la serie se cortó sin dejar una sola línea en el registro.
  - Arreglo: el teléfono solo suena cuando consta que estás despierto
    (`_telefono_puede_sonar` en `_llamar`, con la señal de despertar del resumen guardada
    aparte en `despertares`; sin señal, desde las 10:00; la franja fija queda de suelo).
    Y con el parche 12 de claude-phone, si descuelga el buzón se deja ahí el recado, una
    llamada en la que nadie habla cuenta como no cogida (salvo que descolgara una
    persona: callarse no es no cogerla), y descolgar sin voz ni insiste
    ni se calla: queda en ERROR. Ver «Solo cuando estás despierto» y «Contestar no es
    coger» en `docs/LLAMADAS.md`.
  - Moralejas: **«no es de noche» no es «estás despierto»**: una franja horaria es una
    suposición sobre la persona, y la señal de que se ha despertado ya existía. **Descolgar
    no es coger**: quien contesta puede ser un buzón, y lo que dice si fue una persona es
    que alguien hable. Y **todo error después de descolgar cuelga**: una línea que se
    queda abierta sin nadie hablando es peor que una llamada perdida, porque para quien
    la mira desde fuera está contestada.

- **Una barra invertida se saltaba el invariante 7 entero.** `alud_url_permitida` sacaba
  el host con `urlsplit(url).hostname`, que trata `\` como un carácter más del authority
  y se queda con lo que va detrás de la última `@`. Edge (parser WHATWG) trata `\` como
  `/`, así que para él el authority acaba en la barra. Con
  `https://atacante.example\@alud.deusto.es/...` la función veía alud.deusto.es y Edge
  abría atacante.example, con la sesión de Alud/Okta iniciada y Cowork esperando órdenes
  en esa pestaña. Y como las tres barreras (extraer en `/calendar/events`, dar de alta en
  `POST /jobs` y el agente) usaban la misma función, **se saltaban las tres a la vez**.
  - Arreglo: se rechaza cualquier `\`, espacio o carácter de control, el userinfo y todo
    netloc que no sea exactamente host[:puerto]; el host solo puede llevar `[a-z0-9.-]`.
    Un test exige que la copia del agente sea idéntica a la del backend.
  - Moraleja: **validar una URL con un parser que no es el que la va a abrir es validar
    otra URL.** Lo que decide no es qué host lee Python, sino qué host lee el navegador;
    y cuando no puedes preguntarle al navegador, rechaza todo lo que dos parsers puedan
    leer distinto. Tres barreras con la misma lógica son una sola barrera.

- **La huella de "Sal ya" recortaba el id de Graph.** `_regla_sal_ya` apuntaba cada aviso
  con la huella `salir:<los 60 primeros caracteres del id del evento>`, y `_ya_dicho` no
  deja repetir una huella en cinco días (`AVISOS_REPETIR_DIAS`). Los ids de Graph
  comparten unos 90 caracteres de prefijo —el buzón y la carpeta— y solo cambian al
  final, así que **todas las citas tenían la misma huella**: salía el «Sal ya» de la
  primera cita y el resto se callaba durante cinco días, sin un solo error en el
  registro. «No llegas» tenía el mismo fallo con 30 caracteres por cita, y todas las
  parejas del mismo buzón se callaban entre sí. Se veía como «a veces avisa y a veces
  no», que es lo que tiene un fallo que depende de cuál fue la primera cita de la semana.
  - Arreglo: `_id_evento_corto` (SHA-1 del id, 16 hex) y `_huella_salir`, que además
    lleva la hora de inicio: una cita movida vuelve a tener aviso, y el despachador puede
    comprobar al soltarlo que la cita sigue en pie (`_sigue_en_pie`, ver «Vigencia» en
    `docs/JARVIS.md`). Los «Sal ya» que ya estaban programados al desplegarlo llevan la
    huella vieja, que no casa con la nueva: pueden salir dos veces, una sola vez.
  - Moraleja: **un id opaco no se recorta, se resume con un hash.** Recortar supone que
    lo que distingue un id está al principio, y en los de Graph está al final. Un hash no
    supone nada sobre dónde está la diferencia. Y el test, con un id que tenga la forma
    real: los de antes usaban ids cortos de mentira (`"ev1"`) y no podían verlo.

- **Un estado que compartían dos caminos, y una reserva que valía para dos cosas.** El
  2026-09-27 salieron dos fallos con la misma forma. `pr-listo` pide permiso de despliegue
  para la fila más reciente en `arreglando`, y a ese estado llegaba también la revisión
  aprobada de día, cuya sesión mergea sola: se pedía permiso por un PR que ya se estaba
  mergeando, y la fila no salía nunca de ahí, así que atrapaba el siguiente PR verde de
  cualquier `arreglo/…`. Y el turno de noche usaba el INSERT del parte como «el turno ya
  corrió», pero el parte también lo abre el atajo del código: en invierno, si la revisión
  llegaba antes de las tres, esa noche no se miraba el buzón. Ver `docs/AVERIAS.md` y
  `docs/TURNO_NOCHE.md`.
  - Moraleja: **cuando un segundo camino reusa un estado o una reserva, pregunta qué más
    lee ese estado.** «Reusa entero el camino que ya existe» era verdad para quien
    escribía, no para quien leía.
  - **Y el arreglo de entonces no bastaba** (2026-09-28): sacar la revisión de
    `arreglando` quitó uno de los caminos que caían en la trampa, pero la trampa seguía
    siendo atar por orden. Esa noche dos arreglos de averías abrieron su PR en ramas
    `claude/…`, `pr-listo.yml` no los vio y sus filas se quedaron en `arreglando`; por la
    mañana el PR de la revisión se ató a una de ellas y el teléfono pidió permiso para
    algo que se mergeó solo medio minuto después. Hoy el id va dentro de la rama y
    `pr-listo` no adivina nada. Moraleja: **si dos mitades tienen que encontrarse, dales
    una referencia; «el más reciente» es una suposición sobre quién más escribe.**

- **Dos huellas que no eran la situación: una demasiado ancha y otra demasiado fina.**
  La regla del proyecto ya estaba escrita («la huella es la SITUACIÓN, no el texto») y
  dos avisos se la saltaban en direcciones opuestas. Las reglas tuyas usaban `clave:día`
  para todas las plantillas, y en `antes_de_evento` eso juntaba en una sola situación la
  clase de las 10:00 y la de las 16:00: la segunda se callaba. El correo entrante usaba
  la frase que redacta el modelo, así que el mismo correo sin leer, redactado distinto en
  la siguiente revisión, era otra situación y se avisaba otra vez. Hoy la primera va por
  evento y la segunda por el `internetMessageId` del correo.
  - Moraleja: **antes de escribir una huella, pregúntate qué cuenta como «lo mismo»**.
    Si puede pasar dos veces el mismo día, el día no la identifica; y si la escribe un
    modelo, no identifica nada.

- **El tick de alarmas pisaba el reloj que le acababan de adelantar.**
  `_alarma_marcar_pendiente` solo adelanta, justo para no saltarse lo que otro camino
  acaba de apuntar, pero el tick terminaba asignando `_alarma_siguiente` con las filas
  que había leído al empezar. Una alarma creada mientras corría el GET —o el rearme de
  una semanal que el propio tick acababa de rendir— se perdía del reloj; con otra alarma
  para dentro de días, no se volvía a consultar hasta entonces y la nueva acababa en «no
  pudo sonar». Ahora los apuntes quedan en `_alarma_apuntes` hasta que los ve la lectura
  de un tick posterior.
  - Moraleja: **una garantía de «solo adelanta» vale lo que el escritor que no la
    respeta.** Si un valor tiene una regla de escritura, todos los que lo escriben pasan
    por ella, también el que lo recalcula entero.

- **Tres defensas de seguridad que solo lo eran en serie, o en parte (2026-09-27).**
  - **El tope de cuerpo se había arreglado en un endpoint y el fallo vivía en todos.**
    Con `body: <Modelo>`, FastAPI lee y parsea el JSON entero antes de resolver las
    dependencias y de entrar en la función, así que ni `Depends(verify_token)` ni el
    `_token_ok(...)` de la primera línea llegaban a tiempo: sin token, 30 MB se cargaban
    en memoria y la respuesta era un 422. `/mcp/telefono` ya se había corregido por lo
    mismo —su docstring lo cuenta— y los 47 endpoints con modelo se quedaron
    igual. Hoy lo acota `_TopeDeCuerpo` para todas las rutas, antes de leer nada.
    Moraleja, la de «arreglar un botón no arregla el canal» en otra capa: **cuando un
    fallo sale de cómo funciona el framework, no está en el endpoint donde se notó.**
  - **El límite de login contaba, comparaba y apuntaba en tres viajes a Supabase sin
    nada que los serializara.** Una ráfaga de 40 peticiones leía el recuento antes de
    que se escribiera el primer fallo y las 40 llegaban a comparar la contraseña, con un
    límite de 5. Hoy `_login_lock` deja un login a la vez, y el que llega con otro en
    curso se lleva un 429 al momento: esperando en la cola, una ráfaga habría dejado
    bloqueados los hilos del pool y con ellos el resto del backend. Moraleja: **un
    límite que lee, decide y después escribe no limita nada bajo concurrencia**; los
    tests en serie no lo ven nunca.
  - **El filtro anti-SSRF preguntaba en negativo y se dejaba un rango.** `_ip_publica`
    rechazaba privada, loopback, link-local, reservada, multicast y sin especificar, y
    100.64.0.0/10 (CGNAT, la tailnet de Tailscale) no es ninguna de ellas. Hoy se exige
    `is_global`. Moraleja: **«solo lo público» se comprueba preguntando si es público**,
    no enumerando lo que no lo es. El DNS rebinding de ese mismo filtro sigue abierto
    (`docs/REVISION_2026_08.md` §2.1); el comentario ya no dice lo contrario.
- **El dashboard pintaba cada fallo del backend como otra cosa.** Una revisión de
  septiembre de 2026 encontró el mismo vicio en una decena de sitios de `Dashboard.jsx`:
  se miraba solo el camino bueno y cualquier otra respuesta se daba por buena o por
  vacía. Una caída de Graph (o el backend desplegándose) salía como «Conectar Outlook»,
  y además pegado hasta recargar, porque `authNeeded` solo se ponía a `true`; un 502 de
  `/alarmas` como «Ninguna puesta» con una alarma a las 7:00; uno de `/noche/parte` como
  «Todavía no hay ningún parte»; el 429 del login (global, lo agota cualquiera) como
  «Contraseña incorrecta»; el `{detail}` de un 502 de `/export` se **descargaba** con
  nombre de copia de seguridad; y las escrituras de entrenamiento e ideas cerraban el
  formulario o quitaban la fila aunque el backend dijera que no.
  - La raíz es de `apiFetch`: **solo trata el 401, no lanza con un 4xx ni con un 5xx.**
    Un `try/catch` alrededor no se entera de nada: hay que mirar `r.ok`. Y había borrados
    (`DELETE /ideas`, `DELETE /training/sessions`) que respondían 200 con `{ok: false}`,
    así que ni `r.ok` bastaba: `borradoConfirmado()`. Los dos pasaron después a 502 con
    `_supabase_error`, que además deja el detalle en el registro. Las frases viven en
    `src/lib/respuestas.js`.
  - En el calendario, lo que distingue sesión caducada de caída es el backend: marca con
    `reconectar: true` solo lo que se arregla reconectando (`_graph_fallo` con 401/403 y
    la falta de token).
  - Moraleja: **«no lo sé» y «no hay nada» son estados distintos y cada widget necesita
    los dos.** El comentario de `alarmas` ya lo decía («`null` mientras no se sabe») y el
    `catch` de debajo lo contradecía con un `previo || []`. Un estado de error va aparte
    (`alarmasError`, `{ error: true }`), nunca reciclando el valor que significa vacío. Y
    lo que se pone a `true` en un fallo se vuelve a poner a `false` en el acierto.
  - A la lectura del entrenamiento se le escapó a esa revisión: `loadTraining` guardaba
    el `{detail}` de un 502 como resumen, la tarjeta decía «Sin datos» (lo mismo que sin
    cliente) y, como se relee tras cada escritura, un 502 pasajero justo después de
    apuntar una sesión borraba un resumen bueno. **«Mejor esfuerzo: ignorar» significa
    quedarse con lo que había**, no sobrescribirlo con el cuerpo del error.
- **Tres estados que se quedaban desfasados con la página abierta**, de la misma
  revisión: el detalle del widget «Hoy» guardaba una COPIA del evento pulsado (tras
  editarlo seguía con la hora vieja, y el ✎ la volvía a escribir), la idea desplegada
  se guardaba por posición (las nuevas entran arriba y se desplegaba otra), y «El día»
  se quedaba en el día en que se abrió la página y amanecía titulado «ayer». Y en la
  llamada, cortar a Jarvis después del evento `fin` metía su respuesta DOS veces en el
  historial (`historialTrasCorte`).
  - Moraleja: **guarda el id, no el objeto ni el índice**, y deriva lo demás en cada
    render. Lo que se fija al montar («hoy») tiene que seguir al reloj, igual que ya lo
    hacían los derivados de salud con `diaActual`.

- **La hora tope no era «salgo con lo que haya»: era «renuncio a la noche de hoy».** El
  2026-09-22 la queja fue la de siempre por tercera vez, y esta vez el sistema había
  hecho todo lo que se le pidió. Te despiertas, abres Zepp, sincronizas varias veces; a
  los 45 minutos llega el aviso de que la noche no ha llegado; sincronizas otra vez y la
  noche aparece **en la app**; y aun así el correo que llega trae los datos de ayer.
  - **El agujero estaba detrás de la hora tope, no delante.** A las 10:00 el tick manda
    el resumen con lo que haya, que es la red de seguridad de siempre y está bien. Lo
    que nadie había mirado es lo que pasa DESPUÉS: la reserva de `brief_envios` queda
    puesta, así que cuando la noche entra a las 10:20 el envío que dispara la ingesta se
    encuentra el 409, contesta «el resumen de hoy ya se envió» y se retira **en
    silencio**. El correo del día se queda con la noche de ayer para siempre, y con él
    el briefing, que la rutina redacta a partir de ese correo. La noche de hoy no se
    mandaba nunca, ningún registro decía que faltara, y desde fuera parecía el mismo
    fallo de las otras dos veces.
  - **Y el aviso de los 45 minutos pedía lo que ya se había hecho.** Miraba el final de
    una cadena de cuatro tramos (pulsera → Zepp → app Salud → exportador → backend) y de
    ahí deducía el consejo para el primero. Abrir la app cinco veces no acerca el dato
    si lo que está parado es el exportador del móvil, y no hace falta si el exportador
    ya ha escrito desde que te levantaste sin traer la noche. Las dos cosas se
    distinguen con un dato que ya estaba guardado: la hora de la última escritura de la
    ingesta contra la hora de tu señal de despertar.
  - Arreglo: `_alcanzar_la_noche` manda la noche tardía en un correo corto aparte (no
    reenvía el resumen ni relanza la rutina: el briefing del día ya está escrito), y
    `_donde_esta_el_atasco` pone en el aviso la etapa concreta. Ver `docs/BRIEF.md`.
  - Moraleja doble. Una: **una red de seguridad que además cierra la puerta no es una
    red, es un plazo.** Si el sistema acepta salir con lo que haya, tiene que seguir
    aceptando lo que llegue después — si no, la tolerancia que se añadió para no
    quedarse sin correo es lo que te deja sin el dato. Dos: **un aviso que nombra el
    síntoma en vez de la causa envejece hasta ser ruido**, y este proyecto ya lo tenía
    escrito en el propio código («regañarte por no sincronizar algo ya sincronizado es
    como se deja de leer un aviso») aplicado solo al caso en que el dato ya estaba.

- **«Reconstruir» no reconstruía, y no lo decía.** Se mergean dos arreglos a `main`, se
  pulsa *Reconstruir* en el add-on, termina sin errores… y producción sigue corriendo el
  código de antes. La causa: el `RUN git clone` del `Dockerfile` del add-on es una
  instrucción que no cambia nunca, así que Docker reutilizaba la capa cacheada y no
  volvía a clonar. El add-on llevaba sirviendo el repositorio tal como estaba **el día
  que se construyó la imagen por primera vez**.
  - Lo que lo hizo invisible es que **el fallo no tiene síntoma**: la construcción no
    falla, el add-on arranca, el backend responde. Solo se nota si algo que acabas de
    arreglar sigue roto, y ahí lo natural es dudar del arreglo, no del despliegue.
  - Se descubrió por casualidad: un cambio de ingesta que debía dejar un aviso en
    `app_logs` no lo dejaba, y el volcado de logs es cada dos segundos, así que no había
    otra explicación posible.
  - Dos remedios, y hacen falta los dos. Un `ADD` de
    `api.github.com/repos/.../commits/main` justo antes del clone invalida la capa
    cuando —y solo cuando— hay commit nuevo. Y el SHA clonado se guarda en
    `/app/VERSION` y sale por `GET /`, porque *hasta entonces no existía ninguna forma
    de preguntarle al backend qué código estaba ejecutando*.

- **El correo de datos seguía saliendo antes de sincronizar la noche, después de
  arreglarlo.** El 2026-09-17, un día después del arreglo de abajo, la queja era la
  misma. Dos causas que el arreglo anterior había dejado en pie, y las dos venían de
  tratar como señal algo que no lo era:
  - **La llegada del sueño de hoy disparaba el correo por sí sola**, como deducción de
    "si la noche ha sincronizado es que estás despierto". Pero la pulsera vuelca una
    noche a medias si te despiertas un rato a las seis, la app la sincroniza de fondo,
    y el correo salía mientras seguías durmiendo. Ahora el sueño **solo cierra una
    espera** que abrió una señal de verdad: el cargador, la alarma de respaldo o
    decírselo a Jarvis. Sin señal, el correo espera a la hora tope.
  - **La espera vencía a los 45 minutos y el correo salía sin la noche**, o sea igual de
    cojo que antes, solo que más tarde. Ahora a los 45 minutos solo te avisa de que
    abras la app, y sigue esperando hasta que llegue o hasta la hora tope.
  - Moraleja: **una espera que se rinde antes que la red de seguridad no es una
    espera, es la misma prisa con retraso.** Si el sistema ya tenía una hora a la que
    aceptaba salir con lo que hubiera, la espera tiene que llegar hasta ahí.

- **Jarvis no hacía nada al decirle «estoy despierto» con la alarma sonando.** La única
  herramienta que la callaba era `cancelar_alarma`, que necesita el id (dos vueltas de
  herramienta, `mis_alarmas` antes) y que a una semanal la mata. Por voz y a las siete
  de la mañana el modelo o no llamaba a nada o se quedaba sin la alarma del lunes que
  viene. Ahora hay `estoy_despierto`, sin parámetros: calla lo que suene y cuenta como
  señal de despertar. Y `POST /despertar` (el cargador) hace lo mismo de paso, que es el
  segundo camino del botón que no cuesta nada en el camino feliz. Moraleja: **una
  herramienta que pide un dato que el usuario no tiene a esa hora es una herramienta que
  no existe.**

- **El briefing decía todas las mañanas que no habías llevado el reloj, y el reloj lo
  habías llevado.** Se notó por acumulación (2026-09-16): no era un día raro, era
  *todos* los días. Dos fallos encadenados, y el primero es el que no se veía venir.
  - **El correo lo disparaba una noche vieja.** `_avisar_sueno_recibido` aceptaba como
    señal de despertar que llegara sueño *de hoy o de ayer*, con el razonamiento de que
    el Atajo reenvía los últimos días en cada sync. Pero la noche se fecha **por el día
    en que te despiertas**, así que la de ayer no es nunca la de esta noche: lo único
    que esa tolerancia podía disparar era el reenvío de un dato que ya estaba guardado.
    Y eso es exactamente lo que hacía cada mañana. El 16/09 el reenvío mandó el correo a
    las 08:33:25 y el sueño de verdad llegó a las 08:38:37 — cinco minutos tarde, todos
    los días.
  - **Y cuando salía sin el sueño, afirmaba lo que no podía saber.** El reloj vuelca la
    noche a Salud **al abrir su app**, no al despertarte (entre cinco minutos y ocho
    horas después, según el día). Sin métricas nocturnas y con pasos del móvil,
    `_estado_reloj` devolvía `sin_reloj` y el correo escribía «Anoche: sin reloj». La
    rutina que redacta el briefing lo leía y lo repetía, con toda la razón.
  - Lo segundo es el error de siempre de este proyecto **por el otro lado**. La regla
    `sin_datos` existe justo para no confundir «no llegó nada» con «no pasó nada»… y
    estaba escrita solo para los días pasados. Para el día en curso faltaba, y ahí es
    donde más falta hacía. Hoy `anoche` vale `"si"` o `"pendiente"` y **nunca** `"no"`.
  - Moraleja doble. Una: **un dato que llega por su cuenta no llega cuando tú crees**,
    y si la lógica depende de que haya llegado, hay que preguntárselo a la base de datos
    en vez de deducirlo de que algo se ha movido. Dos: **una tolerancia que se añade
    "por si acaso" también es un camino de ejecución**, y esa en concreto solo podía
    dispararse en el caso equivocado — no ampliaba la ventana, la desplazaba.

- **Todas las noches decían haberse acostado a las 00:00, y el dashboard llamaba
  "anoche" al sueño de anteayer.** Dos fallos distintos que se tapaban el uno al otro
  y que salieron de la misma queja ("el sueño que veo no es el de hoy").
  - `sleep_start` salía de `date_raw[11:16]`, la hora del `date` de la muestra. Pero
    Health Auto Export **resume el sueño por días** y le pone a la muestra la medianoche
    del día al que la asigna, así que la hora era `00:00` en las 64 filas guardadas,
    con el Apple Watch y con la banda Zepp por igual. Y `00:00` no es un valor neutro:
    `sleepBreakdown` resta 5 puntos por acostarse pasada la medianoche (o sea, un
    impuesto fijo sobre todas las noches), la línea del día dibujaba el sueño empezando
    a las doce en punto, `bedtimeHrvInsight` comparaba "temprano" contra "tarde" con un
    solo valor, y la hora habitual de dormir de Jarvis —mediana de `sleep_start`, la que
    decide cuándo avisar de irse a la cama— era 00:00 pasara lo que pasara. La hora real
    venía en el mismo punto (`sleepStart`, `inBedStart`) desde el principio.
    *Un campo derivado que sale siempre igual no es una constante: es un campo roto.*
  - El widget pintaba `sleepAllData[último]` con la etiqueta fija "anoche". Cuando el
    reloj no había sincronizado todavía (pasa a diario: la fila del sueño llega horas
    después que HRV y respiración del mismo día), la última fila era de la noche
    anterior y se enseñaba como la de esta madrugada, sin ninguna pista. El score
    encima mezclaba: puntuaba esa noche vieja con la recuperación de HOY. Ahora la
    etiqueta cuenta las noches de desfase, avisa de que el dato de esta noche no ha
    llegado, y las métricas de recuperación se leen de la fecha de la noche puntuada.

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
- **Se renombró el PC y el relanzado, el apagado y la suspensión murieron sin avisar.**
  El 2026-09-25 se reinstaló Windows y el PC estrenó nombre. El Green seguía haciendo SSH
  al nombre mDNS de antes: nada resolvía, el `shell_command` fallaba dentro de HA y el
  dashboard seguía diciendo «enviado», porque lo único que hacía el backend era poner un
  flag en memoria. **Es la segunda vez que el SSH al PC muere en silencio por el
  destino**: la primera fue la IP fija que el DHCP reasignó, y por eso se pasó al nombre.
  Se arregló moviendo el mando a `caja` (fase 4 del HomeLab): el backend deja un pedido
  en `PC_DIR`, `pc.sh` prueba varios destinos por orden (`PC_HOSTS`) y **escribe cómo le
  ha ido** en `estado.json`, que el modal del streaming enseña (`GET /pc/estado`). Con el
  arreglo salieron otros dos del mismo camino: `abrirStreaming()` y la herramienta de
  Jarvis despertaban al agente ANTES de crear el job (con `caja` actuando en el acto, el
  agente podía mirar la cola vacía y cerrarse), y la de Jarvis ni siquiera lo despertaba.
  Moraleja: **una orden que sale de una máquina y se ejecuta en otra tiene que volver con
  su resultado**. Mientras «lo he pedido» y «se ha hecho» se pinten igual, cualquier cambio
  en el destino —una IP, un nombre, una clave— se descubre semanas después y a mano.
  Y el propio arreglo estuvo a punto de repetirlo: `GET /pc/estado` decía `motor: "caja"`
  solo porque `PC_DIR` estaba puesto, así que con el volumen sin montar (o de solo
  lectura) el pedido se caía al flag de HA y la pantalla pintaba «caja: trabajando en el
  pedido…» cinco minutos. Quien cuenta el estado tiene que usar el mismo criterio que
  quien hace la escritura, no uno más barato.
- **Con Edge ya abierto, `--remote-debugging-port` no abre ningún puerto.** El agente
  lanzaba Edge con ese flag y un puerto aleatorio, dormía cuatro segundos y se conectaba
  por CDP. Funcionaba — mientras el PC viniera de un WOL, porque entonces no había ningún
  Edge en marcha. Con el navegador ya abierto, el proceso nuevo **delega en la instancia
  existente y se cierra**: el puerto llegó a escuchar unos seis segundos y desapareció, y
  `connect_over_cdp` fallaba con un `ECONNREFUSED` que no dice nada de la causa. El
  puerto aleatorio lo hacía irreparable: aunque el Edge abierto tuviera depuración, cada
  arranque buscaba un número distinto. El arreglo, tras dos intentos, no fue afinar el CDP sino
  **quitarlo**: el agente abre la URL con `msedge.exe <url>` y deja que Claude lea la
  página. Controlar el navegador solo hacía falta para extraer el enunciado, y costaba
  todo esto. Moraleja de la primera parte:
  **un flag de línea de comandos de Chromium solo lo aplica la primera instancia**; las
  siguientes son mensajeros que le pasan la URL y se mueren.
- **`localhost` no es `127.0.0.1` en Windows.** La misma conexión CDP iba a
  `http://localhost:<puerto>`, y ese nombre resuelve primero a `::1` mientras Edge escucha
  solo en IPv4: `ECONNREFUSED ::1:49605` con el navegador perfectamente vivo. En un
  loopback, escribe siempre `127.0.0.1`.
- **«Apagar» no apagaba, y el WOL dejó de encender el PC.** El 2026-09-30 `caja` mandó
  el paquete mágico cuatro veces sin que el PC despertara, y cada relanzado posterior
  se quedó sin respuesta por SSH. `caja` no tenía nada roto: la MAC era la buena y el
  paquete salía. Lo que había cambiado era el PC. La reinstalación de Windows del día
  25 trajo el **Inicio rápido** activado de serie, así que «Apagar» desde el menú Inicio
  hibernaba el núcleo en vez de apagar. Los eventos lo dicen claro: 42/187 de
  `winlogon.exe` con `TargetState=6` (apagar) y `EffectiveState=5` (hibernar). Desde ese
  estado la Realtek no atiende el WOL: su «Shutdown Wake-On-Lan» solo vale para el
  apagado real. Se arregló con `HiberbootEnabled=0` (ver `agent/PUESTA_A_PUNTO.md`).
  Moraleja: **tras reinstalar Windows, vuelve a mirar todo lo que se configuró fuera del
  repositorio.** «Siempre ha funcionado» se refería a un Windows que ya no existía.
  **Y no bastó.** Al día siguiente el PC, apagado de verdad, seguía sin despertar. Una
  captura en el propio PC (`pktmon`, UDP 9) dijo cero paquetes y se culpó a la WiFi de
  `caja`, que está en la LAN por cable y por WiFi: la difusión no la decide la métrica,
  sino la tabla `local` de Linux, y salía solo por la WiFi. Se cambió `pc.sh`
  (repositorio HomeLab) para mandarlo atado a cada interfaz. Pero esa captura **no se
  había cerrado** (`BuffersWritten: 0` en su cabecera): repetida bien, llegaban los dos
  paquetes, el del cable y el de la WiFi. La WiFi no era la causa. Moraleja: **una
  prueba que dice «nada» tiene que demostrar antes que habría visto algo.** Una captura
  vacía, un log vacío o un test sin aserciones se parecen mucho a «no ha pasado nada».
- **Un `sleep` fijo esperando a que un servicio levante es un bug esperando su turno.**
  Los cuatro segundos que se dormían tras lanzar Edge bastaban en caliente y no en frío.
  Sustituido por espera activa contra el puerto, con límite.
- **Y la moraleja de fondo de esa tarde**: se persiguieron dos capas de síntomas (el
  puerto aleatorio, `localhost` contra `::1`) sin mirar antes **cómo estaba hecho antes**
  ni preguntar para qué servía la pieza que fallaba. El historial lo decía: hasta
  `e29d302` no había CDP, y el cambio se hizo por un motivo concreto y menor (que Edge
  sobreviviera al agente) que se resuelve con `DETACHED_PROCESS` a secas. `git log -S`
  sobre la línea que falla, antes de arreglarla.
- **El perfil por defecto de Edge no admite depuración remota, y no lo dice.** El remate
  de esa misma tarde. Tras dos intentos de arreglar el CDP (puerto fijo en vez de
  aleatorio, `127.0.0.1` en vez de `localhost`) el navegador seguía sin abrir el puerto —
  arrancando con el flag puesto, visible en su línea de comandos, sin un solo error.
  Chromium **desactiva la depuración remota cuando se usa el directorio de datos de
  usuario por defecto** (desde Chrome 136; aquí, Edge 152), para que ningún proceso local
  pueda vaciarle las cookies al navegador donde están todas las sesiones. Con un
  `--user-data-dir` propio el mismo comando sí abre el puerto. La moraleja no es el dato
  concreto sino el patrón: **cuando un flag no hace nada y no hay error, sospecha de una
  restricción deliberada antes que de tu forma de usarlo**, y compruébalo con el
  experimento mínimo que separa las dos hipótesis (aquí, el mismo comando con y sin
  `--user-data-dir`). Media noche de arreglos habría sobrado con hacerlo primero.
- **El atajo que deja de existir y no falla: `Ctrl+2` para ir a Cowork.** El agente lo
  usaba para saltar del chat a Cowork en Claude Desktop. La app lo retiró, y el síntoma
  no se parecía a un error: Claude se abría, la instrucción se pegaba y se enviaba, el
  log decía «Instrucción enviada a Cowork» — pero aterrizaba en el **chat normal**, que
  responde en vez de ponerse a trabajar. Un atajo que ya no existe no da error: la
  pulsación simplemente no hace nada. Hoy se llega con dos clics, porque cambiar de
  sección solo se puede con el ratón (anthropics/claude-code#18818) y la app es Electron,
  así que UI Automation tampoco ve el botón. Moraleja: **cuando un paso de automatización
  de UI depende de un atajo de otra aplicación, deja constancia de en qué versión
  funcionaba** — y si el resultado final no es el esperado, sospecha del paso que "no
  falla" antes que del que sí.
- **El secreto que solo existía en el portátil de quien desplegó.** `/finanzas/resumen`
  llevaba días devolviendo un 500 —ocho al día— y nadie se enteró: el widget se veía
  vacío y no hay nadie mirando `fly logs`. La causa,
  `FileNotFoundError: 'enable_banking_key.pem'`. La clave privada de Enable Banking está
  en `.gitignore` **porque es un secreto**, así que viaja en un `fly deploy` desde local
  (el `.pem` está en el contexto de build) y **no** en uno lanzado desde
  `deploy-backend.yml`, donde el repositorio no lo tiene. Un despliegue por el camino
  bueno la borró de producción sin decir nada. Tres moralejas, y la tercera es la que más
  se repite en este proyecto:
  - **Un secreto que solo existe en el disco de quien desplegó no existe.** Va en una
    variable (`ENABLE_BANKING_PRIVATE_KEY`), que es lo único que sobrevive a los dos
    caminos de despliegue.
  - **«Configurado» tiene que significar «esto puede funcionar».** Comprobar que la
    variable con la RUTA estaba escrita no comprueba nada: `_enable_banking_configurado()`
    mira ahora que la clave exista de verdad.
  - **Una fuente secundaria que puede lanzar tumba el endpoint entero.** El saldo de
    Revolut es un extra dentro de un endpoint que sirve la cartera de Indexa, y se llevó
    por delante la cartera —que funcionaba perfectamente— porque su excepción subía sin
    red. Al añadir una fuente dentro de una respuesta que ya sirve otra, envuélvela.
- **El permiso de despliegue que no caducaba nunca, y secuestró la pantalla de llamada.**
  Salió probando «avísame» el 4 de septiembre de 2026: se manda el aviso de prueba, llega
  al móvil con sus dos botones, se pulsa «Hablarlo»… y Jarvis descuelga diciendo «he
  detectado un fallo y ya lo he corregido, ¿quieres que lo despliegue?». No era un fallo
  del canal nuevo: era el orden funcionando. `GET /llamada/pendiente` anuncia **primero**
  el despliegue esperando permiso, porque es el que tiene trabajo parado, y había una fila
  en `listo` de la prueba del canal de averías de la víspera que nadie llegó a contestar.
  Dos caras del mismo descuido, y ninguna avisaba de sí misma:
  - **Un permiso sin contestar se quedaba pendiente para siempre**, así que ningún aviso
    de sesión llegaría a anunciarse nunca mientras esa fila siguiera ahí. Un camino nuevo
    que no funciona porque otro viejo no se cerró.
  - **Ofrecía desplegar un PR que ya no existía** (mergeado a mano por el medio). Decir
    que sí habría fallado contra la API de GitHub.
  Moraleja: **si le pones caducidad a lo que escribes, mira si la tiene lo que está al
  lado.** El aviso de sesión nació con TTL de 48 h el mismo día, y el permiso de
  despliegue —que es más peligroso— llevaba sin ninguna desde que se escribió; se diseñó
  mirando solo la pieza nueva. Hoy `DESPLIEGUE_TTL_HORAS` (48 h) se aplica **al leer**,
  igual que el del aviso: un permiso caducado no se cierra —nadie decidió nada, y eso es
  justo lo que interesa poder ver después—, simplemente deja de anunciarse. Y la segunda
  moraleja, más general: **esto no salía leyendo el código.** Salió a la primera al
  probarlo de punta a punta, que es lo que dice `docs/AVISAME.md` que hay que hacer antes
  de fiarse.
- **Los diez segundos mudos al final de cada respuesta hablada.** Reportado el 5 de
  septiembre de 2026: «desde que deja de hablar hasta que empieza a escucharme fácilmente
  pasan 10 segundos». No era el micrófono, ni Scribe, ni el barge-in — el sitio donde se
  buscó primero, porque el micro es lo que se había tocado la víspera. Era el backend:
  **la destilación de memoria corría antes de emitir el evento `fin`**. Colgaba de
  `_responder()`, «el punto único de salida del turno», puesta ahí a propósito *para que
  no haya que acordarse de llamarla en cada `return`* — una buena razón que resultó ser
  el sitio exacto donde más duele. Lo que hace: una llamada al modelo entera (400 tokens)
  más hasta cinco escrituras a Supabase.
  - **Por escrito no se nota y por eso duró.** Cuando eso corre, la respuesta ya está
    leída en la pantalla; el turno tarda más en cerrar y da igual. Hablando no: el modo
    llamada no vuelve a escuchar hasta que llega el `fin` (`escucharSiTocaYa` en
    Dashboard.jsx espera a que la cola de audio se vacíe **y** el turno cierre), así que
    ese trabajo se pagaba en silencio, con el micrófono cerrado, justo cuando ibas a
    contestar.
  - **Y era intermitente**, que es lo que lo hacía difícil de creer: hay un freno de 30
    minutos entre destilaciones y un mínimo de 6 turnos. Aparecía a mitad de una
    conversación larga y no volvía a aparecer, o aparecía en la primera respuesta después
    de un arranque en frío de Fly, porque el freno vive en memoria.
  - El arreglo es de orden, no de velocidad: `_jarvis_turno` envuelve ahora a
    `_jarvis_turno_bruto` y destila **después** de agotarlo. Sigue siendo síncrona y sigue
    sin ser un hilo — es el mismo generador continuando tras el último `yield`, y el
    consumidor ya mandó el `fin` al cliente antes de pedir el siguiente elemento.
  Moraleja: **el «punto único de salida» es el peor sitio para colgar trabajo que no
  forma parte de la respuesta.** Todo lo que se enganche ahí se cobra en la latencia
  percibida de cada turno, y lo hace en el único momento en que el usuario está esperando
  a poder hablar. Antes de colgar algo del cierre de un turno, pregunta si el cliente
  necesita ese trabajo para seguir; si no lo necesita, va después del `fin`. Y la
  segunda, para diagnosticar: **un fallo de latencia en la voz no tiene por qué estar en
  la voz.** Se buscó en el micrófono porque era lo último tocado; estaba a 2.000 líneas
  de allí, en un sitio que no menciona la voz por ninguna parte.
- **Jarvis se cargó el README por hacer él lo que tenía que encargar.** El 5 de
  septiembre de 2026, estrenando el encargo por voz, se le pidió lo más pequeño que se
  nos ocurrió —«añade hola al README»— justo para ver si llamaba a
  `encargar_a_una_sesion`. No la llamó: tiró del MCP de GitHub y ejecutó
  `create_or_update_file`. El resultado fue un commit directo a `main` (sin rama, sin PR,
  sin CI) que dejó el README en 9 líneas de las 231 que tenía. Tres fallos encadenados, y
  el tercero es el que hace daño:
  - **Eligió la herramienta equivocada** aunque el prompt de sistema ya decía, ese mismo
    día, que el código no lo toca él. Tenía delante dos caminos y el del MCP era más
    corto.
  - **Escribió en `main` sin pasar por nada.** Todo el proyecto está montado sobre que
    los cambios entran por rama y PR con el CI en verde; el MCP era un agujero lateral en
    esa regla que nadie había mirado, porque hasta entonces solo se había usado para leer
    issues.
  - **`create_or_update_file` reemplaza el fichero ENTERO.** No añade: sustituye por lo
    que le pases. Un «añade una línea» se convierte en «déjalo con lo que quepa en el
    argumento», y lo demás desaparece sin que nada falle. El commit se llamaba «Añadir
    hola al README» y borraba 222 líneas.
  Moraleja: **una regla que solo vive en el prompt es una sugerencia, no una garantía.**
  Si algo no debe poder pasar, el muro va en el código. Hoy `_j_mcp_usar` rechaza sobre
  `JARVIS_REPO` toda herramienta que no empiece por un prefijo de lectura conocido
  (`get_`, `list_`, `search_`, `read_`, `download_`), y el mensaje de error dice cuál es
  el camino bueno. Es lista BLANCA de lectura y no lista negra de verbos a propósito: el
  día que el servidor estrene `replace_file_contents`, una lista negra lo dejaría pasar.
  Y la segunda, sobre herramientas ajenas: **antes de dejar que un modelo llame a algo,
  mira qué hace la herramienta con lo que NO le pasas.** Aquí lo que no se pasaba se
  borraba.

- **«Estoy despierto» no despertaba a nadie: el botón de la alarma se pulsaba y no pasaba
  nada.** El 2026-09-14 sonó la alarma de respaldo, se pulsó el botón de la notificación
  y la casa siguió insistiendo; hubo que entrar al dashboard a confirmar a mano. En el
  backend no había ni un error: el aviso salió a las 06:00, la escalada se ejecutó a las
  06:03 y el único `POST /alarmas/{id}/despierto` del día llegó desde el túnel de
  Cloudflare —el dashboard— dos horas después.
  - La causa es el tramo que **nadie registra**: iPhone → Home Assistant. La app
    companion no llegó a entregar el evento `mobile_app_notification_action`, y ese fallo
    no deja huella en ninguna parte. Ni el móvil avisa ni el backend se entera: para él
    seguías dormido, que es exactamente lo que hace que la alarma siga sonando.
  - Todo lo demás estaba bien, y comprobarlo fue lo que señaló al culpable: lanzando el
    evento a mano en HA (`POST /api/events/mobile_app_notification_action`) la
    automatización se disparó y el backend contestó 200 al primer intento. La única
    huella del fallo era `last_triggered` de `automation.life_assistant_alarma_estoy_despierto`:
    tres días atrás, cuando el botón se había pulsado por última vez con éxito.
  - Moraleja: **un botón cuya confirmación viaja por un solo camino de cuatro saltos no
    es un botón, es una apuesta** — y menos aún si el salto más frágil es el único que no
    escribe en ningún log.
  - **Y el arreglo duró un día, por pasarse de listo** (2026-09-15). El segundo camino fue
    un `uri` en el propio botón: pulsarlo abría el dashboard con `?despierto=<id>` y el
    dashboard confirmaba sin pasar por Home Assistant. Redundante de verdad, y aun así
    peor que el fallo — porque el que falla es el caso raro y la web se abría **todas** las
    mañanas, para apagar un despertador, medio dormido. De paso, el acuse de recibo
    («alarma confirmada») acababa a menudo en el buzón en vez de en el móvil: se manda por
    `_notificar`, que se cae al correo cuando HA no está sondeando — justo la situación en
    la que hacía falta el segundo camino. Un correo de «hecho» leído horas después no
    confirma nada.
  - Moraleja de la moraleja, que es la que vale: **la redundancia no puede cobrarse en el
    camino feliz.** Si el arreglo de un fallo que pasa una vez al mes añade un paso a las
    treinta veces que la cosa funciona, el arreglo es el fallo nuevo. Lo que quedó en su
    sitio: el botón vuelve a ser un `action` a secas y el backend contesta con otra
    notificación efímera («⏰ Alarma quitada»), que no arregla el salto frágil pero lo hace
    **visible** — que era lo único que faltaba aquel día. Y un acuse de recibo va al móvil
    o no va: por correo no es un acuse, es un recordatorio de algo que ya no se puede
    contestar.

- **El mismo día y el mismo fallo en «Arreglarlo»: el aviso del vigilante llegaba y
  pulsarlo no lanzaba ninguna sesión.** El 2026-09-14, horas después de lo anterior, llegó
  el aviso de «N errores en las últimas 24 h» con sus dos botones; al pulsar «Arreglarlo»
  no pasó nada. En `revision_hallazgos`, las **cinco** decisiones de ese día seguían en
  `pendiente` con `decidido_at` a null: el `POST /revision/{id}/accion` no llegó a hacerse
  ni una vez. El endpoint estaba bien (probado a mano con el `ha_poll_token` del Green:
  200), el YAML estaba bien y la automatización estaba bien.
  - Misma causa y mismo tramo mudo que el botón de la alarma. Lo que enseña este segundo
    caso es que **arreglar un botón no arregla el canal**: el fallo nunca fue de las
    alarmas, era de *todos* los botones que vuelven por Home Assistant, y el arreglo se
    aplicó solo donde se había notado. Al añadir un botón nuevo, la pregunta no es si el
    YAML casa con el prefijo, es por dónde vuelve — y si vuelve por un solo sitio, ya
    está roto.
  - De paso se vio lo otro: con dos botones, «arreglar» o «no hacer nada» es una decisión
    **a ciegas**, porque en una notificación cabe cuántos errores hay pero no cuáles. De
    ahí el tercer botón, «Hablarlo», y que Jarvis lea el issue entero al descolgar.

- **La alarma no encendió ni una luz, y el ritual de Home Assistant estaba perfecto.** El
  2026-09-17 la alarma de las 08:30 no encendió las luces, no puso música y no habló. El
  ritual de HA era el sospechoso natural —se acababa de reescribir para que las luces
  fueran primero y ningún paso de Alexa se llevara el resto— pero la automatización **ni
  siquiera se disparó**: `sensor.life_assistant_alarma` estuvo a `0` toda la mañana. El
  backend sí había escalado; lo que no hizo fue decírselo a la casa, porque
  `_alarma_en_casa()` leyó la presencia y decía `not_home`.
  - Y la presencia decía `not_home` porque el `device_tracker` del iPhone llevaba **desde
    el día anterior a las 09:24 sin reportar**, clavado en unas coordenadas a 26 km de
    casa. El backend tiene una defensa justo para esto —`presencia_vigente()` caduca el
    dato a los `PRESENCE_TTL_MINUTES`— y no sirvió de nada: la automatización
    `Life Assistant - Presencia` reenvía el estado del tracker **cada 15 minutos**, así
    que el `updated_at` se renovaba solo y el dato caducado se presentaba siempre recién
    hecho.
  - Moraleja: **una marca de tiempo solo caduca lo que la pone, no lo que la cuenta.** Un
    TTL sobre la hora en que un dato se *copió* no dice nada de la hora en que se
    *midió*; si el copiador corre en bucle, el TTL no se dispara nunca. Cuando un dato
    pasa por dos manos, la que hay que vigilar es la primera.
  - Corolario para depurar: antes de acusar al último tramo (aquí, el ritual de HA),
    comprueba que el tramo llegó a pedirse. `last_triggered` de la automatización y el
    historial del sensor lo dicen en diez segundos, y ahorran reescribir algo que
    funcionaba.

- **«Hablarlo» descolgaba hablando de otra cosa, y la caducidad solo tapó la mitad.**
  Segunda parte de *«El permiso de despliegue que no caducaba nunca»*, más arriba. Aquel
  día se arregló poniéndole `DESPLIEGUE_TTL_HORAS` al permiso, y con eso el síntoma dejó
  de verse — porque la fila culpable ya estaba caducada. Dentro de esas 48 h seguía
  pasando exactamente igual: pulsabas «Hablarlo» sobre un issue de la revisión, descolgabas
  y Jarvis contestaba que no había ningún issue. Eran **tres agujeros en el mismo camino**,
  y ninguno se veía desde el otro:
  - **De los cuatro botones «Hablarlo», solo el de la revisión llevaba el id.** Los del
    despliegue y el aviso de sesión abrían `?llamada=1` a secas, así que el id se quedaba
    en la notificación y el backend no tenía más remedio que resolver «lo más reciente».
  - **El id que sí viajaba se paraba en la pantalla.** El dashboard se lo daba a
    `GET /llamada/pendiente` —que por eso anunciaba bien al descolgar— y **no** al cuerpo
    de `/jarvis`. El prompt lo resolvía otra vez por su cuenta.
  - **Y el contexto de la revisión vivía en el último `else` de una cadena `if/elif/else`**
    ordenada por prioridad. Con un permiso de despliegue vivo, ese `else` no se alcanzaba
    nunca. Jarvis decía que no había ningún issue y tenía razón: con lo que le habían dado,
    no lo había.
  Hoy el motivo viaja como `aviso` + `tipo` desde el botón hasta el prompt, en cada turno,
  y manda sobre el orden; el orden solo decide cuando no se sabe por qué se ha descolgado.
  Hizo falta `tipo` porque un UUID a secas es ambiguo: los permisos y las decisiones son la
  misma tabla con distinto `estado`, y los avisos de sesión son otra — que es justo por lo
  que los otros dos botones nunca llegaron a llevar id.
  - Moraleja, y ya es la segunda vez que este fichero la escribe: **arreglar un botón no
    arregla el canal.** El `&aviso=` se añadió donde se había notado el problema y los
    otros dos se quedaron atrás, igual que pasó con los botones que vuelven por HA.
  - Y la de fondo: **una caducidad que hace desaparecer el síntoma no es un arreglo, es un
    temporizador.** Si lo que falla es un orden de prioridades, acortar la vida de lo que
    va primero solo cambia cada cuánto duele. Cuando un arreglo consiste en que algo deje
    de existir antes, pregúntate qué pasa mientras todavía existe.

- **El sueño se guardaba y el dashboard no lo enseñaba: Supabase corta a 1.000 filas.**
  Durante tres días (desde el 2026-09-20) la noche llegaba, la ingesta respondía 200 y la
  fila estaba en `health_metrics`, pero el widget seguía con la noche de hace tres días,
  por mucho que se sincronizara y se lanzara el Atajo. `/health/metrics` pedía
  `limit=5000` en orden **ascendente**, y PostgREST no sube de su `db-max-rows` (1.000 en
  Supabase) por mucho `limit` que se le pida: lo ignora sin avisar. Mientras los 30 días
  cabían en 1.000 filas no pasaba nada; al darse de alta métricas nuevas (energía basal,
  oxígeno, temperatura, horas en casa) se pasó el tope, y lo que se quedaba fuera era
  justo **lo más nuevo**. Lo mismo le pasaba al resumen diario, al informe semanal, a
  `/health/diagnostico`, al aviso de reloj y a la lectura previa de la ingesta (esta
  última, con un export de 30 días, dejaba de proteger los totales de las acumulativas).
  Hoy todas pasan por `_leer_todas()`, que pagina con `count=exact` y un orden que no
  empata (`metric_date,metric_name`).
  - Moraleja: **un `limit` alto en una URL de Supabase no es una garantía, es un deseo.**
    La copia de seguridad ya paginaba por esto mismo (`scripts/copia_supabase.py`) y nadie
    lo trasladó al backend. Cualquier lectura que pueda pasar de 1.000 filas va por
    `_leer_todas()`.
  - Y la de siempre con los datos que faltan: **si falta lo más reciente y la ingesta dice
    200, mira la lectura antes que el teléfono.**

- **Los workflows que avisan al backend se fiaban de quien los disparaba.** La revisión
  del 2026-09-27 encontró dos puertas abiertas en `.github/workflows/`, las dos por la
  misma razón: el filtro miraba el QUÉ y no el QUIÉN.
  - `revision-aviso.yml` solo miraba el título del issue. El repositorio es público: un
    desconocido que abriera «Revisión nocturna — …» mandaba al móvil un aviso idéntico al
    de verdad, con el botón «Arreglarlo» que mergea sin segunda pregunta, y con el turno
    de noche encendido lanzaba el arreglo sin preguntar a nadie. Hoy exige que el issue
    lo abra el dueño del repositorio, y la skill `arreglar-revision` se niega a trabajar
    con uno que no lo sea.
  - `ci-averiado.yml` confiaba en `branches: [main]`, que en `workflow_run` se compara con
    la rama de ORIGEN del run: un PR desde el `main` de un fork la pasa. Hoy descarta los
    runs de PR y los de otro repositorio.
  - Moraleja: **en un workflow que corre con los secrets del repositorio, lo que llega en
    el evento lo ha escrito alguien, y en un repositorio público ese alguien puede ser
    cualquiera.** Filtra por autor o por repositorio, no por el nombre de lo que llega.

- **Un error de Supabase leído como «no hay nada» acaba guardado como dato.** Cobrar un
  entrenamiento leía el último cobro y las sesiones pendientes con
  `r.json() if r.status_code < 300 else []`, e insertaba el cobro igual. Con un 503 en las
  sesiones se guardaba un cobro de **0 €**; con un 503 en los cobros desaparecía el filtro
  por fecha y se cobraba **el histórico entero**. Las dos respuestas salían con `ok: true`,
  Jarvis decía «cobrado», y ese cobro falso pasaba a ser el corte del pendiente, sin
  endpoint para deshacerlo. Mismo patrón en `save_idea` (devolvía el payload local sin id:
  «guardada», y al recargar no existía; hoy `/ideas/audio` devuelve la transcripción en
  el error y el dashboard la deja en el formulario de texto para reintentar, porque un
  error que el cliente se traga no salva ninguna nota), en `delete_idea` (un `{"ok": false}` en un 200
  que Jarvis no miraba) y en `_buzon_yo`, que guardaba en la caché la cadena vacía de un
  fallo pasajero y dejaba la regla del «voy en copia» apagada hasta el siguiente
  despliegue. Hoy todos cortan con `_supabase_error` o no cachean el fallo.
  - Moraleja: **una lectura que falla no es una lectura vacía.** Y menos antes de
    escribir: si lo que se va a guardar se calcula con lo leído, un fallo leído como `[]`
    se convierte en un dato falso con cara de verdadero. El invariante 5 de `CLAUDE.md`
    ya lo decía; los sitios que no lo cumplían eran los que nadie había visto fallar.

- **Graph rechaza un `$filter` cuyo primer campo no es el del `$orderby`.** El buzón pedía
  `isRead eq false and receivedDateTime ge …` con `$orderby=receivedDateTime desc`, y Graph
  exige que lo que ordena aparezca en el filtro **y delante** de lo demás; si no, 400
  `InefficientFilter`, que desde #199 es `BuzonCaido`: ni avisos de correo de día ni buzón
  en el turno de noche. Los tests no podían verlo porque el simulador acepta cualquier URL.
  Hoy el filtro empieza por `receivedDateTime` y un test mira la URL.
  - Moraleja: **un simulador que acepta cualquier petición no prueba la petición.** Con
    APIs de terceros que ponen reglas a la forma de la consulta, el test tiene que mirar
    la URL, no solo lo que se hace con la respuesta.

- **Cortar a Jarvis mataba la voz de Azure y la frase cortada salía por el navegador.**
  `callar()` abortaba la petición en vuelo a `/voz/decir`, y el `catch` de `siguiente()`
  solo se callaba el rechazo si la voz estaba `cerrado || muerto`. Callar no es ninguna de
  las dos, así que el abort de un barge-in se tomaba por una caída de Azure: `rendirse`
  devolvía la frase a `caerAlNavegador`, que la decía con `speechSynthesis` justo después
  de cortarle, y el resto de la llamada seguía con esa voz. El comentario del `catch`
  aseguraba que ese caso estaba cubierto; la condición de debajo no lo cubría. Y con la
  decodificación a medias, la frase cortada sonaba igual después del corte. El test solo
  llamaba a `callar()` con el audio ya sonando, que es justo el caso que no fallaba.
  Hoy cada `callar()` abre una generación nueva, y lo que vuelve de un `await` con una
  generación vieja se va sin tocar nada.
  - Moraleja: **después de cada `await`, pregúntate si el mundo que había antes sigue
    existiendo.** Un par de banderas de estado (`cerrado`, `muerto`) no dicen si alguien
    ha cortado entre medias; un número de turno sí.

- **El troceado de la voz partía las URLs antes de que nadie pudiera quitarlas.** El
  modo llamada trocea el texto crudo y `textoParaVoz` limpia cada trozo después. Como
  `.` y `:` eran corte sin mirar lo que venía detrás, «https://elpais.com/…» llegaba a la
  limpieza como «https:» y «//elpais.com/…», que ya no parecía una URL: se leía entera.
  Igual con «10:30» o «23.5 grados», dichos como dos frases. Hoy un signo solo corta si
  lo sigue un espacio, y si es lo último del buffer se espera al siguiente delta.
  Esa espera tuvo su propio fallo: cuando el modelo escribe una frase antes de pedir una
  herramienta («Déjame mirar el calendario.»), el punto queda al final y el siguiente
  texto no llega hasta que la herramienta acaba, y encima sin espacio delante («Tienes…»).
  La frase sonaba detrás del relleno y pegada a la respuesta. Por eso el evento
  `herramienta` vacía el buffer antes del relleno, y un signo fuerte corta también si lo
  sigue una mayúscula o «¿»/«¡» (dominios, horas y decimales llevan minúscula o dígito).
  - Moraleja: **una red de seguridad que va detrás de un paso que rompe su entrada no es
    una red.** Cuando una limpieza reconoce patrones, lo que corre antes no puede partirlos.

- **La línea de ⚙ y la zona dev leían el estado del sistema con dos listas.** Como
  `Dashboard.jsx` no puede importar `src/lib/dev.js` de forma estática (chunk principal),
  `cargarEstadoSistema` copiaba a mano las consultas de `leerEstadoSistema`. La copia
  no guardaba `brief`, así que la fila «Resumen diario» salía siempre «sin comprobar» en
  ⚙: con el correo pausado, la zona dev lo pintaba en ámbar y ⚙ decía «todo responde».
  Hoy `leerEstadoSistema` vive en `src/lib/estadoSistema.js` (ligero, como
  `registro.js`) y los dos lados la llaman.
  - Moraleja: **compartir la función que decide no basta si cada lado junta sus datos
    por su cuenta.** Cuando la regla del chunk impide importar un módulo, se saca a un
    módulo ligero lo que hace falta, no se copia.

- **Un endpoint `async` que llama a algo síncrono congela el backend entero.**
  `/ideas/audio`, `/health/ingest` y `/health/ingest/simple` son `async def` solo para
  leer el cuerpo acotado (`_leer_cuerpo_limitado`, `audio.read`), y después llamaban a
  Whisper, al modelo y a Supabase —todo síncrono— dentro del bucle de eventos. Con un
  solo worker de uvicorn, mientras Whisper transcribía o Supabase tardaba sus 15 s no se
  atendía ninguna otra petición: ni el tick de HA, ni n8n, ni el dashboard. Ya se había
  arreglado en `/mcp/telefono` y nadie buscó el mismo patrón en los demás. Hoy lo que
  sigue a la lectura va en `asyncio.to_thread`. Y el SDK de OpenAI, la única salida que
  no pasa por `http`, esperaba 600 s con dos reintentos: un OpenAI colgado dejaba el
  chat, una nota de voz o una llamada callados media hora (`OPENAI_TIMEOUT`).
  - Moraleja: **en un `async def`, todo lo que no lleva `await` delante bloquea a todos.**
    Si un endpoint es `async` solo por leer el cuerpo, lo demás va a un hilo; y al
    arreglar un patrón en un sitio, búscalo en el resto. Cada cliente saliente necesita
    además su propio tope, no el que traiga la librería.

- **La alarma del E2E salía «hoy» de madrugada, y en invierno habría salido a las 07:30.**
  El simulador la ponía en «`_dia(1)` a las 06:30 UTC»: mañana contado en UTC y una hora
  que solo son las 08:30 en Madrid con horario de verano. El backend la pasa a
  `Europe/Madrid` y el widget compara el día con el reloj del navegador, que va en la zona
  de la máquina. En CI (UTC) siempre salía «mañana»; en local, entre las 00:00 y las 02:00,
  el mañana UTC ya era hoy y el test fallaba. Y desde el 25 de octubre habría fallado
  siempre, CI incluido. Hoy el simulador calcula «mañana a las 08:30» en la zona del
  usuario (`_manana_a_las`) y `playwright.config.js` fija la misma zona para el navegador
  (`timezoneId`) y para el backend de pruebas (`TIMEZONE`). Hacían falta las dos cosas:
  arreglar solo el simulador mudaba el fallo a CI.
  - Moraleja: **un dato de prueba con fecha se escribe en el reloj de quien lo lee.** Si el
    test habla de «mañana a las 8:30», el fixture tiene que decir eso mismo en esa zona, no
    su traducción a UTC del día que se escribió.

- **Las alarmas no entraban en la copia de seguridad, y nadie lo había decidido.** La
  copia solo pregunta por lo que está en `TABLAS`, así que una tabla nueva que no se
  añadía ahí ni se copiaba ni salía como ausente en el volcado: el hueco no se veía por
  ninguna parte. Así se quedó fuera `alarmas`, cuyas semanales se escriben a mano como un
  recordatorio. Hoy las tablas que no se copian están en `SIN_COPIA`, y un test cruza las
  dos listas con los `create table` de las migraciones.
  - Moraleja: **una lista blanca sin su lista negra no distingue «decidido» de
    «olvidado».** Escribe las dos y haz que un test compruebe que entre ambas está todo.
