"""Tests de la integración con Home Assistant (poll de eventos y Wake-on-LAN)."""
from datetime import datetime, timedelta, timezone

import main
from conftest import FakeResponse


def _graph_events(*starts_minutes, all_day=False):
    now = datetime.now(timezone.utc)
    return FakeResponse({
        "value": [
            {
                "subject": f"Evento {m}",
                "start": {"dateTime": (now + timedelta(minutes=m)).strftime("%Y-%m-%dT%H:%M:%SZ"), "timeZone": "UTC"},
                "isAllDay": all_day,
            }
            for m in starts_minutes
        ]
    })


class TestHaEventsSoon:
    def test_sin_token_forbidden(self, client):
        assert client.get("/ha/events/soon").status_code == 403

    def test_token_incorrecto(self, client):
        assert client.get("/ha/events/soon?token=malo").status_code == 403

    def test_evento_a_15_min_se_notifica(self, client, graph_token, mock_requests):
        mock_requests.add("GET", "graph.microsoft.com", _graph_events(15))
        r = client.get("/ha/events/soon?token=ha-poll-token")
        assert r.status_code == 200
        assert r.json()["event"]["title"] == "Evento 15"

    def test_token_por_header_tambien_vale(self, client, graph_token, mock_requests):
        mock_requests.add("GET", "graph.microsoft.com", _graph_events(15))
        r = client.get("/ha/events/soon", headers={"X-Auth-Token": "ha-poll-token"})
        assert r.status_code == 200
        assert r.json()["event"] is not None

    def test_evento_lejano_no_se_notifica(self, client, graph_token, mock_requests):
        mock_requests.add("GET", "graph.microsoft.com", _graph_events(45))
        r = client.get("/ha/events/soon?token=ha-poll-token")
        assert r.json() == {"event": None}

    def test_evento_de_dia_completo_se_ignora(self, client, graph_token, mock_requests):
        mock_requests.add("GET", "graph.microsoft.com", _graph_events(15, all_day=True))
        r = client.get("/ha/events/soon?token=ha-poll-token")
        assert r.json() == {"event": None}

    def test_sin_sesion_graph_devuelve_none(self, client, monkeypatch):
        monkeypatch.setattr(main, "get_valid_token", lambda: None)
        r = client.get("/ha/events/soon?token=ha-poll-token")
        assert r.json() == {"event": None}


class TestWakeOnLan:
    def test_wake_pc_requiere_jwt(self, client):
        assert client.post("/wake-pc").status_code in (401, 403)

    def test_wol_pending_requiere_token_servicio(self, client):
        assert client.get("/ha/wol-pending").status_code == 403

    def test_flujo_completo(self, client, auth_headers):
        # Sin WOL marcado, el poll devuelve false
        r = client.get("/ha/wol-pending?token=ha-poll-token")
        assert r.json() == {"pending": False}
        # El dashboard marca WOL
        assert client.post("/wake-pc", headers=auth_headers).json() == {"ok": True}
        # El primer poll lo recoge y lo limpia
        assert client.get("/ha/wol-pending?token=ha-poll-token").json() == {"pending": True}
        assert client.get("/ha/wol-pending?token=ha-poll-token").json() == {"pending": False}


class TestRelaunchAgent:
    def test_relaunch_agent_requiere_jwt(self, client):
        assert client.post("/relaunch-agent").status_code in (401, 403)

    def test_relaunch_pending_requiere_token_servicio(self, client):
        assert client.get("/ha/agent-relaunch-pending").status_code == 403

    def test_flujo_completo(self, client, auth_headers):
        # Sin relanzado marcado, el poll devuelve false
        assert client.get("/ha/agent-relaunch-pending?token=ha-poll-token").json() == {"pending": False}
        # El dashboard marca relanzado
        assert client.post("/relaunch-agent", headers=auth_headers).json() == {"ok": True}
        # El primer poll lo recoge y lo limpia
        assert client.get("/ha/agent-relaunch-pending?token=ha-poll-token").json() == {"pending": True}
        assert client.get("/ha/agent-relaunch-pending?token=ha-poll-token").json() == {"pending": False}

    def test_wol_y_relanzado_son_flags_independientes(self, client, auth_headers):
        # Marcar solo WOL no debe activar el relanzado
        client.post("/wake-pc", headers=auth_headers)
        assert client.get("/ha/agent-relaunch-pending?token=ha-poll-token").json() == {"pending": False}
        assert client.get("/ha/wol-pending?token=ha-poll-token").json() == {"pending": True}


class TestPcPower:
    def test_shutdown_requiere_jwt(self, client):
        assert client.post("/shutdown-pc").status_code in (401, 403)

    def test_suspend_requiere_jwt(self, client):
        assert client.post("/suspend-pc").status_code in (401, 403)

    def test_power_pending_requiere_token_servicio(self, client):
        assert client.get("/ha/pc-power-pending").status_code == 403

    def test_flujo_apagar(self, client, auth_headers):
        # Sin acción marcada, el poll devuelve null
        assert client.get("/ha/pc-power-pending?token=ha-poll-token").json() == {"action": None}
        # El dashboard pide apagar
        assert client.post("/shutdown-pc", headers=auth_headers).json() == {"ok": True}
        # El primer poll la recoge y la limpia
        assert client.get("/ha/pc-power-pending?token=ha-poll-token").json() == {"action": "shutdown"}
        assert client.get("/ha/pc-power-pending?token=ha-poll-token").json() == {"action": None}

    def test_flujo_suspender(self, client, auth_headers):
        client.post("/suspend-pc", headers=auth_headers)
        assert client.get("/ha/pc-power-pending?token=ha-poll-token").json() == {"action": "suspend"}
        assert client.get("/ha/pc-power-pending?token=ha-poll-token").json() == {"action": None}

    def test_la_ultima_accion_gana(self, client, auth_headers):
        # Si se piden dos, prevalece la última marcada
        client.post("/suspend-pc", headers=auth_headers)
        client.post("/shutdown-pc", headers=auth_headers)
        assert client.get("/ha/pc-power-pending?token=ha-poll-token").json() == {"action": "shutdown"}
