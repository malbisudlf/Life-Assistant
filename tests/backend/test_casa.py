"""Tests del control de la casa: la cola de órdenes que recoge Home Assistant y el
catálogo de dispositivos que HA empuja.

Aquí se prueba lo que el backend garantiza pase lo que pase al otro lado: que no salga
una orden de un dominio que no está en la lista blanca, que no se ejecute una orden vieja,
y que lo que abre cerraduras o persianas no lo dispare el modelo por su cuenta.
"""
import time

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

    def test_las_ordenes_de_jarvis_tambien_llevan_acuse(self, mock_requests):
        _con_catalogo(mock_requests, CATALOGO)
        r = main._j_casa_ordenar("light.turn_on", "light.salon")
        assert r["ok"] is True and len(r["id"]) == 12
        assert main._ha_ordenes_hist[-1]["id"] == r["id"]
