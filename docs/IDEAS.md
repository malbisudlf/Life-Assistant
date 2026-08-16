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

---

## 1. El reloj, hasta el final

La detección de uso del reloj vive hoy solo en el correo de datos. El resto del sistema
sigue sin saberlo, y es donde más se nota.

### 1.1 Que el dashboard sepa cuándo no llevaste el reloj ●●

**Qué.** Que los widgets de salud distingan "no hay dato" de "no llevabas el reloj". Una
marca en el panel de estado (junto a "última sync") y, en las sparklines, un hueco
etiquetado en vez de una línea que salta.

**Por qué.** Hoy el dashboard solo dice cuándo fue la última sincronización, que es la
pregunta *del sistema*. La pregunta *del usuario* es otra: "¿por qué mi HRV lleva tres
días plano?". La respuesta ya se calcula en el backend y no llega a la pantalla.

**Por dónde.** `_uso_del_reloj()` ya devuelve la serie de estados; hace falta exponerla en
`GET /health/metrics` (mismo cálculo, misma consulta) y pintarla en `datosSalud`. Ojo con
la regla de siempre: la lógica pura va a `helpers.js`, no a `Dashboard.jsx`.

### 1.2 Que las conclusiones no hablen de tendencias que no existen ●●

**Qué.** Que `healthConclusions` y `healthCorrelations` reciban los días con reloj y
descarten los cruces cuyos grupos se apoyen en días sin medir.

**Por qué.** Es el mismo error que cometió el correo, un piso más arriba y peor: el correo
solo daba una media sin base, pero las conclusiones **afirman**. "Tu HRV ha bajado un 8%"
cuando la mitad de la ventana no se midió no es un matiz, es una frase falsa. `minPorGrupo`
protege del tamaño de la muestra, no de su procedencia.

**Por dónde.** Depende de 1.1 (que el dato llegue al frontend). Después es un filtro en
`pairByDate`/`splitCompare`.

### 1.3 Avisar de que te lo has dejado quitado ●

**Qué.** Un recordatorio que salte si el reloj lleva N noches sin señal, o si a la hora de
acostarse no ha habido señal en toda la tarde (se quedó en el cargador).

**Por qué.** El dato perdido no se recupera: una noche sin medir es una noche que ya no
existirá en ningún histórico. El aviso vale más *antes* de dormir que el diagnóstico
después.

**Por dónde.** Toda la infraestructura está: `jarvis_recordatorios` + el tick de HA. Lo
único nuevo es la condición. Y la regla que ya se aplica en todo el proyecto: **un día sin
datos de NINGUNA fuente no dispara el aviso** — ahí no se sabe si fue el reloj o la
sincronización, y avisar sobre un "no lo sé" es cómo se pierde la confianza en los avisos.

### 1.4 Puntuación de bienestar consciente de su propia cobertura ●●

**Qué.** Que `wellnessBreakdown` marque el día como "puntuación parcial" cuando los
componentes ausentes lo son por falta de reloj, y que la sparkline de evolución lo pinte
distinto de un día malo.

**Por qué.** Un componente `sinDatos` ya queda fuera de la fracción, así que la nota no se
hunde — pero tampoco avisa de que está midiendo otra cosa. Un 78 sobre nueve componentes y
un 78 sobre cuatro no son el mismo 78, y la sparkline los pinta a la misma altura.

---

## 2. Salud: de umbrales fijos a tu propia línea base

### 2.1 Baselines personales en vez de números redondos ●●●

**Qué.** Que los umbrales de `wellnessBreakdown` salgan de percentiles del propio
histórico (p. ej. FC en reposo: comparar contra tu p25/p75 de 90 días) en vez de contra
constantes.

**Por qué.** "FC en reposo ≤50 = 8 puntos" premia la genética, no el progreso. Alguien con
una FC basal de 62 nunca sacará esos puntos por mucho que mejore, y alguien con 48 los saca
durmiendo mal. Lo que interesa medir es el movimiento respecto a uno mismo, que es
exactamente lo que ya hace el componente de HRV (referencia de la semana anterior) y lo que
no hacen los demás.

**Coste real.** La comparación entre días deja de ser estable: la misma jornada puntúa
distinto según la ventana. Hay que fijar la baseline por día (como ya hace
`wellnessHistory` anclando la referencia de HRV a D-14..D-8) o el histórico se vuelve
irreproducible.

### 2.2 Firma de "algo va mal" ●●

**Qué.** Detectar la combinación clásica —FC en reposo arriba, HRV abajo, frecuencia
respiratoria arriba, todo a la vez respecto a la baseline— y decirlo antes de que se note.

