# Life Assistant, explicado de arriba abajo

> Este fichero no es guía de trabajo: es la explicación del proyecto entero para alguien
> que llega de fuera y quiere entender qué es, qué hace y por qué está construido así.
> Para trabajar en el código, el índice sigue siendo `CLAUDE.md`.

---

## 1. Qué es esto en una frase

Un panel personal de **un solo usuario** que reúne en una pantalla el calendario, la
salud del Apple Watch, los entrenamientos, las ideas, la casa y el PC — y encima de todo
eso, un asistente que consulta, actúa y **habla sin que se le hable**.

Empezó siendo un dashboard. Hoy es más bien un pequeño sistema operativo de la vida
diaria: manda el correo de la mañana, avisa al móvil de que hay que salir ya, enciende el
PC desde la cama, vigila que los datos sigan llegando, revisa su propio código de
madrugada y abre un issue si encuentra algo.

---

## 2. El problema de fondo: cinco islas que no se hablan

Casi todo lo interesante del proyecto sale de una sola realidad incómoda: **los datos que
componen un día viven en sitios que no pueden llamarse entre sí.**

| Isla | Dónde vive | Por qué no se deja llamar |
|---|---|---|
| El calendario | Outlook / Microsoft Graph, en la nube | Necesita OAuth y tokens que caducan |
| La salud | En el iPhone, junto al Apple Watch | Solo sale de ahí cuando el móvil quiere |
| La casa | Home Assistant, en la red local | No tiene IP pública; el navegador (HTTPS) no puede llamar a un HTTP de la LAN |
| El PC | Windows, **apagado** la mayor parte del tiempo | Un ordenador apagado no atiende peticiones |
| El histórico | PostgreSQL en Supabase | Solo entra el backend, con la service key |

El proyecto es, en el fondo, **la fontanería entre esas islas**. Y esa fontanería es lo
que le da su forma: como casi nadie puede llamar a casi nadie, todo se resuelve con
**colas, sondeos y banderas**, no con llamadas directas. Quien pueda preguntar, pregunta;
quien sepa algo, lo empuja.

---

## 3. El mapa

```
                        ┌───────────────────────────────┐
                        │  Navegador (React 19 + Vite)  │
                        │      desplegado en Vercel     │
                        └───────────────┬───────────────┘
                                        │ JWT + REST
                                        ▼
        ┌──────────────────────────────────────────────────────────┐
        │   backend/main.py — FastAPI en Fly.io (escala a CERO)     │
        │   un solo fichero, ~10.700 líneas, 73 endpoints           │
        └───┬───────┬───────┬────────┬────────┬────────┬───────────┘
            │       │       │        │        │        │
            ▼       ▼       ▼        ▼        ▼        ▼
        Microsoft  Google  Open-   OpenAI  Supabase  colas en
         Graph      Maps   Meteo   (Whisper (Postgres) memoria
       (calendario)(tráfico)(clima) +GPT)   histórico  (órdenes)
                                                │        │
                                                │        │  sondeo
                                                ▼        ▼
   Apple Watch ──► Health Auto Export ──► POST /health/ingest
   (+ Atajo iOS)                                      │
                                                      ▼
                             ┌───────────────────────────────────────┐
                             │ Home Assistant (red local, siempre ON)│
                             │  · sondea órdenes cada 15–30 s        │
                             │  · tick del reloj cada 5 min          │
                             │  · EMPUJA presencia y catálogo        │
                             │  · manda avisos al móvil y a Alexa    │
                             └───────────────┬───────────────────────┘
                                             │ WOL / SSH
                                             ▼
                             ┌───────────────────────────────────────┐
                             │  PC Windows + agent/agent.py          │
                             │  agente EFÍMERO: arranca, drena la    │
                             │  cola de jobs y se cierra             │
                             └───────────────────────────────────────┘
```

Fíjate en la dirección de las flechas: **el backend casi nunca llama a la casa**. Deja
una orden en una cola y Home Assistant viene a buscarla. Y cuando el que sabe algo es HA
(dónde estás, qué dispositivos hay), es HA quien lo empuja. Esa asimetría no es un
capricho: es la única forma que hay de cruzar la frontera de la red local.

---

## 4. Las piezas, una a una

