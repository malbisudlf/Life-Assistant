<!-- Parte de la guía del repositorio. El índice y las reglas que aplican
     SIEMPRE están en CLAUDE.md, en la raíz. -->

## Backend: patrones que hay que conocer

- **Cliente HTTP saliente**: TODO lo que sale del backend va por `http` (la sesión de
  módulo), nunca por `requests.get` suelto. Impone `HTTP_TIMEOUT` por defecto y
  reutiliza conexiones. Sin timeout, una llamada colgada retiene un hilo del pool de
  FastAPI para siempre. Los tests mockean `main.http`, no `main.requests`.
- **Interruptores booleanos por entorno**: siempre con `_flag("NOMBRE")`, nunca con una
  comparación a mano. Normaliza espacios y mayúsculas y acepta `0`, `false`, `no`, `off`
  y la cadena vacía como apagado. El patrón que había antes
  (`os.getenv(...) not in ("0", "false", "False")`) dejaba la función ENCENDIDA si
  escribías `FALSE`, `no` u `off`, y estaba repetido en once sitios. Todos esos flags
  existen para apagar algo que molesta (avisos que siguen saliendo, un vigilante que no
  para), así que fallar hacia "encendido" es fallar en la única dirección que importa.
  La excepción deliberada es `TRUST_FORWARDED_FOR`, que usa una lista blanca estricta
  (`in ("1", "true", "yes")`) porque es un opt-in de seguridad: ahí lo correcto es que
  cualquier valor raro deje la protección puesta, no que la quite.
- **Token de Graph**: una renovación puede traer `access_token` sin `refresh_token`; el
  protocolo permite no rotarlo. `save_token_data()` conserva el anterior cuando no llega
  uno nuevo. Escribir ese `None` encima mataba la conexión de Outlook de forma
  permanente y silenciosa: el siguiente `get_valid_token()` se encontraba
  `if not refresh_token: return None` y el calendario se quedaba vacío sin más salida
  que rehacer `/auth/login` a mano.
- **Dependencias opcionales**: lo que la documentación llame opcional no puede
  impedir arrancar. El cliente de OpenAI se crea de forma perezosa y devuelve 503
  si falta la configuración, nunca revienta el import.
- **Ideas → evento sugerido**: `extract_idea_from_text()` le pasa al modelo la fecha
  de hoy (si no, no puede resolver "el martes" o "mañana") y le pide también
  `fecha`/`hora` cuando la nota señala una cita. Lo que devuelve el LLM **nunca** se
  manda a Graph sin pasar por `sugerencia_evento()`, que valida que la fecha/hora
  tengan forma real (descarta cosas como `2026-02-30`) y exige un título no vacío.
  El evento no se crea solo: el endpoint solo devuelve `evento_sugerido` y el
  frontend lo ofrece como chip — crear el evento lo dispara el usuario. `/ideas/audio`
  (Whisper) y `/ideas/text` comparten la extracción y el guardado.
- **Zonas horarias**: Microsoft Graph devuelve fechas con nombres de zona de Windows
  ("Romance Standard Time"). `normalize_graph_dt()` + `WINDOWS_TZ_MAP` las convierten
  SIEMPRE a ISO UTC con sufijo `Z`. La zona del usuario es `TIMEZONE`/`LOCAL_TZ`
  (env, default `Europe/Madrid`) — úsala en vez de hardcodear zonas. Cualquier
  fecha nueva que salga de la API debe ser UTC-Z.
- **Kit self-hosted**: la instancia se personaliza por env — `TIMEZONE`,
  `CLASSES_CALENDAR`, `CORS_ORIGINS`, `HOME_ADDRESS`, `WEATHER_LAT`/`WEATHER_LON`
  (backend, ver `backend/.env.example` y `backend/check_config.py`) y `VITE_API_URL`,
  `VITE_HA_URL`, `VITE_HA_DASHBOARD_PATH`, `VITE_ENTREGAS_MARKER` (frontend).
  La guía de despliegue para terceros es `docs/DESPLIEGUE.md`: si añades una
  variable o migración, actualízala. No reintroduzcas valores personales
  hardcodeados en el código.
