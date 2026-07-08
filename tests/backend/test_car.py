"""Tests del envío de destino al coche (BMW API simulada + fallback de HA)."""
import asyncio

import main
from conftest import FakeResponse


def _geocode_ok():
    return FakeResponse({
        "results": [{
            "geometry": {"location": {"lat": 43.2708, "lng": -2.9389}},
            "formatted_address": "Av. de las Universidades 24, 48007 Bilbao",
        }]
    })


class TestSendCarDestination:
    def test_requiere_jwt(self, client):
        r = client.post("/car/send-destination", json={"address": "Universidad de Deusto"})
        assert r.status_code in (401, 403)

    def test_direccion_no_geocodificable(self, client, auth_headers, mock_requests):
        mock_requests.add("GET", "maps/api/geocode", FakeResponse({"results": []}))
        r = client.post("/car/send-destination", headers=auth_headers,
                        json={"address": "xxxxxx sitio inexistente"})
        assert r.status_code == 400

    def test_validacion_de_entrada(self, client, auth_headers):
        assert client.post("/car/send-destination", headers=auth_headers,
                           json={"address": "ab"}).status_code == 422       # muy corta
        assert client.post("/car/send-destination", headers=auth_headers,
                           json={"address": "x" * 501}).status_code == 422  # muy larga

    def test_via_bmw_cuando_funciona(self, client, auth_headers, mock_requests, monkeypatch):
        mock_requests.add("GET", "maps/api/geocode", _geocode_ok())

        async def bmw_ok(lat, lon, name):
            bmw_ok.called_with = (lat, lon, name)
            return True
        monkeypatch.setattr(main, "_send_poi_bmw", bmw_ok)

        r = client.post("/car/send-destination", headers=auth_headers,
                        json={"address": "Universidad de Deusto, Bilbao", "name": "Clase de Redes"})
        assert r.status_code == 200
        assert r.json() == {"ok": True, "via": "bmw"}
        assert bmw_ok.called_with == (43.2708, -2.9389, "Clase de Redes")
        # La vía BMW NO deja nada encolado para HA
        assert main._car_destination_pending is None

    def test_fallback_ha_cuando_bmw_falla(self, client, auth_headers, mock_requests, monkeypatch):
        mock_requests.add("GET", "maps/api/geocode", _geocode_ok())

        async def bmw_ko(lat, lon, name):
            return False
        monkeypatch.setattr(main, "_send_poi_bmw", bmw_ko)

        r = client.post("/car/send-destination", headers=auth_headers,
                        json={"address": "Universidad de Deusto, Bilbao"})
        assert r.json() == {"ok": True, "via": "ha"}

        pending = main._car_destination_pending
        assert pending["lat"] == 43.2708
        assert pending["name"] == "Universidad de Deusto, Bilbao"  # sin name → usa la dirección
        assert pending["address"] == "Av. de las Universidades 24, 48007 Bilbao"
        assert "google.com/maps" in pending["maps_url"]

    def test_geocode_usa_la_api_key(self, client, auth_headers, mock_requests, monkeypatch):
        mock_requests.add("GET", "maps/api/geocode", _geocode_ok())

        async def bmw_ko(lat, lon, name):
            return False
        monkeypatch.setattr(main, "_send_poi_bmw", bmw_ko)

        client.post("/car/send-destination", headers=auth_headers,
                    json={"address": "Universidad de Deusto, Bilbao"})
        params = mock_requests.called("GET", "maps/api/geocode")[0][2]["params"]
        assert params["key"] == "maps-test-key"
        assert params["address"] == "Universidad de Deusto, Bilbao"


class TestHaCarDestination:
    def test_requiere_token_de_servicio(self, client):
        assert client.get("/ha/car-destination").status_code == 403
        assert client.get("/ha/car-destination?token=malo").status_code == 403

    def test_devuelve_y_limpia_el_destino(self, client, auth_headers, mock_requests, monkeypatch):
        mock_requests.add("GET", "maps/api/geocode", _geocode_ok())

        async def bmw_ko(lat, lon, name):
            return False
        monkeypatch.setattr(main, "_send_poi_bmw", bmw_ko)

        # Sin destino pendiente
        r0 = client.get("/ha/car-destination?token=ha-poll-token")
        assert r0.json() == {"destination": None}

        # El dashboard encola un destino
        client.post("/car/send-destination", headers=auth_headers,
                    json={"address": "Universidad de Deusto, Bilbao", "name": "Clase"})

        # El primer poll lo recoge...
        r1 = client.get("/ha/car-destination?token=ha-poll-token")
        dest = r1.json()["destination"]
        assert dest["name"] == "Clase"
        assert dest["lat"] == 43.2708
        # ...y lo limpia
        r2 = client.get("/ha/car-destination?token=ha-poll-token")
        assert r2.json() == {"destination": None}

    def test_acepta_token_por_header(self, client):
        r = client.get("/ha/car-destination", headers={"X-Auth-Token": "ha-poll-token"})
        assert r.status_code == 200


class TestSendPoiBmw:
    def test_sin_credenciales_devuelve_false(self):
        # En el entorno de test BMW_USERNAME/PASSWORD están vacíos
        assert asyncio.run(main._send_poi_bmw(43.0, -2.0, "X")) is False

    def test_geocode_sin_api_key(self, monkeypatch):
        monkeypatch.setattr(main, "GOOGLE_MAPS_API_KEY", None)
        assert main._geocode_address("Bilbao") is None
