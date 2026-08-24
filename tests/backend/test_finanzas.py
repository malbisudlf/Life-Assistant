"""Tests del módulo de finanzas (Indexa Capital).

Todo va contra el MockRouter: los tests no hablan con Indexa ni necesitan un token real.
Las respuestas simuladas copian la forma de la API de verdad (`instrument_accounts` →
`positions`, `return.total_amounts`…), que es justo lo que hay que fijar aquí: si esa
forma cambiara, es este fichero el que tiene que enterarse primero.
"""
import datetime

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


# ── Cartera manual de ETFs (Yahoo Finance) ────────────────────────────────────
# Ni Indexa ni Revolut pueden decir esto: aquí el "aportado" y las "participaciones" son
# siempre datos propios (vienen de Supabase, no de una API externa), y solo el precio
# actual / la ganancia dependen de Yahoo Finance — por eso los tests distinguen tan
# bien entre "un ETF sin precio" y "los demás siguen saliendo".

ETF_HOLDINGS = [
    {"ticker": "VWCE", "nombre": "Vanguard FTSE All-World UCITS ETF (USD) Acc",
     "simbolo_yahoo": "VWCE.DE"},
    {"ticker": "SECO", "nombre": "iShares MSCI Global Semiconductors UCITS ETF USD (Acc)",
     "simbolo_yahoo": "SEC0.DE"},
]

ETF_APORTACIONES = [
    {"id": "a1", "ticker": "VWCE", "fecha": "2026-01-23", "importe_eur": 318.51,
     "participaciones": 2.00320755, "precio_compra": 159.0},
    {"id": "a2", "ticker": "SECO", "fecha": "2026-08-20", "importe_eur": 1000.0,
     "participaciones": 60.3862, "precio_compra": 16.5600},
]


def _epoch(fecha_iso):
    d = datetime.date.fromisoformat(fecha_iso)
    return int(datetime.datetime(d.year, d.month, d.day, tzinfo=datetime.timezone.utc).timestamp())


def _yahoo_chart_ok(precio_actual=None, historico=None):
    """Simula una respuesta de /v8/finance/chart. Con `period1` en los params (petición
    de histórico) devuelve `historico` (lista de (fecha_iso, cierre)); si no, el precio
    actual (petición con `range`)."""
    def _f(url, **kwargs):
        params = kwargs.get("params") or {}
        if "period1" in params:
            timestamps = [_epoch(f) for f, _ in (historico or [])]
            cierres    = [c for _, c in (historico or [])]
            return FakeResponse({"chart": {"result": [{
                "timestamp": timestamps,
                "indicators": {"quote": [{"close": cierres}]},
            }], "error": None}})
        return FakeResponse({"chart": {"result": [{"meta": {"regularMarketPrice": precio_actual}}]}, "error": None})
    return _f


def _yahoo_chart_error(url, **kwargs):
    return FakeResponse({"chart": {"result": None, "error": {"code": "Not Found", "description": "No data found"}}})


def _yahoo_chart_por_intervalo(horario=None, diario=None, actual=None):
    """Como _yahoo_chart_ok, pero distingue `interval=60m` (petición con hora — `horario`
    es una lista de (datetime UTC, cierre)) de `interval=1d` (`diario`, igual que
    `_yahoo_chart_ok`). Necesaria porque ambas peticiones llevan `period1` en los params."""
    def _f(url, **kwargs):
        params = kwargs.get("params") or {}
        if params.get("interval") == "60m":
            timestamps = [int(dt.timestamp()) for dt, _ in (horario or [])]
            cierres    = [c for _, c in (horario or [])]
        elif "period1" in params:
            timestamps = [_epoch(f) for f, _ in (diario or [])]
            cierres    = [c for _, c in (diario or [])]
        else:
            return FakeResponse({"chart": {"result": [{"meta": {"regularMarketPrice": actual}}]}, "error": None})
        return FakeResponse({"chart": {"result": [{
            "timestamp": timestamps,
            "indicators": {"quote": [{"close": cierres}]},
        }], "error": None}})
    return _f


class TestEtfAuth:
    def test_requiere_jwt(self, client):
        assert client.get("/finanzas/etfs").status_code in (401, 403)


