"""Salud de la familia: sus datos en su tabla, su resumen y su correo, sin rozar lo de Mikel.

Lo que más importa aquí no es que funcione, sino lo que NO puede pasar: que una fila de
otra persona acabe en `health_metrics` (y de ahí en el briefing de Mikel, en Jarvis o en
el dashboard), que un token abra lo de otro, o que el correo vaya a una dirección que
no sea la suya.
"""
from datetime import datetime, timedelta

import pytest

import main
from conftest import FakeResponse

TOKEN_AMA  = "a" * 40
TOKEN_AITA = "b" * 40
CORREO_AMA = "ama@ejemplo.test"


@pytest.fixture
def familia(monkeypatch):
    monkeypatch.setattr(main, "SALUD_FAMILIA", {
        "ama":  {"token": TOKEN_AMA,  "correo": CORREO_AMA},
        "aita": {"token": TOKEN_AITA, "correo": "aita@ejemplo.test"},
    })


def _cab(token):
    return {"X-Auth-Token": token}


def _lote(nombre="resting_heart_rate", fecha="2026-10-14", valor=58, unidad="count/min"):
    return {"data": {"metrics": [
        {"name": nombre, "units": unidad, "data": [{"date": f"{fecha} 08:00:00 +0200", "qty": valor}]},
    ]}}


def _sin_health_metrics(mock_requests):
    tocadas = [c for c in mock_requests.calls if "health_metrics" in c[1]]
    assert tocadas == [], f"la salud de la familia ha tocado health_metrics: {tocadas}"


class TestConfiguracion:
    def test_lee_varias_personas(self):
        p = main._leer_salud_familia(f"ama:{TOKEN_AMA}:{CORREO_AMA}, aita:{TOKEN_AITA}:a@b.es", {})
        assert p == {"ama":  {"token": TOKEN_AMA, "correo": CORREO_AMA},
                     "aita": {"token": TOKEN_AITA, "correo": "a@b.es"}}

    def test_vacia_no_hay_nadie(self):
        assert main._leer_salud_familia("", {}) == {}

    @pytest.mark.parametrize("entrada", [
        f"Ama:{TOKEN_AMA}:{CORREO_AMA}",           # mayúsculas en el identificador
        f"ama:{'x' * 10}:{CORREO_AMA}",            # token corto
        f"ama:{TOKEN_AMA}:no-es-un-correo",
        f"ama:{TOKEN_AMA}",                        # le falta una parte
    ])
    def test_una_entrada_mala_se_descarta_sola(self, entrada):
        p = main._leer_salud_familia(f"{entrada},aita:{TOKEN_AITA}:a@b.es", {})
        assert list(p) == ["aita"]

    def test_token_repetido_descarta_a_los_dos(self):
        p = main._leer_salud_familia(f"ama:{TOKEN_AMA}:a@b.es,aita:{TOKEN_AMA}:c@d.es", {})
        assert p == {}

    def test_token_igual_que_otro_del_entorno_se_descarta(self):
        """Con el mismo token que la ingesta de Mikel, el iPhone de su madre escribiría en
        lo suyo y el token de Mikel leería lo de ella."""
        p = main._leer_salud_familia(f"ama:{TOKEN_AMA}:a@b.es",
                                     {"HEALTH_INGEST_TOKEN": TOKEN_AMA})
        assert p == {}


class TestAutenticacion:
    def test_sin_token(self, client, familia):
        assert client.post("/familia/salud/ingest", json=_lote()).status_code == 403
        assert client.get("/familia/salud/resumen").status_code == 403

    def test_el_token_de_mikel_no_entra(self, client, familia, mock_requests):
        r = client.post("/familia/salud/ingest", json=_lote(), headers=_cab("health-token"))
        assert r.status_code == 403
        assert client.get("/familia/salud/resumen", headers=_cab("health-token")).status_code == 403
        assert mock_requests.calls == []

    def test_el_token_de_la_familia_no_entra_en_lo_de_mikel(self, client, familia, mock_requests):
        assert client.post("/health/ingest", json=_lote(), headers=_cab(TOKEN_AMA)).status_code == 403
        assert client.post("/health/ingest/simple", json=[], headers=_cab(TOKEN_AMA)).status_code == 403
        assert mock_requests.calls == []

    def test_por_la_query_no_vale(self, client, familia, mock_requests):
        """Integración nueva: el token solo en cabecera, que por la query acaba en el
        registro de URLs."""
        r = client.post(f"/familia/salud/ingest?token={TOKEN_AMA}", json=_lote())
        assert r.status_code == 403

    def test_bearer_vale(self, client, familia, mock_requests):
        r = client.post("/familia/salud/ingest", json=_lote(),
                        headers={"Authorization": f"Bearer {TOKEN_AMA}"})
        assert r.status_code == 200

    def test_sin_configurar_no_entra_nadie(self, client, monkeypatch, mock_requests):
        monkeypatch.setattr(main, "SALUD_FAMILIA", {})
        assert client.post("/familia/salud/ingest", json=_lote(), headers=_cab("")).status_code == 403


