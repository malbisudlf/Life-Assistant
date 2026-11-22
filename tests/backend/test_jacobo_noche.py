"""Tests de «jacobo de noche»: caja apaga jacobo desde las 00:30 y el reloj de la placa lo
enciende antes de que Mikel se levante.

Lo que se protege: la hora de despertar (la alarma, la costumbre o la de por defecto, con su
margen y sus topes), que no se apague con una llamada o una peli en marcha, que la llave
sea la de los scripts de caja, y que mientras duerme a propósito el vigilante no llame por
una caída que no lo es (y que pasada la ventana, sí).
"""
from datetime import datetime, timedelta, timezone

import pytest

import main
from conftest import FakeResponse

TOKEN = "token-de-jacobo"
H = {"X-Auth-Token": TOKEN}
TZ = main.LOCAL_TZ


def _noche(dia=21, h=0, m=30):
    # El 2026-11-21 es sábado: la mañana que viene (22) es domingo.
    return datetime(2026, 11, dia, h, m, tzinfo=TZ)


@pytest.fixture
def jacobo(monkeypatch, mock_requests):
    monkeypatch.setattr(main, "JACOBO_NOCHE_TOKEN", TOKEN)
    monkeypatch.setattr(main, "REVISION_TOKEN", "token-de-caja")
    monkeypatch.setattr(main, "JACOBO_NOCHE", True)
    monkeypatch.setattr(main, "JACOBO_DESPIERTA_DEFECTO", "08:00")
    monkeypatch.setattr(main, "JACOBO_MARGEN_MIN", 15)
    monkeypatch.setattr(main, "TELEFONO_URL", "http://voz.prueba:3010")
    monkeypatch.setattr(main, "_jellyfin_configurado", lambda: False)
    monkeypatch.setattr(main, "_jacobo_hasta", {"cargado": False, "hasta": None})
    monkeypatch.setattr(main, "_alarma_leer_vivas", lambda: [])
    mock_requests.add("GET", "/api/calls", FakeResponse({"success": True, "count": 0, "calls": []}))
    return mock_requests


def _despertares(*filas):
    return FakeResponse([{"fecha": f, "primera_senal_at": t} for f, t in filas])


