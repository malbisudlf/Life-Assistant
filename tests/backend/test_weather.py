"""Tests del endpoint de clima (Open-Meteo)."""
from conftest import FakeResponse

# Respuesta realista de Open-Meteo con los campos que pedimos (6 días de previsión).
OPEN_METEO_OK = {
    "current": {
        "temperature_2m": 21.4,
        "weather_code": 2,
        "apparent_temperature": 20.1,
        "relative_humidity_2m": 55,
        "wind_speed_10m": 12.3,
        "precipitation": 0.0,
    },
    "daily": {
        "time":                     ["2026-07-23", "2026-07-24", "2026-07-25"],
        "weather_code":             [3, 1, 61],
        "temperature_2m_max":       [24.6, 26.2, 22.0],
        "temperature_2m_min":       [12.1, 13.4, 14.9],
        "precipitation_probability_max": [10, 0, 70],
    },
}


class TestWeather:
    def test_requiere_jwt(self, client):
        assert client.get("/weather").status_code in (401, 403)

    def test_devuelve_clima_actual_redondeado(self, client, auth_headers, mock_requests):
        mock_requests.add("GET", "open-meteo.com", FakeResponse(OPEN_METEO_OK))
        r = client.get("/weather", headers=auth_headers)
        assert r.status_code == 200
        data = r.json()
        # Actual + máx/mín de hoy (día 0)
        assert data["temp"] == 21
        assert data["code"] == 2
        assert data["temp_max"] == 25
        assert data["temp_min"] == 12
        # Extras de la vista desplegada
        assert data["feels_like"] == 20
        assert data["humidity"] == 55
        assert data["wind"] == 12

    def test_devuelve_prevision_por_dias(self, client, auth_headers, mock_requests):
        mock_requests.add("GET", "open-meteo.com", FakeResponse(OPEN_METEO_OK))
        data = client.get("/weather", headers=auth_headers).json()
        assert len(data["daily"]) == 3
        assert data["daily"][0] == {"date": "2026-07-23", "code": 3, "max": 25, "min": 12, "precip_prob": 10}
        assert data["daily"][2]["precip_prob"] == 70

    def test_extras_ausentes_no_rompen(self, client, auth_headers, mock_requests):
        # Si Open-Meteo omite los extras, el núcleo sigue devolviéndose (opcionales).
        minimo = {
            "current": {"temperature_2m": 18.0, "weather_code": 0},
            "daily": {"time": ["2026-07-23"], "weather_code": [0],
                      "temperature_2m_max": [20.0], "temperature_2m_min": [10.0]},
        }
        mock_requests.add("GET", "open-meteo.com", FakeResponse(minimo))
        data = client.get("/weather", headers=auth_headers).json()
        assert data["temp"] == 18
        assert data["feels_like"] is None
        assert data["daily"][0]["precip_prob"] is None

    def test_respuesta_invalida_devuelve_502(self, client, auth_headers, mock_requests):
        mock_requests.add("GET", "open-meteo.com", FakeResponse({"algo": "raro"}))
        assert client.get("/weather", headers=auth_headers).status_code == 502

    def test_error_de_open_meteo_devuelve_502(self, client, auth_headers, mock_requests):
        mock_requests.add("GET", "open-meteo.com", FakeResponse({}, status_code=500))
        assert client.get("/weather", headers=auth_headers).status_code == 502

    def test_acepta_lat_lon_del_dispositivo(self, client, auth_headers, mock_requests):
        capturado = {}

        def responder(url, **kwargs):
            capturado["params"] = kwargs.get("params", {})
            return FakeResponse(OPEN_METEO_OK)

        mock_requests.add("GET", "open-meteo.com", responder)
        r = client.get("/weather?lat=43.26&lon=-2.93", headers=auth_headers)
        assert r.status_code == 200
        # Las coordenadas del dispositivo llegan a Open-Meteo, no las fijas
        assert capturado["params"]["latitude"] == 43.26
        assert capturado["params"]["longitude"] == -2.93

    def test_lat_lon_invalidos_devuelven_422(self, client, auth_headers):
        assert client.get("/weather?lat=hola&lon=-2.93", headers=auth_headers).status_code == 422
