"""Tests del control de la casa: la cola de órdenes que recoge Home Assistant y el
catálogo de dispositivos que HA empuja.

Aquí se prueba lo que el backend garantiza pase lo que pase al otro lado: que no salga
una orden de un dominio que no está en la lista blanca, que no se ejecute una orden vieja,
y que lo que abre cerraduras o persianas no lo dispare el modelo por su cuenta.
"""
import http.client
import logging
import socket
import threading
import time

import pytest
import requests
import urllib3

import main
from conftest import FakeResponse

CABECERA = {"X-Auth-Token": "ha-poll-token"}


def _con_catalogo(mock_requests, entidades):
    mock_requests.add("GET", "ha_entidades", FakeResponse([{"entidades": entidades}]))


class TestCatalogoDeLaCasa:
    def test_empujar_requiere_token(self, client):
        r = client.post("/ha/entidades", json={"entidades": []})
        assert r.status_code == 403

    def test_guarda_lo_que_manda_ha(self, client, mock_requests):
        r = client.post("/ha/entidades", headers=CABECERA, json={"entidades": [
            {"id": "light.salon", "nombre": "Salón", "estado": "off"},
            {"id": "switch.cafetera", "nombre": "Cafetera", "estado": "on"},
        ]})
        assert r.status_code == 200
        assert r.json()["guardadas"] == 2
        guardado = mock_requests.called("POST", "ha_entidades")[0][2]["json"]
        assert [e["id"] for e in guardado["entidades"]] == ["light.salon", "switch.cafetera"]

    def test_descarta_los_ids_con_forma_rara(self, client, mock_requests):
        r = client.post("/ha/entidades", headers=CABECERA, json={"entidades": [
            {"id": "light.salon"},
            {"id": "esto no es una entidad"},
        ]})
        assert r.json() == {"ok": True, "guardadas": 1, "descartadas": 1}

    def test_sin_catalogo_lo_dice_en_vez_de_callar(self, mock_requests):
        """Si Jarvis no sabe qué hay, tiene que decirlo: el hueco que deja un 'no lo sé'
        se rellena con nombres inventados."""
        r = main._j_casa_dispositivos()
        assert r["dispositivos"] == []
        assert "no ha mandado" in r["nota"]

    def test_el_filtro_acota_la_lista(self, mock_requests):
        _con_catalogo(mock_requests, [
            {"id": "light.salon", "nombre": "Luz del salón"},
            {"id": "light.cocina", "nombre": "Luz de la cocina"},
            {"id": "switch.tele", "nombre": "Tele"},
        ])
        r = main._j_casa_dispositivos("salon")
        assert [d["id"] for d in r["dispositivos"]] == ["light.salon"]

    def test_un_filtro_sin_coincidencias_devuelve_los_ids(self, mock_requests):
        _con_catalogo(mock_requests, [{"id": "light.salon", "nombre": "Luz del salón"}])
        r = main._j_casa_dispositivos("garaje")
        assert r["dispositivos"] == []
        assert "light.salon" in r["nota"]


class TestOrdenesDeLaCasa:
    def test_recoger_requiere_token(self, client):
        assert client.get("/ha/ordenes-pending").status_code == 403

    def test_encola_y_ha_la_recoge_una_sola_vez(self, client, mock_requests):
        _con_catalogo(mock_requests, [{"id": "light.salon", "nombre": "Salón"}])
        assert main._j_casa_ordenar("light.turn_on", "light.salon")["ok"] is True

        r = client.get("/ha/ordenes-pending", headers=CABECERA)
        assert r.json()["ordenes"] == [
            {"servicio": "light.turn_on", "entidad": "light.salon", "datos": {}}]
        # La cola se vacía al recogerla, igual que el flag del WOL.
        assert client.get("/ha/ordenes-pending", headers=CABECERA).json()["ordenes"] == []

    def test_una_orden_vieja_no_se_ejecuta(self, client, mock_requests):
        """Si HA estuvo caído dos horas, al volver no puede ponerse a encender lo que
        pediste al mediodía. Misma regla que hace caducar la presencia."""
        _con_catalogo(mock_requests, [{"id": "light.salon"}])
        main._j_casa_ordenar("light.turn_on", "light.salon")
        main._ha_ordenes[0]["pedida"] = time.time() - main.CASA_ORDEN_TTL - 1
        assert client.get("/ha/ordenes-pending", headers=CABECERA).json()["ordenes"] == []

    def test_rechaza_los_dominios_que_no_estan_en_la_lista(self, mock_requests):
        """La orden acaba en un service call de HA, donde shell_command es mucho más que
        una luz."""
        _con_catalogo(mock_requests, [{"id": "light.salon"}])
        r = main._j_casa_ordenar("shell_command.borrar_todo", "light.salon")
        assert r["ok"] is False
        assert main._ha_ordenes == []

    def test_rechaza_una_entidad_que_no_existe(self, mock_requests):
        """Con catálogo delante, una entidad que no está en él es una invención."""
        _con_catalogo(mock_requests, [{"id": "light.salon"}])
        r = main._j_casa_ordenar("light.turn_on", "light.inventada")
        assert r["ok"] is False
        assert main._ha_ordenes == []

    def test_rechaza_un_servicio_con_forma_rara(self, mock_requests):
        assert main._j_casa_ordenar("enciende la luz", "light.salon")["ok"] is False

    def test_limpia_los_datos_del_servicio(self, mock_requests):
        """Los redacta un modelo y viajan hasta HA: solo escalares y con nombre válido."""
        _con_catalogo(mock_requests, [{"id": "light.salon"}])
        main._j_casa_ordenar("light.turn_on", "light.salon", {
            "brightness_pct": 40,
            "Nombre Raro": "x",
            "anidado": {"no": "pasa"},
        })
        assert main._ha_ordenes[0]["datos"] == {"brightness_pct": 40}

    def test_los_datos_no_cambian_a_que_se_le_da_la_orden(self, mock_requests):
        """HA mezcla `datos` con el `target`, y gana lo de `datos`. Con un `area_id` o un
        `entity_id` ahí, una orden de luz —directa, sin botón— acababa abriendo el garaje."""
        _con_catalogo(mock_requests, [{"id": "light.salon"}])
        main._j_casa_ordenar("homeassistant.turn_on", "light.salon", {
            "entity_id": "cover.garaje", "area_id": "garaje", "device_id": "abc",
            "label_id": "x", "floor_id": "planta_baja", "brightness_pct": 40,
        })
        assert main._ha_ordenes[0]["entidad"] == "light.salon"
        assert main._ha_ordenes[0]["datos"] == {"brightness_pct": 40}


class TestFronteraDeLaCasa:
    def test_una_luz_es_como_pulsar_el_interruptor(self):
        assert main._casa_pide_confirmar(
            {"servicio": "light.turn_on", "entidad": "light.salon"}) is False
        assert main._casa_pide_confirmar(
            {"servicio": "switch.turn_off", "entidad": "switch.enchufe"}) is False
        assert main._casa_pide_confirmar(
            {"servicio": "homeassistant.toggle", "entidad": "light.salon"}) is False

    def test_cerraduras_persianas_y_alarmas_las_confirma_el_usuario(self):
        for servicio, entidad in (("lock.unlock", "lock.puerta"),
                                  ("cover.open_cover", "cover.garaje"),
                                  ("alarm_control_panel.alarm_disarm",
                                   "alarm_control_panel.casa")):
            assert main._casa_pide_confirmar(
                {"servicio": servicio, "entidad": entidad}) is True

    def test_el_servicio_generico_no_abre_el_garaje_sin_boton(self):
        """`homeassistant.toggle` lo traduce HA al dominio de la entidad: sobre una
        persiana o una cerradura es abrirla, y eso lo aprueba una persona."""
        for entidad in ("cover.garaje", "lock.puerta", "alarm_control_panel.casa"):
            for servicio in ("homeassistant.toggle", "homeassistant.turn_on",
                             "homeassistant.turn_off"):
                assert main._casa_pide_confirmar(
                    {"servicio": servicio, "entidad": entidad}) is True

    def test_ante_la_duda_se_confirma(self):
        """Un servicio desconocido no puede colarse por la vía directa."""
        assert main._casa_pide_confirmar({}) is True
        assert main._casa_pide_confirmar({"servicio": "loquesea.hacer"}) is True


