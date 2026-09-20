"""«Hablarlo» en el aviso de una sesión de Claude Code: hace sonar el teléfono.

Hermano de `test_revision_hablar.py`. No es un cierre del aviso —eso lo sigue haciendo
«Vale», con su PATCH condicional— así que no toca `estado` y se puede pulsar más de una
vez.
"""
from conftest import FakeResponse

import main

UN_UUID = "11111111-2222-3333-4444-555555555555"
BOTON = {"X-Auth-Token": "ha-poll-token"}

_FILA = {"id": UN_UUID, "titulo": "He tocado el brief", "pedido": "arreglar el sueño",
         "hecho": "cambié el cálculo de sleepScore", "pendiente": "desplegarlo",
         "bloqueado": False}


def _pendiente(mock_requests, filas=None):
    mock_requests.add("GET", "sesion_avisos", FakeResponse([_FILA] if filas is None else filas))


class TestElBotonDeHablar:
    def test_arma_el_contexto_y_llama(self, client, mock_requests, monkeypatch):
        _pendiente(mock_requests)
        llamadas = []
        monkeypatch.setattr(main, "_llamar",
                            lambda texto, rid="", contexto="":
                                llamadas.append((texto, rid, contexto)) or True)
        r = client.post(f"/sesion/{UN_UUID}/accion",
                        json={"accion": "hablar"}, headers=BOTON)
        assert r.status_code == 200 and r.json() == {"ok": True, "accion": "hablar"}
        assert len(llamadas) == 1
        texto, rid, contexto = llamadas[0]
        assert rid == UN_UUID
        assert texto == main._apertura_sesion(_FILA)
        assert "AVISO_DE_LA_SESION" in contexto
        assert "desplegarlo" in contexto

    def test_no_toca_el_estado(self, client, mock_requests, monkeypatch):
        _pendiente(mock_requests)
        monkeypatch.setattr(main, "_llamar", lambda *a, **k: True)
        client.post(f"/sesion/{UN_UUID}/accion", json={"accion": "hablar"}, headers=BOTON)
        assert not mock_requests.called("PATCH", "sesion_avisos")

    def test_sin_nada_pendiente_da_404(self, client, mock_requests, monkeypatch):
        _pendiente(mock_requests, filas=[])
        monkeypatch.setattr(main, "_llamar", lambda *a, **k: True)
        r = client.post(f"/sesion/{UN_UUID}/accion",
                        json={"accion": "hablar"}, headers=BOTON)
        assert r.status_code == 404

    def test_una_accion_invalida_sigue_dando_422(self, client, mock_requests):
        r = client.post(f"/sesion/{UN_UUID}/accion",
                        json={"accion": "desplegar"}, headers=BOTON)
        assert r.status_code == 422
        assert not mock_requests.called("PATCH", "sesion_avisos")

    def test_exige_credencial(self, client):
        r = client.post(f"/sesion/{UN_UUID}/accion", json={"accion": "hablar"})
        assert r.status_code == 403
