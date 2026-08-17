"""Tests de ingesta de salud (Apple Watch / iOS Shortcuts) y entrenamiento."""
import json
import logging

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

    def test_avg_con_mayuscula_tambien_cuenta(self, client, mock_requests):
        """heart_rate llega como rango diario: "Avg"/"Min"/"Max", con mayúscula inicial.

        Solo se buscaba "avg" en minúscula, así que la fila se guardaba con value=None
        mientras el promedio estaba entero en `extra`, a la vista y sin usar por nadie.
        """
        r = client.post(self.URL, json={"data": {"metrics": [
            {"name": "heart_rate", "units": "count/min",
             "data": [{"date": "2026-08-05 00:00:00", "Avg": 64.7, "Min": 47, "Max": 114}]}
        ]}})
        assert r.status_code == 200
        fila = self._filas(mock_requests)[0]
        assert fila["value"] == 64.7, "el promedio del día es el valor de la métrica"
        assert fila["extra"]["Max"] == 114, "el rango completo se conserva en extra"

    def test_avg_en_minuscula_sigue_funcionando(self, client, mock_requests):
        r = client.post(self.URL, json={"data": {"metrics": [
            {"name": "heart_rate", "units": "count/min",
             "data": [{"date": "2026-08-05 00:00:00", "avg": 61.0}]}
        ]}})
        assert self._filas(mock_requests)[0]["value"] == 61.0

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

    def test_dice_que_dias_estuvo_puesto_el_reloj(self, client, auth_headers, mock_requests):
        """El frontend no puede repetir la clasificación de métricas: se le manda hecha,
        junto con la fuente de cada una, para que no haya dos listas que se
        desincronicen a la primera métrica nueva."""
        mock_requests.add("GET", "health_metrics", FakeResponse([
            {"metric_name": "step_count", "metric_date": "2026-07-04", "value": 9000, "unit": "count", "extra": {}},
            {"metric_name": "step_count", "metric_date": "2026-07-05", "value": 9500, "unit": "count", "extra": {}},
            {"metric_name": "heart_rate", "metric_date": "2026-07-05", "value": 70, "unit": "bpm", "extra": {}},
            {"metric_name": "sleep_analysis", "metric_date": "2026-07-05", "value": 7.2, "unit": "h", "extra": {}},
        ]))
        reloj = client.get("/health/metrics?days=7", headers=auth_headers).json()["reloj"]
        assert reloj["dias"] == {"2026-07-04": "sin_reloj", "2026-07-05": "ambos"}
        assert reloj["fuentes"]["heart_rate"] == "dia"
        assert reloj["fuentes"]["sleep_analysis"] == "noche"
        assert "step_count" not in reloj["fuentes"], "los pasos no dependen del reloj"

    def test_un_cero_del_atajo_no_da_el_dia_por_llevado(self, client, auth_headers, mock_requests):
        mock_requests.add("GET", "health_metrics", FakeResponse([
            {"metric_name": "heart_rate_variability", "metric_date": "2026-07-05", "value": 0, "unit": "ms", "extra": {}},
            {"metric_name": "step_count", "metric_date": "2026-07-05", "value": 9000, "unit": "count", "extra": {}},
        ]))
        reloj = client.get("/health/metrics?days=7", headers=auth_headers).json()["reloj"]
        assert reloj["dias"]["2026-07-05"] == "sin_reloj"

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

    def test_una_lista_de_lotes_se_acepta(self, client, mock_requests):
        """Con "Batch requests" el exportador manda una lista de lotes, no un lote.

        Daba 400 y se perdía la sincronización entera por el envoltorio, no por los
        datos: el endpoint llevaba semanas rechazando cada envío del Watch.
        """
        mock_requests.add("GET", "/rest/v1/health_metrics", FakeResponse([]))
        mock_requests.add("POST", "/rest/v1/health_metrics", FakeResponse(None, 201))
        r = client.post("/health/ingest?token=health-token", json=[
            {"data": {"metrics": [{"name": "step_count", "units": "count",
                                   "data": [{"date": "2026-08-05 00:00:00 +0200", "qty": 9000}]}],
                      "workouts": []}},
            {"data": {"metrics": [{"name": "resting_heart_rate", "units": "bpm",
                                   "data": [{"date": "2026-08-05 00:00:00 +0200", "qty": 53}]}],
                      "workouts": []}},
        ])
        assert r.status_code == 200, r.text
        cuerpo = r.json()
        assert cuerpo["ok"] is True and cuerpo["upserted"] == 2

    def test_una_lista_vacia_no_es_un_error(self, client, mock_requests):
        """"No tengo nada que exportar" no puede salir como cuerpo ininteligible."""
        r = client.post("/health/ingest?token=health-token", json=[{"data": {"metrics": [], "workouts": []}}])
        assert r.status_code == 200 and r.json()["vacio"] is True

    def test_una_lista_de_cualquier_cosa_sigue_siendo_400(self, client, mock_requests):
        assert client.post("/health/ingest?token=health-token", json=[1, 2, 3]).status_code == 400

    def test_el_400_deja_rastro_en_el_registro(self, client, mock_requests, caplog):
        """El detalle solo lo veía el cliente, que es una app del móvil y no lo enseña:
        en el registro constaba un 400 pelado y no había forma de saber qué llegaba."""
        with caplog.at_level("WARNING"):
            assert client.post("/health/ingest?token=health-token",
                               content=b"no soy json", headers={"Content-Type": "application/json"}).status_code == 400
        registrado = "\n".join(r.getMessage() for r in caplog.records)
        assert "cuerpo no reconocido" in registrado
        assert "no-json" in registrado

    def test_el_400_dice_quien_lo_mandó(self, client, mock_requests, caplog):
        """Saber que llega basura no sirve si no se sabe cuál de los clientes la manda.

        Con Health Auto Export y varios Atajos apuntando al mismo endpoint con el mismo
        token, "400 en /health/ingest" no dice qué hay que abrir para arreglarlo.
        """
        with caplog.at_level("WARNING"):
            client.post("/health/ingest?token=health-token", content=b"no soy json",
                        headers={"Content-Type": "application/json",
                                 "User-Agent": "HealthAutoExport/8.2"})
        assert "HealthAutoExport/8.2" in "\n".join(r.getMessage() for r in caplog.records)

    def test_un_cuerpo_vacio_no_se_confunde_con_uno_ininteligible(
            self, client, mock_requests, caplog):
        """0 bytes y "otro envoltorio" llevan a sitios opuestos y salían igual.

        Un envoltorio desconocido se arregla en el backend; un cuerpo vacío es un cliente
        que no llegó a construir la petición y no hay tolerancia del servidor que lo
        arregle, porque no ha llegado ni un dato que interpretar.
        """
        with caplog.at_level("WARNING"):
            r = client.post("/health/ingest?token=health-token", content=b"",
                            headers={"Content-Type": "application/json"})
        assert r.status_code == 400
        registrado = "\n".join(rec.getMessage() for rec in caplog.records)
        assert "VACÍO" in registrado
        assert "'bytes': 0" in registrado

    def test_el_atajo_tambien_deja_rastro_al_rechazar(self, client, mock_requests, caplog):
        """El 400 de /simple no dejaba más rastro que el "→ 400" del middleware, que es
        justo lo que hizo durar semanas el del envoltorio en /health/ingest."""
        with caplog.at_level("WARNING"):
            r = client.post("/health/ingest/simple?token=health-token", content=b"",
                            headers={"Content-Type": "application/json",
                                     "User-Agent": "Shortcuts/2600.1"})
        assert r.status_code == 400
        registrado = "\n".join(rec.getMessage() for rec in caplog.records)
        assert "VACÍO" in registrado and "Shortcuts/2600.1" in registrado

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