class TestEtfResumen:
    def test_calcula_valor_y_ganancia_con_precio(self, client, auth_headers, mock_requests):
        mock_requests.add("GET", "etf_holdings", FakeResponse(ETF_HOLDINGS))
        mock_requests.add("GET", "etf_aportaciones", FakeResponse(ETF_APORTACIONES))
        mock_requests.add("GET", "chart/VWCE.DE", _yahoo_chart_ok(precio_actual=166.0))
        mock_requests.add("GET", "chart/SEC0.DE", _yahoo_chart_ok(precio_actual=16.6))
        datos = client.get("/finanzas/etfs", headers=auth_headers).json()
        vwce = next(e for e in datos["etfs"] if e["ticker"] == "VWCE")
        assert vwce["aportado_eur"] == 318.51
        assert vwce["participaciones"] == pytest.approx(2.00320755)
        assert vwce["precio_actual"] == 166.0
        assert vwce["valor_actual"] == pytest.approx(2.00320755 * 166.0, abs=0.01)
        assert vwce["ganancia_eur"] == pytest.approx(vwce["valor_actual"] - 318.51, abs=0.01)
        assert datos["total"]["valor_actual"] is not None

    def test_un_etf_sin_precio_no_tumba_a_los_demas(self, client, auth_headers, mock_requests):
        # Solo se sabe cotizar SEC0.DE: VWCE se queda sin precio, pero sigue en la respuesta.
        mock_requests.add("GET", "etf_holdings", FakeResponse(ETF_HOLDINGS))
        mock_requests.add("GET", "etf_aportaciones", FakeResponse(ETF_APORTACIONES))
        mock_requests.add("GET", "chart/VWCE.DE", _yahoo_chart_error)
        mock_requests.add("GET", "chart/SEC0.DE", _yahoo_chart_ok(precio_actual=16.6))
        datos = client.get("/finanzas/etfs", headers=auth_headers).json()
        vwce = next(e for e in datos["etfs"] if e["ticker"] == "VWCE")
        seco = next(e for e in datos["etfs"] if e["ticker"] == "SECO")
        # Sin precio no hay valor: None, nunca un 0 € que afirmaría algo que no se sabe.
        assert vwce["precio_actual"] is None
        assert vwce["valor_actual"] is None
        assert seco["precio_actual"] == 16.6
        # El total no puede sumar lo que falta: incompleto es None, no un total más bajo.
        assert datos["total"]["valor_actual"] is None

    def test_caché_evita_repreguntar_a_yahoo(self, client, auth_headers, mock_requests):
        mock_requests.add("GET", "etf_holdings", FakeResponse(ETF_HOLDINGS))
        mock_requests.add("GET", "etf_aportaciones", FakeResponse(ETF_APORTACIONES))
        mock_requests.add("GET", "chart/VWCE.DE", _yahoo_chart_ok(precio_actual=166.0))
        mock_requests.add("GET", "chart/SEC0.DE", _yahoo_chart_ok(precio_actual=16.6))
        client.get("/finanzas/etfs", headers=auth_headers)
        client.get("/finanzas/etfs", headers=auth_headers)
        assert len(mock_requests.called("GET", "chart/VWCE.DE")) == 1   # una vez, no dos
        assert len(mock_requests.called("GET", "chart/SEC0.DE")) == 1


class TestEtfAportacion:
    def test_calcula_participaciones_con_precio_historico(self, client, auth_headers, mock_requests):
        mock_requests.add("GET", "etf_holdings", FakeResponse([ETF_HOLDINGS[0]]))
        mock_requests.add("GET", "chart/VWCE.DE", _yahoo_chart_ok(historico=[("2026-01-23", 159.0)]))
        mock_requests.add("POST", "etf_aportaciones", FakeResponse([{
            "id": "nuevo", "ticker": "VWCE", "fecha": "2026-01-23",
            "importe_eur": 318.51, "participaciones": 2.00320755, "precio_compra": 159.0,
        }]))
        r = client.post("/finanzas/etfs/VWCE/aportaciones", headers=auth_headers,
                         json={"fecha": "2026-01-23", "importe_eur": 318.51})
        assert r.status_code == 200
        assert r.json()["aportacion"]["participaciones"] == pytest.approx(2.00320755)

    def test_fin_de_semana_usa_el_dia_habil_anterior(self, client, auth_headers, mock_requests):
        # Yahoo no cotiza fines de semana: no hay valor para esa fecha exacta, se usa el
        # último día hábil anterior dentro de la ventana pedida — nunca un precio a 0.
        mock_requests.add("GET", "etf_holdings", FakeResponse([ETF_HOLDINGS[0]]))
        mock_requests.add("GET", "chart/VWCE.DE", _yahoo_chart_ok(historico=[("2026-08-21", 165.0)]))  # viernes
        mock_requests.add("POST", "etf_aportaciones", FakeResponse([{
            "id": "nuevo", "ticker": "VWCE", "fecha": "2026-08-23", "importe_eur": 100.0,
            "participaciones": 0.60606061, "precio_compra": 165.0,
        }]))
        r = client.post("/finanzas/etfs/VWCE/aportaciones", headers=auth_headers,
                         json={"fecha": "2026-08-23", "importe_eur": 100.0})  # domingo
        assert r.status_code == 200
        assert r.json()["fecha_precio_usada"] == "2026-08-21"

    def test_ticker_desconocido_da_404(self, client, auth_headers, mock_requests):
        mock_requests.add("GET", "etf_holdings", FakeResponse([]))
        r = client.post("/finanzas/etfs/ZZZZ/aportaciones", headers=auth_headers,
                         json={"fecha": "2026-01-23", "importe_eur": 100})
        assert r.status_code == 404

    def test_fallo_de_yahoo_da_502_y_no_inserta_nada(self, client, auth_headers, mock_requests):
        mock_requests.add("GET", "etf_holdings", FakeResponse([ETF_HOLDINGS[0]]))
        mock_requests.add("GET", "chart/VWCE.DE", _yahoo_chart_error)
        r = client.post("/finanzas/etfs/VWCE/aportaciones", headers=auth_headers,
                         json={"fecha": "2026-01-23", "importe_eur": 100})
        assert r.status_code == 502
        assert mock_requests.called("POST", "etf_aportaciones") == []


