# Que Jarvis haga cosas sin que se las pidas

Ideas para que Jarvis deje de ser algo a lo que hay que acordarse de preguntar. Mismo
formato que `docs/IDEAS.md`: **qué**, **por qué** (la parte que no se puede reconstruir
después) y **por dónde se empieza**, con el esfuerzo orientativo — ● una tarde, ●● medio,
●●● grande o con partes fuera del código.

Lo que ya está hecho (recordatorios, el proactivo de las 19:00, el aviso del reloj, los
vigilantes de ingesta y de sistema) no se repite aquí; está en
`docs/JARVIS.md`. Esto es lo que vendría después.

---

## Parte 0: las tres piezas que faltan antes de añadir una sola regla más

Esta es la parte importante del documento. **Un asistente proactivo tiene exactamente un
modo de fallo: volverse ruido.** Y no falla de golpe — falla porque cada regla nueva
parece razonable por separado, hasta que un día se dejan de leer todos los avisos a la
vez. A partir de ahí da igual lo buenas que sean las reglas siguientes.

Hoy el sistema no tiene ninguna defensa contra eso: cada regla escribe su propio aviso,
ninguna compite con las demás y ninguna sabe si sirvió de algo. Con cinco reglas más,
tienes cinco avisos más. Las tres piezas de abajo son lo que convierte "más reglas" en
"más listo" en vez de en "más ruido", y por eso van antes que cualquier idea de la Parte 1.

### 0.1 Presupuesto de interrupciones ●●

**Qué.** Que los avisos compitan entre sí en vez de sumarse. Una cola con prioridad y un
tope diario (2, quizá 3); lo que no entra no se pierde, baja al resumen de la mañana.

**Por qué.** Ahora mismo el orden en que salen los avisos es el orden en que están
escritas las funciones en `main.py`, que no es ningún orden. Y un día con cuatro cosas
que decir manda cuatro notificaciones al móvil, que es como se enseña a ignorarlas. Un
tope obliga a la pregunta correcta —*¿esto es más importante que lo otro?*— y la respuesta
la da el código, no el modelo.

**Por dónde.** `_notificar()` ya es la única puerta de salida: el presupuesto vive ahí.
Cada aviso entra con una prioridad (entrega hoy > firma de malestar > racha sin entrenar)
y una caducidad (un "sal ya" caducado no vale; un "llevas 3 días sin entrenar" sí).

### 0.2 Señal de utilidad ●●

**Qué.** Que cada aviso pueda contestarse *útil / no útil*, y que una regla cuyos últimos
N avisos se hayan ignorado **se silencie sola y lo diga**.

**Por qué.** Es lo único de esta lista que de verdad hace a Jarvis más listo en el sentido
literal: hoy no hay forma de saber si un aviso sirvió. Sin esa señal, la única forma de
que una regla mala desaparezca es que tú te acuerdes de decirlo, y no te vas a acordar —
vas a dejar de mirar los avisos, que es peor porque se lleva por delante a los buenos.
Con ella, el sistema converge solo hacia lo que usas.

**Cuidado.** Silenciarse sola tiene que ser **visible**: una regla apagada en silencio es
el mismo error que el sistema persigue desde el principio. Y "no útil" no puede
confundirse con "no lo vi": si no hay respuesta, no se sabe — no cuenta como negativa.

**Por dónde.** Las notificaciones de la app de HA admiten botones de acción, que llaman a
un endpoint. Un `POST /avisos/{id}/util` y una columna por regla con las últimas N
respuestas. Sin la app, un enlace en el correo hace lo mismo.

### 0.3 Memoria de lo ya dicho ●

**Qué.** Que no repita algo que ya dijo esta semana si la situación no ha cambiado.

**Por qué.** La idempotencia de hoy es *por día y por regla*: impide dos avisos iguales el
mismo día, pero no impide el mismo aviso siete días seguidos. "Llevas 3 días sin entrenar"
el jueves, el viernes y el sábado son tres avisos de los que solo el primero informa de
algo — los otros dos son la misma frase con un número distinto.

**Por dónde.** `vigilante_estado` ya hace exactamente esto para las averías (clave, veces,
primera vez). Es la misma tabla y el mismo patrón, aplicado a los avisos.

---

## Parte 1: ideas que solo usan lo que ya hay

Ninguna necesita una integración nueva. Todas son una regla en código sobre datos que el
backend ya tiene delante.

### 1.1 «Sal ya» ●

**Qué.** Un evento con ubicación, tú en casa, y el tráfico dice que hay que salir en 10
minutos → aviso. Con el tráfico real, no con una estimación.

