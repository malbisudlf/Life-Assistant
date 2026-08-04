"""Fixtures compartidas para los tests del backend.

Configura variables de entorno ANTES de importar main (el módulo exige
SECRET_KEY y DASHBOARD_PASSWORD al arrancar) y sustituye todas las llamadas
HTTP salientes (Supabase, Microsoft Graph, Google Maps) por un router de mocks.
"""
import os
import sys

os.environ.setdefault("SECRET_KEY", "test-secret-key")
os.environ.setdefault("DASHBOARD_PASSWORD", "1234")
os.environ.setdefault("OPENAI_API_KEY", "sk-test")
os.environ.setdefault("SUPABASE_URL", "https://supabase.test")
os.environ.setdefault("SUPABASE_KEY", "supa-test-key")
os.environ.setdefault("GOOGLE_MAPS_API_KEY", "maps-test-key")
os.environ.setdefault("HA_POLL_TOKEN", "ha-poll-token")
os.environ.setdefault("HEALTH_INGEST_TOKEN", "health-token")
os.environ.setdefault("HOME_ADDRESS", "Calle Falsa 123, Bilbao")
os.environ.setdefault("BRIEF_TOKEN", "brief-token")
os.environ.setdefault("AGENT_TOKEN", "agent-token")
# El registro persistente escribe en Supabase desde un hilo de fondo. Encendido en los
# tests, ese hilo colaría POSTs a app_logs en el MockRouter de cualquier test que además
# registre un warning, y reventaría los asertos de "cuántas llamadas se hicieron". Los
# tests del registro llaman a _registro.volcar() a mano, que es lo que hace el hilo.
os.environ.setdefault("LOG_PERSIST", "0")

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "backend"))

import pytest
from fastapi.testclient import TestClient

import main


class FakeResponse:
    def __init__(self, json_data=None, status_code=200, text=""):
        self._json = json_data if json_data is not None else []
        self.status_code = status_code
        self.text = text or ""
        self.encoding = "utf-8"

    def json(self):
        return self._json


class MockRouter:
    """Enruta requests.get/post/patch/delete simulados por (método, fragmento de URL)."""

    def __init__(self):
        self.routes = []   # (method, fragment, response_or_callable)
        self.calls = []    # (method, url, kwargs)

    def add(self, method, fragment, response):
        self.routes.append((method.upper(), fragment, response))

    def _dispatch(self, method, url, **kwargs):
        self.calls.append((method, url, kwargs))
        for m, fragment, resp in self.routes:
            if m == method and fragment in url:
                if callable(resp):
                    return resp(url, **kwargs)
                return resp
        # Por defecto: éxito vacío (como Supabase sin filas)
        return FakeResponse([], 200)

    def get(self, url, **kwargs):
        return self._dispatch("GET", url, **kwargs)

    def post(self, url, **kwargs):
        return self._dispatch("POST", url, **kwargs)

    def patch(self, url, **kwargs):
        return self._dispatch("PATCH", url, **kwargs)

    def delete(self, url, **kwargs):
        return self._dispatch("DELETE", url, **kwargs)

    def called(self, method, fragment):
        return [c for c in self.calls if c[0] == method.upper() and fragment in c[1]]


@pytest.fixture
def mock_requests(monkeypatch):
    router = MockRouter()
    # main usa una sesión única (main.http) con timeout por defecto, no requests.* suelto.
    monkeypatch.setattr(main.http, "get", router.get)
    monkeypatch.setattr(main.http, "post", router.post)
    monkeypatch.setattr(main.http, "patch", router.patch)
    monkeypatch.setattr(main.http, "delete", router.delete)
    return router


def _limpiar_estado():
    # Los intentos de login viven en Supabase (login_attempts), no en memoria: no hace
    # falta limpiarlos aquí, cada test que los necesite mockea su propia respuesta.
    with main._rate_lock:
        main._rate_buckets.clear()
    main._wol_pending = False
    main._agent_relaunch_pending = False
    main._pc_power_action = None
    main._token_cache = None
    main._presencia_cache = None
    # El middleware registra todo 4xx/5xx, así que la cola arrastraría entradas de un
    # test al siguiente. `_purgado` también se resetea: es "una purga por proceso".
    with main._registro._lock:
        main._registro._cola.clear()
        main._registro._descartados = 0
    main._registro._purgado = False


@pytest.fixture(autouse=True)
def reset_state():
    """Estado en memoria limpio entre tests (rate limiting, flags WOL/relanzado y las
    copias en memoria del token de Graph y de la presencia)."""
    _limpiar_estado()
    yield
    _limpiar_estado()


@pytest.fixture
def client():
    return TestClient(main.app)


@pytest.fixture
def auth_headers():
    return {"Authorization": f"Bearer {main.create_token()}"}


@pytest.fixture
def graph_token(monkeypatch):
    """Simula sesión de Microsoft Graph activa."""
    monkeypatch.setattr(main, "get_valid_token", lambda: "graph-token")
    return "graph-token"


@pytest.fixture
def login_attempts_mock(mock_requests):
    """Simula la tabla login_attempts de Supabase con una lista en memoria.

    _check_login_rate() ahora consulta Supabase en cada intento; sin este fixture,
    cualquier test que llame a /auth/password intentaría una llamada de red real.
    """
    from datetime import datetime, timezone

    fallos = []

    def _get(url, **kwargs):
        return FakeResponse([{"created_at": t} for t in fallos])

    def _post(url, **kwargs):
        fallos.append(datetime.now(timezone.utc).isoformat())
        return FakeResponse([], 201)

    def _delete(url, **kwargs):
        fallos.clear()
        return FakeResponse([], 204)

    mock_requests.add("GET", "/rest/v1/login_attempts", _get)
    mock_requests.add("POST", "/rest/v1/login_attempts", _post)
    mock_requests.add("DELETE", "/rest/v1/login_attempts", _delete)
    return fallos
