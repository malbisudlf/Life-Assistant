#!/bin/bash
# ¿Lo que corre en caja es lo que hay en el repositorio? Desde el PC (o cualquier sitio con
# `ssh caja`), en la raíz de Life Assistant:
#
#   bash telefono/claude-phone/comprobar.sh
#
# Exporta caja a un directorio temporal y lo compara con telefono/claude-phone/. Sale con 0
# si coinciden y con 1 (y el diff) si no: o alguien tocó caja a mano, o falta versionar algo.
set -euo pipefail
AQUI="$(cd "$(dirname "$0")" && pwd)"
TMP=$(mktemp -d)
trap 'rm -rf "$TMP"' EXIT
ssh -o BatchMode=yes "${CAJA:-caja}" 'bash -s' < "$AQUI/exportar.sh" > "$TMP/cp.tar"
mkdir "$TMP/caja"
tar -xf "$TMP/cp.tar" -C "$TMP/caja"
if diff -ru --exclude='*.sh' --exclude=README.md --exclude=.gitattributes "$AQUI" "$TMP/caja"; then
  echo "caja y el repositorio coinciden."
else
  echo "caja y el repositorio NO coinciden (arriba, lo distinto)." >&2
  exit 1
fi
