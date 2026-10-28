"""La cámara y los proyectos de la vista J.A.R.V.I.S.

La cámara: el fotograma se describe una vez y la descripción llega al modelo como dato,
pegada al mensaje; sin fotograma no se llama a la visión, y si la visión falla el modelo
lo sabe. Los proyectos: el panel ve lo mismo que `ver_proyectos` y habla por la misma
puerta firmada que `hablar_con_el_programador`.
"""
import pytest

import main

FOTOGRAMA = "aGVsbG8="   # base64 de juguete: la visión está simulada


@pytest.fixture
def chat_visto(monkeypatch):
    """El turno que llega a `_jarvis_chat`, sin modelo de verdad detrás."""
    visto = {}

    def _chat(body, **kw):
        visto["mensaje"] = body.mensaje
        visto["camara"] = body.camara
        return {"respuesta": "Le veo, señor.", "herramientas": [], "pendiente": None}
    monkeypatch.setattr(main, "_jarvis_chat", _chat)
    return visto


class TestCamara:
    def test_el_fotograma_se_describe_y_va_como_dato(self, client, auth_headers, chat_visto, monkeypatch):
        pedidos = []
        monkeypatch.setattr(main, "_describir_camara",
                            lambda b64, pregunta="": pedidos.append((b64, pregunta)) or "Lleva una camiseta azul")
        r = client.post("/jarvis", headers=auth_headers,
                        json={"mensaje": "¿qué llevo puesto?", "camara": FOTOGRAMA})
        assert r.status_code == 200
        assert pedidos == [(FOTOGRAMA, "¿qué llevo puesto?")]
        assert chat_visto["mensaje"].startswith("¿qué llevo puesto?")
        assert "camiseta azul" in chat_visto["mensaje"] and "DATO" in chat_visto["mensaje"]
        # El fotograma no sigue viajando: ni al modelo ni a la memoria.
        assert chat_visto["camara"] == ""

    def test_sin_fotograma_no_se_llama_a_la_vision(self, client, auth_headers, chat_visto, monkeypatch):
        monkeypatch.setattr(main, "_describir_camara", lambda *a, **k: pytest.fail("no toca"))
        client.post("/jarvis", headers=auth_headers, json={"mensaje": "hola"})
        assert chat_visto["mensaje"] == "hola"

    def test_si_la_vision_falla_el_modelo_lo_sabe(self, client, auth_headers, chat_visto, monkeypatch):
        def _rota(*a, **k):
            raise RuntimeError("sin cuota")
        monkeypatch.setattr(main, "_describir_camara", _rota)
        r = client.post("/jarvis", headers=auth_headers, json={"mensaje": "¿me ves?", "camara": FOTOGRAMA})
        assert r.status_code == 200
        assert "no se ha podido ver" in chat_visto["mensaje"]

    def test_solo_base64_y_con_tope(self, client, auth_headers, chat_visto):
        r = client.post("/jarvis", headers=auth_headers,
                        json={"mensaje": "hola", "camara": "<script>alert(1)</script>"})
        assert r.status_code == 422
        r = client.post("/jarvis", headers=auth_headers,
                        json={"mensaje": "hola", "camara": "A" * (main.CAMARA_MAX_B64 + 1)})
        assert r.status_code == 422


class TestProyectos:
    def test_piden_sesion(self, client):
        assert client.get("/programador/proyectos").status_code in (401, 403)
        assert client.post("/programador/mensaje", json={"mensaje": "hola"}).status_code in (401, 403)

    def test_sin_programador_lo_dice(self, client, auth_headers, monkeypatch):
        monkeypatch.setattr(main, "_programador_configurado", lambda: False)
        assert client.get("/programador/proyectos", headers=auth_headers).json()["configurado"] is False
        assert client.post("/programador/mensaje", headers=auth_headers,
                           json={"mensaje": "hola"}).status_code == 503

    def test_ve_lo_mismo_que_ver_proyectos(self, client, auth_headers, monkeypatch):
        monkeypatch.setattr(main, "_programador_configurado", lambda: True)
        monkeypatch.setattr(main, "_j_ver_proyectos",
                            lambda: {"ok": True, "proyectos": [{"titulo": "web: la compra", "estado": "trabajando"}]})
        d = client.get("/programador/proyectos", headers=auth_headers).json()
        assert d["configurado"] and d["proyectos"][0]["titulo"] == "web: la compra"

    def test_hablar_va_por_la_puerta_firmada(self, client, auth_headers, monkeypatch):
        monkeypatch.setattr(main, "_programador_configurado", lambda: True)
        dicho = []
        monkeypatch.setattr(main, "_j_hablar_con_el_programador",
                            lambda mensaje, proyecto="": dicho.append((mensaje, proyecto)) or {"ok": True})
        r = client.post("/programador/mensaje", headers=auth_headers,
                        json={"mensaje": "el fondo azul", "proyecto": "la-compra"})
        assert r.json() == {"ok": True}
        assert dicho == [("el fondo azul", "la-compra")]

    def test_encargar_sigue_siendo_algo_que_se_confirma(self):
        """El panel crea por /jarvis/ejecutar: tiene que seguir siendo confirmable."""
        assert main._JARVIS_HERRAMIENTAS["encargar_proyecto"]["confirmar"]
