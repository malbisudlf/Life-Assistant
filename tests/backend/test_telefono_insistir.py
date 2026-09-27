"""Tests de lo que pasa cuando no coges el teléfono: otra llamada, y después el buzón.

Lo que se comprueba es la cadena entera sin esperar de verdad (`_dormir` no duerme) y,
sobre todo, cuándo NO se insiste: una llamada contestada, rechazada o de la que no se
sabe cómo acabó no vuelve a sonar. Llamarte dos veces seguidas por algo que ya has oído
es la forma más rápida de que dejes de coger el teléfono.
"""
import pytest

import main
from conftest import FakeResponse

CENTRALITA = "/api/outbound-call"


@pytest.fixture(autouse=True)
def _configurado(monkeypatch):
    monkeypatch.setattr(main, "TELEFONO_URL", "http://centralita.test:3010")
    monkeypatch.setattr(main, "TELEFONO_EXTENSION", "11410")
    monkeypatch.setattr(main, "TELEFONO_INTENTOS", 2)
    monkeypatch.setattr(main, "TELEFONO_BUZON", True)
    monkeypatch.setattr(main, "_dormir", lambda s: None)


def _centralita(mock_requests, estados):
    """Cada llamada lanzada recibe un callId (c1, c2…) y acaba como diga `estados`.

    `estados` es una lista de (state, reason) por llamada, en orden; None es un 404, que
    es lo que contesta un claude-phone sin el parche 7 (no encuentra la sesión nunca).
    """
    lanzadas = []

    def _post(url, **kw):
        lanzadas.append(kw["json"])
        return FakeResponse({"success": True, "callId": f"c{len(lanzadas)}"})

    def _get(url, **kw):
        n = int(url.rsplit("/c", 1)[1])
        estado = estados[n - 1]
        if estado is None:
            return FakeResponse({}, 404)
        return FakeResponse({"success": True,
                             "data": {"state": estado[0], "reason": estado[1]}})

    mock_requests.add("POST", CENTRALITA, _post)
    mock_requests.add("GET", "/api/call/", _get)
    return lanzadas


def _cuerpo(texto="Mikel, soy Jarvis. home-assistant lleva un rato sin responder."):
    return {"to": "11410", "device": "Jarvis", "mode": "conversation",
            "message": texto, "timeoutSeconds": main.TELEFONO_TIMBRE_SEG,
            "context": "lo que sabe Jarvis"}


NO_COGIDA = ("FAILED", "no_answer")
COGIDA    = ("COMPLETED", "conversation_complete")


class TestLaPrimeraLlamada:
    def test_pide_colgar_antes_de_que_salte_el_buzon(self, mock_requests, monkeypatch):
        """Sin `timeoutSeconds` el 3CX desviaba al buzón, el buzón descolgaba y Jarvis
        se quedaba hablando con él con la línea ocupada."""
        monkeypatch.setattr(main, "_insistir_en_segundo_plano", lambda *a: None)
        lanzadas = _centralita(mock_requests, [COGIDA])
        assert main._llamar_telefono("hola", rid="r-1") is True
        assert lanzadas[0]["timeoutSeconds"] == main.TELEFONO_TIMBRE_SEG
        assert lanzadas[0]["mode"] == "conversation"

    def test_con_callid_se_queda_vigilando_la_llamada(self, mock_requests, monkeypatch):
        seguidas = []
        monkeypatch.setattr(main, "_insistir_en_segundo_plano",
                            lambda call_id, cuerpo, rid: seguidas.append((call_id, rid)))
        _centralita(mock_requests, [COGIDA])
        main._llamar_telefono("hola", rid="r-1")
        assert seguidas == [("c1", "r-1")]

    def test_sin_callid_no_hay_nada_que_vigilar(self, mock_requests, monkeypatch):
        """Una centralita que no devuelve callId sigue valiendo para que suene."""
        seguidas = []
        monkeypatch.setattr(main, "_insistir_en_segundo_plano",
                            lambda *a: seguidas.append(a))
        assert main._llamar_telefono("hola") is True
        assert seguidas == []

    def test_si_no_llega_a_lanzarse_no_se_insiste(self, mock_requests, monkeypatch):
        seguidas = []
        monkeypatch.setattr(main, "_insistir_en_segundo_plano",
                            lambda *a: seguidas.append(a))
        mock_requests.add("POST", CENTRALITA, FakeResponse({}, 503, text="SIP sin registrar"))
        assert main._llamar_telefono("hola") is False
        assert seguidas == []


