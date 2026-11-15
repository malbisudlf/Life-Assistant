#!/usr/bin/env bash
# El canario: un parche ya aprobado se enciende un día, vigilado, y se apaga solo si falla.
#
#   canario.sh empezar <id-del-parche> <PARCHE_NN>   enciende el interruptor y empieza a vigilar
#   canario.sh vigilar                               una pasada (la lanza cron cada 10 min)
#   canario.sh volver "<motivo>"                     apaga el interruptor ahora
#   canario.sh estado
#
# Un parche de Jarvis nace detrás de un interruptor apagado (`PARCHE_NN`, lo exige la
# puerta). Desplegarlo no cambia nada; ENCENDERLO es el canario: se añade `PARCHE_NN=1` al
# `backend.env` de caja y se recrea el contenedor (sin reconstruir la imagen). Durante 24 h
# cada pasada mira si el backend sigue sano y si escribe más errores que antes. Al primer
# fallo se quita la línea y se recrea: VUELTA ATRÁS SIN PREGUNTAR, y después se avisa.
# Pasadas las 24 h, queda confirmado y encendido.
#
# Dos cosas que este script NO hace nunca: empezar un canario sin la aprobación de Mikel
# apuntada en el rastro, y encender algo que no sea un `PARCHE_NN`.
set -euo pipefail

STACK="${STACK:-$HOME/stack}"
DIR="${ESPEJO_DIR:-$HOME/espejo-jarvis}"
RASTRO="$DIR/rastro.jsonl"
ESTADO="$DIR/canario.json"
ENV="$STACK/backend.env"
AQUI="$(dirname "$(readlink -f "$0")")"
NUCLEO="$AQUI/../backend/nucleo_seguridad.json"
HORAS=$(python3 -c 'import json,sys;print(json.load(open(sys.argv[1]))["parches"]["canario_horas"])' "$NUCLEO")
ERRORES_MAX=$(python3 -c 'import json,sys;print(json.load(open(sys.argv[1]))["parches"]["canario_errores_max"])' "$NUCLEO")
mkdir -p "$DIR"

apuntar() { python3 "$AQUI/espejo.py" apuntar --rastro "$RASTRO" "$@" >/dev/null; }
campo()   { python3 -c 'import json,sys;print(json.load(open(sys.argv[1])).get(sys.argv[2],""))' "$ESTADO" "$1"; }
errores() { docker logs backend --since "$1" 2>&1 | grep -cE ' (ERROR|CRITICAL) |Traceback \(most recent call last\)' || true; }

sano() {
  for _ in $(seq 1 30); do
    [ "$(docker inspect -f '{{.State.Health.Status}}' backend 2>/dev/null)" = "healthy" ] && \
      curl -fsS --max-time 5 http://localhost:8080/ >/dev/null 2>&1 && return 0
    sleep 2
  done
  return 1
}

avisar() {  # por el mismo canal que los vigías, si están; si no, al log
  if [ -x "$STACK/vigias/avisar.sh" ]; then
    "$STACK/vigias/avisar.sh" "Jarvis · canario" "$1" >/dev/null 2>&1 || echo "canario: no pude avisar: $1" >&2
  else
    echo "canario: $1" >&2
  fi
}

recrear() { (cd "$STACK" && docker compose up -d backend >/dev/null 2>&1); }

volver() {  # volver <motivo>
  local motivo="$1" flag id
  [ -f "$ESTADO" ] || { echo "canario: no hay ningún canario en marcha"; return 0; }
  flag=$(campo flag); id=$(campo id)
  cp "$ENV" "$ENV.bak-canario-$(date +%Y%m%d-%H%M%S)"
  sed -i "/^${flag}=/d" "$ENV"
  recrear
  if sano; then
    apuntar --id "$id" --paso vuelta --dato "motivo=$motivo" --dato "manual=no" --dato "sano=si"
    avisar "He apagado el parche $id ($flag) yo solo: $motivo. El backend está sano. No hace falta que haga nada."
  else
    apuntar --id "$id" --paso vuelta --dato "motivo=$motivo" --dato "manual=no" --dato "sano=no"
    avisar "He apagado el parche $id ($flag) por: $motivo, pero el backend NO vuelve sano. Esto ya no es del parche: mírelo."
  fi
  rm -f "$ESTADO"
}

