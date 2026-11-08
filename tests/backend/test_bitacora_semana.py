"""La bitácora del domingo (`_informe_jarvis`), dentro del informe semanal.

Lo que se protege: que cada parte vaya por separado (una que revienta no se lleva a las
demás y lo dice), que el gasto incompleto se diga, y que el texto se lea.
"""
import time

import main


def _todo_bien(monkeypatch, terceros=None):
    monkeypatch.setattr(main, "get_gasto", lambda dias=30, credentials=None: {
        "total": {"euros": 1.234, "euros_incompleto": False, "llamadas": 412},
        "por_boca": {"telefono": {"euros": 0.8}, "chat": {"euros": 0.3}, "voz": {"euros": 0.1}}})
    monkeypatch.setattr(main, "_j_plan_entreno", lambda: {
        "hechos": {"Fuerza": 2, "Natación": 3, "Pádel": 1},
        "plan": {"Fuerza": [3, 4], "Natación": [3, 3], "Pádel": [1, 1]}, "sesiones": [{}] * 6})
    monkeypatch.setattr(main, "get_logs", lambda **k: {"errores": 3, "entradas": [
        {"source": "whatsapp"}, {"source": "whatsapp"}, {"source": "graph"}]})
    monkeypatch.setattr(main, "_terceros", terceros or {})


def test_lo_junta_todo(monkeypatch):
    ahora = time.time()
    _todo_bien(monkeypatch, {"a": {"creada": ahora, "estado": "hecha", "cita": {"hora": "17:30"}},
                             "b": {"creada": ahora, "estado": "sin_hablar"},
                             "c": {"creada": ahora - 9 * 86400, "estado": "hecha"}})
    j = main._informe_jarvis()
    assert j["gasto"]["euros"] == 1.234 and j["gasto"]["por_boca"][0] == ("telefono", 0.8)
    assert j["entreno"]["hechos"]["Fuerza"] == 2
    assert j["terceros"] == {"llamadas": 2, "hablaron": 1, "citas": 1}
    assert j["fallos"] == {"total": 3, "donde": [("whatsapp", 2), ("graph", 1)]}


def test_una_parte_rota_no_se_lleva_las_demas(monkeypatch):
    _todo_bien(monkeypatch)
    monkeypatch.setattr(main, "get_gasto", lambda **k: (_ for _ in ()).throw(RuntimeError("supabase")))
    j = main._informe_jarvis()
    assert j["sin_gasto"] is True and "entreno" in j and "fallos" in j


def test_el_texto(monkeypatch):
    _todo_bien(monkeypatch)
    d = {"fecha": "2026-11-15", "semanas": 13, "zona": "Europe/Madrid", "salud": {}, "entrenamiento": {},
         "avisos": {}, "jarvis": main._informe_jarvis()}
    texto = main.render_informe_texto(d)
    assert "## ESTA SEMANA, CON JARVIS" in texto
    assert "Entrenos: Fuerza 2/3-4, Natación 3/3, Pádel 1/1" in texto
    assert "Lo que ha costado: 1.23 € en 412 llamadas a modelos" in texto
    assert "Lo que ha fallado: 3 errores en el registro — whatsapp 2, graph 1" in texto


def test_el_gasto_incompleto_se_dice(monkeypatch):
    _todo_bien(monkeypatch)
    monkeypatch.setattr(main, "get_gasto", lambda **k: {
        "total": {"euros": 0.5, "euros_incompleto": True, "llamadas": 10}, "por_boca": {}})
    d = {"fecha": "x", "semanas": 1, "zona": "z", "salud": {}, "entrenamiento": {}, "avisos": {},
         "jarvis": main._informe_jarvis()}
    assert "incompleto" in main.render_informe_texto(d)


def test_entra_en_el_informe(monkeypatch):
    monkeypatch.setattr(main, "_informe_salud", lambda s, h: {})
    monkeypatch.setattr(main, "_brief_entrenamiento", lambda: {})
    monkeypatch.setattr(main, "_informe_avisos", lambda: {})
    monkeypatch.setattr(main, "_informe_jarvis", lambda: {"fallos": {"total": 0, "donde": []}})
    d = main.construir_informe_semanal()
    assert d["jarvis"] == {"fallos": {"total": 0, "donde": []}}
    assert "nada en el registro" in main.render_informe_texto(d)
