"""Los avisos de "falló" dicen POR QUÉ falló.

Un `logger.warning("Presencia: falló el guardado de tramos")` a secas llega a `app_logs`
igual para un timeout que para una conexión rechazada o un DNS caído, y son tres averías
distintas con tres arreglos distintos. Se añade el tipo de la excepción (nunca su
mensaje: el de `requests` lleva la URL entera dentro), que es el criterio que ya seguían
los avisos de GitHub y de Graph.
"""
from datetime import datetime

import pytest
import requests

import main
from conftest import FakeResponse


def _revienta(url, **kwargs):
    raise requests.ConnectionError("sin red")


def _avisos(caplog) -> list[str]:
    return [r.getMessage() for r in caplog.records if r.levelname == "WARNING"]


@pytest.fixture
def purgas_pendientes(monkeypatch):
    """Las purgas van "una vez al día" con el día apuntado en el módulo: sin olvidarlo,
    el primer test de la suite que la dispare dejaría mudos a todos los siguientes."""
    monkeypatch.setattr(main, "_presencia_purga_dia", "")
    monkeypatch.setattr(main, "_casa_purga_dia", "")


class TestAvisosConCausa:
    def test_ajustes_de_salud(self, mock_requests, caplog):
        mock_requests.add("GET", "salud_ajustes", _revienta)
        with caplog.at_level("WARNING"):
            ajustes = main._leer_salud_ajustes()
        # Fail-open intacto: sin ajustes, los de por defecto.
        assert ajustes == {"cambio_dispositivo": None, "dispositivo": None}
        assert any("Ajustes de salud" in m and "ConnectionError" in m for m in _avisos(caplog))

    def test_guardado_de_tramos_de_presencia(self, mock_requests, caplog):
        mock_requests.add("POST", "presencia_tramos", _revienta)
        desde = datetime(2026, 8, 4, 10, 0, tzinfo=main.LOCAL_TZ)
        hasta = datetime(2026, 8, 4, 11, 0, tzinfo=main.LOCAL_TZ)
        with caplog.at_level("WARNING"):
            main._guardar_tramos_presencia([("2026-08-04", desde, hasta)], True)
        assert any("guardado de tramos" in m and "ConnectionError" in m
                   for m in _avisos(caplog))

    def test_purga_de_tramos_de_presencia(self, mock_requests, caplog, purgas_pendientes):
        mock_requests.add("DELETE", "presencia_tramos", _revienta)
        with caplog.at_level("WARNING"):
            main._purgar_tramos_presencia()
        assert any("purga de tramos" in m and "ConnectionError" in m for m in _avisos(caplog))

    def test_apunte_de_una_accion_de_la_casa(self, mock_requests, caplog):
        mock_requests.add("POST", "casa_acciones", _revienta)
        with caplog.at_level("WARNING"):
            main._apuntar_accion_casa("light.turn_on", "light.salon")
        assert any("apunte de la acción" in m and "ConnectionError" in m
                   for m in _avisos(caplog))

    def test_purga_de_acciones_de_la_casa_sin_red(self, mock_requests, caplog,
                                                  purgas_pendientes):
        mock_requests.add("POST", "casa_acciones", FakeResponse({}, 201))
        mock_requests.add("DELETE", "casa_acciones", _revienta)
        with caplog.at_level("WARNING"):
            main._apuntar_accion_casa("light.turn_on", "light.salon")
        assert any("purga de acciones" in m and "ConnectionError" in m
                   for m in _avisos(caplog))

    def test_purga_de_acciones_de_la_casa_rechazada(self, mock_requests, caplog,
                                                    purgas_pendientes):
        # Supabase no lanza con un 500: responde. Sin mirar el código, la purga fallaba
        # cada día sin que ningún registro lo contara, y la tabla crecía sin tope.
        mock_requests.add("POST", "casa_acciones", FakeResponse({}, 201))
        mock_requests.add("DELETE", "casa_acciones", FakeResponse({}, 500))
        with caplog.at_level("WARNING"):
            main._apuntar_accion_casa("light.turn_on", "light.salon")
        assert any("purgar las acciones viejas" in m and "500" in m for m in _avisos(caplog))

    def test_purga_de_acciones_de_la_casa_correcta_no_avisa(self, mock_requests, caplog,
                                                           purgas_pendientes):
        mock_requests.add("POST", "casa_acciones", FakeResponse({}, 201))
        mock_requests.add("DELETE", "casa_acciones", FakeResponse([], 204))
        with caplog.at_level("WARNING"):
            main._apuntar_accion_casa("light.turn_on", "light.salon")
        assert not [m for m in _avisos(caplog) if "Casa" in m]

    def test_estado_del_resumen_diario(self, mock_requests, caplog):
        mock_requests.add("GET", "brief_envios", _revienta)
        with caplog.at_level("WARNING"):
            estado = main._brief_ajustes_estado()
        # "No se pudo comprobar" sigue siendo None, no un "no ha salido".
        assert estado["enviado_hoy"] is None
        assert any("ya salió" in m and "ConnectionError" in m for m in _avisos(caplog))

    def test_salud_de_las_reglas(self, monkeypatch, caplog):
        def _falla():
            raise RuntimeError("roto")

        def _regla_que_pide_salud(obtener_salud):
            assert obtener_salud() == {}
            return 0

        monkeypatch.setattr(main, "REGLAS_PROACTIVAS", True)
        monkeypatch.setattr(main, "_brief_salud", _falla)
        monkeypatch.setattr(main, "_REGLAS", (("prueba", _regla_que_pide_salud),))
        with caplog.at_level("WARNING"):
            main._correr_reglas()
        assert any("Reglas: no se pudo leer la salud" in m and "RuntimeError" in m
                   for m in _avisos(caplog))
