# Ideas para Life Assistant

Ideas nuevas, ordenadas por lo que aportan frente a lo que cuestan. No es una hoja de
ruta ni un compromiso: es un sitio donde dejarlas escritas con el porqué delante, para
que dentro de tres meses se pueda decidir con la razón a la vista en vez de con el
recuerdo de la razón.

Cada una lleva **qué**, **por qué** (que es la parte que no se puede reconstruir después)
y **por dónde se empieza**. El esfuerzo es orientativo: ● pequeño (una tarde), ●● medio,
●●● grande o con partes fuera del código (Atajos de iOS, YAML de Home Assistant).

El hilo conductor de casi todas es el mismo que ya recorre el proyecto entero:
**distinguir "no lo sé" de "es que no". La detección de uso del reloj es el último
capítulo de esa historia, no el final.**

> Los **puntos 1, 2, 3 y 4 están implementados** (agosto de 2026). Se dejan escritos, con
> el resultado debajo de cada uno, porque el porqué sigue valiendo y porque de hacerlos
> salieron dos cosas que no estaban previstas: un bug de ventanas por registros en el
> dashboard y la frontera entre `_CRUCES` y `healthConclusions`.

---

## 1. El reloj, hasta el final — ✅ HECHO (agosto de 2026)

La detección de uso del reloj vivía solo en el correo de datos. Ya no: el dashboard, las
conclusiones, la puntuación y un aviso nocturno saben lo mismo. Lo que se hizo de cada
punto, por si hay que volver sobre ello:

- **1.1 El dashboard sabe cuándo no llevaste el reloj.** `GET /health/metrics` devuelve
  `reloj` (`dias`: fecha → estado, y `fuentes`: métrica → día/noche) desde las mismas
  filas que ya traía, sin un viaje de red más. El panel de estado tiene una fila propia:
  la de sincronización responde "¿llegan datos?" y esta "¿se pudieron medir?".
- **1.2 Las conclusiones ya no hablan de tendencias que no existen.** Al mirarlo de cerca
  el problema de fondo era peor de lo previsto: `seriesTrend` y las medias de
  `healthConclusions` cogían los últimos N *registros*, no los de los últimos N *días* —
  el mismo bug que el correo ya tenía corregido, pero aquí produciendo frases afirmativas.
  Ahora las ventanas van por fecha real, una tendencia exige fondo a los dos lados
  (`nCorto >= 3`, `nLargo >= 7`) y hay un dominio "Reloj" que dice cuántas noches se pudo
  medir. La clasificación de métricas se queda en el backend y viaja en `reloj.fuentes`:
  una sola lista, no dos que se desincronicen.
- **1.3 Avisa de que te lo has dejado quitado.** `_avisar_reloj_si_toca()` en el tick de
  HA, a partir de las 21:30, montado sobre los recordatorios que ya existían (idempotencia
  por `uuid5` de la fecha contra la clave primaria). Un día sin datos de ninguna fuente no
  dispara nada.
- **1.4 La puntuación sabe sobre cuánto está calculada.** `scoreFromBreakdown` devuelve
  `cobertura`, el tooltip dice "calculado sobre N de M componentes" y la sparkline de
  evolución marca con un punto los días puntuados sin reloj: menos sensores, no peor día.

Lo que queda pendiente de este bloque, y no es poco: **los cruces del catálogo `_CRUCES`
siguen sin mirar la cobertura**. Hoy no es un problema —cada cruce solo empareja días con
dato en las dos series—, pero un cruce cuyos dos grupos caigan a distintos lados de un mes
sin reloj compararía dos épocas, no dos condiciones.

---

## 2, 3 y 4 — ✅ HECHOS (agosto de 2026)

Implementados en el mismo lote. Lo que quedó de cada uno, con lo que se decidió por el
camino:

### 2. Salud

