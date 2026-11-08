#!/bin/bash
# Exporta lo que corre de claude-phone en caja, tal cual, para versionarlo en
# telefono/claude-phone/ (ver su README.md). Se ejecuta EN caja y escribe un .tar en
# la salida estándar:
#
#   ssh caja 'bash -s' < telefono/claude-phone/exportar.sh > /tmp/cp.tar
#   tar -xf /tmp/cp.tar -C telefono/claude-phone
#
# Lo que sale:
#   BASE            commit del repositorio original sobre el que van los cambios
#   cambios.diff    `git diff` de los ficheros del original que están tocados
#   nuevos/         los ficheros nuestros (módulos y tests), con su ruta
#   compose.yml     ~/.claude-phone/docker-compose.yml (parches 13 y 33), con la IP de
#                   la LAN cambiada por ${EXTERNAL_IP}: el repositorio es público
#
# Lo que NO sale, a propósito: los .bak-*, audio/, config/frases-fijas/ (se regeneran),
# config/devices.json y config/tele-token.json (credenciales), .env, node_modules y la
# copia vieja voice-app.antes-p32/.
set -euo pipefail
RAIZ="${CLAUDE_PHONE_DIR:-$HOME/.claude-phone-cli}"
COMPOSE="${CLAUDE_PHONE_COMPOSE:-$HOME/.claude-phone/docker-compose.yml}"
SAL=$(mktemp -d)
trap 'rm -rf "$SAL"' EXIT
cd "$RAIZ"

git rev-parse HEAD > "$SAL/BASE"
git diff HEAD -- . ':(exclude)*.bak-*' > "$SAL/cambios.diff"

mkdir -p "$SAL/nuevos"
git ls-files --others --exclude-standard \
  | grep -Ev '\.bak-|(^|/)node_modules/|/audio/|^voice-app\.antes-|/config/frases-fijas/|/config/tele-token\.json$|^parche-[0-9]+\.diff$|\.(wav|mp3)$|(^|/)\.env' \
  | while read -r f; do
      mkdir -p "$SAL/nuevos/$(dirname "$f")"
      cp -p "$f" "$SAL/nuevos/$f"
    done

if [ -f "$COMPOSE" ]; then
  ip=$(grep -oP 'EXTERNAL_IP=\K[0-9.]+' "$COMPOSE" | head -1 || true)
  if [ -n "$ip" ]; then
    sed "s/${ip//./\\.}/\${EXTERNAL_IP}/g" "$COMPOSE" > "$SAL/compose.yml"
  else
    cp "$COMPOSE" "$SAL/compose.yml"
  fi
  sed -i "s#$HOME#\${HOME}#g" "$SAL/compose.yml"
fi

# Última barrera: si algo parece una IP privada, un token o una ruta de usuario, no sale.
if grep -rIlE '192\.168\.[0-9]+\.[0-9]+|100\.(6[4-9]|[7-9][0-9]|1[01][0-9]|12[0-7])\.[0-9]+\.[0-9]+|/home/[a-z]|sk-[A-Za-z0-9]{20}' "$SAL" >&2; then
  echo "exportar.sh: hay datos personales en lo de arriba; no exporto nada" >&2
  exit 1
fi

tar -C "$SAL" -cf - .
