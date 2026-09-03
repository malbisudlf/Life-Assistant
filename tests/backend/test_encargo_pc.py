"""Tests del encargo libre al PC: lo que sustituye a la lista blanca.

Todo lo que el agente ejecutaba hasta ahora venía de una URL de `ALUD_ALLOWED_HOSTS`,
validada en tres sitios (invariante 7). Un encargo en lenguaje natural no se puede
validar contra ninguna lista: no hay forma de comprobar QUÉ dice. Lo que se comprueba es
QUIÉN lo escribió, y eso es lo que se prueba aquí.
"""
import hmac
import hashlib

import pytest

import main
from conftest import FakeResponse


@pytest.fixture(autouse=True)
def _jobs(mock_requests):
    mock_requests.add("POST", "/jobs", FakeResponse([{"id": "job-1"}], 201))
    return mock_requests


def _payload_enviado(mock_requests):
    return [c[2]["json"] for c in mock_requests.called("POST", "/jobs")][0]["payload"]


class TestFirma:
    def test_la_firma_es_hmac_del_token_del_agente(self, monkeypatch):
        monkeypatch.setattr(main, "AGENT_TOKEN", "token-del-agente")
        esperada = hmac.new(b"token-del-agente", "ordena el escritorio".encode(),
                            hashlib.sha256).hexdigest()
        assert main.firma_encargo("ordena el escritorio") == esperada

    def test_sin_token_no_hay_firma(self, monkeypatch):
        """Sin secreto no hay firma que valga, y quien llama tiene que tratarlo como
        'esto no se puede encargar', nunca como 'va sin firma'."""
        monkeypatch.setattr(main, "AGENT_TOKEN", "")
        assert main.firma_encargo("lo que sea") == ""

    def test_cambiar_una_letra_cambia_la_firma(self, monkeypatch):
        monkeypatch.setattr(main, "AGENT_TOKEN", "token-del-agente")
        assert main.firma_encargo("borra todo") != main.firma_encargo("borra todo.")


class TestCrearElJob:
    def test_el_backend_firma_el_encargo(self, client, auth_headers, monkeypatch,
                                         mock_requests):
        monkeypatch.setattr(main, "AGENT_TOKEN", "token-del-agente")
        r = client.post("/jobs", headers=auth_headers, json={
            "dedupe_key": "encargo-1",
            "payload": {"accion": "encargo", "instruccion": "busca vuelos a Roma"},
        })
        assert r.status_code == 200
        payload = _payload_enviado(mock_requests)
        assert payload["firma"] == main.firma_encargo("busca vuelos a Roma")

    def test_una_firma_traida_de_fuera_se_ignora(self, client, auth_headers, monkeypatch,
                                                 mock_requests):
        """La firma NO se acepta del cliente ni aunque venga correcta: este endpoint es
        el único sitio donde consta que detrás hay un JWT de usuario, y eso es justo lo
        que la firma transporta hasta el agente."""
        monkeypatch.setattr(main, "AGENT_TOKEN", "token-del-agente")
        client.post("/jobs", headers=auth_headers, json={
            "dedupe_key": "encargo-2",
            "payload": {"accion": "encargo", "instruccion": "algo", "firma": "inventada"},
        })
        assert _payload_enviado(mock_requests)["firma"] == main.firma_encargo("algo")

    def test_sin_agent_token_se_dice_lo_que_falta(self, client, auth_headers, monkeypatch):
        """Error con el arreglo dentro: si no, el agente rechazaría el job y el usuario
        vería 'falló' sin saber por qué."""
        monkeypatch.setattr(main, "AGENT_TOKEN", "")
        r = client.post("/jobs", headers=auth_headers, json={
            "dedupe_key": "encargo-3",
            "payload": {"accion": "encargo", "instruccion": "algo"},
        })
        assert r.status_code == 503
        assert "AGENT_TOKEN" in r.json()["detail"]

    def test_un_encargo_vacio_no_se_encola(self, client, auth_headers, monkeypatch):
        monkeypatch.setattr(main, "AGENT_TOKEN", "token-del-agente")
        r = client.post("/jobs", headers=auth_headers, json={
            "dedupe_key": "encargo-4",
            "payload": {"accion": "encargo", "instruccion": "   "},
        })
        assert r.status_code == 400

    def test_un_encargo_enorme_se_rechaza(self, client, auth_headers, monkeypatch):
        monkeypatch.setattr(main, "AGENT_TOKEN", "token-del-agente")
        r = client.post("/jobs", headers=auth_headers, json={
            "dedupe_key": "encargo-5",
            "payload": {"accion": "encargo",
                        "instruccion": "a" * (main.ENCARGO_MAX_CHARS + 1)},
        })
        assert r.status_code == 400

    def test_los_jobs_de_siempre_no_cambian(self, client, auth_headers, mock_requests):
        """El streaming y Alud no llevan firma y tienen que seguir funcionando igual."""
        r = client.post("/jobs", headers=auth_headers, json={
            "dedupe_key": "streaming-1", "payload": {"accion": "abrir_streaming"},
        })
        assert r.status_code == 200
        assert "firma" not in _payload_enviado(mock_requests)

    def test_sigue_sin_admitir_una_url_de_alud_ajena(self, client, auth_headers):
        """La otra defensa no se ha tocado al añadir esta."""
        r = client.post("/jobs", headers=auth_headers, json={
            "dedupe_key": "alud-1",
            "payload": {"alud_url": "https://evil.example.com/entrega"},
        })
        assert r.status_code == 400


class TestHerramientaDeJarvis:
    def test_siempre_pide_confirmacion(self):
        """Es la única herramienta que acaba en texto libre dentro de Claude Desktop, en
        el PC del usuario y con todas sus sesiones abiertas."""
        assert main._JARVIS_HERRAMIENTAS["encargar_al_pc"]["confirmar"] is True

    def test_el_modelo_propone_y_no_ejecuta(self, client, auth_headers, monkeypatch,
                                            mock_requests):
        from test_jarvis import _con_modelo, _llamada, _mensaje

        monkeypatch.setattr(main, "AGENT_TOKEN", "token-del-agente")
        _con_modelo(monkeypatch, [
            _mensaje(tool_calls=[_llamada("encargar_al_pc",
                                          {"instruccion": "ordena la carpeta de descargas"})]),
            _mensaje("¿Se lo digo?"),
        ])
        datos = client.post("/jarvis", json={"mensaje": "que el pc ordene descargas"},
                            headers=auth_headers).json()
        assert datos["pendiente"]["herramienta"] == "encargar_al_pc"
        assert mock_requests.called("POST", "/jobs") == []

    def test_al_confirmar_se_encola_firmado(self, client, auth_headers, monkeypatch,
                                            mock_requests):
        monkeypatch.setattr(main, "AGENT_TOKEN", "token-del-agente")
        r = client.post("/jarvis/ejecutar", headers=auth_headers, json={
            "herramienta": "encargar_al_pc",
            "argumentos": {"instruccion": "prepara el resumen de la reunión"},
        })
        assert r.status_code == 200
        payload = _payload_enviado(mock_requests)
        assert payload["accion"] == "encargo"
        assert payload["firma"] == main.firma_encargo("prepara el resumen de la reunión")

    def test_un_encargo_vacio_lo_dice_sin_reventar(self, monkeypatch):
        monkeypatch.setattr(main, "AGENT_TOKEN", "token-del-agente")
        assert main._j_encargar_al_pc("  ")["ok"] is False
