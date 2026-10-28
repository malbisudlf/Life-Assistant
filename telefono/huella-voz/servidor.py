"""La huella de voz de Mikel: ¿es él quien acaba de decir «Jarvis»?

Corre en «jacobo» desde el 2026-10-28, en su propio contenedor junto al oído (y no dentro
de él: así no se toca el servicio que ya transcribe las llamadas). La voice-app aún no lo
llama: eso es el parche 23, en «El parche 23» de telefono/PARCHES.md. Modelo: el ERes2Net
de 3D-Speaker (VoxCeleb), el mejor del banco (banco.py), restando la media del canal.

Parche 23 de claude-phone (ver telefono/PARCHES.md). En el modo coche la llamada está
abierta todo el viaje y Jarvis se despierta al oír su nombre; sin esto, también lo
despierta un pasajero o la radio. La voice-app (Node) le manda aquí el audio de la frase
que trae el nombre y este servicio contesta si es su voz: un embedding del locutor con un
modelo ONNX que corre en CPU (sherpa-onnx) y el coseno contra la huella guardada.

Por qué un servicio aparte y no dentro de la voice-app: el modelo y su runtime son
Python/C++, la voice-app es Node, y así se puede mover a otra máquina (con una GPU, junto
a un Whisper local) cambiando una URL. Para eso está `HUELLA_TOKEN`: fuera de
127.0.0.1 no arranca sin él.

Tres reglas:

1. NI AUDIO NI TEXTO EN DISCO. Lo único que se guarda es la huella (un vector) y sus
   números. El registro dice cuánto duró la frase y cuánto se parecía, nunca qué se dijo
   (aquí no llega el texto) ni el audio.
2. LA HUELLA SE GRABA POR LA LÍNEA. El canal cambia la huella mucho más que el ruido: el
   3CX negocia G.711 (8 kHz, 300-3.400 Hz), y una huella grabada con el micro del PC y
   comparada con la voz del teléfono se parece a la de otra persona. Por eso el alta es
   hablando por teléfono («Jarvis, aprende mi voz») y no subiendo un fichero.
3. UNA HUELLA ES DE UN MODELO Y DE UNA MEDIA. Si se cambia `HUELLA_MODELO` o
   `HUELLA_MEDIA`, la huella guardada no vale (sus vectores no se pueden comparar con los
   nuevos) y se contesta `sin_huella` hasta grabar otra: la voice-app hace entonces lo que
   diga `HUELLA_VOZ_SI_FALLA`.

La media del canal: el G.711 empuja todas las huellas hacia un mismo sitio, y restarle a
cada vector la media de muchas voces por ese canal antes del coseno lo compensa (en el
banco, el error del ERes2Net en coche baja del 4,1 % al 2,5 %). `HUELLA_MEDIA` es esa
media, un .npy que deja banco.py; sin ella el coseno es a pelo y el umbral de 0,40 ya no
sirve, por eso si se nombra y no está, no arranca. `HUELLA_MEDIA=` (vacía) la quita.

API (cuerpo: PCM s16le, 16 kHz, mono, que es lo que da el audio fork de FreeSWITCH):

  GET  /salud      → {ok, modelo, umbral, huella: {frases, segundos, fecha} | null}
  POST /verificar  → {es_el, similitud, umbral, segundos}
                     409 sin_huella · 400 poco_audio / audio_impar · 413 demasiado_audio
  POST /alta       → cabecera X-Frases con los bytes de cada frase, separados por comas;
                     el cuerpo, todas seguidas. {ok, frases, descartadas, segundos,
                     consistencia}, o 422 poca_voz. La huella anterior queda en
                     huella.anterior.json.
"""

import hashlib
import hmac
import io
import json
import logging
import os
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import numpy as np

