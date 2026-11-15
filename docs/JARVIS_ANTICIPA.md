# Jarvis que se anticipa

Jarvis propone lo que sueles pedir, un poco antes de que lo pidas, a partir de patrones
reales. **Nunca hace nada solo: propone y espera tu «sí».**

Estado: **fase 1 hecha** (2026-11-15). Apunta, aprende, sugiere con Sí/No, explica y borra.
La fase 2 (ejecutar sin preguntar) no existe y no se enciende con una variable.

| Qué | Dónde |
|---|---|
| La aritmética: qué es un patrón, cuánto sube un sí, cuándo toca | `backend/anticipa.py` (sin red ni reloj) |
| Las reglas: qué se puede sugerir, topes, lo irreversible | `backend/nucleo_seguridad.json` |
| El enganche: apuntar, aprender, sugerir, responder, ver y borrar | «JARVIS QUE SE ANTICIPA» en `backend/main.py` |
| Las tablas | `supabase/migrations/20261115_jarvis_anticipa.sql` |
| Las pruebas | `tests/backend/test_anticipa.py` |

---

## Qué ve Mikel

- **Una notificación con dos botones**, como mucho dos al día: «Señor, los lunes, sobre las
  9:00, suele poner «lofi» en casa. ¿Lo hago?» → *Sí, hazlo* / *No*. La frase la escribe el
  backend a partir de los argumentos guardados, no un modelo: lo que lees es lo que se hace.
- **El «sí» lo hace** y sube la confianza de ese patrón. **El «no» la baja más**, y con uno
  basta para que deje de proponerlo hasta que lo vuelvas a pedir tú unas cuantas veces.
  **No contestar no cuenta**: a los diez minutos queda como «ignorada».
- **«¿Por qué me propones esto?»** → `mis_patrones`: «Porque los lunes, sobre las 9:00, en
  casa, ha pedido poner «lofi» 4 de 5 días (80 %). Confianza 0.60; propongo a partir de 0.55.»
- **«¿Qué has aprendido de mí?»** → la misma herramienta: cada patrón con su número, y
  cuántas sugerencias has aceptado en 14 días.
- **«Olvida el segundo»** → `olvidar_patron`: borra el patrón y los apuntes que lo sostenían.
- **«Borra todo lo que has aprendido de mí»** → `borrar_anticipacion`: borra el registro y
  los patrones, **vuelve a contar** y contesta con lo que ha encontrado.

Sale por el móvil y no por la voz ni por el HUD: es el único canal que hoy tiene dos
botones. Por los altavoces de casa no se pregunta nada que alguien pueda contestar por ti.

---

## Qué se apunta

Cada herramienta que Jarvis ejecuta pasa por `_jarvis_despachar`, y de ahí sale el evento.
Se apunta **solo** lo que `nucleo_seguridad.json` declara, con los argumentos que declara:

| Herramienta | Nivel | Qué se guarda |
|---|---|---|
| `musica_poner` | bajo | qué, tipo, dispositivo |
| `tele` | bajo | solo encender, apagar y abrir una aplicación |
| `pc_abrir` | bajo | qué |
| `encender_pc`, `lanzar_streaming` | bajo | nada más |
| `casa_ordenar` | medio | solo `light`, `fan`, `climate` y `media_player`; brillo y temperatura |
| `recordarme` | medio | el texto y la hora (la fecha se pone al aceptar) |

Y de cada evento: el día y el minuto **locales**, el día de la semana, el lugar (la
categoría: casa, gimnasio, uni o fuera; nunca la zona ni coordenadas) y por dónde lo pediste.

**Lo que no se apunta**, y dónde se decide (`_anticipa_apuntar`):

- **Lo hecho en un turno que ha leído texto de otros** (un WhatsApp, un correo, una web,
  la pantalla). El chat se lo dice al despachador con `tras_ajeno`, que sale del mismo
  conjunto que usa `_ajeno_bloquea`. Es la regla «lo ajeno no enseña»: si un mensaje
  consiguiera que Jarvis pusiera música, esa música no sería una costumbre de Mikel.
- Lo que falló o quedó sin confirmar.
- Lo que lleva botón (`_jarvis_confirma`), aunque el núcleo lo nombrara por error.
- Lo que hizo el sistema solo (`sistema` no es una boca de Mikel).
- El «sí» de una sugerencia: queda como sugerencia aceptada, no como petición nueva.
- Cuando no se sabe dónde estás: «no lo sé» no se guarda como «fuera».
- Texto de conversaciones. No hay columna donde quepa.

Por teléfono el turno nunca cuenta como ajeno: allí el texto de otros no llega al modelo,
lo lee la llamada (parches 36 y 37).

---

## Cómo se aprende

Una vez al día (a partir de las 04:00, con el reloj de Home Assistant) se recalcula todo
con los últimos 42 días:

- **Un patrón** es una acción que se repite a la misma hora (una ventana de 60 minutos), en
  el mismo lugar y en el mismo tipo de día. Se prueba de lo general a lo concreto —cada
  día, entre semana, el fin de semana, un día de la semana— y se queda lo más general que
  se sostenga. «Cada día» tiene que sostenerse también el fin de semana.
- **Mínimos**: 4 días distintos (3 si es de un día concreto) y haberlo hecho al menos el
  60 % de los días que había para hacerlo desde la primera vez. Pedirlo tres veces una
  mañana cuenta como una mañana.
- **Confianza**: nace en 0,60. Un sí: `c + 0,15·(1−c)`. Un no: `c − 0,25·c`. Que lo vuelvas
  a hacer tú: `c + 0,05·(1−c)`. Sin evidencia: `c · 0,98` por día. Por debajo de 0,20 el
  patrón se borra solo. Se sugiere a partir de 0,55.

Es aritmética. Ningún modelo decide si un patrón vale, ni redacta la sugerencia.

---

## Cuándo sugiere, y cuándo calla

En cada pasada del reloj (cada 5 minutos), si un patrón es de ahora —su tipo de día, desde
15 minutos antes de su hora hasta 15 después, y estás en su lugar— y:

- no lo has pedido ya hoy ni se te ha propuesto ya hoy,
- han pasado 90 minutos desde la última sugerencia y hoy van menos de dos,
- no es de noche (`AVISOS_HORA_SILENCIO`), consta que estás despierto, no estás en clase
  (`_telefono_puede_sonar`) y el móvil está recogiendo avisos,

entonces sale una. Si no, no sale: una sugerencia no se guarda para luego ni se rescata
por correo.

El «sí» vale diez minutos. Al pulsarlo, la acción **vuelve a pasar por el núcleo**
(`_anticipa_ejecutar`): la fila vive en una tabla que la service key puede escribir, y una
fila manipulada no ejecuta nada que no esté en la lista.

---

## Las reglas que no se negocian

1. **Jarvis no amplía sus permisos.** Qué se puede sugerir está en `nucleo_seguridad.json`,
   que ninguna herramienta escribe y que el espejo de parches protege
   (`docs/JARVIS_PARCHES_ESPEJO.md`). Cambiarlo es un commit de Mikel.
2. **Nada irreversible sale de un patrón**: mensajes, llamadas, compras, cerraduras, garaje,
   cámaras y alarmas están en la lista `irreversible` del mismo fichero, y un núcleo que
   pusiera una de ellas entre lo sugerible no carga.
3. **Lo ajeno no enseña** (arriba).
4. **Nada se ejecuta solo.** `puede_ejecutar_sola` devuelve `False` diga lo que diga el
   núcleo; hay un test que lo enciende a mano y comprueba que sigue siendo `False`.
5. **Borrar es verdad.** Se vuelve a contar después de borrar, las tres tablas están fuera
   de la copia de seguridad semanal (`SIN_COPIA`) y lo único que queda es el acuse: la
   fecha y cuántos eran.

---

## Encenderlo

1. Aplicar `20261115_jarvis_anticipa` en el editor SQL de Supabase.
2. `ANTICIPA=1` en el `backend.env` de `caja`: empieza a apuntar y a aprender.
3. `ANTICIPA_SUGIERE=1`: empieza a proponer. Puede ir desde el primer día: sin patrones no
   hay nada que proponer, y tarda al menos cuatro días de costumbre en haber uno.

Sin la migración no pasa nada malo: se avisa una vez en el registro y lo pedido se hace igual.

## Cómo se mide

`mis_patrones` da la aceptación de los últimos 14 días: sí / (sí + no), con las ignoradas
aparte. El objetivo es el 60 % tras dos semanas con patrones. Si las ignoradas pasan del
40 %, lo que hay que tocar es el tope del día (en el núcleo), no la confianza.

## Lo que no hace todavía

- **El contexto del sueño y de la agenda** no se guarda: la fase 1 no lo usa para decidir.
- **El registro vive en Supabase**, como todo lo que escribe el backend, y no en jacobo:
  su enlace se cae con tráfico sostenido y un apunte no puede depender de él. Si algún día
  jacobo es estable, mudarlo es cambiar tres URL.
- **El coche** no se distingue como lugar: fuera de casa, del gimnasio y de la uni es «fuera».
- **Cadenas** («luz, luego música»): cada acción es su propio patrón.
- **Fase 2**: ejecutar sin preguntar lo de nivel bajo con confianza ≥ 0,90. Es una decisión
  de Mikel con los números de dos semanas delante, no un interruptor.

## Fuera de alcance

Compras, dinero, salud y cualquier acción que dependa de quién más está en casa.
