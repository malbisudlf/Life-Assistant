#!/usr/bin/env python3
"""El cuerpo de escritorio de Jarvis: el reactor junto a la barra de tareas y la tecla de
hablar. Pedido el 2026-11-12 («algo como Roamies, pero con mi Jarvis: que todo sea uno»).

No es un segundo asistente: es una boca más del mismo, como la llamada del dashboard.

- **Oye** por el oído de jacobo, a través del puente `/voz/oido` del backend (el mismo que
  usa la llamada del navegador). Aquí no corre ningún modelo: en este PC no se ejecuta IA
  (memoria «sin IA en el PC»), solo se graba y se manda.
- **Piensa** en `/jarvis/voz`: el turno de siempre, con sus herramientas, su memoria y sus
  frenos, retransmitido según se escribe.
- **Habla** con `/voz/decir` (Fish, la voz «Jarvis», con Azure detrás), frase a frase: así
  empieza a hablar antes de que el modelo acabe.

Cómo se usa:
  - Mantener **Ctrl + Alt izquierdos** mientras se habla; al soltar, contesta. AltGr no
    cuenta (con ella se escribe la @), y si mientras se mantiene se pulsa otra tecla era un
    atajo y se cancela. La lógica está en `escritorio_logica.py`, con sus tests.
  - Un clic en el reactor también empieza a escuchar, y otro lo manda. Mientras habla, un
    clic lo calla. Se arrastra para moverlo; el botón derecho tiene el resto.

La sesión es la del dashboard: la primera vez pide la contraseña (la escribe él en la
ventanita; aquí no se guarda), y guarda el JWT de 30 días en `~/.jarvis-pc/escritorio.json`,
fuera de OneDrive. Cuando caduca, el reactor se pone gris y vuelve a pedirla: nada que
arranque solo se queda mudo sin decirlo (invariante 2 de CLAUDE.md).

Arranca con Windows por el acceso directo que crea `instalar_escritorio.ps1`. Ver
docs/ESCRITORIO.md.
"""

import array
import ctypes
import json
import logging
import math
import os
import queue
import sys
import tempfile
import threading
import time
from pathlib import Path

import tkinter as tk

sys.path.insert(0, str(Path(__file__).resolve().parent))
from escritorio_logica import Frases, LectorSSE, Tecla, debe_verse, recorta_historial  # noqa: E402

# Otra carpeta solo para probarlo contra un backend de mentira sin tocar la sesión de verdad.
DIR      = Path(os.environ.get("JARVIS_ESCRITORIO_DIR") or Path.home() / ".jarvis-pc")
CONFIG   = DIR / "escritorio.json"
REGISTRO = DIR / "escritorio.log"
HZ       = 16000
TROZO    = 320                     # 20 ms de audio a 16 kHz
CLAVE    = "#010203"               # el color que Windows vuelve transparente
LADO     = 150

COLORES = {"reposo": "#2fb8e6", "escucha": "#8af6ff", "piensa": "#ffb84d",
           "habla": "#4fd0ff", "error": "#ff5a4f", "sin_sesion": "#7d8b96"}

log = logging.getLogger("escritorio")


# ── Configuración ─────────────────────────────────────────────────────────────────────

def _leer_env(ruta: Path) -> dict:
    try:
        lineas = ruta.read_text(encoding="utf-8").splitlines()
    except OSError:
        return {}
    salida = {}
    for linea in lineas:
        clave, _, valor = linea.strip().partition("=")
        if clave and not clave.startswith("#") and valor:
            salida[clave.strip()] = valor.strip()
    return salida


def backend_url() -> str:
    """JARVIS_BACKEND del entorno, de ~/.jarvis-pc/escritorio.env o el LA_API_BASE del
    agente (agent/.env): la misma dirección que ya usa el agente del PC."""
    url = (os.environ.get("JARVIS_BACKEND") or _leer_env(DIR / "escritorio.env").get("JARVIS_BACKEND")
           or _leer_env(Path(__file__).resolve().parent / ".env").get("LA_API_BASE") or "")
    return url.rstrip("/")


def cargar_config() -> dict:
    try:
        datos = json.loads(CONFIG.read_text(encoding="utf-8"))
        return datos if isinstance(datos, dict) else {}
    except (OSError, ValueError):
        return {}


