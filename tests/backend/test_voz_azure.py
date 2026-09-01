"""Tests de la voz de Azure (`POST /voz/decir`).

Aquí el audio SÍ pasa por el backend, al revés que con ElevenLabs, así que lo que hay que
proteger es distinto: que la clave no salga, que un 200 vacío no se dé por bueno, y sobre
todo que el texto NO se pueda colar como marcado SSML. Ese último es el que importa: lo
que llega aquí lo escribe el modelo a partir de lo que le han dicho por el micrófono.
"""
import time

import main
from conftest import FakeResponse

AUDIO = b"ID3\x04fingido"
AZURE = "tts.speech.microsoft.com"


def _configurar(monkeypatch, mock_requests, respuesta=None):
    monkeypatch.setattr(main, "AZURE_SPEECH_KEY", "clave-de-prueba")
    monkeypatch.setattr(main, "AZURE_SPEECH_REGION", "francecentral")
    monkeypatch.setattr(main, "AZURE_SPEECH_VOICE", "es-ES-SaulNeural")
    mock_requests.add("POST", AZURE,
                      respuesta if respuesta is not None else FakeResponse(content=AUDIO))


class TestVozDecir:
    def test_sin_autenticacion_no_sintetiza(self, client):
        assert client.post("/voz/decir", json={"texto": "hola"}).status_code in (401, 403)

    def test_sin_configurar_responde_503(self, client, auth_headers, monkeypatch):
        """503 y no 500: no es un error, es que esta voz no está puesta. El cliente lee
        eso y se cae a la voz del navegador en vez de quedarse mudo."""
        monkeypatch.setattr(main, "AZURE_SPEECH_KEY", "")
        r = client.post("/voz/decir", json={"texto": "hola"}, headers=auth_headers)
        assert r.status_code == 503

    def test_devuelve_el_audio(self, client, auth_headers, monkeypatch, mock_requests):
        _configurar(monkeypatch, mock_requests)
        r = client.post("/voz/decir", json={"texto": "Hola Mikel"}, headers=auth_headers)
        assert r.status_code == 200
        assert r.headers["content-type"] == "audio/mpeg"
        assert r.content == AUDIO

    def test_el_texto_va_escapado_y_no_puede_cambiar_la_voz(
            self, client, auth_headers, monkeypatch, mock_requests):
        """El agujero de verdad de este endpoint.

        Sin escapar, un `</voice><voice name="...">` metido en el texto cambiaría la voz,
        y un `<audio src="...">` haría que el altavoz reprodujera lo que hubiera al otro
        lado de una URL ajena. Y ese texto no lo escribe el usuario: lo escribe el modelo
        a partir de lo que oye. Es la misma regla que el enunciado de Alud — lo de fuera
        entra como DATO, nunca como marcado.
        """
        _configurar(monkeypatch, mock_requests)
        ataque = '</voice><audio src="https://ajeno.invalido/x.mp3"/><voice name="en-US-Guy">'
        r = client.post("/voz/decir", json={"texto": ataque}, headers=auth_headers)
        assert r.status_code == 200
        enviado = mock_requests.called("POST", AZURE)[0][2]["data"].decode("utf-8")
        # El ataque sigue ahi, pero como TEXTO: Saul lo leera en alto y quedara en
        # ridiculo, que es exactamente lo que tiene que pasar. Lo que no puede es ser
        # marcado, y por eso se mira el escapado y no la ausencia de la cadena.
        assert "&lt;audio" in enviado and "<audio" not in enviado
        # Y sigue habiendo exactamente una voz declarada como marcado: la nuestra.
        assert enviado.count("<voice name=") == 1
        assert "es-ES-SaulNeural" in enviado

    def test_un_200_sin_audio_no_se_da_por_bueno(
            self, client, auth_headers, monkeypatch, mock_requests):
        """El fallo MUDO de siempre con otra cara: sin esto el cliente se queda esperando
        un audio que no existe, que es justo lo que costó dos tardes con ElevenLabs."""
        _configurar(monkeypatch, mock_requests, FakeResponse(content=b""))
        r = client.post("/voz/decir", json={"texto": "hola"}, headers=auth_headers)
        assert r.status_code == 502

    def test_un_error_de_azure_no_se_reenvia_al_cliente(
            self, client, auth_headers, monkeypatch, mock_requests):
        _configurar(monkeypatch, mock_requests,
                    FakeResponse(status_code=401, text="clave-de-prueba no vale"))
        r = client.post("/voz/decir", json={"texto": "hola"}, headers=auth_headers)
        assert r.status_code == 502
        assert "clave-de-prueba" not in r.text

    def test_el_texto_vacio_no_gasta_una_peticion(
            self, client, auth_headers, monkeypatch, mock_requests):
        _configurar(monkeypatch, mock_requests)
        r = client.post("/voz/decir", json={"texto": "   "}, headers=auth_headers)
        assert r.status_code == 400
        assert not mock_requests.called("POST", AZURE)

    def test_un_texto_kilometrico_se_rechaza(self, client, auth_headers, monkeypatch,
                                             mock_requests):
        """El troceado es del cliente; esto es el tope, no el troceador."""
        _configurar(monkeypatch, mock_requests)
        r = client.post("/voz/decir", json={"texto": "a" * 5000}, headers=auth_headers)
        assert r.status_code == 422


