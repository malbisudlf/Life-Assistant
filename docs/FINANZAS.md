<!-- Parte de la guía del repositorio. El índice y las reglas que aplican
     SIEMPRE están en CLAUDE.md, en la raíz. -->

## Finanzas: la cartera de Indexa Capital + el ahorro en Revolut + los ETFs manuales

Un widget, tres fuentes. `GET /finanzas/resumen` devuelve la cartera de Indexa en las
claves de siempre y el saldo de Revolut en `revolut`; `GET /finanzas/etfs` (endpoint
aparte) devuelve la cartera manual de ETFs. No se suman entre sí — inversión con
plusvalía, dinero parado en una cuenta corriente y una cartera llevada a mano son tres
cosas distintas, y sumarlas daría un "total" que no significa nada.

### Indexa Capital

Un widget que dice cuánto hay invertido, cuánto se ha aportado, cuánto lleva ganado y en
qué está puesto. **Solo lectura**: la API de Indexa tiene endpoints que mueven dinero y
aquí no se usa ninguno a propósito — el dashboard es un sitio para mirar el dinero.

### Cómo se saca el token

En Indexa: **Configuración de usuario → Aplicaciones → crear token**. Se pone en
`INDEXA_TOKEN` del `.env` del backend y no se toca nada más. Nunca en el frontend: el
navegador es público, y ese token abre la cuenta entera.

### Qué se pide y qué da cada llamada

Base `https://api.indexacapital.com`, cabecera `X-AUTH-TOKEN`. Tres llamadas por carga
fresca (1 + 2 por cuenta):

| Endpoint | Qué se saca de ahí |
|---|---|
| `GET /users/me` | La lista de cuentas: `account_number`, `type` (`mutual`, `pension`, `epsv`, `employment_plan`) y `status` |
| `GET /accounts/{n}/portfolio` | `instrument_accounts[].positions[]` (valor, coste, títulos, precio y **la fecha de la valoración**) y `portfolio.cash_amount` / `portfolio.total_amount` |
| `GET /accounts/{n}/performance` | `return.investment` (lo aportado), `return.pl` (la plusvalía de la cuenta), `return.time_return` / `time_return_annual` (rentabilidad ponderada por tiempo, en **fracción**) y las series diarias `total_amounts` / `net_amounts` |

Las dos de cada cuenta van en paralelo (`ThreadPoolExecutor`), y las cuentas también entre
sí: es una pantalla que se abre con el arranque en frío de Fly por delante.

### Las decisiones que no son obvias

- **Si `/performance` falla, la cuenta sale igual.** Sin esa llamada se sigue sabiendo lo
  que vale la cartera hoy, así que se devuelve lo que hay y lo que dependía de ella queda a
  `None`. `None` significa "no lo sé" y el frontend lo pinta como `—`, nunca como `0 €`: un
  cero es una afirmación sobre el dinero de alguien. Lo que **no** se tolera es que falle
  `/portfolio` — sin posiciones no hay cuenta que enseñar, y eso corta con 502.
- **La plusvalía dice de dónde sale** (`plusvalia_origen`). La de la **cuenta** (`return.pl`)
  es todo lo ganado desde que se abrió, traspasos y ventas incluidos; la de las
  **posiciones** (suma de `amount - cost_amount`) es solo lo que llevan ganado los fondos
  que hay ahora mismo. Sin rendimiento solo se puede calcular la segunda, y llamarlas igual
  sería mentir en la dirección que más gusta.
- **La fecha de valoración se enseña siempre.** Indexa valora una vez al día y con un par de
  días de retraso: sin `fecha_valores` a la vista, la cartera del viernes se lee como la de
  hoy. Es la misma regla que la presencia caducada y los días sin reloj.
- **El total avisa cuando está incompleto** (`total.completo`). Si a una cuenta le faltó el
  rendimiento, la suma de aportaciones es la de las demás — presentarla como el total sería
  un número correcto respondiendo a otra pregunta.
- **La serie total solo usa los días que tienen TODAS las cuentas.** Con dos cuentas abiertas
  en fechas distintas, incluir los días en que solo existía una dibuja un salto vertical el
  día que empieza la segunda: la línea diría "ganaste 20.000 € en un día" cuando lo que pasó
  es que empezó a contar otra cuenta.
- **El efectivo va en su propia clase**, separado de los fondos monetarios: uno es una
  decisión de la cartera y el otro es dinero esperando a invertirse.
