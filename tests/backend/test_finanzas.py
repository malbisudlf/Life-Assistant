"""Tests del módulo de finanzas (Indexa Capital).

Todo va contra el MockRouter: los tests no hablan con Indexa ni necesitan un token real.
Las respuestas simuladas copian la forma de la API de verdad (`instrument_accounts` →
`positions`, `return.total_amounts`…), que es justo lo que hay que fijar aquí: si esa
forma cambiara, es este fichero el que tiene que enterarse primero.
"""
import pytest
from conftest import FakeResponse

import main


USERS_ME = {
    "accounts": [
        {"account_number": "ABC12345", "type": "mutual",  "status": "active"},
        # Cuenta a medio contratar: no tiene posiciones y se omite (diciéndolo).
        {"account_number": "PEN99999", "type": "pension", "status": "pending-contract"},
    ],
}

PORTFOLIO = {
    "portfolio": {"total_amount": 12500.0, "cash_amount": 250.0},
    "instrument_accounts": [{
        "positions": [
            {
                "instrument": {
                    "name": "Vanguard Global Stock Index Fund",
                    "isin_code": "IE00B03HCZ61",
                    "identifier_name": "ISIN",
                    "asset_class": "equity_world",
                    "management_company_description": "Vanguard",
                },
                "amount": 9000.0, "cost_amount": 7500.0,
                "titles": 300.0, "price": 30.0, "date": "2026-08-21",
            },
            {
                "instrument": {
                    "name": "Vanguard Euro Government Bond Index",
                    "isin_code": "IE00B04GQR24",
                    "identifier_name": "ISIN",
                    "asset_class": "fixed_euro",
                    "management_company_description": "Vanguard",
                },
                "amount": 3250.0, "cost_amount": 3300.0,
                "titles": 200.0, "price": 16.25, "date": "2026-08-21",
            },
        ],
    }],
}

PERFORMANCE = {
    "return": {
        "total_amount": 12500.0,
        "investment": 11000.0,
        "pl": 1500.0,
        "time_return": 0.1364,
        "time_return_annual": 0.0712,
        "volatility": 0.0891,
        "total_amounts": {"2026-08-19": 12300.0, "2026-08-20": 12400.0, "2026-08-21": 12500.0},
        "net_amounts":   {"2026-08-19": 11000.0, "2026-08-20": 11000.0, "2026-08-21": 11000.0},
    },
    "plan_expected_return": 0.0521,
}


@pytest.fixture
def indexa(monkeypatch, mock_requests):
    """Token puesto y las tres llamadas de la API respondiendo bien."""
    monkeypatch.setattr(main, "INDEXA_TOKEN", "indexa-test-token")
    monkeypatch.setattr(main, "INDEXA_CUENTAS", [])
    mock_requests.add("GET", "/users/me", FakeResponse(USERS_ME))
    mock_requests.add("GET", "/accounts/ABC12345/portfolio", FakeResponse(PORTFOLIO))
    mock_requests.add("GET", "/accounts/ABC12345/performance", FakeResponse(PERFORMANCE))
    return mock_requests


class TestFinanzasAuth:
    def test_requiere_jwt(self, client):
        assert client.get("/finanzas/resumen").status_code in (401, 403)

    def test_sin_token_no_es_un_error(self, client, auth_headers, mock_requests, monkeypatch):
        # Una integración que no está puesta no es un fallo: se dice que no está.
        monkeypatch.setattr(main, "INDEXA_TOKEN", "")
        r = client.get("/finanzas/resumen", headers=auth_headers)
        assert r.status_code == 200
        assert r.json()["configurado"] is False
        # Y no se sale a la red a comprobarlo.
        assert mock_requests.called("GET", "indexacapital.com") == []


