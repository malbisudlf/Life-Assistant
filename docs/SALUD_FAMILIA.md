<!-- Parte de la guía del repositorio. El índice y las reglas que aplican
     SIEMPRE están en CLAUDE.md, en la raíz. -->

## Salud de la familia

Lo mismo que Mikel tiene con su salud, para otras personas (sus padres): su Apple
Watch/iPhone manda los datos a este backend y **su propio Claude** (cada uno con su
Claude Pro) les redacta un resumen que les llega por correo. Montado el 2026-10-15.

```
iPhone de la persona ── Health Auto Export ──► POST /familia/salud/ingest ──► salud_familia
                                                    (su token)                (su persona)
Rutina de SU Claude ── GET /familia/salud/resumen ──► datos crudos de SU salud
        │ (redacta)
        └────────────── POST /familia/salud/briefing ──► el backend se lo manda a SU correo
```

Antes hubo un intento con un webhook y mandando los datos por correo que no llegó a
funcionar; no quedó nada de él ni en el repositorio ni en `caja`.

### Las tres reglas (no las relajes)

1. **Sus datos viven en `salud_familia`, nunca en `health_metrics`.** `health_metrics` la
   leen decenas de sitios (el resumen diario, Jarvis, las reglas, el diagnóstico, el
   dashboard) y ninguno filtra por persona. Con una columna `persona` en esa tabla, un
   filtro olvidado en una sola lectura metería la salud de otra persona en el briefing de
   Mikel. Con otra tabla, nada de lo de Mikel puede verla aunque se olvide de algo. Por lo
   mismo, la ingesta de la familia **no dispara nada** de lo que cuelga de la de Mikel: ni
   la señal de «la noche ha llegado» que manda su correo de la mañana, ni «días sin
   entrenar». Hay tests que fallan si una petición de la familia toca `health_metrics`
   (`tests/backend/test_salud_familia.py`).
2. **La persona sale del token y de nada más.** Ni del cuerpo ni de la query. Cada token
   solo abre lo de su persona: escribir sus datos, leer su resumen y mandarle su correo.
   Solo por cabecera (`X-Auth-Token` o `Authorization: Bearer`), nunca por la query: es
   una integración nueva y por ahí el token acabaría en el registro de URLs.
3. **El correo va a la dirección del `backend.env`**, nunca a una que traiga la petición.
   Un token filtrado puede, como mucho, escribir datos falsos de esa persona, leer su
   resumen o mandarle a ella su propio correo (cinco al día como mucho). Se rota cambiando
   el token en el `.env`.

### Lo que hay en el backend

| Pieza | Qué hace |
|---|---|
| `SALUD_FAMILIA` | `persona:token:correo` separadas por comas, en `backend.env`. Una entrada mal escrita se descarta ella sola al arrancar y el registro dice cuál (por posición), sin tumbar el backend: un fallo en esto no puede dejar a Mikel sin servicio. También se descarta un token de menos de 32 caracteres, uno repetido entre dos personas (las dos fuera) y uno igual que **cualquier otra variable del entorno**: con el de `HEALTH_INGEST_TOKEN`, el iPhone de un familiar escribiría en lo de Mikel |
| `POST /familia/salud/ingest` | La misma ingesta que `/health/ingest` (mismas reglas: acumulativas que no bajan, kJ a kcal, ceros sin medida, sueño por tramos…), escribiendo en `salud_familia` con su persona. Los entrenos van en el mismo upsert, una fila por día |
| `GET /familia/salud/resumen` | La sección de salud del correo de Mikel (`_resumir_salud` y `_render_salud_texto`, compartidas), en JSON (`salud`) y en texto (`texto`), sacada solo de sus filas. Si Supabase no contesta, **502**, nunca «sin datos»: quien lo lee es un modelo y lo contaría como que el reloj no mandó nada. 30 lecturas por hora |
| `POST /familia/salud/briefing` | `{texto, asunto?}`. Lo manda por SMTP, **desde la cuenta de Mikel**, a su correo, con un pie que pone el backend («no es una opinión médica…») para que salga aunque cambie el prompt. Uno al día (`salud_familia_envios`, la misma reserva atómica que `brief_envios`: 409 si ya salió). `?forzar=1` se salta la reserva para probar, dentro del tope de `SALUD_FAMILIA_ENVIOS_DIA` (5) al día. Si el envío falla, libera el día |
| Retención | Al recibir datos, como mucho una vez al día por persona, se borra lo de esa persona con más de `SALUD_FAMILIA_RETENCION_DIAS` (400) días. 0 lo apaga |
| Copia de seguridad | **No se copian** (`SIN_COPIA` en `scripts/copia_supabase.py`): un volcado más es un sitio más donde viven datos de salud que no son de Mikel, y Health Auto Export puede reenviar el histórico |

