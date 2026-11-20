"""La grabación de las llamadas a otros (parche 52), del lado del backend (2026-11-20).

Lo que se protege: que se pida con la llave de los terceros, que se vuelva a transcribir
SOLO el canal del otro (el izquierdo) con el modelo grande de jacobo, que el audio le llegue
por Telegram, que lo transcrito cuente como ajeno, y que sin grabación se diga por qué.
"""
import io
import time
import wave

import pytest

import main
from conftest import FakeResponse

TID = "11111111-2222-3333-4444-555555555555"


def _wav_estereo(izq: int, der: int, n: int = 800) -> bytes:
    b = io.BytesIO()
    with wave.open(b, "wb") as w:
        w.setnchannels(2)
        w.setsampwidth(2)
        w.setframerate(8000)
        w.writeframes(b"".join(izq.to_bytes(2, "little", signed=True) + der.to_bytes(2, "little", signed=True)
                               for _ in range(n)))
    return b.getvalue()


@pytest.fixture
def centralita(monkeypatch, mock_requests):
    monkeypatch.setattr(main, "TELEFONO_URL", "http://voz.test:3000")
    monkeypatch.setattr(main, "TELEFONO_TERCEROS_TOKEN", "llave-terceros")
    monkeypatch.setattr(main, "OIDO_URL", "http://jacobo.test:8770")
    monkeypatch.setattr(main, "OIDO_TOKEN", "llave-oido")
    monkeypatch.setattr(main, "TELEGRAM_BOT_TOKEN", "")
    monkeypatch.setattr(main, "_terceros", {TID: {"tid": TID, "nombre": "Erik", "creada": time.time() - 600}})
    return mock_requests


class TestGrabacion:
    def test_transcribe_solo_al_otro_con_el_modelo_grande(self, centralita):
        centralita.add("GET", f"/api/grabacion/{TID}", FakeResponse(None, 200, content=_wav_estereo(1000, -7)))
        centralita.add("POST", "/transcribir", FakeResponse({"texto": "En el Maine, el bar de la plaza."}))
        r = main._j_llamada_grabacion("erik", enviar=False)
        assert r["ok"] is True and r["lo_que_dijo_el_otro"] == "En el Maine, el bar de la plaza."
        assert r["transcrito_por"] == "jacobo" and r["llamada"].startswith("Erik (")
        (_, _, kw_g), (_, _, kw_t) = centralita.calls
        assert kw_g["headers"]["X-Auth-Token"] == "llave-terceros"
        assert kw_t["headers"]["X-Modelo"] == "final"
        # Solo el canal izquierdo (el otro): mono y con sus muestras
        with wave.open(io.BytesIO(kw_t["data"]), "rb") as w:
            assert w.getnchannels() == 1
            assert int.from_bytes(w.readframes(1), "little", signed=True) == 1000
        assert r["aviso"].startswith(main._AVISO_WEB)
        assert "llamada_grabacion" in main._HERRAMIENTAS_AJENAS

    def test_le_manda_el_audio_por_telegram(self, centralita, monkeypatch):
        monkeypatch.setattr(main, "TELEGRAM_BOT_TOKEN", "bot")
        monkeypatch.setattr(main, "TELEGRAM_CHAT_ID", "123")
        enviados = []
        monkeypatch.setattr(main, "_telegram_api", lambda m, datos=None, ficheros=None:
                            enviados.append((m, datos, ficheros)) or ({"ok": True}, 200))
        centralita.add("GET", f"/api/grabacion/{TID}", FakeResponse(None, 200, content=_wav_estereo(1, 2)))
        centralita.add("POST", "/transcribir", FakeResponse({"texto": "hola"}))
        r = main._j_llamada_grabacion()
        assert r["enviada_por_telegram"] is True
        (metodo, datos, ficheros), = enviados
        assert metodo == "sendDocument" and datos["chat_id"] == "123"
        nombre, audio, tipo = ficheros["document"]
        assert nombre.startswith("erik-") and nombre.endswith(".wav") and tipo == "audio/wav"

    def test_sin_grabacion_lo_dice(self, centralita):
        centralita.add("GET", f"/api/grabacion/{TID}", FakeResponse({"ok": False}, 404))
        r = main._j_llamada_grabacion("Erik")
        assert r["ok"] is False and "parche 52" in r["error"]

    def test_a_quien_no_se_ha_llamado(self, centralita):
        r = main._j_llamada_grabacion("Aimar")
        assert r["ok"] is False and "Aimar" in r["error"]
        assert not centralita.calls

    def test_tras_un_reinicio_tira_de_la_lista_de_la_centralita(self, centralita, monkeypatch):
        monkeypatch.setattr(main, "_terceros", {})
        otra = "22222222-2222-3333-4444-555555555555"
        centralita.add("GET", "/api/grabaciones", FakeResponse(
            {"grabaciones": [{"id": otra, "fecha": "2026-11-20T18:00:00Z"}, {"id": "../x"}]}))
        centralita.add("GET", f"/api/grabacion/{otra}", FakeResponse(None, 200, content=_wav_estereo(1, 2)))
        centralita.add("POST", "/transcribir", FakeResponse({"texto": "vale"}))
        r = main._j_llamada_grabacion(enviar=False)
        assert r["ok"] is True and r["llamada"] == "la última llamada (20/11 19:00)"

    def test_si_jacobo_falla_transcribe_openai(self, centralita, monkeypatch):
        centralita.add("GET", f"/api/grabacion/{TID}", FakeResponse(None, 200, content=_wav_estereo(1, 2)))
        centralita.add("POST", "/transcribir", FakeResponse({}, 500))

        class Cliente:
            class audio:
                class transcriptions:
                    @staticmethod
                    def create(**kw):
                        return type("R", (), {"text": "en el bar Mine"})()
        monkeypatch.setattr(main, "get_openai_client", lambda: Cliente)
        r = main._j_llamada_grabacion(enviar=False)
        assert r["transcrito_por"] == "openai" and r["lo_que_dijo_el_otro"] == "en el bar Mine"


def test_un_wav_mono_se_queda_como_esta():
    b = io.BytesIO()
    with wave.open(b, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(8000)
        w.writeframes(b"\x01\x00" * 10)
    assert main._wav_un_canal(b.getvalue()) == b.getvalue()
