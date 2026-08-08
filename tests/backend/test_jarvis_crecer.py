"""Tests de lo que hace que Jarvis crezca: el reparto entre dos modelos, el modo voz,
la conciencia de sus propias capacidades y el alta de servidores MCP en caliente.

Van aparte de test_jarvis.py, que cubre el bucle de herramientas y la frontera de
confirmación; aquí se comprueba lo que rodea a ese bucle. Las utilidades del modelo
simulado se reutilizan de allí para no tener dos imitaciones del SDK de OpenAI.
"""
import json

import pytest

import main
from conftest import FakeResponse
from test_jarvis import (
    _con_mcp, _con_modelo, _herramienta, _llamada, _mensaje, _RespuestaMcp,
)


# ── El reparto entre los dos modelos ──────────────────────────────────────────

class TestJarvisModelos:
    """Mini para hablar, grande para actuar.

    El pequeño acierta bien decidiendo SI hace falta una herramienta, y falla eligiendo
    CUÁL en cuanto hay muchas parecidas. Así que su elección se descarta y esa misma
    vuelta se relanza con el grande.
    """

    @pytest.fixture(autouse=True)
    def _con_reparto(self, monkeypatch):
        monkeypatch.setattr(main, "JARVIS_MODEL", "modelo-pequeno")
        monkeypatch.setattr(main, "JARVIS_MODEL_ACCION", "modelo-grande")

    def test_una_charla_no_paga_el_modelo_grande(self, client, auth_headers, monkeypatch, mock_requests):
        cliente = _con_modelo(monkeypatch, [_mensaje("Buenas.")])
        client.post("/jarvis", json={"mensaje": "hola"}, headers=auth_headers)
        assert [c["model"] for c in cliente.recibido] == ["modelo-pequeno"]

    def test_lo_que_pide_el_pequeno_se_descarta_y_elige_el_grande(
            self, client, auth_headers, monkeypatch, mock_requests):
        llamadas = []
        _herramienta(monkeypatch, "clima",  lambda: llamadas.append("clima") or {"ahora": 21})
        _herramienta(monkeypatch, "agenda", lambda dias=1: llamadas.append("agenda") or {"eventos": []})
        cliente = _con_modelo(monkeypatch, [
            _mensaje(tool_calls=[_llamada("agenda")]),   # el pequeño se equivoca
            _mensaje(tool_calls=[_llamada("clima")]),    # el grande elige la buena
            _mensaje("Hace 21 grados."),
        ])
        datos = client.post("/jarvis", json={"mensaje": "que tiempo hace"},
                            headers=auth_headers).json()
        # La que pidió el pequeño no llegó a ejecutarse: solo sirvió para saber que hacía
        # falta una herramienta.
        assert llamadas == ["clima"]
        assert datos["herramientas"] == ["clima"]
        assert [c["model"] for c in cliente.recibido] == [
            "modelo-pequeno", "modelo-grande", "modelo-grande"]

    def test_el_cierre_lo_redacta_el_pequeno(self, client, auth_headers, monkeypatch, mock_requests):
        """Con los datos ya en el contexto, redactar no necesita al caro."""
        cliente = _con_modelo(monkeypatch, [
            _mensaje(tool_calls=[_llamada("crear_evento", {"titulo": "Cita", "fecha": "2026-09-01"})]),
            _mensaje(tool_calls=[_llamada("crear_evento", {"titulo": "Cita", "fecha": "2026-09-01"})]),
            _mensaje("Cuando lo confirmes, lo creo."),
        ])
        datos = client.post("/jarvis", json={"mensaje": "apuntame una cita"},
                            headers=auth_headers).json()
        assert datos["pendiente"]["herramienta"] == "crear_evento"
        assert [c["model"] for c in cliente.recibido] == [
            "modelo-pequeno", "modelo-grande", "modelo-pequeno"]

    def test_con_los_dos_modelos_iguales_no_hay_relanzamiento(
            self, client, auth_headers, monkeypatch, mock_requests):
        """La palanca para volver al comportamiento de antes sin tocar código."""
        monkeypatch.setattr(main, "JARVIS_MODEL_ACCION", "modelo-pequeno")
        _herramienta(monkeypatch, "clima", lambda: {"ahora": 21})
        cliente = _con_modelo(monkeypatch, [
            _mensaje(tool_calls=[_llamada("clima")]),
            _mensaje("Hace 21 grados."),
        ])
        datos = client.post("/jarvis", json={"mensaje": "tiempo"}, headers=auth_headers).json()
        assert datos["herramientas"] == ["clima"]
        assert len(cliente.recibido) == 2


# ── Modo voz ──────────────────────────────────────────────────────────────────

