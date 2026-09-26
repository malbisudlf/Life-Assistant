"""Tests del disparo del resumen diario: cuándo sale el correo y cuántas veces.

Antes salía a hora fija desde un cron de GitHub Actions, que se retrasa cuando su cola
va cargada. Ahora sale al despertarse — y como hay VARIAS fuentes que pueden avisar de
eso a la vez (el móvil al desenchufarse, la llegada del sueño del Watch, el reloj de
respaldo de HA y el propio workflow), lo que más se prueba aquí es que dos disparadores
simultáneos no manden dos correos.
"""
from datetime import datetime

import pytest

import main
from conftest import FakeResponse
from test_brief import _SMTPFalso, _salud_filas, configurar_smtp, montar_fuentes


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


def preparar(mock_requests, monkeypatch, ya_enviado=False, salud=None):
    montar_fuentes(mock_requests, salud=salud)
    configurar_smtp(monkeypatch)
    # Sin esto, cada POST a /despertar dormiría DESPERTAR_RETRASO_SEGUNDOS de verdad: el
    # retraso se prueba aparte, en su propia clase, con el tiempo controlado a mano.
    monkeypatch.setattr(main, "DESPERTAR_RETRASO_SEGUNDOS", 0)
    return tabla_envios(mock_requests, ya_enviado)


def sueno_de_hoy(mock_requests, hay):
    """Qué contesta la consulta de `_hay_sueno_de`: si la noche de hoy ha sincronizado.

    Se registra ANTES que `montar_fuentes` a propósito. El router resuelve por fragmento
    y gana el primero registrado, y el mock general de `health_metrics` devuelve las
    filas de TODOS los días ignorando el filtro: sin esta ruta más específica, la
    consulta vería el sueño de cualquier día y el test pasaría siempre, también con el
    código mal.
    """
    hoy = datetime.now(main.LOCAL_TZ).date().isoformat()
    filas = [{"metric_date": hoy, "metric_name": "sleep_analysis",
              "value": 7.2, "unit": "h", "extra": {}}] if hay else []
    mock_requests.add("GET", "metric_name=in.(sleep_analysis,sleep)", FakeResponse(filas))


@pytest.fixture(autouse=True)
def _sin_espera_pendiente():
    """La espera al sueño y la noche por alcanzar viven en globales del módulo: sin
    limpiarlas, lo que apunta un test decide el resultado del siguiente."""
    main._olvidar_despertar()
    main._olvidar_alcance()
    yield
    main._olvidar_despertar()
    main._olvidar_alcance()


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

    def test_desenchufar_el_cargador_calla_la_alarma_que_sonaba(
            self, client, mock_requests, graph_token, monkeypatch):
        """El segundo camino del botón «Estoy despierto», y el único que no cuesta nada
        en el camino feliz: si desenchufas el móvil estás despierto, y la alarma de
        respaldo que estuviera sonando se calla sin que nadie pulse nada."""
        preparar(mock_requests, monkeypatch)
        monkeypatch.setattr(main, "ALARMA_ALTAVOZ", "media_player.cuarto")
        mock_requests.add("PATCH", "/rest/v1/alarmas",
                          FakeResponse([{"id": "11111111-1111-1111-1111-111111111111",
                                         "etiqueta": "Entrenar"}]))
        reloj(monkeypatch, 7, 15)

        r = client.post("/despertar?token=brief-token&fuente=cargador")
        assert r.json()["alarma"]["hecho"] is True
        assert "estado=in.(avisada,escalada)" in mock_requests.called("PATCH", "/rest/v1/alarmas")[0][1]
        assert ("media_player.media_stop", "media_player.cuarto") in [
            (o["servicio"], o["entidad"]) for o in main._ha_ordenes]
        # Y el resumen sale igual: la alarma es lo de menos de esta petición.
        assert r.json()["enviado"] is True

    def test_la_alarma_se_calla_aunque_sea_de_madrugada(
            self, client, mock_requests, graph_token, monkeypatch):
        """La ventana horaria es del resumen, no de la alarma: una que suene a las
        cuatro se calla igual si dices que estás despierto."""
        preparar(mock_requests, monkeypatch)
        mock_requests.add("PATCH", "/rest/v1/alarmas",
                          FakeResponse([{"id": "11111111-1111-1111-1111-111111111111"}]))
        reloj(monkeypatch, 4, 0)

        r = client.post("/despertar?token=brief-token&fuente=cargador")
        assert r.json()["alarma"]["hecho"] is True
        assert r.json()["enviado"] is False

    def test_un_fallo_callando_la_alarma_no_deja_el_resumen_sin_mandar(
            self, client, mock_requests, graph_token, monkeypatch):
        preparar(mock_requests, monkeypatch)
        mock_requests.add("PATCH", "/rest/v1/alarmas", FakeResponse(None, 500, "boom"))
        reloj(monkeypatch, 7, 15)

        r = client.post("/despertar?token=brief-token&fuente=cargador")
        assert r.status_code == 200
        assert r.json()["enviado"] is True
        assert r.json()["alarma"]["ok"] is False

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


