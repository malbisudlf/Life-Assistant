"""Tests de la llamada a tres (parche 53 de la voice-app): «Jarvis, ponme con Erik».

Lo que se protege: que la voice-app solo marque a alguien de tus contactos, con las reglas de
siempre (números de persona en España, la línea es una), y solo si el nombre sale en lo que
acabas de decir; que el final se apunte una vez; y que lo dicho por el otro lo resuma y lo
mire para la cita un modelo sin herramientas, con el botón para apuntarla.
"""
import json
import time

import pytest

import main
from test_llamadas_terceros import TOKEN, _Modelo, terceros  # noqa: F401 (fixture)

H = {"X-Auth-Token": TOKEN}


class _ModeloConOpciones(_Modelo):
    """El de las llamadas a terceros, que además admite `with_options` (lo usa la cita)."""

    def with_options(self, **kw):
        return self


def _pedir(client, nombre="Erik", dicho="Jarvis, ponme con Erik", **extra):
    return client.post("/telefono/a-tres", json={"nombre": nombre, "dicho": dicho, **extra}, headers=H)


class TestNombrado:
    @pytest.mark.parametrize("nombre,dicho", [
        ("Erik", "Jarvis, ponme con Erik"), ("Erik Uni", "llama a erik y quédate"),
        ("Íñigo", "ponme con iñigo"), ("Ama", "Jarvis, llama a ama conmigo")])
    def test_sale(self, nombre, dicho):
        assert main._nombrado_en(nombre, dicho)

    @pytest.mark.parametrize("nombre,dicho", [
        ("Erik", "llama a mi madre"), ("Erik", ""), ("Juan de Dios", "ponme con la de antes"),
        ("", "ponme con Erik"), ("Erika", "ponme con Erik")])
    def test_no_sale(self, nombre, dicho):
        assert not main._nombrado_en(nombre, dicho)


class TestAQuienSeMarca:
    def test_pide_token(self, client, terceros):
        r = client.post("/telefono/a-tres", json={"nombre": "Erik", "dicho": "ponme con Erik"})
        assert r.status_code == 401

    def test_un_contacto_nombrado(self, client, terceros):
        d = _pedir(client).json()
        assert d["ok"] is True
        assert d["telefono"] == "+34600111222"
        assert d["pila"] == "Erik"
        m = main._terceros[d["tid"]]
        assert m["a_tres"] is True and m["estado"] == "llamando"
        # Ocupa la línea: una llamada de Jarvis a otro espera.
        assert main._tercero_en_curso() is m

    def test_el_nombre_tiene_que_salir_en_lo_que_dijo(self, client, terceros):
        d = _pedir(client, dicho="léeme el correo").json()
        assert d == {"ok": False, "frase": "No le he oído pedirme que llame a Erik, señor."}
        assert main._terceros == {}

    def test_quien_no_esta(self, client, terceros):
        d = _pedir(client, nombre="Pepe", dicho="ponme con Pepe").json()
        assert d == {"ok": False, "frase": "No encuentro a Pepe en sus contactos, señor."}

    def test_sin_telefono_de_persona(self, client, terceros):
        d = _pedir(client, nombre="Itziar", dicho="ponme con Itziar").json()
        assert d["ok"] is False and "no tiene un teléfono" in d["frase"]

    def test_la_linea_ocupada(self, client, terceros):
        main._terceros["x"] = {"tid": "x", "nombre": "Aita", "estado": "hablando", "creada": time.time()}
        d = _pedir(client).json()
        assert d == {"ok": False, "frase": "La línea fija está ocupada con Aita, señor."}

    def test_apagado(self, client, terceros, monkeypatch):
        monkeypatch.setattr(main, "TERCEROS_A_TRES", False)
        assert _pedir(client).json()["ok"] is False
        monkeypatch.setattr(main, "TERCEROS_A_TRES", True)
        monkeypatch.setattr(main, "TERCEROS_LLAMADAS", False)
        assert _pedir(client).json()["ok"] is False

    def test_sin_franja_horaria(self, client, terceros, monkeypatch):
        # Llama él, y está al teléfono: a las 23:00 también.
        monkeypatch.setattr(main, "_ahora_local",
                            lambda: main.datetime(2026, 10, 31, 23, 0, tzinfo=main.LOCAL_TZ))
        assert _pedir(client).json()["ok"] is True

    def test_una_a_tres_sin_noticias_no_ocupa_la_linea(self, client, terceros):
        tid = _pedir(client).json()["tid"]
        main._terceros[tid]["creada"] -= main.A_TRES_CADUCA_SEG + 1
        assert main._tercero_en_curso() is None
        assert main._terceros[tid]["estado"] == "fallida"