class TestElRastroDeLaCasa:
    """Lo que se le pidió a la casa, con su hora.

    La cola (`_ha_ordenes`) se vacía en cuanto HA la sirve, y eso dejaba el carril «Casa»
    de la línea del día sin absolutamente nada que dibujar: media hora después de
    encender una luz no había forma de saber que se encendió.
    """

    def test_encolar_una_orden_deja_constancia(self, mock_requests):
        apuntado = {}

        def _post(url, **kwargs):
            apuntado["fila"] = kwargs.get("json")
            return FakeResponse({}, 201)

        _con_catalogo(mock_requests, [{"id": "light.salon"}])
        mock_requests.add("POST", "/casa_acciones", _post)

        main._j_casa_ordenar("light.turn_on", "light.salon")

        assert apuntado["fila"]["servicio"] == "light.turn_on"
        assert apuntado["fila"]["entidad"] == "light.salon"

    def test_una_orden_rechazada_no_deja_rastro(self, mock_requests):
        """El apunte va DESPUÉS de las validaciones: lo que no se encoló no pasó."""
        llamadas = []
        _con_catalogo(mock_requests, [{"id": "light.salon"}])
        mock_requests.add("POST", "/casa_acciones",
                          lambda url, **kw: llamadas.append(1) or FakeResponse({}, 201))

        assert main._j_casa_ordenar("shell_command.turn_on", "light.salon")["ok"] is False
        assert main._j_casa_ordenar("light.turn_on", "light.inventada")["ok"] is False
        assert llamadas == []

    def test_si_no_se_puede_apuntar_la_orden_sale_igual(self, mock_requests):
        """El registro es para mirar; la orden es para que pase algo. Si Supabase está
        caído, lo que no puede fallar es lo segundo."""
        _con_catalogo(mock_requests, [{"id": "light.salon"}])
        mock_requests.add("POST", "/casa_acciones", FakeResponse({}, 500))

        assert main._j_casa_ordenar("light.turn_on", "light.salon")["ok"] is True

    def test_leer_las_acciones_pide_jwt_y_valida_el_dia(self, client, auth_headers):
        assert client.get("/casa/acciones").status_code == 401
        assert client.get("/casa/acciones?dia=ayer", headers=auth_headers).status_code == 400

    def test_los_tramos_de_presencia_piden_jwt_y_validan_el_dia(self, client, auth_headers):
        assert client.get("/presencia/tramos").status_code == 401
        assert client.get("/presencia/tramos?dia=2026-13", headers=auth_headers).status_code == 400


# ── El widget «Casa» del dashboard ──────────────────────────────────────────────

CATALOGO = [
    {"id": "light.salon", "nombre": "Salón", "estado": "off"},
    {"id": "light.cocina", "nombre": "Cocina", "estado": "on"},
    {"id": "fan.techo", "nombre": "Ventilador", "estado": "off"},
    {"id": "switch.alexa_no_molestar", "nombre": "No molestar", "estado": "on"},
    {"id": "switch.pc", "nombre": "PC", "estado": "on"},
    {"id": "scene.cine", "nombre": "Cine", "estado": "2026-09-27T20:00:00+00:00"},
    {"id": "lock.puerta", "nombre": "Puerta", "estado": "locked"},
    {"id": "cover.garaje", "nombre": "Garaje", "estado": "closed"},
    {"id": "climate.salon", "nombre": "Termostato", "estado": "heat"},
    {"id": "alarm_control_panel.x", "nombre": "Alarma", "estado": "armed_away"},
]


def _hace(minutos):
    from datetime import datetime, timedelta, timezone
    return (datetime.now(timezone.utc) - timedelta(minutes=minutos)).isoformat()


def _con_catalogo_fechado(mock_requests, entidades, actualizado):
    mock_requests.add("GET", "ha_entidades", FakeResponse(
        [{"entidades": entidades, "actualizado": actualizado}]))


def _pedir(client, auth_headers, entidad, accion, **extra):
    return client.post("/casa/orden", headers=auth_headers,
                       json={"entidad": entidad, "accion": accion, **extra})


class TestEstadoDeLaCasa:
    def test_pide_jwt(self, client):
        assert client.get("/casa/estado").status_code == 401
        assert client.post("/casa/orden", json={"entidad": "light.salon",
                                                 "accion": "encender"}).status_code == 401

    def test_sin_catalogo_es_un_estado_vacio(self, client, auth_headers, mock_requests):
        """Que HA no lo haya mandado todavía no es un error: el widget lo dice y ya."""
        r = client.get("/casa/estado", headers=auth_headers)
        assert r.status_code == 200
        d = r.json()
        assert d["catalogo"]["conocido"] is False
        assert d["entidades"] == [] and d["sugeridas"] == []
        assert d["presencia"] == {"conocida": False}

    def test_edad_dominios_y_pc_de_solo_lectura(self, client, auth_headers, mock_requests,
                                                monkeypatch):
        monkeypatch.setattr(main, "PC_ENTIDAD", "switch.pc")
        _con_catalogo_fechado(mock_requests, CATALOGO, _hace(30))
        d = client.get("/casa/estado", headers=auth_headers).json()
        assert d["catalogo"]["conocido"] is True
        assert d["catalogo"]["total"] == len(CATALOGO)
        assert d["catalogo"]["actualizado"].endswith("Z")
        assert 29 <= d["catalogo"]["edad_min"] <= 31
        ids = {e["id"] for e in d["entidades"]}
        # Lo que necesita parámetros o un código no se puede pedir con un toque.
        assert "climate.salon" not in ids and "alarm_control_panel.x" not in ids
        assert {"light.salon", "scene.cine", "lock.puerta", "cover.garaje"} <= ids
        pc = next(e for e in d["entidades"] if e["id"] == "switch.pc")
        assert pc["solo_lectura"] is True
        salon = next(e for e in d["entidades"] if e["id"] == "light.salon")
        assert salon == {"id": "light.salon", "nombre": "Salón", "estado": "off",
                         "dominio": "light", "solo_lectura": False}

    def test_la_presencia_tiene_la_forma_de_get_presencia(self, client, auth_headers,
                                                          mock_requests):
        """Una sola petición para el widget, y la misma respuesta que ya conocía el panel."""
        mock_requests.add("GET", "/rest/v1/presence", FakeResponse([{
            "zona": "home", "en_casa": True, "updated_at": _hace(3)}]))
        d = client.get("/casa/estado", headers=auth_headers).json()
        assert d["presencia"] == client.get("/presencia", headers=auth_headers).json()
        assert d["presencia"]["en_casa"] is True and d["presencia"]["vigente"] is True

    def test_sugeridas_salen_de_la_lista_blanca_sin_el_pc(self, client, auth_headers,
                                                          mock_requests, monkeypatch):
        monkeypatch.setattr(main, "PC_ENTIDAD", "switch.pc")
        monkeypatch.setattr(main, "SALIR_CASA_ENTIDADES",
                            ("light.cocina", "switch.pc", "light.inventada", "fan.techo"))
        _con_catalogo(mock_requests, CATALOGO)
        d = client.get("/casa/estado", headers=auth_headers).json()
        assert d["sugeridas"] == ["light.cocina", "fan.techo"]

    def test_sin_lista_blanca_caen_a_luces_y_ventiladores_nunca_switch(
            self, client, auth_headers, mock_requests, monkeypatch):
        """Un switch por dominio es casi siempre un ajuste de una Alexa."""
        monkeypatch.setattr(main, "SALIR_CASA_ENTIDADES", ())
        muchas = [{"id": f"light.l{i}", "nombre": f"L{i}", "estado": "off"} for i in range(10)]
        _con_catalogo(mock_requests, [{"id": "switch.alexa_no_molestar"}, *muchas])
        d = client.get("/casa/estado", headers=auth_headers).json()
        assert len(d["sugeridas"]) == 8
        assert all(s.split(".")[0] in ("light", "fan") for s in d["sugeridas"])

    def test_empujar_el_catalogo_actualiza_la_edad(self, client, auth_headers, mock_requests):
        _con_catalogo_fechado(mock_requests, CATALOGO, _hace(120))
        assert client.get("/casa/estado", headers=auth_headers).json()["catalogo"]["edad_min"] >= 119
        client.post("/ha/entidades", headers=CABECERA, json={"entidades": CATALOGO[:2]})
        d = client.get("/casa/estado", headers=auth_headers).json()
        assert d["catalogo"]["edad_min"] == 0
        assert d["catalogo"]["total"] == 2

    def test_una_fecha_ilegible_no_rompe_nada(self):
        main._ha_entidades_actualizado = "ayer por la tarde"
        assert main._casa_edad_catalogo_min() is None
        main._ha_entidades_actualizado = None
        assert main._casa_edad_catalogo_min() is None


