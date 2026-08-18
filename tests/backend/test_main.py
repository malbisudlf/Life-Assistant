"""Tests de autenticación, rate limiting, helpers puros, /maps/departure e ideas."""
from datetime import datetime, timezone

from jose import jwt

import main
from conftest import FakeResponse


# ── Helpers puros ─────────────────────────────────────────────────────────────

class TestNormalizeGraphDt:
    def test_utc_con_z(self):
        assert main.normalize_graph_dt({"dateTime": "2026-07-05T10:00:00Z", "timeZone": "UTC"}) == "2026-07-05T10:00:00Z"

    def test_offset_explicito(self):
        out = main.normalize_graph_dt({"dateTime": "2026-07-05T12:00:00+02:00", "timeZone": "Romance Standard Time"})
        assert out == "2026-07-05T10:00:00Z"

    def test_zona_windows_sin_offset(self):
        # Julio: Europe/Paris es UTC+2
        out = main.normalize_graph_dt({"dateTime": "2026-07-05T12:00:00.0000000", "timeZone": "Romance Standard Time"})
        assert out == "2026-07-05T10:00:00Z"

    def test_zona_iana_directa(self):
        out = main.normalize_graph_dt({"dateTime": "2026-01-05T12:00:00", "timeZone": "Europe/Madrid"})
        assert out == "2026-01-05T11:00:00Z"  # invierno: UTC+1

    def test_zona_desconocida_cae_a_utc(self):
        out = main.normalize_graph_dt({"dateTime": "2026-07-05T12:00:00", "timeZone": "Zona Inventada"})
        assert out == "2026-07-05T12:00:00Z"

    def test_vacio(self):
        assert main.normalize_graph_dt({}) == ""


class TestCleanClassTitle:
    def test_quita_prefijo_numerico_y_sufijo_grupo(self):
        assert main._clean_class_title("14 - Álgebra Grupo: 2 - Asignatura") == "Álgebra"

    def test_titulo_normal_intacto(self):
        assert main._clean_class_title("Reunión TFG") == "Reunión TFG"


class TestTokenOk:
    def test_coincide(self):
        assert main._token_ok("abc", "abc") is True

    def test_no_coincide(self):
        assert main._token_ok("abc", "xyz") is False

    def test_esperado_no_configurado(self):
        # Si el token del servidor no está configurado, NUNCA debe autorizar
        assert main._token_ok("cualquiera", "") is False

    def test_provisto_vacio(self):
        assert main._token_ok("", "abc") is False


class TestExtractServiceToken:
    def _req(self, headers):
        class R:
            def __init__(self, h):
                self.headers = h
        return R(headers)

    def test_prefiere_header_x_auth_token(self):
        req = self._req({"x-auth-token": "h1", "authorization": "Bearer h2"})
        assert main._extract_service_token(req, "qs") == "h1"

    def test_luego_bearer(self):
        req = self._req({"authorization": "Bearer h2"})
        assert main._extract_service_token(req, "qs") == "h2"

    def test_por_ultimo_query_string(self):
        req = self._req({})
        assert main._extract_service_token(req, "qs") == "qs"


# ── /auth/password ────────────────────────────────────────────────────────────

