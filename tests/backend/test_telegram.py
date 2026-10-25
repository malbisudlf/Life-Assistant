"""Tests de Jarvis por Telegram (`POST /telegram/webhook`).

Aquí no se prueba el cerebro —es el mismo de siempre— sino lo que tiene de propio esta
puerta, con la Bot API simulada: quién entra (el secreto, el chat), que un reintento de
Telegram no se atienda dos veces, que el texto y las notas de voz lleguen al turno y
vuelvan formateados, que lo que se confirma llegue con dos botones y que esos botones
respeten la frontera de siempre (la primera respuesta vale, y caducan).
"""
import json
import time
from types import SimpleNamespace

import pytest

import main
from conftest import FakeResponse
from test_jarvis import ClienteFalso, _con_modelo, _herramienta, _llamada, _mensaje  # noqa: E402

CHAT    = "424242"
SECRETO = "secreto-de-prueba"
CABECERA = {"X-Telegram-Bot-Api-Secret-Token": SECRETO}
OGG     = b"OggS\x00\x02nota-de-voz"


@pytest.fixture
def telegram(monkeypatch, mock_requests):
    """Bot configurado, segundo plano en línea y la Bot API simulada."""
    monkeypatch.setattr(main, "TELEGRAM_BOT_TOKEN", "123:token-del-bot")
    monkeypatch.setattr(main, "TELEGRAM_WEBHOOK_SECRET", SECRETO)
    monkeypatch.setattr(main, "TELEGRAM_CHAT_ID", CHAT)
    monkeypatch.setattr(main, "_telegram_lanzar", main._telegram_atender)
    monkeypatch.setattr(main, "FISH_AUDIO_API_KEY", "")
    monkeypatch.setattr(main, "AZURE_SPEECH_KEY", "")
    mock_requests.add("POST", "api.telegram.org/bot",
                      FakeResponse({"ok": True, "result": {"message_id": 77}}))
    return mock_requests


def _api(router, metodo=None):
    """Lo que se le ha mandado a la Bot API: (método, cuerpo) en orden."""
    salida = []
    for metodo_http, url, kwargs in router.calls:
        if "api.telegram.org/bot" not in url or metodo_http != "POST":
            continue
        nombre = url.rsplit("/", 1)[1]
        if metodo is None or nombre == metodo:
            salida.append((nombre, kwargs.get("json") or kwargs.get("data") or {},
                           kwargs.get("files")))
    return salida


def _mensaje_tg(texto=None, update_id=1, chat=CHAT, de=CHAT, voz=None):
    m = {"message_id": 10, "chat": {"id": int(chat), "type": "private"},
         "from": {"id": int(de)}}
    if texto is not None:
        m["text"] = texto
    if voz is not None:
        m["voice"] = voz
    return {"update_id": update_id, "message": m}


def _boton(data, update_id=50, chat=CHAT, de=CHAT):
    return {"update_id": update_id, "callback_query": {
        "id": "cq-1", "data": data, "from": {"id": int(de)},
        "message": {"message_id": 77, "chat": {"id": int(chat)}, "text": "Para confirmar…"}}}


def _post(client, update, cabeceras=CABECERA):
    return client.post("/telegram/webhook", json=update, headers=cabeceras)


# ── Quién entra ───────────────────────────────────────────────────────────────

