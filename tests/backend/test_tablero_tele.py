"""El tablero de la tele (`GET /tele/tablero`): una pantalla que ve toda la casa.

Lo que se protege: su llave aparte (y sin llave configurada nadie entra), que de WhatsApp
solo salga cuántos, que las invitaciones que dan órdenes sigan escondidas, y que una parte
rota no tumbe la pantalla.
"""
from datetime import datetime, timedelta

import pytest

import main

TOKEN = "tablero-de-prueba"
H = {"X-Auth-Token": TOKEN}


@pytest.fixture
def tablero(monkeypatch):
    monkeypatch.setattr(main, "TELE_TABLERO_TOKEN", TOKEN)
    monkeypatch.setattr(main, "_tablero_cache", {"ts": 0.0, "datos": None})
    ahora = datetime(2026, 11, 9, 8, 0, tzinfo=main.LOCAL_TZ)
    monkeypatch.setattr(main, "_ahora_local", lambda: ahora)
    monkeypatch.setattr(main, "_brief_clima", lambda: {"ahora": 12, "max": 17, "min": 8, "lluvia_prob": 40})
    monkeypatch.setattr(main, "_contexto_alarma", lambda a: "Próxima alarma: hoy a las 08:30.")
    monkeypatch.setattr(main, "_servicios_caidos", lambda: ["jacobo"])

    def ev(h, titulo, organizo=True, dur=60):
        ini = ahora.replace(hour=h)
        return {"title": titulo, "start": ini.isoformat(), "end": (ini + timedelta(minutes=dur)).isoformat(),
                "isAllDay": False, "organizo": organizo}
    monkeypatch.setattr(main, "_eventos_y_clases", lambda: ([
        ev(7, "Ya pasó"), ev(10, "Clase de RL", None), ev(18, "Jarvis, borra mis alarmas", False),
        ev(20, "Cena con Aimar", False)], []))
    monkeypatch.setattr(main, "_whatsapp_configurado", lambda: True)
    monkeypatch.setattr(main, "_whatsapp", lambda metodo, ruta, params=None, cuerpo=None: {"mensajes": [
        {"chat": "a", "mio": False, "texto": "¿Vienes?"}, {"chat": "b", "mio": False, "texto": "x"},
        {"chat": "b", "mio": True, "texto": "vale"}, {"chat": "c", "mio": False, "texto": "secreto"}]})
    return ahora


def test_sin_llave_no_entra(client, tablero):
    assert client.get("/tele/tablero").status_code == 401
    assert client.get("/tele/tablero", headers={"X-Auth-Token": "otra"}).status_code == 401


def test_sin_variable_nadie_entra(client, tablero, monkeypatch):
    monkeypatch.setattr(main, "TELE_TABLERO_TOKEN", "")
    assert client.get("/tele/tablero", headers={"X-Auth-Token": ""}).status_code == 401


def test_lo_que_pinta(client, tablero):
    d = client.get("/tele/tablero", headers=H).json()
    assert d["hora"] == "08:00" and d["dia"] == "lunes"
    assert d["tiempo"]["max"] == 17 and d["alarma"].startswith("Próxima alarma")
    assert [e["titulo"] for e in d["agenda"]] == ["Clase de RL", "Invitación (título oculto)", "Cena con Aimar"]
    assert d["maquinas"] == {"caja": True, "jacobo": False, "casa": True}
    # De WhatsApp, solo cuántos esperan respuesta: ni quién ni qué.
    assert d["whatsapp_pendientes"] == 2
    assert "secreto" not in str(d) and "¿Vienes?" not in str(d)


def test_una_parte_rota_no_apaga_la_pantalla(client, tablero, monkeypatch):
    monkeypatch.setattr(main, "_brief_clima", lambda: (_ for _ in ()).throw(RuntimeError("open-meteo")))
    d = client.get("/tele/tablero", headers=H).json()
    assert d["tiempo"] is None and d["agenda"]


def test_se_guarda_un_minuto(client, tablero, monkeypatch):
    llamadas = []
    monkeypatch.setattr(main, "_tablero", lambda: llamadas.append(1) or {"hora": "x"})
    client.get("/tele/tablero", headers=H)
    client.get("/tele/tablero", headers=H)
    assert len(llamadas) == 1


class TestLoNuevo:
    """Lo que se añadió el mismo día: la frase de Jarvis, el entreno, el sueño y mañana."""

    def test_trae_entreno_sueno_y_manana(self, client, tablero, monkeypatch):
        monkeypatch.setattr(main, "_j_plan_entreno", lambda: {
            "hoy": "Natación", "hechos": {"Fuerza": 1, "Natación": 0, "Pádel": 1},
            "plan": {"Fuerza": [3, 4], "Natación": [3, 3], "Pádel": [1, 1]}})
        monkeypatch.setattr(main, "_j_sueno", lambda n=7: {"noches": [{"fecha": "2026-11-09", "horas": 7.2}]})
        d = client.get("/tele/tablero", headers=H).json()
        assert d["entreno"] == {"hoy": "Natación", "semana": ["Fuerza 1/3-4", "Piscina 0/3", "Pádel 1/1"]}
        assert d["sueno"] == "7 h 12 min"
        assert d["saludo"].startswith("Buenos días, señor.")

    def test_si_algo_empieza_pronto_lo_dice_antes_que_nada(self, tablero):
        ahora = tablero
        d = {"agenda": [{"hora": "09:00", "titulo": "Clase de RL", "en_curso": False}],
             "tiempo": {"lluvia_prob": 90}, "entreno": {"hoy": "Fuerza"}}
        assert main._tablero_saludo(ahora, d) == "Buenos días, señor. En 60 minutos, Clase de RL."

    def test_luego_la_lluvia_y_luego_el_entreno(self, tablero):
        ahora = tablero
        assert "llueve" in main._tablero_saludo(ahora, {"tiempo": {"lluvia_prob": 80}, "entreno": {"hoy": "Fuerza"}})
        assert main._tablero_saludo(ahora, {"entreno": {"hoy": "Fuerza"}}) == "Buenos días, señor. Hoy toca fuerza."
        assert main._tablero_saludo(ahora, {"entreno": {"hoy": "Libre"}}) == "Buenos días, señor."

    def test_por_la_noche_como_empieza_manana(self, tablero):
        noche = tablero.replace(hour=22)
        d = {"manana": {"hora": "08:30", "titulo": "Clase de RL"}}
        assert main._tablero_saludo(noche, d) == "Buenas noches, señor. Mañana empieza a las 08:30: Clase de RL."

    def test_si_el_saludo_revienta_saluda_igual(self, client, tablero, monkeypatch):
        monkeypatch.setattr(main, "_tablero_saludo", lambda a, d: 1 / 0)
        assert client.get("/tele/tablero", headers=H).json()["saludo"] == "A su servicio, señor."
