"""Alarmas de respaldo: el aviso con botón, la escalada a la casa y el tope.

Lo que hay que proteger aquí no es que "suene": es que suene UNA vez (la reserva
atómica), que no suene donde no toca (fuera de casa) y que deje de sonar (el tope y la
confirmación). Un despertador que se equivoca en cualquiera de esas tres cosas es peor
que no tenerlo.
"""
from datetime import datetime, timedelta, timezone

import pytest

import main
from conftest import FakeResponse


HOY = datetime.now(main.LOCAL_TZ)


def _fila(minutos_desde_ahora=-1, estado="armada", intentos=0, etiqueta="Entrenar",
          avisado_hace_min=None, escalado_hace_min=None, rid="11111111-1111-1111-1111-111111111111"):
    """Una fila de `alarmas` tal y como la devuelve Supabase."""
    ahora  = datetime.now(timezone.utc)
    fila = {
        "id": rid,
        "cuando": (ahora + timedelta(minutes=minutos_desde_ahora)).isoformat(),
        "etiqueta": etiqueta, "estado": estado, "intentos": intentos,
        "avisado_at": None, "escalado_at": None,
    }
    if avisado_hace_min is not None:
        fila["avisado_at"] = (ahora - timedelta(minutes=avisado_hace_min)).isoformat()
    if escalado_hace_min is not None:
        fila["escalado_at"] = (ahora - timedelta(minutes=escalado_hace_min)).isoformat()
    return fila


@pytest.fixture
def canal_movil(monkeypatch):
    """El canal del móvil vivo, para que los avisos se encolen en vez de irse por SMTP."""
    monkeypatch.setattr(main, "AVISOS_MOVIL", True)
    main._ultimo_sondeo_avisos = main.time.time()
    return main._avisos_movil


def _reserva_ok(url, **kwargs):
    """El PATCH condicional que SÍ se lleva la fila (devuelve una)."""
    return FakeResponse([{"id": "11111111-1111-1111-1111-111111111111"}])


def _reserva_perdida(url, **kwargs):
    """El PATCH condicional que NO se lleva la fila: otro tick fue antes."""
    return FakeResponse([])


class TestPonerAlarma:
    def test_la_pone_y_devuelve_la_hora(self, mock_requests):
        mock_requests.add("GET", "/rest/v1/alarmas", FakeResponse([]))
        mock_requests.add("POST", "/rest/v1/alarmas", FakeResponse([{"id": "abc"}]))
        manana = (HOY + timedelta(days=1)).strftime("%Y-%m-%d")
        r = main._j_poner_alarma(manana, "08:30", "Entrenar")
        assert r["ok"] is True
        assert r["cuando"] == f"{manana} 08:30"
        assert r["etiqueta"] == "Entrenar"

    def test_una_hora_pasada_se_rechaza(self, mock_requests):
        ayer = (HOY - timedelta(days=1)).strftime("%Y-%m-%d")
        r = main._j_poner_alarma(ayer, "08:30")
        assert r["ok"] is False
        assert mock_requests.called("POST", "/rest/v1/alarmas") == []

    def test_formato_malo_se_rechaza(self):
        assert main._j_poner_alarma("mañana", "08:30")["ok"] is False
        assert main._j_poner_alarma("2030-01-01", "8:30")["ok"] is False

    def test_con_el_cupo_lleno_no_se_apunta(self, mock_requests):
        mock_requests.add("GET", "/rest/v1/alarmas",
                          FakeResponse([{"id": str(i)} for i in range(main.ALARMAS_MAX)]))
        manana = (HOY + timedelta(days=1)).strftime("%Y-%m-%d")
        r = main._j_poner_alarma(manana, "08:30")
        assert r["ok"] is False
        assert mock_requests.called("POST", "/rest/v1/alarmas") == []

    def test_ponerla_adelanta_el_reloj_del_tick(self, mock_requests):
        # Sin esto, una alarma para dentro de dos minutos no sonaría: el tick estaría
        # durmiendo hasta la hora que apuntó la última consulta.
        mock_requests.add("GET", "/rest/v1/alarmas", FakeResponse([]))
        mock_requests.add("POST", "/rest/v1/alarmas", FakeResponse([{"id": "abc"}]))
        main._alarma_siguiente = main.time.time() + 86400
        manana = (HOY + timedelta(days=1)).strftime("%Y-%m-%d")
        main._j_poner_alarma(manana, "08:30")
        assert main._alarma_siguiente < main.time.time() + 86400


