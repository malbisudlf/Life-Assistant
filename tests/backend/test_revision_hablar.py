"""«Hablarlo» en un hallazgo de revisión/vigilante: hace sonar el teléfono con Jarvis-Claude.

No es una decisión — no compite con «Arreglarlo»/«No hacer nada», no toca `estado`, y se
puede pulsar varias veces sin que pase nada raro. Lo único que hace es armar el contexto
que ya usa la pantalla del navegador (`_jarvis_contexto_llamada`) y pasárselo a `_llamar`.
"""
import pytest

from conftest import FakeResponse

import main

UN_UUID = "fa27dab6-f054-5982-bd86-994e5e8b151b"
CABECERA = {"X-Auth-Token": "ha-poll-token"}

_FILA = {"id": UN_UUID, "origen": "vigilante", "issue_numero": 0, "issue_url": "",
         "issue_titulo": "5 errores", "detalle": "5 errores\n· 1× Graph"}


def _pendiente(mock_requests, filas=None):
    mock_requests.add("GET", "/rest/v1/revision_hallazgos",
                      FakeResponse([_FILA] if filas is None else filas))


class TestElBotonDeHablar:
    def test_arma_el_contexto_y_llama(self, client, mock_requests, monkeypatch):
        _pendiente(mock_requests)
        llamadas = []
        monkeypatch.setattr(main, "_llamar",
                            lambda texto, rid="", contexto="":
                                llamadas.append((texto, rid, contexto)) or True)
        r = client.post(f"/revision/{UN_UUID}/accion",
                        json={"accion": "hablar"}, headers=CABECERA)
        assert r.status_code == 200 and r.json() == {"ok": True, "accion": "hablar"}
        assert len(llamadas) == 1
        texto, rid, contexto = llamadas[0]
        assert rid == UN_UUID
        assert texto == main._apertura_revision(_FILA)
        assert "REVISION_PENDIENTE" in contexto
        assert "1× Graph" in contexto

    def test_no_toca_el_estado(self, client, mock_requests, monkeypatch):
        """A diferencia de «arreglar»/«nada», esto no es un PATCH condicional."""
        _pendiente(mock_requests)
        monkeypatch.setattr(main, "_llamar", lambda *a, **k: True)
        client.post(f"/revision/{UN_UUID}/accion",
                    json={"accion": "hablar"}, headers=CABECERA)
        assert not mock_requests.called("PATCH", "revision_hallazgos")

    def test_sin_nada_pendiente_da_404(self, client, mock_requests, monkeypatch):
        _pendiente(mock_requests, filas=[])
        monkeypatch.setattr(main, "_llamar", lambda *a, **k: True)
        r = client.post(f"/revision/{UN_UUID}/accion",
                        json={"accion": "hablar"}, headers=CABECERA)
        assert r.status_code == 404

    def test_si_el_telefono_no_contesta_lo_dice_sin_reventar(self, client, mock_requests,
                                                              monkeypatch):
        """`_llamar` ya absorbe sus propios fallos; este endpoint solo refleja el `ok`."""
        _pendiente(mock_requests)
        monkeypatch.setattr(main, "_llamar", lambda *a, **k: False)
        r = client.post(f"/revision/{UN_UUID}/accion",
                        json={"accion": "hablar"}, headers=CABECERA)
        assert r.status_code == 200 and r.json()["ok"] is False

    def test_una_accion_invalida_sigue_dando_422(self, client, mock_requests):
        r = client.post(f"/revision/{UN_UUID}/accion",
                        json={"accion": "despliega"}, headers=CABECERA)
        assert r.status_code == 422
        assert not mock_requests.called("PATCH", "revision_hallazgos")

    def test_exige_credencial(self, client):
        r = client.post(f"/revision/{UN_UUID}/accion", json={"accion": "hablar"})
        assert r.status_code == 403
