"""La voz en directo pensada por Claude y retransmitida (2026-11-21).

`/jarvis/voz` (el modo llamada del navegador y el Jarvis de escritorio) lo piensa Claude con
`JARVIS_VOZ_MOTOR=claude`, soltando cada trozo según lo escribe. Lo que se protege: que los
eventos sean los de siempre (texto, herramienta con su relleno, fin con `por_decir`), que si
Claude no puede ni empezar conteste OpenAI, que un corte a media respuesta se diga, y que la
sesión que lo piensa siga sin terminal (los argumentos los monta `comando`).
"""
import json
from types import SimpleNamespace

import pytest

import main
from test_jarvis import _con_modelo, _mensaje
from test_jarvis_claude import _servicio


class _Flujo:
    """Una respuesta de `requests` con `stream=True`: líneas NDJSON."""

    def __init__(self, eventos, status_code=200):
        self.status_code = status_code
        self._lineas = [json.dumps(e, ensure_ascii=False) for e in eventos]
        self.cerrada = False

    def iter_lines(self, decode_unicode=False):
        yield from self._lineas

    def close(self):
        self.cerrada = True


@pytest.fixture
def voz_claude(monkeypatch, mock_requests):
    monkeypatch.setattr(main, "JARVIS_VOZ_MOTOR", "claude")
    monkeypatch.setattr(main, "JARVIS_CLAUDE_URL", "http://caja.test:3340")
    monkeypatch.setattr(main, "JARVIS_CLAUDE_TOKEN", "claude-token")
    monkeypatch.setattr(main, "JARVIS_MCP_CHAT_TOKEN", "mcp-chat-token")
    monkeypatch.setattr(main, "_quizas_destilar", lambda cliente, turnos: None)
    return mock_requests


def _sse(texto: str) -> list:
    eventos = []
    for bloque in texto.strip().split("\n\n"):
        tipo = bloque.split("\n")[0].removeprefix("event: ")
        eventos.append((tipo, json.loads(bloque.split("\n")[1].removeprefix("data: "))))
    return eventos


class TestElBackend:
    def test_retransmite_con_los_eventos_de_siempre(self, client, auth_headers, voz_claude):
        voz_claude.add("POST", "/turno/flujo", lambda url, **kw: _Flujo([
            {"tipo": "mensaje"}, {"tipo": "delta", "texto": "Déjeme mirar. "},
            {"tipo": "herramienta", "nombre": "mcp__jarvis__agenda"},
            {"tipo": "mensaje"}, {"tipo": "delta", "texto": "Mañana tiene "},
            {"tipo": "delta", "texto": "dentista a las diez."},
            {"tipo": "fin", "respuesta": "Mañana tiene dentista a las diez.", "modelo": "claude-sonnet-5-5"}]))
        r = client.post("/jarvis/voz", headers=auth_headers, json={"mensaje": "¿qué tengo mañana?"})
        eventos = _sse(r.text)
        assert [t for t, _ in eventos] == ["texto", "herramienta", "texto", "texto", "fin"]
        assert eventos[1][1] == {"nombre": "agenda", "decir": main._relleno_herramienta("agenda")}
        fin = eventos[-1][1]
        assert fin["respuesta"] == "Mañana tiene dentista a las diez." and fin["por_decir"] == ""
        assert fin["motor"] == "claude"
        [(_, _, kw)] = voz_claude.called("POST", "/turno/flujo")
        assert kw["stream"] is True and kw["json"]["sistema"] == main._sistema_chat(voz=True)

    def test_si_lo_ultimo_no_se_dijo_entero_queda_por_decir(self, voz_claude):
        voz_claude.add("POST", "/turno/flujo", lambda url, **kw: _Flujo([
            {"tipo": "delta", "texto": "Mañana tiene"},
            {"tipo": "fin", "respuesta": "Mañana tiene dentista."}]))
        eventos = list(main._jarvis_turno_voz(main.JarvisIn(mensaje="hola", voz=True)))
        assert eventos[-1][1]["por_decir"] == "dentista."

    def test_si_claude_no_puede_empezar_contesta_openai(self, client, auth_headers, voz_claude,
                                                        monkeypatch):
        voz_claude.add("POST", "/turno/flujo", lambda url, **kw: _Flujo([], status_code=503))
        _con_modelo(monkeypatch, [_mensaje("Hola desde OpenAI")])
        eventos = _sse(client.post("/jarvis/voz", headers=auth_headers, json={"mensaje": "hola"}).text)
        assert eventos[-1][0] == "fin" and eventos[-1][1]["respuesta"] == "Hola desde OpenAI"

    def test_un_corte_a_media_respuesta_se_dice(self, voz_claude):
        voz_claude.add("POST", "/turno/flujo", lambda url, **kw: _Flujo([
            {"tipo": "delta", "texto": "Mañana tiene "}, {"tipo": "error", "error": "matado"}]))
        eventos = list(main._jarvis_turno_voz(main.JarvisIn(mensaje="hola", voz=True)))
        assert eventos[-1][0] == "error"

    def test_con_openai_de_motor_no_se_llama_a_caja(self, client, auth_headers, voz_claude,
                                                     monkeypatch):
        monkeypatch.setattr(main, "JARVIS_VOZ_MOTOR", "openai")
        _con_modelo(monkeypatch, [_mensaje("Hola")])
        client.post("/jarvis/voz", headers=auth_headers, json={"mensaje": "hola"})
        assert voz_claude.called("POST", "/turno/flujo") == []


