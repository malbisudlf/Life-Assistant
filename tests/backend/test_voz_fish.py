"""Tests de Fish Audio como la voz de Jarvis en la web (`POST /voz/decir`).

Desde el 2026-10-29 habla Fish (la voz «Jarvis») y Azure va detrás, como en el teléfono
y en las notas de Telegram. Lo que hay que proteger: que Fish vaya primero, que un fallo
suyo —error, 200 vacío o red caída— acabe en Azure y no en silencio, que la clave no
salga, y que con una sola de las dos baste.
"""
import requests

import main
from conftest import FakeResponse

AUDIO_FISH  = b"ID3\x04de-fish"
AUDIO_AZURE = b"ID3\x04de-azure"
FISH  = "api.fish.audio/v1/tts"
AZURE = "tts.speech.microsoft.com"


def _fish(monkeypatch, mock_requests, respuesta=None, voz=""):
    monkeypatch.setattr(main, "FISH_AUDIO_API_KEY", "sk-fish-de-prueba")
    monkeypatch.setattr(main, "FISH_AUDIO_VOICE", voz)
    mock_requests.add("POST", FISH,
                      respuesta if respuesta is not None else FakeResponse(content=AUDIO_FISH))


def _azure(monkeypatch, mock_requests, respuesta=None):
    monkeypatch.setattr(main, "AZURE_SPEECH_KEY", "clave-azure")
    monkeypatch.setattr(main, "AZURE_SPEECH_REGION", "francecentral")
    monkeypatch.setattr(main, "AZURE_SPEECH_VOICE", "es-ES-SaulNeural")
    mock_requests.add("POST", AZURE,
                      respuesta if respuesta is not None else FakeResponse(content=AUDIO_AZURE))


def _sin_azure(monkeypatch):
    monkeypatch.setattr(main, "AZURE_SPEECH_KEY", "")


class TestVozDecir:
    def test_fish_va_antes_que_azure(self, client, auth_headers, monkeypatch, mock_requests):
        _fish(monkeypatch, mock_requests)
        _azure(monkeypatch, mock_requests)
        r = client.post("/voz/decir", json={"texto": "Buenas tardes, señor"},
                        headers=auth_headers)
        assert r.status_code == 200
        assert r.content == AUDIO_FISH
        # Ni una petición a Azure si Fish contesta: sería gastar cuota y nada más.
        assert not mock_requests.called("POST", AZURE)

    def test_si_fish_falla_habla_azure(self, client, auth_headers, monkeypatch, mock_requests):
        """Una frase con otra voz se oye rara; el silencio o la voz robótica, peor."""
        _fish(monkeypatch, mock_requests, FakeResponse(status_code=429, text="cuota"))
        _azure(monkeypatch, mock_requests)
        r = client.post("/voz/decir", json={"texto": "hola"}, headers=auth_headers)
        assert r.status_code == 200
        assert r.headers["content-type"] == "audio/mpeg"
        assert r.content == AUDIO_AZURE

    def test_un_200_vacio_de_fish_tampoco_vale(self, client, auth_headers, monkeypatch,
                                               mock_requests):
        _fish(monkeypatch, mock_requests, FakeResponse(content=b""))
        _azure(monkeypatch, mock_requests)
        r = client.post("/voz/decir", json={"texto": "hola"}, headers=auth_headers)
        assert r.content == AUDIO_AZURE

    def test_fish_caido_cae_a_azure(self, client, auth_headers, monkeypatch, mock_requests):
        def _timeout(url, **kwargs):
            raise requests.Timeout("Hong Kong no contesta")
        _fish(monkeypatch, mock_requests, _timeout)
        _azure(monkeypatch, mock_requests)
        r = client.post("/voz/decir", json={"texto": "hola"}, headers=auth_headers)
        assert r.status_code == 200 and r.content == AUDIO_AZURE

    def test_lo_que_se_le_manda_a_fish(self, client, auth_headers, monkeypatch, mock_requests):
        _sin_azure(monkeypatch)
        _fish(monkeypatch, mock_requests, voz="voz-de-jarvis")
        client.post("/voz/decir", json={"texto": "Hola"}, headers=auth_headers)
        _, _, kwargs = mock_requests.called("POST", FISH)[0]
        assert kwargs["headers"]["Authorization"] == "Bearer sk-fish-de-prueba"
        assert kwargs["headers"]["model"] == main.FISH_AUDIO_MODEL
        assert kwargs["json"]["text"] == "Hola"
        assert kwargs["json"]["format"] == "mp3"
        assert kwargs["json"]["reference_id"] == "voz-de-jarvis"
        # Timeout propio y corto: un Fish colgado no puede dejar 15 s muda una frase.
        assert kwargs["timeout"] == main.FISH_AUDIO_TIMEOUT

    def test_sin_voz_elegida_no_manda_reference_id(self, client, auth_headers, monkeypatch,
                                                   mock_requests):
        _sin_azure(monkeypatch)
        _fish(monkeypatch, mock_requests)
        client.post("/voz/decir", json={"texto": "Hola"}, headers=auth_headers)
        assert "reference_id" not in mock_requests.called("POST", FISH)[0][2]["json"]

    def test_fallan_las_dos_y_da_502_sin_las_claves(self, client, auth_headers, monkeypatch,
                                                   mock_requests):
        _azure(monkeypatch, mock_requests, FakeResponse(status_code=401, text="clave-azure"))
        _fish(monkeypatch, mock_requests,
              FakeResponse(status_code=401, text="sk-fish-de-prueba no vale"))
        r = client.post("/voz/decir", json={"texto": "hola"}, headers=auth_headers)
        assert r.status_code == 502
        assert "sk-fish" not in r.text and "clave-azure" not in r.text

    def test_solo_fish_basta(self, client, auth_headers, monkeypatch, mock_requests):
        _sin_azure(monkeypatch)
        _fish(monkeypatch, mock_requests)
        r = client.post("/voz/decir", json={"texto": "hola"}, headers=auth_headers)
        assert r.status_code == 200 and r.content == AUDIO_FISH

    def test_solo_azure_basta(self, client, auth_headers, monkeypatch, mock_requests):
        monkeypatch.setattr(main, "FISH_AUDIO_API_KEY", "")
        _azure(monkeypatch, mock_requests)
        r = client.post("/voz/decir", json={"texto": "hola"}, headers=auth_headers)
        assert r.status_code == 200 and r.content == AUDIO_AZURE


