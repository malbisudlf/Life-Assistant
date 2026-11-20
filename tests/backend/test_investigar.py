"""La investigación de noche (2026-11-20): el servicio de caja que la hace
(`chat/jarvis_claude.py`) y el backend que la encarga y la entrega.

Lo que se protege: que la sesión que investiga tenga SOLO búsqueda y lectura web (ni
terminal, ni ficheros, ni MCP), que corra de madrugada salvo que se pida ya, que una que se
cortó vuelva a la cola, que el informe cuente como ajeno, y que llegue por Telegram por la
mañana una sola vez.
"""
import json
from datetime import datetime
from types import SimpleNamespace

import pytest

import main
from conftest import FakeResponse
from test_jarvis_claude import _servicio

IID = "12345678-1234-1234-1234-123456789abc"
INFORME = "# Portátiles\n**En una frase:** el X1 Carbon por 1.450 €.\n## Recomendación\n…"


class TestElServicio:
    def test_solo_web_y_nada_mas(self, monkeypatch, tmp_path):
        servicio = _servicio(monkeypatch)
        sistema = tmp_path / "s.txt"
        sistema.write_text("investiga")
        args = servicio.comando_investigar(str(sistema), "--tools --system-prompt-file --restricted --effort")
        assert args[args.index("--tools") + 1] == "WebSearch,WebFetch"
        assert args[args.index("--allowedTools") + 1] == "WebSearch,WebFetch"
        assert "--strict-mcp-config" in args and "--mcp-config" not in args
        assert args[args.index("--permission-mode") + 1] == "dontAsk"
        assert args[args.index("--model") + 1] == "claude-opus-5-5"
        assert "--restricted" in args and not any("dangerously" in a or "bypass" in a for a in args)

    def test_de_madrugada_o_ya(self, monkeypatch):
        servicio = _servicio(monkeypatch)
        assert servicio.toca_investigar(3, False) and not servicio.toca_investigar(12, False)
        assert servicio.toca_investigar(12, True)
        monkeypatch.setattr(servicio, "INVESTIGAR_DESDE", 23)
        monkeypatch.setattr(servicio, "INVESTIGAR_HASTA", 6)
        assert servicio.toca_investigar(23, False) and servicio.toca_investigar(2, False)
        assert not servicio.toca_investigar(8, False)

    def test_encargar_listar_y_leer(self, monkeypatch, tmp_path):
        servicio = _servicio(monkeypatch)
        monkeypatch.setattr(servicio, "DIR_INVESTIGAR", str(tmp_path))
        codigo, inv = servicio.investigar_encargar({"tema": "  mejor   portátil 1500 € ", "detalle": "programar"})
        assert codigo == 200 and inv["tema"] == "mejor portátil 1500 €" and inv["estado"] == "pendiente"
        assert servicio.investigar_encargar({"tema": "x"})[0] == 400
        codigo, lista = servicio.investigar_lista({})
        assert [i["id"] for i in lista["investigaciones"]] == [inv["id"]]
        assert servicio.investigar_leer({"id": "../../etc/passwd"})[0] == 404

    def test_una_investigacion_entera(self, monkeypatch, tmp_path):
        servicio = _servicio(monkeypatch)
        monkeypatch.setattr(servicio, "DIR_INVESTIGAR", str(tmp_path / "inv"))
        monkeypatch.setattr(servicio, "DIRECTORIO", str(tmp_path))
        visto = {}

        def _run(args, **kw):
            visto.update(args=args, **kw)
            return SimpleNamespace(returncode=0, stderr="",
                                   stdout=json.dumps({"subtype": "success", "result": INFORME}))
        monkeypatch.setattr(servicio.subprocess, "run", _run)
        _, inv = servicio.investigar_encargar({"tema": "mejor portátil", "detalle": "para programar"})
        servicio._investigar_una(servicio._inv_leer(inv["id"]), "--tools")
        codigo, hecha = servicio.investigar_leer({"id": inv["id"]})
        assert hecha["estado"] == "hecha" and hecha["informe"] == INFORME.strip()
        assert hecha["en_una_frase"] == "el X1 Carbon por 1.450 €."
        assert "mejor portátil" in visto["input"] and "mejor portátil" not in " ".join(visto["args"])

    def test_si_falla_queda_fallida_con_su_motivo(self, monkeypatch, tmp_path):
        servicio = _servicio(monkeypatch)
        monkeypatch.setattr(servicio, "DIR_INVESTIGAR", str(tmp_path / "inv"))
        monkeypatch.setattr(servicio, "DIRECTORIO", str(tmp_path))
        monkeypatch.setattr(servicio.subprocess, "run", lambda *a, **k: SimpleNamespace(
            returncode=1, stderr="OAuth caducado", stdout=json.dumps({"is_error": True, "result": "OAuth caducado"})))
        _, inv = servicio.investigar_encargar({"tema": "algo que mirar"})
        servicio._investigar_una(servicio._inv_leer(inv["id"]), "--tools")
        _, leida = servicio.investigar_leer({"id": inv["id"]})
        assert leida["estado"] == "fallida" and "OAuth" in leida["error"]

    def test_las_rutas_piden_la_llave(self, monkeypatch):
        servicio = _servicio(monkeypatch)
        assert set(servicio._INVESTIGAR_RUTAS) == {"/investigar/encargar", "/investigar/lista",
                                                   "/investigar/leer", "/investigar/avisada",
                                                   "/investigar/cancelar"}