class TestTickBarato:
    def test_sin_nada_pendiente_no_consulta_supabase(self, client, mock_requests):
        # El tick pasa 1.440 veces al día. Si cada una costara una consulta, el reloj
        # sería más caro que todo lo demás junto.
        main._alarma_siguiente = main.time.time() + 3600
        r = client.get("/ha/alarma-tick", headers={"X-Auth-Token": "ha-poll-token"})
        assert r.status_code == 200
        assert r.json()["escalar"] == 0
        assert mock_requests.called("GET", "/rest/v1/alarmas") == []

    def test_requiere_el_token_de_servicio(self, client):
        assert client.get("/ha/alarma-tick").status_code == 403
        assert client.get("/ha/alarma-tick", headers={"X-Auth-Token": "otro"}).status_code == 403

    def test_un_fallo_leyendo_no_tumba_el_tick(self, client, mock_requests):
        # Si contestara 500, HA marcaría el sensor no disponible y la automatización
        # dejaría de dispararse en silencio.
        mock_requests.add("GET", "/rest/v1/alarmas", FakeResponse([], 500))
        r = client.get("/ha/alarma-tick", headers={"X-Auth-Token": "ha-poll-token"})
        assert r.status_code == 200
        assert r.json()["escalar"] == 0


class TestPrimerAviso:
    def test_una_alarma_vencida_avisa_con_el_boton(self, mock_requests, canal_movil):
        mock_requests.add("GET", "/rest/v1/alarmas", FakeResponse([_fila(minutos_desde_ahora=-1)]))
        mock_requests.add("PATCH", "/rest/v1/alarmas", _reserva_ok)
        main._correr_alarmas()
        assert len(canal_movil) == 1
        aviso = canal_movil[0]
        assert "Entrenar" in aviso["texto"]
        # Un despertador que no suena con el móvil en silencio no despierta.
        assert aviso["critico"] is True
        assert aviso["acciones"] == [
            {"action": "LA_DESPIERTO_11111111-1111-1111-1111-111111111111",
             "title": "Estoy despierto"}]

    def test_todavia_no_es_la_hora_y_no_avisa(self, mock_requests, canal_movil):
        mock_requests.add("GET", "/rest/v1/alarmas", FakeResponse([_fila(minutos_desde_ahora=30)]))
        main._correr_alarmas()
        assert canal_movil == []
        assert mock_requests.called("PATCH", "/rest/v1/alarmas") == []

    def test_dos_ticks_solapados_avisan_una_sola_vez(self, mock_requests, canal_movil):
        # La condición `&estado=eq.armada` del PATCH ES la pregunta: quien no se lleve
        # la fila no manda nada. Con un GET previo, los dos avisarían.
        mock_requests.add("GET", "/rest/v1/alarmas", FakeResponse([_fila(minutos_desde_ahora=-1)]))
        mock_requests.add("PATCH", "/rest/v1/alarmas", _reserva_perdida)
        main._correr_alarmas()
        assert canal_movil == []

    def test_el_aviso_prepara_el_altavoz(self, mock_requests, canal_movil, monkeypatch):
        # Se prepara AL AVISAR y no al escalar porque órdenes y avisos son dos colas con
        # sondeos distintos: dos minutos de margen garantizan que el volumen esté puesto.
        monkeypatch.setattr(main, "ALARMA_ALTAVOZ", "media_player.cuarto")
        monkeypatch.setattr(main, "ALARMA_NO_MOLESTAR", "switch.no_molestar")
        mock_requests.add("GET", "/rest/v1/alarmas", FakeResponse([_fila(minutos_desde_ahora=-1)]))
        mock_requests.add("PATCH", "/rest/v1/alarmas", _reserva_ok)
        main._correr_alarmas()
        servicios = [(o["servicio"], o["entidad"]) for o in main._ha_ordenes]
        assert ("switch.turn_off", "switch.no_molestar") in servicios
        assert ("media_player.volume_set", "media_player.cuarto") in servicios


