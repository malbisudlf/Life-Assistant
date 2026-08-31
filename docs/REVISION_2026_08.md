# Revisión general — agosto de 2026

Repaso completo del código (backend, frontend, agente, despliegue y CI) más una tanda de
ideas nuevas. No es la revisión nocturna automática (esa es `docs/REVISION_NOCTURNA.md` y
mira solo los commits del día): esto es la foto entera, del tipo que se hace cada cierto
tiempo.

Cada hallazgo lleva **dónde está**, **qué pasa** y **por qué importa**. Los que no tienen
consecuencia visible hoy lo dicen: un fallo latente es útil escribirlo, pero mentir sobre
su gravedad es la forma más rápida de que nadie vuelva a leer una lista como esta.

Las ideas van al final, con **qué**, **por qué** y **por dónde se empieza**, y el mismo
esfuerzo orientativo que usa `docs/IDEAS.md`: ● pequeño, ●● medio, ●●● grande.

---

## Estado de partida

Todo verde antes de tocar nada, con la verificación obligatoria de `CLAUDE.md`:

| Comprobación | Resultado |
|---|---|
| `npm run lint` | 0 errores, 0 warnings |
| `npm test` | 213 tests, 3 ficheros |
| `pytest tests/backend` | 1.023 tests |
| `npm run build` | 408 kB (118 kB gzip) |

Es decir: **nada de lo que hay debajo lo caza el CI hoy**. No es un reproche a los tests
—cubren muchísimo— sino la razón de que una revisión así siga haciendo falta: casi todo lo
que sigue son huecos entre dos piezas que por separado están bien probadas.

---

## Parte 1: fallos de corrección

### 1.1 Jarvis lee la plusvalía cien veces más grande (alta)

`backend/main.py:10045` y `:10054`

`_j_finanzas()` devuelve al modelo `plusvalia_pct` y `rentabilidad_anual` juntos, y cierra
con esta nota:

```python
"unidades": "Euros. Las rentabilidades son fracciones: 0.0523 = 5,23 %.",
```

Pero las dos cosas no vienen en la misma unidad. `_finanzas_cuenta()` calcula
`plusvalia_pct` **ya en porcentaje**:

```python
pct = round(plusvalia / base * 100, 2) if plusvalia is not None and base else None
```

mientras que `rentabilidad`, `rentabilidad_anual` y `volatilidad` sí son fracciones tal
cual las da Indexa. Así que la nota es correcta para tres campos y falsa para el cuarto: si
le preguntas a Jarvis cuánto has ganado y la cartera lleva un 13,64 %, el modelo lee
`13.64` como fracción y responde **1.364 %**.

El frontend no tiene el problema porque usa dos formateadores distintos a propósito
(`formatoPorcentaje` para `plusvalia_pct`, `formatoRentabilidad` para las fracciones,
`helpers.js:1769` y `:1782`). Jarvis no tiene esa pista: solo la frase.

**Arreglo.** O bien decirlo campo a campo en `unidades`, o —mejor— devolver la plusvalía
también como fracción y que la conversión viva en un solo sitio, que es exactamente el
motivo por el que existe `formatoRentabilidad`.

### 1.2 El saldo de Revolut suma euros con lo que no lo son (alta)

`backend/main.py:2898-2899`

```python
moneda = monto.get("currency") or moneda
saldo_total += saldo
cuentas.append({"nombre": nombre, "moneda": monto.get("currency") or moneda, ...})
```

`saldo_total` acumula el saldo de todas las cuentas del consentimiento sin mirar la
divisa, y `moneda` acaba siendo la de la **última** cuenta que se recorrió. Revolut es
multidivisa por diseño: en cuanto haya una cuenta en libras o en dólares, el widget enseña
una suma que no significa nada, etiquetada con una moneda elegida por el orden en que
Enable Banking devolvió los UIDs.

Hoy puede que solo haya una cuenta en euros y no se note. Eso es precisamente lo que lo
hace peligroso: el día que se añada otra, el número seguirá saliendo y seguirá pareciendo
correcto. Es el mismo criterio que ya gobierna el resto de finanzas —«un cero es una
afirmación sobre el dinero de alguien»— aplicado a la suma en vez de al cero.

**Arreglo.** Agrupar por divisa y devolver `{"EUR": 1234.5, "GBP": 80.0}`, o sumar solo la
divisa principal y sacar el resto en su propia fila. Lo que no puede quedarse es un
escalar sin unidad fiable.

### 1.3 Un fallo pasajero de Revolut apaga el widget durante una hora (media)

`backend/main.py:2909-2920`

`_revolut_datos_cache()` guarda en la caché **todo** lo que devuelve `_revolut_datos()`,
incluidos los caminos de error:

```python
return {"configurado": False, "motivo": "No se pudo consultar Revolut"}
```

