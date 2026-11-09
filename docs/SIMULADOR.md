<!-- Parte de la guía del repositorio. El índice y las reglas que aplican
     SIEMPRE están en CLAUDE.md, en la raíz. -->

## El simulador de llamadas y el repaso nocturno

Dos piezas que van juntas, del 2026-11-09, las dos en `telefono/simulador/` y las dos
pensadas para correr **en `caja`**, que es donde vive el teléfono:

- **El repaso** (`repasar.js`): cada madrugada Jarvis lee sus propias llamadas del día y
  apunta dónde rozó. Hasta ahora eso solo se sabía si Mikel lo contaba al día siguiente
  («es demasiado redundante, repito todo muchísimo»).
- **El simulador** (`simular.js`): alguien que hace de Mikel llama a Jarvis, en texto, y se
  comprueba qué pasa. Es lo que permite cambiar el RUNBOOK, una descripción o un modelo y
  saber si se ha roto algo **antes** de que lo note él conduciendo.

El repaso alimenta al simulador: cada llamada de verdad con roces queda guardada como un
caso que se puede volver a pasar.

| Fichero | Qué es |
|---|---|
| `simular.js` | El runner del simulador. Monta una copia del puente, el mundo falso, y pasa los casos |
| `mundo.js` | El backend de mentira: el MCP del teléfono, el contexto al descolgar y la confirmación |
| `oido.js` | Estropea la frase como la estropea el oído en el coche, siempre igual para el mismo caso |
| `juez.js` | Qué tenía que pasar y si pasó. Sin modelo |
| `casos.json` | Los casos versionados. **Todos inventados** |
| `friccion.js` | Lee la transcripción de una llamada y marca los roces. Sin modelo |
| `repasar.js` | El repaso: mirar, pensar (si hubo roces) y dejar el informe y los casos |
| `repaso-llamadas.{service,timer}` | El temporizador de usuario que lo lanza a las 05:10 |
| `test/` | `node --test "telefono/simulador/test/*.test.js"`. No entra en el CI: es Node suelto, como los de la voice-app |

### Cuánto gasta

Nada de API de pago y nada de voz. Las dos piezas usan **Claude Code con la suscripción**,
igual que el teléfono y el chat:

- **Simulador**: cada llamada simulada gasta lo que una de verdad igual de larga (un turno
  de Sonnet por frase; el sí o el no de una confirmación no gasta, lo decide la voice-app).
  Los doce casos son unos catorce turnos. Por eso **no corre solo** y tiene un tope de 15
  llamadas por tirada (`--max` para subirlo a propósito).
- **Repaso**: mirar no gasta nada. Pensar es **una** sesión de Sonnet sin herramientas, y
  solo las noches en que hubo algún roce.

Quien hace de Mikel hoy es un guion con ruido, no un modelo: un Mikel que improvise y
«cientos de llamadas por noche» esperan a que haya un modelo local en jacobo, que es
cuando dejan de costar.

### El simulador: qué es de verdad y qué no

```bash
node telefono/simulador/simular.js                    # los casos de casos.json
node telefono/simulador/simular.js --filtro garaje    # solo los que casen
node telefono/simulador/simular.js --ruido coche      # como se oye en el coche (o «malo»)
node telefono/simulador/simular.js --casos ~/telefono-repaso/casos-reales.json --filtro real-2026-11-09
node telefono/simulador/simular.js --modelo claude-haiku-5-5   # ¿aguanta otro modelo?
```

- **El cerebro es el de verdad.** Se lanza una copia del `server.js` del puente
  (`~/.claude-phone-cli/claude-api-server`) en otro puerto, con el mismo RUNBOOK
  (`~/telefono-jarvis/CLAUDE.md`), el mismo modelo, la misma identidad y el **catálogo de
  herramientas real**, que se le pide al backend solo para leerlo. No se copia ni una línea
  de cómo se lanza Claude: si mañana cambia el puente, el simulador cambia con él.
- **Lo que confirma es lo de verdad**: `confirmacion.js` de la voice-app decide qué es un
  sí, hace la pregunta y deja el aviso entre corchetes para el turno siguiente.
- **El mundo es de mentira.** `CONTEXTO_URL` apunta a `mundo.js`, y el puente lleva ahí el
  MCP. Las herramientas contestan lo que diga el caso (`mundo`), proponen si son de las que
  se confirman, y si el caso no dice nada, `{"ok": true}`. **Nada de lo simulado abre una
  puerta, manda un mensaje ni apunta una cita.** El `.mcp.json` de la copia apunta a un
  dominio `.invalid`: si el puente dejara de reescribirlo, la sesión se queda sin
  herramientas, no con las de verdad.
- **Sin terminal.** La sesión del teléfono lleva Bash y `--dangerously-skip-permissions`:
  una llamada simulada que dijera «reinicia el backend» lo reiniciaría. La copia se lanza
  con `--tools ''`, y `montarPuente` **se niega a montar** si no encuentra exactamente una
  vez el `'--tools', 'Bash',` que sabe quitar. Consecuencia: las averías (lo que Jarvis
  diagnostica con la shell) no se pueden simular.
