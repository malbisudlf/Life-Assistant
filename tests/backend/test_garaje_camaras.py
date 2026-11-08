"""El garaje desde una llamada y las cámaras de fuera (2026-11-08).

Lo que sostiene el garaje no es el «sí», que puede decirlo cualquiera que vaya en el coche,
sino dónde está el móvil de Mikel: lejos de casa, o con una ubicación vieja o imprecisa, no
se abre por ningún canal. Y las cámaras: solo las de la lista, y lo que vuelve al modelo es
una descripción, nunca el texto de la imagen.
"""
import json
from datetime import datetime, timedelta, timezone

import pytest

import main
from conftest import FakeResponse

CASA = (43.0000, -2.0000)


def _iso(minutos_atras=1):
    return (datetime.now(timezone.utc) - timedelta(minutes=minutos_atras)).isoformat()


@pytest.fixture
def garaje(monkeypatch, mock_requests):
    monkeypatch.setattr(main, "HA_URL", "http://ha.test:8123")
    monkeypatch.setattr(main, "HA_TOKEN", "ha-token")
    monkeypatch.setattr(main, "GARAJE_SCRIPT", "script.abrir_garaje")
    monkeypatch.setattr(main, "GARAJE_SENSOR", "binary_sensor.puerta_garaje")
    monkeypatch.setattr(main, "GARAJE_MOVIL", "device_tracker.movil")
    monkeypatch.setattr(main, "GARAJE_PEDIR_UBICACION", "notify.mobile_app_movil")
    monkeypatch.setattr(main, "_garaje_pulsos", [])
    temporizadores = []

    class _Timer:
        def __init__(self, seg, fn, args=()):
            temporizadores.append((seg, fn, args))
            self.daemon = False

        def start(self):
            pass

    monkeypatch.setattr(main.threading, "Timer", _Timer)
    avisos = []
    monkeypatch.setattr(main, "_acusar_recibo", lambda t, x, **k: avisos.append((t, x)))
    mock_requests.add("GET", "/api/states/zone.home", FakeResponse(
        {"state": "1", "attributes": {"latitude": CASA[0], "longitude": CASA[1], "radius": 24}}))
    mock_requests.temporizadores = temporizadores
    mock_requests.avisos = avisos
    return mock_requests


def _movil(garaje, lat=CASA[0], lon=CASA[1], minutos=1, precision=20):
    garaje.add("GET", "/api/states/device_tracker.movil", FakeResponse({
        "state": "home", "last_updated": _iso(minutos), "last_reported": _iso(minutos),
        "attributes": {"latitude": lat, "longitude": lon, "gps_accuracy": precision}}))


def _puerta(garaje, estado):
    garaje.add("GET", "/api/states/binary_sensor.puerta_garaje", FakeResponse({"state": estado}))


def _pulsos(garaje):
    return garaje.called("POST", "/api/services/script/turn_on")