Un 502 puntual de Enable Banking se queda cacheado `ENABLE_BANKING_TTL_MINUTOS` (60 por
defecto) y el dashboard dice «Ninguna cuenta conectada» durante una hora, aunque la sesión
esté perfectamente viva y el siguiente intento fuera a funcionar. Pulsar «refrescar» lo
arregla, pero el usuario no tiene forma de saber que eso es lo que hace falta: el mensaje
que ve le dice que el problema es la conexión, no la caché.

Indexa no comete este fallo: `get_finanzas()` lanza `HTTPException` y no toca
`_finanzas_cache`, así que el error no sobrevive a la petición.

**Arreglo.** Cachear solo los payloads que no dependen de la red (`_enable_banking_configurado()`
falso, sin sesión guardada, sesión caducada) y dejar el fallo de consulta sin cachear. La
distinción ya existe en el propio código, solo hay que separarla en dos retornos.

### 1.4 `fecha_precio_usada` miente cuando se pide con hora (media)

`backend/main.py:2982-3030`

El camino diario de `_yahoo_precio_historico()` es honesto: busca velas con `d <= fecha`,
se queda con la más reciente y **devuelve esa fecha real**, que es lo que sale al cliente
como `fecha_precio_usada`. Si compraste un sábado, la respuesta dice que se usó el precio
del viernes.

El camino horario no. `_yahoo_precio_historico_horario()` pide la ventana
`fecha-3d … fecha+1d` y escoge la vela **más cercana en el tiempo** al objetivo, sin exigir
que sea del mismo día:

```python
_, cierre = min(candidatos, key=lambda x: abs((x[0] - objetivo).total_seconds()))
return float(cierre)
```

Y quien llama devuelve la fecha pedida sin más:

```python
if precio_horario is not None:
    return precio_horario, fecha
```

Si `fecha` es festivo o fin de semana, se coge una vela de hasta tres días antes y se
presenta como el precio de ese día a esa hora. Las participaciones quedan calculadas con
un precio de otro día y `fecha_precio_usada` no lo dice — que es justo el campo que existe
para poder auditar una aportación mal metida.

**Arreglo.** Que la función horaria devuelva también la fecha de la vela elegida, o que
descarte candidatos de otro día y deje caer al cierre diario, que ya hace lo correcto.

### 1.5 `/health/latest` pierde las métricas que se miden de tarde en tarde (media)

`backend/main.py:4206`

```python
f"{SUPABASE_URL}/rest/v1/health_metrics?order=metric_date.desc&limit=500",
```

500 filas ordenadas por fecha, y de ahí se saca «el último valor de cada métrica». Con
unas 25 métricas al día, esas 500 filas cubren **unos veinte días**. Cualquier métrica que
se escriba con menos frecuencia —VO2 máx (el propio código dice que «se escribe de higos a
brevas»), peso, grasa corporal, masa magra— desaparece de `latest` en cuanto lleva tres
semanas sin medirse.

Y desaparece en silencio, que es el modo de fallo contra el que está construido medio
proyecto: «no lo sé» disfrazado de «no hay». No es un número equivocado, es un hueco donde
había un dato que sigue guardado en la tabla.

**Arreglo.** Pedir un `select` con `metric_name` y ordenar por `(metric_name,
metric_date desc)`, o —más simple— hacer la consulta por nombres conocidos. Subir el
límite solo mueve el problema más lejos.

### 1.6 `/health/metrics` mide «hoy» en UTC y el resto del módulo en local (baja)

`backend/main.py:4021` y `:4030`

```python
since     = (datetime.now(timezone.utc) - timedelta(days=days)).strftime("%Y-%m-%d")
today_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")
```

Todo lo que hay alrededor usa la zona del usuario: `get_health_diagnostico()` arranca con
`hoy = datetime.now(LOCAL_TZ).date()`, el resumen diario con `_ahora_local()`, la presencia
con `_ahora_local()`. Aquí no. En Madrid, entre medianoche y las dos de la madrugada, el
`today_str` de este endpoint es el día de **ayer**, así que `has_today` responde a otra
pregunta que la que dice su nombre y `last_sync` se recalcula por el motivo equivocado.

El efecto práctico es pequeño (`last_sync` se pone a «ahora» de todas formas porque casi
siempre hay filas de ayer), pero es una inconsistencia de las que se cobran más tarde: la
próxima cosa que se cuelgue de `has_today` heredará el desfase.

### 1.7 `_check_rate` poda con la ventana equivocada (latente)

`backend/main.py:780`

```python
for k in [k for k, ts in _rate_buckets.items() if not ts or ahora - ts[-1] >= ventana]:
    del _rate_buckets[k]
```

La poda recorre **todas** las claves del diccionario aplicándoles la `ventana` de la
llamada actual, que es la del recurso que se está comprobando ahora mismo. Con tres
recursos distintos usando el mismo diccionario (`ideas_audio`, `jarvis`, `voz_token`), una
llamada con ventana corta borra los cubos de los recursos con ventana larga antes de
tiempo, y su contador vuelve a cero.

