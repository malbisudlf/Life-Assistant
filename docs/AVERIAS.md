# Averías: se detectan solas, se arreglan solas y te llaman por teléfono

La revisión nocturna (`docs/REVISION_NOCTURNA.md`) pregunta **antes** de arreglar: abre
un issue de madrugada y por la mañana decides si quieres que lo arregle. Esto es el
camino inverso, y es el que de verdad quita trabajo:

```
   El CI se pone rojo en `main`
        ↓  ci-averiado.yml  →  POST /averia
   El backend lanza una sesión a arreglarlo. NO pregunta nada.
        ↓  la sesión arregla y abre un PR. NO lo mergea.
   El CI aprueba el PR
        ↓  pr-listo.yml  →  POST /revision/pr-listo
   Suena el teléfono: «he detectado un fallo, ya lo he corregido, ¿lo despliego?»
        ↓  dices que sí — por teléfono, por el botón del móvil o hablando con Jarvis
   Se mergea el PR y se dispara el deploy del backend.
```

La diferencia con preguntar antes no es de comodidad, es de **calidad de la decisión**.
Preguntar antes te hace decidir con lo que menos sabes: «¿quieres que mire un fallo que
aún no he mirado?». Preguntar después te deja decidir viendo el arreglo hecho, escrito y
verificado por el CI. Y el 90% de las veces la respuesta correcta es que sí, así que
gastarte una decisión al principio es gastarla en el sitio equivocado.

## Las cuatro fronteras

Ninguna de estas se relaja. Son lo que separa esto de un sistema que despliega solo.

1. **Arreglar solo, sí; desplegar solo, NO.** Abrir un PR es reversible y no lo ve nadie
   más. Desplegar toca producción. Por eso el arreglo no pregunta y el despliegue
   siempre pregunta, aunque el CI esté verde y el cambio sea de una línea. Es la misma
   frontera que separa las herramientas de Jarvis que se ejecutan solas de las que pasan
   por confirmación.

2. **El permiso vale para UN PR concreto.** El que estaba verde cuando se preguntó, que
   se guarda en `pr_numero` con la decisión. Entre la pregunta y tu respuesta pueden
   pasar horas; resolver «el PR más reciente» al contestar podría desplegar otro que
   entró por el medio. Misma razón por la que el aviso de «te has ido con las luces
   encendidas» guarda las entidades de ESE momento.

3. **Solo se despliega lo que el CI ha aprobado.** Quien avisa de que hay algo que
   desplegar no es la sesión que arregló, es el CI al ponerse verde. La sesión puede
   *creer* que ha terminado; el CI lo *sabe*. Por eso `pr-listo.yml` cuelga del resultado
   del CI y no de que se abra un PR.

4. **Una avería que se repite no se arregla, se cuenta.** Pasados `AVERIA_MAX_INTENTOS`
   arreglos del mismo origen sin llegar a desplegarse, se deja de lanzar sesiones y se
   avisa de que **el arreglo es el problema**. Es la regla del vigilante del sistema: un
   fallo que se arregla solo todos los días no está arreglado, está escondido.

## Las piezas

| Pieza | Dónde vive | Qué hace |
|---|---|---|
| `.github/workflows/ci-averiado.yml` | Aquí | Ve el CI rojo en `main` y llama a `POST /averia` |
| `POST /averia` | `backend/main.py`, sección «Averías que se arreglan solas» | Apunta la avería y dispara la sesión de arreglo. No avisa |
| La routine que arregla | claude.ai — **la misma** que la de la revisión nocturna | Arregla y abre PR. La instrucción le dice que NO mergee |
| `.claude/skills/arreglar-revision/SKILL.md` | Aquí | Su paso 0 distingue los dos caminos: con issue se mergea, con avería no |
| `.github/workflows/pr-listo.yml` | Aquí | Ve el CI verde sobre una rama `claude/…` con PR y llama a `POST /revision/pr-listo` |
| `POST /revision/pr-listo` | `backend/main.py` | Marca la avería como `listo`, deja el aviso con botones y **llama por teléfono** |
| `POST /despliegue/{id}/accion` | `backend/main.py` | La respuesta al botón: mergea el PR y dispara `deploy-backend.yml` |
| Herramienta `desplegar` | El registro de Jarvis | Lo mismo, hablando, para cuando el aviso salió por correo y no traía botones |
| `supabase/migrations/20260831_averias.sql` | Aquí | Las columnas `origen`, `pr_numero` y `detalle` sobre `revision_hallazgos` |

