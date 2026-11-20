"""La casa en holograma (2026-11-20).

Lo que se protege: que las plantas y habitaciones sean las de Home Assistant y vayan en
orden, que las habitaciones de los demás salgan como «privado» sin un solo dato ni mando,
que lo privado de siempre (móviles, ubicaciones) no entre, que tocar una habitación vaya por
la puerta de siempre (`_j_casa_ordenar`) y solo con sus luces, y que el panel lo ponga Jarvis.
"""
import json

import pytest

import main
from conftest import FakeResponse

ESTRUCTURA = [
    {"id": "planta_2", "nombre": "Planta 2", "areas": [
        {"id": "cuarto_mikel", "nombre": "Cuarto Mikel", "e": [
            ["light.flexo", "", "Flexo"], ["light.techo_mikel", "", "Techo"],
            ["sensor.temp_mikel", "temperature", "Temperatura"],
            ["binary_sensor.mov_mikel", "motion", "Movimiento"],
            ["sensor.iphone_de_mikel_ubicacion", "", "Ubicación del iPhone"]]},
        {"id": "cuarto_iker", "nombre": "Cuarto Iker", "e": [["light.iker", "", "Luz Iker"]]}]},
    {"id": "planta_0", "nombre": "Planta 0", "areas": [
        {"id": "garaje", "nombre": "Garaje", "e": [["binary_sensor.puerta_garaje", "garage_door", "Puerta"]]}]},
]
ESTADOS = {"light.flexo": "on", "light.techo_mikel": "off", "sensor.temp_mikel": "21.43",
           "binary_sensor.mov_mikel": "on", "light.iker": "on", "binary_sensor.puerta_garaje": "on"}


@pytest.fixture
def casa(monkeypatch, mock_requests):
    monkeypatch.setattr(main, "HA_URL", "http://ha.test:8123")
    monkeypatch.setattr(main, "HA_TOKEN", "ha-token")
    monkeypatch.setattr(main, "_ha_directo", lambda: True)
    monkeypatch.setattr(main, "CASA_HOLO_OTROS", ["iker", "ane"])
    monkeypatch.setattr(main, "_casa_holo_cache", {"ts": 0.0, "pisos": None})
    monkeypatch.setattr(main, "_ha_estados_vivos", lambda: (ESTADOS, 1763700000.0))
    monkeypatch.setattr(main, "_hud_paneles", [])
    mock_requests.add("POST", "/api/template", FakeResponse(None, 200, text=json.dumps(ESTRUCTURA)))
    return mock_requests


class TestLaMaqueta:
    def test_plantas_en_orden_y_lo_que_pasa_en_cada_habitacion(self, casa):
        r = main._casa_holograma()
        assert r["ok"] is True and [p["nivel"] for p in r["pisos"]] == [0, 2]
        mikel = next(a for a in r["pisos"][1]["areas"] if a["id"] == "cuarto_mikel")
        assert mikel["luces_on"] == 1 and len(mikel["luces"]) == 2
        assert mikel["temp"] == 21.4 and mikel["presencia"] is True
        garaje = r["pisos"][0]["areas"][0]
        assert garaje["abiertas"] == 1 and garaje["luces"] == []

    def test_lo_de_los_demas_es_privado_y_sin_datos(self, casa):
        r = main._casa_holograma()
        iker = next(a for a in r["pisos"][1]["areas"] if a["id"] == "cuarto_iker")
        assert iker == {"id": "cuarto_iker", "nombre": "Cuarto Iker", "privado": True}

    def test_lo_privado_de_siempre_no_entra(self, casa):
        assert "iphone" not in json.dumps(main._casa_holograma())

    def test_la_estructura_se_guarda_un_rato(self, casa):
        main._casa_holograma()
        main._casa_holograma()
        assert len(casa.called("POST", "/api/template")) == 1

    def test_sin_ha_lo_dice(self, casa, monkeypatch):
        monkeypatch.setattr(main, "_ha_directo", lambda: False)
        assert main._casa_holograma()["ok"] is False

    def test_la_plantilla_usa_las_plantas_y_areas_de_ha(self):
        for trozo in ("floors()", "floor_areas(f)", "area_entities(a)", "tojson"):
            assert trozo in main._CASA_HOLO_PLANTILLA


class TestTocar:
    def test_enciende_sus_luces_por_la_puerta_de_siempre(self, casa, client, auth_headers, monkeypatch):
        pedidas = []
        monkeypatch.setattr(main, "_j_casa_ordenar", lambda s, e, d=None: pedidas.append((s, e)) or {"ok": True})
        r = client.post("/casa/holograma/luces", headers=auth_headers, json={"area": "cuarto_mikel", "encender": True})
        assert r.status_code == 200 and r.json()["hechas"] == 2
        assert pedidas == [("light.turn_on", "light.flexo"), ("light.turn_on", "light.techo_mikel")]

    def test_la_de_otro_no_se_toca(self, casa, client, auth_headers, monkeypatch):
        monkeypatch.setattr(main, "_j_casa_ordenar", lambda *a, **k: pytest.fail("no toca"))
        r = client.post("/casa/holograma/luces", headers=auth_headers, json={"area": "cuarto_iker", "encender": False})
        assert r.status_code == 403

    def test_una_que_no_existe_o_mal_escrita(self, casa, client, auth_headers):
        assert client.post("/casa/holograma/luces", headers=auth_headers,
                           json={"area": "trastero", "encender": True}).status_code == 404
        assert client.post("/casa/holograma/luces", headers=auth_headers,
                           json={"area": "../x", "encender": True}).status_code == 422

    def test_pide_sesion(self, client):
        assert client.post("/casa/holograma/luces", json={"area": "garaje", "encender": True}).status_code in (401, 403)


class TestElPanel:
    def test_jarvis_la_pone_en_la_vista(self, casa):
        assert main._j_casa_holograma()["ok"] is True
        panel, = main._hud_paneles
        assert panel["tipo"] == "casa" and panel["fuentes"] == ["casa"]
        datos = main._hud_datos("casa")
        assert datos["clase"] == "casa" and datos["ok"] is True

    def test_tambien_con_hud_panel(self, casa):
        assert main._j_hud_panel("casa", "Mi casa")["ok"] is True
        assert main._hud_paneles[0]["tipo"] == "casa"