class TestFinanzasResumen:
    def test_agrega_valor_aportado_y_plusvalia(self, client, auth_headers, indexa):
        datos = client.get("/finanzas/resumen", headers=auth_headers).json()
        assert datos["configurado"] is True
        assert len(datos["cuentas"]) == 1
        cuenta = datos["cuentas"][0]
        assert cuenta["numero"] == "ABC12345"
        assert cuenta["tipo"] == "mutual"
        assert cuenta["valor"] == 12500.0
        assert cuenta["efectivo"] == 250.0
        assert cuenta["aportado"] == 11000.0
        assert cuenta["plusvalia"] == 1500.0
        assert cuenta["plusvalia_origen"] == "cuenta"
        assert cuenta["plusvalia_pct"] == pytest.approx(13.64, abs=0.01)
        assert cuenta["rentabilidad_anual"] == 0.0712
        assert datos["total"] == {
            "valor": 12500.0, "aportado": 11000.0, "plusvalia": 1500.0,
            "plusvalia_pct": pytest.approx(13.64, abs=0.01), "completo": True,
        }

    def test_reparte_por_clase_de_activo(self, client, auth_headers, indexa):
        cuenta = client.get("/finanzas/resumen", headers=auth_headers).json()["cuentas"][0]
        # El efectivo sin invertir va en su propia clase, no con los monetarios.
        assert cuenta["distribucion"] == {"acciones": 9000.0, "bonos": 3250.0, "efectivo": 250.0}
        assert sum(cuenta["distribucion"].values()) == cuenta["valor"]

    def test_posiciones_ordenadas_y_con_su_plusvalia(self, client, auth_headers, indexa):
        posiciones = client.get("/finanzas/resumen", headers=auth_headers).json()["cuentas"][0]["posiciones"]
        assert [p["valor"] for p in posiciones] == [9000.0, 3250.0]
        assert posiciones[0]["identificador"] == "IE00B03HCZ61"
        assert posiciones[0]["clase"] == "acciones"
        assert posiciones[0]["plusvalia"] == 1500.0
        assert posiciones[1]["plusvalia"] == -50.0     # una posición en pérdidas se ve

    def test_dice_a_que_dia_corresponden_los_valores(self, client, auth_headers, indexa):
        # Indexa valora una vez al día y con retraso: sin la fecha, una cartera de hace
        # tres días se lee como la de hoy.
        cuenta = client.get("/finanzas/resumen", headers=auth_headers).json()["cuentas"][0]
        assert cuenta["fecha_valores"] == "2026-08-21"

    def test_serie_ordenada_por_fecha(self, client, auth_headers, indexa):
        serie = client.get("/finanzas/resumen", headers=auth_headers).json()["serie"]
        assert [p["fecha"] for p in serie] == ["2026-08-19", "2026-08-20", "2026-08-21"]
        assert serie[-1] == {"fecha": "2026-08-21", "valor": 12500.0, "aportado": 11000.0}

    def test_omite_las_cuentas_sin_dinero_diciendolo(self, client, auth_headers, indexa):
        datos = client.get("/finanzas/resumen", headers=auth_headers).json()
        assert [c["numero"] for c in datos["cuentas"]] == ["ABC12345"]
        # Una cuenta que no sale tiene que distinguirse de una cuenta que no existe.
        assert datos["omitidas"] == [{"cuenta": "PEN99999", "motivo": "estado «pending-contract»"}]
        assert indexa.called("GET", "/accounts/PEN99999/") == []

    def test_filtro_de_cuentas_por_entorno(self, client, auth_headers, indexa, monkeypatch):
        monkeypatch.setattr(main, "INDEXA_CUENTAS", ["OTRA1234"])
        datos = client.get("/finanzas/resumen", headers=auth_headers).json()
        assert datos["cuentas"] == []
        assert indexa.called("GET", "/accounts/ABC12345/") == []

    def test_numero_de_cuenta_raro_no_llega_a_la_url(self, client, auth_headers, mock_requests, monkeypatch):
        # El número se interpola en la ruta de la llamada siguiente: patrón, como los path
        # params de Supabase (invariante 6 de CLAUDE.md).
        monkeypatch.setattr(main, "INDEXA_TOKEN", "indexa-test-token")
        monkeypatch.setattr(main, "INDEXA_CUENTAS", [])
        mock_requests.add("GET", "/users/me", FakeResponse(
            {"accounts": [{"account_number": "../../users/me", "type": "mutual", "status": "active"}]}))
        datos = client.get("/finanzas/resumen", headers=auth_headers).json()
        assert datos["cuentas"] == []
        assert datos["omitidas"][0]["motivo"] == "número de cuenta con forma inesperada"
        assert mock_requests.called("GET", "/accounts/") == []


