"""Tests de las llamadas a otras personas (la línea fija por O2), con la voice-app y el
modelo simulados.

Lo que se protege: que solo se llame a alguien de tus contactos de Outlook, por el
nombre, y a números de persona de España (nada de 112, 016 ni tarificación especial);
que la presentación la ponga el backend y no dependa del modelo; que la conversación con
el tercero la piense un modelo sin herramientas, con tope de turnos y una despedida si
falla; y que al colgar te llegue lo que dijo, o por qué no se habló.
"""
import json
from datetime import datetime
from types import SimpleNamespace

import pytest

import main
from conftest import FakeResponse

VOZ   = "http://voz.prueba:3000"
TOKEN = "token-terceros-de-prueba"
# Como los devuelve Graph (/me/contacts).
ERIK  = {"displayName": "Erik Uni", "givenName": "Erik", "surname": "", "nickName": "El Primo",
         "mobilePhone": "+34 600 11 12 22", "homePhones": [], "businessPhones": []}
ERIKA = {"displayName": "Erika Ruiz", "givenName": "Erika", "surname": "Ruiz", "nickName": "",
         "mobilePhone": None, "homePhones": ["944 11 12 22"], "businessPhones": []}
ITZIAR = {"displayName": "Itziar Óptica", "givenName": "", "surname": "", "nickName": "",
          "mobilePhone": None, "homePhones": [], "businessPhones": ["902 123 456"]}


def _contactos(*filas):
    return FakeResponse({"value": list(filas)})


class _Modelo:
    """chat.completions.create que devuelve lo que se le guioniza, en orden."""

    def __init__(self, *respuestas):
        self.respuestas = list(respuestas)
        self.pedidos = []
        self.chat = self
        self.completions = self

    def create(self, **kwargs):
        self.pedidos.append(kwargs)
        r = self.respuestas.pop(0)
        if isinstance(r, Exception):
            raise r
        contenido = r if isinstance(r, str) else json.dumps(r, ensure_ascii=False)
        return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=contenido))],
                               usage=None)


@pytest.fixture
def terceros(monkeypatch, mock_requests):
    monkeypatch.setattr(main, "TERCEROS_LLAMADAS", True)
    monkeypatch.setattr(main, "TELEFONO_URL", VOZ)
    monkeypatch.setattr(main, "TELEFONO_TERCEROS_TOKEN", TOKEN)
    monkeypatch.setattr(main, "_ahora_local", lambda: datetime(2026, 10, 31, 12, 0, tzinfo=main.LOCAL_TZ))
    monkeypatch.setattr(main, "_terceros", {})
    monkeypatch.setattr(main, "_contactos_cache", {"ts": 0.0, "filas": []})
    monkeypatch.setattr(main, "_seguir_tercero_seguro", lambda tid: None)
    monkeypatch.setattr(main, "get_valid_token", lambda: "graph-token")
    mock_requests.add("GET", "/me/contacts", _contactos(ERIK, ERIKA, ITZIAR))
    mock_requests.add("POST", "/api/outbound-call", FakeResponse({"success": True, "callId": "llamada-1"}))
    return mock_requests


def _llamar(**extra):
    args = {"nombre": "Erik", "mensaje": "Me pide que te pregunte si comes hoy con él.",
            "objetivo": "saber si come con Mikel hoy y a qué hora"}
    return main._j_llamar_a_alguien(**{**args, **extra})


class TestNumeros:
    @pytest.mark.parametrize("entrada", ["600111222", "+34 600 11 12 22", "0034600111222",
                                         "34600111222", "600-111-222", "(+34) 944.111.222",
                                         "711222333"])
    def test_de_persona_en_espana(self, entrada):
        assert main._tel_llamable(entrada).startswith("+34")

    @pytest.mark.parametrize("entrada", ["112", "016", "900123456", "806123456", "902123456",
                                         "701234567", "11811", "+33612345678", "60011122",
                                         "", None, "hola"])
    def test_lo_demas_no(self, entrada):
        assert main._tel_llamable(entrada) == ""