class TestEtfAportacionHora:
    # Con la hora exacta se pide el precio HORARIO más cercano (más preciso que el
    # cierre del día), que fue justo lo que faltaba: sin hora, el cierre diario podía
    # diferir del precio real de la operación en un ~0,1-0,2% acumulado.

    def test_usa_el_precio_horario_mas_cercano_a_la_hora_de_compra(self, client, auth_headers, mock_requests):
        # 23 ene 2026, 16:25 hora de Madrid (CET, UTC+1 en invierno) = 15:25 UTC. La
        # vela de las 15:00 UTC (147.84) está a 25 min; la de las 16:00 (147.72), a 35.
        mock_requests.add("GET", "etf_holdings", FakeResponse([ETF_HOLDINGS[0]]))
        mock_requests.add("GET", "chart/VWCE.DE", _yahoo_chart_por_intervalo(horario=[
            (datetime.datetime(2026, 1, 23, 14, 0, tzinfo=datetime.timezone.utc), 147.5),
            (datetime.datetime(2026, 1, 23, 15, 0, tzinfo=datetime.timezone.utc), 147.84),
            (datetime.datetime(2026, 1, 23, 16, 0, tzinfo=datetime.timezone.utc), 147.72),
        ]))
        mock_requests.add("POST", "etf_aportaciones", FakeResponse([{
            "id": "nuevo", "ticker": "VWCE", "fecha": "2026-01-23", "hora": "16:25",
            "importe_eur": 318.51, "participaciones": 318.51 / 147.84, "precio_compra": 147.84,
        }]))
        r = client.post("/finanzas/etfs/VWCE/aportaciones", headers=auth_headers,
                         json={"fecha": "2026-01-23", "importe_eur": 318.51, "hora": "16:25"})
        assert r.status_code == 200
        enviado = mock_requests.called("POST", "etf_aportaciones")[0][2]["json"]
        assert enviado["precio_compra"] == 147.84
        assert enviado["hora"] == "16:25"

    def test_sin_datos_horarios_cae_al_cierre_diario(self, client, auth_headers, mock_requests):
        # Compra de hace más de ~730 días: Yahoo ya no guarda velas horarias tan atrás.
        mock_requests.add("GET", "etf_holdings", FakeResponse([ETF_HOLDINGS[0]]))
        mock_requests.add("GET", "chart/VWCE.DE", _yahoo_chart_por_intervalo(diario=[("2026-01-23", 147.72)]))
        mock_requests.add("POST", "etf_aportaciones", FakeResponse([{
            "id": "nuevo", "ticker": "VWCE", "fecha": "2026-01-23", "hora": "16:25",
            "importe_eur": 318.51, "participaciones": 318.51 / 147.72, "precio_compra": 147.72,
        }]))
        r = client.post("/finanzas/etfs/VWCE/aportaciones", headers=auth_headers,
                         json={"fecha": "2026-01-23", "importe_eur": 318.51, "hora": "16:25"})
        assert r.status_code == 200
        enviado = mock_requests.called("POST", "etf_aportaciones")[0][2]["json"]
        assert enviado["precio_compra"] == 147.72

    def test_hora_con_formato_invalido_la_rechaza(self, client, auth_headers, mock_requests):
        r = client.post("/finanzas/etfs/VWCE/aportaciones", headers=auth_headers,
                         json={"fecha": "2026-01-23", "importe_eur": 100, "hora": "25:99"})
        assert r.status_code == 422


class TestEtfBorrarAportacion:
    def test_requiere_jwt(self, client):
        assert client.delete("/finanzas/etfs/VWCE/aportaciones/11111111-1111-1111-1111-111111111111").status_code in (401, 403)

    def test_borra_la_fila(self, client, auth_headers, mock_requests):
        mock_requests.add("DELETE", "etf_aportaciones", FakeResponse([], 200))
        r = client.delete("/finanzas/etfs/VWCE/aportaciones/11111111-1111-1111-1111-111111111111",
                           headers=auth_headers)
        assert r.status_code == 200
        assert r.json()["ok"] is True
        borrado = mock_requests.called("DELETE", "etf_aportaciones")[0][1]
        assert "ticker=eq.VWCE" in borrado
        assert "id=eq.11111111-1111-1111-1111-111111111111" in borrado