Hoy no pasa nada porque los tres valores por defecto son 300 s
(`AUDIO_WINDOW_SECONDS`, `JARVIS_WINDOW_SECONDS`, `VOZ_TOKEN_WINDOW_SECONDS`). Pero los
tres son configurables por entorno, y son justo los que uno tocaría al ajustar costes: poner
`JARVIS_WINDOW_SECONDS=60` desactivaría de hecho el límite de Whisper y el de ElevenLabs,
sin ningún síntoma hasta que llegue la factura. Un limitador que se apaga solo al cambiar
una variable no relacionada es peor que no tenerlo, porque nadie va a sospechar de él.

**Arreglo.** Guardar la ventana junto al cubo (`{clave: (ventana, [ts…])}`) y podar con la
suya, o simplemente no podar claves de otro recurso.

### 1.8 Los workouts se saltan el camino que se arregló (media)

`backend/main.py:3600-3630`

`/health/ingest` escribe los workouts a mano, con `POST` y un `PATCH` de rescate si sale
409:

```python
r = http.post(f"{SUPABASE_URL}/rest/v1/health_metrics", ...)
if r.status_code == 409:
    r = http.patch(...)
```

Es exactamente el patrón que `HEALTH_UPSERT_URL` documenta como causa del 409 que dejó al
Watch sin sincronizar (`backend/main.py:3327-3335`), y que el resto de la ingesta ya no
usa. Dos consecuencias concretas:

- **Sin firma de fuente.** `_guardar_metricas()` estampa `fuente` (`auto_export`, `atajo`,
  `home_assistant`); esta rama no. Las filas de `workouts` salen en `/health/diagnostico`
  contadas dentro de `sin_fuente`, que es la columna que existe justo para las filas
  viejas de antes de que hubiera atribución. O sea: se siguen creando filas «antiguas».
- **Sin la protección del upsert.** Funciona, pero por el camino largo y sin la
  resolución explícita contra `unique(metric_date, metric_name)`.

**Arreglo.** Meter los workouts en el mismo `agrupadas` que las métricas normales y
dejar que `_guardar_metricas()` los escriba. Es menos código, no más.

### 1.9 El tope de `/ideas/audio` llega tarde (baja, con matiz)

`backend/main.py:1699-1707`

```python
_check_rate("ideas_audio", _client_ip(request), AUDIO_MAX_REQUESTS, AUDIO_WINDOW_SECONDS)
audio_bytes = await audio.read(MAX_AUDIO_BYTES + 1)
```

Cuando estas dos líneas se ejecutan, Starlette **ya ha leído y parseado el multipart
entero** (a un `SpooledTemporaryFile`, que pasa a disco de la VM al superar el umbral). Ni
el límite de tamaño ni el rate limit evitan la recepción; solo evitan la llamada de pago a
Whisper.

El invariante 8 de `CLAUDE.md` existe precisamente para esto y el resto del backend lo
cumple con `_leer_cuerpo_limitado()`, que corta **en el stream**. Esta ruta es la excepción,
y no está dicho en ningún sitio.

El matiz: el endpoint exige JWT de usuario, así que el atacante ya tiene que tener la
contraseña del dashboard. El coste real es de disco temporal, no de RAM. Por eso va como
baja — pero como excepción documentada, no como despiste.

### 1.10 `/calendar/events` no pagina (baja)

`backend/main.py:1203`

`$top=100` sobre una ventana de 30 días, sin mirar `@odata.nextLink`. Pasados 100 eventos
en el mes, los últimos días se caen sin decir nada — y de esa misma lista salen las
entregas del resumen diario (`construir_brief()` recorre `[*eventos, *clases]` buscando el
marcador), así que un mes cargado se lleva por delante entregas del correo.

`/calendar/classes` tiene `$top=200` sobre 60 días, mismo asunto.

No es urgente para un calendario personal, pero es del tipo de límite que se cruza sin
enterarse.

### 1.11 `cal_id` se interpola sin escapar (baja)

`backend/main.py:1385`

```python
f"https://graph.microsoft.com/v1.0/me/calendars/{cal_id}/calendarView"
```

`create_event()` escapa el mismo tipo de identificador con `quote(body.calendar_id,
safe='')` y explica por qué en un comentario de tres líneas. Aquí no, aunque los ids de
Graph pueden traer `/`, `+` y `=`. El valor viene de Graph, no del usuario, así que no es
una vulnerabilidad: es una inconsistencia que hace que la regla parezca opcional.

---

## Parte 2: seguridad

### 2.1 La comprobación anti-SSRF es vulnerable a DNS rebinding (media)

`backend/main.py:10345-10370`

```python
def _ip_publica(host: str) -> bool:
    infos = socket.getaddrinfo(host, None)
    ...

def _descargar(url, saltos=3):
    for _ in range(saltos + 1):
        if not url_web_permitida(url):
            return None
        r = http.get(url, ...)
```

Se resuelve el host, se comprueba que todas sus IPs son públicas, y **después** se llama a
`http.get()`, que vuelve a resolver el nombre por su cuenta. Entre las dos resoluciones no
hay nada que garantice que devuelvan lo mismo: un dominio con TTL 0 puede contestar una IP
pública a la comprobación y `127.0.0.1` o `169.254.169.254` a la petición real. Es el
bypass clásico, y se salta la lista entera.

