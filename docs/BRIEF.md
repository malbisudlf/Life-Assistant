<!-- Parte de la guía del repositorio. El índice y las reglas que aplican
     SIEMPRE están en CLAUDE.md, en la raíz. -->

## Backend: el resumen diario y el informe semanal

Todo lo que sale por correo sin que nadie lo pida. El resto de patrones del
backend está en `docs/BACKEND_PATRONES.md`.

- **Resumen diario por correo** (`/brief`, `POST /brief/send`): manda a tu propio buzón
  los datos del día **en crudo, sin interpretarlos**, porque quien los consume es una
  rutina externa que lee el correo y redacta el resumen — ya es un modelo, así que aquí
  **no hay ninguna llamada a un LLM** y no debe haberla. Tampoco hay conclusiones:
  `healthConclusions` y compañía viven en `helpers.js`, son JavaScript y son la única
  fuente de verdad de esa lógica; portarlas a Python la duplicaría. Lo único que se
  replica es `_horas_sueno()` (equivalente a `_sleepHours`), que es forma del dato y no
  regla — si cambia cómo llegan los datos del Watch, hay que tocar los dos.
  **Cada media va con su `n`** (días con dato dentro de la ventana) y cada último valor
  con su antigüedad, y las ventanas se cuentan por fecha real, no por número de
  registros: sin eso, una métrica con una sola observación sale con las tres cifras
  iguales y quien lee el correo la toma por estabilidad en vez de por ausencia de datos.
  **Qué va en la sección de salud**: la consulta de `_brief_salud()` es UNA y no filtra
  por nombre, así que ya trae la tabla entera de la ventana — añadir una métrica a
  `_BRIEF_METRICAS` no cuesta un viaje más de red, solo tamaño de correo. Por eso van
  todas las que escribe el Watch (~19), no una selección. Tres cosas que no son
  decoración:
  - **La serie diaria** (`salud.series`, una posición por día, `None` en los huecos, solo
    para métricas con `BRIEF_MIN_DIAS_SERIE`+ días de dato). Una media dice dónde estás y
    una serie hacia dónde vas, y la segunda no se deduce de la primera. Es además lo
    único con lo que quien lee el correo puede **cruzar dos métricas entre sí**: el motor
    de correlaciones (`healthCorrelations`) vive en `helpers.js` y no se porta aquí, así
    que sin los valores día a día ese cruce no existe para el correo. Los huecos se
    marcan, nunca se comprimen: comprimirlos desplaza las posiciones y el cruce acabaría
    comparando fechas distintas.
  - **El cero es un dato en las acumulativas** (quinto campo de `_BRIEF_METRICAS`). Un
    día de 0 pisos ocurrió y tiene que bajar la media; un 0 en HRV o FC en reposo es el
    sensor sin medir y promediarlo sería inventarse una bradicardia. Antes se descartaba
    todo lo que no fuera `> 0` y las acumulativas salían sesgadas al alza.
  - **Fases del sueño y detalle de los entrenos**, que salen del `extra` y no de filas
    propias. Sin las fases, del sueño solo viajaba la cantidad; sin el detalle, de los
    entrenos solo "hace 2 días". `_minutos_entreno()` usa el mismo umbral que el widget
    del frontend (>300 ⇒ segundos): forma del dato, como `_horas_sueno()`.
  - **Una métrica se lee de TODOS sus nombres, no del primero que tenga filas**
    (`_filas_por_alias()`): Health Auto Export y el Atajo de iOS no coinciden en cómo
    llaman a todo (`apple_exercise_time` contra `exercise_time`), así que el histórico
    vive partido en dos nombres y quedarse con uno descarta el otro entero. Se fusiona
    por fecha, con el orden de la tupla como preferencia. Es lo mismo que hace
    `findMetric` en helpers.js, que ya recibía los dos nombres.
  - **Qué días estuvo puesto el reloj** (`_uso_del_reloj()`, sección `## RELOJ`). Es el
    denominador que le faltaba a todo lo demás: una métrica del Watch **no puede** tener
    dato un día que estuvo en un cajón, así que su `n` hay que leerlo contra los días que
    se pudo medir y no contra el calendario — por eso cada media del reloj sale como
    `n=3/3` y las del teléfono siguen saliendo como `n=29`. Tres reglas:
    - **Tres estados por día, no dos** (`A`/`D`/`N` con reloj, `.` sin reloj pero con
      datos del móvil, `-` sin datos de nada). El tercero es el que impide repetir el
      error de siempre por el otro lado: si no llegó NADA, no se sabe si hubo reloj o
      falló la sincronización, y dar eso por "día sin reloj" convierte una caída de la
      ingesta en un hábito. Los días `-` ni suman ni rompen la racha.
    - **El reparto es día / noche, no por sensor**, porque son dos hábitos distintos:
      llevarlo todo el día y quitárselo para dormir anula las nocturnas (HRV, FC en
      reposo, sueño, respiración) y deja intactas las diurnas.
    - **Una fila no es una medida** (`_hay_medida()`): el Atajo de iOS guarda ceros los
      días que no encuentra muestras —todos los días sin reloj—, así que contar filas
      daría por puesto justo el día que no lo estaba. Una noche anulada a mano
      (`extra.excluded`) tampoco cuenta: se anulan las que salieron mal, y la razón
      habitual es el reloj en el cargador. Por lo mismo, **un 0 de una
      acumulativa del reloj un día sin reloj se descarta** en vez de promediarse: 0 horas
      de pie con el reloj puesto es un día de sofá y tiene que bajar la media, pero con el
      reloj en el cajón es un hueco disfrazado. Los pasos no entran ahí — los cuenta el
      teléfono.
    `vo2_max` queda fuera de la detección a propósito (el reloj lo estima con semanas de
    caminatas: ni su presencia marca el día ni su ausencia dice nada), y el peso y la
    grasa vienen de la báscula. El día de HOY cuenta en las ventanas —para que cuadren
    con las medias, que también lo incluyen— pero no en la racha sin reloj: el correo sale
    por la mañana y la jornada está a medias.
    - **«Anoche» tiene TRES estados, y uno de ellos no se puede dar el mismo día.**
      `anoche` era un booleano (`hoy in con_noche`) y el correo escribía «Anoche: sin
      reloj» en cuanto faltaba la noche. Era falso casi todas las mañanas: el reloj no
      vuelca la noche a Salud al despertarte, sino **al abrir su app**, y eso pasaba
      entre cinco minutos y ocho horas después del correo. Hoy vale `"si"` o
      `"pendiente"`, nunca `"no"` — el mismo día no hay forma de distinguir «no lo
      llevaste» de «todavía no ha llegado», que es exactamente la regla de `sin_datos`
      para los días pasados, solo que faltaba por el otro lado. Y el correo lo dice con
      todas las letras («NO significa que no llevara el reloj»), porque quien lo lee es
      un modelo y sin esa frase lo traduce él solo. Que de verdad no lo llevaras lo
      dicen al día siguiente el último rastro y la racha —las dos cuentan desde ayer— y
      esa misma noche el aviso de `_avisar_reloj_si_toca`, que es el único momento en
      que sirve de algo.
  - **Si `value` es `null`, el valor se busca en `extra`** (`_valor_metrica()`). Hay
    filas viejas guardadas así por el bug del `Avg`: son histórico real y descartarlas
    es tirar semanas de dato que sí se recibió y sigue en la tabla.
  `construir_brief()` llama a las funciones de los endpoints existentes con
  `credentials=None` (ninguna usa ese parámetro; lo resuelve FastAPI solo por HTTP) para
  heredar su normalización y manejo de errores en vez de duplicar consultas, y las lanza
  en paralelo. Cada sección cae por su cuenta: un fallo de Graph deja la agenda vacía
  pero el resto del correo sigue siendo útil. Envío por `smtplib` (librería estándar, sin
  dependencias nuevas). Todos los disparadores usan tokens de servicio: un JWT de
  usuario caducaría a los 30 días y el correo dejaría de llegar sin avisar.
