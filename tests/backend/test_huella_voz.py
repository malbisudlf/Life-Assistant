"""El servicio de la huella de voz de jacobo (telefono/huella-voz/servidor.py).

El modelo no se carga aquí (sherpa-onnx y un .onnx de 26 MB): va un extractor de mentira
que convierte el audio en un vector conocido. Lo que se prueba es lo que decide quién
pasa: la huella del alta, la media del canal, el umbral y que una huella de otro modelo o
de otra media no se use nunca.
"""

import json
import os
import sys

import pytest

# numpy no es del backend: lo instala el CI solo para estos tests (ci.yml)
np = pytest.importorskip("numpy")

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "telefono", "huella-voz"))

import servidor as hv  # noqa: E402


def pcm(segundos, valor=1000):
    """PCM s16le de `segundos`; `valor` distingue unas «voces» de otras."""
    return np.full(int(segundos * hv.MUESTRAS_SEG), valor, dtype="<i2").tobytes()


class ExtractorFalso:
    """La «voz» es el primer valor del audio: cada valor tiene su vector fijo."""

    nombre = "falso.onnx"

    def __init__(self, vectores):
        self.vectores = vectores

    def vector(self, muestras):
        clave = int(round(float(muestras[0]) * 32768))
        return hv.unitario(np.array(self.vectores[clave], dtype=np.float32))


MIKEL = [1.0, 0.2, 0.0]
OTRO = [0.0, 0.2, 1.0]
VOCES = {1000: MIKEL, 2000: OTRO, 1001: [0.95, 0.25, 0.05], 1002: [1.0, 0.1, 0.1]}


def servicio(tmp_path, extractor=None, clave="falso.onnx", umbral=0.4):
    ex = extractor or ExtractorFalso(VOCES)
    return hv.Huella(ex, hv.Almacen(str(tmp_path), clave), umbral=umbral)


def alta(s, valores, segundos=6):
    frases = [pcm(segundos, v) for v in valores]
    return s.alta(b"".join(frases), ",".join(str(len(f)) for f in frases))


class TestAlta:
    def test_graba_y_reconoce(self, tmp_path):
        s = servicio(tmp_path)
        codigo, info = alta(s, [1000, 1001, 1002])
        assert codigo == 200 and info["frases"] == 3
        codigo, r = s.verificar(pcm(2, 1000))
        assert codigo == 200 and r["es_el"]
        codigo, r = s.verificar(pcm(2, 2000))
        assert codigo == 200 and not r["es_el"]

    def test_descarta_la_frase_que_no_es_suya(self, tmp_path):
        s = servicio(tmp_path)
        codigo, info = alta(s, [1000, 1001, 1002, 2000])
        assert codigo == 200
        assert info["descartadas"] == 1 and info["frases"] == 3

    def test_poca_voz_no_graba(self, tmp_path):
        s = servicio(tmp_path)
        codigo, info = alta(s, [1000, 1001, 1002], segundos=2)
        assert codigo == 422 and info["motivo"] == "poca_voz"
        assert s.almacen.huella() is None

    def test_frases_mal_contadas(self, tmp_path):
        s = servicio(tmp_path)
        assert s.alta(pcm(6), "123")[0] == 400

    def test_la_anterior_se_guarda(self, tmp_path):
        s = servicio(tmp_path)
        alta(s, [1000, 1001, 1002])
        alta(s, [1000, 1001, 1002])
        assert os.path.exists(tmp_path / "huella.anterior.json")


class TestVerificar:
    def test_sin_huella(self, tmp_path):
        assert servicio(tmp_path).verificar(pcm(2))[0] == 409

    def test_poco_audio_e_impar(self, tmp_path):
        s = servicio(tmp_path)
        assert s.verificar(pcm(0.2))[1]["motivo"] == "poco_audio"
        assert s.verificar(b"\x00\x00\x00")[1]["motivo"] == "audio_impar"