- **Se recorren todas las `instrument_accounts`**, no solo la primera (que es lo que hacen
  varios clientes que andan por ahí). Quedarse con la primera enseñaría una cuenta a la que
  le falta dinero, sin decirlo.
- **Las cuentas sin dinero se omiten diciéndolo** (`omitidas`, con el motivo). Una cuenta a
  medio contratar no tiene posiciones y pedirlas solo produce un 4xx cada tres horas; pero
  una cuenta que no sale tiene que distinguirse de una cuenta que no existe.
- **El número de cuenta se valida con patrón** antes de interpolarlo en la URL de la llamada
  siguiente, igual que los path params de Supabase (invariante 6 de `CLAUDE.md`). Viene de
  la propia API, pero la regla es la regla.
- **Los errores de Indexa no se reenvían.** Al registro va el detalle; al cliente, un 502
  genérico. Y lo que se registra es una etiqueta (`portfolio`, `performance`), nunca la ruta:
  la ruta lleva el número de cuenta dentro y `app_logs` no necesita saberlo.

### La caché

`_finanzas_cache` en memoria, `INDEXA_TTL_MINUTOS` (180 por defecto). Indexa actualiza el
valor una vez al día: pedirlo en cada carga del dashboard son tres llamadas de red para
devolver el mismo número. Se tira en cada cold start de Fly, como el resto de copias en
memoria, y el botón ↻ del widget la salta (`?refrescar=true`) para cuando se quiere mirar
de verdad. La consulta se hace **fuera del lock**: dos cargas simultáneas pueden preguntar
las dos, que es más barato que dejar a una esperando una llamada de red que no es suya.

**No hay tabla propia ni histórico en Supabase**, y es deliberado: la serie diaria completa
la da Indexa en cada respuesta, así que una copia solo sería una segunda versión de la
verdad que mantener sincronizada. Misma decisión y mismo motivo que el histórico de
presencia descartado en `docs/IDEAS.md`.

### El widget

`case "finanzas"` en `Dashboard.jsx`, columna derecha. Valor total, plusvalía en euros y en
porcentaje, cuánto se movió desde el último día **con dato** (no desde "ayer": Indexa no
valora fines de semana, y restar contra una fecha que no existe daría siempre 0 los lunes),
sparkline de la serie, barra de mezcla por clase de activo y, plegado, el detalle de
posiciones. Con más de una cuenta aparece una fila por cuenta.

Los formateadores son puros y viven en `src/lib/helpers.js`: `formatoEuros`,
`formatoPorcentaje`, `formatoRentabilidad` (fracción → porcentaje, en un solo sitio para que
nadie multiplique por 100 a ojo), `mezclaCartera` y `variacionCartera`.

Debajo, separadas por una sola línea, Revolut (`finanzas.revolut`) y la cartera manual de
ETFs (`carteraEtf`, estado propio cargado con `GET /finanzas/etfs`) comparten UNA lista con
el mismo estilo de fila compacta que ya usan las cuentas de Indexa cuando hay más de una
(nombre a la izquierda, valor en monoespaciada a la derecha) — antes cada una tenía su
propia caja con su propio título en mayúsculas, y se veían como tres widgets pegados en vez
de una sola tarjeta. Siguen siendo datos que **no se suman entre sí** (inversión con
plusvalía, saldo de cuenta corriente y cartera manual son cosas distintas), solo cambió
cómo se presentan. Cada ETF muestra precio actual (`€/particip.`) y aportado en una línea
secundaria, y un botón "+ Añadir aportación" que abre un formulario inline (fecha, hora
opcional, importe) y llama a `POST /finanzas/etfs/{ticker}/aportaciones`. El botón ↻
refresca las tres fuentes a la vez.

### Jarvis

Herramienta `finanzas`, de consulta directa (no pide confirmación: no toca nada). Devuelve
los totales, la mezcla y las cinco posiciones mayores de cada cuenta — el detalle entero son
una decena de fondos con ISIN, gestora y títulos que se pagan por token en cada turno sin
responder a lo que de verdad se pregunta. Sin token configurado contesta con el motivo
dentro (`dile_al_usuario_literalmente`), y aparece también en `mis_capacidades` y en el
`diagnostico`.

### Variables