### Frontend — `src/components/Dashboard.jsx`
React 19 sobre Vite, en Vercel, **deploy automático al hacer push a `main`**. Sin router,
sin gestor de estado, sin ORM, sin framework de CSS: un componente principal de ~5.600
líneas con `useState`/`useEffect`, y la lógica pura extraída a `src/lib/helpers.js`
(~1.560 líneas, testeada aparte).

Es una decisión, no una deuda: el proyecto es de una persona y un solo fichero de UI se
navega con `grep` de los banners. Lo que sí está prohibido es meter lógica ahí — todo lo
que se pueda testear se va a `helpers.js`.

Encima de eso: PWA instalable, layout de 2 o 3 columnas con divisores arrastrables,
widgets configurables (visibles, columna, orden, tamaño) persistidos en `localStorage`, y
un **modo simple** para el móvil que reutiliza los mismos widgets con otra distribución.

### Backend — `backend/main.py`
FastAPI en Fly.io (región `cdg`), **un solo fichero de ~10.700 líneas** con 73 endpoints,
organizado por banners `# ── NOMBRE ──`. Escala a cero cuando no hay tráfico: de ahí el
arranque en frío de 10–15 s (y de ahí la mitad de las decisiones de diseño del proyecto).

Deploy **manual** a propósito (`fly deploy`): afecta a producción real.

### Base de datos — Supabase
PostgreSQL por REST, accesible **solo desde el backend** con la service key. 24 migraciones
aplicadas a mano desde el editor SQL — no hay tooling de migraciones. Toda tabla nueva
lleva `enable row level security` sin políticas: la anon key de Supabase es pública por
diseño, así que sin RLS cualquiera con la URL entraría al REST desde internet.

### Home Assistant
En la red local, siempre encendido. Hace tres papeles distintos:
1. **Ejecutor**: recoge órdenes del backend (encender el PC, apagar una luz, mandar un aviso).
2. **Reloj**: un `time_pattern` cada 5 minutos que despierta al backend. Es *el* reloj del sistema.
3. **Sensor**: empuja al backend dónde estás y qué dispositivos hay en casa.

### Agente PC — `agent/agent.py`
Un agente **efímero** de Windows: arranca con el PC (empujado por un Wake-on-LAN), drena
la cola de jobs, y se cierra. ~1.000 líneas de Playwright + `pyautogui` + control de
servicios. No tiene tests ni puede tenerlos: necesita un Windows real con Edge, Sunshine y
Claude Desktop instalados.

### Apple Watch
Los datos llegan por dos caminos en paralelo: la app **Health Auto Export** (métricas +
entrenos + fases de sueño) y un **Atajo de iOS** con horarios fijos (las métricas del día
en tiempo real). Los dos escriben en la misma tabla, y cada fila lleva firma de quién la
escribió para poder saber cuál de los dos ha dejado de funcionar.

---

## 5. Qué hace, módulo a módulo

### Agenda y tiempo
Timeline de hoy que mezcla el calendario general y el de clases, con indicador de evento
activo. Botón «¿A qué hora salir?» que llama a Google Maps Distance Matrix **con tráfico
real** y elige el origen en tres escalones: la geolocalización del navegador → dónde dice
Home Assistant que estás → la dirección de casa. Crear y editar eventos de Outlook desde
el propio panel, con selectores de fecha y hora escritos a mano (los nativos dependen del
locale del sistema operativo, y en un Windows en inglés `08/06/2026` se leía como
mes/día). Detección de entregas por un emoji marcador en el título, ordenadas por
urgencia.

### Salud
El módulo más grande. Del Watch entran ~20 métricas al día. Encima:

- **Bienestar**: puntuación 0–100 con desglose por componente (sueño 25 · actividad 30 ·
  recuperación 25 · forma 10 · estilo de vida 10), con vista «Hoy» y vista «Semana».
- **Sueño**: duración, fases (profundo / REM / core / despierto), puntuación propia y un
  botón para **anular una noche** cuando el reloj estaba en el cargador.
- **Motor de conclusiones**: frases en lenguaje natural derivadas de los datos —
  tendencias, cruces entre series (¿duermes peor los días que andas menos?), y una **firma
  de malestar** que solo salta cuando coinciden las tres señales a la vez (FC en reposo
  arriba + HRV abajo + respiración arriba).