- **Cuándo sale el correo: al despertarse, no a una hora fija.** Lo disparaba el cron de
  `.github/workflows/resumen-diario.yml`, y Actions se retrasa 10-15 min cuando su cola
  va cargada — un disparador que no sabe decirte a qué hora va a disparar no vale para
  algo que tiene que pasar "al despertarte". Ahora hay tres fuentes y **`enviar_brief_si_toca()`
  es la única puerta**: cada fuente sabe CUÁNDO llamar, y quien decide SI se manda es ella.
  - `POST /despertar` (`BRIEF_TOKEN`) — el Atajo del iPhone al desenchufar el cargador.
    Es una señal exacta: instantánea y sin deducir nada. De paso calla la alarma de
    respaldo si estaba sonando (`docs/ALARMAS.md`), eso sí, sin ningún retraso.
    El resumen en sí, en cambio, espera `DESPERTAR_RETRASO_SEGUNDOS` (5 min por defecto,
    `DESPERTAR_RETRASO_MIN`) antes de mirar siquiera si el sueño ya está — probado que un
    delay dentro del propio Atajo de iOS no era fiable, así que el margen se da aquí, en
    segundo plano (`BackgroundTasks`), sin bloquear la respuesta al Atajo. A 0 se
    desactiva y se mira al instante, como antes de que existiera.
    Y no es la única: **confirmar la alarma de respaldo** (el botón, el dashboard) y
    **decirle a Jarvis «estoy despierto»** son la misma señal, por `_senal_despertar`,
    pero SIN este retraso — ya llevas un rato despierto para poder decirlo.
    Las tres son cosas que haces tú, despierto; nada se deduce.
  - La llegada del sueño del reloj en la ingesta (`_avisar_sueno_recibido`) — **ya no
    es una señal: solo cierra una espera** abierta por una señal de verdad. Lo fue,
    como deducción de "si la noche ha sincronizado es que estás despierto", y la
    deducción fallaba por el lado malo: la pulsera vuelca una noche a medias si te
    despiertas un rato a las seis, la app la sincroniza de fondo, y el correo salía a
    las siete mientras seguías durmiendo — o sea, **antes de que pudieras sincronizar la
    noche entera**, que era la queja. Sin señal de despertar, el sueño no manda nada y el
    correo espera a la hora tope. Con `BRIEF_DISPARA_SUENO=0` ni siquiera cierra la
    espera. Un fallo del correo **nunca** tumba la ingesta: guardar los datos del reloj
    importa más, y el correo tiene la hora tope detrás.
    - **Cuenta la noche de HOY, y solo si trae medida.** Aceptar también la de ayer
      parecía prudente —el Atajo reenvía los últimos días en cada sync— y era justo lo
      contrario: la noche se fecha por el día en que te despiertas, así que la de ayer
      **nunca** es la de esta noche y lo único que podía disparar era el reenvío de un
      dato que ya estaba. Y disparaba a diario: el correo salía con la noche de ayer
      recién reescrita y la de hoy todavía sin sincronizar, o sea con la sección RELOJ
      diciendo «anoche sin reloj». El 16/09/2026 el reenvío mandó el correo a las 08:33
      y el sueño de verdad llegó a las 08:38. Una fila de 0 horas tampoco cuenta: es lo
      que escribe el Atajo las noches que no encuentra muestras (`_hay_medida`).
  - **La señal de despertar no manda el correo: lo reserva** (`_esperar_al_sueno`,
    `BRIEF_ESPERA_SUENO`). Cuando desenchufas el cargador estás despierto, pero la noche
    puede no haber sincronizado, y mandar el correo entonces es mandarlo diciendo que no
    llevabas el reloj. Si falta, se apunta la espera en memoria y el correo sale con lo
    primero que pase: que llegue el sueño (lo normal) o que den las `BRIEF_HORA_TOPE`.
    Cinco cosas:
    - **La espera no reserva el día.** Reservarlo dejaría marcado como enviado un día
      cuyo correo aún no ha salido, y al llegar el sueño ya no saldría nunca. Misma
      trampa que la del interruptor, que por eso se mira antes de reservar.
    - **A los `BRIEF_ESPERA_SUENO_MIN` (45) te avisa al móvil, una vez, y sigue
      esperando** (regla `reloj_sync`, en `_vigilar_espera_sueno`). El aviso no es un
      parte de avería: es lo único que puede hacer que el dato de esta noche llegue a
      existir, porque hasta que no abras la app no hay nada que sincronizar. **La
      primera versión mandaba el correo al vencer**, y salía igual de cojo que antes
      solo que más tarde: la sincronización depende de abrir una app, y eso pasa cuando
      pasa. Un correo a las diez con la noche dentro vale más que uno a las ocho menos
      cuarto sin ella, porque la noche es justo lo que se lee de ese correo; y la hora
      tope ya era el sitio donde este sistema aceptaba salir con lo que hubiera.
    - **El tick mira en cada vuelta si el sueño ya está**, no solo al avisar: si entró
      por un camino que no pasa por la ingesta, esperar a las diez con el dato guardado
      —o regañarte por no sincronizar algo ya sincronizado— es como se deja de leer un
      aviso. Ahí «no he podido mirar» cuenta como «todavía no» (`_hay_sueno_de(...,
      si_falla=False)`): mandar el correo por un parpadeo de Supabase lo dejaría sin la
      noche, y esperar cinco minutos no cuesta nada. Y es también el reintento: si el
      SMTP falla justo al llegar el sueño, la espera sigue viva y el tick lo vuelve a
      intentar.
    - **La espera es propiedad de la SEÑAL**, igual que la ventana horaria: la hora tope
      y los respaldos disparan justo cuando ya no tiene sentido esperar, y pasarlos por
      aquí los dejaría sin mandar nada nunca. A la hora tope el correo sale con fuente
      `espera_agotada` y la hora a la que te levantaste: en `brief_envios` es lo único
      que después distingue un correo al que le faltaba la noche de una mañana en la
      que nadie dio señal.
    - **Vive en memoria a propósito.** Quien sabe si el dato ha llegado es Supabase;
      perder la nota en un reinicio cuesta que el correo salga por la hora tope, que es
      exactamente la red de seguridad que este sistema ya tenía.
  - `POST /ha/brief-tick` (`HA_POLL_TOKEN`) — el reloj de respaldo. HA lo sondea cada
    pocos minutos y solo hace algo pasada `BRIEF_HORA_TOPE` (10:00). El reloj lo pone HA
    y no un hilo del backend porque **Fly escala a cero**: sin nadie que llame, aquí no
    hay proceso vivo que pueda mirar la hora.

  Dos invariantes que no se pueden relajar:
  - **La idempotencia es la tabla `brief_envios`, no una comprobación previa.** Se
    inserta la fila del día ANTES de mandar el correo, con un INSERT normal: el 409
    contra la clave primaria es lo que hace la pregunta atómica. Con un GET previo, dos
    disparadores que coincidan en el mismo minuto (el móvil y el sondeo de HA) leen los
    dos "no enviado" y mandan dos correos. Y no puede ser un flag en memoria como los del
    WOL: un cold start de Fly a media mañana lo borraría y mandaría el correo otra vez.
  - **Si el envío falla, se libera la reserva** (`_liberar_envio`). Si no, un error
    transitorio de SMTP de un minuto deja el día marcado como enviado y te quedas sin
    briefing hasta mañana.

  La **ventana de despertar** (`BRIEF_DESPERTAR_DESDE` 05:30 – `BRIEF_DESPERTAR_HASTA`
  11:30) tiene los dos extremos, y cada uno protege de algo distinto: el suelo, de tomar
  por despertar un desenchufe de madrugada camino del baño; el techo, de que el día en
  que fallen todas las señales de la mañana una desconexión de las cinco de la tarde
  mande el correo entonces, con los datos ya caducados y llamándolo "despertar". Es
  propiedad de la SEÑAL,
  no del envío: se comprueba en `/despertar` y en `_avisar_sueno_recibido`, nunca dentro
  de `enviar_brief_si_toca` — la hora tope y la red de seguridad disparan por definición
  fuera de ella. Todo el disparo mira la hora por `_ahora_local()`, punto único que
  existe para poder fijarla en los tests.
  El workflow de Actions **sigue existiendo pero ya no es el disparador**: es la red de
  seguridad para cuando se cae la casa entera (HA apagado, router sin luz), dispara
  tarde y a ciegas, y al pasar por la misma puerta idempotente no duplica nada.
  `POST /brief/send?forzar=1` se salta la idempotencia: es como se prueba el correo a
  mano sin esperar a mañana ni borrar la fila del día.