HOST    = os.getenv("HUELLA_HOST", "127.0.0.1")
PUERTO  = int(os.getenv("HUELLA_PUERTO", "3020"))
MODELO  = os.getenv("HUELLA_MODELO", "/modelo/huella.onnx")
MEDIA   = os.getenv("HUELLA_MEDIA", "/modelo/media.npy")
DATOS   = os.getenv("HUELLA_DATOS", "/datos")
TOKEN   = os.getenv("HUELLA_TOKEN", "")
HILOS   = int(os.getenv("HUELLA_HILOS", "2"))
# El umbral depende del modelo, de la media y del canal. El de por defecto sale del banco
# de LibriSpeech por un G.711 simulado restando la media: 0,40 deja pasar un 1 % de voces
# ajenas (ver «El parche 23» en telefono/PARCHES.md). El bueno sale de las llamadas de
# verdad desde el coche, con la voice-app en HUELLA_VOZ_MODO=medir.
UMBRAL  = float(os.getenv("HUELLA_UMBRAL", "0.40"))

MUESTRAS_SEG       = 16000
BYTES_SEG          = MUESTRAS_SEG * 2
VERIFICAR_MIN_SEG  = 0.5      # por debajo, el embedding es ruido
VERIFICAR_MAX_SEG  = 30       # el turno más largo de la voice-app son 25 s (parche 10)
ALTA_MAX_SEG       = 180
ALTA_MIN_SEG       = float(os.getenv("HUELLA_ALTA_MIN_SEG", "15"))
ALTA_MIN_FRASES    = 3
# Una frase del alta que no se parece al resto (la radio, alguien que habló encima) se
# descarta en vez de ensuciar la huella. Bajo a propósito: solo lo claramente ajeno.
ALTA_DESCARTE      = float(os.getenv("HUELLA_ALTA_DESCARTE", "0.25"))

log = logging.getLogger("huella")


class Extractor:
    """El modelo: audio → vector unitario. Un cerrojo porque se llama desde varios hilos."""

    def __init__(self, ruta, hilos=HILOS):
        import sherpa_onnx
        self.nombre = os.path.basename(ruta)
        self._ex = sherpa_onnx.SpeakerEmbeddingExtractor(
            sherpa_onnx.SpeakerEmbeddingExtractorConfig(model=ruta, num_threads=hilos))
        self._cerrojo = threading.Lock()

    def vector(self, muestras):
        with self._cerrojo:
            s = self._ex.create_stream()
            s.accept_waveform(MUESTRAS_SEG, muestras)
            s.input_finished()
            v = np.array(self._ex.compute(s), dtype=np.float32)
        return unitario(v)


class ConMedia:
    """Un extractor que le resta a cada vector la media del canal (ver arriba).

    Igual que en banco.py: el vector unitario del modelo, menos la media, y otra vez a
    unitario. `id` va en la huella guardada: con otra media, la huella no vale.
    """

    def __init__(self, extractor, media, id_media):
        self._ex = extractor
        self.media = np.asarray(media, dtype=np.float32)
        self.nombre = extractor.nombre
        self.id = "%s+%s" % (extractor.nombre, id_media)

    def vector(self, muestras):
        return unitario(self._ex.vector(muestras) - self.media)


def leer_media(ruta):
    """(vector, id) de la media del canal, o (None, None) si HUELLA_MEDIA va vacía."""
    if not ruta:
        return None, None
    if not os.path.exists(ruta):
        raise RuntimeError("HUELLA_MEDIA=%s no existe: sin ella el umbral no sirve "
                           "(HUELLA_MEDIA= vacía para el coseno a pelo)" % ruta)
    with open(ruta, "rb") as f:
        datos = f.read()
    return np.load(io.BytesIO(datos)), "media-" + hashlib.sha256(datos).hexdigest()[:12]


def unitario(v):
    n = float(np.linalg.norm(v))
    return v / n if n > 0 else v


def pcm_a_muestras(datos):
    return np.frombuffer(datos, dtype="<i2").astype(np.float32) / 32768.0


def partir_frases(cuerpo, cabecera):
    """Las frases del alta: X-Frases trae los bytes de cada una. None si no cuadra."""
    try:
        largos = [int(x) for x in str(cabecera or "").split(",") if x.strip()]
    except ValueError:
        return None
    if not largos or any(n <= 0 or n % 2 for n in largos) or sum(largos) != len(cuerpo):
        return None
    frases, i = [], 0
    for n in largos:
        frases.append(cuerpo[i:i + n])
        i += n
    return frases


