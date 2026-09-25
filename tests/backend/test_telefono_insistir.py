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
