"""El chat escrito pensado por Claude Code: `/mcp/chat`, el enrutado de `/jarvis` y el
servicio de `caja` que lanza `claude -p` (`chat/jarvis_claude.py`).

Lo que se comprueba es lo que no puede romperse al cambiar de cerebro: que la sesión no
tenga terminal ni más MCP que el de Jarvis, que lo que necesita confirmación siga
quedando PROPUESTO para el botón del dashboard, y que si Claude no contesta el chat siga
contestando (con OpenAI) y lo diga.
"""
import importlib.util
import json
import pathlib
import subprocess
from types import SimpleNamespace

import pytest
import requests

import main
from conftest import FakeResponse
from test_jarvis import _con_modelo, _herramienta, _llamada, _mensaje

TOKEN_MCP = {"Authorization": "Bearer mcp-chat-token"}
TURNO = "12345678-1234-1234-1234-123456789abc"


@pytest.fixture(autouse=True)
def _configurado(monkeypatch):
    monkeypatch.setattr(main, "JARVIS_MCP_CHAT_TOKEN", "mcp-chat-token")
    monkeypatch.setattr(main, "JARVIS_CLAUDE_URL", "http://caja.test:3340")
    monkeypatch.setattr(main, "JARVIS_CLAUDE_TOKEN", "claude-token")
    main._chat_turnos.clear()


def _rpc(client, metodo, params=None, turno=TURNO, sesion=None):
    cabeceras = dict(TOKEN_MCP)
    if sesion:
        cabeceras["Mcp-Session-Id"] = sesion
    return client.post(f"/mcp/chat?turno={turno}", headers=cabeceras,
                       json={"jsonrpc": "2.0", "id": 1, "method": metodo, "params": params or {}})


def _sesion(client):
    return _rpc(client, "initialize").headers["mcp-session-id"]


class TestMcpChat:
    def test_sin_token_no_pasa(self, client):
        r = client.post("/mcp/chat", json={"jsonrpc": "2.0", "id": 1, "method": "initialize"})
        assert r.status_code == 401

    def test_el_token_del_telefono_no_vale_aqui(self, client, monkeypatch):
        monkeypatch.setattr(main, "JARVIS_MCP_TELEFONO_TOKEN", "mcp-telefono-token")
        r = client.post("/mcp/chat", headers={"Authorization": "Bearer mcp-telefono-token"},
                        json={"jsonrpc": "2.0", "id": 1, "method": "initialize"})
        assert r.status_code == 401

    def test_sin_token_configurado_no_entra_nadie(self, client, monkeypatch):
        monkeypatch.setattr(main, "JARVIS_MCP_CHAT_TOKEN", "")
        assert _rpc(client, "initialize").status_code == 401

    def test_ve_las_mismas_herramientas_que_el_chat(self, client):
        """No la lista cerrada del teléfono: el chat tiene botón de confirmar, así que ve
        también lo que lo necesita (crear un evento, desplegar...)."""
        sesion = _sesion(client)
        nombres = {t["name"] for t in _rpc(client, "tools/list", sesion=sesion).json()["result"]["tools"]}
        assert nombres == {h["function"]["name"] for h in main._jarvis_esquema()}
        assert "crear_evento" in nombres

    def test_lo_que_se_confirma_queda_propuesto_y_no_se_ejecuta(self, client, monkeypatch):
        ejecutado = []
        _herramienta(monkeypatch, "crear_evento", lambda **kw: ejecutado.append(kw))
        main._chat_turnos[TURNO] = {"ts": main.time.time(), "usadas": [], "pendiente": None}
        sesion = _sesion(client)
        cena = {"titulo": "Cena", "fecha": "2026-10-30"}
        r = _rpc(client, "tools/call", {"name": "crear_evento", "arguments": cena},
                 sesion=sesion)
        texto = json.loads(r.json()["result"]["content"][0]["text"])
        assert texto["estado"] == "pendiente_de_confirmacion"
        assert ejecutado == []
        assert main._chat_turnos[TURNO]["pendiente"] == {"herramienta": "crear_evento",
                                                         "argumentos": cena}

    def test_lo_que_se_rechazaria_al_pulsar_no_llega_a_proponerse(self, client, monkeypatch):
        """Diez pádel hasta Navidad por `reservar_bloques`, que solo llega a 14 días: el
        «no» tiene que llegarle al modelo en el turno, no a ti después de pulsar."""
        monkeypatch.setattr(main, "_ahora_local",
                            lambda: main.datetime(2026, 10, 22, 12, 0, tzinfo=main.LOCAL_TZ))
        main._chat_turnos[TURNO] = {"ts": main.time.time(), "usadas": [], "pendiente": None}
        sesion = _sesion(client)
        bloques = [{"titulo": "Pádel", "fecha": "2026-12-04", "hora_inicio": "10:00",
                    "hora_fin": "12:00"}]
        r = _rpc(client, "tools/call",
                 {"name": "reservar_bloques", "arguments": {"bloques": bloques}}, sesion=sesion)
        resultado = r.json()["result"]
        assert resultado["isError"] is True
        assert "14 días" in resultado["content"][0]["text"]
        assert "repetir_hasta" in resultado["content"][0]["text"]
        assert main._chat_turnos[TURNO]["pendiente"] is None

    def test_sin_turno_conocido_no_se_puede_proponer(self, client, monkeypatch):
        """Sin turno no hay respuesta a la que colgar el botón: se dice, no se ejecuta."""
        ejecutado = []
        _herramienta(monkeypatch, "crear_evento", lambda **kw: ejecutado.append(kw))
        sesion = _sesion(client)
        r = _rpc(client, "tools/call", {"name": "crear_evento", "arguments": {}},
                 sesion=sesion, turno="no-es-un-uuid")
        assert "error" in r.json()
        assert ejecutado == []

    def test_lo_directo_se_ejecuta_y_se_apunta_en_el_turno(self, client, monkeypatch):
        _herramienta(monkeypatch, "clima", lambda: {"temperatura": 18})
        main._chat_turnos[TURNO] = {"ts": main.time.time(), "usadas": [], "pendiente": None}
        sesion = _sesion(client)
        r = _rpc(client, "tools/call", {"name": "clima", "arguments": {}}, sesion=sesion)
        assert json.loads(r.json()["result"]["content"][0]["text"]) == {"temperatura": 18}
        assert main._chat_turnos[TURNO]["usadas"] == ["clima"]

    def test_lo_que_el_chat_no_anuncia_tampoco_se_puede_llamar(self, client, monkeypatch):
        monkeypatch.setattr(main, "TAREAS_TODO", False)
        sesion = _sesion(client)
        r = _rpc(client, "tools/call", {"name": "tareas", "arguments": {}}, sesion=sesion)
        assert r.json()["error"]["code"] == -32601


