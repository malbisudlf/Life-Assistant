"""Lo delicado de la casa se confirma aunque sea un script o un interruptor.

El 2026-11-04 se vio que `script.quitar_alarm_script` y `script.abrir_puerta_garaje` se
ejecutaban sin botón, también por teléfono: la regla solo miraba el dominio.
"""
import pytest

import main


@pytest.mark.parametrize("servicio,entidad", [
    ("script.turn_on", "script.abrir_puerta_garaje"),
    ("script.turn_on", "script.quitar_alarm_script"),
    ("script.quitar_alarm_script", "script.quitar_alarm_script"),
    ("homeassistant.turn_on", "script.alarma_total_script"),
    ("switch.turn_on", "switch.puerta_garaje"),
    ("switch.turn_on", "switch.camara_garaje_privacy"),
    ("switch.turn_off", "switch.camara_jardin_record_to_sd_card"),
    ("lock.unlock", "lock.entrada"),
    ("cover.open_cover", "cover.persiana_salon"),
    ("homeassistant.toggle", "cover.garaje"),
])
def test_se_confirma(servicio, entidad):
    assert main._casa_pide_confirmar({"servicio": servicio, "entidad": entidad}) is True


@pytest.mark.parametrize("servicio,entidad", [
    ("light.turn_on", "light.tira_led"),
    ("switch.turn_off", "switch.luces_jardin"),
    ("climate.set_temperature", "climate.hab_mikel"),
    ("script.turn_on", "script.amanecer_gradual"),
    ("media_player.volume_set", "media_player.cocina"),
    ("switch.turn_on", "switch.block_de_notas"),
    ("light.turn_on", "light.camara_jardin_floodlight_timed"),
])
def test_no_se_confirma(servicio, entidad):
    assert main._casa_pide_confirmar({"servicio": servicio, "entidad": entidad}) is False


def test_ante_la_duda_se_pregunta():
    assert main._casa_pide_confirmar({"servicio": "light.turn_on"}) is True
    assert main._casa_pide_confirmar({}) is True
