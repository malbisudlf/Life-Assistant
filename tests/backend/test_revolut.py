"""Tests del saldo de Revolut vía Enable Banking (open banking, PSD2).

A diferencia de Indexa no hay un token fijo que mockear: hay que dar de alta una sesión
(login → callback → GET /sessions/{id} → GET /accounts/{uid}/details|balances). La firma
del JWT de aplicación se sustituye (`_enable_banking_jwt`) porque probar la lógica
alrededor no necesita una clave RSA real — eso ya lo prueba `python-jose` por su cuenta.

Las respuestas simuladas copian la forma real de la API, no la que documenta Enable
Banking públicamente: `accounts` en `POST/GET /sessions...` es una lista de UIDs
(string), no de objetos con `name`/`currency` — se comprobó contra la API de verdad y
costó un 500 en su momento. Si esa forma cambiara, es este fichero el que se entera
primero.
"""
import pytest
from conftest import FakeResponse

import main


@pytest.fixture
def enable_banking(monkeypatch):
    """App de Enable Banking configurada; la firma del JWT se sustituye por una fija."""
    monkeypatch.setattr(main, "ENABLE_BANKING_APPLICATION_ID", "app-test-id")
    monkeypatch.setattr(main, "ENABLE_BANKING_PRIVATE_KEY_PATH", "fake.pem")
    monkeypatch.setattr(main, "ENABLE_BANKING_ASPSP_NAME", "Revolut")
    monkeypatch.setattr(main, "ENABLE_BANKING_ASPSP_COUNTRY", "ES")
    monkeypatch.setattr(main, "ENABLE_BANKING_REDIRECT_URL", "https://backend.test/auth/enablebanking/callback")
    monkeypatch.setattr(main, "_enable_banking_jwt", lambda: "fake-jwt")
    return None


def _sesion_guardada(expires_at):
    return FakeResponse([{"access_token": "session-abc", "expires_at": expires_at}])


class TestRevolutSinConectar:
    def test_sin_configurar_no_es_un_error(self, client, auth_headers, mock_requests):
        # Enable Banking no está configurado en el backend: ni siquiera se sale a la red.
        r = client.get("/finanzas/resumen", headers=auth_headers)
        assert r.json()["revolut"] == {
            "configurado": False,
            "motivo": "Enable Banking no configurado en el backend",
        }
        assert mock_requests.called("GET", "enablebanking.com") == []

    def test_configurado_pero_sin_sesion(self, client, auth_headers, mock_requests, enable_banking):
        # Sin fila en oauth_tokens, el MockRouter devuelve [] por defecto: "no hay sesión".
        revolut = client.get("/finanzas/resumen", headers=auth_headers).json()["revolut"]
        assert revolut["configurado"] is False
        assert "Ninguna cuenta conectada" in revolut["motivo"]

    def test_sesion_caducada(self, client, auth_headers, mock_requests, enable_banking):
        mock_requests.add("GET", "provider=eq.enablebanking_revolut", _sesion_guardada(expires_at=1.0))
        revolut = client.get("/finanzas/resumen", headers=auth_headers).json()["revolut"]
        assert revolut["configurado"] is False
        assert "caducado" in revolut["motivo"]
        # Con la sesión caducada no hace falta preguntarle nada más a Enable Banking.
        assert mock_requests.called("GET", "/sessions/") == []


class TestRevolutLogin:
    def test_requiere_jwt(self, client):
        assert client.get("/auth/enablebanking/login").status_code in (401, 403)

    def test_sin_configurar_da_503(self, client, auth_headers):
        r = client.get("/auth/enablebanking/login", headers=auth_headers)
        assert r.status_code == 503

    def test_pide_autorizacion_con_state_firmado(self, client, auth_headers, mock_requests, enable_banking):
        capturado = {}

        def _auth(url, **kwargs):
            capturado["body"] = kwargs["json"]
            return FakeResponse({"url": "https://tilisy.enablebanking.com/ais/start?sessionid=x"})

        mock_requests.add("POST", "api.enablebanking.com/auth", _auth)
        r = client.get("/auth/enablebanking/login", headers=auth_headers)
        assert r.status_code == 200
        assert r.json()["auth_url"] == "https://tilisy.enablebanking.com/ais/start?sessionid=x"
        # El state es el mismo mecanismo firmado que usa Microsoft Graph: sin esto,
        # cualquiera que supiera la URL podía completar SU PROPIO consentimiento.
        assert main._verify_oauth_state(capturado["body"]["state"])
        assert capturado["body"]["aspsp"] == {"name": "Revolut", "country": "ES"}
        assert capturado["body"]["psu_type"] == "personal"

    def test_fallo_de_enable_banking_da_502(self, client, auth_headers, mock_requests, enable_banking):
        mock_requests.add("POST", "api.enablebanking.com/auth", FakeResponse({}, 400, text="Redirect URI not allowed"))
        r = client.get("/auth/enablebanking/login", headers=auth_headers)
        assert r.status_code == 502
        # El detalle de Enable Banking no se reenvía al cliente (mismo criterio que Indexa).
        assert "Redirect URI" not in r.text


