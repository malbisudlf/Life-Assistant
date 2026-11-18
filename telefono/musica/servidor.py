#!/usr/bin/env python3
"""La música de la escucha pasiva (parche 50). Ver «El parche 50» en telefono/PARCHES.md.

Mikel, el 2026-11-18: «quiero poder tener a Jarvis en modo de escucha pasiva mientras
escucho música, música que yo puedo controlar desde el móvil o el coche, y que en cualquier
momento diga "Jarvis…" y me conteste». Con la llamada abierta, iOS para la música del
iPhone: los dos no suenan a la vez. Así que la música va DENTRO de la llamada:

    Spotify (en el móvil o en CarPlay) ──Connect──▶ Soloist «Jarvis» (aquí, en caja)
        ──PulseAudio──▶ parec ──PCM──▶ este servidor ──MP3──▶ FreeSWITCH (shout://)

- **El motor es Soloist**, el cliente Connect oficial de Spotify para Linux (agosto de 2026),
  y no librespot: desde 2025 Spotify niega la clave de audio a librespot en muchas cuentas
  («error audio key 0 1», librespot#1649), la de Mikel entre ellas (2026-11-18). Soloist
  necesita una clave de Spotify for Developers (`SOLOIST_API_KEY`, en `soloist.env`), y sus
  binarios caducan a los 90 días: se baja solo al arrancar y al caducar (sale con 10).
  librespot sigue como `MUSICA_MOTOR=librespot`, por si algún día vuelve a valer.

- **«Jarvis» es un altavoz de Spotify.** Se elige en la lista de dispositivos como el de
  casa o el del coche, y desde ahí se pasa, se pausa o se cambia de lista. Lo controla él,
  con la app de siempre; Jarvis no elige nada.
- **La canción se para mientras nadie escucha.** Al decir «Jarvis», la voice-app deja de
  pedir la música; al dormirse, la vuelve a pedir. Con Soloist, este servidor le manda
  `pause` por su WebSocket local al irse el último oyente y `play` al volver el primero
  (solo si la pausa fue suya: lo que pausó Mikel, pausado se queda). Con librespot bastaba
  con dejar de leerle la tubería.
- **Nunca se queda sin sonido de relleno.** Entre canción y canción, o con Spotify en
  pausa, sale silencio al mismo ritmo: un MP3 que se corta, FreeSWITCH lo da por acabado.
- **Solo en loopback** (`MUSICA_ESCUCHA`, 127.0.0.1): lo pide FreeSWITCH desde la misma
  máquina. No lleva llave porque no sale de caja.

Lo que se oye es audio de teléfono: la llamada va en banda estrecha, y en el coche por
Bluetooth también. Es la radio de una centralita, no un equipo de música.
"""
import array
import base64
import http.server
import io
import json
import logging
import os
import queue
import socket
import socketserver
import subprocess
import sys
import tarfile
import threading
import time
import urllib.request

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("musica")

PUERTO   = int(os.getenv("MUSICA_PUERTO", "8095"))
ESCUCHA  = os.getenv("MUSICA_ESCUCHA", "127.0.0.1")
NOMBRE   = os.getenv("MUSICA_NOMBRE", "Jarvis")
DATOS    = os.getenv("MUSICA_DATOS", "/datos")
KBPS     = os.getenv("MUSICA_KBPS", "64")
# 0-100: cuánto suena por debajo de la voz de Jarvis. El volumen fino, en la app de Spotify.
GANANCIA = max(0, min(100, int(os.getenv("MUSICA_GANANCIA", "70")))) / 100
MOTOR    = os.getenv("MUSICA_MOTOR", "soloist")
WS_PUERTO = int(os.getenv("MUSICA_WS_PUERTO", "8097"))   # el WebSocket de Soloist, en loopback
SOLOIST_URL = os.getenv("MUSICA_SOLOIST_URL",
                        "https://soloist-builds.spotifycdn.com/soloist_release_x86_64.tar.gz")
