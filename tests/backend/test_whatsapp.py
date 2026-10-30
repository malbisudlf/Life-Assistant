"""Tests de WhatsApp en Jarvis (leer y enviar), con el puente de caja simulado.

Lo que se protege: que el token vaya en la cabecera; que sin puente configurado Jarvis ni
vea las herramientas; que enviar siga la frontera de siempre (se confirma, y lo que dice el
botón —el nombre del PUENTE y el texto entero— es lo que se manda); que solo se mande a un
chat que el puente tiene; que lo leído vaya marcado como dato y recortado; y que leer no
esté en el teléfono, que tiene shell en caja.
"""
import pytest

import main
from conftest import FakeResponse

PUENTE = "http://whatsapp.prueba:8090"
TOKEN  = "token-del-puente-de-prueba"
AIMAR  = "34600000001@s.whatsapp.net"


@pytest.fixture
def wa(monkeypatch, mock_requests):
    monkeypatch.setattr(main, "WHATSAPP_PUENTE_URL", PUENTE)
    monkeypatch.setattr(main, "WHATSAPP_PUENTE_TOKEN", TOKEN)
    return mock_requests


def _chats(*filas):
    return FakeResponse({"chats": list(filas)})


def _aimar(**extra):
    return {"chat": AIMAR, "nombre": "Aimar", "grupo": False, "en_agenda": True,
            "ultimo": "2026-10-30T16:20:00Z", **extra}


class TestConfiguracion:
    def test_sin_puente_no_hay_herramientas(self, monkeypatch):
        monkeypatch.setattr(main, "WHATSAPP_PUENTE_URL", "")
        nombres = {h["function"]["name"] for h in main._jarvis_esquema()}
        assert not {"whatsapp_chats", "whatsapp_leer", "whatsapp_enviar"} & nombres

    def test_con_puente_estan_las_tres(self, wa):
        nombres = {h["function"]["name"] for h in main._jarvis_esquema()}
        assert {"whatsapp_chats", "whatsapp_leer", "whatsapp_enviar"} <= nombres

    def test_el_token_va_en_la_cabecera(self, wa):
        wa.add("GET", "/chats", _chats(_aimar()))
        main._j_whatsapp_chats("aimar")
        _, url, kwargs = wa.called("GET", "/chats")[0]
        assert TOKEN not in url and TOKEN not in str(kwargs.get("params"))
        assert kwargs["headers"]["X-Auth-Token"] == TOKEN

    def test_token_rechazado_se_dice(self, wa):
        wa.add("GET", "/chats", FakeResponse({"error": "token inválido"}, 401))
        r = main._j_whatsapp_chats("aimar")
        assert r["ok"] is False and "WHATSAPP_PUENTE_TOKEN" in r["error"]

    def test_puente_caido_se_dice(self, wa):
        def caido(url, **kw):
            raise ConnectionError("nada")
        wa.add("GET", "/mensajes", caido)
        r = main._j_whatsapp_leer()
        assert r["ok"] is False and "no contesta" in r["error"]


class TestChats:
    def test_devuelve_el_chat_y_la_hora_local(self, wa):
        wa.add("GET", "/chats", _chats(_aimar()))
        r = main._j_whatsapp_chats("aimar")
        assert r["resultados"] == [{"chat": AIMAR, "nombre": "Aimar", "grupo": False,
                                    "en_agenda": True, "ultimo_mensaje": "30/10 17:20"}]
        assert r["aviso"] == main._AVISO_WEB

    def test_un_chat_raro_del_puente_no_pasa(self, wa):
        wa.add("GET", "/chats", _chats(_aimar(chat="123@lid"), _aimar(chat="x@broadcast")))
        r = main._j_whatsapp_chats("aimar")
        assert r["resultados"] == [] and "No encuentro" in r["nota"]


class TestLeer:
    def _mensajes(self, wa, mensajes, **extra):
        wa.add("GET", "/mensajes", FakeResponse({"mensajes": mensajes, **extra}))

    def test_agrupa_por_chat_y_dice_de_quien_es_el_ultimo(self, wa):
        self._mensajes(wa, [
            {"chat": AIMAR, "chat_nombre": "Aimar", "grupo": False, "mio": False,
             "autor": "Aimar", "hora": "2026-10-30T16:20:00Z",
             "texto": "Oye, ¿me mandas el acta antes del viernes?"},
            {"chat": "34600000002@s.whatsapp.net", "chat_nombre": "Ane", "grupo": False,
             "mio": False, "autor": "Ane", "hora": "2026-10-30T16:25:00Z", "texto": "¿Cenamos?"},
            {"chat": "34600000002@s.whatsapp.net", "chat_nombre": "Ane", "grupo": False,
             "mio": True, "autor": "", "hora": "2026-10-30T16:30:00Z", "texto": "Vale"},
        ])
        r = main._j_whatsapp_leer()
        aimar, ane = r["chats"]
        assert aimar["mensajes"] == ["30/10 17:20 Aimar: Oye, ¿me mandas el acta antes del viernes?"]
        assert aimar["ultimo_es_tuyo"] is False
        assert ane["mensajes"][-1] == "30/10 17:30 tú: Vale" and ane["ultimo_es_tuyo"] is True
        assert r["aviso"].startswith(main._AVISO_WEB)

    def test_sin_grupos_salvo_que_se_pidan(self, wa):
        self._mensajes(wa, [])
        main._j_whatsapp_leer()
        main._j_whatsapp_leer(grupos=True)
        params = [c[2]["params"] for c in wa.called("GET", "/mensajes")]
        assert "grupos" not in params[0] and params[1]["grupos"] == "1"

    def test_recorta_los_mensajes_largos(self, wa):
        self._mensajes(wa, [{"chat": AIMAR, "chat_nombre": "Aimar", "mio": False,
                             "autor": "Aimar", "hora": "2026-10-30T16:20:00Z",
                             "texto": "palabra " * 300}])
        linea = main._j_whatsapp_leer()["chats"][0]["mensajes"][0]
        assert len(linea) < main._WHATSAPP_LEIDO_MAX + 40 and linea.endswith("…")

    def test_un_chat_inventado_no_llega_al_puente(self, wa):
        r = main._j_whatsapp_leer(chat="../estado")
        assert r["ok"] is False and not wa.called("GET", "/mensajes")

    def test_avisa_si_el_puente_esta_desconectado(self, wa):
        self._mensajes(wa, [], conectado=False)
        assert "no está conectado" in main._j_whatsapp_leer()["puente"]

    def test_horas_acotadas(self, wa):
        self._mensajes(wa, [])
        main._j_whatsapp_leer(horas=100000)
        assert wa.called("GET", "/mensajes")[0][2]["params"]["horas"] == 720


