"""Tests de los arreglos de la revisión de seguridad: C1, C2, C3, A3 y A4.

- C1: /auth/login exige JWT y /auth/callback exige un `state` firmado — antes
  cualquiera que supiera la URL del backend podía secuestrar la conexión de Outlook
  completando SU PROPIO login de Microsoft.
- C2: `alud_url` sale del cuerpo de un evento de Outlook y acaba en `page.goto()` del
  agente, en un navegador con la sesión de Alud iniciada. Solo pasan https y hosts de
  la lista blanca, y se comprueba tanto al extraerla como al dar de alta el job.
- C3: el límite de intentos de login es global (no por IP) y vive en Supabase, no en
  memoria — antes se reseteaba cada vez que Fly dormía la máquina.
- A3: `event_id` y `calendar_id` se interpolan en la ruta de Graph — van escapados.
- A4: `/ideas/audio` y `/health/ingest*` cargaban en memoria lo que mandara el cliente.

(A2 es una migración SQL: `supabase/migrations/20260729_rls_jobs.sql`.)
"""
from datetime import datetime, timedelta, timezone

from jose import jwt as jose_jwt

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

    def test_el_limitador_del_audio_no_afecta_al_del_login(
        self, client, auth_headers, monkeypatch, login_attempts_mock,
    ):
        """Son contadores distintos: agotar uno no debe bloquear el otro."""
        monkeypatch.setattr(main, "MAX_AUDIO_BYTES", 50)
        monkeypatch.setattr(main, "AUDIO_MAX_REQUESTS", 1)
        ficheros = {"audio": ("nota.webm", b"x" * 500, "audio/webm")}
        client.post("/ideas/audio", headers=auth_headers, files=ficheros)
        assert client.post("/ideas/audio", headers=auth_headers, files=ficheros).status_code == 429
        assert client.post("/auth/password", json={"password": "1234"}).status_code == 200

    def test_ip_spoofing_no_evade_el_limite_de_audio(self, client, auth_headers, monkeypatch):
        """X-Forwarded-For la controla quien llama: rotarla no debe dar cupos nuevos.

        Esta protección vivía antes en el limitador de login (por IP); ahora ese es
        global y esta es la única ruta que sigue limitando por IP — la resistencia al
        spoofing se prueba aquí. _client_ip() la ignora salvo opt-in (TRUST_FORWARDED_FOR).
        """
        monkeypatch.setattr(main, "MAX_AUDIO_BYTES", 50)
        monkeypatch.setattr(main, "AUDIO_MAX_REQUESTS", 3)
        ficheros = {"audio": ("nota.webm", b"x" * 500, "audio/webm")}
        codigos = [
            client.post("/ideas/audio", headers={**auth_headers, "X-Forwarded-For": f"9.9.9.{i}"},
                        files=ficheros).status_code
            for i in range(6)
        ]
        assert 429 in codigos, f"el límite se evade rotando X-Forwarded-For: {codigos}"

    def test_fly_client_ip_se_ignora_fuera_de_fly(self, client, auth_headers, monkeypatch):
        """Sin el runtime de Fly nadie sobrescribe la cabecera, así que no vale nada."""
        monkeypatch.setattr(main, "MAX_AUDIO_BYTES", 50)
        monkeypatch.setattr(main, "AUDIO_MAX_REQUESTS", 3)
        ficheros = {"audio": ("nota.webm", b"x" * 500, "audio/webm")}
        codigos = [
            client.post("/ideas/audio", headers={**auth_headers, "Fly-Client-IP": f"9.9.9.{i}"},
                        files=ficheros).status_code
            for i in range(6)
        ]
        assert 429 in codigos, f"cabecera de Fly aceptada fuera de Fly: {codigos}"

    def test_rate_limit_usa_fly_client_ip_frente_a_forwarded_for(self, client, auth_headers, monkeypatch):
        """En Fly, Fly-Client-IP la pone el proxy: manda sobre lo que declare el cliente."""
        monkeypatch.setattr(main, "MAX_AUDIO_BYTES", 50)
        monkeypatch.setattr(main, "AUDIO_MAX_REQUESTS", 3)
        monkeypatch.setattr(main, "EN_FLY", True)
        ficheros = {"audio": ("nota.webm", b"x" * 500, "audio/webm")}
        for _ in range(3):
            client.post(
                "/ideas/audio",
                headers={**auth_headers, "Fly-Client-IP": "5.5.5.5", "X-Forwarded-For": "1.1.1.1"},
                files=ficheros,
            )
        r = client.post(
            "/ideas/audio",
            headers={**auth_headers, "Fly-Client-IP": "5.5.5.5", "X-Forwarded-For": "2.2.2.2"},
            files=ficheros,
        )
        assert r.status_code == 429

    def test_con_trust_forwarded_for_usa_la_ultima_entrada(self, client, auth_headers, monkeypatch):
        """Con proxy propio declarado, la entrada de confianza es la última.

        Las anteriores las puede inventar el cliente, así que prefijarlas no debe
        conseguir un cupo de intentos nuevo.
        """
        monkeypatch.setattr(main, "MAX_AUDIO_BYTES", 50)
        monkeypatch.setattr(main, "AUDIO_MAX_REQUESTS", 3)
        monkeypatch.setattr(main, "TRUST_FORWARDED_FOR", True)
        ficheros = {"audio": ("nota.webm", b"x" * 500, "audio/webm")}
        for i in range(3):
            client.post(
                "/ideas/audio",
                headers={**auth_headers, "X-Forwarded-For": f"1.1.1.{i}, 7.7.7.7"},
                files=ficheros,
            )
        r = client.post(
            "/ideas/audio",
            headers={**auth_headers, "X-Forwarded-For": "9.9.9.9, 7.7.7.7"},
            files=ficheros,
        )
        assert r.status_code == 429


