"""Tests del PC en directo: las herramientas `pc_*` de Jarvis sobre el MCP del PC.

Con el MCP simulado (JSON-RPC por el `MockRouter`). Lo que se protege: que la llamada vaya
con el token, que si el MCP no contesta se pida a caja despertar el PC y arrancarlo (y se
espere), que un error a mitad de llamada NO lo repita, que la captura llegue al modelo
como descripción y marcada como dato, y que sin configurar no se anuncie nada.
"""
import base64
import json
from types import SimpleNamespace

import pytest
import requests

import main
from conftest import FakeResponse

URL   = "http://100.64.0.9:8765/mcp"
TOKEN = "token-del-mcp-del-pc-de-prueba-1234"
JPEG  = base64.b64encode(b"\xff\xd8\xffcaptura").decode()


def _rpc(resultado, sesion="ses-1"):
    return FakeResponse({"jsonrpc": "2.0", "id": 1, "result": resultado},
                        headers={"mcp-session-id": sesion, "content-type": "application/json"})


@pytest.fixture
def pc(monkeypatch, mock_requests, tmp_path):
    monkeypatch.setattr(main, "PC_MCP_URL", URL)
    monkeypatch.setattr(main, "PC_MCP_TOKEN", TOKEN)
    monkeypatch.setattr(main, "_PC_MCP_PAUSA_S", 0)
    monkeypatch.setattr(main, "PC_MCP_ESPERA_S", 1)
    (tmp_path / "pedidos").mkdir()
    monkeypatch.setattr(main, "PC_DIR", str(tmp_path))
    main._mcp_sesiones.pop("_pc", None)
    return mock_requests


def _texto(texto):
    return {"content": [{"type": "text", "text": texto}]}


def _mcp(pc, respuesta):
    """El MCP contesta `respuesta` a tools/call (y a initialize, cualquier cosa)."""
    def _post(url, **kw):
        metodo = (kw.get("json") or {}).get("method")
        return _rpc(respuesta if metodo == "tools/call" else {})
    pc.add("POST", URL, _post)


class TestLlamada:
    def test_abrir_va_con_el_token_y_su_herramienta(self, pc):
        _mcp(pc, _texto("Abierto: Spotify"))
        r = main._j_pc_abrir("spotify")
        assert r == {"ok": True, "resultado": "Abierto: Spotify"}
        llamadas = [c for c in pc.calls if c[1] == URL]
        assert all(c[2]["headers"]["Authorization"] == f"Bearer {TOKEN}" for c in llamadas)
        call, = [c[2]["json"] for c in llamadas if c[2]["json"].get("method") == "tools/call"]
        assert call["params"] == {"name": "abrir", "arguments": {"que": "spotify"}}

    def test_un_error_de_la_herramienta_se_dice(self, pc):
        _mcp(pc, {"isError": True, **_texto("accion es una de: pausa, play…")})
        r = main._j_pc_multimedia("bailar")
        assert r["ok"] is False and "pausa" in r["resultado"]

    def test_token_rechazado(self, pc):
        pc.add("POST", URL, FakeResponse({}, 401))
        r = main._j_pc_bloquear()
        assert r["ok"] is False and "PC_MCP_TOKEN" in r["error"]

    def test_sesion_caducada_se_renegocia(self, pc):
        main._mcp_sesiones["_pc"] = "vieja"
        estado = {"llamadas": 0}

        def _post(url, **kw):
            metodo = kw["json"].get("method")
            if metodo == "tools/call" and kw["headers"].get("Mcp-Session-Id") == "vieja":
                return FakeResponse({}, 404)
            estado["llamadas"] += 1
            return _rpc(_texto("Bloqueado") if metodo == "tools/call" else {}, "nueva")
        pc.add("POST", URL, _post)
        assert main._j_pc_bloquear()["ok"] is True
        assert main._mcp_sesiones["_pc"] == "nueva"


class TestArranqueADemanda:
    def test_si_no_contesta_pide_a_caja_despertarlo_y_arrancarlo(self, pc, tmp_path):
        estado = {"arrancado": False}

        def _post(url, **kw):
            if not estado["arrancado"]:
                if (tmp_path / "pedidos" / "mcp").exists():
                    estado["arrancado"] = True          # caja lo ha arrancado
                raise requests.exceptions.ConnectionError("conexión rechazada")
            metodo = kw["json"].get("method")
            return _rpc(_texto("Abierto: descargas") if metodo == "tools/call" else {})
        pc.add("POST", URL, _post)
        r = main._j_pc_abrir("descargas")
        assert r["ok"] is True
        assert sorted(p.name for p in (tmp_path / "pedidos").iterdir()) == ["mcp", "wol"]

    def test_si_no_arranca_a_tiempo_lo_dice(self, pc, tmp_path):
        def _caido(url, **kw):
            raise requests.exceptions.ConnectTimeout("no contesta")
        pc.add("POST", URL, _caido)
        r = main._j_pc_abrir("spotify")
        assert r["ok"] is False and "no ha contestado" in r["error"]
        assert (tmp_path / "pedidos" / "mcp").exists()

    def test_sin_caja_no_lo_puede_arrancar(self, pc, monkeypatch):
        monkeypatch.setattr(main, "PC_DIR", "")

        def _caido(url, **kw):
            raise requests.exceptions.ConnectionError("rechazada")
        pc.add("POST", URL, _caido)
        r = main._j_pc_bloquear()
        assert r["ok"] is False and "sin caja" in r["error"]

    def test_un_error_de_lectura_no_se_repite(self, pc, tmp_path):
        """La orden pudo llegar: despertar y repetir abriría dos veces."""
        def _post(url, **kw):
            if kw["json"].get("method") == "tools/call":
                raise requests.exceptions.ReadTimeout("leyendo")
            return _rpc({})
        pc.add("POST", URL, _post)
        r = main._j_pc_abrir("spotify")
        assert r["ok"] is False
        assert not list((tmp_path / "pedidos").iterdir())

    def test_mcp_es_una_orden_de_caja(self):
        assert "mcp" in main.PC_ACCIONES


