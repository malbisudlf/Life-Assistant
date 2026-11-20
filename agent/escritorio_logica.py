"""La lógica pura del Jarvis de escritorio (`escritorio.py`): sin ventanas, audio ni red.

Aparte para poder probarla en CI (Linux, sin pantalla): `tests/backend/test_escritorio.py`.
Tres piezas:

- `Tecla`: cuándo una pulsación de Ctrl + Alt izquierdos es «quiero hablar». La derecha
  (AltGr) es Ctrl + Alt para Windows, y con ella se escriben la @ y el #: si contara,
  Jarvis se despertaría cada vez que escribe un correo. Y si mientras se mantiene se pulsa
  cualquier otra tecla, era un atajo (Ctrl + Alt + Supr), no una orden: se cancela.
- `LectorSSE`: los eventos de `/jarvis/voz` según llegan, en trozos de bytes cualesquiera.
- `Frases`: de los trozos de texto del modelo a frases enteras que se pueden mandar a la
  voz una a una (así empieza a hablar antes de que acabe de escribir), sin markdown.
"""

import json
import re

# Lo que dura como mínimo una pulsación para contar como orden. Por debajo era un roce o
# un atajo que se soltó rápido.
MANTENER_S = 0.25

_FIN_FRASE = re.compile(r"(?<=[.!?…:;])\s+|\n+")
_MIN_FRASE = 18


class Tecla:
    """Máquina de estados de la tecla de hablar. `paso()` se llama ~30 veces por segundo con
    lo que está pulsado y devuelve un evento o None:

      "empieza"  → abrir el micrófono (ya, para no comerse la primera sílaba)
      "habla"    → ya cuenta como orden (pasó MANTENER_S): mandar lo grabado
      "suelta"   → fin de la orden: transcribir
      "cancela"  → era un roce o un atajo: tirar lo grabado
    """

    def __init__(self, mantener_s: float = MANTENER_S):
        self.mantener_s = mantener_s
        self.desde = None          # cuándo empezó la pulsación
        self.confirmada = False
        self.anulada = False

    def paso(self, ctrl: bool, alt_izq: bool, altgr: bool, otra: bool, ahora: float):
        acorde = ctrl and alt_izq and not altgr
        if self.desde is None:
            if acorde and not otra:
                self.desde, self.confirmada, self.anulada = ahora, False, False
                return "empieza"
            return None
        if self.anulada:
            if not (ctrl or alt_izq):
                self.desde = None          # hasta soltar del todo no se vuelve a armar
            return None
        if otra or altgr:
            self.anulada = True
            return "cancela"
        if not acorde:
            confirmada, self.desde = self.confirmada, None
            return "suelta" if confirmada else "cancela"
        if not self.confirmada and ahora - self.desde >= self.mantener_s:
            self.confirmada = True
            return "habla"
        return None


class LectorSSE:
    """Server-Sent Events a (tipo, datos). Aguanta trozos partidos por cualquier sitio."""

    def __init__(self):
        self._resto = ""

    def trozo(self, datos: bytes) -> list:
        self._resto += datos.decode("utf-8", errors="replace").replace("\r\n", "\n")
        eventos = []
        while "\n\n" in self._resto:
            bloque, self._resto = self._resto.split("\n\n", 1)
            tipo, lineas = "message", []
            for linea in bloque.split("\n"):
                if linea.startswith("event:"):
                    tipo = linea[6:].strip()
                elif linea.startswith("data:"):
                    lineas.append(linea[5:].lstrip())
            if not lineas:
                continue
            try:
                eventos.append((tipo, json.loads("\n".join(lineas))))
            except ValueError:
                continue
        return eventos


def para_voz(texto: str) -> str:
    """Lo que se dice no lleva markdown ni enlaces: se oirían los asteriscos."""
    t = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", texto or "")
    t = re.sub(r"https?://\S+", "", t)
    t = re.sub(r"[*_`#>]+", "", t)
    return " ".join(t.split())


class Frases:
    """Junta los trozos del modelo y suelta frases enteras. Una frase muy corta («Sí.») se
    espera a la siguiente: una petición de voz por cada dos palabras se oye a saltos."""

    def __init__(self):
        self._buffer = ""

    def mete(self, delta: str) -> list:
        self._buffer += delta or ""
        partes = _FIN_FRASE.split(self._buffer)
        if len(partes) < 2:
            return []
        listas, actual = [], ""
        for p in partes[:-1]:
            actual = f"{actual} {p}".strip()
            if len(actual) >= _MIN_FRASE:
                listas.append(para_voz(actual))
                actual = ""
        self._buffer = f"{actual} {partes[-1]}".strip() if actual else partes[-1]
        return [f for f in listas if f]

    def resto(self) -> list:
        final, self._buffer = para_voz(self._buffer), ""
        return [final] if final else []


def recorta_historial(historial: list, maximo: int = 12) -> list:
    """Los últimos turnos, en la forma de `JarvisTurno`, para que el siguiente se entienda
    («¿y mañana?»). En memoria: al cerrar el programa se olvida, como el chat."""
    limpio = [{"rol": t["rol"], "texto": str(t["texto"])[:2000]} for t in historial
              if isinstance(t, dict) and t.get("rol") in ("user", "assistant") and t.get("texto")]
    return limpio[-maximo:]
