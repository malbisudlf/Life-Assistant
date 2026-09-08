<!-- Parte de la guía del repositorio. El índice y las reglas que aplican
     SIEMPRE están en CLAUDE.md, en la raíz. -->

## Módulo Salud (Apple Watch)

### Flujo de datos

Dos fuentes de ingesta en paralelo:

1. **Health Auto Export** (app) → `POST /health/ingest` → Supabase — incluye workouts y
   sueño con fases detalladas.
2. **iOS Shortcut "Run Custom Automation"** → `POST /health/ingest/simple` → Supabase —
   métricas del día en tiempo real.

### Configuración de Health Auto Export

- Dos automatizaciones REST API: una para **Health Metrics** y otra para **Workouts**.
- Export Format: JSON v2, Summarize Data: ON, **Batch requests activado** (manda todas
  las métricas en un POST en vez de uno por métrica).
- Sync Cadence: 5 min (pero iOS no garantiza la ejecución — el workaround es un Atajo de
  iOS con 3 horarios fijos al día).
- El sync en segundo plano requiere: Ajustes → General → Actualización en segundo plano →
  Health Auto Export → ON.
- Para datos históricos: cambiar Date Range a "Last 30 Days" y hacer Export Now manual.

Métricas del bulk export: `active_energy`, `apple_exercise_time`, `apple_stand_hour`,
`flights_climbed`, `heart_rate`, `heart_rate_variability`, `resting_heart_rate`,
`respiratory_rate`, `sleep_analysis`, `step_count`, `vo2_max`,
`walking_running_distance`, `walking_heart_rate_average`, `cardio_recovery`,
`time_in_daylight`, `weight_body_mass`, `body_fat_percentage`, `lean_body_mass`,
`resting_energy`, `physical_effort`.

**Nombres reales en Supabase** (el que usa Health Auto Export puede diferir del lógico):
el peso es `weight_body_mass` (NO `weight`); `body_fat_percentage` y `lean_body_mass`
sí coinciden.

### iOS Shortcut "Run Custom Automation"

- **Métricas**: `step_count`, `active_energy`, `exercise_time`, `resting_heart_rate`,
  `heart_rate_variability`, `respiratory_rate`, `vo2_max`, `sleep_analysis`.
- **Formato del body**: iOS Shortcuts serializa las listas como NDJSON (un dict por línea)
  dentro de un único campo `{"metric": "..."}`. El backend lo parsea automáticamente.
- **Filtros de fecha**: `step_count`, `active_energy`, `exercise_time` → *Start Date is
  today*; métricas nocturnas (HRV, FC en reposo, respiración, sueño) → *in the last 2
  days*; `vo2_max` → *in the last 7 days*.
- **Bug conocido**: `respiratory_rate` puede acabar con el mismo valor que
  `heart_rate_variability` si el paso "Get Value from Item from List" queda DESPUÉS del
  Dictionary. Verificar que va antes.
- **Trampa de "Obtener contenido de URL" con POST**: un `Request Body` de tipo JSON **sin
  ningún campo** hace que Atajos construya una petición que muere sola, y el error que
  enseña es `the network connection was lost` — que apunta a la red y no a lo que pasa de
  verdad. La petición no llega a salir del teléfono: en los logs del backend no aparece
  nada, y esa ausencia es justo lo que lo distingue de un problema de URL o de token (una
  ruta mal escrita da 404 y un token malo da 403, pero los dos *llegan*). Se arregla
  añadiendo cualquier campo al cuerpo, aunque el endpoint no lo lea, o cambiando el
  cuerpo a tipo File. Le pasó al Atajo de `/despertar` el 2026-08-05.

  **Y volvió a pasar, esta vez sin que nadie mirara durante tres semanas.** Desde el
  2026-08-17 hay un Atajo (`BackgroundShortcutRunner` en el User-Agent) llamando a
  `POST /health/ingest` con **0 bytes**, decenas de veces al día — más de mil intentos
  contados, todos 400, ninguna fila escrita jamás. Se descubrió persiguiendo otra cosa
  (que no salía el sueño del día). Dos lecciones:
  - **Un 400 repetido no avisa a nadie.** Queda en `app_logs` como WARNING y ahí se
    queda; el canal de averías mira el CI y los crons, no las integraciones del móvil.
    Si una integración deja de entregar, hoy solo se nota por el hueco en los datos.
  - **Para saber quién llama, mira el User-Agent en `app_logs`**: distingue Health Auto
    Export de un Atajo de iOS, que es justo lo que hace falta para saber en qué app del
    teléfono está el fallo.

