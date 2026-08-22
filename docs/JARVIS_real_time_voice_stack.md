# JARVIS — Real-Time Voice Stack

## Objetivo

Construir una interfaz de voz para JARVIS que se sienta como una conversación natural y en tiempo real.

JARVIS debe poder:

- Escuchar al usuario.
- Transcribir el habla en tiempo real.
- Enviar la petición al LLM mediante streaming.
- Empezar a hablar antes de que el LLM termine toda la respuesta.
- Reproducir audio por streaming.
- Detectar cuándo el usuario vuelve a hablar.
- Interrumpirse inmediatamente cuando el usuario le corta.
- Mantener memoria.
- Utilizar herramientas mediante MCP / tool calling.
- Utilizar una voz masculina, grave, calmada y natural en español de España.

---

# 1. Stack

| Componente | Tecnología |
|---|---|
| Speech-to-Text | **ElevenLabs Scribe v2 Realtime** |
| Text-to-Speech | **ElevenLabs Flash v2.5** |
| LLM | **LLM de JARVIS + streaming** |
| Orquestación | **JARVIS Core** |
| Detección de voz | **VAD + turn detection** |
| Interrupciones | **Barge-in + cancelación de TTS** |
| Herramientas | **MCP / Tool Calling** |
| Memoria | **JARVIS Core** |
| Transporte realtime | **WebSocket / conexión persistente** |
| API de ElevenLabs | **PAYG, sin suscripción inicialmente** |

La arquitectura debe estar diseñada alrededor de **streaming y concurrencia**, no de peticiones secuenciales.

---

# 2. Arquitectura general

```text
┌──────────────────────┐
│      MICRÓFONO       │
└──────────┬───────────┘
           │ Audio
           ▼
┌──────────────────────┐
│    VAD / TURN DET.   │
└──────────┬───────────┘
           │
           ▼
┌──────────────────────┐
│ ElevenLabs Scribe    │
│     v2 Realtime      │
│        STT           │
└──────────┬───────────┘
           │ Transcript
           ▼
┌────────────────────────────────┐
│          JARVIS CORE           │
│                                │
│  • Conversación                │
│  • Memoria                     │
│  • Contexto                    │
│  • MCP                         │
│  • Tool Calling                │
│  • Estado                      │
│  • Interrupciones              │
└──────────────┬─────────────────┘
               │
               ▼
┌──────────────────────┐
│          LLM         │
│    Token Streaming   │
└──────────┬───────────┘
           │ Tokens
           ▼
┌──────────────────────┐
│     TEXT CHUNKER     │
│   ~40–100 chars      │
└──────────┬───────────┘
           │
           ▼
┌──────────────────────┐
│ ElevenLabs Flash     │
│       v2.5 TTS       │
│      Streaming       │
└──────────┬───────────┘
           │ Audio chunks
           ▼
┌──────────────────────┐
│       ALTAVOZ        │
└──────────────────────┘
```

---

# 3. Principio fundamental: streaming

No implementar:

```text
Usuario
  ↓
STT completo
  ↓
LLM completo
  ↓
TTS completo
  ↓
Reproducir
```

Esto obliga al usuario a esperar a que todas las etapas terminen.

La arquitectura correcta es:

```text
Usuario habla
      ↓
STT streaming
      ↓
LLM empieza a generar
      ↓
Primeros tokens
      ↓
Primer chunk
      ↓
TTS empieza a generar
      ↓
JARVIS empieza a hablar
      ↓
LLM continúa generando
```

Mientras JARVIS reproduce una parte, el LLM puede estar generando la siguiente.

El resultado es una reducción importante de la **latencia percibida**.

---

# 4. Speech-to-Text — ElevenLabs Scribe v2 Realtime

Scribe convierte el audio del micrófono en texto en tiempo real.

```text
Microphone
    ↓
Audio stream
    ↓
Scribe v2 Realtime
    ↓
Partial transcript
    ↓
Final transcript
    ↓
JARVIS Core
```

Hay que distinguir:

- **Partial transcript:** transcripción provisional.
- **Final transcript:** texto confirmado.

No se debe llamar al LLM cada vez que cambia el partial transcript.

El sistema debe esperar a que el turno del usuario se considere terminado.

---

# 5. VAD y turn detection

## VAD

VAD significa **Voice Activity Detection** y determina si existe voz.

```text
Audio
  ↓
¿Hay voz?
 ├── NO → silencio
 └── SÍ → usuario hablando
```

## Turn detection

Determina cuándo el usuario ha terminado de hablar.

El objetivo es encontrar un equilibrio entre:

- Latencia.
- Naturalidad.
- Precisión.

Un timeout demasiado grande hace que JARVIS parezca lento; uno demasiado pequeño puede cortar frases.

---

# 6. JARVIS Core