- **Días atípicos** (`_atipicos()`, sección `## DÍAS ATÍPICOS`): los días que se salen
  de ±`BRIEF_SIGMA_ATIPICO` de la propia ventana de cada métrica. No interpreta nada
  —sigue siendo aritmética sobre el dato crudo— pero convierte una lectura completa de
  ~600 números en una mirada. Dos reglas: la media y la σ se calculan **sin el propio
  día** (si no, un valor extremo tira de la media hacia sí mismo y se tapa solo: cuanto
  más raro es, menos raro parece), y hacen falta `BRIEF_MIN_DIAS_ATIPICO` días de dato
  (con cuatro observaciones la σ es tan ruidosa como el dato y marcaría cualquier cosa,
  que es la forma más rápida de que nadie mire las marcas). Una serie sin dispersión
  (σ=0) no señala nada: no hay escala contra la que medir.

- **Qué ha cambiado desde el último resumen** (`_instantanea_brief`, `_cambios_desde`,
  columna `brief_envios.datos`): va la PRIMERA del correo, porque es lo que decide si
  hay que leer el resto con atención. Cuatro cosas:
  - Se guarda una instantánea **mínima**, no el correo entero: solo lo que tiene
    identidad de un día para otro (último valor de cada métrica, entregas por título y
    las dos cifras del entrenamiento). Las series diarias no entran — su diff es la
    propia serie.
  - **Una métrica se movió si trae FECHA nueva, no valor distinto.** Comparando el valor
    se daría por novedad el mismo dato de ayer leído otra vez, que es justo lo contrario.
  - **Las que NO se han movido también se cuentan**: si media tabla sigue con el dato del
    mismo día, no es que no pase nada, es que no ha llegado nada.
  - Se escribe con un PATCH **después** de enviar y un fallo solo se registra: si la
    migración no está aplicada, el resumen sale igual sin esa sección. Un resumen sin el
    diff sigue siendo el resumen; uno que no sale por una columna que falta, no.