class TestFalloConNombre:
    """El 2026-09-26 el resumen no salió en todo el día y el issue del vigilante (#233)
    solo decía «fallo al enviarlo por hora tope», diez veces: ni qué sección, ni si era
    el SMTP. El vigilante, el aviso y el issue solo ven la primera línea del registro."""

    @staticmethod
    def _smtp_rechaza(*_a, **_k):
        import smtplib
        raise smtplib.SMTPAuthenticationError(535, b"5.7.8 Username and Password not accepted")

    def test_una_seccion_rota_no_deja_el_dia_sin_correo(self, client, mock_requests,
                                                         graph_token, monkeypatch):
        preparar(mock_requests, monkeypatch)
        reloj(monkeypatch, 10, 0)

        def _revienta():
            raise AttributeError("'str' object has no attribute 'get'")
        monkeypatch.setattr(main, "_brief_salud", _revienta)

        r = client.post("/ha/brief-tick?token=ha-poll-token")
        assert r.json()["enviado"] is True
        assert len(_SMTPFalso.enviados) == 1
        assert "Avería del backend" in _SMTPFalso.enviados[0].get_body().get_content()

    @pytest.mark.parametrize("hora, ruta, mensaje", [
        (10, "/ha/brief-tick?token=ha-poll-token", "Resumen diario: fallo al enviarlo por hora tope"),
        (7, "/despertar?token=brief-token", "Despertar: fallo al construir o enviar el resumen"),
        (7, "/brief/send?token=brief-token",
         "Resumen diario: fallo inesperado al construir o enviar el correo"),
    ])
    def test_el_fallo_del_envio_dice_su_tipo(self, client, mock_requests, graph_token,
                                             monkeypatch, caplog, hora, ruta, mensaje):
        preparar(mock_requests, monkeypatch)
        reloj(monkeypatch, hora, 15)
        monkeypatch.setattr(main, "enviar_correo", self._smtp_rechaza)

        with caplog.at_level("ERROR"):
            r = client.post(ruta)
        assert r.status_code == 502
        primeras = [main._firma_error(x.getMessage()) for x in caplog.records]
        assert f"{mensaje} (SMTPAuthenticationError)" in primeras

    def test_la_primera_linea_no_lleva_el_mensaje(self, client, mock_requests, graph_token,
                                                  monkeypatch, caplog):
        """Esa línea acaba en un issue de un repositorio PÚBLICO, y el mensaje de una
        excepción puede traer un correo o un host: solo viaja el tipo."""
        import smtplib
        preparar(mock_requests, monkeypatch)
        reloj(monkeypatch, 10, 0)

        def _rechaza_destinatario(*_a, **_k):
            raise smtplib.SMTPRecipientsRefused({"yo@test": (550, b"5.1.1 no existe")})
        monkeypatch.setattr(main, "enviar_correo", _rechaza_destinatario)

        with caplog.at_level("ERROR"):
            client.post("/ha/brief-tick?token=ha-poll-token")
        primeras = [main._firma_error(x.getMessage()) for x in caplog.records]
        assert any("(SMTPRecipientsRefused)" in p for p in primeras)
        assert not any("yo@test" in p for p in primeras)


class TestSuenoComoSenal:
    """La llegada del sueño del reloj NO es una señal de despertar: solo cierra una
    espera que abrió una señal de verdad. Deducir "ha sincronizado, luego está
    despierto" fallaba por el lado malo: una noche a medias sincronizada de fondo
    mandaba el correo mientras seguías durmiendo, antes de poder sincronizar la noche
    entera."""

    def _muestra(self, fecha, valor=7.2):
        return {"metric": "sleep_analysis", "date": fecha, "value": valor, "unit": "hr",
                "extra": {"deep": 1.2, "rem": 1.5, "core": 4.5}}

    def test_el_sueno_sin_senal_de_despertar_no_manda_nada(self, client, mock_requests,
                                                           graph_token, monkeypatch):
        """ESTE era el fallo que quedaba: la pulsera vuelca una noche a medias si te
        despiertas un rato a las seis, la app la sincroniza de fondo, y el correo salía
        a las siete mientras seguías durmiendo."""
        preparar(mock_requests, monkeypatch)
        reloj(monkeypatch, 7, 40)
        hoy = datetime.now(main.LOCAL_TZ).date().isoformat()

        r = client.post("/health/ingest/simple?token=health-token", json=self._muestra(hoy))
        assert r.status_code == 200
        assert _SMTPFalso.enviados == []
        assert mock_requests.called("POST", "/rest/v1/brief_envios") == []

    def test_el_sueno_cierra_la_espera_que_abrio_el_cargador(self, client, mock_requests,
                                                             graph_token, monkeypatch):
        preparar(mock_requests, monkeypatch)
        reloj(monkeypatch, 7, 40)
        main._apuntar_despertar(_a_las(7, 15), "cargador")
        hoy = datetime.now(main.LOCAL_TZ).date().isoformat()

        r = client.post("/health/ingest/simple?token=health-token", json=self._muestra(hoy))
        assert r.status_code == 200
        assert len(_SMTPFalso.enviados) == 1
        assert main._despertar_esperado(_a_las(7, 40)) is None

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
        """Apagado, ni siquiera cierra la espera: la cierra la hora tope."""
        preparar(mock_requests, monkeypatch)
        reloj(monkeypatch, 7, 40)
        monkeypatch.setattr(main, "BRIEF_DISPARA_SUENO", False)
        main._apuntar_despertar(_a_las(7, 15), "cargador")
        hoy = datetime.now(main.LOCAL_TZ).date().isoformat()

        client.post("/health/ingest/simple?token=health-token", json=self._muestra(hoy))
        assert _SMTPFalso.enviados == []
        assert main._despertar_esperado(_a_las(7, 40)) == _a_las(7, 15)

    def test_un_fallo_del_correo_no_tumba_la_ingesta(self, client, mock_requests, graph_token, monkeypatch):
        """Guardar los datos del reloj importa más que mandar el correo, y el correo
        tiene la hora tope detrás."""
        preparar(mock_requests, monkeypatch)
        reloj(monkeypatch, 7, 40)
        main._apuntar_despertar(_a_las(7, 15), "cargador")

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