class TestAuthPassword:
    """El límite de intentos es GLOBAL (no por IP) y vive en Supabase (login_attempts),
    no en memoria — ver _check_login_rate en main.py. Los tests de resistencia a
    rotar X-Forwarded-For / Fly-Client-IP viven ahora en test_seguridad.py, contra
    /ideas/audio: ese es el endpoint que sigue limitando por IP."""

    def test_password_correcta_devuelve_jwt_valido(self, client, login_attempts_mock):
        r = client.post("/auth/password", json={"password": "1234"})
        assert r.status_code == 200
        token = r.json()["token"]
        claims = jwt.decode(token, "test-secret-key", algorithms=["HS256"])
        assert claims["exp"] > datetime.now(timezone.utc).timestamp()

    def test_password_incorrecta(self, client, login_attempts_mock):
        r = client.post("/auth/password", json={"password": "mala"})
        assert r.status_code == 401

    def test_password_demasiado_larga_rechazada_por_validacion(self, client):
        r = client.post("/auth/password", json={"password": "x" * 201})
        assert r.status_code == 422

    def test_rate_limit_tras_5_fallos(self, client, login_attempts_mock):
        for _ in range(5):
            assert client.post("/auth/password", json={"password": "mala"}).status_code == 401
        r = client.post("/auth/password", json={"password": "mala"})
        assert r.status_code == 429
        assert "Retry-After" in r.headers
        # Incluso con la contraseña buena sigue bloqueado
        r2 = client.post("/auth/password", json={"password": "1234"})
        assert r2.status_code == 429

    def test_login_correcto_resetea_contador(self, client, login_attempts_mock):
        for _ in range(3):
            client.post("/auth/password", json={"password": "mala"})
        assert client.post("/auth/password", json={"password": "1234"}).status_code == 200
        # El contador se ha reseteado: caben otros 5 fallos antes del 429
        for _ in range(5):
            assert client.post("/auth/password", json={"password": "mala"}).status_code == 401
        assert client.post("/auth/password", json={"password": "mala"}).status_code == 429

    def test_limite_es_global_no_por_ip(self, client, login_attempts_mock):
        """Antes el límite era por IP; ahora es global porque solo hay un usuario
        legítimo, así que rotar de IP no da un cupo de intentos nuevo."""
        codigos = [
            client.post(
                "/auth/password",
                json={"password": "mala"},
                headers={"X-Forwarded-For": f"9.9.9.{i}"},
            ).status_code
            for i in range(6)
        ]
        assert codigos[-1] == 429, f"el límite no aplica de forma global: {codigos}"

    def test_supabase_caido_no_bloquea_el_login(self, client, mock_requests):
        """Si Supabase no responde, se deja pasar en vez de tumbar el único endpoint
        que hoy no depende de la base de datos para nada más."""
        mock_requests.add("GET", "/rest/v1/login_attempts", FakeResponse(None, 500, "caído"))
        r = client.post("/auth/password", json={"password": "1234"})
        assert r.status_code == 200

    def test_password_con_tilde_devuelve_401_no_500(self, client, login_attempts_mock):
        """compare_digest sobre str lanza TypeError con no-ASCII → antes era un 500."""
        r = client.post("/auth/password", json={"password": "contraseña"})
        assert r.status_code == 401


# ── Protección con JWT ────────────────────────────────────────────────────────

class TestJwtProtection:
    def test_sin_token(self, client):
        assert client.get("/ideas").status_code in (401, 403)

    def test_token_invalido(self, client):
        r = client.get("/ideas", headers={"Authorization": "Bearer no-es-un-jwt"})
        assert r.status_code == 401

    def test_token_firmado_con_otra_clave(self, client):
        forged = jwt.encode({"exp": 9999999999}, "otra-clave", algorithm="HS256")
        r = client.get("/ideas", headers={"Authorization": f"Bearer {forged}"})
        assert r.status_code == 401

    def test_token_valido_pasa(self, client, auth_headers, mock_requests):
        mock_requests.add("GET", "/rest/v1/ideas", FakeResponse([]))
        assert client.get("/ideas", headers=auth_headers).status_code == 200


# ── /maps/departure ───────────────────────────────────────────────────────────