class TestHoraDeDespertar:
    def test_sin_nada_la_de_por_defecto(self, jacobo):
        cuando, porque = main._jacobo_hora_despertar(_noche())
        assert cuando == datetime(2026, 11, 21, 8, 0, tzinfo=TZ)
        assert porque == "la hora por defecto"

    def test_antes_de_medianoche_es_la_mañana_siguiente(self, jacobo):
        cuando, _ = main._jacobo_hora_despertar(_noche(21, 23, 50))
        assert cuando.date().isoformat() == "2026-11-22"

    def test_la_alarma_menos_el_margen(self, jacobo, monkeypatch):
        monkeypatch.setattr(main, "_alarma_leer_vivas", lambda: [
            {"cuando": "2026-11-21T07:30:00+01:00", "saltar": False},
            {"cuando": "2026-11-21T06:00:00+01:00", "saltar": True},
            {"cuando": "2026-11-23T06:00:00+01:00", "saltar": False}])
        cuando, porque = main._jacobo_hora_despertar(_noche())
        assert cuando == datetime(2026, 11, 21, 7, 15, tzinfo=TZ)
        assert porque == "la alarma de las 07:30"

    def test_la_costumbre_de_los_dias_como_ese(self, jacobo):
        # La mañana del 21 es sábado: cuentan los fines de semana (7, 8, 14 y 15 de nov), no
        # los laborables, que se levanta antes. El cuartil bajo de cuatro es la primera.
        jacobo.add("GET", "/rest/v1/despertares", _despertares(
            ("2026-11-07", "2026-11-07T09:40:00+01:00"), ("2026-11-08", "2026-11-08T10:10:00+01:00"),
            ("2026-11-14", "2026-11-14T09:20:00+01:00"), ("2026-11-15", "2026-11-15T11:00:00+01:00"),
            ("2026-11-17", "2026-11-17T07:00:00+01:00"), ("2026-11-18", "2026-11-18T07:05:00+01:00")))
        cuando, porque = main._jacobo_hora_despertar(_noche())
        assert porque == "suele levantarse a las 09:20"
        assert cuando == datetime(2026, 11, 21, 9, 5, tzinfo=TZ)

    def test_con_pocos_dias_no_hay_costumbre(self, jacobo):
        jacobo.add("GET", "/rest/v1/despertares", _despertares(
            ("2026-11-14", "2026-11-14T09:20:00+01:00"), ("2026-11-15", "2026-11-15T11:00:00+01:00")))
        assert main._jacobo_hora_despertar(_noche())[1] == "la hora por defecto"

    def test_manda_la_mas_temprana(self, jacobo, monkeypatch):
        jacobo.add("GET", "/rest/v1/despertares", _despertares(
            ("2026-11-07", "2026-11-07T09:40:00+01:00"), ("2026-11-14", "2026-11-14T09:20:00+01:00"),
            ("2026-11-15", "2026-11-15T10:00:00+01:00")))
        monkeypatch.setattr(main, "_alarma_leer_vivas", lambda: [{"cuando": "2026-11-21T10:30:00+01:00"}])
        assert main._jacobo_hora_despertar(_noche())[1] == "suele levantarse a las 09:20"

    def test_los_topes(self, jacobo, monkeypatch):
        monkeypatch.setattr(main, "_alarma_leer_vivas", lambda: [{"cuando": "2026-11-21T04:00:00+01:00"}])
        assert main._jacobo_hora_despertar(_noche())[0] == datetime(2026, 11, 21, 5, 0, tzinfo=TZ)
        monkeypatch.setattr(main, "_alarma_leer_vivas", lambda: [])
        monkeypatch.setattr(main, "JACOBO_DESPIERTA_DEFECTO", "13:00")
        assert main._jacobo_hora_despertar(_noche())[0] == datetime(2026, 11, 21, 11, 0, tzinfo=TZ)

    def test_si_las_alarmas_fallan_sigue(self, jacobo, monkeypatch):
        def roto():
            raise RuntimeError("supabase caído")
        monkeypatch.setattr(main, "_alarma_leer_vivas", roto)
        jacobo.add("GET", "/rest/v1/despertares", FakeResponse({}, 503))
        assert main._jacobo_hora_despertar(_noche())[1] == "la hora por defecto"


class TestRuta:
    def test_pide_la_llave_de_jacobo(self, client, jacobo):
        assert client.post("/jacobo/noche").status_code == 401
        # La de los scripts de caja no apaga jacobo: solo pregunta el estado.
        assert client.post("/jacobo/noche", headers={"X-Auth-Token": "token-de-caja"}).status_code == 401

    def test_el_estado_para_el_latido_de_caja(self, client, jacobo):
        assert client.get("/jacobo/noche/estado").status_code == 401
        main._jacobo_hasta.update(cargado=True, hasta=datetime.now(timezone.utc) + timedelta(hours=5))
        d = client.get("/jacobo/noche/estado", headers={"X-Auth-Token": "token-de-caja"}).json()
        assert d["durmiendo"] is True and d["hasta"]
        main._jacobo_hasta.update(hasta=None)
        assert client.get("/jacobo/noche/estado", headers=H).json() == {"durmiendo": False, "hasta": None}

    def test_se_apaga_y_apunta_la_ventana(self, client, jacobo, monkeypatch):
        monkeypatch.setattr(main, "_jacobo_hora_despertar",
                            lambda ahora: (datetime(2026, 11, 22, 7, 45, tzinfo=TZ), "la hora por defecto"))
        d = client.post("/jacobo/noche", headers=H).json()
        assert d["dormir"] is True
        assert d["epoch"] == int(datetime(2026, 11, 22, 7, 45, tzinfo=TZ).timestamp())
        assert d["motivo"] == "la hora por defecto"
        guardado = jacobo.called("POST", "/rest/v1/vigilante_estado")[-1][2]["json"]
        assert guardado["clave"] == "plan:jacobo-dormido"
        assert guardado["ultima_vez"].startswith("2026-11-22T06:45")
        assert main._jacobo_dormido_hasta() == datetime(2026, 11, 22, 7, 45, tzinfo=TZ)

    def test_no_con_una_llamada_en_curso(self, client, jacobo):
        jacobo.routes.insert(0, ("GET", "/api/calls", FakeResponse({"count": 1, "calls": [{}]})))
        d = client.post("/jacobo/noche", headers=H).json()
        assert d == {"dormir": False, "motivo": "hay una llamada en curso"}
        assert not jacobo.called("POST", "/rest/v1/vigilante_estado")

    def test_no_con_una_peli_puesta(self, client, jacobo, monkeypatch):
        monkeypatch.setattr(main, "_jellyfin_configurado", lambda: True)
        monkeypatch.setattr(main, "_jellyfin", lambda *a, **k: [{"NowPlayingItem": {"Name": "x"}}, {}])
        assert client.post("/jacobo/noche", headers=H).json()["motivo"] == "hay algo puesto en Jellyfin"

    def test_si_la_centralita_o_jellyfin_no_contestan_se_apaga_igual(self, client, jacobo, monkeypatch):
        jacobo.routes.insert(0, ("GET", "/api/calls", FakeResponse({}, 502)))
        monkeypatch.setattr(main, "_jellyfin_configurado", lambda: True)

        def caido(*a, **k):
            raise main.JellyfinNoContesta("no")
        monkeypatch.setattr(main, "_jellyfin", caido)
        assert client.post("/jacobo/noche", headers=H).json()["dormir"] is True

    def test_apagado(self, client, jacobo, monkeypatch):
        monkeypatch.setattr(main, "JACOBO_NOCHE", False)
        assert client.post("/jacobo/noche", headers=H).json()["dormir"] is False