class TestTelegramAuth:
    def test_sin_secreto_configurado_no_pasa_nada(self, client, telegram, monkeypatch):
        """La regla de `_token_ok`: un secreto vacío no es «todo vale»."""
        monkeypatch.setattr(main, "TELEGRAM_WEBHOOK_SECRET", "")
        for cabeceras in ({}, {"X-Telegram-Bot-Api-Secret-Token": ""},
                          {"X-Telegram-Bot-Api-Secret-Token": "lo-que-sea"}):
            assert _post(client, _mensaje_tg("hola"), cabeceras).status_code == 401
        assert not _api(telegram)

    def test_secreto_malo(self, client, telegram):
        r = _post(client, _mensaje_tg("hola"), {"X-Telegram-Bot-Api-Secret-Token": "otro"})
        assert r.status_code == 401
        assert not _api(telegram)

    def test_otro_chat_se_ignora_en_silencio(self, client, telegram, monkeypatch):
        cliente = _con_modelo(monkeypatch, [_mensaje("no debería contestar")])
        r = _post(client, _mensaje_tg("hola", chat="999", de="999"))
        assert r.status_code == 200
        assert not _api(telegram)
        assert not cliente.recibido

    def test_un_grupo_no_cuela_aunque_escriba_mikel(self, client, telegram, monkeypatch):
        """Chat y remitente tienen que ser el mismo: su chat privado con el bot."""
        cliente = _con_modelo(monkeypatch, [_mensaje("no")])
        assert _post(client, _mensaje_tg("hola", chat="-1001", de=CHAT)).status_code == 200
        assert not cliente.recibido and not _api(telegram)

    def test_alguien_en_el_chat_de_mikel_tampoco(self, client, telegram, monkeypatch):
        cliente = _con_modelo(monkeypatch, [_mensaje("no")])
        assert _post(client, _mensaje_tg("hola", chat=CHAT, de="555")).status_code == 200
        assert not cliente.recibido and not _api(telegram)

    def test_sin_token_del_bot_no_trabaja(self, client, telegram, monkeypatch):
        monkeypatch.setattr(main, "TELEGRAM_BOT_TOKEN", "")
        cliente = _con_modelo(monkeypatch, [_mensaje("no")])
        assert _post(client, _mensaje_tg("hola")).status_code == 200
        assert not cliente.recibido

    def test_cuerpo_desmesurado_da_413(self, client, telegram):
        grande = _mensaje_tg("a" * (main.MAX_BODY_BYTES + 10))
        assert _post(client, grande).status_code == 413

    def test_el_token_del_bot_no_sale_en_el_registro(self, client, telegram, monkeypatch,
                                                     caplog):
        """La URL de la Bot API lleva el token, y la excepción de requests, la URL."""
        def _revienta(url, **kwargs):
            raise ConnectionError(f"no se pudo conectar a {url}")
        telegram.routes.insert(0, ("POST", "api.telegram.org/bot", _revienta))
        _con_modelo(monkeypatch, [_mensaje("Buenas.")])
        _post(client, _mensaje_tg("hola"))
        assert "token-del-bot" not in caplog.text


# ── Duplicados ────────────────────────────────────────────────────────────────

class TestTelegramDuplicados:
    def test_el_mismo_update_se_atiende_una_vez(self, client, telegram, monkeypatch):
        """Telegram reintenta si tardas: el mismo update_id no puede ser dos turnos."""
        cliente = _con_modelo(monkeypatch, [_mensaje("Buenas, señor."), _mensaje("otra vez")])
        assert _post(client, _mensaje_tg("hola", update_id=9)).status_code == 200
        assert _post(client, _mensaje_tg("hola", update_id=9)).status_code == 200
        assert len(_api(telegram, "sendMessage")) == 1
        assert len([c for c in cliente.recibido if not c.get("stream")]) <= 2

    def test_otro_update_si_se_atiende(self, client, telegram, monkeypatch):
        _con_modelo(monkeypatch, [_mensaje("Uno."), _mensaje("Dos.")])
        _post(client, _mensaje_tg("hola", update_id=1))
        _post(client, _mensaje_tg("adiós", update_id=2))
        assert len(_api(telegram, "sendMessage")) == 2


# ── Texto ─────────────────────────────────────────────────────────────────────