SOLOIST_CADUCADO = 10    # el código con que sale un Soloist caducado

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

    def __init__(self, al_cambiar=None):
        self._colas: list = []
        self._cerrojo = threading.Lock()
        self.hay = threading.Event()
        # al_cambiar(True) al llegar el primero, al_cambiar(False) al irse el último.
        self.al_cambiar = al_cambiar

    def alta(self) -> queue.Queue:
        q: queue.Queue = queue.Queue(maxsize=64)
        with self._cerrojo:
            primero = not self._colas
            self._colas.append(q)
            self.hay.set()
        if primero and self.al_cambiar:
            self.al_cambiar(True)
        return q

    def baja(self, q: queue.Queue) -> None:
        with self._cerrojo:
            habia = bool(self._colas)
            if q in self._colas:
                self._colas.remove(q)
            ultimo = habia and not self._colas
            if not self._colas:
                self.hay.clear()
        if ultimo and self.al_cambiar:
            self.al_cambiar(False)

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
                 reloj=time.monotonic, dormir=time.sleep, descartar: bool = False):
        self.fuente, self.destino, self.oyentes = fuente, destino, oyentes
        # Con una fuente que no espera (parec, de PulseAudio), lo que suena sin nadie
        # escuchando se tira: si se dejara en la tubería, al volver se oiría lo viejo.
        self.descartar = descartar
        self.ganancia, self.reloj, self.dormir = ganancia, reloj, dormir
        self.cola: queue.Queue = queue.Queue(maxsize=10)          # 200 ms como mucho
        self.musica = 0           # trozos con música entregados
        self.silencio = 0         # trozos de relleno
        self.parar = threading.Event()

    def leer(self) -> None:
        """Hilo: de la fuente a la cola, pero solo con alguien al otro lado."""
        pendiente = b""
        while not self.parar.is_set():
            if not self.oyentes.hay.is_set():
                if not self.descartar:
                    self.oyentes.hay.wait(timeout=0.5)
                    continue
                if not self.fuente.read(TROZO):
                    log.warning("La fuente se ha cerrado")
                    return
                pendiente = b""
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


def marco_ws(texto: str) -> bytes:
    """Un marco de texto WebSocket de cliente (RFC 6455: el cliente siempre enmascara)."""
    datos = texto.encode()
    n = len(datos)
    cabeza = bytes([0x81])
    if n < 126:
        cabeza += bytes([0x80 | n])
    elif n < 65536:
        cabeza += bytes([0x80 | 126]) + n.to_bytes(2, "big")
    else:
        cabeza += bytes([0x80 | 127]) + n.to_bytes(8, "big")
    mascara = os.urandom(4)
    return cabeza + mascara + bytes(b ^ mascara[i % 4] for i, b in enumerate(datos))


def leer_marcos(datos: bytes):
    """Los mensajes de texto completos de lo recibido (el servidor no enmascara), y lo que
    sobra. Sin fragmentos: Soloist manda cada evento en un marco."""
    mensajes = []
    while len(datos) >= 2:
        n, i = datos[1] & 0x7F, 2
        if n == 126:
            if len(datos) < 4:
                break
            n, i = int.from_bytes(datos[2:4], "big"), 4
        elif n == 127:
            if len(datos) < 10:
                break
            n, i = int.from_bytes(datos[2:10], "big"), 10
        if len(datos) < i + n:
            break
        if datos[0] & 0x0F == 0x1:
            mensajes.append(datos[i:i + n].decode("utf-8", "replace"))
        datos = datos[i + n:]
    return mensajes, datos


class Mando:
    """El WebSocket local de Soloist (`--ws 127.0.0.1:PUERTO`). Sin llave: solo en loopback.
    Al conectar, Soloist manda `auth_state` y, con sesión, `playback_state` con `status`."""

    def __init__(self, host: str = "127.0.0.1", puerto: int = WS_PUERTO, espera: float = 3.0):
        self.host, self.puerto, self.espera = host, puerto, espera

    def ordenar(self, comando: str, solo_si: str = "") -> str:
        """Manda `comando` y devuelve el estado que había («playing», «paused»…, o «» si no
        llegó a decirlo). Con `solo_si`, solo lo manda si el estado era ese."""
        clave = base64.b64encode(os.urandom(16)).decode()
        s = socket.create_connection((self.host, self.puerto), timeout=self.espera)
        try:
            s.sendall((f"GET / HTTP/1.1\r\nHost: {self.host}:{self.puerto}\r\n"
                       "Upgrade: websocket\r\nConnection: Upgrade\r\n"
                       f"Sec-WebSocket-Key: {clave}\r\nSec-WebSocket-Version: 13\r\n\r\n").encode())
            recibido = b""
            while b"\r\n\r\n" not in recibido:
                trozo = s.recv(4096)
                if not trozo:
                    raise ConnectionError("Soloist cerró al saludar")
                recibido += trozo
            cabecera, resto = recibido.split(b"\r\n\r\n", 1)
            primera = cabecera.split(b"\r\n", 1)[0]
            if b" 101" not in primera:
                raise ConnectionError(primera.decode("latin-1"))
            estado, limite = "", time.monotonic() + 1.5
            s.settimeout(0.3)
            while True:
                mensajes, resto = leer_marcos(resto)
                for m in mensajes:
                    try:
                        ev = json.loads(m)
                    except ValueError:
                        continue
                    if ev.get("type") in ("playback_state", "playback_changed"):
                        estado = ev.get("status", "") or estado
                if estado or time.monotonic() >= limite:
                    break
                try:
                    trozo = s.recv(4096)
                except socket.timeout:
                    continue
                if not trozo:
                    break
                resto += trozo
            if not solo_si or estado == solo_si:
                s.sendall(marco_ws(json.dumps({"type": "command", "command": comando})))
                time.sleep(0.2)
            s.sendall(bytes([0x88, 0x80]) + os.urandom(4))     # cierre, enmascarado y vacío
            return estado
        finally:
            s.close()


