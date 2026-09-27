"""Tests de agent/agent.py que no necesitan un Windows de verdad.

El agente solo corre en un PC con Edge, pyautogui y Claude Desktop, así que casi todo él
se prueba a mano. Pero dos piezas son lógica pura, y las dos tapaban un fallo:

- `alud_url_permitida`, la última de las tres barreras del invariante 7 (la fila de
  `jobs` se puede escribir sin pasar por el backend). Se saltaba con una barra
  invertida, porque Python y Edge leían hosts distintos. Tiene una copia en
  backend/main.py, y aquí se exige que las dos digan lo mismo.
- El ciclo de un job (`procesar_job`): no miraba lo que respondía el backend al pasarlo
  a running ni al cerrarlo, así que un fallo puntual lo dejaba en claimed para siempre
  mientras el log decía «completado».

El fichero se carga con `pyautogui` y `dotenv` simulados, que es lo único suyo que no
existe fuera de ese PC.
"""
import ast
import importlib.util
import logging
import sys
import types
from pathlib import Path

import pytest
import requests

import main

RUTA_AGENTE = Path(__file__).resolve().parents[2] / "agent" / "agent.py"
JOB_ID = "123e4567-e89b-12d3-a456-426614174000"


@pytest.fixture
def agente(monkeypatch):
    monkeypatch.setitem(sys.modules, "pyautogui", types.ModuleType("pyautogui"))
    dotenv = types.ModuleType("dotenv")
    dotenv.load_dotenv = lambda *a, **k: False
    monkeypatch.setitem(sys.modules, "dotenv", dotenv)
    # Al importarse abre agent.log en el directorio actual y configura el logging raíz:
    # ninguna de las dos cosas tiene que pasar dentro de la suite.
    monkeypatch.setattr(logging, "basicConfig", lambda *a, **k: None)
    monkeypatch.setattr(logging, "FileHandler", lambda *a, **k: logging.NullHandler())
    spec = importlib.util.spec_from_file_location("agente_pc_bajo_prueba", RUTA_AGENTE)
    modulo = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(modulo)
    monkeypatch.setattr(modulo.time, "sleep", lambda _s: None)
    return modulo


# ── alud_url_permitida ──────────────────────────────────────────────────────────

PERMITIDAS = [
    "https://alud.deusto.es/mod/assign/view.php?id=99",
    "https://aulas.alud.deusto.es/x",
    "https://ALUD.deusto.es/mod/assign/view.php?id=99",
    "https://alud.deusto.es:443/mod/assign/view.php?id=99",
]

RECHAZADAS = [
    # Para urlsplit el host es lo que va tras la @; para Edge la barra invertida es una
    # barra, el host acaba ahí y es atacante.example. Es el agujero que se cerró.
    "https://atacante.example\\@alud.deusto.es/mod/assign/view.php?id=1",
    # Para Python el host termina en .alud.deusto.es; para Edge es atacante.example.
    "https://atacante.example\\.alud.deusto.es/",
    # Una URL de Alud no lleva barras invertidas nunca, ni siquiera en la ruta.
    "https://alud.deusto.es/mod\\assign",
    # El navegador se salta tabuladores y saltos de línea; Python no.
    "https://atacante.example\t@alud.deusto.es/",
    "https://atacante.example\n.alud.deusto.es/",
    "https://alud.deusto.es /x",
    # Userinfo: aunque el host sea el bueno, una URL de Alud no lo lleva.
    "https://alud.deusto.es@atacante.com/x",
    "https://usuario:clave@alud.deusto.es/x",
    # Un host con escapes lo normaliza el navegador, no esta función.
    "https://alud%2edeusto.es/x",
    "https://alud.deusto.es.atacante.com/x",
    "https://alud.deusto.es:99999/x",
    "http://alud.deusto.es/x",
    "javascript:alert(1)",
    "",
    None,
]


def _las_dos():
    return [pytest.param("backend", id="backend"), pytest.param("agente", id="agente")]


@pytest.fixture
def permitida(request, agente):
    return main.alud_url_permitida if request.param == "backend" else agente.alud_url_permitida


@pytest.mark.parametrize("permitida", _las_dos(), indirect=True)
class TestAludUrlPermitida:
    @pytest.mark.parametrize("url", PERMITIDAS)
    def test_las_de_alud_pasan(self, permitida, url):
        assert permitida(url)

    @pytest.mark.parametrize("url", RECHAZADAS)
    def test_lo_que_se_lee_de_dos_maneras_no_pasa(self, permitida, url):
        assert not permitida(url)


def _funcion(ruta, nombre):
    arbol = ast.parse(Path(ruta).read_text(encoding="utf-8-sig"))  # main.py lleva BOM
    return next(n for n in arbol.body if isinstance(n, ast.FunctionDef) and n.name == nombre)


def _cuerpo_sin_docstring(nodo):
    cuerpo = nodo.body
    primero = cuerpo[0] if cuerpo else None
    if isinstance(primero, ast.Expr) and isinstance(getattr(primero, "value", None), ast.Constant) \
            and isinstance(primero.value.value, str):
        cuerpo = cuerpo[1:]
    return [ast.dump(n) for n in cuerpo]