- **Línea base personal**: en las métricas de fisiología, el listón sale de los
  percentiles de tu propio histórico, no de un umbral fijo. Con una FC basal de 62, los
  puntos de «≤50» no se sacan nunca por mucho que mejores.
- **Uso del reloj**: el sistema sabe qué días llevaste el Watch puesto, y separa tres
  estados que no son lo mismo — *lo llevabas*, *no lo llevabas pero el móvil sí midió*, y
  *no llegó absolutamente nada*. Sin ese denominador, un mes de vacaciones sin reloj se
  lee como un mes de empeoramiento.

### Entrenamiento personal
Contador de sesiones desde el último cobro, horas acumuladas, importe pendiente. El precio
por hora y las sesiones por cobro salen de la base de datos, no del código.

### Ideas por voz
Grabas → Whisper transcribe → GPT-4o-mini extrae título, categoría y resumen → se guarda.
Si la nota apunta a una cita, el panel **ofrece** crear el evento con un chip. Nunca lo
crea solo.

### Hogar y PC
Wake-on-LAN desde el navegador (pasando por el backend y HA), apagado y suspensión por
SSH, notificaciones habladas por Alexa 15 minutos antes de cada evento con **el nombre**
del evento, y control de luces, enchufes y persianas hablando con el asistente.

### Jarvis
El asistente. Sección propia, más abajo.

### El correo de la mañana
Un resumen diario con **los datos del día en crudo, sin interpretar**. No hay ninguna
llamada a un modelo dentro: quien lo lee es una rutina externa que redacta el briefing de
verdad. Lo interesante está en el detalle: cada media va con su `n` (cuántos días de dato
tiene dentro de la ventana), las series diarias van con los huecos marcados y nunca
comprimidos, se marcan los **días atípicos** (±2σ de la propia ventana de cada métrica,
calculada *sin el propio día*, porque si no un valor extremo tira de la media hacia sí
mismo y se tapa solo), y lo primero que se lee es **qué ha cambiado desde ayer**.

Los domingos sale además un informe semanal con medias **por semana** de los últimos tres
meses: una media de 30 días dice dónde estás, trece semanas seguidas dicen hacia dónde
vas.

---

## 6. Las cinco decisiones que explican todo lo demás

### 6.1 Fly escala a cero, así que el reloj lo pone la casa

El backend se duerme cuando nadie lo llama. Eso significa que **no hay ningún proceso vivo
dentro del backend capaz de mirar la hora**. Un `while True: sleep(60)` no existe aquí.

Así que el reloj es externo: Home Assistant tiene un `time_pattern` cada 5 minutos que
llama a `POST /ha/brief-tick`. Ese tick es lo que despacha los recordatorios, evalúa las
reglas proactivas, revisa el correo entrante, vigila la ingesta y vigila el sistema. Se
eligió HA y no el cron de GitHub Actions porque **Actions se retrasa 10–15 minutos** cuando
su cola va cargada, y un disparador que no sabe decirte a qué hora va a disparar no vale
para algo que tiene que pasar «al despertarte».

Corolario: el tick tiene que ser **barato**. Antes de la hora tope no toca la base de datos
para nada.

### 6.2 Órdenes en memoria, estado en la base de datos

Dos patrones, y la diferencia importa:

- **Órdenes** (enciende el PC, apaga esa luz, manda este aviso): viven en una cola **en
  memoria** del backend. Home Assistant sondea, y leerlas las consume. Si Fly se duerme y
  se pierden, el coste es volver a pulsar un botón. Aceptable.
- **Estado** (dónde estás, qué dispositivos hay, si el resumen de hoy ya salió, si el
  correo está pausado): va a **Supabase**. Un apagado que no sobrevive a un arranque en
  frío se enciende solo a la mañana siguiente, que es justo lo que se pidió que no pasara.

Cada vez que aparece una funcionalidad nueva, la primera pregunta es a cuál de los dos
grupos pertenece.

### 6.3 La idempotencia es un INSERT, no una comprobación previa

El resumen diario tiene **tres disparadores** distintos (el Atajo del iPhone al desenchufar
el cargador, la llegada de los datos de sueño del Watch, y el tick de HA pasada la hora
tope). Los tres pasan por la misma puerta, y esa puerta **reserva el día insertando una
fila antes de mandar el correo**: el 409 contra la clave primaria es lo que hace la
pregunta atómica.

