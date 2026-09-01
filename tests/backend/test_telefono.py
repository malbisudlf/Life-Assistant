"""Tests del teléfono: la llamada, su puerta de entrada y el audio.

El puente entero (el WebSocket) no se prueba aquí: necesitaría a Twilio al otro lado
mandando tramas. Lo que sí se prueba es todo lo que puede romperse SIN Twilio, que es
donde están los fallos que importan: quién puede abrir el puente, qué se entiende por un
«sí», y que la conversión de audio no devuelva ruido.
"""
from types import SimpleNamespace

import pytest
from jose import jwt

import main


@pytest.fixture(autouse=True)
def _configurado(monkeypatch):
    monkeypatch.setattr(main, "LLAMADAS", True)
    monkeypatch.setattr(main, "TWILIO_SID", "AC123")
    monkeypatch.setattr(main, "TWILIO_TOKEN", "twilio-token")
    monkeypatch.setattr(main, "TWILIO_DESDE", "+34600000000")
    monkeypatch.setattr(main, "TWILIO_HASTA", "+34600000001")
    monkeypatch.setattr(main, "BACKEND_URL", "https://backend.test")


class TestLlamar:
    def test_llama_con_el_contexto_firmado(self, mock_requests):
        from conftest import FakeResponse
        mock_requests.add("POST", "twilio.com", FakeResponse({"sid": "CA1"}, 201))

        assert main._llamar("Se ha roto el CI", rid="r-1") is True
        datos = mock_requests.called("POST", "twilio.com")[0][2]["data"]
        assert datos["To"] == "+34600000001" and datos["From"] == "+34600000000"
        # El texto NO viaja en claro en la URL: va dentro de un JWT firmado, porque esa
        # URL se la damos a Twilio y la llama de vuelta desde internet.
        assert "Se ha roto" not in datos["Url"]
        assert "/telefono/voz?ctx=" in datos["Url"]

    def test_sin_configurar_no_llama_ni_revienta(self, monkeypatch, mock_requests):
        """El canal caro es de refuerzo: que no suene no puede tumbar el aviso que sí salió."""
        monkeypatch.setattr(main, "LLAMADAS", False)
        assert main._llamar("lo que sea") is False
        assert not mock_requests.called("POST", "twilio.com")

    def test_un_fallo_de_twilio_no_se_propaga(self, mock_requests):
        from conftest import FakeResponse
        mock_requests.add("POST", "twilio.com", FakeResponse({}, 400, text="saldo agotado"))
        assert main._llamar("lo que sea") is False


class TestContextoDeLlamada:
    def test_ida_y_vuelta(self):
        ctx = main._contexto_llamada("He arreglado el CI", "r-1")
        assert main._leer_contexto_llamada(ctx) == {"texto": "He arreglado el CI", "rid": "r-1"}

    def test_un_token_de_usuario_no_abre_el_telefono(self):
        """La invariante 2 de CLAUDE.md, en el sentido que aquí importa.

        Todos los JWT se firman con la misma SECRET_KEY. Sin comprobar `purpose`, el
        token de sesión del dashboard —o el `state` del OAuth, que viaja en la barra de
        direcciones— serviría para abrir un puente de voz contra Jarvis.
        """
        de_usuario = jwt.encode({"sub": "mikel"}, main.SECRET_KEY, algorithm=main.ALGORITHM)
        assert main._leer_contexto_llamada(de_usuario) == {}

    def test_un_token_de_otro_proposito_tampoco(self):
        otro = jwt.encode({"purpose": "oauth_state"}, main.SECRET_KEY, algorithm=main.ALGORITHM)
        assert main._leer_contexto_llamada(otro) == {}

    def test_firmado_con_otra_clave_no_vale(self):
        ajeno = jwt.encode({"purpose": "llamada", "texto": "despliega"}, "otra-clave",
                           algorithm=main.ALGORITHM)
        assert main._leer_contexto_llamada(ajeno) == {}

    def test_basura_no_revienta(self):
        assert main._leer_contexto_llamada("no-es-un-jwt") == {}


class TestFirmaDeTwilio:
    """El vector de ejemplo de la documentación de Twilio.

    Se usa el suyo y no uno calculado aquí a propósito: comprobar mi HMAC contra mi HMAC
    no prueba nada, solo que la función es determinista.
    """
    URL = "https://mycompany.com/myapp.php?foo=1&bar=2"
    CUERPO = {"CallSid": "CA1234567890ABCDE", "Caller": "+14158675309",
              "Digits": "1234", "From": "+14158675309", "To": "+18005551212"}
    FIRMA = "RSOYDt4T1cUTdK1PDd93/VVr8B8="

    def _peticion(self, firma):
        return SimpleNamespace(headers={"X-Twilio-Signature": firma}, url=self.URL)

    def test_la_firma_buena_pasa(self, monkeypatch):
        monkeypatch.setattr(main, "TWILIO_TOKEN", "12345")
        assert main._firma_twilio_ok(self._peticion(self.FIRMA), self.CUERPO) is True

    def test_una_firma_cualquiera_no(self, monkeypatch):
        monkeypatch.setattr(main, "TWILIO_TOKEN", "12345")
        assert main._firma_twilio_ok(self._peticion("AAAA="), self.CUERPO) is False

    def test_sin_firma_no(self, monkeypatch):
        monkeypatch.setattr(main, "TWILIO_TOKEN", "12345")
        assert main._firma_twilio_ok(self._peticion(""), self.CUERPO) is False

    def test_sin_token_configurado_no_pasa_nadie(self, monkeypatch):
        """Fail-closed, como `_token_ok`: sin el token esperado no vale ninguna firma."""
        monkeypatch.setattr(main, "TWILIO_TOKEN", "")
        assert main._firma_twilio_ok(self._peticion(self.FIRMA), self.CUERPO) is False


