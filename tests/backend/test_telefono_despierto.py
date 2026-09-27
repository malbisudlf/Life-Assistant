"""Tests de «solo cuando estás despierto»: cuándo puede sonar el teléfono.

El 2026-09-27 la web cayó de madrugada, el vigilante aplazó la llamada por la franja
nocturna y a las 07:00:32 —acabada la franja— llamó con Mikel dormido. «No es de noche» se
tomaba por «estás despierto». Lo que se comprueba aquí es la regla nueva: la franja fija
como suelo, la señal de despertar que ya usa el resumen como llave, la hora de respaldo
cuando no llega ninguna señal y el corte de la noche por tu hora habitual de dormirte.
Y que todo eso vive en `_llamar`, la puerta, para que ninguna llamada se lo salte.
"""
from datetime import datetime, timedelta

import pytest

import main
from conftest import FakeResponse

CENTRALITA = "/api/outbound-call"


def _a(hora, minuto=0, dia=27):
    return datetime(2026, 9, dia, hora, minuto, tzinfo=main.LOCAL_TZ)


@pytest.fixture
def reloj(monkeypatch):
    """Fija `_ahora_local` (lo usan `_hora_habitual_dormir` y la puerta) y devuelve un
    ajustador para moverlo dentro del test."""
    ahora = [_a(12)]
    monkeypatch.setattr(main, "_ahora_local", lambda: ahora[0])

    def _poner(hora, minuto=0, dia=27):
        ahora[0] = _a(hora, minuto, dia)
        return ahora[0]
    return _poner


def _habitual(mock_requests, hhmm, noches=7):
    """Tu hora habitual de dormirte, como la guarda la ingesta de salud."""
    mock_requests.add("GET", "metric_name=eq.sleep_analysis",
                      FakeResponse([{"extra": {"sleep_start": hhmm}}] * noches))


def _puede(ahora):
    return main._telefono_puede_sonar(ahora)[0]


class TestCuandoPuedeSonar:
    def test_de_madrugada_ni_con_senal(self, mock_requests, reloj):
        """La franja fija es el suelo: ni con señal suena antes de las 07:00."""
        reloj(3)
        main._despierto = {"dia": "2026-09-27", "desde": _a(2, 50), "fuente": "x"}
        puede, motivo = main._telefono_puede_sonar(_a(3))
        assert puede is False and motivo == "franja nocturna"

    def test_a_las_siete_sin_senal_no_suena(self, mock_requests, reloj):
        """El caso del 27/09: acabada la franja, sin señal de despertar."""
        puede, motivo = main._telefono_puede_sonar(reloj(7, 5))
        assert puede is False
        assert "no consta que estés despierto" in motivo and "10:00" in motivo

    def test_con_la_senal_suena(self, mock_requests, reloj):
        main._anotar_despierto(reloj(7, 2), "despertar")
        puede, motivo = main._telefono_puede_sonar(reloj(7, 5))
        assert puede is True
        assert "07:02" in motivo and "despertar" in motivo

    def test_la_senal_de_ayer_no_vale(self, mock_requests, reloj):
        main._anotar_despierto(reloj(8, 0, dia=26), "despertar")
        assert _puede(reloj(8, 0, dia=27)) is False

    def test_una_senal_de_madrugada_no_cuenta(self, mock_requests, reloj):
        """Un desenchufe camino del baño no abre el teléfono."""
        main._anotar_despierto(reloj(4, 10), "despertar")
        assert not mock_requests.called("POST", "despertares")
        assert _puede(reloj(7, 30)) is False

    def test_una_senal_temprana_espera_al_suelo(self, mock_requests, reloj):
        main._anotar_despierto(reloj(6, 10), "despertar")
        assert _puede(reloj(6, 30)) is False
        assert _puede(reloj(7, 0)) is True

    def test_sin_senal_a_la_hora_de_respaldo_suena(self, mock_requests, reloj):
        assert _puede(reloj(9, 59)) is False
        assert _puede(reloj(10, 0)) is True

    def test_la_noche_corta_a_tu_hora_de_dormir(self, mock_requests, reloj):
        """Te duermes a las 23:40: desde las 23:10 ya no suena."""
        _habitual(mock_requests, "23:40")
        assert _puede(reloj(23, 5)) is True
        puede, motivo = main._telefono_puede_sonar(reloj(23, 15))
        assert puede is False and "23:10" in motivo

    def test_el_corte_nunca_antes_de_las_diez(self, mock_requests, reloj):
        _habitual(mock_requests, "22:00")
        assert _puede(reloj(21, 59)) is True
        puede, motivo = main._telefono_puede_sonar(reloj(22, 0))
        assert puede is False and "22:00" in motivo

    def test_si_te_duermes_pasada_la_medianoche_no_hay_corte_propio(self, mock_requests, reloj):
        """00:40 menos 30 min es 00:10: pasada la medianoche manda la franja, como antes."""
        _habitual(mock_requests, "00:40")
        assert _puede(reloj(23, 55)) is True

    def test_sin_base_tampoco(self, mock_requests, reloj):
        _habitual(mock_requests, "22:00", noches=3)
        assert _puede(reloj(23, 55)) is True

    def test_la_hora_de_dormir_se_consulta_una_vez_al_dia(self, mock_requests, reloj):
        _habitual(mock_requests, "23:40")
        _puede(reloj(22, 5))
        _puede(reloj(22, 30))
        _puede(reloj(23, 30))
        assert len(mock_requests.called("GET", "sleep_analysis")) == 1

    def test_a_mediodia_no_se_pregunta_nada(self, mock_requests, reloj):
        """El caso de casi todas las llamadas: de día no cuesta ni una consulta."""
        assert _puede(reloj(12)) is True
        assert mock_requests.calls == []