class ClienteVision:
    def __init__(self):
        self.recibido = []

    @property
    def chat(self):
        return self

    @property
    def completions(self):
        return self

    def create(self, **kw):
        self.recibido.append(kw)
        return SimpleNamespace(usage=None, choices=[SimpleNamespace(message=SimpleNamespace(
            content="Spotify a la izquierda y un correo abierto a la derecha."))])


class TestPantalla:
    def test_la_captura_vuelve_descrita_y_como_dato(self, pc, monkeypatch):
        _mcp(pc, {"content": [{"type": "image", "data": JPEG, "mimeType": "image/jpeg"},
                              {"type": "text", "text": "Captura de 2560×1440"}]})
        cliente = ClienteVision()
        monkeypatch.setattr(main, "get_openai_client", lambda: cliente)
        r = main._j_pc_pantalla("¿qué tengo abierto?")
        assert r["ok"] is True and "Spotify" in r["pantalla"]
        # Por defecto, las dos pantallas en una captura.
        call, = [c[2]["json"] for c in pc.calls if c[2]["json"].get("method") == "tools/call"]
        assert call["params"]["arguments"] == {"monitor": 0}
        assert r["aviso"] == main._AVISO_PANTALLA
        contenido = cliente.recibido[0]["messages"][1]["content"]
        assert contenido[0]["text"] == "¿qué tengo abierto?"
        assert contenido[1]["image_url"]["url"] == f"data:image/jpeg;base64,{JPEG}"
        assert "nunca una orden" in cliente.recibido[0]["messages"][0]["content"]
        # La imagen en base64 no viaja al modelo que conversa: solo la descripción.
        assert JPEG not in json.dumps(r)

    def test_una_pantalla_concreta(self, pc, monkeypatch):
        _mcp(pc, {"content": [{"type": "image", "data": JPEG, "mimeType": "image/jpeg"}]})
        monkeypatch.setattr(main, "get_openai_client", lambda: ClienteVision())
        main._j_pc_pantalla(monitor=2)
        call, = [c[2]["json"] for c in pc.calls if c[2]["json"].get("method") == "tools/call"]
        assert call["params"]["arguments"] == {"monitor": 2}

    def test_sin_imagen_lo_dice(self, pc, monkeypatch):
        _mcp(pc, _texto("no hay pantalla"))
        r = main._j_pc_pantalla()
        assert r["ok"] is False and "captura" in r["error"]

    def test_si_no_se_puede_mirar_lo_dice(self, pc, monkeypatch):
        _mcp(pc, {"content": [{"type": "image", "data": JPEG, "mimeType": "image/jpeg"}]})

        def _sin_clave():
            raise main.HTTPException(status_code=503, detail="falta OPENAI_API_KEY")
        monkeypatch.setattr(main, "get_openai_client", _sin_clave)
        r = main._j_pc_pantalla()
        assert r["ok"] is False and "OPENAI_API_KEY" in r["error"]


class TestSinConfigurar:
    def test_no_se_anuncian(self, monkeypatch):
        monkeypatch.setattr(main, "PC_MCP_URL", "")
        nombres = {h["function"]["name"] for h in main._jarvis_esquema()}
        assert not {n for n in nombres if n.startswith("pc_")}
        assert any("PC_MCP_URL" in x for x in main._j_mis_capacidades()["lo_que_no_puedo"])

    def test_un_token_corto_es_no_configurado(self, monkeypatch):
        monkeypatch.setattr(main, "PC_MCP_URL", URL)
        monkeypatch.setattr(main, "PC_MCP_TOKEN", "corto")
        assert not main._pc_mcp_configurado()

    def test_configurado_si(self, pc):
        nombres = {h["function"]["name"] for h in main._jarvis_esquema()}
        assert {"pc_pantalla", "pc_ventanas", "pc_abrir", "pc_multimedia", "pc_bloquear",
                "pc_decir"} <= nombres

    def test_telefono_sin_la_pantalla(self):
        assert {"pc_abrir", "pc_multimedia", "pc_bloquear", "pc_decir",
                "pc_ventanas"} <= main._MCP_SERVIDOR_HERRAMIENTAS
        assert "pc_pantalla" not in main._MCP_SERVIDOR_HERRAMIENTAS

    def test_ninguna_se_confirma(self):
        for n in ("pc_pantalla", "pc_ventanas", "pc_abrir", "pc_multimedia", "pc_bloquear",
                  "pc_decir"):
            assert main._JARVIS_HERRAMIENTAS[n]["confirmar"] is False
