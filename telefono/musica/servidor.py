#!/usr/bin/env python3
"""La música de la escucha pasiva (parche 50). Ver «El parche 50» en telefono/PARCHES.md.

Mikel, el 2026-11-18: «quiero poder tener a Jarvis en modo de escucha pasiva mientras
escucho música, música que yo puedo controlar desde el móvil o el coche, y que en cualquier
momento diga "Jarvis…" y me conteste». Con la llamada abierta, iOS para la música del
iPhone: los dos no suenan a la vez. Así que la música va DENTRO de la llamada:

    Spotify (en el móvil o en CarPlay) ──Connect──▶ librespot «Jarvis» (aquí, en caja)
        ──PCM──▶ este servidor ──MP3──▶ FreeSWITCH (shout://, mezclado en la llamada)

- **«Jarvis» es un altavoz de Spotify.** Se elige en la lista de dispositivos como el de
  casa o el del coche, y desde ahí se pasa, se pausa o se cambia de lista. Lo controla él,
  con la app de siempre; Jarvis no elige nada.
- **Solo se escucha mientras alguien escucha.** Sin nadie conectado, este servidor deja de
  leer a librespot, que se queda esperando: la canción se para donde iba. Es lo que hace
  que, al decir «Jarvis», la voice-app corte la música (deja de pedirla) y al dormirse
  vuelva por donde estaba, sin tocar la API de Spotify.
- **Nunca se queda sin sonido de relleno.** Entre canción y canción, o con Spotify en
  pausa, sale silencio al mismo ritmo: un MP3 que se corta, FreeSWITCH lo da por acabado.
- **Solo en loopback** (`MUSICA_ESCUCHA`, 127.0.0.1): lo pide FreeSWITCH desde la misma
  máquina. No lleva llave porque no sale de caja.

Lo que se oye es audio de teléfono: la llamada va en banda estrecha, y en el coche por
Bluetooth también. Es la radio de una centralita, no un equipo de música.
"""
import array
import http.server
import json
import logging
import os
import queue
import socketserver
import subprocess
import sys
import threading
import time

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("musica")

PUERTO   = int(os.getenv("MUSICA_PUERTO", "8095"))
ESCUCHA  = os.getenv("MUSICA_ESCUCHA", "127.0.0.1")
NOMBRE   = os.getenv("MUSICA_NOMBRE", "Jarvis")
DATOS    = os.getenv("MUSICA_DATOS", "/datos")
KBPS     = os.getenv("MUSICA_KBPS", "64")
# 0-100: cuánto suena por debajo de la voz de Jarvis. El volumen fino, en la app de Spotify.
GANANCIA = max(0, min(100, int(os.getenv("MUSICA_GANANCIA", "70")))) / 100

# Lo que entrega librespot con `--backend pipe --format S16`: 44,1 kHz, estéreo, 16 bits.
FRECUENCIA, CANALES, BYTES = 44100, 2, 2
TROZO_MS = 20
TROZO    = FRECUENCIA * CANALES * BYTES * TROZO_MS // 1000      # 3528 bytes
SILENCIO = bytes(TROZO)


def ajustar(pcm: bytes, ganancia: float) -> bytes:
    """El PCM con su volumen. Sin `audioop` (fuera desde Python 3.13)."""
    if ganancia >= 0.999:
        return pcm
    muestras = array.array("h")
    muestras.frombytes(pcm[: len(pcm) - len(pcm) % 2])
    for i, m in enumerate(muestras):
        muestras[i] = int(m * ganancia)
    return muestras.tobytes()


class Oyentes:
    """Quién está escuchando: una cola por conexión. La primera que llega abre el grifo."""

    def __init__(self):
        self._colas: list = []
        self._cerrojo = threading.Lock()
        self.hay = threading.Event()

    def alta(self) -> queue.Queue:
        q: queue.Queue = queue.Queue(maxsize=64)
        with self._cerrojo:
            self._colas.append(q)
            self.hay.set()
        return q

    def baja(self, q: queue.Queue) -> None:
        with self._cerrojo:
            if q in self._colas:
                self._colas.remove(q)
            if not self._colas:
                self.hay.clear()

    def cuantos(self) -> int:
        with self._cerrojo:
            return len(self._colas)

    def repartir(self, trozo: bytes) -> None:
        with self._cerrojo:
            colas = list(self._colas)
        for q in colas:
            try:
                q.put_nowait(trozo)
            except queue.Full:
                # Un oyente atascado pierde lo más viejo, no frena a los demás.
                try:
                    q.get_nowait()
                    q.put_nowait(trozo)
                except (queue.Empty, queue.Full):
                    pass