class TestRetrasoDelDespertar:
    """El Atajo dispara al desenchufar el cargador, antes de que el reloj haya tenido
    tiempo de sincronizar de fondo. DESPERTAR_RETRASO_SEGUNDOS le da ese margen sin
    depender de un delay dentro del propio Atajo, que en la práctica no era fiable."""

    def test_con_retraso_la_respuesta_no_espera_y_no_manda_todavia(
            self, client, mock_requests, graph_token, monkeypatch):
        preparar(mock_requests, monkeypatch)
        monkeypatch.setattr(main, "DESPERTAR_RETRASO_SEGUNDOS", 300)
        dormido = []
        monkeypatch.setattr(main.time, "sleep", lambda s: dormido.append(s))
        reloj(monkeypatch, 7, 15)

        r = client.post("/despertar?token=brief-token&fuente=cargador")
        assert r.status_code == 200
        assert r.json()["enviado"] is False
        assert dormido == [300], "el retraso tiene que aplicarse, y solo una vez"
        # Y como es tarea de fondo, ya se ha ejecutado dentro del propio POST (TestClient
        # corre las background tasks antes de devolver la respuesta): el correo sale.
        assert len(_SMTPFalso.enviados) == 1

    def test_la_alarma_se_calla_sin_esperar_al_retraso(
            self, client, mock_requests, graph_token, monkeypatch):
        preparar(mock_requests, monkeypatch)
        monkeypatch.setattr(main, "DESPERTAR_RETRASO_SEGUNDOS", 300)
        monkeypatch.setattr(main.time, "sleep", lambda s: None)
        mock_requests.add("PATCH", "/rest/v1/alarmas",
                          FakeResponse([{"id": "11111111-1111-1111-1111-111111111111"}]))
        reloj(monkeypatch, 7, 15)

        r = client.post("/despertar?token=brief-token&fuente=cargador")
        assert r.json()["alarma"]["hecho"] is True

    def test_desactivado_no_espera_nada(
            self, client, mock_requests, graph_token, monkeypatch):
        preparar(mock_requests, monkeypatch)
        monkeypatch.setattr(main, "DESPERTAR_RETRASO_SEGUNDOS", 0)
        reloj(monkeypatch, 7, 15)

        r = client.post("/despertar?token=brief-token&fuente=cargador")
        assert r.json()["enviado"] is True
        assert len(_SMTPFalso.enviados) == 1


