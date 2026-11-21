"""El lienzo de Jarvis: dibujar encima de la pantalla de verdad y guiar paso a paso.

Fases 3 y 4 del cuerpo de escritorio (docs/ESCRITORIO.md, «Las manos y el lienzo»). Vive
dentro de `escritorio.py`, en el mismo proceso que el reactor, porque es el mismo cuerpo:
la voz que dice cada paso es la de Jarvis y el reactor vuela junto al botón que toca.

- **Marcas**: un anillo que late alrededor de un botón, una caja o una flecha, con una
  etiqueta. Se quitan solas a los `segundos`.
- **Tarjetas**: un panel flotante con un título, unas líneas, barras o una línea de una
  serie, encima de lo que esté mirando (el esquema cerrado de `lienzo_logica`).
- **Tutoriales**: una lista de pasos. En cada uno se busca el botón con las manos
  (`manos.buscar`, que espera a que aparezca si un diálogo se está abriendo), se rodea, se
  dice el paso y se espera a que Mikel lo pulse. Esc lo corta.

La ventana del lienzo es transparente y **deja pasar los clics** (WS_EX_TRANSPARENT): se
dibuja encima, pero se trabaja debajo. Solo existe mientras hay algo que enseñar, y del
tamaño de lo que se enseña, no de las tres pantallas.

Recibe los encargos de `pc_mcp.py` por HTTP en 127.0.0.1, con un token que se genera al
arrancar y se deja en `~/.jarvis-pc/lienzo.json` (puerto y token): solo lo lee quien ya
es Mikel en este PC. Nada de lo que llega se ejecuta: son marcas y texto.
"""

import ctypes
import hmac
import json
import logging
import os
import secrets
import threading
import time
from ctypes import wintypes
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import tkinter as tk
import tkinter.font as tkfont

from lienzo_logica import (BUSCAR_MAX_S, MAX_MARCAS, Tutorial, caja_de, colocar, de_fraccion,
                           pantalla_de, segundos, validar_marcas, validar_pasos, validar_tarjeta)

log = logging.getLogger("escritorio")

_u32 = ctypes.windll.user32
CIAN, CIAN_VIVO, FONDO, TEXTO, TENUE = "#2fb8e6", "#8af6ff", "#0b1a22", "#e2f7ff", "#7fa7b8"
VK_LBUTTON, VK_ESCAPE = 0x01, 0x1B
MAX_CUERPO = 65536


def pantallas() -> list:
    """Cada monitor como (izq, arriba, der, abajo), en píxeles físicos."""
    salida = []

    class RECT(ctypes.Structure):
        _fields_ = [("l", wintypes.LONG), ("t", wintypes.LONG), ("r", wintypes.LONG), ("b", wintypes.LONG)]

    @ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HMONITOR, wintypes.HDC, ctypes.POINTER(RECT), wintypes.LPARAM)
    def _cada(_h, _dc, r, _p):
        salida.append((r.contents.l, r.contents.t, r.contents.r, r.contents.b))
        return True

    _u32.EnumDisplayMonitors(None, None, _cada, 0)
    return salida or [(0, 0, _u32.GetSystemMetrics(0), _u32.GetSystemMetrics(1))]


def _raton() -> tuple:
    p = wintypes.POINT()
    _u32.GetCursorPos(ctypes.byref(p))
    return p.x, p.y


def _pulsada(vk: int) -> bool:
    return bool(_u32.GetAsyncKeyState(vk) & 0x8000)