class TestIngesta:
    def test_guarda_en_su_tabla_con_su_persona(self, client, familia, mock_requests):
        r = client.post("/familia/salud/ingest", json=_lote(), headers=_cab(TOKEN_AMA))
        assert r.status_code == 200 and r.json() == {"ok": True, "upserted": 1}
        upsert = mock_requests.called("POST", "/rest/v1/salud_familia?")
        assert len(upsert) == 1
        assert "on_conflict=persona,metric_date,metric_name" in upsert[0][1]
        filas = upsert[0][2]["json"]
        assert filas == [{"metric_date": "2026-10-14", "metric_name": "resting_heart_rate",
                          "value": 58.0, "unit": "count/min",
                          "extra": {"qty": 58}, "fuente": main.FUENTE_AUTO_EXPORT,
                          "persona": "ama"}]
        _sin_health_metrics(mock_requests)

    def test_lo_existente_se_lee_solo_de_su_persona(self, client, familia, mock_requests):
        client.post("/familia/salud/ingest", json=_lote(), headers=_cab(TOKEN_AITA))
        lecturas = mock_requests.called("GET", "/rest/v1/salud_familia")
        assert lecturas and all("persona=eq.aita" in c[1] for c in lecturas)
        assert mock_requests.called("POST", "salud_familia")[0][2]["json"][0]["persona"] == "aita"

    def test_la_persona_del_cuerpo_no_cuenta(self, client, familia, mock_requests):
        cuerpo = _lote()
        cuerpo["persona"] = "aita"
        cuerpo["data"]["metrics"][0]["data"][0]["persona"] = "aita"
        client.post("/familia/salud/ingest", json=cuerpo, headers=_cab(TOKEN_AMA))
        assert mock_requests.called("POST", "salud_familia")[0][2]["json"][0]["persona"] == "ama"

    def test_las_reglas_de_la_ingesta_se_aplican_igual(self, client, familia, mock_requests):
        """Forma del dato, no de quién lo manda: kJ a kcal, y una acumulativa no baja."""
        mock_requests.add("GET", "/rest/v1/salud_familia", FakeResponse([
            {"metric_date": "2026-10-14", "metric_name": "active_energy", "value": 500, "extra": {}},
        ]))
        lote = _lote("active_energy", valor=1046, unidad="kJ")       # 250 kcal < 500
        r = client.post("/familia/salud/ingest", json=lote, headers=_cab(TOKEN_AMA))
        assert r.json() == {"ok": True, "upserted": 0}

    def test_entrenos_en_el_mismo_upsert(self, client, familia, mock_requests):
        cuerpo = {"data": {"metrics": [], "workouts": [
            {"name": "Caminar", "start": "2026-10-14 10:00:00 +0200", "duration": 1800},
            {"name": "Yoga",    "start": "2026-10-14 19:00:00 +0200", "duration": 1200},
        ]}}
        r = client.post("/familia/salud/ingest", json=cuerpo, headers=_cab(TOKEN_AMA))
        assert r.json()["ok"] is True
        fila = mock_requests.called("POST", "salud_familia")[0][2]["json"][0]
        assert fila["metric_name"] == "workouts" and fila["value"] == 2.0
        assert fila["persona"] == "ama"
        _sin_health_metrics(mock_requests)

    def test_no_dispara_nada_de_lo_de_mikel(self, client, familia, mock_requests, monkeypatch):
        """La noche de su madre no puede mandar el correo de la mañana de Mikel."""
        llamadas = []
        monkeypatch.setattr(main, "_avisar_sueno_recibido", lambda *a, **k: llamadas.append(a))
        antes = main._ultimo_envio_entrenos
        lote = {"data": {"metrics": [{"name": "sleep_analysis", "units": "hr", "data": [
            {"date": "2026-10-15 00:00:00 +0200", "totalSleep": 7.2,
             "sleepStart": "2026-10-14 23:30:00 +0200"}]}]}}
        r = client.post("/familia/salud/ingest", json=lote, headers=_cab(TOKEN_AMA))
        assert r.status_code == 200
        assert llamadas == []
        assert main._ultimo_envio_entrenos == antes
        _sin_health_metrics(mock_requests)

    def test_cuerpo_vacio_400(self, client, familia, mock_requests):
        r = client.post("/familia/salud/ingest", content=b"", headers=_cab(TOKEN_AMA))
        assert r.status_code == 400

    def test_lote_vacio_ok(self, client, familia, mock_requests):
        r = client.post("/familia/salud/ingest", json={"data": {"metrics": [], "workouts": []}},
                        headers=_cab(TOKEN_AMA))
        assert r.json()["vacio"] is True

    def test_fallo_de_escritura_502(self, client, familia, mock_requests):
        mock_requests.add("POST", "salud_familia", FakeResponse({}, 500))
        r = client.post("/familia/salud/ingest", json=_lote(), headers=_cab(TOKEN_AMA))
        assert r.status_code == 502

    def test_la_ingesta_de_mikel_sigue_igual(self, client, familia, mock_requests):
        r = client.post("/health/ingest", json=_lote(), headers=_cab("health-token"))
        assert r.status_code == 200
        upsert = mock_requests.called("POST", "health_metrics")
        assert upsert and "persona" not in upsert[0][2]["json"][0]
        assert mock_requests.called("POST", "salud_familia") == []

    def test_tope_de_cuerpo(self):
        assert main._tope_de_cuerpo("/familia/salud/ingest") == main.MAX_INGEST_BYTES