- **El JSON va adjunto** además del texto (`enviar_correo(..., adjunto=...)`). El texto
  lo tiene que poder leer un modelo Y una persona, y esa doble función le pone un techo a
  lo que cabe dentro. Con el adjunto no hay que elegir.

- **Economía: titulares y término del día** (`_brief_economia`, `_titulares_nuevos`,
  `_termino_del_dia`, secciones `## ECONOMÍA — TITULARES` y `## TÉRMINO ECONÓMICO DEL
  DÍA`, interruptor `BRIEF_ECONOMIA`): las dos únicas secciones del correo que no salen
  de un sensor. Un puñado de titulares de economía general y un término económico
  distinto cada día. **Siguen siendo dato crudo**: el correo manda el titular con su
  medio, su hora, su extracto y su enlace, y del término manda la PALABRA, no la
  explicación. Elegir qué noticia cuenta y explicar el término es de quien redacta el
  briefing, que ya es un modelo — meter aquí un diccionario sería mantenerlo en el
  backend para el único lector que no lo necesita, el mismo motivo por el que no hay
  conclusiones de salud.
  - **La relevancia la decide la FUENTE, no un filtro.** Lo que se pide es economía que
    te toca (tipos, hipotecas, empleo, precios), no la balanza comercial de Zimbabue, y
    eso se consigue eligiendo secciones de economía de medios generalistas españoles
    (`BRIEF_ECONOMIA_FEEDS`). Filtrar por palabras clave sería interpretar, y además
    tiraría justo la noticia que no se te ocurrió nombrar. Si lo que llega no sirve, se
    cambia la fuente.
  - **Cada fuente sale en el correo con cuántos titulares aportó.** Un feed que muere
    (una URL que el medio cambia sin avisar) no vacía la sección: la deja corta, y sin
    esa línea eso se lee como un día tranquilo en vez de como una avería. Un 0 sostenido
    o un `CAÍDA (...)` es la única forma de enterarse. Es también cómo se comprueban las
    URLs por defecto sin desplegar nada: `GET /brief` y mirar `economia.fuentes`.
  - **El feed se parsea con expresiones regulares, no con `xml.etree`.** `xml.etree` es
    vulnerable a las bombas de entidades y `defusedxml` sería una dependencia nueva para
    leer cuatro campos. Es tosco a propósito, como `_html_a_texto`. Se descarga con
    `_descargar`, que es el único cliente saliente que valida SSRF en cada salto y corta
    por bytes: las URLs vienen de configuración, pero un redirect no.
  - **Los titulares del resumen anterior se descartan, y el tope se aplica DESPUÉS.** La
    ventana es de `BRIEF_ECONOMIA_HORAS` (30) y no de 24 porque con 24 justas una noticia
    publicada ayer a la hora de tu correo no entra hoy y ya no entra nunca. Ese solape lo
    limpia comparar contra los titulares que se mandaron de verdad (`brief_envios.datos`,
    la misma instantánea del diff), que es exacto y no depende de la hora a la que te
    despiertes. Se comparan por titular normalizado y no por URL: la misma noticia llega
    de dos medios con dos enlaces, y el mismo enlace cambia de parámetros de campaña
    entre dos descargas. Y recortar antes de descartar dejaría el correo con la mitad de
    titulares justo los días en que se repite algo.
  - **El término del día no tiene tabla: lo decide la fecha.** `(ordinal del día × paso)
    % total` sobre `_GLOSARIO_ECONOMIA`. Así es idempotente (reenviar el correo o probar
    con `?forzar=1` no gasta el de mañana), sobrevive a un Supabase caído y no necesita
    migración. El paso es un número primo respecto al total en vez de 1 porque la lista
    está agrupada por temas: de uno en uno saldrían cinco días seguidos de hipotecas.
    Se elige a partir del total (`_paso_glosario`) para que añadir términos no rompa la
    propiedad de recorrer la lista entera sin repetir ninguno. Van también **los dos
    términos anteriores**: quien redacta el correo no recuerda lo que escribió ayer, y sin
    eso dos días seguidos se explican desde cero en vez de enlazarse.
  - **Los dos bloques son independientes**: el término no toca la red, así que un feed
    caído no se lo lleva por delante. `BRIEF_ECONOMIA=0` apaga los dos.
  - **Una fuente muere de dos maneras, y solo una se veía.** Las tres URL originales
    duraron menos de lo que parecía: en septiembre de 2026 **dos de las tres estaban
    muertas** y todos los titulares salían de EL PAÍS.
    - *Caída*: CincoDías responde **403** con cualquier User-Agent, el de un navegador
      incluido. Sale en el correo como `CAÍDA`, que es lo correcto.
    - *Congelada*: RTVE (`api2.rtve.es/rss/temas_economia.xml`) responde **200** con
      288 KB de XML impecable cuya entrada más reciente es del **9 de junio de 2022**.
      No falla, no avisa, y por el número de titulares es idéntico a un día tranquilo.
      Se pasó así **más de cuatro años**. Por eso `_leer_feed` devuelve ahora
      `mas_reciente` y `_brief_economia` marca `congelado_desde` / `congelado_dias`
      cuando una fuente no aporta nada y lo último que trae pasa de
      `FEED_CONGELADO_DIAS` (9, para que un puente largo no lo dispare). El correo lo
      escribe con la fecha y con un «Cambia la fuente».

    Las tres de ahora son **un generalista, un diario económico y una agencia** (EL PAÍS,
    Expansión, Europa Press), y son tres papeles distintos a propósito: con tres versiones
    de lo mismo, la caída de una deja el bloque igual de cojo. Comprobadas vivas el
    2026-09-05. Si cambias una, mira que traiga `pubDate` de verdad — eldiario.es lo
    manda vacío, y sin fecha las entradas se cuelan sin pasar por la ventana.

    **Ojo**: `BRIEF_ECONOMIA_FEEDS` es variable de entorno. Si está puesta en los secrets
    de Fly, cambiar el valor por defecto del código no cambia nada en producción.
  - **La codificación no se le pregunta a `requests`.** `_descargar` decide el códec con
    `_codificacion()`: charset de la cabecera → declaración del propio documento (prólogo
    XML o `<meta charset>`) → UTF-8. Usar `r.encoding` era el bug: para cualquier `text/*`
    sin charset, requests aplica el viejo RFC 2616 y decide **ISO-8859-1**, que para un
    XML es casi siempre falso. Es lo que hacía llegar «EconomÃ­a en rtve.es» al correo, y
    lo que EL PAÍS se libraba de sufrir solo por servirse como `application/xml`, donde
    requests no adivina nada.
  - **El clima se reintenta.** El correo se compone una vez al día: un parpadeo de red de
    dos segundos en ese instante dejaba el bloque en `(no disponible)` hasta mañana, y en
    el correo eso se lee igual que Open-Meteo caído de verdad. `BRIEF_CLIMA_INTENTOS` (2)
    y `BRIEF_CLIMA_ESPERA` (2 s). `_brief_clima` captura además `requests.RequestException`:
    `get_weather` traduce a `HTTPException` lo que *responde* Open-Meteo, pero un timeout
    subía sin capturar hasta el `.result()` del pool.
  - **Falta la otra mitad, y no vive en este repositorio**: la rutina de Claude Code que
    redacta el briefing tiene que saber que estas secciones existen. Sin tocar su prompt,
    el correo llega con los titulares y el término dentro y el briefing no los cuenta.