**Por qué.** Es lo que más se parece a lo que hace un asistente de verdad, y las tres
piezas están puestas y sin conectar: `/maps/departure` calcula la hora de salida con
tráfico, la presencia dice si estás en casa y el tick de HA pasa cada 5 minutos. Hoy esa
cuenta solo se hace si abres el dashboard y pulsas un botón — o sea, solo si ya te estabas
preocupando por llegar tarde.

**Cuidado.** Solo eventos con ubicación real y solo si estás fuera del sitio. Y una vez
por evento, no cada cinco minutos.

### 1.2 No llegas de una a la otra ●

**Qué.** Dos eventos con ubicación cuyo hueco entre medias es menor que el tiempo de
viaje. Se avisa **la noche antes**, que es cuando todavía se puede mover algo.

**Por qué.** Es un choque que el calendario no marca como choque: las dos citas no se
solapan, así que Outlook las da por buenas. El conflicto solo existe cuando metes el
desplazamiento, que es justo el dato que ya sabes pedir a Google Maps.

### 1.3 Mañana empiezas pronto ●

**Qué.** Si el primer evento de mañana empieza antes de lo habitual, un aviso a las 22:00
diciendo a qué hora tendrías que estar durmiendo para llegar a tus horas.

**Por qué.** El backend sabe a qué hora sueles dormirte (`sleep_start` está en `extra` de
`sleep_analysis`) y a qué hora empiezas mañana. Nadie ha juntado las dos cosas. Es un
aviso que se puede accionar en el momento en que llega, que es la definición de aviso útil.

### 1.4 La firma de malestar, por la mañana ●

**Qué.** Que `_firmaMalestar` (FC en reposo arriba + HRV abajo + respiración arriba, las
tres a la vez) salga por el canal de avisos y no solo en el dashboard.

**Por qué.** Ya está escrita, probada y es la señal más fiable que da el Watch — y hoy
solo la ves si abres el dashboard y bajas hasta las conclusiones. El día que tu cuerpo
dice que no es exactamente el día en que no vas a abrir el dashboard.

**Cuidado.** Vive en `helpers.js` y las conclusiones **no se portan a Python** (regla del
proyecto). O se expone el mínimo por API, o se acepta calcular solo la firma en el
backend, que son tres tendencias. Yo haría lo segundo y lo diría en el código.

### 1.5 Un hueco para entrenar ●●

**Qué.** En vez de «llevas 3 días sin entrenar», mirar la agenda de mañana y decir «mañana
tienes libre de 18:00 a 20:00».

**Por qué.** Convierte un reproche en una acción. El aviso actual te da información que ya
tenías (sabes que no has entrenado); este te da la parte que no tenías, que es cuándo.

### 1.6 Te has dejado algo encendido ●

**Qué.** La presencia pasa a "fuera" y hay luces o enchufes encendidos → aviso.

**Por qué.** El catálogo de la casa ya está en Supabase (`POST /ha/entidades`, con estado)
y la presencia ya llega. La frontera de confirmación por dominio ya está pensada: una luz
se puede apagar sola, una cerradura no. Es aplicar dos cosas que ya existen a un caso que
pasa todas las semanas.

### 1.7 El PC encendido y tú fuera ●

**Qué.** Nadie en casa, el agente sin heartbeat reciente y el PC encendido → proponer
suspender.

**Por qué.** `/suspend-pc` ya existe y lo ejecuta HA por SSH. Es dinero en la factura y no
requiere nada nuevo.

---

## Parte 2: ideas que necesitan una capacidad nueva

Aquí ya no basta con cruzar lo que hay. Todas pasan por conectar un servidor MCP, que es
el camino que el proyecto ya eligió para crecer sin tocar código.

### 2.1 Vigilar una página ●●

**Qué.** «Avísame cuando esta página cambie / cuando baje de X». Una tabla de vigilancias
(url, qué buscar, última vez), el tick de HA como reloj y `leer_pagina`, que ya existe con
su protección de SSRF.

**Por qué.** Es la capacidad proactiva **genérica**: en vez de una regla nueva por cada
cosa que quieras vigilar, una que las cubre todas y que puedes crear hablando. Precio de
algo, una plaza que se libera, una nota que se publica, un horario que cambia.

**Cuidado.** El contenido viene de fuera y va a un modelo con herramientas: sigue haciendo
falta `_AVISO_WEB`. Y un tope de vigilancias, que cada una es una descarga por tick.

### 2.2 El correo entrante ●●