Hace falta haber aplicado la migración `20261015_salud_familia` (dos tablas con RLS y sin
policies).

**Por qué la rutina entrega el texto al backend en vez de mandar ella el correo**: desde
una rutina de Claude no se puede *enviar* un correo (el conector de Gmail solo crea
borradores), y darle a la rutina el conector de Gmail le daría acceso a todo su buzón.
**Por qué no un correo de datos crudos como el de Mikel**: su rutina tendría que leer su
buzón para encontrarlo, y llenaría su bandeja de correos con números.

### Dar de alta a una persona

1. Genera su token: `python -c "import secrets; print(secrets.token_urlsafe(32))"`.
2. Añádela a `SALUD_FAMILIA` en `~/stack/backend.env` de `caja` (haz copia del fichero
   antes, como siempre). El identificador **no debe ser su nombre completo**: puede salir
   en el registro y, de ahí, en un issue del repositorio público.
3. Recrea el contenedor (el `.env` se lee al arrancar) con `./desplegar.sh`, y comprueba en
   el registro que no ha salido ningún «entrada N de SALUD_FAMILIA descartada».
4. Monta su iPhone y su rutina (abajo).

**Darla de baja**: quítala de `SALUD_FAMILIA`, recrea el contenedor y borra sus filas desde
el editor SQL de Supabase (`delete from salud_familia where persona = '…'`, y lo mismo en
`salud_familia_envios`). Su rutina, en su cuenta de Claude, la tiene que apagar ella.

### En su iPhone: Health Auto Export

La automatización REST de Health Auto Export es de la versión de pago; mira el precio en
la App Store antes de montarlo.

1. Dale permiso de lectura en Salud a todo lo que vaya a exportar.
2. Automations → nueva → **REST API**:
   - URL: `https://api.lifeassistantbackend.bid/familia/salud/ingest`
   - Headers: `X-Auth-Token` = su token. **En cabecera, nunca en la URL.**
   - Data Type: Health Metrics. Export Format: JSON, versión 2. Summarize Data: ON.
     **Batch requests: ON**. Sync Cadence: la más frecuente.
3. Otra automatización igual con Data Type **Workouts**.
4. Ajustes → General → Actualización en segundo plano → Health Auto Export → ON.
5. Para el histórico: Date Range «Last 30 Days» y Export Now a mano, una vez.

Para comprobarlo: en la app, la automatización enseña la respuesta del backend
(`{"ok": true, "upserted": N}`). Un 403 es el token mal copiado. Si no aparece nada,
aplica lo de siempre (`docs/SALUD.md`): iOS no garantiza el segundo plano, y el registro
del backend dice qué llegó y quién lo mandó.

### En su Claude Pro: la rutina

Las rutinas de Claude Code funcionan con Pro y corren en la nube aunque su ordenador esté
apagado. Se montan en `claude.ai/code/routines` desde su cuenta.

1. **Entorno**: en `claude.ai/code`, crea un entorno nuevo (no el Default) y, en
   **Network secrets → Add secret**, tipo **Bearer**, host
   `api.lifeassistantbackend.bid`, cabecera `Authorization` con prefijo `Bearer` y su
   token como valor. El proxy de Anthropic se lo añade a cada petición a ese host: Claude
   **nunca ve el token**, no hay que abrir la red a ese dominio y el token no queda en el
   prompt ni en las sesiones.
2. **Rutina**: nueva rutina con ese entorno, modelo Sonnet (sobra para esto), **sin
   conectores** (quita todos los que vengan por defecto: aquí no hacen falta y cada uno es
   acceso de más a su cuenta), trigger diario a una hora con minutos (las 9:37 mejor que
   las 9:00, que puede salir tarde). Si el formulario exige un repositorio, uno privado y
   vacío en su GitHub: la rutina no toca nada de él.
