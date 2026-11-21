"""La lógica pura del lienzo de Jarvis (`lienzo.py`): qué se dibuja sobre la pantalla y cómo
avanza un tutorial, sin ventanas ni ratón. Se prueba en CI: `tests/backend/test_lienzo.py`.

Lo que llega aquí lo ha decidido un modelo, que a su vez pudo leer una web: por eso todo
pasa por un esquema cerrado y recortado (`marcas`, `tarjeta`, `pasos`), como `hud_panel`.
Texto y cifras, nunca HTML ni órdenes; lo peor que puede salir es una marca torcida.
"""

FORMAS = ("anillo", "caja", "flecha")
TIPOS_PASO = ("clic", "mira")
MAX_MARCAS = 8
MAX_PASOS = 12
MAX_TEXTO = 160
MAX_LINEAS = 8
MAX_BARRAS = 12
MAX_SERIE = 60
SEGUNDOS_POR_DEFECTO = 20
SEGUNDOS_MAX = 120
# Lo que espera un paso de tutorial a que se haga antes de darlo por abandonado.
PASO_MAX_S = 180
# Lo que espera a que aparezca el botón de un paso (un diálogo que se está abriendo).
BUSCAR_MAX_S = 12
# Margen alrededor de un botón para dar por bueno un clic (los dedos no son exactos).
MARGEN_CLIC = 14


def _texto(valor, largo: int = MAX_TEXTO) -> str:
    return " ".join(str(valor or "").split())[:largo]


def _numero(valor):
    try:
        n = float(valor)
    except (TypeError, ValueError):
        return None
    return n if n == n and abs(n) < 1e12 else None          # ni NaN ni disparates


def _fraccion(valor):
    n = _numero(valor)
    return n if n is not None and 0 <= n <= 1 else None


def segundos(valor) -> int:
    n = _numero(valor)
    if n is None or n <= 0:
        return SEGUNDOS_POR_DEFECTO
    return int(min(n, SEGUNDOS_MAX))


def validar_marcas(marcas) -> list:
    """Las marcas, limpias. Cada una señala un `objetivo` (el nombre de un botón o campo, que
    se busca con las manos) o un punto `x`, `y` en fracción de la pantalla entera, y lleva
    una `forma` y un `texto` corto. Lo que no se entiende se descarta, no se adivina."""
    salida = []
    for m in (marcas if isinstance(marcas, list) else [])[:MAX_MARCAS]:
        if not isinstance(m, dict):
            continue
        forma = m.get("forma") if m.get("forma") in FORMAS else "anillo"
        limpia = {"forma": forma, "texto": _texto(m.get("texto"))}
        objetivo = _texto(m.get("objetivo"), 80)
        x, y = _fraccion(m.get("x")), _fraccion(m.get("y"))
        if objetivo:
            limpia["objetivo"] = objetivo
        elif x is not None and y is not None:
            limpia["x"], limpia["y"] = x, y
        else:
            continue
        salida.append(limpia)
    return salida


def validar_tarjeta(tarjeta):
    """Una tarjeta flotante: título, unas líneas, barras con etiqueta o una serie para una
    línea. None si no trae nada que pintar."""
    if not isinstance(tarjeta, dict):
        return None
    limpia = {"titulo": _texto(tarjeta.get("titulo"), 60)}
    lineas = [_texto(l) for l in (tarjeta.get("lineas") or []) if _texto(l)] \
        if isinstance(tarjeta.get("lineas"), list) else []
    if lineas:
        limpia["lineas"] = lineas[:MAX_LINEAS]
    barras = []
    for b in (tarjeta.get("barras") if isinstance(tarjeta.get("barras"), list) else [])[:MAX_BARRAS]:
        if isinstance(b, dict) and _numero(b.get("valor")) is not None:
            barras.append({"etiqueta": _texto(b.get("etiqueta"), 24), "valor": _numero(b["valor"])})
    if barras:
        limpia["barras"] = barras
    serie = [n for n in (_numero(v) for v in (tarjeta.get("serie") if isinstance(tarjeta.get("serie"), list) else []))
             if n is not None][-MAX_SERIE:]
    if len(serie) >= 2:
        limpia["serie"] = serie
    if not (limpia["titulo"] or lineas or barras or len(serie) >= 2):
        return None
    return limpia


