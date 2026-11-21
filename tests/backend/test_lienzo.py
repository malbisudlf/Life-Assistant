"""El lienzo de Jarvis (agent/lienzo_logica.py): lo que se dibuja y cómo avanza un tutorial.

Lo que llega lo decide un modelo que pudo leer una web, así que el esquema es cerrado: lo
que no se entiende se tira. Y un tutorial avanza solo con lo que hace Mikel.
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "agent"))

import lienzo_logica as L  # noqa: E402


class TestEsquema:
    def test_marcas_por_nombre_o_por_punto(self):
        marcas = L.validar_marcas([
            {"objetivo": "Guardar", "texto": "Aquí", "forma": "caja"},
            {"x": 0.5, "y": 0.25, "forma": "cohete"},
            {"x": 2, "y": 0.5},                  # fuera de la pantalla
            {"texto": "sin sitio"},
            "una cadena",
        ])
        assert marcas == [{"forma": "caja", "texto": "Aquí", "objetivo": "Guardar"},
                          {"forma": "anillo", "texto": "", "x": 0.5, "y": 0.25}]

    def test_como_mucho_ocho_marcas_y_textos_cortos(self):
        marcas = L.validar_marcas([{"objetivo": f"b{i}", "texto": "x" * 500} for i in range(20)])
        assert len(marcas) == L.MAX_MARCAS
        assert len(marcas[0]["texto"]) == L.MAX_TEXTO

    def test_la_tarjeta_solo_trae_texto_y_cifras(self):
        t = L.validar_tarjeta({"titulo": "Sueño", "lineas": ["7 h", "", 3],
                               "barras": [{"etiqueta": "Lun", "valor": "6.5"},
                                          {"etiqueta": "Mar", "valor": "nada"}],
                               "serie": [1, "2", None, float("nan"), 4],
                               "html": "<script>"})
        assert t == {"titulo": "Sueño", "lineas": ["7 h", "3"],
                     "barras": [{"etiqueta": "Lun", "valor": 6.5}], "serie": [1.0, 2.0, 4.0]}

    def test_una_tarjeta_vacia_no_es_tarjeta(self):
        assert L.validar_tarjeta({"serie": [1]}) is None
        assert L.validar_tarjeta("hola") is None

    def test_segundos(self):
        assert L.segundos(None) == L.SEGUNDOS_POR_DEFECTO
        assert L.segundos(9999) == L.SEGUNDOS_MAX
        assert L.segundos("5") == 5

    def test_pasos(self):
        pasos = L.validar_pasos([{"texto": "Abra Ajustes", "objetivo": "Ajustes"},
                                 {"texto": "Y ya está"},
                                 {"objetivo": "sin texto"},
                                 {"texto": "Mire", "objetivo": "Barra", "tipo": "mira"}])
        assert [p["tipo"] for p in pasos] == ["clic", "mira", "mira"]
        assert len(L.validar_pasos([{"texto": "x"}] * 30)) == L.MAX_PASOS


class TestColocar:
    PANTALLA = (0, 0, 1920, 1080)

    def test_debajo_si_cabe(self):
        assert L.donde_etiqueta((100, 100, 200, 130), 150, 40, self.PANTALLA) == (100, 148)

    def test_encima_si_debajo_no_cabe(self):
        x, y = L.donde_etiqueta((100, 1040, 200, 1070), 150, 40, self.PANTALLA)
        assert y + 40 <= 1040

    def test_no_tapa_otra_marca(self):
        boton, otro = (100, 100, 200, 130), (90, 140, 400, 200)
        x, y = L.colocar(boton, 150, 40, self.PANTALLA, [otro])
        assert not L.se_pisan((x, y, x + 150, y + 40), otro)
        assert not L.se_pisan((x, y, x + 150, y + 40), boton)

    def test_en_la_segunda_pantalla_a_la_izquierda(self):
        pantallas = [(-3840, 0, 0, 2160), (0, 0, 2560, 1440)]
        assert L.pantalla_de((-100, 50), pantallas) == (-3840, 0, 0, 2160)
        x, _ = L.donde_etiqueta((-60, 50, -10, 80), 300, 40, pantallas[0])
        assert x + 300 <= 0

    def test_la_fraccion_cubre_todas_las_pantallas(self):
        assert L.de_fraccion(0.5, 0.5, (-3840, 0, 2560, 2160)) == (-640, 1080)


class TestTutorial:
    def _tutorial(self):
        return L.Tutorial("Modo oscuro", L.validar_pasos([
            {"texto": "Abra Ajustes", "objetivo": "Ajustes"},
            {"texto": "Así queda"},
        ]))

    def test_avanza_con_el_clic_en_el_boton_y_no_fuera(self):
        t = self._tutorial()
        t.empezar_paso(0)
        assert t.clic(10, 10) is False            # aún buscando el botón
        t.encontrado((100, 100, 200, 130))
        assert t.clic(500, 500) is False
        assert t.clic(150, 140) is True           # dentro, con margen

    def test_si_no_encuentra_el_boton_vale_cualquier_clic(self):
        t = self._tutorial()
        t.empezar_paso(0)
        t.encontrado(None)
        assert t.clic(1, 1) is True

    def test_un_paso_de_mirar_sigue_al_acabar_de_decirse(self):
        t = self._tutorial()
        t.avanzar()
        t.empezar_paso(10)
        assert t.clic(1, 1) is False              # no se salta con un clic
        assert not t.toca_seguir(11)
        t.dicho(11)
        assert not t.toca_seguir(12)              # 1,5 s después de decirlo…
        assert t.toca_seguir(13)                  # …y nunca antes de 3 s

    def test_termina_y_caduca(self):
        t = self._tutorial()
        t.empezar_paso(0)
        assert t.caducado(L.PASO_MAX_S + 1)
        t.avanzar()
        t.avanzar()
        assert t.fin == "hecho" and t.actual is None
        assert t.estado() == {"titulo": "Modo oscuro", "paso": 2, "de": 2, "fin": "hecho"}