| Variable | Por defecto | Qué hace |
|---|---|---|
| `INDEXA_TOKEN` | — | El token de la API. Sin él, `configurado: false` y el widget lo dice; no es un error |
| `INDEXA_API_URL` | `https://api.indexacapital.com` | Solo para pruebas |
| `INDEXA_CUENTAS` | (todas) | Filtro de números de cuenta separados por comas. **No** sustituye a `/users/me`: el estado y el tipo salen de ahí, y una lista escrita a mano no sabría que una cuenta se canceló |
| `INDEXA_TTL_MINUTOS` | `180` | Vida de la copia en memoria |
| `INDEXA_SERIE_DIAS` | `365` | Días de serie que se devuelven al frontend (la completa es desde que abriste la cuenta y viaja entera en cada respuesta) |
| `ENABLE_BANKING_APPLICATION_ID` | — | El `application_id` de la app registrada en su Control Panel |
| `ENABLE_BANKING_PRIVATE_KEY_PATH` | — | Ruta al `.pem` descargado UNA VEZ al registrar la app (no se puede volver a descargar) |
| `ENABLE_BANKING_API_URL` | `https://api.enablebanking.com` | Solo para pruebas |
| `ENABLE_BANKING_ASPSP_NAME` / `_COUNTRY` | `Revolut` / `ES` | El banco al que se pide consentimiento |
| `ENABLE_BANKING_REDIRECT_URL` | — | Debe estar en las "Redirect URLs" de la app y apuntar al backend, no al frontend. Tiene que ser `https`, incluso en local |
| `ENABLE_BANKING_VALID_DIAS` | `180` | Cuánto dura el consentimiento antes de tener que repetirlo |
| `ENABLE_BANKING_TTL_MINUTOS` | `60` | Vida de la copia en memoria del saldo |
| `YAHOO_FINANCE_API_URL` | `https://query1.finance.yahoo.com` | Solo para pruebas |
| `ETF_PRECIO_TTL_MINUTOS` | `60` | Vida de la copia en memoria de los precios actuales de la cartera manual de ETFs |

### Los tests

`tests/backend/test_finanzas.py`: las respuestas simuladas **copian la forma de la API real**
(`instrument_accounts` → `positions`, `return.total_amounts`…). Si esa forma cambiara, es ese
fichero el que tiene que enterarse primero. Cubren la agregación, el reparto por clase, el
camino sin rendimiento, la caché, el 502 que no reenvía el cuerpo de Indexa y que el token
viaja en cabecera y no en la URL.

El E2E (`tests/e2e/servidor_pruebas.py`) trae una cartera simulada con 40 días de serie, así
que el widget se pinta con números de verdad en un navegador real.

### Revolut (vía Enable Banking)

Enable Banking es un agregador PSD2/open banking (licencia AISP propia en la UE): no hace
falta que el usuario del dashboard tenga su propia licencia regulatoria, algo que sí exigen
GoCardless/Nordigen, Salt Edge o usar la API de Revolut directamente. Con eso resuelto, lo que
da acceso NO es un token fijo como Indexa — es un consentimiento OAuth con el banco, con el
mismo patrón que Microsoft Graph (`/auth/login` → `/auth/callback`, `state` firmado con
`SECRET_KEY`), solo que aquí es `/auth/enablebanking/login` → `/auth/enablebanking/callback`.

**El flujo:**

1. `GET /auth/enablebanking/login` (JWT del dashboard) construye un JWT de *aplicación*
   (`_enable_banking_jwt()`, RS256, firmado con la clave privada RSA que se descargó UNA VEZ
   al registrar la app en su Control Panel — Enable Banking no la vuelve a enseñar; si se
   pierde, hay que registrar otra app) y llama a `POST /auth` de Enable Banking. Devuelve una
   `auth_url` a la que el usuario tiene que ir a autorizar con Revolut.
2. Revolut redirige a `ENABLE_BANKING_REDIRECT_URL` (el backend, no el frontend — como Graph)
   con un `code`. `GET /auth/enablebanking/callback` verifica el `state` (misma función que
   Graph, `_verify_oauth_state`, genérica de sobra para reusarla) y canjea el `code` por una
   sesión con `POST /sessions`.
3. La sesión (`session_id` + `valid_until`, hasta `ENABLE_BANKING_VALID_DIAS` días — 180 por
   defecto) se guarda en `oauth_tokens` (la misma tabla de Graph, `provider =
   "enablebanking_revolut"`, sin `refresh_token`: a diferencia de Graph, una sesión caducada
   **no se renueva sola** — hay que repetir el paso 1).
