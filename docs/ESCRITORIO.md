<!-- Parte de la guía del repositorio. El índice y las reglas que aplican
     SIEMPRE están en CLAUDE.md, en la raíz. -->

# El Jarvis de escritorio

Un reactor junto a la barra de tareas del PC: se mantiene **Ctrl + Alt izquierdos**, se
habla, se suelta y Jarvis contesta con su voz y en un bocadillo. Es la fase 1 del «Roamies
con mi Jarvis» que pidió Mikel el 2026-11-12: **el mismo Jarvis, otra boca**, no un segundo
asistente. Las fases siguientes (manos en otras apps, dibujar sobre la pantalla, tutoriales)
están en la memoria del proyecto y sin empezar.

## Las piezas

| Fichero | Qué |
|---|---|
| `agent/escritorio.py` | La ventana (Tk: el reactor transparente, el bocadillo, la contraseña), el micrófono, el oído, el turno y la voz |
| `agent/escritorio_logica.py` | Lo que decide, sin ventanas: la tecla, los eventos del turno y el corte en frases. Sus tests, `tests/backend/test_escritorio.py` |
| `agent/instalar_escritorio.ps1` | Instala `requirements-escritorio.txt` en el entorno de `~/.jarvis-pc` y deja el acceso directo en Inicio |

## Cómo funciona

1. **Oír**: al pulsar se abre el micrófono (PCM a 16 kHz) y un WebSocket a `/voz/oido` del
   backend, el puente al Whisper de jacobo que ya usa la llamada del navegador. Lo grabado
   antes de conectar sale primero. Al soltar, `{"tipo": "fin"}` y llega el texto. En el PC
   no corre ningún modelo (memoria «sin IA en el PC»).
2. **Pensar**: lo piensa **Claude**, como las notas de voz de Telegram: `/jarvis` con
   `voz: true` y `pensar_con_claude: true` (el prompt de voz, de una pieza). Si Claude no
   contesta, el backend tira de OpenAI y el bocadillo lo dice. Lleva los últimos 12 turnos
   de esta sesión, en memoria (al cerrar se olvidan, como el chat). Hasta el 2026-11-20 iba
   por `/jarvis/voz`, que retransmite pero piensa siempre OpenAI; Mikel lo quiere por Claude
   y por jacobo, como Telegram. Lo que Jarvis deja propuesto se aprueba en el dashboard o
   en el móvil: aquí no hay botón.
3. **Hablar**: la respuesta, frase a frase, va a `/voz/decir` (Fish con Azure detrás) y suena por MCI
   de Windows. La siguiente se pide mientras suena la anterior.

Ningún endpoint nuevo: funciona con el backend tal como está.

**Solo aparece al hablarle** (2026-11-20, a petición de Mikel): en reposo el reactor se
oculta y no se dibuja (no gasta nada; despierto, unos 65 MB y menos del 0,1 % de CPU). Ctrl +
Alt lo trae, y se queda mientras oye, piensa, habla o enseña la respuesta. «Dejarlo siempre a
la vista», en el menú del botón derecho (con él a la vista), lo fija (`siempre_visible` en
`escritorio.json`). La regla, en `debe_verse` de `escritorio_logica.py`.

**«Se ha roto el turno» el día que se estrenó** no era de aquí: el backend mandaba 139
herramientas a OpenAI, que admite 128, y todos los turnos por OpenAI fallaban. Ver
`_esquema_openai` en `backend/main.py`.

## Lo que no se puede relajar

- **AltGr no cuenta.** Para Windows es Ctrl + Alt, y con ella se escribe la @. Y si
  mientras se mantiene se pulsa otra tecla, era un atajo (Ctrl + Alt + Supr): se cancela y no
  se vuelve a armar hasta soltar. Por debajo de 0,25 s, también se cancela.
- **La sesión es la del dashboard**, con su contraseña escrita por él en la ventanita (no se
  guarda) y el JWT de 30 días en `~/.jarvis-pc/escritorio.json`, fuera de OneDrive. Cuando
  caduca, el reactor se pone gris y la vuelve a pedir: nada se queda mudo sin decirlo.
- **El micrófono solo está abierto mientras se habla.** Dejarlo abierto ahorraría unas
  décimas al empezar, pero Windows enseñaría el micro en uso todo el día.

## Ponerlo en marcha

```powershell
powershell -ExecutionPolicy Bypass -File agent\instalar_escritorio.ps1
```

y arrancarlo (o reiniciar). La dirección del backend la toma de `LA_API_BASE` en
`agent/.env` (o `JARVIS_BACKEND` en `~/.jarvis-pc/escritorio.env`). El registro, sin
contenido de las conversaciones, en `~/.jarvis-pc/escritorio.log`.

Para probarlo sin tocar la sesión de verdad: `JARVIS_ESCRITORIO_DIR` apunta a otra carpeta
y `JARVIS_BACKEND` a un backend de mentira. Así se probó el 2026-11-20: Ctrl + Alt
inyectados con `keybd_event`, y llegaron el audio, la frase, el turno y las dos frases a la
voz.

**Ojo al capturar la pantalla**: el reactor y el bocadillo son ventanas con transparencia y
`pc_pantalla` (mss) no las ve. Una captura con `CopyFromScreen` sí.
