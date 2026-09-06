#!/usr/bin/env bash
# Arranque del add-on: convierte las opciones y el fichero de entorno en
# variables, y cede el proceso a uvicorn.
set -euo pipefail

OPCIONES=/data/options.json
FICHERO_ENV=$(jq -r '.fichero_env // "/homeassistant/life_assistant.env"' "$OPCIONES")
NIVEL_LOG=$(jq -r '.nivel_log // "info"' "$OPCIONES")

if [ ! -f "$FICHERO_ENV" ]; then
  echo "FATAL: no encuentro $FICHERO_ENV." >&2
  echo "Copialo con Samba desde ~/.life-assistant/backend.env.produccion." >&2
  echo "Sin el, faltan SECRET_KEY y DASHBOARD_PASSWORD y el backend no arranca." >&2
  exit 1
fi

# `set -a` exporta todo lo que se defina a continuacion. El fichero se lee con
# `.` en vez de parsearlo a mano para que la clave PEM multilinea de Enable
# Banking, que va entrecomillada, sobreviva entera.
set -a
# shellcheck disable=SC1090
. "$FICHERO_ENV"
set +a

# Un aviso temprano vale mas que un stack trace: el backend lanza RuntimeError
# al importar si faltan, pero ese error se lee peor que esta linea.
for critica in SECRET_KEY DASHBOARD_PASSWORD; do
  if [ -z "${!critica:-}" ]; then
    echo "FATAL: falta $critica en $FICHERO_ENV." >&2
    exit 1
  fi
done

echo "Life Assistant: arrancando en el puerto 8080 (log: $NIVEL_LOG)"
cd /app
exec uvicorn main:app --host 0.0.0.0 --port 8080 --log-level "$NIVEL_LOG"