**Se reutiliza `revision_hallazgos` y no una tabla nueva** porque es la misma pregunta
con el mismo id determinista y la misma transición atómica. Lo único que cambia es de
dónde vino y hasta dónde llega. Los estados son ahora:

```
pendiente  → hay algo que decidir (el camino del issue nocturno)
arreglando → hay una sesión trabajando en ello
listo      → hay un PR con el CI en verde esperando tu permiso
desplegado → dijiste que sí y se desplegó
descartado → dijiste que no
```

## El teléfono

Cuando hay un PR esperando permiso, además del aviso al móvil **suena el teléfono**:
descuelgas y hablas con el Jarvis de siempre, que te cuenta qué se ha roto y despliega si
le dices que sí. Es el único caso de todo el proyecto que hoy justifica llamar, porque es
el único que **se queda parado hasta que contestes**.

El canal entero —qué servicios se evaluaron y por qué se eligió Twilio, cómo está montado
el puente de audio, qué protege sus dos endpoints públicos, cuánto cuesta y qué le
falta— está en **`docs/LLAMADAS.md`**. Aquí solo importa quién llama y cuándo:
`POST /revision/pr-listo` es el único sitio del backend que lo hace.

Dos cosas de allí que conviene saber sin abrirlo:

- **Un «sí» no lo interpreta el modelo.** Antes de pasarle nada a Jarvis se mira si lo
  dicho es la respuesta a la pregunta que motivó la llamada (`_sio_no`, lista cerrada).
  Ante la duda **no se despliega**.
- **El puente es la única parte asíncrona del backend**, y no está probado contra Twilio
  real: la primera llamada de verdad es la prueba que falta.

## Montarlo

### 1. La migración

Aplica `supabase/migrations/20260831_averias.sql` en el editor SQL de Supabase. Sin ella
todo lo demás falla al escribir las columnas nuevas.

### 2. Los workflows

En *Settings → Secrets and variables → Actions* ya tienen que estar (los usa la revisión
nocturna): la variable `BACKEND_URL` y el secret `REVISION_TOKEN`. Los dos workflows
nuevos no piden nada más — reutilizan el mismo token a propósito, porque son la misma
clase de cliente (un workflow que arranca solo) y separarlos no protegería de nada.

Ojo con `workflow_run`: **solo dispara desde la rama por defecto.** Mientras esto viva en
una rama de trabajo no salta, ni aunque el CI falle.

### 3. La credencial de despliegue

`DEPLOY_GITHUB_TOKEN` es un PAT de GitHub con permiso para mergear PRs y lanzar
workflows (`contents: write`, `pull_requests: write`, `actions: write` sobre este
repositorio). **Es la credencial más peligrosa del backend**: con ella se toca
producción. Sin configurar, el botón de desplegar lo dice en vez de fallar en silencio, y
todo lo demás —detectar, arreglar, avisar, llamar— sigue funcionando igual.

### 4. El teléfono

