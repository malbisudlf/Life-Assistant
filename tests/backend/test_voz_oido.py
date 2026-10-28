"""El puente `/voz/oido`: la llamada del navegador escucha con el Whisper de jacobo.

Lo que no puede romperse: que sin sesión no se entre, que la llave de jacobo la ponga el
backend (nunca el navegador), que solo pasen los mensajes que el protocolo conoce y que,
si jacobo no está, el navegador se entere a tiempo de caer a Scribe.
"""
import asyncio
import json
import time

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


def _colgar(ws, jacobo):
    """Cuelga y espera a que el puente termine de cerrar.

    Al salir del `with`, el cliente de pruebas manda el «disconnect» y cancela la app en
    el acto: si el puente aún no ha procesado la desconexión, la cancelación le llega a
    mitad de su limpieza y el test muere con `CancelledError` (solo bajo carga, que es
    como lo vio el CI). Esperar a que cierre el WebSocket de jacobo es esperar a esa
    limpieza."""
    ws.close()
    for _ in range(500):
        if jacobo.cerrado:
            return
        time.sleep(0.01)


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


def test_el_audio_y_el_fin_pasan_y_vuelve_el_texto(client, jacobo):
    with client.websocket_connect("/voz/oido") as ws:
        ws.send_text(json.dumps({"token": main.create_token()}))
        assert json.loads(ws.receive_text()) == {"tipo": "listo"}
        ws.send_bytes(b"\x01\x00" * 160)
        ws.send_text(json.dumps({"tipo": "fin"}))
        assert json.loads(ws.receive_text()) == {"tipo": "final", "texto": "abre spotify"}
        _colgar(ws, jacobo)
    assert jacobo.recibido[0] == b"\x01\x00" * 160
    assert json.loads(jacobo.recibido[1]) == {"tipo": "fin"}


def test_solo_pasa_lo_que_el_protocolo_conoce(client, jacobo):
    with client.websocket_connect("/voz/oido") as ws:
        ws.send_text(json.dumps({"token": main.create_token()}))
        ws.receive_text()
        ws.send_text(json.dumps({"tipo": "cualquier_cosa", "x": 1}))
        ws.send_bytes(b"\x00" * (main.OIDO_TROZO_MAX + 2))   # un trozo desmedido se tira
        ws.send_text(json.dumps({"tipo": "fin"}))
        ws.receive_text()
        _colgar(ws, jacobo)
    assert jacobo.recibido == [json.dumps({"tipo": "fin"})]


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
