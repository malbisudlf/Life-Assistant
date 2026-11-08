# La app «Jarvis» de la tele de la sala

La tele (Samsung Q70, Tizen, 2020) **ignora la orden de abrir una URL** (`ed.apps.launch`,
comprobado el 2026-11-04), pero sí obedece **«abre esta aplicación»** por su REST (`POST
/api/v2/applications/<id>`, que además la enciende si está en reposo). Así que el tablero
(`#tele` del frontend) va dentro de una app de Tizen mínima: un `index.html` que salta a la
URL del tablero con su llave.

| Fichero | Qué es |
|---|---|
| `config.xml` | La app: id `JarvisTabl.Tablero`, nombre «Jarvis», permiso de internet |
| `index.html` | **El tablero entero**, en JavaScript ES5 y CSS sin nada posterior a 2018, que pide `GET /tele/tablero` él mismo. `__API__` y `__LLAVE__` los rellena `instalar.sh`. Atrás cierra la app |
| `icon.png` | El icono (el reactor, en el azul del HUD) |
| `instalar.sh` | Empaqueta, firma e instala. **En caja**, con la imagen `ghcr.io/georift/install-jellyfin-tizen` que ya se usó para Jellyfin (Tizen Studio y su certificado de desarrollo dentro) |

**La llave no está aquí**: `instalar.sh` la lee de `~/stack/backend.env` y la mete en el paquete,
que se hace en un directorio temporal y se borra.

**La 1.0.0 (2026-11-08) se quedó en negro y el mando sin respuesta**: saltaba al frontend de Vercel, que es la app web entera (500 KB de React, CSS con `inset` y `gap`), en el navegador de una tele de 2020; y fuera de la app la tecla Atrás no tenía quién la atendiera. Se cerró desde caja (`DELETE /api/v2/applications/JarvisTabl.Tablero`, que es lo que hay que hacer si se vuelve a colgar). Desde la 1.0.1 el tablero va dentro de la app y el backend le contesta desde cualquier origen solo en esa ruta (`_CorsDelTablero`).

## Instalar (con la tele encendida)

La tele tiene que estar en **modo desarrollador con «Host PC IP» = caja** (se puso el
2026-10-26 para Jellyfin; si caducó, Apps → 12345 con el mando → activarlo y reiniciarla).

```bash
cd ~/stack/Life-Assistant && bash tele/tablero-tizen/instalar.sh
```

Si cambia la llave del tablero, hay que reinstalarla.

## Abrirla

- Por teléfono: «pon el tablero» / «enciende la tele y pon el tablero» (reflejo, sin Claude;
  parche 40 de claude-phone, `jarvis` en `APPS_CONOCIDAS`).
- Desde el chat o el backend: la herramienta `tele` con abrir «tablero».
- Por la mañana, sola: falta la presencia en el salón (Bluetooth del Green; ver «El tablero de
  la tele» en `docs/JARVIS.md`).
