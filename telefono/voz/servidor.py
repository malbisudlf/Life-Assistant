"""La voz de Jarvis: síntesis local, en jacobo, para que la llamada no dependa de cuotas.

El oído (telefono/oido/) ya transcribe en casa; esto es la otra mitad. Nace del
2026-10-28, cuando se agotó la cuota del mes de ElevenLabs y todas las llamadas se
cortaban al descolgar (parche 29). La voice-app de `caja` le pide cada frase por la red de
casa y, si jacobo no contesta, sigue con Azure y ElevenLabs. Por qué estos motores y estas
voces, en «La voz en jacobo» de telefono/PARCHES.md.

Dos motores, los dos por ONNX en la CPU (la RX 580 se queda para Whisper):

- **Piper**: voces VITS de una sola persona, muy rápidas. Una voz = un `.onnx` con su
  `.onnx.json` en `/modelos/piper/`.
- **Kokoro** (82M): más natural, pero ~10 veces más lento (2,3 s por frase en caja con
  dos hilos, frente a 0,25 s de Piper). Opcional: solo se carga si la imagen trae
  `kokoro-onnx` y están sus ficheros en `/modelos/kokoro/`. Hoy no va: ver PARCHES.md.

Las voces se llaman `motor:nombre` (`piper:es_ES-davefx-medium`, `kokoro:em_alex`). La
que se usa si la petición no dice otra es `VOZ_POR_DEFECTO`, y elegir voz es cambiar esa
variable (o mandar `voz` en cada petición).

Tres reglas, las del oído:

1. NI TEXTO NI AUDIO EN DISCO, ni en el registro. El registro dice cuántos caracteres y
   cuánto tardó, nunca qué se dijo. Lo único que se guarda es una caché EN MEMORIA de las
   frases fijas (despedidas, «¿sigues ahí?»), que se pierde al reiniciar.
2. NADA QUE ESCUCHE FUERA DE LOCAL SIN CREDENCIAL: con `VOZ_HOST` distinto de 127.0.0.1
   no arranca sin `VOZ_TOKEN`, y el token va en cabecera, nunca en la URL.
3. SI JACOBO NO CONTESTA, JARVIS NO SE QUEDA MUDO: eso lo resuelve la voice-app con sus
   otras voces. Aquí solo hay que fallar deprisa y en claro.

API:

  GET  /salud  → {ok, voces, por_defecto, ocupado}
  POST /decir  → JSON {texto, voz?, velocidad?}
                 → el audio en WAV (PCM 16 bits mono, a la frecuencia de la voz), con X-Voz
                   y X-Ms en la respuesta. WAV y no MP3: FreeSWITCH lo reproduce igual, no
                   hace falta ffmpeg (que eran 450 MB de imagen por el enlace de jacobo, que
                   no los aguanta) y no se paga la codificación.
"""

import asyncio
import hmac
import io
import json
import logging
import os
import sys
import time
import wave
from collections import OrderedDict
from concurrent.futures import ThreadPoolExecutor

import numpy as np
from aiohttp import web

HOST          = os.getenv("VOZ_HOST", "127.0.0.1")
PUERTO        = int(os.getenv("VOZ_PUERTO", "8772"))
TOKEN         = os.getenv("VOZ_TOKEN", "")
MODELOS       = os.getenv("VOZ_MODELOS", "/modelos")
POR_DEFECTO   = os.getenv("VOZ_POR_DEFECTO", "piper:es_ES-davefx-medium")
# Hilos de ONNX por síntesis. jacobo tiene 6 núcleos y el oído usa la GPU, pero sus
# whisper-server también tiran de CPU al preparar el audio: no se los quita todos.
HILOS         = int(os.getenv("VOZ_HILOS", "4"))
# Una frase cada vez: dos a la vez se reparten la CPU y tardan las dos el doble, que en
# una llamada es peor que esperar la cola.
EN_PARALELO   = int(os.getenv("VOZ_EN_PARALELO", "1"))
MAX_CHARS     = int(os.getenv("VOZ_MAX_CHARS", "600"))
CACHE_FRASES  = int(os.getenv("VOZ_CACHE_FRASES", "64"))
CACHE_MAX_CHARS = 80          # solo las cortas: las fijas son cortas, las de Claude no

log = logging.getLogger("voz")


