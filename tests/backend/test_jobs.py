"""Tests de la cola de jobs (Supabase simulado) y heartbeat de agentes."""
from datetime import datetime, timedelta, timezone

import main
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
        # Con ignore-duplicates el insert no devuelve filas si la clave ya existía
        mock_requests.add("POST", "/rest/v1/jobs", FakeResponse([], 201))
        mock_requests.add("GET", "/rest/v1/jobs?dedupe_key=eq.alud-99", FakeResponse([existing]))
        r = client.post("/jobs", headers=auth_headers, json={"dedupe_key": "alud-99"})
        assert r.json() == {"ok": True, "job": existing}

    def test_el_insert_nombra_la_restriccion_de_dedupe(self, client, auth_headers, mock_requests):
        """Sin on_conflict, PostgREST resuelve contra la primaria (`id`, uuid nuevo cada
        vez) y la clave repetida acaba en un 409 que este endpoint traducía a 502: el
        camino de "ya existe" no se alcanzaba nunca. Y la resolución tiene que ser
        ignore-duplicates para no pisarle el payload a un job ya en marcha."""
        client.post("/jobs", headers=auth_headers, json={"dedupe_key": "alud-99"})
        _, url, kwargs = mock_requests.called("POST", "/rest/v1/jobs")[0]
        assert "on_conflict=dedupe_key" in url
        assert "resolution=ignore-duplicates" in kwargs["headers"]["Prefer"]

    def test_dedupe_key_con_caracteres_de_url_va_escapada(self, client, auth_headers, mock_requests):
        """La clave lleva el título del evento: '&' y '#' romperían la query de Supabase.

        Sin quote(), el '&' abre un parámetro nuevo y el '#' convierte el resto en
        fragmento (que ni se envía), perdiendo también el &limit=1.
        """
        clave = "entrega-Deber & repaso #2-175"
        existing = {"id": JOB_ID, "dedupe_key": clave, "status": "running"}
        mock_requests.add("POST", "/rest/v1/jobs", FakeResponse([], 201))
        mock_requests.add("GET", "/rest/v1/jobs?dedupe_key=eq.", FakeResponse([existing]))
        r = client.post("/jobs", headers=auth_headers, json={"dedupe_key": clave})
        assert r.json() == {"ok": True, "job": existing}

        url = mock_requests.called("GET", "/rest/v1/jobs")[0][1]
        assert "%26" in url and "%23" in url, f"clave sin escapar: {url}"
        assert url.endswith("&limit=1")

    def test_error_supabase_da_502_sin_detalles(self, client, auth_headers, mock_requests):
        mock_requests.add("POST", "/rest/v1/jobs", FakeResponse(None, 500, "secreto interno"))
        r = client.post("/jobs", headers=auth_headers, json={"dedupe_key": "k"})
        assert r.status_code == 502
        assert "secreto" not in r.text


class TestPendingJob:
    """El agente consulta esto en vez de llamar a Supabase con la service_role key
    directamente (A1): esta es la única llamada que se la obligaba a tener."""

    def test_requiere_jwt(self, client):
        assert client.get("/jobs/pending").status_code in (401, 403)

    def test_devuelve_el_mas_reciente(self, client, auth_headers, mock_requests):
        job = {"id": JOB_ID, "status": "pending"}
        mock_requests.add("GET", "/rest/v1/jobs", FakeResponse([job]))
        r = client.get("/jobs/pending", headers=auth_headers)
        assert r.status_code == 200
        assert r.json() == {"ok": True, "job": job}

    def test_sin_pendientes_devuelve_null(self, client, auth_headers, mock_requests):
        mock_requests.add("GET", "/rest/v1/jobs", FakeResponse([]))
        r = client.get("/jobs/pending", headers=auth_headers)
        assert r.json() == {"ok": True, "job": None}

    def test_filtra_por_pendiente_y_ultima_hora(self, client, auth_headers, mock_requests):
        mock_requests.add("GET", "/rest/v1/jobs", FakeResponse([]))
        client.get("/jobs/pending", headers=auth_headers)
        url = mock_requests.called("GET", "/rest/v1/jobs")[0][1]
        assert "status=eq.pending" in url
        assert "created_at=gt." in url
        assert "limit=1" in url

    def test_el_corte_no_lleva_un_mas_en_la_query(self, client, auth_headers, mock_requests):
        """El "+" de "+00:00" es un espacio en una query string: PostgREST recibía
        "...T05:10:01 00:00" y devolvía 400 (22007), así que /jobs/pending era un 502
        fijo y el agente no podía recoger ningún job."""
        mock_requests.add("GET", "/rest/v1/jobs", FakeResponse([]))
        client.get("/jobs/pending", headers=auth_headers)
        url = mock_requests.called("GET", "/rest/v1/jobs")[0][1]
        corte = url.split("created_at=gt.")[1].split("&")[0]
        assert "+" not in corte
        assert corte.endswith("Z")

    def test_error_supabase_da_502_sin_detalles(self, client, auth_headers, mock_requests):
        mock_requests.add("GET", "/rest/v1/jobs", FakeResponse(None, 500, "secreto interno"))
        r = client.get("/jobs/pending", headers=auth_headers)
        assert r.status_code == 502
        assert "secreto" not in r.text