Con un `GET` previo, dos disparadores que coincidan en el mismo minuto leen los dos «no
enviado» y mandan dos correos. Y si el envío falla, la reserva se libera — porque si no, un
error de SMTP de un minuto te deja sin briefing hasta mañana.

### 6.4 La frontera de confirmación

El asistente tiene 51 herramientas. Algunas las ejecuta él solo; otras **solo las propone**
y hace falta un botón.

La línea no es «peligroso / no peligroso», es más precisa: **lo que ya tiene un botón en el
dashboard lo ejecuta el modelo** (encender el PC, guardar una idea, encender una luz — pedir
permiso para lo que se hace con un clic solo estorba). **Lo que toca el calendario, conecta
un servidor MCP nuevo, o abre una cerradura, se propone**. Y el botón de confirmar enseña
los **argumentos reales** de la llamada, no lo que el modelo haya redactado — traduciendo
los ids a nombres con lo que el dashboard ya tiene cargado, porque el nombre no puede venir
de quien hay que desconfiar.

Ante la duda, se pide confirmación. Se falla siempre hacia el lado seguro.

### 6.5 «No pude preguntar» no es «no hay nada»

Esta es la moraleja que atraviesa el proyecto entero, y viene de haberla aprendido tres
veces:

- El agente PC capturaba cualquier excepción al consultar la cola y devolvía `None` — el
  mismo valor que «la cola está vacía». Cuando su token caducó, el agente arrancaba, decía
  «no hay jobs pendientes» y se cerraba con código 0. Desde fuera parecía que todo
  funcionaba.
- La ingesta del Watch respondía `200 {"ok": true}` con el error escondido en una clave que
  nadie lee. Estuvo días sin guardar nada.
- El resumen diario, si no podía leer si estaba pausado, se habría callado — leyendo «no he
  podido preguntar» como «estaba apagado» cuesta un día entero de briefing sin que nada lo
  parezca.

Hoy la regla está en todas partes: un fallo de escritura corta con un 502; una herramienta
que revienta devuelve el error al modelo en vez de un `None`; y si no se puede comprobar si
un aviso está silenciado, **se manda igual** — repetir un aviso molesta, callarlo puede
costar el dato.

---

## 7. Jarvis

### Un cerebro, muchas bocas
Entra lenguaje natural, sale una respuesta habiendo consultado o actuado por el camino. El
cliente **solo manda texto**: toda la decisión de qué herramienta usar vive en el backend,
para que el día que se le hable desde otro sitio (el PC, un altavoz) no haya que
reimplementarla.

Las 51 herramientas **no son integraciones nuevas**: son envoltorios de los endpoints que
ya existen, llamados igual que los llama el resumen diario, para heredar su normalización y
su manejo de errores. Añadir una capacidad es añadir una entrada a un diccionario, y de ahí
salen a la vez el esquema que ve el modelo, el despachador y la puerta de confirmación.

### Dos modelos, y la diferencia es la que separa hablar de actuar
Un modelo pequeño acierta bien decidiendo **si** hace falta una herramienta, y falla
eligiendo **cuál** en cuanto hay muchas parecidas (medido contra el MCP de GitHub:
pidiéndole leer issues escogía `add_issue_comment`). Así que:

1. La primera vuelta la tira el pequeño.
2. En cuanto pide una herramienta, esa misma vuelta **se relanza con el modelo grande** y
   lo que pidiera el pequeño se descarta sin ejecutarse.
3. El cierre —redactar con los datos ya delante— vuelve al pequeño.

Una conversación que no toca nada no le paga al grande ni una llamada. Y el relanzamiento
salta también **cuando el pequeño se niega**: negarse es la única respuesta que no puede
darse sin haberla comprobado.

### Detalles que no son detalles
- **Un turno nunca sale vacío.** Un modelo de razonamiento cobra su techo de tokens contra
  lo que piensa *más* lo que dice, así que con el techo a secas se lo gastaba pensando y
  devolvía cadena vacía — y justo en las peticiones grandes, que son las que más piensa. Hay
  una reserva de razonamiento por encima del techo de la respuesta, y una garantía en el
  punto único de salida: si aun así no hay nada, se contesta con lo que el backend sabe.
