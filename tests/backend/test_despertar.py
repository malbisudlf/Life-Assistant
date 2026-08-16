"""Tests del disparo del resumen diario: cuándo sale el correo y cuántas veces.

Antes salía a hora fija desde un cron de GitHub Actions, que se retrasa cuando su cola
va cargada. Ahora sale al despertarse — y como hay VARIAS fuentes que pueden avisar de
eso a la vez (el móvil al desenchufarse, la llegada del sueño del Watch, el reloj de
respaldo de HA y el propio workflow), lo que más se prueba aquí es que dos disparadores
simultáneos no manden dos correos.
"""
from datetime import datetime

import main
from conftest import FakeResponse
from test_brief import _SMTPFalso, configurar_smtp, montar_fuentes


def _a_las(hora, minuto=0):
    """Hoy a una hora concreta, en la zona del usuario."""
    hoy = datetime.now(main.LOCAL_TZ).date()
    return datetime(hoy.year, hoy.month, hoy.day, hora, minuto, tzinfo=main.LOCAL_TZ)


def reloj(monkeypatch, hora, minuto=0):
    monkeypatch.setattr(main, "_ahora_local", lambda: _a_las(hora, minuto))


def tabla_envios(mock_requests, ya_enviado=False):
    """Simula brief_envios: el primer INSERT del día pasa, los siguientes dan 409.

    Es exactamente lo que hace la clave primaria de la tabla real, y es de lo que
    depende toda la idempotencia: sin ese 409, dos disparadores que coincidan mandan
    dos correos.
    """
    estado = {"reservado": ya_enviado}

    def _insert(url, **kwargs):
        if estado["reservado"]:
            return FakeResponse(None, 409, "duplicate key value violates unique constraint")
        estado["reservado"] = True
        return FakeResponse([], 201)

    def _delete(url, **kwargs):
        estado["reservado"] = False
        return FakeResponse([], 204)

    mock_requests.add("POST", "/rest/v1/brief_envios", _insert)
    mock_requests.add("DELETE", "/rest/v1/brief_envios", _delete)
    return estado


def preparar(mock_requests, monkeypatch, ya_enviado=False):
    montar_fuentes(mock_requests)
    configurar_smtp(monkeypatch)
    return tabla_envios(mock_requests, ya_enviado)


class TestAuthDespertar:
    def test_sin_token_no_pasa(self, client):
        assert client.post("/despertar").status_code == 403

    def test_con_token_equivocado_no_pasa(self, client):
        assert client.post("/despertar?token=noes").status_code == 403

    def test_no_acepta_el_jwt_de_usuario(self, client, auth_headers):
        """Lo llama una máquina que arranca sola: un JWT caduca a los 30 días y
        dejaría de funcionar sin que nadie se entere (ya pasó con el agente PC)."""
        assert client.post("/despertar", headers=auth_headers).status_code == 403

    def test_tick_de_ha_va_con_su_propio_token(self, client):
        assert client.post("/ha/brief-tick").status_code == 403
        assert client.post("/ha/brief-tick?token=brief-token").status_code == 403