class TestAuthAgente:
    """El agente PC se autentica con AGENT_TOKEN, un token de servicio que no caduca.

    Antes llevaba el JWT del dashboard copiado a mano en su `.env`. Ese JWT dura 30
    días: cuando caducó, `/jobs/pending` empezó a devolver 401 y el agente —que no
    distinguía un fallo de "no hay nada que hacer"— se cerró en silencio en cada
    arranque durante meses. Mismo razonamiento que BRIEF_TOKEN.
    """

    AGENTE = {"Authorization": "Bearer agent-token"}

    def test_token_de_servicio_vale(self, client, mock_requests):
        job = {"id": JOB_ID, "status": "pending"}
        mock_requests.add("GET", "/rest/v1/jobs", FakeResponse([job]))
        r = client.get("/jobs/pending", headers=self.AGENTE)
        assert r.status_code == 200
        assert r.json() == {"ok": True, "job": job}

    def test_tambien_por_cabecera_x_auth_token(self, client, mock_requests):
        mock_requests.add("GET", "/rest/v1/jobs", FakeResponse([]))
        r = client.get("/jobs/pending", headers={"X-Auth-Token": "agent-token"})
        assert r.status_code == 200

    def test_token_equivocado_da_401(self, client):
        r = client.get("/jobs/pending", headers={"Authorization": "Bearer no-soy-el-agente"})
        assert r.status_code == 401

    def test_sin_token_da_401(self, client):
        assert client.get("/jobs/pending").status_code == 401

    def test_no_se_acepta_por_query_string(self, client):
        """El cliente es código propio, así que no hay integración desplegada que migrar
        —al contrario que HA o los Shortcuts— y un token en la query acaba en los logs
        de acceso del proveedor."""
        r = client.get("/jobs/pending?token=agent-token")
        assert r.status_code == 401

    def test_jwt_caducado_da_401(self, client):
        """El bug real, como test: el token del agente llevaba meses expirado."""
        from jose import jwt

        caducado = jwt.encode(
            {"exp": datetime.now(timezone.utc) - timedelta(days=1)},
            main.SECRET_KEY,
            algorithm=main.ALGORITHM,
        )
        r = client.get("/jobs/pending", headers={"Authorization": f"Bearer {caducado}"})
        assert r.status_code == 401

    def test_el_jwt_del_dashboard_sigue_valiendo(self, client, auth_headers, mock_requests):
        """El dashboard consulta estos endpoints con la sesión del usuario, y una
        instancia sin AGENT_TOKEN configurado tiene que seguir funcionando."""
        mock_requests.add("GET", "/rest/v1/jobs", FakeResponse([]))
        assert client.get("/jobs/pending", headers=auth_headers).status_code == 200

    def test_cubre_todo_lo_que_usa_el_agente(self, client, mock_requests):
        """Los seis endpoints del ciclo de vida de un job. Si uno se queda fuera, el
        agente muere a mitad de trabajo: reclama el job y no puede cerrarlo."""
        mock_requests.add("PATCH", "/rest/v1/jobs", FakeResponse([{"id": JOB_ID}]))
        mock_requests.add("POST", "/rest/v1/job_events", FakeResponse([{"stage": "s"}], 201))
        mock_requests.add("POST", "/rest/v1/pc_agents", FakeResponse([{"agent_id": "pc-mikel"}], 201))
        mock_requests.add("GET", "/rest/v1/jobs", FakeResponse([]))

        llamadas = [
            ("GET",  "/jobs/pending", None),
            ("POST", f"/jobs/{JOB_ID}/claim",  {"worker_id": "w1"}),
            ("POST", f"/jobs/{JOB_ID}/start",  {"worker_id": "w1"}),
            ("POST", f"/jobs/{JOB_ID}/finish", {"worker_id": "w1", "status": "done"}),
            ("POST", f"/jobs/{JOB_ID}/events", {"stage": "job_done", "message": "ok"}),
            ("POST", "/agents/heartbeat",      {"agent_id": "pc-mikel", "status": "online"}),
        ]
        for metodo, ruta, cuerpo in llamadas:
            r = client.request(metodo, ruta, headers=self.AGENTE, json=cuerpo)
            assert r.status_code != 401, f"{metodo} {ruta} rechaza el token del agente"

    def test_no_abre_el_resto_de_la_api(self, client):
        """El alcance del token es la cola de jobs, no la sesión del usuario: vive en un
        `.env` de un PC de escritorio que arranca solo y sin nadie delante."""
        assert client.post("/jobs", headers=self.AGENTE,
                           json={"dedupe_key": "k"}).status_code == 401
        assert client.get("/health/metrics", headers=self.AGENTE).status_code == 401
        assert client.get(f"/jobs/{JOB_ID}/events", headers=self.AGENTE).status_code in (401, 403)


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