class TestFinanzasSinRendimiento:
    """Si /performance falla, la cartera de hoy se sigue sabiendo: se devuelve lo que hay."""

    @pytest.fixture
    def sin_rendimiento(self, monkeypatch, mock_requests):
        monkeypatch.setattr(main, "INDEXA_TOKEN", "indexa-test-token")
        monkeypatch.setattr(main, "INDEXA_CUENTAS", [])
        mock_requests.add("GET", "/users/me", FakeResponse(USERS_ME))
        mock_requests.add("GET", "/accounts/ABC12345/portfolio", FakeResponse(PORTFOLIO))
        mock_requests.add("GET", "/accounts/ABC12345/performance", FakeResponse({}, 503))
        return mock_requests

    def test_la_cartera_sigue_saliendo(self, client, auth_headers, sin_rendimiento):
        cuenta = client.get("/finanzas/resumen", headers=auth_headers).json()["cuentas"][0]
        assert cuenta["valor"] == 12500.0
        assert cuenta["rendimiento"] is False

    def test_lo_que_no_se_sabe_va_a_none_no_a_cero(self, client, auth_headers, sin_rendimiento):
        cuenta = client.get("/finanzas/resumen", headers=auth_headers).json()["cuentas"][0]
        assert cuenta["aportado"] is None
        assert cuenta["rentabilidad"] is None
        assert cuenta["rentabilidad_anual"] is None
        assert cuenta["serie"] == []

    def test_cae_a_la_plusvalia_de_las_posiciones_y_lo_dice(self, client, auth_headers, sin_rendimiento):
        # 9000-7500 y 3250-3300: lo que llevan ganado los fondos que hay AHORA, que no es
        # lo mismo que lo ganado por la cuenta desde que se abrió.
        cuenta = client.get("/finanzas/resumen", headers=auth_headers).json()["cuentas"][0]
        assert cuenta["plusvalia"] == 1450.0
        assert cuenta["plusvalia_origen"] == "posiciones"
        assert cuenta["plusvalia_pct"] == pytest.approx(1450 / 10800 * 100, abs=0.01)

    def test_el_total_avisa_de_que_esta_incompleto(self, client, auth_headers, sin_rendimiento):
        total = client.get("/finanzas/resumen", headers=auth_headers).json()["total"]
        assert total["valor"] == 12500.0
        assert total["aportado"] is None
        assert total["completo"] is False


class TestFinanzasVariasCuentas:
    @pytest.fixture
    def dos_cuentas(self, monkeypatch, mock_requests):
        monkeypatch.setattr(main, "INDEXA_TOKEN", "indexa-test-token")
        monkeypatch.setattr(main, "INDEXA_CUENTAS", [])
        mock_requests.add("GET", "/users/me", FakeResponse({"accounts": [
            {"account_number": "ABC12345", "type": "mutual",  "status": "active"},
            {"account_number": "PLN54321", "type": "pension", "status": "active"},
        ]}))
        mock_requests.add("GET", "/accounts/ABC12345/portfolio", FakeResponse(PORTFOLIO))
        mock_requests.add("GET", "/accounts/ABC12345/performance", FakeResponse(PERFORMANCE))
        # La segunda cuenta empieza un día más tarde: ese día no puede sumarse.
        plan = {
            "portfolio": {"total_amount": 2000.0, "cash_amount": 0.0},
            "instrument_accounts": [{"positions": [{
                "instrument": {"name": "Plan de pensiones", "dgs_code": "N5432",
                               "identifier_name": "DGS", "asset_class": "equity_europe"},
                "amount": 2000.0, "cost_amount": 1800.0, "titles": 100.0,
                "price": 20.0, "date": "2026-08-21"}]}],
        }
        rend = {"return": {
            "investment": 1800.0, "pl": 200.0, "time_return": 0.1111,
            "total_amount": 2000.0,
            "total_amounts": {"2026-08-20": 1950.0, "2026-08-21": 2000.0},
            "net_amounts":   {"2026-08-20": 1800.0, "2026-08-21": 1800.0},
        }}
        mock_requests.add("GET", "/accounts/PLN54321/portfolio", FakeResponse(plan))
        mock_requests.add("GET", "/accounts/PLN54321/performance", FakeResponse(rend))
        return mock_requests

    def test_suma_las_dos(self, client, auth_headers, dos_cuentas):
        total = client.get("/finanzas/resumen", headers=auth_headers).json()["total"]
        assert total["valor"] == 14500.0
        assert total["aportado"] == 12800.0
        assert total["plusvalia"] == 1700.0
        assert total["completo"] is True

    def test_la_serie_total_solo_usa_los_dias_que_tienen_las_dos(self, client, auth_headers, dos_cuentas):
        # Incluir el 19 (día en que solo contaba una cuenta) dibujaría un salto de +1.950 €
        # que no ocurrió: lo que empezó ese día fue la segunda cuenta, no una ganancia.
        serie = client.get("/finanzas/resumen", headers=auth_headers).json()["serie"]
        assert [p["fecha"] for p in serie] == ["2026-08-20", "2026-08-21"]
        assert serie[0]["valor"] == 14350.0
        assert serie[1] == {"fecha": "2026-08-21", "valor": 14500.0, "aportado": 12800.0}