class Pausador:
    """Con Soloist la canción no se para sola: se le dice. En su propio hilo y en orden,
    para que la petición de FreeSWITCH no espere y un `play` no adelante a un `pause`."""

    def __init__(self, mando, hilo: bool = True):
        self.mando = mando
        self.pausada_por_mi = False
        self.cola: queue.Queue = queue.Queue()
        if hilo:
            threading.Thread(target=self._trabajar, daemon=True).start()

    def cambio(self, hay: bool) -> None:
        self.cola.put(hay)

    def aplicar(self, hay: bool) -> None:
        try:
            if hay:
                if self.pausada_por_mi:
                    self.pausada_por_mi = False
                    self.mando.ordenar("play")
                    log.info("Vuelve la música")
            else:
                antes = self.mando.ordenar("pause", solo_si="playing")
                self.pausada_por_mi = antes == "playing"
                if self.pausada_por_mi:
                    log.info("Música en pausa mientras habla Jarvis")
        except OSError as e:
            log.warning("No he podido %s Soloist: %s", "reanudar" if hay else "pausar", e)

    def _trabajar(self) -> None:
        while True:
            self.aplicar(self.cola.get())


def bajar_soloist(destino: str) -> str:
    """El binario de Soloist, bajado de Spotify (no se redistribuye: se baja cada vez aquí).
    Devuelve la ruta del ejecutable."""
    os.makedirs(destino, exist_ok=True)
    log.info("Bajando Soloist de %s", SOLOIST_URL)
    with urllib.request.urlopen(SOLOIST_URL, timeout=120) as r:
        paquete = r.read()
    ruta = os.path.join(destino, "soloist")
    with tarfile.open(fileobj=io.BytesIO(paquete), mode="r:gz") as tar:
        miembro = next(m for m in tar.getmembers() if os.path.basename(m.name) == "soloist")
        with tar.extractfile(miembro) as f, open(ruta + ".nuevo", "wb") as o:
            o.write(f.read())
    os.chmod(ruta + ".nuevo", 0o755)
    os.replace(ruta + ".nuevo", ruta)
    return ruta


ESTADO: dict = {"motor": MOTOR, "desde": time.time()}



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


def orden_codificador() -> list:
    """ffmpeg de PCM a MP3. `-probesize 32 -analyzeduration 0`: sin ellos, el ffmpeg 7 de
    Debian 13 se queda analizando la entrada varios segundos antes de sacar el primer byte, y
    de una tubería en directo no saca nada (probado el 2026-11-18: 0 bytes en 3 s)."""
    return ["ffmpeg", "-hide_banner", "-loglevel", "error", "-probesize", "32",
            "-analyzeduration", "0", "-f", "s16le", "-ar", str(FRECUENCIA), "-ac", str(CANALES),
            "-i", "pipe:0", "-ac", "1", "-ar", "22050", "-b:a", f"{KBPS}k",
            "-f", "mp3", "-flush_packets", "1", "pipe:1"]


def lanzar_codificador() -> subprocess.Popen:
    return subprocess.Popen(orden_codificador(), stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                            bufsize=0)


