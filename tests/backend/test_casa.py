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
