"""Lo que han visto las cámaras: Frigate en jacobo (2026-11-18).

Jarvis le pregunta a la API de Frigate con un usuario de solo lectura. Lo que vuelve son
campos cerrados (cámara, qué, hora, confianza), y los avisos nacen apagados y, por
defecto, solo salen con Mikel fuera de casa.
"""
import time

import pytest

import main
from conftest import FakeResponse


def _ev(eid, camara="jardin", etiqueta="person", hace=30, dura=8, puntos=0.81, fp=False):
    inicio = time.time() - hace
    return {"id": eid, "camera": camara, "label": etiqueta, "start_time": inicio,
            "end_time": None if dura is None else inicio + dura, "zones": [],
            "false_positive": fp, "top_score": None, "data": {"top_score": puntos}}


@pytest.fixture
def frigate(monkeypatch, mock_requests):
    monkeypatch.setattr(main, "FRIGATE_URL", "http://frigate.test:8971")
    monkeypatch.setattr(main, "FRIGATE_USUARIO", "jarvis")
    monkeypatch.setattr(main, "FRIGATE_CLAVE", "clave")
    monkeypatch.setattr(main, "_frigate_jwt", {"token": "", "hasta": 0.0})
    monkeypatch.setattr(main, "_frigate_vistos", {})
    monkeypatch.setattr(main, "_frigate_ultimo_aviso", {})
    mock_requests.add("POST", "/api/login", FakeResponse(
        {}, headers={"Set-Cookie": "frigate_token=jwt-1; Path=/; HttpOnly"}))
    mock_requests.add("GET", "/api/stats", FakeResponse(
        {"cameras": {"jardin": {"camera_fps": 5.0}, "salon": {"camera_fps": 0.0}}}))
    return mock_requests


def test_sin_configurar_ni_se_anuncia(monkeypatch):
    monkeypatch.setattr(main, "FRIGATE_URL", "")
    assert main._j_camaras_detecciones()["ok"] is False
    assert main._j_camaras_detecciones()["motivo"].startswith("No tengo Frigate")


def test_detecciones_en_campos_cerrados(frigate):
    frigate.add("GET", "/api/events", FakeResponse([
        _ev("a", etiqueta="person"), _ev("b", etiqueta="car", dura=None),
        _ev("c", etiqueta="person", fp=True)]))
    r = main._j_camaras_detecciones("jardín", "alguien")
    assert r["ok"] is True and r["camaras"] == ["jardin"]
    assert r["total"] == 2                      # el falso positivo no cuenta
    assert {d["que"] for d in r["detecciones"]} == {"persona", "coche"}
    assert r["detecciones"][1]["en_curso"] is True
    assert set(r["detecciones"][0]) == {"camara", "que", "hora", "segundos", "en_curso",
                                        "seguro", "zonas"}
    url = frigate.called("GET", "/api/events")[0][1]
    assert "cameras=jardin" in url and "labels=person" in url
    # El JWT del login va como Bearer, nunca en la URL.
    cabeceras = frigate.called("GET", "/api/events")[0][2]["headers"]
    assert cabeceras["Authorization"] == "Bearer jwt-1" and "jwt-1" not in url


def test_la_puerta_no_es_una_camara_se_mira_en_todas(frigate):
    frigate.add("GET", "/api/events", FakeResponse([]))
    r = main._j_camaras_detecciones("puerta", "alguien")
    assert r["ok"] is True and r["camaras"] == ["jardin", "salon"]
    assert "puerta" in r["nota"]
    assert r["sin_imagen_ahora"] == ["salon"]


def test_token_caducado_se_renueva_una_vez(frigate):
    respuestas = iter([FakeResponse({}, 401), FakeResponse([_ev("a")])])
    frigate.add("GET", "/api/events", lambda url, **k: next(respuestas))
    r = main._j_camaras_detecciones("jardin")
    assert r["ok"] is True and r["total"] == 1
    assert len(frigate.called("POST", "/api/login")) == 2