- **Informe semanal** (`construir_informe_semanal`, `render_informe_texto`,
  `_enviar_informe_si_toca`, tabla `informe_envios`): los domingos (`INFORME_DIA`), medias
  **por semana** de las últimas `INFORME_SEMANAS`. Una media de 30 días dice dónde estás;
  trece semanas seguidas dicen hacia dónde vas, y eso hoy solo se veía abriendo el modal
  de patrones — o sea, solo si a uno se le ocurría mirar. Cuatro decisiones:
  - **No reutiliza `_brief_salud()`**: sus claves (`media_7d`, `n_30d`, la serie día a
    día) describen una ventana de 30 días y estirarlas a 90 haría que los nombres
    mintieran. Se comparte `_BRIEF_METRICAS` y las funciones de lectura del dato.
  - **Tabla propia en vez de una columna en `brief_envios`**, aunque la forma sea idéntica:
    si la migración no se aplica, lo único que no funciona es el informe. Metiéndolo en
    `brief_envios` (cambiando su clave primaria para admitir dos tipos) una migración sin
    aplicar rompería el resumen DIARIO.
  - **Una semana con menos de `INFORME_MIN_DIAS_SEMANA` días de dato sale como hueco**: no
    es una semana medida, y presentar la media de dos días como semanal es el mismo error
    que las medias sin `n`.
  - **Los días de reloj por semana van con las métricas**, en las mismas posiciones: una
    semana de vacaciones sin el Watch baja todas las medias nocturnas, y sin el
    denominador esa caída se lee como un empeoramiento.