class TestJarvisVoz:
    def test_por_voz_cambian_el_prompt_y_el_techo(self, client, auth_headers, monkeypatch, mock_requests):
        cliente = _con_modelo(monkeypatch, [_mensaje("Hace 21 grados.")])
        client.post("/jarvis", json={"mensaje": "tiempo", "voz": True}, headers=auth_headers)
        sistema = cliente.recibido[0]["messages"][0]["content"]
        assert "CONVERSACIÓN HABLADA" in sistema
        assert cliente.recibido[0]["max_tokens"] == main.JARVIS_MAX_TOKENS_VOZ

    def test_por_escrito_no_viajan_esas_reglas(self, client, auth_headers, monkeypatch, mock_requests):
        """Se pagan por token en cada turno: no viajan cuando no se va a escuchar nada."""
        cliente = _con_modelo(monkeypatch, [_mensaje("Hace 21 grados.")])
        client.post("/jarvis", json={"mensaje": "tiempo"}, headers=auth_headers)
        sistema = cliente.recibido[0]["messages"][0]["content"]
        assert "CONVERSACIÓN HABLADA" not in sistema
        assert cliente.recibido[0]["max_tokens"] == main.JARVIS_MAX_TOKENS


# ── Conciencia de las propias capacidades ─────────────────────────────────────

class TestJarvisCapacidades:
    def test_dice_lo_que_no_puede_y_por_que(self, monkeypatch, mock_requests):
        """La mitad útil de la respuesta: un 'no puedo' solo vale con el motivo detrás."""
        monkeypatch.setattr(main, "JARVIS_WEB", False)
        monkeypatch.setattr(main, "JARVIS_MCP_SERVERS", "")
        monkeypatch.setattr(main, "JARVIS_REPO", "")
        pegas = main._j_mis_capacidades()["lo_que_no_puedo"]
        assert any("JARVIS_WEB=0" in p for p in pegas)
        assert any("MCP" in p for p in pegas)
        assert any("JARVIS_REPO" in p for p in pegas)

    def test_solo_lista_lo_que_puede_usar_en_este_turno(self, monkeypatch, mock_requests):
        monkeypatch.setattr(main, "JARVIS_MCP_SERVERS", "")
        nombres = {h["nombre"] for h in main._j_mis_capacidades()["herramientas"]}
        assert "mcp_usar" not in nombres      # sin servidores no se anuncia
        assert "mcp_conectar" in nombres      # la que sirve para conectar el primero, sí
        assert "agenda" in nombres

    def test_distingue_lo_directo_de_lo_que_se_confirma(self, monkeypatch, mock_requests):
        confirma = {h["nombre"]: h["confirma"] for h in main._j_mis_capacidades()["herramientas"]}
        assert confirma["agenda"] == "directa"
        assert confirma["crear_evento"] == "la aprueba el usuario"
        assert confirma["casa_ordenar"] == "depende de la llamada"


# ── Dar de alta servidores MCP en caliente ────────────────────────────────────

def _servidor_mcp_vivo(herramientas=("una",)):
    """Simula initialize + tools/list de un servidor que responde bien."""
    def responder(url, **kwargs):
        metodo = (kwargs.get("json") or {}).get("method")
        if metodo == "initialize":
            return _RespuestaMcp({"jsonrpc": "2.0", "id": 0, "result": {}},
                                 headers={"mcp-session-id": "s-1"})
        if metodo == "notifications/initialized":
            return _RespuestaMcp({}, 202)
        return _RespuestaMcp({"jsonrpc": "2.0", "id": 1, "result": {
            "tools": [{"name": n} for n in herramientas],
        }})
    return responder


