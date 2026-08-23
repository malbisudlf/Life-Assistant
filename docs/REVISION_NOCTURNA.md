# Revisión nocturna del código

Si durante el día han entrado commits en `main`, de madrugada se lanza una sesión de
Claude Code que los revisa y abre un issue con lo que haya encontrado. Por la mañana o
hay issue o no lo hay; una noche sin hallazgos no deja ruido.

Y si hay issue, **a las 08:30 llega al móvil una notificación con dos botones**:
«Arreglarlo» —que lanza otra sesión en la nube, esta sí de escritura, que arregla los
hallazgos, abre un PR y lo mergea si el CI pasa— y «No hacer nada», que no hace nada. La
segunda mitad está en "El informe accionable", abajo.

**No sustituye al CI.** `ci.yml` ya ejecuta lint, tests, build y E2E en cada push. Lo
que esta revisión mira es lo que ninguna herramienta comprueba: las invariantes de
`CLAUDE.md`, las moralejas de `docs/BUGS_HISTORICOS.md` y los datos personales que se
cuelan en un repositorio público.

## Las piezas

| Pieza | Dónde vive | Qué hace |
|---|---|---|
| La routine que revisa | En la cuenta de claude.ai (`claude.ai/code/routines`), **no en el repositorio** | La sesión que revisa: prompt guardado, modelo, repositorio y sus dos disparos (el endpoint de API y el barrido semanal) |
| `.claude/skills/revision-nocturna/SKILL.md` | Versionado aquí | El checklist de verdad: qué buscar, cómo verificarlo y cómo escribir el issue |
| `.github/workflows/revision-nocturna.yml` | Versionado aquí | El disparador: mira si hay commits nuevos y, solo entonces, llama a la routine |
| `.github/workflows/revision-aviso.yml` | Versionado aquí | Ve el issue nuevo y se lo cuenta al backend, que es quien sabe llegar a tu móvil |
| La routine que arregla | En claude.ai, **otra distinta** | La sesión que la pulsa el botón «Arreglarlo»: arregla, abre PR y mergea |
| `.claude/skills/arreglar-revision/SKILL.md` | Versionado aquí | Qué arregla, qué no, y cuándo NO se mergea |

El prompt guardado en la routine es corto a propósito: **la revisión evoluciona en la
skill**, que está en el repositorio y se cambia en un commit como todo lo demás. Las
routines usan las skills del repositorio que clonan.

## Los dos relojes

El disparo primario es el workflow, no un schedule de la routine, por una razón: **es la
única pieza que sabe gratis si hubo commits**. Las routines tienen tope diario de
ejecuciones y una noche sin tocar el código no debe gastar una; mirar el `git log` en
Actions no cuesta nada. El backend no puede hacer este papel: escala a cero y no tiene
reloj propio —lo despiertan el iPhone o Home Assistant—, y además no sabe nada de git.

El cron de Actions no es de fiar, y cada uno de sus fallos se tapa por separado:

| Fallo | Quién lo cubre |
|---|---|
| Llega tarde | Nadie, y da igual: son las tres de la mañana |
| No llega (Actions descarta la ejecución) | La etiqueta: no se movió, así que la noche siguiente arrastra el rango |
| Llega, pero la sesión se cae a mitad de revisión | El barrido semanal de la routine |

Ese tercer caso es el que obliga a tener dos relojes: la etiqueta se mueve cuando el
disparo sale bien, no cuando la revisión termina, así que unos commits pueden quedar
marcados como revisados sin haberlo sido. El barrido semanal vuelve a mirar los últimos
siete días con orden expresa de no repetir hallazgos ya reportados, así que la semana
normal termina sin abrir nada.

Es la misma forma que el resumen diario: señal primaria, reloj de respaldo y una puerta
que evita el duplicado.

## Cómo se montó (y cómo rehacerlo)

### 1. Crear la routine