class TestEsperaAlSueno:
    """Te despiertas antes de que el reloj haya sincronizado la noche.

    Es el fallo que tenía el correo todos los días: la señal del cargador llega al
    desenchufar el móvil, pero el sueño no está en Salud hasta que se abre la app del
    reloj — entre cinco minutos y esa misma tarde, según el día. El correo salía
    mientras tanto y la sección RELOJ escribía "anoche sin reloj", que es lo que la
    rutina que redacta el briefing leía y repetía cada mañana.
    """

    def test_sin_el_sueno_de_esta_noche_el_correo_espera(
            self, client, mock_requests, graph_token, monkeypatch):
        sueno_de_hoy(mock_requests, False)
        preparar(mock_requests, monkeypatch)
        reloj(monkeypatch, 7, 15)

        r = client.post("/despertar?token=brief-token&fuente=cargador")
        assert r.json()["enviado"] is False and r.json()["esperando_sueno"] is True
        assert _SMTPFalso.enviados == []
        # Y sobre todo: NO puede reservar el día. Si lo reservara, el envío de verdad
        # —cuando llegue el sueño— se encontraría el día marcado y no saldría nunca.
        assert mock_requests.called("POST", "/rest/v1/brief_envios") == []

    def test_con_el_sueno_ya_sincronizado_sale_al_momento(
            self, client, mock_requests, graph_token, monkeypatch):
        """Los días que abres la app antes de desenchufar no hay nada que esperar."""
        sueno_de_hoy(mock_requests, True)
        preparar(mock_requests, monkeypatch)
        reloj(monkeypatch, 7, 15)

        assert client.post("/despertar?token=brief-token").json()["enviado"] is True
        assert len(_SMTPFalso.enviados) == 1

    def test_al_llegar_el_sueno_sale_con_la_hora_del_despertar(
            self, client, mock_requests, graph_token, monkeypatch):
        """El correo sale tarde, pero te despertaste a las 07:15: es esa hora la que
        decide después cuándo se lanza la rutina que lo redacta."""
        sueno_de_hoy(mock_requests, False)
        preparar(mock_requests, monkeypatch)
        reloj(monkeypatch, 7, 15)
        client.post("/despertar?token=brief-token&fuente=cargador")

        reloj(monkeypatch, 7, 32)
        hoy = datetime.now(main.LOCAL_TZ).date().isoformat()
        client.post("/health/ingest/simple?token=health-token",
                    json={"metric": "sleep_analysis", "date": hoy, "value": 7.8,
                          "unit": "hr", "extra": {}})

        assert len(_SMTPFalso.enviados) == 1
        fila = mock_requests.called("POST", "/rest/v1/brief_envios")[0][2]["json"][0]
        assert fila["fuente"] == "sueno"
        esperado = _a_las(7, 15).astimezone(main.timezone.utc).isoformat()
        assert fila["despertar_at"][:16] == esperado[:16]

    def test_la_noche_de_ayer_reenviada_no_manda_nada(
            self, client, mock_requests, graph_token, monkeypatch):
        """ESTE era el fallo. El Atajo reenvía los últimos días en cada sync, y como la
        noche se fecha por el día en que te despiertas, la de ayer no es nunca la de
        esta noche: aceptarla hacía que el correo saliera con el dato de hoy sin llegar.
        """
        sueno_de_hoy(mock_requests, False)
        preparar(mock_requests, monkeypatch)
        reloj(monkeypatch, 8, 33)
        ayer = (datetime.now(main.LOCAL_TZ).date() - main.timedelta(days=1)).isoformat()

        client.post("/health/ingest/simple?token=health-token",
                    json={"metric": "sleep_analysis", "date": ayer, "value": 7.7,
                          "unit": "hr", "extra": {}})
        assert _SMTPFalso.enviados == []

    def test_una_noche_de_cero_horas_no_cierra_la_espera(
            self, client, mock_requests, graph_token, monkeypatch):
        """El Atajo escribe 0 las noches que no encuentra muestras. Una fila no es una
        medida: darla por noche cerrada devolvería el problema por la otra puerta."""
        sueno_de_hoy(mock_requests, False)
        preparar(mock_requests, monkeypatch)
        reloj(monkeypatch, 7, 40)
        hoy = datetime.now(main.LOCAL_TZ).date().isoformat()

        client.post("/health/ingest/simple?token=health-token",
                    json={"metric": "sleep_analysis", "date": hoy, "value": 0,
                          "unit": "hr", "extra": {}})
        assert _SMTPFalso.enviados == []

    def test_a_los_45_min_te_avisa_pero_el_correo_sigue_esperando(
            self, client, mock_requests, graph_token, monkeypatch):
        """El aviso al móvil no es un parte de avería: es lo único que puede hacer que
        el dato de esta noche exista, porque hasta que no abras la app no hay nada que
        sincronizar. Y el correo NO sale al avisar: la primera versión lo mandaba a los
        45 minutos y salía igual de cojo que antes, solo que más tarde. Sale cuando
        llegue la noche, o a la hora tope sin ella."""
        sueno_de_hoy(mock_requests, False)
        preparar(mock_requests, monkeypatch)
        avisos = []
        monkeypatch.setattr(main, "_apuntar_aviso",
                            lambda regla, texto, **kw: avisos.append((regla, texto)) or True)
        reloj(monkeypatch, 7, 15)
        client.post("/despertar?token=brief-token&fuente=cargador")

        reloj(monkeypatch, 8, 5)        # 50 min > BRIEF_ESPERA_SUENO_MIN (45)
        r = client.post("/ha/brief-tick?token=ha-poll-token")

        assert r.json()["enviado"] is False
        assert r.json()["aviso_sueno_sin_sincronizar"] is True
        assert _SMTPFalso.enviados == []
        assert [t for regla, t in avisos if regla == "reloj_sync"], "tiene que avisar al movil"
        assert main._despertar_esperado(_a_las(8, 5)) == _a_las(7, 15)

        # El siguiente tick no vuelve a avisar: una vez por espera.
        reloj(monkeypatch, 8, 10)
        r = client.post("/ha/brief-tick?token=ha-poll-token")
        assert "aviso_sueno_sin_sincronizar" not in r.json()
        assert len(avisos) == 1

        # Y cuando por fin abres la app, el correo sale con la noche y con la hora a la
        # que te levantaste de verdad.
        reloj(monkeypatch, 8, 30)
        hoy = datetime.now(main.LOCAL_TZ).date().isoformat()
        client.post("/health/ingest/simple?token=health-token",
                    json={"metric": "sleep_analysis", "date": hoy, "value": 7.8,
                          "unit": "hr", "extra": {}})
        assert len(_SMTPFalso.enviados) == 1
        fila = mock_requests.called("POST", "/rest/v1/brief_envios")[0][2]["json"][0]
        assert fila["fuente"] == "sueno"
        assert fila["despertar_at"][:16] == _a_las(7, 15).astimezone(main.timezone.utc).isoformat()[:16]

    def test_antes_de_vencer_el_tick_no_toca_nada(
            self, client, mock_requests, graph_token, monkeypatch):
        sueno_de_hoy(mock_requests, False)
        preparar(mock_requests, monkeypatch)
        avisos = []
        monkeypatch.setattr(main, "_apuntar_aviso",
                            lambda regla, texto, **kw: avisos.append(regla) or True)
        reloj(monkeypatch, 7, 15)
        client.post("/despertar?token=brief-token&fuente=cargador")

        reloj(monkeypatch, 7, 50)       # 35 min: aún dentro de la espera
        r = client.post("/ha/brief-tick?token=ha-poll-token")
        assert r.json()["enviado"] is False
        assert _SMTPFalso.enviados == []
        assert avisos == []

    def test_el_tick_manda_el_correo_en_cuanto_ve_el_sueno(
            self, client, mock_requests, graph_token, monkeypatch):
        """Si la noche entró por un camino que no pasa por la ingesta, no se espera a
        las diez con el dato ya guardado: el tick lo mira en cada vuelta."""
        sueno_de_hoy(mock_requests, True)
        preparar(mock_requests, monkeypatch)
        reloj(monkeypatch, 7, 15)
        main._apuntar_despertar(_a_las(7, 15), "cargador")

        reloj(monkeypatch, 7, 25)       # 10 min: ni de lejos los 45 del aviso
        r = client.post("/ha/brief-tick?token=ha-poll-token")
        assert r.json()["enviado"] is True
        fila = mock_requests.called("POST", "/rest/v1/brief_envios")[0][2]["json"][0]
        assert fila["fuente"] == "sueno"

    def test_a_la_hora_tope_sale_sin_el_sueno_y_dice_por_que(
            self, client, mock_requests, graph_token, monkeypatch):
        """La hora tope es donde este sistema acepta salir con lo que haya. La fuente
        «espera_agotada» es lo único que después distingue, en brief_envios, un correo
        al que le faltaba la noche de una mañana en la que nadie dio señal."""
        sueno_de_hoy(mock_requests, False)
        preparar(mock_requests, monkeypatch)
        reloj(monkeypatch, 7, 15)
        client.post("/despertar?token=brief-token&fuente=cargador")

        reloj(monkeypatch, 10, 0)
        r = client.post("/ha/brief-tick?token=ha-poll-token")
        assert r.json()["enviado"] is True
        fila = mock_requests.called("POST", "/rest/v1/brief_envios")[0][2]["json"][0]
        assert fila["fuente"] == "espera_agotada"
        assert fila["despertar_at"][:16] == _a_las(7, 15).astimezone(main.timezone.utc).isoformat()[:16]
        assert main._despertar_esperado(_a_las(10, 0)) is None

    def test_si_el_sueno_llego_por_otro_camino_no_te_regana(
            self, client, mock_requests, graph_token, monkeypatch):
        """Regañarte por no sincronizar algo que ya está sincronizado es exactamente
        como se deja de leer un aviso."""
        sueno_de_hoy(mock_requests, True)
        preparar(mock_requests, monkeypatch)
        avisos = []
        monkeypatch.setattr(main, "_apuntar_aviso",
                            lambda regla, texto, **kw: avisos.append(regla) or True)
        reloj(monkeypatch, 7, 15)
        main._apuntar_despertar(_a_las(7, 15), "cargador")

        reloj(monkeypatch, 8, 5)
        r = client.post("/ha/brief-tick?token=ha-poll-token")

        assert r.json()["enviado"] is True
        assert "reloj_sync" not in avisos

    def test_la_hora_tope_manda_aunque_falte_el_sueno(
            self, client, mock_requests, graph_token, monkeypatch):
        """La espera es propiedad de la SEÑAL de despertar. El respaldo dispara justo
        cuando ya no tiene sentido esperar más, y no puede quedarse mudo por ella."""
        sueno_de_hoy(mock_requests, False)
        preparar(mock_requests, monkeypatch)
        reloj(monkeypatch, 10, 0)

        assert client.post("/ha/brief-tick?token=ha-poll-token").json()["enviado"] is True
        assert len(_SMTPFalso.enviados) == 1

    def test_pasada_la_hora_tope_la_senal_ya_no_espera(
            self, client, mock_requests, graph_token, monkeypatch):
        """Entre la hora tope y el techo de la ventana el correo todavía puede salir por
        la señal, y a esas alturas esperar solo serviría para no mandarlo."""
        sueno_de_hoy(mock_requests, False)
        preparar(mock_requests, monkeypatch)
        reloj(monkeypatch, 11, 0)

        assert client.post("/despertar?token=brief-token").json()["enviado"] is True

    def test_se_puede_apagar(self, client, mock_requests, graph_token, monkeypatch):
        sueno_de_hoy(mock_requests, False)
        preparar(mock_requests, monkeypatch)
        monkeypatch.setattr(main, "BRIEF_ESPERA_SUENO", False)
        reloj(monkeypatch, 7, 15)

        assert client.post("/despertar?token=brief-token").json()["enviado"] is True

    def test_un_supabase_caido_no_retiene_el_correo(
            self, client, mock_requests, graph_token, monkeypatch):
        """"No he podido mirar si ha llegado" no es "no ha llegado". Tratarlo como un no
        dejaría el correo esperando por una avería que no tiene que ver con él."""
        mock_requests.add("GET", "metric_name=in.(sleep_analysis,sleep)",
                          FakeResponse(None, 500, "boom"))
        preparar(mock_requests, monkeypatch)
        reloj(monkeypatch, 7, 15)

        assert client.post("/despertar?token=brief-token").json()["enviado"] is True

    def test_un_parpadeo_de_supabase_no_manda_el_correo_sin_la_noche(
            self, client, mock_requests, graph_token, monkeypatch):
        """En el tick, "no he podido mirar" es "todavía no": mandar el correo por un
        parpadeo lo dejaría sin la noche, y esperar cinco minutos no cuesta nada."""
        mock_requests.add("GET", "metric_name=in.(sleep_analysis,sleep)",
                          FakeResponse(None, 500, "boom"))
        preparar(mock_requests, monkeypatch)
        reloj(monkeypatch, 7, 15)
        main._apuntar_despertar(_a_las(7, 15), "cargador")

        reloj(monkeypatch, 7, 25)
        r = client.post("/ha/brief-tick?token=ha-poll-token")
        assert r.json()["enviado"] is False
        assert _SMTPFalso.enviados == []
        assert main._despertar_esperado(_a_las(7, 25)) == _a_las(7, 15)

    def test_si_el_correo_falla_al_llegar_el_sueno_el_tick_lo_reintenta(
            self, client, mock_requests, graph_token, monkeypatch):
        """Un SMTP caído un minuto no puede costar la noche entera: la espera sigue viva
        y el tick, que ve el sueño ya guardado, lo vuelve a intentar sin regañarte."""
        sueno_de_hoy(mock_requests, True)
        preparar(mock_requests, monkeypatch)
        avisos = []
        monkeypatch.setattr(main, "_apuntar_aviso",
                            lambda regla, texto, **kw: avisos.append(regla) or True)
        real  = main.enviar_correo
        caido = {"si": True}

        def _quizas_explota(asunto, cuerpo, adjunto=None):
            if caido["si"]:
                raise TimeoutError("SMTP caído")
            return real(asunto, cuerpo, adjunto)

        monkeypatch.setattr(main, "enviar_correo", _quizas_explota)
        reloj(monkeypatch, 7, 15)
        main._apuntar_despertar(_a_las(7, 15), "cargador")
        hoy = datetime.now(main.LOCAL_TZ).date().isoformat()
        client.post("/health/ingest/simple?token=health-token",
                    json={"metric": "sleep_analysis", "date": hoy, "value": 7.8,
                          "unit": "hr", "extra": {}})
        assert _SMTPFalso.enviados == []
        assert main._despertar_esperado(_a_las(7, 15)) == _a_las(7, 15)

        caido["si"] = False
        reloj(monkeypatch, 8, 20)      # pasados los 45 min: y aun así no avisa, el sueño está
        r = client.post("/ha/brief-tick?token=ha-poll-token")
        assert r.json()["enviado"] is True
        assert len(_SMTPFalso.enviados) == 1
        assert "reloj_sync" not in avisos

    def test_confirmar_la_alarma_de_respaldo_es_senal_de_despertar(
            self, client, mock_requests, graph_token, monkeypatch):
        """Has pulsado «Estoy despierto»: no hay señal más exacta. Abre la misma espera
        que el cargador, para las mañanas en que el móvil no estaba enchufado."""
        sueno_de_hoy(mock_requests, False)
        preparar(mock_requests, monkeypatch)
        mock_requests.add("PATCH", "/rest/v1/alarmas",
                          FakeResponse([{"id": "11111111-1111-1111-1111-111111111111"}]))
        reloj(monkeypatch, 7, 15)

        r = client.post("/alarmas/11111111-1111-1111-1111-111111111111/despierto",
                        headers={"X-Auth-Token": "ha-poll-token"})
        assert r.json()["hecho"] is True
        assert main._despertar_esperado(_a_las(7, 15)) == _a_las(7, 15)
        assert _SMTPFalso.enviados == []

    def test_dos_desenchufes_seguidos_conservan_la_primera_hora(
            self, client, mock_requests, graph_token, monkeypatch):
        """Vuelves a enchufar el móvil y lo quitas otra vez: te despertaste a la
        primera, no a la última."""
        sueno_de_hoy(mock_requests, False)
        preparar(mock_requests, monkeypatch)
        reloj(monkeypatch, 7, 15)
        client.post("/despertar?token=brief-token&fuente=cargador")
        reloj(monkeypatch, 7, 40)
        client.post("/despertar?token=brief-token&fuente=cargador")

        assert main._despertar_esperado(_a_las(7, 40)) == _a_las(7, 15)


