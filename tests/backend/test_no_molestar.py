"""No molestar (`_wa_no_molestar`): Jarvis contesta por ti en clase y en el gimnasio.

Es mandar un mensaje en tu nombre sin que pulses nada, así que lo que se protege son los
candados: solo a la lista, a un grupo solo si te etiquetan de verdad, el texto lo escribe el
backend, una vez cada pocas horas, y nunca si estás contestando tú.
"""
from datetime import datetime, timedelta, timezone

import pytest

import main

AIMAR = "34600000001@s.whatsapp.net"
OTRO = "34600000009@s.whatsapp.net"
GRUPO = "120363000000000001@g.us"
GRUPO_VIEJO = "34635759151-1629495916@g.us"


@pytest.fixture
def nm(monkeypatch):
    enviados = []
    monkeypatch.setattr(main, "WHATSAPP_NO_MOLESTAR", frozenset({AIMAR}))
    monkeypatch.setattr(main, "_wa_nm_enviados", {})
    monkeypatch.setattr(main, "_en_clase", lambda: {"titulo": "RL", "fin": datetime(2026, 11, 9, 12, 0, tzinfo=main.LOCAL_TZ)})
    monkeypatch.setattr(main, "_lugar_actual_seguro", lambda: {"lugar": main.LUGAR_UNI})
    monkeypatch.setattr(main, "_j_whatsapp_enviar", lambda chat, texto: enviados.append((chat, texto)) or {"ok": True})
    return enviados


def _msg(texto, mio=False):
    return {"texto": texto, "mio": mio}


def test_en_clase_contesta_con_la_hora_de_fin(nm):
    assert main._wa_no_molestar(AIMAR, [_msg("¿Vienes luego?")]) is True
    chat, texto = nm[0]
    assert chat == AIMAR
    assert texto.startswith("Mikel está en clase hasta las 12:00")
    assert "¿Vienes luego?" not in texto and texto.endswith(main._WA_NM_FIRMA)


def test_en_el_gimnasio_tambien(nm, monkeypatch):
    monkeypatch.setattr(main, "_en_clase", lambda: None)
    monkeypatch.setattr(main, "_lugar_actual_seguro", lambda: {"lugar": main.LUGAR_GIMNASIO})
    assert main._wa_no_molestar(AIMAR, [_msg("ey")]) is True
    assert nm[0][1].startswith("Mikel está entrenando")


def test_en_casa_no(nm, monkeypatch):
    monkeypatch.setattr(main, "_en_clase", lambda: None)
    monkeypatch.setattr(main, "_lugar_actual_seguro", lambda: {"lugar": main.LUGAR_CASA})
    assert main._wa_no_molestar(AIMAR, [_msg("ey")]) is False and nm == []


@pytest.mark.parametrize("donde", [
    {"lugar": main.LUGAR_CASA},     # ha faltado a clase
    {"lugar": main.LUGAR_FUERA},    # está en otra parte
    None,                           # el móvil no informa: ante la duda no se habla por él
])
def test_con_clase_en_el_calendario_pero_sin_estar_en_la_uni_no(nm, monkeypatch, donde):
    monkeypatch.setattr(main, "_lugar_actual_seguro", lambda: donde)
    assert main._wa_no_molestar(AIMAR, [_msg("¿Vienes luego?")]) is False and nm == []


def test_con_clase_en_el_calendario_y_en_el_gimnasio_dice_que_entrena(nm, monkeypatch):
    monkeypatch.setattr(main, "_lugar_actual_seguro", lambda: {"lugar": main.LUGAR_GIMNASIO})
    assert main._wa_no_molestar(AIMAR, [_msg("ey")]) is True
    assert nm[0][1].startswith("Mikel está entrenando")


def test_en_la_uni_sin_clase_no(nm, monkeypatch):
    monkeypatch.setattr(main, "_en_clase", lambda: None)
    assert main._wa_no_molestar(AIMAR, [_msg("ey")]) is False and nm == []


def test_solo_a_la_lista(nm):
    assert main._wa_no_molestar(OTRO, [_msg("hola")]) is False
    assert nm == []


def _grupo_msg(texto, menciona=None, hace_min=1, mio=False):
    hora = datetime.now(timezone.utc) - timedelta(minutes=hace_min)
    m = {"texto": texto, "mio": mio, "hora": hora.isoformat().replace("+00:00", "Z")}
    if menciona is not None:
        m["menciona"] = menciona
    return m


@pytest.fixture
def con_grupo(nm, monkeypatch):
    monkeypatch.setattr(main, "WHATSAPP_NO_MOLESTAR", frozenset({AIMAR, GRUPO, GRUPO_VIEJO}))
    return nm


@pytest.mark.parametrize("burbuja", [
    [_grupo_msg("hola a todos")],                                  # escribe cualquiera
    [_grupo_msg("Mikel, ¿vienes?")],                               # te nombra sin etiquetar
    [_grupo_msg("@Mikel ¿vienes?", menciona=False)],               # la etiqueta no es de verdad
    [_grupo_msg("@Mikel ¿vienes?", menciona="true")],              # solo el True de verdad cuenta
    [_grupo_msg("@Mikel ¿vienes?", menciona=True, hace_min=30)],   # etiqueta vieja
    [{"texto": "@Mikel", "mio": False, "menciona": True}],         # sin hora no se fía
    [_grupo_msg("@Mikel ¿vienes?", menciona=True, mio=True)],      # la etiqueta es tuya
])
def test_un_grupo_no_se_contesta_sin_etiqueta_de_verdad(con_grupo, burbuja):
    assert main._wa_no_molestar(GRUPO, burbuja) is False
    assert con_grupo == []


