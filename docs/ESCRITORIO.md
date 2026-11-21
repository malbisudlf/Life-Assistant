<!-- Parte de la guía del repositorio. El índice y las reglas que aplican
     SIEMPRE están en CLAUDE.md, en la raíz. -->

# El Jarvis de escritorio

Un reactor junto a la barra de tareas del PC: se mantiene **Ctrl + Alt izquierdos**, se
habla, se suelta y Jarvis contesta con su voz y en un bocadillo. Es el «Roamies con mi
Jarvis» que pidió Mikel el 2026-11-12: **el mismo Jarvis, otra boca**, no un segundo
asistente. La fase 1 (oír, pensar, hablar) es del 2026-11-20; las fases 2-4 (manos en otras
apps, dibujar sobre la pantalla, tutoriales) del 2026-11-21: ver «Las manos y el lienzo».

## Las piezas

| Fichero | Qué |
|---|---|
| `agent/escritorio.py` | La ventana (Tk: el reactor transparente, el bocadillo, la contraseña), el micrófono, el oído, el turno y la voz |
| `agent/escritorio_logica.py` | Lo que decide, sin ventanas: la tecla, los eventos del turno y el corte en frases. Sus tests, `tests/backend/test_escritorio.py` |
| `agent/lienzo.py` | El lienzo: marcas, tarjetas y tutoriales encima de la pantalla, dentro del mismo proceso que el reactor. Escucha a `pc_mcp.py` en 127.0.0.1 |
| `agent/lienzo_logica.py` | Lo que decide el lienzo, sin ventanas: el esquema cerrado de marcas, tarjetas y pasos, dónde va cada etiqueta sin tapar nada y cuándo avanza un tutorial. Sus tests, `tests/backend/test_lienzo.py` |
| `agent/manos.py` | Las manos finas: botones y campos por su nombre con UI Automation, y sus frenos. Sus tests, `tests/backend/test_manos.py` |
| `agent/instalar_escritorio.ps1` | Instala `requirements-escritorio.txt` en el entorno de `~/.jarvis-pc` y deja el acceso directo en Inicio |

## Cómo funciona

1. **Oír**: al pulsar se abre el micrófono (PCM a 16 kHz) y un WebSocket a `/voz/oido` del
   backend, el puente al Whisper de jacobo que ya usa la llamada del navegador. Lo grabado
   antes de conectar sale primero. Al soltar, `{"tipo": "fin"}` y llega el texto. En el PC
   no corre ningún modelo (memoria «sin IA en el PC»).
2. **Pensar**: lo piensa **Claude**, como Telegram, y **retransmitido**: `/jarvis/voz` con
   `JARVIS_VOZ_MOTOR=claude` en el backend (ver «El turno retransmitido» en `docs/JARVIS.md`),
   con OpenAI de reserva si Claude no puede empezar. Va diciendo cada frase según se
   escribe, y el relleno («Miro la agenda.») mientras usa una herramienta. Lleva los
   últimos 12 turnos de esta sesión, en memoria (al cerrar se olvidan, como el chat). Lo
   que Jarvis deja propuesto se aprueba en el dashboard o en el móvil: aquí no hay botón.
3. **Hablar**: cada frase entera va a `/voz/decir` (Fish con Azure detrás) y suena por MCI
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

## Las manos y el lienzo (fases 2-4, 2026-11-21)

Lo que Roamies hace sobre la pantalla, hecho con el Jarvis de siempre: **pulsar y rellenar
por nombre, dibujar encima de lo que está mirando y enseñarle a hacer algo paso a paso**.
Se pide hablando al reactor, por Telegram o en el chat («¿dónde se cambia la fuente en
Word?», «enséñame a poner el modo oscuro», «pulsa Guardar», «ponme mi sueño encima»).

