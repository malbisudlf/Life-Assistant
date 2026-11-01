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
    monkeypatch.setattr(main, "_contactos_cache", {"ts": 0.0, "filas": [], "incompleto": ""})
    monkeypatch.setattr(main, "_seguir_tercero_seguro", lambda tid: None)
    monkeypatch.setattr(main, "ICLOUD_USUARIO", "")
    monkeypatch.setattr(main, "ICLOUD_CONTRASENA_APP", "")
    monkeypatch.setattr(main, "MI_MOVIL", "")
    monkeypatch.setattr(main, "TERCEROS_MOTOR", "openai")
    monkeypatch.setattr(main, "_terceros_claude_listo", {})
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

    def test_llamame_le_llama_a_el(self, terceros, monkeypatch):
        monkeypatch.setattr(main, "MI_MOVIL", "711 22 33 44")
        r = _llamar(nombre="Yo", mensaje="Es una prueba de la línea.")
        assert r["ok"] is True
        _, _, kw = terceros.called("POST", "/api/outbound-call")[0]
        assert kw["json"]["to"] == "+34711223344"
        assert kw["json"]["message"] == "Hola, señor. Soy Jarvis, desde el fijo de casa. Es una prueba de la línea."
        assert not terceros.called("GET", "/me/contacts")   # no busca en los contactos
        mision = next(iter(main._terceros.values()))
        assert mision["propio"] is True

    def test_llamame_sin_su_numero_lo_dice(self, terceros):
        r = _llamar(nombre="mí")
        assert r["ok"] is False and "MI_MOVIL" in r["error"]

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

    def test_a_el_mismo_le_habla_como_a_el(self, client, terceros, monkeypatch):
        monkeypatch.setattr(main, "MI_MOVIL", "711223344")
        _llamar(nombre="yo")
        tid = next(iter(main._terceros))
        modelo = _Modelo({"decir": "Le oigo perfectamente, señor.", "colgar": True, "resultado": "Se oye bien."})
        monkeypatch.setattr(main, "get_openai_client", lambda: modelo)
        client.post(f"/telefono/tercero/{tid}/turno", json={"dicho": "¿Me oyes?"},
                    headers={"X-Auth-Token": TOKEN})
        assert "propio Mikel" in modelo.pedidos[0]["messages"][0]["content"]

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


# ── iCloud (CardDAV) ─────────────────────────────────────────────────────────
VCARD_ERIK = (
    "BEGIN:VCARD\r\nVERSION:3.0\r\nN:Uni;Erik;;;\r\nFN:Erik Uni\r\n"
    "NICKNAME:Eriko\r\nitem1.TEL;type=pref:944 11 12 22\r\n"
    "TEL;type=CELL;type=VOICE:+34 600 22 2\r\n 3 33\r\nPHOTO;ENCODING=b:AAAA\r\nEND:VCARD\r\n")
VCARD_GRUPO = "BEGIN:VCARD\r\nFN:Familia\r\nX-ADDRESSBOOKSERVER-KIND:group\r\nEND:VCARD\r\n"
VCARD_MIKEL = ("BEGIN:VCARD\r\nN:Albisu;Mikel;;;\r\nFN:Mikel Albisu\r\n"
               "TEL;type=IPHONE;type=CELL:711 22 33 44\r\nEND:VCARD\r\n")


def _multistatus(*respuestas):
    return '<?xml version="1.0"?><multistatus xmlns="DAV:">' + "".join(respuestas) + "</multistatus>"