class TestGaraje:
    def test_en_casa_abre_y_avisa_luego_de_lo_que_dice_el_sensor(self, garaje):
        _movil(garaje)
        _puerta(garaje, "off")
        garaje.add("POST", "/api/services/script/turn_on", FakeResponse([]))
        r = main._j_garaje("abrir")
        assert r["ok"] is True and "Abriendo" in r["frase"]
        (_, _, kw), = _pulsos(garaje)
        assert kw["json"] == {"entity_id": "script.abrir_garaje"}
        # El aviso al móvil va después, con lo que diga el sensor.
        (seg, fn, args), = garaje.temporizadores
        assert seg == main.GARAJE_COMPROBAR_SEG
        garaje.routes[:] = [x for x in garaje.routes if "puerta_garaje" not in x[1]]
        _puerta(garaje, "on")
        fn(*args)
        assert garaje.avisos[0][0] == "🚗 Garaje" and "Abierta" in garaje.avisos[0][1]

    def test_lejos_de_casa_no_abre_y_pide_la_ubicacion(self, garaje):
        _movil(garaje, lat=CASA[0] + 0.1)        # ~11 km al norte
        _puerta(garaje, "off")
        r = main._j_garaje("abrir")
        assert r["ok"] is False and "km de casa" in r["motivo"]
        assert not _pulsos(garaje)
        (_, _, kw), = garaje.called("POST", "/api/services/notify/mobile_app_movil")
        assert kw["json"] == {"message": "request_location_update"}

    def test_con_la_ubicacion_vieja_no_abre(self, garaje):
        _movil(garaje, minutos=25)
        _puerta(garaje, "off")
        r = main._j_garaje("abrir")
        assert r["ok"] is False and "25 minutos" in r["motivo"]
        assert not _pulsos(garaje)

    def test_con_la_ubicacion_imprecisa_no_abre(self, garaje):
        _movil(garaje, precision=900)
        _puerta(garaje, "off")
        assert main._j_garaje("abrir")["ok"] is False
        assert not _pulsos(garaje)

    def test_sin_saber_donde_esta_el_movil_no_abre(self, garaje):
        garaje.add("GET", "/api/states/device_tracker.movil", FakeResponse({}, 404))
        _puerta(garaje, "off")
        assert main._j_garaje("abrir")["ok"] is False
        assert not _pulsos(garaje)

    def test_abrir_lo_abierto_no_manda_el_pulso(self, garaje):
        """El motor es un pulso: abrir lo que ya está abierto lo cerraría."""
        _movil(garaje)
        _puerta(garaje, "on")
        r = main._j_garaje("abrir")
        assert r.get("ya_estaba") is True and not _pulsos(garaje)

    def test_cerrar_sin_sensor_no_se_hace(self, garaje):
        """El mismo pulso que cierra abre: sin saber cómo está, no se toca."""
        _movil(garaje)
        _puerta(garaje, "unavailable")
        r = main._j_garaje("cerrar")
        assert r["ok"] is False and "sensor" in r["motivo"] and not _pulsos(garaje)

    def test_tope_por_hora(self, garaje, monkeypatch):
        monkeypatch.setattr(main, "GARAJE_MAX_HORA", 2)
        monkeypatch.setattr(main, "_garaje_pulsos", [main.time.time()] * 2)
        _movil(garaje)
        _puerta(garaje, "off")
        assert main._j_garaje("abrir")["ok"] is False and not _pulsos(garaje)

    def test_sin_configurar_no_hace_nada(self, garaje, monkeypatch):
        monkeypatch.setattr(main, "GARAJE_MOVIL", "")
        r = main._j_garaje("abrir")
        assert r["ok"] is False and not garaje.calls

    def test_se_confirma_siempre_y_no_tras_leer_texto_ajeno(self):
        h = main._JARVIS_HERRAMIENTAS["garaje"]
        assert main._jarvis_confirma(h, {"accion": "abrir"}) is True
        assert "garaje" in main._AJENO_NI_CON_BOTON
        assert main._ajeno_bloquea("garaje", {"whatsapp_leer"}, se_confirma=True) is not None

    def test_casa_ordenar_sobre_el_garaje_sigue_pidiendo_confirmacion(self):
        assert main._casa_pide_confirmar({"servicio": "script.turn_on",
                                          "entidad": "script.abrir_puerta_garaje"}) is True


class TestGarajePorTelefono:
    TOKEN = {"Authorization": "Bearer mcp-telefono-token"}

    def _llamar(self, client, nombre, argumentos):
        sesion = client.post("/mcp/telefono", headers=self.TOKEN, json={
            "jsonrpc": "2.0", "id": 0, "method": "initialize",
            "params": {"protocolVersion": "2025-06-18", "capabilities": {},
                       "clientInfo": {"name": "t", "version": "1"}}}).headers["mcp-session-id"]
        return client.post("/mcp/telefono", headers={**self.TOKEN, "Mcp-Session-Id": sesion},
                           json={"jsonrpc": "2.0", "id": 1, "method": "tools/call",
                                 "params": {"name": nombre, "arguments": argumentos}}).json()

    @pytest.fixture(autouse=True)
    def _token(self, monkeypatch):
        monkeypatch.setattr(main, "JARVIS_MCP_TELEFONO_TOKEN", "mcp-telefono-token")

    def test_se_propone_para_el_si_hablado_con_la_distancia(self, client, garaje):
        _movil(garaje, lat=CASA[0] + 0.0005)      # ~55 m
        _puerta(garaje, "off")
        garaje.add("POST", "jarvis_preguntas", FakeResponse({}, 201))
        r = self._llamar(client, "garaje", {"accion": "abrir"})
        salida = json.loads(r["result"]["content"][0]["text"])
        assert salida["linea_para_la_llamada"].startswith("✅ CONFIRMAR: ")
        assert salida["lo_que_se_hara"].startswith("Abrir la puerta del garaje (su móvil está a 5")
        assert not _pulsos(garaje)
        # El «sí» vale minutos, no media hora.
        guardada = garaje.called("POST", "jarvis_preguntas")[0][2]["json"]
        caduca = datetime.fromisoformat(guardada["accion"]["caduca"])
        assert caduca - datetime.now(timezone.utc) <= timedelta(minutes=main.GARAJE_VIGENCIA_MIN)
        assert "garaje" in main.PREGUNTAS_HABLADAS

    def test_lejos_ni_se_propone(self, client, garaje):
        _movil(garaje, lat=CASA[0] + 0.1)
        _puerta(garaje, "off")
        r = self._llamar(client, "garaje", {"accion": "abrir"})
        salida = json.loads(r["result"]["content"][0]["text"])
        assert salida["ok"] is False and "km de casa" in salida["motivo"]
        assert not garaje.called("POST", "jarvis_preguntas")

    def test_casa_ordenar_sobre_el_garaje_le_manda_a_la_herramienta(self, client, garaje):
        r = self._llamar(client, "casa_ordenar", {"servicio": "script.turn_on",
                                                  "entidad": "script.abrir_puerta_garaje"})
        assert "garaje" in r["error"]["message"] and not _pulsos(garaje)