- **El interruptor** (`brief_ajustes`, `GET`/`PATCH /brief/ajustes`, panel ⚙ y las
  herramientas `estado_resumen_diario`/`configurar_resumen_diario` de Jarvis): apagar el
  resumen, o pausarlo hasta una fecha. Cuatro cosas que no son decoración:
  - **Es estado, no una orden**: va a Supabase, no a un flag en memoria como el WOL. Un
    apagado que no sobrevive al cold start de Fly se enciende solo a la mañana siguiente,
    que es justo lo que se pidió que no pasara. Con copia en memoria
    (`_brief_ajustes_cache`), como el token de Graph y la presencia; resetéala en
    `conftest.py` como el resto de estado de módulo.
  - **La comprobación va DENTRO de `enviar_brief_si_toca()` y solo ahí**, que es la única
    puerta del envío automático: puesta ahí apaga de una vez las tres fuentes, y una
    cuarta que se añada mañana no se puede olvidar de mirarla. Y va **antes de reservar**:
    reservar el día de un correo que no va a salir lo deja marcado como enviado, y al
    quitar la pausa no saldría hasta el día siguiente.
  - **No tapa el envío pedido a mano** (`?forzar=1`, `enviar_resumen` de Jarvis): ahí hay
    una persona pidiéndolo en ese momento, que puede apagar el interruptor en el mismo
    gesto. Obedecer al ajuste antes que a quien lo puso sería el sitio equivocado.
  - **Un fallo leyéndolo no apaga el correo**: se sigue con el defecto (activo) y se
    registra. El envío necesita Supabase igualmente para reservar, así que un Supabase
    caído no manda nada por su cuenta; en cambio leer "no he podido preguntar" como
    "estaba apagado" cuesta un día entero de briefing sin que nada lo parezca — el mismo
    error que cometió el agente PC con la cola de jobs.
  La **pausa lleva fecha de fin, inclusive, y se agota sola**: es lo que separa "me voy
  una semana" de "no lo quiero más". Una pausa vencida se reporta como si no existiera
  (`pausado_hasta` a `None`), porque una fecha pasada al lado de un resumen que vuelve a
  salir se lee como avería.