class TestElOrdenDeLasNotas:
    """Las notas de voz (Telegram, cuando existan) priman la calidad: Fish delante."""

    def test_las_notas_van_con_fish_delante(self, monkeypatch, mock_requests):
        _azure(monkeypatch, mock_requests)
        _fish(monkeypatch, mock_requests)
        assert main._decir_con("hola", main._VOZ_ORDEN_NOTAS) == AUDIO_FISH
        assert not mock_requests.called("POST", AZURE)

    def test_y_azure_las_rescata(self, monkeypatch, mock_requests):
        _fish(monkeypatch, mock_requests, FakeResponse(status_code=500, text="caído"))
        _azure(monkeypatch, mock_requests)
        assert main._decir_con("hola", main._VOZ_ORDEN_NOTAS) == AUDIO_AZURE


class TestQueVozSeElige:
    def test_con_las_dos_el_proveedor_es_fish(self, client, auth_headers, monkeypatch,
                                              mock_requests):
        _fish(monkeypatch, mock_requests)
        _azure(monkeypatch, mock_requests)
        r = client.post("/voz/token", json={"tipo": "tts_websocket"}, headers=auth_headers)
        assert r.status_code == 200 and r.json()["proveedor"] == "fish"

    def test_solo_con_fish_el_proveedor_es_fish(self, client, auth_headers, monkeypatch,
                                                mock_requests):
        _sin_azure(monkeypatch)
        _fish(monkeypatch, mock_requests)
        r = client.post("/voz/token", json={"tipo": "tts_websocket"}, headers=auth_headers)
        assert r.status_code == 200
        datos = r.json()
        assert datos["proveedor"] == "fish"
        # Como con Azure: el audio va por /voz/decir con el JWT, no hay token que dar.
        assert "token" not in datos
        assert "sk-fish" not in r.text

    def test_la_transcripcion_sigue_siendo_de_elevenlabs(self, client, auth_headers,
                                                         monkeypatch, mock_requests):
        _sin_azure(monkeypatch)
        _fish(monkeypatch, mock_requests)
        monkeypatch.setattr(main, "JARVIS_VOZ_ELEVENLABS", True)
        monkeypatch.setattr(main, "ELEVENLABS_API_KEY", "xi-clave")
        monkeypatch.setattr(main, "ELEVENLABS_VOICE_ID", "voz")
        mock_requests.add("POST", "api.elevenlabs.io/v1/single-use-token/",
                          FakeResponse({"token": "sutkn_x"}))
        r = client.post("/voz/token", json={"tipo": "realtime_scribe"}, headers=auth_headers)
        assert r.json()["proveedor"] == "elevenlabs"
