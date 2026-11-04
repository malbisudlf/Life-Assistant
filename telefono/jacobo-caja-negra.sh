#!/usr/bin/env bash
# La caja negra de jacobo: para saber qué le pasa cuando desaparece. Una vez, en jacobo:
#   sudo bash jacobo-caja-negra.sh
#
# Por qué (2026-11-04): el Prometheus de caja enseñó que, del 31/10 al 04/11, jacobo «se caía»
# varias veces al día sin reiniciarse nunca: estaba encendido, fresco y sin errores, y lo que
# perdía era la red. Pero desde fuera no se puede saber qué tramo falla, ni qué ha pasado
# cuando ni siquiera vuelve después de reiniciarlo. Esto deja la respuesta en su propio disco:
#
#   1. El registro del sistema sobrevive a un reinicio: `journalctl -b -1` es el arranque anterior.
#   2. GRUB no se queda parado en su menú tras un apagado brusco, que sin pantalla parece
#      exactamente «no arranca». Y un kernel panic reinicia solo.
#   3. Arrancar no espera dos minutos a la red.
#   4. Cada minuto se prueba tramo a tramo la red, y en /var/log/red-caja-negra.log se apunta
#      cada cambio: enlace → puerta de enlace → internet → Tailscale. Dice qué tramo cae primero.
#      A los 5 minutos sin salida intenta recomponerla, una vez por caída. Nunca reinicia.
#
# Para leerlo luego:  tail -50 /var/log/red-caja-negra.log ; journalctl -b -1 -p warning
set -euo pipefail
[ "$(id -u)" = 0 ] || { echo "Con sudo, por favor."; exit 1; }

# 1. El registro, persistente y con tope
mkdir -p /var/log/journal /etc/systemd/journald.conf.d
cat > /etc/systemd/journald.conf.d/99-caja-negra.conf <<'EOF'
[Journal]
Storage=persistent
SystemMaxUse=500M
EOF
systemctl restart systemd-journald

# 2. GRUB sin esperas, y un panic reinicia
cat > /etc/default/grub.d/99-caja-negra.cfg <<'EOF'
GRUB_TIMEOUT=5
GRUB_TIMEOUT_STYLE=menu
GRUB_RECORDFAIL_TIMEOUT=5
EOF
update-grub
cat > /etc/sysctl.d/99-caja-negra.conf <<'EOF'
kernel.panic=15
kernel.panic_on_oops=1
EOF
sysctl -q --system

# 3. Arrancar no espera a la red: con una interfaz basta, y 30 s como mucho
mkdir -p /etc/systemd/system/systemd-networkd-wait-online.service.d
cat > /etc/systemd/system/systemd-networkd-wait-online.service.d/99-caja-negra.conf <<'EOF'
[Service]
ExecStart=
ExecStart=/lib/systemd/systemd-networkd-wait-online --any --timeout=30
EOF

# 4. La vigilancia de la red, tramo a tramo
cat > /usr/local/bin/red-caja-negra <<'EOF'
#!/usr/bin/env bash
# Una pasada: prueba cada tramo y apunta solo si algo ha cambiado.
LOG=/var/log/red-caja-negra.log
ESTADO=/run/red-caja-negra
mkdir -p "$ESTADO"
ping1() { ping -c 2 -W 2 "$1" >/dev/null 2>&1 && echo ok || echo MAL; }

enlaces=$(for d in /sys/class/net/*; do
  n=$(basename "$d"); [ "$n" = lo ] && continue
  case "$n" in en*|wl*) printf '%s=%s ' "$n" "$(cat "$d/operstate" 2>/dev/null)";; esac
done)
puerta=$(ip -4 route show default | awk 'NR==1{print $3}')
via=$(ip -4 route show default | awk 'NR==1{print $5}')
if [ -n "$puerta" ]; then pp=$(ping1 "$puerta"); else pp=SIN_RUTA; fi
inet=$(ping1 1.1.1.1)
dns=$(getent hosts controlplane.tailscale.com >/dev/null 2>&1 && echo ok || echo MAL)
ts=$(tailscale status --json 2>/dev/null | python3 -c 'import json,sys;print("ok" if json.load(sys.stdin).get("Self",{}).get("Online") else "MAL")' 2>/dev/null || echo MAL)

linea="enlaces[$enlaces] via=$via puerta=$pp internet=$inet dns=$dns tailscale=$ts"
if [ "$linea" != "$(cat "$ESTADO/ultima" 2>/dev/null)" ]; then
  echo "$(date '+%F %T') $linea" >> "$LOG"
  echo "$linea" > "$ESTADO/ultima"
  # Lo que diga el kernel de las tarjetas en ese momento
  dmesg --since '-3min' 2>/dev/null | grep -iE 'r8169|r8152|rtw|link (is )?(up|down)|NETDEV|transmit queue' | tail -5 | sed 's/^/    /' >> "$LOG"
fi

# Sin salida a internet: se recompone una vez por caída, a los 5 minutos. Nunca reinicia.
if [ "$inet" = MAL ]; then
  n=$(( $(cat "$ESTADO/fallos" 2>/dev/null || echo 0) + 1 ))
  echo "$n" > "$ESTADO/fallos"
  if [ "$n" = 5 ]; then
    echo "$(date '+%F %T') 5 min sin internet: recompongo la red y Tailscale" >> "$LOG"
    networkctl reload >/dev/null 2>&1
    networkctl reconfigure "$via" >/dev/null 2>&1
    systemctl restart tailscaled >/dev/null 2>&1
  fi
else
  echo 0 > "$ESTADO/fallos"
fi
EOF
chmod 755 /usr/local/bin/red-caja-negra

cat > /etc/systemd/system/red-caja-negra.service <<'EOF'
[Unit]
Description=Caja negra de la red de jacobo: una pasada
[Service]
Type=oneshot
ExecStart=/usr/local/bin/red-caja-negra
EOF
cat > /etc/systemd/system/red-caja-negra.timer <<'EOF'
[Unit]
Description=Caja negra de la red de jacobo, cada minuto
[Timer]
OnBootSec=30s
OnUnitActiveSec=1min
AccuracySec=5s
[Install]
WantedBy=timers.target
EOF
cat > /etc/logrotate.d/red-caja-negra <<'EOF'
/var/log/red-caja-negra.log {
  monthly
  rotate 6
  missingok
  notifempty
  compress
}
EOF
systemctl daemon-reload
systemctl enable --now red-caja-negra.timer
/usr/local/bin/red-caja-negra
echo "Hecho. Ahora mismo:"
tail -3 /var/log/red-caja-negra.log