class TestRetencion:
    def test_purga_lo_viejo_de_su_persona_una_vez_al_dia(self, client, familia, mock_requests,
                                                         monkeypatch):
        monkeypatch.setattr(main, "_ahora_local",
                            lambda: datetime(2026, 10, 15, 9, 0, tzinfo=main.LOCAL_TZ))
        for _ in range(2):
            client.post("/familia/salud/ingest", json=_lote(), headers=_cab(TOKEN_AMA))
        borrados = mock_requests.called("DELETE", "salud_familia")
        limite = (datetime(2026, 10, 15).date() - timedelta(days=400)).isoformat()
        assert len(borrados) == 2           # sus métricas y sus envíos, una sola vez
        assert all("persona=eq.ama" in c[1] and f"lt.{limite}" in c[1] for c in borrados)

    def test_a_cero_no_purga(self, client, familia, mock_requests, monkeypatch):
        monkeypatch.setattr(main, "SALUD_FAMILIA_RETENCION_DIAS", 0)
        client.post("/familia/salud/ingest", json=_lote(), headers=_cab(TOKEN_AMA))
        assert mock_requests.called("DELETE", "salud_familia") == []


class TestResumen:
    def _filas(self):
        hoy = datetime.now(main.LOCAL_TZ).date()
        return [{"metric_date": (hoy - timedelta(days=i)).isoformat(),
                 "metric_name": "resting_heart_rate", "value": 60 + i, "unit": "count/min",
                 "extra": {}} for i in range(5)]

    def test_lee_solo_su_persona_y_su_tabla(self, client, familia, mock_requests):
        mock_requests.add("GET", "/rest/v1/salud_familia", FakeResponse(self._filas()))
        r = client.get("/familia/salud/resumen", headers=_cab(TOKEN_AMA))
        assert r.status_code == 200
        d = r.json()
        assert d["salud"]["fc_reposo"]["ultimo"] == 60
        assert "## SALUD" in d["texto"]
        lecturas = mock_requests.called("GET", "salud_familia")
        assert len(lecturas) == 2 and all("persona=eq.ama" in c[1] for c in lecturas)
        _sin_health_metrics(mock_requests)

    def test_sin_datos_lo_dice(self, client, familia, mock_requests):
        r = client.get("/familia/salud/resumen", headers=_cab(TOKEN_AMA))
        assert r.json()["salud"] == {}
        assert "no ha mandado nada" in r.json()["texto"]

    def test_supabase_caido_502(self, client, familia, mock_requests):
        """No una sección vacía: el modelo lo contaría como que el reloj no mandó nada."""
        mock_requests.add("GET", "salud_familia", FakeResponse({}, 500))
        assert client.get("/familia/salud/resumen", headers=_cab(TOKEN_AMA)).status_code == 502

    def test_el_resumen_de_mikel_no_lee_la_familia(self, mock_requests):
        main._brief_salud()
        assert mock_requests.called("GET", "health_metrics")
        assert mock_requests.called("GET", "salud_familia") == []