- **2.1 Baselines personales.** Solo en métricas de FISIOLOGÍA (FC en reposo y FC
  caminando). Sueño, pasos, energía y compañía son CONDUCTA: puntuarlas contra la propia
  media es calificar en curva. La ventana (90 días, hasta D-1) se ancla al día que se
  puntúa, no a hoy — sin eso el histórico deja de ser reproducible. Sin 21 días de medida
  se cae al umbral fijo, y el desglose dice contra cuál de los dos ha puntuado.
- **2.2 Firma de "algo va mal".** Acabó como conclusión en `healthConclusions`, no como
  cruce: `_CRUCES` describe hábitos estables y lo ejecuta también la ventana larga, donde
  una firma de hace ocho meses no es un hallazgo. Umbrales de entrada más bajos que los
  de cada métrica por separado, y sin base declarada no afirma nada.
- **2.3 Días atípicos en el correo.** Con la media y la σ calculadas **sin el propio
  día**: si no, un valor extremo tira de la media hacia sí mismo y se tapa solo.

### 3. El correo

- **3.1 Informe semanal.** Domingos, medias por semana de las últimas 13, con los días de
  reloj de cada semana como denominador. Tabla propia (`informe_envios`) para que una
  migración sin aplicar no pueda romper el resumen diario.
- **3.2 Qué ha cambiado desde ayer.** Va la primera del correo. Una métrica "se movió" si
  trae fecha nueva, no valor distinto; y las que NO se movieron se cuentan también,
  porque media tabla quieta no es que no pase nada, es que no ha llegado nada.
- **3.3 El JSON adjunto.** Además del texto, sin quitarle nada.

### 4. Jarvis

- **4.1 Se diagnostica.** Fallos por origen, estado del resumen, frescura de cada métrica
  y qué está configurado. Sin cuerpos de error: acabarían en el prompt de un modelo.
- **4.2 Habla primero.** Una vez al día, con el listón en el código y el modelo solo
  redactando. Si el modelo falla, sale en crudo.
- **4.3 Destila la memoria.** Al cerrar turnos de conversaciones largas, con dos frenos
  de coste.

Lo que se decidió NO hacer, y por qué:

- **El informe semanal no reutiliza `_brief_salud()`**: sus claves describen una ventana
  de 30 días y estirarlas a 90 haría que los nombres mintieran.
- **El aviso proactivo no incluye el reloj**: ya tiene el suyo, y dos correos por lo mismo
  es la forma más rápida de que se dejen de leer los dos.

---

## 5. Operación: que el sistema se vigile a sí mismo

> **5.1 y 5.2 están hechos** (agosto de 2026). Lo que salió de hacerlos, antes del texto
> original de cada uno:
>
> - **5.1** — `_vigilar_ingesta()` cuelga del tick de HA: 24 h sin recibir nada → un
>   `logger.error` (que ya llega solo a `app_logs`, al panel y al `diagnostico` de
>   Jarvis); 48 h → además un recordatorio, por el camino de correo que ya existía. Lo
>   que costó decidir no fue el umbral: fue que **si la consulta falla se calla**. Avisar
>   ahí convertiría un Supabase lento en "el Watch no sincroniza".
> - **5.2** — Al ir a escribirlo se vio que la tabla **no guardaba de quién venía cada
>   fila**, así que la mitad del endpoint no se podía escribir: hacía falta una columna
>   (`health_metrics.fuente`, migración `20260816_health_fuente`), nullable, porque lo ya
>   guardado no se puede atribuir sin inventárselo. `GET /health/diagnostico` da lo que
>   antes solo se veía mirando la tabla en crudo, y el `diagnostico` de Jarvis enseña la
>   última escritura de cada cliente.
>
> **5.3 y 5.4 siguen pendientes.** El 5.3 nació de estrenar el canal de avisos al móvil:
> el único fallo que ese canal no sabe detectar es justo el que ocurrió la primera noche.

### 5.1 Vigilante de ingesta ● — ✅ HECHO

**Qué.** Si no entra ningún dato de salud en más de N horas, un `logger.error()` (que ya
persiste en `app_logs` y sale en el panel de ajustes) y, pasado más tiempo, un correo.

