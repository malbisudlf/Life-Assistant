#!/usr/bin/env bash
# El espejo: prueba una rama del backend en una copia aislada, EN caja, sin red.
#
#   espejo.sh <rama> [--resumen "qué cambia"] [--propone mikel|jarvis:fallo] [--capacidad nombre]
#
# Qué hace, en orden, y dónde para:
#   1. Trae la rama y saca su diff contra `main`.
#   2. LA PUERTA: `espejo.py revisar`, con el `espejo.py` y el núcleo de MAIN, nunca los de
#      la rama (un parche no puede traerse su propio juez). Si rechaza, aquí se acaba.
#   3. Dos copias limpias (`git archive`, sin `.git`): la de main y la de la rama. Ninguna
#      es el repositorio desplegado, y ninguna ve `backend.env`.
#   4. Comprueba que el espejo está aislado: desde dentro, internet, la LAN y el backend de
#      verdad tienen que NO contestar. Si algo contesta, no se prueba nada.
#   5. Las pruebas del backend en las dos copias, en un contenedor con `--network none` y el
#      código montado de solo lectura. La base de datos y los servicios son los simulados
#      de `tests/backend/conftest.py`: la real no está ni al alcance.
#   6. Compara: lo que pasaba en main y deja de pasar en la rama es una REGRESIÓN.
#   7. El informe de tres líneas y la pregunta, y una línea en el rastro.
#
# No despliega nada y no toca nada de lo que corre. Sale con 0 solo si el informe termina
# preguntando «¿Lo despliego?».
set -euo pipefail

RAMA="${1:?uso: espejo.sh <rama> [--resumen ...] [--propone ...] [--capacidad ...]}"; shift
RESUMEN=""; PROPONE="mikel"; CAPACIDADES=()
while [ $# -gt 0 ]; do
  case "$1" in
    --resumen)   RESUMEN="$2"; shift 2 ;;
    --propone)   PROPONE="$2"; shift 2 ;;
    --capacidad) CAPACIDADES+=(--capacidad "$2"); shift 2 ;;
    *) echo "espejo.sh: no entiendo $1" >&2; exit 64 ;;
  esac
done

REPO="${ESPEJO_REPO:-$HOME/stack/Life-Assistant}"
DIR="${ESPEJO_DIR:-$HOME/espejo-jarvis}"
RASTRO="$DIR/rastro.jsonl"
IMAGEN_BASE="${ESPEJO_IMAGEN_BASE:-stack-backend:latest}"
IMAGEN="espejo-pruebas:latest"
ID="$(date +%Y%m%d-%H%M%S)-$(echo "$RAMA" | tr -c 'A-Za-z0-9' '-' | cut -c1-40)"
TRABAJO="$DIR/copias/$ID"
mkdir -p "$TRABAJO/main" "$TRABAJO/rama" "$TRABAJO/salida"
trap 'rm -rf "$TRABAJO/main" "$TRABAJO/rama"' EXIT

decir() { echo "== $*"; }

# ------------------------------------------------------------------ 1. diff --
cd "$REPO"
git fetch --quiet origin main "$RAMA"
MAIN_SHA=$(git rev-parse origin/main)
RAMA_SHA=$(git rev-parse FETCH_HEAD)
git diff "$MAIN_SHA...$RAMA_SHA" > "$TRABAJO/salida/cambio.diff"
decir "parche $ID: $RAMA (${RAMA_SHA:0:7}) contra main (${MAIN_SHA:0:7})"

git archive "$MAIN_SHA" | tar -x -C "$TRABAJO/main"
git archive "$RAMA_SHA" | tar -x -C "$TRABAJO/rama"
JUEZ="$TRABAJO/main/espejo/espejo.py"
[ -f "$JUEZ" ] || { echo "espejo.sh: main no tiene espejo/espejo.py" >&2; exit 70; }
apuntar() { python3 "$JUEZ" apuntar --rastro "$RASTRO" --id "$ID" "$@" >/dev/null; }

apuntar --paso propuesto --dato "propuesto_por=$PROPONE" --dato "rama=$RAMA" \
        --dato "sha=$RAMA_SHA" --dato "base=$MAIN_SHA" --dato "resumen=$RESUMEN"

