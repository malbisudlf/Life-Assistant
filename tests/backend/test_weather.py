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
