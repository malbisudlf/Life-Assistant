"""Tests del endpoint de clima (Open-Meteo)."""
from conftest import FakeResponse

OPEN_METEO_OK = {
    "current": {"temperature_2m": 21.4, "weather_code": 2},
    "daily": {
        "temperature_2m_max": [24.6],
        "temperature_2m_min": [12.1],
        "weather_code": [3],
    },
}


class TestWeather:
    def test_requiere_jwt(self, client):
        assert client.get("/weather").status_code in (401, 403)

    def test_devuelve_temp_y_maxmin_redondeados(self, client, auth_headers, mock_requests):
        mock_requests.add("GET", "open-meteo.com", FakeResponse(OPEN_METEO_OK))
        r = client.get("/weather", headers=auth_headers)
        assert r.status_code == 200
        assert r.json() == {"temp": 21, "code": 2, "temp_max": 25, "temp_min": 12}

    def test_respuesta_invalida_devuelve_502(self, client, auth_headers, mock_requests):
        mock_requests.add("GET", "open-meteo.com", FakeResponse({"algo": "raro"}))
        assert client.get("/weather", headers=auth_headers).status_code == 502

    def test_error_de_open_meteo_devuelve_502(self, client, auth_headers, mock_requests):
        mock_requests.add("GET", "open-meteo.com", FakeResponse({}, status_code=500))
        assert client.get("/weather", headers=auth_headers).status_code == 502