- **Sin voz.** Ni Fish, ni Azure, ni oído. Los segundos que salen son los de Claude, no los
  de la llamada entera.
- Las sesiones de mentira se borran al acabar (`~/.claude/projects/-tmp-simulador-…`), para
  que el repaso no las lea como llamadas.

**Un caso** (`casos.json`), con todo lo que admite:

```json
{ "id": "garaje-abrir-si",
  "turnos": ["Jarvis, abre la puerta del garaje", "sí"],
  "mundo":     { "herramienta": { "lo": "que contesta" }, "otra": { "_error": "Outlook no responde." } },
  "contexto":  "Lo ya mirado al descolgar.",
  "preguntas": { "garaje": "¿Abro la puerta del garaje?" },
  "modo": "coche", "ruido": "malo",
  "espera": { "herramientas": ["agenda"], "sin_herramientas": ["casa_ordenar"],
              "argumentos": { "garaje": { "accion": "abrir" } },
              "propone": "garaje", "confirmado": true,
              "dice": ["dentista"], "no_dice": ["está libre"], "max_palabras": 25, "max_segundos": 6 } }
```

Y dos reglas que se le piden a todos sin escribirlas: **40 palabras por turno** como mucho
(el RUNBOOK) y **al proponer, solo «De acuerdo.»** (el parche 44). Los resultados, con todo
lo dicho, quedan en `~/telefono-simulador/` de `caja`.

**El primer resultado (2026-11-09):** 12 de 12, turno mediano de 3,1 s. Y el parche 44
visto con el cerebro real: «Jarvis, abre la puerta del garaje» → «De acuerdo.» + «¿Abro la
puerta del garaje?» → «sí» → «Hecho.».

### El repaso: tres pasos

```bash
node telefono/simulador/repasar.js                    # mira y escribe el informe
node telefono/simulador/repasar.js --pensar --avisar  # lo de cada noche (el temporizador)
node telefono/simulador/repasar.js --horas 72
```

1. **Mirar.** Lee las transcripciones que Claude Code deja de cada sesión del teléfono
   (`~/.claude/projects/-home-…-telefono-jarvis/*.jsonl`, una por llamada) y marca:

   | Roce | Cómo se detecta |
   |---|---|
   | tuvo que repetirse | la frase comparte casi todas las palabras con la anterior |
   | le corrigió | empieza por «no», «te he dicho», «otra vez»… y Jarvis **no** acababa de preguntar |
   | le cortó | el turno trae el aviso de interrupción de la voice-app |
   | no se le entendió el sí o el no | el aviso de `resolverConfirmacion` |
   | turno lento | más de 8 s |
   | falló una herramienta | resultado con error |
   | respuesta larga | más de 40 palabras |
   | dijo que no podía | «no puedo», «no he podido» |

   No entiende nada, solo cuenta: hay falsos positivos (el «no puedo» del garaje antes de
   que se pudiera era la regla, no un fallo), y por eso existe el paso 2.
2. **Pensar** (`--pensar`, solo si hubo roces). Una sesión de `claude -p` **sin ninguna
   herramienta** (`--tools ''`, sin MCP, sin ajustes) lee las llamadas con roces y escribe
   qué pasó, cuáles son falsos positivos y como mucho tres cambios. Sin herramientas porque
   en una llamada se leen WhatsApp y páginas escritos por otros: lo que haya ahí puede
   decir lo que quiera, que esa sesión no puede hacer nada.
3. **Dejarlo a mano.** El informe (`~/telefono-repaso/AAAA-MM-DD.md`) y las llamadas con
   roces como casos del simulador (`casos-reales.json`, hasta 200). Con `--avisar`, una
   notificación al móvil por `mandar_notificacion` que **solo lleva cuentas**.

**Todo se queda en `caja`, y eso no se relaja.** Las llamadas llevan nombres, mensajes y
citas, y este repositorio es público: el repaso no abre issues ni escribe en el
repositorio, a diferencia de la revisión nocturna del código. Por lo mismo, un caso real
que se quiera versionar se reescribe antes con datos inventados.

**Lo que NO hace: arreglar.** Dice qué rozó y lo deja reproducible. El arreglo lo hace una
sesión con el código delante: lee el informe en `caja`, pasa los casos reales, cambia lo
que sea y los vuelve a pasar. Un caso real nace sin `espera` (solo se le piden las dos
reglas de siempre); escribirle qué tenía que haber pasado es parte del arreglo.

**El primer repaso (2026-11-09, 72 h):** 17 llamadas, 12 con roces. Lo más útil que sacó:
que dijo no poder ver las cámaras cuando `camaras_mirar` había funcionado esa misma tarde,
y que para poner una película reintentó tres veces con la línea en silencio (45 y 70 s).

### Instalarlo en caja

Las unidades no están aún en HomeLab (que es la fuente de verdad de `caja`): se copian a
mano, como dice la cabecera de `repaso-llamadas.service`. Usa el repositorio que despliega
`desplegar.sh`, así que el repaso es siempre el de la versión desplegada.
