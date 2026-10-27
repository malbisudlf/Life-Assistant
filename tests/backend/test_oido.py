"""La lógica pura del oído de jacobo (telefono/oido/acuerdo.py).

El servidor no se prueba aquí: necesita whisper.cpp y una GPU. Lo que sí se prueba es lo
que decide qué texto se da por bueno, que es donde un error pasa sin que nadie lo vea.
"""

import os
import sys
import wave
import io

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "telefono", "oido"))

from acuerdo import Acuerdo, dice_nombre, es_alucinacion, limpia, normaliza, rms, wav_de_pcm16  # noqa: E402


class TestAcuerdo:
    def test_lo_que_coincide_en_dos_pasadas_queda_fijo(self):
        a = Acuerdo()
        assert a.pasada("Jarvis enciende") == ("", "Jarvis enciende")
        assert a.pasada("Jarvis, enciende la luz") == ("Jarvis, enciende", "la luz")

    def test_lo_fijo_no_se_desdice(self):
        a = Acuerdo()
        a.pasada("apaga la luz del salón")
        a.pasada("apaga la luz del salón")
        # Whisper cambia de opinión sobre una palabra ya fijada: se queda lo fijado
        fijo, provisional = a.pasada("apaga las luces del salón ya")
        assert fijo == "apaga la luz del salón"
        assert provisional == "ya"

    def test_compara_sin_tildes_ni_signos(self):
        a = Acuerdo()
        a.pasada("¿Qué tiempo hace?")
        assert a.pasada("que tiempo hace mañana")[0] == "que tiempo hace"

    def test_reinicia_empieza_de_cero(self):
        a = Acuerdo()
        a.pasada("hola")
        a.pasada("hola")
        a.reinicia()
        assert a.pasada("adiós") == ("", "adiós")


class TestNombre:
    def test_oye_jarvis_en_cualquier_punto(self):
        assert dice_nombre("y entonces le dije, Jarvis, pon música")
        assert dice_nombre("JARVIS")

    def test_como_lo_escribe_whisper_por_telefono(self):
        assert dice_nombre("Yarvis, ¿qué hora es?")
        assert dice_nombre("Járvis apaga")
        # Como lo parte `small` en los parciales
        assert dice_nombre("Y Arvis, ¿qué tiempo va a hacer mañana?")
        assert dice_nombre("Oye, vamos a ver, ya, Arvis.")

    def test_no_salta_con_palabras_parecidas(self):
        assert not dice_nombre("jarvisito")
        assert not dice_nombre("Jar vis")
        assert not dice_nombre("")


class TestAlucinaciones:
    def test_los_subtitulos_inventados_no_cuentan(self):
        assert es_alucinacion("Subtítulos realizados por la comunidad de Amara.org")
        assert es_alucinacion("¡Gracias por ver el video!")
        assert es_alucinacion("  ")

    def test_gracias_a_secas_si_cuenta(self):
        # Es lo que se le dice a Jarvis al acabar: contra la alucinación está el umbral de
        # silencio del servidor, no esta lista
        assert not es_alucinacion("Gracias.")
        assert not es_alucinacion("gracias por avisarme")

    def test_las_acotaciones_se_quitan(self):
        # Medido en jacobo: «[MÚSICA]» al empezar una frase, como texto provisional
        assert limpia("[MÚSICA] no fueron golpes") == "no fueron golpes"
        assert limpia("vale (risas) ya está") == "vale ya está"
        assert es_alucinacion(limpia("[Música]"))


class TestAudio:
    def test_rms(self):
        assert rms(b"") == 0.0
        assert rms((1000).to_bytes(2, "little", signed=True) * 10) == 1000.0
        assert rms((-1000).to_bytes(2, "little", signed=True) * 10) == 1000.0
        assert rms(b"\x00\x00" * 50) == 0.0

    def test_wav_se_lee_con_el_modulo_estandar(self):
        pcm = (1234).to_bytes(2, "little", signed=True) * 8000
        with wave.open(io.BytesIO(wav_de_pcm16(pcm, 8000))) as w:
            assert (w.getnchannels(), w.getsampwidth(), w.getframerate()) == (1, 2, 8000)
            assert w.readframes(w.getnframes()) == pcm

    def test_normaliza(self):
        assert normaliza("¡Hola, Señor!") == "hola senor"