- **Quién redacta el briefing, y cuándo** (`_lanzar_rutina`): el correo de datos no es
  el final del camino — lo lee una rutina de Claude Code que redacta el briefing de
  verdad. Las rutinas admiten **varios triggers a la vez** (horario, API, eventos de
  GitHub), y aquí se usan dos porque las dos situaciones piden cosas distintas:
  - Te despiertas **pronto** → el correo de datos sale pronto, pero el briefing todavía
    no debe redactarse: recoge newsletters que a las 6 de la mañana no han llegado. De
    eso se encarga el **trigger de horario** de la propia rutina (08:00) y el backend no
    hace nada.
  - Te despiertas **tarde** → esperar al reloj sería redactar el briefing sin los datos
    del día o con horas de retraso. Ahí el backend dispara el **trigger de API**
    (`POST .../routines/{trig_...}/fire`, bearer `sk-ant-oat01-...`) justo después de
    mandar el correo, gobernado por `BRIEF_RUTINA_DESDE`.

  El disparo **nunca puede tumbar el envío**: cuando se llama, el correo ya ha salido, y
  eso es lo que importa. Un fallo se registra y se sigue. Si `RUTINA_FIRE_URL`/
  `RUTINA_FIRE_TOKEN` no están configuradas no se dispara nada y la rutina se queda con
  su horario — el sistema sigue funcionando, solo que sin esta mitad. El token se genera
  en la web (`claude.ai/code/routines`), se enseña una sola vez y solo sirve para
  disparar esa rutina. `RUTINA_BETA` es una cabecera beta **con fecha**: el endpoint está
  en research preview y si un día devuelve 400, es lo primero que hay que mirar.
  El campo `text` del disparo llega a la rutina envuelto y etiquetado como dato no
  fiable, así que sirve de contexto para el registro de la sesión, no de instrucción: la
  rutina no debe depender de él para saber qué hacer.