def calcular_huella(vectores, segundos):
    """De los vectores de cada frase, la huella: la media de los que se parecen entre sí.

    Cada frase se compara con la media de las DEMÁS (si no, cada una tira de la media
    hacia sí misma y nunca parece ajena). Devuelve (huella, info) o (None, info).
    """
    V = np.array(vectores)
    usadas = list(range(len(V)))
    if len(V) >= ALTA_MIN_FRASES:
        total = V.sum(axis=0)
        parecidos = [float(unitario(total - V[i]) @ V[i]) for i in range(len(V))]
        usadas = [i for i, p in enumerate(parecidos) if p >= ALTA_DESCARTE]
    segs = sum(segundos[i] for i in usadas)
    info = {"frases": len(usadas), "descartadas": len(V) - len(usadas), "segundos": round(segs, 1)}
    if len(usadas) < ALTA_MIN_FRASES or segs < ALTA_MIN_SEG:
        info["motivo"] = "poca_voz"
        return None, info
    huella = unitario(V[usadas].mean(axis=0))
    info["consistencia"] = round(float(np.mean(V[usadas] @ huella)), 3)
    return huella, info


class Almacen:
    """La huella en disco: huella.json, y la anterior al lado para poder volver."""

    def __init__(self, directorio, modelo):
        self.ruta = os.path.join(directorio, "huella.json")
        self.anterior = os.path.join(directorio, "huella.anterior.json")
        self.modelo = modelo
        self._cerrojo = threading.Lock()
        self._huella = None
        self._info = None
        self._leer()

    def _leer(self):
        try:
            with open(self.ruta, encoding="utf-8") as f:
                d = json.load(f)
        except FileNotFoundError:
            return
        except (OSError, ValueError) as e:
            log.error("huella.json ilegible (%s): sin huella hasta grabar otra", e)
            return
        if d.get("modelo") != self.modelo:
            log.warning("la huella es del modelo %s y el de ahora es %s: hay que grabarla otra vez",
                        d.get("modelo"), self.modelo)
            return
        self._huella = unitario(np.array(d["vector"], dtype=np.float32))
        self._info = {k: d.get(k) for k in ("frases", "segundos", "fecha", "consistencia")}

    def huella(self):
        with self._cerrojo:
            return self._huella

    def info(self):
        with self._cerrojo:
            return dict(self._info) if self._info else None

    def guardar(self, huella, info):
        d = dict(info, modelo=self.modelo, fecha=time.strftime("%Y-%m-%dT%H:%M:%S%z"),
                 vector=[round(float(x), 6) for x in huella])
        tmp = self.ruta + ".tmp"
        with self._cerrojo:
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(d, f)
            if os.path.exists(self.ruta):
                os.replace(self.ruta, self.anterior)
            os.replace(tmp, self.ruta)
            self._huella = unitario(np.array(d["vector"], dtype=np.float32))
            self._info = {k: d.get(k) for k in ("frases", "segundos", "fecha", "consistencia")}


class Huella:
    """Lo que hace el servicio, sin HTTP: así se prueba con un extractor de mentira."""

    def __init__(self, extractor, almacen, umbral=UMBRAL):
        self.ex = extractor
        self.almacen = almacen
        self.umbral = umbral

    def salud(self):
        return 200, {"ok": True, "modelo": self.ex.nombre, "umbral": self.umbral,
                     "huella": self.almacen.info()}

    def verificar(self, pcm):
        if len(pcm) % 2:
            return 400, {"motivo": "audio_impar"}
        segundos = len(pcm) / BYTES_SEG
        if segundos < VERIFICAR_MIN_SEG:
            return 400, {"motivo": "poco_audio", "segundos": round(segundos, 2)}
        huella = self.almacen.huella()
        if huella is None:
            return 409, {"motivo": "sin_huella"}
        t0 = time.monotonic()
        similitud = float(self.ex.vector(pcm_a_muestras(pcm)) @ huella)
        es_el = similitud >= self.umbral
        log.info("verificar %.1f s → %.2f (umbral %.2f) %s, %.0f ms", segundos, similitud,
                 self.umbral, "sí" if es_el else "NO", (time.monotonic() - t0) * 1000)
        return 200, {"es_el": es_el, "similitud": round(similitud, 3), "umbral": self.umbral,
                     "segundos": round(segundos, 2)}

    def alta(self, cuerpo, cabecera):
        frases = partir_frases(cuerpo, cabecera)
        if frases is None:
            return 400, {"motivo": "frases_mal_contadas"}
        frases = [f for f in frases if len(f) / BYTES_SEG >= VERIFICAR_MIN_SEG]
        vectores = [self.ex.vector(pcm_a_muestras(f)) for f in frases]
        segundos = [len(f) / BYTES_SEG for f in frases]
        if not vectores:
            return 422, {"motivo": "poca_voz", "frases": 0, "descartadas": 0, "segundos": 0}
        huella, info = calcular_huella(vectores, segundos)
        if huella is None:
            log.info("alta rechazada: %s", info)
            return 422, info
        self.almacen.guardar(huella, info)
        log.info("huella nueva: %s", info)
        return 200, dict(info, ok=True)


