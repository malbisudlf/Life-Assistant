"""Tests del modo coche: el Atajo de iOS de CarPlay pide una llamada en escucha pasiva.

Lo que importa no es que llame, que es una línea, sino lo que NO hace: no insiste si no lo
coges, no deja recado en el buzón, no llama dos veces por reconectar el coche en un
semáforo, y no deja pasar a nadie sin el token del iPhone.
"""
import pytest

import main
from conftest import FakeResponse

CENTRALITA = "/api/outbound-call"
CABECERA = {"X-Auth-Token": "health-token"}


@pytest.fixture(autouse=True)
def _configurado(monkeypatch):
    monkeypatch.setattr(main, "TELEFONO_URL", "http://centralita.test:3010")
    monkeypatch.setattr(main, "TELEFONO_EXTENSION", "11410")
    monkeypatch.setattr(main, "_modo_coche_ultima", {"ts": 0.0})


def _centralita(mock_requests, estado=200):
    lanzadas = []

    def _post(url, **kw):
        lanzadas.append(kw["json"])
        return FakeResponse({"success": True, "callId": "c1"}, estado)

    mock_requests.add("POST", CENTRALITA, _post)
    return lanzadas


def test_sin_token_no_entra_nadie(client, mock_requests):
    lanzadas = _centralita(mock_requests)
    assert client.post("/telefono/modo-coche").status_code == 403
    assert client.post("/telefono/modo-coche", headers={"X-Auth-Token": "otro"}).status_code == 403
    assert lanzadas == []


def test_pide_la_llamada_en_escucha_pasiva(client, mock_requests, monkeypatch):
    insistir = []
    monkeypatch.setattr(main, "_insistir_en_segundo_plano", lambda *a: insistir.append(a))
    lanzadas = _centralita(mock_requests)
    r = client.post("/telefono/modo-coche", headers=CABECERA)
    assert r.status_code == 200
    assert r.json() == {"ok": True, "llamada": True, "callId": "c1"}
    [cuerpo] = lanzadas
    assert cuerpo["escuchaPasiva"] is True and cuerpo["mode"] == "conversation"
    assert cuerpo["to"] == "11410" and "Jarvis" in cuerpo["message"]
    # Si descuelga el buzón, se cuelga en el acto: ni recado ni tres horas escuchándolo.
    assert cuerpo["detectVoicemail"] is True and "voicemailMessage" not in cuerpo
    # Y si no lo coges, nada: lo pediste tú y no lo quieres ahora.
    assert insistir == []


def test_no_mira_si_estas_despierto(client, mock_requests, monkeypatch):
    """Lo pides tú al arrancar el coche, como «Hablarlo»: no hay puerta que mirar."""
    monkeypatch.setattr(main, "_telefono_puede_sonar", lambda ahora: (False, "franja nocturna"))
    lanzadas = _centralita(mock_requests)
    assert client.post("/telefono/modo-coche", headers=CABECERA).json()["llamada"] is True
    assert len(lanzadas) == 1


def test_reconectar_el_coche_no_vuelve_a_llamar(client, mock_requests):
    lanzadas = _centralita(mock_requests)
    client.post("/telefono/modo-coche", headers=CABECERA)
    r = client.post("/telefono/modo-coche", headers=CABECERA)
    assert r.status_code == 200
    assert r.json()["llamada"] is False and "no repito" in r.json()["motivo"]
    assert len(lanzadas) == 1


def test_si_la_centralita_falla_lo_dice_y_no_cuenta_la_pausa(client, mock_requests):
    _centralita(mock_requests, estado=503)
    r = client.post("/telefono/modo-coche", headers=CABECERA)
    assert r.status_code == 502
    # Al reintentar (otra conexión del coche), vuelve a probar en vez de decir «ya te llamé».
    assert main._modo_coche_ultima["ts"] == 0.0


def test_sin_centralita_configurada_dice_que_falta(client, mock_requests, monkeypatch):
    monkeypatch.setattr(main, "TELEFONO_URL", "")
    r = client.post("/telefono/modo-coche", headers=CABECERA)
    assert r.status_code == 503 and "TELEFONO_URL" in r.json()["detail"]