**Por qué.** Por separado, cada una de las tres se mueve por ruido a diario y no significa
nada; juntas y en la misma dirección son la señal más fiable que da el Watch. El motor de
cruces (`_CRUCES`) ya sabe cruzar dos series: esto es un cruce de tres con una regla de
dirección.

**Cuidado.** Es justo el tipo de conclusión que no se puede dar con `n` bajo ni con días
sin reloj de por medio (ver 1.2). Si no hay base, la conclusión es "no hay base".

### 2.3 Días atípicos, marcados en el correo ●

**Qué.** Una línea por métrica que se salga de ±2σ de su propia ventana de 30 días.

**Por qué.** El correo manda hoy 19 métricas por 30 días: unos 570 números. Quien lo lee
tiene que encontrar lo raro leyéndolo todo. Marcar los atípicos no interpreta nada (sigue
siendo dato crudo, que es la regla del correo) y convierte una lectura completa en una
mirada.

**Por dónde.** `_brief_salud()`, junto a `_ventana()`. Es aritmética sobre datos que ya
están cargados en memoria: cuesta cero viajes de red.

---

## 3. El correo y quien lo lee

### 3.1 Un informe semanal, con la ventana larga ●●

**Qué.** Los domingos, un correo aparte con 90 días de ventana: tendencias, cruces con
`HEALTH_MIN_MUESTRA_PATRONES`, entrenos por semana, dinero del entrenamiento personal.

**Por qué.** El correo diario tiene una ventana de 30 días porque es lo que sirve para
decidir el día de hoy. Pero las cosas que de verdad cambian una rutina se ven en meses, y
hoy solo se pueden mirar abriendo el modal de patrones del dashboard — es decir, solo si a
uno se le ocurre mirar.

**Por dónde.** `construir_brief()` con la ventana parametrizada y otra entrada en la puerta
idempotente (`brief_envios` con clave semanal). El disparador puede ser el mismo tick de HA.

### 3.2 Qué ha cambiado desde ayer ●●

**Qué.** Una sección corta al principio: lo que se movió respecto al correo de ayer
(eventos nuevos o cancelados, métricas que cruzaron un umbral, entregas que se acercan).

**Por qué.** El correo diario es idéntico al 90% en días consecutivos. Lo que hace falta
leer entero es el 10% restante, y hoy hay que releerlo todo para encontrarlo.

**Coste real.** Obliga a guardar el brief de ayer, que es estado nuevo (una fila más en
`brief_envios`, no una tabla). Estado que hay que purgar, y hasta ahora el proyecto ha
evitado guardar cosas a propósito.

### 3.3 Adjuntar el JSON del brief ●

**Qué.** El mismo `construir_brief()` como adjunto `.json`, además del texto.

**Por qué.** El texto está pensado para que lo lea un modelo *y* una persona, y esa doble
función le pone un techo: cualquier dato que solo sirva a la máquina se queda fuera para no
ensuciar la lectura. Con el adjunto no hay que elegir.

---

## 4. Jarvis

### 4.1 Que sepa diagnosticarse ●

**Qué.** Una herramienta que lea `GET /logs` y el estado de las integraciones, para poder
responder a "¿por qué no me llegó el correo?" o "¿por qué no hay datos de ayer?".

**Por qué.** Toda la información existe (la tabla `app_logs`, `brief_ajustes`, la última
escritura de cada métrica) y no hay ninguna forma de preguntarla hablando. Es además la
pregunta más frecuente que se le puede hacer a un asistente personal que falla de vez en
cuando: no "qué tiempo hace", sino "qué te ha pasado".

**Cuidado.** Los registros pueden llevar detalle de errores; ahí la regla del proyecto es
que el detalle se queda en el servidor. Devolver nivel, ruta y recuento, no cuerpos.

### 4.2 Que hable primero, con presupuesto ●●

**Qué.** Que el tick de HA le dé a Jarvis la oportunidad de decidir si hay algo que decir
(máximo uno al día, y solo si supera un listón claro: una entrega mañana sin haberla
tocado, tres noches sin reloj, un cobro pendiente muy por encima de lo habitual).

**Por qué.** Hoy Jarvis solo habla si le hablas, salvo los recordatorios que tú mismo le
pusiste. Un asistente que solo contesta obliga a acordarse de preguntar, que es justo lo
que no funciona.

**Cuidado.** Es la idea con más potencial de volverse insoportable de toda la lista. El
listón tiene que estar en el código como una regla explícita, no en el criterio del modelo,
o acabará mandando avisos porque sí. Y con un interruptor, como el resumen diario.

