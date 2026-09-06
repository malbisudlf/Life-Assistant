# Imagen propia en vez de la base de Home Assistant: el backend ya tiene su
# Dockerfile probado sobre python:3.11-slim y no gana nada heredando de Alpine.
# Desde Supervisor 2026.04 el argumento BUILD_FROM ya no se inyecta, asi que un
# FROM explicito es ademas lo correcto.
FROM python:3.11-slim

# El codigo sale del repositorio publico y NO de una copia dentro del add-on:
# asi actualizar el backend es reconstruir el add-on, sin volver a pasar
# ficheros por Samba y sin que la copia del Green se quede atras en silencio
# (que es justo lo que le pasa al prompt de la rutina del briefing).
ARG REPO=https://github.com/malbisudlf/Life-Assistant
ARG RAMA=main

RUN apt-get update \
 && apt-get install -y --no-install-recommends git jq ca-certificates \
 && rm -rf /var/lib/apt/lists/*

WORKDIR /app
RUN git clone --depth 1 --branch "${RAMA}" "${REPO}" /tmp/repo \
 && cp -r /tmp/repo/backend/. /app/ \
 && rm -rf /tmp/repo \
 && pip install --no-cache-dir -r requirements.txt

COPY run.sh /run.sh
RUN chmod +x /run.sh

# `run.sh` termina en `exec uvicorn`, asi que uvicorn sustituye al shell y queda
# de PID 1: es lo que le hace recibir el SIGTERM del Supervisor y parar limpio.
CMD ["/run.sh"]
