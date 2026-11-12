"""El HUD que se dibuja solo: Jarvis deja la receta de un panel y la vista lo pinta.

Lo que se protege: que el modelo solo pueda elegir piezas del catálogo (ni HTML ni datos
suyos), que las recetas no crezcan sin tope, que reponerlas desde el navegador pase por la
misma validación y no pise lo que Jarvis haya cambiado, y que los datos pidan el JWT.
"""
import pytest

import main


@pytest.fixture(autouse=True)
def _limpio(monkeypatch):
    monkeypatch.setattr(main, "_hud_paneles", [])


def _salud(monkeypatch, metricas):
    monkeypatch.setattr(main, "get_health_metrics", lambda days=30, credentials=None: {"metrics": metricas})


class TestLaReceta:
    def test_un_panel_de_una_serie(self):
        r = main._j_hud_panel("sueno", titulo="Sueño de dos semanas", tipo="barras", dias=14)
        assert r["ok"] and r["panel"] == "Sueño de dos semanas" and r["tipo"] == "barras"
        [p] = main._hud_paneles
        assert p["fuentes"] == ["sueno"] and p["dias"] == 14 and len(p["id"]) == 8

    def test_dos_fuentes_una_contra_otra(self):
        main._j_hud_panel("sueno, hrv", titulo="Sueño contra HRV")
        assert main._hud_paneles[0]["fuentes"] == ["sueno", "hrv"]
        assert main._hud_paneles[0]["tipo"] == "linea"

    def test_una_fuente_inventada_se_rechaza_diciendo_las_que_hay(self):
        r = main._j_hud_panel("glucosa", titulo="x")
        assert not r["ok"] and "glucosa" in r["error"] and "sueno" in r["error"]
        assert main._hud_paneles == []

    def test_el_tipo_y_los_dias_se_acotan(self):
        main._j_hud_panel("pasos", titulo="<script>alert(1)</script>", tipo="tarta", dias=9999)
        [p] = main._hud_paneles
        assert p["tipo"] == "linea" and p["dias"] == 90
        # El título es texto: se guarda tal cual (recortado) y la vista lo pinta como texto.
        assert p["titulo"] == "<script>alert(1)</script>"

    def test_la_agenda_es_lista_y_el_trafico_cifra_digan_lo_que_digan(self):
        main._j_hud_panel("agenda", tipo="barras")
        main._j_hud_panel("trafico", tipo="linea", destino="uni")
        agenda, trafico = main._hud_paneles
        assert (agenda["tipo"], agenda["titulo"]) == ("lista", "Agenda")
        assert (trafico["tipo"], trafico["destino"]) == ("cifra", "uni")

    def test_el_mismo_titulo_sustituye_y_hay_tope(self):
        main._j_hud_panel("sueno", titulo="Mi panel")
        main._j_hud_panel("pasos", titulo="mi PANEL")
        assert [p["fuentes"] for p in main._hud_paneles] == [["pasos"]]
        for i in range(main.HUD_PANELES_MAX + 2):
            main._j_hud_panel("hrv", titulo=f"P{i}")
        assert len(main._hud_paneles) == main.HUD_PANELES_MAX
        assert main._hud_paneles[-1]["titulo"] == f"P{main.HUD_PANELES_MAX + 1}"

    def test_quitar_uno_o_todos(self):
        main._j_hud_panel("sueno", titulo="Sueño")
        main._j_hud_panel("pasos", titulo="Pasos")
        assert main._j_hud_quitar("sueñ") == {"ok": True, "quitados": 1}
        assert not main._j_hud_quitar("nada")["ok"]
        assert main._j_hud_quitar("todos") == {"ok": True, "quitados": 1}
        assert main._hud_paneles == []

    def test_estan_en_el_chat_y_en_el_telefono_sin_confirmar(self):
        for nombre in ("hud_panel", "hud_quitar"):
            assert main._JARVIS_HERRAMIENTAS[nombre]["confirmar"] is False
            assert nombre in main._MCP_SERVIDOR_ACCIONES


