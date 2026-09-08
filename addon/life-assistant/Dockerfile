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

# Esta linea es la que hace que "Reconstruir" reconstruya de verdad.
#
# El RUN de abajo no cambia nunca, asi que Docker reutilizaba su capa cacheada y NO
# volvia a clonar: el add-on seguia sirviendo el codigo del dia en que se construyo la
# imagen por primera vez, y la reconstruccion era un no-op SILENCIOSO — termina bien,
# sin avisos, y el backend arranca igual de viejo. Se descubrio el 2026-09-08, tras
# mergear dos arreglos a main, reconstruir, y comprobar que produccion los ignoraba.
#
# `ADD` con una URL se descarga siempre y compara el contenido: como este JSON lleva
# el SHA del ultimo commit de la rama, la capa se invalida cuando —y solo cuando— hay
# codigo nuevo que traer. Si GitHub no responde, la construccion falla, que es
# preferible a desplegar lo de antes creyendo que se ha desplegado lo de ahora.
ADD https://api.github.com/repos/malbisudlf/Life-Assistant/commits/main /tmp/ultimo_commit.json

# Del clon se guarda el SHA en /app/VERSION: `GET /` lo devuelve, y es la unica forma
# de saber que codigo esta corriendo ahi dentro sin entrar en el Green.
RUN git clone --depth 1 --branch "${RAMA}" "${REPO}" /tmp/repo \
 && git -C /tmp/repo rev-parse HEAD > /app/VERSION \
 && cp -r /tmp/repo/backend/. /app/ \
 && rm -rf /tmp/repo \
 && pip install --no-cache-dir -r requirements.txt

COPY run.sh /run.sh
RUN chmod +x /run.sh

# `run.sh` termina en `exec uvicorn`, asi que uvicorn sustituye al shell y queda
# de PID 1: es lo que le hace recibir el SIGTERM del Supervisor y parar limpio.
CMD ["/run.sh"]
