"""Tests de la contabilidad del modelo: medir en vez de estimar.

Dos propiedades por encima del resto, y las dos son de la misma familia que el resto del
proyecto:

  - **Apuntar el gasto nunca puede tocar la respuesta.** Es contabilidad, no
    funcionalidad: si Supabase no contesta, el turno sale igual.
  - **No saber lo que cuesta algo no es que sea gratis.** Un modelo sin tarifa
    configurada sale con euros a null y sus tokens contados, no con un cero que se lee
    como "no gastó".
"""
from types import SimpleNamespace

import pytest

import main
from conftest import FakeResponse


def _usage(entrada=1000, salida=200, cacheados=0):
    return SimpleNamespace(
        prompt_tokens=entrada,
        completion_tokens=salida,
        prompt_tokens_details=SimpleNamespace(cached_tokens=cacheados),
    )


@pytest.fixture(autouse=True)
def _cola_limpia(monkeypatch):
    monkeypatch.setattr(main, "GASTO_PERSIST", True)
    main._gasto_cola.clear()
    yield
    main._gasto_cola.clear()


class TestApuntar:
    def test_apunta_los_tokens_de_una_llamada(self):
        main._apuntar_gasto("chat", "gpt-4o-mini", _usage(3667, 210, cacheados=3456))
        fila = main._gasto_cola[0]
        assert fila["boca"] == "chat"
        assert fila["tokens_entrada"] == 3667
        assert fila["tokens_cacheados"] == 3456
        assert fila["tokens_salida"] == 210

    def test_sin_usage_no_se_inventa_nada(self):
        """El streaming solo manda usage si se le pide, y un modelo simulado no lo trae.
        Eso es una llamada de la que no sabemos el gasto, no una llamada gratis."""
        main._apuntar_gasto("voz", "gpt-4o-mini", None)
        assert len(main._gasto_cola) == 0

    def test_el_audio_va_en_su_columna(self):
        main._apuntar_gasto("telefono", "whisper-1", segundos_audio=12.5)
        fila = main._gasto_cola[0]
        assert fila["segundos_audio"] == 12.5
        assert fila["tokens_entrada"] == 0

    def test_apagado_no_apunta(self, monkeypatch):
        monkeypatch.setattr(main, "GASTO_PERSIST", False)
        main._apuntar_gasto("chat", "gpt-4o-mini", _usage())
        assert len(main._gasto_cola) == 0

    def test_un_usage_raro_no_revienta(self):
        """Lo que devuelve el SDK cambia con las versiones: esto es contabilidad, no
        puede propagar un AttributeError al turno."""
        main._apuntar_gasto("chat", "gpt-4o-mini", SimpleNamespace(cosa="rara"))
        assert len(main._gasto_cola) == 0

    def test_la_cola_esta_acotada(self):
        for _ in range(main.GASTO_QUEUE_MAX + 50):
            main._apuntar_gasto("chat", "gpt-4o-mini", _usage())
        assert len(main._gasto_cola) == main.GASTO_QUEUE_MAX

    def test_si_supabase_falla_no_lanza(self, mock_requests):
        mock_requests.add("POST", "jarvis_gasto", FakeResponse({"message": "no"}, 500))
        main._apuntar_gasto("chat", "gpt-4o-mini", _usage())
        main._volcar_gasto()          # no lanza
        assert len(main._gasto_cola) == 0

    def test_al_volcar_se_escribe_el_lote_entero(self, mock_requests):
        mock_requests.add("POST", "jarvis_gasto", FakeResponse([], 201))
        for _ in range(3):
            main._apuntar_gasto("chat", "gpt-4o-mini", _usage())
        main._volcar_gasto()
        enviadas = mock_requests.called("POST", "jarvis_gasto")
        assert len(enviadas) == 1                 # un solo viaje, no tres
        assert len(enviadas[0][2]["json"]) == 3


class TestEuros:
    def test_los_cacheados_no_se_cobran_dos_veces(self):
        """Vienen DENTRO de los de entrada. Cobrarlos aparte inflaría el total justo en
        el caso que el proyecto optimiza: el prefijo estable del prompt."""
        tarifa = main._TARIFAS_POR_DEFECTO["gpt-4o-mini"]
        euros = main._euros("gpt-4o-mini", 1000, 800, 0, 0)
        esperado = (200 * tarifa[0] + 800 * tarifa[1]) / 1_000_000
        assert euros == pytest.approx(esperado, rel=1e-6)

    def test_un_modelo_sin_tarifa_no_vale_cero(self):
        assert main._euros("modelo-inventado", 1000, 0, 100, 0) is None

    def test_el_audio_se_cobra_por_minutos(self):
        assert main._euros("whisper-1", 0, 0, 0, 60) == pytest.approx(main.TARIFA_AUDIO_MINUTO)

    def test_las_tarifas_se_pueden_configurar(self, monkeypatch):
        monkeypatch.setenv("MODELO_TARIFAS", '{"mi-modelo": [1.0, 0.5, 2.0]}')
        assert main._euros("mi-modelo", 1_000_000, 0, 0, 0) == pytest.approx(1.0)

    def test_una_configuracion_rota_no_tumba_nada(self, monkeypatch):
        monkeypatch.setenv("MODELO_TARIFAS", "esto no es json")
        assert main._euros("gpt-4o-mini", 1000, 0, 0, 0) is not None