Importa porque la URL que llega aquí no es de confianza por diseño: el propio comentario de
cabecera lo dice —«en el mejor caso ha salido de un resultado de búsqueda, y en el peor la
ha redactado un modelo a partir de texto de una web»—. Y el mismo comentario deja la
sensación de que el problema está resuelto («se repite en cada salto de redirección»), que
es la parte que más conviene corregir: la comprobación por salto tapa el 302 a loopback,
no la re-resolución.

**Arreglo de verdad.** Conectar contra la IP ya validada y mandar el `Host` a mano (un
`HTTPAdapter` propio que fije la dirección, o resolver una vez y construir la URL con la
IP). **Arreglo mínimo.** Dejarlo escrito en el comentario, para que el siguiente que lea
esa sección sepa que es un mitigante y no una garantía.

Alcance real hoy: Fly no expone credenciales en `169.254.169.254` como AWS, y el propio
backend en `127.0.0.1` pide token en todo lo que importa. Sigue siendo una puerta que
conviene cerrar antes de que la red de al lado cambie.

### 2.2 La clave privada RSA de Enable Banking viaja dentro de la imagen (media)

`backend/main.py:2733-2755`, `backend/Dockerfile`, `backend/.dockerignore`

```python
with open(ENABLE_BANKING_PRIVATE_KEY_PATH, "r", encoding="utf-8") as f:
    clave_privada = f.read()
```

La clave se lee de un fichero en disco. En Fly, sin volumen y con la máquina escalando a
cero, ese fichero solo puede estar **dentro de la imagen**: el `Dockerfile` hace `COPY . .`
y `.dockerignore` excluye `.env`, `.token`, `venv/`, `__pycache__/`, `*.pyc` y `.git/` —
pero **no `*.pem`**.

Es la única credencial del proyecto que no vive en `fly secrets`, y es una que Enable
Banking no vuelve a enseñar: si se pierde, hay que registrar otra aplicación
(`docs/FINANZAS.md:132`). Estar en la imagen significa estar en el registro de imágenes de
Fly, en cualquier caché de build y en el disco de quien construya el proyecto.

**Arreglo.** Aceptar también `ENABLE_BANKING_PRIVATE_KEY` con el contenido PEM (dos líneas:
si está la variable se usa, si no se cae al fichero) y añadir `*.pem` a `.dockerignore`. Con
eso la clave pasa a comportarse como el resto de secretos del proyecto y `.env.example`
puede documentar las dos formas.

### 2.3 Los servidores MCP del entorno admiten `http://` (baja)

`backend/main.py:10752-10775`

```python
if not url.startswith(("https://", "http://")):
    logger.warning(...)
    continue
```

`_mcp_del_env()` acepta `http://`; `_mcp_guardados()` (los que se dan de alta hablando con
Jarvis) exige `https://` estricto. Como cada entrada puede llevar un `token`, un servidor
declarado por `http://` manda ese token en claro por la red.

Puede que sea deliberado (un servidor MCP en la LAN, en local), pero entonces merece un
comentario que lo diga: hoy son dos criterios distintos para la misma frontera y no hay
manera de saber cuál es el que se quería.

### 2.4 `AGENT_ID = "pc-mikel"` está en un fichero versionado (baja)

`agent/agent.py:44`

`CLAUDE.md` es explícito: «No hardcodear nunca IPs, direcciones, emails, tokens,
contraseñas ni rutas de usuario en ficheros versionados». Esto es el nombre del usuario en
un repositorio público. Además ya está apuntado en `docs/REVISION_PROYECTO.md` desde la
revisión anterior, con el arreglo escrito (`os.getenv("AGENT_ID", ...)`), y sigue igual.

Es el tipo de cosa que no se arregla porque parece que no pasa nada; y no pasa nada, hasta
que se cruza con cualquier otro dato del repo.

---

## Parte 3: hallazgos anteriores que siguen abiertos

De `docs/REVISION_BACKEND.md` y `docs/REVISION_PROYECTO.md`. Los repaso porque una lista de
hallazgos que nadie vuelve a mirar es peor que no haberla escrito: da la sensación de que se
revisó.

| Hallazgo | Dónde | Estado |
|---|---|---|
| `api_headers()` usa `Authorization: Bearer` en vez de `X-Auth-Token` | `agent/agent.py:208` | **Abierto** — el backend prefiere la cabecera dedicada (`_extract_service_token`) |
| `AGENT_ID` hardcodeado | `agent/agent.py:44` | **Abierto** (ver 2.4) |
| `COPY . .` en el Dockerfile | `backend/Dockerfile` | **Mitigado** — existe `.dockerignore`, pero sin `*.pem` (ver 2.2) |
| Imagen base sin fijar (`python:3.11-slim`) | `backend/Dockerfile` | **Abierto** |
| Uvicorn como root en el contenedor | `backend/Dockerfile` | **Abierto** |