class TestLoteVacioNoEsUnFallo:
    """Health Auto Export manda lotes vacíos varias veces al día cuando el Watch no ha
    volcado nada nuevo: es su funcionamiento normal, no una sincronización rota.

    Salían como WARNING con `ok: false` igual que un envoltorio desconocido, y 49 en
    una semana tapaban en `app_logs` los avisos que sí importan. Lo que NO puede pasar
    es que esto debilite la protección del 409: los tests de abajo fijan la frontera.
    """

    def test_data_vacio_responde_ok(self, client, mock_requests):
        # {"data": {}} — lo que llegaba de verdad, 21 bytes.
        cuerpo = client.post("/health/ingest?token=health-token", json={"data": {}}).json()
        assert cuerpo["ok"] is True
        assert cuerpo["vacio"] is True
        assert cuerpo["upserted"] == 0

    def test_metrics_vacio_responde_ok(self, client, mock_requests):
        # {"data": {"metrics": []}} — el otro cuerpo real, 45 bytes.
        cuerpo = client.post("/health/ingest?token=health-token", json={"data": {"metrics": []}}).json()
        assert cuerpo["ok"] is True
        assert cuerpo["vacio"] is True

    def test_un_lote_vacio_no_se_registra_como_aviso(self, client, mock_requests, caplog):
        """Va a INFO justamente para que no se persista en app_logs (WARNING+)."""
        with caplog.at_level(logging.INFO, logger="main"):
            client.post("/health/ingest?token=health-token", json={"data": {}})
        assert not [r for r in caplog.records if r.levelno >= logging.WARNING]
        assert any("lote vacío" in r.message for r in caplog.records)

    # ── La frontera: lo de abajo SIGUE siendo un fallo ────────────────────────

    def test_cuerpo_vacio_del_todo_sigue_avisando(self, client, mock_requests, caplog):
        """`{}` es lo que manda "Get contents of URL" sin adjuntar el fichero: no tiene
        el envoltorio `data`, así que no es un lote vacío sino otra cosa."""
        with caplog.at_level(logging.INFO, logger="main"):
            cuerpo = client.post("/health/ingest?token=health-token", json={}).json()
        assert cuerpo["ok"] is False
        assert [r for r in caplog.records if r.levelno >= logging.WARNING]

    def test_envoltorio_desconocido_sigue_avisando(self, client, mock_requests):
        cuerpo = client.post("/health/ingest?token=health-token",
                             json={"data": {"otra_cosa": []}}).json()
        assert cuerpo["ok"] is False

    def test_muestras_que_no_se_reconocen_siguen_avisando(self, client, mock_requests):
        """Llegaron datos y no se entendió ninguno: eso no es un lote vacío."""
        cuerpo = client.post("/health/ingest?token=health-token", json={"data": {"metrics": [
            {"name": "metrica_inventada", "units": "x", "data": [{"sin_fecha": 1}]}
        ]}}).json()
        assert cuerpo["ok"] is False

    def test_la_funcion_distingue_los_casos(self):
        assert main._lote_vacio({"data": {}}) is True
        assert main._lote_vacio({"data": {"metrics": [], "workouts": []}}) is True
        assert main._lote_vacio({}) is False
        assert main._lote_vacio({"metrics": []}) is False
        assert main._lote_vacio({"data": {"otra": 1}}) is False
        assert main._lote_vacio({"data": {"metrics": [{"name": "x"}]}}) is False
        assert main._lote_vacio([]) is False


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