class TestEndpointGasto:
    def test_requiere_token(self, client):
        assert client.get("/gasto").status_code in (401, 403)

    def test_dias_fuera_de_rango(self, client, auth_headers):
        assert client.get("/gasto?dias=0", headers=auth_headers).status_code == 400
        assert client.get("/gasto?dias=999", headers=auth_headers).status_code == 400

    def test_agrega_por_boca_y_por_modelo(self, client, auth_headers, mock_requests):
        mock_requests.add("GET", "jarvis_gasto", FakeResponse([
            {"boca": "chat", "modelo": "gpt-4o-mini", "tokens_entrada": 1000,
             "tokens_cacheados": 900, "tokens_salida": 100, "segundos_audio": 0},
            {"boca": "voz", "modelo": "gpt-4o-mini", "tokens_entrada": 2000,
             "tokens_cacheados": 1800, "tokens_salida": 300, "segundos_audio": 0},
            {"boca": "voz", "modelo": "whisper-1", "tokens_entrada": 0,
             "tokens_cacheados": 0, "tokens_salida": 0, "segundos_audio": 30},
        ]))
        datos = client.get("/gasto", headers=auth_headers).json()
        assert datos["total"]["llamadas"] == 3
        assert datos["por_boca"]["voz"]["llamadas"] == 2
        assert datos["por_boca"]["chat"]["entrada"] == 1000
        assert datos["por_modelo"]["whisper-1"]["segundos_audio"] == 30
        # 2.700 cacheados de 3.000 de entrada: la palanca de coste de Jarvis.
        assert datos["cacheado_pct"] == 90.0

    def test_un_modelo_sin_tarifa_se_declara(self, client, auth_headers, mock_requests):
        mock_requests.add("GET", "jarvis_gasto", FakeResponse([
            {"boca": "chat", "modelo": "modelo-nuevo", "tokens_entrada": 1000,
             "tokens_cacheados": 0, "tokens_salida": 100, "segundos_audio": 0},
        ]))
        datos = client.get("/gasto", headers=auth_headers).json()
        assert datos["sin_tarifa"] == ["modelo-nuevo"]
        # El total en euros existe pero se declara incompleto: un número que no incluye
        # todo el gasto y no lo dice es peor que no darlo.
        assert datos["total"]["euros_incompleto"] is True

    def test_sin_gasto_todavia_responde_vacio(self, client, auth_headers, mock_requests):
        mock_requests.add("GET", "jarvis_gasto", FakeResponse([]))
        datos = client.get("/gasto", headers=auth_headers).json()
        assert datos["total"]["llamadas"] == 0
        assert datos["cacheado_pct"] is None

    def test_lo_encolado_se_vuelca_antes_de_responder(self, client, auth_headers,
                                                      mock_requests):
        """Se mira el panel justo después de usar Jarvis: si lo último se quedara en la
        cola en memoria, el panel enseñaría todo menos lo que acabas de gastar."""
        mock_requests.add("POST", "jarvis_gasto", FakeResponse([], 201))
        mock_requests.add("GET", "jarvis_gasto", FakeResponse([]))
        main._apuntar_gasto("chat", "gpt-4o-mini", _usage())
        client.get("/gasto", headers=auth_headers)
        assert mock_requests.called("POST", "jarvis_gasto")


class TestBocas:
    """Por dónde entró el gasto. Es la pregunta que hoy no se puede responder y la que
    decide si el modo llamada se está comiendo el presupuesto."""

    def test_el_chat_se_apunta_como_chat(self, client, auth_headers, monkeypatch):
        from test_jarvis import _con_modelo, _mensaje

        cliente = _con_modelo(monkeypatch, [_mensaje("Hola.")])
        monkeypatch.setattr(cliente, "create", _create_con_usage(cliente), raising=False)
        client.post("/jarvis", json={"mensaje": "hola"}, headers=auth_headers)
        assert [f["boca"] for f in main._gasto_cola] == ["chat"]

    def test_el_atajo_se_apunta_aparte(self, client, monkeypatch):
        from test_jarvis import _con_modelo, _mensaje

        monkeypatch.setattr(main, "JARVIS_TOKEN", "jarvis-token")
        cliente = _con_modelo(monkeypatch, [_mensaje("Hola.")])
        monkeypatch.setattr(cliente, "create", _create_con_usage(cliente), raising=False)
        client.post("/jarvis/atajo", json={"mensaje": "hola"},
                    headers={"X-Auth-Token": "jarvis-token"})
        assert [f["boca"] for f in main._gasto_cola] == ["atajo"]


def _create_con_usage(cliente):
    """El cliente falso no devuelve `usage`; aquí se le añade para poder mirar la boca.

    Por streaming el `usage` llega como un trozo final SIN `choices`, que es exactamente
    lo que manda OpenAI con `include_usage` — así el test comprueba también que ese trozo
    se sabe leer sin confundirlo con contenido.
    """
    original = cliente.create

    def _create(**kwargs):
        respuesta = original(**kwargs)
        if kwargs.get("stream"):
            def _con_cola():
                yield from respuesta
                yield SimpleNamespace(choices=[], usage=_usage())
            return _con_cola()
        respuesta.usage = _usage()
        return respuesta

    return _create