def test_un_grupo_si_te_etiquetan(con_grupo):
    assert main._wa_no_molestar(GRUPO, [_grupo_msg("hola"), _grupo_msg("@Mikel ¿vienes?", menciona=True)]) is True
    chat, texto = con_grupo[0]
    assert chat == GRUPO
    assert texto.startswith("Mikel está en clase hasta las 12:00") and texto.endswith(main._WA_NM_FIRMA)
    assert "dímelo" not in texto and "que le llame" in texto      # nadie le pasaría el recado
    assert "vienes" not in texto                                  # no repite lo que dijeron


def test_un_grupo_de_id_antiguo_tambien(con_grupo):
    assert main._wa_no_molestar(GRUPO_VIEJO, [_grupo_msg("@Mikel", menciona=True)]) is True


def test_un_grupo_una_vez_cada_tres_horas_y_si_contestas_no(con_grupo):
    assert main._wa_no_molestar(GRUPO, [_grupo_msg("@Mikel", menciona=True)]) is True
    assert main._wa_no_molestar(GRUPO, [_grupo_msg("@Mikel otra vez", menciona=True)]) is False
    assert main._wa_no_molestar(GRUPO_VIEJO, [_grupo_msg("@Mikel", menciona=True),
                                              _grupo_msg("ya voy", mio=True)]) is False
    assert len(con_grupo) == 1


def test_un_grupo_en_casa_no(con_grupo, monkeypatch):
    monkeypatch.setattr(main, "_lugar_actual_seguro", lambda: {"lugar": main.LUGAR_CASA})
    assert main._wa_no_molestar(GRUPO, [_grupo_msg("@Mikel", menciona=True)]) is False


def test_un_grupo_en_el_gimnasio(con_grupo, monkeypatch):
    monkeypatch.setattr(main, "_en_clase", lambda: None)
    monkeypatch.setattr(main, "_lugar_actual_seguro", lambda: {"lugar": main.LUGAR_GIMNASIO})
    assert main._wa_no_molestar(GRUPO, [_grupo_msg("@Mikel", menciona=True)]) is True
    assert con_grupo[0][1] == f"Mikel está entrenando y no mira el móvil. Si es urgente, que le llame. {main._WA_NM_FIRMA}"


def test_los_mensajes_de_los_grupos_se_piden_solo_en_clase(con_grupo, monkeypatch):
    pedidos = []

    def puente(metodo, ruta, params=None, cuerpo=None):
        pedidos.append(params)
        return {"mensajes": [{"chat": params["chat"], "texto": "@Mikel", "hora": "2026-11-10T11:00:00Z",
                              "menciona": True}]}

    monkeypatch.setattr(main, "_whatsapp", puente)
    extra = main._wa_nm_mensajes_de_grupos([])
    assert {p["chat"] for p in pedidos} == {GRUPO, GRUPO_VIEJO} and len(extra) == 2
    assert all(p["limite"] <= 60 for p in pedidos)             # no se come las plazas de la pasada
    pedidos.clear()
    monkeypatch.setattr(main, "_en_clase", lambda: None)
    monkeypatch.setattr(main, "_lugar_actual_seguro", lambda: {"lugar": main.LUGAR_CASA})
    assert main._wa_nm_mensajes_de_grupos([]) == [] and pedidos == []


def test_un_grupo_caido_no_tira_la_pasada(con_grupo, monkeypatch):
    def puente(metodo, ruta, params=None, cuerpo=None):
        if params["chat"] == GRUPO:
            raise main.WhatsappNoContesta("caído")
        return {"mensajes": [{"chat": params["chat"], "texto": "x", "hora": "2026-11-10T11:00:00Z"}]}

    monkeypatch.setattr(main, "_whatsapp", puente)
    assert [m["chat"] for m in main._wa_nm_mensajes_de_grupos([])] == [GRUPO_VIEJO]


def test_sin_lista_no_contesta_a_nadie(nm, monkeypatch):
    monkeypatch.setattr(main, "WHATSAPP_NO_MOLESTAR", frozenset())
    assert main._wa_no_molestar(AIMAR, [_msg("hola")]) is False


def test_una_vez_cada_tres_horas(nm):
    assert main._wa_no_molestar(AIMAR, [_msg("hola")]) is True
    assert main._wa_no_molestar(AIMAR, [_msg("¿sigues?")]) is False
    assert len(nm) == 1


def test_si_contestas_tu_no_contesta_el(nm):
    assert main._wa_no_molestar(AIMAR, [_msg("¿vienes?"), _msg("sí, ahora voy", mio=True)]) is False


def test_su_propia_respuesta_no_cuenta_como_tuya(nm, monkeypatch):
    monkeypatch.setattr(main, "_wa_nm_enviados", {})
    burbuja = [_msg(f"Mikel está en clase. {main._WA_NM_FIRMA}", mio=True), _msg("es urgente")]
    assert main._wa_no_molestar(AIMAR, burbuja) is True


def test_la_lista_del_entorno_acepta_grupos_y_descarta_basura(monkeypatch):
    monkeypatch.setenv("WHATSAPP_NO_MOLESTAR", f"{AIMAR}, {GRUPO}, {GRUPO_VIEJO}, ../estado,")
    valores = frozenset(c.strip() for c in main.os.getenv("WHATSAPP_NO_MOLESTAR", "").split(",")
                        if c.strip() and main._wa_chat_valido(c.strip()))
    assert valores == frozenset({AIMAR, GRUPO, GRUPO_VIEJO})


def test_si_el_envio_falla_no_se_apunta(nm, monkeypatch):
    monkeypatch.setattr(main, "_j_whatsapp_enviar", lambda chat, texto: {"ok": False, "error": "caído"})
    assert main._wa_no_molestar(AIMAR, [_msg("hola")]) is False
    assert main._wa_nm_enviados == {}
