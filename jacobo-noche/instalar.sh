#!/bin/bash
# Instala jacobo de noche en jacobo. Se ejecuta allí, con sudo, desde esta carpeta:
#   sudo bash instalar.sh
# La llave no va en el repositorio: si junto a este script hay un `jacobo-noche.env` (con
# JACOBO_NOCHE_URL, JACOBO_NOCHE_TOKEN y JACOBO_NOCHE_IFACE), se mueve a /etc/jacobo-noche.env
# como root y con chmod 600. Sin él, el temporizador corre y no hace nada.
set -euo pipefail
cd "$(dirname "$0")"
[ "$(id -u)" = 0 ] || { echo "con sudo" >&2; exit 1; }
install -m 755 jacobo-noche /usr/local/sbin/jacobo-noche
install -m 644 jacobo-noche.service jacobo-noche.timer /etc/systemd/system/
if [ -f jacobo-noche.env ]; then
  install -m 600 -o root -g root jacobo-noche.env /etc/jacobo-noche.env
  rm -f jacobo-noche.env
fi
systemctl daemon-reload
systemctl enable --now jacobo-noche.timer
[ -f /etc/jacobo-noche.env ] || echo "Aviso: falta /etc/jacobo-noche.env (URL y llave)."
systemctl list-timers jacobo-noche.timer --no-pager
