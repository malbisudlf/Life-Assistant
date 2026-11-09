<!-- Parte de la guía del repositorio. El índice y las reglas que aplican
     SIEMPRE están en CLAUDE.md, en la raíz. -->

# Las pelis en Jarvis: Radarr y Prowlarr

Jarvis pide películas a Radarr, dice cómo van las descargas, las borra, y mira y arregla
los indexadores de Prowlarr (las webs de donde salen los torrents). Lo que ya se puede ver
es cosa de Jellyfin (`docs/JELLYFIN.md`); esto es lo de antes: pedirla y que baje. Radarr y
Prowlarr corren en `caja`, en el proyecto «pelis» del repositorio HomeLab (`caja/pelis/`),
**dentro de la red de la VPN** (gluetun), que publica sus webs en el 7878 y el 9696 solo
para la LAN y la tailnet. El código está en la sección «Pelis» de `backend/main.py`; los
tests, en `tests/backend/test_pelis.py`.

## Lo hace Mikel

1. **Las dos claves.** En `caja`, en `~/docker/pelis/radarr/config.xml` y
   `~/docker/pelis/prowlarr/config.xml`, la etiqueta `<ApiKey>`. O en cada web: *Settings →
   General → API Key*.
2. **Comprobar que el backend llega.** Como con Jellyfin, `localhost` en el contenedor es
   el contenedor. Desde `caja`:

   ```bash
   docker exec backend python -c "import urllib.request as u; print(u.urlopen('http://172.17.0.1:7878/ping', timeout=5).read())"
   ```

   Tiene que decir `"status": "OK"` (y lo mismo con el 9696). Comprobado el 2026-10-26.
3. **Las variables**, en el `.env` del backend en `caja`:

   ```
   RADARR_URL=http://172.17.0.1:7878
   RADARR_API_KEY=<la de Radarr>
   RADARR_PERFIL=<el perfil de calidad con el que se piden, por su nombre>
   RADARR_PERFIL_4K=Solo 4K   # el de «en 4K»; ese es el valor por defecto
   PROWLARR_URL=http://172.17.0.1:9696
   PROWLARR_API_KEY=<la de Prowlarr>
   ```

   `RADARR_PERFIL` no tiene valor por defecto a propósito: el primero de la lista de Radarr
   («Any») acepta hasta grabaciones de cine. En `caja` es el que crea `configurar-arr.py`.
4. **Desplegar** y probar:
   - «¿Cómo van las descargas?» → `pelis_descargas`.
   - «Bájame Interstellar» → `pelis_buscar` y el botón «Pedir a Radarr Interstellar (2014)».
   - «¿Funcionan los indexadores?» → `indexadores_estado`, y si hace falta
     `indexadores_probar`.

## Las herramientas

| Herramienta | Confirma | Qué hace |
|---|---|---|
| `pelis_buscar` | No | `GET /movie/lookup` (TMDB a través de Radarr): título, original, año y `tmdb_id`. Si alguna ya está en Radarr, `GET /movie` para decir si está descargada, pedida o borrada; de la descargada, su resolución (`4K`, `1080p`), calidad, píxeles, HDR y tamaño, y `buscando_4k` si espera su 4K |
| `pelis_pedir` | No (desde el 2026-11-08) | Nueva: `POST /movie` con el perfil de `RADARR_PERFIL` (o `RADARR_PERFIL_4K` con `en_4k`), la primera carpeta raíz y `searchForMovie`. Ya en Radarr sin fichero: la vuelve a vigilar (`PUT /movie/{id}`) y la busca (`MoviesSearch`), sin añadirla dos veces. Ya descargada: no toca nada, salvo que se pida `en_4k` y la que tiene sea de menos: entonces pasa al perfil 4K y se busca, y Radarr cambia el fichero al encontrarla |
| `pelis_versiones` | No | `GET /release?movieId=` (la búsqueda manual de Radarr, hasta `ARR_PRUEBA_TIMEOUT`): cuántas versiones hay por resolución, cuántas se pueden bajar (sin contar los rechazos que solo son del perfil o del fichero que ya hay) y semillas y tamaño de la mejor. Sin nombres de torrent. Solo de películas que ya están en Radarr |
| `pelis_descargas` | No | `GET /queue` (porcentaje, minutos, calidad y avisos), lo vigilado sin fichero que no está en la cola («pedidas sin encontrar»), las que esperan su 4K (`esperando_su_4k`) y el espacio libre de la carpeta |
| `pelis_borrar` | **Sí** | Cancela lo que tenga a medias (`DELETE /queue/{id}` quitándolo de qBittorrent), borra el fichero (`DELETE /moviefile/{id}`) y la deja de vigilar. **La película se queda en Radarr**, ver abajo |
| `indexadores_estado` | No | Prowlarr: los indexadores, si están activos y si pasan por FlareSolverr, y los avisos de su última comprobación; y los avisos de Radarr. No prueba nada |
| `indexadores_probar` | No | `POST /indexer/test` (uno) o `/indexer/testall` (todos: 77 s con trece el 2026-10-26) |
| `indexadores_flaresolverr` | No | Al indexador que Cloudflare bloquea le pone la etiqueta del proxy FlareSolverr (`PUT /indexer/{id}?forceSave=true`) y lo vuelve a probar |