class TestEnviar:
    def test_se_confirma(self):
        h = main._JARVIS_HERRAMIENTAS["whatsapp_enviar"]
        assert main._jarvis_confirma(h, {"chat": AIMAR, "texto": "hola"}) is True
        assert "whatsapp_enviar" in main.PREGUNTAS_ACCIONES
        assert "whatsapp_enviar" in main.PREGUNTAS_HABLADAS

    def test_la_frase_lleva_el_nombre_del_puente_y_el_texto_entero(self, wa):
        wa.add("GET", "/chats", _chats(_aimar(nombre="Aimar Ibáñez")))
        d = main._describir_whatsapp_enviar({"chat": AIMAR, "texto": "Llego cinco minutos tarde"})
        assert d == {"texto": "Mandar por WhatsApp a Aimar Ibáñez: «Llego cinco minutos tarde»"}
        # Se busca por el número, no por un nombre que podría escribir el modelo.
        assert wa.called("GET", "/chats")[0][2]["params"]["q"] == "34600000001"

    def test_a_un_grupo_lo_dice(self, wa):
        grupo = "120363000000000001@g.us"
        wa.add("GET", "/chats", _chats({"chat": grupo, "nombre": "Pádel", "grupo": True}))
        d = main._describir_whatsapp_enviar({"chat": grupo, "texto": "Voy"})
        assert d["texto"].startswith("Mandar por WhatsApp al grupo Pádel")

    def test_un_chat_que_el_puente_no_tiene_no_se_propone(self, wa):
        wa.add("GET", "/chats", _chats())
        d = main._describir_whatsapp_enviar({"chat": "34699999999@s.whatsapp.net",
                                             "texto": "hola"})
        assert "ni en tus chats ni en tu agenda" in d["error"]

    def test_valida_antes_de_proponer(self):
        assert "no es válido" in main._propuesta_invalida(
            "whatsapp_enviar", {"chat": "+34 600", "texto": "hola"})
        assert "largo" in main._propuesta_invalida(
            "whatsapp_enviar", {"chat": AIMAR, "texto": "x" * 2001})
        assert main._propuesta_invalida("whatsapp_enviar", {"chat": AIMAR, "texto": "hola"}) == ""

    def test_lo_guardado_para_el_movil_no_se_recorta(self):
        texto = "palabra " * 60   # 480 caracteres: más que los 300 del resto
        args = main._args_de("whatsapp_enviar", {"chat": AIMAR, "texto": texto})
        assert args["texto"] == texto

    def test_envia_lo_que_dice(self, wa):
        wa.add("POST", "/enviar", FakeResponse({"ok": True, "id": "X", "a": "Aimar",
                                                "hora": "2026-10-30T16:40:00Z"}))
        r = main._jarvis_despachar("whatsapp_enviar", {"chat": AIMAR, "texto": " Llego tarde "})
        assert r == {"ok": True, "enviado_a": "Aimar", "hora": "30/10 17:40"}
        assert wa.called("POST", "/enviar")[0][2]["json"] == {"chat": AIMAR, "texto": "Llego tarde"}
        assert main._lo_hecho("whatsapp_enviar", {}, r) == "Enviado a Aimar."

    def test_el_rechazo_del_puente_se_dice(self, wa):
        wa.add("POST", "/enviar", FakeResponse({"error": "el puente no está conectado a "
                                                         "WhatsApp"}, 503))
        r = main._j_whatsapp_enviar(AIMAR, "hola")
        assert r["ok"] is False and "no está conectado" in r["error"]


class TestTelefono:
    def test_leer_no_esta_en_el_telefono(self):
        assert "whatsapp_leer" not in main._MCP_SERVIDOR_HERRAMIENTAS

    def test_buscar_y_enviar_si(self):
        assert {"whatsapp_chats", "whatsapp_enviar"} <= main._MCP_SERVIDOR_HERRAMIENTAS
        assert "whatsapp_enviar" in main._MCP_SERVIDOR_CONFIRMA_EN_MOVIL
