"""La lógica pura del oído: sin red, sin modelos y sin dependencias, para poder probarla.

Whisper no es de flujo: transcribe un trozo entero cada vez. Para dar texto mientras se
habla, el servidor vuelve a transcribir la frase en curso cada medio segundo, y aquí se
decide qué parte de lo transcrito ya no va a cambiar: lo que coincide en dos pasadas
seguidas (*LocalAgreement*, de whisper_streaming). Lo fijo no se desdice nunca; lo demás
es provisional y puede cambiar en la siguiente pasada.
"""

import math
import re
import unicodedata

# Cómo transcribe Whisper «Jarvis» por un G.711 cuando no lo entiende del todo. Sin tildes:
# se comparan ya normalizadas. «Arvis» es como lo parte `small` (el de los parciales):
# «Y Arvis, ¿qué tiempo…», «ya, Arvis, pon la radio»; medido en jacobo, y no es palabra
# española con la que pueda confundirse.
NOMBRES = ("jarvis", "yarvis", "jarbis", "yarbis", "harvis", "charvis", "jervis",
           "arvis", "arbis")

# Lo que Whisper escribe sobre silencio o ruido: viene de los subtítulos con los que se
# entrenó. Una pasada que solo dice esto no ha oído nada. «Gracias» a secas NO está,
# aunque también lo alucina: es lo que se le dice a Jarvis al acabar. Contra eso está el
# umbral de silencio del servidor, que no le deja transcribir lo que no suena.
ALUCINACIONES = (
    "subtitulos realizados por la comunidad de amara org",
    "subtitulado por la comunidad de amara org",
    "gracias por ver el video",
    "gracias por ver",
    "suscribete al canal",
)


def normaliza(texto):
    """Minúsculas, sin tildes ni signos: para comparar palabras, nunca para enseñarlas."""
    t = unicodedata.normalize("NFD", texto.lower())
    t = "".join(c for c in t if unicodedata.category(c) != "Mn")
    t = re.sub(r"[^\w\s]", " ", t)
    return re.sub(r"\s+", " ", t).strip()


def limpia(texto):
    """Quita las acotaciones de subtítulo («[MÚSICA]», «(risas)»): Whisper las escribe al
    principio de una frase con ruido de fondo, y nadie las ha dicho."""
    t = re.sub(r"\[[^\]]*\]|\([^)]*\)", " ", texto)
    return re.sub(r"\s+", " ", t).strip()


def es_alucinacion(texto):
    n = normaliza(texto)
    return not n or n in ALUCINACIONES or "amara org" in n


def dice_nombre(texto, nombres=NOMBRES):
    return any(p in nombres for p in normaliza(texto).split())


def rms(pcm16):
    """Energía media de PCM s16le, en la misma escala que las muestras (0-32768)."""
    n = len(pcm16) // 2
    if not n:
        return 0.0
    total = 0
    for i in range(0, n * 2, 2):
        m = int.from_bytes(pcm16[i:i + 2], "little", signed=True)
        total += m * m
    return math.sqrt(total / n)


def wav_de_pcm16(pcm16, hz):
    """Cabecera WAV a mano (44 bytes conocidos), como `_wav_de_pcm16` del backend."""
    n = len(pcm16)
    return (b"RIFF" + (36 + n).to_bytes(4, "little") + b"WAVEfmt "
            + (16).to_bytes(4, "little") + (1).to_bytes(2, "little")
            + (1).to_bytes(2, "little") + hz.to_bytes(4, "little")
            + (hz * 2).to_bytes(4, "little") + (2).to_bytes(2, "little")
            + (16).to_bytes(2, "little") + b"data" + n.to_bytes(4, "little") + pcm16)


class Acuerdo:
    """Lo fijo y lo provisional de una frase que se transcribe una y otra vez entera."""

    def __init__(self):
        self.fijo     = []      # palabras tal como las escribió Whisper
        self.anterior = []      # la pasada anterior, normalizada

    def pasada(self, texto):
        """Una transcripción nueva de la frase entera. Devuelve (fijo, provisional)."""
        palabras = texto.split()
        normal   = [normaliza(p) for p in palabras]
        comun = 0
        for a, b in zip(self.anterior, normal):
            if a != b:
                break
            comun += 1
        # Lo fijo solo crece: si Whisper cambia de opinión sobre algo ya fijado, se queda
        # lo fijado. Desdecirse de un texto que el cliente ya ha podido usar es peor que un
        # error en una palabra.
        if comun > len(self.fijo):
            self.fijo = palabras[:comun]
        self.anterior = normal
        return " ".join(self.fijo), " ".join(palabras[len(self.fijo):])

    def reinicia(self):
        self.fijo, self.anterior = [], []