class TestInsistir:
    def test_no_la_coges_dos_veces_y_te_deja_el_mensaje(self, mock_requests):
        lanzadas = _centralita(mock_requests, [NO_COGIDA, NO_COGIDA, COGIDA])
        cuerpo = _cuerpo()
        main._lanzar_llamada(cuerpo)                     # la primera, c1
        main._insistir("c1", cuerpo, "vigilancia:home-assistant")
        assert len(lanzadas) == 3
        # La segunda es la misma llamada otra vez: con conversación y con lo que sabe.
        assert lanzadas[1] == cuerpo
        # La tercera es el buzón: leída y colgada, sin modelo al otro lado.
        buzon = lanzadas[2]
        assert buzon["mode"] == "announce"
        assert "context" not in buzon
        assert buzon["timeoutSeconds"] == main.TELEFONO_BUZON_TIMBRE_SEG
        assert buzon["timeoutSeconds"] > main.TELEFONO_TIMBRE_SEG
        assert buzon["delaySeconds"] == main.TELEFONO_BUZON_ESPERA_SEG
        assert "Te he llamado 2 veces" in buzon["message"]
        assert "home-assistant lleva un rato sin responder" in buzon["message"]

    def test_si_la_coges_a_la_primera_no_vuelve_a_sonar(self, mock_requests):
        lanzadas = _centralita(mock_requests, [COGIDA])
        cuerpo = _cuerpo()
        main._lanzar_llamada(cuerpo)
        main._insistir("c1", cuerpo, "r")
        assert len(lanzadas) == 1

    def test_mientras_suena_espera_a_que_acabe(self, mock_requests):
        """Un sondeo que la pilla todavía sonando no es un resultado: sigue mirando."""
        lanzadas, vistas = [], []

        def _post(url, **kw):
            lanzadas.append(kw["json"])
            return FakeResponse({"callId": f"c{len(lanzadas)}"})

        def _get(url, **kw):
            vistas.append(url)
            estado = "DIALING" if len(vistas) < 3 else "CONVERSING"
            return FakeResponse({"data": {"state": estado}})

        mock_requests.add("POST", CENTRALITA, _post)
        mock_requests.add("GET", "/api/call/", _get)
        assert main._como_acabo("c1") == "cogida"
        assert len(vistas) == 3

    def test_si_la_coges_a_la_segunda_no_hay_buzon(self, mock_requests):
        lanzadas = _centralita(mock_requests, [NO_COGIDA, COGIDA])
        cuerpo = _cuerpo()
        main._lanzar_llamada(cuerpo)
        main._insistir("c1", cuerpo, "r")
        assert len(lanzadas) == 2
        assert all(l["mode"] == "conversation" for l in lanzadas)

    def test_comunicando_cuenta_como_no_cogida(self, mock_requests):
        lanzadas = _centralita(mock_requests, [("FAILED", "busy"), COGIDA])
        cuerpo = _cuerpo()
        main._lanzar_llamada(cuerpo)
        main._insistir("c1", cuerpo, "r")
        assert len(lanzadas) == 2

    def test_si_la_rechazas_no_insiste(self, mock_requests):
        """Colgarle a quien ha rechazado la llamada para volver a llamarle, no."""
        lanzadas = _centralita(mock_requests, [("FAILED", "declined")])
        cuerpo = _cuerpo()
        main._lanzar_llamada(cuerpo)
        main._insistir("c1", cuerpo, "r")
        assert len(lanzadas) == 1

    def test_una_averia_de_la_centralita_no_se_arregla_insistiendo(self, mock_requests):
        lanzadas = _centralita(mock_requests, [("FAILED", "service_unavailable")])
        cuerpo = _cuerpo()
        main._lanzar_llamada(cuerpo)
        main._insistir("c1", cuerpo, "r")
        assert len(lanzadas) == 1

    def test_sin_el_parche_de_claude_phone_se_queda_como_antes(self, mock_requests):
        """Sin el parche 7, `GET /api/call/{id}` da 404 siempre: no se sabe cómo acabó,
        y ante la duda no se vuelve a llamar."""
        lanzadas = _centralita(mock_requests, [None])
        cuerpo = _cuerpo()
        main._lanzar_llamada(cuerpo)
        main._insistir("c1", cuerpo, "r")
        assert len(lanzadas) == 1

    def test_si_nunca_deja_de_sonar_no_insiste(self, mock_requests, monkeypatch):
        """Un sondeo que no ve el final se rinde: 'otra', no 'no_cogida'."""
        monkeypatch.setattr(main, "TELEFONO_TIMBRE_SEG", -60)   # tope ya vencido
        lanzadas = _centralita(mock_requests, [("DIALING", "")])
        cuerpo = _cuerpo()
        main._lanzar_llamada(cuerpo)
        main._insistir("c1", cuerpo, "r")
        assert len(lanzadas) == 1

    def test_con_el_buzon_apagado_insiste_pero_no_deja_mensaje(self, mock_requests,
                                                                monkeypatch):
        monkeypatch.setattr(main, "TELEFONO_BUZON", False)
        lanzadas = _centralita(mock_requests, [NO_COGIDA, NO_COGIDA])
        cuerpo = _cuerpo()
        main._lanzar_llamada(cuerpo)
        main._insistir("c1", cuerpo, "r")
        assert len(lanzadas) == 2

    def test_con_un_solo_intento_va_derecho_al_buzon(self, mock_requests, monkeypatch):
        monkeypatch.setattr(main, "TELEFONO_INTENTOS", 1)
        lanzadas = _centralita(mock_requests, [NO_COGIDA, COGIDA])
        cuerpo = _cuerpo()
        main._lanzar_llamada(cuerpo)
        main._insistir("c1", cuerpo, "r")
        assert [l["mode"] for l in lanzadas] == ["conversation", "announce"]
        assert "Te he llamado una vez" in lanzadas[1]["message"]


