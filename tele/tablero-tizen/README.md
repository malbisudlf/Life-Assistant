# La app «Jarvis» de la tele de la sala

La tele (Samsung Q70, Tizen, 2020) **ignora la orden de abrir una URL** (`ed.apps.launch`,
comprobado el 2026-11-04), pero sí obedece **«abre esta aplicación»** por su REST (`POST
/api/v2/applications/<id>`, que además la enciende si está en reposo). Así que el tablero
(`#tele` del frontend) va dentro de una app de Tizen mínima: un `index.html` que salta a la
URL del tablero con su llave.

| Fichero | Qué es |
|---|---|
| `config.xml` | La app: id `JarvisTabl.Tablero`, nombre «Jarvis», permiso de internet |
| `index.html` | Salta al tablero. `__URL__` lo rellena `instalar.sh` |
| `icon.png` | El icono (el reactor, en el azul del HUD) |
| `instalar.sh` | Empaqueta, firma e instala. **En caja**, con la imagen `ghcr.io/georift/install-jellyfin-tizen` que ya se usó para Jellyfin (Tizen Studio y su certificado de desarrollo dentro) |

**La llave no está aquí**: `instalar.sh` la lee de `~/stack/backend.env` y la mete en el paquete,
que se hace en un directorio temporal y se borra.

**Instalada el 2026-11-08** (`JarvisTabl.Tablero`, 1.0.0) y comprobada: «pon el tablero» la abre y carga el tablero.

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
