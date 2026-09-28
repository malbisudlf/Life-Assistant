"""Las tareas de Microsoft To Do.

Van con el mismo token de Graph que el calendario, así que lo delicado no es la API sino
lo de alrededor: que encender el permiso nuevo no se lleve por delante lo que ya
funcionaba, que las fechas no se corran un día por la zona horaria, y que Jarvis solo
proponga (nunca cree) y solo vea las herramientas si están encendidas.
"""
import pytest

import main
from conftest import FakeResponse

LISTAS = FakeResponse({"value": [
    {"id": "lista-otra", "displayName": "Compra", "wellknownListName": "none"},
    {"id": "lista-def", "displayName": "Tareas", "wellknownListName": "defaultList"},
]})


@pytest.fixture
def encendidas(monkeypatch, graph_token):
    monkeypatch.setattr(main, "TAREAS_TODO", True)


class TestLosPermisos:
    def test_apagadas_no_se_pide_el_permiso(self, monkeypatch):
        monkeypatch.setattr(main, "TAREAS_TODO", False)
        assert "Tasks.ReadWrite" not in main._scopes()

    def test_encendidas_se_pide(self, monkeypatch):
        monkeypatch.setattr(main, "TAREAS_TODO", True)
        assert "Tasks.ReadWrite" in main._scopes()
        assert set(main.SCOPES_BASE) <= set(main._scopes())

    def test_sin_reconsentir_no_se_pierde_el_correo(self, monkeypatch, mock_requests):
        """Con el correo ya consentido y las tareas recién encendidas, la renovación prueba
        antes quitando SOLO las tareas: con un único repuesto (los permisos de siempre),
        encender las tareas se llevaba también el buzón hasta reconectar."""
        monkeypatch.setattr(main, "CORREO_LEER", True)
        monkeypatch.setattr(main, "TAREAS_TODO", True)
        mock_requests.add("GET", "oauth_tokens", FakeResponse(
            [{"access_token": "viejo", "refresh_token": "r", "expires_at": 0}], 200))
        pedidos = []

        class _Msal:
            def acquire_token_by_refresh_token(self, refresh_token, scopes):
                pedidos.append(list(scopes))
                if "Tasks.ReadWrite" in scopes:
                    return {"error": "invalid_grant"}
                return {"access_token": "nuevo", "refresh_token": "r", "expires_in": 3600}

        monkeypatch.setattr(main, "_msal_app", lambda: _Msal())
        assert main.get_valid_token() == "nuevo"
        assert len(pedidos) == 2
        assert "Mail.ReadWrite" in pedidos[1] and "Tasks.ReadWrite" not in pedidos[1]


class TestLeer:
    def test_la_lista_por_defecto_y_la_fecha_en_hora_local(self, encendidas, mock_requests):
        """To Do devuelve el vencimiento en UTC: la medianoche del 1 de octubre en Madrid
        llega como las 22:00 del 30 de septiembre. Tomada tal cual, adelantaba un día."""
        mock_requests.add("GET", "/lista-def/tasks", FakeResponse({"value": [
            {"id": "t2", "title": "Sin fecha", "importance": "normal"},
            {"id": "t1", "title": "Pasar el contrato", "importance": "high",
             "dueDateTime": {"dateTime": "2026-09-30T22:00:00.0000000", "timeZone": "UTC"}},
        ]}))
        mock_requests.add("GET", "/me/todo/lists", LISTAS)

        tareas = main._todo_pendientes()

        assert tareas == [
            {"id": "t1", "titulo": "Pasar el contrato", "fecha": "2026-10-01", "importante": True},
            {"id": "t2", "titulo": "Sin fecha", "fecha": None, "importante": False},
        ]
        url = mock_requests.called("GET", "/tasks")[0][1]
        assert "status ne 'completed'" in url

    def test_la_lista_se_recuerda(self, encendidas, mock_requests):
        mock_requests.add("GET", "/lista-def/tasks", FakeResponse({"value": []}))
        mock_requests.add("GET", "/me/todo/lists", LISTAS)
        main._todo_pendientes()
        main._todo_pendientes()
        assert len([c for c in mock_requests.calls if c[1].split("?")[0].endswith("/lists")]) == 1

    def test_un_404_con_la_lista_recordada_la_vuelve_a_buscar(self, encendidas, mock_requests):
        main._todo_lista_cache.update(id="lista-vieja", ts=main.time.time())
        mock_requests.add("GET", "/lista-vieja/tasks", FakeResponse({}, 404))
        mock_requests.add("GET", "/lista-def/tasks", FakeResponse({"value": []}))
        mock_requests.add("GET", "/me/todo/lists", LISTAS)
        assert main._todo_pendientes() == []

    def test_sin_permiso_lo_dice_con_su_arreglo(self, client, auth_headers, encendidas,
                                               mock_requests):
        mock_requests.add("GET", "/me/todo/lists", FakeResponse({"error": "x"}, 403))
        r = client.get("/tareas", headers=auth_headers)
        assert r.status_code == 200
        assert r.json()["activo"] is False
        assert "vuelve a conectar Outlook" in r.json()["motivo"]

    def test_apagadas_no_llaman_a_graph(self, client, auth_headers, mock_requests):
        r = client.get("/tareas", headers=auth_headers)
        assert r.json() == {"activo": False, "tareas": [],
                            "motivo": "Las tareas están apagadas (TAREAS_TODO=0)."}
        assert mock_requests.calls == []

    def test_sin_sesion_no(self, client):
        assert client.get("/tareas").status_code in (401, 403)