class TestSenalDeDespertar:
    def test_despertarse_manda_el_correo(self, client, mock_requests, graph_token, monkeypatch):
        preparar(mock_requests, monkeypatch)
        reloj(monkeypatch, 7, 15)

        r = client.post("/despertar?token=brief-token&fuente=cargador")
        assert r.status_code == 200
        assert r.json()["enviado"] is True
        assert len(_SMTPFalso.enviados) == 1

    def test_de_madrugada_no_cuenta(self, client, mock_requests, graph_token, monkeypatch):
        """Desenchufar el móvil a las 04:00 para ir al baño no es despertarse."""
        preparar(mock_requests, monkeypatch)
        reloj(monkeypatch, 4, 0)

        r = client.post("/despertar?token=brief-token")
        assert r.status_code == 200
        assert r.json()["enviado"] is False
        assert _SMTPFalso.enviados == []
        # Y no puede haber reservado el día: si lo hiciera, el despertar de verdad
        # de las 7 se encontraría el día marcado y no mandaría nada.
        assert mock_requests.called("POST", "/rest/v1/brief_envios") == []

    def test_de_media_tarde_tampoco_cuenta(self, client, mock_requests, graph_token, monkeypatch):
        """El día que fallen todas las señales de la mañana, cargar el móvil por la
        tarde no puede mandar el correo del día a las 17:00 llamándolo despertar."""
        preparar(mock_requests, monkeypatch)
        reloj(monkeypatch, 17, 0)

        r = client.post("/despertar?token=brief-token&fuente=cargador")
        assert r.json()["enviado"] is False
        assert _SMTPFalso.enviados == []
        assert mock_requests.called("POST", "/rest/v1/brief_envios") == []

    def test_el_techo_no_afecta_a_la_hora_tope(self, client, mock_requests, graph_token, monkeypatch):
        """La ventana es propiedad de la señal: el respaldo dispara fuera de ella por
        definición y no puede quedarse mudo por su culpa."""
        preparar(mock_requests, monkeypatch)
        reloj(monkeypatch, 12, 30)

        r = client.post("/ha/brief-tick?token=ha-poll-token")
        assert r.json()["enviado"] is True
        assert len(_SMTPFalso.enviados) == 1

    def test_dos_senales_seguidas_mandan_un_solo_correo(self, client, mock_requests, graph_token, monkeypatch):
        """El caso real: el móvil se desenchufa y el Watch sincroniza casi a la vez."""
        preparar(mock_requests, monkeypatch)
        reloj(monkeypatch, 7, 15)

        primera = client.post("/despertar?token=brief-token&fuente=cargador")
        segunda = client.post("/despertar?token=brief-token&fuente=cargador")

        assert primera.json()["enviado"] is True
        assert segunda.json()["enviado"] is False
        assert "ya se envió" in segunda.json()["motivo"]
        assert len(_SMTPFalso.enviados) == 1

    def test_la_etiqueta_de_fuente_se_limpia(self, client, mock_requests, graph_token, monkeypatch):
        """Acaba en una fila de Supabase: no se confía en lo que mande el cliente."""
        preparar(mock_requests, monkeypatch)
        reloj(monkeypatch, 7, 15)

        client.post("/despertar?token=brief-token&fuente=carga'dor;drop")
        enviado = mock_requests.called("POST", "/rest/v1/brief_envios")[0][2]["json"][0]
        assert enviado["fuente"] == "cargadordrop"
        assert enviado["despertar_at"]


class TestHoraTope:
    def test_antes_de_la_hora_tope_no_hace_nada(self, client, mock_requests, graph_token, monkeypatch):
        """El sondeo es constante: antes de la hora tope tiene que ser un no-op barato,
        sin tocar Supabase ni construir el resumen."""
        preparar(mock_requests, monkeypatch)
        reloj(monkeypatch, 8, 30)

        r = client.post("/ha/brief-tick?token=ha-poll-token")
        assert r.json()["enviado"] is False
        assert _SMTPFalso.enviados == []
        assert mock_requests.called("POST", "/rest/v1/brief_envios") == []

    def test_pasada_la_hora_tope_manda_el_correo(self, client, mock_requests, graph_token, monkeypatch):
        """Nadie ha dado señal de despertar: se asume que la señal falló."""
        preparar(mock_requests, monkeypatch)
        reloj(monkeypatch, 10, 0)

        r = client.post("/ha/brief-tick?token=ha-poll-token")
        assert r.json()["enviado"] is True
        assert len(_SMTPFalso.enviados) == 1

    def test_si_ya_te_despertaste_el_tope_no_duplica(self, client, mock_requests, graph_token, monkeypatch):
        preparar(mock_requests, monkeypatch, ya_enviado=True)
        reloj(monkeypatch, 10, 30)

        r = client.post("/ha/brief-tick?token=ha-poll-token")
        assert r.json()["enviado"] is False
        assert _SMTPFalso.enviados == []