class TestCeroQueNoEsUnaMedida:
    """Un 0 en una métrica de sensor es "no se midió", y no puede escribirse.

    El Atajo de iOS manda el campo vacío cuando su "Find Health Samples" no encuentra
    nada —cada día que el reloj se queda en el cajón—, eso se convertía en un 0 y el 0
    se escribía en la tabla. El daño no es ocupar sitio: es que el upsert resuelve por
    metric_date+metric_name, así que ese 0 pisa la medida del primer día que sí la haya
    si el Atajo corre después. Las acumulativas nunca corrieron el riesgo, porque solo
    se pisan si el valor nuevo es mayor.
    """

    HAE    = "/health/ingest?token=health-token"
    SIMPLE = "/health/ingest/simple?token=health-token"

    @staticmethod
    def _filas(mock_requests):
        for _, _, kw in mock_requests.called("POST", "health_metrics"):
            if isinstance(kw.get("json"), list):
                return kw["json"]
        return []

    def test_el_hueco_del_shortcut_ya_no_se_guarda_como_cero(self, client, mock_requests):
        r = client.post(self.SIMPLE, json=[
            {"metric": "heart_rate_variability", "date": "2026-08-07", "value": ""}
        ])
        cuerpo = r.json()
        assert cuerpo["received"] == 0
        assert cuerpo["upserted"] == 0
        assert not mock_requests.called("POST", "health_metrics"), "no se escribe nada"
        assert "vacío" in cuerpo["parse_errors"][0]["reason"]

    def test_un_cero_explicito_tampoco_pisa_la_medida(self, client, mock_requests):
        r = client.post(self.SIMPLE, json=[
            {"metric": "resting_heart_rate", "date": "2026-08-07", "value": 0}
        ])
        assert r.json()["upserted"] == 0
        assert any("sin medida" in s for s in r.json()["skipped"])
        assert not mock_requests.called("POST", "health_metrics")

    def test_lo_que_si_trae_medida_se_guarda_igual(self, client, mock_requests):
        """El filtro es por muestra: un hueco no puede llevarse por delante el lote."""
        r = client.post(self.SIMPLE, json=[
            {"metric": "heart_rate_variability", "date": "2026-08-07", "value": 0},
            {"metric": "resting_heart_rate",     "date": "2026-08-07", "value": 51},
        ])
        assert r.json()["upserted"] == 1
        assert [f["metric_name"] for f in self._filas(mock_requests)] == ["resting_heart_rate"]

    def test_en_health_auto_export_vale_el_mismo_criterio(self, client, mock_requests):
        r = client.post(self.HAE, json={"data": {"metrics": [
            {"name": "respiratory_rate", "units": "count/min",
             "data": [{"date": "2026-08-07 03:00:00", "qty": 0}]},
            {"name": "vo2_max", "units": "ml/kg/min",
             "data": [{"date": "2026-08-07 03:00:00", "qty": 47.5}]},
        ]}})
        assert r.status_code == 200
        assert [f["metric_name"] for f in self._filas(mock_requests)] == ["vo2_max"]

    def test_el_cero_de_una_acumulativa_si_es_un_dato(self, client, mock_requests):
        """Un día de 0 pisos o 0 pasos ocurrió y tiene que bajar la media."""
        client.post(self.SIMPLE, json=[
            {"metric": "flights_climbed", "date": "2026-08-07", "value": 0},
            {"metric": "step_count",      "date": "2026-08-07", "value": 0},
        ])
        assert {f["metric_name"] for f in self._filas(mock_requests)} == {"flights_climbed", "step_count"}

    def test_una_noche_con_las_fases_en_extra_no_es_un_hueco(self, client, mock_requests):
        """`value` puede llegar a 0 con la noche entera dentro de `extra`: ahí sí se
        midió, y `_horas_sueno` la reconstruye desde las fases."""
        client.post(self.SIMPLE, json=[
            {"metric": "sleep_analysis", "date": "2026-08-07", "value": 0,
             "extra": {"deep": 1.2, "rem": 1.5, "core": 4.1}},
        ])
        assert self._filas(mock_requests)[0]["metric_name"] == "sleep_analysis"

    def test_una_noche_a_cero_y_sin_fases_no_se_guarda(self, client, mock_requests):
        client.post(self.SIMPLE, json=[
            {"metric": "sleep_analysis", "date": "2026-08-07", "value": 0, "extra": {}},
        ])
        assert not mock_requests.called("POST", "health_metrics")

    def test_un_value_nulo_se_conserva_porque_la_medida_puede_estar_en_extra(self, client, mock_requests):
        """heart_rate llega como rango y su promedio viene con mayúscula ("Avg"): la
        fila con value=None sigue guardándose porque el dato va dentro de extra."""
        client.post(self.HAE, json={"data": {"metrics": [
            {"name": "heart_rate", "units": "count/min",
             "data": [{"date": "2026-08-07 00:00:00", "Máximo": 120}]},
        ]}})
        fila = self._filas(mock_requests)[0]
        assert fila["value"] is None
        assert fila["extra"]["Máximo"] == 120

    def test_un_envio_entero_de_huecos_queda_registrado(self, client, mock_requests, caplog):
        """Que se descarte una muestra suelta es normal; que no llegue NI UNA con
        medida es que el Atajo está roto, y eso no puede pasar en silencio."""
        with caplog.at_level(logging.WARNING):
            client.post(self.SIMPLE, json=[
                {"metric": "heart_rate_variability", "date": "2026-08-07", "value": 0},
                {"metric": "resting_heart_rate",     "date": "2026-08-07", "value": 0},
            ])
        assert "0 sin medida" in caplog.text
        assert "heart_rate_variability" in caplog.text

    def test_no_se_desincroniza_del_criterio_del_resumen(self):
        """`METRICAS_SIN_MEDIDA_EN_CERO` (por nombre en la tabla) y la columna
        `cero_es_dato` de `_BRIEF_METRICAS` (por clave de salida) dicen lo mismo con
        dos formas distintas. Si divergen, el resumen descarta ceros que la ingesta
        guardó, o al revés."""
        for _, nombres, _, cero_es_dato, etiqueta in main._BRIEF_METRICAS:
            for nombre in nombres:
                sin_medida = nombre in main.METRICAS_SIN_MEDIDA_EN_CERO
                assert sin_medida == (not cero_es_dato), (
                    f"{etiqueta} ({nombre}): la ingesta y el resumen no tratan igual el 0"
                )


