"""Tests de los arreglos de la revisión de seguridad: C2, A3 y A4.

- C2: `alud_url` sale del cuerpo de un evento de Outlook y acaba en `page.goto()` del
  agente, en un navegador con la sesión de Alud iniciada. Solo pasan https y hosts de
  la lista blanca, y se comprueba tanto al extraerla como al dar de alta el job.
- A3: `event_id` y `calendar_id` se interpolan en la ruta de Graph — van escapados.
- A4: `/ideas/audio` y `/health/ingest*` cargaban en memoria lo que mandara el cliente.

(A2 es una migración SQL: `supabase/migrations/20260729_rls_jobs.sql`.)
"""
import main
from conftest import FakeResponse

JOB_ID = "123e4567-e89b-12d3-a456-426614174000"


class TestAludUrlPermitida:
    def test_host_de_la_lista_con_https(self):
        assert main.alud_url_permitida("https://alud.deusto.es/mod/assign/view.php?id=99")

    def test_subdominio_del_host_permitido(self):
        assert main.alud_url_permitida("https://aulas.alud.deusto.es/x")

    def test_http_no_vale(self):
        """El agente abre esta URL con sesión iniciada: por http se ve y se reescribe."""
        assert not main.alud_url_permitida("http://alud.deusto.es/mod/assign/view.php?id=99")

    def test_otro_host(self):
        assert not main.alud_url_permitida("https://atacante.example/pagina")

    def test_sufijo_que_imita_al_host_permitido(self):
        """'alud.deusto.es.atacante.com' termina en el host permitido pero no lo es."""
        assert not main.alud_url_permitida("https://alud.deusto.es.atacante.com/x")

    def test_userinfo_no_engana(self):
        """El host real de esta URL es atacante.com, no alud.deusto.es."""
        assert not main.alud_url_permitida("https://alud.deusto.es@atacante.com/x")

    def test_esquema_javascript(self):
        assert not main.alud_url_permitida("javascript:alert(1)")

    def test_vacia_o_no_texto(self):
        assert not main.alud_url_permitida("")
        assert not main.alud_url_permitida(None)

    def test_lista_configurable_por_instancia(self, monkeypatch):
        monkeypatch.setattr(main, "ALUD_ALLOWED_HOSTS", ("moodle.example.edu",))
        assert main.alud_url_permitida("https://moodle.example.edu/x")
        assert not main.alud_url_permitida("https://alud.deusto.es/x")


def _evento_con_cuerpo(cuerpo):
    return FakeResponse({
        "value": [{
            "id": "ev1",
            "subject": "Entrega",
            "start": {"dateTime": "2026-07-06T10:00:00Z", "timeZone": "UTC"},
            "end": {"dateTime": "2026-07-06T12:00:00Z", "timeZone": "UTC"},
            "location": {"displayName": "Aula 3"},
            "body": {"content": cuerpo},
            "bodyPreview": "",
            "isAllDay": False,
        }]
    })


class TestAludUrlEnCalendario:
    def test_url_de_host_ajeno_se_descarta(self, client, auth_headers, graph_token, mock_requests):
        """Quien pueda meter un evento en el calendario no debe elegir a dónde navega el PC."""
        mock_requests.add("GET", "graph.microsoft.com", _evento_con_cuerpo(
            "alud_url: https://atacante.example/carga</p>"))
        ev = client.get("/calendar/events", headers=auth_headers).json()["events"][0]
        assert ev["alud_url"] is None

    def test_url_http_se_descarta(self, client, auth_headers, graph_token, mock_requests):
        mock_requests.add("GET", "graph.microsoft.com", _evento_con_cuerpo(
            "alud_url: http://alud.deusto.es/mod/assign/view.php?id=99</p>"))
        ev = client.get("/calendar/events", headers=auth_headers).json()["events"][0]
        assert ev["alud_url"] is None

    def test_url_legitima_sigue_pasando(self, client, auth_headers, graph_token, mock_requests):
        mock_requests.add("GET", "graph.microsoft.com", _evento_con_cuerpo(
            "alud_url: https://alud.deusto.es/mod/assign/view.php?id=99</p>"))
        ev = client.get("/calendar/events", headers=auth_headers).json()["events"][0]
        assert ev["alud_url"] == "https://alud.deusto.es/mod/assign/view.php?id=99"


class TestAludUrlEnAltaDeJob:
    def test_payload_con_url_no_permitida_da_400(self, client, auth_headers, mock_requests):
        r = client.post("/jobs", headers=auth_headers, json={
            "dedupe_key": "entrega-x",
            "payload": {"accion": "resolver_alud", "alud_url": "https://atacante.example/x"},
        })
        assert r.status_code == 400
        assert not mock_requests.called("POST", "/rest/v1/jobs"), "no debe llegar a guardarse"

    def test_payload_con_url_legitima_se_crea(self, client, auth_headers, mock_requests):
        job = {"id": JOB_ID, "status": "pending"}
        mock_requests.add("POST", "/rest/v1/jobs", FakeResponse([job], 201))
        r = client.post("/jobs", headers=auth_headers, json={
            "dedupe_key": "entrega-x",
            "payload": {"accion": "resolver_alud", "alud_url": "https://alud.deusto.es/x"},
        })
        assert r.status_code == 200

    def test_payload_sin_alud_url_no_se_toca(self, client, auth_headers, mock_requests):
        job = {"id": JOB_ID, "status": "pending"}
        mock_requests.add("POST", "/rest/v1/jobs", FakeResponse([job], 201))
        r = client.post("/jobs", headers=auth_headers, json={
            "dedupe_key": "streaming-1", "payload": {"accion": "abrir_streaming"},
        })
        assert r.status_code == 200