def _salud_sin_la_noche_de_hoy():
    """Las filas de salud de siempre, pero sin el sueño de esta madrugada: es el estado
    real de la tabla cuando la pulsera aún no ha volcado la noche."""
    hoy = datetime.now(main.LOCAL_TZ).date().isoformat()
    return [f for f in _salud_filas()
            if not (f["metric_date"] == hoy and f["metric_name"] == "sleep_analysis")]


def noche_que_llega_tarde(mock_requests, estado):
    """Como `sueno_de_hoy`, pero la respuesta cambia a media mañana.

    Es lo que pasa de verdad: a las diez la noche no está y a las diez y veinte sí. Con
    una respuesta fija no se puede probar nada de lo que viene después de la hora tope.
    """
    hoy = datetime.now(main.LOCAL_TZ).date().isoformat()

    def _get(url, **kwargs):
        if estado.get("fallos"):
            estado["fallos"] -= 1
            return FakeResponse(None, 500, "boom")
        if not estado["hay"]:
            return FakeResponse([])
        return FakeResponse([{"metric_date": hoy, "metric_name": "sleep_analysis",
                              "value": 7.8, "unit": "h",
                              "extra": {"sleep_start": "23:41", "deep": 1.2,
                                        "rem": 1.6, "core": 4.7, "awake": 0.3}}])

    mock_requests.add("GET", "metric_name=in.(sleep_analysis,sleep)", _get)


