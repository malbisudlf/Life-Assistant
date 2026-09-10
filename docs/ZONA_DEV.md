<!-- Parte de la guía del repositorio. El índice y las reglas que aplican
     SIEMPRE están en CLAUDE.md, en la raíz. -->

# La zona de desarrollo

Una vista propia, a pantalla completa, a la que se entra con el botón 🛠 de la esquina
superior derecha del dashboard. No es un widget ni un modal: es **otra aplicación dentro
de la aplicación**, con sus propias pestañas, y su público es una sola persona haciendo
una sola cosa — mirar cómo va el sistema y decidir qué tocar después.

## Por qué existe

Las señales de si esto funciona ya estaban todas, pero repartidas: los logs en un
endpoint, el gasto en otro, el SHA desplegado en `GET /`, las migraciones en un directorio
que hay que comparar a ojo con Supabase, y las ideas en un fichero Markdown de 373 líneas.
Averiguar "¿qué está roto y desde cuándo?" costaba abrir cinco sitios, y por eso **no se
hacía**: la copia de seguridad de Supabase estuvo meses fallando en cada ejecución sin que
nadie lo notara, y una migración pasó un mes sin aplicar rompiendo dos cosas a la vez.

La zona dev es la respuesta a eso: **un sitio donde mirar antes de tocar nada**, y donde
apuntar lo que se ha visto para que no se olvide.

Lo que ya existía dentro del panel ⚙ (backend, agente, presencia, avisos, registro,
gasto) se muda aquí y crece. En ⚙ queda una sola línea de resumen con enlace: lo que se
mira deprisa desde el móvil sigue estando a un toque, y el detalle no se duplica.

## Dónde retomar

