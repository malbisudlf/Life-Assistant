"""Tests de notificaciones push (Web Push).

El envío real no se puede probar aquí (hace falta un servicio de push de verdad),
así que se cubre todo lo demás: autorización, dedupe, ventana de aviso y que la
funcionalidad esté apagada de forma segura cuando no hay claves VAPID.
"""
import main
from conftest import FakeResponse


class TestPushSinConfigurar:
    """Sin claves VAPID el push queda apagado, pero nada revienta (lección de C5)."""

    def test_clave_publica_dice_que_no_esta_habilitado(self, client, auth_headers):
        r = client.get("/push/clave-publica", headers=auth_headers)
        assert r.json() == {"habilitado": False, "clave": None}

    def test_suscribir_da_503_no_500(self, client, auth_headers):
        r = client.post("/push/suscribir", headers=auth_headers, json={
            "endpoint": "https://push.example/abc", "p256dh": "k", "auth": "a",
        })
        assert r.status_code == 503
        assert "VAPID" in r.json()["detail"]

    def test_enviar_push_no_lanza(self):
        assert main.enviar_push("t", "c")["enviados"] == 0

    def test_el_tick_de_ha_no_falla(self, client):
        r = client.post("/ha/push-eventos", headers={"X-Auth-Token": "ha-poll-token"})
        assert r.status_code == 200
        assert r.json()["enviados"] == 0


class TestPushAutorizacion:
    def test_suscribir_requiere_jwt(self, client):
        assert client.post("/push/suscribir", json={
            "endpoint": "https://push.example/abc", "p256dh": "k", "auth": "a",
        }).status_code in (401, 403)

    def test_el_tick_requiere_token_de_servicio(self, client):
        assert client.post("/ha/push-eventos").status_code == 403
        assert client.post("/ha/push-eventos", headers={"X-Auth-Token": "malo"}).status_code == 403


class TestPushHabilitado:
    def _habilitar(self, monkeypatch):
        monkeypatch.setattr(main, "PUSH_HABILITADO", True)
        monkeypatch.setattr(main, "VAPID_PUBLIC_KEY", "clave-publica-test")

    def test_clave_publica_se_expone_al_frontend(self, client, auth_headers, monkeypatch):
        self._habilitar(monkeypatch)
        assert client.get("/push/clave-publica", headers=auth_headers).json() == {
            "habilitado": True, "clave": "clave-publica-test",
        }

    def test_suscribir_guarda_la_suscripcion(self, client, auth_headers, mock_requests, monkeypatch):
        self._habilitar(monkeypatch)
        mock_requests.add("POST", "/rest/v1/push_subscriptions", FakeResponse([], 201))
        r = client.post("/push/suscribir", headers=auth_headers, json={
            "endpoint": "https://push.example/abc", "p256dh": "k", "auth": "a",
            "user_agent": "iPhone",
        })
        assert r.json() == {"ok": True}
        cuerpo = mock_requests.called("POST", "/rest/v1/push_subscriptions")[0][2]["json"]
        assert cuerpo["endpoint"] == "https://push.example/abc"

    def test_desuscribir_escapa_el_endpoint_en_la_url(self, client, auth_headers, mock_requests):
        # El endpoint es una URL entera: sin escapar rompería la query de Supabase.
        client.post("/push/desuscribir", headers=auth_headers, json={
            "endpoint": "https://push.example/abc?x=1&y=2", "p256dh": "k", "auth": "a",
        })
        url = mock_requests.called("DELETE", "/rest/v1/push_subscriptions")[0][1]
        assert "%3A" in url and "%26" in url


class TestDedupe:
    """El dedupe vive en Supabase porque HA dispara cada minuto y Fly escala a cero:
    en memoria se perdería en cada arranque en frío y el aviso se repetiría."""

    def test_primera_vez_envia(self, mock_requests):
        mock_requests.add("POST", "/rest/v1/push_enviados", FakeResponse([], 201))
        assert main._push_marcar_enviado("evento:1:2026-07-28T10:00:00Z") is True

    def test_segunda_vez_no_envia(self, mock_requests):
        mock_requests.add("POST", "/rest/v1/push_enviados", FakeResponse(None, 409))
        assert main._push_marcar_enviado("evento:1:2026-07-28T10:00:00Z") is False

    def test_ante_un_error_de_bd_no_envia(self, mock_requests):
        # Callarse molesta menos que repetir el mismo aviso cada minuto.
        mock_requests.add("POST", "/rest/v1/push_enviados", FakeResponse(None, 500))
        assert main._push_marcar_enviado("x") is False


class TestVentanaDeAviso:
    """La ventana 13–17 min es la misma que /ha/events/soon, para que un evento no se
    cuele entre dos sondeos de HA (que llama cada minuto)."""

    def _evento(self, minutos, ident="ev-1"):
        from datetime import datetime, timedelta, timezone
        inicio = datetime.now(timezone.utc) + timedelta(minutes=minutos)
        return {
            "id": ident,
            "subject": "Reunión TFG",
            "isAllDay": False,
            "start": {"dateTime": inicio.strftime("%Y-%m-%dT%H:%M:%S"), "timeZone": "UTC"},
            "location": {"displayName": "Sala 3"},
        }

    def _tick(self, client, mock_requests, monkeypatch, eventos):
        monkeypatch.setattr(main, "PUSH_HABILITADO", True)
        mock_requests.add("GET", "graph.microsoft.com", FakeResponse({"value": eventos}))
        mock_requests.add("POST", "/rest/v1/push_enviados", FakeResponse([], 201))
        return client.post("/ha/push-eventos", headers={"X-Auth-Token": "ha-poll-token"})

    def test_avisa_de_un_evento_a_15_minutos(self, client, auth_headers, graph_token, mock_requests, monkeypatch):
        self._tick(client, mock_requests, monkeypatch, [self._evento(15)])
        marcas = mock_requests.called("POST", "/rest/v1/push_enviados")
        assert len(marcas) == 1
        assert "ev-1" in marcas[0][2]["json"]["clave"]

    def test_no_avisa_de_uno_lejano_ni_de_uno_inminente(self, client, auth_headers, graph_token, mock_requests, monkeypatch):
        self._tick(client, mock_requests, monkeypatch, [self._evento(45, "lejos"), self._evento(2, "ya")])
        assert mock_requests.called("POST", "/rest/v1/push_enviados") == []

    def test_ignora_los_eventos_de_todo_el_dia(self, client, auth_headers, graph_token, mock_requests, monkeypatch):
        ev = self._evento(15)
        ev["isAllDay"] = True
        self._tick(client, mock_requests, monkeypatch, [ev])
        assert mock_requests.called("POST", "/rest/v1/push_enviados") == []

    def test_si_graph_falla_no_revienta(self, client, auth_headers, graph_token, mock_requests, monkeypatch):
        monkeypatch.setattr(main, "PUSH_HABILITADO", True)
        mock_requests.add("GET", "graph.microsoft.com", FakeResponse(None, 500, "boom"))
        r = client.post("/ha/push-eventos", headers={"X-Auth-Token": "ha-poll-token"})
        assert r.status_code == 200 and r.json()["enviados"] == 0
        assert "boom" not in r.text
