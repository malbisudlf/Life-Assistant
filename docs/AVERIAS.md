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

El resto de canales del proyecto tienen todos el mismo techo: **hace falta que mires**.
Un correo espera a que abras el buzón; una notificación, a que desbloquees. Los dos valen
para casi todo y no valen para lo único que de verdad se queda parado: un arreglo hecho
esperando permiso.

La llamada es el único canal que no espera a nadie, y en el coche suena por el manos
libres. Por eso es el canal más caro que hay aquí —cuesta dinero e interrumpe de
verdad— y por eso su regla es la más estrecha del proyecto:

> **Solo llama lo que se queda parado hasta que contestes.** No lo urgente, no lo
> importante: lo BLOQUEADO. Hoy eso es exactamente una cosa, el permiso de despliegue.

Si algún día llama una segunda cosa, tiene que estar justificada aquí. El día que el
teléfono suene por algo que podía haber esperado, dejarás de cogerlo — y con él se irá
también el aviso que sí importaba. Es el mismo fallo que el presupuesto de avisos
previene en el canal de al lado, con la factura más alta.

### Es una conversación, no un contestador

Descuelgas y hablas con el Jarvis de siempre: el mismo `_jarvis_turno`, las mismas
herramientas y la misma frontera de confirmación que en el chat y en el modo llamada del
navegador. No hay un asistente nuevo, hay un **transporte** nuevo, y eso es deliberado:
dos asistentes que responden distinto según por dónde entres son dos asistentes que
mantener. Puedes preguntarle qué se ha roto, qué ha cambiado, y decirle que lo despliegue
o que lo deje.

```
Twilio  ──WebSocket (μ-law 8 kHz)──▶  /telefono/media
                                          │
                              ┌───────────┴───────────┐
                              │  VAD por energía      │  ¿ha terminado de hablar?
                              │  Whisper              │  audio → texto
                              │  _jarvis_turno        │  el cerebro de siempre
                              │  ElevenLabs (ulaw)    │  texto → audio
                              └───────────┬───────────┘
                                          ▼
                                  vuelve por el mismo WebSocket
```

Cuatro decisiones que conviene entender antes de tocar `# ── El puente de voz del
teléfono ──` en `main.py`:

- **Es la única parte asíncrona del backend.** El resto de `main.py` no usa `asyncio`, y
  no es un descuido: los endpoints hacen E/S de bloque y viven mejor en el pool de hilos
  de FastAPI. Un WebSocket no se puede servir así. Todo lo síncrono que se llama desde
  dentro del puente va envuelto en `asyncio.to_thread`; llamarlo directo bloquearía el
  bucle de eventos y con él el audio de la llamada, que **se oye como un corte**.

- **El audio del teléfono es μ-law a 8 kHz**, que no es lo que come ninguno de los dos
  extremos. Se convierte a mano (`_ulaw_a_pcm16`, tabla G.711) en vez de con `audioop`:
  está en la stdlib de Python 3.11 pero **desaparece en 3.13**, y son treinta líneas que
  no merecen atar el proyecto a una versión. A la vuelta no hace falta convertir nada: a
  ElevenLabs se le pide `ulaw_8000` directamente, que además lo hace mejor que nosotros
  porque tiene la señal sin comprimir delante.

- **Quién habla lo decide el silencio.** No hay «pulsa para hablar» en una llamada: se
  mide la energía de lo que entra y se da el turno por terminado tras `VOZ_SILENCIO_MS`
  de calma. Es un VAD pobre a propósito — el bueno vive en ElevenLabs y cuesta, y para
  «sí, despliégalo» éste llega de sobra.

- **Un «sí» no lo interpreta el modelo.** Antes de pasarle nada a Jarvis se mira si lo
  que has dicho es la respuesta a la pregunta que ha motivado la llamada (`_sio_no`, con
  una lista cerrada de formas de decir sí y no). Hacer que el permiso de despliegue
  dependa de que el modelo elija bien la herramienta metería un fallo posible justo en la
  puerta que toca producción. **Ante la duda no se despliega**: de los dos errores, ése
  es el único que se puede deshacer solo.

### Lo que le falta

**Interrumpirle.** Mientras Jarvis piensa o habla, el audio que entra se tira. Es
exactamente lo que también le falta al modo llamada del navegador (`docs/JARVIS_VOZ.md`,
fases 5 a 7) y se resolverá en los dos sitios a la vez o en ninguno: hacerlo aquí aparte
sería mantener dos micrófonos distintos.

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
