"""Tests de ingesta de salud (Apple Watch / iOS Shortcuts) y entrenamiento."""
import json

import main
from conftest import FakeResponse


class TestHealthIngestAuth:
    def test_ingest_sin_token(self, client):
        assert client.post("/health/ingest", json={}).status_code == 403

    def test_ingest_simple_sin_token(self, client):
        assert client.post("/health/ingest/simple", json=[]).status_code == 403


class TestHealthIngest:
    URL = "/health/ingest?token=health-token"

    @staticmethod
    def _filas(mock_requests):
        """Filas del upsert en bloque de métricas (M4: una sola llamada por lote)."""
        for _, _, kw in mock_requests.called("POST", "health_metrics"):
            cuerpo = kw["json"]
            if isinstance(cuerpo, list):
                return cuerpo
        return []

    @staticmethod
    def _existentes(mock_requests, filas):
        """Simula la lectura previa en bloque, que sustituye a un GET por métrica."""
        mock_requests.add("GET", "metric_date=in.", FakeResponse(filas))

    def test_metrica_normal_se_inserta(self, client, mock_requests):
        r = client.post(self.URL, json={"data": {"metrics": [
            {"name": "weight_body_mass", "units": "kg", "data": [{"date": "2026-07-05 08:00:00", "qty": 68.5}]}
        ]}})
        assert r.status_code == 200
        assert r.json()["upserted"] == 1
        fila = self._filas(mock_requests)[0]
        assert fila["metric_date"] == "2026-07-05"
        assert fila["metric_name"] == "weight_body_mass"
        assert fila["value"] == 68.5

    def test_acumulativa_no_pisa_valor_mayor_existente(self, client, mock_requests):
        self._existentes(mock_requests, [
            {"metric_date": "2026-07-05", "metric_name": "step_count", "value": 9000}
        ])
        r = client.post(self.URL, json={"data": {"metrics": [
            {"name": "step_count", "units": "count", "data": [{"date": "2026-07-05 08:00:00", "qty": 5000}]}
        ]}})
        assert r.json()["upserted"] == 0
        assert self._filas(mock_requests) == []      # no se escribe nada
        assert not mock_requests.called("PATCH", "health_metrics")

    def test_acumulativa_actualiza_si_es_mayor(self, client, mock_requests):
        self._existentes(mock_requests, [
            {"metric_date": "2026-07-05", "metric_name": "step_count", "value": 3000}
        ])
        r = client.post(self.URL, json={"data": {"metrics": [
            {"name": "step_count", "units": "count", "data": [{"date": "2026-07-05 08:00:00", "qty": 5000}]}
        ]}})
        assert r.json()["upserted"] == 1
        assert self._filas(mock_requests)[0]["value"] == 5000

    def test_energia_kj_se_convierte_a_kcal(self, client, mock_requests):
        r = client.post(self.URL, json={"data": {"metrics": [
            {"name": "active_energy", "units": "kJ", "data": [{"date": "2026-07-05 08:00:00", "qty": 4184}]}
        ]}})
        assert r.json()["upserted"] == 1
        fila = self._filas(mock_requests)[0]
        assert fila["value"] == 1000.0
        assert fila["unit"] == "kcal"

    def test_sleep_guarda_hora_de_inicio(self, client, mock_requests):
        r = client.post(self.URL, json={"data": {"metrics": [
            {"name": "sleep_analysis", "units": "hr",
             "data": [{"date": "2026-07-04 23:45:00", "totalSleep": 7.8, "deep": 1.2}]}
        ]}})
        assert r.json()["upserted"] == 1
        fila = self._filas(mock_requests)[0]
        assert fila["value"] == 7.8
        assert fila["extra"]["sleep_start"] == "23:45"

    def test_un_lote_grande_son_dos_viajes_no_uno_por_metrica(self, client, mock_requests):
        """M4: antes eran GET+POST(+PATCH) por métrica — decenas de viajes secuenciales
        a Supabase por cada sincronización del Watch. Ahora: una lectura y un upsert."""
        metricas = [
            {"name": f"metrica_{i}", "units": "u",
             "data": [{"date": "2026-07-05 08:00:00", "qty": i}]}
            for i in range(30)
        ]
        r = client.post(self.URL, json={"data": {"metrics": metricas}})
        assert r.json()["upserted"] == 30
        assert len(mock_requests.called("GET", "health_metrics")) == 1
        assert len(mock_requests.called("POST", "health_metrics")) == 1
        assert len(self._filas(mock_requests)) == 30
        assert not mock_requests.called("PATCH", "health_metrics")

    def test_workouts_agrupados_por_dia(self, client, mock_requests):
        r = client.post(self.URL, json={"data": {"workouts": [
            {"start": "2026-07-05 10:00:00", "name": "Fuerza"},
            {"start": "2026-07-05 18:00:00", "name": "Cardio"},
            {"start": "2026-07-04 09:00:00", "name": "Fuerza"},
        ]}})
        assert r.json()["upserted"] == 2  # una fila por día
        payloads = [c[2]["json"] for c in mock_requests.called("POST", "health_metrics")]
        by_date = {p["metric_date"]: p for p in payloads}
        assert by_date["2026-07-05"]["value"] == 2.0
        assert by_date["2026-07-04"]["value"] == 1.0


