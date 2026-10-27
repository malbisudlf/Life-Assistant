#!/bin/bash
# Que la RX 580 no entre en reposo (BACO) en jacobo (2026-10-27). Sin pantalla, amdgpu la
# duerme en cuanto no hace nada, y al dormirla saca los modelos de la VRAM a la memoria
# del sistema (GTT): se quedan allí al despertar y Whisper va 5 veces más lento (small
# 1,4 s en vez de 0,28). En reposo, despierta, gasta ~10 W.
# Se lanza con: sudo bash ~/oido/gpu-sin-reposo.sh. Vuelta atrás: borrar la regla y reiniciar.
set -euo pipefail
cat > /etc/udev/rules.d/99-gpu-sin-reposo.rules <<'R'
ACTION=="add|bind", SUBSYSTEM=="pci", DRIVER=="amdgpu", ATTR{power/control}="on"
R
udevadm control --reload
for d in /sys/bus/pci/drivers/amdgpu/0000:*; do echo on > "$d/power/control"; echo "$d: $(cat $d/power/control) $(cat $d/power/runtime_status)"; done
# Que el oído vuelva a cargar los modelos, ahora sí en la VRAM
docker restart oido
