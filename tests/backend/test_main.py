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

    def test_supabase_sin_red_tampoco_bloquea_el_login(self, client, mock_requests):
        """El caso de la caída del DNS: no hay respuesta con error, hay una excepción,
        y el login daba 500 con la contraseña buena."""
        import requests

        def _sin_red(*a, **k):
            raise requests.ConnectionError("NameResolutionError")
        for metodo in ("GET", "POST", "DELETE"):
            mock_requests.add(metodo, "/rest/v1/login_attempts", _sin_red)
        assert client.post("/auth/password", json={"password": "1234"}).status_code == 200
        assert client.post("/auth/password", json={"password": "mala"}).status_code == 401

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

    # ── Caché: Distance Matrix se paga por petición, y el widget «Lo siguiente» y las
    # reglas de salida la piden solas. Dos peticiones iguales seguidas son una sola.

    def _pedir(self, client, auth_headers, **cambios):
        cuerpo = {"destination": "Universidad de Deusto, Bilbao",
                  "event_time": "2026-07-06T10:00:00+02:00", "origin": "43.26311,-2.93511"}
        cuerpo.update(cambios)
        return client.post("/maps/departure", headers=auth_headers, json=cuerpo)

    def test_dos_peticiones_iguales_llaman_una_vez_a_maps(self, client, auth_headers, mock_requests):
        mock_requests.add("GET", "maps.googleapis.com", self._maps_response())
        r1 = self._pedir(client, auth_headers)
        r2 = self._pedir(client, auth_headers)
        assert r1.status_code == r2.status_code == 200
        assert r1.json() == r2.json()
        assert len(mock_requests.called("GET", "maps.googleapis.com")) == 1

    def test_el_destino_no_distingue_mayusculas_ni_espacios(self, client, auth_headers, mock_requests):
        mock_requests.add("GET", "maps.googleapis.com", self._maps_response())
        self._pedir(client, auth_headers)
        self._pedir(client, auth_headers, destination="  universidad de deusto, BILBAO ")
        assert len(mock_requests.called("GET", "maps.googleapis.com")) == 1

    def test_otro_modo_destino_u_hora_vuelve_a_llamar(self, client, auth_headers, mock_requests):
        mock_requests.add("GET", "maps.googleapis.com", self._maps_response())
        self._pedir(client, auth_headers)
        cambios = [{"mode": "walking"}, {"destination": "Gimnasio"},
                   {"event_time": "2026-07-06T11:00:00+02:00"}]
        for n, cambio in enumerate(cambios, start=2):
            self._pedir(client, auth_headers, **cambio)
            assert len(mock_requests.called("GET", "maps.googleapis.com")) == n, cambio

    def test_origenes_que_redondean_igual_comparten_entrada(self, client, auth_headers, mock_requests):
        # La geolocalización del navegador baila unos metros entre cargas sin que te
        # hayas movido: a 3 decimales (~110 m) es la misma ruta, y a Google se le manda
        # ya redondeado.
        mock_requests.add("GET", "maps.googleapis.com", self._maps_response())
        self._pedir(client, auth_headers, origin="43.26311,-2.93511")
        self._pedir(client, auth_headers, origin="43.26349,-2.93549")
        llamadas = mock_requests.called("GET", "maps.googleapis.com")
        assert len(llamadas) == 1
        assert llamadas[0][2]["params"]["origins"] == "43.263,-2.935"

    def test_un_origen_de_texto_no_se_toca(self):
        assert main._origen_normalizado("  Calle Falsa 123, Bilbao ") == "Calle Falsa 123, Bilbao"
        assert main._origen_normalizado("-43.26311, +2.93511") == "-43.263,2.935"

    def test_un_fallo_no_se_cachea(self, client, auth_headers, mock_requests):
        # Si se cacheara, el ↺ del dashboard no podría reintentar en diez minutos.
        mock_requests.add("GET", "maps.googleapis.com", FakeResponse({
            "rows": [{"elements": [{"status": "NOT_FOUND"}]}]
        }))
        assert self._pedir(client, auth_headers).status_code == 400
        assert self._pedir(client, auth_headers).status_code == 400
        assert len(mock_requests.called("GET", "maps.googleapis.com")) == 2

    def test_pasados_diez_minutos_vuelve_a_llamar(self, client, auth_headers, mock_requests, monkeypatch):
        mock_requests.add("GET", "maps.googleapis.com", self._maps_response())
        self._pedir(client, auth_headers)
        real = main.time.time
        monkeypatch.setattr(main.time, "time", lambda: real() + main.SALIDA_CACHE_S + 1)
        self._pedir(client, auth_headers)
        assert len(mock_requests.called("GET", "maps.googleapis.com")) == 2

    def test_la_caché_no_crece_sin_límite(self, monkeypatch):
        monkeypatch.setattr(main, "SALIDA_CACHE_MAX", 3)
        for i in range(5):
            main._cachear_salida((f"destino {i}",), {"i": i})
        assert len(main._salida_cache) == 3
        assert ("destino 0",) not in main._salida_cache
        assert ("destino 4",) in main._salida_cache

    def test_devuelve_una_copia_y_no_la_entrada(self, client, auth_headers, mock_requests):
        mock_requests.add("GET", "maps.googleapis.com", self._maps_response())
        self._pedir(client, auth_headers)
        clave = next(iter(main._salida_cache))
        main._salida_cacheada(clave)["departure_time"] = "trampa"
        assert main._salida_cacheada(clave)["departure_time"] == "09:20"

    def test_el_origen_dice_de_donde_sale(self, client, auth_headers, mock_requests):
        mock_requests.add("GET", "maps.googleapis.com", self._maps_response())
        assert self._pedir(client, auth_headers).json()["origen"] == "dispositivo"


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
        mock_requests.add("POST", "/rest/v1/ideas", FakeResponse([{"id": "i1"}], 201))
        main.save_idea("x" * 100, {})
        enviado = mock_requests.called("POST", "/rest/v1/ideas")[0][2]["json"]
        assert enviado["key"] == "x" * 60      # default: primeros 60 chars del texto
        assert enviado["tag"] == "idea"
        assert enviado["full_text"] == "x" * 100

    def test_si_supabase_no_la_guarda_no_se_dice_que_se_guardo(self, client, auth_headers,
                                                               mock_requests, monkeypatch):
        """Antes se devolvía el payload local con ok:true: la idea salía en pantalla sin
        id, no se podía borrar y al recargar ya no existía."""
        monkeypatch.setattr(main, "extract_idea_from_text", lambda t: {"key": "k"})
        mock_requests.add("POST", "/rest/v1/ideas", FakeResponse(None, 401, "clave rotada"))
        r = client.post("/ideas/text", headers=auth_headers, json={"text": "comprar leche"})
        assert r.status_code == 502
        assert "clave rotada" not in r.text
        # Y Jarvis tampoco contesta «guardada».
        assert "ok" not in main._jarvis_despachar("guardar_idea", {"texto": "comprar leche"})

    def test_la_nota_de_voz_no_se_pierde_si_no_se_guarda(self, client, auth_headers,
                                                         mock_requests, monkeypatch):
        """Whisper ya se ha cobrado y el audio no se guarda: la transcripción vuelve en
        el error para que quien grabó no tenga que repetirlo."""
        class _Whisper:
            audio = transcriptions = property(lambda self: self)

            def create(self, **kw):
                return type("T", (), {"text": "llamar al fontanero"})()

        monkeypatch.setattr(main, "get_openai_client", lambda: _Whisper())
        monkeypatch.setattr(main, "extract_idea_from_text", lambda t: {"key": "k"})
        mock_requests.add("POST", "/rest/v1/ideas", FakeResponse(None, 503, "caído"))
        r = client.post("/ideas/audio", headers=auth_headers,
                        files={"audio": ("a.webm", b"xxxx", "audio/webm")})
        assert r.status_code == 502
        assert r.json()["detail"]["transcript"] == "llamar al fontanero"

    def test_borrar_con_supabase_caido_no_dice_ok(self, client, auth_headers, mock_requests):
        """Jarvis confirmaba el borrado aunque la nota siguiera ahí."""
        mock_requests.add("DELETE", "/rest/v1/ideas", FakeResponse(None, 503, "caído"))
        ident = "123e4567-e89b-12d3-a456-426614174000"
        assert client.delete(f"/ideas/{ident}", headers=auth_headers).status_code == 502
        r = client.post("/jarvis/ejecutar", headers=auth_headers,
                        json={"herramienta": "borrar_idea", "argumentos": {"idea_id": ident}})
        assert r.json()["ok"] is False


