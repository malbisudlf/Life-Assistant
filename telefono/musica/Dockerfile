# La música de la escucha pasiva (parche 50): Soloist + PulseAudio + este servidor + ffmpeg.
#
# Soloist es el cliente Spotify Connect oficial para Linux. Su binario NO va en la imagen:
# Spotify pide no redistribuirlo y caduca a los 90 días, así que servidor.py lo baja de
# Spotify al arrancar (a /datos/soloist/bin) y otra vez cuando caduca. Pide Debian 13 (glibc
# 2.38 y libatomic) y un PulseAudio, que aquí es del propio contenedor.
#
# Hasta el 2026-11-18 el motor era librespot (compilado aquí, Rust): Spotify le niega la clave
# de audio a la cuenta de Mikel («error audio key 0 1»). Ver «El parche 50» en PARCHES.md.
#
# Sin compilar nada ya, se puede construir en caja; por costumbre, en jacobo:
#   jacobo$ docker build -t musica:local .
#   jacobo$ docker save musica:local | ssh caja docker load
FROM debian:trixie-slim
RUN apt-get update \
 && apt-get install -y --no-install-recommends python3 ffmpeg pulseaudio pulseaudio-utils \
      libatomic1 ca-certificates \
 && rm -rf /var/lib/apt/lists/*
COPY servidor.py /app/servidor.py
USER 1000:1000
ENV HOME=/tmp XDG_RUNTIME_DIR=/tmp/run
CMD ["python3", "-u", "/app/servidor.py"]
