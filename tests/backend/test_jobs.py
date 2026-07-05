"""Tests de la cola de jobs (Supabase simulado) y heartbeat de agentes."""
from datetime import datetime, timedelta, timezone

from conftest import FakeResponse

JOB_ID = "123e4567-e89b-12d3-a456-426614174000"


class TestCreateJob:
    def test_crea_job(self, client, auth_headers, mock_requests):
        job = {"id": JOB_ID, "dedupe_key": "alud-99", "status": "pending"}
        mock_requests.add("POST", "/rest/v1/jobs", FakeResponse([job], 201))
        r = client.post("/jobs", headers=auth_headers, json={"dedupe_key": "alud-99", "payload": {"url": "x"}})
        assert r.status_code == 200
        assert r.json() == {"ok": True, "job": job}

    def test_dedupe_devuelve_job_existente(self, client, auth_headers, mock_requests):
        existing = {"id": JOB_ID, "dedupe_key": "alud-99", "status": "running"}
        # El upsert con merge-duplicates no devuelve filas si ya existía
        mock_requests.add("POST", "/rest/v1/jobs", FakeResponse([], 201))
        mock_requests.add("GET", "/rest/v1/jobs?dedupe_key=eq.alud-99", FakeResponse([existing]))
        r = client.post("/jobs", headers=auth_headers, json={"dedupe_key": "alud-99"})
        assert r.json() == {"ok": True, "job": existing}

    def test_error_supabase_da_502_sin_detalles(self, client, auth_headers, mock_requests):
        mock_requests.add("POST", "/rest/v1/jobs", FakeResponse(None, 500, "secreto interno"))
        r = client.post("/jobs", headers=auth_headers, json={"dedupe_key": "k"})
        assert r.status_code == 502
        assert "secreto" not in r.text


class TestClaimStartFinish:
    def test_job_id_invalido(self, client, auth_headers):
        r = client.post("/jobs/../etc/claim", headers=auth_headers, json={"worker_id": "w1"})
        assert r.status_code in (404, 422)

    def test_worker_id_invalido(self, client, auth_headers):
        r = client.post(f"/jobs/{JOB_ID}/claim", headers=auth_headers, json={"worker_id": "w1; DROP TABLE"})
        assert r.status_code == 422

    def test_claim_ok(self, client, auth_headers, mock_requests):
        job = {"id": JOB_ID, "status": "claimed", "claimed_by": "w1"}
        mock_requests.add("PATCH", f"id=eq.{JOB_ID}&status=eq.pending", FakeResponse([job]))
        r = client.post(f"/jobs/{JOB_ID}/claim", headers=auth_headers, json={"worker_id": "w1"})
        assert r.json() == {"ok": True, "claimed": True, "job": job}

    def test_claim_ya_reclamado(self, client, auth_headers, mock_requests):
        mock_requests.add("PATCH", "status=eq.pending", FakeResponse([]))
        r = client.post(f"/jobs/{JOB_ID}/claim", headers=auth_headers, json={"worker_id": "w1"})
        assert r.json() == {"ok": False, "claimed": False, "reason": "already_claimed"}

    def test_start_requiere_estado_claimed_del_worker(self, client, auth_headers, mock_requests):
        mock_requests.add("PATCH", "status=eq.claimed", FakeResponse([]))
        r = client.post(f"/jobs/{JOB_ID}/start", headers=auth_headers, json={"worker_id": "w1"})
        assert r.status_code == 409

    def test_start_ok(self, client, auth_headers, mock_requests):
        job = {"id": JOB_ID, "status": "running"}
        mock_requests.add("PATCH", "status=eq.claimed&claimed_by=eq.w1", FakeResponse([job]))
        r = client.post(f"/jobs/{JOB_ID}/start", headers=auth_headers, json={"worker_id": "w1"})
        assert r.json() == {"ok": True, "job": job}

    def test_finish_status_invalido(self, client, auth_headers):
        r = client.post(f"/jobs/{JOB_ID}/finish", headers=auth_headers,
                        json={"worker_id": "w1", "status": "cancelled"})
        assert r.status_code == 400

    def test_finish_ok(self, client, auth_headers, mock_requests):
        job = {"id": JOB_ID, "status": "done"}
        mock_requests.add("PATCH", "status=eq.running&claimed_by=eq.w1", FakeResponse([job]))
        r = client.post(f"/jobs/{JOB_ID}/finish", headers=auth_headers,
                        json={"worker_id": "w1", "status": "done"})
        assert r.json() == {"ok": True, "job": job}


