"""El oído de Jarvis: transcripción local, en jacobo, mientras se habla.

Sustituye a whisper-1 de OpenAI en el teléfono (y después en el backend). Corre en jacobo
(la RX 580, por Vulkan) y la voice-app de `caja` le habla por la red de casa. Por qué
aquí y con estos modelos, en «Whisper medido en jacobo» de telefono/PARCHES.md.

Dos modelos cargados a la vez, cada uno en su whisper-server de whisper.cpp:

- el RÁPIDO (`small`, ~0,3 s por pasada) vuelve a transcribir la frase en curso cada
  `OIDO_PASO_SEG` y da el texto parcial, que es de donde sale si se ha dicho «Jarvis»;
- el FINAL (`large-v3-turbo`, ~1,1 s) transcribe la frase una sola vez, cuando el cliente
  dice que ha acabado. El fin de frase lo sigue decidiendo la voice-app (parches 5, 10 y
  17): aquí no se adivina.

Tres reglas:

1. NI AUDIO NI TEXTO EN DISCO, ni en el registro. El audio vive en memoria lo que dura la
   frase; el registro dice cuánto duró y cuánto tardó, nunca qué se dijo. La conversión de
   `/transcribir` va por tuberías, no por ficheros temporales.
2. NADA QUE ESCUCHE FUERA DE LOCAL SIN CREDENCIAL (la regla del parche 21): con
   `OIDO_HOST` distinto de 127.0.0.1 no arranca sin `OIDO_TOKEN`. El token va en
   cabecera (`X-Auth-Token` o `Authorization: Bearer`), nunca en la URL.
3. SI JACOBO NO CONTESTA, JARVIS NO SE QUEDA SORDO. Eso no se resuelve aquí sino en los
   clientes: vuelven a OpenAI. Este servicio solo tiene que fallar deprisa y en claro.

API:

  GET  /salud        → {ok, gpu, modelos: {rapido, final}, sesiones}
  POST /transcribir  → cualquier audio en el cuerpo (WAV, OGG de Telegram…; lo convierte
                       ffmpeg). Cabeceras opcionales X-Idioma (es) y X-Modelo
                       (final | rapido). {texto, segundos, ms}
  WS   /escucha?hz=8000|16000&idioma=es
       cliente → binario: PCM s16le mono, al ritmo al que llega (trozos de 20 ms)
                 texto:   {"tipo": "fin"}      la frase ha acabado: transcripción final
                          {"tipo": "reinicia"} tira lo oído sin transcribirlo
       servidor → {"tipo": "parcial", "fijo", "provisional", "nombre", "ms"}
                  {"tipo": "final", "texto", "nombre", "segundos", "ms"}
                  {"tipo": "error", "detalle"}
       `nombre` del parcial es "fijo", "provisional" o null: dónde se ha oído «Jarvis».
       Lo fijo ya no cambia (ver acuerdo.py); lo provisional puede cambiar en la siguiente
       pasada.
"""

import asyncio
import hmac
import json
import logging
import os
import sys
import time

from aiohttp import ClientSession, ClientTimeout, FormData, WSMsgType, web

from acuerdo import Acuerdo, dice_nombre, es_alucinacion, limpia, rms, wav_de_pcm16

HOST            = os.getenv("OIDO_HOST", "127.0.0.1")
PUERTO          = int(os.getenv("OIDO_PUERTO", "8770"))
TOKEN           = os.getenv("OIDO_TOKEN", "")
WHISPER         = os.getenv("OIDO_WHISPER", "/opt/whisper/whisper-server")
MODELO_RAPIDO   = os.getenv("OIDO_MODELO_RAPIDO", "/modelos/ggml-small.bin")
MODELO_FINAL    = os.getenv("OIDO_MODELO_FINAL", "/modelos/ggml-large-v3-turbo-q5_0.bin")
HILOS           = os.getenv("OIDO_HILOS", "6")
PASO_SEG        = float(os.getenv("OIDO_PASO_SEG", "0.5"))
# Por debajo de esta energía no hay voz y no se transcribe: Whisper sobre silencio se
# inventa subtítulos (ver ALUCINACIONES en acuerdo.py). La voz por el G.711 anda por los
# miles; el silencio de la línea, por las decenas.
SILENCIO_RMS    = float(os.getenv("OIDO_SILENCIO_RMS", "150"))
MAX_SESIONES    = int(os.getenv("OIDO_MAX_SESIONES", "4"))
MAX_SUBIDA      = 25 * 1024 * 1024        # lo mismo que acepta OpenAI
VENTANA_MAX_SEG = 28                      # Whisper no ve más de 30 s de una vez
MIN_SEG         = 0.5