En [twilio.com](https://www.twilio.com): compra un número con voz, y apunta el Account
SID y el Auth Token. En el backend:

```bash
LLAMADAS=1
TWILIO_ACCOUNT_SID=AC...
TWILIO_AUTH_TOKEN=...
TWILIO_NUMERO=+34...        # el número que compras
TWILIO_MI_NUMERO=+34...     # tu móvil
BACKEND_URL=https://...     # la URL pública del backend, para que Twilio vuelva
```

No hay que configurar nada en la consola de Twilio: el webhook viaja en la propia
petición que crea la llamada (`Url`), así que el número no necesita tener nada asociado.
El detalle de cada variable y los ajustes finos del audio, en `docs/LLAMADAS.md`.

**Coste**: el número son un par de euros al mes y la llamada, céntimos por minuto. A dos
o tres avisos por semana no llega a un café al mes. Lo que sí cuesta de verdad si se
descuida es lo de dentro: cada turno de la llamada es una transcripción de Whisper, una
vuelta de Jarvis y una síntesis de ElevenLabs. De ahí `LLAMADA_MAX_SEG`, que es un tope
duro — una llamada que no se cierra sigue cobrando por minuto.

### 5. El interruptor

`AVERIA_CI=1` enciende el arreglo automático. **Los dos flags nuevos (`AVERIA_CI` y
`LLAMADAS`) nacen apagados**, al revés que el resto de `_flag()` del proyecto: uno lanza
agentes que escriben código y el otro hace sonar un teléfono de pago. Encenderlos por
defecto al desplegar sería la clase de sorpresa que este fichero existe para evitar.

## Seguridad

Tres cosas nuevas expuestas a internet, y qué las protege:

- **`POST /telefono/voz`** es público —lo llama Twilio, sin cabeceras nuestras— y lo que
  devuelve abre un puente de voz contra Jarvis. Lo protege la **firma de Twilio**
  (HMAC-SHA1 sobre la URL más los campos del formulario, `_firma_twilio_ok`), comparada
  con `hmac.compare_digest` como todas las credenciales de este proyecto. Sin el token
  configurado no vale ninguna firma: fail-closed, igual que `_token_ok`.

- **`WS /telefono/media`** no puede llevar token en cabecera —un WebSocket que abre
  Twilio no trae las nuestras—, así que lo autentica un **JWT firmado en la query**
  (`_contexto_llamada`) que dice qué se va a decir y sobre qué decisión va. Caduca en
  cinco minutos y solo vale para una llamada. Lleva `purpose: "llamada"` porque lo exige
  la invariante 2 de `CLAUDE.md`: todos los JWT se firman con la misma `SECRET_KEY`, y es
  ese claim lo que impide que este token valga como sesión de usuario — y, al revés, que
  el token del dashboard o el `state` del OAuth abran el teléfono.

- **`POST /despliegue/{id}/accion`** es la única ruta HTTP del backend cuyo efecto es
  tocar producción. Va en un endpoint aparte de `/revision/{id}/accion`, con su propia
  función de decisión, aunque el patrón sea idéntico: conviene poder leerla, auditarla y
  revocarla sin arrastrar la otra, y que un fallo leyendo la acción no pueda desplegar
  cuando se quería arreglar. Ni siquiera comparten el `if`.

Y el texto que se dice por teléfono sale de `detalle`, que lo escribe el workflow, no un
tercero. Si algún día una avería la reporta algo de fuera, ese texto acaba en un prompt
de un modelo con herramientas: habrá que envolverlo como dato, igual que el enunciado de
Alud en `build_cowork_instruction`.

## Probarlo sin esperar a que se rompa nada

```bash
# 1. Simular el CI roto (lanza una sesión de arreglo de verdad)
curl -X POST "$BACKEND_URL/averia" -H "X-Auth-Token: $REVISION_TOKEN" \
     -H "Content-Type: application/json" \
     -d '{"origen":"ci","referencia":"prueba-1","detalle":"prueba a mano"}'

# 2. Simular que el PR ya está verde (avisa y LLAMA de verdad)
curl -X POST "$BACKEND_URL/revision/pr-listo" -H "X-Auth-Token: $REVISION_TOKEN" \
     -H "Content-Type: application/json" -d '{"pr":122}'
```

El segundo hace sonar el teléfono, así que es la forma de probar la llamada sin romper el
CI. Para probar solo el aviso sin gastar una llamada, apaga `LLAMADAS`.