### Cómo se comprueba que una noche no llegó

`sleep_analysis` puede faltar por dos motivos que desde el dashboard se ven igual (no
hay fila): que el reloj no la haya mandado, o que la mandara a cero y la ingesta la
tirara por `_cero_sin_medida` para no pisar la medida buena. Desde 09/2026 el descarte
se registra en `app_logs` ("métrica(s) descartada(s) por llegar a cero sin medida"), así
que la ausencia de ese aviso significa que el dato no llegó — y entonces el problema
está en el teléfono, no aquí. Las peticiones con 200 no se loguean, así que el contenido
de un lote correcto no queda registrado en ningún sitio.

#### Pendientes del Shortcut

**1. Sueño con fases** — sustituir el paso actual de `sleep_analysis` por un bucle:

1. *Find Health Samples*: Sleep Analysis, Yesterday 20:00 → Today 12:00, **sin Group by**.
2. Variables iniciales: `deep=0`, `rem=0`, `core=0`, `awake=0`.
3. *Repeat with each* item:
   - Get Details → **Value** → fase (Core/Deep/REM/Awake).
   - Get Details → **Duration** (segundos) → /3600 → horas.
   - Si la fase es "Deep" → `deep += horas`; "REM" → `rem += horas`; "Core" →
     `core += horas`; "Awake" → `awake += horas`.
4. `total = deep + rem + core`.
5. Dictionary: `metric=sleep_analysis`, `date=fecha_hoy`, `value=total`, `unit=hr`,
   `extra={deep, rem, core, awake}`.

El backend ya soporta `extra` en `/health/ingest/simple` (sin cambios de servidor) y el
frontend ya usa `extra.deep`/`extra.rem`/`extra.core` para el score y el widget.

**2. Workouts** — añadir después del bucle de sueño:

1. *Find Workouts*: Yesterday 04:00 → Now.
2. `workout_list=[]`.
3. *Repeat with each* workout: Name (tipo), Duration (segundos), Start Date →
   `yyyy-MM-dd`, Active Calories → dict `{name, duration, start, activeEnergy}` → add.
4. Dictionary final: `metric=workouts`, `date=fecha_entreno`, `value=count(workout_list)`,
   `unit=count`, `extra={workouts: workout_list}`.

El widget de bienestar cuenta con `d.extra?.workouts?.length` y "Entrenamientos AW" usa
`w.name`, `w.duration` y `w.start` — la estructura es compatible con ambos.

### Tabla Supabase `health_metrics`

```sql
metric_date  date        -- fecha de la métrica (YYYY-MM-DD)
metric_name  text        -- sleep_analysis, heart_rate, heart_rate_variability,
                         -- step_count, active_energy, workouts...
value        numeric     -- valor principal (horas de sueño, bpm, pasos...)
unit         text        -- unidad
extra        jsonb       -- datos adicionales (fases de sueño, workouts del día...)
UNIQUE(metric_date, metric_name)
```

### Notas técnicas

- **Workouts** llegan en `data.workouts` (no en `data.metrics`) — se guardan como una
  fila por día con `extra.workouts = [array]`. La duración viene en segundos en v2
  (dividir entre 60 para minutos) y las calorías pueden ser `activeEnergy.qty` (objeto)
  o un número directo según la versión.