class TestTelegramTexto:
    def test_texto_va_al_turno_y_vuelve_en_html(self, client, telegram, monkeypatch):
        _con_modelo(monkeypatch, [_mensaje("Mañana tiene **dos** reuniones, señor.")])
        assert _post(client, _mensaje_tg("qué tengo mañana")).status_code == 200
        (_, cuerpo, _), = _api(telegram, "sendMessage")
        assert cuerpo["chat_id"] == CHAT
        assert cuerpo["parse_mode"] == "HTML"
        assert "<b>dos</b>" in cuerpo["text"]

    def test_va_con_su_propia_boca(self, client, telegram, monkeypatch):
        """Para `jarvis_gasto` y lo que dependa de por dónde entró."""
        vistas = []

        def _turno(body, **kw):
            vistas.append((main._boca_actual.get(), body.voz))
            return {"respuesta": "Hecho."}
        monkeypatch.setattr(main, "_jarvis_chat", _turno)
        _post(client, _mensaje_tg("hola"))
        assert vistas == [("telegram", False)]

    def test_mientras_piensa_dice_escribiendo(self, client, telegram, monkeypatch):
        """El hilo manda la acción al entrar; con el turno ya acabado deja de mandarla."""
        def _turno(body, **kw):
            import time as _t
            _t.sleep(0.2)              # deja al hilo mandar la primera
            return {"respuesta": "Hecho."}
        monkeypatch.setattr(main, "_jarvis_chat", _turno)
        _post(client, _mensaje_tg("hola"))
        acciones = _api(telegram, "sendChatAction")
        assert acciones and all(c["action"] == "typing" and c["chat_id"] == CHAT
                                for _, c, _ in acciones)
        antes = len(acciones)
        import time as _t
        _t.sleep(0.3)
        assert len(_api(telegram, "sendChatAction")) == antes

    def test_la_ventana_lleva_la_conversacion(self, client, telegram, monkeypatch):
        historiales = []

        def _turno(body, **kw):
            historiales.append([(t.rol, t.texto) for t in body.historial])
            return {"respuesta": f"Respuesta a {body.mensaje}"}
        monkeypatch.setattr(main, "_jarvis_chat", _turno)
        _post(client, _mensaje_tg("qué tengo mañana", update_id=1))
        _post(client, _mensaje_tg("¿y pasado?", update_id=2))
        assert historiales[0] == []
        assert historiales[1] == [("user", "qué tengo mañana"),
                                  ("assistant", "Respuesta a qué tengo mañana")]

    def test_la_ventana_caduca(self, client, telegram, monkeypatch):
        historiales = []

        def _turno(body, **kw):
            historiales.append(list(body.historial))
            return {"respuesta": "Vale."}
        monkeypatch.setattr(main, "_jarvis_chat", _turno)
        _post(client, _mensaje_tg("hola", update_id=1))
        monkeypatch.setattr(main, "_telegram_ventana_ts",
                            time.time() - main.TELEGRAM_CONTEXTO_MIN * 60 - 5)
        _post(client, _mensaje_tg("otra cosa", update_id=2))
        assert historiales[1] == []

    def test_la_ventana_no_pasa_del_tope_de_historial(self, client, telegram, monkeypatch):
        historiales = []

        def _turno(body, **kw):
            historiales.append(len(body.historial))
            return {"respuesta": "Vale."}
        monkeypatch.setattr(main, "_jarvis_chat", _turno)
        for n in range(1, 10):
            _post(client, _mensaje_tg(f"mensaje {n}", update_id=n))
        assert max(historiales) <= main.JARVIS_MAX_HISTORIAL

    def test_nuevo_olvida_la_conversacion(self, client, telegram, monkeypatch):
        historiales = []

        def _turno(body, **kw):
            historiales.append(list(body.historial))
            return {"respuesta": "Vale."}
        monkeypatch.setattr(main, "_jarvis_chat", _turno)
        _post(client, _mensaje_tg("hola", update_id=1))
        _post(client, _mensaje_tg("/nuevo", update_id=2))
        _post(client, _mensaje_tg("otra cosa", update_id=3))
        assert len(historiales) == 2 and historiales[1] == []

    def test_si_el_turno_falla_lo_dice_sin_detalles_de_fuera(self, client, telegram,
                                                             monkeypatch):
        def _turno(body, **kw):
            raise main.HTTPException(status_code=503, detail="Falta OPENAI_API_KEY")
        monkeypatch.setattr(main, "_jarvis_chat", _turno)
        _post(client, _mensaje_tg("hola"))
        (_, cuerpo, _), = _api(telegram, "sendMessage")
        assert "No he podido contestar" in cuerpo["text"]

    def test_html_rechazado_se_reenvia_en_texto_plano(self, client, telegram, monkeypatch):
        respuestas = [FakeResponse({"ok": False, "description": "can't parse entities"}, 400),
                      FakeResponse({"ok": True, "result": {"message_id": 3}})]
        telegram.routes.insert(0, ("POST", "/sendMessage", lambda url, **kw: respuestas.pop(0)))
        monkeypatch.setattr(main, "_jarvis_chat", lambda body, **kw: {"respuesta": "**raro*"})
        _post(client, _mensaje_tg("hola"))
        envios = _api(telegram, "sendMessage")
        assert len(envios) == 2
        assert envios[0][1]["parse_mode"] == "HTML"
        assert "parse_mode" not in envios[1][1]
        assert envios[1][1]["text"] == "**raro*"

    def test_lo_largo_se_parte(self, client, telegram, monkeypatch):
        largo = "\n".join(f"Línea {n} " + "x" * 80 for n in range(120))
        monkeypatch.setattr(main, "_jarvis_chat", lambda body, **kw: {"respuesta": largo})
        _post(client, _mensaje_tg("cuéntame mucho"))
        envios = _api(telegram, "sendMessage")
        assert len(envios) >= 3
        assert all(len(c["text"]) <= 4096 for _, c, _ in envios)