**Qué.** Leer el buzón (MCP de Gmail, o IMAP) para lo que tiene fecha: un paquete que
llega hoy, una factura que vence, una cita confirmada que no está en el calendario.

**Por qué.** Es la fuente de información diaria más rica que hay y hoy el backend solo
sabe **escribir** correo, no leerlo. Ojo: no es "resumir el buzón" —eso ya lo hace la
rutina del briefing y hacerlo dos veces sería peor— sino **extraer lo accionable con
fecha** y meterlo donde vive lo demás: el calendario y los recordatorios.

### 2.3 Una lista de tareas de verdad ●●

**Qué.** Conectar un gestor de tareas (Todoist, Notion) por MCP, para que las ideas por
voz que son tareas acaben donde las miras.

**Por qué.** Hoy una idea por voz que sea una tarea se queda en la lista de ideas, que es
un sitio donde las cosas van a morir tranquilas. El paso de "lo dije" a "está en mi lista"
lo tienes que dar tú.

---

## Parte 3: que aprenda de ti

Esto es lo que separa "muchas reglas" de "más listo", y encaja con la regla del proyecto
—el listón va en código— si se hace de una manera concreta: **el modelo propone la regla,
tú la apruebas, y la regla aprobada pasa a ser configuración, no criterio del modelo.**

### 3.1 Horas aprendidas en vez de constantes ●●

**Qué.** Que las 19:00 del proactivo y las 21:30 del aviso del reloj salgan de tus datos:
tu hora habitual de acostarte, de despertarte, de entrenar.

**Por qué.** Son constantes elegidas a ojo un día. El backend tiene meses de `sleep_start`
y de horas de despertar; un aviso de "ponte el reloj" tiene que llegar **antes de que te
duermas**, y esa hora la sabe él mejor que la constante.

### 3.2 Que proponga sus propias reglas ●●●

**Qué.** Que al detectar un patrón repetido (siempre mueves el entreno del martes, siempre
llegas tarde a la misma cita) proponga una regla, y que aprobarla la deje escrita en una
tabla de reglas activas.

**Por qué.** Es la única forma de que crezca sin que tú tengas que pensar en cada caso, y
sin romper la frontera: la propuesta la hace el modelo, la decisión la tomas tú y **la
ejecución es determinista**. Mismo patrón que `mcp_conectar` — el modelo propone, el botón
de confirmar aprueba, y lo aprobado queda escrito.

### 3.3 Informe de utilidad ●

**Qué.** Una vez al mes, en el informe semanal: cuántos avisos mandó, cuáles se
respondieron, cuáles se ignoraron, qué reglas están calladas.

**Por qué.** Es la pieza 0.2 mirada desde arriba, y es la que evita que el sistema
envejezca mal sin que nadie se entere.

---

## Lo que no haría

- **Dejar que el modelo decida cuándo hablar.** Ya está escrito en `docs/JARVIS.md` y sigue
  siendo verdad: acaba en un aviso diario porque sí. El modelo redacta lo que el código ha
  decidido.
- **Avisos de ánimo o de coaching.** «¡Buen trabajo esta semana!» no es información, y
  cada uno de esos gasta el crédito de atención que necesita el aviso que sí importa.
- **Cruzar los entrenos del Watch con las sesiones de entrenamiento personal.** Descartado
  a propósito en `docs/IDEAS.md`, agosto de 2026, y sigue descartado.
- **Que Jarvis actúe sobre la casa por su cuenta más allá de lo obvio.** Apagar una luz que
  te dejaste es un caso; decidir la temperatura es otro, y el día que se equivoca no hay
  forma de saber por qué lo hizo.

---

## Por dónde empezaría

| Orden | Qué | Esfuerzo | Por qué ahí |
|---|---|---|---|
| 1 | 0.1 Presupuesto de interrupciones | ●● | Sin esto, todo lo demás envenena el canal |
| 2 | 1.1 «Sal ya» | ● | Máximo valor diario con cero piezas nuevas |
| 3 | 0.2 Señal de utilidad | ●● | Es lo que hace que el sistema mejore solo |
| 4 | 1.3 Mañana empiezas pronto | ● | Accionable en el momento en que llega |
| 5 | 1.4 Firma de malestar | ● | Ya está escrita; solo le falta el canal |
| 6 | 2.1 Vigilar una página | ●● | La capacidad proactiva genérica |

Las tres primeras son, en conjunto, la diferencia entre un asistente que interrumpe y uno
que se lee. El resto son reglas, y las reglas son la parte fácil.
