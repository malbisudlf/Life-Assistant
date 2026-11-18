# La música de la escucha pasiva (parche 50): librespot + este servidor + ffmpeg.
#
# librespot se compila aquí desde su fuente en crates.io (no hay paquete de Debian ni
# binario oficial). Compilar Rust es pesado: la imagen se construye en jacobo, no en caja
# (caja se calienta, ver «caja sin carga pesada»), y se lleva hecha:
#   jacobo$ docker build -t musica:local .
#   jacobo$ docker save musica:local | ssh caja docker load
# 0.8.0, no la 0.6: con la 0.6 Spotify ya no da el audio («Track should be available, but no
# alternatives found» en cada canción, 2026-11-18). La 0.8 pide Rust 1.85.
FROM rust:1.85-slim-bookworm AS librespot
ARG LIBRESPOT_VERSION=0.8.0
RUN apt-get update \
 && apt-get install -y --no-install-recommends pkg-config libasound2-dev libssl-dev \
 && rm -rf /var/lib/apt/lists/*
RUN cargo install librespot --locked --version "${LIBRESPOT_VERSION}"

FROM python:3.12-slim-bookworm
RUN apt-get update \
 && apt-get install -y --no-install-recommends ffmpeg libasound2 ca-certificates \
 && rm -rf /var/lib/apt/lists/*
COPY --from=librespot /usr/local/cargo/bin/librespot /usr/local/bin/librespot
COPY servidor.py /app/servidor.py
USER 1000:1000
CMD ["python3", "-u", "/app/servidor.py"]