JARVIS Core es la pieza central de la arquitectura.

Debe encargarse de:

### Conversación

- Historial.
- Contexto.
- Turnos.
- Estado de la conversación.

### Memoria

- Memoria de corto plazo.
- Memoria persistente.
- Recuperación de información relevante.

### LLM

- Construcción del contexto.
- Envío de prompts.
- Recepción de tokens.
- Gestión del streaming.

### Herramientas

- MCP.
- Tool calling.
- Ejecución de acciones.
- Gestión de resultados.

### Voz

- Recepción de transcripciones.
- Text chunking.
- Envío al TTS.
- Gestión de audio.
- Interrupciones.

---

# 7. Máquina de estados

JARVIS debería tener un estado explícito:

```text
IDLE
LISTENING
THINKING
SPEAKING
INTERRUPTED
EXECUTING_TOOL
```

Flujo:

```text
             ┌─────────────┐
             │    IDLE     │
             └──────┬──────┘
                    │ voz
                    ▼
             ┌─────────────┐
             │  LISTENING  │
             └──────┬──────┘
                    │ turno terminado
                    ▼
             ┌─────────────┐
             │  THINKING   │
             └──────┬──────┘
                    │ primer chunk
                    ▼
             ┌─────────────┐
             │  SPEAKING   │
             └──────┬──────┘
                    │
          ┌─────────┴─────────┐
          │                   │
      terminado           usuario habla
          │                   │
          ▼                   ▼
        IDLE             INTERRUPTED
                              │
                              ▼
                          LISTENING
```

---

# 8. LLM con streaming

El LLM debe utilizar streaming.

En lugar de recibir una respuesta completa:

```text
Respuesta completa
```

se reciben progresivamente tokens:

```text
"Claro,"
"Claro, puedo"
"Claro, puedo comprobarlo."
"Claro, puedo comprobarlo. Voy"
"Claro, puedo comprobarlo. Voy a..."
```

JARVIS Core procesa estos tokens conforme llegan.

No hay que enviar cada token individual al TTS.

---

# 9. Text Chunker

El Text Chunker agrupa los tokens del LLM en fragmentos adecuados para TTS.

Punto de partida:

```text
40–100 caracteres
```

Debe priorizar límites lingüísticos.

Preferible:

```text
"Claro, puedo comprobar tus reuniones de mañana."
```

que:

```text
"Claro, puedo comprobar"
```

Ejemplo:

```text
LLM:
"Claro, puedo comprobar tus reuniones de mañana.
Después puedo decirte cuáles requieren preparación."

Chunk 1:
"Claro, puedo comprobar tus reuniones de mañana."

Chunk 2:
"Después puedo decirte cuáles requieren preparación."
```

Mientras el TTS procesa el Chunk 1, el LLM puede seguir generando el Chunk 2.

---

# 10. Text-to-Speech — ElevenLabs Flash v2.5

Flash v2.5 convierte los chunks de texto en audio.

```text
Text chunk
    ↓
ElevenLabs Flash v2.5
    ↓
Audio stream
    ↓
Speaker
```

La voz buscada:

- Masculina.
- Grave.
- Calm.
- Natural.
- Segura.
- Concisa.
- Español de España.

No se busca una voz exageradamente teatral. Debe parecer un asistente inteligente.

---

# 11. Barge-in / interrupciones

JARVIS debe poder ser interrumpido.

Ejemplo:

```text
JARVIS:
"Claro, puedo buscar esa información y..."

Usuario:
"Espera."
```

Proceso:

```text
JARVIS SPEAKING
       ↓
VAD detecta voz
       ↓
USER_INTERRUPTED
       ↓
Cancelar TTS pendiente
       ↓
Detener reproducción
       ↓
Procesar nueva intervención
       ↓
LISTENING
```

No se debe esperar a que JARVIS termine la frase.

---

# 12. MCP y Tool Calling

MCP debe vivir en JARVIS Core y ser independiente de la capa de voz.

```text
Usuario
   ↓
STT
   ↓
JARVIS Core
   ↓
LLM
   ↓
¿Necesita herramienta?
   │
   ├── NO → respuesta
   │
   └── SÍ
        ↓
       MCP
        ↓
      Tool
        ↓
      Result
        ↓
       LLM
        ↓
     respuesta
        ↓
       TTS
```

Esto permite utilizar:

- Calendario.
- Correo.
- Búsqueda.
- APIs.
- Automatización.
- Sistemas propios.
- Herramientas de desarrollo.

La capa de voz no necesita saber qué herramienta está utilizando JARVIS.

---

# 13. Memoria

La memoria debe pertenecer a JARVIS Core.

