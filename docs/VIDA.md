<!-- Parte de la guía del repositorio. El índice y las reglas que aplican
     SIEMPRE están en CLAUDE.md, en la raíz. -->

# El buscador de la vida

«¿Qué le regalé a mi madre el año pasado?», «¿dónde cené con Ane en Bilbao?», «¿cuándo
fui al dentista por última vez?». Jarvis busca en lo que Mikel ha dicho, escrito y apuntado:
WhatsApp, correo recibido y enviado, citas pasadas del calendario e ideas. Pedido el
2026-11-20.

## Las piezas

| Dónde | Qué |
|---|---|
| `vida/indice.py` | La lógica: SQLite con FTS5, guardar por `id` estable, buscar por palabras (primero todas, luego alguna) y decir cuántos hay de cada fuente. Sin red ni modelo |
| `vida/servidor.py` | El HTTP en jacobo (`aiohttp`, puerto 8773, con llave). Su cabecera tiene la API |
| `vida/Dockerfile`, `vida/compose.yml` | Se copian a mano a `~/vida/servicio/` de jacobo |
| «El buscador de la vida» en `backend/main.py` | La herramienta `vida_buscar` y la pasada que alimenta el índice cada `VIDA_CADA_MIN` desde el tick de HA |
| `tests/backend/test_vida_indice.py`, `test_vida.py` | Los tests de cada lado |

## Por qué así

- **En jacobo, no en caja ni en Supabase.** El puente de WhatsApp olvida a los 30 días y
  este índice no, que es justo para lo que sirve. Así que el texto se queda en casa, detrás
  de su llave, y solo viaja al modelo lo que encuentra una búsqueda que ha pedido él. caja
  no carga con nada pesado (memoria «caja sin carga pesada»).
- **Sin modelo de vectores.** La pregunta la convierte en palabras Jarvis, que ya está
  pensando el turno y sabe que «regalo de mi madre» también puede ser «cumpleaños ama» o
  «perfume». La raíz de cada palabra (`raiz()`) hace que «regalé», «regalos» y «regalo» se
  encuentren entre sí. Si algún día se queda corto, el sitio para los vectores es este
  mismo servicio.
- **Lo que encuentra lo escribió cualquiera.** `vida_buscar` está en `_HERRAMIENTAS_AJENAS`:
  después de buscar, nada que dé órdenes sin que él lo pida en su mensaje. Cada resultado
  lleva quién: «TÚ» solo si lo escribió él; lo demás, entre corchetes, como en
  `whatsapp_leer`. Por teléfono no está, porque allí hay shell.
- **De WhatsApp, solo la agenda y los grupos**, como lo pendiente (`_wa_pend_pasada`): de un
  número desconocido no se guarda nada.
- **Por dónde sigue** lo dice el propio índice (`/salud`: lo más reciente de cada fuente),
  así que no hace falta otra tabla. De cada chat y del calendario, además, un cursor en
  memoria: un mes sin citas no movería «lo más reciente». Tras reiniciar se repasa con un
  día de solape, y como el `id` es estable, repetir no duplica.

## Ponerlo en marcha (lo hace Mikel o una sesión con su visto bueno)

**En marcha desde el 2026-11-20** (backend `1d29a7a`): la primera pasada metió 5.350
WhatsApp, 39 citas e ideas. El correo pasa por la misma puerta que el resto de lecturas del
buzón (`_buzon_listo`, o sea `CORREO_LEER`): encendido en caja ese mismo día, entraron 143
recibidos y 220 enviados del último año.

1. **En jacobo**: copiar `vida/` a `~/vida/servicio/`, crear `~/vida/datos` y un `.env` con
   `VIDA_TOKEN=<aleatorio>` (`chmod 600`), y `docker compose up -d --build`.
   Comprobar: `curl -H "X-Auth-Token: …" http://127.0.0.1:8773/salud`.
2. **En caja**, en `~/stack/backend.env`: `VIDA_URL=http://<ip de Tailscale de jacobo>:8773`
   y `VIDA_TOKEN`. Desplegar.
3. La primera pasada llena el último año de correo y calendario (`VIDA_DIAS_INICIO`) y lo
   que tenga el puente de WhatsApp, a trozos: el correo va de 500 en 500 por carpeta y el
   calendario de mes en mes, cada `VIDA_CADA_MIN`.
4. Probar: «¿qué le dije a Aimar del piso?».

## Listar un día

`POST /listar {desde, hasta, fuentes?, limite?}` (ISO en UTC; `hasta` no entra) devuelve lo
de un trozo de calendario por orden, con el texto recortado a 240 caracteres. Lo usa la
máquina del tiempo (`dia_reconstruir`, «¿qué hice el 3 de agosto?»; ver `docs/JARVIS.md`).

## Lo que falta

- **Fotos de iCloud** (fecha y sitio de cada foto: «¿dónde estaba el 3 de agosto?»). Pide
  su inicio de sesión de iCloud con doble factor, que hace él.
- Borrar desde Jarvis («olvida lo de tal chat»): hoy es `POST /olvidar` en jacobo.