class _ICloud:
    """http.request para CardDAV: responde por método y URL, y guarda lo que se pidió."""

    def __init__(self, vcards, estado=207):
        self.pedidos = []
        self.vcards = vcards
        self.estado = estado

    def __call__(self, metodo, url, **kw):
        self.pedidos.append((metodo, url, kw))
        if self.estado != 207:
            return FakeResponse({}, self.estado)
        if url == "https://contacts.icloud.com/":
            xml = _multistatus("<response><href>/</href><propstat><prop><current-user-principal>"
                               "<href>/123/principal/</href></current-user-principal></prop>"
                               "</propstat></response>")
        elif url.endswith("/principal/"):
            xml = _multistatus('<response><href>/123/principal/</href><propstat><prop>'
                               '<C:addressbook-home-set xmlns:C="urn:ietf:params:xml:ns:carddav">'
                               '<href xmlns="DAV:">https://p45-contacts.icloud.com:443/123/carddav/</href>'
                               '</C:addressbook-home-set></prop></propstat></response>')
        elif metodo == "PROPFIND":
            xml = _multistatus("<response><href>/123/carddav/</href><propstat><prop><resourcetype>"
                               "<collection/></resourcetype></prop></propstat></response>",
                               "<response><href>/123/carddav/card/</href><propstat><prop><resourcetype>"
                               '<collection/><C:addressbook xmlns:C="urn:ietf:params:xml:ns:carddav"/>'
                               "</resourcetype></prop></propstat></response>")
        else:
            xml = _multistatus(*[
                f'<response><href>/123/carddav/card/{i}.vcf</href><propstat><prop>'
                f'<C:address-data xmlns:C="urn:ietf:params:xml:ns:carddav">'
                f'{v.replace("&", "&amp;").replace("<", "&lt;")}</C:address-data>'
                f'</prop></propstat></response>' for i, v in enumerate(self.vcards)])
        return FakeResponse({}, 207, text=xml)


@pytest.fixture
def icloud(terceros, monkeypatch):
    monkeypatch.setattr(main, "ICLOUD_USUARIO", "apple@prueba.invalid")
    monkeypatch.setattr(main, "ICLOUD_CONTRASENA_APP", "abcd-efgh-ijkl-mnop")
    falso = _ICloud([VCARD_ERIK, VCARD_GRUPO, VCARD_MIKEL])
    monkeypatch.setattr(main.http, "request", falso)
    # En Outlook no está Erik: solo Erika y la óptica.
    terceros.routes.insert(0, ("GET", "/me/contacts", _contactos(ERIKA, ITZIAR)))
    return falso


class TestICloud:
    def test_la_vcard(self):
        c = main._vcard_contacto(VCARD_ERIK)
        assert c["nombre"] == "Erik Uni" and c["pila"] == "Erik" and c["apodo"] == "Eriko"
        # El móvil antes que el «pref», aunque venga después y partido en dos líneas.
        assert c["tels"] == ["+34 600 22 23 33", "944 11 12 22"]
        assert main._vcard_contacto(VCARD_GRUPO) is None

    def test_escapes_de_la_vcard(self):
        c = main._vcard_contacto("BEGIN:VCARD\nFN:Ane\\, la de clase\nEND:VCARD")
        assert c["nombre"] == "Ane, la de clase" and c["pila"] == "" and c["tels"] == []

    def test_descubre_la_agenda_y_lee_las_vcards(self, icloud):
        contactos = main._contactos_icloud()
        assert [c["nombre"] for c in contactos] == ["Erik Uni", "Mikel Albisu"]
        metodos = [(m, u) for m, u, _ in icloud.pedidos]
        assert metodos[-1] == ("REPORT", "https://p45-contacts.icloud.com:443/123/carddav/card/")
        _, _, kw = icloud.pedidos[0]
        assert kw["auth"] == ("apple@prueba.invalid", "abcd-efgh-ijkl-mnop")

    def test_llama_a_alguien_que_solo_esta_en_icloud(self, icloud, terceros):
        r = _llamar(nombre="eriko")
        assert r["ok"] is True and r["llamando_a"] == "Erik Uni"
        _, _, kw = terceros.called("POST", "/api/outbound-call")[0]
        assert kw["json"]["to"] == "+34600222333"

    def test_por_nombre_y_apellido(self, icloud):
        assert _llamar(nombre="Mikel Albisu")["llamando_a"] == "Mikel Albisu"

    def test_outlook_caido_no_tumba_icloud(self, icloud, terceros):
        terceros.routes.insert(0, ("GET", "/me/contacts", FakeResponse({}, 403)))
        assert _llamar()["ok"] is True
        main._terceros.clear()
        r = _llamar(nombre="Aimar")
        assert "No encuentro a «Aimar»" in r["error"] and "Outlook" in r["error"]

    def test_icloud_con_mala_contrasena_y_outlook_bien(self, icloud):
        icloud.estado = 401
        r = _llamar()
        assert r["ok"] is False and "iCloud no acepta" in r["error"]
        assert _llamar(nombre="Erika")["ok"] is True

    def test_los_dos_caidos(self, icloud, terceros):
        icloud.estado = 401
        terceros.routes.insert(0, ("GET", "/me/contacts", FakeResponse({}, 500)))
        r = _llamar()
        assert "No he podido mirar sus contactos" in r["error"] and "iCloud" in r["error"]

    def test_el_mismo_en_outlook_y_en_icloud_no_es_ambiguo(self, icloud, terceros):
        terceros.routes.insert(0, ("GET", "/me/contacts", _contactos(
            {**ERIK, "mobilePhone": "600222333"})))
        assert _llamar()["ok"] is True


