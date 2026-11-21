"""Las manos finas de Jarvis en el PC: leer los botones y campos de una ventana y pulsarlos
por su nombre, con UI Automation (la accesibilidad de Windows), sin coordenadas.

Es la fase 2 del cuerpo de escritorio (docs/ESCRITORIO.md, «Las manos y el lienzo»). Lo
usan dos procesos:

- `pc_mcp.py`, para las herramientas `elementos`, `pulsar` y `rellenar` (y para saber dónde
  está lo que `dibujar` tiene que marcar).
- `escritorio.py` (el lienzo), para encontrar en cada paso de un tutorial el botón que
  toca, aunque la ventana se haya movido o el diálogo acabe de abrirse.

Por qué UI Automation y no clics a ojo sobre una captura: el modelo que mira la captura la
describe en texto y no da coordenadas fiables, y una ventana cambia de sitio. «El botón
Guardar de la ventana activa» sigue siendo el mismo aunque se mueva.

Dos frenos que no dependen del modelo:

- **Lo irreversible no se pulsa** (`es_irreversible`): enviar, comprar, pagar, borrar,
  publicar… Lo pulsa Mikel. Un tutorial sí puede SEÑALARLO, que es justo lo útil.
- **Las contraseñas no se rellenan** (campos `IsPassword`).

La parte pura (qué elemento casa con «guardar», qué cuenta como irreversible) se prueba en
CI sin Windows: `tests/backend/test_manos.py`. Lo de Windows, a mano.
"""

import re
import sys
import threading
import time
import unicodedata

ES_WINDOWS = sys.platform == "win32"

# Los tipos de control que se pueden usar con la mano, por su id de UI Automation. Los
# demás (texto suelto, paneles, imágenes) no se pulsan y solo harían la lista más larga.
TIPOS = {
    50000: "botón", 50002: "casilla", 50003: "desplegable", 50004: "campo",
    50005: "enlace", 50007: "elemento de lista", 50011: "menú", 50013: "opción",
    50016: "control deslizante", 50019: "pestaña", 50024: "elemento de árbol",
    50029: "botón dividido", 50031: "botón de cinta",
}
# Sinónimos con los que el modelo pide un tipo («el campo», «la pestaña»).
_TIPO_PEDIDO = {
    "boton": 50000, "botón": 50000, "casilla": 50002, "checkbox": 50002,
    "desplegable": 50003, "combo": 50003, "campo": 50004, "texto": 50004, "edit": 50004,
    "enlace": 50005, "link": 50005, "lista": 50007, "menu": 50011, "menú": 50011,
    "opcion": 50013, "opción": 50013, "radio": 50013, "pestana": 50019, "pestaña": 50019,
    "tab": 50019, "arbol": 50024, "árbol": 50024,
}
MAX_ELEMENTOS = 120

# Lo que nunca se pulsa en nombre de Mikel. Por palabras enteras y sin tildes, en español e
# inglés, que es como vienen las aplicaciones. «Aceptar» no está: cierra mil diálogos
# inofensivos al día, y lo que importa es la orden que lo precede, que sí está aquí.
_IRREVERSIBLE = re.compile(
    r"\b(enviar|envia|envio|send|reenviar|forward|responder a todos|reply all|"
    r"comprar|compra|buy|purchase|pagar|pago|pay|checkout|tramitar pedido|realizar pedido|"
    r"confirmar pedido|confirmar compra|confirmar pago|place order|order now|"
    r"eliminar|elimina|borrar|borra|delete|remove|quitar cuenta|suprimir|vaciar|empty|"
    r"publicar|publica|publish|post|tweet|twittear|compartir publicamente|"
    r"desinstalar|uninstall|formatear|format|restablecer|reset|"
    r"transferir|transferencia|transfer|bizum|firmar|sign|suscribir\w*|subscribe|"
    r"darse de baja|darme de baja|cancelar suscripcion|unsubscribe|cerrar cuenta)\b")


def normalizar(texto: str) -> str:
    """Minúsculas, sin tildes ni signos (la misma regla que `pc_mcp.normalizar`)."""
    t = unicodedata.normalize("NFKD", str(texto or "")).encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9]+", " ", t.lower()).strip()