De los cinco, el que más valor tiene por línea escrita es fijar la imagen base: hoy un
`fly deploy` puede traerse un parche de Python distinto al que se probó, y el despliegue del
backend es manual precisamente porque afecta a producción real.

---

## Parte 4: deuda, consistencia y rendimiento

### 4.1 Documentación que se ha quedado atrás

- **La lista de migraciones de `CLAUDE.md` está incompleta.** Faltan
  `20260824_etf_cartera` y `20260824_etf_aportaciones_hora`, que sí están en
  `supabase/migrations/`. Es la lista que alguien mira para saber qué aplicar en un
  Supabase nuevo, así que una migración que no está ahí es una tabla que no existirá.
- **`src/components/Dashboard.jsx:1101` dice «precio real vía Twelve Data».** Es Yahoo
  Finance; Twelve Data se probó y se descartó (su plan gratuito no cubre ETFs de XETR), y
  el backend lo explica bien en su cabecera. El comentario del frontend se quedó en la
  versión anterior.

### 4.2 Código muerto y desorden

- **`VOZ_TIPOS` no se usa** (`backend/main.py:12529`): se define y acto seguido se duplican
  sus valores en el `Literal` de `VozTokenIn`. Dos sitios donde mantener la misma lista, y
  uno de ellos no hace nada.
- **La configuración de la voz vive en la línea 12.500**, junto al endpoint, en vez de con
  el resto de constantes de entorno de la cabecera. Es el único bloque de `os.getenv()` que
  está fuera. Como el fichero es deliberadamente único y navegable por banners, esto rompe
  la única convención que lo hace navegable.
- **`from collections import defaultdict` dentro de `health_ingest()`**
  (`backend/main.py:3604`) cuando el módulo ya importa de `collections` arriba.
- **`fly.toml` declara `memory = '1gb'` y `memory_mb = 1024`** en el mismo bloque `[[vm]]`.
  Redundante y, si algún día no coinciden, ambiguo.

### 4.3 Rendimiento

- **Diez `ThreadPoolExecutor` creados y destruidos por petición.**
  `backend/main.py:1773, 2286, 2507, 2653, 5444, 5630, 6242, 8150, 9955` y los anidados. Cada
  `with ThreadPoolExecutor(...)` arranca hilos nuevos y los mata al salir. En el resumen
  diario se anidan: 8 hilos en `construir_brief()`, y dentro `_brief_economia()` abre otros
  4 y `_finanzas_cuenta()` otros 2 por cuenta. Todo eso encima del pool de FastAPI (40
  hilos) en una VM de 1 GB. Un ejecutor de módulo, acotado y compartido, ahorra la creación
  y —más importante— **pone un techo** que hoy no existe.
- **`_revolut_datos()` hace 1 + 2N llamadas en serie** (`backend/main.py:2870-2900`): la
  sesión, y luego `details` y `balances` de cada cuenta, una detrás de otra. Es el único
  bloque de finanzas que no paraleliza, teniendo el patrón al lado en `_finanzas_cuenta()`.
  Con `HTTP_TIMEOUT=15` y tres cuentas, el peor caso son 105 s reteniendo un hilo.
- **`_etf_precios_actuales()` cachea el diccionario entero sin clave**
  (`backend/main.py:3047`). Dos consecuencias: dar de alta un ETF nuevo lo deja sin precio
  hasta que caduque la caché (una hora), y un ticker que falló por un hipo de Yahoo se
  queda sin precio la hora entera aunque el minuto siguiente ya funcionara. El comentario
  dice «si un ETF concreto falla, ese ticker queda sin precio», que es verdad — lo que no
  dice es cuánto dura.

### 4.4 Consistencia de la API

`plusvalia_pct` viene en porcentaje y `ganancia_pct` en fracción, y son dos endpoints
(`/finanzas/resumen` y `/finanzas/etfs`) que alimentan **el mismo widget**. El frontend lo
resuelve bien con dos formateadores; Jarvis no (hallazgo 1.1). Mientras la unidad dependa
del endpoint que la sirvió, cada consumidor nuevo tiene una probabilidad de equivocarse.

### 4.5 CI

El CI hace exactamente lo que promete y está bien montado (tres jobs paralelos,
concurrencia con cancelación, `workflow_dispatch` para relanzar). Le falta una cosa:
**nadie mira las dependencias**. No hay Dependabot (`.github/` solo tiene `workflows/`), ni
`pip-audit`, ni `npm audit` en ningún job. Con `requirements.txt` fijado al parche —que está
bien— eso significa que las versiones se quedan donde están hasta que alguien las suba a
mano, en un repositorio público con un backend en producción que guarda datos de salud.

Un `pip-audit` y un `npm audit --audit-level=high` en los jobs que ya existen son cuatro
líneas y no añaden tiempo perceptible.

---

## Parte 5: lo que está bien y no hay que tocar

Corto, pero conviene escribirlo: en una lista de hallazgos todo parece roto, y no lo está.