class TestRevolutCallback:
    def test_completa_el_flujo_y_guarda_la_sesion(self, client, mock_requests, enable_banking):
        mock_requests.add("POST", "api.enablebanking.com/sessions", FakeResponse({
            "session_id": "session-nueva",
            "accounts": ["uid-1"],
            "access": {"valid_until": "2027-02-19T21:47:55Z"},
        }))
        estado = main._create_oauth_state()
        r = client.get("/auth/enablebanking/callback", params={"code": "abc", "state": estado})
        assert r.status_code == 200
        assert r.json() == {"status": "ok", "message": "Cuenta de Revolut conectada", "cuentas": 1}
        guardado = mock_requests.called("POST", "/rest/v1/oauth_tokens")
        assert guardado
        payload = guardado[0][2]["json"]
        assert payload["provider"] == "enablebanking_revolut"
        assert payload["access_token"] == "session-nueva"
        assert payload["refresh_token"] is None   # no se renueva sola, a diferencia de Graph

    def test_fallo_al_canjear_el_codigo_da_502(self, client, mock_requests, enable_banking):
        mock_requests.add("POST", "api.enablebanking.com/sessions", FakeResponse({}, 400, text="invalid_grant"))
        estado = main._create_oauth_state()
        r = client.get("/auth/enablebanking/callback", params={"code": "abc", "state": estado})
        assert r.status_code == 502
        assert "invalid_grant" not in r.text


class TestRevolutSaldo:
    @pytest.fixture
    def conectado(self, mock_requests, enable_banking):
        mock_requests.add("GET", "provider=eq.enablebanking_revolut", _sesion_guardada(expires_at=99999999999.0))
        mock_requests.add("GET", "api.enablebanking.com/sessions/session-abc", FakeResponse({
            "status": "AUTHORIZED", "accounts": ["uid-1"],
        }))
        mock_requests.add("GET", "/accounts/uid-1/details", FakeResponse({
            "uid": "uid-1", "name": "Mikel Albisu De La Fuente", "currency": "EUR",
        }))
        mock_requests.add("GET", "/accounts/uid-1/balances", FakeResponse({
            "balances": [{
                "name": "Available balance", "balance_type": "ITAV",
                "balance_amount": {"currency": "EUR", "amount": "79.70"},
            }],
        }))
        return mock_requests

    def test_lee_el_saldo_disponible(self, client, auth_headers, conectado):
        revolut = client.get("/finanzas/resumen", headers=auth_headers).json()["revolut"]
        assert revolut == {
            "configurado": True, "saldo": 79.7, "moneda": "EUR",
            "cuentas": [{"nombre": "Mikel Albisu De La Fuente", "moneda": "EUR", "saldo": 79.7}],
        }

    def test_prefiere_el_saldo_disponible_sobre_el_contable(self, client, auth_headers, mock_requests, enable_banking):
        mock_requests.add("GET", "provider=eq.enablebanking_revolut", _sesion_guardada(expires_at=99999999999.0))
        mock_requests.add("GET", "api.enablebanking.com/sessions/session-abc", FakeResponse({"accounts": ["uid-1"]}))
        mock_requests.add("GET", "/accounts/uid-1/details", FakeResponse({"name": "Cuenta", "currency": "EUR"}))
        mock_requests.add("GET", "/accounts/uid-1/balances", FakeResponse({
            "balances": [
                {"balance_type": "CLAV", "balance_amount": {"currency": "EUR", "amount": "100.00"}},
                {"balance_type": "ITAV", "balance_amount": {"currency": "EUR", "amount": "79.70"}},
            ],
        }))
        revolut = client.get("/finanzas/resumen", headers=auth_headers).json()["revolut"]
        assert revolut["saldo"] == 79.7

    def test_suma_varias_cuentas(self, client, auth_headers, mock_requests, enable_banking):
        mock_requests.add("GET", "provider=eq.enablebanking_revolut", _sesion_guardada(expires_at=99999999999.0))
        mock_requests.add("GET", "api.enablebanking.com/sessions/session-abc", FakeResponse({
            "accounts": ["uid-1", "uid-2"],
        }))

        def _details(url, **kwargs):
            uid = "uid-1" if "uid-1" in url else "uid-2"
            return FakeResponse({"name": f"Cuenta {uid}", "currency": "EUR"})

        def _balances(url, **kwargs):
            monto = "50.00" if "uid-1" in url else "30.00"
            return FakeResponse({"balances": [{"balance_type": "ITAV",
                                                "balance_amount": {"currency": "EUR", "amount": monto}}]})

        mock_requests.add("GET", "/details", _details)
        mock_requests.add("GET", "/balances", _balances)
        revolut = client.get("/finanzas/resumen", headers=auth_headers).json()["revolut"]
        assert revolut["saldo"] == 80.0
        assert len(revolut["cuentas"]) == 2

    def test_fallo_al_consultar_la_sesion_no_es_un_502(self, client, auth_headers, mock_requests, enable_banking):
        # A diferencia de Indexa, un fallo aquí no corta el widget entero (que sigue
        # enseñando la cartera de Indexa si la hay): se dice que no se pudo consultar.
        mock_requests.add("GET", "provider=eq.enablebanking_revolut", _sesion_guardada(expires_at=99999999999.0))
        mock_requests.add("GET", "api.enablebanking.com/sessions/session-abc", FakeResponse({}, 500))
        r = client.get("/finanzas/resumen", headers=auth_headers)
        assert r.status_code == 200
        assert r.json()["revolut"] == {"configurado": False, "motivo": "No se pudo consultar Revolut"}