class TestRetry:
    def test_retry_incrementa_intento(self, client, auth_headers, mock_requests):
        mock_requests.add("GET", "status=eq.failed", FakeResponse([{"id": JOB_ID, "attempt": 0}]))
        updated = {"id": JOB_ID, "status": "pending", "attempt": 1}
        mock_requests.add("PATCH", "status=eq.failed", FakeResponse([updated]))
        r = client.post(f"/jobs/{JOB_ID}/retry", headers=auth_headers, json={"worker_id": "w1"})
        assert r.json() == {"ok": True, "job": updated, "max_attempts": 3}
        patched = mock_requests.called("PATCH", "status=eq.failed")[0][2]["json"]
        assert patched["attempt"] == 1
        assert patched["claimed_by"] is None

    def test_retry_respeta_maximo(self, client, auth_headers, mock_requests):
        mock_requests.add("GET", "status=eq.failed", FakeResponse([{"id": JOB_ID, "attempt": 3}]))
        r = client.post(f"/jobs/{JOB_ID}/retry", headers=auth_headers, json={"worker_id": "w1"})
        assert r.status_code == 409
        assert "3" in r.json()["detail"]

    def test_retry_job_no_elegible(self, client, auth_headers, mock_requests):
        mock_requests.add("GET", "status=eq.failed", FakeResponse([]))
        r = client.post(f"/jobs/{JOB_ID}/retry", headers=auth_headers, json={"worker_id": "w1"})
        assert r.status_code == 409


class TestJobEvents:
    def test_crea_evento(self, client, auth_headers, mock_requests):
        ev = {"job_id": JOB_ID, "stage": "browser_open", "message": "ok"}
        mock_requests.add("POST", "/rest/v1/job_events", FakeResponse([ev], 201))
        r = client.post(f"/jobs/{JOB_ID}/events", headers=auth_headers,
                        json={"stage": "browser_open", "message": "ok"})
        assert r.json() == {"ok": True, "event": ev}

    def test_stage_con_caracteres_raros_rechazado(self, client, auth_headers):
        r = client.post(f"/jobs/{JOB_ID}/events", headers=auth_headers,
                        json={"stage": "bad stage!", "message": "x"})
        assert r.status_code == 422

    def test_lista_eventos(self, client, auth_headers, mock_requests):
        evs = [{"job_id": JOB_ID, "stage": "s1", "message": None, "created_at": "2026-07-05T10:00:00Z"}]
        mock_requests.add("GET", "/rest/v1/job_events", FakeResponse(evs))
        r = client.get(f"/jobs/{JOB_ID}/events", headers=auth_headers)
        assert r.json() == {"ok": True, "events": evs}


class TestAgents:
    def test_heartbeat_status_invalido(self, client, auth_headers):
        r = client.post("/agents/heartbeat", headers=auth_headers,
                        json={"agent_id": "pc-mikel", "status": "explotando"})
        assert r.status_code == 400

    def test_heartbeat_ok(self, client, auth_headers, mock_requests):
        agent = {"agent_id": "pc-mikel", "status": "online"}
        mock_requests.add("POST", "/rest/v1/pc_agents", FakeResponse([agent], 201))
        r = client.post("/agents/heartbeat", headers=auth_headers,
                        json={"agent_id": "pc-mikel", "status": "online", "hostname": "PC", "version": "1.1.0"})
        assert r.json() == {"ok": True, "agent": agent}

    def test_agente_desconocido(self, client, auth_headers, mock_requests):
        mock_requests.add("GET", "/rest/v1/pc_agents", FakeResponse([]))
        r = client.get("/agents/pc-mikel", headers=auth_headers)
        assert r.json() == {"exists": False, "status": "offline", "offline": True}

    def test_agente_reciente_online(self, client, auth_headers, mock_requests):
        now = datetime.now(timezone.utc).isoformat()
        mock_requests.add("GET", "/rest/v1/pc_agents", FakeResponse([
            {"agent_id": "pc-mikel", "status": "online", "last_seen_at": now, "hostname": "PC", "version": "1.1.0"}
        ]))
        r = client.get("/agents/pc-mikel", headers=auth_headers)
        data = r.json()
        assert data["offline"] is False
        assert data["status"] == "online"

    def test_agente_silencioso_marcado_offline(self, client, auth_headers, mock_requests):
        old = (datetime.now(timezone.utc) - timedelta(minutes=5)).isoformat()
        mock_requests.add("GET", "/rest/v1/pc_agents", FakeResponse([
            {"agent_id": "pc-mikel", "status": "online", "last_seen_at": old, "hostname": "PC", "version": "1.1.0"}
        ]))
        r = client.get("/agents/pc-mikel", headers=auth_headers)
        data = r.json()
        assert data["offline"] is True
        assert data["status"] == "offline"
        assert data["silence_seconds"] >= 299
