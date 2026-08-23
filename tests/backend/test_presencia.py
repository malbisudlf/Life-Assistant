"""Tests de la presencia que empuja Home Assistant.

Cubren las tres cosas que pueden salir mal en silencio: que una ubicación caducada se
use como si fuera actual, que el tramo que cruza la medianoche se impute entero a un
solo día, y que un hueco largo (HA caído) se cuente como tiempo en la última zona.
"""
from datetime import datetime, timedelta, timezone

import pytest

import main
from conftest import FakeResponse


def _presencia_guardada(zona="casa", en_casa=True, hace_minutos=1, lat=43.26, lon=-2.93):
    # main._ahora_local() y no datetime.now() directo: así, en los tests que fijan el
    # reloj (monkeypatch sobre main._ahora_local), "hace X minutos" se cuenta desde la
    # hora fijada y no desde la hora real en que corre la suite.
    visto = main._ahora_local().astimezone(timezone.utc) - timedelta(minutes=hace_minutos)
    return FakeResponse([{
        "zona": zona, "en_casa": en_casa, "lat": lat, "lon": lon,
        "precision_m": 15.0, "fuente": "ha_companion",
        "updated_at": visto.isoformat(),
    }])


class TestAuthPresencia:
    def test_post_sin_token_forbidden(self, client):
        assert client.post("/ha/presencia", json={"zona": "casa"}).status_code == 403

    def test_post_token_incorrecto(self, client):
        r = client.post("/ha/presencia?token=malo", json={"zona": "casa"})
        assert r.status_code == 403

    def test_token_por_header_tambien_vale(self, client, mock_requests):
        r = client.post("/ha/presencia", json={"zona": "casa"}, headers={"X-Auth-Token": "ha-poll-token"})
        assert r.status_code == 200

    def test_get_requiere_jwt(self, client):
        assert client.get("/presencia").status_code in (401, 403)


class TestRegistroDePresencia:
    def test_guarda_zona_y_coordenadas(self, client, mock_requests):
        capturado = {}

        def responder(url, **kwargs):
            capturado["url"] = url
            capturado["json"] = kwargs.get("json")
            return FakeResponse([], 201)

        mock_requests.add("POST", "/rest/v1/presence", responder)
        r = client.post("/ha/presencia?token=ha-poll-token", json={
            "zona": "trabajo", "en_casa": False, "lat": 43.26, "lon": -2.93, "precision_m": 12,
        })
        assert r.status_code == 200
        assert r.json() == {"ok": True, "zona": "trabajo", "en_casa": False}
        fila = capturado["json"][0]
        assert fila["zona"] == "trabajo" and fila["en_casa"] is False
        assert fila["lat"] == 43.26
        # El upsert nombra la restricción, igual que el de health_metrics
        assert "on_conflict=id" in capturado["url"]

    def test_en_casa_se_deriva_de_la_zona_si_no_viene(self, client, mock_requests):
        r = client.post("/ha/presencia?token=ha-poll-token", json={"zona": "home"})
        assert r.json()["en_casa"] is True
        r = client.post("/ha/presencia?token=ha-poll-token", json={"zona": "gimnasio"})
        assert r.json()["en_casa"] is False

    def test_coordenadas_fuera_de_rango_dan_422(self, client):
        r = client.post("/ha/presencia?token=ha-poll-token", json={"zona": "x", "lat": 200, "lon": 0})
        assert r.status_code == 422

    def test_fallo_al_guardar_da_error_http_no_un_ok(self, client, mock_requests):
        # Quien llama es una automatización de HA que no mira el cuerpo: el fallo tiene
        # que viajar en el código de estado o pasa desapercibido (lección del 409 del Watch).
        mock_requests.add("POST", "/rest/v1/presence", FakeResponse(None, 500, text="boom"))
        r = client.post("/ha/presencia?token=ha-poll-token", json={"zona": "casa"})
        assert r.status_code == 502
        assert "boom" not in r.text


