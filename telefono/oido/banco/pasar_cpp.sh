#!/bin/bash
# Pasa el banco con whisper.cpp: levanta su servidor con un modelo, mide y lo apaga.
# Uso: pasar_cpp.sh <modelo> [gpu|cpu]   (modelo = small, medium-q5_0, large-v3-turbo-q5_0…)
set -uo pipefail
M=$1; MODO=${2:-gpu}
cd ~/oido
OPC=(-t 6 -l es -m modelos/ggml-$M.bin --host 127.0.0.1 --port 8090)
[ "$MODO" = cpu ] && OPC+=(-ng)
whisper.cpp/build-vk/bin/whisper-server "${OPC[@]}" > banco/resultados/servidor-$M-$MODO.log 2>&1 &
PID=$!
for _ in $(seq 60); do curl -s -o /dev/null 127.0.0.1:8090/ && break; sleep 1; done
venv/bin/python -I banco/banco_whisper.py "cpp-$M-$MODO${CTX:+-ctx}" cpp:http://127.0.0.1:8090
kill $PID; wait $PID 2>/dev/null