- **Sleep**: `value` puede ser 0 si Health Auto Export no rellena el campo principal; el
  frontend calcula la duración real desde `extra.asleep` o sumando las fases.
- **Capitalización de los campos**: Health Auto Export no la mantiene entre métricas. Las
  que exporta como rango diario (`heart_rate`) traen `Avg`/`Min`/`Max` con **mayúscula
  inicial** y no tienen `avg`, así que buscar solo la minúscula guardaba `value: None`
  con el promedio entero en `extra`. La extracción prueba las dos formas. Si añades una
  métrica nueva y llega con `value` a null, mira el `extra` de la fila antes que nada:
  el dato suele estar ahí con otro nombre.
- **Extracción de valor acumulativo**: se toma el `max()` de todos los campos no-None
  (`qty`, `sum`, `value`) del punto JSON. Health Auto Export v2 usa `qty` para el total
  diario; `sum` puede llegar como 0 y no debe usarse como valor principal.
- **Unidades de energía**: `active_energy`, `resting_energy` y `basal_energy` se
  guardan **siempre en kcal**. Apple puede exportarlas en kilojulios, así que las dos
  rutas de ingesta pasan por `_normalizar_energia()`, que reconoce la unidad de forma
  laxa (`kJ`, `kj`, `kilojoules`, `kilojulios`…) porque el exportador no garantiza cómo
  la escribe. La conversión va **antes** de la comparación de acumulativas: si no, un
  valor en kJ le gana siempre al mismo dato en kcal solo por la unidad, y como esa
  comparación solo pisa hacia arriba, el número inflado se queda para siempre. Si ves
  energía absurdamente alta en el histórico, divide entre 4,184 antes de creértela y
  mira `docs/BUGS_HISTORICOS.md`. Para reescribir filas ya guardadas está
  `backend/corregir_energia_kj.py` (simulacro por defecto, `--aplicar` para escribir);
  no basta con arreglar la ingesta, esas filas no se corrigen solas.
- **Métricas acumulativas**: nunca se sobreescriben con un valor menor (previene que un
  sync parcial del día borre el total). Sí se sobreescribe si el valor existente es 0.
- **Upsert en lote con `on_conflict`**: ver "Ingesta de salud" en
  `docs/BACKEND_PATRONES.md`, y el bug histórico del 409. *(Esto sustituye al esquema antiguo de
  GET + POST/PATCH por métrica, que se retiró al pasar a lotes.)*
- **`last_sync` en `/health/metrics`**: como el upsert no actualiza `created_at`, si hay
  cualquier fila con `metric_date = hoy` se devuelve `datetime.now()` como `last_sync` en
  vez del `created_at` real.
- **Reenvíos de varios días soportados**: el Shortcut puede mandar `sleep_analysis` (y el
  resto) de los últimos N días en cada sync — cada muestra se procesa con su propio
  `metric_date`, así que cada día es una fila independiente y no pisa otras fechas. Para
  `sleep_analysis` concretamente, antes de escribir se comprueba si la fila existente
  tenía `extra.excluded=true` y, si es así, se preserva — evita que un reenvío "resucite"
  una noche que el usuario había anulado a mano.
- **Scripts de mantenimiento en Supabase**: `backend/.env` local **no contiene**
  `SUPABASE_URL`/`SUPABASE_KEY`. Con el backend en el Green ya no hace falta entrar en
  la máquina: esas dos variables están en el volcado del entorno
  (`~/.life-assistant/backend.env.produccion`, ver `docs/MIGRACION_BACKEND.md`), así que
  un script contra la BD se lanza desde tu propio equipo:
  `set -a && . ~/.life-assistant/backend.env.produccion && set +a && python backend/script.py`.
  Es además la única vía cómoda hoy: en el Green, `docker exec` está bloqueado por el
  `Protection mode` del add-on de SSH.

### Cambio de dispositivo