class TestFuenteDeCadaFila:
    """Las dos ingestas escriben en la MISMA tabla, y hasta ahora sin dejar firma.

    Por eso "¿cuál de las dos ha dejado de correr?" había que deducirlo a ojo cada vez
    que algo iba mal — el mismo trabajo manual que ya costó semanas en el 409 y en el
    400 del envoltorio.
    """

    HAE    = "/health/ingest?token=health-token"
    SIMPLE = "/health/ingest/simple?token=health-token"

    @staticmethod
    def _filas(mock_requests):
        for _, _, kw in mock_requests.called("POST", "health_metrics"):
            if isinstance(kw.get("json"), list):
                return kw["json"]
        return []

    def test_health_auto_export_firma_lo_que_escribe(self, client, mock_requests):
        client.post(self.HAE, json={"data": {"metrics": [
            {"name": "step_count", "units": "count",
             "data": [{"date": "2026-08-07 23:00:00", "qty": 9000}]}
        ]}})
        assert self._filas(mock_requests)[0]["fuente"] == main.FUENTE_AUTO_EXPORT

    def test_el_atajo_firma_lo_suyo(self, client, mock_requests):
        client.post(self.SIMPLE, json=[
            {"metric": "resting_heart_rate", "date": "2026-08-07", "value": 52}
        ])
        assert self._filas(mock_requests)[0]["fuente"] == main.FUENTE_ATAJO

    def test_sin_fuente_no_se_escribe_la_columna(self, mock_requests):
        """Escribir `None` en el upsert BORRARÍA la atribución que ya tuviera la fila:
        no saber quién escribe no puede desacreditar a quien escribió antes."""
        mock_requests.add("POST", "health_metrics", FakeResponse([], 201))
        main._guardar_metricas({("2026-08-07", "step_count"): {
            "metric_date": "2026-08-07", "metric_name": "step_count",
            "value": 9000, "unit": "count", "extra": {}}})
        assert "fuente" not in self._filas(mock_requests)[0]