def test_frigate_caido(frigate, monkeypatch):
    frigate.routes = [x for x in frigate.routes if x[1] != "/api/stats"]
    frigate.add("GET", "/api/stats", FakeResponse({}, 502))
    assert "no contesta" in main._j_camaras_detecciones()["motivo"]


def test_que_se_pide(frigate):
    assert main._frigate_etiquetas("¿ha venido algún vehículo?") == ["car", "motorcycle"]
    assert main._frigate_etiquetas("animales") == ["dog", "cat", "bird"]
    assert main._frigate_etiquetas("") == []


# ── El vigía de los avisos ──────────────────────────────────────────────────

@pytest.fixture
def vigia(frigate, monkeypatch):
    monkeypatch.setattr(main, "FRIGATE_AVISOS", "jardin")
    monkeypatch.setattr(main, "FRIGATE_AVISOS_SIEMPRE", False)
    apuntados, entregados = [], []
    monkeypatch.setattr(main, "_apuntar_aviso",
                        lambda regla, texto, **k: apuntados.append((regla, texto, k)) or True)
    monkeypatch.setattr(main, "_entregar_aviso_ya", lambda rid: entregados.append(rid) or "movil")
    monkeypatch.setattr(main, "_en_clase", lambda: None)
    monkeypatch.setattr(main, "presencia_vigente", lambda: {"en_casa": False})
    frigate.apuntados, frigate.entregados = apuntados, entregados
    return frigate


def test_nace_apagado(frigate, monkeypatch):
    monkeypatch.setattr(main, "FRIGATE_AVISOS", "")
    assert main._frigate_vig_pasada() == 0
    assert not frigate.called("GET", "/api/events")


def test_persona_fuera_de_casa_avisa_una_vez(vigia):
    vigia.add("GET", "/api/events", FakeResponse([_ev("e1")]))
    assert main._frigate_vig_pasada() == 1
    regla, texto, k = vigia.apuntados[0]
    assert regla == main.REGLA_CAMARAS and "Persona en jardin" in texto
    assert k["huella"] == "frigate:e1" and k["prioridad"] == main.PRIO_URGENTE
    assert vigia.entregados == [k["id"]]
    # La siguiente pasada ve el mismo evento: no repite.
    assert main._frigate_vig_pasada() == 0


def test_con_el_en_casa_calla(vigia, monkeypatch):
    monkeypatch.setattr(main, "presencia_vigente", lambda: {"en_casa": True})
    vigia.add("GET", "/api/events", FakeResponse([_ev("e1")]))
    assert main._frigate_vig_pasada() == 0 and not vigia.apuntados


def test_siempre_avisa_aunque_este_en_casa(vigia, monkeypatch):
    monkeypatch.setattr(main, "presencia_vigente", lambda: {"en_casa": True})
    monkeypatch.setattr(main, "FRIGATE_AVISOS_SIEMPRE", True)
    vigia.add("GET", "/api/events", FakeResponse([_ev("e1")]))
    assert main._frigate_vig_pasada() == 1


def test_poca_confianza_y_pausa_entre_avisos(vigia):
    vigia.add("GET", "/api/events", FakeResponse([
        _ev("flojo", puntos=0.55), _ev("e1", hace=60), _ev("e2", hace=20)]))
    # El flojo no avisa; de e1 y e2 (misma cámara y etiqueta), solo el primero.
    assert main._frigate_vig_pasada() == 1
    assert vigia.apuntados[0][2]["huella"] == "frigate:e1"


def test_en_clase_se_apunta_pero_no_sale(vigia, monkeypatch):
    monkeypatch.setattr(main, "_en_clase", lambda: {"fin": "12:00"})
    vigia.add("GET", "/api/events", FakeResponse([_ev("e1")]))
    assert main._frigate_vig_pasada() == 1
    assert vigia.apuntados and not vigia.entregados