| Herramienta (backend → MCP del PC) | Qué hace | Nivel del MCP |
|---|---|---|
| `pc_elementos` → `elementos` | Los botones, campos, pestañas y menús de la ventana de delante, por su nombre | `mirar` |
| `pc_pulsar` → `pulsar` | Pulsa uno por su nombre (Invoke, Select, Toggle o Expand de UI Automation; si no tiene ninguno, un clic en su centro) | `usar` |
| `pc_rellenar` → `rellenar` | Escribe en un campo por su nombre (ValuePattern), sin pulsar Intro | `usar` |
| `pc_dibujar` → `dibujar` | Anillos que laten, cajas y flechas con etiqueta alrededor de un botón; tarjetas con líneas, barras o una serie | `usar` |
| `pc_tutorial` → `tutorial` | Hasta 12 pasos: rodea el botón, lo dice con la voz de Jarvis, espera a que lo pulse; el reactor vuela junto al paso. Esc lo corta | `usar` |

**Por nombre y no por coordenadas.** El modelo que mira las capturas (`pc_pantalla`) las
describe en texto y no da coordenadas fiables, y una ventana se mueve. UI Automation (la
accesibilidad de Windows, con `comtypes`) da el botón «Guardar» esté donde esté: 135
elementos de un Edge con YouTube en 0,26 s, también en la pantalla 4K al 125 %.

**Los frenos viven en el PC**, donde ningún modelo los salta:

- **Lo irreversible no se pulsa** (`manos.es_irreversible`): enviar, comprar, pagar,
  borrar, publicar, transferir, firmar, suscribirse, desinstalar… en español e inglés.
  «Aceptar» no está: cierra mil diálogos inofensivos al día, y la orden peligrosa es la que
  lo precede. Lo que no se pulsa se SEÑALA con `pc_dibujar`, y lo pulsa él.
- **Las contraseñas no se rellenan** (campos `IsPassword`).
- **Lo ajeno**, en el backend como siempre: los nombres de los botones los pone cada web,
  así que `pc_elementos` es de `_HERRAMIENTAS_AJENAS`. Tras leerlos se puede dibujar y
  guiar (solo pintan), pero pulsar y rellenar solo si él lo pide en su mensaje
  (`_AJENO_SI_LO_PIDES`): rellenar es por donde saldría lo leído a un formulario ajeno.

`pulsar` y `rellenar` son de nivel `usar` y no `total` porque no son teclado ni ratón
libres: solo lo que tiene nombre en la ventana de delante, sin lo irreversible. El
teléfono no las ve (no hay pantalla delante en el coche).

**El lienzo es una ventana que deja pasar los clics** (`WS_EX_TRANSPARENT`, además de
`NOACTIVATE`: nunca roba el foco), del tamaño justo de lo que enseña y solo mientras lo
enseña. Las etiquetas se colocan sin tapar ningún botón marcado ni otra etiqueta
(`lienzo_logica.colocar`). `pc_mcp.py` le habla por 127.0.0.1 con el puerto y un token
aleatorio que el reactor deja al arrancar en `~/.jarvis-pc/lienzo.json`; si el reactor no
está abierto, lo arranca y espera a ese fichero.

**Píxeles físicos (per-monitor v2).** El reactor era «system aware», y con la segunda
pantalla al 125 % las marcas habrían caído desplazadas: los rectángulos de UI Automation son
físicos. Ahora el proceso entero es per-monitor v2; en la pantalla al 125 % el reactor se ve
un poco más pequeño, que es el precio.

**Un tutorial no espera a que acabe**: la herramienta vuelve enseguida («en marcha») y el
lienzo lo lleva solo. En cada paso busca el botón cada 0,6 s hasta 12 s (el diálogo que
abre el paso anterior tarda) y luego cada 1,5 s mientras dure, por si la ventana se mueve.
Si no lo encuentra, deja el texto junto al reactor y vale cualquier clic. Un paso «mira»
sigue 1,5 s después de decirse. Un paso sin hacer en 3 minutos se abandona. Esc, en
cualquier sitio, lo corta.

**Probado el 2026-11-21** en el PC de Mikel con una ventana de prueba (WinForms) y un reactor
de pruebas sin voz: `elementos`, `pulsar` (botón y casilla), `rellenar`, el freno con
«Enviar», marcas y tarjeta capturadas con `CopyFromScreen`, y un tutorial de tres pasos
avanzado con clics de verdad que atravesaron el lienzo.