@pytest.fixture
def caja(monkeypatch, mock_requests):
    monkeypatch.setattr(main, "JARVIS_CLAUDE_URL", "http://caja.test:3340")
    monkeypatch.setattr(main, "JARVIS_CLAUDE_TOKEN", "claude-token")
    monkeypatch.setattr(main, "TELEGRAM_BOT_TOKEN", "bot")
    monkeypatch.setattr(main, "TELEGRAM_CHAT_ID", "123")
    return mock_requests


class TestElBackend:
    def test_encarga_con_la_llave(self, caja):
        caja.add("POST", "/investigar/encargar", FakeResponse({"id": IID, "tema": "x", "estado": "pendiente"}))
        r = main._j_investigar("mejor portátil por 1.500 €", "para programar")
        assert r["ok"] is True and "madrugada" in r["cuando"]
        _, _, kw = caja.called("POST", "/investigar/encargar")[0]
        assert kw["headers"]["Authorization"] == "Bearer claude-token"
        assert kw["json"] == {"tema": "mejor portátil por 1.500 €", "detalle": "para programar", "ya": False}

    def test_un_servicio_viejo_lo_dice(self, caja):
        caja.add("POST", "/investigar/encargar", FakeResponse({"error": "No existe"}, 404))
        assert "jarvis_claude.py" in main._j_investigar("algo largo")["error"]

    def test_el_informe_es_ajeno(self, caja):
        caja.add("POST", "/investigar/leer", FakeResponse({"id": IID, "tema": "x", "estado": "hecha",
                                                           "informe": INFORME, "terminada": 1763700000}))
        r = main._j_investigaciones(IID)
        assert r["informe"] == INFORME and r["aviso"].startswith(main._AVISO_WEB)
        assert "investigaciones" in main._HERRAMIENTAS_AJENAS
        assert main._j_investigaciones("../x")["ok"] is False

    def test_por_la_manana_llega_una_vez(self, caja, monkeypatch):
        enviados = []
        monkeypatch.setattr(main, "_telegram_api", lambda m, datos=None, ficheros=None:
                            enviados.append((m, datos, ficheros)) or ({"ok": True}, 200))
        caja.add("POST", "/investigar/lista", FakeResponse({"investigaciones": [
            {"id": IID, "tema": "Mejor portátil", "estado": "hecha", "avisada": False,
             "en_una_frase": "el X1 Carbon"},
            {"id": "22222222-1234-1234-1234-123456789abc", "tema": "otra", "estado": "pendiente"}]}))
        caja.add("POST", "/investigar/leer", FakeResponse({"informe": INFORME}))
        caja.add("POST", "/investigar/avisada", FakeResponse({"ok": True}))
        madrugada = datetime(2026, 11, 21, 4, 0, tzinfo=main.LOCAL_TZ)
        assert main._investigar_entregar(madrugada) == 0 and not enviados
        manana = datetime(2026, 11, 21, 8, 30, tzinfo=main.LOCAL_TZ)
        assert main._investigar_entregar(manana) == 1
        (metodo, datos, ficheros), = enviados
        assert metodo == "sendDocument" and "el X1 Carbon" in datos["caption"]
        nombre, contenido, tipo = ficheros["document"]
        assert nombre == "mejor-portatil.md" and contenido == INFORME.encode() and tipo == "text/markdown"
        assert caja.called("POST", "/investigar/avisada")

    def test_sin_servicio_no_se_anuncia(self, monkeypatch):
        monkeypatch.setattr(main, "JARVIS_CLAUDE_URL", "")
        nombres = {h["function"]["name"] for h in main._jarvis_esquema()}
        assert "investigar" not in nombres and "investigaciones" not in nombres
