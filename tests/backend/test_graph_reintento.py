"""Graph responde 429 ApplicationThrottled en picos: las lecturas se reintentan."""
import requests

import main


class _R:
    def __init__(self, code, headers=None):
        self.status_code = code
        self.headers = headers or {}


def _sesion(monkeypatch, codigos):
    llamadas, esperas = [], []
    cola = list(codigos)

    def falso(self, method, url, **kw):
        llamadas.append((method, url))
        return _R(cola.pop(0), {"Retry-After": "1"})

    monkeypatch.setattr(requests.Session, "request", falso)
    monkeypatch.setattr(main.time, "sleep", esperas.append)
    return main._SesionConTimeout(), llamadas, esperas


def test_get_a_graph_se_reintenta_tras_429(monkeypatch):
    s, llamadas, esperas = _sesion(monkeypatch, [429, 200])
    assert s.get("https://graph.microsoft.com/v1.0/me/calendars").status_code == 200
    assert len(llamadas) == 2 and esperas == [1.0]


def test_el_reintento_tiene_tope(monkeypatch):
    s, llamadas, _ = _sesion(monkeypatch, [429, 429, 429])
    assert s.get("https://graph.microsoft.com/v1.0/me/calendars").status_code == 429
    assert len(llamadas) == 1 + main.GRAPH_REINTENTOS


def test_post_y_otros_hosts_no_se_reintentan(monkeypatch):
    s, llamadas, _ = _sesion(monkeypatch, [429])
    assert s.post("https://graph.microsoft.com/v1.0/me/calendars").status_code == 429
    s, llamadas, _ = _sesion(monkeypatch, [429])
    assert s.get("https://example.com/x").status_code == 429
    assert len(llamadas) == 1
