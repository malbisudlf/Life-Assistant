#!/bin/bash
# Monta claude-phone tal como corre en caja a partir de lo versionado aquí, sin ir parche
# a parche. Se ejecuta EN caja, con el repositorio de Life Assistant clonado o copiado:
#
#   bash telefono/claude-phone/aplicar.sh /tmp/cp-nuevo     # monta en un directorio aparte
#   bash telefono/claude-phone/aplicar.sh --en-sitio         # sobre ~/.claude-phone-cli
#
# Lo normal es el primero: monta, pasa los tests y luego se compara o se copia. --en-sitio
# guarda antes una copia de cada fichero que va a pisar (*.bak-AAAAMMDD-aplicar) y NO
# reconstruye ni reinicia nada: eso sigue siendo `docker compose up -d --build voice-app`
# y matar el puente por PID (ver telefono/PARCHES.md).
set -euo pipefail
AQUI="$(cd "$(dirname "$0")" && pwd)"
BASE=$(cat "$AQUI/BASE")
ORIGEN="https://github.com/theNetworkChuck/claude-phone.git"

if [ "${1:-}" = "--en-sitio" ]; then
  DEST="${CLAUDE_PHONE_DIR:-$HOME/.claude-phone-cli}"
  cd "$DEST"
  [ "$(git rev-parse HEAD)" = "$BASE" ] || { echo "aplicar.sh: $DEST no está en BASE ($BASE)" >&2; exit 1; }
  sello=$(date +%Y%m%d)
  { git diff --name-only HEAD; (cd "$AQUI/nuevos" && find . -type f | sed 's#^\./##'); } | sort -u | while read -r f; do
    [ -f "$f" ] && cp -p "$f" "$f.bak-$sello-aplicar"
  done
  git checkout -- .
else
  DEST="${1:?uso: aplicar.sh <directorio> | --en-sitio}"
  [ -e "$DEST" ] && { echo "aplicar.sh: $DEST ya existe" >&2; exit 1; }
  git clone -q "$ORIGEN" "$DEST"
  cd "$DEST"
  git checkout -q "$BASE"
fi

git apply --whitespace=nowarn "$AQUI/cambios.diff"
cp -rp "$AQUI/nuevos/." .
echo "Montado en $DEST sobre $BASE."
echo "Falta, si es un directorio nuevo: npm ci en voice-app/ y claude-api-server/, config/devices.json,"
echo "config/tele-token.json y ~/.claude-phone/.env (no están en el repositorio)."
echo "El compose: envsubst '\$EXTERNAL_IP \$HOME' < $AQUI/compose.yml > ~/.claude-phone/docker-compose.yml"