class TestTextoDelBuzon:
    def test_no_repite_el_saludo(self):
        texto = main._texto_buzon("Mikel, soy Jarvis. El CI está roto.")
        assert texto.count("soy Jarvis") == 1
        assert "El CI está roto." in texto

    def test_sin_saludo_tambien_vale(self):
        assert "¿Arreglo los hallazgos?" in main._texto_buzon("¿Arreglo los hallazgos?")

    def test_cabe_en_lo_que_acepta_claude_phone(self):
        assert len(main._texto_buzon("x" * 5000)) <= 1000


class TestEnSegundoPlano:
    def test_un_fallo_insistiendo_no_se_propaga(self, monkeypatch):
        """El aviso al móvil ya salió y la primera llamada ya sonó: lo de después es
        refuerzo, y un fallo en él se registra y ya."""
        def _revienta(*a):
            raise RuntimeError("boom")

        hilos = []

        class _HiloEnLinea:
            def __init__(self, target, **kw):
                self._target = target
                hilos.append(kw.get("name"))

            def start(self):
                self._target()

        monkeypatch.setattr(main, "_insistir", _revienta)
        monkeypatch.setattr(main.threading, "Thread", _HiloEnLinea)
        main._insistir_en_segundo_plano("c1", _cuerpo(), "r")
        assert hilos == ["insistir-llamada"]


# ── Contestar no es coger (parche 12 de claude-phone) ────────────────────────────────
#
# Con el parche 12, `GET /api/call/{id}` trae `answeredBy` (siempre, aunque sea null: es
# la marca de contrato) y `userTurns`. Los tests de arriba se quedan como están: son los
# de un claude-phone sin el parche, que tiene que decidir exactamente igual que antes.