class TestConfiguracion:
    def test_apagado_no_hay_herramientas(self, monkeypatch):
        monkeypatch.setattr(main, "TERCEROS_LLAMADAS", False)
        nombres = {h["function"]["name"] for h in main._jarvis_esquema()}
        assert not {"llamar_a_alguien", "llamadas_a_otros"} & nombres

    def test_encendido_estan_las_dos(self, terceros):
        nombres = {h["function"]["name"] for h in main._jarvis_esquema()}
        assert {"llamar_a_alguien", "llamadas_a_otros"} <= nombres
        assert "apuntar_contacto" not in main._JARVIS_HERRAMIENTAS

    def test_pide_permiso_de_contactos(self, monkeypatch):
        monkeypatch.setattr(main, "CUMPLES", False)
        monkeypatch.setattr(main, "TERCEROS_LLAMADAS", False)
        assert "Contacts.Read" not in main._scopes()
        monkeypatch.setattr(main, "TERCEROS_LLAMADAS", True)
        assert "Contacts.Read" in main._scopes()

    def test_sin_token_no_se_enciende(self, terceros, monkeypatch):
        monkeypatch.setattr(main, "TELEFONO_TERCEROS_TOKEN", "")
        assert _llamar()["ok"] is False

    def test_llamar_es_autonomo(self):
        assert main._JARVIS_HERRAMIENTAS["llamar_a_alguien"]["confirmar"] is False

    def test_en_el_telefono(self):
        assert "llamar_a_alguien" in main._MCP_SERVIDOR_ACCIONES
        assert "llamadas_a_otros" in main._MCP_SERVIDOR_SOLO_LECTURA


class TestLlamar:
    def test_llama_por_la_linea_o2_con_la_presentacion(self, terceros):
        r = _llamar()
        assert r["ok"] is True and r["llamando_a"] == "Erik Uni"
        _, _, kw = terceros.called("POST", "/api/outbound-call")[0]
        cuerpo = kw["json"]
        assert cuerpo["to"] == "+34600111222"
        assert cuerpo["linea"] == "o2" and cuerpo["mode"] == "tercero"
        # Se le saluda por el nombre de pila, no por «Erik Uni».
        assert cuerpo["message"].startswith("Hola, Erik. Soy Jarvis, el asistente de Mikel.")
        assert "si comes hoy" in cuerpo["message"]
        mision = main._terceros[cuerpo["tercero"]]
        assert mision["call_id"] == "llamada-1" and mision["estado"] == "llamando"

    def test_por_apodo_y_sin_tildes(self, terceros):
        assert _llamar(nombre="el primo")["llamando_a"] == "Erik Uni"
        main._terceros.clear()
        r = _llamar(nombre="Itziar Optica")
        assert r["ok"] is False and "sin un móvil ni un fijo" in r["error"]   # el 902 no

    def test_el_fijo_si_no_tiene_movil(self, terceros):
        assert _llamar(nombre="Erika Ruiz")["ok"] is True
        _, _, kw = terceros.called("POST", "/api/outbound-call")[0]
        assert kw["json"]["to"] == "+34944111222"
        assert kw["json"]["message"].startswith("Hola, Erika.")

    def test_desconocido_no_se_llama(self, terceros):
        r = _llamar(nombre="Aimar")
        assert r["ok"] is False and "No encuentro a «Aimar»" in r["error"]
        assert not terceros.called("POST", "/api/outbound-call")
        # Antes de decir que no está, se ha vuelto a mirar sin caché.
        assert len(terceros.called("GET", "/me/contacts")) == 2

    def test_la_cache_vale_diez_minutos(self, terceros):
        assert _llamar()["ok"] is True
        main._terceros.clear()
        assert _llamar(nombre="Erika")["ok"] is True
        assert len(terceros.called("GET", "/me/contacts")) == 1

    def test_ambiguo_pregunta(self, terceros):
        terceros.routes.insert(0, ("GET", "/me/contacts", _contactos(
            ERIK, {**ERIK, "displayName": "Erik Sanz", "surname": "Sanz", "nickName": "",
                   "mobilePhone": "600999888"})))
        r = _llamar(nombre="erik")
        assert r["ok"] is False and "Hay varios: Erik Uni, Erik Sanz" in r["error"]
        assert _llamar(nombre="Erik Sanz")["ok"] is True

    def test_el_mismo_guardado_dos_veces_no_es_ambiguo(self, terceros):
        terceros.routes.insert(0, ("GET", "/me/contacts", _contactos(
            ERIK, {**ERIK, "displayName": "Erik"})))
        assert _llamar()["ok"] is True

    def test_sin_permiso_de_contactos_lo_dice(self, terceros):
        terceros.routes.insert(0, ("GET", "/me/contacts", FakeResponse({}, 403)))
        r = _llamar()
        assert r["ok"] is False and "volver a conectar Outlook" in r["error"].replace("vuelve a", "volver a")
        assert not terceros.called("POST", "/api/outbound-call")

    def test_sin_outlook_lo_dice(self, terceros, monkeypatch):
        monkeypatch.setattr(main, "get_valid_token", lambda: None)
        assert "Outlook no está conectado" in _llamar()["error"]

    def test_de_noche_no(self, terceros, monkeypatch):
        monkeypatch.setattr(main, "_ahora_local",
                            lambda: datetime(2026, 10, 31, 23, 0, tzinfo=main.LOCAL_TZ))
        assert _llamar()["ok"] is False

    def test_una_a_la_vez(self, terceros):
        assert _llamar()["ok"] is True
        r = _llamar()
        assert r["ok"] is False and "línea fija es una" in r["error"]

    def test_tope_diario(self, terceros, monkeypatch):
        monkeypatch.setattr(main, "TERCEROS_DIA_MAX", 1)
        assert _llamar()["ok"] is True
        for m in main._terceros.values():
            m["estado"] = "hecha"
        assert "tope" in _llamar()["error"]

    def test_si_la_voice_app_falla_se_dice(self, terceros):
        terceros.routes.insert(0, ("POST", "/api/outbound-call", FakeResponse({}, 503)))
        r = _llamar()
        assert r["ok"] is False
        assert all(m["estado"] == "fallida" for m in main._terceros.values())


