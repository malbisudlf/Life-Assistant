"""La tele de la sala (`tele`) y el vigilante que llama si se cae lo que sostiene a Jarvis.

Lo que se protege de la tele: que vaya con la llave, que una acción desconocida no salga, y
que sin centralita no se anuncie. Del vigilante: que no llame a la primera, que llame UNA vez
por caída, que dormido lo reintente y no lo dé por hecho, y que al volver avise sin llamar.
"""
from datetime import datetime, timedelta, timezone

import pytest
import requests

import main
from conftest import FakeResponse

URL = "http://centralita:3010"
LLAVE = "llave-de-la-centralita"


@pytest.fixture
def central(monkeypatch, mock_requests):
    monkeypatch.setattr(main, "TELEFONO_URL", URL)
    monkeypatch.setattr(main, "TELEFONO_TERCEROS_TOKEN", LLAVE)
    return mock_requests


class TestTele:
    def test_manda_la_orden_con_la_llave(self, central):
        central.add("POST", "/api/tele", FakeResponse({"ok": True, "frase": "Apagada, señor."}))
        r = main._j_tele("apagar")
        assert r == {"ok": True, "frase": "Apagada, señor."}
        llamada = [c for c in central.calls if c[0] == "POST" and "/api/tele" in c[1]][0]
        assert llamada[2]["headers"]["X-Auth-Token"] == LLAVE
        assert llamada[2]["json"]["accion"] == "apagar"
        assert llamada[2]["timeout"] >= 46     # el permiso en pantalla y encender

    def test_abrir_lleva_el_valor(self, central):
        central.add("POST", "/api/tele", FakeResponse({"ok": True, "frase": "Abriendo."}))
        main._j_tele("abrir", "Netflix")
        llamada = [c for c in central.calls if c[0] == "POST"][0]
        assert llamada[2]["json"] == {"accion": "abrir", "valor": "Netflix"}

    def test_accion_desconocida_no_sale(self, central):
        r = main._j_tele("explotar")
        assert r["ok"] is False
        assert not [c for c in central.calls if c[0] == "POST"]

    def test_centralita_caida(self, central, monkeypatch):
        def falla(*a, **k):
            raise requests.ConnectionError("no")
        monkeypatch.setattr(main.http, "post", falla)
        assert main._j_tele("apagar")["ok"] is False

    def test_sin_configurar_no_se_anuncia(self, monkeypatch):
        monkeypatch.setattr(main, "TELEFONO_URL", "")
        nombres = {h["function"]["name"] for h in main._jarvis_esquema()}
        assert "tele" not in nombres

    def test_configurada_se_anuncia_y_no_se_confirma(self, central):
        nombres = {h["function"]["name"] for h in main._jarvis_esquema()}
        assert "tele" in nombres
        assert main._JARVIS_HERRAMIENTAS["tele"]["confirmar"] is False

    def test_llega_al_telefono(self):
        assert "tele" in main._MCP_SERVIDOR_HERRAMIENTAS


@pytest.fixture
def vigia(monkeypatch, central):
    monkeypatch.setattr(main, "SUPABASE_URL", "https://supabase.test")
    monkeypatch.setattr(main, "VIGILANTE_ESTADO_URL", "https://supabase.test/rest/v1/vigilante_estado")
    monkeypatch.setattr(main, "HA_URL", "")
    monkeypatch.setattr(main, "HA_TOKEN", "")
    monkeypatch.setattr(main, "VIGIA_SERVICIOS", True)
    monkeypatch.setattr(main, "VIGIA_SERVICIOS_MIN", 10)
    avisos, llamadas = [], []
    monkeypatch.setattr(main, "_apuntar_aviso", lambda regla, texto, **k: avisos.append(texto) or True)
    monkeypatch.setattr(main, "_llamar", lambda texto, **k: llamadas.append((texto, k)) or True)
    central.avisos, central.llamadas = avisos, llamadas
    return central


def _jacobo(router, disponible):
    router.add("GET", "/api/salud", FakeResponse({"ok": True, "oido": {"configurado": True, "disponible": disponible}}))


def _filas(router, filas):
    router.add("GET", "vigilante_estado", FakeResponse(filas))