**Por qué.** Es el fallo que más veces ha ocurrido en este proyecto y siempre se ha
descubierto tarde y de casualidad: el 409 del upsert, el 400 del envoltorio, el JWT
caducado del agente. Los tres tenían en común que **el sistema seguía respondiendo que todo
iba bien**. Nadie vigila la ausencia salvo que se le pida expresamente.

**Por dónde.** El tick de HA otra vez: ya pasa cada 5 minutos y ya sabe mirar la hora.

### 5.2 `GET /health/diagnostico` ● — ✅ HECHO

**Qué.** Un endpoint que responda, por métrica: último `metric_date`, última escritura,
qué fuente la escribió y cuántos huecos tiene en 30 días.

**Por qué.** Cada vez que ha habido un problema de datos, el diagnóstico ha sido el mismo
trabajo manual: mirar la tabla, contar días, comparar nombres, deducir la fuente. Es
exactamente lo que se automatiza bien.

**Qué queda tras el 4.1.** La herramienta `diagnostico` de Jarvis ya da la mitad: días sin
dato de cada métrica, fallos por origen y qué está configurado. Falta lo que solo se ve
mirando la tabla en crudo — QUÉ FUENTE escribió cada fila (Health Auto Export o el Atajo) y
los huecos intercalados. Eso es lo que distingue "el Atajo dejó de correr" de "el reloj no
se llevó", que hoy sigue habiendo que deducirlo.

### 5.3 El acuse de entrega de los avisos al móvil ●

**Qué.** Que la automatización de HA confirme (`POST /ha/avisos-entregados`) que ha
mandado cada aviso, y que lo recogido-pero-no-confirmado se rescate por correo igual que
hoy se rescata lo que nadie recoge.

**Por qué.** Es el punto ciego que dejó al descubierto el estreno del canal (ver
`docs/BUGS_HISTORICOS.md`): con el `notify` mal escrito, HA recogía el aviso y lo perdía
al mandarlo, y desde el backend eso es **idéntico a haberlo entregado** — la única señal
que hay es el sondeo. El rescate por correo no salta, porque cubre lo que nadie recoge, y
un aviso recogido está fuera de la cola. Así que hoy el único fallo del canal que no se
detecta es justo el que ocurrió.

**Cuidado, que aquí está la parte que no es obvia.** El ack **no puede ser obligatorio**:
si se da por perdido todo lo que no se confirma, una instalación que no haya añadido esa
línea al YAML recibiría cada aviso dos veces, por móvil y por correo. Tiene que
autodetectarse igual que el canal — mientras no llegue ni un ack, se sigue como ahora; en
cuanto llega el primero, se puede exigir. Es la misma regla que ya gobierna el canal
entero: **la señal es que alguien conteste, no un interruptor que haya que acordarse de
poner**.

**Por dónde.** Un id por aviso, una lista de "recogidos pendientes de confirmar" en
memoria, y `_rescatar_avisos` mirando también esa lista pasado un plazo.

### 5.4 Copia de seguridad de Supabase ●●

**Qué.** Un volcado periódico de `health_metrics`, `training_*` y `jarvis_memoria` a un
sitio que no sea Supabase.

**Por qué.** Es el único dato del proyecto que no se puede regenerar. El calendario está en
Outlook, la configuración en el `.env`, el código en GitHub; el histórico del Watch existe
en un solo sitio, y con la ingesta resolviendo por `(metric_date, metric_name)`, un fallo
que escriba mal lo pisa sin dejar rastro.

**Cuidado.** El repositorio es público. El destino tiene que ser privado, y eso ya no es
"un workflow y ya".

---

## 6. Ronda de septiembre de 2026