class TestMapsDeparture:
    def _maps_response(self, seconds=1800):
        return FakeResponse({
            "rows": [{"elements": [{
                "status": "OK",
                "duration": {"value": seconds, "text": "30 min"},
                "duration_in_traffic": {"value": seconds, "text": "30 min"},
                "distance": {"text": "20 km"},
            }]}]
        })

    def test_calcula_hora_de_salida_con_margen(self, client, auth_headers, mock_requests):
        mock_requests.add("GET", "maps.googleapis.com", self._maps_response(1800))
        r = client.post("/maps/departure", headers=auth_headers, json={
            "destination": "Universidad de Deusto, Bilbao",
            "event_time": "2026-07-06T10:00:00+02:00",
        })
        assert r.status_code == 200
        data = r.json()
        # 10:00 - 30 min de viaje - 10 min de margen = 09:20 hora de Madrid
        assert data["departure_time"] == "09:20"
        assert data["duration_text"] == "30 min"
        assert data["distance_text"] == "20 km"
        madrid = datetime.fromisoformat(data["departure_iso"])
        assert madrid.tzinfo is not None

    def test_modo_walking_no_pide_trafico(self, client, auth_headers, mock_requests):
        mock_requests.add("GET", "maps.googleapis.com", self._maps_response())
        r = client.post("/maps/departure", headers=auth_headers, json={
            "destination": "X", "event_time": "2026-07-06T10:00:00Z", "mode": "walking",
        })
        assert r.status_code == 200
        params = mock_requests.called("GET", "maps.googleapis.com")[0][2]["params"]
        assert "departure_time" not in params

    def test_modo_invalido(self, client, auth_headers):
        r = client.post("/maps/departure", headers=auth_headers, json={
            "destination": "X", "event_time": "2026-07-06T10:00:00Z", "mode": "bicycling",
        })
        assert r.status_code == 422

    def test_fecha_invalida(self, client, auth_headers):
        r = client.post("/maps/departure", headers=auth_headers, json={
            "destination": "X", "event_time": "no-es-fecha",
        })
        assert r.status_code == 422

    def test_ruta_no_encontrada(self, client, auth_headers, mock_requests):
        mock_requests.add("GET", "maps.googleapis.com", FakeResponse({
            "rows": [{"elements": [{"status": "NOT_FOUND"}]}]
        }))
        r = client.post("/maps/departure", headers=auth_headers, json={
            "destination": "X", "event_time": "2026-07-06T10:00:00Z",
        })
        assert r.status_code == 400

    def test_respuesta_maps_malformada(self, client, auth_headers, mock_requests):
        mock_requests.add("GET", "maps.googleapis.com", FakeResponse({"rows": []}))
        r = client.post("/maps/departure", headers=auth_headers, json={
            "destination": "X", "event_time": "2026-07-06T10:00:00Z",
        })
        assert r.status_code == 500

    def test_error_http_de_maps_da_502_y_no_filtra_el_cuerpo(self, client, auth_headers, mock_requests):
        mock_requests.add("GET", "maps.googleapis.com", FakeResponse(None, 403, text="API key inválida: AIza-secreta"))
        r = client.post("/maps/departure", headers=auth_headers, json={
            "destination": "X", "event_time": "2026-07-06T10:00:00Z",
        })
        assert r.status_code == 502
        assert "AIza-secreta" not in r.text

    def test_status_de_error_de_maps_da_502(self, client, auth_headers, mock_requests):
        # Maps responde 200 con el error dentro (cuota agotada, key sin permisos…)
        mock_requests.add("GET", "maps.googleapis.com", FakeResponse({
            "status": "OVER_QUERY_LIMIT", "error_message": "quota", "rows": [],
        }))
        r = client.post("/maps/departure", headers=auth_headers, json={
            "destination": "X", "event_time": "2026-07-06T10:00:00Z",
        })
        assert r.status_code == 502

    def test_maps_no_json_da_502_en_vez_de_reventar(self, client, auth_headers, mock_requests):
        class RespuestaNoJson(FakeResponse):
            def json(self):
                raise ValueError("no es JSON")

        mock_requests.add("GET", "maps.googleapis.com", RespuestaNoJson(None, 200, text="<html>"))
        r = client.post("/maps/departure", headers=auth_headers, json={
            "destination": "X", "event_time": "2026-07-06T10:00:00Z",
        })
        assert r.status_code == 502


# ── IDEAS ─────────────────────────────────────────────────────────────────────

class TestIdeas:
    def test_texto_vacio(self, client, auth_headers):
        r = client.post("/ideas/text", headers=auth_headers, json={"text": "   "})
        assert r.status_code == 400

    def test_crear_idea_desde_texto(self, client, auth_headers, mock_requests, monkeypatch):
        monkeypatch.setattr(main, "extract_idea_from_text", lambda t: {
            "key": "Comprar pan", "tag": "recados", "full_text": "Comprar pan mañana",
        })
        saved = {"id": "abc", "key": "Comprar pan", "tag": "recados", "full_text": "Comprar pan mañana"}
        mock_requests.add("POST", "/rest/v1/ideas", FakeResponse([saved], 201))
        r = client.post("/ideas/text", headers=auth_headers, json={"text": "comprar pan mañana"})
        assert r.status_code == 200
        # evento_sugerido es null porque la extracción no devolvió fecha
        assert r.json() == {"ok": True, "idea": saved, "evento_sugerido": None}

    def test_listar_con_error_de_supabase_da_502_sin_filtrar_detalle(self, client, auth_headers, mock_requests):
        # Antes se devolvía r.json() sin mirar el estado: el cuerpo de error de
        # Supabase (con sus mensajes internos) llegaba tal cual al navegador.
        mock_requests.add("GET", "/rest/v1/ideas", FakeResponse(
            {"message": 'relation "public.ideas" does not exist', "hint": "interno"}, 500, text="detalle interno"))
        r = client.get("/ideas", headers=auth_headers)
        assert r.status_code == 502
        assert "does not exist" not in r.text
        assert r.json()["detail"] == "Error en el almacenamiento de datos"

    def test_delete_idea_valida_uuid(self, client, auth_headers, mock_requests):
        assert client.delete("/ideas/no-uuid", headers=auth_headers).status_code == 422
        mock_requests.add("DELETE", "/rest/v1/ideas", FakeResponse([], 204))
        r = client.delete("/ideas/123e4567-e89b-12d3-a456-426614174000", headers=auth_headers)
        assert r.status_code == 200
        assert r.json() == {"ok": True}

    def test_save_idea_trunca_y_aplica_defaults(self, mock_requests):
        mock_requests.add("POST", "/rest/v1/ideas", FakeResponse(None, 500, "boom"))
        # Con error de Supabase devuelve el payload construido (fallback)
        out = main.save_idea("x" * 100, {})
        assert out["key"] == "x" * 60      # default: primeros 60 chars del texto
        assert out["tag"] == "idea"
        assert out["full_text"] == "x" * 100