class TestLaSenal:
    def test_el_atajo_abre_el_telefono_al_momento_aunque_el_correo_espere(
            self, client, mock_requests, reloj, monkeypatch):
        """El retraso de /despertar es del correo (esperar a que sincronice el sueño), no
        del teléfono: la llamada no tiene por qué esperar esos cinco minutos."""
        monkeypatch.setattr(main, "DESPERTAR_RETRASO_SEGUNDOS", 300)
        monkeypatch.setattr(main, "_despertar_tras_retraso", lambda *a: None)
        reloj(7, 20)
        r = client.post("/despertar?fuente=cargador", headers={"X-Auth-Token": "brief-token"})
        assert r.status_code == 200 and r.json()["enviado"] is False
        assert _puede(_a(7, 21)) is True
        fila = mock_requests.called("POST", "/rest/v1/despertares")[0][2]["json"]
        assert fila["fecha"] == "2026-09-27" and fila["fuente"] == "cargador"
        cuando = datetime.fromisoformat(fila["primera_senal_at"])
        assert cuando == _a(7, 20)
        # En UTC, como toda fecha que sale del backend.
        assert cuando.utcoffset() == timedelta(0)

    @pytest.mark.parametrize("quien", ["alarma", "jarvis"])
    def test_la_alarma_confirmada_y_jarvis_tambien(self, mock_requests, reloj, quien):
        mock_requests.add("GET", "brief_ajustes", FakeResponse([{"activo": False}]))
        reloj(7, 20)
        if quien == "jarvis":
            main._j_estoy_despierto()
        else:
            main._senal_despertar_segura("alarma")    # lo que llama la alarma confirmada
        puede, motivo = main._telefono_puede_sonar(_a(7, 25))
        assert puede is True and quien in motivo

    def test_solo_cuenta_la_primera_del_dia(self, mock_requests, reloj):
        main._anotar_despierto(reloj(7, 2), "despertar")
        main._anotar_despierto(reloj(7, 40), "despertar")
        assert len(mock_requests.called("POST", "despertares")) == 1
        assert "07:02" in main._telefono_puede_sonar(reloj(8))[1]

    def test_con_el_resumen_pausado_cuenta_igual(self, mock_requests, reloj):
        """El resumen consume la señal; el teléfono no depende de él."""
        mock_requests.add("GET", "brief_ajustes",
                          FakeResponse([{"activo": True, "pausado_hasta": "2026-10-05"}]))
        reloj(7, 20)
        r = main._senal_despertar("despertar")
        assert r["enviado"] is False and "pausado" in r["motivo"]
        assert _puede(_a(7, 25)) is True

    def test_tras_un_reinicio_se_lee_la_fila(self, mock_requests, reloj):
        """El 27/09 caja se reinició a las 03:30: la memoria sola no habría bastado."""
        mock_requests.add("GET", "/rest/v1/despertares", FakeResponse([{
            "primera_senal_at": _a(7, 10).astimezone(main.timezone.utc).isoformat(),
            "fuente": "cargador"}]))
        puede, motivo = main._telefono_puede_sonar(reloj(7, 30))
        assert puede is True and "07:10" in motivo and "cargador" in motivo
        _puede(reloj(7, 40))
        assert len(mock_requests.called("GET", "despertares")) == 1

    def test_sin_fila_se_pregunta_una_vez_al_dia(self, mock_requests, reloj):
        """Las señales nuevas entran por memoria: volver a preguntar no traería nada."""
        _puede(reloj(7, 30))
        _puede(reloj(7, 35))
        _puede(reloj(8, 40))
        assert len(mock_requests.called("GET", "despertares")) == 1
        # Y una señal posterior se ve sin preguntar más.
        main._anotar_despierto(reloj(8, 45), "jarvis")
        assert _puede(reloj(8, 50)) is True
        assert len(mock_requests.called("GET", "despertares")) == 1

    def test_si_supabase_falla_no_se_da_el_dia_por_mirado(self, mock_requests, reloj):
        """«No he podido mirar» es dormido, pero el siguiente sondeo vuelve a preguntar."""
        mock_requests.add("GET", "/rest/v1/despertares", FakeResponse({}, 500))
        assert _puede(reloj(7, 30)) is False
        assert _puede(reloj(7, 35)) is False
        assert len(mock_requests.called("GET", "despertares")) == 2

    def test_sin_la_migracion_vale_la_memoria(self, mock_requests, reloj):
        mock_requests.add("POST", "/rest/v1/despertares", FakeResponse({}, 404))
        mock_requests.add("GET", "/rest/v1/despertares", FakeResponse({}, 404))
        main._anotar_despierto(reloj(7, 0), "despertar")
        assert _puede(reloj(7, 5)) is True