# Los dos whisper-server, solo en local dentro del contenedor
INTERNOS = {"rapido": (8091, MODELO_RAPIDO), "final": (8090, MODELO_FINAL)}

log = logging.getLogger("oido")
estado = {"gpu": False, "sesiones": 0}


# ── Los whisper-server ──────────────────────────────────────────────────────────────

async def arranca_whisper(app, nombre, puerto, modelo):
    """Lo arranca y espera a que conteste. Que está listo se pregunta por HTTP y no se lee
    de su salida: el «server listening» va por stdout, que en una tubería se queda en el
    búfer y no llega nunca (así estuvo el primer arranque, esperando para siempre)."""
    # Sin la llave en su entorno: whisper-server no la necesita
    entorno = {k: v for k, v in os.environ.items() if k != "OIDO_TOKEN"}
    proc = await asyncio.create_subprocess_exec(
        WHISPER, "-t", HILOS, "-m", modelo, "--host", "127.0.0.1", "--port", str(puerto),
        stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.PIPE, env=entorno)
    vista = {"gpu": False}
    asyncio.create_task(vigila(nombre, proc, vista))
    for _ in range(600):                  # 5 min: el primer arranque compila los sombreadores
        if proc.returncode is not None:
            log.error("whisper-server %s murió al arrancar (modelo %s)", nombre, modelo)
            sys.exit(1)
        try:
            async with app["http"].get(f"http://127.0.0.1:{puerto}/") as r:
                if r.status == 200:
                    break
        except OSError:
            pass
        await asyncio.sleep(0.5)
    else:
        log.error("whisper-server %s no contesta tras 5 min", nombre)
        sys.exit(1)
    log.info("whisper-server %s listo: %s, %s", nombre, os.path.basename(modelo),
             "GPU" if vista["gpu"] else "SOLO CPU")
    return vista["gpu"]


async def vigila(nombre, proc, vista):
    """Lee su stderr (lo de Vulkan va por ahí, sin búfer) para saber si usa la GPU, lo vacía
    para que la tubería no se llene y lo bloquee, y tumba el servicio si muere: que Docker
    lo levante entero es mejor que seguir medio sordo."""
    while linea := await proc.stderr.readline():
        if b"using Vulkan0 backend" in linea:
            vista["gpu"] = True
    await proc.wait()
    log.error("whisper-server %s se ha parado (código %s): salgo", nombre, proc.returncode)
    os._exit(1)


async def whisper(app, modelo, wav, idioma="es"):
    puerto = INTERNOS[modelo][0]
    datos = FormData()
    datos.add_field("file", wav, filename="audio.wav", content_type="audio/wav")
    datos.add_field("language", idioma)
    datos.add_field("response_format", "json")
    datos.add_field("temperature", "0")
    async with app["http"].post(f"http://127.0.0.1:{puerto}/inference", data=datos) as r:
        r.raise_for_status()
        texto = limpia((await r.json()).get("text", ""))
    return "" if es_alucinacion(texto) else texto


# ── Credencial ──────────────────────────────────────────────────────────────────────

def autorizado(request):
    if not TOKEN:
        return True                       # solo se llega aquí escuchando en local
    dado = request.headers.get("X-Auth-Token", "")
    auth = request.headers.get("Authorization", "")
    if not dado and auth.lower().startswith("bearer "):
        dado = auth[7:].strip()
    return hmac.compare_digest(dado.encode(), TOKEN.encode())


@web.middleware
async def con_llave(request, handler):
    if not autorizado(request):
        return web.json_response({"error": "sin_credencial"}, status=401)
    return await handler(request)