def es_irreversible(nombre: str) -> bool:
    return bool(_IRREVERSIBLE.search(normalizar(nombre)))


def tipo_pedido(texto: str):
    """El id de UI Automation de un tipo dicho en palabras («pestaña»), o None."""
    return _TIPO_PEDIDO.get(str(texto or "").strip().lower()) or _TIPO_PEDIDO.get(normalizar(texto))


def elegir_elemento(texto: str, elementos: list, tipo=None):
    """El elemento cuyo nombre mejor casa con `texto`, o None.

    `elementos` son dicts con `nombre`, `tipo_id` y `activo`. Gana el nombre exacto, luego
    el que empieza por lo pedido, luego el que lo contiene y por último el que contiene
    todas las palabras pedidas; a igualdad, uno activo antes que uno gris y el nombre más
    corto («Guardar» antes que «Guardar como»). `tipo` (un id) filtra si viene.
    """
    pedido = normalizar(texto)
    if not pedido:
        return None
    palabras = pedido.split()
    mejor, mejor_clave = None, None
    for e in elementos:
        if tipo and e.get("tipo_id") != tipo:
            continue
        nombre = normalizar(e.get("nombre"))
        if not nombre:
            continue
        if nombre == pedido:
            nivel = 0
        elif nombre.startswith(pedido):
            nivel = 1
        elif pedido in nombre:
            nivel = 2
        elif all(p in nombre.split() for p in palabras):
            nivel = 3
        else:
            continue
        clave = (nivel, not e.get("activo", True), len(nombre))
        if mejor_clave is None or clave < mejor_clave:
            mejor, mejor_clave = e, clave
    return mejor


def para_el_modelo(elementos: list) -> list:
    """Lo que se le enseña al modelo de cada elemento: nombre, tipo y si está gris. Sin
    coordenadas (no le sirven: pulsa y marca por nombre) y recortado, que lo ha escrito
    cualquiera."""
    salida = []
    for e in elementos[:MAX_ELEMENTOS]:
        fila = {"nombre": str(e.get("nombre") or "")[:80], "tipo": TIPOS.get(e.get("tipo_id"), "otro")}
        if not e.get("activo", True):
            fila["gris"] = True
        if e.get("secreto"):
            fila["contraseña"] = True
        salida.append(fila)
    return salida


