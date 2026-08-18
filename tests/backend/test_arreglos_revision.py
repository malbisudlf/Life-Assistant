"""Tests de los cuatro arreglos salidos de la revisión de `backend/main.py` (2026-08-18).

- El bloqueo progresivo del login: estaba documentado en tres sitios y no existía en el
  código. Eran 5 intentos cada 5 minutos, planos y para siempre.
- `verify_token` aceptaba cualquier JWT firmado con SECRET_KEY, incluido el `state` de
  OAuth — que viaja en la URL de vuelta de Microsoft y queda en el historial.
- Una renovación de Graph sin `refresh_token` sobrescribía el bueno con NULL y dejaba
  el calendario muerto hasta rehacer /auth/login a mano.
- Los interruptores booleanos no normalizaban el valor: `FALSE`, `no` u `off` dejaban
  la función encendida.
"""
from datetime import datetime, timedelta, timezone

from jose import jwt as jose_jwt

import main
from conftest import FakeResponse


def _hace(segundos: int) -> str:
    return (datetime.now(timezone.utc) - timedelta(seconds=segundos)).isoformat()


class TestBloqueoProgresivoDelLogin:
    """`_check_login_rate`: cada tanda de fallos dobla la espera, con techo."""

    def test_por_debajo_del_limite_se_deja_pasar(self, client, login_attempts_mock):
        login_attempts_mock.extend(_hace(10) for _ in range(main.LOGIN_MAX_ATTEMPTS - 1))
        assert client.post("/auth/password", json={"password": "1234"}).status_code == 200

    def test_la_primera_tanda_bloquea_una_ventana(self, client, login_attempts_mock):
        login_attempts_mock.extend(_hace(10) for _ in range(main.LOGIN_MAX_ATTEMPTS))
        r = client.post("/auth/password", json={"password": "1234"})
        assert r.status_code == 429
        # Una ventana desde el ÚLTIMO fallo, no desde el primero.
        assert 0 < int(r.headers["Retry-After"]) <= main.LOGIN_WINDOW_SECONDS

    def test_la_segunda_tanda_dobla_la_espera(self, client, login_attempts_mock):
        """Este es el agujero que existía: con la ventana plana, aguantar 300s devolvía
        otros cinco intentos indefinidamente — 1.440 al día contra la contraseña."""
        login_attempts_mock.extend(_hace(400) for _ in range(main.LOGIN_MAX_ATTEMPTS * 2))
        r = client.post("/auth/password", json={"password": "1234"})
        assert r.status_code == 429, "a los 400s la segunda tanda todavía debe estar bloqueada"
        # Dos tandas = 600s de bloqueo contados desde el último fallo; han pasado 400,
        # así que quedan ~200. La banda es estrecha a propósito: el cálculo viejo
        # también devolvía 429 aquí, pero con un Retry-After de 1s (la resta le salía
        # negativa y la tapaba un max(retry, 1)), y ese es el bloqueo que no existía.
        assert 150 <= int(r.headers["Retry-After"]) <= 200

    def test_la_espera_tiene_techo(self, client, login_attempts_mock, monkeypatch):
        monkeypatch.setattr(main, "LOGIN_BLOQUEO_MAX_SECONDS", 3600)
        login_attempts_mock.extend(_hace(10) for _ in range(main.LOGIN_MAX_ATTEMPTS * 20))
        r = client.post("/auth/password", json={"password": "1234"})
        assert r.status_code == 429
        assert int(r.headers["Retry-After"]) <= 3600

    def test_cumplido_el_bloqueo_se_puede_reintentar(self, client, login_attempts_mock):
        """Una tanda cuyo último fallo es más viejo que su bloqueo ya no retiene a nadie."""
        login_attempts_mock.extend(
            _hace(main.LOGIN_WINDOW_SECONDS + 60) for _ in range(main.LOGIN_MAX_ATTEMPTS)
        )
        assert client.post("/auth/password", json={"password": "1234"}).status_code == 200

    def test_acertar_borra_el_castigo_acumulado(self, client, login_attempts_mock):
        """Al usuario legítimo que se equivocó de tecla no le persigue el bloqueo."""
        login_attempts_mock.extend(
            _hace(main.LOGIN_WINDOW_SECONDS + 60) for _ in range(main.LOGIN_MAX_ATTEMPTS)
        )
        assert client.post("/auth/password", json={"password": "1234"}).status_code == 200
        assert login_attempts_mock == []

    def test_si_supabase_no_responde_se_deja_pasar(self, client, mock_requests):
        """Fail-open deliberado: poder entrar aunque la BD esté caída vale más que
        blindar una ventana de fallo de infraestructura poco probable."""
        mock_requests.add("GET", "/rest/v1/login_attempts", FakeResponse([], 500))
        assert client.post("/auth/password", json={"password": "1234"}).status_code == 200