- **Tokens OAuth de Graph** se persisten en la tabla `oauth_tokens` de Supabase
  (`supabase/migrations/20260607_oauth_tokens.sql`). Antes se guardaban en
  `backend/.token`, pero ese fichero se perdía en cada `fly deploy` (el filesystem del
  contenedor se reconstruye desde la imagen) → forzaba reautenticación constante y
  desconexiones del calendario "cada dos por tres". `backend/.dockerignore` excluye
  `.env`/`.token`/`venv`/`__pycache__` de la imagen para que nunca se cuele un fichero
  local de desarrollo en producción. `get_valid_token()` renueva con el refresh token
  de forma transparente. Además hay una **copia en memoria** (`_token_cache`): antes
  cada endpoint de calendario leía la tabla, así que una carga del dashboard gastaba
  dos viajes de red en releer un token que no había cambiado, y el sondeo de HA sumaba
  otro por minuto. La copia se rellena al leer, se actualiza en `save_token_data()` y
  se tira si el refresh falla. Si tocas la escritura del token, mantén esa invalidación
  (y resetéala en `reset_state` de los tests, como el resto de estado de módulo).
  **`SCOPES` incluye `Calendars.ReadWrite`** (necesario para crear/editar eventos): si
  cambias los scopes hay que **reautenticar** pasando otra vez por `/auth/login` →
  `/auth/callback`, porque el refresh token guardado está ligado al consentimiento
  anterior.
- **Cliente MSAL compartido** (`_msal_app()`, perezoso): construir un
  `ConfidentialClientApplication` descubre la autoridad por red, y antes se construía
  de cero en `/auth/login`, `/auth/callback` y en cada renovación de token.
- **Cola de jobs** (máquina de estados estricta, transiciones vía PATCH condicional de
  Supabase para que sean atómicas):
  `pending → claimed → running → done | failed`, y `failed → pending` con `retry`
  (incrementa `attempt`, máx. `MAX_JOB_ATTEMPTS=3`). El claim usa
  `?status=eq.pending` como guard: si devuelve 0 filas, otro worker ganó la carrera.
  `dedupe_key` es único: el upsert con `resolution=merge-duplicates` devuelve 0 filas
  en conflicto y entonces se recupera el job existente. `GET /jobs/pending` es
  lo que sondea `agent.py`: por eso el agente NO tiene `SUPABASE_KEY` en su `.env` — es
  la única consulta que se lo exigía, y la service_role key salta toda la RLS de la
  base. Si añades un endpoint nuevo que el agente necesite, que pase por el backend
  en vez de darle más alcance de Supabase directo.
  Los seis endpoints del ciclo de vida de un job (`/jobs/pending`, `claim`, `start`,
  `finish`, `POST .../events` y `/agents/heartbeat`) van con `Depends(verify_agente)`:
  aceptan `AGENT_TOKEN` **o** el JWT del usuario (el dashboard también los consulta).
  Los demás siguen con `verify_token` a propósito — el alcance de ese token es la cola
  de jobs, no la sesión entera, y vive en un `.env` de un PC que arranca solo. Si
  amplías `verify_agente` a un endpoint nuevo, añádelo a
  `TestAuthAgente::test_cubre_todo_lo_que_usa_el_agente`.
