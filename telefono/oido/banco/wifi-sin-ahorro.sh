#!/bin/bash
# Quita el ahorro de energía del Wi-Fi USB (rtw_8822bu) de jacobo (2026-10-27): con él, el
# ping desde caja iba de 3 a 157 ms. Se lanza con: sudo bash ~/oido/wifi-sin-ahorro.sh
# Vuelta atrás: borrar los dos ficheros de /etc y reiniciar.
set -euo pipefail
apt-get install -y iw
# Al arrancar, y cada vez que aparezca la interfaz (el adaptador es USB)
cat > /etc/udev/rules.d/70-wifi-sin-ahorro.rules <<'R'
ACTION=="add", SUBSYSTEM=="net", KERNEL=="wl*", RUN+="/usr/sbin/iw dev %k set power_save off"
R
# El modo más profundo del driver, que el power_save de arriba no cubre; vale al reiniciar
echo "options rtw88_core disable_lps_deep=y" > /etc/modprobe.d/rtw88-sin-ahorro.conf
# Y ya, sin reiniciar ni cortar la conexión
for i in /sys/class/net/wl*; do iw dev "${i##*/}" set power_save off; iw dev "${i##*/}" get power_save; done