# ── Con Claude (una sesión de Claude Code en caja, sin nada a mano) ───────────
def _respuesta_claude(datos):
    return FakeResponse({"respuesta": "```json\n" + json.dumps(datos, ensure_ascii=False) + "\n```"})


@pytest.fixture
def con_claude(terceros, monkeypatch):
    monkeypatch.setattr(main, "TERCEROS_MOTOR", "claude")
    monkeypatch.setattr(main, "JARVIS_CLAUDE_URL", "http://caja.prueba:3340")
    monkeypatch.setattr(main, "JARVIS_CLAUDE_TOKEN", "claude-token")
    terceros.add("POST", "/tercero/abrir", FakeResponse({"ok": True}))
    terceros.add("POST", "/tercero/cerrar", FakeResponse({"ok": True}))

    def sin_openai():
        raise AssertionError("no debía pensar OpenAI")
    monkeypatch.setattr(main, "get_openai_client", sin_openai)
    return terceros


def _esperar_abierta():
    for m in main._terceros.values():
        main._terceros_claude_listo[m["tid"]].wait(2)
        return m


class TestConClaude:
    def test_se_abre_al_marcar_con_el_encargo(self, con_claude):
        assert _llamar()["ok"] is True
        mision = _esperar_abierta()
        assert mision["claude"] == "abierta"
        _, url, kw = con_claude.called("POST", "/tercero/abrir")[0]
        assert kw["json"]["id"] == mision["tid"]
        assert "saber si come con Mikel" in kw["json"]["sistema"]
        assert kw["headers"]["Authorization"] == "Bearer claude-token"

    def test_piensa_claude_y_solo_le_llega_lo_nuevo(self, client, con_claude):
        _llamar()
        tid = _esperar_abierta()["tid"]
        con_claude.add("POST", "/tercero/turno",
                       _respuesta_claude({"decir": "¡Genial! ¿A qué hora?", "colgar": False, "resultado": ""}))
        h = {"X-Auth-Token": TOKEN}
        r = client.post(f"/telefono/tercero/{tid}/turno", json={"dicho": "Sí, claro"}, headers=h).json()
        assert r == {"decir": "¡Genial! ¿A qué hora?", "colgar": False}
        client.post(f"/telefono/tercero/{tid}/turno", json={"dicho": "A las dos"}, headers=h)
        textos = [kw["json"]["texto"] for _, _, kw in con_claude.called("POST", "/tercero/turno")]
        assert textos == ["Sí, claro", "A las dos"]

    def test_si_claude_falla_sigue_openai_hasta_el_final(self, client, con_claude, monkeypatch):
        _llamar()
        tid = _esperar_abierta()["tid"]
        con_claude.add("POST", "/tercero/turno", FakeResponse({"error": "x"}, 502))
        modelo = _Modelo({"decir": "Vale.", "colgar": False, "resultado": ""},
                         {"decir": "Adiós.", "colgar": True, "resultado": "Dice que sí."})
        monkeypatch.setattr(main, "get_openai_client", lambda: modelo)
        h = {"X-Auth-Token": TOKEN}
        assert client.post(f"/telefono/tercero/{tid}/turno", json={"dicho": "Hola"}, headers=h).json()["decir"] == "Vale."
        assert client.post(f"/telefono/tercero/{tid}/turno", json={"dicho": "Sí"}, headers=h).json()["colgar"] is True
        assert len(con_claude.called("POST", "/tercero/turno")) == 1   # después, ya no
        assert con_claude.called("POST", "/tercero/cerrar")
        # OpenAI recibe la transcripción entera, no solo lo último.
        assert [m["content"] for m in modelo.pedidos[1]["messages"] if m["role"] == "user"] == ["Hola", "Sí"]

    def test_sin_json_tambien_cae_a_openai(self, client, con_claude, monkeypatch):
        _llamar()
        tid = _esperar_abierta()["tid"]
        con_claude.add("POST", "/tercero/turno", FakeResponse({"respuesta": "Hola, ¿qué tal?"}))
        monkeypatch.setattr(main, "get_openai_client",
                            lambda: _Modelo({"decir": "Vale.", "colgar": False, "resultado": ""}))
        r = client.post(f"/telefono/tercero/{tid}/turno", json={"dicho": "Hola"},
                        headers={"X-Auth-Token": TOKEN}).json()
        assert r["decir"] == "Vale."

    def test_si_no_se_abre_piensa_openai(self, client, con_claude, monkeypatch):
        con_claude.routes.insert(0, ("POST", "/tercero/abrir", FakeResponse({"error": "x"}, 503)))
        _llamar()
        mision = _esperar_abierta()
        assert mision["claude"] == "rota"
        monkeypatch.setattr(main, "get_openai_client",
                            lambda: _Modelo({"decir": "Vale.", "colgar": False, "resultado": ""}))
        r = client.post(f"/telefono/tercero/{mision['tid']}/turno", json={"dicho": "Hola"},
                        headers={"X-Auth-Token": TOKEN}).json()
        assert r["decir"] == "Vale."
        assert not con_claude.called("POST", "/tercero/turno")

    def test_al_colgar_se_cierra(self, con_claude, monkeypatch):
        monkeypatch.setattr(main, "_notificar", lambda *a, **kw: "movil")
        monkeypatch.setattr(main, "_dormir", lambda s: None)
        con_claude.add("GET", "/api/call/llamada-1", FakeResponse(
            {"success": True, "data": {"state": "FAILED", "reason": "no_answer", "answeredAt": None}}))
        _llamar()
        mision = _esperar_abierta()
        main._seguir_tercero(mision["tid"])
        assert con_claude.called("POST", "/tercero/cerrar")
        assert mision["tid"] not in main._terceros_claude_listo