class TestHealthIngestSimple:
    URL = "/health/ingest/simple?token=health-token"

    def test_array_plano(self, client, mock_requests):
        r = client.post(self.URL, json=[
            {"metric": "weight_body_mass", "date": "2026-07-05", "value": 68.2, "unit": "kg"}
        ])
        assert r.status_code == 200
        body = r.json()
        assert body["upserted"] == 1
        assert body["received"] == 1

    def test_ndjson_de_ios_shortcuts(self, client, mock_requests):
        ndjson = "\n".join([
            json.dumps({"metric": "step_count", "date": "2026-07-05", "value": 8000}),
            json.dumps({"metric": "resting_heart_rate", "date": "2026-07-05", "value": 52}),
        ])
        r = client.post(self.URL, json={"lines": ndjson})
        body = r.json()
        assert body["received"] == 2
        assert body["upserted"] == 2

    def test_value_none_va_a_parse_errors(self, client, mock_requests):
        r = client.post(self.URL, json=[{"metric": "step_count", "date": "2026-07-05", "value": None}])
        body = r.json()
        assert body["received"] == 0
        assert body["parse_errors"][0]["metric"] == "step_count"

    def test_acumulativa_saltada_si_existente_mayor(self, client, mock_requests):
        # La lectura de lo ya guardado es en bloque desde M4 (un GET por lote).
        mock_requests.add("GET", "metric_date=in.", FakeResponse([
            {"metric_date": "2026-07-05", "metric_name": "step_count", "value": 9000}
        ]))
        r = client.post(self.URL, json=[{"metric": "step_count", "date": "2026-07-05", "value": 100}])
        body = r.json()
        assert body["upserted"] == 0
        assert body["skipped"]

    def test_ndjson_linea_mal_formada_no_tumba_el_lote(self, client, mock_requests):
        # Regresión: una sola línea con JSON inválido daba un 500 y el Shortcut
        # dejaba de sincronizar. Ahora se descarta y las buenas se procesan igual.
        ndjson = "\n".join([
            json.dumps({"metric": "heart_rate", "date": "2026-07-26", "value": 60}),
            '{"metric": "step_count", "date": "2026-07-26", "value":}',  # inválido
        ])
        r = client.post(self.URL, json={"data": ndjson})
        assert r.status_code == 200
        body = r.json()
        assert body["upserted"] == 1                       # la línea buena entra
        assert any("JSON inválido" in e.get("error", "") for e in body["parse_errors"])

    def test_cuerpo_no_json_devuelve_400(self, client):
        r = client.post(self.URL, content=b"esto no es json",
                        headers={"Content-Type": "application/json"})
        assert r.status_code == 400

    def test_ndjson_crudo_en_el_cuerpo(self, client, mock_requests):
        # El Shortcut manda NDJSON directamente en el cuerpo (no envuelto en una clave):
        # varias líneas => no es un JSON de una pieza, pero debe procesarse igual.
        ndjson = "\n".join([
            json.dumps({"metric": "heart_rate", "date": "2026-07-26", "value": 60}),
            json.dumps({"metric": "respiratory_rate", "date": "2026-07-26", "value": 14}),
        ])
        r = client.post(self.URL, content=ndjson.encode("utf-8"),
                        headers={"Content-Type": "application/json"})
        assert r.status_code == 200
        assert r.json()["upserted"] == 2

    def test_ndjson_crudo_con_bom(self, client, mock_requests):
        # iOS a veces añade un BOM al principio del cuerpo; no debe romper el parseo.
        one = json.dumps({"metric": "heart_rate", "date": "2026-07-26", "value": 61})
        r = client.post(self.URL, content=b"\xef\xbb\xbf" + one.encode("utf-8"),
                        headers={"Content-Type": "application/json"})
        assert r.status_code == 200
        assert r.json()["upserted"] == 1