class TestElServicio:
    def test_los_argumentos_son_los_del_turno_con_salida_retransmitida(self, monkeypatch, tmp_path):
        servicio = _servicio(monkeypatch)
        sistema = tmp_path / "s.txt"
        sistema.write_text("Eres Jarvis")
        args = servicio.comando_flujo("mcp.json", str(sistema), "--tools --system-prompt-file --restricted")
        assert args[args.index("--output-format") + 1] == "stream-json"
        assert "--include-partial-messages" in args and "--verbose" in args
        assert args[args.index("--tools") + 1] == ""
        assert args[args.index("--allowedTools") + 1] == "mcp__jarvis"

    def test_traduce_la_salida_de_claude(self, monkeypatch):
        servicio = _servicio(monkeypatch)
        lineas = [json.dumps(x) for x in (
            {"type": "system", "subtype": "init"},
            {"type": "stream_event", "event": {"type": "message_start"}},
            {"type": "stream_event", "event": {"type": "content_block_start", "content_block": {"type": "text"}}},
            {"type": "stream_event", "event": {"type": "content_block_delta", "delta": {"type": "text_delta", "text": "Hola"}}},
            {"type": "stream_event", "event": {"type": "content_block_start",
                                               "content_block": {"type": "tool_use", "name": "mcp__jarvis__agenda"}}},
            {"type": "stream_event", "event": {"type": "content_block_delta",
                                               "delta": {"type": "input_json_delta", "partial_json": "{}"}}},
            {"type": "result", "subtype": "success", "result": "Hola, señor."},
            {"type": "result", "subtype": "success", "result": "no llega: ya se cerró"},
        )] + ["no es json"]
        assert list(servicio.eventos_flujo(lineas)) == [
            {"tipo": "mensaje"}, {"tipo": "delta", "texto": "Hola"},
            {"tipo": "herramienta", "nombre": "mcp__jarvis__agenda"},
            {"tipo": "fin", "respuesta": "Hola, señor."}]
        assert list(servicio.eventos_flujo([json.dumps({"type": "result", "is_error": True, "result": "OAuth"})])) \
            == [{"tipo": "error", "error": "OAuth"}]

    def test_un_turno_retransmitido_entero(self, monkeypatch, tmp_path):
        servicio = _servicio(monkeypatch)
        monkeypatch.setattr(servicio, "DIRECTORIO", str(tmp_path))
        salida = [json.dumps({"type": "stream_event", "event": {"type": "content_block_delta",
                                                                "delta": {"type": "text_delta", "text": "Hola"}}}) + "\n",
                  json.dumps({"type": "result", "subtype": "success", "result": "Hola"}) + "\n"]
        visto = {}

        class Proceso:
            def __init__(self, args, **kw):
                visto["args"] = args
                self.stdin = SimpleNamespace(write=lambda t: visto.setdefault("entrada", t), close=lambda: None)
                self.stdout = iter(salida)
                self.stderr = None
                self.returncode = 0

            def wait(self, timeout=None):
                return 0

            def kill(self):
                pass
        monkeypatch.setattr(servicio.subprocess, "Popen", Proceso)
        escritos = []
        codigo, error = servicio.turno_flujo({"turno": "12345678-1234-1234-1234-123456789abc",
                                              "prompt": "hola", "sistema": "Eres Jarvis"},
                                             "--tools --system-prompt-file", escritos.append)
        assert (codigo, error) == (200, None)
        assert escritos == [{"tipo": "delta", "texto": "Hola"},
                            {"tipo": "fin", "respuesta": "Hola", "modelo": "claude-sonnet-5-5"}]
        assert visto["entrada"] == "hola" and "hola" not in visto["args"]
        assert servicio.turno_flujo({"turno": "x", "prompt": "hola"}, "", escritos.append)[0] == 400