4. `_revolut_datos()` usa esa sesión para pedir `GET /sessions/{id}` (la lista de cuentas
   autorizadas), y por cada una `GET /accounts/{uid}/details` (nombre, moneda) y
   `GET /accounts/{uid}/balances` (saldo; se prefiere el tipo `ITAV`, disponible, sobre `CLAV`,
   contable). Se cachea con `ENABLE_BANKING_TTL_MINUTOS` (60 por defecto — un saldo de cuenta
   corriente se mueve durante el día, así que el TTL es mucho más corto que el de Indexa).

**Redirect URL: tiene que ser `https`, incluso en local.** Enable Banking rechaza `http://`
con `REDIRECT_URI_NOT_ALLOWED` incluso para `localhost`. Para probar en local hace falta un
certificado autofirmado (`openssl req -x509 -newkey rsa:2048 -nodes -keyout
backend/localhost-key.pem -out backend/localhost-cert.pem -days 365 -subj "/CN=localhost"`,
ambos en `.gitignore` vía `backend/*.pem`) y arrancar uvicorn con `--ssl-keyfile`/
`--ssl-certfile`. El navegador avisará de certificado no confiable una vez; para una prueba
propia vale con continuar.

**La documentación pública de Enable Banking no coincide con la API real** en un punto
concreto: dice que `accounts` en la respuesta de `POST /sessions` y `GET /sessions/{id}` son
objetos con `uid`, `name`, `currency`... y en realidad son solo una lista de **UIDs (string)**.
El nombre y la moneda hay que sacarlos aparte de `GET /accounts/{uid}/details`. Costó un 500
descubrirlo — si su documentación cambia de forma otra vez, es aquí donde se nota primero.

**Solo aparece la cuenta corriente, no la de ahorro (vault).** Se comprobó en la propia
pantalla de consentimiento de Revolut: solo ofrece una cuenta para compartir, con el motivo de
que el vault de ahorro no tiene IBAN propio — no es una cuenta de pago separada a ojos de
Revolut, así que no la expone por PSD2. No hay nada que arreglar en este backend: es Revolut
quien no la ofrece.

**La cartera de inversión/cripto de Revolut es inalcanzable por esta vía, y por CUALQUIER
agregador PSD2 (Enable Banking, GoCardless, Salt Edge, Tink...).** PSD2 solo cubre cuentas de
*pago*; las posiciones de inversión quedan fuera de su ámbito legal hasta que entre en vigor
FIDA (Financial Data Access), que a fecha de escribir esto no está desplegada en ningún banco.
No es una limitación de esta integración: ningún AISP puede pedir ese dato hoy, venga de donde
venga. Si algún día se quiere esa cartera en el dashboard, la única vía real es la API propia
de la plataforma donde se invierta — igual que Indexa — y de los brokers de acciones/ETFs
habituales (DEGIRO, Trade Republic, MyInvestor) **ninguno tiene API pública**; el único con API
oficial documentada es Interactive Brokers (pendiente de evaluar: exige mantener corriendo su
Client Portal Gateway, más trabajoso que un token fijo).

### Cartera manual de ETFs (Yahoo Finance)

Ya que ningún agregador puede leer la cartera de inversión de Revolut, se lleva a mano:
dos tablas en Supabase y el precio real de cada ETF sacado de Yahoo Finance, para que
el valor no sea un número que se edite a ojo.

**Por qué Yahoo Finance y no otra cosa.** Se probaron dos fuentes antes:
- **Stooq**: gratis y sin clave sobre el papel, pero en algún momento de 2026 metió un
  reto anti-bot (proof-of-work en JavaScript, SHA-256) delante de sus CSV — un backend
  no puede resolverlo sin un navegador headless, así que quedó descartado.
- **Twelve Data**: API con clave gratuita, pero su plan free **no cubre ETFs cotizados
  en bolsas europeas como XETR** — ni el precio actual ni el histórico. Comprobado en
  vivo, con una clave real: `GET /price?symbol=VWCE&exchange=XETR` devuelve 404 con
  `"This symbol is available starting with the Grow or Venture plan"`.

El endpoint de gráficas de Yahoo Finance (`/v8/finance/chart/{símbolo}`) **no es una
API oficial ni documentada** — puede cambiar o bloquearse sin aviso, exactamente como
le pasó a Stooq. Es la opción que queda tras descartar las otras dos, no una elección
sin riesgo: si deja de funcionar algún día, este es el sitio donde mirar primero.
Eso sí, de momento da tanto el precio actual como el histórico diario **sin clave y
sin límite de peticiones conocido** — solo hace falta mandar un `User-Agent` de
navegador, sin él responde `429` aunque no haya habido ningún tráfico previo.

