# Las notificaciones de Jarvis

Manual de la parte que habla sola. `CLAUDE.md` explica cómo está construida; esto explica
cómo se usa y qué esperar de ella.

La idea de fondo, que justifica casi todas las decisiones raras de aquí: **un asistente
proactivo tiene un solo modo de fallo, volverse ruido.** Y no falla de golpe — falla porque
cada aviso parece razonable por separado hasta que un día dejas de leerlos todos a la vez,
buenos incluidos. Todo lo que sigue existe para que eso no pase.

---

## Por dónde te llegan

| Canal | Cuándo se usa |
|---|---|
| **Móvil** (app de Home Assistant) | Siempre que HA esté recogiendo la cola |
| **Voz** (Alexa) | Además del móvil, cuando el aviso lo pide y estás en casa |
| **Correo** | Cuando nadie recoge la cola: HA apagado, YAML sin instalar, o el aviso lleva 10 min esperando |

No hay nada que activar: **la señal es el propio sondeo**. Si HA lleva más de 5 minutos sin
pasar a recoger, se vuelve al correo solo. Y un aviso encolado que nadie recoge en 10
minutos se rescata por correo — cambiar de canal no puede perder avisos.

Hoy solo un aviso pide voz: **«sal ya»**. Es deliberado: el móvil puede estar en otra
habitación, y ese es justo el aviso que no vale leído diez minutos tarde.

---

## De qué te avisa

### Lo que miras tú
Los **recordatorios** que le pides a Jarvis («recuérdame llamar al dentista el jueves a las
10»). Estos no se gobiernan por nada de lo que viene abajo: ni tope diario, ni silenciado.
Si lo pediste tú, sale.

### Lo que decide él

| Aviso | Cuándo | Condición |
|---|---|---|
| **Sal ya** | al momento | Un evento con ubicación y el tráfico dice que toca salir |
| **No llegas** | 21:30 | Dos citas de mañana entre las que no da tiempo a moverse |
| **Mañana empiezas pronto** | 21:30 | El primer evento de mañana es antes de las 09:00 |
| **Hueco para entrenar** | 21:30 | 3+ días sin entrenar y mañana hay un rato libre |
| **Algo va mal** | 08:00 | FC en reposo ↑, HRV ↓ y respiración ↑, las tres a la vez |
| **Ponte el reloj** | ~1 h antes de dormirte | Hoy sin datos del Watch, o 2 noches sin medir |
| **Te dejaste algo encendido** | al salir de casa | Luces o enchufes encendidos según HA |
| **Resumen del día** | 19:00 | Entrega mañana, sesiones sin cobrar, racha sin entrenar |
| **Vigilancias** | cada hora | Una página que vigilas ha cambiado |
| **Del buzón** | cada 3 h | Algo accionable con fecha en el correo sin leer |
| **Averías** | cada hora | Errores repetidos, o algo que se ha reparado solo |

Y las **reglas tuyas**: las que Jarvis propone y tú apruebas con el botón de confirmar
(«los martes recuérdame X», «antes de los exámenes avísame de Y», «si mi HRV baja de 40,
dímelo»).

---

## Los botones: Útil / No

Cada aviso llega con dos botones. **En iOS hay que mantener pulsada la notificación** para
verlos; en Android salen directamente.

Son la única pieza que hace que el sistema mejore sin que nadie lo toque. Sin esa señal, la
única forma de que un aviso inútil desaparezca sería que dejaras de mirarlos todos.

- Marcar **No** tres veces seguidas en la misma regla la **silencia**.
- Un **Útil** pone el contador a cero. Se busca una regla que ha dejado de valer, no una
  que tuvo un mal día.
- **No contestar no cuenta como "no me sirvió".** El silencio no vota, ni a favor ni en
  contra.

Cuando una regla se calla, **te lo dice**, con cómo devolverla. Una regla apagada en
silencio sería exactamente el error que este sistema persigue.

---

## Por qué no te llegan veinte avisos al día

### Presupuesto
Máximo **3 avisos de regla al día**. Cuando se agota, lo que sobra **se pospone a las
08:30** del día siguiente — no se pierde.

El orden es **por prioridad, no por hora**. Con el orden por hora, un «sal ya» se habría
quedado fuera por tres avisos de la noche anterior.