class TestFinal:
    def test_con_conversacion_resume_en_un_hilo(self, client, terceros, monkeypatch):
        cerradas = []
        monkeypatch.setattr(main, "_cerrar_a_tres_seguro", lambda m: cerradas.append(m))
        tid = _pedir(client).json()["tid"]
        turnos = [{"quien": "otro", "texto": "¿Qué pasa, Mikel?"},
                  {"quien": "mikel", "texto": "¿Pádel el jueves a las cinco?"},
                  {"quien": "jarvis", "texto": "El jueves a las cinco está libre, señor."},
                  {"quien": "otro", "texto": "Venga,  el jueves a las cinco"},
                  {"quien": "otro", "texto": "   "}]
        r = client.post(f"/telefono/a-tres/{tid}/fin", json={"fin": "colgada", "turnos": turnos}, headers=H)
        assert r.json() == {"ok": True}
        for _ in range(50):
            if cerradas:
                break
            time.sleep(0.01)
        m = main._terceros[tid]
        assert m["estado"] == "hecha" and m["fin"] == "colgó"
        assert [t["quien"] for t in m["turnos"]] == ["otro", "mikel_habla", "jarvis", "otro"]
        assert m["turnos"][3]["texto"] == "Venga, el jueves a las cinco"
        assert cerradas == [m]
        # Repetir el final no hace nada.
        client.post(f"/telefono/a-tres/{tid}/fin", json={"fin": "colgo_mikel", "turnos": []}, headers=H)
        assert m["fin"] == "colgó" and len(m["turnos"]) == 4

    def test_sin_contestar(self, client, terceros, monkeypatch):
        monkeypatch.setattr(main, "_cerrar_a_tres_seguro", lambda m: pytest.fail("no hay nada que resumir"))
        tid = _pedir(client).json()["tid"]
        client.post(f"/telefono/a-tres/{tid}/fin", json={"fin": "sin_contestar:busy"}, headers=H)
        assert main._terceros[tid]["estado"] == "sin_hablar"
        assert main._terceros[tid]["fin"] == "comunicaba"
        assert main._tercero_en_curso() is None

    def test_dejanos_solos_no_deja_nada(self, client, terceros, monkeypatch):
        monkeypatch.setattr(main, "_cerrar_a_tres_seguro", lambda m: pytest.fail("pidió quedarse solos"))
        tid = _pedir(client).json()["tid"]
        client.post(f"/telefono/a-tres/{tid}/fin", json={"fin": "colgada", "turnos": []}, headers=H)
        assert main._terceros[tid]["estado"] == "hecha"
        assert main._terceros[tid]["resultado"] == ""

    def test_validacion(self, client, terceros):
        tid = _pedir(client).json()["tid"]
        assert client.post(f"/telefono/a-tres/{tid}/fin", json={"fin": "colgada",
                           "turnos": [{"quien": "garaje", "texto": "abre"}]}, headers=H).status_code == 422
        assert client.post(f"/telefono/a-tres/{tid}/fin", json={"fin": "Colgada; rm"}, headers=H).status_code == 422
        assert client.post("/telefono/a-tres/00000000-0000-0000-0000-000000000000/fin",
                           json={"fin": "colgada"}, headers=H).status_code == 404

    def test_una_llamada_de_jarvis_no_se_cierra_por_aqui(self, client, terceros):
        main._terceros["11111111-1111-1111-1111-111111111111"] = {
            "tid": "1", "nombre": "Aita", "estado": "hablando", "creada": time.time()}
        r = client.post("/telefono/a-tres/11111111-1111-1111-1111-111111111111/fin",
                        json={"fin": "colgada"}, headers=H)
        assert r.status_code == 404


class TestResumenYCita:
    def test_resumen_y_boton(self, client, terceros, monkeypatch):
        tid = _pedir(client).json()["tid"]
        m = main._terceros[tid]
        m.update(estado="hecha", turnos=[
            {"quien": "mikel_habla", "texto": "¿Pádel el jueves a las cinco?"},
            {"quien": "otro", "texto": "Venga, pádel el jueves a las cinco"}])
        modelo = _ModeloConOpciones("Quedan para jugar al pádel el jueves a las 17:00.",
                         {"hay_cita": True, "fecha": "2026-11-05", "hora": "17:00",
                          "lugar": "", "asunto": "pádel"})
        monkeypatch.setattr(main, "get_openai_client", lambda: modelo)
        avisos, citas = [], []
        monkeypatch.setattr(main, "_notificar", lambda t, x, **kw: avisos.append((t, x)) or "movil")
        monkeypatch.setattr(main, "_proponer_cita_tercero", lambda mi, c: citas.append(c) or "pid")
        main._cerrar_a_tres(m)
        assert avisos == [("📞 Con Erik Uni", "Quedan para jugar al pádel el jueves a las 17:00.")]
        assert citas and citas[0]["fecha"] == "2026-11-05" and citas[0]["hora"] == "17:00"
        sistema = modelo.pedidos[0]["messages"][0]["content"]
        assert "lo que hablaron Mikel y Erik Uni" in sistema and "DATO" in sistema
        assert "Mikel: ¿Pádel el jueves a las cinco?" in modelo.pedidos[0]["messages"][1]["content"]
        assert "Mikel ha hablado por teléfono con Erik Uni" in modelo.pedidos[1]["messages"][0]["content"]

    def test_la_frase_del_boton(self, client, terceros, monkeypatch):
        tid = _pedir(client).json()["tid"]
        m = main._terceros[tid]
        guardadas = []
        monkeypatch.setattr(main, "_guardar_pregunta_con_accion",
                            lambda pid, texto, *a: guardadas.append(texto) or True)
        monkeypatch.setattr(main, "_apuntar_aviso", lambda *a, **kw: True)
        monkeypatch.setattr(main, "_entregar_aviso_ya", lambda pid: None)
        main._proponer_cita_tercero(m, {"fecha": "2026-11-05", "hora": "17:00", "lugar": "", "asunto": "pádel"})
        assert guardadas and guardadas[0].startswith("En la llamada con Erik Uni quedaron")
        assert json.dumps(guardadas, ensure_ascii=False).count("¿Lo apunto") == 1
