"""`_regla_alarma_tarde`: la alarma de respaldo de mañana no deja tiempo para lo primero.

Solo el choque: una alarma que existe y llega tarde. Que falte no se avisa (muchas
mañanas no hay alarma de respaldo a propósito). La propuesta va con botón y la alarma que
llega tarde no se toca.
"""
from datetime import datetime, timedelta

import pytest

import main


@pytest.fixture
def escena(monkeypatch):
    manana = (main._ahora_local() + timedelta(days=1)).date()
    hecho = {"avisos": [], "preguntas": [], "eventos": [], "alarmas": []}

    def _ev(hora, titulo="Clase de RL", todo=False):
        h, m = (int(x) for x in hora.split(":"))
        ini = datetime(manana.year, manana.month, manana.day, h, m, tzinfo=main.LOCAL_TZ)
        hecho["eventos"].append({"id": titulo, "title": titulo, "ini": ini, "isAllDay": todo})

    def _alarma(hora, estado="armada", saltada=False, dia=manana):
        hecho["alarmas"].append({"cuando": f"{dia.isoformat()} {hora}", "estado": estado,
                                 "saltada": saltada, "etiqueta": ""})

    monkeypatch.setattr(main, "_toca_una_vez", lambda clave, hora: True)
    monkeypatch.setattr(main, "_eventos_con_fecha", lambda dias=2: sorted(hecho["eventos"], key=lambda e: e["ini"]))
    monkeypatch.setattr(main, "_alarma_listar", lambda filas=None: hecho["alarmas"])
    monkeypatch.setattr(main, "_guardar_pregunta_con_accion",
                        lambda pid, texto, op, h, args, caduca=None: hecho["preguntas"].append((h, args)) or True)
    monkeypatch.setattr(main, "_apuntar_aviso",
                        lambda regla, texto, **k: hecho["avisos"].append((regla, texto, k)) or True)
    hecho["ev"], hecho["alarma"], hecho["manana"] = _ev, _alarma, manana
    return hecho


def test_la_alarma_que_llega_tarde_se_avisa_con_su_boton(escena, monkeypatch):
    monkeypatch.setattr(main, "PREP_MANANA_MIN", 60)
    escena["ev"]("08:30")
    escena["alarma"]("08:15")
    assert main._regla_alarma_tarde() == 1
    regla, texto, k = escena["avisos"][0]
    assert regla == main.REGLA_ALARMA_TARDE
    assert "«Clase de RL» a las 08:30" in texto and "suena a las 08:15" in texto
    assert "¿Le pongo otra a las 07:30?" in texto
    assert escena["preguntas"] == [("poner_alarma", {"hora": "07:30", "fecha": escena["manana"].isoformat(),
                                                     "etiqueta": "Clase de RL"})]
    assert k["caduca"].strftime("%H:%M") == "07:30"


def test_la_propuesta_cae_en_multiplos_de_cinco(escena, monkeypatch):
    monkeypatch.setattr(main, "PREP_MANANA_MIN", 60)
    escena["ev"]("08:47")
    escena["alarma"]("08:00")
    main._regla_alarma_tarde()
    assert escena["preguntas"][0][1]["hora"] == "07:45"


@pytest.mark.parametrize("hora_alarma", ["07:30", "06:00"])
def test_si_da_tiempo_calla(escena, monkeypatch, hora_alarma):
    monkeypatch.setattr(main, "PREP_MANANA_MIN", 60)
    escena["ev"]("08:30")
    escena["alarma"](hora_alarma)
    assert main._regla_alarma_tarde() == 0 and escena["avisos"] == []


def test_sin_alarma_no_dice_nada(escena):
    escena["ev"]("08:30")
    assert main._regla_alarma_tarde() == 0


def test_cuenta_la_primera_que_suena_y_no_las_saltadas_ni_las_apagadas(escena, monkeypatch):
    monkeypatch.setattr(main, "PREP_MANANA_MIN", 60)
    escena["ev"]("08:30")
    escena["alarma"]("07:00", saltada=True)
    escena["alarma"]("06:30", estado="confirmada")
    escena["alarma"]("08:20")
    escena["alarma"]("08:10")
    main._regla_alarma_tarde()
    assert "suena a las 08:10" in escena["avisos"][0][1]


def test_lo_de_todo_el_dia_no_es_lo_primero(escena, monkeypatch):
    monkeypatch.setattr(main, "PREP_MANANA_MIN", 60)
    escena["ev"]("00:00", titulo="Festivo", todo=True)
    escena["ev"]("10:00")
    escena["alarma"]("08:30")
    assert main._regla_alarma_tarde() == 0


def test_el_boton_dice_lo_que_hara(monkeypatch):
    fecha = (main._ahora_local() + timedelta(days=1)).date().isoformat()
    d = main._describir_accion("poner_alarma", {"hora": "07:30", "fecha": fecha, "etiqueta": "Clase"})
    assert d == {"texto": "Poner una alarma de respaldo mañana a las 07:30 (Clase)."}
    assert "error" in main._describir_accion("poner_alarma", {"hora": "7:3", "fecha": fecha})
    assert "error" in main._describir_accion("poner_alarma", {"hora": "07:30", "fecha": "mañana"})
    assert "poner_alarma" in main.PREGUNTAS_ACCIONES


def test_esta_entre_las_reglas_y_se_puede_pedir_que_llame():
    assert main.REGLA_ALARMA_TARDE in dict(main._REGLAS)
    assert main.REGLA_ALARMA_TARDE in main.REGLAS_LLAMABLES