3. **Prompt**: el de abajo, cambiando el nombre.
4. **Run now** para probarlo. El primer día, si quieres probar dos veces, la segunda dará
   409 (ya enviado): es lo correcto.

```text
Redactas cada mañana el resumen de salud de <NOMBRE> a partir de los datos de su reloj y
su iPhone, y se lo mandas. No hagas nada más: no crees ficheros, ramas ni pull requests.

1. Pide los datos:
   curl -sS -w '\nHTTP %{http_code}\n' https://api.lifeassistantbackend.bid/familia/salud/resumen
   La autenticación la añade el entorno: no la pidas ni la escribas.
   - 403: el token del entorno está mal. Para aquí y no mandes nada.
   - 502 u otro 5xx: espera dos minutos y reinténtalo una vez; si sigue, para.
2. Lee el campo "texto" de la respuesta (en "salud" está lo mismo en JSON). Cómo leerlo:
   - n = días con dato. Con n bajo no hables de tendencias ni de cambios.
   - «Anoche: el sueño todavía no ha llegado» NO significa que no llevara el reloj: el dato
     tarda en sincronizar. No digas nada sobre si lo llevó puesto.
   - Los días atípicos dicen qué se sale de su costumbre; no son un diagnóstico.
3. Escribe el resumen en español, cercano y claro, para alguien que no es médico ni
   técnico, sin jerga ni siglas sin explicar, en 150-300 palabras: cómo ha dormido, cuánto
   se ha movido, cómo va su corazón en reposo, lo que más destaque de la semana y una
   sugerencia sencilla para hoy. Tutéale. Sin listas de números: como mucho dos o tres
   cifras que importen.
   - Nunca diagnostiques ni le asustes. Si algo se sale mucho de lo suyo varios días
     seguidos, sugiérele con calma comentarlo con su médico.
   - Si no hay datos, díselo con naturalidad y recuérdale llevar el reloj y abrir la app
     de Health Auto Export. No inventes valores.
   Guárdalo en resumen.txt, solo el texto del correo, sin saludo de asistente ni notas.
4. Mándaselo. Construye el JSON con Python para que las comillas y los saltos de línea
   vayan bien escapados:
   python3 -c 'import json,sys; print(json.dumps({"asunto": sys.argv[1], "texto": open(sys.argv[2]).read()}))' "<un asunto corto y amable>" resumen.txt > cuerpo.json
   curl -sS -w '\nHTTP %{http_code}\n' -X POST -H 'Content-Type: application/json' \
     --data @cuerpo.json https://api.lifeassistantbackend.bid/familia/salud/briefing
   - 200: hecho. 409: ya se le mandó hoy; termina sin error.
   - 503 o 502: espera cinco minutos y reinténtalo una vez.
```

### Coste

- **Backend**: nada. Ni una llamada a un modelo (el análisis lo hace su Claude), unas 25
  filas al día por persona en Supabase (menos de 10.000 al año, con la retención) y un
  correo al día por SMTP.
- **Su Claude**: una sesión corta al día, que gasta de su cuota de Pro como cualquier
  conversación.
- **Health Auto Export**: la versión de pago, en su iPhone.

### Privacidad: son datos de salud de otras personas

- **Que lo sepan y lo quieran.** Los datos pasan por el backend de Mikel y quedan en su
  Supabase: técnicamente, Mikel puede verlos. Que lo sepan antes de montarlo.
- **Ningún sitio de Mikel los enseña**: ni el dashboard, ni Jarvis, ni su resumen, ni la
  zona dev (todo eso lee `health_metrics`). No añadas un widget ni una herramienta de
  Jarvis que los lea sin hablarlo antes con ellos.
- **No se copian** en el volcado semanal, y lo más antiguo de 400 días se borra solo.
- **En el registro no hay valores**, solo la forma de lo que llega (igual que con lo de
  Mikel) y el identificador de la persona. Por eso el identificador no es su nombre.
- **El correo no es una alarma médica.** Llega una vez al día y lo escribe un modelo: no
  sustituye a los avisos del propio reloj (ritmo irregular, caídas) ni a su médico. El
  pie lo dice en cada correo.
- **Lo que lee su Claude** son sus propios datos, en su propia cuenta de Anthropic.
