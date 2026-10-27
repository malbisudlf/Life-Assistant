<!-- Parte de la guía del repositorio. El índice y las reglas que aplican
     SIEMPRE están en CLAUDE.md, en la raíz. -->

# Jellyfin en Jarvis

Jarvis sabe qué está viendo Mikel en Jellyfin, qué ha entrado nuevo, si una película
está en la biblioteca, y puede ponerla en la tele. Jellyfin corre en `caja`, en el
proyecto «pelis» del repositorio HomeLab (`caja/pelis/`), con el 8096 solo para la LAN y
la tailnet. El código está en la sección «Jellyfin» de `backend/main.py`; los tests, en
`tests/backend/test_jellyfin.py`.

## Lo hace Mikel

1. **La clave.** En Jellyfin (`http://<caja>:8096`, desde casa o la tailnet): *Panel de
   control → Claves de API → +*, con nombre «Life Assistant». Copia la clave.
2. **Tu id de usuario.** *Panel de control → Usuarios →* tu usuario: el id va en la URL
   (`userId=` y 32 caracteres hexadecimales). O desde `caja`:

   ```bash
   curl -s -H 'Authorization: MediaBrowser Token="<CLAVE>"' http://localhost:8096/Users
   ```

   y el `Id` de tu usuario.
3. **Comprobar que el backend llega.** El backend corre en un contenedor: ahí
   `localhost` es el contenedor, no `caja`. Desde `caja`:

   ```bash
   docker exec backend python -c "import urllib.request as u; print(u.urlopen('http://172.17.0.1:8096/System/Info/Public', timeout=5).read()[:120])"
   ```

   Si contesta con un JSON que dice `Jellyfin`, la URL es `http://172.17.0.1:8096`. Si
   no, la otra salida es añadir al servicio `backend` del `compose.yaml` de HomeLab
   `extra_hosts: ["host.docker.internal:host-gateway"]` (como ya lleva `cloudflared`) y
   usar `http://host.docker.internal:8096`.
4. **Las tres variables**, en el `.env` del backend en `caja`:

   ```
   JELLYFIN_URL=http://172.17.0.1:8096
   JELLYFIN_API_KEY=<la clave del paso 1>
   JELLYFIN_USER_ID=<tu id del paso 2>
   ```

5. **Desplegar** (botón *Desplegar* de la zona dev) y probar:
   - «¿Por dónde iba de la serie?» → `jellyfin_seguir`.
   - «¿Qué hay nuevo en Jellyfin?» → `jellyfin_novedades`.
   - Con Jellyfin abierto en la tele: «Ponme Dune en la tele» → busca, y propone con el
     botón «Poner en Jellyfin "Dune" en "tele"». Pulsar Sí y que empiece.
6. **Opcional**: las evals con los casos nuevos (`gh workflow run "Evals de Jarvis"
   --ref main`, unos céntimos), para ver que el modelo no confunde la tele de Jellyfin
   con un dispositivo de la casa.

## Las cuatro herramientas

| Herramienta | Confirma | Qué pregunta a Jellyfin |
|---|---|---|
| `jellyfin_seguir` | No | `GET /UserItems/Resume` (lo que está a medias, con por dónde ibas) y `GET /Shows/NextUp` (el capítulo siguiente de cada serie), sin repetir |
| `jellyfin_novedades` | No | `GET /Items/Latest`, agrupado, con la fecha en que entró. `tipo` = película, serie o capítulo |
| `jellyfin_buscar` | No | `GET /Items` con `searchTerm` en toda la biblioteca. Devuelve el id que pide reproducir |
| `jellyfin_reproducir` | **Sí** | `GET /Items/{id}` (que exista y que el título case), `GET /Sessions` (los clientes que este usuario puede mandar, activos en `JELLYFIN_SESION_S`) y `POST /Sessions/{id}/Playing` con `PlayNow` |

Rutas comprobadas contra la especificación OpenAPI de Jellyfin 12 (la imagen de `caja` es
la 12.1). Las de usuario van con `userId` en la query, que es la forma de las versiones
nuevas; las viejas (`/Users/{id}/Items/Resume`) no se usan.

## Lo que no se puede relajar

- **La clave va en la cabecera `Authorization`** (`MediaBrowser Client=…, Token="…"`),
  **nunca en la query**: por la URL acabaría en cualquier registro, que es justo lo que
  obligó a rotar el token de HA. Hay un test que lo mira. De un error solo se registra el
  tipo o el código, nunca el texto de la excepción (lleva la URL).
- **Sin configurar, no se anuncian** (`requiere_jellyfin`, como `requiere_moodle`): una
  herramienta que solo sabe fallar se paga por token en cada turno. `mis_capacidades` lo
  dice en «lo que no puedo», con qué falta. `JELLYFIN_USER_ID` tiene que tener forma de id
  (va a la query); si no, cuenta como sin configurar.
- **Leer es directo; reproducir, con botón.** Mirar no cambia nada; poner algo en la tele
  de otra habitación, sí.
- **Lo que dice el botón es lo que se pone.** El botón del dashboard enseña el `titulo`
  que redactó el modelo (`jarvisEtiquetaAccion`), así que al ejecutar el backend comprueba
  que ese título casa con el nombre real del elemento de ese id (`_jellyfin_cuadra`); si
  no, no pone nada y pide buscarlo otra vez. En Telegram la frase ni siquiera sale del
  modelo: la escribe el backend con los datos de Jellyfin (`describir` en el registro), y
  si el id no existe o no casa, no se propone.
- **Un Jellyfin caído se dice**: `ok: false` con el motivo («no contesta», «ha rechazado
  la clave: revisar `JELLYFIN_API_KEY`»), nunca una lista vacía que parezca «no hay nada».
- **Solo nombres, nunca sinopsis.** Los títulos vienen de metadatos de terceros —y, si
  Jellyfin no reconoce un fichero, del nombre que le puso quien subió el torrent—: van
  recortados y con `_AVISO_WEB`. La sinopsis, un párrafo entero de texto ajeno, no viaja
  al modelo.

## El teléfono

Las tres de leer **entran** en la lista blanca del teléfono (`_MCP_SERVIDOR_SOLO_LECTURA`),
con el criterio que ya tiene: se admite lo que trae poco texto ajeno y marcado como dato
(`moodle_entregas`, con lo que escribe el profesorado), y se deja fuera lo que trae
párrafos de desconocidos a una sesión con shell (`leer_documento`, la web). Aquí son
nombres cortos, sin sinopsis. `jellyfin_reproducir` entra desde el 2026-10-27 por el
camino del calendario: va al móvil con el botón «Sí, hazlo» (`PREGUNTAS_ACCIONES`) y se
puede confirmar también hablando (`PREGUNTAS_HABLADAS`), con la frase de su `describir`.

## Evals

Cinco casos nuevos en el grupo `jellyfin` de `evals/casos.json`, y el runner enciende
Jellyfin con valores de mentira para que se anuncien. El fallo previsto es confundir «la
tele» con la casa (`casa_ordenar`), y pedir un capítulo con `jellyfin_novedades` en vez de
`jellyfin_seguir`.