class TestLosDatos:
    def test_una_serie_de_salud(self, client, auth_headers, monkeypatch):
        _salud(monkeypatch, {"heart_rate_variability": [
            {"date": "2026-11-10", "value": 48.0}, {"date": "2026-11-11", "value": None},
            {"date": "2026-11-12", "value": 52.345}]})
        r = client.get("/hud/datos", headers=auth_headers, params={"fuente": "hrv", "dias": 7}).json()
        assert r == {"clase": "serie", "nombre": "HRV", "unidad": "ms",
                     "puntos": [{"d": "2026-11-10", "v": 48.0}, {"d": "2026-11-12", "v": 52.34}]} \
            or r["puntos"][-1]["v"] == 52.35

    def test_el_sueno_va_en_horas_y_sin_las_noches_anuladas(self, client, auth_headers, monkeypatch):
        _salud(monkeypatch, {"sleep_analysis": [
            {"date": "2026-11-10", "value": 7.5, "extra": {}},
            {"date": "2026-11-11", "value": 3.0, "extra": {"excluded": True}}]})
        monkeypatch.setattr(main, "_horas_sueno", lambda f: float(f["value"]))
        r = client.get("/hud/datos", headers=auth_headers, params={"fuente": "sueno"}).json()
        assert r["puntos"] == [{"d": "2026-11-10", "v": 7.5}] and r["unidad"] == "h"

    def test_la_agenda_es_una_lista(self, client, auth_headers, monkeypatch):
        hoy = main._ahora_local().date().isoformat()
        monkeypatch.setattr(main, "_j_agenda", lambda dias=1: {"eventos": [
            {"dia": hoy, "hora": "15:00", "titulo": "Clase"},
            {"dia": "2026-12-24", "hora": "00:00", "titulo": "Cena", "todo_el_dia": True}]})
        r = client.get("/hud/datos", headers=auth_headers, params={"fuente": "agenda"}).json()
        assert r["items"] == [{"a": "15:00", "b": "Clase"}, {"a": "24/12 todo el día", "b": "Cena"}]

    def test_el_trafico_es_una_cifra(self, client, auth_headers, monkeypatch):
        monkeypatch.setattr(main, "_j_trafico", lambda destino="": {
            "ok": True, "a": "uni", "rutas": [{"via": "AP-8", "minutos": 29, "retraso_min": 7}]})
        r = client.get("/hud/datos", headers=auth_headers, params={"fuente": "trafico", "destino": "uni"}).json()
        assert r == {"clase": "cifra", "nombre": "A uni", "valor": 29, "unidad": "min",
                     "nota": "+7 min sobre lo normal · AP-8"}
        monkeypatch.setattr(main, "_j_trafico", lambda destino="": {"ok": False, "error": "No sé a dónde."})
        r = client.get("/hud/datos", headers=auth_headers, params={"fuente": "trafico"}).json()
        assert r["valor"] is None and r["nota"] == "No sé a dónde."

    def test_sin_jwt_o_con_fuente_inventada_no_hay_datos(self, client, auth_headers):
        assert client.get("/hud/datos", params={"fuente": "hrv"}).status_code in (401, 403)
        assert client.get("/hud/paneles").status_code in (401, 403)
        assert client.get("/hud/datos", headers=auth_headers, params={"fuente": "glucosa"}).status_code == 404


class TestLaVista:
    def test_lee_quita_y_repone(self, client, auth_headers):
        main._j_hud_panel("sueno", titulo="Sueño")
        paneles = client.get("/hud/paneles", headers=auth_headers).json()["paneles"]
        assert [p["titulo"] for p in paneles] == ["Sueño"]
        pid = paneles[0]["id"]
        assert client.delete(f"/hud/paneles/{pid}", headers=auth_headers).json()["paneles"] == []
        # Tras un despliegue no hay nada: la vista repone los suyos, con su mismo id.
        r = client.put("/hud/paneles", headers=auth_headers, json={"paneles": [
            {"id": pid, "titulo": "Sueño", "tipo": "barras", "fuentes": ["sueno"], "dias": 30},
            {"id": "zzzzzzzz", "titulo": "Malo", "tipo": "linea", "fuentes": ["glucosa"], "dias": 7}]}).json()
        assert [(p["id"], p["tipo"], p["dias"]) for p in r["paneles"]] == [(pid, "barras", 30)]

    def test_reponer_no_pisa_lo_que_ya_hay(self, client, auth_headers):
        main._j_hud_panel("pasos", titulo="Pasos")
        r = client.put("/hud/paneles", headers=auth_headers, json={"paneles": [
            {"titulo": "Viejo", "tipo": "linea", "fuentes": ["hrv"], "dias": 7}]}).json()
        assert [p["titulo"] for p in r["paneles"]] == ["Pasos"]
