<!-- Parte de la guía del repositorio. El índice y las reglas que aplican
     SIEMPRE están en CLAUDE.md, en la raíz. -->

## Evals de Jarvis: cuánto acierta eligiendo herramienta

Una tirada de casos («¿qué tengo mañana?» → `agenda`) contra la API real, que mide **una
sola cosa**: qué herramienta pide el modelo en la primera vuelta, con el esquema que el
backend expone de verdad. No mide si la respuesta está bien redactada ni si la
herramienta funciona — eso ya lo cubren `tests/backend` y el E2E.

| Fichero | Qué es |
|---|---|
| `evals/casos.json` | Los casos: petición en lenguaje natural → herramienta(s) aceptable(s). Y el umbral por defecto |
| `evals/correr.py` | El runner. Importa `backend/main.py` para sacar el esquema real |
| `.github/workflows/evals-jarvis.yml` | A mano (`workflow_dispatch`) y semanal (lunes). **No corre en cada push**: cuesta dinero |
| `evals/resultados.json` | La salida de la última tirada. Ignorado por git — el histórico vive en los artefactos del workflow |

### Por qué existe

Está medido y escrito en `docs/JARVIS.md` que **el modelo pequeño falla eligiendo entre
herramientas parecidas** —pidiéndole leer issues escogía `add_issue_comment`— y que ese
fallo **crece con el catálogo**, que ya va por 53 herramientas y sigue creciendo. Hasta
ahora esa regresión solo se detectaba hablándole y notando que hacía algo raro, o sea:
tarde y por casualidad.

Y hay una segunda pregunta, que es la que de verdad no se podía contestar: **si el
reparto de dos modelos sigue mereciendo la pena y si el de acción puede bajar de gama.**
Por eso el runner mide los dos por separado (`JARVIS_MODEL` y `JARVIS_MODEL_ACCION`) y
saca la diferencia en puntos: sin ese número, cambiar de modelo es una corazonada con
factura.

### Por qué NO vive en `tests/backend`

Tres motivos, y ninguno es de organización:

1. **Allí el modelo está simulado a propósito** (`conftest.py` monkeypatchea `requests` y
   el cliente de OpenAI). Esa suite comprueba el BUCLE de Jarvis —el despachador, el
   filtro de argumentos, la frontera de confirmación—, no el criterio del modelo. Son dos
   preguntas distintas y solo una necesita la API.
2. **Cuesta dinero real.** La verificación obligatoria antes de cada commit y el CI de
   cada push tienen que poder correr siempre y gratis. Una eval en el CI son ~130
   llamadas de pago por push.
3. **Falla de forma intermitente por definición.** Un modelo no es determinista, y un
   429 tampoco es un fallo del código. Meter eso en la suite que decide si un PR se
   mergea convierte "el CI está rojo" en algo que no significa nada.

Por lo mismo, el resultado **no bloquea nada**: sale con código distinto de cero si baja
del umbral, y ese código solo pone en rojo el run de las evals.

### Cómo se corre

```bash
python evals/correr.py                                  # los dos modelos del entorno
python evals/correr.py --modelos gpt-5-nano gpt-5-mini  # comparar candidatos
python evals/correr.py --filtro mcp --umbral 0.9        # solo un grupo
python evals/correr.py --hilos 1                        # si la cuenta va justa de TPM
```

Necesita `OPENAI_API_KEY` (la coge de `backend/.env` si está) y las dependencias del
backend. **No necesita nada más**: ni Supabase, ni Graph, ni Home Assistant. Lo que el
prompt de sistema leería de Supabase —el catálogo de la casa, los servidores MCP
guardados, la memoria— lo sustituye el runner por datos fijos, porque si no dos tiradas
del mismo día no serían comparables. Y enciende con valores de mentira las integraciones
que recortan el esquema (`requiere_mcp`, `requiere_arreglo`, `requiere_despliegue`): con
el catálogo a medias la cifra no diría nada, ya que el fallo que se busca crece
justamente con el número de herramientas parecidas.

En Actions: `gh workflow run "Evals de Jarvis" --ref main`. El único secreto que usa es
`OPENAI_API_KEY`; los modelos salen de las variables de repositorio `JARVIS_MODEL` y
`JARVIS_MODEL_ACCION` si están puestas. El resultado se publica en el resumen del run
(la tabla y el detalle de cada fallo) y el JSON queda como artefacto 90 días.

### Cómo se puntúa

- `espera` es una lista de nombres **aceptables**: basta con que pida uno. No es tibieza,
  es que hay peticiones con dos caminos igual de correctos (mirar el catálogo de la casa
  antes de ordenar, listar antes de borrar).
- `espera_todas` exige todas, para lo que de verdad necesita dos herramientas.
- `espera: []` es un **caso negativo**: no debe pedir ninguna. Están a propósito, porque
  un modelo que llama a algo ante cualquier frase gasta el doble y contesta peor.