class TestOrdenDesdeElDashboard:
    def test_encender_encola_y_apunta_el_origen(self, client, auth_headers, mock_requests):
        apuntado = {}

        def _post(url, **kwargs):
            apuntado["fila"] = kwargs.get("json")
            return FakeResponse({}, 201)

        _con_catalogo(mock_requests, CATALOGO)
        mock_requests.add("POST", "/casa_acciones", _post)
        antes = main._boca_actual.get()

        r = _pedir(client, auth_headers, "light.salon", "encender")

        assert r.status_code == 200
        orden = r.json()["orden"]
        assert orden["servicio"] == "light.turn_on" and orden["estado"] == "en_cola"
        assert orden["pedida"].endswith("Z") and orden["id"]
        assert [(o["servicio"], o["entidad"]) for o in main._ha_ordenes] == [
            ("light.turn_on", "light.salon")]
        assert apuntado["fila"]["origen"] == "dashboard"
        assert main._boca_actual.get() == antes

    def test_la_accion_tiene_que_ser_del_dominio(self, client, auth_headers, mock_requests):
        _con_catalogo(mock_requests, CATALOGO)
        r = _pedir(client, auth_headers, "light.salon", "activar")
        assert r.status_code == 400
        assert r.json()["detail"] == "Esa acción no vale para ese dispositivo"
        assert main._ha_ordenes == []

    def test_no_se_puede_pedir_un_servicio_a_mano(self, client, auth_headers, mock_requests):
        """El cliente manda una acción de una lista cerrada, nunca el servicio."""
        _con_catalogo(mock_requests, CATALOGO)
        assert _pedir(client, auth_headers, "light.salon", "toggle").status_code == 422
        assert _pedir(client, auth_headers, "light.salon", "light.turn_on").status_code == 422
        assert main._ha_ordenes == []

    def test_cerraduras_y_persianas_piden_confirmacion(self, client, auth_headers,
                                                       mock_requests):
        _con_catalogo(mock_requests, CATALOGO)
        for entidad, accion in (("lock.puerta", "desbloquear"), ("cover.garaje", "abrir")):
            r = _pedir(client, auth_headers, entidad, accion)
            assert r.status_code == 409
            assert r.json()["detail"].startswith("Hay que confirmar: ")
        assert r.json()["detail"] == "Hay que confirmar: abrir Garaje"
        assert main._ha_ordenes == []

        r = _pedir(client, auth_headers, "cover.garaje", "abrir", confirmado=True)
        assert r.status_code == 200
        r = _pedir(client, auth_headers, "lock.puerta", "bloquear", confirmado=True)
        assert r.status_code == 200
        assert [o["servicio"] for o in main._ha_ordenes] == ["cover.open_cover", "lock.lock"]

    def test_fuera_del_catalogo_es_404(self, client, auth_headers, mock_requests):
        _con_catalogo(mock_requests, CATALOGO)
        r = _pedir(client, auth_headers, "light.inventada", "encender")
        assert r.status_code == 404
        # No el texto dirigido a Jarvis, que menciona su herramienta.
        assert "casa_dispositivos" not in r.json()["detail"]
        assert main._ha_ordenes == []

    def test_el_pc_no_se_apaga_desde_aqui(self, client, auth_headers, mock_requests,
                                          monkeypatch):
        monkeypatch.setattr(main, "PC_ENTIDAD", "switch.pc")
        _con_catalogo(mock_requests, CATALOGO)
        r = _pedir(client, auth_headers, "switch.pc", "apagar")
        assert r.status_code == 400
        assert r.json()["detail"] == "El PC no se apaga desde aquí: se suspende"
        assert main._ha_ordenes == []

    def test_una_entidad_con_forma_rara_es_400(self, client, auth_headers, mock_requests):
        assert _pedir(client, auth_headers, "light.salon; rm", "encender").status_code == 400
        assert main._ha_ordenes == []


class TestAcuseDeLasOrdenes:
    """«Pedido…», «HA la recogió» o «no se ejecutó»: lo que la ficha dice de una orden.

    La cola se vacía al servirla, así que el acuse vive aparte (`_ha_ordenes_hist`) y lo
    que recibe HA no cambia.
    """

    def _orden(self, **extra):
        return {"id": "x", "servicio": "light.turn_on", "entidad": "light.salon",
                "pedida": 1000.0, "recogida": None, "caducada": False, **extra}

    def test_en_cola_y_caducada_por_ttl(self):
        o = self._orden()
        assert main._estado_orden_casa(o, None, None, 1000.0 + 5) == "en_cola"
        assert main._estado_orden_casa(o, None, None,
                                       1000.0 + main.CASA_ORDEN_TTL + 1) == "caducada"

    def test_confirmada_solo_con_un_catalogo_posterior_que_coincide(self):
        o = self._orden(recogida=1010.0)
        encendida = {"id": "light.salon", "estado": "on"}
        assert main._estado_orden_casa(o, encendida, 1020.0, 1030.0) == "confirmada"
        # Un catálogo de ANTES de la recogida dice cómo estaba la casa, no qué pasó.
        assert main._estado_orden_casa(o, encendida, 1005.0, 1030.0) == "recogida"
        assert main._estado_orden_casa(o, {"estado": "off"}, 1020.0, 1030.0) == "recogida"
        assert main._estado_orden_casa(o, None, 1020.0, 1030.0) == "recogida"

    def test_lo_que_no_tiene_estado_se_queda_en_recogida(self):
        for servicio in ("scene.turn_on", "script.turn_on", "media_player.media_play_pause"):
            o = self._orden(servicio=servicio, recogida=1010.0)
            assert main._estado_orden_casa(o, {"estado": "on"}, 1020.0, 1030.0) == "recogida"

    def test_cerraduras_y_persianas(self):
        o = self._orden(servicio="cover.open_cover", recogida=1010.0)
        assert main._estado_orden_casa(o, {"estado": "opening"}, 1020.0, 1030.0) == "confirmada"
        o = self._orden(servicio="lock.lock", recogida=1010.0)
        assert main._estado_orden_casa(o, {"estado": "locked"}, 1020.0, 1030.0) == "confirmada"

    def test_recogida_tras_servir_la_cola(self, client, auth_headers, mock_requests):
        _con_catalogo(mock_requests, CATALOGO)
        _pedir(client, auth_headers, "light.salon", "encender")
        estado = client.get("/casa/estado", headers=auth_headers).json()
        assert [o["estado"] for o in estado["ordenes"]] == ["en_cola"]

        servidas = client.get("/ha/ordenes-pending", headers=CABECERA).json()["ordenes"]
        # Lo que recibe HA no cambia: ni `id` ni nada del acuse.
        assert servidas == [{"servicio": "light.turn_on", "entidad": "light.salon", "datos": {}}]

        estado = client.get("/casa/estado", headers=auth_headers).json()
        assert [o["estado"] for o in estado["ordenes"]] == ["recogida"]

    def test_confirmada_cuando_llega_el_catalogo(self, client, auth_headers, mock_requests):
        _con_catalogo(mock_requests, CATALOGO)
        _pedir(client, auth_headers, "light.salon", "encender")
        client.get("/ha/ordenes-pending", headers=CABECERA)
        # El catálogo tiene que llegar DESPUÉS de la recogida; en un test van en el mismo
        # instante, así que se echa la recogida un poco atrás.
        main._ha_ordenes_hist[-1]["recogida"] -= 5
        client.post("/ha/entidades", headers=CABECERA, json={"entidades": [
            {"id": "light.salon", "nombre": "Salón", "estado": "on"}]})
        estado = client.get("/casa/estado", headers=auth_headers).json()
        assert [o["estado"] for o in estado["ordenes"]] == ["confirmada"]

    def test_caducada_si_ha_no_la_recoge_a_tiempo(self, client, auth_headers, mock_requests):
        _con_catalogo(mock_requests, CATALOGO)
        _pedir(client, auth_headers, "light.salon", "encender")
        main._ha_ordenes[0]["pedida"] -= main.CASA_ORDEN_TTL + 1
        main._ha_ordenes_hist[-1]["pedida"] -= main.CASA_ORDEN_TTL + 1
        assert client.get("/ha/ordenes-pending", headers=CABECERA).json()["ordenes"] == []
        assert main._ha_ordenes_hist[-1]["caducada"] is True
        estado = client.get("/casa/estado", headers=auth_headers).json()
        assert [o["estado"] for o in estado["ordenes"]] == ["caducada"]

    def test_caducada_si_la_cola_se_desborda(self, mock_requests):
        """Con la cola llena se tira la más vieja: esa orden se ha perdido y hay que
        poder decirlo."""
        _con_catalogo(mock_requests, CATALOGO)
        primera = main._j_casa_ordenar("light.turn_on", "light.salon")["id"]
        for _ in range(main.CASA_MAX_ORDENES):
            main._j_casa_ordenar("light.turn_off", "light.cocina")
        hist = {h["id"]: h for h in main._ha_ordenes_hist}
        assert main._estado_orden_casa(hist[primera], None, None, time.time()) == "caducada"
        assert primera not in {o["id"] for o in main._ha_ordenes}

    def test_sin_ha_en_directo_la_cola_no_anula_nada(self, client, mock_requests):
        """Sin HA_URL/HA_TOKEN hay un solo motor: el Green ejecuta en orden todo lo que se
        pidió. El modo y la temperatura del termostato hacen falta los dos."""
        assert main._ha_directo() is False
        _con_catalogo(mock_requests, CATALOGO)
        main._j_casa_ordenar("climate.set_hvac_mode", "climate.salon", {"hvac_mode": "heat"})
        main._j_casa_ordenar("climate.set_temperature", "climate.salon", {"temperature": 21})
        servidas = client.get("/ha/ordenes-pending", headers=CABECERA).json()["ordenes"]
        assert [(o["servicio"], o["datos"]) for o in servidas] == [
            ("climate.set_hvac_mode", {"hvac_mode": "heat"}),
            ("climate.set_temperature", {"temperature": 21})]

    def test_las_ordenes_de_jarvis_tambien_llevan_acuse(self, mock_requests):
        _con_catalogo(mock_requests, CATALOGO)
        r = main._j_casa_ordenar("light.turn_on", "light.salon")
        assert r["ok"] is True and len(r["id"]) == 12
        assert main._ha_ordenes_hist[-1]["id"] == r["id"]


# ── Home Assistant en directo ────────────────────────────────────────────────────

HA = "http://ha.test:8123"
HA_SECRETO = "ha-directo-secreto-de-prueba"


def _estados_ha(**estados):
    """La forma real de GET /api/states: una lista de objetos con entity_id y state.
    Los ids van con `__` en vez de punto porque son nombres de argumento."""
    return FakeResponse([{"entity_id": eid.replace("__", "."), "state": st,
                          "attributes": {}} for eid, st in estados.items()])


def _a_ha(mock_requests, metodo=None):
    return [c for c in mock_requests.calls
            if c[1].startswith(HA) and (metodo is None or c[0] == metodo)]