# ── Los motores ─────────────────────────────────────────────────────────────────────

class Piper:
    """Una voz de Piper cargada. Cada `.onnx` es una voz entera."""

    def __init__(self, ruta):
        import onnxruntime
        from piper import PiperVoice
        opciones = onnxruntime.SessionOptions()
        opciones.intra_op_num_threads = HILOS
        opciones.inter_op_num_threads = 1
        self.voz = PiperVoice.load(ruta)
        # PiperVoice no deja pasar las opciones al cargar: se rehace la sesión con ellas
        self.voz.session = onnxruntime.InferenceSession(
            ruta, sess_options=opciones, providers=["CPUExecutionProvider"])
        self.hz = self.voz.config.sample_rate
        # Algunas voces traen varias personas (sharvard: un hombre y una mujer)
        self.hablantes = dict(getattr(self.voz.config, "speaker_id_map", None) or {})

    def sintetiza(self, texto, velocidad, hablante=None):
        from piper import SynthesisConfig
        # length_scale es la duración: más alto, más lento
        config = SynthesisConfig(length_scale=1.0 / velocidad, speaker_id=hablante)
        pcm = b"".join(t.audio_int16_bytes for t in self.voz.synthesize(texto, syn_config=config))
        return pcm, self.hz


class Kokoro:
    """Kokoro-82M: un modelo y muchas voces."""

    def __init__(self, modelo, voces):
        import onnxruntime
        from kokoro_onnx import Kokoro as K
        opciones = onnxruntime.SessionOptions()
        opciones.intra_op_num_threads = HILOS
        opciones.inter_op_num_threads = 1
        sesion = onnxruntime.InferenceSession(
            modelo, sess_options=opciones, providers=["CPUExecutionProvider"])
        self.k = K.from_session(sesion, voces)

    def nombres(self):
        # Solo las españolas: ef_ (mujer) y em_ (hombre)
        return sorted(v for v in self.k.get_voices() if v[:3] in ("ef_", "em_"))

    def sintetiza(self, texto, velocidad, voz):
        muestras, hz = self.k.create(texto, voice=voz, speed=velocidad, lang="es")
        pcm = (np.clip(muestras, -1.0, 1.0) * 32767).astype("<i2").tobytes()
        return pcm, hz


def carga_voces():
    """{nombre: función(texto, velocidad) → (pcm s16le, hz)}"""
    voces = {}
    carpeta = os.path.join(MODELOS, "piper")
    if os.path.isdir(carpeta):
        for f in sorted(os.listdir(carpeta)):
            if f.endswith(".onnx") and os.path.exists(os.path.join(carpeta, f + ".json")):
                try:
                    p = Piper(os.path.join(carpeta, f))
                    if len(p.hablantes) > 1:
                        for nombre, sid in p.hablantes.items():
                            voces[f"piper:{f[:-5]}:{nombre}"] = (
                                lambda p, sid: lambda t, v: p.sintetiza(t, v, sid))(p, sid)
                    else:
                        voces["piper:" + f[:-5]] = p.sintetiza
                except Exception as e:   # una voz rota no tumba las demás
                    log.error("Piper: no se pudo cargar %s (%s)", f, e)
    modelo = os.path.join(MODELOS, "kokoro", "kokoro-v1.0.onnx")
    banco  = os.path.join(MODELOS, "kokoro", "voices-v1.0.bin")
    if os.path.exists(modelo) and os.path.exists(banco):
        try:
            k = Kokoro(modelo, banco)
            for n in k.nombres():
                voces["kokoro:" + n] = (lambda n: lambda t, v: k.sintetiza(t, v, n))(n)
        except Exception as e:
            log.error("Kokoro: no se pudo cargar (%s)", e)
    return voces


# ── El audio ────────────────────────────────────────────────────────────────────────

