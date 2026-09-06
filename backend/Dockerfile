FROM python:3.11-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# El puerto sale de $PORT si la plataforma lo inyecta (Koyeb lo hace), y si no
# cae al 8080 de siempre (Fly, y `docker run` a pelo). Es lo único que separa
# este Dockerfile de ser portable: todo lo demás ya lo era.
#
# `sh -c` con `exec` a propósito: sin el `exec`, uvicorn queda como hijo del
# shell, el shell se queda de PID 1 y no reenvía SIGTERM — la plataforma pide
# parada limpia, nadie la recibe y el contenedor muere de un SIGKILL a los 30s.
CMD ["sh", "-c", "exec uvicorn main:app --host 0.0.0.0 --port ${PORT:-8080}"]
