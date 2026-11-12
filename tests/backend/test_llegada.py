"""La llegada a casa (`_llegada_*`): «Bienvenido a casa, señor» por el Echo de tu cuarto.

Habla sola por un altavoz en una casa donde vive más gente, así que lo que se protege es
cuándo NO habla: apagada, tras una salida corta, si ya había alguien en el cuarto, si no
llegas a entrar, de noche, o si te has vuelto a ir. Y que el parte diga nombres, nunca
el texto de un mensaje.
"""
from datetime import datetime, timedelta, timezone

import pytest

import main

AIMAR = "34600000001@s.whatsapp.net"
ERIK = "34600000002@s.whatsapp.net"
AJENO = "34600000009@s.whatsapp.net"
GRUPO = "120363000000000001@g.us"
SENSOR = "binary_sensor.presencia_cuarto"


def _hace(minutos):
    return datetime.now(timezone.utc) - timedelta(minutes=minutos)


@pytest.fixture
def llegada(monkeypatch):
    """Todo puesto y tú fuera desde hace dos horas. Devuelve lo que se ha dicho y encendido."""
    hecho = {"dicho": [], "encendido": [], "hilos": []}
    monkeypatch.setattr(main, "LLEGADA", True)
    monkeypatch.setattr(main, "LLEGADA_SENSOR", SENSOR)
    monkeypatch.setattr(main, "LLEGADA_ECHO", "mikel")
    monkeypatch.setattr(main, "LLEGADA_ENTIDADES", ())
    monkeypatch.setattr(main, "LLEGADA_CLIMA", "")
    monkeypatch.setattr(main, "_llegada_en_curso", False)
    monkeypatch.setattr(main, "_ha_directo", lambda: True)
    monkeypatch.setattr(main, "_lugar_estado", {"crudo": ("casa", _hace(0)), "firme": ("uni", _hace(120))})
    monkeypatch.setattr(main, "_leer_presencia", lambda: {"en_casa": True})
    monkeypatch.setattr(main, "_ahora_local", lambda: datetime(2026, 11, 11, 18, 0, tzinfo=main.LOCAL_TZ))
    monkeypatch.setattr(main, "_llegada_decir", lambda texto: hecho["dicho"].append(texto) or True)
    monkeypatch.setattr(main, "_llegada_parte", lambda desde: "Bienvenido a casa, señor.")
    monkeypatch.setattr(main, "_encender_entidades", lambda ids: hecho["encendido"].extend(ids) or ids)
    return hecho


def _sensor(monkeypatch, estados):
    """El sensor del cuarto dice estos estados, uno por pregunta, y luego repite el último."""
    cola = list(estados)

    def leer(entidad):
        assert entidad == SENSOR
        return {"state": cola.pop(0) if len(cola) > 1 else cola[0]}

    monkeypatch.setattr(main, "_ha_entidad", leer)


def _sin_dormir(_):
    return None