def manejador(servicio, token=TOKEN):
    class Manejador(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def log_message(self, *a):          # el registro propio ya dice lo que importa
            pass

        def _responder(self, codigo, cuerpo):
            datos = json.dumps(cuerpo, ensure_ascii=False).encode()
            self.send_response(codigo)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(datos)))
            self.end_headers()
            self.wfile.write(datos)

        def _llave(self):
            if not token:
                return True
            return hmac.compare_digest(self.headers.get("X-Auth-Token", "").encode(), token.encode())

        def _cuerpo(self, maximo):
            # Content-Length obligatorio y acotado: nada de leer lo que mande el cliente.
            try:
                n = int(self.headers.get("Content-Length", ""))
            except ValueError:
                return None, (411, {"motivo": "sin_content_length"})
            if n < 0 or n > maximo:
                return None, (413, {"motivo": "demasiado_audio"})
            return self.rfile.read(n), None

        def do_GET(self):
            if not self._llave():
                return self._responder(401, {"motivo": "sin_llave"})
            if self.path == "/salud":
                return self._responder(*servicio.salud())
            self._responder(404, {"motivo": "no_existe"})

        def do_POST(self):
            if not self._llave():
                self.close_connection = True
                return self._responder(401, {"motivo": "sin_llave"})
            if self.path not in ("/verificar", "/alta"):
                self.close_connection = True
                return self._responder(404, {"motivo": "no_existe"})
            maximo = (VERIFICAR_MAX_SEG if self.path == "/verificar" else ALTA_MAX_SEG) * BYTES_SEG
            cuerpo, error = self._cuerpo(maximo)
            if error:
                self.close_connection = True
                return self._responder(*error)
            try:
                if self.path == "/verificar":
                    r = servicio.verificar(cuerpo)
                else:
                    r = servicio.alta(cuerpo, self.headers.get("X-Frases"))
            except Exception:
                log.exception("fallo en %s", self.path)
                r = (500, {"motivo": "fallo_interno"})
            self._responder(*r)

    return Manejador


def comprobar_arranque(host, token):
    """Fuera de 127.0.0.1, sin llave no: cualquiera de la red podría grabar su huella."""
    if host not in ("127.0.0.1", "::1", "localhost") and not token:
        raise RuntimeError("HUELLA_HOST=%s sin HUELLA_TOKEN: fuera de local hace falta llave" % host)


def main():
    logging.basicConfig(level=logging.INFO, stream=sys.stdout,
                        format="%(asctime)s %(levelname)s %(message)s")
    comprobar_arranque(HOST, TOKEN)
    media, id_media = leer_media(MEDIA)
    ex = Extractor(MODELO)
    clave = ex.nombre
    if media is not None:
        ex = ConMedia(ex, media, id_media)
        clave = ex.id
    os.makedirs(DATOS, exist_ok=True)
    servicio = Huella(ex, Almacen(DATOS, clave))
    servidor = ThreadingHTTPServer((HOST, PUERTO), manejador(servicio))
    log.info("huella de voz en %s:%d, modelo %s, %s, umbral %.2f, %s", HOST, PUERTO, ex.nombre,
             id_media or "SIN media del canal", UMBRAL,
             "con huella" if servicio.almacen.huella() is not None else "SIN huella todavía")
    servidor.serve_forever()


if __name__ == "__main__":
    main()