def _centralita12(mock_requests, finales):
    """Como `_centralita`, pero con la forma del parche 12.

    `finales` es una lista, por llamada, de lo que devuelve cada sondeo: un dict de
    `data` o una lista de dicts para los sondeos sucesivos de esa misma llamada (se
    repite el último cuando se acaban).
    """
    lanzadas, vistas = [], {}

    def _post(url, **kw):
        lanzadas.append(kw["json"])
        return FakeResponse({"success": True, "callId": f"c{len(lanzadas)}"})

    def _get(url, **kw):
        n = int(url.rsplit("/c", 1)[1])
        pasos = finales[n - 1]
        pasos = pasos if isinstance(pasos, list) else [pasos]
        i = vistas.get(n, 0)
        vistas[n] = i + 1
        data = {"answeredBy": None, "userTurns": 0, **pasos[min(i, len(pasos) - 1)]}
        return FakeResponse({"success": True, "data": data})

    mock_requests.add("POST", CENTRALITA, _post)
    mock_requests.add("GET", "/api/call/", _get)
    return lanzadas


BUZON_CON_RECADO = {"state": "COMPLETED", "reason": "voicemail_message",
                    "answeredBy": "voicemail"}
BUZON_SIN_RECADO = {"state": "FAILED", "reason": "voicemail", "answeredBy": "voicemail"}
NADIE_HABLA      = {"state": "COMPLETED", "reason": "no_speech", "answeredBy": "unknown"}
COGIDA12         = {"state": "COMPLETED", "reason": "conversation_complete",
                    "answeredBy": "person", "userTurns": 3}
ANUNCIO_GRABADO  = {"state": "COMPLETED", "reason": "announce_complete",
                    "answeredBy": "voicemail"}


def _serie(cuerpo=None):
    cuerpo = cuerpo or _cuerpo()
    main._lanzar_llamada(cuerpo)
    main._insistir("c1", cuerpo, "vigilancia:la web")
    return cuerpo