@pytest.fixture
def camaras(monkeypatch, mock_requests):
    monkeypatch.setattr(main, "HA_URL", "http://ha.test:8123")
    monkeypatch.setattr(main, "HA_TOKEN", "ha-token")
    monkeypatch.setattr(main, "CAMARAS", "garaje=camera.garaje_hd, jardín=camera.jardin_hd, "
                                         "salon=no_es_una_camara")
    mock_requests.add("GET", "/api/camera_proxy/", FakeResponse(
        content=b"\xff\xd8jpeg", headers={"Content-Type": "image/jpeg"}))
    return mock_requests


class TestCamaras:
    def test_solo_las_de_la_lista_y_validas(self, camaras):
        assert main._camaras() == {"garaje": "camera.garaje_hd", "jardin": "camera.jardin_hd"}

    def test_mirar_describe_y_no_copia_el_texto(self, camaras, monkeypatch):
        vistos = []

        def _ver(foto, instruccion, json_cerrado=False):
            vistos.append(instruccion)
            return "El coche aparcado, nadie más."

        monkeypatch.setattr(main, "_camara_ver", _ver)
        r = main._j_camaras_mirar("garaje", "¿hay alguien?")
        assert r["ok"] is True
        assert r["camaras"] == [{"camara": "garaje", "visto": "El coche aparcado, nadie más."}]
        (_, url, _), = camaras.called("GET", "/api/camera_proxy/")
        assert url.endswith("/api/camera_proxy/camera.garaje_hd")
        assert "NUNCA lo copies" in main._CAMARA_OJOS

    def test_una_camara_que_no_existe_dice_cuales_hay(self, camaras):
        r = main._j_camaras_mirar("salón")
        assert r["ok"] is False and "garaje" in r["motivo"] and "jardin" in r["motivo"]

    def test_vigilar_avisa_cuando_aparece_no_mientras_se_ve(self, camaras, monkeypatch):
        monkeypatch.setattr(main, "CAMARA_VIGILAR_SEG", 0)
        monkeypatch.setattr(main, "CAMARA_AVISO_PAUSA_SEG", 0)
        avisos = []
        monkeypatch.setattr(main, "_acusar_recibo", lambda t, x, **k: avisos.append((t, x)))
        secuencia = [(False, "Nadie."), (True, "Una persona junto al coche."),
                     (True, "La persona sigue."), (False, "Nadie."), (True, "Otra vez alguien.")]

        def _hay(foto, que):
            if not secuencia:
                main._camaras_vigiladas.pop("garaje", None)
                return False, ""
            return secuencia.pop(0)

        monkeypatch.setattr(main, "_camara_hay", _hay)
        main._camaras_vigiladas["garaje"] = {"marca": "m", "que": "una persona",
                                             "hasta": main.time.time() + 60}
        main._camara_vigilar_bucle("garaje", "camera.garaje_hd", "m")
        assert [x for _, x in avisos] == ["Una persona junto al coche.", "Otra vez alguien."]

    def test_lo_que_ya_se_veia_al_empezar_no_avisa(self, camaras, monkeypatch):
        monkeypatch.setattr(main, "CAMARA_VIGILAR_SEG", 0)
        avisos = []
        monkeypatch.setattr(main, "_acusar_recibo", lambda t, x, **k: avisos.append(x))
        secuencia = [(True, "Un coche aparcado."), (True, "Un coche aparcado.")]

        def _hay(foto, que):
            if not secuencia:
                main._camaras_vigiladas.pop("garaje", None)
                return False, ""
            return secuencia.pop(0)

        monkeypatch.setattr(main, "_camara_hay", _hay)
        main._camaras_vigiladas["garaje"] = {"marca": "m", "que": "un coche",
                                             "hasta": main.time.time() + 60}
        main._camara_vigilar_bucle("garaje", "camera.garaje_hd", "m")
        assert avisos == []

    def test_al_acabar_sin_nada_dice_sin_novedad(self, camaras, monkeypatch):
        monkeypatch.setattr(main, "CAMARA_VIGILAR_SEG", 0)
        avisos = []
        monkeypatch.setattr(main, "_acusar_recibo", lambda t, x, **k: avisos.append(x))
        monkeypatch.setattr(main, "_camara_hay", lambda foto, que: (False, "Nadie."))
        main._camaras_vigiladas["jardin"] = {"marca": "m", "que": "una persona",
                                             "hasta": main.time.time() - 1}
        main._camara_vigilar_bucle("jardin", "camera.jardin_hd", "m")
        assert avisos == ["Fin de la vigilancia: sin novedad."]
        assert "jardin" not in main._camaras_vigiladas

    def test_minutos_cero_deja_de_vigilar(self, camaras):
        main._camaras_vigiladas["garaje"] = {"marca": "m", "que": "x", "hasta": 0}
        r = main._j_camaras_vigilar("garaje", 0)
        assert r["dejadas"] == ["garaje"] and "garaje" not in main._camaras_vigiladas

    def test_por_telefono_mirar_es_de_lectura_y_vigilar_accion(self):
        assert "camaras_mirar" in main._MCP_SERVIDOR_SOLO_LECTURA
        assert "camaras_vigilar" in main._MCP_SERVIDOR_ACCIONES