def _llega_la_noche(client, estado, mock_requests=None):
    """La ingesta entrega por fin el sueño de hoy."""
    estado["hay"] = True
    hoy = datetime.now(main.LOCAL_TZ).date().isoformat()
    return client.post("/health/ingest/simple?token=health-token",
                       json={"metric": "sleep_analysis", "date": hoy, "value": 7.8,
                             "unit": "hr", "extra": {"sleep_start": "23:41", "deep": 1.2,
                                                     "rem": 1.6, "core": 4.7, "awake": 0.3}})


class TestAlcanceDeLaNoche:
    """La noche que llega DESPUÉS de que el resumen haya salido sin ella.

    La hora tope existe para que el correo salga con lo que haya, y eso estaba bien. Lo
    que no se veía es que además cerraba el día: la reserva de `brief_envios` ya está
    puesta, así que el envío que dispara la ingesta se encuentra el 409 y se retira en
    silencio. El correo se quedaba con la noche de AYER para siempre — que es justo la
    queja del 2026-09-22 — y con él el briefing que la rutina redacta a partir de él.
    """

    def test_la_noche_que_llega_tras_la_hora_tope_se_manda_aparte(
            self, client, mock_requests, graph_token, monkeypatch):
        estado = {"hay": False}
        noche_que_llega_tarde(mock_requests, estado)
        preparar(mock_requests, monkeypatch, salud=_salud_sin_la_noche_de_hoy())
        reloj(monkeypatch, 7, 15)
        client.post("/despertar?token=brief-token&fuente=cargador")
        assert _SMTPFalso.enviados == []

        reloj(monkeypatch, 10, 0)
        assert client.post("/ha/brief-tick?token=ha-poll-token").json()["enviado"] is True
        assert len(_SMTPFalso.enviados) == 1

        reloj(monkeypatch, 10, 20)
        _llega_la_noche(client, estado)

        assert len(_SMTPFalso.enviados) == 2, "la noche de hoy no puede quedarse sin mandar"
        alcance = _SMTPFalso.enviados[1]
        assert "llegó tarde" in alcance["Subject"]
        cuerpo = alcance.get_content()
        assert "7.80 h" in cuerpo and "23:41" in cuerpo
        assert "1.20 h" in cuerpo, "las fases van dentro: sin ellas solo viaja la cantidad"

    def test_no_se_manda_dos_veces(self, client, mock_requests, graph_token, monkeypatch):
        """Health Auto Export reintenta, y dos correos por la misma noche son peor que
        ninguno. Reclamar el alcance lo consume."""
        estado = {"hay": False}
        noche_que_llega_tarde(mock_requests, estado)
        preparar(mock_requests, monkeypatch, salud=_salud_sin_la_noche_de_hoy())
        reloj(monkeypatch, 7, 15)
        client.post("/despertar?token=brief-token&fuente=cargador")
        reloj(monkeypatch, 10, 0)
        client.post("/ha/brief-tick?token=ha-poll-token")

        reloj(monkeypatch, 10, 20)
        _llega_la_noche(client, estado)
        _llega_la_noche(client, estado)
        assert len(_SMTPFalso.enviados) == 2

    def test_si_el_resumen_llevaba_la_noche_no_hay_alcance(
            self, client, mock_requests, graph_token, monkeypatch):
        """Un reenvío de la misma noche no puede provocar un segundo correo: el resumen
        ya la llevaba dentro."""
        estado = {"hay": True}
        noche_que_llega_tarde(mock_requests, estado)
        preparar(mock_requests, monkeypatch)
        reloj(monkeypatch, 7, 15)
        assert client.post("/despertar?token=brief-token").json()["enviado"] is True

        reloj(monkeypatch, 8, 30)
        _llega_la_noche(client, estado)
        assert len(_SMTPFalso.enviados) == 1

    def test_el_alcance_no_relanza_la_rutina(
            self, client, mock_requests, graph_token, monkeypatch):
        """El briefing del día ya está redactado. Relanzar la rutina daría dos briefings
        cada mañana en que la pulsera tarde en volcar, que es el precio que este correo
        corto existe para no pagar."""
        estado = {"hay": False}
        noche_que_llega_tarde(mock_requests, estado)
        preparar(mock_requests, monkeypatch, salud=_salud_sin_la_noche_de_hoy())
        monkeypatch.setattr(main, "RUTINA_FIRE_URL", "https://api.test/rutina")
        monkeypatch.setattr(main, "RUTINA_FIRE_TOKEN", "t")
        mock_requests.add("POST", "api.test/rutina", FakeResponse({"ok": True}))
        reloj(monkeypatch, 7, 15)
        client.post("/despertar?token=brief-token&fuente=cargador")
        reloj(monkeypatch, 10, 0)
        client.post("/ha/brief-tick?token=ha-poll-token")
        disparos = len(mock_requests.called("POST", "api.test/rutina"))

        reloj(monkeypatch, 10, 20)
        _llega_la_noche(client, estado)
        assert len(mock_requests.called("POST", "api.test/rutina")) == disparos

    def test_un_fallo_del_alcance_no_tumba_la_ingesta(
            self, client, mock_requests, graph_token, monkeypatch):
        """Guardar los datos del reloj importa más que el correo. Misma regla que ya
        tenía el envío del resumen desde la ingesta."""
        estado = {"hay": False}
        noche_que_llega_tarde(mock_requests, estado)
        preparar(mock_requests, monkeypatch, salud=_salud_sin_la_noche_de_hoy())
        reloj(monkeypatch, 7, 15)
        client.post("/despertar?token=brief-token&fuente=cargador")
        reloj(monkeypatch, 10, 0)
        client.post("/ha/brief-tick?token=ha-poll-token")

        def _revienta(*a, **kw):
            raise RuntimeError("SMTP caído")

        monkeypatch.setattr(main, "enviar_correo", _revienta)
        reloj(monkeypatch, 10, 20)
        assert _llega_la_noche(client, estado).status_code == 200

    def test_un_parpadeo_de_supabase_no_gasta_el_alcance(
            self, client, mock_requests, graph_token, monkeypatch):
        """Reclamar el alcance va después de leer la noche, no antes: si no, un 500 de
        un segundo dejaría al día sin su correo para siempre."""
        estado = {"hay": False}
        noche_que_llega_tarde(mock_requests, estado)
        preparar(mock_requests, monkeypatch, salud=_salud_sin_la_noche_de_hoy())
        reloj(monkeypatch, 7, 15)
        client.post("/despertar?token=brief-token&fuente=cargador")
        reloj(monkeypatch, 10, 0)
        client.post("/ha/brief-tick?token=ha-poll-token")

        reloj(monkeypatch, 10, 20)
        estado["fallos"] = 1
        _llega_la_noche(client, estado)
        assert len(_SMTPFalso.enviados) == 1, "con Supabase caído no hay nada que mandar"

        _llega_la_noche(client, estado)
        assert len(_SMTPFalso.enviados) == 2, "y al siguiente intento sí sale"

    def test_se_puede_apagar(self, client, mock_requests, graph_token, monkeypatch):
        estado = {"hay": False}
        noche_que_llega_tarde(mock_requests, estado)
        preparar(mock_requests, monkeypatch, salud=_salud_sin_la_noche_de_hoy())
        monkeypatch.setattr(main, "BRIEF_ALCANCE_SUENO", False)
        reloj(monkeypatch, 7, 15)
        client.post("/despertar?token=brief-token&fuente=cargador")
        reloj(monkeypatch, 10, 0)
        client.post("/ha/brief-tick?token=ha-poll-token")

        reloj(monkeypatch, 10, 20)
        _llega_la_noche(client, estado)
        assert len(_SMTPFalso.enviados) == 1