class TestRevolutCache:
    @pytest.fixture
    def conectado(self, mock_requests, enable_banking):
        mock_requests.add("GET", "provider=eq.enablebanking_revolut", _sesion_guardada(expires_at=99999999999.0))
        mock_requests.add("GET", "api.enablebanking.com/sessions/session-abc", FakeResponse({"accounts": ["uid-1"]}))
        mock_requests.add("GET", "/details", FakeResponse({"name": "Cuenta", "currency": "EUR"}))
        mock_requests.add("GET", "/balances", FakeResponse({
            "balances": [{"balance_type": "ITAV", "balance_amount": {"currency": "EUR", "amount": "10.00"}}],
        }))
        return mock_requests

    def test_la_segunda_carga_no_vuelve_a_preguntar(self, client, auth_headers, conectado):
        client.get("/finanzas/resumen", headers=auth_headers)
        llamadas = len(conectado.called("GET", "api.enablebanking.com"))
        client.get("/finanzas/resumen", headers=auth_headers)
        assert len(conectado.called("GET", "api.enablebanking.com")) == llamadas

    def test_refrescar_salta_la_cache(self, client, auth_headers, conectado):
        client.get("/finanzas/resumen", headers=auth_headers)
        llamadas = len(conectado.called("GET", "api.enablebanking.com"))
        client.get("/finanzas/resumen?refrescar=true", headers=auth_headers)
        assert len(conectado.called("GET", "api.enablebanking.com")) > llamadas

    def test_la_cache_caduca(self, client, auth_headers, conectado, monkeypatch):
        monkeypatch.setattr(main, "ENABLE_BANKING_TTL_MINUTOS", 0)
        client.get("/finanzas/resumen", headers=auth_headers)
        llamadas = len(conectado.called("GET", "api.enablebanking.com"))
        client.get("/finanzas/resumen", headers=auth_headers)
        assert len(conectado.called("GET", "api.enablebanking.com")) > llamadas


class TestFinanzasResumenIncluyeRevolutSiempre:
    def test_sin_indexa_configurado_revolut_sigue_saliendo(self, client, auth_headers, mock_requests, monkeypatch, enable_banking):
        monkeypatch.setattr(main, "INDEXA_TOKEN", "")
        mock_requests.add("GET", "provider=eq.enablebanking_revolut", _sesion_guardada(expires_at=99999999999.0))
        mock_requests.add("GET", "api.enablebanking.com/sessions/session-abc", FakeResponse({"accounts": []}))
        datos = client.get("/finanzas/resumen", headers=auth_headers).json()
        assert datos["configurado"] is False       # Indexa sigue sin estar
        assert datos["revolut"]["configurado"] is True   # pero Revolut sí


class TestRevolutJarvis:
    def test_saldo_disponible_para_jarvis(self, mock_requests, enable_banking, monkeypatch):
        monkeypatch.setattr(main, "INDEXA_TOKEN", "")
        mock_requests.add("GET", "provider=eq.enablebanking_revolut", _sesion_guardada(expires_at=99999999999.0))
        mock_requests.add("GET", "api.enablebanking.com/sessions/session-abc", FakeResponse({"accounts": ["uid-1"]}))
        mock_requests.add("GET", "/details", FakeResponse({"name": "Cuenta", "currency": "EUR"}))
        mock_requests.add("GET", "/balances", FakeResponse({
            "balances": [{"balance_type": "ITAV", "balance_amount": {"currency": "EUR", "amount": "79.70"}}],
        }))
        datos = main._j_finanzas()
        assert datos["ahorro_revolut"] == {"saldo": 79.7, "moneda": "EUR"}

    def test_sin_conectar_va_a_none_no_a_cero(self, monkeypatch):
        monkeypatch.setattr(main, "INDEXA_TOKEN", "")
        assert main._j_finanzas()["ahorro_revolut"] is None
