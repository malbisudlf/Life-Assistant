#!/usr/bin/env bash
# Vigilante del perfil SIP de FreeSWITCH, en caja. Cada minuto, desde el crontab de Mikel:
#
#   * * * * * $HOME/telefono-vigilante/vigilante-sip.sh >> $HOME/telefono-vigilante/vigilante.log 2>&1
#
# Por qué existe (avería del 2026-11-18, «Avería del 2026-11-18» en PARCHES.md): cuando el
# adaptador de red de caja se cae y vuelve, FreeSWITCH reinicia su perfil `drachtio_mrf`. Si la
# IP aún no ha vuelto, no puede enlazar el 5080, lo intenta tres veces y SE RINDE. El
# contenedor sigue «Up», drachtio sigue aceptando llamadas y todas acaban en 503: el teléfono
# muerto sin que nada lo cante.
#
# Lo que hace: si el perfil no está RUNNING, lo arranca (`sofia profile drachtio_mrf start`,
# que no corta nada: sin perfil no hay llamadas que cortar) y avisa al móvil por el canal de
# los vigías (`avisar.sh`, que deduplica y no avisa de noche). Si todo está bien, calla.
#
# Lo que NO hace: reiniciar contenedores (eso es de `restart: unless-stopped`) ni tocar la red.
# Si el ESL no contesta, solo lo apunta: sin ESL no se puede mirar, y un reinicio a ciegas
# podría cortar una llamada en curso.
#
# VIGILANTE_DRY_RUN=1 lo cuenta todo sin arrancar nada ni avisar.
set -uo pipefail
export PATH="/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin"

PERFIL=${VIGILANTE_PERFIL:-drachtio_mrf}
CONTENEDOR=${VIGILANTE_CONTENEDOR:-freeswitch}
ENV_TELEFONO=${VIGILANTE_ENV:-$HOME/.claude-phone/.env}
AVISAR=${VIGILANTE_AVISAR:-$HOME/stack/vigias/avisar.sh}
WORKFLOW="Teléfono: FreeSWITCH sin perfil SIP"
DRY=${VIGILANTE_DRY_RUN:-0}

ahora() { date '+%Y-%m-%d %H:%M:%S'; }

# Uno cada vez: si un arranque tarda, el minuto siguiente no se le pisa.
exec 9>"${TMPDIR:-/tmp}/vigilante-sip.lock"
flock -n 9 || exit 0

[ "$(docker inspect -f '{{.State.Running}}' "$CONTENEDOR" 2>/dev/null)" = "true" ] || exit 0

# La clave del ESL, la misma que usa la voice-app. Se lee aquí y va por el entorno de
# `docker exec`, no por la línea de órdenes del anfitrión.
CLAVE=$(grep -m1 '^FREESWITCH_SECRET=' "$ENV_TELEFONO" 2>/dev/null | cut -d= -f2- | tr -d '"'"'")
[ -n "$CLAVE" ] || { echo "$(ahora) sin FREESWITCH_SECRET en $ENV_TELEFONO"; exit 1; }

fsc() {
  docker exec -e CLAVE="$CLAVE" "$CONTENEDOR" sh -c 'fs_cli -H 127.0.0.1 -p "$CLAVE" -x "$1"' _ "$1" 2>&1
}

perfil_vivo() { fsc "sofia status" | grep -qE "^\s*$PERFIL\s+profile\s.*RUNNING"; }

ESTADO=$(fsc "sofia status")
if ! grep -q "profile" <<<"$ESTADO" && ! grep -q "0 profiles" <<<"$ESTADO"; then
  echo "$(ahora) el ESL no contesta: ${ESTADO//$'\n'/ }" | cut -c1-300
  exit 0
fi

perfil_vivo && exit 0

CANALES=$(fsc "show channels count" | grep -oE '^[0-9]+' | head -1)
echo "$(ahora) perfil $PERFIL caído (canales: ${CANALES:-?})"

if [ "$DRY" = "1" ]; then
  echo "$(ahora) [dry-run] arrancaría $PERFIL y avisaría"
  exit 0
fi

# Arrancar tarda: hasta ~25 s tras un reinicio. Se espera mirando, y NUNCA se repite el
# `start` sobre uno que está arrancando: el 2026-11-18 un segundo `start` encontró el 5080
# ocupado por el primero y dejó el perfil fuera de la lista («Invalid Profile!») con el
# agente SIP vivo debajo, un estado del que solo saca un reinicio.
esperar_perfil() {
  for _ in $(seq 1 "$1"); do perfil_vivo && return 0; sleep 1; done
  return 1
}

fsc "sofia profile $PERFIL start" | tr '\n' ' ' | sed "s/^/$(ahora) /"; echo
if esperar_perfil 30; then
  echo "$(ahora) perfil $PERFIL arrancado de nuevo"
  "$AVISAR" "$WORKFLOW" "El perfil SIP de FreeSWITCH se había caído (las llamadas daban 503). Lo he vuelto a arrancar solo. Suele ser el adaptador de red de caja." || true
  exit 0
fi

# No ha arrancado. Si la IP no está (el adaptador sigue caído), reiniciar no sirve: el minuto
# siguiente se vuelve a intentar. Si está, es el estado a medias: se reinicia FreeSWITCH,
# solo sin llamadas (sin perfil no las hay, pero se mira igual).
IP=${VIGILANTE_IP:-$(grep -m1 '^EXTERNAL_IP=' "$ENV_TELEFONO" 2>/dev/null | cut -d= -f2- | tr -d '"'"'")}
CANALES=$(fsc "show channels count" | grep -oE '^[0-9]+' | head -1)
if [ -n "$IP" ] && [ "${CANALES:-1}" = "0" ] && ip -4 -o addr | grep -qF "inet $IP/"; then
  echo "$(ahora) no arranca con la IP presente: reinicio $CONTENEDOR"
  docker restart "$CONTENEDOR" >/dev/null
  if esperar_perfil 60; then
    echo "$(ahora) $CONTENEDOR reiniciado, perfil $PERFIL vivo"
    "$AVISAR" "$WORKFLOW" "El perfil SIP de FreeSWITCH se había caído y no arrancaba: he reiniciado FreeSWITCH y el teléfono vuelve a funcionar." || true
    exit 0
  fi
fi
echo "$(ahora) NO arranca: $(fsc "sofia status" | tr '\n' ' ' | cut -c1-200)"
"$AVISAR" "$WORKFLOW" "El perfil SIP de FreeSWITCH está caído y no arranca: el teléfono no funciona. Mirar la red de caja (ip -br addr) y PARCHES.md, «Avería del 2026-11-18»." || true
