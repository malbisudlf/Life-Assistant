"""Tests de los recordatorios: lo único que hace que Jarvis hable sin que le hablen.

Lo que se comprueba es que un aviso no se pierda ni se duplique, que es donde fallan
estas cosas: la reserva tiene que ser atómica (como el INSERT del resumen diario) y un
fallo de SMTP no puede consumir el recordatorio.
"""
from datetime import datetime, timedelta

import pytest

import main
from conftest import FakeResponse

CABECERA = {"X-Auth-Token": "ha-poll-token"}


@pytest.fixture
def correos(monkeypatch):
    enviados = []
    monkeypatch.setattr(main, "enviar_correo", lambda asunto, cuerpo: enviados.append((asunto, cuerpo)))
    return enviados


def _manana(hora="09:00"):
    dia = (datetime.now(main.LOCAL_TZ) + timedelta(days=1)).date().isoformat()
    return dia, hora


class TestApuntarRecordatorio:
    def test_guarda_uno_para_manana(self, mock_requests):
        mock_requests.add("POST", "jarvis_recordatorios", FakeResponse([{"id": "r-1"}]))
        dia, hora = _manana()
        r = main._j_recordarme("llamar al dentista", dia, hora)
        assert r["ok"] is True
        guardado = mock_requests.called("POST", "jarvis_recordatorios")[0][2]["json"]
        assert guardado["texto"] == "llamar al dentista"
        # Se guarda en UTC: la hora local es de quien la dice, no de la base de datos.
        assert guardado["cuando"].endswith("+00:00")

    def test_rechaza_una_hora_que_ya_paso(self, mock_requests):
        r = main._j_recordarme("tarde", "2020-01-01", "09:00")
        assert r["ok"] is False
        assert not mock_requests.called("POST", "jarvis_recordatorios")

    def test_rechaza_una_fecha_que_no_existe(self, mock_requests):
        assert main._j_recordarme("algo", "2030-02-30", "09:00")["ok"] is False

    def test_rechaza_formatos_raros(self, mock_requests):
        assert main._j_recordarme("algo", "mañana", "por la tarde")["ok"] is False

    def test_exige_saber_de_que_avisar(self, mock_requests):
        dia, hora = _manana()
        assert main._j_recordarme("   ", dia, hora)["ok"] is False

    def test_no_deja_acumular_infinitos(self, mock_requests):
        pendientes = [{"id": f"r-{i}"} for i in range(main.RECORDATORIOS_MAX + 1)]
        mock_requests.add("GET", "jarvis_recordatorios", FakeResponse(pendientes))
        dia, hora = _manana()
        assert main._j_recordarme("uno más", dia, hora)["ok"] is False

    def test_cancelar_exige_un_id_de_verdad(self, mock_requests):
        assert main._j_cancelar_recordatorio("el del dentista")["ok"] is False
        assert not mock_requests.called("DELETE", "jarvis_recordatorios")