class TestExport:
    def test_requiere_token(self, client):
        assert client.get("/export").status_code in (401, 403)

    def test_agrupa_cada_tabla_en_su_clave(self, client, auth_headers, mock_requests):
        mock_requests.add("GET", "/rest/v1/ideas", FakeResponse([{"id": "i1"}]))
        mock_requests.add("GET", "/rest/v1/training_clients", FakeResponse([{"id": "c1"}]))
        mock_requests.add("GET", "/rest/v1/training_sessions", FakeResponse([{"id": "s1"}]))
        mock_requests.add("GET", "/rest/v1/training_payments", FakeResponse([{"id": "p1"}]))
        mock_requests.add("GET", "/rest/v1/health_metrics", FakeResponse([{"id": "h1"}]))
        mock_requests.add("GET", "/rest/v1/clothing", FakeResponse([{"id": "r1"}]))
        r = client.get("/export", headers=auth_headers)
        assert r.status_code == 200
        data = r.json()
        assert data["ideas"] == [{"id": "i1"}]
        assert data["training_clients"] == [{"id": "c1"}]
        assert data["training_sessions"] == [{"id": "s1"}]
        assert data["training_payments"] == [{"id": "p1"}]
        assert data["health_metrics"] == [{"id": "h1"}]
        assert data["clothing"] == [{"id": "r1"}]
        assert "exported_at" in data

    def test_la_copia_trae_mas_de_las_mil_filas_que_corta_supabase(
            self, client, auth_headers, mock_requests):
        """El `limit=100000` lo ignoraba Supabase: la copia de `health_metrics` traía los
        ~25 días más recientes y el resto del histórico faltaba sin aviso."""
        filas = [{"metric_date": "2026-09-01", "metric_name": f"m{i:04d}"} for i in range(2345)]

        def _con_tope(url, **kwargs):
            offset = int(url.split("offset=")[1].split("&")[0]) if "offset=" in url else 0
            lote = filas[offset:offset + 1000]
            return FakeResponse(lote, headers={
                "Content-Range": f"{offset}-{offset + len(lote) - 1}/{len(filas)}"})
        mock_requests.add("GET", "/rest/v1/health_metrics", _con_tope)
        r = client.get("/export", headers=auth_headers)
        assert r.status_code == 200
        assert len(r.json()["health_metrics"]) == 2345

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
    assert r.json()["status"] == "Life Assistant API running"


def test_root_dice_que_codigo_corre(client, tmp_path, monkeypatch):
    """Reconstruir el add-on no cambia nada visible, así que una reconstrucción que no
    trajo el código nuevo se parece a una que sí. `GET /` es la única forma de saberlo
    sin entrar en el Green; en local no hay fichero VERSION y responde "desconocida"."""
    assert client.get("/").json()["version"] == "desconocida"

    sha = "a" * 40
    (tmp_path / "VERSION").write_text(sha + "\n", encoding="utf-8")
    monkeypatch.setattr(main.os.path, "dirname", lambda _: str(tmp_path))
    assert client.get("/").json()["version"] == sha


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