def _lanza(excepcion):
    def _r(url, **kwargs):
        raise excepcion
    return _r


def _no_conecta(causa=None):
    """Lo que lanza `requests` cuando no pudo ni abrir la conexión: un ConnectionError con
    el MaxRetryError de urllib3 dentro, y como `reason` el fallo al conectar."""
    causa = causa or urllib3.exceptions.NewConnectionError(
        None, "Failed to establish a new connection: [Errno 111] Connection refused")
    return requests.exceptions.ConnectionError(
        urllib3.exceptions.MaxRetryError(None, "/api/services/x/y", reason=causa))


def _cortada():
    """Lo que lanza `requests` cuando la petición salió y HA cerró sin contestar."""
    return requests.exceptions.ConnectionError(urllib3.exceptions.ProtocolError(
        "Connection aborted.",
        http.client.RemoteDisconnected("Remote end closed connection without response")))


@pytest.fixture
def directo(monkeypatch):
    monkeypatch.setattr(main, "HA_URL", HA)
    monkeypatch.setattr(main, "HA_TOKEN", HA_SECRETO)


class TestCasaEnDirecto:
    """Con el backend en la LAN del Green, el estado se le pregunta a HA y las órdenes se
    le mandan en el acto. El catálogo y la cola siguen ahí: son el camino de vuelta."""

    # — Sin configurar, lo de siempre —

    def test_sin_token_no_se_llama_a_ha(self, client, auth_headers, mock_requests,
                                        monkeypatch):
        monkeypatch.setattr(main, "HA_URL", HA)   # URL sin token: sigue sin haber directo
        _con_catalogo_fechado(mock_requests, CATALOGO, _hace(30))
        d = client.get("/casa/estado", headers=auth_headers).json()
        assert d["fuente"] == "catalogo" and d["ha_directo"] is False
        assert 1790 <= d["edad_s"] <= 1810
        r = _pedir(client, auth_headers, "fan.techo", "encender").json()
        assert r["directa"] is False and r["orden"]["estado"] == "en_cola"
        assert [o["entidad"] for o in main._ha_ordenes] == ["fan.techo"]
        assert _a_ha(mock_requests) == []

    def test_una_url_sin_esquema_no_cuenta(self, monkeypatch):
        monkeypatch.setattr(main, "HA_URL", "ha.test:8123")
        monkeypatch.setattr(main, "HA_TOKEN", HA_SECRETO)
        assert main._ha_directo() is False

    # — El estado —

    def test_el_estado_sale_de_ha_y_no_del_catalogo(self, client, auth_headers,
                                                    mock_requests, directo):
        """El caso que lo trajo: el catálogo decía «apagado» de un ventilador encendido."""
        _con_catalogo_fechado(mock_requests, CATALOGO, _hace(50))
        mock_requests.add("GET", f"{HA}/api/states", _estados_ha(
            fan__techo="on", light__salon="off", light__cocina="off"))
        d = client.get("/casa/estado", headers=auth_headers).json()
        assert d["fuente"] == "vivo" and d["ha_directo"] is True and d["edad_s"] == 0
        por_id = {e["id"]: e for e in d["entidades"]}
        assert por_id["fan.techo"]["estado"] == "on"
        assert por_id["light.cocina"]["estado"] == "off"
        # Lo que HA ya no conoce no hereda el estado viejo del catálogo.
        assert por_id["lock.puerta"]["estado"] == "unavailable"
        # El catálogo sigue diciendo QUÉ hay y cómo se llama.
        assert por_id["fan.techo"]["nombre"] == "Ventilador"
        (_, url, kwargs), = _a_ha(mock_requests)
        assert url == f"{HA}/api/states"
        assert kwargs["headers"]["Authorization"] == f"Bearer {HA_SECRETO}"
        assert kwargs["timeout"] == main._HA_TIMEOUT_ESTADOS

    def test_varios_refrescos_seguidos_son_una_sola_pregunta(self, client, auth_headers,
                                                             mock_requests, directo):
        _con_catalogo(mock_requests, CATALOGO)
        mock_requests.add("GET", f"{HA}/api/states", _estados_ha(fan__techo="on"))
        for _ in range(3):
            client.get("/casa/estado", headers=auth_headers)
        assert len(_a_ha(mock_requests)) == 1
        # Pasada la caché, se vuelve a preguntar.
        main._ha_vivo["ts"] -= main.HA_VIVO_CACHE_S + 1
        client.get("/casa/estado", headers=auth_headers)
        assert len(_a_ha(mock_requests)) == 2

    def test_ha_caido_cae_al_catalogo_y_lo_dice(self, client, auth_headers, mock_requests,
                                                directo):
        _con_catalogo_fechado(mock_requests, CATALOGO, _hace(50))
        mock_requests.add("GET", f"{HA}/api/states",
                          _lanza(requests.exceptions.ConnectTimeout("sin ruta")))
        d = client.get("/casa/estado", headers=auth_headers).json()
        assert d["fuente"] == "catalogo" and d["ha_directo"] is True
        assert d["edad_s"] >= 2990
        assert next(e for e in d["entidades"] if e["id"] == "fan.techo")["estado"] == "off"
        # Un HA caído no se vuelve a esperar en cada refresco.
        client.get("/casa/estado", headers=auth_headers)
        assert len(_a_ha(mock_requests)) == 1
        # Pasado el rato, se le vuelve a preguntar.
        main._ha_vivo["fallo_ts"] -= main.HA_VIVO_FALLO_S + 1
        client.get("/casa/estado", headers=auth_headers)
        assert len(_a_ha(mock_requests)) == 2

    def test_un_error_de_ha_tambien_cae_al_catalogo(self, client, auth_headers,
                                                    mock_requests, directo):
        _con_catalogo(mock_requests, CATALOGO)
        mock_requests.add("GET", f"{HA}/api/states",
                          FakeResponse({"message": "detalle interno de HA"}, 500))
        r = client.get("/casa/estado", headers=auth_headers)
        assert r.json()["fuente"] == "catalogo"
        assert "detalle interno" not in r.text

    def test_jarvis_tambien_ve_el_estado_de_ahora(self, mock_requests, directo):
        _con_catalogo(mock_requests, CATALOGO)
        mock_requests.add("GET", f"{HA}/api/states", _estados_ha(fan__techo="on"))
        r = main._j_casa_dispositivos("ventilador")
        assert r["dispositivos"][0]["estado"] == "on"
        assert "ahora mismo" in r["estados"]

    # — Las órdenes —

    def test_la_orden_va_directa_y_no_se_encola(self, client, auth_headers, mock_requests,
                                                directo, caplog):
        caplog.set_level(logging.DEBUG)
        _con_catalogo(mock_requests, CATALOGO)
        # La respuesta real de HA: los estados que cambiaron durante la llamada.
        mock_requests.add("POST", f"{HA}/api/services/fan/turn_on",
                          FakeResponse([{"entity_id": "fan.techo", "state": "on"}], 200))

        r = _pedir(client, auth_headers, "fan.techo", "encender")

        assert r.status_code == 200
        cuerpo = r.json()
        assert cuerpo["directa"] is True and cuerpo["estado_entidad"] == "on"
        assert cuerpo["orden"]["estado"] == "hecha"
        # Si se encolara también, el Green la ejecutaría otra vez al sondear.
        assert main._ha_ordenes == []
        (_, url, kwargs), = _a_ha(mock_requests, "POST")
        assert url == f"{HA}/api/services/fan/turn_on"
        assert kwargs["json"] == {"entity_id": "fan.techo"}
        assert kwargs["headers"]["Authorization"] == f"Bearer {HA_SECRETO}"
        # El secreto no sale en ninguna respuesta ni en ningún registro.
        estado = client.get("/casa/estado", headers=auth_headers)
        for texto in (r.text, estado.text, caplog.text):
            assert HA_SECRETO not in texto
        assert [o["estado"] for o in estado.json()["ordenes"]] == ["hecha"]

    def test_tras_la_orden_se_vuelve_a_preguntar_y_no_se_da_por_bueno_lo_viejo(
            self, client, auth_headers, mock_requests, directo):
        """Una integración lenta (nube, o una carrera en ESPHome) no ha reflejado aún el
        cambio cuando HA contesta al servicio. Lo que había en la caché ya no vale y lo
        que se leyera en ese instante sería el estado de antes: ni una cosa ni la otra
        pueden salir como «cómo quedó», porque la ficha recién encendida volvía a
        «apagada» y se quedaba así."""
        _con_catalogo(mock_requests, CATALOGO)
        lecturas = iter(["off", "off", "on"])

        def _states(url, **kwargs):
            return _estados_ha(fan__techo=next(lecturas))

        mock_requests.add("GET", f"{HA}/api/states", _states)
        # HA la ejecuta, pero la entidad no está entre lo que cambió durante la llamada.
        mock_requests.add("POST", f"{HA}/api/services/fan/turn_on", FakeResponse([], 200))
        client.get("/casa/estado", headers=auth_headers)   # la caché se queda con «off»

        r = _pedir(client, auth_headers, "fan.techo", "encender").json()
        # Ni «off» leído demasiado pronto ni el de la caché: no se sabe todavía.
        assert r["orden"]["estado"] == "hecha" and r["estado_entidad"] is None
        # Y no se ha releído la entidad justo después: esa lectura era la que mentía.
        assert len(_a_ha(mock_requests, "GET")) == 1

        # La caché se ha olvidado: el refresco siguiente pregunta, aunque no hayan pasado
        # los segundos de la caché.
        client.get("/casa/estado", headers=auth_headers)
        assert len(_a_ha(mock_requests, "GET")) == 2
        main._ha_vivo["ts"] -= main.HA_VIVO_CACHE_S + 1
        d = client.get("/casa/estado", headers=auth_headers).json()
        assert next(e for e in d["entidades"] if e["id"] == "fan.techo")["estado"] == "on"

    # — Qué pasa con la orden: hecha, rechazada, sin confirmar o a la cola —
    #
    # La cola solo recibe lo que HA SEGURO que no vio. Lo que HA recibió no se encola nunca:
    # si la rechazó, el Green la ejecutaría con sus privilegios de administrador; si no
    # contestó, puede haberla hecho y el Green la haría otra vez.

    @pytest.mark.parametrize("codigo", [401, 403, 400, 404])
    def test_si_ha_la_rechaza_no_se_encola(self, client, auth_headers, mock_requests,
                                           directo, codigo):
        _con_catalogo(mock_requests, CATALOGO)
        mock_requests.add("POST", f"{HA}/api/services/fan/turn_on",
                          FakeResponse({"message": "detalle interno de HA"}, codigo))

        r = main._j_casa_ordenar("fan.turn_on", "fan.techo")
        assert r["ok"] is False and r["estado"] == "rechazada"
        assert "rechazado" in r["motivo"] and "detalle interno" not in r["motivo"]
        assert main._ha_ordenes == []
        assert main._estado_orden_casa(main._ha_ordenes_hist[-1], None, None,
                                       time.time()) == "rechazada"
        # Ni siquiera un 401/403 apaga el directo cuando llega en una ORDEN: puede ser que el
        # usuario sin administrador no pueda con ese servicio (TestTokenRechazado).
        assert main._ha_directo() is True

        # Desde el widget: un error que lo dice, y nunca un 401, que cerraría la sesión.
        w = _pedir(client, auth_headers, "fan.techo", "encender")
        assert w.status_code == 502
        assert "rechazado" in w.json()["detail"] and "detalle interno" not in w.text
        assert main._ha_ordenes == []
        assert client.get("/ha/ordenes-pending", headers=CABECERA).json()["ordenes"] == []
        estado = client.get("/casa/estado", headers=auth_headers).json()
        assert [o["estado"] for o in estado["ordenes"]] == ["rechazada", "rechazada"]

    def test_lo_rechazado_no_deja_rastro_de_hecho(self, mock_requests, directo):
        _con_catalogo(mock_requests, CATALOGO)
        mock_requests.add("POST", f"{HA}/api/services/fan/turn_on", FakeResponse({}, 403))
        main._j_casa_ordenar("fan.turn_on", "fan.techo")
        assert mock_requests.called("POST", "/casa_acciones") == []

    def test_un_5xx_queda_sin_confirmar_y_no_se_encola(self, client, auth_headers,
                                                       mock_requests, directo):
        """Un 500 no dice si el servicio llegó a correr: el desbloqueo puede estar hecho."""
        _con_catalogo(mock_requests, CATALOGO)
        mock_requests.add("POST", f"{HA}/api/services/lock/unlock",
                          FakeResponse({"message": "error interno"}, 500))

        r = _pedir(client, auth_headers, "lock.puerta", "desbloquear", confirmado=True)

        assert r.status_code == 200
        cuerpo = r.json()
        assert cuerpo["orden"]["estado"] == "sin_confirmar" and cuerpo["directa"] is True
        assert cuerpo["estado_entidad"] is None and "error interno" not in r.text
        assert main._ha_ordenes == []
        assert client.get("/ha/ordenes-pending", headers=CABECERA).json()["ordenes"] == []

        j = main._j_casa_ordenar("lock.unlock", "lock.puerta")
        assert j["ok"] is True and j["estado"] == "sin_confirmar"
        assert "no ha confirmado" in j["nota"]
        assert main._ha_ordenes == []

    @pytest.mark.parametrize("servicio,entidad", [
        ("script.turn_on", "script.buenas_noches"),   # un script con un delay largo
        ("cover.open_cover", "cover.garaje"),         # el pulso del garaje
        ("light.turn_on", "light.salon"),             # aunque repetirlo fuera inofensivo
    ])
    def test_un_timeout_de_lectura_queda_sin_confirmar(self, mock_requests, directo,
                                                       servicio, entidad):
        """HA recibió la orden y no contestó a tiempo: su API no contesta hasta que el
        servicio termina y no lo cancela si el cliente se va. Encolarla sería que la
        hicieran los dos, sea el dominio que sea."""
        _con_catalogo(mock_requests, [*CATALOGO, {"id": "script.buenas_noches"}])
        mock_requests.add("POST", f"{HA}/api/services/",
                          _lanza(requests.exceptions.ReadTimeout("lento")))
        r = main._j_casa_ordenar(servicio, entidad)
        assert r["ok"] is True and r["estado"] == "sin_confirmar" and r["directa"] is True
        assert main._ha_ordenes == []

    def test_una_conexion_cortada_tras_mandar_queda_sin_confirmar(self, mock_requests,
                                                                  directo):
        _con_catalogo(mock_requests, CATALOGO)
        mock_requests.add("POST", f"{HA}/api/services/light/turn_on", _lanza(_cortada()))
        r = main._j_casa_ordenar("light.turn_on", "light.salon")
        assert r["estado"] == "sin_confirmar" and main._ha_ordenes == []

    def test_lo_que_no_se_reconoce_queda_sin_confirmar(self, mock_requests, directo):
        """Un `ConnectionError` pelado no dice si la petición salió: ante la duda, no se
        repite."""
        _con_catalogo(mock_requests, CATALOGO)
        mock_requests.add("POST", f"{HA}/api/services/light/turn_on",
                          _lanza(requests.exceptions.ConnectionError("algo raro")))
        assert main._j_casa_ordenar("light.turn_on", "light.salon")["estado"] == "sin_confirmar"
        assert main._ha_ordenes == []

    @pytest.mark.parametrize("excepcion", [
        requests.exceptions.ConnectTimeout("sin ruta"),
        None,   # conexión rechazada (NewConnectionError): HA reiniciando
        "dns",  # el nombre de HA_URL no resuelve
    ])
    def test_si_no_se_pudo_ni_conectar_va_a_la_cola(self, client, auth_headers,
                                                    mock_requests, directo, excepcion):
        """El único caso en que el Green es el respaldo: HA no vio la orden."""
        if excepcion is None:
            excepcion = _no_conecta()
        elif excepcion == "dns":
            excepcion = _no_conecta(urllib3.exceptions.NameResolutionError(
                "ha.test", None, socket.gaierror(11001, "getaddrinfo failed")))
        _con_catalogo(mock_requests, CATALOGO)
        mock_requests.add("POST", f"{HA}/api/services/", _lanza(excepcion))

        r = _pedir(client, auth_headers, "light.salon", "encender")

        assert r.status_code == 200
        assert r.json()["directa"] is False and r.json()["orden"]["estado"] == "en_cola"
        servidas = client.get("/ha/ordenes-pending", headers=CABECERA).json()["ordenes"]
        assert [(o["servicio"], o["entidad"]) for o in servidas] == [
            ("light.turn_on", "light.salon")]

    def test_sin_confirmar_se_confirma_con_una_lectura_posterior(self, client, auth_headers,
                                                                 mock_requests, directo):
        """Tras una sin confirmar, la caché se olvida: el refresco siguiente pregunta a HA,
        y si dice lo pedido, la orden se hizo."""
        _con_catalogo(mock_requests, CATALOGO)
        lecturas = iter(["off", "on"])
        mock_requests.add("GET", f"{HA}/api/states",
                          lambda url, **kw: _estados_ha(fan__techo=next(lecturas)))
        mock_requests.add("POST", f"{HA}/api/services/fan/turn_on",
                          _lanza(requests.exceptions.ReadTimeout("lento")))
        client.get("/casa/estado", headers=auth_headers)   # la caché se queda con «off»

        r = _pedir(client, auth_headers, "fan.techo", "encender").json()
        assert r["orden"]["estado"] == "sin_confirmar"
        # El reloj de Windows puede dar el mismo instante a la orden y a la lectura de
        # justo después; la de verdad llega segundos más tarde.
        main._ha_ordenes_hist[-1]["recogida"] -= 1
        d = client.get("/casa/estado", headers=auth_headers).json()
        assert len(_a_ha(mock_requests, "GET")) == 2
        assert [o["estado"] for o in d["ordenes"]] == ["confirmada"]

    def test_directa_dice_lo_mismo_en_la_respuesta_y_en_el_historial(
            self, client, auth_headers, mock_requests, directo):
        _con_catalogo(mock_requests, CATALOGO)
        mock_requests.add("POST", f"{HA}/api/services/fan/turn_on", FakeResponse([], 200))
        mock_requests.add("POST", f"{HA}/api/services/light/turn_on",
                          _lanza(requests.exceptions.ReadTimeout("lento")))
        mock_requests.add("POST", f"{HA}/api/services/light/turn_off", _lanza(_no_conecta()))
        for entidad, accion in (("fan.techo", "encender"), ("light.salon", "encender"),
                                ("light.cocina", "apagar")):
            r = _pedir(client, auth_headers, entidad, accion).json()
            hist = next(h for h in main._ha_ordenes_hist if h["id"] == r["orden"]["id"])
            assert r["directa"] is bool(hist.get("directa")), entidad
        assert [h.get("directa", False) for h in main._ha_ordenes_hist] == [True, True, False]

    def test_el_token_no_sale_en_ningun_registro_ni_respuesta(self, client, auth_headers,
                                                              mock_requests, directo,
                                                              caplog):
        caplog.set_level(logging.DEBUG)
        _con_catalogo(mock_requests, CATALOGO)
        mock_requests.add("GET", f"{HA}/api/states",
                          FakeResponse({"message": f"token {HA_SECRETO}"}, 500))
        # 400 y no 401: un 401 apagaría el directo y las órdenes de detrás irían a la cola
        # sin pasar por los caminos que se quieren mirar (el 401 lo mira TestTokenRechazado).
        mock_requests.add("POST", f"{HA}/api/services/fan/turn_on",
                          FakeResponse({"message": f"token {HA_SECRETO}"}, 400))
        mock_requests.add("POST", f"{HA}/api/services/light/turn_on",
                          _lanza(requests.exceptions.ReadTimeout(f"{HA} {HA_SECRETO}")))
        mock_requests.add("POST", f"{HA}/api/services/light/turn_off",
                          FakeResponse({"message": HA_SECRETO}, 503))
        mock_requests.add("POST", f"{HA}/api/services/switch/turn_off",
                          _lanza(_no_conecta()))
        textos = [
            _pedir(client, auth_headers, "fan.techo", "encender").text,
            _pedir(client, auth_headers, "light.salon", "encender").text,
            _pedir(client, auth_headers, "light.cocina", "apagar").text,
            str(main._j_casa_ordenar("switch.turn_off", "switch.alexa_no_molestar")),
            client.get("/casa/estado", headers=auth_headers).text,
            str(main._j_casa_dispositivos()),
            client.get("/ha/ordenes-pending", headers=CABECERA).text,
        ]
        for texto in [*textos, caplog.text]:
            assert HA_SECRETO not in texto

    # — homeassistant.*: solo encender, apagar y alternar —

    @pytest.mark.parametrize("con_directo", [True, False])
    @pytest.mark.parametrize("servicio", ["homeassistant.restart", "homeassistant.stop",
                                          "homeassistant.reload_all",
                                          "homeassistant.update_entity"])
    def test_homeassistant_solo_enciende_y_apaga(self, mock_requests, monkeypatch,
                                                 con_directo, servicio):
        """El resto del dominio administra HA, y por la cola lo haría el Green con sus
        privilegios. Cerrado por los dos caminos."""
        if con_directo:
            monkeypatch.setattr(main, "HA_URL", HA)
            monkeypatch.setattr(main, "HA_TOKEN", HA_SECRETO)
        _con_catalogo(mock_requests, CATALOGO)
        r = main._j_casa_ordenar(servicio, "light.salon")
        assert r["ok"] is False and "homeassistant" in r["motivo"]
        assert _a_ha(mock_requests) == [] and main._ha_ordenes == []
        assert list(main._ha_ordenes_hist) == []

    @pytest.mark.parametrize("con_directo", [True, False])
    @pytest.mark.parametrize("servicio,entidad", [
        ("script.reload", "script.buenas_noches"),
        ("scene.reload", "scene.cine"),
        ("input_boolean.reload", "input_boolean.invitados"),
        ("light.reload", "light.salon"),
        ("automation.reload", "automation.luces"),
    ])
    def test_los_servicios_de_recarga_no_pasan(self, mock_requests, monkeypatch,
                                               con_directo, servicio, entidad):
        """Recargar la configuración es administrar HA, como `homeassistant.reload_all`:
        cerrado por los dos caminos, sin llamar a HA ni encolar."""
        if con_directo:
            monkeypatch.setattr(main, "HA_URL", HA)
            monkeypatch.setattr(main, "HA_TOKEN", HA_SECRETO)
        _con_catalogo(mock_requests, [*CATALOGO, {"id": "script.buenas_noches"},
                                      {"id": "input_boolean.invitados"}])
        r = main._j_casa_ordenar(servicio, entidad)
        assert r["ok"] is False and "reload" in r["motivo"]
        assert _a_ha(mock_requests) == [] and main._ha_ordenes == []
        assert list(main._ha_ordenes_hist) == []

    # — La orden hecha anula lo que esperaba en la cola sobre lo mismo —

    def test_un_apagar_hecho_anula_el_encender_que_esperaba(self, client, mock_requests,
                                                            directo):
        """HA no aceptaba conexiones y el encender se encoló; en cuanto vuelve, el apagar
        sale directo. Si el Green recogiera luego el encender, desharía el apagar."""
        _con_catalogo(mock_requests, CATALOGO)
        mock_requests.add("POST", f"{HA}/api/services/light/turn_on", _lanza(_no_conecta()))
        mock_requests.add("POST", f"{HA}/api/services/light/turn_off", FakeResponse([], 200))

        encendido = main._j_casa_ordenar("light.turn_on", "light.salon")
        assert [o["entidad"] for o in main._ha_ordenes] == ["light.salon"]
        assert main._j_casa_ordenar("light.turn_off", "light.salon")["estado"] == "hecha"

        assert main._ha_ordenes == []
        hist = next(h for h in main._ha_ordenes_hist if h["id"] == encendido["id"])
        assert main._estado_orden_casa(hist, None, None, time.time()) == "caducada"
        assert client.get("/ha/ordenes-pending", headers=CABECERA).json()["ordenes"] == []

    def test_el_garaje_encolado_lo_anula_el_cerrar_hecho(self, mock_requests, directo):
        _con_catalogo(mock_requests, CATALOGO)
        mock_requests.add("POST", f"{HA}/api/services/cover/open_cover", _lanza(_no_conecta()))
        mock_requests.add("POST", f"{HA}/api/services/cover/close_cover", FakeResponse([], 200))
        main._j_casa_ordenar("cover.open_cover", "cover.garaje")
        assert [o["servicio"] for o in main._ha_ordenes] == ["cover.open_cover"]
        main._j_casa_ordenar("cover.close_cover", "cover.garaje")
        assert main._ha_ordenes == []

    def test_otra_familia_no_se_anula(self, client, mock_requests, directo):
        """El modo del termostato sigue haciendo falta aunque luego se apague."""
        _con_catalogo(mock_requests, CATALOGO)
        mock_requests.add("POST", f"{HA}/api/services/climate/set_hvac_mode",
                          _lanza(_no_conecta()))
        mock_requests.add("POST", f"{HA}/api/services/climate/turn_off", FakeResponse([], 200))
        main._j_casa_ordenar("climate.set_hvac_mode", "climate.salon", {"hvac_mode": "heat"})
        assert main._j_casa_ordenar("climate.turn_off", "climate.salon")["estado"] == "hecha"
        servidas = client.get("/ha/ordenes-pending", headers=CABECERA).json()["ordenes"]
        assert [o["servicio"] for o in servidas] == ["climate.set_hvac_mode"]

    def test_ni_lo_rechazado_ni_lo_sin_confirmar_anulan(self, mock_requests, directo):
        """Solo una orden HECHA dice que lo encolado ya no se quiere: una rechazada no ha
        cambiado nada, y de una sin confirmar no se sabe."""
        _con_catalogo(mock_requests, CATALOGO)
        mock_requests.add("POST", f"{HA}/api/services/light/turn_on", _lanza(_no_conecta()))
        # 400 y no 403: un 403 apagaría el directo y el toggle ya no llegaría a HA.
        mock_requests.add("POST", f"{HA}/api/services/light/turn_off", FakeResponse({}, 400))
        mock_requests.add("POST", f"{HA}/api/services/light/toggle",
                          _lanza(requests.exceptions.ReadTimeout("lento")))
        main._j_casa_ordenar("light.turn_on", "light.salon")
        main._j_casa_ordenar("light.turn_off", "light.salon")
        main._j_casa_ordenar("light.toggle", "light.salon")
        assert [o["servicio"] for o in main._ha_ordenes] == ["light.turn_on"]

    def test_lo_que_no_llego_sale_en_orden_por_la_cola(self, client, mock_requests, directo):
        """Por la cola no se anula nada: el Green las ejecuta en el orden en que se
        pidieron, que es lo que pasaba siempre."""
        _con_catalogo(mock_requests, CATALOGO)
        mock_requests.add("POST", f"{HA}/api/services/", _lanza(_no_conecta()))
        main._j_casa_ordenar("light.turn_on", "light.salon")
        main._j_casa_ordenar("light.turn_on", "light.cocina")
        main._j_casa_ordenar("light.turn_off", "light.salon")
        servidas = client.get("/ha/ordenes-pending", headers=CABECERA).json()["ordenes"]
        assert [(o["servicio"], o["entidad"]) for o in servidas] == [
            ("light.turn_on", "light.salon"), ("light.turn_on", "light.cocina"),
            ("light.turn_off", "light.salon")]

    def test_familias(self):
        assert main._casa_familia("light.turn_on", "light.salon") == "encendido"
        assert main._casa_familia("homeassistant.toggle", "light.salon") == "encendido"
        assert main._casa_familia("climate.turn_off", "climate.salon") == "encendido"
        assert main._casa_familia("climate.set_hvac_mode", "climate.salon") is None
        assert main._casa_familia("lock.unlock", "lock.puerta") == "cerrojo"
        assert main._casa_familia("lock.open", "lock.puerta") == "cerrojo"
        assert main._casa_familia("cover.set_cover_position", "cover.garaje") == "persiana"
        # El genérico sobre el garaje lo abre: es de la familia de la persiana.
        assert main._casa_familia("homeassistant.turn_on", "cover.garaje") == "persiana"
        assert main._casa_familia("media_player.media_pause", "media_player.x") == "reproduccion"
        assert main._casa_familia("media_player.volume_set", "media_player.x") is None
        for accion in ("alarm_arm_away", "alarm_arm_home", "alarm_arm_night",
                       "alarm_disarm", "alarm_trigger"):
            assert main._casa_familia(f"alarm_control_panel.{accion}",
                                      "alarm_control_panel.x") == "alarma", accion
        # El mismo servicio se pisa aunque no tenga familia; dos distintos sin familia, no.
        assert main._casa_se_pisan("climate.set_temperature", "climate.set_temperature",
                                   "climate.salon") is True
        assert main._casa_se_pisan("climate.set_temperature", "climate.set_hvac_mode",
                                   "climate.salon") is False
        # Lo que se acumula no se pisa consigo mismo: dos «sube el volumen» son dos pasos.
        for servicio, entidad in (("media_player.volume_up", "media_player.echo"),
                                  ("button.press", "button.timbre"),
                                  ("script.turn_on", "script.buenas_noches")):
            assert main._casa_se_pisan(servicio, servicio, entidad) is False, servicio
        assert main._casa_se_pisan("media_player.volume_set", "media_player.volume_set",
                                   "media_player.echo") is True
        assert main._casa_se_pisan("light.turn_off", "homeassistant.turn_on",
                                   "light.salon") is True

    def test_un_armar_hecho_anula_el_desarmar_que_esperaba(self, client, mock_requests,
                                                            directo):
        """Si el Green recogiera el desarmar después, la casa se quedaría desarmada justo
        cuando se acababa de armar."""
        _con_catalogo(mock_requests, CATALOGO)
        mock_requests.add("POST", f"{HA}/api/services/alarm_control_panel/alarm_disarm",
                          _lanza(_no_conecta()))
        mock_requests.add("POST", f"{HA}/api/services/alarm_control_panel/alarm_arm_away",
                          FakeResponse([], 200))
        desarmar = main._j_casa_ordenar("alarm_control_panel.alarm_disarm",
                                        "alarm_control_panel.x", {"code": "1234"})
        assert [o["servicio"] for o in main._ha_ordenes] == ["alarm_control_panel.alarm_disarm"]
        armar = main._j_casa_ordenar("alarm_control_panel.alarm_arm_away",
                                     "alarm_control_panel.x")
        assert armar["estado"] == "hecha"
        assert main._ha_ordenes == []
        hist = next(h for h in main._ha_ordenes_hist if h["id"] == desarmar["id"])
        assert main._estado_orden_casa(hist, None, None, time.time()) == "caducada"
        assert client.get("/ha/ordenes-pending", headers=CABECERA).json()["ordenes"] == []

    def test_el_mismo_servicio_hecho_anula_el_encolado(self, client, mock_requests, directo):
        """Un 25 encolado que el Green recogiera después del 21 hecho dejaría el 25."""
        _con_catalogo(mock_requests, CATALOGO)
        valores = iter([_lanza(_no_conecta()), lambda url, **kw: FakeResponse([], 200)])
        mock_requests.add("POST", f"{HA}/api/services/climate/set_temperature",
                          lambda url, **kw: next(valores)(url, **kw))
        veinticinco = main._j_casa_ordenar("climate.set_temperature", "climate.salon",
                                           {"temperature": 25})
        assert [o["datos"] for o in main._ha_ordenes] == [{"temperature": 25}]
        veintiuno = main._j_casa_ordenar("climate.set_temperature", "climate.salon",
                                         {"temperature": 21})
        assert veintiuno["estado"] == "hecha"
        assert main._ha_ordenes == []
        hist = next(h for h in main._ha_ordenes_hist if h["id"] == veinticinco["id"])
        assert main._estado_orden_casa(hist, None, None, time.time()) == "caducada"
        assert client.get("/ha/ordenes-pending", headers=CABECERA).json()["ordenes"] == []

    def test_la_anulacion_y_el_sondeo_comparten_cerrojo(self, client, mock_requests,
                                                         directo):
        """Mientras se anula, el Green no puede llevarse la cola: espera al cerrojo, y
        cuando entra la orden ya no está."""
        _con_catalogo(mock_requests, CATALOGO)
        mock_requests.add("POST", f"{HA}/api/services/light/turn_on", _lanza(_no_conecta()))
        main._j_casa_ordenar("light.turn_on", "light.salon")
        servidas = []
        with main._ha_ordenes_lock:
            hilo = threading.Thread(target=lambda: servidas.append(
                client.get("/ha/ordenes-pending", headers=CABECERA).json()["ordenes"]))
            hilo.start()
            hilo.join(timeout=0.3)
            assert hilo.is_alive() and servidas == []   # el sondeo espera al cerrojo
            # Lo que haría _casa_anular_pendientes por dentro, con el cerrojo cogido.
            main._ha_ordenes.clear()
        hilo.join(timeout=5)
        assert servidas == [[]]

    # — Cómo se sabe si una orden salió —

    def test_no_llego_solo_cuando_no_se_pudo_conectar(self):
        rechazada = urllib3.exceptions.NewConnectionError(
            None, "Failed to establish a new connection: [Errno 111] Connection refused")
        # Un reset AL CONECTAR va dentro del NewConnectionError: sigue sin haber salido.
        rechazada.__cause__ = ConnectionResetError(104, "reset")
        dns = urllib3.exceptions.NameResolutionError(
            "ha.test", None, socket.gaierror(-2, "Name or service not known"))
        assert main._ha_no_llego(requests.exceptions.ConnectTimeout("x")) is True
        assert main._ha_no_llego(_no_conecta(rechazada)) is True
        assert main._ha_no_llego(_no_conecta(dns)) is True
        assert main._ha_no_llego(requests.exceptions.ConnectionError(
            ConnectionRefusedError(111, "Connection refused"))) is True

        assert main._ha_no_llego(requests.exceptions.ReadTimeout("x")) is False
        assert main._ha_no_llego(_cortada()) is False
        assert main._ha_no_llego(requests.exceptions.ConnectionError(
            urllib3.exceptions.ProtocolError("Connection aborted.",
                                             ConnectionResetError(104, "reset")))) is False
        assert main._ha_no_llego(requests.exceptions.ConnectionError("¿?")) is False
        assert main._ha_no_llego(ValueError("otra cosa")) is False
        # La causa también se encuentra por __context__ (una excepción relanzada).
        try:
            try:
                raise rechazada
            except urllib3.exceptions.NewConnectionError:
                raise requests.exceptions.ConnectionError("envuelta")
        except requests.exceptions.ConnectionError as e:
            assert main._ha_no_llego(e) is True

    # — La caché del estado en vivo —

    def test_mientras_otro_pregunta_se_sirve_lo_de_hace_un_momento(self, mock_requests,
                                                                   directo):
        """Nadie espera a una petición a HA que ya ha hecho otro si hay una lectura de
        hace unos segundos que servir."""
        hace = time.time() - main.HA_VIVO_CACHE_S - 5
        main._ha_vivo.update(estados={"fan.techo": "on"}, ts=hace, en_curso=True)
        assert main._ha_estados_vivos() == ({"fan.techo": "on"}, hace)
        assert _a_ha(mock_requests) == []

    def test_sin_nada_que_servir_se_espera_poco(self, mock_requests, directo, monkeypatch):
        monkeypatch.setattr(main, "_HA_ESPERA_LECTURA_S", 0.05)
        main._ha_vivo.update(en_curso=True)
        inicio = time.time()
        assert main._ha_estados_vivos() == (None, None)
        assert time.time() - inicio < 1
        assert _a_ha(mock_requests) == []

    def test_una_lectura_de_antes_de_la_orden_no_se_guarda(self, mock_requests, directo):
        """La lectura salió antes de la orden y volvió después: puede ser el estado de
        antes, y guardarla la serviría como el de ahora."""
        _con_catalogo(mock_requests, CATALOGO)

        def _states(url, **kwargs):
            main._ha_olvidar_estados()   # una orden llega mientras HA contesta
            return _estados_ha(fan__techo="off")

        mock_requests.add("GET", f"{HA}/api/states", _states)
        estados, _ = main._ha_estados_vivos()
        assert estados == {"fan.techo": "off"}   # a quien la pidió sí se le da
        assert main._ha_vivo["ts"] == 0.0 and main._ha_vivo["en_curso"] is False

    def test_una_accion_que_no_vale_no_llega_a_ha(self, client, auth_headers, mock_requests,
                                                  directo, monkeypatch):
        _con_catalogo(mock_requests, CATALOGO)
        monkeypatch.setattr(main, "PC_ENTIDAD", "switch.pc")
        assert _pedir(client, auth_headers, "light.salon", "activar").status_code == 400
        assert _pedir(client, auth_headers, "light.salon", "toggle").status_code == 422
        assert _pedir(client, auth_headers, "light.inventada", "encender").status_code == 404
        # El PC sigue siendo de solo lectura aunque ahora se pueda hablar con HA.
        assert _pedir(client, auth_headers, "switch.pc", "apagar").status_code == 400
        assert _a_ha(mock_requests, "POST") == []

    def test_el_servicio_tiene_que_ser_del_dominio_de_la_entidad(self, mock_requests,
                                                                 directo):
        _con_catalogo(mock_requests, CATALOGO)
        assert main._j_casa_ordenar("light.turn_on", "switch.alexa_no_molestar")["ok"] is False
        assert main._j_casa_ordenar("shell_command.turn_on", "light.salon")["ok"] is False
        assert _a_ha(mock_requests) == [] and main._ha_ordenes == []

    def test_lo_delicado_sin_confirmar_no_se_ejecuta(self, client, auth_headers,
                                                     mock_requests, directo):
        _con_catalogo(mock_requests, CATALOGO)
        mock_requests.add("POST", f"{HA}/api/services/cover/open_cover", FakeResponse([], 200))
        assert _pedir(client, auth_headers, "cover.garaje", "abrir").status_code == 409
        assert _pedir(client, auth_headers, "lock.puerta", "desbloquear").status_code == 409
        assert _a_ha(mock_requests, "POST") == []

        r = _pedir(client, auth_headers, "cover.garaje", "abrir", confirmado=True)
        assert r.status_code == 200 and r.json()["orden"]["estado"] == "hecha"
        (_, url, kwargs), = _a_ha(mock_requests, "POST")
        assert url == f"{HA}/api/services/cover/open_cover"
        assert kwargs["json"] == {"entity_id": "cover.garaje"}

    def test_jarvis_manda_sus_datos_pero_no_cambia_el_objetivo(self, mock_requests, directo):
        _con_catalogo(mock_requests, CATALOGO)
        mock_requests.add("POST", f"{HA}/api/services/homeassistant/turn_on",
                          FakeResponse([], 200))
        r = main._j_casa_ordenar("homeassistant.turn_on", "light.salon",
                                 {"brightness_pct": 40, "entity_id": "cover.garaje",
                                  "area_id": "garaje"})
        assert r["ok"] is True and r["directa"] is True
        (_, _, kwargs), = _a_ha(mock_requests, "POST")
        assert kwargs["json"] == {"brightness_pct": 40, "entity_id": "light.salon"}
        assert main._ha_ordenes == []

    def test_la_orden_directa_deja_rastro_igual(self, mock_requests, directo):
        apuntado = {}

        def _post(url, **kwargs):
            apuntado["fila"] = kwargs.get("json")
            return FakeResponse({}, 201)

        _con_catalogo(mock_requests, CATALOGO)
        mock_requests.add("POST", "/casa_acciones", _post)
        mock_requests.add("POST", f"{HA}/api/services/light/turn_on", FakeResponse([], 200))
        main._j_casa_ordenar("light.turn_on", "light.salon")
        assert apuntado["fila"]["servicio"] == "light.turn_on"

    # — Lo que no puede dar un 500 ni dejar el widget diciendo que HA no contesta —

    def test_una_excepcion_cualquiera_al_leer_cae_al_catalogo(self, client, auth_headers,
                                                              mock_requests, directo,
                                                              caplog):
        """Un token que no cabe en latin-1 hace que la cabecera lance UnicodeEncodeError, que
        no es de `requests`: tiene que caer al catálogo, no dar un 500."""
        caplog.set_level(logging.DEBUG)
        _con_catalogo(mock_requests, CATALOGO)
        mock_requests.add("GET", f"{HA}/api/states", _lanza(UnicodeEncodeError(
            "latin-1", f"Bearer {HA_SECRETO}ñ", 7, 8, "ordinal not in range(256)")))
        r = client.get("/casa/estado", headers=auth_headers)
        assert r.status_code == 200 and r.json()["fuente"] == "catalogo"
        assert main._ha_vivo["caido"] is True
        assert "UnicodeEncodeError" in caplog.text and HA_SECRETO not in caplog.text

    def test_una_orden_hecha_dice_que_ha_esta_vivo(self, client, auth_headers,
                                                   mock_requests, directo):
        """Una lectura lenta de otro hilo lo dio por caído; la orden acaba de hacerse, así
        que HA contesta, y el refresco siguiente le pregunta en vez de servir el catálogo."""
        _con_catalogo(mock_requests, CATALOGO)
        mock_requests.add("POST", f"{HA}/api/services/fan/turn_on", FakeResponse([], 200))
        mock_requests.add("GET", f"{HA}/api/states", _estados_ha(fan__techo="on"))
        main._ha_vivo.update(caido=True, fallo_ts=time.time())
        assert main._j_casa_ordenar("fan.turn_on", "fan.techo")["estado"] == "hecha"
        assert main._ha_vivo["caido"] is False and main._ha_vivo["fallo_ts"] == 0.0
        d = client.get("/casa/estado", headers=auth_headers).json()
        assert d["fuente"] == "vivo" and d["ha_directo"] is True