class TestLaPuerta:
    @pytest.fixture(autouse=True)
    def _centralita(self, monkeypatch):
        monkeypatch.setattr(main, "TELEFONO_URL", "http://centralita.test:3010")
        monkeypatch.setattr(main, "TELEFONO_EXTENSION", "100")

    def test_dormido_no_sale_nada(self, mock_requests, reloj):
        reloj(7, 30)
        assert main._llamar("Mikel, soy Jarvis. Algo.") is False
        assert not mock_requests.called("POST", CENTRALITA)

    def test_despierto_sale(self, mock_requests, reloj):
        main._anotar_despierto(reloj(7, 20), "despertar")
        reloj(7, 30)
        assert main._llamar("Mikel, soy Jarvis. Algo.") is True
        assert mock_requests.called("POST", CENTRALITA)

    def test_aunque_duermas_suena(self, mock_requests, reloj):
        """La excepción con nombre: «Hablarlo» y lo crítico."""
        _habitual(mock_requests, "23:00")
        reloj(23, 30)
        assert main._llamar("Mikel, soy Jarvis. Algo.") is False
        assert not mock_requests.called("POST", CENTRALITA)
        assert main._llamar("Mikel, soy Jarvis. Algo.", aunque_duermas=True) is True
        assert len(mock_requests.called("POST", CENTRALITA)) == 1

    def test_solo_centralita_no_cae_a_twilio(self, mock_requests, reloj, monkeypatch):
        monkeypatch.setattr(main, "LLAMADAS", True)
        monkeypatch.setattr(main, "TWILIO_SID", "AC123")
        monkeypatch.setattr(main, "TWILIO_TOKEN", "twilio-token")
        monkeypatch.setattr(main, "TWILIO_DESDE", "+34600000000")
        monkeypatch.setattr(main, "TWILIO_HASTA", "+34600000001")
        monkeypatch.setattr(main, "BACKEND_URL", "https://backend.test")
        mock_requests.add("POST", CENTRALITA, FakeResponse({}, 503, text="SIP sin registrar"))
        mock_requests.add("POST", "twilio.com", FakeResponse({"sid": "CA1"}, 201))
        reloj(12)
        assert main._llamar("algo", solo_centralita=True) is False
        assert not mock_requests.called("POST", "twilio.com")
        assert main._llamar("algo") is True
        assert mock_requests.called("POST", "twilio.com")