class TestElChat:
    @pytest.fixture
    def con_claude(self, monkeypatch):
        monkeypatch.setattr(main, "JARVIS_MOTOR_CHAT", "claude")
        monkeypatch.setattr(main, "_quizas_destilar", lambda cliente, turnos: None)
        monkeypatch.setattr(main, "get_openai_client", lambda: None)

    def test_contesta_claude_con_lo_que_paso_en_el_turno(self, client, auth_headers,
                                                          mock_requests, con_claude):
        """Lo que la sesión hizo dentro de `/mcp/chat` vuelve en la respuesta: las
        herramientas debajo del mensaje y lo pendiente como el botón de siempre."""
        def _turno(url, **kw):
            turno = kw["json"]["turno"]
            main._chat_turnos[turno]["usadas"].append("agenda")
            main._chat_turnos[turno]["pendiente"] = {"herramienta": "crear_evento",
                                                     "argumentos": {"titulo": "Cena"}}
            return FakeResponse({"respuesta": "¿Te la apunto el viernes?"})
        mock_requests.add("POST", "caja.test:3340/turno", _turno)

        r = client.post("/jarvis", headers=auth_headers, json={
            "mensaje": "apúntame cena el viernes",
            "historial": [{"rol": "user", "texto": "hola"}, {"rol": "assistant", "texto": "dime"}]})

        assert r.json() == {"respuesta": "¿Te la apunto el viernes?", "herramientas": ["agenda"],
                            "pendiente": {"herramienta": "crear_evento", "argumentos": {"titulo": "Cena"}},
                            "motor": "claude", "modelo": ""}
        [(_, _, kw)] = mock_requests.called("POST", "/turno")
        # Sin pedir potencia, el servicio usa el suyo de siempre.
        assert kw["json"]["modelo"] == ""
        assert kw["headers"] == {"Authorization": "Bearer claude-token"}
        # La conversación viaja entera: cada turno es una sesión nueva.
        assert "Usuario: hola" in kw["json"]["prompt"] and "Jarvis: dime" in kw["json"]["prompt"]
        assert kw["json"]["prompt"].endswith("apúntame cena el viernes")
        assert "mcp__jarvis__" in kw["json"]["sistema"]
        # El turno no se queda colgado en memoria.
        assert main._chat_turnos == {}

    def test_la_potencia_maxima_pide_el_modelo_potente(self, client, auth_headers,
                                                       mock_requests, con_claude):
        """La vista de Jarvis lo pide con `potente`; el modelo de la respuesta es el que
        dice el servicio, no el pedido: uno sin actualizar lo ignora."""
        mock_requests.add("POST", "caja.test:3340/turno",
                          FakeResponse({"respuesta": "A sus órdenes", "modelo": "claude-opus-5-5"}))
        r = client.post("/jarvis", headers=auth_headers, json={"mensaje": "hola", "potente": True})
        [(_, _, kw)] = mock_requests.called("POST", "/turno")
        assert kw["json"]["modelo"] == main.JARVIS_CLAUDE_MODELO_POTENTE == "claude-opus-5-5"
        assert r.json()["modelo"] == "claude-opus-5-5"

    def test_un_servicio_viejo_no_dice_modelo(self, client, auth_headers, mock_requests,
                                              con_claude):
        mock_requests.add("POST", "caja.test:3340/turno", FakeResponse({"respuesta": "Hola"}))
        r = client.post("/jarvis", headers=auth_headers, json={"mensaje": "hola", "potente": True})
        assert r.json()["modelo"] == ""

    def test_si_claude_no_contesta_contesta_openai_y_lo_dice(self, client, auth_headers,
                                                             mock_requests, monkeypatch):
        monkeypatch.setattr(main, "JARVIS_MOTOR_CHAT", "claude")

        def _caido(url, **kw):
            raise requests.ConnectionError("caja apagada")
        mock_requests.add("POST", "caja.test:3340/turno", _caido)
        _con_modelo(monkeypatch, [_mensaje("Hola desde OpenAI")])

        r = client.post("/jarvis", headers=auth_headers, json={"mensaje": "hola"})
        assert r.status_code == 200
        assert r.json()["respuesta"] == "Hola desde OpenAI"
        assert r.json()["motor"] == "openai"
        assert "Claude no ha contestado" in r.json()["motor_aviso"]

    def test_una_respuesta_vacia_tambien_es_no_contestar(self, client, auth_headers,
                                                         mock_requests, monkeypatch):
        monkeypatch.setattr(main, "JARVIS_MOTOR_CHAT", "claude")
        mock_requests.add("POST", "caja.test:3340/turno", FakeResponse({"error": "sesión caducada"}, 502))
        _con_modelo(monkeypatch, [_mensaje("respaldo")])
        r = client.post("/jarvis", headers=auth_headers, json={"mensaje": "hola"})
        assert r.json()["respuesta"] == "respaldo" and r.json()["motor_aviso"]

    def test_por_defecto_sigue_openai_y_no_llama_a_caja(self, client, auth_headers,
                                                        mock_requests, monkeypatch):
        _con_modelo(monkeypatch, [_mensaje("Hola")])
        r = client.post("/jarvis", headers=auth_headers, json={"mensaje": "hola"})
        assert "motor" not in r.json() and "motor_aviso" not in r.json()
        assert mock_requests.called("POST", "/turno") == []

    def test_el_modo_llamada_sigue_con_openai(self, client, auth_headers, mock_requests,
                                              monkeypatch):
        """Arrancar Claude Code cuesta segundos, y hablando se notan."""
        monkeypatch.setattr(main, "JARVIS_MOTOR_CHAT", "claude")
        _con_modelo(monkeypatch, [_mensaje("Hola")])
        client.post("/jarvis", headers=auth_headers, json={"mensaje": "hola", "voz": True})
        assert mock_requests.called("POST", "/turno") == []

    def test_la_memoria_se_sigue_destilando(self, client, auth_headers, mock_requests,
                                            monkeypatch):
        monkeypatch.setattr(main, "JARVIS_MOTOR_CHAT", "claude")
        destilado = []
        monkeypatch.setattr(main, "get_openai_client", lambda: "cliente")
        monkeypatch.setattr(main, "_quizas_destilar", lambda c, turnos: destilado.append(turnos))
        mock_requests.add("POST", "caja.test:3340/turno", FakeResponse({"respuesta": "vale"}))
        client.post("/jarvis", headers=auth_headers, json={"mensaje": "mi objetivo es 75 kg"})
        assert destilado[0][-2:] == [{"rol": "user", "texto": "mi objetivo es 75 kg"},
                                     {"rol": "assistant", "texto": "vale"}]


