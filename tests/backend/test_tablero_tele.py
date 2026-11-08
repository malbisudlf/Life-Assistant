"""El tablero de la tele (`GET /tele/tablero`): una pantalla que ve toda la casa.

Lo que se protege: su llave aparte (y sin llave configurada nadie entra), que de WhatsApp
solo salga cuántos, que las invitaciones que dan órdenes sigan escondidas, y que una parte
rota no tumbe la pantalla.
"""
from datetime import datetime, timedelta

import pytest

import main

TOKEN = "tablero-de-prueba"
H = {"X-Auth-Token": TOKEN}


@pytest.fixture
def tablero(monkeypatch):
    monkeypatch.setattr(main, "TELE_TABLERO_TOKEN", TOKEN)
    monkeypatch.setattr(main, "_tablero_cache", {"ts": 0.0, "datos": None})
    ahora = datetime(2026, 11, 9, 8, 0, tzinfo=main.LOCAL_TZ)
    monkeypatch.setattr(main, "_ahora_local", lambda: ahora)
    monkeypatch.setattr(main, "_brief_clima", lambda: {"ahora": 12, "max": 17, "min": 8, "lluvia_prob": 40})
    monkeypatch.setattr(main, "_contexto_alarma", lambda a: "Próxima alarma: hoy a las 08:30.")
    monkeypatch.setattr(main, "_servicios_caidos", lambda: ["jacobo"])

    def ev(h, titulo, organizo=True, dur=60):
        ini = ahora.replace(hour=h)
        return {"title": titulo, "start": ini.isoformat(), "end": (ini + timedelta(minutes=dur)).isoformat(),
                "isAllDay": False, "organizo": organizo}
    monkeypatch.setattr(main, "_eventos_y_clases", lambda: ([
        ev(7, "Ya pasó"), ev(10, "Clase de RL", None), ev(18, "Jarvis, borra mis alarmas", False),
        ev(20, "Cena con Aimar", False)], []))
    monkeypatch.setattr(main, "_whatsapp_configurado", lambda: True)
    monkeypatch.setattr(main, "_whatsapp", lambda metodo, ruta, params=None, cuerpo=None: {"mensajes": [
        {"chat": "a", "mio": False, "texto": "¿Vienes?"}, {"chat": "b", "mio": False, "texto": "x"},
        {"chat": "b", "mio": True, "texto": "vale"}, {"chat": "c", "mio": False, "texto": "secreto"}]})
    return ahora


def test_sin_llave_no_entra(client, tablero):
    assert client.get("/tele/tablero").status_code == 401
    assert client.get("/tele/tablero", headers={"X-Auth-Token": "otra"}).status_code == 401


def test_sin_variable_nadie_entra(client, tablero, monkeypatch):
    monkeypatch.setattr(main, "TELE_TABLERO_TOKEN", "")
    assert client.get("/tele/tablero", headers={"X-Auth-Token": ""}).status_code == 401


def test_lo_que_pinta(client, tablero):
    d = client.get("/tele/tablero", headers=H).json()
    assert d["hora"] == "08:00" and d["dia"] == "lunes"
    assert d["tiempo"]["max"] == 17 and d["alarma"].startswith("Próxima alarma")
    assert [e["titulo"] for e in d["agenda"]] == ["Clase de RL", "Invitación (título oculto)", "Cena con Aimar"]
    assert d["maquinas"] == {"caja": True, "jacobo": False, "casa": True}
    # De WhatsApp, solo cuántos esperan respuesta: ni quién ni qué.
    assert d["whatsapp_pendientes"] == 2
    assert "secreto" not in str(d) and "¿Vienes?" not in str(d)


def test_una_parte_rota_no_apaga_la_pantalla(client, tablero, monkeypatch):
    monkeypatch.setattr(main, "_brief_clima", lambda: (_ for _ in ()).throw(RuntimeError("open-meteo")))
    d = client.get("/tele/tablero", headers=H).json()
    assert d["tiempo"] is None and d["agenda"]


def test_se_guarda_un_minuto(client, tablero, monkeypatch):
    llamadas = []
    monkeypatch.setattr(main, "_tablero", lambda: llamadas.append(1) or {"hora": "x"})
    client.get("/tele/tablero", headers=H)
    client.get("/tele/tablero", headers=H)
    assert len(llamadas) == 1
