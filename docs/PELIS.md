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
| `pelis_buscar` | No | `GET /movie/lookup` (TMDB a través de Radarr): título, original, año y `tmdb_id`. Si alguna ya está en Radarr, `GET /movie` para decir si está descargada, pedida o borrada |
| `pelis_pedir` | **Sí** | Nueva: `POST /movie` con el perfil de `RADARR_PERFIL`, la primera carpeta raíz y `searchForMovie`. Ya en Radarr sin fichero: la vuelve a vigilar (`PUT /movie/{id}`) y la busca (`MoviesSearch`), sin añadirla dos veces. Ya descargada: no toca nada |
| `pelis_descargas` | No | `GET /queue` (porcentaje, minutos, calidad y avisos), lo vigilado sin fichero que no está en la cola («pedidas sin encontrar») y el espacio libre de la carpeta |
| `pelis_borrar` | **Sí** | Cancela lo que tenga a medias (`DELETE /queue/{id}` quitándolo de qBittorrent), borra el fichero (`DELETE /moviefile/{id}`) y la deja de vigilar. **La película se queda en Radarr**, ver abajo |
| `indexadores_estado` | No | Prowlarr: los indexadores, si están activos y si pasan por FlareSolverr, y los avisos de su última comprobación; y los avisos de Radarr. No prueba nada |
| `indexadores_probar` | No | `POST /indexer/test` (uno) o `/indexer/testall` (todos: 77 s con trece el 2026-10-26) |
| `indexadores_flaresolverr` | No | Al indexador que Cloudflare bloquea le pone la etiqueta del proxy FlareSolverr (`PUT /indexer/{id}?forceSave=true`) y lo vuelve a probar |

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
  (`caja/pelis/INSTALAR.md`, paso 8): fuera el fichero y deja de vigilarla. Si se quitara
  entera, Radarr perdería el rastro del torrent que aún se comparte —es el mismo fichero,
  con un enlace duro— y esa copia no saldría nunca de la imagen de las pelis. Hay un test
  que exige que no haya `DELETE /movie`.
- **El 400 de las pruebas de indexadores es la respuesta**, no un error: Prowlarr contesta
  así, con la lista de fallos, cuando alguno no funciona (`validacion=True` en `_arr`). En
  cualquier otra llamada, un 400 sigue siendo un error.
- **Solo títulos y años, nunca sinopsis**, y los avisos de una descarga y los fallos de un
  indexador recortados y con `_AVISO_WEB`: los escribe quien subió el torrent o la web del
  indexador.

## El teléfono

Las tres de mirar (`pelis_buscar`, `pelis_descargas`, `indexadores_estado`) **entran** en
`_MCP_SERVIDOR_SOLO_LECTURA`, con el criterio de Jellyfin: poco texto ajeno, recortado y
marcado como dato. Pedir y borrar **no**: se confirman, y por teléfono no hay botón. Probar
los indexadores tampoco: tarda un par de minutos y trae lo que contesta cada web.

## Evals

Casos en el grupo `pelis` de `evals/casos.json`. Lo que se espera que confunda: pedir una
película con `jellyfin_buscar` (que solo mira lo que ya se puede ver) o con
`buscar_en_internet`, y el estado de una descarga con `jellyfin_novedades`.