def arrancar_pulse() -> None:
    """Un PulseAudio para este contenedor, con un altavoz de mentira («musica») por defecto:
    Soloist toca en él y `parec` recoge lo que suena por su monitor."""
    os.makedirs(os.environ.setdefault("XDG_RUNTIME_DIR", "/tmp/run"), mode=0o700, exist_ok=True)
    subprocess.run(["pulseaudio", "--daemonize=yes", "--exit-idle-time=-1", "-n",
                    "--load=module-native-protocol-unix",
                    "--load=module-null-sink sink_name=musica rate=44100 channels=2"],
                   check=True)
    for _ in range(50):
        if subprocess.run(["pactl", "info"], capture_output=True).returncode == 0:
            break
        time.sleep(0.1)
    subprocess.run(["pactl", "set-default-sink", "musica"], check=True)


def lanzar_parec() -> subprocess.Popen:
    return subprocess.Popen(["parec", "-d", "musica.monitor", "--raw", "--format=s16le",
                             f"--rate={FRECUENCIA}", f"--channels={CANALES}",
                             "--latency-msec=100"], stdout=subprocess.PIPE, bufsize=0)


def vigilar_soloist(clave: str) -> None:
    """Hilo: Soloist siempre vivo. Caducado (sale con 10) o sin binario, se baja de nuevo."""
    carpeta = os.path.join(DATOS, "soloist")
    binario = os.path.join(carpeta, "bin", "soloist")
    while True:
        try:
            if not os.path.exists(binario):
                bajar_soloist(os.path.dirname(binario))
            ESTADO["soloist"] = "vivo"
            codigo = subprocess.run(
                [binario, "--device-name", NOMBRE, "--api-key", clave,
                 "--data-dir", os.path.join(carpeta, "datos"),
                 "--cache-dir", os.path.join(carpeta, "cache"), "--cache-size", "200",
                 "--initial-volume", "80", "--ws", f"127.0.0.1:{WS_PUERTO}"],
                stdout=sys.stderr, stderr=sys.stderr).returncode
        except Exception as e:      # noqa: BLE001 — una caída de red no tumba el servicio
            codigo = f"error: {e}"
        ESTADO["soloist"] = f"caído ({codigo}), reiniciando"
        log.warning("Soloist ha salido con %s; lo vuelvo a lanzar en 10 s", codigo)
        if codigo == SOLOIST_CADUCADO:
            log.warning("Soloist caducado: bajo uno nuevo")
            try:
                os.remove(binario)
            except OSError:
                pass
        time.sleep(10)


def main_soloist() -> None:
    clave = os.getenv("SOLOIST_API_KEY", "").strip()
    pausador = Pausador(Mando())
    oyentes = Oyentes(al_cambiar=pausador.cambio)
    codificador = lanzar_codificador()
    threading.Thread(target=repartir_mp3, args=(codificador.stdout, oyentes), daemon=True).start()

    arrancar_pulse()
    parec = lanzar_parec()
    grifo = Grifo(parec.stdout, codificador.stdin, oyentes, descartar=True)
    threading.Thread(target=grifo.marcar, daemon=True).start()
    lector = threading.Thread(target=grifo.leer, daemon=True)
    lector.start()
    http_srv = servidor(oyentes, grifo)
    threading.Thread(target=http_srv.serve_forever, daemon=True).start()
    log.info("Música en http://%s:%d/musica.mp3, altavoz «%s» (Soloist)", ESCUCHA, PUERTO, NOMBRE)
    if clave:
        threading.Thread(target=vigilar_soloist, args=(clave,), daemon=True).start()
    else:
        ESTADO["soloist"] = "sin clave: falta SOLOIST_API_KEY en soloist.env"
        log.error("Falta SOLOIST_API_KEY: sale silencio hasta que se ponga")

    # parec se reinicia si se cae; si se cae PulseAudio, salgo y Docker me levanta.
    while True:
        codigo = parec.wait()
        log.warning("parec ha salido con %s; lo vuelvo a lanzar", codigo)
        if subprocess.run(["pactl", "info"], capture_output=True).returncode != 0:
            log.error("PulseAudio no responde: salgo para que Docker me levante")
            sys.exit(1)
        time.sleep(1)
        parec = lanzar_parec()
        grifo.fuente = parec.stdout
        if not lector.is_alive():
            lector = threading.Thread(target=grifo.leer, daemon=True)
            lector.start()


def main() -> None:
    if MOTOR == "soloist":
        main_soloist()
        return
    oyentes = Oyentes()
    codificador = lanzar_codificador()
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