La tabla `salud_ajustes` (una sola fila, `id = 'actual'`) guarda `cambio_dispositivo`:
la fecha a partir de la cual los datos son del aparato actual. Se fija desde el panel ⚙
(`PATCH /health/ajustes`) y viaja al frontend dentro de `GET /health/metrics`.

**Por qué hace falta.** Las puntuaciones no comparan valores absolutos: comparan cada
día contra la propia historia del usuario — la HRV contra la ventana D-14..D-8, la
respiración contra 30 días, la FC en reposo contra los percentiles de 90. Al cambiar de
reloj las métricas siguen llamándose igual y pareciendo lo mismo, pero las mide otro
sensor con otro algoritmo, así que durante más de un mes se estaría midiendo la
diferencia entre dos fabricantes y leyéndola como fisiología. **El histórico no se borra
ni se toca**: sigue entero en las gráficas, solo deja de servir como referencia.

Respetan el corte `baselinePersonal`, `refHrv` (vía `wellnessHistory({ corte })` y el
widget), `mediaReciente` y el `baseline30` de Dashboard.jsx. Si el corte deja la muestra
por debajo del mínimo, `baselinePersonal` devuelve `null` y quien llama cae al umbral
fijo — que es lo correcto mientras el aparato nuevo no tenga historia propia.

**El widget diario se saltaba el corte, y es el número que se mira todos los días.** El
histórico (`wellnessHistory`) lo pasaba desde el principio, pero en `Dashboard.jsx` la
`baselines` del widget se calculaba con `wellnessBaselines(healthData, todayStr)` sin
`corte`, así que la FC en reposo y la FC caminando se puntuaban contra los percentiles
del reloj anterior. Y la referencia de HRV se calculaba aparte, con
`avg7(wHrvRaw.slice(-14,-7))`: por **número de registros** en vez de por fecha —con la
serie agujereada que deja un mes sin reloj, esas "últimas siete medidas" pueden abarcar
meses— y sin corte, de modo que justo después de cambiar comparaba el HRV nuevo contra
la referencia del viejo. Las dos vías salen ahora de `refHrv()`, en helpers, para que no
vuelva a haber dos reglas para la misma señal. Si añades otro sitio que compare contra
la historia, pásale el corte: el ajuste no sirve de nada si quien puntúa lo ignora.

**El corte se sugiere solo.** `fechaCambioSugerida()` (helpers.js) lo detecta en los
propios datos: un cambio de aparato deja una firma que no se parece a nada más —**varias**
métricas del desglose mueren a la vez mientras **otras siguen llegando**—. Una semana sin
llevar nada las mata todas; una métrica que falla por su cuenta mata una sola. Ninguna de
las dos dispara la sugerencia. Como en `metricasMuertas`, no hay lista de "lo que mide
cada fabricante": lo que se detecta es el corte simultáneo. El panel ⚙ la propone con un
botón «Usar»; decidir sigue siendo del usuario.

**Lo que NO hizo falta tocar**: la detección de "reloj puesto" (`_dias_de_reloj`) se
conforma con que llegue **cualquier** métrica de `_RELOJ_DIA` o `_RELOJ_NOCHE`, y
`heart_rate` / `sleep_analysis` / `resting_heart_rate` los manda cualquier pulsera. El
resumen diario tampoco: ya omite las métricas sin datos.

### Métricas que el aparato no mide

`metricasMuertas()` (helpers.js) distingue dos cosas que el desglose del score pintaba
igual y no lo son: **"hoy no hay dato"** —un hueco, se arregla llevando el reloj— y
**"tu aparato no mide esto"**, que no se arregla nunca. Al cambiar de dispositivo, los
componentes que el Apple Watch *deriva* (horas de pie, minutos de ejercicio,
recuperación cardíaca, FC caminando, luz natural) pasan a la segunda categoría de golpe,
y dejarlos en gris reclamándolos cada día convierte el tooltip en una lista de reproches
imposibles de cumplir.