> **Las siete están HECHAS** (3 de septiembre de 2026), en el mismo día en que se
> escribieron. Se deja el texto original de cada una porque el porqué sigue valiendo, y
> debajo de este aviso lo que salió de hacerlas que no estaba previsto:
>
> - **6.2 obligó a una invariante nueva de seguridad** (la 9 de `CLAUDE.md`): un encargo
>   en lenguaje natural no se puede validar contra una lista blanca, así que se firma con
>   `AGENT_TOKEN` y el agente verifica la firma. Al escribirlo se vio además que el camino
>   hasta Cowork tenía que ser UNO (`_pegar_en_cowork`), porque es donde vive la propiedad
>   que no se puede perder: la instrucción nunca se interpola en un comando.
> - **6.3 no podía ser una columna.** Empezó como un campo más en `jarvis_recordatorios`
>   y acabó en tabla propia al caer en la cuenta de que, con la migración sin aplicar, el
>   insert del aviso devolvería 400 — o sea que añadir una función de diagnóstico dejaría
>   al sistema SIN AVISOS. Y obligó a que el backend ponga siempre el `id` del aviso.
> - **6.4 midió algo que no se esperaba**: `gpt-4o-mini` acierta 63/63 eligiendo
>   herramienta y `gpt-5-mini` 51/63, pero cinco de esos doce fallos son el mismo patrón
>   (pedir `estado_pc` antes de actuar), que en el bucle real se resolvería solo. La cifra
>   del modelo grande es un SUELO, no su acierto: no se puede quitar el reparto de modelos
>   con ese número solo. Está escrito en `docs/EVALS.md` para que nadie lo haga.
> - **6.5 descubrió que por streaming el `usage` hay que pedirlo** (`include_usage`): sin
>   eso, el modo llamada —el que más gasta— era justo el único que no se podía medir.
> - **6.7 se topó con tres huecos del backend** y de ellos salió un endpoint nuevo
>   (`GET /avisos/enviados`, que además es donde se cuelga el 6.3). Los otros dos siguen
>   abiertos: `/calendar/events` solo consulta desde hoy, así que al retroceder el carril
>   de eventos dice «no lo sé»; y de la casa no hay histórico ninguno.

Siete ideas propuestas y aprobadas el 3 de septiembre de 2026. Ninguna repite nada de las
listas anteriores ni de `docs/JARVIS_PROACTIVO.md`: se escribieron después de comprobar
en el código qué estaba ya hecho (las reglas proactivas, el presupuesto de avisos, la
señal de utilidad, las vigilancias web y el correo entrante lo están).

Se descartó una octava —**los movimientos de Revolut**, categorizados y cruzados con los
cobros de entrenamiento— y conviene dejar escrito que se descartó por decisión, no por
imposibilidad: el consentimiento de Enable Banking **ya pide `transactions: True`**
(`main.py`, `/auth/enablebanking/login`), así que el permiso está concedido y sin usar.
Si alguna vez se retoma, lo que hay que saber es que aquí sí haría falta tabla propia, al
revés que con Indexa: un movimiento antiguo se cae del ventanal de la API y el histórico
de gasto es justo el dato con valor.

### 6.1 Jarvis en la muñeca ●

**Qué.** Un Atajo de iOS —«Oye Siri, dile a Jarvis…»— que dicta, llama a `POST /jarvis`
con `voz: true` y lee la respuesta en alto. Desde el reloj, sin sacar el móvil.

**Por qué.** Jarvis vive hoy dentro del dashboard: para hablarle hay que desbloquear el
móvil, abrir la web y esperar el arranque en frío de Fly. La decisión de diseño de que
**la elección de herramienta viva entera en el backend** («un cerebro, muchas bocas») se
tomó precisamente para este día, y todavía no ha cobrado: solo hay una boca.

**Por dónde.** La pieza que falta no es el Atajo, es la auth. Un Atajo **no puede llevar
un JWT de usuario** (invariante 2 de `CLAUDE.md`): caduca a los 30 días y el cliente se
queda mudo sin avisar a nadie, que es exactamente como se rompió el agente PC. Hace falta
un `JARVIS_TOKEN` de servicio con `_token_ok()`, el limitador genérico por IP
(`_check_rate`, el mismo que protege `/ideas/audio`, porque cada turno es una llamada de
pago) y una respuesta pensada para oírse, no para leerse — que es lo que ya hace
`voz: true`.