- **Ingesta de salud**: las métricas acumulativas (`step_count`, `active_energy`,
  `basal_energy`, `resting_energy`, definidas en `CUMULATIVE_METRICS`, constante de
  módulo compartida por las dos rutas de ingesta) solo se sobreescriben si el valor
  nuevo es MAYOR (llegan snapshots parciales a lo largo del día). Energía en kJ se
  convierte a kcal (÷ 4.184, `ENERGY_METRICS`). `sleep_analysis` guarda `sleep_start`
  ("HH:MM") en `extra` y respeta el flag `excluded` (noches anuladas por el usuario).
  Escritura en **dos viajes por lote**, no uno por métrica: `_existentes_por_clave()`
  trae de golpe lo ya guardado para las fechas/nombres del lote y `_guardar_metricas()`
  hace un único upsert (`resolution=merge-duplicates`, aprovechando el
  `unique(metric_date, metric_name)` de la tabla) con el resto. Un GET+POST por
  métrica aquí son 60-90 viajes secuenciales a Supabase por sincronización del
  Watch — no lo reintroduzcas.
  **Un 0 en una métrica de sensor no se guarda** (`METRICAS_SIN_MEDIDA_EN_CERO` +
  `_cero_sin_medida()`, compartidos por las dos rutas): en HRV, FC, respiración, VO₂max,
  peso o sueño el 0 es "no se midió", y como el upsert resuelve por
  `(metric_date, metric_name)` esa fila **pisa la medida buena del día** y la deja
  irrecuperable. Es el espejo por nombre de la columna `cero_es_dato` de
  `_BRIEF_METRICAS`, y hay un test que comprueba que las dos no se desincronizan. En las
  acumulativas el 0 sí es un dato (un día de 0 pisos ocurrió) y se guarda. `value` a
  `None` también se conserva: ahí la medida suele estar en `extra` con otro nombre.
  La URL del upsert sale de `HEALTH_UPSERT_URL` y **lleva
  `?on_conflict=metric_date,metric_name`**: PostgREST resuelve `merge-duplicates`
  contra la CLAVE PRIMARIA salvo que se le nombre otra restricción, y aquí la primaria
  es `id` (uuid nuevo en cada inserción, que no colisiona nunca), así que sin ese
  parámetro cualquier fila repetida acaba en un 409 que tumba el lote entero. Mismo
  criterio para cualquier tabla cuya unicidad real no sea su clave primaria.
  Y un fallo de escritura **corta con 502**: los clientes son máquinas (Health Auto
  Export, un Shortcut de iOS) que no miran el cuerpo de la respuesta, así que un 200
  `{"ok": true}` con el error escondido dentro es indistinguible de haber sincronizado.
  Por lo mismo, **una sincronización de la que no se reconoce nada responde `ok: false`**
  con `_resumen_cuerpo()` (claves recibidas y tamaños, nunca valores) en el cuerpo y en
  el registro: un JSON bien formado con la estructura equivocada —un `{}`, el envoltorio
  de otro exportador— pasaba todas las validaciones y salía como `200 {"upserted": 0}`.
  Ojo con la condición: se mira lo RECONOCIDO (`grouped_metrics`/`samples`), no lo
  escrito, porque un lote de acumulativas que ya tenían un valor mayor escribe cero y es
  correcto.
  El cuerpo pasa antes por `_normalizar_lote_salud()`, que acepta la **lista de lotes**
  que manda el exportador con "Batch requests" activado además del `{"data": {...}}`
  suelto. Lo que no se reconozca sigue saliendo por un 400 — pero ese 400 **registra la
  forma de lo que llegó** (tipo, tamaño, content-type; los primeros bytes solo si ni
  siquiera era JSON): el detalle solo viajaba en la respuesta HTTP, que la app del móvil
  no enseña, y eso tapó semanas de sincronizaciones perdidas. Lo que no se tolera a
  propósito es `metrics` en la raíz sin `data`: esa forma no la manda nadie y sigue
  saliendo por el aviso de estructura desconocida.
  Ese aviso dice además **quién lo mandó** (`_cliente_http`, el `User-Agent` recortado) y
  separa el **cuerpo vacío** (0 bytes) del envoltorio ininteligible, en las dos rutas de
  ingesta. Las dos cosas son la misma lección un paso más atrás: al endpoint apuntan
  Health Auto Export y varios Atajos **con el mismo token y la misma URL**, así que "llega
  basura a `/health/ingest`" no se puede accionar sin saber cuál de los tres hay que
  abrir. Y los dos casos llevan a sitios opuestos: un envoltorio nuevo se arregla aquí,
  enseñándoselo al endpoint; 0 bytes es un cliente que ni llegó a construir el JSON —la
  trampa conocida del "Obtener contenido de URL" con un `Request Body` JSON sin campos, o
  una automatización REST a medio configurar— y **ninguna tolerancia del servidor lo va a
  arreglar, porque no ha llegado ni un dato**. Sigue siendo 400 en los dos casos: ese
  envío no guardó nada. El 400 de `/health/ingest/simple` no registraba nada de esto, solo
  el `→ 400` del middleware, que es exactamente lo que hizo durar semanas el del
  envoltorio.
