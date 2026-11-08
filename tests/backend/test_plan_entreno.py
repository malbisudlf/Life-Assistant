"""El entrenador adaptativo, a modo de prueba (`plan_entreno`).

Lo que se protege: que el pádel de la Amazfit («Other», troceado) cuente como UNA sesión y
solo si suma 45 min; que un entreno repetido no cuente dos veces; que la recuperación de hoy
cambie lo que toca; y que no prometa más días de los que quedan.
"""
from datetime import datetime, timedelta

import pytest

import main

# Un miércoles: quedan miércoles a domingo (5 días si hoy no ha entrenado).
AHORA = datetime(2026, 11, 11, 9, 0, tzinfo=main.LOCAL_TZ)


def _w(dia, nombre, minutos, hora="20:00"):
    """Como lo manda Health Auto Export: con inicio, fin y la duración en segundos."""
    ini = datetime.strptime(f"{dia} {hora}", "%Y-%m-%d %H:%M").replace(tzinfo=main.LOCAL_TZ)
    fin = ini + timedelta(minutes=minutos)
    return {"name": nombre, "start": ini.strftime("%Y-%m-%d %H:%M:%S %z"),
            "end": fin.strftime("%Y-%m-%d %H:%M:%S %z"), "duration": minutos * 60}


@pytest.fixture
def semana(monkeypatch):
    estado = {"workouts": [], "salud": {}, "sueno": []}
    monkeypatch.setattr(main, "_ahora_local", lambda: AHORA)
    monkeypatch.setattr(main, "PLAN_ENTRENO", "Fuerza:3-4,Natación:3,Pádel:1")

    def _metrics(days=7, credentials=None):
        return {"metrics": {"workouts": [{"date": w["start"][:10], "extra": {"workouts": [w]}}
                                         for w in estado["workouts"]]}}
    monkeypatch.setattr(main, "get_health_metrics", _metrics)
    monkeypatch.setattr(main, "_brief_salud", lambda: estado["salud"])
    monkeypatch.setattr(main, "_j_sueno", lambda n=7: {"noches": estado["sueno"]})
    return estado


def test_el_plan_se_lee_del_entorno(monkeypatch):
    monkeypatch.setattr(main, "PLAN_ENTRENO", "Fuerza:3-4, Natación:3,Pádel:1,raro")
    assert main._plan_objetivo() == {"Fuerza": (3, 4), "Natación": (3, 3), "Pádel": (1, 1)}


def test_el_padel_troceado_es_una_sesion_y_lo_repetido_no_cuenta(semana):
    semana["workouts"] = [
        _w("2026-11-09", "Traditional Strength Training", 60),
        _w("2026-11-09", "Traditional Strength Training", 60),          # repetido
        _w("2026-11-10", "Other", 70, "10:00"), _w("2026-11-10", "Other", 60, "11:15"),
        _w("2026-11-08", "Swim", 30),                                    # domingo pasado
        _w("2026-11-10", "Other", 5, "18:00"),                           # suma al pádel
        _w("2026-11-10", "Swim", 0),                                     # sin duración
    ]
    r = main._j_plan_entreno()
    assert r["hechos"] == {"Fuerza": 1, "Natación": 0, "Pádel": 1}
    assert [s["tipo"] for s in r["sesiones"]] == ["Fuerza", "Pádel"]
    assert r["sesiones"][1]["minutos"] == 135


def test_un_trozo_corto_en_segundos_no_son_horas(semana):
    """240 s de pádel sin `end`: la regla vieja (≤300 = minutos) lo leía como 4 horas. Con
    `end`, se mide de verdad."""
    w = _w("2026-11-10", "Other", 4)
    assert main._minutos_de_entreno(w) == 4
    sin_fin = {k: v for k, v in w.items() if k != "end"}
    assert main._minutos_de_entreno(sin_fin) == 240      # sin fin no hay forma de saberlo


def test_fragmentos_sueltos_no_son_padel(semana):
    semana["workouts"] = [_w("2026-11-10", "Other", 12)]
    assert main._j_plan_entreno()["hechos"]["Pádel"] == 0


def test_bien_recuperado_toca_lo_que_mas_falta(semana):
    semana["workouts"] = [_w("2026-11-09", "Traditional Strength Training", 60),
                          _w("2026-11-10", "Other", 120)]
    r = main._j_plan_entreno()
    assert r["faltan"] == {"Fuerza": 2, "Natación": 3, "Pádel": 0}
    assert r["hoy"] == "Natación" and r["dias_que_quedan"] == 5
    assert "no_da" not in r and r["prueba"] is True


def test_con_mala_noche_toca_suave(semana):
    semana["sueno"] = [{"fecha": "2026-11-11", "horas": 4.8}]
    r = main._j_plan_entreno()
    assert r["hoy"] == "Natación (suave)" and "4 h 48 min" in r["porque"]


def test_con_la_fc_alta_tambien(semana):
    semana["salud"] = {"fc_reposo": {"ultimo": 62, "media_30d": 55, "n_30d": 25, "dias_atras": 0}}
    r = main._j_plan_entreno()
    assert r["hoy"] == "Natación (suave)" and "FC en reposo" in r["porque"]


def test_una_fc_de_ayer_no_dice_nada_de_hoy(semana):
    semana["salud"] = {"fc_reposo": {"ultimo": 70, "media_30d": 55, "n_30d": 25, "dias_atras": 1}}
    assert main._j_plan_entreno()["hoy"] != "Natación (suave)"


def test_si_hoy_ya_entreno_lo_dice_y_hoy_no_cuenta_como_dia_libre(semana):
    semana["workouts"] = [_w("2026-11-11", "Swim", 40, "08:00")]
    r = main._j_plan_entreno()
    assert r["hoy"] == "Ya ha entrenado hoy" and r["dias_que_quedan"] == 4


def test_si_no_da_la_semana_lo_avisa(semana, monkeypatch):
    monkeypatch.setattr(main, "_ahora_local", lambda: datetime(2026, 11, 14, 9, 0, tzinfo=main.LOCAL_TZ))
    r = main._j_plan_entreno()                 # sábado, nada hecho: 7 pendientes, 2 días
    assert r["dias_que_quedan"] == 2 and "no_da" in r


def test_cumplido_es_libre(semana):
    semana["workouts"] = ([_w(f"2026-11-0{d}", "Traditional Strength Training", 60) for d in (9,)] +
                          [_w("2026-11-10", "Traditional Strength Training", 50, "21:00"),
                           _w("2026-11-10", "Traditional Strength Training", 55, "07:00")] +
                          [_w("2026-11-09", "Swim", 30, "08:00"), _w("2026-11-10", "Swim", 30, "08:30"),
                           _w("2026-11-10", "Swim", 31, "12:00"), _w("2026-11-10", "Other", 100, "17:00")])
    assert main._j_plan_entreno()["hoy"] == "Libre"


def test_es_una_herramienta_de_solo_mirar():
    h = main._JARVIS_HERRAMIENTAS["plan_entreno"]
    assert h["confirmar"] is False and "plan_entreno" in main._TRAS_AJENO_SE_PUEDE