class TestCrear:
    def test_crea_con_la_fecha_a_medianoche_local(self, encendidas, mock_requests):
        mock_requests.add("GET", "/me/todo/lists", LISTAS)
        mock_requests.add("POST", "/lista-def/tasks", FakeResponse({"id": "nueva"}, 201))
        r = main._j_crear_tarea("Pasar el contrato", "2026-10-01", "a Luis")
        assert r == {"ok": True, "id": "nueva", "titulo": "Pasar el contrato",
                     "fecha": "2026-10-01"}
        cuerpo = mock_requests.called("POST", "/tasks")[0][2]["json"]
        assert cuerpo["dueDateTime"] == {"dateTime": "2026-10-01T00:00:00",
                                         "timeZone": str(main.LOCAL_TZ)}
        assert cuerpo["body"] == {"content": "a Luis", "contentType": "text"}

    @pytest.mark.parametrize("fecha", ["mañana", "2026-02-30"])
    def test_una_fecha_sin_forma_no_llega_a_graph(self, encendidas, mock_requests, fecha):
        assert main._j_crear_tarea("Algo", fecha)["ok"] is False
        assert mock_requests.calls == []

    def test_sin_titulo_no(self, encendidas, mock_requests):
        assert main._j_crear_tarea("  ")["ok"] is False
        assert mock_requests.calls == []

    def test_apagadas_no_crea(self, graph_token, mock_requests):
        r = main._j_crear_tarea("Algo")
        assert r["ok"] is False and "TAREAS_TODO" in r["motivo"]
        assert mock_requests.calls == []


class TestJarvis:
    def test_crear_pide_confirmacion(self):
        assert main._JARVIS_HERRAMIENTAS["crear_tarea"]["confirmar"] is True
        assert main._JARVIS_HERRAMIENTAS["tareas"]["confirmar"] is False

    def test_solo_se_anuncian_encendidas(self, monkeypatch):
        nombres = lambda: {f["function"]["name"] for f in main._jarvis_esquema()}  # noqa: E731
        assert not {"tareas", "crear_tarea"} & nombres()
        monkeypatch.setattr(main, "TAREAS_TODO", True)
        assert {"tareas", "crear_tarea"} <= nombres()

    def test_ejecutar_la_propuesta(self, client, auth_headers, encendidas, mock_requests):
        mock_requests.add("GET", "/me/todo/lists", LISTAS)
        mock_requests.add("POST", "/lista-def/tasks", FakeResponse({"id": "nueva"}, 201))
        r = client.post("/jarvis/ejecutar", headers=auth_headers, json={
            "herramienta": "crear_tarea", "argumentos": {"titulo": "Llamar al taller"}})
        assert r.status_code == 200
        assert mock_requests.called("POST", "/lista-def/tasks")