- **Flags de control del PC (poll de HA, mismo patrón que WOL)**: son flags globales
  en memoria que el dashboard marca y HA limpia al sondearlos. Se resetean en cold
  start de Fly (aceptable). No los conviertas en estado persistente sin pensar en el
  poll de HA.
  - `_wol_pending` → `/wake-pc` marca, `/ha/wol-pending` recoge (magic packet).
  - `_agent_relaunch_pending` → `/relaunch-agent` marca, `/ha/agent-relaunch-pending`
    recoge. Para relanzar el agente efímero por SSH cuando el PC ya está encendido.
  - `_pc_power_action` (`"shutdown"|"suspend"|None`) → `/shutdown-pc` / `/suspend-pc`
    marcan, `/ha/pc-power-pending` recoge. Apagar/suspender no pasa por el agente: HA
    lo ejecuta por SSH directo (el agente es efímero y ya terminó).
- **Presencia (HA → backend)**: es el **único punto donde HA empuja un dato** en vez de
  sondear, porque aquí el que sabe es HA (tiene el `device_tracker` de la app del móvil)
  y el que necesita saber es el backend, que no puede llamar a HA (vive en la LAN, mismo
  mixed content que obligó a que el WOL pasara por aquí). `POST /ha/presencia`
  (`HA_POLL_TOKEN`) guarda zona, `en_casa` y coordenadas en la tabla `presence` — **una
  sola fila que se sobreescribe, sin histórico a propósito**: un registro de por dónde
  has pasado es el dato más sensible del proyecto y nada de lo que hay encima lo
  necesita. No es un flag en memoria como el WOL: aquellos son ÓRDENES pendientes
  (perderlas en un cold start cuesta volver a pulsar un botón) y esto es ESTADO
  (perderlo deja al dashboard sin saber dónde estás hasta que te muevas de zona). Con
  copia en memoria (`_presencia_cache`), igual que el token de Graph y por lo mismo:
  `/weather` y `/maps/departure` lo consultan en cada carga.
  **Un dato caducado no se usa**: `presencia_vigente()` devuelve `None` pasados
  `PRESENCE_TTL_MINUTES`, porque dar el clima de donde estabas hace horas como si fuera
  el de donde estás es peor que caer al default — la misma regla de siempre, "no lo sé"
  no puede disfrazarse de dato. Por eso HA tiene que mandar **también un aviso periódico**,
  no solo los cambios de zona: sin él el TTL no puede distinguir "sigues en casa" de
  "HA se cayó". `GET /presencia` (JWT) sí devuelve lo caducado, marcado, para el panel
  de estado.
- **Serie diaria de presencia**: cada aviso acumula el tramo transcurrido en la métrica
  `time_at_home` de `health_metrics` (`value` = horas en casa, `extra.fuera` = horas
  fuera). Va ahí y no a una tabla propia para que entre sola en `/health/metrics` y con
  ella en el motor de correlaciones del frontend. Solo se guardan HORAS, nunca lugares.
  Dos cosas que no se pueden relajar: el tramo se **trocea por día local**
  (`_tramos_por_dia`) porque el que cruza la medianoche es el de la noche, justo el que
  más pesa al cruzarlo con el sueño; y un hueco de más de `PRESENCE_MAX_GAP_HOURS` **se
  descarta** en vez de imputarse entero a la última zona conocida. Del lado del
  frontend, `_serieFuera` exige `COBERTURA_PRESENCIA` horas contabilizadas en el día: si
  HA estuvo caído media jornada, ese día sale bajo en las dos columnas y sin el filtro
  se colaría como "día tranquilo en casa", que es lo contrario de lo que dice el dato.