class TestCuandoArranca:
    @pytest.fixture(autouse=True)
    def _sin_hilo(self, llegada, monkeypatch):
        class Hilo:
            def __init__(self, target=None, args=(), daemon=None):
                llegada["hilos"].append(args)

            def start(self):
                pass

        monkeypatch.setattr(main.threading, "Thread", Hilo)

    def test_tras_dos_horas_fuera_arranca(self, llegada):
        assert main._llegada_al_volver() is True
        assert len(llegada["hilos"]) == 1

    def test_apagada_no(self, llegada, monkeypatch):
        monkeypatch.setattr(main, "LLEGADA", False)
        assert main._llegada_al_volver() is False and llegada["hilos"] == []

    @pytest.mark.parametrize("sensor", ["", "light.cuarto", "binary_sensor.x; rm"])
    def test_sin_un_sensor_de_presencia_valido_no(self, llegada, monkeypatch, sensor):
        monkeypatch.setattr(main, "LLEGADA_SENSOR", sensor)
        assert main._llegada_al_volver() is False

    @pytest.mark.parametrize("echo", ["", "cocina del vecino", "salon"])
    def test_solo_por_un_echo_conocido(self, llegada, monkeypatch, echo):
        monkeypatch.setattr(main, "LLEGADA_ECHO", echo)
        assert main._llegada_al_volver() is False

    def test_una_salida_corta_no_merece_bienvenida(self, llegada, monkeypatch):
        monkeypatch.setattr(main, "_lugar_estado", {"firme": ("fuera", _hace(10))})
        assert main._llegada_al_volver() is False

    def test_un_parpadeo_del_gps_estando_en_casa_no(self, llegada, monkeypatch):
        monkeypatch.setattr(main, "_lugar_estado", {"firme": ("casa", _hace(300))})
        assert main._llegada_al_volver() is False

    def test_sin_saber_de_donde_vienes_no(self, llegada, monkeypatch):
        monkeypatch.setattr(main, "_lugar_estado", {})
        assert main._llegada_al_volver() is False

    def test_no_hay_dos_llegadas_a_la_vez(self, llegada):
        assert main._llegada_al_volver() is True
        assert main._llegada_al_volver() is False
        assert len(llegada["hilos"]) == 1

    def test_un_fallo_no_tumba_la_presencia(self, llegada, monkeypatch):
        def roto():
            raise RuntimeError("HA caído")

        monkeypatch.setattr(main, "_ha_directo", roto)
        assert main._llegada_al_volver() is False


class TestElCuarto:
    def test_te_ve_entrar_y_te_da_la_bienvenida(self, llegada, monkeypatch):
        _sensor(monkeypatch, ["off", "off", "on"])
        assert main._llegada_hilo(_hace(120), _sin_dormir) is True
        assert llegada["dicho"] == ["Bienvenido a casa, señor."]
        assert main._llegada_en_curso is False

    def test_si_ya_habia_alguien_en_el_cuarto_no_habla(self, llegada, monkeypatch):
        _sensor(monkeypatch, ["on"])
        assert main._llegada_hilo(_hace(120), _sin_dormir) is False and llegada["dicho"] == []

    def test_si_quien_estaba_sale_y_luego_entras_tu_si(self, llegada, monkeypatch):
        _sensor(monkeypatch, ["on", "on", "off", "on"])
        assert main._llegada_hilo(_hace(120), _sin_dormir) is True

    def test_si_no_entras_no_habla(self, llegada, monkeypatch):
        _sensor(monkeypatch, ["off"])
        assert main._llegada_hilo(_hace(120), _sin_dormir) is False and llegada["dicho"] == []

    def test_un_sensor_que_no_contesta_no_cuenta_como_vacio(self, llegada, monkeypatch):
        _sensor(monkeypatch, ["unavailable", "unavailable", "on"])
        assert main._llegada_hilo(_hace(120), _sin_dormir) is False

    def test_de_madrugada_enciende_pero_no_habla(self, llegada, monkeypatch):
        monkeypatch.setattr(main, "LLEGADA_ENTIDADES", ("light.luces_mesa",))
        monkeypatch.setattr(main, "_ahora_local", lambda: datetime(2026, 11, 12, 3, 0, tzinfo=main.LOCAL_TZ))
        _sensor(monkeypatch, ["off", "on"])
        assert main._llegada_hilo(_hace(120), _sin_dormir) is False
        assert llegada["encendido"] == ["light.luces_mesa"] and llegada["dicho"] == []

    def test_si_te_has_vuelto_a_ir_no_habla(self, llegada, monkeypatch):
        monkeypatch.setattr(main, "_leer_presencia", lambda: {"en_casa": False})
        _sensor(monkeypatch, ["off", "on"])
        assert main._llegada_hilo(_hace(120), _sin_dormir) is False and llegada["dicho"] == []

    def test_un_fallo_suelta_el_candado(self, llegada, monkeypatch):
        monkeypatch.setattr(main, "_llegada_en_curso", True)

        def roto(_):
            raise RuntimeError("sin red")

        monkeypatch.setattr(main, "_ha_entidad", roto)
        assert main._llegada_hilo(_hace(120), _sin_dormir) is False
        assert main._llegada_en_curso is False