class _FakeMsalApp:
    """Sustituye a msal.ConfidentialClientApplication: sin red, sin credenciales reales."""

    def __init__(self, *args, **kwargs):
        pass

    def get_authorization_request_url(self, scopes, redirect_uri=None, state=None):
        self.__class__.ultimo_state = state
        return f"https://login.microsoftonline.com/fake/authorize?state={state}"

    def acquire_token_by_authorization_code(self, code, scopes=None, redirect_uri=None):
        return {"access_token": "tok-x", "refresh_token": "ref-x", "expires_in": 3600}


class TestOAuthLoginProtegido:
    def test_login_requiere_jwt(self, client):
        assert client.get("/auth/login").status_code in (401, 403)

    def test_login_con_jwt_genera_state_valido(self, client, auth_headers, monkeypatch):
        monkeypatch.setattr(main.msal, "ConfidentialClientApplication", _FakeMsalApp)
        r = client.get("/auth/login", headers=auth_headers)
        assert r.status_code == 200
        state = _FakeMsalApp.ultimo_state
        assert state and main._verify_oauth_state(state)


class TestOAuthCallbackState:
    def test_sin_state_da_403(self, client):
        r = client.get("/auth/callback", params={"code": "abc"})
        assert r.status_code == 403

    def test_state_no_es_un_jwt_da_403(self, client):
        r = client.get("/auth/callback", params={"code": "abc", "state": "no-es-un-jwt"})
        assert r.status_code == 403

    def test_state_de_otro_proposito_no_vale(self, client):
        """Un JWT válido (el propio token del dashboard) pero sin purpose=oauth_state
        no debe colarse como si fuera el state del flujo OAuth."""
        token_dashboard = main.create_token()
        r = client.get("/auth/callback", params={"code": "abc", "state": token_dashboard})
        assert r.status_code == 403

    def test_state_expirado_da_403(self, client):
        expirado = jose_jwt.encode(
            {"exp": datetime.now(timezone.utc) - timedelta(minutes=1), "purpose": "oauth_state"},
            "test-secret-key", algorithm="HS256",
        )
        r = client.get("/auth/callback", params={"code": "abc", "state": expirado})
        assert r.status_code == 403

    def test_state_firmado_con_otra_clave_da_403(self, client):
        ajeno = jose_jwt.encode(
            {"exp": datetime.now(timezone.utc) + timedelta(minutes=5), "purpose": "oauth_state"},
            "otra-clave", algorithm="HS256",
        )
        r = client.get("/auth/callback", params={"code": "abc", "state": ajeno})
        assert r.status_code == 403

    def test_state_valido_completa_el_flujo(self, client, mock_requests, monkeypatch):
        monkeypatch.setattr(main.msal, "ConfidentialClientApplication", _FakeMsalApp)
        estado = main._create_oauth_state()
        r = client.get("/auth/callback", params={"code": "abc", "state": estado})
        assert r.status_code == 200
        assert r.json()["status"] == "ok"
        assert mock_requests.called("POST", "/rest/v1/oauth_tokens")
