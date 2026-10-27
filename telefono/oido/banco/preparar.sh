#!/bin/bash
# Lo básico de jacobo para el oído de Jarvis (2026-10-27). Se lanza con: sudo bash ~/oido/preparar.sh
set -euo pipefail
U=${SUDO_USER:?lánzalo con sudo}
export DEBIAN_FRONTEND=noninteractive
apt-get update
# Compilar whisper.cpp con Vulkan, y lo que piden los audios de prueba y el banco
apt-get install -y build-essential cmake git ffmpeg python3-venv python3-pip \
  mesa-vulkan-drivers vulkan-tools libvulkan-dev glslc
# Docker de los repositorios de Ubuntu (con compose v2)
apt-get install -y docker.io docker-compose-v2
systemctl enable --now docker
# La GPU (/dev/dri/renderD128) es del grupo render; docker, para no ir con sudo
usermod -aG render,video,docker "$U"
echo
echo "== Listo =="
vulkaninfo --summary 2>/dev/null | grep -E "deviceName|driverName|apiVersion" || true
docker --version; docker compose version