class TestBriefing:
    @pytest.fixture
    def correos(self, monkeypatch):
        enviados = []
        monkeypatch.setattr(main, "enviar_correo",
                            lambda asunto, cuerpo, adjunto=None, destino=None, html=None:
                            enviados.append({"asunto": asunto, "cuerpo": cuerpo,
                                             "destino": destino, "html": html}))
        return enviados

    def test_va_a_su_correo_con_el_pie(self, client, familia, mock_requests, correos):
        r = client.post("/familia/salud/briefing", headers=_cab(TOKEN_AMA),
                        json={"texto": "Has dormido bien.", "asunto": "Tu día\r\nBcc: x@y.z"})
        assert r.status_code == 200
        assert correos[0]["destino"] == CORREO_AMA
        assert correos[0]["asunto"] == "Tu día Bcc: x@y.z"     # sin saltos de línea
        assert correos[0]["cuerpo"].startswith("Has dormido bien.")
        assert "No es una opinión médica" in correos[0]["cuerpo"]
        reserva = mock_requests.called("POST", "salud_familia_envios")
        assert reserva[0][2]["json"][0]["persona"] == "ama"

    def test_el_destino_del_cuerpo_no_cuenta(self, client, familia, mock_requests, correos):
        client.post("/familia/salud/briefing", headers=_cab(TOKEN_AITA),
                    json={"texto": "Hola", "destino": "otro@malo.test", "correo": "otro@malo.test"})
        assert correos[0]["destino"] == "aita@ejemplo.test"

    def test_uno_al_dia(self, client, familia, mock_requests, correos):
        mock_requests.add("POST", "salud_familia_envios", FakeResponse({}, 409))
        r = client.post("/familia/salud/briefing", headers=_cab(TOKEN_AMA), json={"texto": "Hola"})
        assert r.status_code == 409 and correos == []

    def test_forzar_se_salta_la_reserva(self, client, familia, mock_requests, correos):
        mock_requests.add("POST", "salud_familia_envios", FakeResponse({}, 409))
        r = client.post("/familia/salud/briefing?forzar=1", headers=_cab(TOKEN_AMA),
                        json={"texto": "Hola"})
        assert r.status_code == 200 and len(correos) == 1

    def test_tope_diario(self, client, familia, mock_requests, correos):
        for _ in range(main.SALUD_FAMILIA_ENVIOS_DIA):
            client.post("/familia/salud/briefing?forzar=1", headers=_cab(TOKEN_AMA), json={"texto": "x"})
        r = client.post("/familia/salud/briefing?forzar=1", headers=_cab(TOKEN_AMA), json={"texto": "x"})
        assert r.status_code == 429

    def test_si_falla_el_envio_libera_el_dia(self, client, familia, mock_requests, monkeypatch):
        def _falla(*a, **k):
            raise OSError("sin red")
        monkeypatch.setattr(main, "enviar_correo", _falla)
        r = client.post("/familia/salud/briefing", headers=_cab(TOKEN_AMA), json={"texto": "Hola"})
        assert r.status_code == 502
        borrado = mock_requests.called("DELETE", "salud_familia_envios")
        assert borrado and "persona=eq.ama" in borrado[0][1]

    def test_alerta_no_gasta_el_informe_del_dia(self, client, familia, mock_requests, correos):
        mock_requests.add("POST", "salud_familia_envios", FakeResponse({}, 409))
        r = client.post("/familia/salud/briefing", headers=_cab(TOKEN_AMA),
                        json={"texto": "Pulso alto dos días", "tipo": "alerta"})
        assert r.status_code == 200 and r.json()["tipo"] == "alerta"
        assert mock_requests.called("POST", "salud_familia_envios") == []
        assert correos[0]["destino"] == CORREO_AMA

    def test_tipo_desconocido_422(self, client, familia, mock_requests, correos):
        r = client.post("/familia/salud/briefing", headers=_cab(TOKEN_AMA),
                        json={"texto": "x", "tipo": "otro"})
        assert r.status_code == 422 and correos == []

    def test_html_lleva_el_pie_dentro_del_cuerpo(self, client, familia, mock_requests, correos):
        client.post("/familia/salud/briefing", headers=_cab(TOKEN_AMA),
                    json={"texto": "Hola", "html": "<html><body><h1>Hola</h1></body></html>"})
        html = correos[0]["html"]
        assert "No es una opinión médica" in html
        assert html.index("No es una opinión médica") < html.index("</body>")

    def test_sin_html_no_hay_html(self, client, familia, mock_requests, correos):
        client.post("/familia/salud/briefing", headers=_cab(TOKEN_AMA), json={"texto": "Hola"})
        assert correos[0]["html"] is None

    def test_sin_token(self, client, familia, mock_requests, correos):
        r = client.post("/familia/salud/briefing", json={"texto": "Hola"},
                        headers=_cab("health-token"))
        assert r.status_code == 403 and correos == []

    def test_texto_vacio_o_enorme(self, client, familia, mock_requests, correos):
        assert client.post("/familia/salud/briefing", headers=_cab(TOKEN_AMA),
                           json={"texto": ""}).status_code == 422
        assert client.post("/familia/salud/briefing", headers=_cab(TOKEN_AMA),
                           json={"texto": "x" * (main.SALUD_FAMILIA_TEXTO_MAX + 1)}).status_code == 422


