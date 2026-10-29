# La voz de Jarvis en jacobo (servidor.py): Piper en la CPU, por ONNX. Las versiones van
# fijadas a las que se midieron el 2026-10-29 («La voz en jacobo», telefono/PARCHES.md).
# Los modelos NO van dentro: se montan de ~/voz/modelos.
#
# `ruedas/` son los paquetes ya bajados (en caja: `pip download`, ver PARCHES.md). El
# enlace de jacobo se cae con tráfico sostenido y bajarlos desde allí tumba el oído; si
# la carpeta está vacía, pip los baja de PyPI como siempre. En jacobo se construye con
# `--build-arg PIP_NO_INDEX=1` para que ni pregunte a PyPI.
FROM python:3.12-slim
ARG PIP_NO_INDEX=
COPY ruedas/ /tmp/ruedas/
RUN pip install --no-cache-dir --root-user-action=ignore --find-links /tmp/ruedas \
      piper-tts==1.3.0 aiohttp==3.12.15 numpy==2.3.4 \
    && rm -rf /tmp/ruedas
COPY servidor.py /app/
WORKDIR /app
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 HOME=/tmp
EXPOSE 8772
CMD ["python3", "servidor.py"]