class TestVigencia:
    def test_presencia_reciente_es_vigente(self, client, auth_headers, mock_requests):
        mock_requests.add("GET", "/rest/v1/presence", _presencia_guardada(hace_minutos=5))
        d = client.get("/presencia", headers=auth_headers).json()
        assert d["conocida"] is True and d["vigente"] is True
        assert d["zona"] == "casa" and d["en_casa"] is True
        assert d["tiene_coords"] is True

    def test_presencia_vieja_se_devuelve_pero_marcada_no_vigente(self, client, auth_headers, mock_requests):
        mock_requests.add("GET", "/rest/v1/presence", _presencia_guardada(hace_minutos=600))
        d = client.get("/presencia", headers=auth_headers).json()
        assert d["conocida"] is True
        assert d["vigente"] is False
        assert d["hace_minutos"] >= 599

    def test_sin_filas_es_desconocida(self, client, auth_headers, mock_requests):
        mock_requests.add("GET", "/rest/v1/presence", FakeResponse([]))
        assert client.get("/presencia", headers=auth_headers).json() == {"conocida": False}

    def test_coords_presencia_ignora_lo_caducado(self, mock_requests):
        mock_requests.add("GET", "/rest/v1/presence", _presencia_guardada(hace_minutos=600))
        assert main.coords_presencia() is None

    def test_coords_presencia_sin_gps_devuelve_none(self, mock_requests):
        mock_requests.add("GET", "/rest/v1/presence", _presencia_guardada(lat=None, lon=None))
        assert main.coords_presencia() is None


class TestGeolocalizacionDerivada:
    """La presencia entra en el escalón de en medio: por debajo de lo que manda el
    dispositivo y por encima de las coordenadas fijas."""

    OPEN_METEO = {
        "current": {"temperature_2m": 18.0, "weather_code": 0},
        "daily": {"time": ["2026-08-04"], "weather_code": [0],
                  "temperature_2m_max": [20.0], "temperature_2m_min": [10.0]},
    }

    def _capturar_meteo(self, mock_requests):
        capturado = {}

        def responder(url, **kwargs):
            capturado["params"] = kwargs.get("params", {})
            return FakeResponse(self.OPEN_METEO)

        mock_requests.add("GET", "open-meteo.com", responder)
        return capturado

    def test_weather_usa_la_presencia_si_el_navegador_no_manda_nada(self, client, auth_headers, mock_requests):
        mock_requests.add("GET", "/rest/v1/presence", _presencia_guardada(lat=40.1, lon=-3.5))
        capturado = self._capturar_meteo(mock_requests)
        assert client.get("/weather", headers=auth_headers).status_code == 200
        assert capturado["params"]["latitude"] == 40.1
        assert capturado["params"]["longitude"] == -3.5

    def test_lo_que_manda_el_dispositivo_gana_a_la_presencia(self, client, auth_headers, mock_requests):
        mock_requests.add("GET", "/rest/v1/presence", _presencia_guardada(lat=40.1, lon=-3.5))
        capturado = self._capturar_meteo(mock_requests)
        client.get("/weather?lat=43.26&lon=-2.93", headers=auth_headers)
        assert capturado["params"]["latitude"] == 43.26

    def test_presencia_caducada_cae_a_las_coordenadas_fijas(self, client, auth_headers, mock_requests):
        mock_requests.add("GET", "/rest/v1/presence", _presencia_guardada(hace_minutos=600, lat=40.1, lon=-3.5))
        capturado = self._capturar_meteo(mock_requests)
        client.get("/weather", headers=auth_headers)
        assert capturado["params"]["latitude"] == main.WEATHER_LAT

    def test_departure_sale_desde_donde_estas(self, client, auth_headers, mock_requests):
        mock_requests.add("GET", "/rest/v1/presence", _presencia_guardada(lat=43.26, lon=-2.93))
        capturado = {}

        def responder(url, **kwargs):
            capturado["params"] = kwargs.get("params", {})
            return FakeResponse({"rows": [{"elements": [{
                "status": "OK",
                "duration": {"value": 600, "text": "10 min"},
                "duration_in_traffic": {"value": 600, "text": "10 min"},
                "distance": {"text": "5 km"},
            }]}]})

        mock_requests.add("GET", "maps.googleapis.com", responder)
        r = client.post("/maps/departure", headers=auth_headers, json={
            "destination": "X", "event_time": "2026-08-04T10:00:00Z",
        })
        assert r.status_code == 200
        assert capturado["params"]["origins"] == "43.26,-2.93"

    def test_departure_respeta_el_origen_del_dispositivo(self, client, auth_headers, mock_requests):
        mock_requests.add("GET", "/rest/v1/presence", _presencia_guardada(lat=43.26, lon=-2.93))
        capturado = {}

        def responder(url, **kwargs):
            capturado["params"] = kwargs.get("params", {})
            return FakeResponse({"rows": [{"elements": [{
                "status": "OK",
                "duration": {"value": 600, "text": "10 min"},
                "duration_in_traffic": {"value": 600, "text": "10 min"},
                "distance": {"text": "5 km"},
            }]}]})

        mock_requests.add("GET", "maps.googleapis.com", responder)
        client.post("/maps/departure", headers=auth_headers, json={
            "destination": "X", "event_time": "2026-08-04T10:00:00Z", "origin": "1.0,2.0",
        })
        assert capturado["params"]["origins"] == "1.0,2.0"

    def test_sin_presencia_cae_a_home_address(self, client, auth_headers, mock_requests):
        capturado = {}

        def responder(url, **kwargs):
            capturado["params"] = kwargs.get("params", {})
            return FakeResponse({"rows": [{"elements": [{
                "status": "OK",
                "duration": {"value": 600, "text": "10 min"},
                "duration_in_traffic": {"value": 600, "text": "10 min"},
                "distance": {"text": "5 km"},
            }]}]})

        mock_requests.add("GET", "maps.googleapis.com", responder)
        client.post("/maps/departure", headers=auth_headers, json={
            "destination": "X", "event_time": "2026-08-04T10:00:00Z",
        })
        assert capturado["params"]["origins"] == main.HOME_ADDRESS