# ── Notas de voz ──────────────────────────────────────────────────────────────

class ClienteConOido(ClienteFalso):
    """El modelo falso de siempre, y además Whisper."""

    def __init__(self, guion, transcripcion="qué tengo mañana"):
        super().__init__(guion)
        self.transcripcion = transcripcion
        self.audios = []

    @property
    def audio(self):
        return SimpleNamespace(transcriptions=SimpleNamespace(create=self._transcribir))

    def _transcribir(self, **kwargs):
        self.audios.append(kwargs)
        return SimpleNamespace(text=self.transcripcion)


def _nota(tam=4000):
    return {"file_id": "fid-1", "file_unique_id": "u1", "duration": 3,
            "mime_type": "audio/ogg", "file_size": tam}


def _con_oido(monkeypatch, telegram, guion, transcripcion="qué tengo mañana"):
    cliente = ClienteConOido(guion, transcripcion)
    monkeypatch.setattr(main, "get_openai_client", lambda: cliente)
    telegram.routes.insert(0, ("POST", "/getFile", FakeResponse(
        {"ok": True, "result": {"file_path": "voice/file_1.oga", "file_size": 4000}})))
    telegram.add("GET", "api.telegram.org/file/bot", FakeResponse(content=b"audio-ogg"))
    return cliente


def _fish(monkeypatch, telegram, respuesta):
    monkeypatch.setattr(main, "FISH_AUDIO_API_KEY", "sk-fish")
    telegram.add("POST", "api.fish.audio/v1/tts", respuesta)


def _azure(monkeypatch, telegram, respuesta):
    monkeypatch.setattr(main, "AZURE_SPEECH_KEY", "clave-azure")
    monkeypatch.setattr(main, "AZURE_SPEECH_REGION", "francecentral")
    telegram.add("POST", "tts.speech.microsoft.com", respuesta)