case "${1:-}" in
  empezar)
    id="${2:?falta el id del parche}"; flag="${3:?falta el interruptor (PARCHE_NN)}"
    [[ "$flag" =~ ^PARCHE_[0-9A-Z_]{1,40}$ ]] || { echo "canario: $flag no es un PARCHE_NN" >&2; exit 64; }
    [ -f "$ESTADO" ] && { echo "canario: ya hay uno en marcha ($(campo id))" >&2; exit 65; }
    python3 - "$RASTRO" "$id" <<'PY' || { echo "canario: $id no tiene la aprobación de Mikel en el rastro" >&2; exit 66; }
import json, sys
pasos = [json.loads(l) for l in open(sys.argv[1], encoding="utf-8") if l.strip()]
mios = [p for p in pasos if p.get("parche") == sys.argv[2]]
probado = any(p["paso"] == "probado" and p.get("pasa") == "si" for p in mios)
aprobado = any(p["paso"] == "aprobado" and p.get("aprobado_por") == "mikel" and p.get("literal") for p in mios)
sys.exit(0 if probado and aprobado else 1)
PY
    grep -q "^${flag}=" "$ENV" && { echo "canario: $flag ya está en backend.env" >&2; exit 67; }
    base=$(errores "${HORAS}h")
    cp "$ENV" "$ENV.bak-canario-$(date +%Y%m%d-%H%M%S)"
    printf '%s=1\n' "$flag" >> "$ENV"
    python3 - "$ESTADO" "$id" "$flag" "$base" <<'PY'
import json, sys, time
json.dump({"id": sys.argv[2], "flag": sys.argv[3], "desde": int(time.time()),
           "errores_antes": int(sys.argv[4])}, open(sys.argv[1], "w"))
PY
    recrear
    if ! sano; then volver "el backend no arrancó sano con el interruptor encendido"; exit 1; fi
    apuntar --id "$id" --paso canario --dato "flag=$flag" --dato "horas=$HORAS" --dato "errores_antes=$base"
    echo "canario: $id encendido ($flag). Se vigila $HORAS h; si falla, se apaga solo."
    ;;
  vigilar)
    [ -f "$ESTADO" ] || exit 0
    id=$(campo id); desde=$(campo desde); antes=$(campo errores_antes)
    ahora=$(date +%s); llevo=$(( (ahora - desde) / 60 ))
    if ! sano; then volver "el backend dejó de responder a los $llevo min"; exit 0; fi
    nuevos=$(errores "${llevo}m")
    # Lo que ya fallaba antes del parche no es culpa suya: se compara con el ritmo de las
    # 24 h anteriores, prorrateado al tiempo que lleva.
    esperados=$(( antes * llevo / (HORAS * 60) ))
    if [ $(( nuevos - esperados )) -gt "$ERRORES_MAX" ]; then
      volver "$nuevos errores en $llevo min (lo normal eran $esperados)"; exit 0
    fi
    if [ "$llevo" -ge $(( HORAS * 60 )) ]; then
      apuntar --id "$id" --paso confirmado --dato "errores=$nuevos" --dato "horas=$HORAS"
      avisar "El parche $id ha pasado sus $HORAS h de canario sin fallos. Queda encendido."
      rm -f "$ESTADO"
    fi
    ;;
  volver) volver "${2:-pedido a mano}" ;;
  estado) [ -f "$ESTADO" ] && cat "$ESTADO" && echo || echo "sin canario en marcha" ;;
  *) sed -n '2,8p' "$0"; exit 64 ;;
esac