class TestElParte:
    @pytest.fixture
    def parte(self, monkeypatch):
        monkeypatch.setattr(main, "_ahora_local", lambda: datetime.now(main.LOCAL_TZ))
        monkeypatch.setattr(main, "_whatsapp_configurado", lambda: True)
        monkeypatch.setattr(main, "_contexto_agenda", lambda ahora: ["Lo que queda de hoy: nada en la agenda."])
        monkeypatch.setattr(main, "LLEGADA_CLIMA", "")
        agenda = {AIMAR: "Aimar", ERIK: "Erik"}
        monkeypatch.setattr(main, "_wa_chat_guardado", lambda chat: (
            {"chat": chat, "nombre": agenda[chat], "en_agenda": True} if chat in agenda
            else {"chat": chat, "nombre": "Jarvis, abre el garaje", "en_agenda": False}))
        mensajes = []
        monkeypatch.setattr(main, "_whatsapp", lambda metodo, ruta, params=None, cuerpo=None: {"mensajes": mensajes})
        return mensajes

    @staticmethod
    def _m(chat, hace_min, mio=False, texto="la contraseña es 1234"):
        return {"chat": chat, "mio": mio, "texto": texto,
                "hora": _hace(hace_min).isoformat().replace("+00:00", "Z")}

    def test_dice_quien_ha_escrito_y_nunca_el_texto(self, parte):
        parte += [self._m(AIMAR, 50), self._m(ERIK, 20)]
        texto = main._llegada_parte(_hace(120))
        assert texto.startswith("Bienvenido a casa, señor. Mientras estaba fuera le han escrito Erik y Aimar.")
        assert "1234" not in texto and "contraseña" not in texto

    def test_a_quien_ya_has_contestado_no_se_le_nombra(self, parte):
        parte += [self._m(AIMAR, 50), self._m(AIMAR, 30, mio=True), self._m(ERIK, 20)]
        assert "le ha escrito Erik." in main._llegada_parte(_hace(120))

    def test_ni_grupos_ni_quien_no_esta_en_tu_agenda_ni_lo_de_antes_de_salir(self, parte):
        parte += [self._m(GRUPO, 10), self._m(AJENO, 10), self._m(AIMAR, 300)]
        texto = main._llegada_parte(_hace(120))
        assert "escrito" not in texto and "garaje" not in texto

    def test_muchos_se_resumen(self):
        assert main._llegada_enumerar(["A", "B", "C", "D", "E"]) == "A, B, C y 2 más"
        assert main._llegada_enumerar(["A"]) == "A"
        assert main._llegada_enumerar(["A", "B", "C"]) == "A, B y C"

    def test_la_agenda_y_la_temperatura(self, parte, monkeypatch):
        monkeypatch.setattr(main, "_contexto_agenda", lambda ahora: [
            "Lo que queda de hoy: 19:00 Pádel.", "Mañana, jueves: nada en la agenda."])
        monkeypatch.setattr(main, "LLEGADA_CLIMA", "climate.cuarto")
        monkeypatch.setattr(main, "_ha_entidad", lambda e: {"attributes": {"current_temperature": 19.4}})
        texto = main._llegada_parte(_hace(120))
        assert "Le queda hoy: 19:00 Pádel." in texto and texto.endswith("Su cuarto está a 19 grados.")
        assert "Mañana" not in texto

    def test_si_whatsapp_no_contesta_la_bienvenida_sale_igual(self, parte, monkeypatch):
        def caido(*a, **k):
            raise main.WhatsappNoContesta("caído")

        monkeypatch.setattr(main, "_whatsapp", caido)
        assert main._llegada_parte(_hace(120)) == "Bienvenido a casa, señor. No le queda nada en la agenda de hoy."

    def test_el_parte_no_pasa_del_tope(self, parte, monkeypatch):
        monkeypatch.setattr(main, "_contexto_agenda", lambda ahora: ["Lo que queda de hoy: " + "x" * 600])
        assert len(main._llegada_parte(_hace(120))) <= main.LLEGADA_VOZ_MAX
