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