class TestEnviarCorreoDestino:
    def test_destino_sustituye_a_brief_to(self, monkeypatch):
        enviados = []

        class _SMTP:
            def __init__(self, *a, **k): pass
            def __enter__(self): return self
            def __exit__(self, *a): pass
            def starttls(self): pass
            def login(self, *a): pass
            def send_message(self, msg): enviados.append(msg)

        for nombre, valor in (("SMTP_HOST", "smtp.test"), ("SMTP_USER", "yo@test"),
                              ("SMTP_PASSWORD", "x"), ("BRIEF_TO", "mikel@test"), ("SMTP_PORT", 587)):
            monkeypatch.setattr(main, nombre, valor)
        monkeypatch.setattr(main.smtplib, "SMTP", _SMTP)
        main.enviar_correo("a", "b", destino=CORREO_AMA)
        main.enviar_correo("a", "b")
        assert [m["To"] for m in enviados] == [CORREO_AMA, "mikel@test"]
        # Sin html, el correo de siempre: texto plano y nada más.
        assert enviados[1].get_content_type() == "text/plain"
        main.enviar_correo("a", "b", destino=CORREO_AMA, html="<p>hola</p>")
        assert enviados[2].get_content_type() == "multipart/alternative"
        assert [p.get_content_type() for p in enviados[2].iter_parts()] == ["text/plain", "text/html"]


