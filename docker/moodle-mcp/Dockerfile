# moodle-mcp (github.com/loyaniu/moodle-mcp) por HTTP, con llave. Ver servidor.py y
# docs/MOODLE.md.
FROM python:3.12-slim

# Versiones FIJAS, todas. Dos motivos que no son el de siempre:
#  - moodle-mcp 0.2.1 importa `mcp.server.fastmcp`, que en `mcp` 2.x ya no existe: con
#    lo que instala pip hoy por defecto, el contenedor no arranca (comprobado el
#    2026-10-07). Y por debajo de 1.8 no hay transporte Streamable HTTP. De ahí el 1.30.
#  - servidor.py declara de SOLO LECTURA las 24 herramientas del original. Es cierto en
#    la 0.2.1; subirla sin volver a mirar la lista podría hacer que una herramienta que
#    escribe en Moodle se ejecutara sin pedir confirmación a nadie.
RUN pip install --no-cache-dir \
      moodle-mcp==0.2.1 \
      "mcp[cli]==1.30.0" \
      glom==25.12.0 \
      requests==2.34.2 \
      python-dotenv==1.2.4 \
      uvicorn==0.54.0

# Sin root: lo único que hace es hablar por red.
RUN useradd --create-home --uid 10001 moodle
USER moodle
WORKDIR /home/moodle
COPY servidor.py .

EXPOSE 8765
CMD ["python", "servidor.py"]