def validar_pasos(pasos) -> list:
    """Los pasos de un tutorial. Cada uno: `texto` (lo que se enseña y se dice), `objetivo`
    (el botón o campo que hay que tocar; vacío = solo explicar) y `tipo`: «clic» espera a
    que lo pulse, «mira» solo enseña y sigue cuando acaba de decirlo."""
    salida = []
    for p in (pasos if isinstance(pasos, list) else [])[:MAX_PASOS]:
        if not isinstance(p, dict):
            continue
        texto = _texto(p.get("texto"))
        if not texto:
            continue
        objetivo = _texto(p.get("objetivo"), 80)
        tipo = p.get("tipo") if p.get("tipo") in TIPOS_PASO else ("clic" if objetivo else "mira")
        salida.append({"texto": texto, "objetivo": objetivo, "tipo": tipo,
                       "ventana": _texto(p.get("ventana"), 80)})
    return salida


def dentro(rect, x: int, y: int, margen: int = MARGEN_CLIC) -> bool:
    return rect[0] - margen <= x <= rect[2] + margen and rect[1] - margen <= y <= rect[3] + margen


def caja_de(rects: list, margen: int = 0):
    """La caja que contiene todos los rectángulos, con margen. None si no hay ninguno."""
    if not rects:
        return None
    return (min(r[0] for r in rects) - margen, min(r[1] for r in rects) - margen,
            max(r[2] for r in rects) + margen, max(r[3] for r in rects) + margen)


def recortar(rect, pantalla):
    """El rectángulo metido dentro de `pantalla` (izq, arriba, der, abajo)."""
    return (max(rect[0], pantalla[0]), max(rect[1], pantalla[1]),
            min(rect[2], pantalla[2]), min(rect[3], pantalla[3]))


def donde_etiqueta(objetivo, ancho: int, alto: int, pantalla, hueco: int = 18) -> tuple:
    """Dónde va la etiqueta de una marca: debajo del objetivo; si no cabe, encima; si
    tampoco, a su derecha. Siempre dentro de la pantalla del objetivo."""
    izq, arr, der, aba = pantalla
    x = min(max(objetivo[0], izq + 8), der - ancho - 8)
    if objetivo[3] + hueco + alto <= aba - 8:
        return x, objetivo[3] + hueco
    if objetivo[1] - hueco - alto >= arr + 8:
        return x, objetivo[1] - hueco - alto
    x = objetivo[2] + hueco
    if x + ancho > der - 8:
        x = max(izq + 8, objetivo[0] - hueco - ancho)
    return x, min(max(objetivo[1], arr + 8), aba - alto - 8)


def se_pisan(a, b) -> bool:
    return a[0] < b[2] and b[0] < a[2] and a[1] < b[3] and b[1] < a[3]


def colocar(objetivo, ancho: int, alto: int, pantalla, ocupados: list, hueco: int = 18) -> tuple:
    """Como `donde_etiqueta`, pero sin tapar nada de `ocupados` (los botones marcados y las
    etiquetas ya puestas): prueba debajo, encima, a la derecha y a la izquierda del
    objetivo, y luego más abajo, y se queda con el primer sitio libre. Si no hay ninguno,
    el de siempre: mejor una etiqueta encima de otra que ninguna."""
    izq, arr, der, aba = pantalla

    def dentro_de_pantalla(x, y):
        return (min(max(x, izq + 8), der - ancho - 8), min(max(y, arr + 8), aba - alto - 8))

    l, t, r, b = objetivo
    candidatos = [(l, b + hueco), (l, t - hueco - alto), (r + hueco, t), (l - hueco - ancho, t),
                  (r + hueco, b + hueco), (l - hueco - ancho, b + hueco)]
    candidatos += [(l, b + hueco + k * (alto + 10)) for k in range(1, 6)]
    for x, y in candidatos:
        x, y = dentro_de_pantalla(x, y)
        caja = (x, y, x + ancho, y + alto)
        if not se_pisan(caja, objetivo) and not any(se_pisan(caja, o) for o in ocupados):
            return x, y
    return donde_etiqueta(objetivo, ancho, alto, pantalla, hueco)


