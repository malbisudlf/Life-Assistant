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
    def test_password_correcta_devuelve_jwt_valido(self, client):
        r = client.post("/auth/password", json={"password": "1234"})
        assert r.status_code == 200
        token = r.json()["token"]
        claims = jwt.decode(token, "test-secret-key", algorithms=["HS256"])
        assert claims["exp"] > datetime.now(timezone.utc).timestamp()

    def test_password_incorrecta(self, client):
        r = client.post("/auth/password", json={"password": "mala"})
        assert r.status_code == 401

    def test_password_demasiado_larga_rechazada_por_validacion(self, client):
        r = client.post("/auth/password", json={"password": "x" * 201})
        assert r.status_code == 422

    def test_rate_limit_tras_5_fallos(self, client):
        for _ in range(5):
            assert client.post("/auth/password", json={"password": "mala"}).status_code == 401
        r = client.post("/auth/password", json={"password": "mala"})
        assert r.status_code == 429
        assert "Retry-After" in r.headers
        # Incluso con la contraseña buena sigue bloqueado
        r2 = client.post("/auth/password", json={"password": "1234"})
        assert r2.status_code == 429

    def test_login_correcto_resetea_contador(self, client):
        for _ in range(3):
            client.post("/auth/password", json={"password": "mala"})
        assert client.post("/auth/password", json={"password": "1234"}).status_code == 200
        # El contador se ha reseteado: caben otros 5 fallos antes del 429
        for _ in range(5):
            assert client.post("/auth/password", json={"password": "mala"}).status_code == 401
        assert client.post("/auth/password", json={"password": "mala"}).status_code == 429


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
        assert r.json() == {"ok": True, "idea": saved}

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

        monkeypatch.setattr(main, "openai_client", FakeClient())
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

        monkeypatch.setattr(main, "openai_client", FakeClient())
        assert main.extract_idea_from_text("hola") == {}


# ── CONTEO DE ROPA ────────────────────────────────────────────────────────────

class TestClothing:
    def test_listar_requiere_token(self, client):
        assert client.get("/clothing").status_code in (401, 403)

    def test_listar_devuelve_lista(self, client, auth_headers, mock_requests):
        items = [{"id": "abc", "name": "Camiseta", "price": 20, "currency": "EUR", "photo": None}]
        mock_requests.add("GET", "/rest/v1/clothing", FakeResponse(items))
        r = client.get("/clothing", headers=auth_headers)
        assert r.status_code == 200
        assert r.json() == items

    def test_crear_prenda(self, client, auth_headers, mock_requests):
        saved = {"id": "abc", "name": "Camiseta", "price": 20.0, "currency": "EUR", "photo": None}
        mock_requests.add("POST", "/rest/v1/clothing", FakeResponse([saved], 201))
        r = client.post("/clothing", headers=auth_headers,
                        json={"name": "Camiseta", "price": 20, "currency": "EUR"})
        assert r.status_code == 200
        assert r.json() == {"ok": True, "item": saved}

    def test_crear_prenda_minima_usa_defaults(self, client, auth_headers, mock_requests):
        saved = {"id": "x", "name": "", "price": 0.0, "currency": "EUR", "photo": None}
        mock_requests.add("POST", "/rest/v1/clothing", FakeResponse([saved], 201))
        r = client.post("/clothing", headers=auth_headers, json={})
        assert r.status_code == 200
        # El payload enviado a Supabase aplica los defaults del modelo
        sent = mock_requests.called("POST", "/rest/v1/clothing")[0][2]["json"]
        assert sent == {"name": "", "price": 0.0, "currency": "EUR", "photo": None}

    def test_moneda_invalida_rechazada(self, client, auth_headers):
        r = client.post("/clothing", headers=auth_headers,
                        json={"price": 10, "currency": "USD"})
        assert r.status_code == 422

    def test_precio_negativo_rechazado(self, client, auth_headers):
        r = client.post("/clothing", headers=auth_headers, json={"price": -5})
        assert r.status_code == 422

    def test_error_supabase_al_crear(self, client, auth_headers, mock_requests):
        mock_requests.add("POST", "/rest/v1/clothing", FakeResponse(None, 500, "boom"))
        r = client.post("/clothing", headers=auth_headers, json={"price": 10})
        assert r.status_code == 502

    def test_borrar_valida_uuid(self, client, auth_headers, mock_requests):
        assert client.delete("/clothing/no-uuid", headers=auth_headers).status_code == 422
        mock_requests.add("DELETE", "/rest/v1/clothing", FakeResponse([], 204))
        r = client.delete("/clothing/123e4567-e89b-12d3-a456-426614174000", headers=auth_headers)
        assert r.status_code == 200
        assert r.json() == {"ok": True}


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