- **Lo que cambia cada minuto va al final del prompt.** El caché de la API se calcula sobre
  el prefijo, así que la hora metida en el system invalidaba en cada minuto los ~4.800
  tokens estables que viajan en todas las llamadas. Medido: 3.667 tokens de entrada por
  llamada, de los que se cachean 3.456 (el 94 %).
- **Por voz cambia el prompt, no el cerebro**: frases cortas, sin listas ni markdown ni
  URLs, y otro techo de tokens. Lo que se escucha no se puede ojear.
- **El backend no guarda conversaciones.** El historial viaja en cada petición y vive en el
  `localStorage` del navegador. Menos estado que mantener y nada que purgar.
- **Modo llamada**: hablar seguido sin pulsar enviar. El micro se cierra mientras Jarvis
  habla (por altavoz se oía a sí mismo, se transcribía y se contestaba solo: una llamada
  infinita que además se paga), el fin de frase lo decide el silencio y no el navegador, y
  la sesión de reconocimiento se reabre sola porque Chrome la corta cada pocos segundos.
- **La voz es del navegador**, entrada y salida. Gratis y sin salir del dispositivo. Whisper
  se paga por minuto y no compensa para dictar una frase.

### Memoria, MCP e internet
- **Memoria**: los hechos duraderos (preferencias, objetivos, decisiones) se destilan al
  cerrar una conversación larga y se guardan con clave. El historial no; son datos distintos
  con reglas distintas.
- **Cliente MCP**: se conecta a servidores MCP por HTTP, con lista blanca **del usuario**.
  El modelo elige *entre* los servidores aprobados, nunca añade uno — un modelo que decide
  sus propios endpoints es un canal de exfiltración con tus datos como argumentos. Puede
  proponer añadir uno; conectarlo pasa por el botón.
- **Internet**: buscar y leer páginas, con dos defensas. Contra **SSRF**, la URL se resuelve
  y se exige que todas sus IPs sean públicas, revalidando **en cada salto de redirección**
  (el backend vive donde `169.254.169.254` son las credenciales de la instancia). Y el error
  no dice por qué se rechazó, para no convertir la herramienta en un escáner de red. Contra
  la **inyección de prompt**, lo que vuelve de la web va envuelto y etiquetado como DATO NO
  FIABLE. No es una garantía —contra la inyección no hay ninguna— pero es la diferencia entre
  ponérselo difícil y servírselo en bandeja.
- **Conciencia de sí mismo**: hay una herramienta que responde qué sabe hacer, **qué tiene
  apagado y por qué**, y cómo puede crecer. Un asistente que no sabe de lo que es capaz falla
  de las dos maneras a la vez: dice que no puede lo que sí puede, e inventa lo que no.

---

## 8. Lo proactivo, y su único modo de fallo

Un asistente que solo contesta obliga a acordarse de preguntar, que es justo lo que no
funciona. Así que el sistema habla primero: «sal ya» calculando el tráfico, «no llegas» a
dos citas que no se solapan pero entre las que no da tiempo a moverse, «mañana empiezas
pronto» cruzando el primer evento con tu hora habitual de dormirte, «ponte el reloj» antes
de que te duermas, huecos libres para entrenar, la firma de malestar.

**Un asistente proactivo tiene un solo modo de fallo: volverse ruido.** Y no falla de
golpe — falla porque cada regla parece razonable por separado hasta que un día se dejan de
leer todos los avisos a la vez, buenos incluidos. Tres piezas lo gobiernan, y las tres viven
en la puerta común y no en cada regla, para que una regla nueva las herede sin poder
olvidarse:

1. **Presupuesto**: los avisos **compiten** en vez de sumarse. Tres al día por defecto,
   ordenados por prioridad y no por fecha, y lo que no entra se pospone en vez de perderse.
   Lo urgente se salta el tope: si el presupuesto pudiera con lo que caduca en minutos, el
   aviso que más corre sería el primero en caerse.
2. **Utilidad**: la notificación del móvil trae botones de útil / no útil. Es lo **único**
   que hace que el sistema mejore sin que nadie lo toque — sin esa señal, la única forma de
   que una regla mala desaparezca es dejar de mirar los avisos, que se lleva por delante a
   los buenos. El contador de «no útil» es consecutivo y un «útil» lo pone a cero: se busca
   una regla que dejó de valer, no una que tuvo un mal día. Y silenciar es **visible**.