### Lo urgente se salta el tope
Si el presupuesto pudiera con lo que caduca en minutos, el aviso que más corre sería el
primero en caerse. Un «sal ya» sale aunque ya hayas recibido tres.

### Lo caducado no se manda
Un «sal ya» pasada la hora de salir no es un aviso tarde: es una mentira, y enseña a no
fiarse del canal. Se descarta.

### Memoria
No repite la misma situación en 5 días. Antes, «llevas 3 días sin entrenar» salía el
jueves, el viernes y el sábado — y solo el primero informaba de algo. Si la situación
cambia (pasas a 5 días), vuelve a hablar.

---

## Dónde ver el estado

**⚙ → Avisos** te dice:

- Por dónde están saliendo ahora mismo (móvil o correo) y cuánto hace que HA los recogió.
- El **presupuesto del día**: cuántos van y cuántos caben.
- Las **reglas silenciadas**, si hay alguna.
- Un botón **«Probar aviso»**.

---

## Si algo no llega

**El punto ciego, dicho por delante:** desde el backend solo se ve que HA *recogió* el
aviso, no que llegara a tu bolsillo. Si la automatización de HA falla al mandarlo, el panel
dirá «al móvil» y no te llegará nada. Por eso el botón de prueba dice «encolado» y no
«enviado».

| Síntoma | Dónde mirar |
|---|---|
| No llega nada, ni al móvil ni al correo | ¿Sigue vivo el tick de HA? Todo cuelga de `la_brief_tick` |
| Llega al correo en vez de al móvil | HA no está recogiendo la cola: mira el sensor `life_assistant_avisos` |
| El panel dice «al móvil» y no llega | La automatización de HA o el nombre del `notify.*`. Los logs con `ha core logs`, no en `/config/home-assistant.log` |
| No salen los botones | En iOS hay que mantener pulsada la notificación |
| «Probar aviso» dice `con_botones: false` | Falta la migración `20260818_avisos_gobierno` |
| Una regla dejó de hablar | Mira las silenciadas en ⚙ → Avisos |

---

## Ajustes

Todo por variables de entorno del backend; los valores de abajo son los de fábrica.

| Variable | Def. | Qué hace |
|---|---|---|
| `AVISOS_MAX_DIA` | 3 | Avisos de regla al día |
| `AVISOS_NO_UTILES` | 3 | «No» seguidos para silenciar una regla |
| `AVISOS_REPETIR_DIAS` | 5 | Días sin repetir la misma situación |
| `AVISOS_HORA_DIFERIDOS` | 08:30 | Cuándo sale lo que ayer no entró |
| `REGLAS_PROACTIVAS` | 1 | `0` apaga todas las reglas de golpe |
| `REGLAS_HORA_NOCHE` | 21:30 | Las que miran lo de mañana |
| `REGLAS_HORA_MANANA` | 08:00 | Las que miran lo de hoy |
| `SALIR_ANTES_MIN` | 10 | Cuánto antes de salir avisa el «sal ya» |
| `SUENO_OBJETIVO_H` | 7.5 | Horas con las que calcula tu hora de dormir |
| `AVISOS_MOVIL` | 1 | `0` fuerza el correo aunque HA recoja |
| `PC_ENTIDAD` | — | Entidad de HA del PC. Vacío: esa regla no corre |

Hay una hora que **no** se configura: la del aviso del reloj. Sale de la mediana de tus
últimas noches, una hora antes de que te sueles dormir, porque ese aviso o llega antes de
dormir o no sirve de nada. `RELOJ_AVISO_HORA` solo pone el suelo, y nunca se pasa de las
23:30.

---

## Lo que este sistema no hará

- **Avisos de ánimo.** «¡Buen trabajo esta semana!» no es información, y gasta el crédito
  de atención que necesita el aviso que sí importa.
- **Decidir por su cuenta cuándo hablar.** Las condiciones están escritas en el código, no
  las juzga el modelo en cada turno. El modelo redacta lo que el código ya decidió.
- **Actuar sobre la casa por su cuenta.** Te dice que te dejaste la luz encendida; no la
  apaga. El catálogo de HA llega con hasta una hora de retraso, y apagar con un dato viejo
  es peor que preguntar.