- **Los comentarios explican el porqué, no el qué**, y con el fallo histórico dentro. Media
  docena de los hallazgos de arriba los encontré leyendo un comentario que decía «esto se
  hace así porque una vez pasó tal cosa» y comprobando si el de al lado lo hacía igual. Eso
  no se puede hacer en un código que documenta lo evidente.
- **La distinción «no lo sé» / «es que no» es coherente en todo el proyecto**: presencia
  caducada, días sin reloj, `plusvalia_origen`, `total.completo`, `reloj.sin_datos`,
  `formatoEuros` devolviendo `—`. Es la mejor decisión de diseño que hay aquí.
- **La cobertura de tests es alta y con intención** (1.023 backend + 213 frontend + E2E con
  navegador real). El E2E importando `main.py` tal cual y sustituyendo solo `main.http` es
  la forma correcta de hacerlo.
- **El gobierno de avisos** (presupuesto, utilidad, memoria, la frontera «lo que pediste tú
  no se gobierna») es la parte más difícil de acertar de un asistente proactivo y está
  resuelta antes de que hiciera falta.

---

## Parte 6: ideas

Ideas nuevas, sin repetir lo que ya está en `docs/IDEAS.md` ni lo que allí se descartó a
propósito (cruzar entrenos con sesiones, histórico de presencia, historial de Jarvis en el
backend, interpretar los datos en el correo, un hilo de relojes en el backend).

### 6.1 Que Jarvis y el correo sepan de la cartera entera ●

**Qué.** `_j_finanzas()` solo llama a `get_finanzas()`: sabe de Indexa y del saldo de
Revolut, pero **no de la cartera manual de ETFs** — `get_cartera_etf()` no lo usa nadie más
que el frontend. Y el resumen diario no lleva finanzas en absoluto.

**Por qué.** El correo de la mañana ya te explica qué es el interés compuesto y te manda
titulares del BCE, y no te dice qué ha hecho tu dinero. Y si le preguntas a Jarvis «cuánto
tengo», la respuesta se deja fuera una cartera entera sin avisar de que se la deja: es el
patrón «no lo sé disfrazado de no hay» que el proyecto persigue en salud y aquí se cuela por
la puerta de atrás.

**Por dónde se empieza.** Añadir `get_cartera_etf(credentials=None)` a `_j_finanzas()` (y
arreglar de paso el `unidades` del hallazgo 1.1). Luego una sección `finanzas` en
`construir_brief()` con el total, la variación desde el resumen anterior —que
`_instantanea_brief()`/`_cambios_desde()` ya saben calcular— y nada más: totales, no
posiciones.

### 6.2 Serie de patrimonio: convertir tres fotos en una película ●●

**Qué.** Una tabla `patrimonio_diario` (fecha, indexa, revolut, etfs, total) escrita una vez
al día desde el tick de HA, con lo que ya devuelven los tres endpoints.

**Por qué.** Hoy solo Indexa tiene historia, y porque la trae de su propia API
(`ret.total_amounts`). Revolut y los ETFs son fotos del instante: si mañana bajan, no hay
forma de saber desde cuándo. El widget dice, con razón, que las tres cosas no se suman entre
sí — pero «cuánto tengo en total y cómo se mueve» es una pregunta legítima y hoy es
imposible de responder, no por decisión de diseño sino porque el dato no se guarda.

Y es barato: el tick ya pasa cada 5 minutos, los tres valores ya están cacheados, y una fila
al día durante diez años son 3.650 filas.

**Por dónde se empieza.** La migración y una función `_apuntar_patrimonio()` con la misma
idempotencia por fecha que ya usan los avisos (`uuid5` de la fecha contra la clave
primaria). El widget puede esperar: primero se acumula el dato, que es lo que no se puede
recuperar hacia atrás.

### 6.3 Gastos, con lo que ya está consentido ●●

**Qué.** `/auth/enablebanking/login` pide el consentimiento con
`{"balances": True, "transactions": True}` (`backend/main.py:2815`) y **las transacciones no
se leen nunca**: solo se llama a `/balances`. `GET /accounts/{uid}/transactions` está a una
llamada de distancia y ya está autorizado.

**Por qué.** Es, con diferencia, la idea con más valor por línea escrita de este documento:
el permiso está dado, el cliente HTTP está montado, la caché está montada y el flujo OAuth
está montado. Lo que falta es leer y agrupar. Con eso se responde «cuánto llevo gastado este
mes», «en qué» y «voy por encima o por debajo de mi media» — que es exactamente el tipo de
pregunta para la que existe un dashboard personal, y la única parte del dinero que hoy es un
agujero negro (se ve lo que se tiene, nunca lo que se va).

**Por dónde se empieza.** Un `/finanzas/movimientos` con la misma forma que el resto
(caché en memoria, TTL corto, `configurado: false` si no hay sesión), y agregación por mes y
por categoría del banco. Nada de categorizar con un LLM al principio: primero el dato crudo,
que es la regla de la casa.

**Después**, si aporta: una regla proactiva montada sobre el sistema que ya existe
(«llevas un 30 % por encima de tu media a mitad de mes»), con su prioridad baja y su huella
mensual para que no se repita.