class Lienzo:
    def __init__(self, app, clave: str):
        self.app = app
        self.root = app.root
        self.clave = clave                       # el color que Windows vuelve transparente
        self.escala = app.escala
        self.ventana = None
        self.lienzo = None
        self.origen = (0, 0)
        self.marcas = []                          # [{forma, texto, rect}]
        self.tarjeta = None
        self.hasta = 0.0
        self.tutorial = None
        self.etiqueta_paso = ""
        self._boton = False
        self._avanzando = False
        self._fase = 0
        self._dibujado = 0.0
        self.fuente = tkfont.Font(family="Segoe UI", size=10)
        self.fuente_negrita = tkfont.Font(family="Segoe UI", size=10, weight="bold")
        self.fuente_peque = tkfont.Font(family="Segoe UI", size=8)
        self.token = secrets.token_urlsafe(32)
        self.servidor = None
        self._arrancar_servidor()

    # ── lo que llega de pc_mcp ──
    def _arrancar_servidor(self) -> None:
        lienzo = self

        class Atiende(BaseHTTPRequestHandler):
            def log_message(self, *_a):
                pass

            def _responder(self, codigo: int, datos: dict) -> None:
                cuerpo = json.dumps(datos, ensure_ascii=False).encode()
                self.send_response(codigo)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(cuerpo)))
                self.end_headers()
                self.wfile.write(cuerpo)

            def _autorizado(self) -> bool:
                recibido = (self.headers.get("X-Lienzo-Token") or "").encode()
                return hmac.compare_digest(recibido, lienzo.token.encode())

            def do_GET(self):
                if not self._autorizado():
                    return self._responder(401, {"error": "token"})
                if self.path == "/estado":
                    return self._responder(200, lienzo.en_hilo_ui(lienzo.estado))
                self._responder(404, {"error": "no existe"})

            def do_POST(self):
                if not self._autorizado():
                    return self._responder(401, {"error": "token"})
                largo = int(self.headers.get("Content-Length") or 0)
                if largo <= 0 or largo > MAX_CUERPO:
                    return self._responder(413, {"error": "cuerpo"})
                try:
                    datos = json.loads(self.rfile.read(largo))
                except ValueError:
                    return self._responder(400, {"error": "json"})
                fn = {"/dibujar": lienzo.dibujar, "/tutorial": lienzo.empezar_tutorial,
                      "/borrar": lienzo.borrar_todo}.get(self.path)
                if fn is None or not isinstance(datos, dict):
                    return self._responder(404, {"error": "no existe"})
                self._responder(200, lienzo.en_hilo_ui(fn, datos))

        try:
            self.servidor = ThreadingHTTPServer(("127.0.0.1", 0), Atiende)
        except OSError as e:
            log.warning("lienzo: no puedo escuchar (%s)", type(e).__name__)
            return
        threading.Thread(target=self.servidor.serve_forever, daemon=True, name="lienzo").start()
        datos = {"puerto": self.servidor.server_address[1], "token": self.token, "pid": os.getpid()}
        ruta = self.app.dir / "lienzo.json"
        tmp = ruta.with_suffix(".tmp")
        tmp.write_text(json.dumps(datos), encoding="utf-8")
        os.replace(tmp, ruta)
        log.info("lienzo: escuchando en 127.0.0.1:%s", datos["puerto"])

    def en_hilo_ui(self, fn, *args) -> dict:
        """Ejecuta `fn` en el hilo de Tk y espera su resultado (Tk no es multihilo)."""
        listo, caja = threading.Event(), {}

        def correr():
            try:
                caja["r"] = fn(*args)
            except Exception as e:   # noqa: BLE001
                log.warning("lienzo: %s", type(e).__name__)
                caja["r"] = {"ok": False, "error": "El lienzo ha fallado."}
            listo.set()

        self.app.en_ui(correr)
        if not listo.wait(5):
            return {"ok": False, "error": "El reactor no contesta."}
        return caja["r"]

    def estado(self) -> dict:
        return {"ok": True, "marcas": len(self.marcas), "tarjeta": bool(self.tarjeta),
                "tutorial": self.tutorial.estado() if self.tutorial else None}

    def dibujar(self, datos: dict) -> dict:
        marcas = []
        total = caja_de(pantallas())
        crudas = datos.get("marcas") if isinstance(datos.get("marcas"), list) else []
        for cruda in crudas[:MAX_MARCAS]:
            limpias = validar_marcas([cruda])
            if not limpias:
                continue
            m, rect = limpias[0], _rect(cruda.get("rect"))
            if rect is None and "x" in m:
                x, y = de_fraccion(m["x"], m["y"], total)
                rect = (x - 14, y - 14, x + 14, y + 14)
            if rect is not None:
                marcas.append({"forma": m["forma"], "texto": m["texto"], "rect": rect})
        tarjeta = validar_tarjeta(datos.get("tarjeta"))
        if not marcas and not tarjeta:
            self.borrar_todo({})
            return {"ok": True, "borrado": True}
        self.marcas, self.tarjeta = marcas, tarjeta
        self.hasta = time.monotonic() + segundos(datos.get("segundos"))
        self._componer()
        return {"ok": True, "marcas": len(marcas), "tarjeta": bool(tarjeta)}

    def borrar_todo(self, _datos=None) -> dict:
        if self.tutorial and not self.tutorial.fin:
            self.tutorial.cancelar()
        self.tutorial = None
        self.marcas, self.tarjeta, self.etiqueta_paso = [], None, ""
        self.app.volar(None)
        self._cerrar_ventana()
        return {"ok": True}

    # ── el tutorial ──
    @property
    def guiando(self) -> bool:
        return bool(self.tutorial and not self.tutorial.fin)

    def empezar_tutorial(self, datos: dict) -> dict:
        pasos = validar_pasos(datos.get("pasos"))
        if not pasos:
            return {"ok": False, "error": "El tutorial no trae ningún paso con texto."}
        self.borrar_todo()
        self.tutorial = Tutorial(datos.get("titulo") or "", pasos)
        self.app.mostrar_aviso(f"{self.tutorial.titulo or 'Tutorial'}: {len(pasos)} pasos. Esc lo corta.")
        self._paso()
        return {"ok": True, "pasos": len(pasos)}

    def _paso(self) -> None:
        t = self.tutorial
        paso = t.empezar_paso(time.monotonic())
        if paso is None:
            self._terminar()
            return
        self.marcas, self.tarjeta = [], None
        self.etiqueta_paso = f"Paso {t.i + 1} de {len(t.pasos)}"
        self._componer()
        self.app.voz.di(paso["texto"])
        if paso["objetivo"]:
            threading.Thread(target=self._buscar, args=(t, t.i), daemon=True, name="lienzo-busca").start()

    def _buscar(self, t: Tutorial, indice: int) -> None:
        """En su hilo: busca el botón del paso y lo sigue buscando mientras el paso dure, por
        si la ventana se mueve o el diálogo tarda en abrirse."""
        import manos
        paso = t.pasos[indice]
        empezado, ultimo = time.monotonic(), "nada"
        while t.i == indice and not t.fin:
            try:
                hallado = manos.buscar(paso["objetivo"], paso.get("ventana") or "")
                rect = hallado["rect"]
                if ultimo == "nada" and paso.get("ventana"):
                    # La primera vez, la ventana del paso delante: si no, el anillo caería
                    # encima de la que la tapa.
                    manos.al_frente(hallado["hwnd"])
                    rect = manos.buscar(paso["objetivo"], paso["ventana"])["rect"]
            except Exception:   # noqa: BLE001 — NoEncontrado o una ventana que se cerró
                rect = None
            if rect is not None and rect != ultimo:
                self.app.en_ui(self._encontrado, t, indice, rect)
                ultimo = rect
            elif rect is None and ultimo == "nada" and time.monotonic() - empezado > BUSCAR_MAX_S:
                self.app.en_ui(self._encontrado, t, indice, None)
                ultimo = None
            time.sleep(0.6 if ultimo == "nada" else 1.5)

    def _encontrado(self, t: Tutorial, indice: int, rect) -> None:
        if t is not self.tutorial or t.i != indice or t.fin:
            return
        t.encontrado(rect)
        self.marcas = [{"forma": "anillo", "texto": "", "rect": tuple(rect)}] if rect else []
        if rect is None:
            log.info("lienzo: no encuentro el objetivo de un paso; sigue con un clic en cualquier sitio")
        self._componer()

    def _siguiente(self) -> None:
        self._avanzando = False
        if not self.tutorial or self.tutorial.fin:
            return
        self.tutorial.avanzar()
        self._paso()

    def _terminar(self) -> None:
        t = self.tutorial
        fin = t.fin if t else "hecho"
        self.app.voz.di({"hecho": "Listo, señor.", "abandonado": "Lo dejo aquí, señor; "
                         "cuando quiera seguimos."}.get(fin, "Lo dejamos aquí, señor."))
        self.borrar_todo()

    # ── el latido (lo llama el de escritorio.py, ~30 veces por segundo) ──
    def latido(self) -> None:
        ahora = time.monotonic()
        boton = _pulsada(VK_LBUTTON)
        t = self.tutorial
        if self._boton and not boton and t and not t.fin and not self._avanzando:
            if t.clic(*_raton()):
                # Un respiro antes de buscar el siguiente: el menú que abre ese clic tarda.
                self._avanzando = True
                self.root.after(450, self._siguiente)
        self._boton = boton
        if t and not t.fin:
            if _pulsada(VK_ESCAPE):
                t.cancelar()
                self._terminar()
                return
            if not self.app.voz.hablando and not self.app.voz.pendientes and ahora - t.desde > 0.5:
                t.dicho(ahora)
            if t.toca_seguir(ahora) and not self._avanzando:
                self._avanzando = True
                self.root.after(100, self._siguiente)
            elif t.caducado(ahora):
                t.cancelar("abandonado")
                self._terminar()
                return
        elif (self.marcas or self.tarjeta) and ahora > self.hasta:
            self.borrar_todo()
        if self.ventana is not None and ahora - self._dibujado > 0.06:
            self._dibujado = ahora
            self._fase += 1
            self._animar()

    # ── dibujar ──
    def _envolver(self, texto: str, ancho: int, fuente) -> list:
        lineas, actual = [], ""
        for palabra in texto.split():
            prueba = f"{actual} {palabra}".strip()
            if fuente.measure(prueba) <= ancho or not actual:
                actual = prueba
            else:
                lineas.append(actual)
                actual = palabra
        return lineas + ([actual] if actual else [])

    def _componer(self) -> None:
        """Calcula dónde va cada cosa (en píxeles de pantalla), ajusta la ventana a lo justo
        y pinta lo que no se mueve. Lo que late lo pinta `_animar`."""
        s = self.escala
        piezas, monitores = [], pantallas()
        ancho_texto = int(320 * s)
        holgura = int(14 * s)
        ocupados = [(m["rect"][0] - holgura, m["rect"][1] - holgura, m["rect"][2] + holgura,
                     m["rect"][3] + holgura) for m in self.marcas]

        def sitio(objetivo, w, h, hueco=18):
            x, y = colocar(objetivo, w, h, pantalla_de(objetivo[:2], monitores), ocupados, hueco)
            ocupados.append((x, y, x + w, y + h))
            return x, y

        for m in self.marcas:
            piezas.append(("marca", m["rect"], m))
            if m["texto"]:
                lineas = self._envolver(m["texto"], ancho_texto, self.fuente)
                w = max(self.fuente.measure(l) for l in lineas) + int(24 * s)
                h = len(lineas) * self.fuente.metrics("linespace") + int(16 * s)
                x, y = sitio(m["rect"], w, h)
                piezas.append(("etiqueta", (x, y, x + w, y + h), {"lineas": lineas}))
        paso = self.tutorial.actual if self.guiando else None
        if paso:
            lineas = self._envolver(paso["texto"], ancho_texto, self.fuente)
            alto_cab = self.fuente_peque.metrics("linespace")
            w = max([self.fuente.measure(l) for l in lineas] + [self.fuente_peque.measure(self.etiqueta_paso)]) + int(28 * s)
            h = alto_cab + len(lineas) * self.fuente.metrics("linespace") + int(22 * s)
            rect = self.marcas[0]["rect"] if self.marcas else None
            if rect:
                x, y = sitio(rect, w, h)
            else:
                x, y = self._junto_al_reactor(w, h, monitores)
            piezas.append(("paso", (x, y, x + w, y + h), {"lineas": lineas}))
            self.app.volar((x + w + int(6 * s), y + h // 2 - self.app.lado // 2))
        if self.tarjeta:
            w, h = self._medir_tarjeta(self.tarjeta)
            ancla = self.marcas[0]["rect"] if self.marcas else None
            if ancla:
                x, y = sitio(ancla, w, h, hueco=int(30 * s))
            else:
                x, y = self._junto_al_reactor(w, h, monitores)
            piezas.append(("tarjeta", (x, y, x + w, y + h), self.tarjeta))
        if not piezas:
            self._cerrar_ventana()
            return
        caja = caja_de([p[1] for p in piezas], margen=int(30 * s))
        self._ventana_en(caja)
        c = self.lienzo
        c.delete("all")
        ox, oy = self.origen
        for tipo, rect, datos in piezas:
            r = (rect[0] - ox, rect[1] - oy, rect[2] - ox, rect[3] - oy)
            if tipo == "etiqueta":
                self._bocadillo(r, datos["lineas"])
            elif tipo == "paso":
                self._bocadillo(r, datos["lineas"], cabecera=self.etiqueta_paso)
            elif tipo == "tarjeta":
                self._pintar_tarjeta(r, datos)
        self._animar()

    def _junto_al_reactor(self, w: int, h: int, monitores: list) -> tuple:
        rx, ry = self.root.winfo_x(), self.root.winfo_y()
        p = pantalla_de((rx, ry), monitores)
        x = min(max(p[0] + 8, rx + self.app.lado - w), p[2] - w - 8)
        y = ry - h - int(10 * self.escala)
        if y < p[1] + 8:
            y = min(ry + self.app.lado + 10, p[3] - h - 8)
        return x, y

    def _bocadillo(self, r, lineas: list, cabecera: str = "") -> None:
        c, s = self.lienzo, self.escala
        c.create_rectangle(*r, fill=FONDO, outline=CIAN, width=max(1, int(1.5 * s)))
        c.create_rectangle(r[0], r[1], r[0] + int(4 * s), r[3], fill=CIAN, outline="")
        y = r[1] + int(8 * s)
        if cabecera:
            c.create_text(r[0] + int(14 * s), y, text=cabecera.upper(), anchor="nw", fill=CIAN_VIVO,
                          font=self.fuente_peque)
            y += self.fuente_peque.metrics("linespace") + int(2 * s)
        for linea in lineas:
            c.create_text(r[0] + int(14 * s), y, text=linea, anchor="nw", fill=TEXTO, font=self.fuente)
            y += self.fuente.metrics("linespace")

    def _medir_tarjeta(self, t: dict) -> tuple:
        s = self.escala
        ancho = int(340 * s)
        alto = int(20 * s) + (self.fuente_negrita.metrics("linespace") if t.get("titulo") else 0)
        lineas = sum(len(self._envolver(l, ancho - int(28 * s), self.fuente)) for l in t.get("lineas", []))
        alto += lineas * self.fuente.metrics("linespace")
        alto += len(t.get("barras", [])) * int(22 * s)
        if t.get("serie"):
            alto += int(90 * s)
        return ancho, alto + int(8 * s)

    def _pintar_tarjeta(self, r, t: dict) -> None:
        c, s = self.lienzo, self.escala
        c.create_rectangle(*r, fill=FONDO, outline=CIAN, width=max(1, int(1.5 * s)))
        x0, y = r[0] + int(14 * s), r[1] + int(10 * s)
        ancho = r[2] - r[0] - int(28 * s)
        if t.get("titulo"):
            c.create_text(x0, y, text=t["titulo"].upper(), anchor="nw", fill=CIAN_VIVO, font=self.fuente_negrita)
            y += self.fuente_negrita.metrics("linespace") + int(4 * s)
        for linea in t.get("lineas", []):
            for trozo in self._envolver(linea, ancho, self.fuente):
                c.create_text(x0, y, text=trozo, anchor="nw", fill=TEXTO, font=self.fuente)
                y += self.fuente.metrics("linespace")
        barras = t.get("barras", [])
        if barras:
            tope = max(abs(b["valor"]) for b in barras) or 1
            col = int(90 * s)
            for b in barras:
                largo = int((ancho - col - int(50 * s)) * abs(b["valor"]) / tope)
                c.create_text(x0, y + int(9 * s), text=b["etiqueta"], anchor="w", fill=TENUE, font=self.fuente_peque)
                c.create_rectangle(x0 + col, y + int(4 * s), x0 + col + max(2, largo), y + int(15 * s),
                                   fill=CIAN, outline="")
                c.create_text(x0 + col + largo + int(6 * s), y + int(9 * s), text=_cifra(b["valor"]),
                              anchor="w", fill=TEXTO, font=self.fuente_peque)
                y += int(22 * s)
        serie = t.get("serie")
        if serie:
            alto = int(70 * s)
            bajo, alto_v = min(serie), max(serie)
            rango = (alto_v - bajo) or 1
            puntos = []
            for i, v in enumerate(serie):
                puntos += [x0 + i * ancho / (len(serie) - 1), y + alto - (v - bajo) / rango * alto]
            c.create_line(*puntos, fill=CIAN, width=max(1, int(2 * s)), smooth=True)
            c.create_oval(puntos[-2] - 4 * s, puntos[-1] - 4 * s, puntos[-2] + 4 * s, puntos[-1] + 4 * s,
                          fill=CIAN_VIVO, outline="")
            c.create_text(x0 + ancho, y - int(2 * s), text=_cifra(alto_v), anchor="ne", fill=TENUE, font=self.fuente_peque)
            c.create_text(x0 + ancho, y + alto + int(2 * s), text=_cifra(bajo), anchor="ne", fill=TENUE, font=self.fuente_peque)

    def _animar(self) -> None:
        """Lo que late: los anillos y las flechas. Se repinta solo eso."""
        c, s = self.lienzo, self.escala
        if c is None:
            return
        c.delete("late")
        ox, oy = self.origen
        pulso = (self._fase % 20) / 20
        for m in self.marcas:
            l, t, r, b = (m["rect"][0] - ox, m["rect"][1] - oy, m["rect"][2] - ox, m["rect"][3] - oy)
            holgura = int(8 * s)
            if m["forma"] == "caja":
                c.create_rectangle(l - holgura, t - holgura, r + holgura, b + holgura, outline=CIAN_VIVO,
                                   width=int(3 * s), tags="late")
                continue
            if m["forma"] == "flecha":
                c.create_line(l - int(70 * s), b + int(50 * s), l - holgura, (t + b) / 2, arrow="last",
                              arrowshape=(int(16 * s), int(20 * s), int(7 * s)), fill=CIAN_VIVO,
                              width=int(4 * s), tags="late")
                continue
            cx, cy = (l + r) / 2, (t + b) / 2
            rx, ry = (r - l) / 2 + holgura, (b - t) / 2 + holgura
            c.create_oval(cx - rx, cy - ry, cx + rx, cy + ry, outline=CIAN_VIVO, width=int(3 * s), tags="late")
            onda = holgura + int(18 * s * pulso)
            color = _mezcla(CIAN, FONDO, pulso)
            c.create_oval(cx - rx - onda + holgura, cy - ry - onda + holgura, cx + rx + onda - holgura,
                          cy + ry + onda - holgura, outline=color, width=int(2 * s), tags="late")

    # ── la ventana ──
    def _ventana_en(self, caja) -> None:
        l, t, r, b = (int(v) for v in caja)
        w, h = max(1, r - l), max(1, b - t)
        if self.ventana is None:
            v = tk.Toplevel(self.root)
            v.overrideredirect(True)
            v.attributes("-topmost", True)
            v.configure(bg=self.clave)
            v.attributes("-transparentcolor", self.clave)
            self.lienzo = tk.Canvas(v, bg=self.clave, highlightthickness=0, bd=0)
            self.lienzo.pack(fill="both", expand=True)
            v.geometry(f"{w}x{h}+{l}+{t}")
            v.update_idletasks()
            hwnd = int(v.wm_frame(), 16)
            estilo = _u32.GetWindowLongW(hwnd, -20)
            # LAYERED | TRANSPARENT (los clics pasan) | TOOLWINDOW (sin botón en la barra) |
            # NOACTIVATE (nunca le quita el foco a su ventana)
            _u32.SetWindowLongW(hwnd, -20, estilo | 0x80000 | 0x20 | 0x80 | 0x08000000)
            self.ventana = v
        else:
            self.ventana.geometry(f"{w}x{h}+{l}+{t}")
        self.lienzo.configure(width=w, height=h)
        self.origen = (l, t)
        self.ventana.lift()
        self.ventana.attributes("-topmost", True)

    def _cerrar_ventana(self) -> None:
        if self.ventana is not None:
            self.ventana.destroy()
        self.ventana, self.lienzo = None, None

    def cerrar(self) -> None:
        self._cerrar_ventana()
        if self.servidor is not None:
            self.servidor.shutdown()
        try:
            (self.app.dir / "lienzo.json").unlink()
        except OSError:
            pass


def _rect(valor):
    """El `rect` en píxeles que `pc_mcp` ya resolvió con las manos, si son cuatro enteros con
    sentido; None si no."""
    if (isinstance(valor, list) and len(valor) == 4 and all(isinstance(v, int) for v in valor)
            and valor[2] > valor[0] and valor[3] > valor[1] and valor[2] - valor[0] < 8000
            and valor[3] - valor[1] < 8000):
        return tuple(valor)
    return None


def _cifra(v: float) -> str:
    if abs(v) >= 1000:
        return f"{v:,.0f}".replace(",", ".")
    return f"{v:.1f}".rstrip("0").rstrip(".").replace(".", ",")


def _mezcla(a: str, b: str, t: float) -> str:
    ca = [int(a[i:i + 2], 16) for i in (1, 3, 5)]
    cb = [int(b[i:i + 2], 16) for i in (1, 3, 5)]
    return "#" + "".join(f"{round(x + (y - x) * t):02x}" for x, y in zip(ca, cb))
