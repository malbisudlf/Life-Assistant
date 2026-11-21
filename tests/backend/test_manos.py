"""Las manos finas de Jarvis (agent/manos.py), sin Windows.

UI Automation necesita un escritorio de verdad y se probó a mano el 2026-11-21. Aquí, lo
que decide: qué botón casa con «guardar», y sobre todo qué no se pulsa nunca.
"""
import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "agent"))

import manos  # noqa: E402


def _el(nombre, tipo_id=50000, activo=True):
    return {"nombre": nombre, "tipo_id": tipo_id, "activo": activo, "rect": (0, 0, 10, 10)}


class TestLoIrreversible:
    @pytest.mark.parametrize("nombre", [
        "Enviar", "Send", "Enviar mensaje", "Comprar ahora", "Pagar 49,99 €", "Buy now",
        "Eliminar", "Borrar conversación", "Delete", "Publicar", "Post", "Tramitar pedido",
        "Desinstalar", "Transferir", "Firmar", "Suscribirse", "Vaciar papelera",
        "Responder a todos", "Darse de baja", "Restablecer",
    ])
    def test_no_se_pulsa(self, nombre):
        assert manos.es_irreversible(nombre)

    @pytest.mark.parametrize("nombre", [
        "Guardar", "Aceptar", "Ajustes", "Modo oscuro", "Cancelar", "Siguiente", "Abrir",
        "Configuración", "Buscar", "Actualizar", "Pestaña nueva", "Postura",
    ])
    def test_lo_de_cada_dia_si(self, nombre):
        assert not manos.es_irreversible(nombre)

    def test_las_tildes_y_mayusculas_no_lo_esquivan(self):
        assert manos.es_irreversible("ENVÍAR") and manos.es_irreversible("Envío")

    def test_el_freno_salta_antes_de_tocar_nada(self):
        # Sin Windows ni elemento real: si llegara a buscar el patrón, fallaría de otra forma.
        if not manos.ES_WINDOWS:
            pytest.skip("pulsar solo existe en Windows")
        with pytest.raises(manos.Irreversible):
            manos.pulsar({"nombre": "Enviar", "_el": None})


class TestElegir:
    def test_gana_el_exacto_y_luego_el_mas_corto(self):
        els = [_el("Guardar como"), _el("Guardar"), _el("Autoguardar")]
        assert manos.elegir_elemento("guardar", els)["nombre"] == "Guardar"

    def test_empieza_por_antes_que_contiene(self):
        els = [_el("Autoguardar activado"), _el("Guardar todo")]
        assert manos.elegir_elemento("guardar", els)["nombre"] == "Guardar todo"

    def test_todas_las_palabras_en_cualquier_orden(self):
        els = [_el("Modo de color oscuro")]
        assert manos.elegir_elemento("modo oscuro", els)["nombre"] == "Modo de color oscuro"

    def test_uno_activo_antes_que_uno_gris(self):
        els = [_el("Siguiente", activo=False), _el("Siguiente")]
        assert manos.elegir_elemento("siguiente", els)["activo"] is True

    def test_el_tipo_desempata(self):
        els = [_el("Inicio", 50000), _el("Inicio", 50019)]
        assert manos.elegir_elemento("inicio", els, manos.tipo_pedido("pestaña"))["tipo_id"] == 50019

    def test_nada_que_casar(self):
        assert manos.elegir_elemento("volar", [_el("Guardar")]) is None
        assert manos.elegir_elemento("", [_el("Guardar")]) is None


def test_al_modelo_le_llega_poco_y_sin_coordenadas():
    els = [_el("x" * 300), {**_el("Clave", 50004), "secreto": True}, _el("Gris", activo=False)]
    vistos = manos.para_el_modelo(els)
    assert len(vistos[0]["nombre"]) == 80
    assert vistos[1] == {"nombre": "Clave", "tipo": "campo", "contraseña": True}
    assert vistos[2]["gris"] is True
    assert all("rect" not in v for v in vistos)


def test_se_ordenan_como_se_leen():
    els = [{"nombre": "b", "rect": (100, 50, 150, 70)}, {"nombre": "a", "rect": (10, 52, 60, 72)},
           {"nombre": "c", "rect": (0, 200, 50, 220)}]
    assert [e["nombre"] for e in manos.ordenar_por_lectura(els)] == ["a", "b", "c"]