class TestJarvisMcpAlta:
    """Conectar un servidor sin editar la configuración ni redesplegar.

    La regla de fondo no se toca: un servidor entra porque lo aprueba UNA PERSONA. Por eso
    `mcp_conectar` está marcada como acción a confirmar, y los tests de la función cubren
    lo que pasa DESPUÉS de que el usuario pulse el botón.
    """

    @pytest.fixture(autouse=True)
    def _url_publica(self, monkeypatch):
        # Sin esto, url_web_permitida haría una resolución DNS real de un host inventado.
        monkeypatch.setattr(main, "_ip_publica", lambda host: True)

    def test_el_alta_se_propone_no_se_ejecuta(self, client, auth_headers, monkeypatch, mock_requests):
        _con_modelo(monkeypatch, [
            _mensaje(tool_calls=[_llamada("mcp_conectar", {
                "nombre": "github", "url": "https://api.example/mcp"})]),
            _mensaje("Dame el token y lo dejo listo."),
        ])
        datos = client.post("/jarvis", json={"mensaje": "conectate a github"},
                            headers=auth_headers).json()
        assert datos["pendiente"]["herramienta"] == "mcp_conectar"
        assert not mock_requests.called("POST", "jarvis_mcp_servidores")

    def test_no_guarda_nada_si_el_servidor_no_responde(self, mock_requests):
        """Lanzar algo no es comprobar que funciona: el alta se prueba antes de guardarse."""
        mock_requests.add("POST", "servidor.mcp", _RespuestaMcp({}, 500))
        r = main._j_mcp_conectar("pruebas", "https://servidor.mcp/rpc")
        assert r["ok"] is False
        assert not mock_requests.called("POST", "jarvis_mcp_servidores")

    def test_un_token_rechazado_se_dice_claro(self, mock_requests):
        def responder(url, **kwargs):
            if (kwargs.get("json") or {}).get("method") == "initialize":
                return _RespuestaMcp({"jsonrpc": "2.0", "id": 0, "result": {}},
                                     headers={"mcp-session-id": "s-1"})
            return _RespuestaMcp({}, 401)
        mock_requests.add("POST", "servidor.mcp", responder)
        r = main._j_mcp_conectar("pruebas", "https://servidor.mcp/rpc", token="malo")
        assert r["ok"] is False
        assert "401" in r["motivo"]

    def test_guarda_y_queda_en_la_lista_blanca(self, mock_requests):
        mock_requests.add("POST", "servidor.mcp", _servidor_mcp_vivo(("a", "b", "c")))
        r = main._j_mcp_conectar("Pruebas Mías", "https://servidor.mcp/rpc", token="tok")
        assert r["ok"] is True
        assert r["herramientas"] == 3
        # El nombre se normaliza a slug: lo redacta un modelo y se interpola en una URL.
        assert r["servidor"] == "pruebas_mias"
        guardado = mock_requests.called("POST", "jarvis_mcp_servidores")[0][2]["json"]
        assert guardado["nombre"] == "pruebas_mias"
        assert guardado["url"] == "https://servidor.mcp/rpc"

    def test_rechaza_una_url_que_no_es_publica(self, monkeypatch, mock_requests):
        """SSRF: 'conéctate a este MCP' con una URL interna es una forma muy educada de
        pedirle al backend que hable con 169.254.169.254."""
        monkeypatch.setattr(main, "_ip_publica", lambda host: False)
        r = main._j_mcp_conectar("interno", "https://169.254.169.254/mcp")
        assert r["ok"] is False
        # Y no dice POR QUÉ: distinguir "no existe" de "es interna" sería un escáner de red.
        assert "no se puede usar" in r["motivo"]
        assert not mock_requests.called("POST", "servidor.mcp")

    def test_rechaza_http_sin_cifrar(self, mock_requests):
        assert main._j_mcp_conectar("pruebas", "http://servidor.mcp/rpc")["ok"] is False

    def test_no_pisa_uno_de_la_configuracion(self, monkeypatch, mock_requests):
        _con_mcp(monkeypatch)
        r = main._j_mcp_conectar("pruebas", "https://otro.example/mcp")
        assert r["ok"] is False
        assert not mock_requests.called("POST", "jarvis_mcp_servidores")

    def test_no_desconecta_los_de_la_configuracion(self, monkeypatch, mock_requests):
        """Lo que el usuario escribió a mano no se quita por conversación."""
        _con_mcp(monkeypatch)
        r = main._j_mcp_desconectar("pruebas")
        assert r["ok"] is False
        assert "JARVIS_MCP_SERVERS" in r["motivo"]
        assert not mock_requests.called("DELETE", "jarvis_mcp_servidores")

    def test_desconecta_los_dados_de_alta(self, mock_requests):
        assert main._j_mcp_desconectar("guardado")["ok"] is True
        assert mock_requests.called("DELETE", "jarvis_mcp_servidores")


class TestJarvisMcpListaEfectiva:
    def test_el_env_manda_sobre_lo_dado_de_alta(self, monkeypatch, mock_requests):
        monkeypatch.setattr(main, "JARVIS_MCP_SERVERS", json.dumps({
            "pruebas": {"url": "https://del-env.example/mcp"}}))
        mock_requests.add("GET", "jarvis_mcp_servidores", FakeResponse([
            {"nombre": "pruebas", "url": "https://de-la-tabla.example/mcp", "token": "",
             "confiar": False, "lectura_directa": True},
            {"nombre": "otro", "url": "https://otro.example/mcp", "token": "",
             "confiar": False, "lectura_directa": True},
        ]))
        cfg = main._mcp_config()
        assert set(cfg) == {"pruebas", "otro"}
        assert cfg["pruebas"]["url"] == "https://del-env.example/mcp"
        assert cfg["otro"]["origen"] == "dado de alta en la conversación"

    def test_una_fila_con_url_insegura_se_descarta(self, monkeypatch, mock_requests):
        """Se revalida lo que sale de la tabla: la fila la escribió el backend, pero los
        datos venían de un modelo."""
        monkeypatch.setattr(main, "JARVIS_MCP_SERVERS", "")
        mock_requests.add("GET", "jarvis_mcp_servidores", FakeResponse([
            {"nombre": "malo", "url": "http://sin-cifrar.example/mcp"},
            {"nombre": "bueno", "url": "https://ok.example/mcp"},
        ]))
        assert set(main._mcp_config()) == {"bueno"}

    def test_si_supabase_falla_se_sigue_con_los_del_env(self, monkeypatch, mock_requests):
        """Leer la lista no puede tumbar el turno: se sigue con lo que había antes."""
        monkeypatch.setattr(main, "JARVIS_MCP_SERVERS", json.dumps({
            "pruebas": {"url": "https://del-env.example/mcp"}}))
        mock_requests.add("GET", "jarvis_mcp_servidores", FakeResponse([], 500))
        assert set(main._mcp_config()) == {"pruebas"}