# ── HTTP ────────────────────────────────────────────────────────────────────────────

async def salud(request):
    return web.json_response({
        "ok": True, "gpu": estado["gpu"], "sesiones": estado["sesiones"],
        "modelos": {k: os.path.basename(v[1]) for k, v in INTERNOS.items()}})


async def a_wav16k(audio):
    """Cualquier audio → WAV 16 kHz mono, por tuberías (regla 1: nada a disco)."""
    proc = await asyncio.create_subprocess_exec(
        "ffmpeg", "-loglevel", "error", "-i", "pipe:0", "-ar", "16000", "-ac", "1",
        "-c:a", "pcm_s16le", "-f", "wav", "pipe:1",
        stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.DEVNULL)
    salida, _ = await asyncio.wait_for(proc.communicate(audio), timeout=60)
    if proc.returncode != 0 or len(salida) <= 44:
        return None
    return salida


async def transcribir(request):
    audio = await request.read()          # client_max_size ya lo acota
    if not audio:
        return web.json_response({"error": "sin_audio"}, status=400)
    modelo = "rapido" if request.headers.get("X-Modelo") == "rapido" else "final"
    t0 = time.perf_counter()
    wav = await a_wav16k(audio)
    if wav is None:
        return web.json_response({"error": "audio_ilegible"}, status=400)
    segundos = (len(wav) - 44) / 32000
    texto = await whisper(request.app, modelo, wav, request.headers.get("X-Idioma", "es"))
    ms = round((time.perf_counter() - t0) * 1000)
    log.info("transcribir: %.1f s de audio en %d ms (%s)", segundos, ms, modelo)
    return web.json_response({"texto": texto, "segundos": round(segundos, 2), "ms": ms})


# ── WebSocket: la frase mientras se dice ────────────────────────────────────────────

class Sesion:
    def __init__(self, app, ws, hz, idioma):
        self.app, self.ws, self.hz, self.idioma = app, ws, hz, idioma
        self.max_bytes = int(VENTANA_MAX_SEG * hz) * 2
        self.min_bytes = int(MIN_SEG * hz) * 2
        self.reinicia()
        self.tarea = None

    def reinicia(self):
        self.audio    = bytearray()
        self.acuerdo  = Acuerdo()
        self.hubo_voz = False
        # Bytes recibidos en total, y cuántos había en la última pasada. No vale el largo de
        # `audio`: con la ventana llena se queda fijo aunque siga llegando audio.
        self.recibido = 0
        self.visto    = 0
        self.pasadas  = 0

    def oye(self, trozo):
        self.audio += trozo
        self.recibido += len(trozo)
        if not self.hubo_voz and rms(trozo) >= SILENCIO_RMS:
            self.hubo_voz = True
        if len(self.audio) > self.max_bytes:
            # Una frase de más de 28 s (la radio hablando sin parar en el modo coche): se
            # queda la cola. Lo fijo se calculó sobre un audio que ya no está, así que se
            # empieza de nuevo; para oír «Jarvis» basta con la cola.
            del self.audio[:len(self.audio) - self.max_bytes]
            self.acuerdo.reinicia()

    def pcm(self):
        n = len(self.audio) & ~1          # nunca media muestra
        return bytes(self.audio[:n])

    async def bucle(self):
        while True:
            await asyncio.sleep(PASO_SEG)
            if not self.hubo_voz or len(self.audio) < self.min_bytes or self.recibido == self.visto:
                continue
            self.visto = self.recibido
            t0 = time.perf_counter()
            try:
                texto = await whisper(self.app, "rapido", wav_de_pcm16(self.pcm(), self.hz), self.idioma)
            except Exception as e:
                # Un parcial perdido no es grave: el siguiente llega en medio segundo
                log.warning("pasada fallida (%s)", type(e).__name__)
                continue
            if not texto:
                continue
            self.pasadas += 1
            fijo, provisional = self.acuerdo.pasada(texto)
            nombre = "fijo" if dice_nombre(fijo) else "provisional" if dice_nombre(provisional) else None
            await self.ws.send_json({"tipo": "parcial", "fijo": fijo, "provisional": provisional,
                                     "nombre": nombre,
                                     "ms": round((time.perf_counter() - t0) * 1000)})

    def empieza(self):
        self.tarea = asyncio.create_task(self.bucle())

    async def para(self):
        if self.tarea:
            self.tarea.cancel()
            try:
                await self.tarea
            except (asyncio.CancelledError, Exception):
                pass
            self.tarea = None

    async def fin(self):
        await self.para()                 # que ningún parcial llegue detrás del final
        t0 = time.perf_counter()
        segundos = len(self.audio) / 2 / self.hz
        texto = ""
        if self.hubo_voz and len(self.audio) >= self.min_bytes:
            texto = await whisper(self.app, "final", wav_de_pcm16(self.pcm(), self.hz), self.idioma)
        ms = round((time.perf_counter() - t0) * 1000)
        await self.ws.send_json({"tipo": "final", "texto": texto, "nombre": dice_nombre(texto),
                                 "segundos": round(segundos, 2), "ms": ms})
        log.info("frase: %.1f s, %d pasadas, final en %d ms%s", segundos, self.pasadas, ms,
                 "" if self.hubo_voz else " (sin voz)")
        self.reinicia()
        self.empieza()