Se decide **mirando los datos**, no con una lista fija de lo que mide cada fabricante:
así vale para cualquier aparato y las filas reaparecen solas si el usuario vuelve al
anterior. `METRICAS_DEL_DESGLOSE` mapea etiqueta → métricas, y hay un test espejo que
comprueba que sus claves son **exactamente** las etiquetas que `wellnessBreakdown` puede
emitir.

Hay **dos ventanas**, y una métrica muere por la que se cumpla antes:

| | Cuándo | Para quién |
|---|---|---|
| Larga (`METRICA_MUERTA_DIAS`, 14) | Siempre, en cuanto el corte lleva 14 días de recorrido | Todas |
| Corta (`METRICA_MUERTA_DIAS_TRAS_CAMBIO`, 5) | Solo con corte puesto, y solo si la ventana cabe **entera** después de él | Solo las que llegaban a diario antes del corte (`_eraRegular`, ≥50% de los 14 días previos) |

La corta existe porque el cambio de aparato es una **explicación**: una métrica que
llegaba todos los días, que deja de llegar justo el día que cambias de pulsera y sigue
sin llegar cinco días, no es un hueco. Sin esa explicación catorce días son lo mínimo
para no confundir "métrica muerta" con "semana sin llevar el reloj"; con ella, esperar
dos semanas solo sirve para que el desglose pase ese tiempo reclamando datos que ya
sabemos que no van a llegar. La ventana corta **se gana**: las esporádicas —VO₂max,
% grasa, recuperación cardíaca— pueden pasarse cinco días sin dar señal con el aparato
viejo puesto, así que para ellas cinco días no prueban nada y se quedan con los catorce.

### La HRV se puntúa promediada, no día a día

El componente de HRV (12 puntos, el segundo de más peso) compara el valor de **un** día
contra la media de **siete** (D-14..D-8). Esa asimetría es la que convierte el ruido en
puntuación: el numerador se mueve solo y el denominador no, así que cruzar la banda del
±5% depende tanto del azar como de la fisiología. La HRV día a día es ruidosa con
cualquier aparato; con uno que solo exporta tres o cuatro lecturas sueltas al día en vez
de la serie nocturna entera —el caso de Zepp escribiendo en Apple Health— deja de ser una
señal y pasa a ser un sorteo.

La corrección no es tocar los umbrales ni el peso: es **medir los dos lados con la misma
vara**. `HRV_SUAVIZADO_DIAS` (3) promedia el día con sus dos anteriores, la varianza cae
~3× y la comparación vuelve a hablar de recuperación. Vale para cualquier aparato, así
que no hay nada de fabricante que mantener. Dos consecuencias que conviene saber:

- **La tarjeta sigue enseñando el dato del día**; lo promediado es lo que *puntúa*. El
  desglose lo dice (`55ms (media 3d) · ref 50ms`) para que el tooltip no parezca
  contradecir a la gráfica.
- **Un hueco de un día ya no borra el componente**: la media lo cubre con los vecinos.
  Es deseable con una fuente de 3–4 lecturas, pero cambia el fixture de cualquier test
  que use la HRV para provocar un "sin datos" — usa `resting_heart_rate`, que no se
  suaviza.

### Calorías de mantenimiento

`mantenimientoEstimado()` (helpers.js) calcula el gasto real sin fórmulas:

```
TDEE = media de ingesta − pendiente_kg_por_día × 7700
```

(pendiente negativa = adelgazas = gastas MÁS de lo que comes, de ahí el signo). La
ingesta sale de `dietary_energy`, que **cualquier app de registro de comida escribe en
Apple Health** y Health Auto Export exporta; la pendiente del peso, por mínimos
cuadrados sobre todas las pesadas de la ventana — no restando la primera a la última,
porque un solo día con retención en cualquiera de los dos extremos se llevaría el número
por delante.