# ---------------------------------------------------------------- 2. puerta --
if ! python3 "$JUEZ" revisar --diff "$TRABAJO/salida/cambio.diff" "${CAPACIDADES[@]}" \
       > "$TRABAJO/salida/puerta.json"; then
  echo '{}' > "$TRABAJO/salida/pruebas.json"
  python3 "$JUEZ" informe --diff "$TRABAJO/salida/cambio.diff" --pruebas "$TRABAJO/salida/pruebas.json" \
          --resumen "$RESUMEN" "${CAPACIDADES[@]}" | tee "$TRABAJO/salida/informe.txt" || true
  apuntar --paso rechazado --dato "motivo=$(python3 -c 'import json,sys;print("; ".join(json.load(open(sys.argv[1]))["rechazos"]))' "$TRABAJO/salida/puerta.json")"
  exit 2
fi
decir "la puerta de seguridad lo deja pasar"

# ---------------------------------------------------------------- 3. imagen --
# Sobre la imagen que ya corre en producción: mismas dependencias, sin bajar nada más que
# pytest. `requirements.txt` es ruta protegida, así que la rama no puede traer otras.
if ! docker image inspect "$IMAGEN" >/dev/null 2>&1 || \
   [ "$(docker image inspect -f '{{.Created}}' "$IMAGEN_BASE")" \> "$(docker image inspect -f '{{.Created}}' "$IMAGEN")" ]; then
  decir "construyendo $IMAGEN sobre $IMAGEN_BASE"
  printf 'FROM %s\nRUN pip install --no-cache-dir pytest\n' "$IMAGEN_BASE" | docker build -q -t "$IMAGEN" - >/dev/null
fi

# ------------------------------------------------------------- 4. aislado --
# Desde dentro del espejo: una IP de internet, un nombre (no hay DNS), la puerta de enlace
# de la LAN y el backend de verdad en el host. Si CUALQUIERA contesta, no está aislado.
PUERTA_LAN=$(ip route show default | awk '{print $3; exit}')
IP_HOST=$(ip route get 1.1.1.1 | awk '{for(i=1;i<=NF;i++) if($i=="src") print $(i+1); exit}')
AISLADO=$(docker run --rm --network none "$IMAGEN" python -c '
import socket, sys
abiertos = []
for host, puerto in (("1.1.1.1", 443), ("api.openai.com", 443), (sys.argv[1], 80), (sys.argv[2], 8080), (sys.argv[2], 8123)):
    try:
        socket.create_connection((host, puerto), timeout=3).close()
        abiertos.append(f"{host}:{puerto}")
    except OSError:
        pass
print("no:" + ",".join(abiertos) if abiertos else "si")
' "$PUERTA_LAN" "$IP_HOST" 2>/dev/null || echo "no:no-arranca")
if [ "$AISLADO" != "si" ]; then
  decir "EL ESPEJO NO ESTÁ AISLADO ($AISLADO): no se prueba nada"
  echo '{"aislado": false}' > "$TRABAJO/salida/pruebas.json"
else
  decir "espejo aislado: ni internet, ni la LAN, ni el backend de verdad contestan"
  # ------------------------------------------------------------ 5. pruebas --
  correr() {  # correr <copia> <nombre>
    docker run --rm --network none --cpus 2 --memory 1500m \
      -e PYTHONDONTWRITEBYTECODE=1 -e HOME=/tmp \
      -v "$TRABAJO/$1:/src:ro" -v "$TRABAJO/salida:/salida" -w /src "$IMAGEN" \
      python -m pytest tests/backend -q -p no:cacheprovider --junitxml="/salida/$2.xml" \
      > "$TRABAJO/salida/$2.log" 2>&1 || true
    tail -1 "$TRABAJO/salida/$2.log"
  }
  decir "pruebas en main:  $(correr main main)"
  decir "pruebas en rama:  $(correr rama rama)"
  # ----------------------------------------------------------- 6. comparar --
  python3 "$TRABAJO/main/espejo/comparar.py" "$TRABAJO/salida/main.xml" "$TRABAJO/salida/rama.xml" \
    > "$TRABAJO/salida/pruebas.json"
fi

# ------------------------------------------------------------- 7. informe --
set +e
python3 "$JUEZ" informe --diff "$TRABAJO/salida/cambio.diff" --pruebas "$TRABAJO/salida/pruebas.json" \
        --resumen "$RESUMEN" "${CAPACIDADES[@]}" | tee "$TRABAJO/salida/informe.txt"
SALIDA=${PIPESTATUS[0]}
set -e
apuntar --paso probado --dato "sha=$RAMA_SHA" --dato "pasa=$([ "$SALIDA" = 0 ] && echo si || echo no)" \
        --dato "pruebas=$(tr -d '\n' < "$TRABAJO/salida/pruebas.json")" \
        --dato "huella=$(sha256sum "$TRABAJO/salida/cambio.diff" | cut -c1-16)"
decir "todo en $TRABAJO/salida · rastro en $RASTRO"
exit "$SALIDA"