class TestPuertaDeEntrada:
    def test_sin_firma_no_se_abre_el_puente(self, client):
        r = client.post("/telefono/voz?ctx=loquesea", data={"CallSid": "CA1"})
        assert r.status_code == 403

    def test_cuerpo_grande_da_413_antes_de_comprobar_la_firma(self, client, monkeypatch):
        """Invariante 8 de CLAUDE.md: el endpoint es público (lo llama Twilio sin
        cabeceras nuestras), así que hasta que la firma no se comprueba el cuerpo puede
        venir de cualquiera. El tamaño se corta antes de mirar la firma, no después."""
        monkeypatch.setattr(main, "MAX_TELEFONO_BYTES", 100)
        r = client.post("/telefono/voz?ctx=loquesea", content=b"CallSid=" + b"x" * 500,
                        headers={"Content-Type": "application/x-www-form-urlencoded"})
        assert r.status_code == 413

    def test_cuerpo_dentro_del_limite_sigue_pasando_por_la_firma(self, client, monkeypatch):
        monkeypatch.setattr(main, "MAX_TELEFONO_BYTES", 100)
        r = client.post("/telefono/voz?ctx=loquesea", data={"CallSid": "CA1"})
        assert r.status_code == 403


class TestSiONo:
    """Lo que se entiende por un permiso para desplegar.

    Es la lista más peligrosa del fichero: un falso positivo aquí despliega producción
    porque alguien dijo algo parecido a «sí». La regla es que ante la duda NO se
    despliega — de los dos errores, ese es el único que se puede deshacer solo.
    """
    @pytest.mark.parametrize("frase", [
        "sí", "si", "vale", "adelante", "despliega", "despliégalo", "hazlo",
        "sí, despliégalo", "vale adelante", "ok", "claro que sí",
    ])
    def test_los_sies(self, frase):
        assert main._sio_no(frase) is True

    @pytest.mark.parametrize("frase", [
        "no", "ahora no", "espera", "déjalo", "mejor no", "no, espera", "todavía no",
    ])
    def test_los_noes(self, frase):
        assert main._sio_no(frase) is False

    @pytest.mark.parametrize("frase", [
        "¿qué se ha roto exactamente?",
        "cuéntame qué has cambiado",
        "el otro día dijiste que sí",
        "",
    ])
    def test_lo_que_no_es_ni_una_cosa_ni_otra(self, frase):
        """Se le pasa al modelo como una frase más. No es un permiso."""
        assert main._sio_no(frase) is None

    def test_el_no_gana_al_si(self):
        """«no, mejor despliega luego» empieza por no. Y el no se mira primero."""
        assert main._sio_no("no, despliega luego") is False

    def test_la_palabra_dentro_de_la_frase_no_cuenta(self):
        """Solo se mira el principio: la palabra suelta a mitad de frase no es respuesta."""
        assert main._sio_no("me pregunto si deberíamos desplegar esto") is None


class TestAudio:
    def test_ulaw_a_pcm16(self):
        """Valores de la tabla G.711, comprobados contra `audioop` de la stdlib.

        Van fijos y no calculados contra `audioop` en vivo porque ese módulo desaparece
        en Python 3.13 y este test tiene que sobrevivir a la actualización — que es
        justo el motivo por el que la tabla está escrita a mano.
        """
        for byte, esperado in ((0, -32124), (127, 0), (128, 32124), (255, 0)):
            pcm = main._ulaw_a_pcm16(bytes([byte]))
            assert int.from_bytes(pcm, "little", signed=True) == esperado

    def test_cada_muestra_ocupa_el_doble(self):
        assert len(main._ulaw_a_pcm16(bytes(160))) == 320

    def test_el_silencio_tiene_energia_baja_y_la_voz_no(self):
        """El VAD entero: por debajo del umbral es silencio, por encima es alguien hablando."""
        silencio = main._ulaw_a_pcm16(bytes([127] * 160))
        assert main._rms(silencio) < main.VOZ_UMBRAL_RMS
        voz = main._ulaw_a_pcm16(bytes([0, 128] * 80))
        assert main._rms(voz) > main.VOZ_UMBRAL_RMS

    def test_rms_de_nada_es_cero(self):
        assert main._rms(b"") == 0.0

    def test_la_cabecera_wav(self):
        """Whisper necesita un fichero, no muestras sueltas."""
        wav = main._wav_de_pcm16(b"\x00\x01" * 8)
        assert wav[:4] == b"RIFF" and wav[8:12] == b"WAVE"
        assert len(wav) == 44 + 16
        # 8 kHz mono 16 bits: es lo que manda el teléfono y lo que se le promete al WAV.
        assert int.from_bytes(wav[24:28], "little") == 8000
        assert int.from_bytes(wav[22:24], "little") == 1
        assert int.from_bytes(wav[40:44], "little") == 16
