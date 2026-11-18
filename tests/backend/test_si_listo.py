"""El sí que se entiende (2026-11-18): «que no solo le valga un sí, sino también un sí
hazlo, un sí dale…». Lo mismo que `siONo` de la voice-app y `respuestaHablada` del
dashboard; si cambia uno, cambian los tres."""
import pytest

import main

SI = ["sí", "Sí, hazlo", "sí, dale", "Dale caña", "venga, va", "Por supuesto", "claro que sí",
      "sí, sí, adelante", "afirmativo", "Hazlo ya, por favor", "Sí señor", "perfecto, hazlo",
      "Llámala", "sí, bórralas", "quítalas todas", "mándaselo", "ok", "Vale, gracias Jarvis",
      "sí, ponlo", "sí, apúntamelo", "sí, llama a Saioa"]
NO = ["no", "No, déjalo", "mejor no", "ni de coña", "cancélalo", "olvídalo", "no lo hagas",
      "ahora no", "para, para", "que va"]
NADA = ["", "sí, pero a las once", "espera", "no sé", "perfecto", "eso es", "correcto",
        "exacto", "si puedes, mira el calendario", "vale, y añade también el logo", "la pastilla",
        "el regalo", "sí no", "cambia la hora", "llama a Erik mejor", "¿qué hora es?",
        "sí, pero mejor mañana"]


@pytest.mark.parametrize("dicho", SI)
def test_si(dicho):
    assert main._respuesta_si_no(dicho, "¿Llamo a Saioa?") is True


@pytest.mark.parametrize("dicho", NO)
def test_no(dicho):
    assert main._respuesta_si_no(dicho) is False


@pytest.mark.parametrize("dicho", NADA)
def test_ni_si_ni_no(dicho):
    assert main._respuesta_si_no(dicho, "¿Llamo a Saioa?") is None


def test_las_palabras_de_la_pregunta_solo_valen_en_su_pregunta():
    assert main._respuesta_si_no("sí, llama a Saioa", "¿Llamo a Saioa?") is True
    assert main._respuesta_si_no("sí, llama a Saioa", "¿Llamo a Erik?") is None