3. **Memoria**: la huella de un aviso es **la situación, no el texto**. «Llevas 3 días sin
   entrenar» salía el jueves, el viernes y el sábado, y solo el primero informaba.

Y la frontera que no se relaja: **lo que has pedido tú no se gobierna**. Un recordatorio que
pusiste a mano no cuenta contra el tope ni se puede silenciar.

Encima de las reglas escritas a mano hay otra capa: **reglas que el asistente propone y tú
apruebas**. Pero el modelo no escribe reglas — **rellena plantillas**. Las condiciones
siguen en Python, revisables en un diff; en la base de datos solo se guarda cuál y con qué
parámetros. Un modelo que pudiera definir la condición sería un modelo decidiendo cuándo
interrumpirte.

---

## 9. El agente PC

El caso de uso original: **entregar un trabajo de la universidad desde la cama**.

```
Dashboard          →  POST /wake-pc          (marca una bandera en memoria)
Home Assistant     →  sondea cada 30 s, ve la bandera, manda el magic packet
PC Windows         →  arranca; el Programador de tareas lanza agent.py
agent.py           →  GET /jobs/pending  (con su propio token, no un JWT)
                   →  claim → start → eventos de progreso → finish
Playwright + Edge  →  abre el Moodle con el perfil real (cookies ya iniciadas),
                      navega y extrae el enunciado
Claude Desktop     →  Ctrl+2 (Cowork), pega el enunciado, Enter
Tú                 →  revisas y envías. Esto no lo hace solo.
```

Con una máquina de estados estricta detrás (`pending → claimed → running → done | failed`,
y `failed → pending` con reintento, máximo 3), donde cada transición es un PATCH condicional
para que sea atómica: el claim lleva `status=eq.pending` como guarda, y si devuelve cero
filas es que otro ganó la carrera.

Tres cosas que aprendió por las malas:

- **Nada de PowerShell en el camino crítico.** La primera invocación de `powershell.exe`
  tras encender el PC tarda **más de 40 segundos** (carga del CLR sobre un disco frío, con
  Defender inspeccionando el binario por primera vez). Y la ruta de arranque del streaming lo
  invocaba media docena de veces: ahí estaban los «45 segundos en negro». Ahora va por
  `sc.exe` y `tasklist.exe`, binarios de Win32 sin runtime detrás: 23 y 108 ms. Se lee el
  **código numérico** del estado, no el texto — el texto viene traducido en un Windows en
  español.
- **Lanzar algo no es comprobar que funciona.** El agente reportaba «streaming listo» sobre
  un PC sin nada abierto. Ahora espera a ver el proceso vivo antes de dar el job por bueno.
- **Lo que arranca solo no puede depender de una credencial que caduca.** Llevaba el JWT del
  dashboard copiado a mano en su `.env`; cuando expiró a los 30 días, todo empezó a fallar en
  silencio. Ahora tiene su propio token de servicio, sin caducidad.

Y una invariante de seguridad concreta: la URL del enunciado sale del **cuerpo HTML de un
evento de Outlook** — dato que escribe quien crea el evento, no necesariamente tú — y acaba
en un navegador con la sesión universitaria ya iniciada. Se valida contra una lista blanca de
hosts en **tres sitios distintos** a propósito, y el enunciado extraído nunca se interpola en
un comando de PowerShell: se escribe a un fichero temporal y se lee de ahí al portapapeles.

---

## 10. Seguridad en un repositorio público

El repo es público, y eso condiciona todo:

- **Sin secretos por defecto.** Si faltan la clave de firma o la contraseña, el backend
  lanza `RuntimeError` al arrancar. Nunca un fallback tipo `"dev-secret"`: en un repo público
  permitiría forjar JWT válidos.
- **Dos niveles de autenticación.** Los humanos usan contraseña → JWT. Las **máquinas** (HA,
  la app del Watch, el Atajo de iOS, el agente PC) usan tokens de servicio dedicados,
  comparados en tiempo constante. **Nada que arranque solo puede autenticarse con un JWT de
  usuario**: caduca a los 30 días y el cliente se queda mudo sin avisar a nadie. Ya pasó dos
  veces.
- **Un JWT firmado no dice para qué es.** Todos se firman con la misma clave, así que validar
  solo la firma hacía que el `state` de OAuth —que viaja en la barra de direcciones— valiera
  como sesión completa del dashboard durante sus 10 minutos. Ahora los tokens de usuario
  rechazan cualquier token con un claim de propósito.