def test_es_de_solo_lectura_y_va_por_telefono():
    assert "camaras_detecciones" in main._MCP_SERVIDOR_SOLO_LECTURA
    assert "camaras_detecciones" in main._TRAS_AJENO_SE_PUEDE
    assert main._JARVIS_HERRAMIENTAS["camaras_detecciones"]["confirmar"] is False


# ── «Cuando veas X en la cámara Y, haz Z» ───────────────────────────────────

@pytest.fixture
def cuando(frigate, monkeypatch):
    monkeypatch.setattr(main, "_frigate_reglas_cache", {"hasta": 0.0, "reglas": []})
    monkeypatch.setattr(main, "_frigate_reglas_disparo", {})
    monkeypatch.setattr(main, "_frigate_reglas_vistos", {})
    monkeypatch.setattr(main, "_FRIGATE_ARRANQUE", 0.0)
    apuntados, entregados, ordenes, llamadas = [], [], [], []
    monkeypatch.setattr(main, "_apuntar_aviso",
                        lambda regla, texto, **k: apuntados.append((regla, texto, k)) or True)
    monkeypatch.setattr(main, "_entregar_aviso_ya", lambda rid: entregados.append(rid) or "movil")
    monkeypatch.setattr(main, "_j_casa_ordenar",
                        lambda s, e, d=None: ordenes.append((s, e)) or {"ok": True})
    monkeypatch.setattr(main, "_llamar", lambda texto, **k: llamadas.append(texto) or True)
    monkeypatch.setattr(main, "_telefono_configurado", lambda: True)
    frigate.add("GET", "reglas_usuario?select=clave", FakeResponse([]))
    frigate.apuntados, frigate.entregados = apuntados, entregados
    frigate.ordenes, frigate.llamadas = ordenes, llamadas
    return frigate


def _regla(**p):
    base = {"camara": "garaje", "etiquetas": ["car"], "hacer": "avisar", "texto": "",
            "servicio": "", "entidad": "", "veces": "una", "desde": 0,
            "hasta": time.time() + 3600}
    return {"clave": "camara_garaje_car_avisar", "parametros": {**base, **p}}


def test_crear_guarda_en_reglas_usuario(cuando):
    cuando.routes = [x for x in cuando.routes if x[1] != "/api/stats"]
    cuando.add("GET", "/api/stats", FakeResponse({"cameras": {"garaje": {"camera_fps": 5}}}))
    r = main._j_camaras_cuando("garaje", "un coche", "casa", servicio="light.turn_on",
                               entidad="light.entrada")
    assert r["ok"] is True and r["camara"] == "garaje" and r["busco"] == ["car"]
    fila = cuando.called("POST", "reglas_usuario")[0][2]["json"]
    assert fila["plantilla"] == "camara" and fila["activa"] is True
    assert fila["parametros"]["entidad"] == "light.entrada"
    assert "light.turn_on a light.entrada" in r["frase"]


def test_lo_delicado_de_la_casa_no_se_deja_preparado(cuando):
    for servicio, entidad in (("script.turn_on", "script.abrir_puerta_garaje"),
                              ("cover.open_cover", "cover.garaje"),
                              ("alarm_control_panel.alarm_disarm", "alarm_control_panel.casa")):
        r = main._j_camaras_cuando("jardin", "alguien", "casa", servicio=servicio, entidad=entidad)
        assert r["ok"] is False, servicio
    assert not cuando.called("POST", "reglas_usuario")


def test_sin_que_o_con_camara_desconocida(cuando):
    assert "Qué tiene que ver" in main._j_camaras_cuando("jardin", "algo raro")["motivo"]
    assert "Qué cámara" in main._j_camaras_cuando("trastero", "alguien")["motivo"]