# ── El servicio de `caja` ─────────────────────────────────────────────────────

def _servicio(monkeypatch):
    ruta = pathlib.Path(__file__).resolve().parents[2] / "chat" / "jarvis_claude.py"
    spec = importlib.util.spec_from_file_location("jarvis_claude", ruta)
    modulo = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(modulo)
    monkeypatch.setattr(modulo, "MCP_URL", "http://127.0.0.1:8000/mcp/chat")
    monkeypatch.setattr(modulo, "MCP_TOKEN", "mcp-chat-token")
    return modulo


class TestElServicio:
    def test_sin_terminal_y_solo_el_mcp_de_jarvis(self, monkeypatch, tmp_path):
        servicio = _servicio(monkeypatch)
        sistema = tmp_path / "s.txt"
        sistema.write_text("Eres Jarvis")
        args = servicio.comando("mcp.json", str(sistema), "--tools --system-prompt-file --restricted")
        assert args[args.index("--tools") + 1] == ""
        assert "--strict-mcp-config" in args and args[args.index("--mcp-config") + 1] == "mcp.json"
        assert args[args.index("--allowedTools") + 1] == "mcp__jarvis"
        assert args[args.index("--permission-mode") + 1] == "dontAsk"
        assert args[args.index("--model") + 1] == "claude-sonnet-5-5"
        assert "--restricted" in args
        assert not any("dangerously" in a or "bypass" in a for a in args)

    def test_una_version_sin_restricted_ni_fichero_de_sistema(self, monkeypatch, tmp_path):
        servicio = _servicio(monkeypatch)
        sistema = tmp_path / "s.txt"
        sistema.write_text("Eres Jarvis")
        args = servicio.comando("mcp.json", str(sistema), "--tools")
        assert "--restricted" not in args
        assert args[args.index("--system-prompt") + 1] == "Eres Jarvis"

    def test_el_modelo_potente_y_nada_mas(self, monkeypatch, tmp_path):
        """Solo se acepta el potente; cualquier otro pedido sale con el de siempre."""
        servicio = _servicio(monkeypatch)
        assert servicio.elegir_modelo("claude-opus-5-5") == "claude-opus-5-5"
        assert servicio.elegir_modelo("") == servicio.elegir_modelo(None) == "claude-sonnet-5-5"
        assert servicio.elegir_modelo("cualquier-otro") == "claude-sonnet-5-5"
        sistema = tmp_path / "s.txt"
        sistema.write_text("Eres Jarvis")
        args = servicio.comando("mcp.json", str(sistema), "--tools", "claude-opus-5-5")
        assert args[args.index("--model") + 1] == "claude-opus-5-5"

    def test_el_turno_va_en_la_url_del_mcp(self, monkeypatch):
        servicio = _servicio(monkeypatch)
        jarvis = servicio.config_mcp(TURNO)["mcpServers"]["jarvis"]
        assert jarvis["url"] == f"http://127.0.0.1:8000/mcp/chat?turno={TURNO}"
        assert jarvis["headers"] == {"Authorization": "Bearer mcp-chat-token"}

    def test_lee_la_salida_de_claude(self, monkeypatch):
        servicio = _servicio(monkeypatch)
        assert servicio.leer_salida(json.dumps({"subtype": "success", "result": " Hola ",
                                                "num_turns": 3})) == {"respuesta": "Hola", "turnos": 3}
        assert "error" in servicio.leer_salida(json.dumps({"is_error": True, "result": "OAuth caducado"}))
        assert "error" in servicio.leer_salida("no es json")

    def test_un_turno_entero(self, monkeypatch, tmp_path):
        servicio = _servicio(monkeypatch)
        monkeypatch.setattr(servicio, "DIRECTORIO", str(tmp_path))
        visto = {}

        def _run(args, **kw):
            visto.update(args=args, **kw)
            visto["mcp"] = json.loads(pathlib.Path(args[args.index("--mcp-config") + 1]).read_text())
            return SimpleNamespace(returncode=0, stderr="",
                                   stdout=json.dumps({"subtype": "success", "result": "Hola"}))
        monkeypatch.setattr(servicio.subprocess, "run", _run)

        codigo, datos = servicio.turno({"turno": TURNO, "prompt": "hola", "sistema": "Eres Jarvis"},
                                       "--tools --system-prompt-file")
        assert (codigo, datos["respuesta"]) == (200, "Hola")
        assert datos["modelo"] == "claude-sonnet-5-5"
        # El mensaje entra por la entrada estándar, no como argumento.
        assert visto["input"] == "hola" and "hola" not in visto["args"]
        assert visto["cwd"] == str(tmp_path)
        assert TURNO in visto["mcp"]["mcpServers"]["jarvis"]["url"]
        # Sin esto las herramientas del MCP quedan tras un buscador que `--tools ""` quita.
        assert visto["env"]["ENABLE_TOOL_SEARCH"] == "false"
        # Y sin tráfico no esencial: ~0,6 s menos de arranque en cada turno.
        assert visto["env"]["CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC"] == "1"

    def test_mal_formado_o_colgado(self, monkeypatch, tmp_path):
        servicio = _servicio(monkeypatch)
        monkeypatch.setattr(servicio, "DIRECTORIO", str(tmp_path))
        assert servicio.turno({"turno": "x", "prompt": "hola"}, "")[0] == 400

        def _colgado(args, **kw):
            raise subprocess.TimeoutExpired(args, 1)
        monkeypatch.setattr(servicio.subprocess, "run", _colgado)
        assert servicio.turno({"turno": TURNO, "prompt": "hola", "sistema": ""}, "")[0] == 504