### 6.4 Un `ErrorBoundary` alrededor de cada widget ●

**Qué.** Un componente que envuelva cada tarjeta del dashboard y pinte «este widget ha
fallado» en vez de tirar el árbol de React entero.

**Por qué.** El comentario de `formatShortDate` en `helpers.js:36-42` ya cuenta la historia:
una fecha con un mes fuera de 1-12 hacía `MONTHS_ES[m-1].slice(...)` sobre `undefined` y
«rompía toda la página, porque no hay ErrorBoundary». Se arregló **ese** helper. Pero la
causa de fondo sigue: son 6.300 líneas de UI con una decena de widgets que consumen datos de
siete integraciones externas, y cualquiera de ellas puede devolver algo con una forma que
nadie previó. La única defensa hoy es acordarse, helper a helper.

**Por dónde se empieza.** `ErrorBoundary` es de las pocas cosas que React sigue exigiendo
como clase, así que son unas veinte líneas. Envolver el `switch` que pinta cada tarjeta y
listo — y el mensaje de fallo puede llevar el `data-card` del widget, para que el registro
diga cuál se cayó.

**Nota.** Esto no contradice la regla de «no crees componentes en ficheros nuevos por
organizar»: no es organización, es una capacidad que no existe.

### 6.5 Cerrar el bucle del sueño: lo que sí controlas ●●

**Qué.** Registrar tres o cuatro cosas que hoy no se miden y que dependen de decisiones
tuyas: cafeína después de cierta hora, alcohol, hora de la última pantalla, si cenaste
tarde. Como métricas propias en `health_metrics`, escritas desde el dashboard o desde una
pregunta de Jarvis por la noche.

**Por qué.** Toda la maquinaria de correlaciones ya existe y ya funciona: `_CRUCES`,
`pairByDate`, `splitCompare`, `healthCorrelations`, la cobertura, las ventanas por fecha
real. Lo que le falta no son más sensores —el reloj ya da todo lo que puede dar— sino
variables **accionables**. Saber que tu HRV baja los días que duermes poco no cambia nada;
saber que baja los días que tomas café después de las seis, sí.

Y encaja con la arquitectura tal cual: una métrica más en la misma tabla entra sola en
`/health/metrics` y, con ella, en el motor de conclusiones, sin abrir ninguna vía de datos
nueva. Es exactamente el argumento con el que `time_at_home` se metió ahí en vez de en una
tabla propia.

**Por dónde se empieza.** Tres interruptores en el widget de sueño, escribiendo por el
mismo `/health/ingest/simple` que ya existe. Antes de añadir el cruce, comprobar la
cobertura: con menos de tres semanas de dato, `splitCompare` no dirá nada y dirá bien que no
dice nada.

### 6.6 Cuánto cuesta un día de dashboard ●

**Qué.** Un contador de gasto por servicio de pago —Whisper, GPT-4o-mini, ElevenLabs,
Tavily/Brave, Google Maps— y una fila en el panel de estado.

**Por qué.** Hoy no hay **ni un solo número**. El código habla de gasto en tres sitios
(«la transcripción cuesta dinero en cada llamada», «un cortacircuitos de gasto, no de
seguridad», «el STT cobra micrófono abierto, no palabras dichas») y todos son límites a
ciegas: se fijaron por intuición y no hay forma de saber si sobran o si se quedan cortos.
El micrófono abierto de ElevenLabs es el caso claro — `JARVIS_VOZ_MAX_MINUTOS = 20` protege
de una llamada olvidada, pero nadie sabe cuánto cuesta una llamada normal.

Es la misma pregunta que el proyecto ya se hace en todo lo demás: distinguir «no lo sé» de
«es que no». Aquí, hoy, es «no lo sé».

**Por dónde se empieza.** Los propios SDK ya devuelven el consumo (`usage` en las respuestas
de OpenAI, la cabecera de coste de ElevenLabs). Una tabla `coste_uso` (fecha, servicio,
unidades, euros) escrita desde donde ya se registra, y un total por día. Con eso, y solo con
eso, los límites de arriba dejan de ser adivinanza.

### 6.7 Sacar la lógica pura del agente PC y probarla ●

**Qué.** `agent/agent.py` son 1.057 líneas sin un solo test, y `CLAUDE.md` dice —con razón—
que no puede tenerlos porque necesita un Windows real. Pero eso solo es verdad de una parte:
`alud_url_permitida()`, `build_cowork_instruction()`, el parseo de payloads de job y la
máquina de estados de claim/start/finish **no tocan el escritorio**.

**Por qué.** `alud_url_permitida()` es una de las tres barreras de una invariante de
seguridad declarada («no quites ninguna de las tres», invariante 7), y es la única de las
tres que no está cubierta por tests. Que la copia del agente y la del backend se separen no
lo detectaría nadie hasta que pasara.

**Por dónde se empieza.** Un `agent/logica.py` con lo puro y un `tests/agent/` que corra en
CI en el job de backend, que ya tiene Python montado. Lo que se queda fuera —Edge,
pyautogui, Claude Desktop— se queda fuera con razón, y entonces la frase de `CLAUDE.md` pasa
a ser cierta del todo en vez de aproximadamente.