class TestMenosPermisos:
    """El 2026-11-08: «quitar la mayoría de pedidas de permiso, salvo lo importante»."""

    @pytest.mark.parametrize("nombre", ["crear_evento", "crear_tarea", "reservar_bloques",
                                        "pelis_pedir", "jellyfin_reproducir",
                                        "ordenar_calendario", "proponer_regla",
                                        "mcp_desconectar"])
    def test_directas(self, nombre):
        assert main._JARVIS_HERRAMIENTAS[nombre]["confirmar"] is False

    @pytest.mark.parametrize("nombre", ["whatsapp_enviar", "whatsapp_programar", "borrar_idea",
                                        "pelis_borrar", "cobrar_entrenamiento", "desplegar",
                                        "arreglar_revision", "encargar_proyecto",
                                        "encargar_al_pc", "encargar_a_una_sesion",
                                        "responder_a_la_sesion", "mcp_conectar", "garaje"])
    def test_lo_importante_se_sigue_confirmando(self, nombre):
        assert main._JARVIS_HERRAMIENTAS[nombre]["confirmar"] is True

    def test_editar_o_borrar_una_reunion_con_gente_se_confirma(self, monkeypatch):
        monkeypatch.setattr(main, "_evento_graph", lambda i: {"invitados": 2})
        assert main._jarvis_confirma(main._JARVIS_HERRAMIENTAS["editar_evento"], {"evento_id": "x"})
        assert main._jarvis_confirma(main._JARVIS_HERRAMIENTAS["borrar_evento"], {"evento_id": "x"})
        monkeypatch.setattr(main, "_evento_graph", lambda i: {"invitados": 0})
        assert not main._jarvis_confirma(main._JARVIS_HERRAMIENTAS["borrar_evento"],
                                         {"evento_id": "x"})
        # Si no se puede leer, se pregunta: la frase dirá que no está.
        monkeypatch.setattr(main, "_evento_graph", lambda i: None)
        assert main._jarvis_confirma(main._JARVIS_HERRAMIENTAS["editar_evento"], {"evento_id": "x"})

    def test_tras_leer_algo_ajeno_salen_si_las_pide_el(self):
        pedidas = main._ajeno_pedidas("mira el correo de Aitor y apúntame la cita en el calendario")
        assert "crear_evento" in pedidas
        assert main._ajeno_bloquea("crear_evento", {"leer_documento"}, pedidas=pedidas) is None
        # Si no las pide, no salen solas: un correo no crea citas.
        assert main._ajeno_bloquea("crear_evento", {"leer_documento"},
                                   pedidas=main._ajeno_pedidas("¿qué dice el correo?")) is not None
        assert "camaras_vigilar" in main._ajeno_pedidas("vigila el garaje media hora")
        assert "pelis_pedir" in main._ajeno_pedidas("pídeme esa peli")

    def test_un_boton_que_ya_estaba_en_el_movil_sigue_sirviendo(self, monkeypatch):
        monkeypatch.setitem(main._JARVIS_HERRAMIENTAS["crear_tarea"], "fn", lambda **k: {"ok": True})
        assert main._jarvis_ejecutar_confirmado("crear_tarea", {"titulo": "x"}) == {"ok": True}
        assert main._jarvis_ejecutar_confirmado("apagar_pc", {}) is None
