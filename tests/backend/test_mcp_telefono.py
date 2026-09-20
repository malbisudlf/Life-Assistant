"""El servidor MCP que Jarvis-Claude (la sesión de `caja`) consume por teléfono.

Aquí el backend es SERVIDOR, no cliente: expone una lista blanca cerrada de
`_JARVIS_HERRAMIENTAS` sobre Streamable HTTP / JSON-RPC 2.0. Lo que se comprueba es que
la lista blanca es de verdad cerrada (nada de `desplegar`, `mcp_*`, `crear_evento`...) y
que la confirmación hablada reusa el mismo `_jarvis_confirma` que el chat de GPT: una
herramienta que la exige se rechaza, no se ejecuta porque venga de una llamada.
"""
import pytest

import main

TOKEN = {"Authorization": "Bearer mcp-telefono-token"}


@pytest.fixture(autouse=True)
def _configurado(monkeypatch):
    monkeypatch.setattr(main, "JARVIS_MCP_TELEFONO_TOKEN", "mcp-telefono-token")


def _initialize(client):
    r = client.post("/mcp/telefono",
                    json={"jsonrpc": "2.0", "id": 0, "method": "initialize",
                          "params": {"protocolVersion": "2025-06-18",
                                    "capabilities": {},
                                    "clientInfo": {"name": "test", "version": "1"}}},
                    headers=TOKEN)
    return r


class TestAuth:
    def test_sin_token_da_401(self, client):
        r = client.post("/mcp/telefono",
                        json={"jsonrpc": "2.0", "id": 0, "method": "tools/list"})
        assert r.status_code == 401

    def test_con_token_incorrecto_da_401(self, client):
        r = client.post("/mcp/telefono",
                        json={"jsonrpc": "2.0", "id": 0, "method": "tools/list"},
                        headers={"Authorization": "Bearer malo"})
        assert r.status_code == 401


class TestHandshake:
    def test_initialize_devuelve_session_id_en_cabecera(self, client):
        r = _initialize(client)
        assert r.status_code == 200
        assert r.headers.get("mcp-session-id")
        assert r.json()["result"]["protocolVersion"]

    def test_sesion_desconocida_da_404(self, client):
        r = client.post("/mcp/telefono",
                        json={"jsonrpc": "2.0", "id": 1, "method": "tools/list"},
                        headers={**TOKEN, "Mcp-Session-Id": "no-existe"})
        assert r.status_code == 404


class TestToolsList:
    def test_respeta_la_lista_blanca(self, client):
        sesion = _initialize(client).headers["mcp-session-id"]
        r = client.post("/mcp/telefono",
                        json={"jsonrpc": "2.0", "id": 1, "method": "tools/list"},
                        headers={**TOKEN, "Mcp-Session-Id": sesion})
        nombres = {t["name"] for t in r.json()["result"]["tools"]}
        assert nombres == main._MCP_SERVIDOR_HERRAMIENTAS
        for peligrosa in ("desplegar", "mcp_conectar", "mcp_usar",
                          "encargar_a_una_sesion", "responder_a_la_sesion",
                          "arreglar_revision", "crear_evento", "cobrar_entrenamiento"):
            assert peligrosa not in nombres

    def test_solo_lectura_marca_readonlyhint(self, client):
        sesion = _initialize(client).headers["mcp-session-id"]
        r = client.post("/mcp/telefono",
                        json={"jsonrpc": "2.0", "id": 1, "method": "tools/list"},
                        headers={**TOKEN, "Mcp-Session-Id": sesion})
        por_nombre = {t["name"]: t for t in r.json()["result"]["tools"]}
        assert por_nombre["agenda"]["annotations"]["readOnlyHint"] is True
        assert por_nombre["recordarme"]["annotations"]["readOnlyHint"] is False


class TestToolsCall:
    def _sesion(self, client):
        return _initialize(client).headers["mcp-session-id"]

    def test_ejecuta_una_de_solo_lectura(self, client, monkeypatch):
        # `_JARVIS_HERRAMIENTAS["agenda"]["fn"]` ya guarda la referencia a la función:
        # monkeypatchear `main._j_agenda` suelto no la sustituye ahí.
        monkeypatch.setitem(main._JARVIS_HERRAMIENTAS["agenda"], "fn",
                            lambda dias=1: {"eventos": ["reunión"]})
        sesion = self._sesion(client)
        r = client.post("/mcp/telefono",
                        json={"jsonrpc": "2.0", "id": 1, "method": "tools/call",
                              "params": {"name": "agenda", "arguments": {"dias": 1}}},
                        headers={**TOKEN, "Mcp-Session-Id": sesion})
        cuerpo = r.json()
        assert "error" not in cuerpo
        assert "reunión" in cuerpo["result"]["content"][0]["text"]

    def test_rechaza_una_que_exige_confirmacion(self, client):
        antes = len(main._ha_ordenes)
        sesion = self._sesion(client)
        r = client.post("/mcp/telefono",
                        json={"jsonrpc": "2.0", "id": 1, "method": "tools/call",
                              "params": {"name": "casa_ordenar",
                                        "arguments": {"servicio": "lock.unlock",
                                                     "entidad": "lock.puerta"}}},
                        headers={**TOKEN, "Mcp-Session-Id": sesion})
        cuerpo = r.json()
        assert "error" in cuerpo
        # Una cerradura no se abre sola porque se haya pedido por teléfono: ni siquiera
        # llega a encolarse la orden.
        assert len(main._ha_ordenes) == antes

    def test_ejecuta_sobre_dominio_no_sensible(self, client):
        sesion = self._sesion(client)
        r = client.post("/mcp/telefono",
                        json={"jsonrpc": "2.0", "id": 1, "method": "tools/call",
                              "params": {"name": "casa_ordenar",
                                        "arguments": {"servicio": "light.turn_on",
                                                     "entidad": "light.salon"}}},
                        headers={**TOKEN, "Mcp-Session-Id": sesion})
        cuerpo = r.json()
        assert "error" not in cuerpo
        assert cuerpo["result"]["content"][0]["text"]

    def test_herramienta_fuera_de_la_lista_blanca(self, client, monkeypatch):
        llamado = []
        monkeypatch.setattr(main, "_jarvis_despachar",
                            lambda *a, **k: llamado.append(a) or {})
        sesion = self._sesion(client)
        r = client.post("/mcp/telefono",
                        json={"jsonrpc": "2.0", "id": 1, "method": "tools/call",
                              "params": {"name": "desplegar", "arguments": {}}},
                        headers={**TOKEN, "Mcp-Session-Id": sesion})
        assert "error" in r.json()
        assert not llamado

    def test_metodo_desconocido(self, client):
        sesion = self._sesion(client)
        r = client.post("/mcp/telefono",
                        json={"jsonrpc": "2.0", "id": 1, "method": "algo/raro"},
                        headers={**TOKEN, "Mcp-Session-Id": sesion})
        assert "error" in r.json()


class TestListaBlancaEsCoherente:
    def test_toda_herramienta_expuesta_existe_de_verdad(self):
        assert main._MCP_SERVIDOR_HERRAMIENTAS <= set(main._JARVIS_HERRAMIENTAS)