class TestTokenRechazado:
    """Un 401/403 de HA es un token revocado o mal puesto. Seguir preguntando cada pocos
    segundos no lo arregla, y con `ip_ban_enabled` HA banearía la IP de `caja` entera (n8n
    y todo lo que sale de ella). Se deja de hablar con HA un rato y se dice una vez."""

    @staticmethod
    def _errores(caplog):
        return [r for r in caplog.records
                if r.levelno >= logging.ERROR and "HA_TOKEN rechazado" in r.getMessage()]

    @pytest.mark.parametrize("codigo", [401, 403])
    def test_la_lectura_rechazada_apaga_el_directo(self, client, auth_headers, mock_requests,
                                                   directo, caplog, codigo):
        caplog.set_level(logging.DEBUG)
        _con_catalogo_fechado(mock_requests, CATALOGO, _hace(30))
        mock_requests.add("GET", f"{HA}/api/states",
                          FakeResponse({"message": f"token {HA_SECRETO}"}, codigo))
        mock_requests.add("POST", f"{HA}/api/services/", FakeResponse([], 200))

        d = client.get("/casa/estado", headers=auth_headers).json()
        assert d["fuente"] == "catalogo" and d["ha_directo"] is False
        # Mientras dura, ni se le pregunta ni se le manda nada: todo como sin HA.
        client.get("/casa/estado", headers=auth_headers)
        r = main._j_casa_ordenar("fan.turn_on", "fan.techo")
        assert r["ok"] is True and "directa" not in r
        assert [o["entidad"] for o in main._ha_ordenes] == ["fan.techo"]
        assert len(_a_ha(mock_requests)) == 1 and _a_ha(mock_requests, "POST") == []
        assert main._ha_vivo["veto_hasta"] >= time.time() + main.HA_TOKEN_VETO_S - 5

        # Un error claro, una sola vez, sin el token; y no el aviso de «no contesta».
        (error,) = self._errores(caplog)
        assert "revisa el token" in error.getMessage()
        assert HA_SECRETO not in caplog.text
        assert "no contesta en directo" not in caplog.text

        # Pasado el rato se vuelve a intentar; si sigue rechazado, no se repite el error.
        main._ha_vivo["veto_hasta"] = time.time() - 1
        client.get("/casa/estado", headers=auth_headers)
        assert len(_a_ha(mock_requests, "GET")) == 2
        assert len(self._errores(caplog)) == 1 and main._ha_directo() is False

    def test_un_401_en_una_orden_no_apaga_el_directo(self, mock_requests, directo, caplog):
        """Con un usuario sin administrador, un 401/403 en una orden es también «ese servicio
        no lo puede usar». Si apagara el directo, repetir la MISMA orden la mandaría a la
        cola y el Green la haría con sus privilegios. Así que: rechazada, ninguna a la cola,
        la siguiente vuelve a ir en directo, y ningún aviso de token."""
        caplog.set_level(logging.DEBUG)
        _con_catalogo(mock_requests, CATALOGO)
        mock_requests.add("POST", f"{HA}/api/services/", FakeResponse({}, 401))
        r = main._j_casa_ordenar("light.turn_on", "light.salon")
        assert r["ok"] is False and r["estado"] == "rechazada" and main._ha_ordenes == []
        otra = main._j_casa_ordenar("light.turn_on", "light.salon")
        assert otra["ok"] is False and otra["estado"] == "rechazada"
        assert main._ha_ordenes == [] and main._ha_directo() is True
        assert len(_a_ha(mock_requests, "POST")) == 2
        assert self._errores(caplog) == [] and HA_SECRETO not in caplog.text

    def test_si_ha_vuelve_a_aceptarlo_se_avisara_otra_vez(self, mock_requests, directo,
                                                          caplog):
        caplog.set_level(logging.DEBUG)
        _con_catalogo(mock_requests, CATALOGO)
        codigos = iter([401, 200, 401])

        def _states(url, **kwargs):
            codigo = next(codigos)
            return _estados_ha(fan__techo="on") if codigo == 200 else FakeResponse({}, codigo)

        mock_requests.add("GET", f"{HA}/api/states", _states)
        main._ha_estados_vivos()
        assert len(self._errores(caplog)) == 1
        main._ha_vivo["veto_hasta"] = 0.0
        assert main._ha_estados_vivos()[0] == {"fan.techo": "on"}
        main._ha_vivo["ts"] = 0.0
        main._ha_estados_vivos()
        assert len(self._errores(caplog)) == 2