class TestHealthIngestCuerpoInvalido:
    def test_ingest_hae_no_json_devuelve_400(self, client):
        r = client.post("/health/ingest?token=health-token", content=b"xxx",
                        headers={"Content-Type": "application/json"})
        assert r.status_code == 400

    def test_ingest_hae_no_objeto_devuelve_400(self, client):
        r = client.post("/health/ingest?token=health-token", json=[1, 2, 3])
        assert r.status_code == 400


class TestSleepExclude:
    def test_toggle(self, client, auth_headers, mock_requests):
        mock_requests.add("GET", "metric_name=eq.sleep_analysis", FakeResponse([{"extra": {"deep": 1.2}}]))
        mock_requests.add("PATCH", "metric_name=eq.sleep_analysis", FakeResponse([], 204))
        r = client.patch("/health/sleep/2026-07-04/exclude", headers=auth_headers)
        assert r.json() == {"date": "2026-07-04", "excluded": True}
        patched = mock_requests.called("PATCH", "metric_name=eq.sleep_analysis")[0][2]["json"]
        assert patched["extra"]["excluded"] is True

    def test_sin_datos_404(self, client, auth_headers, mock_requests):
        mock_requests.add("GET", "metric_name=eq.sleep_analysis", FakeResponse([]))
        r = client.patch("/health/sleep/2026-07-04/exclude", headers=auth_headers)
        assert r.status_code == 404

    def test_fecha_invalida(self, client, auth_headers):
        r = client.patch("/health/sleep/ayer/exclude", headers=auth_headers)
        assert r.status_code == 422


class TestHealthMetrics:
    def test_days_fuera_de_rango(self, client, auth_headers):
        assert client.get("/health/metrics?days=0", headers=auth_headers).status_code == 400
        assert client.get("/health/metrics?days=400", headers=auth_headers).status_code == 400

    def test_agrupa_por_metrica(self, client, auth_headers, mock_requests):
        mock_requests.add("GET", "health_metrics", FakeResponse([
            {"metric_name": "step_count", "metric_date": "2026-07-04", "value": 9000, "unit": "count", "extra": {}},
            {"metric_name": "step_count", "metric_date": "2026-07-05", "value": 4000, "unit": "count", "extra": {}},
            {"metric_name": "weight_body_mass", "metric_date": "2026-07-05", "value": 68.2, "unit": "kg", "extra": {}},
        ]))
        r = client.get("/health/metrics?days=7", headers=auth_headers)
        data = r.json()
        assert len(data["metrics"]["step_count"]) == 2
        assert len(data["metrics"]["weight_body_mass"]) == 1

    def test_latest_devuelve_ultimo_valor(self, client, auth_headers, mock_requests):
        mock_requests.add("GET", "health_metrics", FakeResponse([
            {"metric_name": "step_count", "metric_date": "2026-07-05", "value": 4000, "unit": "count", "extra": {}},
            {"metric_name": "step_count", "metric_date": "2026-07-04", "value": 9000, "unit": "count", "extra": {}},
        ]))
        r = client.get("/health/latest", headers=auth_headers)
        assert r.json()["latest"]["step_count"]["date"] == "2026-07-05"
        assert r.json()["latest"]["step_count"]["value"] == 4000