class TestSuenoComoSenal:
    """La llegada del sueño del Watch es una DEDUCCIÓN de que ya estás despierto: el
    reloj lo sabe, pero el backend no se entera hasta que el iPhone sincroniza."""

    def _muestra(self, fecha, valor=7.2):
        return {"metric": "sleep_analysis", "date": fecha, "value": valor, "unit": "hr",
                "extra": {"deep": 1.2, "rem": 1.5, "core": 4.5}}

    def test_el_sueno_de_esta_noche_dispara_el_correo(self, client, mock_requests, graph_token, monkeypatch):
        preparar(mock_requests, monkeypatch)
        reloj(monkeypatch, 7, 40)
        hoy = datetime.now(main.LOCAL_TZ).date().isoformat()

        r = client.post("/health/ingest/simple?token=health-token", json=self._muestra(hoy))
        assert r.status_code == 200
        assert len(_SMTPFalso.enviados) == 1

    def test_un_reenvio_de_noches_viejas_no_dispara_nada(self, client, mock_requests, graph_token, monkeypatch):
        """El Atajo reenvía los últimos días en cada sync: un backfill de la semana
        pasada no significa que acabes de despertarte."""
        preparar(mock_requests, monkeypatch)
        reloj(monkeypatch, 7, 40)

        r = client.post("/health/ingest/simple?token=health-token",
                        json=self._muestra("2026-01-05"))
        assert r.status_code == 200
        assert _SMTPFalso.enviados == []

    def test_de_madrugada_tampoco(self, client, mock_requests, graph_token, monkeypatch):
        """El iPhone puede sincronizar una noche a medias mientras sigues durmiendo."""
        preparar(mock_requests, monkeypatch)
        reloj(monkeypatch, 4, 30)
        hoy = datetime.now(main.LOCAL_TZ).date().isoformat()

        client.post("/health/ingest/simple?token=health-token", json=self._muestra(hoy))
        assert _SMTPFalso.enviados == []

    def test_se_puede_desactivar(self, client, mock_requests, graph_token, monkeypatch):
        preparar(mock_requests, monkeypatch)
        reloj(monkeypatch, 7, 40)
        monkeypatch.setattr(main, "BRIEF_DISPARA_SUENO", False)
        hoy = datetime.now(main.LOCAL_TZ).date().isoformat()

        client.post("/health/ingest/simple?token=health-token", json=self._muestra(hoy))
        assert _SMTPFalso.enviados == []

    def test_un_fallo_del_correo_no_tumba_la_ingesta(self, client, mock_requests, graph_token, monkeypatch):
        """Guardar los datos del Watch importa más que mandar el correo, y el correo
        tiene otras dos fuentes que lo disparan."""
        preparar(mock_requests, monkeypatch)
        reloj(monkeypatch, 7, 40)

        def _explota(asunto, cuerpo):
            raise TimeoutError("SMTP caído")

        monkeypatch.setattr(main, "enviar_correo", _explota)
        hoy = datetime.now(main.LOCAL_TZ).date().isoformat()

        r = client.post("/health/ingest/simple?token=health-token", json=self._muestra(hoy))
        assert r.status_code == 200
        assert r.json()["upserted"] == 1


class TestReintento:
    def test_si_falla_el_envio_se_libera_el_dia(self, client, mock_requests, graph_token, monkeypatch):
        """Sin liberar la reserva, un error transitorio de SMTP dejaría el día marcado
        como enviado y te quedarías sin briefing hasta mañana."""
        estado = preparar(mock_requests, monkeypatch)
        reloj(monkeypatch, 7, 15)
        real = main.enviar_correo
        caido = {"si": True}

        def _quizas_explota(asunto, cuerpo, adjunto=None):
            if caido["si"]:
                raise TimeoutError("SMTP caído")
            return real(asunto, cuerpo, adjunto)

        monkeypatch.setattr(main, "enviar_correo", _quizas_explota)
        r = client.post("/despertar?token=brief-token")
        assert r.status_code == 502
        assert mock_requests.called("DELETE", "/rest/v1/brief_envios")
        assert estado["reservado"] is False

        # Y el siguiente disparador, con SMTP ya de vuelta, sí lo consigue.
        caido["si"] = False
        reloj(monkeypatch, 7, 20)
        r = client.post("/despertar?token=brief-token")
        assert r.json()["enviado"] is True
        assert len(_SMTPFalso.enviados) == 1


