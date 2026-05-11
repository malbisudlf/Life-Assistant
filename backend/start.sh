#!/bin/sh
set -e

# Arrancar Tailscale daemon en background
tailscaled --state=/tmp/tailscaled.state --tun=userspace-networking &
sleep 2

# Autenticar en la red Tailscale (ephemeral, no necesita persistir)
if [ -n "$TAILSCALE_AUTH_KEY" ]; then
  tailscale up --authkey="$TAILSCALE_AUTH_KEY" --hostname="fly-life-assistant" --accept-routes=false
fi

# Arrancar el backend
exec uvicorn main:app --host 0.0.0.0 --port 8080
