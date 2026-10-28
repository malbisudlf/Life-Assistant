"""El puente `/voz/oido`: la llamada del navegador escucha con el Whisper de jacobo.

Lo que no puede romperse: que sin sesión no se entre, que la llave de jacobo la ponga el
backend (nunca el navegador), que solo pasen los mensajes que el protocolo conoce y que,
si jacobo no está, el navegador se entere a tiempo de caer a Scribe.
"""
import asyncio
import json

import pytest
from starlette.websockets import WebSocketDisconnect

import main


class _Jacobo:
    """El WebSocket de jacobo, simulado: apunta lo que recibe y contesta un final por
    cada «fin»."""

    def __init__(self):
        self.recibido = []
        self.cola = asyncio.Queue()
        self.cerrado = False

    async def send(self, dato):
        self.recibido.append(dato)
        if isinstance(dato, str) and json.loads(dato).get("tipo") == "fin":
            await self.cola.put(json.dumps({"tipo": "final", "texto": "abre spotify"}))

    def __aiter__(self):
        return self

    async def __anext__(self):
        msg = await self.cola.get()
        if msg is None:
            raise StopAsyncIteration
        return msg

    async def close(self):
        self.cerrado = True


@pytest.fixture
def jacobo(monkeypatch):
    falso = _Jacobo()

    async def _conectar():
        return falso
    monkeypatch.setattr(main, "OIDO_URL", "http://jacobo.test:8770")
    monkeypatch.setattr(main, "OIDO_TOKEN", "llave-de-jacobo")
    monkeypatch.setattr(main, "_oido_conectar", _conectar)
    return falso


def test_sin_sesion_no_se_entra(client, jacobo):
    with client.websocket_connect("/voz/oido") as ws:
        ws.send_text(json.dumps({"token": "no-es-un-jwt"}))
        with pytest.raises(WebSocketDisconnect) as e:
            ws.receive_text()
    assert e.value.code == 1008
    assert jacobo.recibido == []


def test_un_token_con_proposito_no_vale_como_sesion(client, jacobo):
    """El `state` de OAuth está firmado con la misma clave: no puede abrir el micro."""
    state = main._create_oauth_state()
    with client.websocket_connect("/voz/oido") as ws:
        ws.send_text(json.dumps({"token": state}))
        with pytest.raises(WebSocketDisconnect) as e:
            ws.receive_text()
    assert e.value.code == 1008


class _Navegador:
    """El WebSocket del navegador, simulado: entrega los mensajes de `guion` y luego se
    desconecta, y apunta lo que le mandan."""

    def __init__(self, guion):
        self.guion = list(guion) + [{"type": "websocket.disconnect"}]
        self.enviado = []
        self.cerrado = False

    async def receive(self):
        # Un respiro entre mensajes, para que lo que contesta jacobo llegue en orden.
        await asyncio.sleep(0.01)
        return self.guion.pop(0)

    async def send_text(self, texto):
        self.enviado.append(json.loads(texto))

    async def close(self):
        self.cerrado = True


def _puente(navegador, jacobo):
    asyncio.run(main._oido_puente(navegador, jacobo, max_seg=5))


def test_el_audio_y_el_fin_pasan_y_vuelve_el_texto():
    jacobo, nav = _Jacobo(), _Navegador([
        {"type": "websocket.receive", "bytes": b"\x01\x00" * 160},
        {"type": "websocket.receive", "text": json.dumps({"tipo": "fin"})},
        {"type": "websocket.receive", "text": json.dumps({"tipo": "reinicia"})},
    ])
    _puente(nav, jacobo)
    assert jacobo.recibido[0] == b"\x01\x00" * 160
    assert json.loads(jacobo.recibido[1]) == {"tipo": "fin"}
    assert nav.enviado == [{"tipo": "final", "texto": "abre spotify"}]
    assert jacobo.cerrado and nav.cerrado


def test_solo_pasa_lo_que_el_protocolo_conoce():
    jacobo, nav = _Jacobo(), _Navegador([
        {"type": "websocket.receive", "text": json.dumps({"tipo": "cualquier_cosa", "x": 1})},
        {"type": "websocket.receive", "text": "no es json"},
        {"type": "websocket.receive", "bytes": b"\x00" * (main.OIDO_TROZO_MAX + 2)},
        {"type": "websocket.receive", "text": json.dumps({"tipo": "fin"})},
    ])
    _puente(nav, jacobo)
    assert jacobo.recibido == [json.dumps({"tipo": "fin"})]


def test_si_jacobo_se_cierra_el_navegador_se_entera():
    jacobo, nav = _Jacobo(), _Navegador([{"type": "websocket.receive", "text": "{}"}] * 50)
    jacobo.cola.put_nowait(None)          # jacobo cuelga en cuanto empieza
    _puente(nav, jacobo)
    assert nav.enviado[-1] == {"tipo": "error", "detalle": "jacobo_se_cerro"}


def test_el_puente_por_el_endpoint_dice_listo(client, jacobo):
    with client.websocket_connect("/voz/oido") as ws:
        ws.send_text(json.dumps({"token": main.create_token()}))
        assert json.loads(ws.receive_text()) == {"tipo": "listo"}


def test_sin_oido_configurado_lo_dice(client, monkeypatch):
    monkeypatch.setattr(main, "OIDO_URL", "")
    with client.websocket_connect("/voz/oido") as ws:
        ws.send_text(json.dumps({"token": main.create_token()}))
        assert json.loads(ws.receive_text())["detalle"] == "sin_oido"


def test_si_jacobo_no_contesta_el_navegador_se_entera(client, monkeypatch):
    async def _apagado():
        raise OSError("connection refused")
    monkeypatch.setattr(main, "OIDO_URL", "http://jacobo.test:8770")
    monkeypatch.setattr(main, "OIDO_TOKEN", "llave")
    monkeypatch.setattr(main, "_oido_conectar", _apagado)
    with client.websocket_connect("/voz/oido") as ws:
        ws.send_text(json.dumps({"token": main.create_token()}))
        assert json.loads(ws.receive_text())["detalle"] == "jacobo_no_contesta"


def test_la_url_es_la_de_escucha_a_16_khz(monkeypatch):
    monkeypatch.setattr(main, "OIDO_URL", "http://jacobo.test:8770")
    assert main._oido_url_escucha() == "ws://jacobo.test:8770/escucha?hz=16000&idioma=es"