- **Dos limitadores de tasa distintos y no intercambiables.** El del login cuenta solo los
  intentos **fallidos** (protege una credencial), es **global y no por IP** (en una app de un
  solo usuario, limitar por IP solo da una vía de escape gratis: rotarla), vive en la base de
  datos y no en memoria (un contador en memoria se borraba en cada arranque en frío, y
  bastaba con esperar a que la máquina se durmiera), y **dobla la espera** en cada tanda. El
  genérico cuenta **todas** las peticiones porque protege un recurso caro —la transcripción,
  que es una llamada de pago— y ese sí va por IP.
- **La IP solo se lee de fuentes que el cliente no controla.** Nunca de `X-Forwarded-For` por
  defecto: coger su primera entrada dejaba el límite a merced de quien rotara la cabecera.
- **Los errores de la base de datos no se reenvían al cliente.** Se loguea el detalle real en
  el servidor y sale un 502 genérico.
- **Los cuerpos van acotados.** Nada de leer un `UploadFile` sin tope: la máquina de Fly tiene
  1 GB, y con `Transfer-Encoding: chunked` no hay ni cabecera que mirar, así que se cuenta el
  stream.

---

## 11. El sistema se mira a sí mismo

Esta es, probablemente, la parte más peculiar del proyecto. Las tres averías más grandes que
ha tenido comparten forma: **los datos dejaron de llegar y el sistema siguió diciendo que
todo iba bien**. Y nadie vigila una ausencia salvo que se le pida.

Así que se le pidió. Hay cuatro capas:

1. **Registro persistente.** Los errores van a stdout *y* a una tabla, porque el stdout se lo
   lleva la máquina de Fly al escalar a cero — que es exactamente por lo que un fallo estuvo
   días registrándose sin que nadie lo viera. Un middleware registra 5xx, 4xx, excepciones con
   su traza y las peticiones lentas, **sin la query string** (por ahí viajan tokens).
2. **Vigilante de la ingesta.** Si no entra un dato de salud en 24 h, un error; a las 48 h,
   además un aviso. Cubre exactamente el hueco donde vivieron las tres averías.
3. **Vigilante del sistema.** Mira si algo se rompe por cualquier otro sitio. Con tres reglas:
   el listón va **en código** (las reglas deciden si hay avería, el modelo como mucho
   redacta); **reparar en silencio tapa la avería**, así que lo reparado se dice y se dice
   cuántas veces lleva (un fallo que se arregla solo todos los días no está arreglado, está
   escondido); y **solo se repara lo que se puede verificar** — lo que necesita un cambio de
   código se convierte en un issue del repositorio, solo la primera vez de cada avería.
4. **Revisión nocturna.** Si durante el día entraron commits en `main`, de madrugada se lanza
   una sesión de Claude Code que los revisa y abre un issue con lo que encuentre. No sustituye
   al CI: mira lo que ninguna herramienta comprueba — las invariantes del proyecto, las
   moralejas de los bugs históricos, y los datos personales que se cuelan en un repo público.
   A las 08:30 el issue llega al móvil **con dos botones**: «Arreglarlo» —que lanza otra
   sesión, esta de escritura, que arregla, abre un PR y lo mergea si el CI pasa— y «No hacer
   nada».

Y el asistente tiene una herramienta de **diagnóstico**: fallos agrupados por origen, estado
del resumen diario, cuántos días lleva cada métrica sin dato, quién escribió por última vez.
Porque la pregunta más frecuente que se le hace a un asistente que falla de vez en cuando no
es «qué tiempo hace», es **«¿por qué no me llegó el correo?»** — y toda esa información
existía sin forma de preguntarla hablando.

---

## 12. Cuatro historias de guerra

**El Watch dejó de sincronizar y nada dio error.** El upsert en bloque de la ingesta no
nombraba la restricción, así que PostgREST lo resolvía contra la clave primaria (un uuid
nuevo cada vez, que no colisiona nunca) en vez de contra `unique(fecha, métrica)`. En cuanto
el lote traía una métrica que ya existía para ese día: 409, y **no se guardaba nada**, ni
siquiera lo nuevo. Antes no pasaba porque cada métrica se escribía por separado con
POST → si 409, PATCH; el paso al lote se llevó por delante ese respaldo. Dos cosas lo
mantuvieron invisible: el endpoint respondía `200 {"ok": true}` y el único síntoma era un
«sync hace 3 d» en una esquina del dashboard.