def ordenar_por_lectura(elementos: list) -> list:
    """De arriba abajo y de izquierda a derecha, en filas de 12 px: como se lee la ventana."""
    return sorted(elementos, key=lambda e: (e["rect"][1] // 12, e["rect"][0]))


# ── Windows ──────────────────────────────────────────────────────────────────────────

class NoEncontrado(LookupError):
    pass


class Irreversible(PermissionError):
    pass


if ES_WINDOWS:
    import ctypes
    from ctypes import wintypes

    _u32 = ctypes.WinDLL("user32", use_last_error=True)
    _dwm = ctypes.WinDLL("dwmapi")
    _hilo = threading.local()

    def _uia():
        """El cliente de UI Automation de este hilo (COM es por hilo)."""
        if getattr(_hilo, "uia", None) is None:
            import comtypes
            import comtypes.client
            try:
                comtypes.CoInitializeEx(comtypes.COINIT_APARTMENTTHREADED)
            except OSError:
                pass                       # ya inicializado en este hilo
            comtypes.client.GetModule("UIAutomationCore.dll")
            from comtypes.gen import UIAutomationClient as U
            _hilo.U = U
            _hilo.uia = comtypes.client.CreateObject(U.CUIAutomation, interface=U.IUIAutomation)
        return _hilo.uia, _hilo.U

    def _clase(hwnd) -> str:
        buf = ctypes.create_unicode_buffer(128)
        _u32.GetClassNameW(hwnd, buf, 128)
        return buf.value

    def _titulo(hwnd) -> str:
        largo = _u32.GetWindowTextLengthW(hwnd)
        buf = ctypes.create_unicode_buffer(largo + 1)
        _u32.GetWindowTextW(hwnd, buf, largo + 1)
        return buf.value

    def _oculta(hwnd) -> bool:
        """Invisible, sin título, minimizada o «cloaked» (las apps de otro escritorio
        virtual y las de la Store suspendidas son visibles para Windows y no se ven)."""
        if not _u32.IsWindowVisible(hwnd) or _u32.IsIconic(hwnd) or not _u32.GetWindowTextLengthW(hwnd):
            return True
        tapada = ctypes.c_int(0)
        _dwm.DwmGetWindowAttribute(hwnd, 14, ctypes.byref(tapada), ctypes.sizeof(tapada))
        return bool(tapada.value)

    # Lo que nunca es «la ventana en la que está trabajando»: el propio reactor y su lienzo
    # (Tk), el escritorio y la barra de tareas.
    _NO_ES_TRABAJO = ("TkTopLevel", "TkChild", "Progman", "WorkerW", "Shell_TrayWnd",
                      "Shell_SecondaryTrayWnd")

    def ventana_de_trabajo(titulo: str = "") -> int:
        """La ventana sobre la que actuar: la que tenga `titulo` (o programa) si se dice; si
        no, la de delante, saltándose el reactor (si acaba de pulsarlo, el foco es suyo)."""
        if titulo:
            pedido = normalizar(titulo)
            hwnd = _u32.GetTopWindow(None)
            while hwnd:
                if not _oculta(hwnd) and _clase(hwnd) not in _NO_ES_TRABAJO \
                        and pedido in normalizar(_titulo(hwnd)):
                    return int(hwnd)
                hwnd = _u32.GetWindow(hwnd, 2)           # GW_HWNDNEXT
            raise NoEncontrado(f"No veo ninguna ventana que se llame «{titulo}»")
        hwnd = _u32.GetForegroundWindow()
        if hwnd and not _oculta(hwnd) and _clase(hwnd) not in _NO_ES_TRABAJO:
            return int(hwnd)
        hwnd = _u32.GetTopWindow(None)
        while hwnd:
            # Ni ventanas de herramientas ni las que dejan pasar los clics (WS_EX_TRANSPARENT):
            # son capas por encima de todo, como la de NVIDIA, no donde se trabaja.
            if not _oculta(hwnd) and _clase(hwnd) not in _NO_ES_TRABAJO \
                    and not (_u32.GetWindowLongW(hwnd, -20) & (0x80 | 0x20)):
                return int(hwnd)
            hwnd = _u32.GetWindow(hwnd, 2)
        raise NoEncontrado("No hay ninguna ventana abierta delante")

    def titulo_de(hwnd: int) -> str:
        return _titulo(hwnd)

    def al_frente(hwnd: int) -> None:
        """Trae la ventana delante: señalar un botón de una ventana tapada pintaría el anillo
        encima de otra. Windows solo deja robar el foco tras una pulsación: un Alt basta."""
        if _u32.GetForegroundWindow() == hwnd:
            return
        if _u32.IsIconic(hwnd):
            _u32.ShowWindow(hwnd, 9)                      # SW_RESTORE
        _u32.keybd_event(0x12, 0, 0, 0)
        _u32.keybd_event(0x12, 0, 2, 0)
        _u32.SetForegroundWindow(hwnd)

    def elementos(hwnd: int) -> list:
        """Los controles visibles y utilizables de una ventana, como se leen."""
        uia, U = _uia()
        raiz = uia.ElementFromHandle(hwnd)
        cache = uia.CreateCacheRequest()
        for p in (U.UIA_NamePropertyId, U.UIA_ControlTypePropertyId,
                  U.UIA_BoundingRectanglePropertyId, U.UIA_IsEnabledPropertyId,
                  U.UIA_IsPasswordPropertyId):
            cache.AddProperty(p)
        cond = None
        for t in TIPOS:
            c = uia.CreatePropertyCondition(U.UIA_ControlTypePropertyId, t)
            cond = c if cond is None else uia.CreateOrCondition(cond, c)
        cond = uia.CreateAndCondition(cond, uia.CreatePropertyCondition(U.UIA_IsOffscreenPropertyId, False))
        hallados = raiz.FindAllBuildCache(U.TreeScope_Descendants, cond, cache)
        salida = []
        for i in range(hallados.Length):
            el = hallados.GetElement(i)
            r = el.CachedBoundingRectangle
            if r.right - r.left < 2 or r.bottom - r.top < 2:
                continue
            nombre = (el.CachedName or "").strip()
            if not nombre and el.CachedControlType != 50004:
                continue                    # un botón sin nombre no se puede pedir
            salida.append({"nombre": nombre or "(campo sin nombre)", "tipo_id": el.CachedControlType,
                           "rect": (r.left, r.top, r.right, r.bottom),
                           "activo": bool(el.CachedIsEnabled), "secreto": bool(el.CachedIsPassword),
                           "_el": el})
        return ordenar_por_lectura(salida)

    def buscar(texto: str, titulo: str = "", tipo=None) -> dict:
        """El elemento que casa con `texto` en la ventana de trabajo. NoEncontrado si no."""
        hwnd = ventana_de_trabajo(titulo)
        e = elegir_elemento(texto, elementos(hwnd), tipo)
        if e is None:
            raise NoEncontrado(f"No veo «{texto}» en «{_titulo(hwnd)[:60]}»")
        e["ventana"] = _titulo(hwnd)
        e["hwnd"] = hwnd
        return e

    def _patron(el, id_patron, interfaz):
        try:
            p = el.GetCurrentPattern(id_patron)
            return p.QueryInterface(interfaz) if p else None
        except Exception:   # noqa: BLE001 — COMError si no lo admite
            return None

    def _clic_en(rect) -> None:
        x, y = (rect[0] + rect[2]) // 2, (rect[1] + rect[3]) // 2
        _u32.SetCursorPos(x, y)
        _u32.mouse_event(0x0002, 0, 0, 0, 0)                # LEFTDOWN
        time.sleep(0.03)
        _u32.mouse_event(0x0004, 0, 0, 0, 0)                # LEFTUP

    def pulsar(e: dict) -> str:
        """Pulsa un elemento por su patrón de UI Automation (sin mover el ratón si se
        puede); si no tiene ninguno, un clic en su centro."""
        if es_irreversible(e["nombre"]):
            raise Irreversible(f"«{e['nombre']}» no lo pulso yo: es irreversible. Puedo "
                               "señalárselo para que lo pulse usted.")
        if not e.get("activo", True):
            raise NoEncontrado(f"«{e['nombre']}» está en gris: ahora no se puede pulsar")
        _, U = _uia()
        el = e["_el"]
        for id_patron, interfaz, accion in (
                (U.UIA_InvokePatternId, U.IUIAutomationInvokePattern, "Invoke"),
                (U.UIA_SelectionItemPatternId, U.IUIAutomationSelectionItemPattern, "Select"),
                (U.UIA_TogglePatternId, U.IUIAutomationTogglePattern, "Toggle"),
                (U.UIA_ExpandCollapsePatternId, U.IUIAutomationExpandCollapsePattern, "Expand")):
            p = _patron(el, id_patron, interfaz)
            if p is not None:
                getattr(p, accion)()
                return f"Pulsado «{e['nombre']}»"
        _u32.SetForegroundWindow(e["hwnd"])
        _clic_en(e["rect"])
        return f"Clic en «{e['nombre']}»"

    def rellenar(e: dict, texto: str) -> str:
        if e.get("secreto"):
            raise PermissionError("Es un campo de contraseña: ésas las escribe usted.")
        if e.get("tipo_id") not in (50004, 50003):
            raise NoEncontrado(f"«{e['nombre']}» no es un campo de texto")
        _, U = _uia()
        p = _patron(e["_el"], U.UIA_ValuePatternId, U.IUIAutomationValuePattern)
        if p is not None and not p.CurrentIsReadOnly:
            p.SetValue(texto)
            return f"Escrito en «{e['nombre']}»"
        raise NoEncontrado(f"«{e['nombre']}» no deja escribir")