- **Clima**: `/weather` (Open-Meteo, gratis, sin API key) resuelve la ubicación en tres
  escalones, de más a menos fiable: lo que mande el dispositivo (`?lat&lon`,
  geolocalización del navegador) → la presencia vigente que reporta HA → `WEATHER_LAT/LON`.
  El cálculo de salida (`/maps/departure`) hace lo mismo con `origin`, con fallback a
  `HOME_ADDRESS`. Por eso `origin` **no puede tener `HOME_ADDRESS` como default del
  modelo**: "no me mandaron origen" y "me mandaron justo mi casa" llegarían
  indistinguibles y la presencia nunca entraría en juego.

- **De quién es cada fila** (columna `health_metrics.fuente`, `FUENTE_AUTO_EXPORT` /
  `FUENTE_ATAJO` / `FUENTE_PRESENCIA`): las dos ingestas escriben en la MISMA tabla y
  hasta ahora sin firma, así que "¿cuál de las dos ha dejado de correr?" se deducía a ojo
  comparando qué métricas faltaban. **Nullable a propósito**: lo ya guardado no se puede
  atribuir, y rellenarlo con una suposición sería inventarse el dato. Se lee en
  `GET /health/diagnostico`, que es lo que antes solo se veía mirando la tabla en crudo:
  huecos INTERCALADOS (los de antes del primer día medido no son huecos, es la prehistoria
  de la métrica), filas de relleno que no son medidas (los ceros del Atajo, misma regla
  que el uso del reloj) y la última escritura de cada cliente.


- **Peticiones a Supabase en paralelo**: cuando dos consultas no dependen entre sí
  (`/training/summary` pide el último pago y las sesiones a la vez con
  `ThreadPoolExecutor`), lánzalas en paralelo en vez de en serie — se ejecuta en cada
  carga del dashboard, con el arranque en frío de Fly por delante. Si una depende del
  resultado de otra, en serie.
- **Registro persistente (`app_logs`)**: `logger.error()`/`warning()` van a stdout Y a
  Supabase, porque el stdout se lo lleva la máquina de Fly al escalar a cero — que es
  justo por lo que el 409 de la ingesta de salud estuvo días registrándose sin que nadie
  lo viera. Lo hace `RegistroSupabase`, un `logging.Handler` enganchado al logger que ya
  existía: **para que algo nuevo quede registrado basta con llamar a `logger.error()`,
  no hay que tocar nada más**. Reglas que no se pueden relajar, todas por lo mismo
  (registrar no puede tumbar ni frenar una petición): la petición solo encola en memoria
  y escribe un hilo de fondo en lotes; la cola está acotada (`LOG_QUEUE_MAX`, tira las
  viejas y deja constancia de cuántas); y un fallo escribiendo el registro **se avisa por
  `stderr`, nunca por `logger`** — por `logger` se realimentaría con el error de escribir
  el error. Se persiste WARNING+ (`LOG_PERSIST_LEVEL`); bajar a INFO llena la tabla de
  ruido. En los tests va desactivado (`LOG_PERSIST=0` en `conftest.py`): encendido, el
  hilo colaría POSTs a `app_logs` en el `MockRouter` de cualquier test que registre algo.
- **Middleware `registrar_peticiones`**: la otra mitad de "logs para todo", la que no se
  puede escribir a mano en 60 endpoints. Registra 5xx, 4xx (menos el 401, que es el JWT
  caducando y el frontend ya lo resuelve), excepciones no controladas con su traza y las
  peticiones que pasan de `LOG_SLOW_MS`. Guarda `"MÉTODO /ruta"` **sin query string**: por
  ahí viajan `HEALTH_INGEST_TOKEN` y `HA_POLL_TOKEN` (soportados por compatibilidad con
  las integraciones ya desplegadas) y no pueden acabar en una tabla. Esa ruta viaja en un
  `ContextVar` hasta el handler, así que cada entrada dice en qué petición pasó.
- **`GET /logs`** (JWT) lo consume el panel de ajustes. Vuelca la cola antes de leer: se
  abre el panel PORQUE algo acaba de fallar, y si no, lo recién ocurrido tardaría
  `LOG_FLUSH_SECONDS` en aparecer. `nivel` va con lista blanca (`NIVELES_LOG`), no con
  regex: se interpola en la URL de Supabase (invariante 6 de `CLAUDE.md`).
