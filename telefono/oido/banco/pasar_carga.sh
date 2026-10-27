#!/bin/bash
# Reposo, una llamada y el modo coche, con turbo (8090) y small (8091) levantados a la vez.
cd ~/oido
B=whisper.cpp/build-vk/bin/whisper-server
$B -t 6 -l es -m modelos/ggml-large-v3-turbo-q5_0.bin --host 127.0.0.1 --port 8090 > /dev/null 2>&1 & P1=$!
$B -t 6 -l es -m modelos/ggml-small.bin --host 127.0.0.1 --port 8091 > /dev/null 2>&1 & P2=$!
for _ in $(seq 60); do curl -s -o /dev/null 127.0.0.1:8090/ && curl -s -o /dev/null 127.0.0.1:8091/ && break; sleep 1; done
sleep 60
for e in "reposo 90" "llamada 300" "reposo 120" "coche 300" "reposo 120"; do venv/bin/python -I banco/carga.py $e; done > banco/resultados/carga.txt 2>&1
kill $P1 $P2
echo FIN >> banco/resultados/carga.txt