class TestContestarNoEsCoger:
    def test_si_descuelga_el_buzon_el_recado_se_deja_ahi_y_no_insiste(self, mock_requests):
        """El 27/09: el buzón descolgó a los 7,5 s. Con el parche 12 el recado se deja en
        esa misma llamada, y volver a llamar solo añadiría llamadas perdidas."""
        lanzadas = _centralita12(mock_requests, [BUZON_CON_RECADO])
        _serie()
        assert len(lanzadas) == 1
        assert main._como_acabo("c1") == "buzon"

    def test_buzon_sin_recado_sigue_la_serie(self, mock_requests):
        lanzadas = _centralita12(mock_requests, [BUZON_SIN_RECADO, COGIDA12])
        _serie()
        assert len(lanzadas) == 2
        assert all(l["mode"] == "conversation" for l in lanzadas)

    def test_si_nadie_habla_cuenta_como_no_cogida(self, mock_requests):
        """Segunda línea de defensa: descolgaron (buzón o lo que sea) y en dos turnos no
        dijo nada nadie. Dos veces así, y la tercera es el buzón."""
        lanzadas = _centralita12(mock_requests, [NADIE_HABLA, NADIE_HABLA, ANUNCIO_GRABADO])
        _serie()
        assert [l["mode"] for l in lanzadas] == ["conversation", "conversation", "announce"]

    def test_alguien_que_habla_es_cogida_en_cuanto_se_ve(self, mock_requests):
        vistas = []

        def _get(url, **kw):
            vistas.append(url)
            return FakeResponse({"data": {"state": "CONVERSING", "answeredBy": "person",
                                          "userTurns": 1}})

        mock_requests.add("GET", "/api/call/", _get)
        assert main._como_acabo("c1") == "cogida"
        assert len(vistas) == 1

    def test_no_speech_con_un_turno_es_cogida(self, mock_requests):
        """Si alguien habló en algún momento, lo cogió una persona."""
        _centralita12(mock_requests, [{**NADIE_HABLA, "userTurns": 1}])
        assert main._como_acabo("c1") == "cogida"

    def test_una_persona_que_descuelga_y_no_habla_es_cogida(self, mock_requests):
        """Descolgaste tú (el Contact trae tu nombre) y no dijiste nada que el oído
        pillara: hablaste encima del primer mensaje o fue un «sí» muy bajo. Eso es
        haberla cogido; no_speech solo cuenta como no cogida si el Contact no dice que
        fuera una persona. Sin esto, dos llamadas más a quien ya había cogido."""
        lanzadas = _centralita12(mock_requests, [{**NADIE_HABLA, "answeredBy": "person"},
                                                 COGIDA12, ANUNCIO_GRABADO])
        _serie()
        assert len(lanzadas) == 1
        assert main._como_acabo("c1") == "cogida"

    @pytest.mark.parametrize("quien", ["voicemail", "unknown"])
    def test_no_speech_sin_persona_sigue_siendo_no_cogida(self, mock_requests, quien):
        """El respaldo de no_speech queda para cuando el Contact no dice que fuera una
        persona: el buzón (con la detección apagada) o un Contact que no se entiende."""
        _centralita12(mock_requests, [{**NADIE_HABLA, "answeredBy": quien}])
        assert main._como_acabo("c1") == "no_cogida"

    def test_colgar_tu_sin_hablar_es_cogida(self, mock_requests):
        """Cogerla y colgar sin decir nada es haberla cogido: no se vuelve a llamar."""
        _centralita12(mock_requests, [{"state": "COMPLETED", "reason": "remote_hangup",
                                       "answeredBy": "person"}])
        assert main._como_acabo("c1") == "cogida"

    def test_descolgada_espera_al_final_aunque_pase_el_timbre(self, mock_requests,
                                                              monkeypatch):
        """Con el parche 12 descolgada ya no es cogida: se espera a ver cómo acaba, y eso
        puede tardar más que el timbre + 60 s de antes (una llamada muda se cuelga a los
        70–90 s)."""
        reloj = [0.0]
        monkeypatch.setattr(main, "_reloj", lambda: reloj[0])
        monkeypatch.setattr(main, "_dormir", lambda s: reloj.__setitem__(0, reloj[0] + s))
        monkeypatch.setattr(main, "TELEFONO_TIMBRE_SEG", 14)
        sonando = [{"state": "DIALING"}] * 2
        muda    = [{"state": "CONVERSING", "answeredBy": "unknown"}] * 25   # 125 s
        _centralita12(mock_requests, [sonando + muda + [NADIE_HABLA]])
        assert main._como_acabo("c1") == "no_cogida"
        assert reloj[0] > main.TELEFONO_TIMBRE_SEG + 60

    def test_descolgada_para_siempre_se_rinde(self, mock_requests, monkeypatch):
        reloj = [0.0]
        monkeypatch.setattr(main, "_reloj", lambda: reloj[0])
        monkeypatch.setattr(main, "_dormir", lambda s: reloj.__setitem__(0, reloj[0] + s))
        _centralita12(mock_requests, [{"state": "CONVERSING", "answeredBy": "unknown"}])
        assert main._como_acabo("c1") == "otra"
        assert reloj[0] <= main.TELEFONO_DESCOLGADA_MAX_SEG + main.TELEFONO_SONDEO_SEG * 2

    def test_sin_voz_no_insiste_y_lo_deja_escrito(self, mock_requests, caplog):
        """Descolgada, pero Jarvis no pudo decir nada (el 27/09, el TTS sin DNS). Una voz
        rota no se arregla llamando otra vez: cada reintento sería otra llamada muda."""
        lanzadas = _centralita12(mock_requests, [{"state": "FAILED", "reason": "unplayed",
                                                  "answeredBy": "voicemail"}])
        with caplog.at_level("ERROR"):
            _serie()
        assert len(lanzadas) == 1
        errores = [r for r in caplog.records if r.levelname == "ERROR"]
        assert errores and "no ha podido hablar" in errores[0].getMessage()

    def test_un_error_de_conversacion_sin_turnos_es_sin_voz(self, mock_requests):
        _centralita12(mock_requests, [{"state": "COMPLETED", "reason": "conversation_error",
                                       "answeredBy": "person"}])
        assert main._como_acabo("c1") == "sin_voz"

    def test_la_serie_deja_escrito_por_que_acaba(self, mock_requests, caplog):
        """El 27/09 la serie se cortó sin una sola línea en el registro."""
        _centralita12(mock_requests, [BUZON_CON_RECADO])
        with caplog.at_level("INFO"):
            _serie()
        assert any("contestó el buzón" in r.getMessage() for r in caplog.records)


