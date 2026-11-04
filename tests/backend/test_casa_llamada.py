"""La casa desde la llamada: leer en vivo sin datos de la familia, los Echo y los reflejos."""
from datetime import datetime

import pytest

import main
from conftest import FakeResponse


def _x(i, estado="on", **attrs):
    return {"entity_id": i, "state": estado, "attributes": attrs}


ESTADOS = [
    _x("climate.hab_mikel", "auto", friendly_name="Hab Mikel", current_temperature=22, temperature=20),
    _x("climate.cocina", "auto", friendly_name="Cocina", current_temperature=18, temperature=20),
    _x("sensor.lavadora_consumo", "12", friendly_name="Lavadora", unit_of_measurement="W"),
    _x("alarm_control_panel.casa", "disarmed", friendly_name="Casa"),
    _x("light.luces_mesa", "off", friendly_name="Luces mesa"),
    _x("switch.luces_jardin", "off", friendly_name="Luces Jardin"),
    # Lo que no puede salir
    _x("person.saioa", "home", friendly_name="Saioa"),
    _x("device_tracker.iphone_de_marco", "not_home", friendly_name="iPhone de Marco"),
    _x("sensor.iphone_15_saioa_battery", "90", friendly_name="iPhone 15 Saioa batería"),
    _x("sensor.marco_de_fotos_location", "x", friendly_name="ubicación"),
    _x("todo.aalbisuc_hotmail_com_libros", "17", friendly_name="Libros"),
]


@pytest.fixture
def ha(monkeypatch, mock_requests):
    monkeypatch.setattr(main, "HA_URL", "http://ha.test:8123")
    monkeypatch.setattr(main, "HA_TOKEN", "t")
    mock_requests.add("GET", "/api/states", FakeResponse(ESTADOS))
    return mock_requests


class TestLeer:
    def test_vacio_da_calefaccion_y_alarma(self, ha):
        r = main._j_casa_leer()
        ids = {x["id"] for x in r["lecturas"]}
        assert ids == {"climate.hab_mikel", "climate.cocina", "alarm_control_panel.casa"}
        z = next(x for x in r["lecturas"] if x["id"] == "climate.hab_mikel")
        assert (z["actual"], z["objetivo"]) == (22, 20)

    def test_busca_y_da_la_unidad(self, ha):
        r = main._j_casa_leer("lavadora")
        assert r["lecturas"][0]["unidad"] == "W"

    @pytest.mark.parametrize("buscar", ["saioa", "marco", "iphone", "libros", "ubicación"])
    def test_nunca_lo_de_la_familia(self, ha, buscar):
        r = main._j_casa_leer(buscar)
        assert all("saioa" not in x["id"] and "iphone" not in x["id"] and "person" not in x["id"]
                   and "todo." not in x["id"] and "location" not in x["id"] for x in r["lecturas"])

    def test_sin_token(self, monkeypatch):
        monkeypatch.setattr(main, "HA_TOKEN", "")
        assert main._j_casa_leer()["ok"] is False


class TestMapa:
    def test_trae_ids_y_temperaturas(self, ha):
        t = main._contexto_casa()
        assert "climate.hab_mikel 22°→20°" in t
        assert "switch.luces_jardin off" in t and "light.luces_mesa off" in t
        assert "Alarma: disarmed" in t

    def test_sin_familia(self, ha):
        t = main._contexto_casa()
        assert "saioa" not in t.lower() and "iphone" not in t.lower()

    def test_si_falla_calla(self, ha, monkeypatch):
        monkeypatch.setattr(main.http, "get", lambda *a, **k: FakeResponse({}, status_code=500))
        assert main._contexto_casa() == ""


class TestAnunciar:
    @pytest.fixture(autouse=True)
    def _de_dia(self, monkeypatch):
        monkeypatch.setattr(main, "_ahora_local", lambda: datetime(2026, 11, 4, 18, 0))

    def test_dice_en_el_echo(self, ha):
        r = main._j_casa_anunciar("La cena está lista", "la cocina")
        assert r["ok"] is True and r["dicho_en"] == ["cocina"]
        c = ha.called("POST", "notify/send_message")[0]
        assert c[2]["json"] == {"entity_id": "notify.cocina_hablar", "message": "La cena está lista"}

    def test_toda_la_casa(self, ha):
        r = main._j_casa_anunciar("Hola", "toda la casa")
        assert len(r["dicho_en"]) == 6

    def test_lugar_desconocido(self, ha):
        assert main._j_casa_anunciar("Hola", "la luna")["ok"] is False
        assert not ha.called("POST", "notify/send_message")

    def test_de_noche_solo_en_su_cuarto(self, ha, monkeypatch):
        monkeypatch.setattr(main, "_ahora_local", lambda: datetime(2026, 11, 4, 23, 30))
        assert main._j_casa_anunciar("Hola", "cocina")["ok"] is False
        assert main._j_casa_anunciar("Hola", "toda la casa")["ok"] is False
        assert main._j_casa_anunciar("Hola", "mi cuarto")["ok"] is True

    def test_sin_texto(self, ha):
        assert main._j_casa_anunciar("  ", "cocina")["ok"] is False


class TestCatalogo:
    def test_el_ruido_no_tapa_lo_util(self, monkeypatch):
        lista = [{"id": f"switch.echo{i}_no_molestar", "nombre": "x", "estado": "off"} for i in range(60)]
        lista.append({"id": "switch.luces_jardin", "nombre": "Luces", "estado": "off"})
        monkeypatch.setattr(main, "_casa_entidades_al_dia", lambda: (lista, "vivo", None))
        assert [e["id"] for e in main._j_casa_dispositivos()["dispositivos"]] == ["switch.luces_jardin"]

    def test_por_su_nombre_si_sale(self, monkeypatch):
        lista = [{"id": "switch.cocina_no_molestar", "nombre": "No molestar", "estado": "off"}]
        monkeypatch.setattr(main, "_casa_entidades_al_dia", lambda: (lista, "vivo", None))
        assert main._j_casa_dispositivos("molestar")["dispositivos"]


class TestRutaTelefono:
    def _cliente(self, monkeypatch):
        from fastapi.testclient import TestClient
        monkeypatch.setattr(main, "JARVIS_MCP_TELEFONO_TOKEN", "llave-del-telefono")
        return TestClient(main.app)

    def test_sin_llave_no(self, monkeypatch):
        r = self._cliente(monkeypatch).post("/telefono/casa", json={"servicio": "switch.turn_off", "entidad": "switch.x"})
        assert r.status_code == 401

    def test_lo_delicado_no_pasa(self, monkeypatch):
        llamadas = []
        monkeypatch.setattr(main, "_j_casa_ordenar", lambda *a: llamadas.append(a) or {"ok": True})
        r = self._cliente(monkeypatch).post("/telefono/casa", headers={"X-Auth-Token": "llave-del-telefono"},
                                            json={"servicio": "script.turn_on", "entidad": "script.quitar_alarm_script"})
        assert r.json()["ok"] is False and not llamadas

    def test_ejecuta(self, monkeypatch):
        monkeypatch.setattr(main, "_j_casa_ordenar", lambda s, e, d: {"ok": True, "s": s, "e": e, "d": d})
        r = self._cliente(monkeypatch).post("/telefono/casa", headers={"X-Auth-Token": "llave-del-telefono"},
                                            json={"servicio": "climate.set_temperature", "entidad": "climate.cocina",
                                                  "datos": {"temperature": 21}})
        assert r.json()["d"] == {"temperature": 21}
