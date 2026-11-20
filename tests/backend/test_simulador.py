"""El simulador del «¿y si…?» (2026-11-20).

Lo que se protege: que parta del dinero real (lo invertido sube y baja, el efectivo no), que
el mismo «¿y si…?» dé siempre el mismo abanico, que con y sin el gasto se compare con los
mismos sorteos, que el coste incluya lo que el dinero habría rentado, que los supuestos raros
se rechacen y que el panel guarde la simulación que se hizo.
"""
import pytest

import main


@pytest.fixture
def dinero(monkeypatch):
    monkeypatch.setattr(main, "_sim_cache", {})
    monkeypatch.setattr(main, "_hud_paneles", [])
    monkeypatch.setattr(main, "get_finanzas", lambda credentials=None: {
        "configurado": True, "total": {"valor": 40000.0},
        "revolut": {"configurado": True, "saldo": 10000.0}})
    monkeypatch.setattr(main, "get_cartera_etf", lambda credentials=None: {"total": {"valor_actual": 5000.0}})


class TestLaCuenta:
    def test_sin_volatilidad_es_interes_compuesto(self, monkeypatch):
        monkeypatch.setitem(main.SIM_ESCENARIOS, "normal", (0.05, 0.0))
        r = main._simular(main._sim_param("i=10000;e=1000;a=0;n=2;s=normal"), n=10)
        assert r["con"][-1]["p50"] == round(10000 * 1.05 ** 2 + 1000)
        assert r["con"][0]["p50"] == 11000 and r["hoy"] == 11000

    def test_el_gasto_sale_primero_del_efectivo(self, monkeypatch):
        monkeypatch.setitem(main.SIM_ESCENARIOS, "normal", (0.0, 0.0))
        r = main._simular(main._sim_param("i=10000;e=3000;g=5000@0;n=1;s=normal"), n=5)
        assert r["con"][0]["p50"] == 8000 and r["sin"][0]["p50"] == 13000

    def test_el_mismo_supuesto_da_el_mismo_abanico(self):
        s = main._sim_param("i=50000;e=5000;a=200;g=20000@6;n=5;s=normal")
        assert main._simular(s, n=200) == main._simular(s, n=200)

    def test_el_abanico_esta_ordenado_y_se_abre_con_el_tiempo(self):
        r = main._simular(main._sim_param("i=50000;e=0;n=10;s=normal"), n=400)
        for fila in r["con"]:
            assert fila["p10"] <= fila["p50"] <= fila["p90"]
        assert r["con"][-1]["p90"] - r["con"][-1]["p10"] > r["con"][1]["p90"] - r["con"][1]["p10"]

    def test_con_y_sin_usan_los_mismos_sorteos(self):
        r = main._simular(main._sim_param("i=50000;e=0;g=10000@0;n=5;s=normal"), n=300)
        # Con los mismos sorteos, el coste es el gasto más lo que habría rentado: más de
        # 10.000 y menos de lo que daría el escenario más loco. Con sorteos distintos
        # saldría cualquier cosa, incluso negativo.
        coste = r["sin"][-1]["p50"] - r["con"][-1]["p50"]
        assert 10000 < coste < 20000


class TestLosSupuestos:
    @pytest.mark.parametrize("malo", [
        "", "i=1;rm -rf", "i=10;n=0", "i=10;n=99", "i=10;s=loco", "i=-5", "i=1;g=5@999;n=1",
        "i=1;g=1@1;g=1@2;g=1@3;g=1@4;g=1@5", "x=1",
    ])
    def test_los_raros_no_pasan(self, malo):
        assert main._sim_param(malo) is None

    def test_ida_y_vuelta(self):
        s = main._sim_param("i=52000;e=8000;a=300;g=25000@6;g=-10000@24;n=5;s=pesimista")
        assert main._sim_param(main._sim_texto(s)) == s


class TestLaHerramienta:
    def test_parte_de_su_dinero_y_compara(self, dinero):
        r = main._j_simular_finanzas(gasto=25000, en_meses=6, anos=5)
        assert r["ok"] is True and r["hoy"] == "55.000 €"
        assert "coste_mediano" in r and "sin_los_gastos" in r
        assert "no es" not in r["supuestos"] and "consejo" in r["aviso"]

    def test_lo_dibuja_con_la_simulacion_que_se_hizo(self, dinero, monkeypatch):
        main._j_simular_finanzas(gasto=25000, en_meses=6, anos=5)
        panel, = main._hud_paneles
        assert panel["tipo"] == "abanico" and panel["param"].startswith("i=45000;e=10000;a=0;g=25000@6")
        # Aunque mañana la cartera valga otra cosa, el panel enseña la misma simulación.
        monkeypatch.setattr(main, "get_finanzas", lambda credentials=None: {"configurado": False})
        datos = main._hud_datos("simulacion", param=panel["param"])
        assert datos["clase"] == "abanico" and len(datos["puntos"]) == 6
        assert all(p["base"] is not None for p in datos["puntos"])

    def test_sin_dinero_que_leer_lo_dice(self, monkeypatch):
        monkeypatch.setattr(main, "get_finanzas", lambda credentials=None: {"configurado": False})
        monkeypatch.setattr(main, "get_cartera_etf", lambda credentials=None: {})
        r = main._j_simular_finanzas(gasto=1000)
        assert r["ok"] is False and "Indexa" in r["error"]

    def test_gastos_mal_escritos(self, dinero):
        assert main._j_simular_finanzas(otros_gastos="mucho@pronto")["ok"] is False
        assert main._j_simular_finanzas(anos=80)["ok"] is False

    def test_por_telefono_si(self):
        assert "simular_finanzas" in main._MCP_SERVIDOR_SOLO_LECTURA