class TestTraining:
    CLIENT = {"id": "c1", "price_per_hour": 20, "sessions_per_payment": 10, "created_at": "2026-01-01"}

    def test_summary_sin_cliente(self, client, auth_headers, mock_requests):
        mock_requests.add("GET", "training_clients", FakeResponse([]))
        r = client.get("/training/summary", headers=auth_headers)
        assert r.json() == {"client": None}

    def test_summary_calcula_deuda(self, client, auth_headers, mock_requests):
        mock_requests.add("GET", "training_clients", FakeResponse([self.CLIENT]))
        mock_requests.add("GET", "training_payments", FakeResponse([
            {"date": "2026-06-01", "created_at": "2026-06-01T10:00:00Z"}
        ]))
        # created_at es NOT NULL en el esquema y ahora el filtrado por cobro se hace
        # en memoria (antes lo hacía Supabase con created_at=gt.), así que el mock
        # tiene que traerlo como lo traería la BD.
        mock_requests.add("GET", "training_sessions", FakeResponse([
            {"date": "2026-07-01", "duration_hours": 1.5, "created_at": "2026-07-01T09:00:00Z"},
            {"date": "2026-06-20", "duration_hours": 1.0, "created_at": "2026-06-20T09:00:00Z"},
        ]))
        r = client.get("/training/summary", headers=auth_headers)
        data = r.json()
        assert data["sessions_since_payment"] == 2
        assert data["hours_since_payment"] == 2.5
        assert data["amount_owed"] == 50.0   # 2.5h × 20€
        assert data["last_payment_date"] == "2026-06-01"

    def test_add_session_sin_cliente_400(self, client, auth_headers, mock_requests):
        mock_requests.add("GET", "training_clients", FakeResponse([]))
        r = client.post("/training/sessions", headers=auth_headers,
                        json={"date": "2026-07-05", "duration_hours": 1})
        assert r.status_code == 400

    def test_add_session_valida_fecha_y_horas(self, client, auth_headers):
        r = client.post("/training/sessions", headers=auth_headers,
                        json={"date": "05/07/2026", "duration_hours": 1})
        assert r.status_code == 422
        r2 = client.post("/training/sessions", headers=auth_headers,
                         json={"date": "2026-07-05", "duration_hours": 0})
        assert r2.status_code == 422

    def test_payment_calcula_importe_pendiente(self, client, auth_headers, mock_requests):
        mock_requests.add("GET", "training_clients", FakeResponse([self.CLIENT]))
        mock_requests.add("GET", "training_payments", FakeResponse([]))
        mock_requests.add("GET", "training_sessions", FakeResponse([
            {"date": "2026-07-01", "duration_hours": 2.0},
        ]))
        payment = {"id": "p1", "client_id": "c1", "date": "2026-07-05", "amount": 40.0}
        mock_requests.add("POST", "training_payments", FakeResponse([payment], 201))
        r = client.post("/training/payments", headers=auth_headers, json={"date": "2026-07-05"})
        assert r.json() == {"ok": True, "payment": payment}
        posted = mock_requests.called("POST", "training_payments")[0][2]["json"]
        assert posted["amount"] == 40.0