## En 4K (2026-11-09)

Mortadelo bajó en 1080p y Jarvis no sabía decir en qué resolución estaba ni pedirla en 4K.
El perfil de siempre («4K o 1080p») coge la mejor que haya **al buscar** y no mejora luego:
una película se baja una vez. Para «en 4K» hay un segundo perfil, `Solo 4K` (WEB 2160p y
Bluray-2160p, sin remux; corte en WEB 2160p y **con** mejoras), que crea
`configurar-arr.py` en jacobo y que ese script no devuelve al de siempre. Las mejoras son
lo que deja a Radarr cambiar la de 1080p por la 4K; el corte en la primera 4K, lo que
impide que luego cambie una 4K por otra. La de 1080p no se borra al pedir: sigue en
Jellyfin hasta que llega la 4K. Si no hay ninguna 4K (`pelis_versiones` lo dice antes),
Radarr la sigue esperando por RSS, y `pelis_descargas` la cuenta en `esperando_su_4k`.

## Lo que no se puede relajar

- **La clave va en la cabecera `X-Api-Key`, nunca en la query**, por lo mismo que la de
  Jellyfin y la de HA. Hay un test que lo mira. De un error solo se registra el tipo o el
  código, nunca el texto de la excepción (lleva la URL).
- **Sin configurar, no se anuncian** (`requiere_radarr`, `requiere_prowlarr`), y
  `mis_capacidades` lo dice en «lo que no puedo».
- **Mirar es directo; pedir y borrar, con botón.** Pedir baja decenas de GB por la VPN, y
  borrar quita el fichero sin papelera. Probar y pasar por FlareSolverr no tocan nada de
  Mikel, solo la configuración de un indexador: directas.
- **Lo que dice el botón es lo que se hace.** Pedir y borrar comprueban que el `titulo` que
  redactó el modelo casa con la película de ese `tmdb_id` (el título en español o el
  original, `_peli_cuadra`); si no, no hacen nada. En Telegram la frase la escribe el
  backend con los datos de Radarr (`describir`).
- **Borrar no quita la película de Radarr.** Es lo mismo que borrarla desde Jellyfin
  (`caja/pelis/INSTALAR.md`, paso 8): fuera el fichero y deja de vigilarla. Así sigue
  constando como «borrada» (`pelis_buscar`), y pedirla otra vez la reutiliza en vez de
  añadirla dos veces. Hay un test que exige que no haya `DELETE /movie`.
- **El torrent no lo quita el backend**: lo quita `notar-borrados.py` en `caja`, cada 10
  minutos, cuando el fichero de un torrent completo de Radarr se queda sin su gemelo de
  `pelis/` (es el mismo fichero, con un enlace duro). Mira el disco y no Radarr, así que
  vale igual se borre desde Jellyfin, desde Radarr o con Jarvis, y el backend no necesita
  la contraseña de qBittorrent.
- **El 400 de las pruebas de indexadores es la respuesta**, no un error: Prowlarr contesta
  así, con la lista de fallos, cuando alguno no funciona (`validacion=True` en `_arr`). En
  cualquier otra llamada, un 400 sigue siendo un error.
- **Solo títulos y años, nunca sinopsis**, y los avisos de una descarga y los fallos de un
  indexador recortados y con `_AVISO_WEB`: los escribe quien subió el torrent o la web del
  indexador.

## El teléfono

Las de mirar (`pelis_buscar`, `pelis_descargas`, `pelis_versiones`, `indexadores_estado`) **entran** en
`_MCP_SERVIDOR_SOLO_LECTURA`, con el criterio de Jellyfin: poco texto ajeno, recortado y
marcado como dato.

Desde el 2026-10-27 («los mismos permisos que el Jarvis de Telegram») también lo demás:

- **Pedir y borrar** van al móvil con el botón «Sí, hazlo» (`PREGUNTAS_ACCIONES`, el
  mismo camino que el calendario: «Lo que se confirma en el móvil» en `docs/JARVIS.md`).
  La frase la escribe `describir` con los datos de Radarr, igual que el botón de
  Telegram, y el «sí» ejecuta lo guardado. Las dos se pueden confirmar además hablando
  (`PREGUNTAS_HABLADAS`), porque en el coche no hay botón. **Borrar** se lleva el fichero y
  no hay papelera, y la frase que se lee antes del sí lo dice.
- **Probar y arreglar los indexadores** van sin preguntar (`_MCP_SERVIDOR_ACCIONES`),
  como en el chat. Lo que traen de cada web es el porqué del fallo, escrito por Prowlarr
  y recortado (`_prowlarr_fallo`). Tardan hasta dos minutos: su descripción le dice que
  avise antes de callarse.

## Evals

Casos en el grupo `pelis` de `evals/casos.json`. Lo que se espera que confunda: pedir una
película con `jellyfin_buscar` (que solo mira lo que ya se puede ver) o con
`buscar_en_internet`, y el estado de una descarga con `jellyfin_novedades`.