async def escucha(request):
    try:
        hz = int(request.query.get("hz", "16000"))
    except ValueError:
        hz = 0
    if hz not in (8000, 16000):
        return web.json_response({"error": "hz_no_valido"}, status=400)
    if estado["sesiones"] >= MAX_SESIONES:
        return web.json_response({"error": "demasiadas_sesiones"}, status=503)
    ws = web.WebSocketResponse(heartbeat=20, max_msg_size=1024 * 1024)
    await ws.prepare(request)
    estado["sesiones"] += 1
    sesion = Sesion(request.app, ws, hz, request.query.get("idioma", "es"))
    sesion.empieza()
    log.info("sesión abierta (%d Hz); %d en curso", hz, estado["sesiones"])
    try:
        async for msg in ws:
            if msg.type == WSMsgType.BINARY:
                sesion.oye(msg.data)
            elif msg.type == WSMsgType.TEXT:
                try:
                    tipo = json.loads(msg.data).get("tipo")
                except (ValueError, AttributeError):
                    tipo = None
                if tipo == "fin":
                    try:
                        await sesion.fin()
                    except Exception as e:
                        log.warning("no se pudo transcribir la frase (%s)", type(e).__name__)
                        await ws.send_json({"tipo": "error", "detalle": "transcripcion"})
                        sesion.reinicia()
                        sesion.empieza()
                elif tipo == "reinicia":
                    await sesion.para()
                    sesion.reinicia()
                    sesion.empieza()
                else:
                    await ws.send_json({"tipo": "error", "detalle": "mensaje_desconocido"})
    finally:
        await sesion.para()
        estado["sesiones"] -= 1
        log.info("sesión cerrada; %d en curso", estado["sesiones"])
    return ws


# ── Arranque ────────────────────────────────────────────────────────────────────────

async def al_arrancar(app):
    app["http"] = ClientSession(timeout=ClientTimeout(total=60))
    gpus = []
    for nombre, (puerto, modelo) in INTERNOS.items():
        gpus.append(await arranca_whisper(app, nombre, puerto, modelo))
    estado["gpu"] = all(gpus)


async def al_parar(app):
    await app["http"].close()


def crea_app():
    app = web.Application(middlewares=[con_llave], client_max_size=MAX_SUBIDA)
    app.router.add_get("/salud", salud)
    app.router.add_post("/transcribir", transcribir)
    app.router.add_get("/escucha", escucha)
    app.on_startup.append(al_arrancar)
    app.on_cleanup.append(al_parar)
    return app


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")
    logging.getLogger("aiohttp.access").setLevel(logging.WARNING)
    if HOST not in ("127.0.0.1", "localhost", "::1") and not TOKEN:
        log.error("OIDO_HOST=%s sin OIDO_TOKEN: no arranco escuchando fuera de local sin llave", HOST)
        sys.exit(2)
    web.run_app(crea_app(), host=HOST, port=PUERTO, print=None)