**El esquema** (`supabase/migrations/20260824_etf_cartera.sql`):
- `etf_holdings`: qué ETFs se trackean — `ticker` (el que muestra Revolut, ej. `VWCE`),
  `nombre`, y `simbolo_yahoo` (el símbolo + sufijo de bolsa que entiende Yahoo, ej.
  `VWCE.DE` para XETRA).
- `etf_aportaciones`: cada aportación real — `fecha`, `importe_eur` y las
  `participaciones` que compró, calculadas UNA VEZ al darla de alta con el precio de
  cierre real de ese día. No se recalculan después: lo que cambia con el tiempo es el
  valor de esas participaciones, no cuántas hay.

**El ticker de Revolut no siempre es el símbolo real.** El "SECO" que enseña Revolut
para el iShares MSCI Global Semiconductors UCITS ETF es en realidad **`SEC0`** (con
cero, no con la letra O) — se confunden con la tipografía de la app, y su
`simbolo_yahoo` es `SEC0.DE`. El `ticker` que usa este dashboard es el de Revolut
(para que Mikel lo reconozca); `simbolo_yahoo` es el real, y son campos separados a
propósito.

**`GET /finanzas/etfs`** agrupa las aportaciones por ticker y calcula, por ETF:
`participaciones` y `aportado_eur` (siempre disponibles — son datos propios, no
dependen de ninguna API externa), y `precio_actual` / `valor_actual` / `ganancia_eur`
/ `ganancia_pct` a `None` si Yahoo Finance falló para ese ETF concreto. Mismo criterio
que Indexa cuando falla `/performance`: `None` es "no lo sé", nunca un 0 €. Un ETF que
falla no tumba a los demás.

**`POST /finanzas/etfs/{ticker}/aportaciones`** es el botón "+ Añadir aportación" del
widget: recibe `fecha` + `importe_eur` y, opcionalmente, `hora` (HH:MM). Sin `hora`
pide a Yahoo el precio de **cierre del día** (con una ventana de 7 días hacia atrás
por si cae en fin de semana o festivo — se usa el último día hábil anterior, no un
precio a 0). Con `hora`, primero intenta el precio **horario** más cercano a ese
momento (`interval=60m`, convertida de la zona horaria del usuario a UTC) y solo cae
al cierre diario si Yahoo no tiene velas horarias para esa fecha — pasa con compras
de hace más de ~730 días, que es hasta donde llega esa granularidad. La diferencia
importa: el cierre del día puede alejarse bastante del precio real de una compra
hecha a media sesión, y sin `hora` esto se notó en producción como una ganancia
mostrada por encima de la real. En los dos casos, `participaciones = importe_eur /
precio` antes de guardar.

**`DELETE /finanzas/etfs/{ticker}/aportaciones/{id}`** borra una aportación mal
metida (fecha, importe u hora equivocados). No hay `PATCH`: todos los campos de una
aportación dependen entre sí (cambiar la fecha invalida el precio ya calculado), así
que corregir es borrar y volver a crear.

**`POST /finanzas/etfs`** da de alta un ETF nuevo. Sin botón en el frontend a
propósito: no es una acción del día a día, se usa una vez por ETF (por curl) cuando
Mikel empieza a invertir en uno nuevo.

**La caché de precios actuales** sigue el mismo patrón que la de Revolut:
`ETF_PRECIO_TTL_MINUTOS` (60 por defecto — un ETF no cambia de precio segundo a
segundo, y no conviene abusar de un endpoint no oficial), tupla `(epoch, precios)` en
memoria, y el botón ↻ del widget la salta igual que con Indexa/Revolut. Si falla el
precio de UN ETF concreto, se registra y ese ticker se queda sin precio — no tumba a
los demás.

### Lo que no se hace y por qué

- **Escribir en Indexa** (aportaciones, traspasos). El token puede; el dashboard no debe. Un
  botón que mueve dinero de verdad no pinta en una pantalla que existe para mirar.
- **Guardar el histórico en Supabase.** Ya está explicado arriba: lo da Indexa entero en cada
  respuesta.
- **Meterlo en el resumen diario por correo.** Se puede y quizá se haga, pero un número que
  cambia una vez al día y que no exige hacer nada no es lo mismo que la agenda o el sueño:
  antes de sumarlo al correo hay que decidir qué se supone que haces al leerlo. Mientras
  tanto, Jarvis lo sabe si se le pregunta.