class TestLasDosCopiasDicenLoMismo:
    """El backend valida al extraer y al dar de alta el job; el agente, antes de abrir
    Edge. Si una copia se arregla y la otra no, el agujero sigue abierto en la otra."""

    def test_mismo_cuerpo(self):
        assert (_cuerpo_sin_docstring(_funcion(main.__file__, "alud_url_permitida"))
                == _cuerpo_sin_docstring(_funcion(RUTA_AGENTE, "alud_url_permitida")))

    def test_mismo_patron_de_host(self, agente):
        assert agente._ALUD_HOST_RE.pattern == main._ALUD_HOST_RE.pattern


# ── El ciclo de un job ──────────────────────────────────────────────────────────

class _Respuesta:
    def __init__(self, status_code):
        self.status_code = status_code


@pytest.fixture
def ciclo(agente, monkeypatch):
    """procesar_job con el backend simulado. `respuestas[tramo]` es la lista de lo que
    devuelve cada llamada (un código o una excepción); el último valor se repite."""
    llamadas, etapas, hechos, respuestas = [], [], [], {}

    def post(url, headers=None, json=None, timeout=None):
        tramo = url.rsplit("/", 1)[-1]
        llamadas.append((tramo, json))
        cola = respuestas.get(tramo, [200])
        r = cola.pop(0) if len(cola) > 1 else cola[0]
        if isinstance(r, Exception):
            raise r
        return _Respuesta(r)

    monkeypatch.setattr(agente.requests, "post", post)
    monkeypatch.setattr(agente, "claim_job", lambda _id: True)
    monkeypatch.setattr(agente, "report_stage",
                        lambda _id, etapa, mensaje="": etapas.append((etapa, mensaje)))
    monkeypatch.setattr(agente, "heartbeat", lambda *_a, **_k: None)
    monkeypatch.setattr(agente, "resolver_accion", lambda _payload: "prueba")
    monkeypatch.setitem(agente.ACCIONES, "prueba", lambda job_id, _payload: hechos.append(job_id))

    def tramos():
        return [t for t, _ in llamadas]

    def cierres():
        return [cuerpo["status"] for t, cuerpo in llamadas if t == "finish"]

    return types.SimpleNamespace(agente=agente, etapas=etapas, hechos=hechos,
                                 respuestas=respuestas, tramos=tramos, cierres=cierres,
                                 procesar=lambda: agente.procesar_job({"id": JOB_ID, "payload": {}}))


class TestCicloDelJob:
    def test_camino_feliz(self, ciclo):
        ciclo.procesar()
        assert ciclo.hechos == [JOB_ID]
        assert ciclo.tramos() == ["start", "finish"]
        assert ciclo.cierres() == ["done"]
        assert ciclo.etapas[-1] == ("job_done", "done")

    def test_si_no_pasa_a_running_no_se_ejecuta_la_accion(self, ciclo):
        """Antes se ignoraba el 5xx del start, se abría Edge y Cowork igualmente, el
        finish daba 409 (el job seguía en claimed) y el log decía «completado»."""
        ciclo.respuestas["start"] = [502]
        ciclo.procesar()
        assert ciclo.hechos == []
        assert ciclo.tramos().count("start") == 3
        assert ciclo.cierres() == ["failed"]
        assert ciclo.etapas[-1][1].startswith("failed")

    def test_sin_red_en_el_start_no_tumba_al_agente(self, ciclo):
        """Un ConnectionError salía de procesar_job sin capturar y mataba el proceso a
        mitad del drenaje de la cola."""
        ciclo.respuestas["start"] = [requests.ConnectionError("sin red")]
        ciclo.procesar()
        assert ciclo.hechos == []

    def test_un_fallo_puntual_se_reintenta(self, ciclo):
        ciclo.respuestas["start"] = [502, 200]
        ciclo.procesar()
        assert ciclo.hechos == [JOB_ID]
        assert ciclo.tramos().count("start") == 2

    def test_un_409_no_se_reintenta(self, ciclo):
        """Repetirlo no lo arregla: el job no está en el estado que toca."""
        ciclo.respuestas["start"] = [409]
        ciclo.procesar()
        assert ciclo.tramos().count("start") == 1
        assert ciclo.hechos == []

    def test_un_cierre_rechazado_no_se_cuenta_como_completado(self, ciclo):
        ciclo.respuestas["finish"] = [409]
        ciclo.procesar()
        assert ciclo.hechos == [JOB_ID]
        etapa, mensaje = ciclo.etapas[-1]
        assert etapa == "job_done" and mensaje != "done"
        assert "no registró" in mensaje

    def test_la_accion_que_falla_se_cierra_como_fallida(self, ciclo, monkeypatch):
        def revienta(_job_id, _payload):
            raise RuntimeError("Edge no abrió")
        monkeypatch.setitem(ciclo.agente.ACCIONES, "prueba", revienta)
        ciclo.procesar()
        assert ciclo.cierres() == ["failed"]
        assert ciclo.etapas[-1] == ("job_done", "failed: Edge no abrió")