class TestDondeEstaElAtasco:
    """El aviso de los 45 minutos pedía abrir la app del reloj, y eso solo es el consejo
    correcto la mitad de las veces: la cadena tiene cuatro etapas (pulsera → Zepp → app
    Salud → exportador → backend) y el aviso solo miraba el final. El 2026-09-22 salió
    después de sincronizar varias veces, pidiendo justo lo que ya se había hecho.
    """

    def _avisar_a_las_ocho(self, client, mock_requests, monkeypatch, escrituras):
        sueno_de_hoy(mock_requests, False)
        mock_requests.add("GET", "select=created_at,fuente", FakeResponse(escrituras))
        preparar(mock_requests, monkeypatch)
        avisos = []
        monkeypatch.setattr(main, "_apuntar_aviso",
                            lambda regla, texto, **kw: avisos.append((regla, texto)) or True)
        reloj(monkeypatch, 7, 15)
        client.post("/despertar?token=brief-token&fuente=cargador")
        reloj(monkeypatch, 8, 5)
        client.post("/ha/brief-tick?token=ha-poll-token")
        return [t for regla, t in avisos if regla == "reloj_sync"]

    def _utc(self, hora, minuto=0):
        return _a_las(hora, minuto).astimezone(main.timezone.utc).isoformat()

    def test_si_el_movil_ya_exporto_el_atasco_es_la_pulsera(
            self, client, mock_requests, graph_token, monkeypatch):
        """Exportó a las 07:50, después de levantarte, y la noche no venía dentro:
        abrir la app otra vez no arregla nada, el dato no ha salido de la pulsera."""
        textos = self._avisar_a_las_ocho(
            client, mock_requests, monkeypatch,
            [{"created_at": self._utc(7, 50), "fuente": "auto_export"}])

        assert len(textos) == 1
        assert "pulsera" in textos[0] and "Zepp" in textos[0]
        assert "15 min" in textos[0]

    def test_si_el_movil_no_exporta_el_atasco_es_el_exportador(
            self, client, mock_requests, graph_token, monkeypatch):
        """Al revés: con la noche ya en Salud pero el exportador parado, puedes
        sincronizar Zepp toda la mañana sin que llegue nada."""
        ayer = (_a_las(20, 0) - main.timedelta(days=1)).astimezone(main.timezone.utc)
        textos = self._avisar_a_las_ocho(
            client, mock_requests, monkeypatch,
            [{"created_at": ayer.isoformat(), "fuente": "auto_export"}])

        assert len(textos) == 1
        assert "exportador" in textos[0] and "auto_export" in textos[0]
        assert "pulsera" in textos[0], "hay que decir también lo que NO es"

    def test_sin_poder_preguntar_se_queda_el_consejo_de_siempre(
            self, client, mock_requests, graph_token, monkeypatch):
        """No poder mirar no es un diagnóstico. El aviso sale igual, sin inventarse
        dónde está el problema."""
        textos = self._avisar_a_las_ocho(client, mock_requests, monkeypatch, [])

        assert len(textos) == 1
        assert "Abre la app del reloj" in textos[0]

    def test_el_aviso_cabe_entero(self, client, mock_requests, graph_token, monkeypatch):
        """Los avisos se recortan a RECORDATORIO_MAX_TEXTO y lo último es el plazo: si
        el texto se pasa, lo que se pierde es lo que hay que hacer."""
        for escrituras in ([{"created_at": self._utc(7, 50), "fuente": "auto_export"}],
                           [{"created_at": self._utc(3, 0), "fuente": "auto_export"}],
                           []):
            main._olvidar_despertar()
            textos = self._avisar_a_las_ocho(client, mock_requests, monkeypatch, escrituras)
            assert len(textos[0]) <= main.RECORDATORIO_MAX_TEXTO, textos[0]