class TestDiagnosticoDeDatos:
    """Lo que solo se veía mirando la tabla en crudo: qué falta y de quién se ha dejado
    de saber. La diferencia con `last_sync` es la de siempre — aquel dice si llega ALGO.
    """

    def _tabla(self, mock_requests, filas):
        mock_requests.add("GET", "/rest/v1/health_metrics", FakeResponse(filas))

    @staticmethod
    def _fila(nombre, fecha, valor=1, fuente=None, creado="2026-08-08T10:00:00+00:00"):
        f = {"metric_date": fecha, "metric_name": nombre, "value": valor,
             "extra": {}, "created_at": creado}
        if fuente:
            f["fuente"] = fuente
        return f

    def test_sin_token_no_se_diagnostica_nada(self, client):
        """Es un endpoint de USUARIO (JWT), no de servicio: lo consume el panel, y lo
        que enseña —qué falta y desde cuándo— no tiene por qué salir de la sesión."""
        assert client.get("/health/diagnostico").status_code == 401

    def test_cuenta_los_huecos_desde_el_primer_dia_medido(self, client, mock_requests,
                                                          auth_headers, monkeypatch):
        """Antes de empezar a medir no hay nada que echar en falta: un hueco es un día
        sin medida ENTRE medidas, no la prehistoria de la métrica."""
        hoy = main.datetime.now(main.LOCAL_TZ).date()
        dia = lambda n: (hoy - main.timedelta(days=n)).isoformat()   # noqa: E731
        self._tabla(mock_requests, [
            self._fila("resting_heart_rate", dia(4)),
            self._fila("resting_heart_rate", dia(1)),   # faltan el 3 y el 2
        ])
        r = client.get("/health/diagnostico?dias=10", headers=auth_headers)
        assert r.status_code == 200
        m = r.json()["metricas"]["resting_heart_rate"]
        assert m["ultimo_dia"] == dia(1)
        assert m["dias_atras"] == 1
        assert m["dias_con_dato"] == 2
        assert m["huecos"] == 3        # los dos de en medio y hoy

    def test_una_fila_de_relleno_no_tapa_un_hueco(self, client, mock_requests, auth_headers):
        """Los ceros que manda el Atajo los días sin reloj son filas, no medidas: la
        misma regla que ya rige la detección de uso del reloj."""
        hoy = main.datetime.now(main.LOCAL_TZ).date().isoformat()
        self._tabla(mock_requests, [self._fila("heart_rate_variability", hoy, valor=0)])
        m = client.get("/health/diagnostico", headers=auth_headers).json()["metricas"]
        assert m["heart_rate_variability"]["dias_con_dato"] == 0
        assert m["heart_rate_variability"]["filas_sin_medida"] == 1

    def test_dice_quien_escribio_por_ultima_vez(self, client, mock_requests, auth_headers):
        hoy = main.datetime.now(main.LOCAL_TZ).date().isoformat()
        self._tabla(mock_requests, [
            self._fila("step_count", hoy, fuente=main.FUENTE_AUTO_EXPORT,
                       creado="2026-08-08T09:00:00+00:00"),
            self._fila("resting_heart_rate", hoy, fuente=main.FUENTE_ATAJO,
                       creado="2026-08-08T11:00:00+00:00"),
            self._fila("flights_climbed", hoy, fuente=main.FUENTE_AUTO_EXPORT,
                       creado="2026-08-08T07:00:00+00:00"),
        ])
        cuerpo = client.get("/health/diagnostico", headers=auth_headers).json()
        assert cuerpo["fuentes"][main.FUENTE_AUTO_EXPORT]["ultima_escritura"] \
            == "2026-08-08T09:00:00+00:00"
        assert cuerpo["fuentes"][main.FUENTE_ATAJO]["ultima_escritura"] \
            == "2026-08-08T11:00:00+00:00"
        assert cuerpo["metricas"]["step_count"]["fuentes"] == [main.FUENTE_AUTO_EXPORT]

    def test_las_filas_viejas_se_cuentan_pero_no_se_atribuyen(self, client, mock_requests,
                                                              auth_headers):
        """Rellenar la fuente de lo que ya estaba guardado sería inventarse un dato."""
        hoy = main.datetime.now(main.LOCAL_TZ).date().isoformat()
        self._tabla(mock_requests, [self._fila("step_count", hoy)])
        cuerpo = client.get("/health/diagnostico", headers=auth_headers).json()
        assert cuerpo["sin_fuente"] == 1
        assert cuerpo["fuentes"] == {}
        assert cuerpo["metricas"]["step_count"]["fuentes"] is None

    def test_una_fecha_futura_no_cuenta(self, client, mock_requests, auth_headers):
        """Hay filas fechadas en diciembre por el bug del Avg: entrarían como "el último
        día con dato" y taparían justo el silencio que se viene a mirar."""
        manana = (main.datetime.now(main.LOCAL_TZ).date()
                  + main.timedelta(days=120)).isoformat()
        self._tabla(mock_requests, [self._fila("step_count", manana)])
        assert client.get("/health/diagnostico",
                          headers=auth_headers).json()["metricas"] == {}

    def test_la_ventana_tiene_limites(self, client, auth_headers):
        assert client.get("/health/diagnostico?dias=0", headers=auth_headers).status_code == 400
        assert client.get("/health/diagnostico?dias=900", headers=auth_headers).status_code == 400

    def test_un_fallo_de_supabase_no_filtra_su_texto(self, client, mock_requests, auth_headers):
        self._tabla(mock_requests, [])
        mock_requests.routes.insert(0, ("GET", "/rest/v1/health_metrics",
                                        FakeResponse(None, 500, "column x does not exist")))
        r = client.get("/health/diagnostico", headers=auth_headers)
        assert r.status_code == 502
        assert "column x" not in r.text