En [claude.ai/code/routines](https://claude.ai/code/routines) → **New routine**:

- **Nombre**: `Revisión nocturna — Life-Assistant`
- **Modelo**: **Sonnet** (el selector está en el propio cuadro de instrucciones; se usa
  en todas las ejecuciones).
- **Repositorio**: este.
- **Entorno**: el **Default** basta. Su acceso de red *Trusted* deja pasar los
  registros de paquetes, que es lo único que hace falta si la revisión quiere ejecutar
  los tests para confirmar una sospecha.
- **Conectores**: **quítalos todos**. Aquí no hace falta ninguno, y durante una
  ejecución Claude puede usar cualquier herramienta de un conector incluido —incluidas
  las de escritura— sin pedir permiso.
- **Trigger**: **API**. La URL y el token se generan después de guardar, porque
  dependen del identificador de la routine.
- **Instrucciones**:

```text
Revisa los cambios que han entrado hoy en main de este repositorio y abre un issue con
los hallazgos.

El rango exacto viene en el bloque <routine-fire-payload> de esta sesión, en la línea
"Rango a revisar: BASE..CABEZA". Úsalo. Si no hay bloque, te ha disparado el barrido
semanal de respaldo: revisa los últimos siete días sin repetir hallazgos que ya estén
en issues de revisiones anteriores.

Sigue la skill `revision-nocturna` del repositorio
(.claude/skills/revision-nocturna/SKILL.md): ahí están el checklist, el formato del
issue y las reglas. Si no hay hallazgos, no abras ningún issue.

Es una revisión de solo lectura: no modifiques ficheros, no crees ramas ni pull
requests, y no despliegues nada.
```

La segunda frase no es de adorno. El `text` del disparo **no llega como mensaje**: llega
envuelto en un bloque `<routine-fire-payload>` marcado como dato no fiable, y la sesión
lo trata como contexto inerte salvo que el prompt guardado lo cite explícitamente. Sin
esa frase, la routine ignora el rango.

### 2. Generar el token del disparo

En la routine → icono del lápiz (**Edit routine**) → **Select a trigger** → **Add
another trigger** → **API**. El modal enseña la URL
(`https://api.anthropic.com/v1/claude_code/routines/trig_.../fire`) y un botón
**Generate token**.

**El token se enseña una sola vez.** Cópialo antes de cerrar el modal; si se pierde, se
regenera desde el mismo sitio (y hay que actualizar el secret). Cada routine tiene su
token y solo sirve para dispararla a ella.

### 3. Añadir el reloj de respaldo

En la misma routine, **Add another trigger** → **Schedule**, semanal. La hora da igual
mientras sea de madrugada; el domingo va bien.

Este disparo llega **sin payload**, y la skill usa justo eso para saber que es un
barrido: en vez de un rango concreto revisa los últimos siete días y no repite lo que ya
esté reportado en issues anteriores.

### 4. Configurar el repositorio

En *Settings → Secrets and variables → Actions*:

- **Secret** `ROUTINE_TOKEN`: el token `sk-ant-oat01-...` del paso anterior.
- **Variable** `ROUTINE_FIRE_URL`: la URL del `/fire`. Va como variable y no como
  secret porque no es secreta —lo que protege el endpoint es el token—, igual que
  `BACKEND_URL`.

Si falta cualquiera de las dos, el workflow falla con un mensaje claro en vez de
quedarse callado.

### 5. Llevarlo a `main`

Los workflows programados **solo corren desde la rama por defecto**. Mientras esto viva
en una rama de trabajo no dispara nada, ni siquiera con `workflow_dispatch`.

## El informe accionable

Un issue que nadie abre es una revisión que no ha servido de nada. Esta mitad convierte
el informe en una pregunta con dos botones en el móvil, y la respuesta en trabajo hecho.

```
03:37  revision-nocturna.yml → routine que revisa → issue en GitHub
03:40  revision-aviso.yml (evento issues) → POST /revision/hallazgos
       backend: apunta la decisión en `revision_hallazgos` + encola el aviso
08:30  el despachador lo entrega: notificación con «Arreglarlo» / «No hacer nada»
   ↓
   «Arreglarlo» → HA → POST /revision/{id}/accion → routine que arregla → PR → merge
   «No hacer nada» → la fila queda `descartado` y no pasa nada más
```

Cinco decisiones, y ninguna es nueva en este proyecto:

- **El aviso lo manda Actions, no la routine que revisa.** La routine no tiene dónde
  guardar un secreto: lo que se le pase acaba en la transcripción de la sesión. El evento
  `issues` de Actions sí, y de paso cubre el issue que abras a mano con ese título.
- **El aviso espera a que estés despierto.** Se apunta a las 03:40 con `cuando` a las
  08:30 (`AVISOS_HORA_DIFERIDOS`): es un aviso que no gana nada por llegar de madrugada y
  lo pierde todo si te despierta. Lo entrega el despachador de siempre, así que hereda el
  canal, el rescate por correo y el registro sin camino nuevo.
- **La decisión vive en Supabase.** Entre que sale el aviso y se pulsa el botón pasan
  horas, y en ese hueco la máquina de Fly se duerme: un mapa en memoria de id → issue no
  llegaría vivo al toque. Es la misma razón por la que los recordatorios no viven en
  memoria.
- **El id del aviso ES el de la fila**, derivado del número del issue (`uuid5`). El botón
  no necesita llevar nada más que su propio id, y un reintento del workflow choca contra
  la clave primaria en vez de mandar un segundo aviso del mismo informe.
- **La transición es un PATCH condicional** (`estado=eq.pendiente`), no un GET y luego un
  UPDATE: dos toques seguidos en la notificación no pueden lanzar dos agentes. Y si el
  disparo falla, la decisión **se libera** y se avisa — una decisión consumida sin efecto
  deja el botón muerto y el issue sin arreglar, que es el peor de los dos errores.

Y una que no es técnica: **la routine que arregla es OTRA**. La de la noche es de solo
lectura a propósito; darle permiso de escritura para ahorrarse una routine sería quitarle
esa garantía justo en la sesión que corre sin nadie delante.

### Montarlo

1. **La migración**: aplica `supabase/migrations/20260820_revision_hallazgos.sql` en el
   editor SQL de Supabase.

2. **La routine que arregla**, en [claude.ai/code/routines](https://claude.ai/code/routines)
   → **New routine**:

   - **Nombre**: `Arreglar revisión — Life-Assistant`
   - **Modelo**: el que quieras; aquí se escribe código, así que compensa el bueno.
   - **Repositorio**: este. **Con permiso de escritura**, a diferencia de la que revisa.
   - **Conectores**: los mínimos para GitHub (PR y merge). Nada más: durante una
     ejecución Claude puede usar cualquier herramienta de un conector incluido, sin pedir
     permiso.
   - **Trigger**: **API**, y **sin schedule**. Esta no tiene reloj: la dispara el botón.
   - **Instrucciones**:

   ```text
   Arregla los hallazgos de la revisión nocturna de este repositorio.

   El issue concreto viene en el bloque <routine-fire-payload> de esta sesión, en la
   línea "Arregla los hallazgos de la revisión nocturna del issue #N". Úsalo. Si no hay
   bloque, coge el issue abierto más reciente cuyo título empiece por "Revisión
   nocturna".

   Sigue la skill `arreglar-revision` del repositorio
   (.claude/skills/arreglar-revision/SKILL.md): ahí están qué se arregla, qué no, la
   verificación obligatoria y cuándo NO se mergea.

   No despliegues el backend nunca, ni aunque el hallazgo parezca urgente.
   ```

   La segunda frase no es de adorno, por lo mismo que en la routine que revisa: el `text`
   del disparo llega envuelto en `<routine-fire-payload>` como dato no fiable, y la sesión
   lo ignora salvo que el prompt guardado lo cite.

3. **El token del disparo**: igual que el de la otra routine (lápiz → *Add another
   trigger* → **API** → *Generate token*). **Se enseña una sola vez.**

4. **El backend** (secrets de Fly, `fly secrets set`):

   - `ARREGLO_FIRE_URL` y `ARREGLO_FIRE_TOKEN`: los del paso anterior.
   - `REVISION_TOKEN`: invéntate uno (`openssl rand -hex 32`). Es el que usará Actions
     para avisar al backend.

5. **El repositorio** (*Settings → Secrets and variables → Actions*): **secret**
   `REVISION_TOKEN`, el mismo valor. La variable `BACKEND_URL` ya está puesta si el
   resumen diario funciona.

6. **Home Assistant**: los botones los pinta HA, así que hay que actualizar la
   automatización de avisos para que use `repeat.item.acciones` en vez de los dos botones
   fijos de útil / no útil, y añadir la que recoge la respuesta. Está en
   `docs/HOME_ASSISTANT_JARVIS.md`, punto 4. **Sin ese cambio el aviso llega igual, pero
   con los botones equivocados.**

Sin nada de esto configurado, el issue de la noche se sigue abriendo exactamente como
antes: lo que no hay es aviso ni botón.

### Si el aviso llega por correo

El correo no tiene botones. Para eso está la herramienta `arreglar_revision` de Jarvis:
«arregla la revisión» lanza lo mismo que el botón, pasando por el botón de confirmar del
dashboard —toca el repositorio y lo mergea, así que no lo decide el modelo solo—. Si no
hay rutina de arreglo configurada, la herramienta ni se anuncia.

## Cómo probarlo

- **El aviso con botones**, sin esperar a la madrugada: abre a mano un issue titulado
  `Revisión nocturna — prueba`. El workflow `revision-aviso.yml` lo verá y el aviso
  quedará apuntado para las 08:30 (o para ya, si es de día). Para no esperar, mira la
  fila en `revision_hallazgos` y llama a `POST /revision/{id}/accion` con
  `{"accion": "nada"}`.
- **El disparador entero**: *Actions → Revisión nocturna del código → Run workflow*.
  Si no hay commits nuevos desde la última revisión, dirá que no hay nada que revisar
  y terminará sin gastar una ejecución de la routine. Para forzarlo, borra la etiqueta
  (abajo) o muévela hacia atrás.
- **Solo la revisión**, sin tocar Actions: **Run now** en la página de la routine. El
  cuadro admite texto, que llega igual que el `text` del disparo — pégale un
  `Rango a revisar: BASE..CABEZA` y revisará ese rango.
- **El barrido semanal**: **Run now** dejando el cuadro de texto vacío. Sin payload, la
  skill se va al camino de los últimos siete días.

## Si pulsas «Arreglarlo» y no pasa nada

La cadena tiene cuatro eslabones y se recorren en este orden: el primero que falle
explica el silencio y los de abajo ya dan igual.

1. **¿Se apuntó el aviso?** *Actions → Avisar de la revisión nocturna → la ejecución de
   ese issue*. El log acaba con la respuesta del backend tal cual. `"avisado":true` es lo
   que quieres ver. `"avisado":false` con `"ya estaba apuntado"` **no es un fallo**: son
   los dos eventos del mismo issue (`opened` y `labeled`), y el segundo choca contra la
   clave primaria a propósito — mira la otra ejecución, la de al lado.
2. **¿Llegó con los botones buenos?** Si el aviso trae «útil / no útil» en vez de
   «Arreglarlo / No hacer nada», el YAML de Home Assistant se quedó en la versión
   anterior a `repeat.item.acciones` (`docs/HOME_ASSISTANT_JARVIS.md`, punto 4). Pulsar
   entonces manda la valoración de una regla, no una decisión, y el backend no tiene
   forma de detectarlo: desde aquí solo se ve que HA recogió la cola.
3. **¿Llegó la pulsación al backend?** Tienen que existir el `rest_command`
   `la_revision_accion` y la automatización que lo llama. Si faltan, pulsar no hace
   nada en absoluto: no hay petición, así que tampoco hay error que contar.
4. **¿Existe todavía la rutina que arregla?** En
   [claude.ai/code/routines](https://claude.ai/code/routines). Es el eslabón que más
   silenciosamente se rompe — ver "Trampas conocidas".

**El backend siempre contesta**, y por el mismo canal por el que llegó la pregunta: «Voy
a por los hallazgos» si el disparo salió, o «No he podido lanzar el arreglo» con el
motivo si no. Un silencio absoluto significa que la petición nunca llegó, es decir, los
eslabones 2 o 3 — no el backend.

## La etiqueta `ultima-revision-nocturna`

Es una etiqueta ligera que marca hasta dónde se revisó la última vez. El workflow la lee
para calcular el rango y la mueve **solo si el disparo salió bien**.

Existe para que una noche perdida no se trague esos commits: si Actions estaba caído o
el disparo falló, la noche siguiente arrastra el rango completo desde donde se quedó.

Marca lo **disparado**, no lo **revisado**: si la sesión se cae a mitad, esos commits
quedan marcados sin haberse mirado. De ese hueco se ocupa el barrido semanal.

```bash
git fetch --tags
git rev-parse ultima-revision-nocturna        # hasta dónde se revisó
git push origin :refs/tags/ultima-revision-nocturna   # borrarla: la próxima revisa las últimas 24 h
git tag -f ultima-revision-nocturna <sha> && git push -f origin refs/tags/ultima-revision-nocturna
```

## Cómo apagarlo

- **Una temporada**: desactiva el workflow desde *Actions* (menú `...` → *Disable
  workflow*) y pausa el schedule semanal desde la sección **Repeats** de la routine. Si
  solo apagas el workflow, el barrido semanal sigue corriendo.
- **Del todo**: borra la routine en claude.ai y este workflow. La skill puede quedarse:
  sirve a mano para revisar un rango cuando quieras.

## Trampas conocidas

- **El verde de una ejecución no significa que la revisión saliera bien**: solo que la
  sesión arrancó y terminó sin error de infraestructura. Si un issue no aparece y
  esperabas uno, abre la ejecución en `claude.ai/code/routines` y lee la transcripción.
- **Las routines tienen un tope diario de ejecuciones** por cuenta, aparte del límite
  normal de la suscripción. Por eso el disparo es condicional: una noche sin commits no
  gasta ninguna. El consumo se ve en la propia página de routines.
- **Gasta suscripción, no API de pago.** Las routines consumen igual que una sesión
  interactiva. Lo único que se llama de la API de Anthropic es el `/fire`, que solo
  dispara.
- **La routine actúa con tu identidad de GitHub**: el issue aparece abierto por Mikel,
  no por un bot.
- **El endpoint `/fire` va con cabecera beta** (`experimental-cc-routine-2026-04-01`) y
  está en vista previa: la forma de la petición puede cambiar. Si un día empieza a
  responder 4xx, mira los docs de routines antes de dar por muerto el montaje.
- **GitHub desactiva los workflows programados** en repositorios sin actividad durante
  60 días. Aquí no debería pasar, pero si el disparo deja de ocurrir sin más, es lo
  primero que hay que mirar.
- **El título del issue es un contrato**, no un formato bonito: `revision-aviso.yml`
  filtra por `Revisión nocturna` al principio del título (la etiqueta solo la pone la
  skill si ya existe en el repositorio, así que no se puede depender de ella). Si cambias
  el formato en `.claude/skills/revision-nocturna/SKILL.md`, cambia también el `if` del
  workflow o el aviso deja de salir en silencio.
- **La rutina que arregla puede desaparecer, y no te enteras hasta pulsar el botón.**
  Pasó en agosto de 2026: la rutina se borró de `claude.ai/code/routines` y
  `ARREGLO_FIRE_URL` se quedó apuntando a un trigger que ya no existía. Todo lo demás
  siguió funcionando —el issue se abría, el aviso salía a las 08:30 con sus dos
  botones—, así que desde fuera el montaje parecía sano y el fallo solo se veía al
  pulsar. El backend hace lo correcto (libera la decisión y te cuenta el fallo), pero
  para entonces la mañana ya se ha gastado. Borrar una rutina es un clic y no avisa a
  nadie: si el arreglo deja de lanzarse, mira ahí ANTES que el código.
- **«Arreglarlo» mergea, y mergear despliega el frontend** (Vercel va detrás de `main`).
  El backend no: su deploy sigue siendo manual y la skill del arreglo tiene prohibido
  tocarlo. Si un hallazgo era del backend, después del merge hay que hacer `fly deploy` a
  mano.
- **El agente que arregla no mergea en rojo.** Si el CI falla tras dos intentos deja el
  PR abierto con una explicación, que es un resultado — el silencio no lo sería.
