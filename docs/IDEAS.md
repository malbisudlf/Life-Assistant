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
exactamente lo que se automatiza bien.

**Qué queda tras el 4.1.** La herramienta `diagnostico` de Jarvis ya da la mitad: días sin
dato de cada métrica, fallos por origen y qué está configurado. Falta lo que solo se ve
mirando la tabla en crudo — QUÉ FUENTE escribió cada fila (Health Auto Export o el Atajo) y
los huecos intercalados. Eso es lo que distingue "el Atajo dejó de correr" de "el reloj no
se llevó", que hoy sigue habiendo que deducirlo.

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
