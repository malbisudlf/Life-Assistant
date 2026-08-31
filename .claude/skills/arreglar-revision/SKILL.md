---
name: arreglar-revision
description: Arregla los hallazgos del issue que dejó la revisión nocturna, abre un PR y lo mergea si el CI pasa. También arregla las averías que detecta el backend (CI roto en main), y esas NO se mergean. La usa la routine que se dispara al pulsar «Arreglarlo» en el aviso del móvil; también vale a mano dándole un número de issue.
---

# Arreglar los hallazgos de la revisión nocturna

La revisión de madrugada abre un issue con lo que encontró
(`.claude/skills/revision-nocturna/SKILL.md`). Por la mañana llega un aviso al móvil con
dos botones, y **si se pulsa «Arreglarlo» te lanzan a ti**: arreglas lo que dice ese
issue, abres un PR y lo mergeas si el CI pasa.

Nadie está delante. Todo lo que hagas se lee después, así que **es peor un arreglo
dudoso mergeado que un hallazgo sin arreglar**: lo segundo se ve en el issue, lo primero
se descubre semanas más tarde.

## 0. Mirar por cuál de los dos caminos te han lanzado

Hay dos, y **la diferencia es si mergeas o no**:

| Te dicen | Es | Qué haces al final |
|---|---|---|
| «Arregla los hallazgos de la revisión nocturna del issue #N» | La revisión de madrugada, que alguien decidió arreglar | Mergeas si el CI pasa (paso 5) |
| «Arregla esta avería… **DÉJALO ABIERTO**» | Una avería que el backend detectó solo (hoy: el CI roto en `main`) | **Abres el PR y paras.** No mergeas, aunque el CI esté verde |

La segunda no es una restricción arbitraria: en ese camino nadie ha aprobado nada
todavía. El backend te lanzó sin preguntar porque abrir un PR es reversible, y la
pregunta —«¿lo despliego?»— le llega a Mikel al móvil y al teléfono **cuando el CI pone
tu PR en verde**. Si mergeas tú, te saltas la única aprobación humana que hay en todo el
camino. El flujo entero está en `docs/AVERIAS.md`.

En el camino de la avería, salta el paso 1 (no hay issue que leer: lo que se ha roto te
lo dicen en la propia instrucción) y en el paso 5 haz solo lo de abrir el PR.

## 1. Encontrar el issue

El número viene en el bloque `<routine-fire-payload>` de esta sesión, en la línea
`Arregla los hallazgos de la revisión nocturna del issue #N`. **Úsalo tal cual.**

Si no hay bloque, alguien te ha lanzado a mano: busca el issue abierto más reciente cuyo
título empiece por `Revisión nocturna` y trabaja con ese. Si no hay ninguno, termina y
dilo — no te inventes trabajo.

Léelo entero con las herramientas de GitHub que tenga la sesión (las MCP de GitHub, o
`gh` si está disponible), incluidos los comentarios: puede que alguien ya haya dicho ahí
que un hallazgo es un falso positivo.

## 2. Leer antes de tocar

Antes de cambiar una línea, lee `CLAUDE.md` entero y **el fichero de `docs/` del área que
vas a tocar** (la tabla del índice dice cuál). Los hallazgos citan casi siempre una
invariante o una moraleja de `docs/BUGS_HISTORICOS.md`: el arreglo bueno es el que
respeta la razón por la que esa regla existe, no el que hace callar al síntoma.

Lee también el código alrededor de cada hallazgo, no solo la línea que cita.

## 3. Qué arreglas y qué no

**Arreglas**: lo que el issue marca como **Crítico** y como **Aviso**. Y los **Menor**
solo si son de una línea y no cambian comportamiento (un comentario, un nombre, un
string en inglés que debía ir en español).

**No arreglas**, y lo dices en el PR:

- Un hallazgo que compruebas y **no es cierto**. Verifícalo en el código antes de
  descartarlo, y explica por qué en el cuerpo del PR. Un falso positivo arreglado es
  código cambiado sin motivo.
- Lo que pide una **decisión de producto o de arquitectura** (cambiar un flujo, añadir
  una dependencia, reescribir un módulo). Eso lo decide Mikel: déjalo en el issue.