### 4.3 Destilar la memoria sola ●●

**Qué.** Que al cerrar una conversación larga se extraigan los hechos nuevos y se guarden
en `jarvis_memoria` sin que el modelo tenga que acordarse de llamar a `recordar`.

**Por qué.** Guardar por iniciativa propia funciona a ratos: el modelo recuerda hacerlo
cuando el hecho es evidente y lo olvida cuando está metido en otra cosa, que es cuando
aparecen los hechos que valen. Un paso aparte al final del turno no compite con la tarea.

**Coste real.** Una llamada más por conversación. Solo compensa disparándolo por longitud
de la conversación, no en cada turno.

---

## 5. Operación: que el sistema se vigile a sí mismo

### 5.1 Vigilante de ingesta ●

**Qué.** Si no entra ningún dato de salud en más de N horas, un `logger.error()` (que ya
persiste en `app_logs` y sale en el panel de ajustes) y, pasado más tiempo, un correo.

**Por qué.** Es el fallo que más veces ha ocurrido en este proyecto y siempre se ha
descubierto tarde y de casualidad: el 409 del upsert, el 400 del envoltorio, el JWT
caducado del agente. Los tres tenían en común que **el sistema seguía respondiendo que todo
iba bien**. Nadie vigila la ausencia salvo que se le pida expresamente.

**Por dónde.** El tick de HA otra vez: ya pasa cada 5 minutos y ya sabe mirar la hora.

### 5.2 `GET /salud/diagnostico` ●

**Qué.** Un endpoint que responda, por métrica: último `metric_date`, última escritura,
qué fuente la escribió y cuántos huecos tiene en 30 días.

**Por qué.** Cada vez que ha habido un problema de datos, el diagnóstico ha sido el mismo
trabajo manual: mirar la tabla, contar días, comparar nombres, deducir la fuente. Es
exactamente lo que se automatiza bien, y encima es lo que necesita 4.1 para poder
contestar.

### 5.3 Copia de seguridad de Supabase ●●

**Qué.** Un volcado periódico de `health_metrics`, `training_*` y `jarvis_memoria` a un
sitio que no sea Supabase.

**Por qué.** Es el único dato del proyecto que no se puede regenerar. El calendario está en
Outlook, la configuración en el `.env`, el código en GitHub; el histórico del Watch existe
en un solo sitio, y con la ingesta resolviendo por `(metric_date, metric_name)`, un fallo
que escriba mal lo pisa sin dejar rastro.

**Cuidado.** El repositorio es público. El destino tiene que ser privado, y eso ya no es
"un workflow y ya".

---

## 6. Entrenamiento

### 6.1 Cruzar los entrenos del Watch con las sesiones cobradas ●

**Qué.** Marcar en el widget de entrenamiento personal las sesiones que tienen un workout
del Watch a esa hora, y avisar de los workouts con pinta de sesión que no están registrados.

**Por qué.** Las sesiones se apuntan a mano y se cobran de cuatro en cuatro: una que se
olvide es dinero perdido, silenciosamente. El Watch ya guardó la prueba de que ocurrió, en
`extra.workouts` de `health_metrics`, con fecha y hora.

**Cuidado.** Un entreno propio y una sesión dada se parecen mucho vistos desde el reloj.
Esto **propone**, nunca registra solo — la misma frontera que ya rige `sugerencia_evento()`
y `crear_evento` en Jarvis.

### 6.2 Previsión de cobro ●

**Qué.** "Al ritmo de las últimas semanas, el próximo cobro cae alrededor del día X."

**Por qué.** Es aritmética sobre datos que ya están en `/training/summary` y responde la
única pregunta que el widget hoy no responde: cuándo, no cuánto.

---

## Lo que se ha descartado a propósito

Escrito aquí para no volver a proponerlo dentro de seis meses sin acordarse del motivo:

- **Guardar el historial de conversaciones de Jarvis en el backend.** Vive en
  `localStorage` por decisión, no por pereza: menos estado que mantener y nada que purgar.
- **Un histórico de presencia.** Es el dato más sensible del proyecto y nada de lo que hay
  encima lo necesita: la serie diaria de horas en casa da todo lo que se usa, sin lugares.
- **Interpretar los datos dentro del correo.** Quien lo lee ya es un modelo, y las
  conclusiones viven en `helpers.js` como única fuente de verdad. Portarlas a Python las
  duplicaría en dos lenguajes.
- **Un hilo dentro del backend para los relojes.** Fly escala a cero: sin nadie que llame,
  no hay proceso vivo que mire la hora. El reloj lo pone Home Assistant.
