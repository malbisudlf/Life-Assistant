"""Tests de los endpoints de calendario (Microsoft Graph simulado)."""
import main
from conftest import FakeResponse


class TestGetEvents:
    def test_requiere_jwt(self, client):
        assert client.get("/calendar/events").status_code in (401, 403)

    def test_sin_sesion_graph(self, client, auth_headers, monkeypatch):
        monkeypatch.setattr(main, "get_valid_token", lambda: None)
        r = client.get("/calendar/events", headers=auth_headers)
        assert r.status_code == 200
        assert "error" in r.json()

    def test_normaliza_eventos_y_extrae_alud_url(self, client, auth_headers, graph_token, mock_requests):
        mock_requests.add("GET", "graph.microsoft.com", FakeResponse({
            "value": [{
                "id": "ev1",
                "subject": "05 - Redes Grupo: 1 - Asignatura",
                "start": {"dateTime": "2026-07-06T10:00:00.0000000", "timeZone": "Romance Standard Time"},
                "end": {"dateTime": "2026-07-06T12:00:00.0000000", "timeZone": "Romance Standard Time"},
                "location": {"displayName": "Aula 3"},
                "body": {"content": "Entrega: alud_url: https://alud.deusto.es/mod/assign/view.php?id=99</p>"},
                "bodyPreview": "Entrega",
                "isAllDay": False,
            }]
        }))
        r = client.get("/calendar/events", headers=auth_headers)
        assert r.status_code == 200
        ev = r.json()["events"][0]
        assert ev["title"] == "Redes"
        assert ev["start"] == "2026-07-06T08:00:00Z"  # Paris verano → UTC-2h
        assert ev["end"] == "2026-07-06T10:00:00Z"
        assert ev["location"] == "Aula 3"
        assert ev["alud_url"] == "https://alud.deusto.es/mod/assign/view.php?id=99"
        assert ev["isAllDay"] is False

    def test_sin_eventos(self, client, auth_headers, graph_token, mock_requests):
        mock_requests.add("GET", "graph.microsoft.com", FakeResponse({"value": []}))
        r = client.get("/calendar/events", headers=auth_headers)
        assert r.json() == {"events": []}


class TestCreateEvent:
    def test_crea_evento_en_outlook(self, client, auth_headers, graph_token, mock_requests):
        mock_requests.add("POST", "graph.microsoft.com/v1.0/me/events", FakeResponse({"id": "nuevo-ev"}, 201))
        r = client.post("/calendar/events", headers=auth_headers, json={
            "subject": "Dentista",
            "start": "2026-07-10T09:00:00",
            "end": "2026-07-10T09:30:00",
            "location": "Clínica",
        })
        assert r.status_code == 200
        assert r.json() == {"status": "ok", "id": "nuevo-ev"}
        payload = mock_requests.called("POST", "graph.microsoft.com")[0][2]["json"]
        assert payload["start"] == {"dateTime": "2026-07-10T09:00:00", "timeZone": "Europe/Madrid"}
        assert payload["location"] == {"displayName": "Clínica"}

    def test_usa_calendario_especifico_si_se_indica(self, client, auth_headers, graph_token, mock_requests):
        mock_requests.add("POST", "/me/calendars/cal-123/events", FakeResponse({"id": "ev2"}, 201))
        r = client.post("/calendar/events", headers=auth_headers, json={
            "subject": "Clase", "start": "2026-07-10T09:00:00", "end": "2026-07-10T10:00:00",
            "calendar_id": "cal-123",
        })
        assert r.json()["status"] == "ok"
        assert mock_requests.called("POST", "/me/calendars/cal-123/events")

    def test_error_de_graph_no_revienta(self, client, auth_headers, graph_token, mock_requests):
        mock_requests.add("POST", "graph.microsoft.com", FakeResponse({"error": "x"}, 400, "bad request"))
        r = client.post("/calendar/events", headers=auth_headers, json={
            "subject": "X", "start": "2026-07-10T09:00:00", "end": "2026-07-10T10:00:00",
        })
        assert r.status_code == 200
        assert "error" in r.json()


class TestUpdateEvent:
    def test_actualiza_campos_enviados(self, client, auth_headers, graph_token, mock_requests):
        mock_requests.add("PATCH", "graph.microsoft.com", FakeResponse({}, 200))
        r = client.patch("/calendar/events/ev1", headers=auth_headers, json={"subject": "Nuevo título"})
        assert r.json() == {"status": "ok"}
        payload = mock_requests.called("PATCH", "graph.microsoft.com")[0][2]["json"]
        assert payload == {"subject": "Nuevo título"}

    def test_body_vacio_da_400(self, client, auth_headers, graph_token):
        r = client.patch("/calendar/events/ev1", headers=auth_headers, json={})
        assert r.status_code == 400


class TestClasses:
    def test_calendario_clases_no_existe(self, client, auth_headers, graph_token, mock_requests):
        mock_requests.add("GET", "/me/calendars", FakeResponse({
            "value": [{"id": "c1", "name": "Calendario"}]
        }))
        r = client.get("/calendar/classes", headers=auth_headers)
        assert r.status_code == 200
        data = r.json()
        assert "error" in data
        assert data["available"] == ["Calendario"]

    def test_devuelve_clases_normalizadas(self, client, auth_headers, graph_token, mock_requests):
        mock_requests.add("GET", "/calendars/cal-clases/calendarView", FakeResponse({
            "value": [{
                "id": "cl1",
                "subject": "10 - Sistemas Operativos Grupo: 3 - Asignatura",
                "start": {"dateTime": "2026-07-07T08:00:00Z", "timeZone": "UTC"},
                "end": {"dateTime": "2026-07-07T10:00:00Z", "timeZone": "UTC"},
                "location": {"displayName": "Lab 2"},
                "isAllDay": False,
            }]
        }))
        mock_requests.add("GET", "/me/calendars", FakeResponse({
            "value": [{"id": "cal-clases", "name": "Clases"}]
        }))
        r = client.get("/calendar/classes", headers=auth_headers)
        assert r.status_code == 200
        ev = r.json()["events"][0]
        assert ev["title"] == "Sistemas Operativos"
        assert ev["start"] == "2026-07-07T08:00:00Z"
        assert ev["location"] == "Lab 2"

    def test_nombre_del_calendario_es_configurable(self, client, auth_headers, graph_token, mock_requests, monkeypatch):
        monkeypatch.setattr(main, "CLASSES_CALENDAR", "horario")
        mock_requests.add("GET", "/calendars/cal-h/calendarView", FakeResponse({"value": []}))
        mock_requests.add("GET", "/me/calendars", FakeResponse({
            "value": [{"id": "cal-h", "name": "Horario"}]   # coincide sin distinguir mayúsculas
        }))
        r = client.get("/calendar/classes", headers=auth_headers)
        assert r.status_code == 200
        assert r.json() == {"events": []}

    def test_list_calendars(self, client, auth_headers, graph_token, mock_requests):
        mock_requests.add("GET", "/me/calendars", FakeResponse({
            "value": [{"id": "c1", "name": "Calendario", "otros": "campos"}]
        }))
        r = client.get("/calendar/calendars", headers=auth_headers)
        assert r.json() == [{"id": "c1", "name": "Calendario"}]
