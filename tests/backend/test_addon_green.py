"""Tests del add-on que corre el backend dentro del Home Assistant Green.

No se puede probar el add-on de verdad sin un Green delante, así que aquí solo
se comprueban las cosas que se rompen en silencio y que solo darían la cara con
el add-on ya copiado al aparato:

- que `run.sh` sea sintácticamente válido (un `bash -n`, no una ejecución),
- que la ruta del fichero de entorno no se desincronice entre `config.yaml` y
  `run.sh`, que son dos ficheros distintos con el mismo valor escrito a mano,
- que no se cuele un secreto en algo que se versiona en un repositorio público.

No hay PyYAML en el proyecto y no se añade una dependencia por esto: las
comprobaciones van por texto, que para estas tres preguntas basta.
"""
import os
import re
import shutil
import subprocess

import pytest

RAIZ = os.path.join(os.path.dirname(__file__), "..", "..")
ADDON = os.path.join(RAIZ, "addon", "life-assistant")

CONFIG = os.path.join(ADDON, "config.yaml")
RUN = os.path.join(ADDON, "run.sh")
DOCKERFILE = os.path.join(ADDON, "Dockerfile")


def _leer(ruta):
    with open(ruta, encoding="utf-8") as f:
        return f.read()


def test_estan_los_tres_ficheros():
    """El Supervisor necesita los tres; sin `config.yaml` el add-on ni aparece
    en la tienda, y sin `run.sh` arranca y muere."""
    for ruta in (CONFIG, RUN, DOCKERFILE):
        assert os.path.isfile(ruta), f"falta {os.path.basename(ruta)}"


@pytest.mark.skipif(shutil.which("bash") is None, reason="no hay bash")
def test_run_sh_no_tiene_errores_de_sintaxis():
    """`bash -n` analiza sin ejecutar. Un paréntesis mal puesto aquí solo se
    vería como un add-on que arranca y se apaga, sin más pista."""
    r = subprocess.run(["bash", "-n", RUN], capture_output=True, text=True)
    assert r.returncode == 0, r.stderr


def test_la_ruta_del_env_coincide_en_config_y_en_run():
    """`config.yaml` declara el valor por defecto y `run.sh` repite ese mismo
    valor como respaldo del `jq`. Si divergen, el add-on busca el fichero donde
    no está y aborta con «no encuentro ...» apuntando a una ruta que el usuario
    sí creó — el peor mensaje de error posible."""
    en_config = re.search(r"fichero_env:\s*(\S+)", _leer(CONFIG))
    en_run = re.search(r'fichero_env\s*//\s*"([^"]+)"', _leer(RUN))
    assert en_config and en_run, "no encuentro la ruta en uno de los dos"
    assert en_config.group(1) == en_run.group(1)


def test_run_sh_exige_los_secretos_sin_valor_por_defecto():
    """`SECRET_KEY` y `DASHBOARD_PASSWORD` no tienen fallback en `main.py` a
    propósito. El add-on los comprueba antes para fallar con un mensaje legible
    en vez de con un RuntimeError al importar."""
    run = _leer(RUN)
    assert "SECRET_KEY" in run and "DASHBOARD_PASSWORD" in run


def test_el_env_se_lee_con_source_y_no_linea_a_linea():
    """`ENABLE_BANKING_PRIVATE_KEY` es una PEM multilínea entrecomillada.
    Parsearla con un bucle de `read` la partiría y Enable Banking fallaría en la
    primera llamada, con el backend arrancado y aparentemente sano."""
    run = _leer(RUN)
    assert re.search(r'^\s*\.\s+"\$FICHERO_ENV"', run, re.M), (
        "el fichero de entorno debe leerse con `.` (source), no a mano"
    )


def test_el_addon_no_lleva_secretos_dentro():
    """Esto se versiona en un repositorio PÚBLICO. Los valores viven en el Green,
    en un fichero que no sale de ahí."""
    sospechoso = re.compile(
        r"(SECRET_KEY|DASHBOARD_PASSWORD|_TOKEN|_KEY|PASSWORD)\s*[=:]\s*[\"']?[A-Za-z0-9/+_-]{16,}",
    )
    for ruta in (CONFIG, RUN, DOCKERFILE):
        assert not sospechoso.search(_leer(ruta)), f"algo con pinta de secreto en {ruta}"


def test_el_dockerfile_clona_el_repo_en_vez_de_copiar_el_codigo():
    """Si el código se copiara a mano al Green, la copia del aparato se quedaría
    atrás en silencio — el fallo que ya tiene el prompt de la rutina del
    briefing. Clonando, desplegar es reconstruir el add-on."""
    dockerfile = _leer(DOCKERFILE)
    assert "git clone" in dockerfile
    assert "requirements.txt" in dockerfile