def guardar_config(datos: dict) -> None:
    try:
        DIR.mkdir(exist_ok=True)
        tmp = CONFIG.with_suffix(".tmp")
        tmp.write_text(json.dumps(datos), encoding="utf-8")
        os.replace(tmp, CONFIG)
    except OSError as e:
        log.warning("No se pudo guardar la configuración (%s)", type(e).__name__)


# ── Windows ───────────────────────────────────────────────────────────────────────────

_u32 = ctypes.windll.user32
VK_LCONTROL, VK_RCONTROL, VK_LMENU, VK_RMENU = 0xA2, 0xA3, 0xA4, 0xA5
# Lo que, pulsado a la vez que Ctrl + Alt, dice que era un atajo: letras, números, F1-F12,
# signos, Supr, Tab, flechas…
_OTRAS = ([*range(0x08, 0x0E), *range(0x13, 0x2F), *range(0x30, 0x3A), *range(0x41, 0x5B),
           *range(0x60, 0x7C), *range(0xBA, 0xC1), *range(0xDB, 0xE0)])


def _pulsada(vk: int) -> bool:
    return bool(_u32.GetAsyncKeyState(vk) & 0x8000)


def una_sola_instancia() -> bool:
    ctypes.windll.kernel32.CreateMutexW(None, False, "Local\\JarvisEscritorio")
    return ctypes.windll.kernel32.GetLastError() != 183      # ERROR_ALREADY_EXISTS


def _mci(orden: str) -> str:
    buf = ctypes.create_unicode_buffer(128)
    ctypes.windll.winmm.mciSendStringW(orden, buf, 128, 0)
    return buf.value


# ── El micrófono ──────────────────────────────────────────────────────────────────────

class Microfono:
    """PCM s16le mono a 16 kHz en trozos de 20 ms, y su nivel para el reactor."""

    def __init__(self):
        self.nivel = 0.0
        self._stream = None
        self._destino = None

    def abrir(self, destino) -> None:
        import sounddevice as sd       # aquí y no arriba: sin él, el reactor dice qué falta
        self._destino = destino

        def llega(datos, _frames, _tiempo, _estado):
            trozo = bytes(datos)
            muestras = array.array("h", trozo)
            if muestras:
                self.nivel = min(1.0, math.sqrt(sum(m * m for m in muestras[::4]) / (len(muestras) / 4)) / 6000)
            if self._destino:
                self._destino(trozo)

        self._stream = sd.RawInputStream(samplerate=HZ, channels=1, dtype="int16",
                                         blocksize=TROZO, callback=llega)
        self._stream.start()

    def cerrar(self) -> None:
        self._destino = None
        self.nivel = 0.0
        if self._stream is not None:
            try:
                self._stream.stop()
                self._stream.close()
            except Exception:   # noqa: BLE001
                pass
            self._stream = None


# ── El oído (jacobo, por el puente del backend) ───────────────────────────────────────

class Oido:
    """Una frase: se conecta al empezar a hablar, manda lo que llega (lo grabado antes de
    conectar va primero) y al soltar pide el texto final."""

    def __init__(self, base: str, token: str):
        self.url = base.replace("https://", "wss://").replace("http://", "ws://") + "/voz/oido"
        self.token = token
        self._cola: "queue.Queue[bytes]" = queue.Queue()
        self._ws = None
        self._listo = threading.Event()
        self._error = ""
        self._hilo = threading.Thread(target=self._conectar, daemon=True, name="oido")
        self._hilo.start()

    def _conectar(self) -> None:
        try:
            from websockets.sync.client import connect
            ws = connect(self.url, open_timeout=8, max_size=1 << 20)
            ws.send(json.dumps({"token": self.token}))
            hola = json.loads(ws.recv(timeout=10))
            if hola.get("tipo") != "listo":
                self._error = str(hola.get("detalle") or "el oído no está")
                ws.close()
                return
            self._ws = ws
        except Exception as e:   # noqa: BLE001
            self._error = "sin_sesion" if "1008" in str(e) else f"no llego al oído ({type(e).__name__})"
            return
        finally:
            self._listo.set()
        while True:
            trozo = self._cola.get()
            if trozo is None:
                return
            try:
                ws.send(trozo)
            except Exception:   # noqa: BLE001
                return

    def mete(self, trozo: bytes) -> None:
        self._cola.put(trozo)

    def texto(self) -> str:
        """Cierra la frase y espera lo que se ha dicho. Lanza RuntimeError con el motivo."""
        self._listo.wait(10)
        if not self._ws:
            raise RuntimeError(self._error or "el oído no ha contestado")
        # Que salga todo lo grabado antes del «fin»
        while not self._cola.empty():
            time.sleep(0.02)
        self._ws.send(json.dumps({"tipo": "fin"}))
        limite = time.time() + 20
        try:
            while time.time() < limite:
                msg = json.loads(self._ws.recv(timeout=max(0.1, limite - time.time())))
                if msg.get("tipo") == "final":
                    return str(msg.get("texto") or "").strip()
                if msg.get("tipo") == "error":
                    raise RuntimeError(str(msg.get("detalle") or "error del oído"))
        finally:
            self.cancelar()
        raise RuntimeError("el oído no ha devuelto el texto")

    def cancelar(self) -> None:
        self._cola.put(None)
        if self._ws is not None:
            try:
                self._ws.close()
            except Exception:   # noqa: BLE001
                pass
            self._ws = None