class TestMetricasAcumulativasCompartidas:
    """Las dos rutas de ingesta deben tratar igual las métricas acumulativas.

    /health/ingest/simple tenía su propia copia del conjunto y le faltaba
    resting_energy, así que por ahí un snapshot parcial podía pisar el total del día.
    """

    def test_ambas_rutas_usan_el_mismo_conjunto(self):
        assert "resting_energy" in main.CUMULATIVE_METRICS
        assert main.ENERGY_METRICS <= main.CUMULATIVE_METRICS

    def test_simple_no_pisa_resting_energy_con_un_valor_menor(self, client, mock_requests):
        mock_requests.add("GET", "metric_date=in.", FakeResponse([
            {"metric_date": "2026-07-28", "metric_name": "resting_energy", "value": 1800}
        ]))
        r = client.post(
            "/health/ingest/simple",
            headers={"X-Auth-Token": "health-token"},
            json=[{"metric": "resting_energy", "date": "2026-07-28", "value": 900}],
        )
        cuerpo = r.json()
        assert cuerpo["upserted"] == 0
        assert any("resting_energy" in s for s in cuerpo["skipped"])
        assert not mock_requests.called("POST", "health_metrics")   # no se escribe nada

    def test_error_de_supabase_no_filtra_su_texto_al_cliente(self, client, mock_requests):
        mock_requests.add("POST", "/rest/v1/health_metrics", FakeResponse(None, 500, "detalle interno de supabase"))
        r = client.post(
            "/health/ingest/simple",
            headers={"X-Auth-Token": "health-token"},
            json=[{"metric": "heart_rate", "date": "2026-07-28", "value": 60}],
        )
        assert r.status_code == 502
        assert "detalle interno" not in r.text


class TestResumenEntrenamientoFiltrado:
    """El resumen pide las sesiones UNA vez y de esa lista saca las dos vistas que
    necesita, en vez de hacer dos consultas con filtros distintos (M5)."""

    CLIENT = {"id": "c1", "price_per_hour": 20, "sessions_per_payment": 8}

    def _mock(self, mock_requests, pagos, sesiones):
        mock_requests.add("GET", "training_clients", FakeResponse([self.CLIENT]))
        mock_requests.add("GET", "training_payments", FakeResponse(pagos))
        mock_requests.add("GET", "training_sessions", FakeResponse(sesiones))

    def test_solo_cuenta_las_sesiones_posteriores_al_ultimo_cobro(self, client, auth_headers, mock_requests):
        self._mock(mock_requests,
            [{"date": "2026-06-15", "created_at": "2026-06-15T10:00:00Z"}],
            [
                {"date": "2026-06-20", "duration_hours": 2.0, "created_at": "2026-06-20T09:00:00Z"},  # cuenta
                {"date": "2026-06-10", "duration_hours": 3.0, "created_at": "2026-06-10T09:00:00Z"},  # ya cobrada
            ])
        d = client.get("/training/summary", headers=auth_headers).json()
        assert d["sessions_since_payment"] == 1
        assert d["hours_since_payment"] == 2.0
        assert d["amount_owed"] == 40.0
        # Las diez recientes salen de la misma lista e incluyen también las ya cobradas
        assert len(d["all_recent_sessions"]) == 2

    def test_sin_cobros_cuentan_todas(self, client, auth_headers, mock_requests):
        self._mock(mock_requests, [], [
            {"date": "2026-06-20", "duration_hours": 1.0, "created_at": "2026-06-20T09:00:00Z"},
            {"date": "2026-06-10", "duration_hours": 1.0, "created_at": "2026-06-10T09:00:00Z"},
        ])
        d = client.get("/training/summary", headers=auth_headers).json()
        assert d["sessions_since_payment"] == 2

    def test_una_sola_consulta_de_sesiones(self, client, auth_headers, mock_requests):
        self._mock(mock_requests, [{"date": "2026-06-15", "created_at": "2026-06-15T10:00:00Z"}], [])
        client.get("/training/summary", headers=auth_headers)
        assert len(mock_requests.called("GET", "training_sessions")) == 1