class TestQueVozSeElige:
    """`/voz/token` es quien decide, y el cliente solo obedece al campo `proveedor`."""

    def test_azure_va_antes_que_elevenlabs(self, client, auth_headers, monkeypatch,
                                           mock_requests):
        _configurar(monkeypatch, mock_requests)
        monkeypatch.setattr(main, "JARVIS_VOZ_ELEVENLABS", True)
        monkeypatch.setattr(main, "ELEVENLABS_API_KEY", "xi-clave")
        monkeypatch.setattr(main, "ELEVENLABS_VOICE_ID", "voz")
        r = client.post("/voz/token", json={"tipo": "tts_websocket"}, headers=auth_headers)
        assert r.status_code == 200
        datos = r.json()
        assert datos["proveedor"] == "azure"
        # Y sin token: el de Azure no existe, su audio va con el JWT por /voz/decir. Un
        # token aquí solo podria ser el de ElevenLabs, emitido y tirado sin usar.
        assert "token" not in datos

    def test_la_transcripcion_sigue_siendo_de_elevenlabs(self, client, auth_headers,
                                                         monkeypatch, mock_requests):
        """Azure esta aqui para hablar. Pedir `realtime_scribe` no puede acabar en Azure."""
        _configurar(monkeypatch, mock_requests)
        monkeypatch.setattr(main, "JARVIS_VOZ_ELEVENLABS", True)
        monkeypatch.setattr(main, "ELEVENLABS_API_KEY", "xi-clave")
        monkeypatch.setattr(main, "ELEVENLABS_VOICE_ID", "voz")
        mock_requests.add("POST", "api.elevenlabs.io/v1/single-use-token/",
                          FakeResponse({"token": "sutkn_x"}))
        r = client.post("/voz/token", json={"tipo": "realtime_scribe"}, headers=auth_headers)
        assert r.json()["proveedor"] == "elevenlabs"

    def test_sin_ninguna_de_las_dos_responde_503(self, client, auth_headers, monkeypatch):
        monkeypatch.setattr(main, "AZURE_SPEECH_KEY", "")
        monkeypatch.setattr(main, "JARVIS_VOZ_ELEVENLABS", False)
        r = client.post("/voz/token", json={"tipo": "tts_websocket"}, headers=auth_headers)
        assert r.status_code == 503


class TestElCalentamiento:
    """`/voz/token` se pide por adelantado; se aprovecha para dejar hecho lo de una vez."""

    def test_pedir_el_permiso_calienta_las_caches(self, client, auth_headers, monkeypatch,
                                                  mock_requests):
        _configurar(monkeypatch, mock_requests)
        llamadas = []
        monkeypatch.setattr(main, "_casa_entidades", lambda: llamadas.append("casa") or [])
        monkeypatch.setattr(main, "_mcp_config", lambda: llamadas.append("mcp") or {})
        r = client.post("/voz/token", json={"tipo": "tts_websocket"}, headers=auth_headers)
        assert r.status_code == 200
        # Va en un hilo: se espera a que suelte el cerrojo en vez de dormir a ciegas.
        for _ in range(200):
            if main._calentando.acquire(blocking=False):
                main._calentando.release()
                if llamadas:
                    break
            time.sleep(0.01)
        assert sorted(llamadas) == ["casa", "mcp"]

    def test_calentar_no_puede_tumbar_el_permiso(self, client, auth_headers, monkeypatch,
                                                 mock_requests):
        """Es trabajo adelantado, no el trabajo. Si falla, la voz sigue estando."""
        _configurar(monkeypatch, mock_requests)
        def _revienta():
            raise RuntimeError("Supabase caído")
        monkeypatch.setattr(main, "_casa_entidades", _revienta)
        r = client.post("/voz/token", json={"tipo": "tts_websocket"}, headers=auth_headers)
        assert r.status_code == 200 and r.json()["proveedor"] == "azure"