def a_wav(pcm, hz):
    b = io.BytesIO()
    with wave.open(b, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(hz)
        w.writeframes(pcm)
    return b.getvalue()



# ── HTTP ────────────────────────────────────────────────────────────────────────────

def autorizado(request):
    if not TOKEN:
        return True                      # solo posible en 127.0.0.1 (ver principal)
    dado = request.headers.get("X-Auth-Token", "")
    if not dado and request.headers.get("Authorization", "").startswith("Bearer "):
        dado = request.headers["Authorization"][7:]
    return hmac.compare_digest(dado.encode(), TOKEN.encode())


@web.middleware
async def con_llave(request, handler):
    if not autorizado(request):
        return web.json_response({"error": "sin_credencial"}, status=401)
    return await handler(request)


async def salud(request):
    app = request.app
    return web.json_response({
        "ok": bool(app["voces"]) and POR_DEFECTO in app["voces"],
        "voces": sorted(app["voces"]),
        "por_defecto": POR_DEFECTO,
        "ocupado": app["ocupado"],
    })


async def decir(request):
    app = request.app
    try:
        datos = await request.json()
    except (json.JSONDecodeError, UnicodeDecodeError):
        return web.json_response({"error": "json_no_valido"}, status=400)
    texto = str(datos.get("texto") or "").strip()
    if not texto:
        return web.json_response({"error": "sin_texto"}, status=400)
    if len(texto) > MAX_CHARS:
        return web.json_response({"error": "texto_largo", "max": MAX_CHARS}, status=413)
    voz = str(datos.get("voz") or POR_DEFECTO)
    if voz not in app["voces"]:
        return web.json_response({"error": "voz_desconocida", "voces": sorted(app["voces"])},
                                 status=400)
    try:
        velocidad = min(2.0, max(0.5, float(datos.get("velocidad") or 1.0)))
    except (TypeError, ValueError):
        return web.json_response({"error": "velocidad_no_valida"}, status=400)

    inicio = time.monotonic()
    clave = (voz, velocidad, texto)
    audio = app["cache"].get(clave)
    if audio is not None:
        app["cache"].move_to_end(clave)
    else:
        async with app["turno"]:
            app["ocupado"] += 1
            try:
                pcm, hz = await asyncio.get_running_loop().run_in_executor(
                    app["hilos"], app["voces"][voz], texto, velocidad)
            except Exception as e:
                log.error("decir: %s falló con %d caracteres (%s)", voz, len(texto), e)
                return web.json_response({"error": "no_ha_salido"}, status=500)
            finally:
                app["ocupado"] -= 1
        audio = a_wav(pcm, hz)
        if len(texto) <= CACHE_MAX_CHARS and CACHE_FRASES > 0:
            app["cache"][clave] = audio
            while len(app["cache"]) > CACHE_FRASES:
                app["cache"].popitem(last=False)
    ms = int((time.monotonic() - inicio) * 1000)
    log.info("decir: %s, %d caracteres en %d ms", voz, len(texto), ms)
    return web.Response(body=audio, content_type="audio/wav",
                        headers={"X-Voz": voz, "X-Ms": str(ms)})


async def al_arrancar(app):
    inicio = time.monotonic()
    app["voces"] = await asyncio.get_running_loop().run_in_executor(app["hilos"], carga_voces)
    log.info("voces cargadas en %.1f s: %s", time.monotonic() - inicio, ", ".join(sorted(app["voces"])))
    if POR_DEFECTO not in app["voces"]:
        log.error("la voz por defecto %s no está cargada", POR_DEFECTO)
    # La primera síntesis de cada motor es lenta (ONNX prepara sus núcleos): se paga aquí
    # y no en la primera frase de una llamada.
    for voz in {POR_DEFECTO} & set(app["voces"]):
        await asyncio.get_running_loop().run_in_executor(app["hilos"], app["voces"][voz],
                                                         "Hola.", 1.0)


def crea_app():
    app = web.Application(middlewares=[con_llave], client_max_size=64 * 1024)
    app["voces"]   = {}
    app["cache"]   = OrderedDict()
    app["ocupado"] = 0
    app["turno"]   = asyncio.Semaphore(EN_PARALELO)
    app["hilos"]   = ThreadPoolExecutor(max_workers=max(1, EN_PARALELO))
    app.router.add_get("/salud", salud)
    app.router.add_post("/decir", decir)
    app.on_startup.append(al_arrancar)
    return app


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, stream=sys.stdout,
                        format="%(asctime)s %(levelname)s %(message)s")
    if HOST not in ("127.0.0.1", "localhost") and not TOKEN:
        sys.exit("VOZ_TOKEN es obligatorio si VOZ_HOST no es 127.0.0.1")
    web.run_app(crea_app(), host=HOST, port=PUERTO, print=None)