Mifflin-St Jeor y Katch-McArdle fallan ±300 kcal según lo musculado que esté uno y
cuánto se mueva fuera del gimnasio. Esto no supone nada de eso, pero **exige constancia**:
sin 10 días de ingesta, 5 pesadas y 14 días de recorrido entre la primera y la última,
devuelve `kcal: null` y un campo `falta` que dice qué es lo que hace falta. Un resultado
fuera de 800–6.000 kcal se descarta también: eso es un dato malo (una báscula en libras,
una ingesta a medio registrar), y enseñarlo sería peor que no enseñar nada porque encima
parece medido.

`dietary_energy` está en `CUMULATIVE_METRICS` (se suma comida a comida, un sync de
mediodía no puede pisar el total de la noche) y en `ENERGY_METRICS` (Apple la puede
mandar en kJ).

### Puntuaciones (bienestar y sueño)

**`helpers.js` es la única fuente de verdad de estos umbrales.** Los números de abajo son
una referencia de lectura: si no cuadran con el código, manda el código. No los copies a
ningún otro sitio (así se reintrodujo el bug del tooltip de sueño).

**Bienestar (`wellnessBreakdown` + `scoreFromBreakdown`, normalizado a 100)**:

| Componente | Máx. | Notas |
|---|---|---|
| 😴 Sueño | 25 | ≥7.5h = 25 · ≥7h = 21 · ≥6.5h = 15 · ≥6h = 9 · resto 4 |
| 💪 Entreno | 15 | Diario: gym = 15; si no, ejercicio ≥30min = 9, ≥15min = 5, HRV alta = 3/2/1. Semanal: escalado por `expectedByNow` |
| 🚶 Pasos | 8 | ≥10.000 = 8 · ≥8.000 = 6 · ≥6.000 = 4 · ≥4.000 = 2 |
| 🔥 Energía activa | 5 | ≥600 kcal = 5 · ≥400 = 4 · ≥250 = 3 · ≥100 = 1 |
| 🧍 De pie | 2 | ≥12h = 2 · ≥8h = 1 |
| 🪜 Pisos | 2 | ≥10 = 2 · ≥5 = 1 |
| ❤️ HRV | 12 | Contra la referencia de la semana anterior: ≥105% = 12 · ≥95% = 8 · resto 4 |
| 🫀 FC en reposo | 8 | ≤50 = 8 · ≤55 = 7 · ≤60 = 6 · ≤65 = 4 · ≤70 = 3 · ≤80 = 1 |
| 💓 Recuperación cardio | 5 | Solo si el Watch la reporta |
| 🫁 VO₂max | 6 | **Solo vista diaria** |
| 🏃 FC caminando | 4 | **Solo vista diaria** |
| ⚖️ % Grasa | 4 | **Solo vista diaria** |
| ☀️ Luz natural | 5 | **Solo vista diaria** |
| 🌬️ Respiración | 5 | **Solo vista diaria** |

Las cinco últimas solo entran en la vista diaria porque el Watch las actualiza de forma
esporádica y promediarlas por semana no dice nada. Un componente `sinDatos` queda fuera
de la fracción: no tener un sensor no puntúa como tenerlo y sacar un cero. El score tiene
un tooltip con el desglose por componente (pts obtenidos / máximo + valor). Los entrenos
de la semana se cuentan **desde el lunes**, no en una ventana rodante de 7 días.

**Sueño (`sleepBreakdown` + `sleepScore`)**: duración 40 + profundo 25 + REM 25 +
tiempo despierto 10, más una penalización por hora de acostarse (02:00–05:59 = −15,
01:00 = −10, 00:00 = −5) y un **techo por duración**: ≥8h → 100, ≥7.5h → 82, ≥7h → 68,
resto 52 (dormir poco no puede dar nota alta por muy buenas que sean las fases).
`respiratory_rate` penaliza indirectamente vía `calcRecoveryMod` (hasta −5 pts si la
frecuencia sube >5% sobre la baseline de 30 días).

**Objetivo del usuario**: 4 entrenamientos de gimnasio por semana (registrados en Hevy →
Apple Health).
