# Revisión nocturna del código

Si durante el día han entrado commits en `main`, de madrugada se lanza una sesión de
Claude Code que los revisa y abre un issue con lo que haya encontrado. Por la mañana o
hay issue o no lo hay; una noche sin hallazgos no deja ruido.

**No sustituye al CI.** `ci.yml` ya ejecuta lint, tests, build y E2E en cada push. Lo
que esta revisión mira es lo que ninguna herramienta comprueba: las invariantes de
`CLAUDE.md`, las moralejas de `docs/BUGS_HISTORICOS.md` y los datos personales que se
cuelan en un repositorio público.

## Las tres piezas

| Pieza | Dónde vive | Qué hace |
|---|---|---|
| La routine | En la cuenta de claude.ai (`claude.ai/code/routines`), **no en el repositorio** | La sesión que revisa: prompt guardado, modelo, repositorio y el endpoint de disparo |
| `.claude/skills/revision-nocturna/SKILL.md` | Versionado aquí | El checklist de verdad: qué buscar, cómo verificarlo y cómo escribir el issue |
| `.github/workflows/revision-nocturna.yml` | Versionado aquí | El disparador: mira si hay commits nuevos y, solo entonces, llama a la routine |

El prompt guardado en la routine es corto a propósito: **la revisión evoluciona en la
skill**, que está en el repositorio y se cambia en un commit como todo lo demás. Las
routines usan las skills del repositorio que clonan.

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
"Rango a revisar: BASE..CABEZA". Úsalo. Si no hay bloque, revisa los commits de las
últimas 24 horas en main.

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

### 3. Configurar el repositorio

En *Settings → Secrets and variables → Actions*:

- **Secret** `ROUTINE_TOKEN`: el token `sk-ant-oat01-...` del paso anterior.
- **Variable** `ROUTINE_FIRE_URL`: la URL del `/fire`. Va como variable y no como
  secret porque no es secreta —lo que protege el endpoint es el token—, igual que
  `BACKEND_URL`.

Si falta cualquiera de las dos, el workflow falla con un mensaje claro en vez de
quedarse callado.

### 4. Llevarlo a `main`

Los workflows programados **solo corren desde la rama por defecto**. Mientras esto viva
en una rama de trabajo no dispara nada, ni siquiera con `workflow_dispatch`.

## Cómo probarlo

- **El disparador entero**: *Actions → Revisión nocturna del código → Run workflow*.
  Si no hay commits nuevos desde la última revisión, dirá que no hay nada que revisar
  y terminará sin gastar una ejecución de la routine. Para forzarlo, borra la etiqueta
  (abajo) o muévela hacia atrás.
- **Solo la revisión**, sin tocar Actions: **Run now** en la página de la routine. El
  cuadro admite texto, que llega igual que el `text` del disparo — pégale un
  `Rango a revisar: BASE..CABEZA` y revisará ese rango.

## La etiqueta `ultima-revision-nocturna`

Es una etiqueta ligera que marca hasta dónde se revisó la última vez. El workflow la lee
para calcular el rango y la mueve **solo si el disparo salió bien**.

Existe para que una noche perdida no se trague esos commits: si Actions estaba caído o
el disparo falló, la noche siguiente arrastra el rango completo desde donde se quedó.

```bash
git fetch --tags
git rev-parse ultima-revision-nocturna        # hasta dónde se revisó
git push origin :refs/tags/ultima-revision-nocturna   # borrarla: la próxima revisa las últimas 24 h
git tag -f ultima-revision-nocturna <sha> && git push -f origin refs/tags/ultima-revision-nocturna
```

## Cómo apagarlo

- **Una temporada**: desactiva el workflow desde *Actions* (menú `...` → *Disable
  workflow*). La routine se queda sin disparo y no gasta nada.
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