class TestIdsDeGraphEscapados:
    def test_event_id_con_caracteres_de_ruta(self, client, auth_headers, graph_token, mock_requests):
        """Un id con '?' cambiaría el endpoint de Graph al que se llama."""
        mock_requests.add("PATCH", "graph.microsoft.com", FakeResponse({}, 200))
        r = client.patch("/calendar/events/ev%3F$select=x", headers=auth_headers,
                         json={"subject": "Nuevo"})
        assert r.status_code == 200
        url = mock_requests.called("PATCH", "graph.microsoft.com")[0][1]
        assert url.endswith("/me/events/ev%3F%24select%3Dx"), url

    def test_calendar_id_con_traversal(self, client, auth_headers, graph_token, mock_requests):
        mock_requests.add("POST", "graph.microsoft.com", FakeResponse({"id": "x"}, 201))
        r = client.post("/calendar/events", headers=auth_headers, json={
            "subject": "X", "start": "2026-07-10T09:00:00", "end": "2026-07-10T10:00:00",
            "calendar_id": "../../users/otro",
        })
        assert r.status_code == 200
        url = mock_requests.called("POST", "graph.microsoft.com")[0][1]
        assert "/users/otro" not in url
        assert url.endswith("/me/calendars/..%2F..%2Fusers%2Fotro/events"), url

    def test_calendar_id_normal_no_se_altera(self, client, auth_headers, graph_token, mock_requests):
        mock_requests.add("POST", "/me/calendars/cal-123/events", FakeResponse({"id": "x"}, 201))
        r = client.post("/calendar/events", headers=auth_headers, json={
            "subject": "X", "start": "2026-07-10T09:00:00", "end": "2026-07-10T10:00:00",
            "calendar_id": "cal-123",
        })
        assert r.status_code == 200
        assert mock_requests.called("POST", "/me/calendars/cal-123/events")


class TestLimiteDeCuerpo:
    def test_ingest_rechaza_cuerpo_grande(self, client, monkeypatch):
        monkeypatch.setattr(main, "MAX_INGEST_BYTES", 100)
        r = client.post("/health/ingest?token=health-token", content=b"x" * 500,
                        headers={"Content-Type": "application/json"})
        assert r.status_code == 413

    def test_ingest_simple_rechaza_cuerpo_grande(self, client, monkeypatch):
        monkeypatch.setattr(main, "MAX_INGEST_BYTES", 100)
        r = client.post("/health/ingest/simple?token=health-token", content=b"x" * 500,
                        headers={"Content-Type": "application/json"})
        assert r.status_code == 413

    def test_ingest_sin_content_length_tambien_se_corta(self, client, monkeypatch):
        """Con Transfer-Encoding: chunked no hay Content-Length que mirar: cuenta el stream."""
        monkeypatch.setattr(main, "MAX_INGEST_BYTES", 100)
        r = client.post("/health/ingest?token=health-token",
                        content=iter([b"x" * 80, b"y" * 80]),
                        headers={"Content-Type": "application/json"})
        assert r.status_code == 413

    def test_ingest_de_tamano_normal_sigue_funcionando(self, client, mock_requests):
        r = client.post("/health/ingest?token=health-token", json={"data": {"metrics": []}})
        assert r.status_code == 200

    def test_token_invalido_se_comprueba_antes_del_tamano(self, client, monkeypatch):
        """Un cuerpo enorme sin token válido no debe llegar siquiera a leerse."""
        monkeypatch.setattr(main, "MAX_INGEST_BYTES", 100)
        r = client.post("/health/ingest?token=mal", content=b"x" * 500,
                        headers={"Content-Type": "application/json"})
        assert r.status_code == 403


class TestAudioAcotado:
    def test_audio_grande_da_413_sin_llamar_a_openai(self, client, auth_headers, monkeypatch):
        monkeypatch.setattr(main, "MAX_AUDIO_BYTES", 50)

        def _no_llamar():
            raise AssertionError("no debería construirse el cliente de OpenAI")

        monkeypatch.setattr(main, "get_openai_client", _no_llamar)
        r = client.post("/ideas/audio", headers=auth_headers,
                        files={"audio": ("nota.webm", b"x" * 500, "audio/webm")})
        assert r.status_code == 413

    def test_rate_limit_por_ip(self, client, auth_headers, monkeypatch):
        """La transcripción se paga por llamada: una sesión robada no puede gastar sin techo."""
        monkeypatch.setattr(main, "MAX_AUDIO_BYTES", 50)
        monkeypatch.setattr(main, "AUDIO_MAX_REQUESTS", 3)
        ficheros = {"audio": ("nota.webm", b"x" * 500, "audio/webm")}
        for _ in range(3):
            assert client.post("/ideas/audio", headers=auth_headers, files=ficheros).status_code == 413
        r = client.post("/ideas/audio", headers=auth_headers, files=ficheros)
        assert r.status_code == 429
        assert r.headers.get("Retry-After")

    def test_el_limitador_del_audio_no_afecta_al_del_login(self, client, auth_headers, monkeypatch):
        """Son contadores distintos: agotar uno no debe bloquear el otro."""
        monkeypatch.setattr(main, "MAX_AUDIO_BYTES", 50)
        monkeypatch.setattr(main, "AUDIO_MAX_REQUESTS", 1)
        ficheros = {"audio": ("nota.webm", b"x" * 500, "audio/webm")}
        client.post("/ideas/audio", headers=auth_headers, files=ficheros)
        assert client.post("/ideas/audio", headers=auth_headers, files=ficheros).status_code == 429
        assert client.post("/auth/password", json={"password": "1234"}).status_code == 200
