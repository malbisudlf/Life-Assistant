# Jarvis que se parchea a sí mismo, probando antes en un espejo

Cuando Jarvis propone un cambio en su propio código, lo prueba primero en una copia aislada.
Solo se despliega si todo pasa **y Mikel lo aprueba**; y aun así se enciende un día a prueba,
y se apaga solo si falla.

Estado (2026-11-15): **hechos la puerta, el espejo, el informe, el rastro y el canario.**
Falta quién lo conduce solo: hoy lo lanza una persona o una sesión por SSH (ver «Lo que falta»).

| Pieza | Dónde | Qué hace |
|---|---|---|
| La puerta | `espejo/espejo.py revisar` | Lee el diff y rechaza lo que toca el núcleo o amplía permisos. No ejecuta nada |
| El espejo | `espejo/espejo.sh <rama>` (en `caja`) | Dos copias limpias, contenedor sin red, pruebas en main y en la rama |
| La comparación | `espejo/comparar.py` | Lo que pasaba en main y ya no pasa es una regresión |
| El informe | `espejo/espejo.py informe` | Tres líneas y «¿Lo despliego?», o tres líneas y un no |
| El rastro | `~/espejo-jarvis/rastro.jsonl` (en `caja`) | Una línea por paso. Solo se añade |
| El canario | `espejo/canario.sh` (en `caja`) | Enciende el interruptor 24 h y lo apaga solo si falla |
| Las reglas | `backend/nucleo_seguridad.json` → `parches` | Rutas y símbolos protegidos, horas y errores del canario |
| Las pruebas | `tests/backend/test_espejo.py` | La puerta, el informe, el rastro y la comparación |

---

## El camino de un parche

1. **Propuesta.** De Mikel («quiero que recuerde las citas del médico») o de un fallo que se
   repite en el registro. Nunca de un texto que ha escrito otro: en el rastro,
   `propuesto_por` solo admite `mikel` y `jarvis:fallo`.
2. **El cambio**, en una rama `arreglo/...` del repositorio, con su prueba y detrás de un
   interruptor apagado: `PARCHE_NN = _flag("PARCHE_NN", "0")`.
3. **`espejo.sh arreglo/lo-que-sea --resumen "…"`** en `caja`:
   - saca el diff contra `main` y lo pasa por **la puerta, con el `espejo.py` y el núcleo de
     `main`**, no con los de la rama: un parche no trae su propio juez;
   - si pasa, exporta dos copias limpias (`git archive`, sin `.git`) y comprueba que el
     contenedor **no llega a internet, ni a la LAN, ni al backend de verdad**. Si algo
     contesta, no se prueba nada;
   - corre `tests/backend` en las dos, con `--network none` y el código de solo lectura;
   - compara y escribe el informe.
4. **El informe**: qué cambia, qué se probó, qué riesgo tiene. Si todo pasó, termina con
   **«¿Lo despliego?»**. Si no, no pregunta.
5. **La aprobación** se apunta con las palabras de Mikel tal cual
   (`espejo.py apuntar --paso aprobado --dato aprobado_por=mikel --dato "literal=…"`).
   Después, lo de siempre: merge con el CI en verde y `desplegar.sh`. **Desplegado no
   cambia nada**: el interruptor sigue apagado.
6. **`canario.sh empezar <id> PARCHE_NN`**: añade `PARCHE_NN=1` al `backend.env` de `caja` y
   recrea el contenedor. Se niega si el rastro no tiene ese parche probado y aprobado.
7. **Cada 10 minutos, `canario.sh vigilar`** (cron): si el backend deja de estar sano, o
   escribe más errores que en las 24 h anteriores (más de `canario_errores_max` por encima
   de lo normal), **quita la línea, recrea y avisa después**. A las 24 h sin fallos, queda
   confirmado y encendido.

---

## La puerta: qué rechaza

Todo se decide sobre el diff. Nada de lo que el parche diga de sí mismo cuenta.

1. **Rutas protegidas**: el núcleo (`backend/nucleo_seguridad.json`, `backend/anticipa.py`),
   el propio espejo (`espejo/`), el CI (`.github/`), las dependencias y el `Dockerfile`, las
   migraciones, el RUNBOOK y la foto del teléfono, `CLAUDE.md`, y los tests que guardan
   estas fronteras. Renombrar un fichero protegido es tocarlo.
2. **Símbolos del núcleo** en cualquier `.py` que no sea un test: la frontera de lo ajeno
   (`_ajeno_bloquea` y sus listas), las confirmaciones (`_jarvis_confirma`,
   `_casa_pide_confirmar`, `PREGUNTAS_ACCIONES`), el no molestar, la autenticación y la
   anticipación. Se rechaza **quitar** una línea que los nombre, **redefinirlos**,
   **escribir** en ellos o nombrarlos **entre comillas** (que es como se parchea por
   detrás). **Usarlos sí se puede**: un endpoint nuevo tiene que poder pedir
   `Depends(verify_token)`.
