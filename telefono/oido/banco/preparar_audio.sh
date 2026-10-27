#!/bin/bash
# Pasa cada frase por el canal del teléfono: 8 kHz G.711 μ-law, y vuelta a 16 kHz PCM
# (lo que recibiría Whisper). Deja tel/<id>.wav (entera) y tel3/<id>.wav (primeros 3 s,
# el largo de una orden típica).
set -euo pipefail
cd ~/oido/datos/mls
mkdir -p tel tel3
for f in *.opus; do
  id=${f%.opus}
  ffmpeg -loglevel error -y -i "$f" -ar 8000 -ac 1 -c:a pcm_mulaw -f mulaw - |
    ffmpeg -loglevel error -y -f mulaw -ar 8000 -ac 1 -i - -ar 16000 -c:a pcm_s16le "tel/$id.wav"
  ffmpeg -loglevel error -y -i "tel/$id.wav" -t 3 -c copy "tel3/$id.wav"
done
ls tel | wc -l