class Grifo:
    """Lee el PCM de la fuente (librespot) solo mientras hay oyentes, y lo entrega a su
    ritmo, con silencio cuando no hay música. Lo que no se lee se queda en la tubería, y
    librespot, al llenarla, espera: así se para la canción."""

    def __init__(self, fuente, destino, oyentes: Oyentes, ganancia: float = GANANCIA,
                 reloj=time.monotonic, dormir=time.sleep):
        self.fuente, self.destino, self.oyentes = fuente, destino, oyentes
        self.ganancia, self.reloj, self.dormir = ganancia, reloj, dormir
        self.cola: queue.Queue = queue.Queue(maxsize=10)          # 200 ms como mucho
        self.musica = 0           # trozos con música entregados
        self.silencio = 0         # trozos de relleno
        self.parar = threading.Event()

    def leer(self) -> None:
        """Hilo: de la fuente a la cola, pero solo con alguien al otro lado."""
        pendiente = b""
        while not self.parar.is_set():
            if not self.oyentes.hay.wait(timeout=0.5):
                continue
            datos = self.fuente.read(TROZO - len(pendiente))
            if not datos:
                log.warning("La fuente se ha cerrado")
                return
            pendiente += datos
            if len(pendiente) >= TROZO:
                self.cola.put(pendiente[:TROZO])
                pendiente = pendiente[TROZO:]

    def paso(self) -> bytes:
        """Un trozo de 20 ms: música si la hay, silencio si no."""
        try:
            trozo = self.cola.get_nowait()
            self.musica += 1
            return ajustar(trozo, self.ganancia)
        except queue.Empty:
            self.silencio += 1
            return SILENCIO

    def marcar(self) -> None:
        """Hilo: un trozo cada 20 ms al codificador mientras hay oyentes. Con la hora fija
        y no con `sleep(0.02)`: los retrasos se sumarían y la música iría lenta."""
        siguiente = None
        while not self.parar.is_set():
            if not self.oyentes.hay.is_set():
                siguiente = None
                self.oyentes.hay.wait(timeout=0.5)
                continue
            ahora = self.reloj()
            if siguiente is None or ahora - siguiente > 1.0:
                siguiente = ahora
            self.destino.write(self.paso())
            self.destino.flush()
            siguiente += TROZO_MS / 1000
            espera = siguiente - self.reloj()
            if espera > 0:
                self.dormir(espera)


def repartir_mp3(salida, oyentes: Oyentes) -> None:
    """Hilo: lo que sale del codificador, a cada oyente."""
    while True:
        trozo = salida.read1(4096) if hasattr(salida, "read1") else salida.read(4096)
        if not trozo:
            log.error("El codificador se ha cerrado")
            return
        oyentes.repartir(trozo)


ESTADO: dict = {"librespot": "arrancando", "desde": time.time()}


def servidor(oyentes: Oyentes, grifo: "Grifo"):
    class Manejador(http.server.BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.0"

        def log_message(self, formato, *args):   # noqa: N802 — sin una línea por petición
            pass

        def do_GET(self):   # noqa: N802
            ruta = self.path.split("?", 1)[0]
            if ruta == "/estado":
                cuerpo = json.dumps({**ESTADO, "oyentes": oyentes.cuantos(),
                                     "trozos_musica": grifo.musica,
                                     "trozos_silencio": grifo.silencio}).encode()
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(cuerpo)))
                self.end_headers()
                self.wfile.write(cuerpo)
                return
            if ruta != "/musica.mp3":
                self.send_error(404)
                return
            self.send_response(200)
            self.send_header("Content-Type", "audio/mpeg")
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            q = oyentes.alta()
            log.info("Escucha alguien (%d)", oyentes.cuantos())
            try:
                while True:
                    self.wfile.write(q.get())
            except (BrokenPipeError, ConnectionResetError, OSError):
                pass
            finally:
                oyentes.baja(q)
                log.info("Deja de escuchar (%d)", oyentes.cuantos())

    class Servidor(socketserver.ThreadingMixIn, http.server.HTTPServer):
        daemon_threads = True
        allow_reuse_address = True

    return Servidor((ESCUCHA, PUERTO), Manejador)


def lanzar_librespot() -> subprocess.Popen:
    orden = ["librespot", "--name", NOMBRE, "--backend", "pipe", "--format", "S16",
             "--bitrate", "160", "--device-type", "speaker", "--initial-volume", "80",
             "--cache", DATOS, "--system-cache", DATOS]
    orden += os.getenv("MUSICA_LIBRESPOT_ARGS", "").split()
    return subprocess.Popen(orden, stdout=subprocess.PIPE, stderr=sys.stderr, bufsize=0)


def main() -> None:
    oyentes = Oyentes()
    codificador = subprocess.Popen(
        ["ffmpeg", "-hide_banner", "-loglevel", "error", "-f", "s16le", "-ar", str(FRECUENCIA),
         "-ac", str(CANALES), "-i", "pipe:0", "-ac", "1", "-ar", "22050", "-b:a", f"{KBPS}k",
         "-f", "mp3", "-flush_packets", "1", "pipe:1"],
        stdin=subprocess.PIPE, stdout=subprocess.PIPE, bufsize=0)
    threading.Thread(target=repartir_mp3, args=(codificador.stdout, oyentes), daemon=True).start()

    librespot = lanzar_librespot()
    grifo = Grifo(librespot.stdout, codificador.stdin, oyentes)
    threading.Thread(target=grifo.marcar, daemon=True).start()
    lector = threading.Thread(target=grifo.leer, daemon=True)
    lector.start()
    http_srv = servidor(oyentes, grifo)
    threading.Thread(target=http_srv.serve_forever, daemon=True).start()
    log.info("Música en http://%s:%d/musica.mp3, altavoz «%s»", ESCUCHA, PUERTO, NOMBRE)
    ESTADO["librespot"] = "vivo"

    # librespot se reinicia si se cae (un corte de red lo tumba a veces); el resto sigue.
    while True:
        codigo = librespot.wait()
        ESTADO["librespot"] = f"caído ({codigo}), reiniciando"
        log.warning("librespot ha salido con %s; lo vuelvo a lanzar en 5 s", codigo)
        time.sleep(5)
        librespot = lanzar_librespot()
        grifo.fuente = librespot.stdout
        if not lector.is_alive():
            lector = threading.Thread(target=grifo.leer, daemon=True)
            lector.start()
        ESTADO["librespot"] = "vivo"


if __name__ == "__main__":
    main()