class TestDisparoDeLaRutina:
    """La rutina que redacta el briefing tiene dos triggers y se reparten el trabajo:
    el de horario cubre despertarse pronto (el briefing recoge newsletters que a las 6
    no han llegado) y este cubre despertarse tarde."""

    def configurar(self, monkeypatch, mock_requests):
        monkeypatch.setattr(main, "RUTINA_FIRE_URL", "https://api.anthropic.test/v1/claude_code/routines/trig_x/fire")
        monkeypatch.setattr(main, "RUTINA_FIRE_TOKEN", "sk-ant-oat01-secreto")
        mock_requests.add("POST", "/fire", FakeResponse(
            {"type": "routine_fire", "claude_code_session_id": "session_1"}, 200))

    def test_no_se_dispara_antes_de_las_ocho(self, client, mock_requests, graph_token, monkeypatch):
        """De esa franja se encarga el trigger de horario de la propia rutina."""
        preparar(mock_requests, monkeypatch)
        self.configurar(monkeypatch, mock_requests)
        reloj(monkeypatch, 6, 40)

        client.post("/despertar?token=brief-token")
        assert len(_SMTPFalso.enviados) == 1
        assert mock_requests.called("POST", "/fire") == []

    def test_se_dispara_si_te_despiertas_tarde(self, client, mock_requests, graph_token, monkeypatch):
        preparar(mock_requests, monkeypatch)
        self.configurar(monkeypatch, mock_requests)
        reloj(monkeypatch, 9, 35)

        client.post("/despertar?token=brief-token")
        llamadas = mock_requests.called("POST", "/fire")
        assert len(llamadas) == 1
        cabeceras = llamadas[0][2]["headers"]
        assert cabeceras["Authorization"] == "Bearer sk-ant-oat01-secreto"
        assert cabeceras["anthropic-beta"] == "experimental-cc-routine-2026-04-01"
        assert cabeceras["anthropic-version"] == "2023-06-01"

    def test_sin_configurar_no_se_llama_a_nada(self, client, mock_requests, graph_token, monkeypatch):
        """Sin URL ni token, la rutina se queda con su trigger de horario y ya está."""
        preparar(mock_requests, monkeypatch)
        monkeypatch.setattr(main, "RUTINA_FIRE_URL", "")
        monkeypatch.setattr(main, "RUTINA_FIRE_TOKEN", "")
        reloj(monkeypatch, 9, 35)

        r = client.post("/despertar?token=brief-token")
        assert r.json()["enviado"] is True
        assert mock_requests.called("POST", "/fire") == []

    def test_un_fallo_del_disparo_no_tumba_el_correo(self, client, mock_requests, graph_token, monkeypatch):
        """Cuando se dispara la rutina el correo YA ha salido: es lo que importa."""
        preparar(mock_requests, monkeypatch)
        monkeypatch.setattr(main, "RUTINA_FIRE_URL", "https://api.anthropic.test/v1/claude_code/routines/trig_x/fire")
        monkeypatch.setattr(main, "RUTINA_FIRE_TOKEN", "sk-ant-oat01-secreto")
        mock_requests.add("POST", "/fire", FakeResponse(None, 401, "unauthorized"))
        reloj(monkeypatch, 9, 35)

        r = client.post("/despertar?token=brief-token")
        assert r.status_code == 200
        assert r.json()["enviado"] is True
        assert len(_SMTPFalso.enviados) == 1

    def test_un_fallo_registra_el_motivo_y_la_beta(self, client, mock_requests, graph_token,
                                                   monkeypatch, caplog):
        """Con el código a secas no se puede diagnosticar: un 400 puede ser la cabecera
        beta caducada, el trigger borrado o el cuerpo mal formado, y son arreglos
        distintos. La respuesta la tenemos nosotros — tirarla es la lección del 400 de
        la ingesta de salud repetida por el otro lado."""
        preparar(mock_requests, monkeypatch)
        monkeypatch.setattr(main, "RUTINA_FIRE_URL", "https://api.anthropic.test/v1/claude_code/routines/trig_x/fire")
        monkeypatch.setattr(main, "RUTINA_FIRE_TOKEN", "sk-ant-oat01-secreto")
        mock_requests.add("POST", "/fire", FakeResponse(
            None, 400, '{"error": {"message": "unsupported beta header"}}'))
        reloj(monkeypatch, 9, 35)

        with caplog.at_level("ERROR"):
            client.post("/despertar?token=brief-token")
        registrado = "\n".join(r.getMessage() for r in caplog.records)
        assert "unsupported beta header" in registrado
        assert main.RUTINA_BETA in registrado, "hay que poder ver con qué beta se llamó"
        assert "sk-ant-oat01-secreto" not in registrado, "el token no se registra"


class TestRespaldoDeActions:
    def test_el_workflow_no_duplica_si_ya_se_envio(self, client, mock_requests, graph_token, monkeypatch):
        """La red de seguridad dispara a ciegas: llega tarde a propósito y casi siempre
        se encuentra el correo ya enviado."""
        preparar(mock_requests, monkeypatch, ya_enviado=True)

        r = client.post("/brief/send?token=brief-token")
        assert r.status_code == 200
        assert r.json()["enviado"] is False
        assert _SMTPFalso.enviados == []

    def test_forzar_se_salta_la_idempotencia(self, client, mock_requests, graph_token, monkeypatch):
        """Es como se prueba el correo a mano sin esperar a mañana ni borrar filas."""
        preparar(mock_requests, monkeypatch, ya_enviado=True)

        r = client.post("/brief/send?token=brief-token&forzar=1")
        assert r.status_code == 200
        assert r.json()["enviado"] is True
        assert len(_SMTPFalso.enviados) == 1
