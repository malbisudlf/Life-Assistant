# La huella de voz (servidor.py) en jacobo. Solo CPU: ~84 ms por frase con 2 hilos del
# i5-9400F (banco del 2026-10-28, «El parche 23» en telefono/PARCHES.md). sherpa-onnx
# fijado a la versión del banco: con otra, los vectores (y la huella guardada) pueden no
# ser los mismos.
FROM python:3.12-slim
RUN pip install --no-cache-dir --root-user-action=ignore sherpa-onnx==2.0.0 numpy==2.3.4
COPY servidor.py /app/
WORKDIR /app
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
EXPOSE 3020
CMD ["python3", "servidor.py"]