### 6.8 El informe semanal del sistema, no de la salud ●●

**Qué.** Un correo el domingo con el estado del **sistema**: qué falló esta semana
(`app_logs` agrupado por fuente), qué integración dejó de escribir
(`/health/diagnostico`), cuántos avisos salieron y cuántos marcaste inútiles
(`avisos_reglas`), qué se reparó solo y cuántas veces lleva reparándose
(`vigilante_estado`), y —si se hace 6.6— cuánto costó.

**Por qué.** Todas esas tablas existen ya y todas se consultan solas, pero solo **cuando
algo cruza un umbral**. El vigilante avisa de averías; nadie enseña la tendencia. Y el
propio `_vigilar_sistema()` explica por qué no puede: es el tick de HA quien lo ejecuta, así
que ve el sistema desde dentro.

Es importante que sea **correo y no aviso**: el gobierno de avisos dice, con razón, que dos
avisos de lo mismo es la forma más rápida de que se dejen de leer los dos. Un informe
semanal es otro canal, se lee cuando uno quiere y no gasta el presupuesto de interrupciones.
Reutiliza el disparador del informe semanal de salud, que ya existe.

### 6.9 Web Push: que los avisos no dependan de Home Assistant ●●

**Qué.** Notificaciones push del navegador (VAPID) desde el backend, en paralelo al camino
actual.

**Por qué.** Hoy un aviso al móvil da este rodeo: el backend lo apunta → HA lo sondea → HA
se lo manda al móvil. Eso significa que **cuando HA se cae, los avisos se caen con él** — y
uno de los avisos que más falta hace es precisamente «HA lleva horas sin dar señales». El
propio código lo reconoce: «si HA muere, el vigilante muere con él. Eso solo lo puede ver
algo de fuera».

La PWA ya está montada y el permiso de notificaciones ya se pide (`tests/frontend/setup.js`
stubea `Notification` porque jsdom no lo trae). Falta el service worker con `push` y las
claves VAPID.

**Cuidado.** No sustituye a HA: HA sabe hacer cosas que un push no (hablar por los
altavoces, encender el PC). Es un segundo camino para lo que hoy tiene uno solo, y el
criterio para elegir cuál debería ser explícito, no accidental.

### 6.10 «¿Por qué me has avisado de esto?» ●

**Qué.** Que Jarvis pueda responder a esa pregunta con la regla que lo disparó, el dato
concreto que la cumplió, cuántas veces ha salido y cuántas la has marcado inútil.

**Por qué.** El sistema de gobierno ya guarda todo eso: `regla`, `huella`, `prioridad`,
utilidad, `avisos_reglas`. Lo que no hay es forma de mirarlo sin abrir Supabase. Y sin poder
mirarlo, la señal de utilidad es un botón que se pulsa a ciegas: marcas «no útil» sin saber
qué regla estás silenciando ni qué más te vas a perder por hacerlo.

Es la pieza que convierte un sistema que aprende en un sistema que puedes auditar, y encaja
con la frontera que ya existe: el código decide, el modelo redacta — aquí el modelo solo
lee lo que el código ya apuntó.

**Por dónde se empieza.** Una herramienta `por_que_este_aviso(id)` que lea la fila del
recordatorio y su regla. Sin escritura, sin confirmación: es una consulta.

---

## Por dónde empezaría

Ordenado por lo que arregla frente a lo que cuesta.

| Orden | Qué | Esfuerzo | Por qué ahí |
|---|---|---|---|
| 1 | 1.1 y 1.2 — las unidades de Jarvis y la suma de divisas | ● | Los dos hacen que un número salga mal hoy, y los dos son de una línea |
| 2 | 1.3 y 1.5 — la caché de errores de Revolut y `/health/latest` | ● | Los dos esconden dato que sí existe, que es el modo de fallo que este proyecto persigue |
| 3 | 2.2 — la clave RSA fuera de la imagen | ● | La única credencial que no vive como el resto, y no se puede volver a descargar |
| 4 | 6.4 — `ErrorBoundary` | ● | Media tarde y desaparece una clase entera de fallo |
| 5 | 6.1 — la cartera entera en Jarvis y en el correo | ● | Cierra el trabajo que dejaron a medias los ETFs |
| 6 | 1.7 y 4.5 — la poda del rate limit y el escaneo de dependencias | ● | Dos trampas que solo se ven cuando ya han pasado |
| 7 | 6.3 — gastos desde Enable Banking | ●● | Más valor por línea escrita que ninguna otra: el permiso ya está dado |
| 8 | 2.1 — el DNS rebinding | ●● | Ninguna prisa hoy, pero el comentario tiene que dejar de decir que está resuelto |

Del 1 al 6 caben en una tarde larga y son todo cosas que hoy dan un número equivocado, un
hueco donde hay dato, o un secreto donde no toca. Del 7 en adelante ya es construir.