class TestTelegramVoz:
    def test_nota_de_voz_se_contesta_con_voz(self, client, telegram, monkeypatch):
        cliente = _con_oido(monkeypatch, telegram, [_mensaje("Mañana tiene dos cosas, señor.")])
        _fish(monkeypatch, telegram, FakeResponse(content=OGG))
        assert _post(client, _mensaje_tg(voz=_nota())).status_code == 200
        # Whisper recibió el audio que bajó, y el turno fue por voz (prompt hablado).
        assert cliente.audios and cliente.audios[0]["file"][1] == b"audio-ogg"
        sistema = cliente.recibido[0]["messages"][0]["content"]
        assert "HABLADA" in sistema
        (metodo, datos, ficheros), = _api(telegram, "sendVoice")
        assert ficheros["voice"][0] == "jarvis.ogg"
        assert ficheros["voice"][1] == OGG and ficheros["voice"][2] == "audio/ogg"
        assert "qué tengo mañana" in datos["caption"]          # lo que entendió
        assert "dos cosas" in datos["caption"]                 # y lo que contesta
        # Fish delante, en opus; Azure ni se toca.
        fish = telegram.called("POST", "api.fish.audio")
        assert json.loads(json.dumps(fish[0][2]["json"]))["format"] == "opus"
        assert not telegram.called("POST", "tts.speech.microsoft.com")
        assert not _api(telegram, "sendMessage")

    def test_whisper_va_con_su_boca_en_el_gasto(self, client, telegram, monkeypatch):
        gastos = []
        monkeypatch.setattr(main, "_apuntar_gasto",
                            lambda boca, modelo, *a, **kw: gastos.append((boca, modelo)))
        _con_oido(monkeypatch, telegram, [_mensaje("Vale.")])
        _post(client, _mensaje_tg(voz=_nota()))
        assert ("telegram", "whisper-1") in gastos

    def test_si_fish_falla_azure_en_ogg(self, client, telegram, monkeypatch):
        _con_oido(monkeypatch, telegram, [_mensaje("Vale, señor.")])
        _fish(monkeypatch, telegram, FakeResponse(status_code=500, text="caído"))
        _azure(monkeypatch, telegram, FakeResponse(content=OGG))
        _post(client, _mensaje_tg(voz=_nota()))
        (_, _, ficheros), = _api(telegram, "sendVoice")
        assert ficheros["voice"][2] == "audio/ogg"
        azure = telegram.called("POST", "tts.speech.microsoft.com")
        assert azure[0][2]["headers"]["X-Microsoft-OutputFormat"] == "ogg-24khz-16bit-mono-opus"

    def test_un_opus_que_no_es_ogg_va_en_mp3(self, client, telegram, monkeypatch):
        _con_oido(monkeypatch, telegram, [_mensaje("Vale.")])
        respuestas = [FakeResponse(content=b"\x1aE\xdf\xa3webm"),
                      FakeResponse(content=b"ID3mp3")]
        _fish(monkeypatch, telegram, lambda url, **kw: respuestas.pop(0))
        _post(client, _mensaje_tg(voz=_nota()))
        (_, _, ficheros), = _api(telegram, "sendVoice")
        assert ficheros["voice"] == ("jarvis.mp3", b"ID3mp3", "audio/mpeg")

    def test_con_claude_de_motor_la_nota_la_piensa_claude(self, client, telegram, monkeypatch):
        """Pedido el 2026-10-25: las notas de voz de Telegram también van a Claude, con el
        prompt de voz, y la voz sigue siendo la de las notas (Fish delante)."""
        cliente = _con_oido(monkeypatch, telegram, [_mensaje("no debería llegar a OpenAI")])
        _fish(monkeypatch, telegram, FakeResponse(content=OGG))
        monkeypatch.setattr(main, "JARVIS_MOTOR_CHAT", "claude")
        vistos = []

        def _claude(body):
            vistos.append((body.voz, main._sistema_chat(voz=body.voz)))
            return {"respuesta": "Mañana dos cosas, señor.", "herramientas": [],
                    "pendiente": None, "motor": "claude"}
        monkeypatch.setattr(main, "_jarvis_turno_claude", _claude)
        _post(client, _mensaje_tg(voz=_nota()))
        (voz, sistema), = vistos
        assert voz is True and "HABLADA" in sistema
        acciones = {c["action"] for _, c, _ in _api(telegram, "sendChatAction")}
        assert acciones <= {"record_voice"}       # «grabando audio», no «escribiendo»
        assert not [c for c in cliente.recibido if c.get("messages")]   # OpenAI, ni tocado
        assert cliente.audios                                           # Whisper sí
        (_, datos, ficheros), = _api(telegram, "sendVoice")
        assert ficheros["voice"][1] == OGG and "dos cosas" in datos["caption"]

    def test_mp3_rechazado_como_nota_va_como_audio(self, client, telegram, monkeypatch):
        _con_oido(monkeypatch, telegram, [_mensaje("Vale.")])
        respuestas = [FakeResponse(content=b"no-ogg"), FakeResponse(content=b"ID3mp3")]
        _fish(monkeypatch, telegram, lambda url, **kw: respuestas.pop(0))
        telegram.routes.insert(0, ("POST", "/sendVoice", FakeResponse(
            {"ok": False, "description": "VOICE_MESSAGES_FORBIDDEN"}, 400)))
        _post(client, _mensaje_tg(voz=_nota()))
        assert _api(telegram, "sendAudio")

    def test_sin_voz_contesta_por_escrito(self, client, telegram, monkeypatch):
        _con_oido(monkeypatch, telegram, [_mensaje("Mañana nada, señor.")])
        _post(client, _mensaje_tg(voz=_nota()))
        assert not _api(telegram, "sendVoice")
        (_, cuerpo, _), = _api(telegram, "sendMessage")
        assert "Mañana nada" in cuerpo["text"]

    def test_nota_demasiado_grande_no_se_baja(self, client, telegram, monkeypatch):
        cliente = _con_oido(monkeypatch, telegram, [_mensaje("no")])
        _post(client, _mensaje_tg(voz=_nota(tam=main.MAX_AUDIO_BYTES + 1)))
        assert not _api(telegram, "getFile")
        assert not cliente.audios
        (_, cuerpo, _), = _api(telegram, "sendMessage")
        assert "demasiado larga" in cuerpo["text"]

    def test_whisper_con_limitador(self, client, telegram, monkeypatch):
        """Es de pago: sin cupo no se baja ni se transcribe nada."""
        cliente = _con_oido(monkeypatch, telegram, [_mensaje("no")])
        monkeypatch.setattr(main, "AUDIO_MAX_REQUESTS", 0)
        _post(client, _mensaje_tg(voz=_nota()))
        assert not _api(telegram, "getFile")
        assert not cliente.audios

    def test_ruta_rara_de_getfile_no_se_pega_a_la_url(self, client, telegram, monkeypatch):
        cliente = _con_oido(monkeypatch, telegram, [_mensaje("no")])
        telegram.routes.insert(0, ("POST", "/getFile", FakeResponse(
            {"ok": True, "result": {"file_path": "../../otra/cosa"}})))
        _post(client, _mensaje_tg(voz=_nota()))
        assert not telegram.called("GET", "api.telegram.org/file/")
        assert not cliente.audios