class TestCiclo:
    """El ciclo menstrual llega en `data.cycleTracking` y solo lo lee la ingesta de la
    familia. Es el dato más sensible de la tabla: se guarda lo justo y tal cual."""

    REGISTROS = [
        {"start": "2026-09-01 00:00:00 +0200", "end": "2026-09-05 23:59:59 +0200",
         "name": "Menstrual Flow", "value": "Medium", "isCycleStart": True, "basura": "x" * 50},
        {"start": "2026-09-14 08:00:00 +0200", "end": "2026-09-14 08:00:00 +0200",
         "name": "Ovulation Test Result", "value": "Positive/Peak"},
        {"start": "no-es-fecha", "name": "Menstrual Flow", "value": "Light"},
        {"start": "2026-09-20 00:00:00 +0200", "value": "Light"},          # sin nombre
        "no-es-un-registro",
    ]

    def test_se_guarda_en_su_tabla_limpio(self, client, familia, mock_requests):
        r = client.post("/familia/salud/ingest", headers=_cab(TOKEN_AMA),
                        json={"data": {"cycleTracking": self.REGISTROS}})
        assert r.json() == {"ok": True, "upserted": 2}
        filas = {f["metric_date"]: f for f in mock_requests.called("POST", "salud_familia")[0][2]["json"]}
        assert set(filas) == {"2026-09-01", "2026-09-14"}
        assert all(f["metric_name"] == "cycle_tracking" and f["persona"] == "ama" for f in filas.values())
        assert filas["2026-09-01"]["extra"] == {"registros": [{
            "start": "2026-09-01 00:00:00 +0200", "end": "2026-09-05 23:59:59 +0200",
            "name": "Menstrual Flow", "value": "Medium", "isCycleStart": True}]}
        assert "isCycleStart" not in filas["2026-09-14"]["extra"]["registros"][0]
        _sin_health_metrics(mock_requests)

    def test_en_lista_de_lotes_tambien(self, client, familia, mock_requests):
        r = client.post("/familia/salud/ingest", headers=_cab(TOKEN_AMA),
                        json=[{"data": {"cycleTracking": self.REGISTROS[:1]}}, _lote()])
        assert r.json() == {"ok": True, "upserted": 2}

    def test_bloque_vacio_es_lote_vacio(self, client, familia, mock_requests):
        r = client.post("/familia/salud/ingest", headers=_cab(TOKEN_AMA),
                        json={"data": {"cycleTracking": []}})
        assert r.json()["ok"] is True and r.json()["vacio"] is True

    def test_la_ingesta_de_mikel_no_lo_guarda(self, client, familia, mock_requests):
        r = client.post("/health/ingest", headers=_cab("health-token"),
                        json={"data": {"cycleTracking": self.REGISTROS}})
        assert r.json()["ok"] is False
        assert mock_requests.called("POST", "health_metrics") == []

    def test_sale_en_el_resumen(self, client, familia, mock_requests):
        hoy = datetime.now(main.LOCAL_TZ).date()
        def dia(n):
            return (hoy - timedelta(days=n)).isoformat()
        filas = [
            {"metric_date": dia(60), "metric_name": "cycle_tracking", "value": 1, "unit": "count",
             "extra": {"registros": [{"start": f"{dia(60)} 00:00:00 +0200", "end": f"{dia(56)} 23:59:59 +0200",
                                      "name": "Menstrual Flow", "value": "Medium", "isCycleStart": True}]}},
            {"metric_date": dia(31), "metric_name": "cycle_tracking", "value": 1, "unit": "count",
             "extra": {"registros": [{"start": f"{dia(31)} 00:00:00 +0200", "end": f"{dia(27)} 23:59:59 +0200",
                                      "name": "Menstrual Flow", "value": "Light", "isCycleStart": True}]}},
        ]
        mock_requests.add("GET", "metric_name=eq.cycle_tracking", FakeResponse(filas))
        d = client.get("/familia/salud/resumen", headers=_cab(TOKEN_AMA)).json()
        assert d["ciclo"]["inicios_de_ciclo"] == [dia(60), dia(31)]
        assert d["ciclo"]["dias_entre_inicios"] == [29]
        assert "## CICLO MENSTRUAL" in d["texto"] and "Días entre inicios" in d["texto"]
        lecturas = [c[1] for c in mock_requests.called("GET", "salud_familia")]
        assert any("metric_name=neq.cycle_tracking" in u for u in lecturas)
        assert all("persona=eq.ama" in u for u in lecturas)

    def test_sin_registros_no_hay_seccion(self, client, familia, mock_requests):
        d = client.get("/familia/salud/resumen", headers=_cab(TOKEN_AMA)).json()
        assert d["ciclo"] == {} and "CICLO" not in d["texto"]


class TestDatosCrudos:
    def test_sus_filas_tal_cual_y_solo_las_suyas(self, client, familia, mock_requests):
        filas = [{"metric_date": "2026-10-14", "metric_name": "heart_rate", "value": 70,
                  "unit": "count/min", "extra": {"Min": 50, "Max": 140}},
                 {"metric_date": "2026-10-15", "metric_name": "sleep_analysis", "value": 7.1,
                  "unit": "hr", "extra": {"sleepStart": "2026-10-14 23:40:00 +0200"}}]
        mock_requests.add("GET", "/rest/v1/salud_familia", FakeResponse(filas))
        r = client.get("/familia/salud/datos?dias=10", headers=_cab(TOKEN_AITA))
        assert r.status_code == 200
        d = r.json()
        assert d["filas"] == filas and d["dias"] == 10
        assert d["ultimo_dia_por_metrica"] == {"heart_rate": "2026-10-14",
                                               "sleep_analysis": "2026-10-15"}
        lecturas = mock_requests.called("GET", "salud_familia")
        assert len(lecturas) == 1 and "persona=eq.aita" in lecturas[0][1]
        _sin_health_metrics(mock_requests)

    def test_dias_acotados(self, client, familia, mock_requests):
        assert client.get("/familia/salud/datos?dias=0", headers=_cab(TOKEN_AMA)).status_code == 422
        assert client.get("/familia/salud/datos?dias=401", headers=_cab(TOKEN_AMA)).status_code == 422

    def test_sin_su_token_no(self, client, familia, mock_requests):
        assert client.get("/familia/salud/datos", headers=_cab("health-token")).status_code == 403
        assert mock_requests.calls == []

    def test_supabase_caido_502(self, client, familia, mock_requests):
        mock_requests.add("GET", "salud_familia", FakeResponse({}, 500))
        assert client.get("/familia/salud/datos", headers=_cab(TOKEN_AMA)).status_code == 502
