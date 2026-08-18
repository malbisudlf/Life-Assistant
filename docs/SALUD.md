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
  `SUPABASE_URL`/`SUPABASE_KEY` (solo están en los secrets de Fly). Para ejecutar un
  script contra la BD: mételo en `backend/` (se copia al contenedor en `fly deploy`) y
  lánzalo con
  `fly ssh console -a backend-tender-glow-160 -C "python3 /app/script.py"`.
  `fly sftp put` no funciona bien en Windows (problema de rutas).

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
