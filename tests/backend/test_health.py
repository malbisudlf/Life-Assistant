"""Tests de ingesta de salud (Apple Watch / iOS Shortcuts) y entrenamiento."""
import json

from conftest import FakeResponse


class TestHealthIngestAuth:
    def test_ingest_sin_token(self, client):
        assert client.post("/health/ingest", json={}).status_code == 403

    def test_ingest_simple_sin_token(self, client):
        assert client.post("/health/ingest/simple", json=[]).status_code == 403


class TestHealthIngest:
    URL = "/health/ingest?token=health-token"

    def test_metrica_normal_se_inserta(self, client, mock_requests):
        r = client.post(self.URL, json={"data": {"metrics": [
            {"name": "weight_body_mass", "units": "kg", "data": [{"date": "2026-07-05 08:00:00", "qty": 68.5}]}
        ]}})
        assert r.status_code == 200
        assert r.json()["upserted"] == 1
        payload = mock_requests.called("POST", "health_metrics")[0][2]["json"]
        assert payload["metric_date"] == "2026-07-05"
        assert payload["metric_name"] == "weight_body_mass"
        assert payload["value"] == 68.5

    def test_acumulativa_no_pisa_valor_mayor_existente(self, client, mock_requests):
        mock_requests.add("GET", "metric_name=eq.step_count", FakeResponse([{"value": 9000}]))
        r = client.post(self.URL, json={"data": {"metrics": [
            {"name": "step_count", "units": "count", "data": [{"date": "2026-07-05 08:00:00", "qty": 5000}]}
        ]}})
        assert r.json()["upserted"] == 0
        assert not mock_requests.called("POST", "health_metrics")
        assert not mock_requests.called("PATCH", "health_metrics")

    def test_acumulativa_actualiza_si_es_mayor(self, client, mock_requests):
        mock_requests.add("GET", "metric_name=eq.step_count", FakeResponse([{"value": 3000}]))
        r = client.post(self.URL, json={"data": {"metrics": [
            {"name": "step_count", "units": "count", "data": [{"date": "2026-07-05 08:00:00", "qty": 5000}]}
        ]}})
        assert r.json()["upserted"] == 1
        patched = mock_requests.called("PATCH", "health_metrics")[0][2]["json"]
        assert patched["value"] == 5000

    def test_energia_kj_se_convierte_a_kcal(self, client, mock_requests):
        mock_requests.add("GET", "metric_name=eq.active_energy", FakeResponse([]))
        r = client.post(self.URL, json={"data": {"metrics": [
            {"name": "active_energy", "units": "kJ", "data": [{"date": "2026-07-05 08:00:00", "qty": 4184}]}
        ]}})
        assert r.json()["upserted"] == 1
        payload = mock_requests.called("POST", "health_metrics")[0][2]["json"]
        assert payload["value"] == 1000.0
        assert payload["unit"] == "kcal"

    def test_sleep_guarda_hora_de_inicio(self, client, mock_requests):
        r = client.post(self.URL, json={"data": {"metrics": [
            {"name": "sleep_analysis", "units": "hr",
             "data": [{"date": "2026-07-04 23:45:00", "totalSleep": 7.8, "deep": 1.2}]}
        ]}})
        assert r.json()["upserted"] == 1
        payload = mock_requests.called("POST", "health_metrics")[0][2]["json"]
        assert payload["value"] == 7.8
        assert payload["extra"]["sleep_start"] == "23:45"

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
        mock_requests.add("GET", "metric_name=eq.step_count", FakeResponse([{"value": 9000}]))
        r = client.post(self.URL, json=[{"metric": "step_count", "date": "2026-07-05", "value": 100}])
        body = r.json()
        assert body["upserted"] == 0
        assert body["skipped"]


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
        mock_requests.add("GET", "training_sessions", FakeResponse([
            {"date": "2026-07-01", "duration_hours": 1.5},
            {"date": "2026-06-20", "duration_hours": 1.0},
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