class TestDevolverLaLlamada:
    def _seguir(self, terceros, monkeypatch, boca):
        llamadas, avisos = [], []
        monkeypatch.setattr(main, "_llamar_telefono",
                            lambda texto, **kw: llamadas.append((texto, kw)) or True)
        monkeypatch.setattr(main, "_notificar", lambda t, x, **kw: avisos.append(x) or "movil")
        monkeypatch.setattr(main, "_dormir", lambda s: None)
        terceros.add("GET", "/api/call/llamada-1", FakeResponse(
            {"success": True, "data": {"state": "COMPLETED", "reason": "conversation_complete",
                                       "answeredAt": "2026-11-01T11:00:05Z"}}))
        marca = main._boca_actual.set(boca)
        try:
            _llamar(nombre="Erika")
        finally:
            main._boca_actual.reset(marca)
        mision = next(iter(main._terceros.values()))
        mision.update(estado="hablando", resultado="Erika dice que llega a las 21:30.")
        main._seguir_tercero(mision["tid"])
        return llamadas, avisos

    def test_pedido_por_telefono_le_llama_y_solo_lee(self, terceros, monkeypatch):
        llamadas, avisos = self._seguir(terceros, monkeypatch, "telefono")
        assert avisos == ["Erika dice que llega a las 21:30."]
        texto, kw = llamadas[0]
        assert texto == "Señor, le cuento la llamada a Erika Ruiz. Erika dice que llega a las 21:30."
        # Solo lee y cuelga: con la conversación, contestaría el Claude Code con terminal.
        assert kw["modo"] == "announce"

    def test_pedido_por_el_chat_basta_el_aviso(self, terceros, monkeypatch):
        llamadas, avisos = self._seguir(terceros, monkeypatch, "chat")
        assert avisos and not llamadas

    def test_llamar_telefono_en_modo_aviso(self, monkeypatch, mock_requests):
        monkeypatch.setattr(main, "TELEFONO_URL", VOZ)
        monkeypatch.setattr(main, "TELEFONO_EXTENSION", "11411")
        monkeypatch.setattr(main, "_insistir_en_segundo_plano", lambda *a: None)
        mock_requests.add("POST", "/api/outbound-call", FakeResponse({"success": True, "callId": "c"}))
        assert main._llamar_telefono("Hola", modo="announce") is True
        _, _, kw = mock_requests.called("POST", "/api/outbound-call")[0]
        assert kw["json"]["mode"] == "announce"