# ── Lo que se confirma: los botones ───────────────────────────────────────────

def _propone(monkeypatch, herramienta="cobrar_entrenamiento", argumentos=None):
    monkeypatch.setattr(main, "_jarvis_chat", lambda body, **kw: {
        "respuesta": "Le propongo cobrar las sesiones.",
        "pendiente": {"herramienta": herramienta, "argumentos": argumentos or {}}})


def _pid(router):
    (_, cuerpo, _), = _api(router, "sendMessage")
    botones = cuerpo["reply_markup"]["inline_keyboard"][0]
    assert [b["text"] for b in botones] == ["✅ Sí", "❌ No"]
    return botones[0]["callback_data"].split(":", 1)[1]


class TestTelegramBotones:
    def test_lo_confirmable_llega_con_si_y_no(self, client, telegram, monkeypatch):
        _propone(monkeypatch)
        _post(client, _mensaje_tg("cóbrame las sesiones"))
        (_, cuerpo, _), = _api(telegram, "sendMessage")
        assert "Para confirmar" in cuerpo["text"]
        assert "cobrar_entrenamiento" in cuerpo["text"]
        assert _pid(telegram)

    def test_el_bucle_de_verdad_deja_los_botones(self, client, telegram, monkeypatch):
        """Con el turno real: el modelo pide una herramienta confirmable y no se ejecuta."""
        hechas = []
        _herramienta(monkeypatch, "cobrar_entrenamiento", lambda: hechas.append(1) or {"ok": True})
        _con_modelo(monkeypatch, [_mensaje(tool_calls=[_llamada("cobrar_entrenamiento")]),
                                  _mensaje("Se lo dejo propuesto, señor.")])
        _post(client, _mensaje_tg("cóbrame"))
        assert not hechas
        assert _pid(telegram)

    def test_si_ejecuta_contesta_y_edita(self, client, telegram, monkeypatch):
        hechas = []
        _herramienta(monkeypatch, "cobrar_entrenamiento", lambda: hechas.append(1) or {"ok": True})
        _propone(monkeypatch)
        _post(client, _mensaje_tg("cóbrame", update_id=1))
        pid = _pid(telegram)
        assert _post(client, _boton(f"si:{pid}")).status_code == 200
        assert hechas == [1]
        (_, respuesta, _), = _api(telegram, "answerCallbackQuery")
        assert respuesta["callback_query_id"] == "cq-1"
        (_, editado, _), = _api(telegram, "editMessageText")
        assert "Confirmado" in editado["text"] and "Hecho" in editado["text"]
        assert editado["reply_markup"] == {"inline_keyboard": []}

    def test_dos_toques_no_ejecutan_dos_veces(self, client, telegram, monkeypatch):
        hechas = []
        _herramienta(monkeypatch, "cobrar_entrenamiento", lambda: hechas.append(1) or {"ok": True})
        _propone(monkeypatch)
        _post(client, _mensaje_tg("cóbrame", update_id=1))
        pid = _pid(telegram)
        _post(client, _boton(f"si:{pid}", update_id=50))
        _post(client, _boton(f"si:{pid}", update_id=51))
        assert hechas == [1]
        assert "Ya no está pendiente" in _api(telegram, "editMessageText")[-1][1]["text"]

    def test_no_cancela_sin_ejecutar(self, client, telegram, monkeypatch):
        hechas = []
        _herramienta(monkeypatch, "cobrar_entrenamiento", lambda: hechas.append(1) or {"ok": True})
        _propone(monkeypatch)
        _post(client, _mensaje_tg("cóbrame", update_id=1))
        pid = _pid(telegram)
        _post(client, _boton(f"no:{pid}"))
        assert not hechas
        (_, editado, _), = _api(telegram, "editMessageText")
        assert "Cancelado" in editado["text"]

    def test_caducado_no_ejecuta(self, client, telegram, monkeypatch):
        hechas = []
        _herramienta(monkeypatch, "cobrar_entrenamiento", lambda: hechas.append(1) or {"ok": True})
        _propone(monkeypatch)
        _post(client, _mensaje_tg("cóbrame", update_id=1))
        pid = _pid(telegram)
        main._telegram_pendientes[pid]["ts"] -= main.TELEGRAM_BOTON_MIN * 60 + 5
        _post(client, _boton(f"si:{pid}"))
        assert not hechas
        (_, editado, _), = _api(telegram, "editMessageText")
        assert "Caducado" in editado["text"]

    def test_un_boton_de_otro_chat_se_ignora(self, client, telegram, monkeypatch):
        hechas = []
        _herramienta(monkeypatch, "cobrar_entrenamiento", lambda: hechas.append(1) or {"ok": True})
        _propone(monkeypatch)
        _post(client, _mensaje_tg("cóbrame", update_id=1))
        pid = _pid(telegram)
        _post(client, _boton(f"si:{pid}", chat="999", de="999"))
        assert not hechas
        assert pid in main._telegram_pendientes       # sigue esperando a Mikel
        assert not _api(telegram, "answerCallbackQuery")

    def test_lo_que_se_ejecuta_es_lo_guardado_no_lo_del_boton(self, client, telegram,
                                                              monkeypatch):
        """El botón solo lleva un id: un callback inventado no trae argumentos."""
        hechas = []
        _herramienta(monkeypatch, "cobrar_entrenamiento", lambda: hechas.append(1) or {"ok": True})
        _post(client, _boton("si:cobrar_entrenamiento"))
        _post(client, _boton("si:inventado", update_id=52))
        assert not hechas

    def test_una_herramienta_no_confirmable_no_se_ejecuta_por_aqui(self, client, telegram,
                                                                    monkeypatch):
        """La frontera es la de /jarvis/ejecutar, venga de donde venga."""
        hechas = []
        _herramienta(monkeypatch, "agenda", lambda **kw: hechas.append(1) or {"ok": True})
        main._telegram_pendientes["abc"] = {"herramienta": "agenda", "argumentos": {},
                                            "ts": time.time(), "texto": "x", "frase": "x"}
        _post(client, _boton("si:abc"))
        assert not hechas
        assert "no se confirma por aquí" in _api(telegram, "editMessageText")[0][1]["text"]

    def test_si_falla_al_ejecutar_lo_dice(self, client, telegram, monkeypatch):
        _herramienta(monkeypatch, "cobrar_entrenamiento",
                     lambda: {"ok": False, "error": "No hay sesiones sin cobrar"})
        _propone(monkeypatch)
        _post(client, _mensaje_tg("cóbrame", update_id=1))
        _post(client, _boton(f"si:{_pid(telegram)}"))
        texto = _api(telegram, "editMessageText")[0][1]["text"]
        assert "No ha salido" in texto and "No hay sesiones sin cobrar" in texto

    def test_lo_que_no_valdria_no_se_propone(self, client, telegram, monkeypatch):
        """Un «sí» a algo que luego falla es un botón que miente: sin título, sin botón."""
        _propone(monkeypatch, "crear_evento", {"fecha": "2099-01-01"})
        _post(client, _mensaje_tg("apúntame algo"))
        (_, cuerpo, _), = _api(telegram, "sendMessage")
        assert "reply_markup" not in cuerpo
        assert "No se lo propongo" in cuerpo["text"]
        assert not main._telegram_pendientes

    def test_la_frase_del_calendario_la_escribe_el_backend(self, client, telegram,
                                                           monkeypatch):
        _propone(monkeypatch, "crear_evento",
                 {"titulo": "Dentista", "fecha": "2099-01-02", "hora_inicio": "10:00",
                  "hora_fin": "11:00"})
        _post(client, _mensaje_tg("apúntame el dentista"))
        (_, cuerpo, _), = _api(telegram, "sendMessage")
        assert "Crear «Dentista»" in cuerpo["text"]