class TestDespacho:
    def _vencido(self, mock_requests, texto="llamar al dentista"):
        mock_requests.add("GET", "jarvis_recordatorios", FakeResponse([{
            "id": "11111111-2222-3333-4444-555555555555",
            "cuando": "2026-08-08T09:00:00+00:00",
            "texto": texto,
        }]))

    def test_manda_el_correo_y_lo_marca(self, mock_requests, correos):
        self._vencido(mock_requests)
        mock_requests.add("PATCH", "jarvis_recordatorios", FakeResponse([{"id": "x"}]))
        assert main._despachar_recordatorios() == {"recordatorios": 1}
        assert "llamar al dentista" in correos[0][0]
        assert mock_requests.called("PATCH", "jarvis_recordatorios")[0][2]["json"] == {"enviado": True}

    def test_si_otro_tick_se_lo_llevo_no_se_manda_dos_veces(self, mock_requests, correos):
        """La reserva ES la pregunta: un PATCH condicional que no devuelve fila significa
        que otro se adelantó. Con un GET previo, dos ticks solapados mandan dos correos."""
        self._vencido(mock_requests)
        mock_requests.add("PATCH", "jarvis_recordatorios", FakeResponse([]))
        assert main._despachar_recordatorios() == {"recordatorios": 0}
        assert correos == []

    def test_si_el_correo_falla_se_libera_para_reintentarlo(self, mock_requests, monkeypatch):
        """Un fallo transitorio de SMTP no puede consumir el recordatorio."""
        self._vencido(mock_requests)
        mock_requests.add("PATCH", "jarvis_recordatorios", FakeResponse([{"id": "x"}]))

        def _revienta(asunto, cuerpo):
            raise RuntimeError("SMTP caído")
        monkeypatch.setattr(main, "enviar_correo", _revienta)

        assert main._despachar_recordatorios() == {"recordatorios": 0}
        liberado = mock_requests.called("PATCH", "jarvis_recordatorios")[-1][2]["json"]
        assert liberado == {"enviado": False}

    def test_un_fallo_de_supabase_no_revienta(self, mock_requests, correos):
        """El tick existe sobre todo para el resumen diario: esto no puede tumbarlo."""
        mock_requests.add("GET", "jarvis_recordatorios", FakeResponse([], 500))
        assert main._despachar_recordatorios() == {"recordatorios": 0}


class TestElRelojEsElTickDeHa:
    def test_el_tick_despacha_aunque_no_sea_la_hora_del_resumen(
            self, client, mock_requests, correos, monkeypatch):
        """Antes de la hora tope el tick no manda el resumen, pero sí los recordatorios:
        es el único reloj que hay, porque Fly escala a cero."""
        monkeypatch.setattr(main, "_ahora_local",
                            lambda: datetime(2026, 8, 8, 7, 0, tzinfo=main.LOCAL_TZ))
        mock_requests.add("GET", "jarvis_recordatorios", FakeResponse([{
            "id": "11111111-2222-3333-4444-555555555555",
            "cuando": "2026-08-08T05:00:00+00:00",
            "texto": "tomar la pastilla",
        }]))
        mock_requests.add("PATCH", "jarvis_recordatorios", FakeResponse([{"id": "x"}]))

        r = client.post("/ha/brief-tick", headers=CABECERA)
        assert r.status_code == 200
        assert r.json() == {"enviado": False, "motivo": "aún no es la hora tope",
                            "recordatorios": 1}
        assert len(correos) == 1

    def test_sigue_haciendo_falta_el_token(self, client):
        assert client.post("/ha/brief-tick").status_code == 403


