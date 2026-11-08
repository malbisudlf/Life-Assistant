"""No molestar (`_wa_no_molestar`): Jarvis contesta por ti en clase y en el gimnasio.

Es mandar un mensaje en tu nombre sin que pulses nada, así que lo que se protege son los
candados: solo a la lista, nunca a un grupo, el texto lo escribe el backend, una vez cada
pocas horas, y nunca si estás contestando tú.
"""
from datetime import datetime

import pytest

import main

AIMAR = "34600000001@s.whatsapp.net"
OTRO = "34600000009@s.whatsapp.net"


@pytest.fixture
def nm(monkeypatch):
    enviados = []
    monkeypatch.setattr(main, "WHATSAPP_NO_MOLESTAR", frozenset({AIMAR}))
    monkeypatch.setattr(main, "_wa_nm_enviados", {})
    monkeypatch.setattr(main, "_en_clase", lambda: {"titulo": "RL", "fin": datetime(2026, 11, 9, 12, 0, tzinfo=main.LOCAL_TZ)})
    monkeypatch.setattr(main, "_lugar_actual_seguro", lambda: None)
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


@pytest.mark.parametrize("chat", [OTRO, "120363000000000001@g.us"])
def test_solo_a_la_lista_y_nunca_a_un_grupo(nm, monkeypatch, chat):
    monkeypatch.setattr(main, "WHATSAPP_NO_MOLESTAR", frozenset({AIMAR, chat}))
    if chat.endswith("@g.us"):
        assert main._wa_no_molestar(chat, [_msg("hola")]) is False
    else:
        monkeypatch.setattr(main, "WHATSAPP_NO_MOLESTAR", frozenset({AIMAR}))
        assert main._wa_no_molestar(chat, [_msg("hola")]) is False
    assert nm == []


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


def test_la_lista_del_entorno_descarta_grupos_y_basura(monkeypatch):
    monkeypatch.setenv("WHATSAPP_NO_MOLESTAR", f"{AIMAR}, 120363000000000001@g.us, ../estado,")
    import importlib
    valores = frozenset(c.strip() for c in main.os.getenv("WHATSAPP_NO_MOLESTAR", "").split(",")
                        if c.strip() and not c.strip().endswith("@g.us") and main._wa_chat_valido(c.strip()))
    assert valores == frozenset({AIMAR})


def test_si_el_envio_falla_no_se_apunta(nm, monkeypatch):
    monkeypatch.setattr(main, "_j_whatsapp_enviar", lambda chat, texto: {"ok": False, "error": "caído"})
    assert main._wa_no_molestar(AIMAR, [_msg("hola")]) is False
    assert main._wa_nm_enviados == {}
