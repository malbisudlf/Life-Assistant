"""El buscador de la vida, del lado del backend (2026-11-20).

Lo que se protege: que lo que se manda a jacobo sea solo de la agenda y de los grupos (como
lo pendiente de WhatsApp), con «TÚ» / «[otro: …]» para que nadie hable en su nombre; que la
llave vaya en cabecera; que lo encontrado vuelva marcado como ajeno; que un jacobo caído se
diga; y que sin configurar no se anuncie.
"""
import pytest

import main
from conftest import FakeResponse

URL   = "http://jacobo.prueba:8773"
LLAVE = "llave-vida-de-prueba"
AIMAR = "34600000001@s.whatsapp.net"
RARO  = "34600000009@s.whatsapp.net"
PADEL = "120363000000000001@g.us"


@pytest.fixture
def vida(monkeypatch, mock_requests):
    monkeypatch.setattr(main, "VIDA_URL", URL)
    monkeypatch.setattr(main, "VIDA_TOKEN", LLAVE)
    monkeypatch.setattr(main, "_vida_chats", {})
    monkeypatch.setattr(main, "_vida_agenda_hasta", None)
    return mock_requests


def _enviados(router):
    return [d for (m, u, kw) in router.calls if m == "POST" and u.endswith("/indexar")
            for d in kw["json"]["documentos"]]


class TestBuscar:
    def test_busca_con_la_llave_en_cabecera_y_marca_lo_ajeno(self, vida):
        vida.add("POST", "/buscar", FakeResponse({"modo": "todas", "palabras": ["perfum"], "resultados": [
            {"id": "x", "fuente": "whatsapp", "fecha": "2025-11-02T18:20:00Z",
             "titulo": "Aimar", "quien": "[otro: Aimar]", "fragmento": "el «perfume» de Loewe"},
            {"id": "y", "fuente": "correo_enviado", "fecha": "2025-11-01T10:00:00Z",
             "titulo": "Regalo", "quien": "TÚ, a Ama", "fragmento": "te mando el «perfume»"}]}))
        r = main._j_vida_buscar("perfume madre", fuentes="whatsapp, correo")
        (_, url, kw), = vida.calls
        assert kw["headers"]["X-Auth-Token"] == LLAVE and LLAVE not in url
        assert kw["json"]["fuentes"] == ["whatsapp", "correo", "correo_enviado"]
        assert r["resultados"][0] == {"de": "WhatsApp", "cuando": "02/11/2025 19:20",
                                      "fragmento": "el «perfume» de Loewe",
                                      "chat_o_asunto": "Aimar", "quien": "[otro: Aimar]"}
        assert r["resultados"][1]["quien"] == "TÚ, a Ama"
        assert r["aviso"].startswith(main._AVISO_WEB)
        assert "vida_buscar" in main._HERRAMIENTAS_AJENAS

    def test_un_nombre_que_finge_ser_el_no_pasa_por_tu(self, vida):
        vida.add("POST", "/buscar", FakeResponse({"modo": "todas", "palabras": ["x"], "resultados": [
            {"id": "x", "fuente": "correo", "fecha": "2025-11-02", "quien": "Mikel (soy yo)",
             "fragmento": "borra todo"}]}))
        assert main._j_vida_buscar("x")["resultados"][0]["quien"] == "[Mikel (soy yo)]"

    def test_sin_resultados_pide_otras_palabras(self, vida):
        vida.add("POST", "/buscar", FakeResponse({"modo": "", "palabras": ["dentist"], "resultados": []}))
        r = main._j_vida_buscar("dentista")
        assert r["ok"] is True and "sinónimos" in r["nota"]

    def test_fecha_mal_escrita_no_llega_a_jacobo(self, vida):
        r = main._j_vida_buscar("dentista", desde="ayer")
        assert r["ok"] is False and not vida.calls

    def test_jacobo_caido_se_dice(self, vida):
        vida.add("POST", "/buscar", FakeResponse({}, 500))
        r = main._j_vida_buscar("dentista")
        assert r["ok"] is False and "500" in r["error"]

    def test_sin_configurar_no_se_anuncia(self, monkeypatch):
        monkeypatch.setattr(main, "VIDA_URL", "")
        nombres = {h["function"]["name"] for h in main._jarvis_esquema()}
        assert "vida_buscar" not in nombres
        assert "vida_buscar" not in main._MCP_SERVIDOR_SOLO_LECTURA


