"""Tests del vigilante de espacio de Supabase y del aviso de /programado/roto.

El plan gratuito da 500 MB y hay tablas que crecen solas: el día que se llene fallan
todas las escrituras a la vez. Lo que se comprueba es que se avisa ANTES, con lo que
más ocupa, sin repetirse, y que no saberlo no es lo mismo que estar lleno.
"""
import main
from conftest import FakeResponse

MB = 1024 * 1024


def _espacio(mb_total, tablas=(("app_logs", 190), ("health_metrics", 120), ("jarvis_gasto", 30))):
    return FakeResponse({"total": int(mb_total * MB),
                         "tablas": [{"tabla": t, "bytes": int(m * MB)} for t, m in tablas]})


class TestElVigilante:
    def test_por_debajo_del_umbral_calla(self, mock_requests):
        mock_requests.add("POST", "rpc/espacio_bd", _espacio(200))
        assert main._vigilar_espacio() == {}
        assert not mock_requests.called("POST", "jarvis_recordatorios")

    def test_pasado_el_umbral_avisa_con_lo_que_mas_ocupa(self, mock_requests):
        mock_requests.add("POST", "rpc/espacio_bd", _espacio(420))
        mock_requests.add("POST", "jarvis_recordatorios", FakeResponse([], 201))
        r = main._vigilar_espacio()
        assert r == {"espacio_pct": 84.0, "aviso_espacio": True}
        aviso = mock_requests.called("POST", "jarvis_recordatorios")[0][2]["json"]
        assert aviso["regla"] == main.REGLA_ESPACIO
        assert "420 MB de 500" in aviso["texto"] and "app_logs (190 MB)" in aviso["texto"]
        assert len(aviso["texto"]) <= main.RECORDATORIO_MAX_TEXTO

    def test_sin_la_migracion_no_se_sabe_y_calla(self, mock_requests):
        mock_requests.add("POST", "rpc/espacio_bd", FakeResponse({"message": "no existe"}, 404))
        assert main._vigilar_espacio() == {}

    def test_mira_cada_seis_horas(self, mock_requests):
        mock_requests.add("POST", "rpc/espacio_bd", _espacio(100))
        main._vigilar_espacio()
        main._vigilar_espacio()
        assert len(mock_requests.called("POST", "rpc/espacio_bd")) == 1

    def test_no_puede_tumbar_el_tick(self, monkeypatch):
        def _revienta():
            raise RuntimeError("boom")
        monkeypatch.setattr(main, "_espacio_bd", _revienta)
        assert main._vigilar_espacio_seguro() == {}

    def test_va_en_el_tick(self):
        import inspect
        assert "_vigilar_espacio_seguro()" in inspect.getsource(main.ha_brief_tick)


class TestLaZonaDev:
    def test_la_pestana_bd_ensena_el_espacio(self, client, auth_headers, mock_requests):
        mock_requests.add("POST", "rpc/espacio_bd", _espacio(250))
        espacio = client.get("/dev/bd", headers=auth_headers).json()["espacio"]
        assert espacio["mb"] == 250.0 and espacio["pct"] == 50.0
        assert espacio["tablas"][0] == {"tabla": "app_logs", "mb": 190.0}

    def test_sin_saberlo_es_none(self, client, auth_headers, mock_requests):
        mock_requests.add("POST", "rpc/espacio_bd", FakeResponse({}, 404))
        assert client.get("/dev/bd", headers=auth_headers).json()["espacio"] is None


class TestProgramadoAviso:
    CABECERA = {"X-Auth-Token": "revision-token"}

    def test_un_aviso_no_dice_que_ha_fallado(self, client, mock_requests, monkeypatch):
        monkeypatch.setattr(main, "REVISION_TOKEN", "revision-token")
        mock_requests.add("POST", "jarvis_recordatorios", FakeResponse([], 201))
        client.post("/programado/roto", headers=self.CABECERA, json={
            "workflow": "Caducidad del dominio", "aviso": True,
            "detalle": "el dominio caduca en 20 días"})
        texto = mock_requests.called("POST", "jarvis_recordatorios")[0][2]["json"]["texto"]
        assert texto == "«Caducidad del dominio»: el dominio caduca en 20 días"

    def test_sin_la_marca_sigue_siendo_un_fallo(self, client, mock_requests, monkeypatch):
        monkeypatch.setattr(main, "REVISION_TOKEN", "revision-token")
        mock_requests.add("POST", "jarvis_recordatorios", FakeResponse([], 201))
        client.post("/programado/roto", headers=self.CABECERA,
                    json={"workflow": "Copia", "detalle": "sin secrets"})
        texto = mock_requests.called("POST", "jarvis_recordatorios")[0][2]["json"]["texto"]
        assert texto.startswith("«Copia» ha fallado.")