```text
                 ┌──────────────┐
                 │   JARVIS     │
                 │     CORE      │
                 └──────┬───────┘
                        │
          ┌─────────────┼─────────────┐
          ▼             ▼             ▼
      Short-term    Long-term       MCP
       memory        memory         Tools
```

Antes de construir el contexto del LLM:

1. Obtener la conversación actual.
2. Recuperar memoria relevante.
3. Añadir contexto necesario.
4. Construir el prompt.
5. Ejecutar el LLM.

La voz no debe almacenar la memoria.

---

# 14. Concurrencia

Evitar:

```python
transcribe()
wait()

llm()
wait()

tts()
wait()

play()
```

La arquitectura debe permitir que las etapas se solapen:

```text
STT ──────────────────────────────►

       LLM ───────────────────────►

              TTS ────────────────►

                    AUDIO ────────►
```

Mientras:

- STT recibe audio.
- El LLM genera tokens.
- El Text Chunker agrupa texto.
- TTS genera audio.
- El reproductor reproduce audio.

todo puede ocurrir concurrentemente.

---

# 15. WebSocket

Para comunicación realtime se recomienda una conexión persistente:

```text
Client
  │
  │ WebSocket
  ▼
JARVIS Backend
  │
  ├── audio input
  ├── transcripts
  ├── state events
  ├── text chunks
  └── audio output
```

Esto evita crear una nueva petición HTTP para cada fragmento.

---

# 16. Eventos internos

El sistema debería utilizar eventos bien definidos.

### Usuario

```text
USER_SPEECH_STARTED
USER_SPEECH_PARTIAL
USER_SPEECH_FINAL
USER_SPEECH_ENDED
```

### LLM

```text
LLM_STARTED
LLM_TOKEN
LLM_CHUNK_READY
LLM_FINISHED
```

### TTS

```text
TTS_STARTED
TTS_AUDIO
TTS_FINISHED
```

### Interrupciones

```text
USER_INTERRUPTED
JARVIS_CANCELLED
```

### Herramientas

```text
TOOL_CALL_STARTED
TOOL_CALL_FINISHED
```

Esto facilita el debugging.

---

# 17. Seguridad

Las API keys nunca deben estar en el cliente.

## Incorrecto

```text
Frontend
   ↓
ELEVENLABS_API_KEY
   ↓
ElevenLabs
```

## Correcto

```text
Frontend
   ↓
JARVIS Backend
   ↓
ElevenLabs API
```

Las claves deben almacenarse mediante variables de entorno o secrets:

```env
ELEVENLABS_API_KEY=...
```

Nunca incluir una clave real en:

- Git.
- GitHub.
- Código frontend.
- Logs.
- Capturas de pantalla.
- Variables públicas del navegador.

---

# 18. Estructura recomendada

```text
jarvis/
├── core/
│   ├── conversation/
│   ├── memory/
│   ├── state/
│   └── orchestration/
│
├── llm/
│   ├── client/
│   └── streaming/
│
├── voice/
│   ├── stt/
│   │   └── elevenlabs_scribe/
│   ├── tts/
│   │   └── elevenlabs_flash/
│   ├── vad/
│   ├── turn_detection/
│   └── playback/
│
├── mcp/
│   ├── client/
│   └── tools/
│
└── api/
    └── websocket/
```

La separación permite sustituir componentes sin rehacer JARVIS entero.

---

# 19. Latencia

Métricas importantes:

- Tiempo desde que el usuario termina hasta el primer token.
- Tiempo hasta el primer audio.
- Latencia entre chunks.
- Tiempo necesario para detener JARVIS al ser interrumpido.

Evitar:

```text
LLM termina
   ↓
TTS completo
   ↓
Reproducir
```

Preferir:

```text
LLM
 │
 ├── Chunk 1 ──► TTS ──► Audio
 │
 ├── Chunk 2 ──► TTS ──► Audio
 │
 └── Chunk 3 ──► TTS ──► Audio
```

---

# 20. Costes

El planteamiento inicial es utilizar ElevenLabs mediante **PAYG**, sin contratar una suscripción.

Referencias utilizadas en el diseño original:

```text
Scribe v2 Realtime ≈ $0.39 / hora
Flash v2.5         ≈ $0.05 / 1.000 caracteres
```

Con $0.50:

```text
≈ 77 minutos de STT
```

El TTS puede terminar siendo más caro que el STT durante conversaciones largas.

Por ello hay que evitar:

- Respuestas innecesariamente largas.
- Repeticiones.
- Generar audio que nunca se reproducirá.
- Mantener TTS activo después de una interrupción.

> **Nota:** los precios de las APIs pueden cambiar. Verificar siempre los precios actuales antes del despliegue.

---

# 21. Optimización de costes

JARVIS debe ser conciso por defecto.

Una pregunta sencilla debería producir una respuesta de pocas frases salvo que el usuario pida profundidad.

Además:

```text
JARVIS speaking
      ↓
Usuario interrumpe
      ↓
Cancelar TTS
      ↓
Descartar audio pendiente
```

Esto evita generar audio que el usuario nunca escuchará.

---

# 22. Orden de implementación

## Fase 1 — STT

```text
Microphone
    ↓
Scribe Realtime
    ↓
Terminal / UI
```

Objetivo:

- Capturar audio.
- Obtener transcripción.
- Comprobar partial/final transcripts.

## Fase 2 — LLM

```text
STT
 ↓
JARVIS Core
 ↓
LLM
 ↓
Texto
```

Activar streaming.

## Fase 3 — TTS

```text
LLM
 ↓
Text Chunker
 ↓
Flash v2.5
 ↓
Speaker
```

Inicialmente sin interrupciones.

## Fase 4 — Streaming completo

```text
STT
 ↓
LLM streaming
 ↓
TTS streaming
 ↓
Audio
```

Objetivo: JARVIS empieza a hablar antes de que el LLM termine.

## Fase 5 — VAD + turn detection

Añadir detección automática de:

```text
START SPEAKING
END SPEAKING
```

## Fase 6 — Barge-in

```text
JARVIS speaking
       ↓
User speaks
       ↓
Cancel TTS
       ↓
Stop playback
       ↓
Listen
```

## Fase 7 — MCP

```text
LLM
 ↓
Tool Call
 ↓
MCP
 ↓
Tool
 ↓
Result
 ↓
LLM
 ↓
TTS
```

## Fase 8 — Memoria

Añadir:

- Memoria conversacional.
- Memoria persistente.
- Retrieval de memoria relevante.

## Fase 9 — Optimización

Medir:

- Latencia STT.
- Latencia del LLM.
- Time-to-first-audio.
- Coste por conversación.
- Tasa de interrupciones.
- Tiempo de cancelación.
- Errores de STT.
- Errores de TTS.

---

# 23. Checklist

- [ ] Crear backend de JARVIS.
- [ ] Configurar variables de entorno.
- [ ] Integrar ElevenLabs Scribe v2 Realtime.
- [ ] Capturar audio del micrófono.
- [ ] Implementar partial/final transcripts.
- [ ] Integrar el LLM.
- [ ] Activar token streaming.
- [ ] Implementar Text Chunker.
- [ ] Integrar ElevenLabs Flash v2.5.
- [ ] Implementar streaming de audio.
- [ ] Implementar reproducción incremental.
- [ ] Añadir VAD.
- [ ] Añadir turn detection.
- [ ] Implementar máquina de estados.
- [ ] Implementar barge-in.
- [ ] Implementar cancelación de TTS.
- [ ] Añadir WebSocket.
- [ ] Añadir MCP.
- [ ] Añadir memoria.
- [ ] Añadir logging.
- [ ] Medir latencia.
- [ ] Medir costes.
- [ ] Probar interrupciones.
- [ ] Probar conversaciones largas.
- [ ] Probar errores de red.
- [ ] Probar reconexión.
- [ ] Verificar que ninguna API key se expone al cliente.

---

# 24. Resultado esperado

La experiencia final debería ser:

```text
USUARIO
  │
  │ "JARVIS, ¿qué tengo mañana?"
  │
  ▼
STT
  │
  ▼
JARVIS CORE
  │
  ▼
LLM
  │
  ├──► MCP → Calendar
  │
  ▼
"Claro, mañana tienes..."
  │
  ▼
TTS
  │
  ▼
🔊 JARVIS HABLA
  │
  │ mientras el resto de la respuesta
  │ continúa generándose
  ▼
```

Y si el usuario interrumpe:

```text
JARVIS:
"Además, tienes una reunión a las..."

USUARIO:
"Espera, ¿a qué hora?"

        ↓

VAD
        ↓
INTERRUPTED
        ↓
STOP AUDIO
        ↓
CANCEL TTS
        ↓
NEW USER TURN
        ↓
LLM
        ↓
JARVIS responde
```

Ese comportamiento de **escuchar, pensar, hablar y poder ser interrumpido de forma natural** es el objetivo principal.

---

# 25. Principios de diseño

1. **Streaming en todas las etapas posibles.**
2. **No esperar a que el LLM termine para comenzar el TTS.**
3. **La voz debe poder interrumpirse.**
4. **MCP y memoria deben estar desacoplados de la capa de voz.**
5. **Las API keys nunca deben llegar al cliente.**
6. **JARVIS Core debe controlar el estado global.**
7. **Cada componente debe poder sustituirse sin rehacer todo el sistema.**
8. **Medir latencia y coste antes de optimizar.**
9. **Verificar precios y APIs actuales antes del despliegue.**
10. **Priorizar una conversación natural sobre una arquitectura innecesariamente compleja.**