class TestExport:
    def test_requiere_token(self, client):
        assert client.get("/export").status_code in (401, 403)

    def test_agrupa_cada_tabla_en_su_clave(self, client, auth_headers, mock_requests):
        mock_requests.add("GET", "/rest/v1/ideas", FakeResponse([{"id": "i1"}]))
        mock_requests.add("GET", "/rest/v1/training_clients", FakeResponse([{"id": "c1"}]))
        mock_requests.add("GET", "/rest/v1/training_sessions", FakeResponse([{"id": "s1"}]))
        mock_requests.add("GET", "/rest/v1/training_payments", FakeResponse([{"id": "p1"}]))
        mock_requests.add("GET", "/rest/v1/health_metrics", FakeResponse([{"id": "h1"}]))
        r = client.get("/export", headers=auth_headers)
        assert r.status_code == 200
        data = r.json()
        assert data["ideas"] == [{"id": "i1"}]
        assert data["training_clients"] == [{"id": "c1"}]
        assert data["training_sessions"] == [{"id": "s1"}]
        assert data["training_payments"] == [{"id": "p1"}]
        assert data["health_metrics"] == [{"id": "h1"}]
        assert "exported_at" in data

    def test_no_exporta_tokens_oauth(self, client, auth_headers, mock_requests):
        # Nunca debe consultarse la tabla de secretos oauth_tokens
        r = client.get("/export", headers=auth_headers)
        assert r.status_code == 200
        assert "oauth_tokens" not in r.json()
        assert not mock_requests.called("GET", "oauth_tokens")

    def test_error_supabase_devuelve_502(self, client, auth_headers, mock_requests):
        mock_requests.add("GET", "/rest/v1/ideas", FakeResponse(None, 500, "boom"))
        r = client.get("/export", headers=auth_headers)
        assert r.status_code == 502

    def test_extract_idea_parsea_json_con_fences(self, monkeypatch):
        class FakeCompletion:
            class Choice:
                class Msg:
                    content = '```json\n{"key": "K", "tag": "t", "full_text": "F"}\n```'
                message = Msg()
            choices = [Choice()]

        class FakeClient:
            class chat:
                class completions:
                    @staticmethod
                    def create(**kwargs):
                        return FakeCompletion()

        monkeypatch.setattr(main, "get_openai_client", lambda: FakeClient())
        assert main.extract_idea_from_text("hola") == {"key": "K", "tag": "t", "full_text": "F"}

    def test_extract_idea_json_invalido_devuelve_vacio(self, monkeypatch):
        class FakeCompletion:
            class Choice:
                class Msg:
                    content = "esto no es json"
                message = Msg()
            choices = [Choice()]

        class FakeClient:
            class chat:
                class completions:
                    @staticmethod
                    def create(**kwargs):
                        return FakeCompletion()

        monkeypatch.setattr(main, "get_openai_client", lambda: FakeClient())
        assert main.extract_idea_from_text("hola") == {}


def test_root(client):
    r = client.get("/")
    assert r.status_code == 200
    assert r.json() == {"status": "Life Assistant API running"}


# ── Configuración de instancia (kit self-hosted) ──────────────────────────────