def pantalla_de(punto, pantallas: list):
    """La pantalla (izq, arriba, der, abajo) que contiene `punto`, o la primera."""
    for p in pantallas:
        if p[0] <= punto[0] < p[2] and p[1] <= punto[1] < p[3]:
            return p
    return pantallas[0]


def de_fraccion(x: float, y: float, total) -> tuple:
    """Un punto en fracción de la pantalla entera (todas juntas, como la captura `monitor=0`)
    → píxeles."""
    return (int(total[0] + x * (total[2] - total[0])), int(total[1] + y * (total[3] - total[1])))


class Tutorial:
    """Por qué paso va un tutorial y qué hace avanzar. La ventana (Tk) le cuenta lo que pasa
    —encontrado el botón, un clic en tal sitio, acabó de hablar, pasa el tiempo— y él dice
    si se avanza. Sin reloj propio: el tiempo entra como argumento, para poder probarlo."""

    def __init__(self, titulo: str, pasos: list):
        self.titulo = _texto(titulo, 80)
        self.pasos = pasos
        self.i = 0
        self.rect = None             # dónde está el botón del paso actual (None = no se sabe)
        self.buscando = False
        self.desde = 0.0             # cuándo empezó el paso actual
        self.dicho_en = None         # cuándo acabó de decirse (pasos «mira»)
        self.fin = ""                # "" en marcha; "hecho", "cancelado" o "abandonado"

    @property
    def actual(self):
        return self.pasos[self.i] if not self.fin and self.i < len(self.pasos) else None

    def empezar_paso(self, ahora: float) -> dict:
        self.rect, self.dicho_en, self.desde = None, None, ahora
        self.buscando = bool(self.actual and self.actual["objetivo"])
        return self.actual

    def encontrado(self, rect) -> None:
        self.buscando = False
        self.rect = tuple(rect) if rect else None

    def clic(self, x: int, y: int) -> bool:
        """Un clic soltado en (x, y). True si completa el paso: dentro del botón, o en
        cualquier sitio si el botón no se encontró (ya lo hizo él mirando la etiqueta)."""
        paso = self.actual
        if not paso or paso["tipo"] != "clic" or self.buscando:
            return False
        return self.rect is None or dentro(self.rect, x, y)

    def dicho(self, ahora: float) -> None:
        if self.dicho_en is None:
            self.dicho_en = ahora

    def toca_seguir(self, ahora: float) -> bool:
        """Un paso «mira» sigue 1,5 s después de decirse, y nunca antes de 3 s."""
        paso = self.actual
        return bool(paso and paso["tipo"] == "mira" and self.dicho_en is not None
                    and ahora - self.dicho_en >= 1.5 and ahora - self.desde >= 3)

    def caducado(self, ahora: float) -> bool:
        return bool(self.actual and ahora - self.desde > PASO_MAX_S)

    def avanzar(self) -> None:
        self.i += 1
        if self.i >= len(self.pasos):
            self.fin = "hecho"

    def cancelar(self, motivo: str = "cancelado") -> None:
        self.fin = motivo

    def estado(self) -> dict:
        return {"titulo": self.titulo, "paso": min(self.i + 1, len(self.pasos)),
                "de": len(self.pasos), "fin": self.fin or None}