class TestTurno:
    def _mision(self, terceros):
        _llamar()
        return next(iter(main._terceros))

    def test_pide_token(self, client, terceros):
        tid = self._mision(terceros)
        r = client.post(f"/telefono/tercero/{tid}/turno", json={"dicho": "¿Sí?"})
        assert r.status_code == 401

    def test_llamada_desconocida(self, client, terceros):
        r = client.post("/telefono/tercero/00000000-0000-0000-0000-000000000000/turno",
                        json={"dicho": "¿Sí?"}, headers={"X-Auth-Token": TOKEN})
        assert r.status_code == 404

    def test_conversa_y_apunta_el_resultado(self, client, terceros, monkeypatch):
        tid = self._mision(terceros)
        modelo = _Modelo({"decir": "¡Genial! ¿A qué hora te viene bien?", "colgar": False, "resultado": ""},
                         {"decir": "Perfecto, se lo digo. ¡Hasta luego!", "colgar": True,
                          "resultado": "Erik dice que sí, a las 14:30."})
        monkeypatch.setattr(main, "get_openai_client", lambda: modelo)
        h = {"X-Auth-Token": TOKEN}
        r1 = client.post(f"/telefono/tercero/{tid}/turno", json={"dicho": "Sí, claro"}, headers=h).json()
        assert r1 == {"decir": "¡Genial! ¿A qué hora te viene bien?", "colgar": False}
        r2 = client.post(f"/telefono/tercero/{tid}/turno", json={"dicho": "A las dos y media"}, headers=h).json()
        assert r2["colgar"] is True
        mision = main._terceros[tid]
        assert mision["resultado"] == "Erik dice que sí, a las 14:30."
        assert [t["quien"] for t in mision["turnos"]] == ["jarvis", "otro", "jarvis", "otro", "jarvis"]
        # Sin herramientas, y con la misión y la presentación en el sistema.
        pedido = modelo.pedidos[1]
        assert "tools" not in pedido
        assert "saber si come con Mikel" in pedido["messages"][0]["content"]
        assert pedido["messages"][-1] == {"role": "user", "content": "A las dos y media"}

    def test_si_el_modelo_falla_se_despide_y_cuelga(self, client, terceros, monkeypatch):
        tid = self._mision(terceros)
        monkeypatch.setattr(main, "get_openai_client", lambda: _Modelo(RuntimeError("caído")))
        r = client.post(f"/telefono/tercero/{tid}/turno", json={"dicho": "¿Sí?"},
                        headers={"X-Auth-Token": TOKEN}).json()
        assert r["colgar"] is True and "Mikel te escribirá" in r["decir"]

    def test_tope_de_turnos(self, client, terceros, monkeypatch):
        tid = self._mision(terceros)
        monkeypatch.setattr(main, "TERCEROS_TURNOS_MAX", 1)
        monkeypatch.setattr(main, "get_openai_client",
                            lambda: _Modelo({"decir": "Ya.", "colgar": False, "resultado": ""}))
        r = client.post(f"/telefono/tercero/{tid}/turno", json={"dicho": "Bla bla"},
                        headers={"X-Auth-Token": TOKEN}).json()
        assert r["colgar"] is True