**Un mes de métricas nocturnas con n=3, y no había ningún bug.** El correo traía sueño, HRV,
FC en reposo y respiración con tres observaciones, y los pasos con 29. Parece una ingesta
rota. No lo era: los pasos los cuenta el iPhone él solo, y todo lo demás necesita el Watch
puesto — y el reloj llevaba un mes en un cajón. La asimetría «pasos sí, todo lo demás no» es
la huella de eso, no de un endpoint roto. De ahí salió toda la sección de «uso del reloj»:
ahora `n=3/3` (no falta ni un día de los que hubo) se distingue de `n=3/29` (ahí sí falta
ingesta) sin tener que reconocer el patrón a ojo.

**El primer aviso al móvil se perdió entero y el dashboard dijo que había salido.** Desde el
backend solo se ve que Home Assistant vino a recoger el aviso; si su automatización falla, el
aviso muere allí. Ahora el botón de prueba dice «encolado» y nombra a los sospechosos, en vez
de «enviado».

**Un `+` en una query string tumbó dos módulos distintos.** Los timestamps de PostgreSQL
llevan `+00:00`, y un `+` sin codificar en una query string se lee como un espacio. Rompía el
filtro contra PostgREST devolviendo cero filas **sin error visible**: primero dejó al agente
PC sin ver jobs, y meses después hizo desaparecer las sesiones de entrenamiento pendientes.
El mismo fallo, dos veces, en dos sitios que no se parecen en nada.

---

## 13. Por los números

| | |
|---|---|
| Backend | ~10.700 líneas, **1 fichero**, 73 endpoints |
| Frontend | ~5.600 líneas de UI + ~1.560 de lógica pura |
| Agente PC | ~1.000 líneas |
| Herramientas del asistente | **51** |
| Tablas en Supabase | 24 migraciones |
| Tests | ~885 de backend, ~160 de frontend, más E2E con navegador real |
| Documentación | 16 ficheros en `docs/` + el índice |
| Servicios externos | Microsoft Graph, Google Maps, Open-Meteo, OpenAI, Supabase, Home Assistant |

**Cómo se desarrolla.** Cuatro comprobaciones obligatorias antes de cada commit (lint sin un
solo warning, tests de frontend, tests de backend, build de producción), y CI que las repite
en tres jobs paralelos en cada push y cada PR. El E2E arranca un navegador real contra el
build de producción y **el backend de verdad** — no una imitación: importa `main.py` tal cual
y solo sustituye el cliente HTTP saliente. Los tests fallan si el navegador registra
*cualquier* excepción o error de consola.

Y una convención que explica el tono de todo el repositorio: **los comentarios explican por
qué, no qué**. La documentación de este proyecto está escrita casi entera en forma de
«esto está así porque una vez pasó lo siguiente». Un fichero entero (`docs/BUGS_HISTORICOS.md`)
son solo bugs con su moraleja, y la instrucción es leerlo **antes de dar por nuevo un fallo
raro**.

---

## 14. Lo que hace a este proyecto interesante

No es la lista de funcionalidades. Es que casi todas las decisiones de arquitectura salen de
**restricciones físicas reales**, no de preferencias:

- El backend se duerme → el reloj tiene que estar fuera.
- El navegador habla HTTPS y la casa habla HTTP en la LAN → todo pasa por colas y sondeos.
- El PC está apagado → el trabajo se encola y espera a que arranque.
- El repositorio es público → no puede haber ni un secreto con fallback.
- Un modelo pequeño elige mal entre muchas herramientas → dos modelos, y el reparto entre
  ellos es la frontera entre hablar y actuar.
- Un asistente proactivo solo puede fallar volviéndose ruido → los avisos tienen presupuesto,
  votación y memoria.

Y una idea que lo recorre entero, que es la que más me gusta: **el sistema tiene que poder
distinguir «no lo sé» de «no hay nada»**. Un hueco no es un cero. Una media sin su `n` es una
mentira educada. Un día sin datos del reloj no es un día malo. Y «no he podido preguntar»
nunca, jamás, puede parecerse a «no hay nada que hacer».
