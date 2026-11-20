"""El índice del buscador de la vida (vida/indice.py), el que corre en jacobo.

Se prueba la lógica pura: que encuentre lo que se dijo con otras formas de la misma palabra
(plurales, tildes), que una palabra de más no deje sin resultados, que mandar dos veces lo
mismo no lo duplique, y que lo mal formado no entre.
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "vida"))

from indice import Indice, consulta_fts, palabras, raiz  # noqa: E402


def _doc(id_, texto, fuente="whatsapp", fecha="2025-11-02T18:20:00Z", **extra):
    return {"id": id_, "fuente": fuente, "fecha": fecha, "texto": texto, **extra}


class TestPalabras:
    def test_quita_las_vacias_y_los_plurales(self):
        assert palabras("¿Qué le regalé a mi madre el año pasado?") == ["regal", "madre"]
        # «regalé», «regalos» y «regalo» acaban igual: se encuentran entre sí
        assert raiz("regalos") == raiz("regalo") == raiz("regale") == "regal"
        assert raiz("canciones") == "cancion"
        assert raiz("clases") == "clas"

    def test_un_tiempo_verbal_encuentra_al_sustantivo(self):
        i = Indice()
        i.guardar([_doc("1", "Le regalo a mi madre unos pendientes")])
        assert i.buscar("qué le regalé a mi madre")["resultados"][0]["id"] == "1"

    def test_la_consulta_no_deja_colar_operadores(self):
        assert consulta_fts(["dune", "or", "near"]) == '"dune"* "or" "near"*'
        assert consulta_fts(["perfume", "madre"], todas=False) == '"perfume"* OR "madre"*'
        assert palabras('NEAR("x" OR y) -*') == ["near", "or"]


class TestBuscar:
    def test_encuentra_con_tildes_y_plurales(self):
        i = Indice()
        i.guardar([_doc("1", "Al final le compré a mi madre el perfume de Loewe por su cumpleaños"),
                   _doc("2", "Mañana pádel a las 19:00", fecha="2025-11-03")])
        r = i.buscar("cumpleanos perfumes")
        assert r["modo"] == "todas"
        assert [x["id"] for x in r["resultados"]] == ["1"]
        assert "«perfume»" in r["resultados"][0]["fragmento"]

    def test_si_no_salen_todas_busca_alguna(self):
        i = Indice()
        i.guardar([_doc("1", "Cena en el Asador Etxebarri con Ane")])
        r = i.buscar("cena restaurante Bilbao Ane")
        assert r["modo"] == "alguna" and r["resultados"][0]["id"] == "1"

    def test_filtra_por_fuente_y_fecha(self):
        i = Indice()
        i.guardar([_doc("w", "dentista revisión"),
                   _doc("c", "Cita dentista", fuente="agenda", fecha="2026-03-10T09:00:00Z"),
                   _doc("v", "dentista otra vez", fuente="agenda", fecha="2024-01-01")])
        assert [x["id"] for x in i.buscar("dentista", fuentes=["agenda"], desde="2025-01-01")["resultados"]] == ["c"]
        assert {x["id"] for x in i.buscar("dentista", hasta="2025-11-02")["resultados"]} == {"w", "v"}

    def test_el_titulo_pesa_mas(self):
        i = Indice()
        i.guardar([_doc("a", "hablamos de la reunión y de otras cosas largas y más cosas", fuente="correo"),
                   _doc("b", "nada", titulo="Reunión de tutoría", fuente="correo")])
        assert i.buscar("reunion")["resultados"][0]["id"] == "b"

    def test_sin_palabras_no_busca(self):
        assert Indice().buscar("¿qué?")["resultados"] == []


class TestGuardar:
    def test_dos_veces_lo_mismo_no_duplica_y_reescribe(self):
        i = Indice()
        i.guardar([_doc("1", "primera versión")])
        i.guardar([_doc("1", "segunda versión")])
        assert i.estado() == {"whatsapp": {"n": 1, "ultimo": "2025-11-02T18:20:00Z"}}
        assert i.buscar("segunda")["resultados"] and not i.buscar("primera")["resultados"]

    def test_lo_mal_formado_no_entra(self):
        r = Indice().guardar([_doc("", "x"), _doc("1", "x", fuente="Mal; drop"),
                              _doc("2", "x", fecha="ayer"), _doc("3", "   "), "basura",
                              _doc("4", "bien")])
        assert r == {"guardados": 1, "rechazados": 5}

    def test_olvidar_una_fuente(self):
        i = Indice()
        i.guardar([_doc("1", "hola"), _doc("2", "hola", fuente="correo")])
        assert i.olvidar("whatsapp") == 1
        assert set(i.estado()) == {"correo"}
        assert i.olvidar("") == 0