def test_dispara_una_vez_y_se_apaga(cuando):
    cuando.add("GET", "/api/events", FakeResponse([_ev("c1", camara="garaje", etiqueta="car")]))
    assert main._frigate_reglas_pasada([_regla(texto="Ha llegado")]) == 1
    regla, texto, k = cuando.apuntados[0]
    assert regla == "tuya:camara_garaje_car_avisar" and "Coche en garaje" in texto
    assert "Ha llegado" in texto and cuando.entregados == [k["id"]]
    apagado = cuando.called("PATCH", "reglas_usuario?clave=eq.camara_garaje_car_avisar")
    assert apagado and apagado[0][2]["json"] == {"activa": False}


def test_lo_de_antes_de_crearla_no_dispara(cuando):
    cuando.add("GET", "/api/events", FakeResponse([_ev("c1", camara="garaje", etiqueta="car",
                                                       hace=120)]))
    assert main._frigate_reglas_pasada([_regla(desde=time.time() - 60)]) == 0


def test_otra_camara_u_otra_cosa_no_dispara(cuando):
    cuando.add("GET", "/api/events", FakeResponse([
        _ev("p1", camara="garaje", etiqueta="person"), _ev("c1", camara="jardin", etiqueta="car")]))
    assert main._frigate_reglas_pasada([_regla()]) == 0


def test_confianza_baja_espera_a_la_siguiente_pasada(cuando):
    respuestas = iter([FakeResponse([_ev("c1", camara="garaje", etiqueta="car", puntos=0.5)]),
                       FakeResponse([_ev("c1", camara="garaje", etiqueta="car", puntos=0.8)])])
    cuando.add("GET", "/api/events", lambda url, **k: next(respuestas))
    assert main._frigate_reglas_pasada([_regla()]) == 0
    assert main._frigate_reglas_pasada([_regla()]) == 1


def test_casa_manda_la_orden_y_lo_cuenta(cuando):
    cuando.add("GET", "/api/events", FakeResponse([_ev("c1", camara="garaje", etiqueta="car")]))
    regla = _regla(hacer="casa", servicio="light.turn_on", entidad="light.entrada", veces="siempre")
    assert main._frigate_reglas_pasada([regla]) == 1
    assert cuando.ordenes == [("light.turn_on", "light.entrada")]
    assert "he mandado light.turn_on a light.entrada" in cuando.apuntados[0][1]
    assert not cuando.called("PATCH", "reglas_usuario")      # «siempre» no se apaga


def test_siempre_respeta_la_pausa(cuando):
    cuando.add("GET", "/api/events", FakeResponse([
        _ev("c1", camara="garaje", etiqueta="car", hace=60),
        _ev("c2", camara="garaje", etiqueta="car", hace=20)]))
    assert main._frigate_reglas_pasada([_regla(veces="siempre")]) == 1


def test_llamar_y_si_no_suena_avisa(cuando, monkeypatch):
    cuando.add("GET", "/api/events", FakeResponse([_ev("c1", camara="garaje", etiqueta="car")]))
    monkeypatch.setattr(main, "_llamar", lambda texto, **k: False)
    assert main._frigate_reglas_pasada([_regla(hacer="llamar")]) == 1
    assert "No he podido llamarle" in cuando.apuntados[0][1]


def test_caducada_se_apaga_sin_mirar_frigate(cuando):
    assert main._frigate_reglas_pasada([_regla(hasta=time.time() - 10)]) == 0
    assert cuando.called("PATCH", "reglas_usuario") and not cuando.called("GET", "/api/events")


def test_si_lo_pide_el_vale_tras_lo_ajeno():
    assert main._AJENO_SI_LO_PIDES["camaras_cuando"].search(
        "cuando veas un coche entrar en el garaje enciende la luz")
    assert "camaras_cuando" in main._MCP_SERVIDOR_ACCIONES


def test_hasta_la_luz_del_garaje_se_confirma():
    # «garaje» en el nombre basta para confirmarse (`_CASA_NOMBRE_DELICADO`): no se deja preparado.
    assert main._frigate_casa_rechazo("light.turn_on", "light.garaje")
    assert main._frigate_casa_rechazo("light.turn_on", "light.entrada") == ""