**Cuidado.** Un token de servicio que puede hablar con Jarvis puede, por el camino, llegar
a las herramientas de Jarvis. La frontera de confirmación tiene que seguir siendo la
misma: lo marcado `confirmar: True` devuelve `pendiente` y no se ejecuta, venga de donde
venga.

### 6.2 Encargarle trabajo al PC hablando ●●

**Qué.** Un tipo de job nuevo, genérico: una instrucción en lenguaje natural para
Cowork/Claude Desktop, creada desde Jarvis. «Que el PC me deje preparado el resumen de
esto para cuando llegue.»

**Por qué.** Hay una cola de jobs con reintentos, eventos, streaming y un agente Windows
que sabe conducir Edge y Claude Desktop — y todo eso sirve hoy a **un solo caso de uso**,
Alud. Es la infraestructura más cara del proyecto y la menos aprovechada. Esto es lo que
convierte el dashboard en algo que *hace* cosas en vez de contarlas.

**Cuidado, y es la parte importante.** Todo el modelo de seguridad del agente
(invariantes 7 y 9 de `CLAUDE.md`) se apoya en una premisa: la instrucción sale de una URL
de `ALUD_ALLOWED_HOSTS` y se valida en tres sitios. **Un job genérico rompe esa premisa**,
así que necesita la suya, igual de explícita:

- La instrucción solo puede venir de un job creado con **JWT de usuario** y marcado
  `confirmar: True` en Jarvis (el modelo propone, tú apruebas, `/jarvis/ejecutar` crea).
  Nunca de una fila escrita en `jobs` con la service key, que es escribible.
- Sigue escribiéndose a **fichero temporal UTF-8** y leyéndose con
  `Get-Content -LiteralPath`: jamás interpolada en un comando (invariante 9, la lección
  del here-string).
- El agente tiene que poder distinguir el tipo de job y **negarse a lo que no conozca**,
  no intentar adivinarlo.

### 6.3 Por qué te dije eso ●

**Qué.** Que cada aviso guarde los valores que lo dispararon y que se puedan consultar
después: «te avisé porque la FC en reposo iba a 62 contra 55 de tu base, el HRV a 31
contra 44, y con 4 noches medidas».

**Por qué.** Es el hilo conductor del proyecto entero —distinguir «no lo sé» de «es que
no»— aplicado al último sitio donde todavía no está. Hoy un aviso es una frase redactada
por un modelo, y cuando se equivoca no hay forma de reconstruir de dónde salió. Y encaja
justo debajo de la señal de utilidad, que ya existe: `_valorar_regla` dice **qué** reglas
se ignoran, pero nunca **por qué** fallan, que es lo único que permite arreglarlas en vez
de silenciarlas.

**Por dónde.** `_apuntar_aviso()` es el punto único por donde pasan todos: la instantánea
entra ahí, al lado de la prioridad y la caducidad. Guardar los números crudos, no la
frase — la frase ya está.

### 6.4 Evals de Jarvis ●●

**Qué.** Un conjunto de casos («¿qué tengo mañana?» → `calendario`) y una tirada que mide
el acierto al elegir herramienta. A mano o semanal, contra la API real; no en cada push,
que cuesta dinero.

**Por qué.** Está medido y escrito en `docs/JARVIS.md` que el modelo pequeño falla
eligiendo entre herramientas parecidas —pidiéndole leer issues escogía
`add_issue_comment`— y que **ese fallo crece con el catálogo**, que va por 41 herramientas
y no para de crecer. Hoy esa regresión solo se detecta hablándole y notando que hace algo
raro. Además es la medida que falta para tomar la decisión de coste que hoy no se puede
tomar: si `JARVIS_MODEL_ACCION` puede bajar a algo más barato, o si el reparto de modelos
sigue mereciendo la pena.