class TestSinElParche12:
    def test_descolgada_es_cogida_como_siempre(self, mock_requests):
        mock_requests.add("GET", "/api/call/",
                          FakeResponse({"data": {"state": "PLAYING", "reason": None}}))
        assert main._como_acabo("c1") == "cogida"

    def test_un_fallo_tras_descolgar_no_insiste_pero_queda_en_error(self, mock_requests,
                                                                     caplog):
        """Sin el 12, el FAILED/error de una llamada descolgada decide como antes (no
        insiste); lo único nuevo es que el registro dice qué pasó."""
        lanzadas = []

        def _post(url, **kw):
            lanzadas.append(kw["json"])
            return FakeResponse({"callId": f"c{len(lanzadas)}"})

        mock_requests.add("POST", CENTRALITA, _post)
        mock_requests.add("GET", "/api/call/", FakeResponse({"data": {
            "state": "FAILED", "reason": "error", "answeredAt": "2026-09-27T05:01:47Z"}}))
        with caplog.at_level("ERROR"):
            _serie()
        assert len(lanzadas) == 1
        assert any(r.levelname == "ERROR" and "no ha podido hablar" in r.getMessage()
                   for r in caplog.records)


class TestLoQueSePide:
    def _lanzada(self, mock_requests, monkeypatch, texto="Mikel, soy Jarvis. La web no va."):
        monkeypatch.setattr(main, "_insistir_en_segundo_plano", lambda *a: None)
        lanzadas = _centralita(mock_requests, [COGIDA])
        assert main._llamar_telefono(texto, rid="r-1") is True
        return lanzadas[0]

    def test_pide_detectar_el_buzon_y_lleva_el_recado(self, mock_requests, monkeypatch):
        cuerpo = self._lanzada(mock_requests, monkeypatch)
        assert cuerpo["detectVoicemail"] is True
        assert cuerpo["voicemailMessage"] == main._recado("Mikel, soy Jarvis. La web no va.")
        assert cuerpo["voicemailMessage"].count("soy Jarvis") == 1
        assert "La web no va." in cuerpo["voicemailMessage"]
        assert cuerpo["voicemailDelaySeconds"] == main.TELEFONO_BUZON_ESPERA_SEG

    def test_el_recado_no_cuenta_las_veces(self):
        """El segundo intento relanza el mismo cuerpo: el recado vale igual en los dos."""
        assert "veces" not in main._recado("Mikel, soy Jarvis. Algo.")

    def test_con_el_buzon_apagado_no_hay_recado(self, mock_requests, monkeypatch):
        monkeypatch.setattr(main, "TELEFONO_BUZON", False)
        cuerpo = self._lanzada(mock_requests, monkeypatch)
        assert cuerpo["detectVoicemail"] is True
        assert "voicemailMessage" not in cuerpo and "voicemailDelaySeconds" not in cuerpo

    def test_con_la_deteccion_apagada_no_se_pide_nada(self, mock_requests, monkeypatch):
        monkeypatch.setattr(main, "TELEFONO_DETECTAR_BUZON", False)
        cuerpo = self._lanzada(mock_requests, monkeypatch)
        assert not any(k.startswith(("detect", "voicemail")) for k in cuerpo)

    def test_la_llamada_del_buzon_no_detecta_el_buzon(self, mock_requests, monkeypatch):
        """La del final busca justo al buzón: pedir que lo detecte la dejaría muda."""
        monkeypatch.setattr(main, "_insistir_en_segundo_plano", lambda *a: None)
        lanzadas = _centralita(mock_requests, [NO_COGIDA, NO_COGIDA, COGIDA])
        main._llamar_telefono("Mikel, soy Jarvis. La web no va.", rid="r")
        main._insistir("c1", lanzadas[0], "r")
        assert len(lanzadas) == 3
        assert lanzadas[1]["detectVoicemail"] is True
        assert lanzadas[2]["mode"] == "announce"
        assert "detectVoicemail" not in lanzadas[2]
        assert "voicemailMessage" not in lanzadas[2]

    def test_el_recado_cabe_en_lo_que_acepta_claude_phone(self):
        assert len(main._recado("x" * 5000)) <= 1000