class TestVigilante:
    def _oido_caido(self, jacobo, monkeypatch):
        monkeypatch.setattr(main, "_tele_configurada", lambda: True)
        monkeypatch.setattr(main, "HA_URL", "")
        jacobo.add("GET", "/api/salud", FakeResponse({"oido": {"configurado": True, "disponible": False}}))

    def test_dormido_no_es_caido(self, jacobo, monkeypatch):
        self._oido_caido(jacobo, monkeypatch)
        main._jacobo_hasta.update(cargado=True, hasta=datetime.now(timezone.utc) + timedelta(hours=6))
        assert "jacobo" not in main._servicios_caidos()

    def test_pasada_la_ventana_vuelve_a_contar(self, jacobo, monkeypatch):
        self._oido_caido(jacobo, monkeypatch)
        main._jacobo_hasta.update(cargado=True,
                                  hasta=datetime.now(timezone.utc) - timedelta(minutes=main.JACOBO_GRACIA_MIN + 1))
        assert "jacobo" in main._servicios_caidos()

    def test_tras_un_reinicio_la_ventana_se_lee_de_supabase(self, jacobo, monkeypatch):
        self._oido_caido(jacobo, monkeypatch)
        hasta = (datetime.now(timezone.utc) + timedelta(hours=3)).isoformat()
        jacobo.add("GET", "/rest/v1/vigilante_estado", FakeResponse([{"ultima_vez": hasta}]))
        assert "jacobo" not in main._servicios_caidos()
        assert "jacobo" not in main._servicios_caidos()
        assert len(jacobo.called("GET", "plan%3Ajacobo-dormido")) == 1


class TestAlertasDeGrafana:
    def _aviso(self, client, detalle):
        return client.post("/programado/roto", headers={"X-Auth-Token": "token-de-caja"},
                           json={"workflow": "Grafana: Prometheus no llega a un medidor",
                                 "detalle": detalle, "aviso": True}).json()

    def test_lo_de_jacobo_dormido_se_calla(self, client, jacobo, monkeypatch):
        avisos = []
        monkeypatch.setattr(main, "_apuntar_aviso", lambda *a, **k: avisos.append(a) or True)
        main._jacobo_hasta.update(cargado=True, hasta=datetime.now(timezone.utc) + timedelta(hours=5))
        d = self._aviso(client, "Prometheus lleva 5 min sin respuesta de node de jacobo (x)")
        assert d["avisado"] is False and avisos == []
        # Lo de caja, no.
        assert self._aviso(client, "Prometheus lleva 5 min sin respuesta de node de caja (x)")["avisado"]

    def test_despierto_se_avisa(self, client, jacobo, monkeypatch):
        monkeypatch.setattr(main, "_apuntar_aviso", lambda *a, **k: True)
        main._jacobo_hasta.update(cargado=True, hasta=None)
        assert self._aviso(client, "sin respuesta de node de jacobo")["avisado"] is True
