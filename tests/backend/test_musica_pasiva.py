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