- `confundible` no puntúa: marca el fallo previsto para que el informe distinga «se
  equivocó como siempre» de «se equivocó de una forma nueva», que es la señal que
  importa.
- **Un 429 o un corte de red no cuenta como fallo**: se reintenta con espera creciente y,
  si aun así no contesta, el caso sale como «sin medir» y desaparece del denominador.
  Contarlo como error de enrutado ensuciaría la única cifra que interesa y, peor, la
  empeoraría justo cuando la tirada va deprisa.

**El runner avisa de las herramientas del esquema que ningún caso cubre.** Al añadir una
entrada a `_JARVIS_HERRAMIENTAS`, añade aquí su caso: una herramienta sin caso no está
medida, y el catálogo crece más deprisa que los casos.

### Qué cuesta

Medido en la primera tirada real (63 casos × 2 modelos = 126 llamadas, 53 herramientas
en el esquema): **~295.000 tokens de entrada y ~1.200 de salida por modelo**, unos 4.700
tokens de entrada por llamada. A precios de septiembre de 2026 eso son unos **0,12 $ la
tirada completa** (0,045 $ con `gpt-4o-mini` y 0,078 $ con `gpt-5-mini`). Con la tirada
semanal, **menos de 7 $ al año**.

El esquema es casi todo el coste, y no se puede recortar sin dejar de medir lo que se
quiere medir. Es la misma conclusión de `docs/JARVIS.md`: **el esquema no es una palanca
de coste**; si algún día hay que adelgazarlo será por precisión.

### La medida de septiembre de 2026 (primera tirada)

| Modelo | Papel | Acierto |
|---|---|---|
| `gpt-4o-mini` | `JARVIS_MODEL` (el pequeño) | **63/63 — 100%** |
| `gpt-5-mini` | `JARVIS_MODEL_ACCION` (el de acción) | **51/63 — 81%** |

El resultado es el contrario del esperado, y por eso vale la pena tenerlo escrito. Lo que
dice el detalle:

- **El grueso del hueco es un solo patrón**: `gpt-5-mini` pide `estado_pc` en cinco de
  las siete peticiones sobre el PC —encender, apagar, suspender, streaming, relanzar—
  antes de actuar. **Y eso no es exactamente un error**: en el bucle real encadenaría y
  acabaría actuando. Esta eval mira solo la PRIMERA vuelta, así que penaliza a un modelo
  que prefiere mirar antes de tocar. Es la limitación conocida de la medida y hay que
  leerla con ella delante: la cifra de `gpt-5-mini` es un suelo, no su acierto real.
- Lo que sí son fallos limpios: `evento-crear` («ponme una cita el jueves») resuelto con
  `agenda`, `regla-crear` con `mis_reglas`, `buscar-internet` con `agenda`, y
  `mcp-desconectar`/`mcp-leer-issues` con `mcp_servidores`. Son todos del tipo que este
  fichero viene a vigilar: **consultar en vez de actuar** cuando las dos herramientas se
  parecen.
- Un negativo fallado: `gpt-5-mini` contesta a «buenas, ¿qué tal andas?» llamando a
  `mis_capacidades`.
- `gpt-5-mini` corre con `reasoning_effort: minimal`, que es lo que hace producción. No
  está medido con esfuerzo alto: subirlo cambia el coste y la latencia del modo llamada,
  así que sería otra medida, no una corrección de esta.

**Qué NO se deduce de aquí**: que haya que quitar el reparto. El reparto no existe para
acertar más en la primera elección, sino para que la vuelta que ACTÚA la tire un modelo
mejor con el resultado de las herramientas delante (ver `docs/JARVIS.md`). Lo que estos
números sí piden es medir con turnos de varias vueltas antes de tocar nada — y eso, hoy,
esta eval no lo hace.

### Lo que esta eval no mide (a propósito, de momento)

- **Turnos de varias vueltas.** Una llamada por caso es lo que la hace barata,
  reproducible y fácil de leer. La consecuencia está arriba: un modelo que consulta antes
  de actuar sale peor de lo que es.
- **Los argumentos.** Se comprueba QUÉ herramienta pide, no con qué valores. El
  despachador ya filtra los argumentos al esquema (`docs/JARVIS.md`), así que un nombre
  inventado no llega a ninguna función; una fecha mal resuelta sí pasaría desapercibida
  aquí.
- **Las herramientas de dentro de un MCP.** El caso `mcp-leer-issues` comprueba el paso
  previo (buscar la herramienta antes de usarla), no la elección final dentro del
  servidor, que es donde vive el fallo original de `add_issue_comment`. Para eso haría
  falta hablar con un servidor MCP real, y entonces la tirada dejaría de ser
  autocontenida.