class TestElStateDeOauthNoEsUnaCredencial:
    """`verify_token` comprobaba solo la firma, y el state se firma con la misma clave."""

    def test_el_state_no_abre_endpoints_de_usuario(self, client):
        state = main._create_oauth_state()
        r = client.get("/calendar/events", headers={"Authorization": f"Bearer {state}"})
        assert r.status_code == 401, "el state de OAuth no puede valer como sesión"

    def test_el_state_tampoco_vale_en_los_endpoints_del_agente(self, client):
        state = main._create_oauth_state()
        r = client.get("/jobs/pending", headers={"Authorization": f"Bearer {state}"})
        assert r.status_code == 401

    def test_cualquier_token_con_proposito_se_rechaza(self, client):
        ajeno = jose_jwt.encode(
            {"exp": datetime.now(timezone.utc) + timedelta(hours=1), "purpose": "lo-que-sea"},
            "test-secret-key", algorithm="HS256",
        )
        r = client.get("/calendar/events", headers={"Authorization": f"Bearer {ajeno}"})
        assert r.status_code == 401

    def test_el_token_del_dashboard_sigue_valiendo(self, client, graph_token, mock_requests):
        """El arreglo no puede echar de la sesión a los tokens ya emitidos (30 días),
        que no llevan `purpose`."""
        mock_requests.add("GET", "graph.microsoft.com", FakeResponse({"value": []}))
        r = client.get("/calendar/events",
                       headers={"Authorization": f"Bearer {main.create_token()}"})
        assert r.status_code == 200


class TestElRefreshTokenNoSePierde:
    """Un refresh sin `refresh_token` nuevo no puede borrar el que ya había."""

    def _rutas(self, mock_requests, guardado):
        mock_requests.add("GET", "/rest/v1/oauth_tokens", FakeResponse([guardado]))
        mock_requests.add("PATCH", "/rest/v1/oauth_tokens", FakeResponse([], 204))
        mock_requests.add("POST", "/rest/v1/oauth_tokens", FakeResponse([], 201))

    def test_se_conserva_el_anterior_si_la_renovacion_no_trae_uno(self, mock_requests, monkeypatch):
        monkeypatch.setattr(main, "_token_cache", None, raising=False)
        self._rutas(mock_requests, {
            "access_token": "viejo", "refresh_token": "ref-bueno", "expires_at": 0,
        })
        main.save_token_data({"access_token": "nuevo", "expires_at": 1})
        escrito = mock_requests.called("PATCH", "/rest/v1/oauth_tokens")[0][2]["json"]
        assert escrito["refresh_token"] == "ref-bueno", "se ha pisado el refresh token con None"

    def test_si_la_renovacion_trae_uno_nuevo_se_rota(self, mock_requests, monkeypatch):
        monkeypatch.setattr(main, "_token_cache", None, raising=False)
        self._rutas(mock_requests, {
            "access_token": "viejo", "refresh_token": "ref-bueno", "expires_at": 0,
        })
        main.save_token_data({
            "access_token": "nuevo", "refresh_token": "ref-nuevo", "expires_at": 1,
        })
        escrito = mock_requests.called("PATCH", "/rest/v1/oauth_tokens")[0][2]["json"]
        assert escrito["refresh_token"] == "ref-nuevo"


class TestFlagsBooleanos:
    """`_flag`: los interruptores existen para APAGAR algo, así que tienen que apagarlo."""

    def test_las_formas_de_apagar(self, monkeypatch):
        for valor in ("0", "false", "False", "FALSE", "no", "NO", "off", "Off", ""):
            monkeypatch.setenv("PRUEBA_FLAG", valor)
            assert main._flag("PRUEBA_FLAG") is False, f"{valor!r} debería apagar"

    def test_las_formas_de_encender(self, monkeypatch):
        for valor in ("1", "true", "True", "yes", "on", "sí"):
            monkeypatch.setenv("PRUEBA_FLAG", valor)
            assert main._flag("PRUEBA_FLAG") is True, f"{valor!r} debería encender"

    def test_los_espacios_no_encienden_nada(self, monkeypatch):
        monkeypatch.setenv("PRUEBA_FLAG", "  false  ")
        assert main._flag("PRUEBA_FLAG") is False

    def test_el_defecto_manda_si_no_esta_definida(self, monkeypatch):
        monkeypatch.delenv("PRUEBA_FLAG", raising=False)
        assert main._flag("PRUEBA_FLAG") is True
        assert main._flag("PRUEBA_FLAG", "0") is False