class TestIngestaSimpleEnBloque:
    """M4 en /health/ingest/simple: una lectura y un upsert por lote, no por muestra."""

    URL = "/health/ingest/simple?token=health-token"

    def test_muchas_muestras_son_dos_viajes(self, client, mock_requests):
        muestras = [
            {"metric": f"metrica_{i}", "date": "2026-07-28", "value": i}
            for i in range(25)
        ]
        r = client.post(self.URL, json=muestras)
        assert r.json()["upserted"] == 25
        assert len(mock_requests.called("GET", "health_metrics")) == 1
        assert len(mock_requests.called("POST", "health_metrics")) == 1
        assert not mock_requests.called("PATCH", "health_metrics")

    def test_conserva_la_noche_anulada_a_mano(self, client, mock_requests):
        # El flag `excluded` lo pone el usuario desde el dashboard; una sincronización
        # posterior del Watch no puede borrarlo.
        mock_requests.add("GET", "metric_date=in.", FakeResponse([
            {"metric_date": "2026-07-28", "metric_name": "sleep_analysis",
             "value": 5.0, "extra": {"excluded": True}}
        ]))
        client.post(self.URL, json=[
            {"metric": "sleep_analysis", "date": "2026-07-28", "value": 7.5, "extra": {"deep": 1.2}}
        ])
        fila = mock_requests.called("POST", "health_metrics")[0][2]["json"][0]
        assert fila["extra"]["excluded"] is True
        assert fila["extra"]["deep"] == 1.2      # y no pierde lo que llega nuevo

    def test_un_fallo_del_upsert_no_filtra_el_texto_de_supabase(self, client, mock_requests):
        mock_requests.add("POST", "/rest/v1/health_metrics", FakeResponse(None, 500, "detalle interno"))
        r = client.post(self.URL, json=[{"metric": "heart_rate", "date": "2026-07-28", "value": 60}])
        assert r.status_code == 502
        assert "detalle interno" not in r.text


class TestSincronizacionVacia:
    """Un cuerpo bien formado pero con la estructura equivocada pasaba todas las
    validaciones y salía como `200 {"ok": true, "upserted": 0}`.

    Es el mismo modo de fallo que el 409: el Shortcut enseña la respuesta en pantalla,
    la da por buena y deja de sincronizar sin que nadie se entere. Un `{}` —lo que manda
    "Get contents of URL" si no se le adjunta el fichero del exportador— entra por aquí.
    """

    def test_hae_sin_envoltorio_data_avisa(self, client, mock_requests):
        r = client.post("/health/ingest?token=health-token", json={"metrics": [{"name": "step_count"}]})
        cuerpo = r.json()
        assert cuerpo["ok"] is False
        assert cuerpo["upserted"] == 0
        # Las claves que llegaron son lo único que hace falta para ver que el envoltorio
        # no es el que este endpoint lee.
        assert cuerpo["recibido"]["claves"] == ["metrics"]
        assert cuerpo["recibido"]["claves_de_data"] is None

    def test_hae_con_cuerpo_vacio_avisa(self, client, mock_requests):
        cuerpo = client.post("/health/ingest?token=health-token", json={}).json()
        assert cuerpo["ok"] is False
        assert cuerpo["recibido"]["claves"] == []

    def test_el_resumen_no_lleva_valores_solo_claves(self, client, mock_requests):
        """El resumen acaba en app_logs: claves y tamaños, nunca los datos."""
        cuerpo = client.post("/health/ingest?token=health-token",
                             json={"data": {"otra_cosa": [{"secreto": "no debe salir"}]}}).json()
        assert cuerpo["recibido"]["claves_de_data"] == ["otra_cosa"]
        assert "secreto" not in str(cuerpo)
        assert "no debe salir" not in str(cuerpo)

    def test_una_ingesta_normal_sigue_diciendo_que_va_bien(self, client, mock_requests):
        r = client.post("/health/ingest?token=health-token", json={"data": {"metrics": [
            {"name": "heart_rate", "units": "count/min", "data": [{"date": "2026-07-28 08:00:00", "qty": 60}]}
        ]}})
        assert r.json() == {"ok": True, "upserted": 1}

    def test_un_cero_legitimo_no_se_marca_como_fallo(self, client, mock_requests):
        """Todas las acumulativas ya guardadas con un valor mayor: se reconoce el lote,
        no se escribe nada y eso es correcto. No puede confundirse con no recibir nada."""
        mock_requests.add("GET", "metric_date=in.", FakeResponse([
            {"metric_date": "2026-07-05", "metric_name": "step_count", "value": 9000}
        ]))
        cuerpo = client.post("/health/ingest?token=health-token", json={"data": {"metrics": [
            {"name": "step_count", "units": "count", "data": [{"date": "2026-07-05 08:00:00", "qty": 5000}]}
        ]}}).json()
        assert cuerpo == {"ok": True, "upserted": 0}

    def test_shortcut_sin_muestras_legibles_avisa(self, client, mock_requests):
        cuerpo = client.post("/health/ingest/simple?token=health-token",
                             json=[{"metric": "step_count", "date": "2026-07-28", "value": None}]).json()
        assert cuerpo["ok"] is False
        assert cuerpo["received"] == 0
        assert cuerpo["parse_errors"][0]["reason"] == "value is None"

    def test_shortcut_con_muestras_sigue_diciendo_que_va_bien(self, client, mock_requests):
        cuerpo = client.post("/health/ingest/simple?token=health-token",
                             json=[{"metric": "heart_rate", "date": "2026-07-28", "value": 60}]).json()
        assert cuerpo["ok"] is True
        assert cuerpo["upserted"] == 1