# ── El formato (funciones puras) ──────────────────────────────────────────────

class TestTelegramFormato:
    def test_escapa_lo_que_no_es_etiqueta(self):
        assert main._md_a_telegram("a < b & c > d") == "a &lt; b &amp; c &gt; d"

    def test_negrita_cursiva_y_tachado(self):
        html = main._md_a_telegram("**fuerte** *suave* _otra_ ~~no~~")
        assert html == "<b>fuerte</b> <i>suave</i> <i>otra</i> <s>no</s>"

    def test_un_identificador_con_guiones_bajos_no_es_cursiva(self):
        assert main._md_a_telegram("mira mis_capacidades_ya") == "mira mis_capacidades_ya"

    def test_codigo_en_linea_no_interpreta_nada_dentro(self):
        assert main._md_a_telegram("usa `**a** < b`") == "usa <code>**a** &lt; b</code>"

    def test_bloque_de_codigo_con_lenguaje(self):
        html = main._md_a_telegram("```python\nif a < b:\n    **x**\n```")
        assert html == ('<pre><code class="language-python">if a &lt; b:\n    **x**'
                        '</code></pre>')

    def test_bloque_sin_lenguaje(self):
        assert main._md_a_telegram("```\nhola\n```") == "<pre>hola</pre>"

    def test_enlaces_solo_web(self):
        html = main._md_a_telegram("[aquí](https://e.com/a_b?x=1&y=2) y [no](javascript:alert(1))")
        assert '<a href="https://e.com/a_b?x=1&amp;y=2">aquí</a>' in html
        assert "<a" not in html.split(" y ")[1]

    def test_tabla_alineada_en_pre(self):
        html = main._md_a_telegram("| Día | Horas |\n|---|---:|\n| lunes | 7 |\n| **martes** | 6,5 |")
        assert html.startswith("<pre>") and html.endswith("</pre>")
        filas = html[5:-6].split("\n")
        assert filas[0] == "Día     Horas"
        assert filas[2] == "lunes   7"
        assert filas[3] == "martes  6,5"

    def test_titulos_vinetas_y_citas(self):
        html = main._md_a_telegram("## Hoy\n- uno\n* dos\n> ojo & cuidado")
        assert html == "<b>Hoy</b>\n• uno\n• dos\n<blockquote>ojo &amp; cuidado</blockquote>"

    def test_partir_respeta_el_limite(self):
        texto = "\n".join("x" * 100 for _ in range(100))
        trozos = main._partir_telegram(texto, 1000)
        assert len(trozos) > 1
        assert all(len(t) <= 1000 for t in trozos)
        assert "".join(trozos).replace("\n", "") == texto.replace("\n", "")

    def test_partir_una_linea_gigante(self):
        trozos = main._partir_telegram("y" * 2500, 1000)
        assert all(len(t) <= 1000 for t in trozos)
        assert "".join(trozos) == "y" * 2500

    def test_partir_cierra_y_reabre_el_codigo(self):
        texto = "```py\n" + "\n".join(f"linea_{n} = {n}" for n in range(200)) + "\n```"
        trozos = main._partir_telegram(texto, 800)
        assert len(trozos) > 1
        for t in trozos:
            assert t.startswith("```py") and t.rstrip().endswith("```")
            html = main._md_a_telegram(t)
            assert html.startswith('<pre><code class="language-py">')

    def test_lo_corto_no_se_parte(self):
        assert main._partir_telegram("hola") == ["hola"]
        assert main._partir_telegram("   ") == []

    def test_la_voz_no_lee_marcas_ni_urls(self):
        assert main._texto_para_nota("**Hola** mira [esto](https://x.com) y https://y.com") \
            == "Hola mira esto y"
