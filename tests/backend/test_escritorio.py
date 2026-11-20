"""La lógica pura del Jarvis de escritorio (agent/escritorio_logica.py).

La ventana, el micrófono y los altavoces necesitan un Windows de verdad; lo que se prueba
aquí es lo que decide, que es donde un fallo pasa sin que nadie lo vea: que AltGr (la @) o
un atajo no despierten a Jarvis, que los eventos lleguen enteros aunque la red los parta, y
que la voz reciba frases enteras y sin markdown.
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "agent"))

from escritorio_logica import Frases, LectorSSE, Tecla, debe_verse, para_voz, recorta_historial  # noqa: E402


def _secuencia(tecla, pasos):
    return [tecla.paso(*p) for p in pasos]


class TestTecla:
    def test_mantener_y_soltar_es_una_orden(self):
        t = Tecla(mantener_s=0.25)
        r = _secuencia(t, [(True, True, False, False, 0.0), (True, True, False, False, 0.1),
                           (True, True, False, False, 0.3), (True, True, False, False, 1.0),
                           (False, False, False, False, 1.2)])
        assert r == ["empieza", None, "habla", None, "suelta"]

    def test_un_roce_se_cancela(self):
        t = Tecla(mantener_s=0.25)
        assert _secuencia(t, [(True, True, False, False, 0.0),
                              (False, True, False, False, 0.1)]) == ["empieza", "cancela"]

    def test_altgr_no_despierta_a_nadie(self):
        # Para Windows, AltGr es Ctrl + Alt: con ella se escribe la @
        t = Tecla()
        assert _secuencia(t, [(True, True, True, False, 0.0), (True, True, True, True, 0.5)]) == [None, None]

    def test_un_atajo_cancela_y_no_rearma_hasta_soltar(self):
        t = Tecla(mantener_s=0.25)
        r = _secuencia(t, [(True, True, False, False, 0.0), (True, True, False, False, 0.4),
                           (True, True, False, True, 0.5),     # Ctrl + Alt + Supr
                           (True, True, False, False, 0.6),    # sigue con Ctrl + Alt
                           (False, False, False, False, 0.7),
                           (True, True, False, False, 1.0)])
        assert r == ["empieza", "habla", "cancela", None, None, "empieza"]

    def test_si_ya_habia_otra_tecla_no_empieza(self):
        assert Tecla().paso(True, True, False, True, 0.0) is None


class TestLectorSSE:
    def test_eventos_partidos_por_cualquier_sitio(self):
        flujo = ('event: texto\ndata: {"delta": "Hola, "}\n\n'
                 'event: texto\ndata: {"delta": "señor."}\n\nevent: fin\ndata: {"respuesta": "Hola, señor."}\n\n').encode()
        lector, eventos = LectorSSE(), []
        for k in range(0, len(flujo), 7):
            eventos += lector.trozo(flujo[k:k + 7])
        assert eventos == [("texto", {"delta": "Hola, "}), ("texto", {"delta": "señor."}),
                           ("fin", {"respuesta": "Hola, señor."})]

    def test_un_dato_roto_se_salta(self):
        assert LectorSSE().trozo(b"event: x\ndata: {roto\n\nevent: y\ndata: {}\n\n") == [("y", {})]


class TestFrases:
    def test_suelta_frases_enteras_segun_llegan(self):
        f = Frases()
        assert f.mete("Tiene una reunión a las ") == []
        assert f.mete("diez con el tutor. Después, ") == ["Tiene una reunión a las diez con el tutor."]
        assert f.mete("pádel a las siete") == []
        assert f.resto() == ["Después, pádel a las siete"]
        assert f.resto() == []

    def test_las_muy_cortas_esperan_a_la_siguiente(self):
        f = Frases()
        assert f.mete("Sí. Ya está encendida la luz del salón. ") == ["Sí. Ya está encendida la luz del salón."]

    def test_sin_markdown_ni_enlaces(self):
        assert para_voz("**Dune** está [aquí](https://x.y) y en https://z.w `ya`") == "Dune está aquí y en ya"


def test_historial_recortado_y_con_la_forma_del_backend():
    h = [{"rol": "user", "texto": f"t{i}"} for i in range(20)] + [{"rol": "system", "texto": "x"}, "basura"]
    r = recorta_historial(h, maximo=5)
    assert len(r) == 5 and r[-1] == {"rol": "user", "texto": "t19"}


def test_el_reactor_solo_se_ve_al_hablarle():
    """2026-11-20: en reposo desaparece; oyendo, pensando, hablando, con un error o sin
    sesión se ve, y mientras siga abierta la respuesta. «Siempre a la vista» lo deja fijo."""
    assert not debe_verse("reposo", bocadillo=False)
    for estado in ("escucha", "piensa", "habla", "error", "sin_sesion"):
        assert debe_verse(estado, bocadillo=False)
    assert debe_verse("reposo", bocadillo=True)
    assert debe_verse("reposo", bocadillo=False, siempre=True)