class TestUpsertContraLaRestriccionCorrecta:
    """El upsert debe apuntar a unique(metric_date, metric_name), no a la clave primaria.

    Regresión real: al pasar la ingesta a un upsert en bloque se perdió el PATCH de
    respaldo que resolvía el 409, pero el POST seguía sin `on_conflict`. PostgREST, sin
    ese parámetro, resuelve el conflicto contra la clave primaria (`id`, un uuid nuevo
    en cada inserción, que nunca colisiona), así que la fila repetida llegaba al índice
    único y Supabase devolvía 409 para el LOTE ENTERO. Resultado: el Watch dejó de
    sincronizar mientras los dos endpoints seguían respondiendo 200 {"ok": true}.
    """

    MUESTRA = {"metric": "heart_rate", "date": "2026-07-28", "value": 60}

    @staticmethod
    def _url_del_upsert(mock_requests):
        return mock_requests.called("POST", "health_metrics")[0][1]

    def test_ingest_nombra_la_restriccion(self, client, mock_requests):
        client.post("/health/ingest?token=health-token", json={"data": {"metrics": [
            {"name": "heart_rate", "units": "count/min", "data": [{"date": "2026-07-28 08:00:00", "qty": 60}]}
        ]}})
        assert "on_conflict=metric_date,metric_name" in self._url_del_upsert(mock_requests)

    def test_ingest_simple_nombra_la_restriccion(self, client, mock_requests):
        client.post("/health/ingest/simple?token=health-token", json=[self.MUESTRA])
        assert "on_conflict=metric_date,metric_name" in self._url_del_upsert(mock_requests)

    def test_un_409_no_se_da_por_sincronizado(self, client, mock_requests):
        """Lo que veía el Shortcut: 200 y "ok" con cero filas guardadas."""
        mock_requests.add("POST", "/rest/v1/health_metrics", FakeResponse(None, 409, "duplicate key"))
        r = client.post("/health/ingest/simple?token=health-token", json=[self.MUESTRA])
        assert r.status_code == 502

    def test_un_409_tampoco_en_la_ruta_de_health_auto_export(self, client, mock_requests):
        mock_requests.add("POST", "/rest/v1/health_metrics", FakeResponse(None, 409, "duplicate key"))
        r = client.post("/health/ingest?token=health-token", json={"data": {"metrics": [
            {"name": "heart_rate", "units": "count/min", "data": [{"date": "2026-07-28 08:00:00", "qty": 60}]}
        ]}})
        assert r.status_code == 502
