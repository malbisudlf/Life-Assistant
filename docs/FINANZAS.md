<!-- Parte de la guía del repositorio. El índice y las reglas que aplican
     SIEMPRE están en CLAUDE.md, en la raíz. -->

## Finanzas: la cartera de Indexa Capital

Un widget que dice cuánto hay invertido, cuánto se ha aportado, cuánto lleva ganado y en
qué está puesto. **Solo lectura**: la API de Indexa tiene endpoints que mueven dinero y
aquí no se usa ninguno a propósito — el dashboard es un sitio para mirar el dinero.

De momento **solo Indexa**. Revolut se dejó fuera a sabiendas: su API para particulares no
da acceso a la cuenta personal sin montar una app de negocio con certificados y consentimiento
periódico, que es un proyecto entero y no un widget (ver "Lo que no se hace y por qué").

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

### Los tests

`tests/backend/test_finanzas.py`: las respuestas simuladas **copian la forma de la API real**
(`instrument_accounts` → `positions`, `return.total_amounts`…). Si esa forma cambiara, es ese
fichero el que tiene que enterarse primero. Cubren la agregación, el reparto por clase, el
camino sin rendimiento, la caché, el 502 que no reenvía el cuerpo de Indexa y que el token
viaja en cabecera y no en la URL.

El E2E (`tests/e2e/servidor_pruebas.py`) trae una cartera simulada con 40 días de serie, así
que el widget se pinta con números de verdad en un navegador real.

### Lo que no se hace y por qué

- **Revolut.** Era la otra mitad de la idea. Su API abierta para particulares no existe como
  tal: hay que darse de alta como negocio, generar un certificado, publicar una app y renovar
  el consentimiento cada 90 días — y aun así lo que se saca son movimientos de cuenta, no una
  cartera. No es un widget: es un proyecto. Queda fuera hasta que haya una razón mejor que
  "estaría bien tenerlo todo junto".
- **Escribir en Indexa** (aportaciones, traspasos). El token puede; el dashboard no debe. Un
  botón que mueve dinero de verdad no pinta en una pantalla que existe para mirar.
- **Guardar el histórico en Supabase.** Ya está explicado arriba: lo da Indexa entero en cada
  respuesta.
- **Meterlo en el resumen diario por correo.** Se puede y quizá se haga, pero un número que
  cambia una vez al día y que no exige hacer nada no es lo mismo que la agenda o el sueño:
  antes de sumarlo al correo hay que decidir qué se supone que haces al leerlo. Mientras
  tanto, Jarvis lo sabe si se le pregunta.