class TestAvisoDeReloj:
    """El dato de una noche sin medir no se recupera: el aviso vale antes de dormir o
    no vale. Y no puede regañar por algo que no ha pasado — de ahí que un día sin datos
    de ninguna fuente no dispare nada.
    """

    NOCHE = datetime(2026, 8, 8, 22, 0, tzinfo=main.LOCAL_TZ)

    def _salud(self, mock_requests, filas):
        mock_requests.add("GET", "/rest/v1/health_metrics", FakeResponse(filas))

    def _fila(self, nombre, valor, dias, hoy=None):
        fecha = (hoy or self.NOCHE.date()) - timedelta(days=dias)
        return {"metric_date": fecha.isoformat(), "metric_name": nombre,
                "value": valor, "extra": {}}

    @pytest.fixture(autouse=True)
    def _de_noche(self, monkeypatch):
        monkeypatch.setattr(main, "_ahora_local", lambda: self.NOCHE)

    def test_avisa_si_hoy_no_hay_rastro_del_reloj(self, mock_requests):
        self._salud(mock_requests, [self._fila("step_count", 9000, 0)])
        mock_requests.add("POST", "jarvis_recordatorios", FakeResponse([], 201))
        assert main._avisar_reloj_si_toca() == {"aviso_reloj": True}
        apuntado = mock_requests.called("POST", "jarvis_recordatorios")[0][2]["json"]
        assert "Hoy no hay ni un dato del reloj" in apuntado["texto"]
        assert "cargador" in apuntado["texto"]

    def test_no_avisa_si_lo_llevas_puesto(self, mock_requests):
        self._salud(mock_requests, [
            self._fila("heart_rate", 70, 0), self._fila("step_count", 9000, 0),
            self._fila("sleep_analysis", 7.2, 1), self._fila("heart_rate", 70, 1),
        ])
        assert main._avisar_reloj_si_toca() == {}
        assert not mock_requests.called("POST", "jarvis_recordatorios")

    def test_un_dia_sin_datos_de_nada_no_dispara_el_aviso(self, mock_requests):
        """No llegó nada: puede ser el reloj o la sincronización, y no se sabe cuál."""
        self._salud(mock_requests, [])
        assert main._avisar_reloj_si_toca() == {}
        assert not mock_requests.called("POST", "jarvis_recordatorios")

    def test_avisa_por_la_racha_de_noches_aunque_hoy_lo_lleves_de_dia(self, mock_requests):
        self._salud(mock_requests, [
            self._fila("heart_rate", 70, 0),                       # hoy: puesto de día
            *[self._fila("step_count", 9000, i) for i in range(4)],  # datos todos los días
            self._fila("sleep_analysis", 7.2, 3),                  # la última noche medida
        ])
        mock_requests.add("POST", "jarvis_recordatorios", FakeResponse([], 201))
        assert main._avisar_reloj_si_toca() == {"aviso_reloj": True}
        texto = mock_requests.called("POST", "jarvis_recordatorios")[0][2]["json"]["texto"]
        assert "2 noches sin medir" in texto

    def test_antes_de_la_hora_no_hace_nada_ni_consulta(self, mock_requests, monkeypatch):
        """El tick pasa cada 5 min: fuera de la ventana tiene que salir sin tocar nada."""
        monkeypatch.setattr(main, "_ahora_local",
                            lambda: datetime(2026, 8, 8, 12, 0, tzinfo=main.LOCAL_TZ))
        assert main._avisar_reloj_si_toca() == {}
        assert not mock_requests.called("GET", "/rest/v1/health_metrics")

    def test_el_id_es_el_del_dia_para_que_el_segundo_choque(self, mock_requests):
        """La idempotencia es el 409 contra la clave primaria, como en brief_envios: dos
        ticks solapados generan el MISMO id y solo uno entra."""
        self._salud(mock_requests, [self._fila("step_count", 9000, 0)])
        mock_requests.add("POST", "jarvis_recordatorios", FakeResponse([], 201))
        main._avisar_reloj_si_toca()
        primero = mock_requests.called("POST", "jarvis_recordatorios")[0][2]["json"]["id"]
        assert primero == main._uuid_aviso_reloj("2026-08-08")
        assert primero != main._uuid_aviso_reloj("2026-08-09")

    def test_un_409_no_es_un_error(self, mock_requests):
        self._salud(mock_requests, [self._fila("step_count", 9000, 0)])
        mock_requests.add("POST", "jarvis_recordatorios", FakeResponse(None, 409, "duplicate key"))
        assert main._avisar_reloj_si_toca() == {}

    def test_dos_veces_en_el_mismo_dia_no_repiten_la_consulta(self, mock_requests):
        self._salud(mock_requests, [self._fila("step_count", 9000, 0)])
        mock_requests.add("POST", "jarvis_recordatorios", FakeResponse([], 201))
        main._avisar_reloj_si_toca()
        main._avisar_reloj_si_toca()
        assert len(mock_requests.called("GET", "/rest/v1/health_metrics")) == 1

    def test_un_fallo_leyendo_la_salud_no_tumba_el_tick(self, mock_requests):
        mock_requests.add("GET", "/rest/v1/health_metrics", FakeResponse(None, 500, "boom"))
        assert main._avisar_reloj_si_toca() == {}
        assert not mock_requests.called("POST", "jarvis_recordatorios")

    def test_apagado_por_env_no_hace_nada(self, mock_requests, monkeypatch):
        monkeypatch.setattr(main, "RELOJ_AVISO", False)
        assert main._avisar_reloj_si_toca() == {}
        assert not mock_requests.called("GET", "/rest/v1/health_metrics")
