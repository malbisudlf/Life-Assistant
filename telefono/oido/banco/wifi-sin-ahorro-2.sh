#!/bin/bash
# Arreglo de wifi-sin-ahorro.sh (2026-10-27): la regla de udev corría con el nombre del
# kernel (wlan0) antes del cambio a wlx…, e iw fallaba. Ahora va al final (99-) y recorre
# las interfaces que haya, sin depender del nombre. Reinicia para probarlo de verdad.
set -euo pipefail
rm -f /etc/udev/rules.d/70-wifi-sin-ahorro.rules
cat > /etc/udev/rules.d/99-wifi-sin-ahorro.rules <<'R'
ACTION=="add", SUBSYSTEM=="net", ENV{DEVTYPE}=="wlan", RUN+="/bin/sh -c 'for i in /sys/class/net/wl*; do /usr/sbin/iw dev $${i##*/} set power_save off; done'"
R
udevadm control --reload
echo "Regla puesta. Reinicio en 5 s."
sleep 5
systemctl reboot
