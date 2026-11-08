#!/bin/bash
# Empaqueta e instala la app «Jarvis» (el tablero) en la tele de la sala. EN caja, con la tele
# ENCENDIDA y en modo desarrollador con «Host PC IP» = caja (como se instaló Jellyfin, ver
# docs/JELLYFIN.md y la memoria de las pelis). Usa la imagen que ya está en caja para eso:
#
#   bash tele/tablero-tizen/instalar.sh            # empaqueta y la instala
#   bash tele/tablero-tizen/instalar.sh --solo-wgt # solo empaqueta (para mirar que firma)
#
# La URL (con la llave del tablero) sale de ~/stack/backend.env y se mete en el index.html del
# paquete, que se hace en un directorio temporal y se borra: la llave no queda en el
# repositorio ni en el disco, solo en la app instalada.
set -euo pipefail
AQUI="$(cd "$(dirname "$0")" && pwd)"
IMAGEN="${IMAGEN_TIZEN:-ghcr.io/georift/install-jellyfin-tizen:latest}"
API="${API_URL:-https://api.lifeassistantbackend.bid}"
TELE="${TELE_IP:-$(grep -E '^TELE_IP=' "$HOME/.claude-phone/.env" | cut -d= -f2-)}"
LLAVE="$(grep -E '^TELE_TABLERO_TOKEN=' "$HOME/stack/backend.env" | cut -d= -f2-)"
[ -n "$LLAVE" ] || { echo "instalar.sh: falta TELE_TABLERO_TOKEN en ~/stack/backend.env" >&2; exit 1; }
[ -n "$TELE" ] || { echo "instalar.sh: falta TELE_IP" >&2; exit 1; }

TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT
mkdir "$TMP/app" "$TMP/salida"
cp "$AQUI/config.xml" "$AQUI/icon.png" "$TMP/app/"
# El tablero lo pinta la propia app (ver la cabecera de index.html): solo le falta a quién
# preguntar y con qué llave.
sed -e "s#__API__#${API}#" -e "s#__LLAVE__#${LLAVE}#" "$AQUI/index.html" > "$TMP/app/index.html"
chmod -R a+rwX "$TMP"

docker run --rm --network host -v "$TMP:/trabajo" --entrypoint bash "$IMAGEN" -c '
  set -e
  cd /trabajo/app
  tizen package -t wgt -o /trabajo/salida -- /trabajo/app >/dev/null
  ls /trabajo/salida
  if [ "$1" = "--solo-wgt" ]; then exit 0; fi
  sdb connect "$2" >/dev/null
  NOMBRE=$(sdb devices | grep -E "device\s+\w+[-]?\w+" -o | sed "s/device//" | xargs)
  [ -n "$NOMBRE" ] || { echo "No veo la tele por sdb: ¿encendida y en modo desarrollador?"; exit 1; }
  tizen install -n /trabajo/salida/*.wgt -t "$NOMBRE"
' _ "${1:-}" "$TELE"