class TestHuellaDeOtroModelo:
    def test_otra_clave_no_carga_la_huella(self, tmp_path):
        alta(servicio(tmp_path, clave="falso.onnx+media-aaa"), [1000, 1001, 1002])
        assert hv.Almacen(str(tmp_path), "falso.onnx+media-aaa").huella() is not None
        # Misma huella.json, pero con otra media (o sin ella): no vale
        assert hv.Almacen(str(tmp_path), "falso.onnx+media-bbb").huella() is None
        assert hv.Almacen(str(tmp_path), "falso.onnx").huella() is None


class TestMediaDelCanal:
    def test_resta_la_media_y_vuelve_a_unitario(self):
        media = np.array([0.5, 0.5, 0.0], dtype=np.float32)
        ex = hv.ConMedia(ExtractorFalso({1000: [1.0, 0.0, 0.0]}), media, "media-x")
        v = ex.vector(np.full(10, 1000 / 32768, dtype=np.float32))
        esperado = hv.unitario(np.array([1.0, 0.0, 0.0]) - media)
        assert np.allclose(v, esperado) and abs(np.linalg.norm(v) - 1) < 1e-6
        assert ex.id == "falso.onnx+media-x"

    def test_separa_voces_que_el_canal_junta(self, tmp_path):
        # Dos voces que el canal empuja hacia un mismo sitio: a pelo se parecen
        # demasiado (0,93); quitando lo común, ya no.
        canal = np.array([0.0, 3.0, 0.0])
        voces = {1000: canal + [1.0, 0, 0], 1001: canal + [1.0, 0, 0.1],
                 1002: canal + [1.0, 0.1, 0], 2000: canal + [0, 0, 1.0]}
        a_pelo = servicio(tmp_path / "a", ExtractorFalso(voces), umbral=0.4)
        (tmp_path / "a").mkdir()
        alta(a_pelo, [1000, 1001, 1002])
        assert a_pelo.verificar(pcm(2, 2000))[1]["es_el"]          # le cuela al otro

        media = hv.unitario(canal)
        (tmp_path / "b").mkdir()
        con_media = servicio(tmp_path / "b", hv.ConMedia(ExtractorFalso(voces), media, "m"), umbral=0.4)
        alta(con_media, [1000, 1001, 1002])
        assert not con_media.verificar(pcm(2, 2000))[1]["es_el"]   # ya no
        assert con_media.verificar(pcm(2, 1000))[1]["es_el"]

    def test_leer_media(self, tmp_path):
        ruta = tmp_path / "media.npy"
        np.save(ruta, np.array([0.1, 0.2], dtype=np.float32))
        v, id_media = hv.leer_media(str(ruta))
        assert np.allclose(v, [0.1, 0.2]) and id_media.startswith("media-")
        # Mismo contenido, mismo id; otro contenido, otro
        np.save(tmp_path / "otra.npy", np.array([0.1, 0.3], dtype=np.float32))
        assert hv.leer_media(str(ruta))[1] == id_media
        assert hv.leer_media(str(tmp_path / "otra.npy"))[1] != id_media

    def test_media_nombrada_y_ausente_no_arranca(self, tmp_path):
        with pytest.raises(RuntimeError):
            hv.leer_media(str(tmp_path / "no-esta.npy"))
        assert hv.leer_media("") == (None, None)


class TestArranque:
    def test_fuera_de_local_sin_llave_no(self):
        with pytest.raises(RuntimeError):
            hv.comprobar_arranque("0.0.0.0", "")
        hv.comprobar_arranque("0.0.0.0", "llave")
        hv.comprobar_arranque("127.0.0.1", "")


class TestNadaDeAudioEnDisco:
    def test_solo_el_vector_y_sus_numeros(self, tmp_path):
        alta(servicio(tmp_path), [1000, 1001, 1002])
        assert sorted(os.listdir(tmp_path)) == ["huella.json"]
        d = json.loads((tmp_path / "huella.json").read_text(encoding="utf-8"))
        assert set(d) == {"frases", "descartadas", "segundos", "consistencia", "modelo", "fecha", "vector"}