**Estado al 2026-09-10.** La fase 1 está en `main` (PR
[#164](https://github.com/malbisudlf/Life-Assistant/pull/164)). De la fase 2 están hechas
**Despliegue y Crons**; quedan **Base de datos y Configuración**, que van en un PR aparte.

Nada de esto se ha abierto todavía en un navegador contra el backend real. Lo que falta
para que funcione de verdad, en orden:

1. **Aplicar `supabase/migrations/20260909_ideas_dev.sql`** a mano en el editor SQL de
   Supabase. Mientras no esté, `GET /dev/ideas` responde 502 y la pestaña lo dice en
   pantalla nombrando la migración.
2. **Reconstruir el add-on** del Home Assistant Green cuando esto esté en `main`: los
   endpoints (`/dev/ideas`, `/dev/despliegue`, `/dev/crons`, los filtros de `/logs`) viven
   en el backend, que no se despliega solo. Comprobar con `GET /` que el `version`
   coincide — o, mejor, mirarlo en la propia pestaña Despliegue, que es para lo que está.
3. Abrir el 🛠 y mirar si el semáforo dice la verdad, que es lo único que estos tests no
   pueden comprobar.

Para la **pestaña Base de datos** hay una decisión ya tomada y sin ejecutar: las
migraciones aplicadas se sabrán por una **tabla de registro** (`migraciones_aplicadas`),
no sondeando el esquema. Eso significa una migración nueva que la cree e inserte las que
ya están puestas, y una convención a partir de ahí: **cada `.sql` nuevo termina
insertando su propio nombre**. Se eligió frente a sondear tabla por tabla porque el
sondeo hay que mantenerlo a mano —un mapa migración → tabla— y una migración sin entrada
en ese mapa pasa desapercibida, que es justo el fallo que la pestaña viene a evitar.

Lo que quedó decidido y no hace falta volver a discutir: dónde vive (vista propia, no
modal), qué pasa con ⚙ (una línea y un enlace), la forma de una idea (la de
`docs/IDEAS.md`, pero guardando con solo el título), el refresco (automático solo en lo
que es gratis) y qué puede tocar la zona dev (vaciar el registro, forzar envíos,
reintentar jobs; nunca desplegar).

Al añadir una pestaña: un fichero en `src/components/dev/`, su entrada en `PESTANAS` de
`ZonaDev.jsx` con `fase: 1` para encenderla, y la lógica que se pueda probar sin pantalla
a `src/lib/dev.js`, que es donde están los tests.

## Decisiones de forma

| Decisión | Por qué |
|---|---|
| Vista a pantalla completa, no modal | Son muchas pestañas y tablas densas: en un modal no cabe, y en un widget menos. El dashboard queda intacto. |
| Sin router: un estado más en `Dashboard.jsx` | El proyecto no tiene router a propósito (CLAUDE.md). La vista se enciende con un `useState`, como los modales. |
| Pensada para escritorio | Es donde se desarrolla. En móvil se ve, pero no se optimiza: para el móvil ya está el resumen de ⚙. |
| Misma paleta, más densidad | Las variables CSS del dashboard (`--bg`, `--accent`…), pero monoespaciada en los datos, tablas finas y mucha información por pantalla. Se tiene que notar que es otra zona. |
| Ficheros propios en `src/components/dev/` | **Excepción explícita a la regla de "toda la UI en `Dashboard.jsx`"**, anotada también en CLAUDE.md. La regla existe para que un widget no se convierta en un fichero suelto; esto no es un widget: son miles de líneas que ninguna sesión que vaya a tocar el dashboard necesita cargar. Una pestaña por fichero. |

## La regla del dinero

**Nada que cueste dinero se refresca solo.** El refresco automático solo puede llamar a
endpoints que peguen contra el propio backend o contra Supabase, que son gratis. Todo lo
que acabe en OpenAI, Whisper o ElevenLabs va detrás de un botón explícito que dice que
cuesta, y no se dispara al abrir la pestaña.

Es la misma regla que gobierna el modo llamada (el micro del navegador es gratis y por eso
se usa; Whisper se paga y por eso no) y no es negociable en una zona que uno deja abierta
en una pestaña del navegador toda la tarde.

## Qué puede tocar

La zona dev no es solo de lectura, pero solo hace cosas que ya existen como endpoint y que
son reversibles o repetibles: vaciar el registro (`DELETE /logs`), forzar el resumen
diario o el informe semanal (`POST /brief/send`, `POST /informe/send`), reintentar un job
del PC (`POST /jobs/{id}/retry`) y despertarlo (`POST /wake-pc`).

**No despliega.** El despliegue del backend sigue siendo pulsar *Reconstruir* en el add-on
del Home Assistant Green, a mano. La pestaña de despliegue dice si entró; no lo lanza.

## Las pestañas

Por fases. Cada fase es un PR.

### Fase 1 — el armazón y lo que se usa a diario

1. **Ideas** — la checklist. Tabla `ideas_dev` en Supabase con la forma que ya usa
   `docs/IDEAS.md` al pensar (qué, por qué, por dónde se empieza, esfuerzo, área, estado),
   porque es el formato que sirve para decidir dentro de tres meses y el que le sirve a
   una sesión de Claude para ejecutarla. Se crea rápido —título y Enter— y se completa
   después: si escribir una idea da pereza, no se escribe.
2. **Estado** — lo que hoy enseña ⚙, ampliado: backend y su latencia, agente PC,
   presencia, avisos, registro, gasto.
3. **Logs** — `app_logs` con filtro por nivel y por fuente, búsqueda de texto, el
   `context` completo de cada entrada y refresco en vivo.

### Fase 2 — qué está roto

4. **Despliegue** (hecha) — el sha del Green contra el `main` de GitHub contra el que
   sirve Vercel, con la lista de commits que le faltan al backend. Responde de un vistazo
   "¿entró la reconstrucción?", que ya mordió una vez. **No reconstruye**: eso se pulsa a
   mano en Home Assistant, y la pestaña lo recuerda en vez de ofrecer un botón que no
   puede existir.
5. **Crons** (hecha) — el último run de cada workflow programado, los envíos del resumen
   y del informe, las averías abiertas del vigilante y **quién sigue sondeando**.
6. **Base de datos** — filas por tabla y qué migraciones están aplicadas (ver «Dónde
   retomar» para cómo se va a saber).
7. **Configuración** — qué variables tiene puestas el backend y cuáles le faltan: lo que
   `backend/check_config.py` sabe, pero sin consola, y qué credenciales caducan. Nunca el
   valor: solo si está y si sirve.

### Lo que se decidió al escribir Despliegue y Crons

| Decisión | Por qué |
|---|---|
| El sha del frontend lo aporta el navegador | El despliegue de Vercel no pasa por el backend, así que nadie más lo sabe. `vite.config.js` hornea `VERCEL_GIT_COMMIT_SHA` en el bundle como una `VITE_*` más; en local vale `dev` y la pestaña lo dice en vez de comparar contra nada. El backend lo valida como sha antes de meterlo en una URL de GitHub. |
| El refresco automático depende de `DEPLOY_GITHUB_TOKEN` | La regla del dinero no aplica —la API de GitHub es gratis— pero la cuota sí: 60 peticiones/hora sin credencial, que una pestaña abierta se gasta sola. Con token son 5.000 y se refresca; sin él, solo a botón, y la pantalla dice por qué. |
| La lista de programados va a mano en `backend/main.py` | Un workflow no publica su cron por la API, y el contenedor del add-on solo lleva `backend/`. Va en la constante `PROGRAMADOS`, y **un test la compara con los `.yml` que llevan `schedule:`**: si se añade un cron y no se apunta aquí, falla el CI. Sin ese test, la lista se quedaría atrás exactamente igual que se quedó atrás la copia de seguridad. |
| Un cron que corrió BIEN pero hace demasiado también es rojo | La copia de Supabase falló meses seguidos; lo contrario —que deje de dispararse— no produce un solo run rojo al que agarrarse. Se compara con `cada_horas` por el doble de margen (`PROGRAMADO_MARGEN`), que absorbe los 10-15 min de retraso de GitHub y las noches sin commits de la revisión nocturna. |
| Los sondeos se cuentan en memoria | Es una escritura cada 15 segundos, siete días a la semana: guardarla costaría más de lo que vale. Se pierden al reiniciar, y por eso `/dev/crons` da también cuánto lleva el proceso en pie — «no ha sondeado» y «no ha sondeado desde que arranqué hace 40 segundos» son cosas distintas. |
| La marca del sondeo la pone el middleware | Son diez rutas y se olvidaría justo en la que se caiga. Un 403 **no** cuenta como sondeo: HA llamando con el token mal es exactamente el fallo que hay que ver. |
| El agente PC y la llamada no se pintan en rojo por callar | El PC está apagado la mayor parte del día. Llamar avería a eso es llamar avería a la noche, y una pantalla que grita cuando todo está bien deja de mirarse. |

### Fase 3 — qué pasó

8. **Línea de tiempo** — todo lo de hoy en un solo hilo cronológico: ingestas, avisos,
   jobs, correos, errores. Hoy vive en cinco tablas y no hay forma de ver la secuencia.
9. **Agente y jobs** — heartbeat, cola, eventos de cada job, reintentar.
10. **Salud de los datos** — sobre `GET /health/diagnostico`: si llegan datos, de qué
    fuente, qué se descartó y por qué.
11. **Avisos y reglas** — qué salió, por qué (`GET /avisos/{id}/porque`), qué está apagado
    y qué reglas siguen vivas.

### Fase 4 — el resto

12. **Gasto** — con histórico y por día. Incluye lo que hoy da `GET /gasto` (OpenAI vía
    Jarvis), más ElevenLabs (voz y Scribe) y el consumo contra los límites del plan
    gratuito de Supabase, Vercel y Cloudflare. Las suscripciones fijas quedan fuera: no
    hay API que las dé y una cifra escrita a mano envejece mal.
13. **CI, PRs y revisión nocturna** — último run, PRs de ramas `claude/*`, hallazgos sin
    atender.
14. **Rendimiento** — cuánto tarda cada servicio del que esto depende y cuántas veces ha
    fallado. Requiere que el backend empiece a medirlo: hoy no se guarda.
15. **Consola de endpoints** — lanzar cualquier endpoint con la sesión ya puesta y ver la
    respuesta cruda.
16. **Interruptores** — todo lo que se enciende, apaga o pausa, en un solo sitio.
17. **Banco de pruebas de Jarvis** — el prompt completo, qué herramienta elige y los
    tokens de esa llamada. **Cuesta dinero: solo bajo botón.**
18. **Evals** — resultados guardados de `evals/`. No lanza tandas desde la web (cuestan).
19. **Diario de cambios** y **mapa del proyecto** — los últimos commits con si están ya
    desplegados, y el repo de un vistazo.