class TestConfiguracionInstancia:
    def test_cors_origins_es_lista_parseada(self):
        assert isinstance(main.CORS_ORIGINS, list)
        assert "http://localhost:5173" in main.CORS_ORIGINS

    def test_timezone_por_defecto(self):
        assert main.TIMEZONE == "Europe/Madrid"
        assert str(main.LOCAL_TZ) == "Europe/Madrid"

    def test_departure_usa_la_zona_configurada(self, client, auth_headers, mock_requests, monkeypatch):
        from zoneinfo import ZoneInfo
        monkeypatch.setattr(main, "LOCAL_TZ", ZoneInfo("America/New_York"))
        mock_requests.add("GET", "maps.googleapis.com", FakeResponse({
            "rows": [{"elements": [{
                "status": "OK",
                "duration": {"value": 1800, "text": "30 min"},
                "duration_in_traffic": {"value": 1800, "text": "30 min"},
                "distance": {"text": "20 km"},
            }]}]
        }))
        r = client.post("/maps/departure", headers=auth_headers, json={
            "destination": "X", "event_time": "2026-07-06T10:00:00+02:00",
        })
        # 08:00 UTC - 40 min = 07:20 UTC → 03:20 en Nueva York (UTC-4 en julio)
        assert r.json()["departure_time"] == "03:20"


# ── CLIENTE DE OPENAI PEREZOSO ────────────────────────────────────────────────

class TestOpenAIOpcional:
    """Las ideas por voz se documentan como opcionales (check_config.py, DESPLIEGUE.md).

    Antes el cliente se construía al importar el módulo, así que el backend entero
    no arrancaba sin OPENAI_API_KEY. Ahora se crea al usarlo y falta de clave = 503.
    """

    def test_sin_api_key_devuelve_503(self, client, auth_headers, monkeypatch):
        monkeypatch.setattr(main, "OPENAI_API_KEY", "")
        monkeypatch.setattr(main, "_openai_client", None)
        r = client.post("/ideas/text", headers=auth_headers, json={"text": "una idea"})
        assert r.status_code == 503
        assert "OPENAI_API_KEY" in r.json()["detail"]

    def test_el_cliente_se_reutiliza_entre_llamadas(self, monkeypatch):
        creados = []

        class FakeOpenAI:
            def __init__(self, **kwargs):
                creados.append(kwargs)

        monkeypatch.setattr(main, "OPENAI_API_KEY", "sk-test")
        monkeypatch.setattr(main, "_openai_client", None)
        monkeypatch.setattr(main, "OpenAI", FakeOpenAI)
        assert main.get_openai_client() is main.get_openai_client()
        assert len(creados) == 1


class TestSugerenciaEvento:
    """Lo que propone el LLM no llega a Graph sin validar: solo pasa lo que tiene forma
    de fecha (YYYY-MM-DD) y de hora (HH:MM), y el evento no se crea sin que el usuario
    lo pulse."""

    def test_fecha_y_hora_validas(self):
        assert main.sugerencia_evento({
            "key": "Llamar al dentista", "fecha": "2026-08-04", "hora": "17:00",
        }) == {"titulo": "Llamar al dentista", "fecha": "2026-08-04", "hora": "17:00"}

    def test_dia_sin_hora(self):
        s = main.sugerencia_evento({"key": "Entrega TFG", "fecha": "2026-08-04", "hora": None})
        assert s["hora"] is None and s["fecha"] == "2026-08-04"

    def test_sin_fecha_no_hay_sugerencia(self):
        assert main.sugerencia_evento({"key": "Idea suelta", "fecha": None}) is None
        assert main.sugerencia_evento({"key": "Idea suelta"}) is None

    def test_fecha_con_formato_o_valor_imposible_se_descarta(self):
        for mala in ["mañana", "04/08/2026", "2026-13-45", "2026-02-30", "", 20260804]:
            assert main.sugerencia_evento({"key": "X", "fecha": mala}) is None

    def test_hora_invalida_se_ignora_pero_conserva_el_dia(self):
        for mala in ["25:00", "17.00", "5pm", "", 1700]:
            s = main.sugerencia_evento({"key": "X", "fecha": "2026-08-04", "hora": mala})
            assert s["hora"] is None and s["fecha"] == "2026-08-04"

    def test_sin_titulo_no_hay_sugerencia(self):
        assert main.sugerencia_evento({"key": "   ", "fecha": "2026-08-04"}) is None

    def test_el_endpoint_devuelve_la_sugerencia(self, client, auth_headers, mock_requests, monkeypatch):
        monkeypatch.setattr(main, "extract_idea_from_text", lambda t: {
            "key": "Llamar al dentista", "tag": "salud", "full_text": "...",
            "fecha": "2026-08-04", "hora": "17:00",
        })
        mock_requests.add("POST", "/rest/v1/ideas", FakeResponse([{"id": "abc"}], 201))
        r = client.post("/ideas/text", headers=auth_headers, json={"text": "el martes al dentista"})
        assert r.json()["evento_sugerido"] == {
            "titulo": "Llamar al dentista", "fecha": "2026-08-04", "hora": "17:00",
        }