class TestFinanzasVariasCarteras:
    def test_suma_todas_las_carteras_de_instrumentos(self, client, auth_headers, mock_requests, monkeypatch):
        # `instrument_accounts` es una lista y por ahí hay clientes que leen solo el primer
        # elemento. Quedarse con el primero es enseñar una cuenta a la que le falta dinero.
        monkeypatch.setattr(main, "INDEXA_TOKEN", "indexa-test-token")
        monkeypatch.setattr(main, "INDEXA_CUENTAS", [])
        dos = {
            "portfolio": {"total_amount": 3000.0, "cash_amount": 0.0},
            "instrument_accounts": [
                {"positions": [{"instrument": {"name": "A", "asset_class": "equity_world"},
                                "amount": 1000.0, "cost_amount": 900.0, "date": "2026-08-21"}]},
                {"positions": [{"instrument": {"name": "B", "asset_class": "fixed_euro"},
                                "amount": 2000.0, "cost_amount": 2100.0, "date": "2026-08-21"}]},
            ],
        }
        mock_requests.add("GET", "/users/me", FakeResponse(
            {"accounts": [{"account_number": "ABC12345", "type": "mutual", "status": "active"}]}))
        mock_requests.add("GET", "/accounts/ABC12345/portfolio", FakeResponse(dos))
        mock_requests.add("GET", "/accounts/ABC12345/performance", FakeResponse({}, 503))
        cuenta = client.get("/finanzas/resumen", headers=auth_headers).json()["cuentas"][0]
        assert len(cuenta["posiciones"]) == 2
        assert cuenta["distribucion"] == {"acciones": 1000.0, "bonos": 2000.0}


class TestFinanzasCache:
    def test_la_segunda_carga_no_vuelve_a_preguntar(self, client, auth_headers, indexa):
        client.get("/finanzas/resumen", headers=auth_headers)
        llamadas = len(indexa.called("GET", "indexacapital.com"))
        segunda = client.get("/finanzas/resumen", headers=auth_headers).json()
        assert segunda["de_cache"] is True
        assert len(indexa.called("GET", "indexacapital.com")) == llamadas

    def test_refrescar_salta_la_cache(self, client, auth_headers, indexa):
        client.get("/finanzas/resumen", headers=auth_headers)
        llamadas = len(indexa.called("GET", "indexacapital.com"))
        r = client.get("/finanzas/resumen?refrescar=true", headers=auth_headers).json()
        assert r["de_cache"] is False
        assert len(indexa.called("GET", "indexacapital.com")) > llamadas

    def test_la_cache_caduca(self, client, auth_headers, indexa, monkeypatch):
        monkeypatch.setattr(main, "INDEXA_TTL_MINUTOS", 0)
        client.get("/finanzas/resumen", headers=auth_headers)
        llamadas = len(indexa.called("GET", "indexacapital.com"))
        assert client.get("/finanzas/resumen", headers=auth_headers).json()["de_cache"] is False
        assert len(indexa.called("GET", "indexacapital.com")) > llamadas