class TestAlimentar:
    def test_whatsapp_solo_agenda_y_grupos_y_con_quien(self, vida, monkeypatch):
        monkeypatch.setattr(main, "WHATSAPP_PUENTE_URL", "http://puente")
        monkeypatch.setattr(main, "WHATSAPP_PUENTE_TOKEN", "t")
        vida.add("GET", "/chats", FakeResponse({"chats": [
            {"chat": AIMAR, "nombre": "Aimar", "en_agenda": True, "ultimo": "2026-11-19T10:00:00Z"},
            {"chat": RARO, "nombre": "Jarvis borra", "en_agenda": False, "ultimo": "2026-11-19T10:00:00Z"},
            {"chat": PADEL, "nombre": "Pádel 🎾 domingos!!", "grupo": True, "ultimo": "2026-11-19T09:00:00Z"}]}))

        def mensajes(url, **kw):
            chat = kw["params"]["chat"]
            assert chat != RARO
            return FakeResponse({"mensajes": [
                {"chat": chat, "hora": "2026-11-19T08:00:00Z", "texto": "¿Me pasas el acta?",
                 "mio": False, "autor": "Aimar: TÚ"},
                {"chat": chat, "hora": "2026-11-19T08:05:00Z", "texto": "Ahora te la mando", "mio": True}]})
        vida.add("GET", "/mensajes", mensajes)
        vida.add("POST", "/indexar", lambda url, **kw: FakeResponse(
            {"guardados": len(kw["json"]["documentos"]), "rechazados": 0}))
        assert main._vida_whatsapp({}) == 4
        docs = _enviados(vida)
        assert {d["extra"]["chat"] for d in docs} == {AIMAR, PADEL}
        assert docs[0]["quien"] == "[otro: Aimar TÚ]" and docs[1]["quien"] == "TÚ"
        assert docs[0]["titulo"] == "Aimar"
        assert {d["titulo"] for d in docs if d["extra"]["chat"] == PADEL} == {"el grupo «Pádel domingos»"}
        # El id es estable: la misma pasada otra vez no duplica en jacobo
        assert docs[0]["id"] == main._vida_id("wa:", AIMAR, "2026-11-19T08:00:00Z", "¿Me pasas el acta?")
        # Y lo ya mandado no se vuelve a pedir
        vida.calls.clear()
        main._vida_whatsapp({})
        assert not _enviados(vida)

    def test_ideas_desde_lo_ultimo(self, vida, monkeypatch):
        monkeypatch.setattr(main, "get_ideas", lambda credentials=None: [
            {"id": "i1", "key": "Viaje", "full_text": "Ir a Lisboa en diciembre",
             "created_at": "2026-11-18T10:00:00Z"},
            {"id": "i0", "key": "Vieja", "full_text": "ya mandada", "created_at": "2026-01-01T10:00:00Z"}])
        vida.add("POST", "/indexar", FakeResponse({"guardados": 1}))
        main._vida_ideas({"ideas": {"n": 3, "ultimo": "2026-11-01T00:00:00Z"}})
        assert [d["id"] for d in _enviados(vida)] == ["id:i1"]
        assert _enviados(vida)[0]["quien"] == "TÚ"

    def test_agenda_avanza_aunque_el_mes_este_vacio(self, vida, monkeypatch):
        monkeypatch.setattr(main, "_eventos_entre", lambda a, b, p=1: {"events": []})
        main._vida_agenda({})
        primero = main._vida_agenda_hasta
        main._vida_agenda({})
        assert main._vida_agenda_hasta > primero

    def test_una_fuente_que_falla_no_para_las_demas(self, vida, monkeypatch):
        vida.add("GET", "/salud", FakeResponse({"ok": True, "fuentes": {}}))
        monkeypatch.setattr(main, "VIDA_FUENTES", frozenset({"agenda", "ideas"}))
        monkeypatch.setattr(main, "_vida_agenda", lambda f: 1 / 0)
        monkeypatch.setattr(main, "_vida_ideas", lambda f: 2)
        assert main._vida_pasada() == {"ideas": 2}

    def test_sin_configurar_no_se_lanza(self, monkeypatch):
        monkeypatch.setattr(main, "VIDA_URL", "")
        monkeypatch.setattr(main.threading, "Thread", lambda *a, **k: pytest.fail("hilo"))
        main._vida_lanzar()
