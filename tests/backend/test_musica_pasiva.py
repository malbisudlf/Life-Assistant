"""La música de la escucha pasiva (telefono/musica/servidor.py, parche 50).

librespot y ffmpeg no se prueban aquí. Lo que sí: que sin oyentes no se lee la fuente (es
lo que para la canción al decir «Jarvis»), que entre canciones sale silencio al mismo ritmo
(si no, FreeSWITCH da el MP3 por acabado) y que el volumen se aplica.
"""
import importlib.util
import io
import os
import threading
import time
import urllib.request

# Por su ruta y con nombre propio: el oído, la voz y la huella también tienen un
# `servidor.py`, y con `import servidor` se cogería el que otro test cargó antes.
_RUTA = os.path.join(os.path.dirname(__file__), "..", "..", "telefono", "musica", "servidor.py")
_spec = importlib.util.spec_from_file_location("musica_servidor", _RUTA)
srv = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(srv)


class FuenteContada(io.RawIOBase):
    """Una fuente infinita que apunta cuánto le han leído."""

    def __init__(self):
        self.leido = 0

    def readable(self):
        return True

    def read(self, n=-1):
        self.leido += n
        return b"\x10\x00" * (n // 2)


class Sumidero(io.RawIOBase):
    def __init__(self):
        self.trozos = []

    def writable(self):
        return True

    def write(self, b):
        self.trozos.append(bytes(b))
        return len(b)


def test_sin_oyentes_no_se_lee_la_fuente():
    oyentes = srv.Oyentes()
    fuente = FuenteContada()
    grifo = srv.Grifo(fuente, Sumidero(), oyentes)
    hilo = threading.Thread(target=grifo.leer, daemon=True)
    hilo.start()
    time.sleep(0.2)
    assert fuente.leido == 0
    q = oyentes.alta()
    time.sleep(0.2)
    assert fuente.leido > 0
    # La cola es corta: con alguien escuchando pero sin consumir, la fuente también espera.
    assert grifo.cola.qsize() <= 10
    oyentes.baja(q)
    grifo.parar.set()


def test_sin_musica_sale_silencio_del_mismo_tamano():
    grifo = srv.Grifo(FuenteContada(), Sumidero(), srv.Oyentes())
    assert grifo.paso() == srv.SILENCIO and len(srv.SILENCIO) == srv.TROZO
    grifo.cola.put(b"\x00\x10" * (srv.TROZO // 2))
    assert grifo.paso() != srv.SILENCIO
    assert (grifo.musica, grifo.silencio) == (1, 1)


def test_marca_el_ritmo_sin_ir_lenta():
    """Con un reloj falso: 50 trozos son un segundo, aunque cada uno tarde algo."""
    oyentes, destino = srv.Oyentes(), Sumidero()
    oyentes.alta()
    reloj = {"t": 0.0}

    def dormir(s):
        reloj["t"] += s + 0.001          # cada espera se pasa un poco
        if len(destino.trozos) >= 50:
            grifo.parar.set()

    grifo = srv.Grifo(FuenteContada(), destino, oyentes, reloj=lambda: reloj["t"], dormir=dormir)
    grifo.marcar()
    assert len(destino.trozos) == 50
    assert abs(reloj["t"] - 1.0) < 0.06


def test_el_volumen():
    pcm = (1000).to_bytes(2, "little", signed=True) * 4
    bajo = srv.ajustar(pcm, 0.5)
    assert int.from_bytes(bajo[:2], "little", signed=True) == 500
    assert srv.ajustar(pcm, 1.0) == pcm


def test_un_oyente_atascado_no_frena_a_los_demas():
    oyentes = srv.Oyentes()
    lento, rapido = oyentes.alta(), oyentes.alta()
    for i in range(100):
        oyentes.repartir(bytes([i]))
        rapido.get_nowait()
    assert lento.qsize() == 64 and lento.get_nowait() == bytes([36])


def test_el_mp3_y_el_estado_por_http(monkeypatch):
    monkeypatch.setattr(srv, "PUERTO", 0)
    oyentes = srv.Oyentes()
    grifo = srv.Grifo(FuenteContada(), Sumidero(), oyentes)
    http_srv = srv.servidor(oyentes, grifo)
    puerto = http_srv.server_address[1]
    threading.Thread(target=http_srv.serve_forever, daemon=True).start()
    try:
        r = urllib.request.urlopen(f"http://127.0.0.1:{puerto}/estado", timeout=3)
        assert b'"oyentes": 0' in r.read()
        stream = urllib.request.urlopen(f"http://127.0.0.1:{puerto}/musica.mp3", timeout=3)
        assert stream.headers["Content-Type"] == "audio/mpeg"
        for _ in range(50):
            if oyentes.cuantos() == 1:
                break
            time.sleep(0.02)
        oyentes.repartir(b"ID3-trozo")
        assert stream.read(9) == b"ID3-trozo"
        stream.close()
    finally:
        http_srv.shutdown()


# --- Soloist (2026-11-18): librespot ya no recibe la clave de audio en la cuenta de Mikel ---

def test_los_oyentes_avisan_del_primero_y_del_ultimo():
    cambios = []
    oyentes = srv.Oyentes(al_cambiar=cambios.append)
    a = oyentes.alta()
    b = oyentes.alta()
    oyentes.baja(a)
    assert cambios == [True]
    oyentes.baja(b)
    oyentes.baja(b)              # una baja repetida no vuelve a avisar
    assert cambios == [True, False]


def test_sin_oyentes_se_tira_lo_que_suena_si_la_fuente_no_espera():
    """parec no se para: lo que suena sin nadie escuchando no puede quedarse para luego."""
    oyentes = srv.Oyentes()
    fuente = FuenteContada()
    grifo = srv.Grifo(fuente, Sumidero(), oyentes, descartar=True)
    hilo = threading.Thread(target=grifo.leer, daemon=True)
    hilo.start()
    time.sleep(0.2)
    assert fuente.leido > 0 and grifo.cola.qsize() == 0
    grifo.parar.set()


def test_los_marcos_websocket():
    marco = srv.marco_ws('{"type":"command","command":"pause"}')
    assert marco[0] == 0x81 and marco[1] & 0x80          # texto, y enmascarado
    n, mascara = marco[1] & 0x7F, marco[2:6]
    texto = bytes(b ^ mascara[i % 4] for i, b in enumerate(marco[6:6 + n])).decode()
    assert texto == '{"type":"command","command":"pause"}'
    largo = "x" * 300
    assert srv.marco_ws(largo)[1] & 0x7F == 126
    # Del servidor: sin máscara, dos seguidos y uno a medias.
    m1, m2 = b'{"a":1}', b'{"b":2}'
    datos = bytes([0x81, len(m1)]) + m1 + bytes([0x81, len(m2)]) + m2 + bytes([0x81, 50]) + b"abc"
    mensajes, resto = srv.leer_marcos(datos)
    assert mensajes == ['{"a":1}', '{"b":2}'] and resto == bytes([0x81, 50]) + b"abc"


class SoloistFalso:
    """Un WebSocket que se porta como el de Soloist: saluda, manda auth_state y
    playback_state, y apunta los comandos que recibe."""

    def __init__(self, estado="playing"):
        import socket
        self.estado, self.comandos = estado, []
        self.srv = socket.socket()
        self.srv.bind(("127.0.0.1", 0))
        self.srv.listen()
        self.puerto = self.srv.getsockname()[1]
        threading.Thread(target=self._atender, daemon=True).start()

    def _atender(self):
        import base64
        import hashlib
        import json as _json
        while True:
            c, _ = self.srv.accept()
            peticion = b""
            while b"\r\n\r\n" not in peticion:
                peticion += c.recv(4096)
            clave = [l.split(b": ", 1)[1] for l in peticion.split(b"\r\n")
                     if l.lower().startswith(b"sec-websocket-key")][0]
            acepta = base64.b64encode(hashlib.sha1(
                clave + b"258EAFA5-E914-47DA-95CA-C5AB0DC85B11").digest())
            c.sendall(b"HTTP/1.1 101 Switching Protocols\r\nUpgrade: websocket\r\n"
                      b"Connection: Upgrade\r\nSec-WebSocket-Accept: " + acepta + b"\r\n\r\n")
            for ev in ({"type": "auth_state", "logged_in": True},
                       {"type": "playback_state", "status": self.estado}):
                m = _json.dumps(ev).encode()
                c.sendall(bytes([0x81, len(m)]) + m)
            c.settimeout(1)
            try:
                d = c.recv(4096)
                while d and d[0] == 0x81:
                    n, mascara = d[1] & 0x7F, d[2:6]
                    self.comandos.append(_json.loads(bytes(
                        b ^ mascara[i % 4] for i, b in enumerate(d[6:6 + n])))["command"])
                    d = d[6 + n:] or c.recv(4096)
            except OSError:
                pass
            c.close()


def test_el_mando_lee_el_estado_y_manda_el_comando():
    falso = SoloistFalso("playing")
    mando = srv.Mando(puerto=falso.puerto)
    assert mando.ordenar("pause", solo_si="playing") == "playing"
    time.sleep(0.3)
    assert falso.comandos == ["pause"]


def test_el_mando_no_pausa_lo_que_ya_estaba_parado():
    falso = SoloistFalso("paused")
    assert srv.Mando(puerto=falso.puerto).ordenar("pause", solo_si="playing") == "paused"
    time.sleep(0.3)
    assert falso.comandos == []


class MandoApuntado:
    def __init__(self, estado):
        self.estado, self.ordenes = estado, []

    def ordenar(self, comando, solo_si=""):
        self.ordenes.append(comando)
        return self.estado


def test_el_pausador_solo_reanuda_lo_que_paro_el():
    sonando = MandoApuntado("playing")
    p = srv.Pausador(sonando, hilo=False)
    p.aplicar(False)          # Jarvis despierta: se pausa
    p.aplicar(True)           # Jarvis duerme: vuelve
    assert sonando.ordenes == ["pause", "play"]

    parada = MandoApuntado("paused")      # Mikel la había pausado
    p = srv.Pausador(parada, hilo=False)
    p.aplicar(False)
    p.aplicar(True)
    assert parada.ordenes == ["pause"]    # el «pause» va con solo_si: no la toca, ni la reanuda


def test_el_pausador_no_se_cae_sin_soloist():
    class Roto:
        def ordenar(self, *a, **k):
            raise ConnectionRefusedError("no hay nadie")
    p = srv.Pausador(Roto(), hilo=False)
    p.aplicar(False)
    p.aplicar(True)
    assert p.pausada_por_mi is False


def test_el_codificador_no_se_queda_analizando():
    """ffmpeg 7 (Debian 13) no saca nada de una tubería en directo sin esto (2026-11-18)."""
    orden = srv.orden_codificador()
    i = orden.index("-i")
    assert "-probesize" in orden[:i] and "-analyzeduration" in orden[:i]