class TestFinanzasErrores:
    def test_un_fallo_de_indexa_no_se_reenvia_al_cliente(self, client, auth_headers, mock_requests, monkeypatch):
        monkeypatch.setattr(main, "INDEXA_TOKEN", "indexa-test-token")
        mock_requests.add("GET", "/users/me", FakeResponse({}, 401, text="token revocado para la cuenta X"))
        r = client.get("/finanzas/resumen", headers=auth_headers)
        assert r.status_code == 502
        assert r.json()["detail"] == "No se pudo consultar Indexa Capital"
        assert "revocado" not in r.text

    def test_el_fallo_de_la_cartera_no_se_traga(self, client, auth_headers, mock_requests, monkeypatch):
        # Sin cartera no hay cuenta que enseñar: eso sí corta. Lo que se tolera es quedarse
        # sin rendimiento, no quedarse sin posiciones.
        monkeypatch.setattr(main, "INDEXA_TOKEN", "indexa-test-token")
        monkeypatch.setattr(main, "INDEXA_CUENTAS", [])
        mock_requests.add("GET", "/users/me", FakeResponse(USERS_ME))
        mock_requests.add("GET", "/accounts/ABC12345/portfolio", FakeResponse({}, 500))
        mock_requests.add("GET", "/accounts/ABC12345/performance", FakeResponse(PERFORMANCE))
        assert client.get("/finanzas/resumen", headers=auth_headers).status_code == 502

    def test_una_respuesta_con_otra_forma_no_revienta(self, client, auth_headers, mock_requests, monkeypatch):
        monkeypatch.setattr(main, "INDEXA_TOKEN", "indexa-test-token")
        monkeypatch.setattr(main, "INDEXA_CUENTAS", [])
        mock_requests.add("GET", "/users/me", FakeResponse({"accounts": [
            {"account_number": "ABC12345", "type": "mutual", "status": "active"}]}))
        mock_requests.add("GET", "/accounts/ABC12345/portfolio", FakeResponse({"portfolio": {}}))
        mock_requests.add("GET", "/accounts/ABC12345/performance", FakeResponse({"return": {}}))
        cuenta = client.get("/finanzas/resumen", headers=auth_headers).json()["cuentas"][0]
        assert cuenta["posiciones"] == []
        assert cuenta["valor"] == 0.0          # nada que sumar
        assert cuenta["coste"] is None         # y ningún coste conocido: no es un cero
        assert cuenta["fecha_valores"] is None


class TestFinanzasToken:
    def test_el_token_viaja_en_la_cabecera_y_no_en_la_url(self, client, auth_headers, indexa):
        r = client.get("/finanzas/resumen", headers=auth_headers)
        llamadas = indexa.called("GET", "indexacapital.com")
        assert llamadas
        for _, url, kwargs in llamadas:
            assert kwargs["headers"]["X-AUTH-TOKEN"] == "indexa-test-token"
            assert "indexa-test-token" not in url
        assert "indexa-test-token" not in r.text


class TestFinanzasJarvis:
    def test_la_herramienta_esta_registrada(self):
        assert "finanzas" in main._JARVIS_HERRAMIENTAS
        assert main._JARVIS_HERRAMIENTAS["finanzas"]["confirmar"] is False

    def test_recorta_lo_que_entra_en_el_prompt(self, indexa):
        datos = main._j_finanzas()
        assert datos["total"]["valor"] == 12500.0
        assert len(datos["cuentas"][0]["mayores"]) <= 5
        # El detalle caro (ISIN, gestora, títulos, la serie entera) no viaja al modelo.
        assert "posiciones" not in datos["cuentas"][0]
        assert "serie" not in datos["cuentas"][0]

    def test_sin_configurar_trae_su_arreglo_dentro(self, monkeypatch):
        monkeypatch.setattr(main, "INDEXA_TOKEN", "")
        assert main._j_finanzas()["dile_al_usuario_literalmente"]