def _hace(minutos):
    return (datetime.now(timezone.utc) - timedelta(minutes=minutos)).isoformat()


class TestVigilante:
    def test_todo_bien_no_hace_nada(self, vigia):
        _jacobo(vigia, True)
        _filas(vigia, [])
        assert main._vigilar_servicios() == {}
        assert not vigia.llamadas and not vigia.avisos

    def test_la_primera_vez_solo_empieza_a_contar(self, vigia):
        _jacobo(vigia, False)
        _filas(vigia, [])
        vigia.add("POST", "vigilante_estado", FakeResponse({}))
        assert main._vigilar_servicios() == {"servicios_caidos": ["jacobo"]}
        assert not vigia.llamadas
        assert [c for c in vigia.calls if c[0] == "POST" and "vigilante_estado" in c[1]]

    def test_antes_de_tiempo_no_llama(self, vigia):
        _jacobo(vigia, False)
        _filas(vigia, [{"clave": "servicio:jacobo", "primera_vez": _hace(5), "issue_url": None}])
        main._vigilar_servicios()
        assert not vigia.llamadas

    def test_pasado_el_tiempo_llama_y_lo_apunta(self, vigia):
        _jacobo(vigia, False)
        _filas(vigia, [{"clave": "servicio:jacobo", "primera_vez": _hace(11), "issue_url": None}])
        vigia.add("PATCH", "vigilante_estado", FakeResponse({}))
        salida = main._vigilar_servicios()
        assert salida["llamada_servicios"] is True
        assert len(vigia.llamadas) == 1
        assert "Jacobo no responde" in vigia.llamadas[0][0]
        assert vigia.llamadas[0][1]["solo_centralita"] is True
        assert vigia.avisos
        assert [c for c in vigia.calls if c[0] == "PATCH"]

    def test_una_sola_llamada_por_caida(self, vigia):
        _jacobo(vigia, False)
        _filas(vigia, [{"clave": "servicio:jacobo", "primera_vez": _hace(60), "issue_url": "llamado:x"}])
        main._vigilar_servicios()
        assert not vigia.llamadas

    def test_si_no_puede_sonar_lo_reintenta(self, vigia, monkeypatch):
        _jacobo(vigia, False)
        _filas(vigia, [{"clave": "servicio:jacobo", "primera_vez": _hace(11), "issue_url": None}])
        monkeypatch.setattr(main, "_llamar", lambda texto, **k: False)
        salida = main._vigilar_servicios()
        assert "llamada_servicios" not in salida
        assert not [c for c in vigia.calls if c[0] == "PATCH"]

    def test_al_volver_avisa_sin_llamar(self, vigia):
        _jacobo(vigia, True)
        _filas(vigia, [{"clave": "servicio:jacobo", "primera_vez": _hace(60), "issue_url": "llamado:x"}])
        vigia.add("DELETE", "vigilante_estado", FakeResponse({}))
        salida = main._vigilar_servicios()
        assert salida["aviso_servicios"] is True
        assert "ha vuelto" in vigia.avisos[0]
        assert not vigia.llamadas

    def test_centralita_caida_no_es_jacobo_caido(self, vigia, monkeypatch):
        def falla(url, **k):
            if "/api/salud" in url:
                raise requests.ConnectionError("no")
            return FakeResponse([])
        monkeypatch.setattr(main.http, "get", falla)
        assert main._servicios_caidos() == []

    def test_token_de_ha_caducado(self, vigia, monkeypatch):
        monkeypatch.setattr(main, "HA_URL", "http://ha.test")
        monkeypatch.setattr(main, "HA_TOKEN", "x")
        _jacobo(vigia, True)
        vigia.add("GET", "/api/", FakeResponse({}, status_code=401))
        assert main._servicios_caidos() == ["home_assistant"]

    def test_el_contexto_lo_cuenta(self, vigia):
        _jacobo(vigia, False)
        assert "AVERÍAS AHORA" in main._contexto_averias()
        assert "Jacobo no responde" in main._contexto_averias()

    def test_el_contexto_sin_averias_calla(self, vigia):
        _jacobo(vigia, True)
        assert main._contexto_averias() == ""