# ── La voz ────────────────────────────────────────────────────────────────────────────

class Voz:
    """Frases → MP3 de `/voz/decir` → altavoces, en orden. Una frase se pide mientras suena
    la anterior, para que no haya huecos. `callar()` lo para todo."""

    def __init__(self, app):
        self.app = app
        self._textos: "queue.Queue" = queue.Queue()
        self._audios: "queue.Queue" = queue.Queue()
        self._turno = 0
        self.hablando = False
        self.pendientes = 0
        threading.Thread(target=self._pedir, daemon=True, name="voz-pedir").start()
        threading.Thread(target=self._sonar, daemon=True, name="voz-sonar").start()

    def di(self, texto: str) -> None:
        if texto and not self.app.mudo:
            self.pendientes += 1
            self._textos.put((self._turno, texto))

    def callar(self) -> None:
        self._turno += 1
        self.pendientes = 0
        for q in (self._textos, self._audios):
            try:
                while True:
                    q.get_nowait()
            except queue.Empty:
                pass

    def _pedir(self) -> None:
        import httpx
        while True:
            turno, texto = self._textos.get()
            if turno != self._turno:
                continue
            audio = b""
            try:
                r = httpx.post(f"{self.app.base}/voz/decir", json={"texto": texto[:600]},
                               headers=self.app.cabeceras(), timeout=20)
                if r.status_code == 200:
                    audio = r.content
                else:
                    log.warning("voz: %s", r.status_code)
            except Exception as e:   # noqa: BLE001
                log.warning("voz: %s", type(e).__name__)
            self._audios.put((turno, audio))

    def _sonar(self) -> None:
        n = 0
        while True:
            turno, audio = self._audios.get()
            self.pendientes = max(0, self.pendientes - 1)
            if turno != self._turno or not audio:
                continue
            n += 1
            ruta = Path(tempfile.gettempdir()) / f"jarvis-voz-{os.getpid()}-{n}.mp3"
            alias = f"jv{n}"
            try:
                ruta.write_bytes(audio)
                self.hablando = True
                _mci(f'open "{ruta}" type mpegvideo alias {alias}')
                _mci(f"play {alias}")
                while turno == self._turno and _mci(f"status {alias} mode") == "playing":
                    time.sleep(0.05)
            finally:
                _mci(f"close {alias}")
                self.hablando = False
                try:
                    ruta.unlink()
                except OSError:
                    pass


# ── La aplicación ─────────────────────────────────────────────────────────────────────

