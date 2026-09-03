"""Tests de /jarvis/atajo: la puerta por la que entra el Atajo de iOS.

Aquí no se prueba el cerebro —eso ya está en test_jarvis.py y es el mismo— sino lo que
tiene de propio esta puerta: con qué se autentica, que no acepte el token por la query,
que el historial no viaje, y que lo que queda pendiente de confirmar se DIGA, porque al
otro lado hay una voz y no un botón.
"""
import main

# El cliente falso del modelo vive en test_jarvis.py y ya sabe partir la respuesta en
# trozos como hace el streaming de verdad, que es por donde pasa este endpoint (va con
# `voz=True`). Duplicarlo aquí sería garantizar que los dos se separan.
from test_jarvis import _con_modelo, _llamada, _mensaje  # noqa: E402


def _con_token(monkeypatch, valor="jarvis-token"):
    monkeypatch.setattr(main, "JARVIS_TOKEN", valor)
    return {"X-Auth-Token": valor}


# ── Autenticación ─────────────────────────────────────────────────────────────

class TestAtajoAuth:
    def test_sin_credenciales_no_entra(self, client):
        assert client.post("/jarvis/atajo", json={"mensaje": "hola"}).status_code in (401, 403)

    def test_con_token_de_servicio(self, client, monkeypatch):
        cabeceras = _con_token(monkeypatch)
        _con_modelo(monkeypatch, [_mensaje("Buenas.")])
        r = client.post("/jarvis/atajo", json={"mensaje": "hola"}, headers=cabeceras)
        assert r.status_code == 200
        assert r.json()["texto"] == "Buenas."

    def test_con_jwt_de_usuario(self, client, auth_headers, monkeypatch):
        """Se acepta para poder probarlo sin configurar nada; el Atajo usa el otro."""
        _con_modelo(monkeypatch, [_mensaje("Buenas.")])
        r = client.post("/jarvis/atajo", json={"mensaje": "hola"}, headers=auth_headers)
        assert r.status_code == 200

    def test_token_equivocado_no_entra(self, client, monkeypatch):
        _con_token(monkeypatch)
        r = client.post("/jarvis/atajo", json={"mensaje": "hola"},
                        headers={"X-Auth-Token": "otro"})
        assert r.status_code in (401, 403)

    def test_sin_token_configurado_no_pasa_cualquier_cosa(self, client, monkeypatch):
        """La regla de _token_ok: token esperado vacío es siempre falso, nunca 'todo vale'."""
        monkeypatch.setattr(main, "JARVIS_TOKEN", "")
        r = client.post("/jarvis/atajo", json={"mensaje": "hola"},
                        headers={"X-Auth-Token": ""})
        assert r.status_code in (401, 403)

    def test_no_admite_el_token_por_la_query(self, client, monkeypatch):
        """Aquí no hay integración desplegada que migrar, así que no se hereda esa
        excepción: un token en la query acaba en los logs de acceso."""
        valor = _con_token(monkeypatch)["X-Auth-Token"]
        r = client.post(f"/jarvis/atajo?token={valor}", json={"mensaje": "hola"})
        assert r.status_code in (401, 403)


# ── El turno ──────────────────────────────────────────────────────────────────

class TestAtajoTurno:
    def test_va_siempre_por_voz(self, client, monkeypatch):
        """Lo que se escucha no se puede ojear: el prompt tiene que ser el de voz."""
        cabeceras = _con_token(monkeypatch)
        cliente = _con_modelo(monkeypatch, [_mensaje("Mañana tienes dos cosas.")])
        client.post("/jarvis/atajo", json={"mensaje": "qué tengo mañana"}, headers=cabeceras)
        sistema = cliente.recibido[0]["messages"][0]["content"]
        assert "voz" in sistema.lower() or "escucha" in sistema.lower()

    def test_no_manda_historial(self, client, monkeypatch):
        """Un Atajo no tiene dónde guardarlo, y el backend no guarda conversaciones."""
        cabeceras = _con_token(monkeypatch)
        cliente = _con_modelo(monkeypatch, [_mensaje("Buenas.")])
        client.post("/jarvis/atajo", json={"mensaje": "hola"}, headers=cabeceras)
        roles = [m["role"] for m in cliente.recibido[0]["messages"]]
        assert roles.count("user") == 1
        assert "assistant" not in roles

    def test_mensaje_demasiado_largo_da_422(self, client, monkeypatch):
        cabeceras = _con_token(monkeypatch)
        largo = "a" * (main.JARVIS_MAX_MENSAJE + 1)
        r = client.post("/jarvis/atajo", json={"mensaje": largo}, headers=cabeceras)
        assert r.status_code == 422

    def test_mensaje_vacio_da_400(self, client, monkeypatch):
        cabeceras = _con_token(monkeypatch)
        _con_modelo(monkeypatch, [_mensaje("no debería llegar")])
        r = client.post("/jarvis/atajo", json={"mensaje": "   "}, headers=cabeceras)
        assert r.status_code == 400

    def test_una_consulta_se_ejecuta_sola(self, client, monkeypatch):
        cabeceras = _con_token(monkeypatch)
        monkeypatch.setitem(main._JARVIS_HERRAMIENTAS["clima"], "fn",
                            lambda: {"ok": True, "resumen": "sol"})
        _con_modelo(monkeypatch, [
            _mensaje(tool_calls=[_llamada("clima")]),
            _mensaje("Hace sol."),
        ])
        r = client.post("/jarvis/atajo", json={"mensaje": "qué tiempo hace"}, headers=cabeceras)
        datos = r.json()
        assert datos["texto"] == "Hace sol."
        assert datos["herramientas"] == ["clima"]
        assert datos["pendiente"] is False

    def test_lo_pendiente_se_dice_y_no_se_ejecuta(self, client, monkeypatch):
        """La frontera de confirmación no se relaja por venir de un Atajo. Pero callarlo
        dejaría al usuario creyendo que su cita está creada, así que se le dice."""
        cabeceras = _con_token(monkeypatch)

        def _no_llamar(*a, **k):
            raise AssertionError("no debería crearse el evento sin confirmar")

        monkeypatch.setattr(main, "create_event", _no_llamar)
        _con_modelo(monkeypatch, [
            _mensaje(tool_calls=[_llamada("crear_evento",
                                          {"titulo": "Dentista", "fecha": "2026-09-01"})]),
            _mensaje("Te lo apunto."),
        ])
        r = client.post("/jarvis/atajo", json={"mensaje": "apunta dentista el 1"},
                        headers=cabeceras)
        datos = r.json()
        assert datos["pendiente"] is True
        assert "dashboard" in datos["texto"]
        assert datos["herramientas"] == []