class TestEscalada:
    def test_a_los_dos_minutos_sin_confirmar_escala(self, mock_requests, canal_movil):
        mock_requests.add("GET", "/rest/v1/alarmas", FakeResponse(
            [_fila(minutos_desde_ahora=-3, estado="avisada", avisado_hace_min=3)]))
        mock_requests.add("PATCH", "/rest/v1/alarmas", _reserva_ok)
        salida = main._correr_alarmas()
        assert salida["escalar"] == 1
        assert salida["texto"] == "Entrenar"
        # Y se insiste también por el móvil, no solo por la casa.
        assert len(canal_movil) == 1

    def test_antes_de_los_dos_minutos_no_escala(self, mock_requests, canal_movil):
        mock_requests.add("GET", "/rest/v1/alarmas", FakeResponse(
            [_fila(minutos_desde_ahora=-1, estado="avisada", avisado_hace_min=1)]))
        salida = main._correr_alarmas()
        assert salida["escalar"] == 0
        assert canal_movil == []

    def test_fuera_de_casa_avisa_al_movil_pero_no_toca_la_casa(self, mock_requests,
                                                              canal_movil, monkeypatch):
        # En casa duerme más gente: si consta que no estás, el Echo no suena.
        monkeypatch.setattr(main, "presencia_vigente", lambda: {"en_casa": False})
        mock_requests.add("GET", "/rest/v1/alarmas", FakeResponse(
            [_fila(minutos_desde_ahora=-3, estado="avisada", avisado_hace_min=3)]))
        mock_requests.add("PATCH", "/rest/v1/alarmas", _reserva_ok)
        salida = main._correr_alarmas()
        assert salida["escalar"] == 0
        assert len(canal_movil) == 1

    def test_sin_saber_donde_estas_escala_igual(self, mock_requests, canal_movil, monkeypatch):
        # Un dato caducado no es un "no estás". Este respaldo existe para cuando lo demás
        # falla: callarse por no saber sería justo el fallo que viene a cubrir.
        monkeypatch.setattr(main, "presencia_vigente", lambda: None)
        mock_requests.add("GET", "/rest/v1/alarmas", FakeResponse(
            [_fila(minutos_desde_ahora=-3, estado="avisada", avisado_hace_min=3)]))
        mock_requests.add("PATCH", "/rest/v1/alarmas", _reserva_ok)
        assert main._correr_alarmas()["escalar"] == 1

    def test_insiste_contando_desde_la_ultima_escalada(self, mock_requests):
        # Ya escalada hace 3 minutos: toca otra vez, y el intento sube.
        mock_requests.add("GET", "/rest/v1/alarmas", FakeResponse(
            [_fila(minutos_desde_ahora=-8, estado="escalada", intentos=2,
                   avisado_hace_min=8, escalado_hace_min=3)]))
        mock_requests.add("PATCH", "/rest/v1/alarmas", _reserva_ok)
        assert main._correr_alarmas()["escalar"] == 3

    def test_recien_escalada_no_repite(self, mock_requests):
        mock_requests.add("GET", "/rest/v1/alarmas", FakeResponse(
            [_fila(minutos_desde_ahora=-6, estado="escalada", intentos=2,
                   avisado_hace_min=6, escalado_hace_min=1)]))
        assert main._correr_alarmas()["escalar"] == 0


class TestSeRinde:
    def test_pasado_el_tope_se_rinde_y_lo_dice(self, mock_requests, canal_movil):
        # Una alarma que deja de sonar sola y no lo cuenta es indistinguible de una que
        # nunca se armó, y eso es lo que hace que dejes de fiarte del respaldo.
        mock_requests.add("GET", "/rest/v1/alarmas", FakeResponse(
            [_fila(minutos_desde_ahora=-40, estado="escalada", intentos=15,
                   avisado_hace_min=main.ALARMA_MAX_MIN + 1, escalado_hace_min=2)]))
        mock_requests.add("PATCH", "/rest/v1/alarmas", _reserva_ok)
        salida = main._correr_alarmas()
        assert salida["escalar"] == 0
        assert len(canal_movil) == 1
        assert "insistir" in canal_movil[0]["titulo"]

    def test_al_rendirse_para_la_musica(self, mock_requests, canal_movil, monkeypatch):
        monkeypatch.setattr(main, "ALARMA_ALTAVOZ", "media_player.cuarto")
        mock_requests.add("GET", "/rest/v1/alarmas", FakeResponse(
            [_fila(minutos_desde_ahora=-40, estado="escalada", intentos=15,
                   avisado_hace_min=main.ALARMA_MAX_MIN + 1, escalado_hace_min=2)]))
        mock_requests.add("PATCH", "/rest/v1/alarmas", _reserva_ok)
        main._correr_alarmas()
        assert ("media_player.media_stop", "media_player.cuarto") in [
            (o["servicio"], o["entidad"]) for o in main._ha_ordenes]