class App:
    def __init__(self):
        self.base = backend_url()
        self.config = cargar_config()
        self.token = str(self.config.get("token") or "")
        self.mudo = bool(self.config.get("mudo"))
        # Por defecto el reactor solo aparece al hablarle (ver `debe_verse`).
        self.siempre = bool(self.config.get("siempre_visible"))
        self.visible = True
        self.estado = "reposo" if self.token else "sin_sesion"
        self.historial: list = []
        self.cola: "queue.Queue" = queue.Queue()
        self.tecla = Tecla()
        self.micro = Microfono()
        self.oido = None
        self.manual = False            # escuchando por un clic, no por la tecla
        self.fase = 0.0
        self.pensando_desde = 0.0
        self.dir = DIR
        self._vuelo = None             # a dónde vuela el reactor durante un tutorial
        self._casa = None              # de dónde salió, para volver

        # Píxeles físicos en todas las pantallas (per-monitor v2): el lienzo dibuja sobre los
        # rectángulos que da UI Automation, que son físicos, y el PC de Mikel tiene una
        # pantalla al 100 % y otra al 125 %. Con «system aware» las marcas caían desplazadas
        # en la segunda.
        try:
            ctypes.windll.user32.SetProcessDpiAwarenessContext(ctypes.c_void_p(-4))
        except Exception:   # noqa: BLE001
            try:
                ctypes.windll.shcore.SetProcessDpiAwareness(2)
            except Exception:   # noqa: BLE001
                pass
        self.root = tk.Tk()
        self.escala = max(1.0, self.root.winfo_fpixels("1i") / 96)
        self.lado = int(LADO * self.escala)
        self.root.overrideredirect(True)
        self.root.attributes("-topmost", True)
        self.root.configure(bg=CLAVE)
        self.root.attributes("-transparentcolor", CLAVE)
        ancho, alto = self.root.winfo_screenwidth(), self.root.winfo_screenheight()
        x = int(self.config.get("x", ancho - self.lado - 24 * self.escala))
        y = int(self.config.get("y", alto - self.lado - 90 * self.escala))
        x, y = max(0, min(x, ancho - self.lado)), max(0, min(y, alto - self.lado))
        self.root.geometry(f"{self.lado}x{self.lado}+{x}+{y}")
        self.lienzo = tk.Canvas(self.root, width=self.lado, height=self.lado, bg=CLAVE,
                                highlightthickness=0, bd=0)
        self.lienzo.pack()
        self._arrastre = None
        self.lienzo.bind("<ButtonPress-1>", self._raton_baja)
        self.lienzo.bind("<B1-Motion>", self._raton_mueve)
        self.lienzo.bind("<ButtonRelease-1>", self._raton_sube)
        self.lienzo.bind("<Button-3>", self._menu)

        self.bocadillo = tk.Toplevel(self.root)
        self.bocadillo.overrideredirect(True)
        self.bocadillo.attributes("-topmost", True)
        self.bocadillo.attributes("-alpha", 0.95)
        self.bocadillo.configure(bg="#0b1a22", highlightthickness=1, highlightbackground="#2fb8e6")
        fuente = ("Segoe UI", 10)
        self.oido_txt = tk.Label(self.bocadillo, bg="#0b1a22", fg="#7fa7b8", justify="left",
                                 font=("Segoe UI", 9, "italic"), wraplength=int(360 * self.escala))
        self.resp_txt = tk.Label(self.bocadillo, bg="#0b1a22", fg="#e2f7ff", justify="left",
                                 font=fuente, wraplength=int(360 * self.escala))
        self.oido_txt.pack(anchor="w", padx=12, pady=(10, 2))
        self.resp_txt.pack(anchor="w", padx=12, pady=(2, 10))
        self.bocadillo.withdraw()
        self.bocadillo.bind("<Button-1>", lambda e: self.bocadillo.withdraw())
        self._ocultar_en = 0.0

        self.voz = Voz(self)
        # El lienzo de la pantalla (dibujar encima y los tutoriales), en `self.pantalla`: OJO,
        # `self.lienzo` es el Canvas del reactor (el 2026-11-21 se pisaron y el reactor dejó de
        # pintarse). Si falla, el reactor sigue
        # siendo el de siempre: es un añadido, no una dependencia.
        try:
            from lienzo import Lienzo
            self.pantalla = Lienzo(self, CLAVE)
        except Exception as e:   # noqa: BLE001
            log.warning("lienzo: no arranca (%s)", type(e).__name__)
            self.pantalla = None
        self.root.after(30, self._latido)
        self.root.after(33, self._dibujar)
        if not self.base:
            self._decir_error("No sé la dirección del backend: falta LA_API_BASE en agent/.env "
                              "o JARVIS_BACKEND en ~/.jarvis-pc/escritorio.env.")
        elif not self.token:
            self.root.after(600, self.pedir_sesion)

    # ── utilidades ──
    def cabeceras(self) -> dict:
        return {"Authorization": f"Bearer {self.token}"}

    def en_ui(self, fn, *args) -> None:
        self.cola.put((fn, args))

    def poner(self, estado: str) -> None:
        self.estado = estado
        if estado == "piensa":
            self.pensando_desde = time.time()

    # ── el bucle ──
    def _latido(self) -> None:
        try:
            while True:
                fn, args = self.cola.get_nowait()
                fn(*args)
        except queue.Empty:
            pass
        evento = self.tecla.paso(
            _pulsada(VK_LCONTROL) or _pulsada(VK_RCONTROL), _pulsada(VK_LMENU),
            _pulsada(VK_RMENU), any(_pulsada(vk) for vk in _OTRAS), time.monotonic())
        if evento == "empieza" and not self.manual:
            self.empezar_a_oir()
        elif evento == "cancela" and not self.manual:
            self.cancelar_oir()
        elif evento == "suelta" and not self.manual:
            self.terminar_de_oir()
        if self.estado == "habla" and not self.voz.hablando and not self.voz.pendientes:
            self.poner("reposo")
        if self._ocultar_en and time.time() > self._ocultar_en and self.estado == "reposo":
            self.bocadillo.withdraw()
            self._ocultar_en = 0.0
        guiando = False
        if self.pantalla is not None:
            try:
                self.pantalla.latido()
                guiando = self.pantalla.guiando
            except Exception as e:   # noqa: BLE001 — un fallo del lienzo no tumba el reactor
                log.warning("lienzo: %s", type(e).__name__)
        self._volando()
        self._ver(debe_verse(self.estado, self.bocadillo.winfo_viewable() == 1,
                             self.siempre or bool(self._arrastre) or guiando or bool(self._vuelo)))
        self.root.after(30, self._latido)

    # ── el vuelo (durante un tutorial, el reactor se pone junto al paso) ──
    def volar(self, destino) -> None:
        """`destino` (x, y) de la esquina del reactor, o None para volver a su sitio."""
        if destino is None:
            if self._casa is not None:
                self._vuelo, self._casa = self._casa, None
            return
        if self._casa is None and not self._vuelo:
            self._casa = (self.root.winfo_x(), self.root.winfo_y())
        m = ctypes.windll.user32.GetSystemMetrics
        izq, arr, ancho, alto = m(76), m(77), m(78), m(79)
        x = max(izq, min(int(destino[0]), izq + ancho - self.lado))
        y = max(arr, min(int(destino[1]), arr + alto - self.lado))
        self._vuelo = (x, y)

    def _volando(self) -> None:
        if not self._vuelo:
            return
        x, y = self.root.winfo_x(), self.root.winfo_y()
        dx, dy = self._vuelo[0] - x, self._vuelo[1] - y
        if abs(dx) + abs(dy) < 3:
            self.root.geometry(f"+{self._vuelo[0]}+{self._vuelo[1]}")
            self._vuelo = None
            return
        paso_x = int(dx * 0.25) or (dx > 0) - (dx < 0)
        paso_y = int(dy * 0.25) or (dy > 0) - (dy < 0)
        self.root.geometry(f"+{x + paso_x}+{y + paso_y}")

    def mostrar_aviso(self, texto: str) -> None:
        self._mostrar("", texto)
        self._ocultar_en = time.time() + 5

    def _ver(self, si: bool) -> None:
        """Enseña u oculta el reactor. Oculto no se dibuja: no gasta nada."""
        if si == self.visible:
            return
        self.visible = si
        if si:
            self.root.deiconify()
            self.root.attributes("-topmost", True)
            self.root.lift()
        else:
            self.root.withdraw()

    # ── oír ──
    def empezar_a_oir(self) -> None:
        if not self.token:
            self.pedir_sesion()
            return
        if self.estado in ("piensa",):
            return
        self.voz.callar()
        try:
            self.oido = Oido(self.base, self.token)
            self.micro.abrir(self.oido.mete)
        except ImportError:
            self.oido = None
            self._decir_error("Falta el micrófono: ejecute agent/instalar_escritorio.ps1.")
            return
        except Exception as e:   # noqa: BLE001
            self.oido = None
            self._decir_error(f"No puedo abrir el micrófono ({type(e).__name__}).")
            return
        self.poner("escucha")

    def cancelar_oir(self) -> None:
        self.micro.cerrar()
        if self.oido:
            self.oido.cancelar()
            self.oido = None
        self.manual = False
        if self.estado == "escucha":
            self.poner("reposo")

    def terminar_de_oir(self) -> None:
        self.micro.cerrar()
        oido, self.oido, self.manual = self.oido, None, False
        if not oido:
            return
        self.poner("piensa")
        threading.Thread(target=self._turno, args=(oido,), daemon=True, name="turno").start()

    # ── pensar y hablar (en su hilo) ──
    def _turno(self, oido: Oido) -> None:
        import httpx
        try:
            texto = oido.texto()
        except RuntimeError as e:
            if str(e) == "sin_sesion":
                self.en_ui(self._sesion_caducada)
            else:
                self.en_ui(self._decir_error, f"No le he oído bien: {e}.")
            return
        if not texto:
            self.en_ui(self.poner, "reposo")
            return
        self.en_ui(self._mostrar, texto, "")
        # `/jarvis/voz` retransmite: va diciendo cada frase según se escribe. Lo piensa Claude
        # (JARVIS_VOZ_MOTOR=claude en el backend), como Telegram, con OpenAI de reserva.
        cuerpo = {"mensaje": texto[:2000], "historial": recorta_historial(self.historial), "voz": True}
        frases, lector, dicho, respuesta = Frases(), LectorSSE(), [], ""
        por_decir, pendiente = None, None
        try:
            with httpx.stream("POST", f"{self.base}/jarvis/voz", json=cuerpo,
                              headers=self.cabeceras(), timeout=httpx.Timeout(120, connect=10)) as r:
                if r.status_code == 401:
                    self.en_ui(self._sesion_caducada)
                    return
                if r.status_code >= 300:
                    self.en_ui(self._decir_error, f"El backend ha contestado {r.status_code}.")
                    return
                for trozo in r.iter_bytes():
                    for tipo, datos in lector.trozo(trozo):
                        if tipo == "texto":
                            for frase in frases.mete(str(datos.get("delta") or "")):
                                dicho.append(frase)
                                self.voz.di(frase)
                                self.en_ui(self._hablar, " ".join(dicho))
                        elif tipo == "herramienta":
                            # Lo escrito antes de ponerse a mirar se dice ya, y luego el
                            # relleno («Miro la agenda.») mientras la herramienta trabaja.
                            for frase in frases.resto():
                                dicho.append(frase)
                                self.voz.di(frase)
                            if datos.get("decir"):
                                self.voz.di(str(datos["decir"]))
                        elif tipo == "fin":
                            respuesta = str(datos.get("respuesta") or "").strip()
                            por_decir = datos.get("por_decir")
                            pendiente = datos.get("pendiente")
                        elif tipo == "error":
                            self.en_ui(self._decir_error, str(datos.get("detalle") or "Se ha roto el turno."))
                            return
        except Exception as e:   # noqa: BLE001
            self.en_ui(self._decir_error, f"No llego al backend ({type(e).__name__}).")
            return
        for frase in frases.resto():
            dicho.append(frase)
            self.voz.di(frase)
        # `por_decir` es lo que el backend sabe que NO ha salido ya por el altavoz; sin él
        # (un backend viejo), la respuesta entera si no se retransmitió nada.
        queda = str(por_decir if por_decir is not None else ("" if dicho else respuesta)).strip()
        if queda:
            partidor = Frases()
            for frase in partidor.mete(queda) + partidor.resto():
                self.voz.di(frase)
        final = respuesta or " ".join(dicho)
        self.historial += [{"rol": "user", "texto": texto}, {"rol": "assistant", "texto": final}]
        self.historial = recorta_historial(self.historial)
        if pendiente:
            # Aquí no hay botón: lo propuesto se aprueba en el dashboard o en el móvil.
            final += "\n\n(Pendiente de su confirmación en el dashboard o el móvil.)"
        self.en_ui(self._hablar, final, True)

    # ── lo que se ve ──
    def _mostrar(self, oido: str, respuesta: str) -> None:
        self.oido_txt.configure(text=f"«{oido}»" if oido else "")
        self.resp_txt.configure(text=respuesta or "…")
        self._colocar_bocadillo()

    def _hablar(self, texto: str, final: bool = False) -> None:
        self.resp_txt.configure(text=texto)
        self._colocar_bocadillo()
        if final:
            self.poner("habla" if (self.voz.hablando or self.voz.pendientes) else "reposo")
            self._ocultar_en = time.time() + 6 + len(texto) / 15
        elif self.estado == "piensa":
            self.poner("habla")

    def _colocar_bocadillo(self) -> None:
        self.bocadillo.deiconify()
        self.bocadillo.update_idletasks()
        an, al = self.bocadillo.winfo_reqwidth(), self.bocadillo.winfo_reqheight()
        x = self.root.winfo_x() - an - int(8 * self.escala)
        if x < 0:
            x = self.root.winfo_x() + self.lado + int(8 * self.escala)
        y = max(0, self.root.winfo_y() + self.lado - al - int(20 * self.escala))
        self.bocadillo.geometry(f"+{x}+{y}")
        self.bocadillo.lift()

    def _decir_error(self, texto: str) -> None:
        log.warning("aviso: %s", texto[:120])
        self.poner("error")
        self._mostrar("", texto)
        self._ocultar_en = time.time() + 8
        self.root.after(4000, lambda: self.estado == "error" and self.poner("reposo" if self.token else "sin_sesion"))

    def _sesion_caducada(self) -> None:
        self.token = ""
        self.config.pop("token", None)
        guardar_config(self.config)
        self.poner("sin_sesion")
        self.pedir_sesion()

    # ── la sesión ──
    def pedir_sesion(self) -> None:
        if getattr(self, "_ventana_sesion", None) and self._ventana_sesion.winfo_exists():
            self._ventana_sesion.lift()
            return
        v = tk.Toplevel(self.root)
        self._ventana_sesion = v
        v.title("Jarvis")
        v.attributes("-topmost", True)
        v.configure(bg="#0b1a22")
        v.resizable(False, False)
        tk.Label(v, text="Contraseña del dashboard", bg="#0b1a22", fg="#e2f7ff",
                 font=("Segoe UI", 10)).pack(padx=18, pady=(14, 6))
        entrada = tk.Entry(v, show="•", width=28, font=("Segoe UI", 11))
        entrada.pack(padx=18)
        aviso = tk.Label(v, text="", bg="#0b1a22", fg="#ff8a80", font=("Segoe UI", 9))
        aviso.pack(padx=18, pady=(4, 12))

        def entrar(_e=None):
            clave = entrada.get()
            entrada.delete(0, "end")
            if not clave:
                return
            aviso.configure(text="Comprobando…")

            def trabajo():
                import httpx
                try:
                    r = httpx.post(f"{self.base}/auth/password", json={"password": clave}, timeout=15)
                except Exception as e:   # noqa: BLE001
                    self.en_ui(aviso.configure, {"text": f"No llego al backend ({type(e).__name__})."})
                    return
                if r.status_code == 200 and r.json().get("token"):
                    self.en_ui(self._sesion_lista, r.json()["token"], v)
                elif r.status_code == 429:
                    self.en_ui(aviso.configure, {"text": "Demasiados intentos: espere un rato."})
                else:
                    self.en_ui(aviso.configure, {"text": "No es esa."})
            threading.Thread(target=trabajo, daemon=True).start()

        entrada.bind("<Return>", entrar)
        v.update_idletasks()
        v.geometry(f"+{self.root.winfo_x() - v.winfo_reqwidth() - 10}+{self.root.winfo_y()}")
        entrada.focus_force()

    def _sesion_lista(self, token: str, ventana) -> None:
        self.token = token
        self.config["token"] = token
        guardar_config(self.config)
        ventana.destroy()
        self.poner("reposo")
        self._mostrar("", "A su servicio, señor. Mantenga Ctrl + Alt para hablarme.")
        self.voz.di("A su servicio, señor.")
        self._ocultar_en = time.time() + 6

    # ── el ratón ──
    def _raton_baja(self, e) -> None:
        self._arrastre = (e.x_root, e.y_root, self.root.winfo_x(), self.root.winfo_y(), False)

    def _raton_mueve(self, e) -> None:
        if not self._arrastre:
            return
        x0, y0, wx, wy, movido = self._arrastre
        dx, dy = e.x_root - x0, e.y_root - y0
        if movido or abs(dx) + abs(dy) > 6:
            self._arrastre = (x0, y0, wx, wy, True)
            self.root.geometry(f"+{wx + dx}+{wy + dy}")

    def _raton_sube(self, _e) -> None:
        if not self._arrastre:
            return
        movido = self._arrastre[4]
        self._arrastre = None
        if movido:
            self.config["x"], self.config["y"] = self.root.winfo_x(), self.root.winfo_y()
            guardar_config(self.config)
            return
        if self.estado == "habla":
            self.voz.callar()
            self.poner("reposo")
        elif self.estado == "escucha" and self.manual:
            self.terminar_de_oir()
        elif self.estado in ("reposo", "error", "sin_sesion"):
            self.manual = True
            self.empezar_a_oir()
            if self.estado != "escucha":
                self.manual = False

    def _menu(self, e) -> None:
        m = tk.Menu(self.root, tearoff=0)
        m.add_command(label="Hablar (o mantenga Ctrl + Alt)", command=lambda: self._raton_sube_simulado())
        m.add_command(label="Activar la voz" if self.mudo else "Silenciar la voz", command=self._alternar_mudo)
        m.add_command(label="Ocultarlo cuando no le hablo" if self.siempre else "Dejarlo siempre a la vista",
                      command=self._alternar_siempre)
        m.add_command(label="Olvidar la conversación", command=lambda: self.historial.clear())
        m.add_separator()
        m.add_command(label="Cerrar sesión", command=self._sesion_caducada)
        m.add_command(label="Salir", command=self.salir)
        m.tk_popup(e.x_root, e.y_root)

    def _raton_sube_simulado(self) -> None:
        self._arrastre = (0, 0, 0, 0, False)
        self._raton_sube(None)

    def _alternar_mudo(self) -> None:
        self.mudo = not self.mudo
        self.config["mudo"] = self.mudo
        guardar_config(self.config)
        if self.mudo:
            self.voz.callar()

    def _alternar_siempre(self) -> None:
        self.siempre = not self.siempre
        self.config["siempre_visible"] = self.siempre
        guardar_config(self.config)

    def salir(self) -> None:
        if self.pantalla is not None:
            self.pantalla.cerrar()
        self.micro.cerrar()
        self.voz.callar()
        self.root.destroy()

    # ── el reactor ──
    def _dibujar(self) -> None:
        if not self.visible:
            # Oculto no hay nada que pintar; se mira de vez en cuando por si vuelve.
            self.root.after(200, self._dibujar)
            return
        c, s = self.lienzo, self.escala
        c.delete("all")
        self.fase += 1
        color = COLORES.get(self.estado, COLORES["reposo"])
        cx = cy = self.lado / 2
        velocidad = {"piensa": 6.0, "escucha": 2.5, "habla": 2.0}.get(self.estado, 0.8)
        if self.estado == "escucha":
            pulso = 0.15 + self.micro.nivel * 0.85
        elif self.estado == "habla":
            pulso = 0.45 + 0.35 * math.sin(self.fase / 3)
        elif self.estado == "piensa":
            pulso = 0.4 + 0.2 * math.sin(self.fase / 2)
        else:
            pulso = 0.25 + 0.1 * math.sin(self.fase / 20)
        tenue = _mezcla(color, "#06121a", 0.65)

        def circulo(r, **kw):
            c.create_oval(cx - r * s, cy - r * s, cx + r * s, cy + r * s, **kw)

        def arco(r, inicio, extension, ancho, col):
            c.create_arc(cx - r * s, cy - r * s, cx + r * s, cy + r * s, start=inicio,
                         extent=extension, style="arc", width=ancho * s, outline=col)

        circulo(66, fill="#06121a", outline=tenue, width=2 * s)
        # Los arcos de fuera, que giran
        giro = self.fase * velocidad
        for k, (r, ext) in enumerate(((60, 70), (60, 40), (55, 25))):
            arco(r, (giro * (1 if k % 2 == 0 else -1.3) + k * 120) % 360, ext, 3, color if k == 0 else tenue)
        # El anillo de segmentos
        for k in range(10):
            encendido = self.estado != "sin_sesion" and (k + int(self.fase / 4)) % 10 < 10 * (0.5 + pulso / 2)
            arco(44, k * 36 + 6, 24, 7, color if encendido else tenue)
        circulo(32, outline=tenue, width=2 * s)
        # El núcleo
        r = 14 + 9 * pulso
        circulo(r + 6, fill=_mezcla(color, "#06121a", 0.55), outline="")
        circulo(r, fill=color, outline="")
        circulo(r * 0.45, fill=_mezcla(color, "#ffffff", 0.6), outline="")
        if self.estado == "piensa" and time.time() - self.pensando_desde > 60:
            self.poner("reposo")
        self.root.after(33, self._dibujar)

    def correr(self) -> None:
        self.root.mainloop()


def _mezcla(a: str, b: str, t: float) -> str:
    """El color `a` llevado hacia `b` en una proporción `t` (Tk no tiene transparencias)."""
    ca = [int(a[i:i + 2], 16) for i in (1, 3, 5)]
    cb = [int(b[i:i + 2], 16) for i in (1, 3, 5)]
    return "#" + "".join(f"{round(x + (y - x) * t):02x}" for x, y in zip(ca, cb))


def principal() -> None:
    DIR.mkdir(exist_ok=True)
    logging.basicConfig(filename=str(REGISTRO), level=logging.INFO,
                        format="%(asctime)s %(levelname)s %(message)s", encoding="utf-8")
    if not una_sola_instancia():
        return
    log.info("arranca")
    App().correr()


if __name__ == "__main__":
    principal()
