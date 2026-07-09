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
    monkeypatch.setattr(main.requests, "get", router.get)
    monkeypatch.setattr(main.requests, "post", router.post)
    monkeypatch.setattr(main.requests, "patch", router.patch)
    monkeypatch.setattr(main.requests, "delete", router.delete)
    return router


@pytest.fixture(autouse=True)
def reset_state():
    """Estado en memoria limpio entre tests (rate limiting y flag WOL)."""
    with main._login_lock:
        main._login_attempts.clear()
    main._wol_pending = False
    yield
    with main._login_lock:
        main._login_attempts.clear()
    main._wol_pending = False


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