class TestAlColgar:
    def _seguir(self, terceros, monkeypatch, info, modelo=None):
        avisos = []
        monkeypatch.setattr(main, "_notificar", lambda t, x, **kw: avisos.append((t, x)) or "movil")
        monkeypatch.setattr(main, "_dormir", lambda s: None)
        if modelo:
            monkeypatch.setattr(main, "get_openai_client", lambda: modelo)
        terceros.add("GET", "/api/call/llamada-1", FakeResponse({"success": True, "data": info}))
        _llamar()
        tid = next(iter(main._terceros))
        return tid, avisos

    def test_no_lo_coge(self, terceros, monkeypatch):
        tid, avisos = self._seguir(terceros, monkeypatch,
                                   {"state": "FAILED", "reason": "no_answer", "answeredAt": None})
        main._seguir_tercero(tid)
        assert avisos == [("📞 Erik Uni", "He llamado a Erik Uni y no lo ha cogido.")]
        assert main._terceros[tid]["estado"] == "sin_hablar"

    def test_hablaron_y_llega_el_resultado(self, terceros, monkeypatch):
        tid, avisos = self._seguir(terceros, monkeypatch,
                                   {"state": "COMPLETED", "reason": "conversation_complete",
                                    "answeredAt": "2026-10-31T11:00:05Z"})
        main._terceros[tid].update(estado="hablando", resultado="Erik dice que sí, a las 14:30.")
        main._seguir_tercero(tid)
        assert avisos == [("📞 Erik Uni", "Erik dice que sí, a las 14:30.")]

    def test_sin_resultado_se_resume(self, terceros, monkeypatch):
        tid, avisos = self._seguir(terceros, monkeypatch,
                                   {"state": "COMPLETED", "reason": "remote_hangup",
                                    "answeredAt": "2026-10-31T11:00:05Z"},
                                   modelo=_Modelo("Erik dice que hoy no puede."))
        main._terceros[tid]["turnos"].append({"quien": "otro", "texto": "Hoy no puedo, tío"})
        main._seguir_tercero(tid)
        assert avisos[0][1] == "Erik dice que hoy no puede."

    def test_lo_recuerda_marcado_como_dato(self, terceros, monkeypatch):
        tid, _ = self._seguir(terceros, monkeypatch,
                              {"state": "FAILED", "reason": "busy", "answeredAt": None})
        main._seguir_tercero(tid)
        r = main._j_llamadas_a_otros()
        assert r["aviso"] == main._AVISO_WEB
        assert r["llamadas"][0]["a"] == "Erik Uni" and r["llamadas"][0]["como_acabo"] == "comunicaba"