class TestTramosPorDia:
    def test_tramo_dentro_del_mismo_dia(self):
        inicio = datetime(2026, 8, 4, 10, 0, tzinfo=main.LOCAL_TZ)
        tramos = main._tramos_por_dia(inicio, inicio + timedelta(hours=2))
        assert tramos == [("2026-08-04", 2.0)]

    def test_tramo_que_cruza_medianoche_se_reparte(self):
        # El tramo nocturno es el que más pesa al cruzar presencia con sueño: imputarlo
        # entero al día en que empezó desplazaría media noche de datos.
        inicio = datetime(2026, 8, 4, 23, 0, tzinfo=main.LOCAL_TZ)
        tramos = main._tramos_por_dia(inicio, inicio + timedelta(hours=3))
        assert tramos == [("2026-08-04", 1.0), ("2026-08-05", 2.0)]

    def test_fin_anterior_al_inicio_no_produce_tramos(self):
        ahora = datetime(2026, 8, 4, 10, 0, tzinfo=main.LOCAL_TZ)
        assert main._tramos_por_dia(ahora, ahora - timedelta(hours=1)) == []


class TestAcumulacionDiaria:
    @pytest.fixture(autouse=True)
    def _mediodia(self, monkeypatch):
        # Fijo a mediodía local: sin esto, "60 minutos en casa" cruza la medianoche
        # local cuando la suite corre justo después de las 22:00 UTC (verano, UTC+2) y
        # el tramo se reparte entre ayer y hoy — que es justo lo que prueba
        # TestPartidoEntreDias más abajo, pero no lo que quieren probar estos tests.
        monkeypatch.setattr(main, "_ahora_local",
                             lambda: datetime(2026, 8, 24, 12, 0, tzinfo=main.LOCAL_TZ))

    def _capturar_upsert(self, mock_requests):
        escrito = {}

        def responder(url, **kwargs):
            escrito["filas"] = kwargs.get("json")
            return FakeResponse([], 201)

        mock_requests.add("POST", "/rest/v1/health_metrics", responder)
        return escrito

    def test_suma_horas_en_casa_al_dia_correspondiente(self, client, mock_requests):
        mock_requests.add("GET", "/rest/v1/presence", _presencia_guardada(en_casa=True, hace_minutos=60))
        mock_requests.add("GET", "/rest/v1/health_metrics", FakeResponse([]))
        escrito = self._capturar_upsert(mock_requests)

        client.post("/ha/presencia?token=ha-poll-token", json={"zona": "trabajo", "en_casa": False})

        fila = escrito["filas"][0]
        assert fila["metric_name"] == "time_at_home"
        assert 0.9 <= fila["value"] <= 1.1     # la hora que estuvo en casa
        assert fila["unit"] == "hr"

    def test_el_tiempo_fuera_va_a_extra_no_a_value(self, client, mock_requests):
        mock_requests.add("GET", "/rest/v1/presence", _presencia_guardada(en_casa=False, hace_minutos=60))
        mock_requests.add("GET", "/rest/v1/health_metrics", FakeResponse([]))
        escrito = self._capturar_upsert(mock_requests)

        client.post("/ha/presencia?token=ha-poll-token", json={"zona": "casa"})

        fila = escrito["filas"][0]
        assert fila["value"] == 0
        assert 0.9 <= fila["extra"]["fuera"] <= 1.1

    def test_acumula_sobre_lo_ya_guardado(self, client, mock_requests):
        hoy = main._ahora_local().date().isoformat()   # sigue al reloj fijado arriba
        mock_requests.add("GET", "/rest/v1/presence", _presencia_guardada(en_casa=True, hace_minutos=60))
        mock_requests.add("GET", "/rest/v1/health_metrics", FakeResponse([
            {"metric_date": hoy, "metric_name": "time_at_home", "value": 5.0, "extra": {"fuera": 2.0}},
        ]))
        escrito = self._capturar_upsert(mock_requests)

        client.post("/ha/presencia?token=ha-poll-token", json={"zona": "trabajo", "en_casa": False})

        fila = next(f for f in escrito["filas"] if f["metric_date"] == hoy)
        assert 5.9 <= fila["value"] <= 6.1      # 5 h previas + 1 h nueva
        assert fila["extra"]["fuera"] == 2.0    # lo de fuera no se toca

    def test_hueco_largo_no_se_contabiliza(self, client, mock_requests):
        # HA estuvo horas sin mandar nada: no sabemos dónde estuviste, así que ese tramo
        # se descarta en vez de imputarlo entero a la última zona conocida.
        mock_requests.add("GET", "/rest/v1/presence", _presencia_guardada(en_casa=True, hace_minutos=600))
        escrito = self._capturar_upsert(mock_requests)

        client.post("/ha/presencia?token=ha-poll-token", json={"zona": "casa"})

        assert "filas" not in escrito

    def test_primer_aviso_sin_estado_previo_no_acumula(self, client, mock_requests):
        mock_requests.add("GET", "/rest/v1/presence", FakeResponse([]))
        escrito = self._capturar_upsert(mock_requests)

        r = client.post("/ha/presencia?token=ha-poll-token", json={"zona": "casa"})

        assert r.status_code == 200
        assert "filas" not in escrito

    def test_un_fallo_de_la_serie_no_tumba_el_aviso(self, client, mock_requests):
        # La serie diaria es un derivado: el efecto principal del aviso (saber dónde
        # estás ahora) tiene que funcionar aunque el upsert de la métrica falle.
        mock_requests.add("GET", "/rest/v1/presence", _presencia_guardada(en_casa=True, hace_minutos=30))
        mock_requests.add("GET", "/rest/v1/health_metrics", FakeResponse([]))
        mock_requests.add("POST", "/rest/v1/health_metrics", FakeResponse(None, 500, text="nope"))

        r = client.post("/ha/presencia?token=ha-poll-token", json={"zona": "casa"})
        assert r.status_code == 200


class TestCacheEnMemoria:
    def test_la_lectura_no_repite_viaje_a_supabase(self, client, auth_headers, mock_requests):
        mock_requests.add("GET", "/rest/v1/presence", _presencia_guardada())
        client.get("/presencia", headers=auth_headers)
        client.get("/presencia", headers=auth_headers)
        assert len(mock_requests.called("GET", "/rest/v1/presence")) == 1

    def test_un_aviso_nuevo_actualiza_la_copia(self, client, auth_headers, mock_requests):
        mock_requests.add("GET", "/rest/v1/presence", _presencia_guardada(zona="casa", en_casa=True))
        assert client.get("/presencia", headers=auth_headers).json()["zona"] == "casa"

        client.post("/ha/presencia?token=ha-poll-token", json={"zona": "gimnasio"})
        d = client.get("/presencia", headers=auth_headers).json()
        assert d["zona"] == "gimnasio" and d["en_casa"] is False