class TestBotonDespierto:
    RUTA = "/alarmas/11111111-1111-1111-1111-111111111111/despierto"

    def test_confirma_y_para_la_musica(self, client, mock_requests, monkeypatch):
        monkeypatch.setattr(main, "ALARMA_ALTAVOZ", "media_player.cuarto")
        mock_requests.add("PATCH", "/rest/v1/alarmas", _reserva_ok)
        r = client.post(self.RUTA, headers={"X-Auth-Token": "ha-poll-token"})
        assert r.status_code == 200
        assert r.json() == {"ok": True, "hecho": True}
        assert ("media_player.media_stop", "media_player.cuarto") in [
            (o["servicio"], o["entidad"]) for o in main._ha_ordenes]

    def test_pulsarlo_dos_veces_no_es_un_error(self, client, mock_requests):
        mock_requests.add("PATCH", "/rest/v1/alarmas", _reserva_perdida)
        r = client.post(self.RUTA, headers={"X-Auth-Token": "ha-poll-token"})
        assert r.status_code == 200
        assert r.json()["hecho"] is False

    def test_lo_puede_pulsar_el_dashboard_con_su_jwt(self, client, mock_requests, auth_headers):
        mock_requests.add("PATCH", "/rest/v1/alarmas", _reserva_ok)
        assert client.post(self.RUTA, headers=auth_headers).status_code == 200

    def test_sin_credencial_no(self, client):
        assert client.post(self.RUTA).status_code == 403

    def test_el_id_tiene_que_ser_un_uuid(self, client):
        r = client.post("/alarmas/no-es-uuid/despierto", headers={"X-Auth-Token": "ha-poll-token"})
        assert r.status_code == 422


class TestEndpointsDelDashboard:
    def test_listar_pide_jwt(self, client):
        assert client.get("/alarmas").status_code in (401, 403)

    def test_listar_devuelve_las_activas_en_hora_local(self, client, mock_requests, auth_headers):
        mock_requests.add("GET", "/rest/v1/alarmas", FakeResponse([_fila(minutos_desde_ahora=60)]))
        r = client.get("/alarmas", headers=auth_headers)
        assert r.status_code == 200
        assert r.json()["alarmas"][0]["etiqueta"] == "Entrenar"
        assert r.json()["espera_min"] == main.ALARMA_ESPERA_MIN

    def test_crear_desde_el_dashboard(self, client, mock_requests, auth_headers):
        mock_requests.add("GET", "/rest/v1/alarmas", FakeResponse([]))
        mock_requests.add("POST", "/rest/v1/alarmas", FakeResponse([{"id": "abc"}]))
        manana = (HOY + timedelta(days=1)).strftime("%Y-%m-%d")
        r = client.post("/alarmas", headers=auth_headers,
                        json={"fecha": manana, "hora": "08:30", "etiqueta": "Entrenar"})
        assert r.status_code == 200
        assert r.json()["ok"] is True

    def test_crear_una_pasada_da_422(self, client, mock_requests, auth_headers):
        ayer = (HOY - timedelta(days=1)).strftime("%Y-%m-%d")
        r = client.post("/alarmas", headers=auth_headers, json={"fecha": ayer, "hora": "08:30"})
        assert r.status_code == 422

    def test_borrar_cancela_sin_borrar_la_fila(self, client, mock_requests, auth_headers):
        # Una alarma que sonó es parte de por qué la casa hizo ruido a las 8:32.
        mock_requests.add("PATCH", "/rest/v1/alarmas", _reserva_ok)
        r = client.delete("/alarmas/11111111-1111-1111-1111-111111111111", headers=auth_headers)
        assert r.status_code == 200
        assert r.json()["hecho"] is True
        assert mock_requests.called("DELETE", "/rest/v1/alarmas") == []
        enviado = mock_requests.called("PATCH", "/rest/v1/alarmas")[0][2]["json"]
        assert enviado == {"estado": "cancelada"}


class TestHerramientasDeJarvis:
    def test_estan_registradas(self):
        for nombre in ("poner_alarma", "mis_alarmas", "cancelar_alarma"):
            assert nombre in main._JARVIS_HERRAMIENTAS
            # Ninguna pide confirmación: poner una alarma no toca nada del mundo real, y
            # cancelarla es lo que quieres poder hacer deprisa cuando está sonando.
            assert main._JARVIS_HERRAMIENTAS[nombre]["confirmar"] is False

    def test_salen_en_el_esquema_que_ve_el_modelo(self):
        nombres = {f["function"]["name"] for f in main._jarvis_esquema()}
        assert {"poner_alarma", "mis_alarmas", "cancelar_alarma"} <= nombres

    def test_cancelar_con_un_id_que_no_es_uuid(self):
        assert main._j_cancelar_alarma("pepe")["ok"] is False
