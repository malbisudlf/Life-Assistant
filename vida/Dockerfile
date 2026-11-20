# El buscador de la vida en jacobo (servidor.py + indice.py). Solo aiohttp: el índice es
# SQLite con FTS5, que ya trae el Python de la imagen. Ver docs/VIDA.md.
FROM python:3.12-slim
RUN pip install --no-cache-dir --root-user-action=ignore aiohttp==3.12.15
COPY indice.py servidor.py /app/
WORKDIR /app
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 HOME=/tmp
EXPOSE 8773
CMD ["python3", "servidor.py"]