**Cuidado.** Esto NO va a `tests/backend`: allí el modelo está simulado por `conftest.py`
a propósito, y mezclarlo metería llamadas de pago y fallos intermitentes en la suite que
tiene que poder correr siempre. Es un job aparte, con su propia salida.

### 6.5 El coste de Jarvis, en el panel ●

**Qué.** Guardar el `usage` de cada llamada (entrada, entrada cacheada, salida, modelo) y
enseñar el gasto del mes en el panel ⚙, desglosado por boca: chat, voz, teléfono, resumen
diario.

**Por qué.** Los números que hay en `docs/JARVIS.md` (3.667 tokens de entrada, 94%
cacheado) se midieron **una vez y a mano**. Desde entonces han entrado el streaming, las
frases de relleno, el modo llamada y el teléfono, cada uno con un patrón de gasto
distinto, y la única alarma de coste que existe hoy es la factura. El modo llamada es el
candidato obvio a sorpresa: paga salida por token *y* segundos de ElevenLabs, y encima es
el que más se usa cuando funciona bien.

**Por dónde.** El punto único de salida ya existe (el cierre de `_jarvis_turno` y
`_texto_garantizado`). Las tarifas van en configuración, no en el código: cambian solas.

### 6.6 Copia de seguridad de Supabase ●

Es el punto **5.4**, que sigue pendiente y que en esta ronda sube de prioridad. El motivo
para subirlo: `health_metrics` es el único dato del proyecto que no se puede regenerar, la
ingesta resuelve por upsert `(metric_date, metric_name)` —un cliente que escriba mal pisa
el histórico sin dejar rastro— y ya hay meses de serie detrás. Es la idea menos vistosa de
la lista y la única cuyo coste, si no se hace, es irreversible. El aviso de siempre: el
repositorio es público, así que el destino tiene que ser privado.

### 6.7 El día en una línea de tiempo ●●

**Qué.** Un carril horizontal por día con todo sobre el mismo eje: eventos, sueño,
entrenos, presencia, avisos mandados y acciones de la casa.

**Por qué.** Los datos están todos y cada uno vive en su widget, así que las coincidencias
las tiene que ver el usuario: que se duerme mal las noches después de una cita tarde, que
los días con el PC encendido hasta las dos el sueño se hunde. El motor de conclusiones
cruza **series** (dos métricas a lo largo de semanas); esto cruza **momentos**, que es
justo lo que un cruce estadístico no puede ver.

**Cuidado.** Es la única de las siete que es sobre todo frontend, y `Dashboard.jsx` va por
6.700 líneas. La lógica pura —colocar cada cosa en su carril y su hueco— va a `src/lib/`,
no al componente.

---

## Lo que se ha descartado a propósito

Escrito aquí para no volver a proponerlo dentro de seis meses sin acordarse del motivo:

- **Cruzar los entrenos del Watch con las sesiones de entrenamiento personal**, y la
  previsión de la fecha del próximo cobro (lo que era el punto 6). Descartado en agosto de
  2026: no interesa. La idea era detectar sesiones dadas y no apuntadas —dinero que se
  pierde en silencio— cruzándolas con `extra.workouts`, pero un entreno propio y una sesión
  dada se parecen demasiado vistos desde el reloj, así que habría propuesto y habría habido
  que confirmar una por una.

- **Guardar el historial de conversaciones de Jarvis en el backend.** Vive en
  `localStorage` por decisión, no por pereza: menos estado que mantener y nada que purgar.
- **Un histórico de presencia.** Es el dato más sensible del proyecto y nada de lo que hay
  encima lo necesita: la serie diaria de horas en casa da todo lo que se usa, sin lugares.
- **Interpretar los datos dentro del correo.** Quien lo lee ya es un modelo, y las
  conclusiones viven en `helpers.js` como única fuente de verdad. Portarlas a Python las
  duplicaría en dos lenguajes.
- **Un hilo dentro del backend para los relojes.** Fly escala a cero: sin nadie que llame,
  no hay proceso vivo que mire la hora. El reloj lo pone Home Assistant.