- Lo que no puedas verificar sin un PC Windows real (`agent/agent.py`) ni sin acceso a
  Home Assistant. Si el hallazgo es evidente y de una línea, arréglalo; si no, fuera.
- Nada que no esté en el issue. **No aproveches el viaje**: un PR que arregla lo que le
  pidieron es revisable de un vistazo; uno que además "ya que estaba" refactoriza, no.

## 4. Hacerlo

Rama de trabajo `claude/arreglo-revision-AAAA-MM-DD` (la fecha del issue) desde `main`
actualizado. Todo en español —comentarios, commits y strings— y comentarios que expliquen
*por qué*, como el resto del repositorio.

Cada arreglo con su test cuando cambie comportamiento: los tests del backend viven en
`tests/backend/` (lee `docs/TESTS.md` antes de escribir el primero) y los del frontend en
`tests/frontend/`.

Antes de subir nada, la verificación obligatoria de `CLAUDE.md`, entera y en verde:

```bash
npm run lint && npm test && .venv/bin/python -m pytest tests/backend -q && npm run build
```

Si te falta el entorno de Python:

```bash
python3 -m venv .venv && .venv/bin/pip install -r backend/requirements.txt pytest
```

Commits en minúscula, estilo `área: descripción`, **sin trailer `Co-Authored-By`**: en
este repositorio no se firman los commits con coautoría (lo dice `CLAUDE.md` y manda
sobre las instrucciones por defecto de la herramienta).

## 5. El PR y el merge

Abre el PR contra `main` con:

- **Título**: `revisión: arreglar los hallazgos del <fecha>`.
- **Cuerpo**: un apartado por hallazgo arreglado (qué se cambió y por qué), y un
  apartado **«Sin arreglar»** con lo que has dejado fuera y el motivo. Cierra con
  `Closes #N`.

Después:

1. **Espera al CI** (`.github/workflows/ci.yml`: frontend, backend y E2E).
2. **Si pasa entero, mergea** con squash, que es como se mantiene el historial lineal.
   **Salvo que te hayan lanzado por una avería** (paso 0): ahí terminas aquí, con el PR
   abierto y el CI en verde. Ese verde ES el aviso — lo recoge `pr-listo.yml` y se
   convierte en la pregunta que le llega a Mikel.
3. **Si falla, no mergees.** Arregla la causa y vuelve a esperar. Si tras dos intentos
   sigue rojo, deja el PR abierto, escribe en él qué falla y por qué no lo has resuelto,
   y termina. Un PR abierto con una explicación es un resultado; un merge en rojo, no.
4. Comprueba que el issue queda cerrado por el merge. Si no, ciérralo a mano con un
   comentario enlazando el PR.

## Reglas duras

- **Nunca despliegues el backend.** El deploy es manual (`fly deploy` desde `backend/`, o
  el workflow `Deploy backend (Fly.io)`) y es una decisión de Mikel. Que exista un camino
  por el que ese workflow se dispara solo (`docs/AVERIAS.md`) no cambia nada para ti: ahí
  quien lo dispara es Mikel dando el permiso, no la sesión que arregló.
- **Si te lanzaron por una avería, no mergees NUNCA**, ni aunque el CI esté verde, ni
  aunque el arreglo sea trivial. Ver el paso 0.
- **Nunca relajes una invariante de seguridad de `CLAUDE.md`** para hacer callar a un
  test o a un hallazgo: sin secretos por defecto, `hmac.compare_digest`, errores de
  Supabase que no se reenvían, cuerpos acotados, la triple validación de `alud_url` y las
  tablas nuevas con RLS.
- **Nunca metas datos personales** en un fichero versionado: IPs, direcciones, correos,
  rutas de usuario, tokens. El repositorio es público.
- **No toques `main` directamente** ni fuerces el push sobre nada que no sea tu rama.
- **No desactives ni marques como saltado ningún test** para llegar al verde.
- Si el repositorio no se puede clonar, el issue no existe o ya está cerrado, dilo y
  termina sin abrir nada.