3. **Los permisos solo bajan.** Una entrada nueva en `_JARVIS_HERRAMIENTAS` es una capacidad
   nueva: se rechaza salvo que se pase `--capacidad <nombre>`, que es la forma de decir
   que Mikel la aprobó **por su nombre**. Y quitar un `"confirmar": True` se rechaza siempre.
4. **Lo nuevo nace apagado.** Un `_flag("X")` o `_flag("X", "1")` nuevo se rechaza.
5. **Sin prueba nueva no se presenta.**

Sin interruptor `PARCHE_NN` no se rechaza, pero se avisa y el riesgo sube a medio: el
canario no podría apagarlo solo.

**Lo que la puerta no ve**, y por eso hay espejo y canario detrás: un cambio que no nombra
ningún símbolo protegido y aun así cambia lo que hace una frontera (tocar una función que
ellas llaman, por ejemplo). Los tests de esas fronteras (`test_ajeno.py`,
`test_no_molestar.py`, `test_anticipa.py`) están protegidos justo para eso: si el parche
rompe una, sale como regresión, y no puede cambiar el test para taparlo.

---

## El espejo: qué garantiza y qué no

- **Sin red**: `--network none`. Se comprueba en cada pasada, no se supone.
- **Sin secretos**: las copias salen de `git archive`; `backend.env` no está en el
  repositorio ni se monta. Las claves son las de mentira de `tests/backend/conftest.py`.
- **Sin base de datos real**: Supabase, Graph, Home Assistant, Maps y OpenAI son los
  simulados de la suite. La real no está ni al alcance.
- **Las mismas dependencias que producción**: la imagen se construye sobre la que corre
  (`stack-backend`), añadiendo solo `pytest`. La rama no puede traer otras: es ruta protegida.
- **No toca lo que corre**: ni el repositorio desplegado (solo `git fetch`), ni el contenedor.

**Las pruebas de conversación** son los tests que guionizan turnos enteros de Jarvis (el
modelo simulado, sus herramientas, las confirmaciones y lo ajeno): unos novecientos. Se
cuentan aparte, y una regresión ahí impide la pregunta. **No son el simulador de llamadas**
(`docs/SIMULADOR.md`), que habla con un Claude de verdad y gasta suscripción: ese se pasa a
mano cuando el parche toca cómo habla el teléfono, que además es ruta protegida.

El frontend no se prueba en el espejo: lo prueba el CI, que el merge ya exige en verde.

---

## Las reglas que no se negocian

1. **El núcleo es de solo lectura para Jarvis.** Lo que lo toca se rechaza sin probarlo.
2. **Los permisos solo bajan.** Quitar una capacidad pasa; añadirla pide su nombre.
3. **Lo ajeno no encarga parches.** Un mensaje que diga «arregla tu código» es un dato.
4. **Todo deja rastro**: quién lo propuso, la rama y el commit, qué pruebas pasó (los
   números), quién lo aprobó y con qué palabras, y cómo acabó el canario.
5. **Ninguna aprobación sale de un texto leído**: `aprobado_por` es `mikel` o no se apunta.
6. **La vuelta atrás no pregunta.** Avisa después.

---

## Instalarlo en `caja`

Los scripts llegan con el despliegue (`~/stack/Life-Assistant/espejo/`). Hace falta, una vez:

```bash
mkdir -p ~/espejo-jarvis
( crontab -l; echo '*/10 * * * * $HOME/stack/Life-Assistant/espejo/canario.sh vigilar >> $HOME/espejo-jarvis/canario.log 2>&1  # espejo' ) | crontab -
```

Sin canario en marcha, la pasada del cron no hace nada.

## Lo que falta

- **Quién lo conduce.** Las sesiones que hoy arreglan averías (`docs/AVERIAS.md`) abren su
  PR y piden permiso por el móvil sin pasar por el espejo. Engancharlas es el siguiente
  paso: que la rutina llame a `espejo.sh` antes de pedir permiso y mande el informe como
  texto del aviso.
- **La puerta en el CI**, para que un PR de `arreglo/` que la salte no pueda mergearse. No
  está puesta porque `.github/` es ruta protegida y lo añade Mikel.
- **Proponer por fallo repetido.** `jarvis:fallo` existe en el rastro, pero nadie cuenta
  aún los errores de `app_logs` para proponer. Va después de unas semanas de parches a mano.
- **La hora del criterio de éxito** (menos de una hora de propuesta a canario) no se ha
  medido: no ha pasado ningún parche de verdad por aquí.
