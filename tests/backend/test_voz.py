"""Tests del permiso de voz (`POST /voz/token`).

Lo que se protege aquí es que la clave de ElevenLabs nunca salga del backend y que el
token de un solo uso —que es una credencial viva durante 15 minutos— no acabe en ningún
registro. Ver docs/JARVIS_VOZ.md.
"""
import pytest

import main
from conftest import FakeResponse

TOKEN_FALSO = "sutkn_pruebaquenodeberiaverse"


@pytest.fixture(autouse=True)
def _sin_azure(monkeypatch):
    """Este fichero prueba la rama de ElevenLabs, así que Azure va apagado.

    Y no es una formalidad: `main` carga el `.env` del desarrollador al importarse, así
    que en cuanto alguien configura Azure en su máquina, `/voz/token` empieza a devolver
    `proveedor: azure` y estos tests se caen todos a la vez sin que nadie haya tocado el
    código. En CI no pasaba —allí no hay `.env`—, que es la peor versión del problema:
    verde en el CI y rojo en local.
    """
    monkeypatch.setattr(main, "AZURE_SPEECH_KEY", "")


def _configurar(monkeypatch, mock_requests, respuesta=None):
    monkeypatch.setattr(main, "JARVIS_VOZ_ELEVENLABS", True)
    monkeypatch.setattr(main, "ELEVENLABS_API_KEY", "xi-clave-de-prueba")
    monkeypatch.setattr(main, "ELEVENLABS_VOICE_ID", "voz-de-prueba")
    mock_requests.add(
        "POST",
        "api.elevenlabs.io/v1/single-use-token/",
        respuesta if respuesta is not None else FakeResponse({"token": TOKEN_FALSO}),
    )


class TestVozToken:
    def test_sin_autenticacion_no_emite_token(self, client):
        r = client.post("/voz/token", json={"tipo": "tts_websocket"})
        assert r.status_code in (401, 403)

    def test_sin_configurar_responde_503(self, client, auth_headers, monkeypatch):
        # Apagado es el estado por defecto: el frontend lee el 503 y se queda con el modo
        # llamada gratuito del navegador en vez de romperse.
        monkeypatch.setattr(main, "JARVIS_VOZ_ELEVENLABS", False)
        r = client.post("/voz/token", json={"tipo": "tts_websocket"}, headers=auth_headers)
        assert r.status_code == 503

    def test_encendido_pero_sin_clave_responde_503(self, client, auth_headers, monkeypatch):
        monkeypatch.setattr(main, "JARVIS_VOZ_ELEVENLABS", True)
        monkeypatch.setattr(main, "ELEVENLABS_API_KEY", "")
        monkeypatch.setattr(main, "ELEVENLABS_VOICE_ID", "voz-de-prueba")
        r = client.post("/voz/token", json={"tipo": "tts_websocket"}, headers=auth_headers)
        assert r.status_code == 503

    def test_tipo_desconocido_se_rechaza(self, client, auth_headers, monkeypatch, mock_requests):
        _configurar(monkeypatch, mock_requests)
        # El tipo se interpola en la URL de salida: solo valen los dos del Literal.
        r = client.post("/voz/token", json={"tipo": "batch_scribe"}, headers=auth_headers)
        assert r.status_code == 422
        assert not mock_requests.called("POST", "elevenlabs.io")

    def test_emite_el_token_y_la_voz(self, client, auth_headers, monkeypatch, mock_requests):
        _configurar(monkeypatch, mock_requests)
        r = client.post("/voz/token", json={"tipo": "tts_websocket"}, headers=auth_headers)
        assert r.status_code == 200
        datos = r.json()
        assert datos["token"] == TOKEN_FALSO
        assert datos["voice_id"] == "voz-de-prueba"
        assert datos["model_id"] == main.ELEVENLABS_MODEL

        llamadas = mock_requests.called("POST", "single-use-token/tts_websocket")
        assert len(llamadas) == 1
        # La clave va en la cabecera que espera ElevenLabs, nunca en la query.
        _, url, kwargs = llamadas[0]
        assert kwargs["headers"]["xi-api-key"] == "xi-clave-de-prueba"
        assert "xi-clave" not in url

    def test_el_stt_usa_su_propio_modelo(self, client, auth_headers, monkeypatch, mock_requests):
        _configurar(monkeypatch, mock_requests)
        r = client.post("/voz/token", json={"tipo": "realtime_scribe"}, headers=auth_headers)
        assert r.status_code == 200
        assert r.json()["model_id"] == main.ELEVENLABS_STT_MODEL
        assert mock_requests.called("POST", "single-use-token/realtime_scribe")

    def test_error_de_elevenlabs_no_se_reenvia_al_cliente(
        self, client, auth_headers, monkeypatch, mock_requests
    ):
        _configurar(
            monkeypatch,
            mock_requests,
            FakeResponse({"detail": "clave xi-secreta inválida"}, 401, "clave xi-secreta inválida"),
        )
        r = client.post("/voz/token", json={"tipo": "tts_websocket"}, headers=auth_headers)
        assert r.status_code == 502
        assert "xi-secreta" not in r.text

    def test_respuesta_sin_token_es_un_error(self, client, auth_headers, monkeypatch, mock_requests):
        _configurar(monkeypatch, mock_requests, FakeResponse({}, 200))
        r = client.post("/voz/token", json={"tipo": "tts_websocket"}, headers=auth_headers)
        assert r.status_code == 502

    def test_el_token_no_acaba_en_los_registros(
        self, client, auth_headers, monkeypatch, mock_requests, caplog
    ):
        _configurar(monkeypatch, mock_requests)
        with caplog.at_level("DEBUG"):
            r = client.post("/voz/token", json={"tipo": "tts_websocket"}, headers=auth_headers)
        assert r.status_code == 200
        assert TOKEN_FALSO not in caplog.text

    def test_limita_por_ip(self, client, auth_headers, monkeypatch, mock_requests):
        _configurar(monkeypatch, mock_requests)
        monkeypatch.setattr(main, "VOZ_TOKEN_MAX_REQUESTS", 2)
        for _ in range(2):
            assert client.post(
                "/voz/token", json={"tipo": "tts_websocket"}, headers=auth_headers
            ).status_code == 200
        r = client.post("/voz/token", json={"tipo": "tts_websocket"}, headers=auth_headers)
        assert r.status_code == 429
