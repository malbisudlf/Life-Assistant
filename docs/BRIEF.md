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
    Es la única señal exacta: instantánea y sin deducir nada.
  - La llegada del sueño del Watch en la ingesta (`_avisar_sueno_recibido`) — **es una
    deducción, no un aviso**. El reloj sabe cuándo te despiertas, pero el backend no se
    entera hasta que el iPhone sincroniza, y ese sync puede traer una noche a medias
    mientras sigues durmiendo. Por eso solo cuentan las noches de hoy y ayer (el Atajo
    reenvía los últimos días en cada sync) y se puede apagar con `BRIEF_DISPARA_SUENO=0`.
    Un fallo del correo **nunca** tumba la ingesta: guardar los datos del Watch importa
    más, y el correo tiene otras dos fuentes.
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
