from fastapi import FastAPI, Depends, HTTPException, Request, status, UploadFile, File, Path
from fastapi.middleware.cors import CORSMiddleware
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from dotenv import load_dotenv
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo
from pydantic import BaseModel, Field, field_validator
from typing import Optional
from jose import JWTError, jwt
from openai import OpenAI
import msal
import requests
import os
import sys
import json
import re
import time
import hmac
import atexit
import logging
import smtplib
import threading
import contextvars
from collections import deque
from concurrent.futures import ThreadPoolExecutor
from email.message import EmailMessage
from urllib.parse import quote, urlsplit

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("life-assistant")

# Mapa de nombres de zona horaria de Windows a IANA
WINDOWS_TZ_MAP = {
    "Romance Standard Time": "Europe/Paris",
    "Central European Standard Time": "Europe/Budapest",
    "W. Europe Standard Time": "Europe/Berlin",
    "GMT Standard Time": "Europe/London",
    "UTC": "UTC",
}

def normalize_graph_dt(dt_obj: dict) -> str:
    """Convierte un objeto {dateTime, timeZone} de Graph API a ISO UTC con Z."""
    dt_str = dt_obj.get("dateTime", "")
    tz_name = dt_obj.get("timeZone", "UTC")
    if not dt_str:
        return dt_str
    # Si ya tiene offset/Z, parsear directamente
    if dt_str.endswith("Z") or "+" in dt_str[10:] or (len(dt_str) > 10 and dt_str[10] == "T" and "-" in dt_str[16:]):
        try:
            dt = datetime.fromisoformat(dt_str.replace("Z", "+00:00"))
            return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        except Exception:
            pass
    # Sin offset: el dateTime está en la zona indicada por timeZone
    iana_tz = WINDOWS_TZ_MAP.get(tz_name, tz_name)
    try:
        local_tz = ZoneInfo(iana_tz)
    except Exception:
        local_tz = ZoneInfo("UTC")
    try:
        # Recortar microsegundos extra si los hay
        clean = dt_str[:26].rstrip(".")
        dt_local = datetime.fromisoformat(clean).replace(tzinfo=local_tz)
        return dt_local.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    except Exception:
        return dt_str

load_dotenv()

app = FastAPI()

# Orígenes permitidos, separados por comas. En tu instancia, añade tu dominio de Vercel.
CORS_ORIGINS = [
    o.strip() for o in os.getenv(
        "CORS_ORIGINS",
        "http://localhost:5173,https://life-assistant-smoky.vercel.app",
    ).split(",") if o.strip()
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

CLIENT_ID = os.getenv("CLIENT_ID")
TENANT_ID = os.getenv("TENANT_ID")
CLIENT_SECRET = os.getenv("CLIENT_SECRET")
REDIRECT_URI = os.getenv("REDIRECT_URI")
# Secretos obligatorios: la app NO debe arrancar con valores por defecto conocidos.
# En un repo público, un fallback como "fallback-secret" permitiría forjar JWT válidos
# si la variable no estuviera configurada en producción.
DASHBOARD_PASSWORD = os.getenv("DASHBOARD_PASSWORD")
SECRET_KEY = os.getenv("SECRET_KEY")
if not SECRET_KEY:
    raise RuntimeError("SECRET_KEY no configurada — define la variable de entorno antes de arrancar")
if not DASHBOARD_PASSWORD:
    raise RuntimeError("DASHBOARD_PASSWORD no configurada — define la variable de entorno antes de arrancar")
ALGORITHM = "HS256"
TOKEN_EXPIRE_DAYS = 30
GOOGLE_MAPS_API_KEY = os.getenv("GOOGLE_MAPS_API_KEY")
SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")
HOME_ADDRESS = os.getenv("HOME_ADDRESS", "")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
MAX_JOB_ATTEMPTS = int(os.getenv("MAX_JOB_ATTEMPTS", "3"))
# Techo de sesiones que trae /training/summary de una vez. De esa lista salen tanto
# las posteriores al último cobro como las diez más recientes, así que basta con que
# cubra un periodo de cobro con holgura.
MAX_SESIONES_RESUMEN = int(os.getenv("MAX_SESIONES_RESUMEN", "200"))
HA_POLL_TOKEN       = os.getenv("HA_POLL_TOKEN", "")
HEALTH_INGEST_TOKEN = os.getenv("HEALTH_INGEST_TOKEN", "")
AGENT_TOKEN         = os.getenv("AGENT_TOKEN", "")   # el agente PC sondea y cierra jobs con este token
# Personalización de la instancia (kit self-hosted)
TIMEZONE         = os.getenv("TIMEZONE", "Europe/Madrid")   # zona horaria IANA del usuario
CLASSES_CALENDAR = os.getenv("CLASSES_CALENDAR", "clases")  # nombre del calendario de clases en Outlook
WEATHER_LAT      = os.getenv("WEATHER_LAT", "40.4168")      # coordenadas para el clima (Open-Meteo)
WEATHER_LON      = os.getenv("WEATHER_LON", "-3.7038")      # por defecto Madrid

# ── Presencia (la manda Home Assistant) ───────────────────────────────────────
# Cuánto se considera vigente la última ubicación conocida. Pasado ese plazo NO se usa
# para geolocalizar nada: HA puede estar caído, sin red o con la app cerrada, y una
# ubicación de hace seis horas es peor que no tener ninguna — daría el clima de donde
# estabas, presentado como si fuera el de donde estás. Igual que con la cola de jobs:
# "no lo sé" no puede disfrazarse de dato.
PRESENCE_TTL_MINUTES = int(os.getenv("PRESENCE_TTL_MINUTES", "45"))
# Hueco máximo entre dos avisos que se sigue contabilizando como tiempo en esa zona.
# Si HA estuvo doce horas sin mandar nada, no sabemos dónde estuviste: ese tramo se
# descarta en vez de imputarlo entero a la última zona conocida.
PRESENCE_MAX_GAP_HOURS = float(os.getenv("PRESENCE_MAX_GAP_HOURS", "3"))

# Hosts a los que se permite apuntar `alud_url`. Esa URL sale del cuerpo HTML de un
# evento de Outlook — dato NO confiable — y termina en `page.goto()` dentro del agente,
# en un Edge que YA tiene la sesión de Alud/Okta iniciada, cuyo texto se le entrega
# después a Cowork como instrucción. Sin lista blanca, quien pueda meter un evento en
# el calendario elige adónde navega ese navegador y qué se le dicta al agente.
# Se valida en tres sitios (extracción, alta del job y el propio agente) a propósito:
# la cola es escribible desde fuera del backend.
ALUD_ALLOWED_HOSTS = tuple(
    h.strip().lower()
    for h in os.getenv("ALUD_ALLOWED_HOSTS", "alud.deusto.es").split(",")
    if h.strip()
)

# ── Resumen diario por correo ─────────────────────────────────────────────────
# El backend NO redacta el resumen: manda los datos crudos a tu propio buzón y de ahí
# los recoge la rutina de Claude Code que ya compone el correo diario (lee el buzón,
# no llama a la API). Por eso aquí no hay ninguna llamada a un LLM: quien interpreta
# los números es el que escribe el correo final, y ya es un modelo.
BRIEF_TOKEN   = os.getenv("BRIEF_TOKEN", "")     # token de servicio del disparador diario
BRIEF_TO      = os.getenv("BRIEF_TO", "")        # destinatario (tu propia dirección)
BRIEF_FROM    = os.getenv("BRIEF_FROM", "")      # remitente; por defecto, SMTP_USER
SMTP_HOST     = os.getenv("SMTP_HOST", "")
SMTP_PORT     = int(os.getenv("SMTP_PORT", "587"))
SMTP_USER     = os.getenv("SMTP_USER", "")
SMTP_PASSWORD = os.getenv("SMTP_PASSWORD", "")
# Marcador que convierte un evento en "entrega". Debe coincidir con
# VITE_ENTREGAS_MARKER del frontend: el backend no ve las variables VITE_*.
ENTREGAS_MARKER     = os.getenv("ENTREGAS_MARKER", "📚")
BRIEF_DIAS_ENTREGAS = int(os.getenv("BRIEF_DIAS_ENTREGAS", "14"))
# Ventana de despertar. Una señal anterior a BRIEF_DESPERTAR_DESDE no cuenta como
# despertarse: levantarse a beber agua a las 04:00 o mirar la hora en el móvil no
# tienen que traer el briefing del día. Y si a BRIEF_HORA_TOPE no ha llegado ninguna
# señal, se manda igual — a esa hora la explicación probable es que algo falló, y un
# briefing tardío es mejor que ninguno y que además nadie eche de menos.
BRIEF_DESPERTAR_DESDE = os.getenv("BRIEF_DESPERTAR_DESDE", "05:30")
# La ventana también tiene techo. Sin él, el día en que fallen todas las señales de la
# mañana, desenchufar el cargador a las cinco de la tarde mandaría el correo del día
# entonces, llamándolo "despertar": datos ya caducados y la palabra significando lo que
# no es. Pasado este tope solo pueden mandarlo los disparadores que se declaran
# respaldo, que es lo honesto.
BRIEF_DESPERTAR_HASTA = os.getenv("BRIEF_DESPERTAR_HASTA", "11:30")
BRIEF_HORA_TOPE       = os.getenv("BRIEF_HORA_TOPE", "10:00")
# Si la llegada del sueño del Watch cuenta como señal de despertar. Ver
# _avisar_sueno_recibido: es una deducción, no un aviso, y se puede apagar.
BRIEF_DISPARA_SUENO   = os.getenv("BRIEF_DISPARA_SUENO", "1") not in ("0", "false", "False")
# Disparo de la rutina de Claude Code que lee este correo y redacta el briefing.
# Su trigger de API: la URL y el token se generan en claude.ai/code/routines (el token
# se enseña UNA vez). Si faltan, no se dispara nada y la rutina se queda solo con su
# trigger de horario — el sistema sigue funcionando, solo que sin esta mitad.
RUTINA_FIRE_URL   = os.getenv("RUTINA_FIRE_URL", "")
RUTINA_FIRE_TOKEN = os.getenv("RUTINA_FIRE_TOKEN", "")
# Cabecera beta con fecha: el endpoint está en research preview y los cambios que
# rompen salen bajo una fecha nueva, manteniendo las dos anteriores. Si un día empieza
# a devolver 400, es esto lo que hay que actualizar.
RUTINA_BETA       = os.getenv("RUTINA_BETA", "experimental-cc-routine-2026-04-01")
# A partir de qué hora dispara el backend. Antes se encarga el trigger de horario de la
# propia rutina: despertarse a las 6 no debe traer el briefing a las 6, porque recoge
# newsletters que a esa hora todavía no han llegado.
BRIEF_RUTINA_DESDE = os.getenv("BRIEF_RUTINA_DESDE", "08:00")

# Topes de cuerpo de las subidas. Sin ellos, `UploadFile.read()` y `request.body()`
# cargan en memoria lo que mande el cliente: la VM de Fly tiene 1 GB y bastan unos
# pocos cuerpos grandes en paralelo para tumbarla.
MAX_AUDIO_BYTES  = int(os.getenv("MAX_AUDIO_BYTES",  str(8 * 1024 * 1024)))
MAX_INGEST_BYTES = int(os.getenv("MAX_INGEST_BYTES", str(4 * 1024 * 1024)))
# La transcripción cuesta dinero en cada llamada: limitar el gasto de una sesión
# comprometida, no solo el consumo de memoria.
AUDIO_MAX_REQUESTS   = int(os.getenv("AUDIO_MAX_REQUESTS", "10"))
AUDIO_WINDOW_SECONDS = int(os.getenv("AUDIO_WINDOW_SECONDS", "300"))

try:
    LOCAL_TZ = ZoneInfo(TIMEZONE)
except Exception:
    raise RuntimeError(f"TIMEZONE inválida: {TIMEZONE!r} — usa un nombre IANA, p.ej. Europe/Madrid")

# ── Cliente HTTP saliente ─────────────────────────────────────────────────────
# Sesión única para todo lo que sale del backend (Supabase, Graph, Maps, Open-Meteo).
# Dos motivos: reutiliza conexiones (evita un handshake TLS por llamada, y algunos
# endpoints encadenan media docena) y sobre todo IMPONE UN TIMEOUT POR DEFECTO. Sin él,
# una llamada colgada retiene un hilo del pool de FastAPI para siempre; con suficientes,
# el backend deja de responder entero y solo lo arregla un redeploy.
HTTP_TIMEOUT = float(os.getenv("HTTP_TIMEOUT", "15"))


class _SesionConTimeout(requests.Session):
    def request(self, method, url, **kwargs):
        kwargs.setdefault("timeout", HTTP_TIMEOUT)
        return super().request(method, url, **kwargs)


http = _SesionConTimeout()

# El cliente de OpenAI se crea perezosamente: construirlo al importar hacía que el
# backend NO ARRANCARA sin OPENAI_API_KEY, aunque check_config.py y DESPLIEGUE.md
# documentan las ideas por voz como funcionalidad opcional.
_openai_client = None


def get_openai_client() -> OpenAI:
    global _openai_client
    if not OPENAI_API_KEY:
        raise HTTPException(
            status_code=503,
            detail="Ideas por voz no disponible: falta OPENAI_API_KEY en el servidor",
        )
    if _openai_client is None:
        _openai_client = OpenAI(api_key=OPENAI_API_KEY)
    return _openai_client


def supabase_headers():
    return {
        "apikey": SUPABASE_KEY,
        "Authorization": f"Bearer {SUPABASE_KEY}",
        "Content-Type": "application/json",
    }

bearer_scheme = HTTPBearer()

# ── REGISTRO PERSISTENTE (tabla app_logs) ─────────────────────────────────────
# El backend ya llamaba a logger.error()/warning() en todos los sitios que importan. El
# problema nunca fue que faltaran mensajes: es que van al stdout de una máquina de Fly
# que ESCALA A CERO, así que se van con ella y solo se ven si alguien mira `fly logs`
# justo en ese momento. El 409 que dejó al Watch sin sincronizar se registró cada vez,
# durante días, sin que nadie lo viera.
#
# Este handler engancha el logger que ya existe, así que CUALQUIER logger.error() del
# fichero —los de ahora y los que se añadan— pasa a ser visible desde el dashboard sin
# tocar el sitio donde se llama. Reglas de diseño, todas por el mismo motivo: registrar
# no puede tumbar ni frenar una petición.
#   - La petición solo encola en memoria; a Supabase escribe un hilo de fondo, en lotes.
#   - La cola está acotada: si se llena se tiran las más viejas y se deja constancia de
#     cuántas, para que un pico de errores no se coma la RAM de la VM (1 GB).
#   - Un fallo escribiendo el registro se traga y se avisa por stderr, nunca por logger:
#     eso realimentaría la cola con el error de escribir la cola.
LOG_PERSIST        = os.getenv("LOG_PERSIST", "1").lower() not in ("0", "false", "no")
LOG_PERSIST_LEVEL  = os.getenv("LOG_PERSIST_LEVEL", "WARNING").upper()
LOG_QUEUE_MAX      = int(os.getenv("LOG_QUEUE_MAX", "500"))
LOG_FLUSH_SECONDS  = float(os.getenv("LOG_FLUSH_SECONDS", "2"))
LOG_RETENTION_DAYS = int(os.getenv("LOG_RETENTION_DAYS", "30"))
# Por encima de esto una petición se considera lenta y se registra. El arranque en frío
# de Fly ya se lleva unos segundos, así que el umbral va holgado para no marcar como
# problema lo que solo es la máquina despertándose.
LOG_SLOW_MS        = float(os.getenv("LOG_SLOW_MS", "8000"))

NIVELES_LOG = ("DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL")

# "MÉTODO /ruta" de la petición que se está atendiendo, para poder responder a "¿y esto
# dónde reventó?" sin tener que deducirlo del texto del mensaje. Lo rellena el
# middleware; fuera de una petición (hilo de volcado, arranque) se queda vacío.
_peticion_actual: contextvars.ContextVar[str] = contextvars.ContextVar("peticion_actual", default="")


class RegistroSupabase(logging.Handler):
    """Handler que encola los registros y los escribe en app_logs desde otro hilo."""

    def __init__(self, nivel: int):
        super().__init__(level=nivel)
        self._cola: deque = deque(maxlen=LOG_QUEUE_MAX)
        self._lock = threading.Lock()
        self._descartados = 0
        self._purgado = False

    def emit(self, record: logging.LogRecord):
        try:
            fila = {
                "level": record.levelname,
                "source": record.name,
                # format() y no getMessage(): así el traceback de logger.exception()
                # queda guardado, que es justo lo que hace falta para diagnosticar.
                "message": self.format(record)[:8000],
                "created_at": datetime.fromtimestamp(record.created, timezone.utc).isoformat(),
                "context": {
                    "origen": f"{record.module}:{record.lineno}",
                    "peticion": _peticion_actual.get(""),
                },
            }
        except Exception:   # noqa: BLE001 — un fallo formateando no puede propagarse
            return
        with self._lock:
            if len(self._cola) == LOG_QUEUE_MAX:
                self._descartados += 1
            self._cola.append(fila)

    def _tomar_lote(self) -> list:
        with self._lock:
            if not self._cola:
                return []
            lote = list(self._cola)
            self._cola.clear()
            descartados, self._descartados = self._descartados, 0
        if descartados:
            lote.append({
                "level": "WARNING",
                "source": logger.name,
                "message": f"Se descartaron {descartados} entradas de registro: la cola se llenó "
                           f"(LOG_QUEUE_MAX={LOG_QUEUE_MAX})",
                "created_at": datetime.now(timezone.utc).isoformat(),
                "context": {"origen": "registro", "peticion": ""},
            })
        return lote

    def volcar(self):
        """Escribe lo encolado. Best-effort: nunca lanza."""
        lote = self._tomar_lote()
        if not lote:
            return
        try:
            r = http.post(
                f"{SUPABASE_URL}/rest/v1/app_logs",
                headers={**supabase_headers(), "Prefer": "return=minimal"},
                json=lote,
            )
            if r.status_code >= 300:
                print(f"[registro] no se pudo escribir en app_logs ({r.status_code})", file=sys.stderr)
                return
        except Exception as e:   # noqa: BLE001 — red caída, Supabase fuera... da igual
            print(f"[registro] fallo escribiendo en app_logs: {e}", file=sys.stderr)
            return
        # Purga de lo viejo una sola vez por proceso. Fly arranca en frío a menudo, así
        # que sale gratis y evita añadir un cron solo para esto.
        if not self._purgado:
            self._purgado = True
            self._purgar()

    def _purgar(self):
        corte = (datetime.now(timezone.utc) - timedelta(days=LOG_RETENTION_DAYS)).isoformat()
        try:
            http.delete(
                f"{SUPABASE_URL}/rest/v1/app_logs?created_at=lt.{quote(corte, safe='')}",
                headers={**supabase_headers(), "Prefer": "return=minimal"},
            )
        except Exception as e:   # noqa: BLE001 — la purga es mantenimiento, no crítica
            print(f"[registro] fallo purgando app_logs: {e}", file=sys.stderr)


_registro = RegistroSupabase(getattr(logging, LOG_PERSIST_LEVEL, logging.WARNING))


def _bucle_de_volcado():
    while True:
        time.sleep(LOG_FLUSH_SECONDS)
        _registro.volcar()


def activar_registro_persistente():
    """Engancha el handler y arranca el hilo de volcado. Idempotente."""
    if _registro in logger.handlers:
        return
    logger.addHandler(_registro)
    threading.Thread(target=_bucle_de_volcado, daemon=True, name="volcado-registro").start()
    # Fly duerme la máquina en cuanto deja de haber tráfico: sin esto, lo encolado en los
    # últimos LOG_FLUSH_SECONDS —justo lo que pasó antes de que todo se parase— se pierde.
    atexit.register(_registro.volcar)


if LOG_PERSIST and SUPABASE_URL:
    activar_registro_persistente()


@app.middleware("http")
async def registrar_peticiones(request: Request, call_next):
    """Deja constancia de lo que falla o va lento, sin depender de que cada endpoint se
    acuerde de registrarlo. Es la mitad de "logs para todo" que no se puede escribir a
    mano en 60 endpoints."""
    # La ruta va SIN query string a propósito: por ahí viajan HEALTH_INGEST_TOKEN y
    # HA_POLL_TOKEN (soportado por compatibilidad), y no pueden acabar en una tabla.
    ruta = f"{request.method} {request.url.path}"
    marca = _peticion_actual.set(ruta)
    inicio = time.monotonic()
    try:
        respuesta = await call_next(request)
        ms = (time.monotonic() - inicio) * 1000
        if respuesta.status_code >= 500:
            logger.error("%s → %d (%.0f ms)", ruta, respuesta.status_code, ms)
        # El 401 se queda fuera: es el JWT caducando, que el frontend ya resuelve solo
        # mandando al login. El 403 SÍ entra — es un token de servicio que no cuadra,
        # o sea una integración (Watch, HA, Shortcut) que ha dejado de entrar.
        elif respuesta.status_code >= 400 and respuesta.status_code != 401:
            logger.warning("%s → %d (%.0f ms)", ruta, respuesta.status_code, ms)
        elif ms > LOG_SLOW_MS:
            logger.warning("%s tardó %.0f ms", ruta, ms)
        return respuesta
    except Exception:
        logger.exception("%s: excepción no controlada", ruta)
        raise
    finally:
        _peticion_actual.reset(marca)


# ── Seguridad: rate limiting del login ────────────────────────────────────────
LOGIN_MAX_ATTEMPTS   = int(os.getenv("LOGIN_MAX_ATTEMPTS", "5"))
LOGIN_WINDOW_SECONDS = int(os.getenv("LOGIN_WINDOW_SECONDS", "300"))
# Solo actívalo si despliegas detrás de un proxy inverso propio que añada la cabecera
# (en Fly no hace falta: ya manda Fly-Client-IP). Ver _client_ip.
TRUST_FORWARDED_FOR  = os.getenv("TRUST_FORWARDED_FOR", "").lower() in ("1", "true", "yes")
# Lo define el runtime de Fly. Sirve para saber si Fly-Client-IP es de fiar.
EN_FLY               = bool(os.getenv("FLY_APP_NAME"))


def _client_ip(request: Request) -> str:
    """IP del cliente para el rate limiting, sin fiarse de lo que él mismo declare.

    `X-Forwarded-For` la puede poner cualquiera: antes se cogía su PRIMERA entrada, así
    que rotando la cabecera se conseguían intentos de login ilimitados. Por eso aquí solo
    se usan fuentes que el cliente NO controla:

      1. `Fly-Client-IP` — la pone el proxy de Fly, y solo se cree si de verdad estamos
         corriendo en Fly (FLY_APP_NAME lo define su runtime). Fuera de Fly no hay nadie
         que la sobrescriba, así que la mandaría el propio cliente: se ignora.
      2. El socket real de la conexión.

    Si alguien despliega detrás de otro proxy inverso propio, puede activar
    TRUST_FORWARDED_FOR=1 y entonces se usa la ÚLTIMA entrada de X-Forwarded-For (la que
    añade el proxy más cercano; las anteriores siguen siendo del cliente). Está apagado
    por defecto a propósito: equivocarse aquí abre la puerta a la fuerza bruta.
    """
    if EN_FLY:
        fly = request.headers.get("fly-client-ip")
        if fly:
            return fly.strip()
    if TRUST_FORWARDED_FOR:
        fwd = request.headers.get("x-forwarded-for", "")
        partes = [p.strip() for p in fwd.split(",") if p.strip()]
        if partes:
            return partes[-1]
    return request.client.host if request.client else "unknown"


def _check_login_rate():
    """Límite de intentos fallidos de login: GLOBAL (no por IP) y persistido en Supabase.

    Global porque esto es una app de un solo usuario: limitar por IP dejaba una vía de
    escape gratis (rotar de dirección, trivial en IPv6) sin proteger nada a cambio — al
    ser global, cambiar de IP no le da a nadie un cupo de intentos nuevo.

    En Supabase y no en memoria porque el contador en memoria se borraba en cada cold
    start de Fly (`auto_stop_machines`): bastaba con esperar a que la máquina se
    durmiera entre tandas para que el límite volviera a cero.

    Si Supabase no responde, se deja pasar en vez de tumbar el login: es el único
    endpoint de la app que hoy no depende de Supabase para nada más, y esa propiedad
    (poder entrar aunque la base de datos esté caída, para al menos ver qué falla)
    vale más que blindar una ventana de fallo de infraestructura poco probable.
    """
    since = (datetime.now(timezone.utc) - timedelta(seconds=LOGIN_WINDOW_SECONDS)).isoformat()
    r = http.get(
        f"{SUPABASE_URL}/rest/v1/login_attempts?created_at=gt.{quote(since)}&select=created_at&order=created_at.asc",
        headers=supabase_headers(),
    )
    if r.status_code >= 300:
        logger.error("Rate limit de login: no se pudo consultar Supabase (%s)", r.status_code)
        return
    attempts = r.json()
    if len(attempts) >= LOGIN_MAX_ATTEMPTS:
        primero = datetime.fromisoformat(attempts[0]["created_at"].replace("Z", "+00:00"))
        retry = int(LOGIN_WINDOW_SECONDS - (datetime.now(timezone.utc) - primero).total_seconds())
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=f"Demasiados intentos. Reintenta en {retry}s",
            headers={"Retry-After": str(max(retry, 1))},
        )


def _register_login_failure(ip: str):
    logger.warning("Login fallido desde %s", ip)
    r = http.post(
        f"{SUPABASE_URL}/rest/v1/login_attempts",
        headers={**supabase_headers(), "Prefer": "return=minimal"},
        json={},
    )
    if r.status_code >= 300:
        logger.error("No se pudo registrar el intento fallido de login (%s)", r.status_code)


def _reset_login_attempts():
    r = http.delete(
        f"{SUPABASE_URL}/rest/v1/login_attempts?created_at=gt.1970-01-01T00:00:00Z",
        headers=supabase_headers(),
    )
    if r.status_code >= 300:
        logger.error("No se pudo limpiar login_attempts (%s)", r.status_code)


# Limitador genérico por (recurso, IP), aparte del del login. La diferencia con
# _check_login_rate es qué se cuenta: allí solo los intentos FALLIDOS, porque lo que se
# protege es una credencial; aquí TODAS las peticiones, porque lo que se protege es un
# recurso caro (memoria, o una llamada de pago a Whisper) y una petición legítima
# consume igual que una abusiva.
_rate_buckets: dict = {}
_rate_lock = threading.Lock()


def _check_rate(recurso: str, ip: str, maximo: int, ventana: int):
    ahora = time.time()
    clave = (recurso, ip)
    with _rate_lock:
        # Poda de claves caducadas: sin esto el diccionario crece sin techo con quien
        # rote IPs (trivial en IPv6). Barato porque solo mira las que ya expiraron.
        for k in [k for k, ts in _rate_buckets.items() if not ts or ahora - ts[-1] >= ventana]:
            del _rate_buckets[k]
        recientes = [t for t in _rate_buckets.get(clave, []) if ahora - t < ventana]
        if len(recientes) >= maximo:
            _rate_buckets[clave] = recientes
            espera = int(ventana - (ahora - recientes[0]))
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail=f"Demasiadas peticiones. Reintenta en {espera}s",
                headers={"Retry-After": str(max(espera, 1))},
            )
        recientes.append(ahora)
        _rate_buckets[clave] = recientes


async def _leer_cuerpo_limitado(request: Request, limite: int) -> bytes:
    """Lee el cuerpo abortando en cuanto se pasa del límite.

    Se mira `Content-Length` primero para cortar sin leer nada, pero no se confía solo
    en él: una petición con `Transfer-Encoding: chunked` no lo trae y el cliente
    tampoco está obligado a decir la verdad. De ahí el contador sobre el propio stream.
    """
    exceso = HTTPException(
        status_code=status.HTTP_413_CONTENT_TOO_LARGE,
        detail=f"Cuerpo demasiado grande (máximo {limite} bytes)",
    )
    declarado = request.headers.get("content-length", "")
    if declarado.isdigit() and int(declarado) > limite:
        raise exceso
    trozos, total = [], 0
    async for trozo in request.stream():
        total += len(trozo)
        if total > limite:
            raise exceso
        trozos.append(trozo)
    return b"".join(trozos)


def alud_url_permitida(url: str) -> bool:
    """True si la URL es https y su host está en ALUD_ALLOWED_HOSTS (o es subdominio).

    Se exige https porque el agente abre esa URL con una sesión iniciada detrás: por
    http, cualquiera en la red del PC vería (y podría reescribir) lo que se navega.
    """
    if not isinstance(url, str) or not url:
        return False
    try:
        partes = urlsplit(url)
    except ValueError:
        return False
    if partes.scheme != "https":
        return False
    host = (partes.hostname or "").lower()
    if not host:
        return False
    return any(host == permitido or host.endswith("." + permitido) for permitido in ALUD_ALLOWED_HOSTS)


def _extract_service_token(request: Request, token_qs: str = "") -> str:
    """Token de servicio (HA / health): preferir header para que no quede en logs de acceso.

    Orden: cabecera X-Auth-Token → Authorization: Bearer → query string (compat. con
    integraciones ya desplegadas de Home Assistant y iOS Shortcuts).
    """
    hdr = request.headers.get("x-auth-token")
    if hdr:
        return hdr
    auth = request.headers.get("authorization", "")
    if auth.lower().startswith("bearer "):
        return auth[7:].strip()
    return token_qs


def _token_ok(provided: str, expected: str) -> bool:
    """Comparación en tiempo constante; falsa si el token esperado no está configurado."""
    if not expected or not provided:
        return False
    return hmac.compare_digest(provided, expected)


def _graph_fallo(r, contexto: str) -> dict | None:
    """Devuelve un error para el cliente si la respuesta de Graph no vino bien.

    Sin esta comprobación, un 401 o un 500 de Graph caían en `data.get("value", [])`
    y salían como lista vacía: el dashboard pintaba "Sin eventos hoy" como si el día
    estuviera libre. Un fallo de autenticación no puede parecerse a una agenda vacía.
    """
    if r.status_code < 300:
        try:
            r.json()
        except ValueError:
            logger.error("Graph %s: respuesta no-JSON (%s)", contexto, r.status_code)
            return {"error": "Respuesta inesperada de Outlook"}
        return None
    logger.error("Graph %s %s: %s", contexto, r.status_code, (r.text or "")[:500])
    if r.status_code in (401, 403):
        return {"error": "Sesión de Outlook caducada. Vuelve a conectar en /auth/login"}
    return {"error": "No se pudo consultar el calendario de Outlook"}


def _supabase_error(r) -> HTTPException:
    """Loguea el detalle real de Supabase en el servidor y devuelve un error genérico al cliente."""
    logger.error("Error de almacenamiento (%s): %s", r.status_code, (r.text or "")[:500])
    return HTTPException(status_code=502, detail="Error en el almacenamiento de datos")


class LoginRequest(BaseModel):
    password: str = Field(max_length=200)


class JobCreateRequest(BaseModel):
    dedupe_key: str = Field(max_length=200)
    payload: dict = {}

class JobClaimRequest(BaseModel):
    worker_id: str = Field(max_length=64, pattern=r'^[a-zA-Z0-9_-]+$')

class JobStartRequest(BaseModel):
    worker_id: str = Field(max_length=64, pattern=r'^[a-zA-Z0-9_-]+$')

class JobFinishRequest(BaseModel):
    worker_id: str = Field(max_length=64, pattern=r'^[a-zA-Z0-9_-]+$')
    status: str  # done | failed

class JobRetryRequest(BaseModel):
    worker_id: str = Field(max_length=64, pattern=r'^[a-zA-Z0-9_-]+$')


class JobEventCreateRequest(BaseModel):
    stage: str = Field(max_length=64, pattern=r'^[a-zA-Z0-9_]+$')
    message: str | None = Field(None, max_length=1000)

class AgentHeartbeatRequest(BaseModel):
    agent_id: str = Field(max_length=64, pattern=r'^[a-zA-Z0-9_-]+$')
    status: str  # starting | online | busy | offline
    hostname: str | None = Field(None, max_length=255)
    version: str | None = Field(None, max_length=64)

def create_token() -> str:
    expire = datetime.now(timezone.utc) + timedelta(days=TOKEN_EXPIRE_DAYS)
    return jwt.encode({"exp": expire}, SECRET_KEY, algorithm=ALGORITHM)

def verify_token(credentials: HTTPAuthorizationCredentials = Depends(bearer_scheme)):
    try:
        jwt.decode(credentials.credentials, SECRET_KEY, algorithms=[ALGORITHM])
    except JWTError:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Token inválido")


def verify_agente(request: Request):
    """Auth de los endpoints que usa el agente PC: token de servicio O JWT de usuario.

    El agente es una máquina y llevaba un JWT del dashboard copiado a mano en su `.env`.
    Ese JWT caduca a los 30 días, y cuando caducó el agente no dejó de funcionar de
    forma visible: `GET /jobs/pending` empezó a responder 401, el agente lo tradujo a
    "no hay jobs pendientes" y se cerró en silencio en cada arranque. Mismo criterio que
    BRIEF_TOKEN: lo que no puede volver a hacer login por su cuenta no puede depender de
    un token que expira.

    Se sigue aceptando el JWT porque estos endpoints no son solo del agente — el
    dashboard consulta el estado de un job con la sesión del usuario — y porque así una
    instancia sin AGENT_TOKEN configurado sigue funcionando como antes.

    El token se lee solo de cabeceras (`_extract_service_token` sin query string): aquí
    el cliente es código propio, así que no hay ninguna integración desplegada que
    migrar, y un token en la query acaba en los logs de acceso.
    """
    provisto = _extract_service_token(request)
    if _token_ok(provisto, AGENT_TOKEN):
        return
    try:
        jwt.decode(provisto, SECRET_KEY, algorithms=[ALGORITHM])
    except JWTError:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Token inválido")


def _create_oauth_state() -> str:
    """`state` del flujo OAuth de Microsoft: firmado y de corta duración.

    /auth/login exige JWT, pero /auth/callback lo recibe Microsoft por redirect y no
    puede llevar ese JWT (es una navegación de nivel superior, sin cabeceras propias).
    Sin este `state`, cualquiera podía completar SU PROPIO login de Microsoft contra
    /auth/callback y sus tokens pisaban los del usuario en `oauth_tokens` (una sola
    fila). Firmado con SECRET_KEY en vez de guardado en memoria: sobrevive a que Fly
    duerma la máquina mientras el usuario está en la pantalla de consentimiento.
    """
    expire = datetime.now(timezone.utc) + timedelta(minutes=10)
    return jwt.encode({"exp": expire, "purpose": "oauth_state"}, SECRET_KEY, algorithm=ALGORITHM)


def _verify_oauth_state(state: str) -> bool:
    try:
        claims = jwt.decode(state, SECRET_KEY, algorithms=[ALGORITHM])
    except JWTError:
        return False
    return claims.get("purpose") == "oauth_state"


SCOPES = ["Calendars.ReadWrite", "User.Read"]
OAUTH_PROVIDER = "microsoft_graph"

# Cliente MSAL compartido. Se construía de cero en /auth/login, /auth/callback y en
# cada renovación de token, y cada construcción descubre la autoridad
# (login.microsoftonline.com) por red antes de poder hacer nada. Perezoso, además,
# para no exigir credenciales de Graph al importar el módulo.
_msal_cliente = None
_msal_lock = threading.Lock()


def _msal_app() -> msal.ConfidentialClientApplication:
    global _msal_cliente
    with _msal_lock:
        if _msal_cliente is None:
            _msal_cliente = msal.ConfidentialClientApplication(
                CLIENT_ID,
                authority="https://login.microsoftonline.com/common",
                client_credential=CLIENT_SECRET,
                timeout=HTTP_TIMEOUT,   # msal usa su propia sesión: sin esto, sin timeout
            )
        return _msal_cliente

_DATE_RE = re.compile(r'^\d{4}-\d{2}-\d{2}$')

DIAS_SEMANA = ("lunes", "martes", "miércoles", "jueves", "viernes", "sábado", "domingo")

_SAFE_ID_RE = re.compile(r'^[a-zA-Z0-9_-]{1,64}$')

# Los ids de recurso se interpolan en las URLs de Supabase, así que todos los path
# params que sean UUID se validan con este patrón. Estaba copiado literalmente en
# cinco endpoints: una sola definición evita que a alguno se le olvide.
_UUID_PATTERN = r'^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$'


def _uuid_path():
    """Validador de path param UUID. Es una FÁBRICA, no una constante: FastAPI asocia
    cada objeto Path() al nombre del parámetro que lo usa, así que compartir una única
    instancia entre endpoints con nombres distintos (idea_id, item_id, session_id…)
    hacía que todos heredaran el último nombre registrado y devolvieran 422."""
    return Path(..., pattern=_UUID_PATTERN)

_wol_pending = False
# El agente PC es efímero (arranca con Windows, drena la cola y se cierra). Si el PC
# YA está encendido, el WOL no relanza nada: este flag pide a HA que arranque el
# agente por SSH. Mismo patrón que _wol_pending: se marca aquí y HA lo limpia al leerlo.
_agent_relaunch_pending = False
# Apagar/suspender el PC. No pasa por el agente (que es efímero y ya terminó cuando el
# PC está encendido): HA lo ejecuta directo por SSH. Guarda la acción pendiente
# ("shutdown" | "suspend" | None) y HA la lee y la limpia.
_pc_power_action = None

def _clean_class_title(subject: str) -> str:
    s = re.sub(r"^\d+\s*-\s*", "", subject)
    s = re.sub(r"\s*Grupo:\s*\d+\s*-\s*Asignatura\s*$", "", s, flags=re.IGNORECASE)
    return s.strip()

# Copia en memoria del token de Graph. Cada endpoint de calendario llamaba a
# get_valid_token(), y este leía la tabla oauth_tokens de Supabase: una carga del
# dashboard son dos viajes de red que solo sirven para releer un token que no ha
# cambiado, y el sondeo de HA suma otro por minuto. El proceso es uno solo, así que
# guardarlo aquí es seguro; expires_at manda y la escritura invalida la copia.
_token_cache: dict | None = None
_token_cache_lock = threading.Lock()


def _cachear_token(data: dict | None):
    global _token_cache
    with _token_cache_lock:
        _token_cache = data


def save_token_data(data: dict):
    """Persiste el token de Microsoft Graph en Supabase (sobrevive a redeploys del backend)."""
    payload = {
        "provider": OAUTH_PROVIDER,
        "access_token": data["access_token"],
        "refresh_token": data.get("refresh_token"),
        "expires_at": data["expires_at"],
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }
    r = http.get(
        f"{SUPABASE_URL}/rest/v1/oauth_tokens?provider=eq.{OAUTH_PROVIDER}&select=provider",
        headers=supabase_headers(),
    )
    if r.status_code < 300 and r.json():
        w = http.patch(
            f"{SUPABASE_URL}/rest/v1/oauth_tokens?provider=eq.{OAUTH_PROVIDER}",
            headers={**supabase_headers(), "Prefer": "return=minimal"},
            json=payload,
        )
    else:
        w = http.post(
            f"{SUPABASE_URL}/rest/v1/oauth_tokens",
            headers={**supabase_headers(), "Prefer": "return=minimal"},
            json=payload,
        )
    # Si la escritura falla, el token renovado solo vive en memoria: al reiniciar Fly
    # habrá que volver a pasar por /auth/login. Sin este log, en silencio.
    if w.status_code >= 300:
        logger.error("No se pudo persistir el token de Graph (%s): %s", w.status_code, (w.text or "")[:500])
    _cachear_token(payload)

def load_token_data() -> dict | None:
    with _token_cache_lock:
        if _token_cache is not None:
            return _token_cache
    r = http.get(
        f"{SUPABASE_URL}/rest/v1/oauth_tokens?provider=eq.{OAUTH_PROVIDER}&select=access_token,refresh_token,expires_at",
        headers=supabase_headers(),
    )
    if r.status_code < 300 and r.json():
        data = r.json()[0]
        _cachear_token(data)
        return data
    return None

def get_valid_token() -> str | None:
    data = load_token_data()
    if not data:
        return None
    # Si el access_token aún no ha expirado, lo devolvemos
    expires_at = data.get("expires_at", 0)
    if datetime.now(timezone.utc).timestamp() < expires_at - 60:
        return data["access_token"]
    # Si hay refresh_token, renovamos
    refresh_token = data.get("refresh_token")
    if not refresh_token:
        return None
    result = _msal_app().acquire_token_by_refresh_token(refresh_token, scopes=SCOPES)
    if "access_token" in result:
        _store_result(result)
        return result["access_token"]
    # El refresh ha fallado (token revocado o caducado): tirar la copia para que el
    # siguiente intento vuelva a leer de Supabase en vez de reintentar con lo mismo.
    logger.error("Renovación del token de Graph fallida: %s", result.get("error_description", result.get("error", "?")))
    _cachear_token(None)
    return None

def _store_result(result: dict):
    expires_at = datetime.now(timezone.utc).timestamp() + result.get("expires_in", 3600)
    save_token_data({
        "access_token": result["access_token"],
        "refresh_token": result.get("refresh_token"),
        "expires_at": expires_at,
    })

@app.post("/auth/password")
def login_password(body: LoginRequest, request: Request):
    _check_login_rate()
    # Comparar bytes: compare_digest sobre str exige ASCII puro y lanza TypeError con
    # cualquier tilde, lo que devolvía un 500 (y además se saltaba el registro del intento).
    if not hmac.compare_digest(body.password.encode("utf-8"), DASHBOARD_PASSWORD.encode("utf-8")):
        _register_login_failure(_client_ip(request))
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Contraseña incorrecta")
    _reset_login_attempts()
    return {"token": create_token()}

@app.get("/auth/login")
def login(credentials: HTTPAuthorizationCredentials = Depends(verify_token)):
    # Exige el JWT del dashboard: sin esto, cualquiera que supiera esta URL (no es
    # secreta — está en el propio CLAUDE.md, público en el repo) podía arrancar el
    # consentimiento de Microsoft con SU cuenta y acabar pisando la conexión de
    # Outlook del usuario.
    auth_url = _msal_app().get_authorization_request_url(
        SCOPES,
        redirect_uri=REDIRECT_URI,
        state=_create_oauth_state(),
    )
    return {"auth_url": auth_url}

@app.get("/auth/callback")
def callback(code: str, state: str = ""):
    # El callback lo llama Microsoft por redirect: no puede llevar el JWT del
    # dashboard. La prueba de que este código viene de un login que SÍ empezó con
    # sesión iniciada es el `state` que /auth/login generó y firmó.
    if not _verify_oauth_state(state):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Solicitud de conexión no reconocida o caducada. Repite el proceso desde el dashboard.",
        )
    result = _msal_app().acquire_token_by_authorization_code(
        code,
        scopes=SCOPES,
        redirect_uri=REDIRECT_URI,
    )
    if "access_token" in result:
        _store_result(result)
        return {"status": "ok", "message": "Autenticado correctamente"}
    return {"error": result.get("error_description")}

@app.get("/calendar/events")
def get_events(credentials: HTTPAuthorizationCredentials = Depends(verify_token)):
    token = get_valid_token()
    if not token:
        return {"error": "No autenticado. Ve a /auth/login primero"}
    
    headers = {"Authorization": f"Bearer {token}"}
    start = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    end = (datetime.now(timezone.utc) + timedelta(days=30)).strftime("%Y-%m-%dT%H:%M:%SZ")
    response = http.get(
        f"https://graph.microsoft.com/v1.0/me/calendarView?startDateTime={start}&endDateTime={end}&$top=100&$select=subject,start,end,location,body,bodyPreview,isAllDay&$orderby=start/dateTime",
        headers=headers
    )
    response.encoding = "utf-8"
    fallo = _graph_fallo(response, "calendarView")
    if fallo:
        return fallo
    data = response.json()
    
    events = []
    for event in data.get("value", []):
        body_content = event.get("body", {}).get("content", "") or ""
        preview_content = event.get("bodyPreview", "") or ""
        # No incluir <, > ni comillas en la URL: en cuerpos HTML la URL suele ir pegada
        # a la etiqueta de cierre (p.ej. ...id=99</p>) y \S+ se la tragaba entera.
        alud_match = re.search(r"alud_url:\s*(https?://[^\s<>\"']+)", body_content) or \
                     re.search(r"alud_url:\s*(https?://[^\s<>\"']+)", preview_content)
        alud_url = alud_match.group(1).rstrip("&;.,") if alud_match else None
        # El cuerpo del evento lo escribe quien lo crea, no necesariamente el usuario:
        # una URL de un host ajeno acabaría abierta en el navegador con sesión del PC.
        # Se descarta aquí, en el punto donde entra al sistema.
        if alud_url and not alud_url_permitida(alud_url):
            logger.warning("Evento %s: alud_url descartada (host no permitido)", event.get("id"))
            alud_url = None
        events.append({
            "id": event.get("id"),
            "title": _clean_class_title(event.get("subject", "")),
            "start": normalize_graph_dt(event.get("start", {})),
            "end": normalize_graph_dt(event.get("end", {})),
            "location": event.get("location", {}).get("displayName"),
            "preview": event.get("bodyPreview"),
            "alud_url": alud_url,
            "isAllDay": event.get("isAllDay"),
        })
    
    return {"events": events}

@app.get("/calendar/calendars")
def list_calendars(credentials: HTTPAuthorizationCredentials = Depends(verify_token)):
    token = get_valid_token()
    if not token:
        return {"error": "No autenticado"}
    headers = {"Authorization": f"Bearer {token}"}
    r = http.get("https://graph.microsoft.com/v1.0/me/calendars", headers=headers)
    fallo = _graph_fallo(r, "me/calendars")
    if fallo:
        return fallo
    return [{"id": c["id"], "name": c["name"]} for c in r.json().get("value", [])]


class CreateEventRequest(BaseModel):
    subject: str = Field(max_length=300)
    start: str  # ISO 8601 sin zona, p.ej. "2026-06-10T18:00:00"
    end: str
    location: str | None = Field(None, max_length=300)
    is_all_day: bool = False
    calendar_id: str | None = Field(None, max_length=200)
    description: str | None = Field(None, max_length=5000)


@app.post("/calendar/events")
def create_event(body: CreateEventRequest, credentials: HTTPAuthorizationCredentials = Depends(verify_token)):
    token = get_valid_token()
    if not token:
        return {"error": "No autenticado"}
    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
    payload = {
        "subject": body.subject,
        "start": {"dateTime": body.start, "timeZone": TIMEZONE},
        "end": {"dateTime": body.end, "timeZone": TIMEZONE},
        "isAllDay": body.is_all_day,
    }
    if body.location:
        payload["location"] = {"displayName": body.location}
    if body.description:
        payload["body"] = {"content": body.description, "bodyType": "text"}
    # quote() obligatorio: el id se interpola en la ruta de Graph y un valor con '/',
    # '?' o '#' cambiaría el endpoint al que se llama. El token de Graph tiene alcance
    # Calendars.ReadWrite sobre toda la cuenta, así que el margen no es estrecho.
    url = (
        f"https://graph.microsoft.com/v1.0/me/calendars/{quote(body.calendar_id, safe='')}/events"
        if body.calendar_id
        else "https://graph.microsoft.com/v1.0/me/events"
    )
    r = http.post(url, headers=headers, json=payload)
    if r.status_code not in (200, 201):
        logger.error("Graph create_event %s: %s", r.status_code, (r.text or "")[:500])
        return {"error": "No se pudo crear el evento en Outlook"}
    data = r.json()
    return {"status": "ok", "id": data.get("id")}


class UpdateEventRequest(BaseModel):
    subject: str | None = Field(None, max_length=300)
    start: str | None = None  # ISO 8601 sin zona, p.ej. "2026-06-10T18:00:00"
    end: str | None = None
    location: str | None = Field(None, max_length=300)
    is_all_day: bool | None = None
    description: str | None = Field(None, max_length=5000)


@app.patch("/calendar/events/{event_id}")
def update_event(
    # Los ids de Graph no tienen una forma fija que se pueda validar con un patrón sin
    # arriesgarse a rechazar ids reales, así que se acota el largo y se escapa al
    # construir la URL (ver más abajo).
    event_id: str = Path(..., max_length=512),
    body: UpdateEventRequest = ...,
    credentials: HTTPAuthorizationCredentials = Depends(verify_token),
):
    token = get_valid_token()
    if not token:
        return {"error": "No autenticado"}
    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
    payload = {}
    if body.subject is not None:
        payload["subject"] = body.subject
    if body.start is not None:
        payload["start"] = {"dateTime": body.start, "timeZone": TIMEZONE}
    if body.end is not None:
        payload["end"] = {"dateTime": body.end, "timeZone": TIMEZONE}
    if body.is_all_day is not None:
        payload["isAllDay"] = body.is_all_day
    if body.location is not None:
        payload["location"] = {"displayName": body.location}
    if body.description is not None:
        payload["body"] = {"content": body.description, "bodyType": "text"}
    if not payload:
        raise HTTPException(status_code=400, detail="Nada que actualizar")
    r = http.patch(
        f"https://graph.microsoft.com/v1.0/me/events/{quote(event_id, safe='')}",
        headers=headers,
        json=payload,
    )
    if r.status_code not in (200, 201):
        logger.error("Graph update_event %s: %s", r.status_code, (r.text or "")[:500])
        return {"error": "No se pudo actualizar el evento en Outlook"}
    return {"status": "ok"}


@app.get("/calendar/classes")
def get_class_events(credentials: HTTPAuthorizationCredentials = Depends(verify_token)):
    token = get_valid_token()
    if not token:
        return {"error": "No autenticado"}
    headers = {"Authorization": f"Bearer {token}"}
    # Buscar el calendario llamado 'Clases'
    r = http.get("https://graph.microsoft.com/v1.0/me/calendars", headers=headers)
    fallo = _graph_fallo(r, "me/calendars (clases)")
    if fallo:
        return fallo
    calendars = r.json().get("value", [])
    cal = next((c for c in calendars if c["name"].lower() == CLASSES_CALENDAR.lower()), None)
    if not cal:
        return {"error": "Calendario 'Clases' no encontrado", "available": [c["name"] for c in calendars]}
    cal_id = cal["id"]
    # Inicio del día en hora local del usuario para no perder clases de hoy
    today_start = datetime.now(LOCAL_TZ).replace(hour=0, minute=0, second=0, microsecond=0)
    start = today_start.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    end = (today_start + timedelta(days=60)).astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    r2 = http.get(
        f"https://graph.microsoft.com/v1.0/me/calendars/{cal_id}/calendarView"
        f"?startDateTime={start}&endDateTime={end}&$top=200"
        f"&$select=subject,start,end,location,isAllDay&$orderby=start/dateTime",
        headers=headers
    )
    r2.encoding = "utf-8"
    fallo = _graph_fallo(r2, "calendarView (clases)")
    if fallo:
        return fallo
    data2 = r2.json()

    events = []
    for event in data2.get("value", []):
        raw_start = event.get("start", {})
        raw_end = event.get("end", {})
        logger.debug("[CLASES] subject=%s tz=%s start_raw=%s", event.get("subject"), raw_start.get("timeZone"), raw_start.get("dateTime"))
        events.append({
            "id": event.get("id"),
            "title": _clean_class_title(event.get("subject", "")),
            "start": normalize_graph_dt(raw_start),
            "end": normalize_graph_dt(raw_end),
            "location": event.get("location", {}).get("displayName"),
            "isAllDay": event.get("isAllDay"),
        })
    logger.debug("[CLASES] Total eventos devueltos: %d", len(events))
    return {"events": events}


@app.get("/")
def root():
    return {"status": "Life Assistant API running"}


# ── MAPS ──────────────────────────────────────────────────────────────────────

class DepartureRequest(BaseModel):
    destination: str = Field(max_length=500)
    event_time: str = Field(max_length=50)
    # Vacío = "resuélvelo tú": el endpoint cae a la ubicación que reporta HA y, si no
    # la hay o está caducada, a HOME_ADDRESS. No puede tener HOME_ADDRESS como default
    # del modelo porque entonces "no me mandaron origen" y "me mandaron justo mi casa"
    # llegarían indistinguibles y la presencia nunca entraría en juego.
    origin: str = Field(default="", max_length=500)
    mode: str = Field(default="driving")

    @field_validator("event_time")
    @classmethod
    def validate_event_time(cls, v: str) -> str:
        try:
            datetime.fromisoformat(v.replace("Z", "+00:00"))
        except ValueError:
            raise ValueError("event_time debe ser una fecha ISO válida")
        return v

    @field_validator("mode")
    @classmethod
    def validate_mode(cls, v: str) -> str:
        if v not in ("driving", "walking"):
            raise ValueError("mode debe ser 'driving' o 'walking'")
        return v

@app.post("/maps/departure")
def get_departure_time(
    body: DepartureRequest,
    credentials: HTTPAuthorizationCredentials = Depends(verify_token)
):
    if not GOOGLE_MAPS_API_KEY:
        raise HTTPException(status_code=500, detail="Google Maps API key no configurada")

    # Orden de preferencia del origen: lo que mande el dispositivo (geolocalización del
    # navegador) → dónde dice HA que estás → HOME_ADDRESS. El segundo escalón es el que
    # arregla el caso real: en el móvil, con el navegador sin permiso de ubicación, la
    # hora de salida se calculaba desde casa aunque estuvieras en la universidad.
    origen = body.origin
    if not origen:
        coords = coords_presencia()
        origen = f"{coords[0]},{coords[1]}" if coords else HOME_ADDRESS

    # Calcular cuánto tarda en llegar
    url = "https://maps.googleapis.com/maps/api/distancematrix/json"
    params = {
        "origins": origen,
        "destinations": body.destination,
        "mode": body.mode,
        "language": "es",
        "key": GOOGLE_MAPS_API_KEY,
    }
    if body.mode == "driving":
        params["departure_time"] = "now"
        params["traffic_model"] = "best_guess"
    r = http.get(url, params=params)
    # Un error de Maps (cuota agotada, key inválida) no llega como JSON con la forma
    # esperada: sin esta comprobación, `.json()` reventaba con ValueError sin registrar
    # nada y el cliente veía un 500 pelado.
    if r.status_code >= 300:
        logger.error("Maps distancematrix %s: %s", r.status_code, (r.text or "")[:500])
        raise HTTPException(status_code=502, detail="No se pudo consultar Google Maps")
    try:
        data = r.json()
    except ValueError:
        logger.error("Maps distancematrix: respuesta no-JSON")
        raise HTTPException(status_code=502, detail="Respuesta inesperada de Google Maps")
    if data.get("status") not in (None, "OK"):
        logger.error("Maps distancematrix status=%s: %s", data.get("status"), data.get("error_message", "")[:300])
        raise HTTPException(status_code=502, detail="No se pudo calcular la ruta")

    try:
        element = data["rows"][0]["elements"][0]
        if element["status"] != "OK":
            raise HTTPException(status_code=400, detail="No se pudo calcular la ruta")

        # Duración con tráfico si es coche, sin tráfico si es a pie
        duration_seconds = element.get("duration_in_traffic", element["duration"])["value"]
        duration_text = element.get("duration_in_traffic", element["duration"])["text"]
        distance_text = element["distance"]["text"]

        # Calcular hora de salida
        event_dt = datetime.fromisoformat(body.event_time.replace("Z", "+00:00"))
        # Añadir 10 min de margen
        departure_dt = event_dt - timedelta(seconds=duration_seconds) - timedelta(minutes=10)
        # Convertir siempre a la hora local del usuario (TIMEZONE)
        departure_local = departure_dt.astimezone(LOCAL_TZ)

        return {
            "duration_text": duration_text,
            "distance_text": distance_text,
            "departure_time": departure_local.strftime("%H:%M"),
            "departure_iso": departure_local.isoformat(),
        }
    except (KeyError, IndexError):
        raise HTTPException(status_code=500, detail="Error procesando respuesta de Maps")


# ── CLIMA ─────────────────────────────────────────────────────────────────────

@app.get("/weather")
def get_weather(
    lat: float | None = None,
    lon: float | None = None,
    credentials: HTTPAuthorizationCredentials = Depends(verify_token),
):
    """Clima actual + máx/mín de hoy vía Open-Meteo (gratis, sin API key). El código
    WMO lo traduce el frontend a icono/texto (helpers.weatherFromCode).

    Tres escalones de ubicación, de más a menos fiable: lo que manda el dispositivo
    (geolocalización del navegador) → dónde dice HA que estás → WEATHER_LAT/LON. El de
    en medio es el que hace que el resumen diario, que no tiene navegador detrás, deje
    de dar siempre el tiempo de casa.
    """
    if lat is None or lon is None:
        coords = coords_presencia()
        if coords:
            lat, lon = coords
    latitude  = lat if lat is not None else WEATHER_LAT
    longitude = lon if lon is not None else WEATHER_LON
    r = http.get(
        "https://api.open-meteo.com/v1/forecast",
        params={
            "latitude": latitude,
            "longitude": longitude,
            "current": "temperature_2m,weather_code,apparent_temperature,relative_humidity_2m,wind_speed_10m,precipitation",
            "daily": "weather_code,temperature_2m_max,temperature_2m_min,precipitation_probability_max",
            "timezone": "auto",
            "forecast_days": 6,
        },
        timeout=10,
    )
    if r.status_code >= 300:
        raise HTTPException(status_code=502, detail="No se pudo obtener el clima")
    try:
        data    = r.json()
        current = data["current"]
        daily   = data["daily"]

        def _round_opt(v):
            return round(v) if isinstance(v, (int, float)) else None

        # Previsión por días (hoy incluido). El frontend deriva el día de la semana.
        dias = []
        for i in range(len(daily["time"])):
            dias.append({
                "date":        daily["time"][i],
                "code":        int(daily["weather_code"][i]),
                "max":         round(daily["temperature_2m_max"][i]),
                "min":         round(daily["temperature_2m_min"][i]),
                "precip_prob": _round_opt(daily.get("precipitation_probability_max", [None] * len(daily["time"]))[i]),
            })

        return {
            "temp":       round(current["temperature_2m"]),
            "code":       int(current["weather_code"]),
            "temp_max":   dias[0]["max"],
            "temp_min":   dias[0]["min"],
            # Extras para la vista desplegada (opcionales por robustez).
            "feels_like": _round_opt(current.get("apparent_temperature")),
            "humidity":   _round_opt(current.get("relative_humidity_2m")),
            "wind":       _round_opt(current.get("wind_speed_10m")),
            "precip":     current.get("precipitation"),
            "daily":      dias,
        }
    except (KeyError, IndexError, TypeError):
        raise HTTPException(status_code=502, detail="Respuesta de clima inválida")


# ── IDEAS ─────────────────────────────────────────────────────────

@app.get("/ideas")
def get_ideas(credentials: HTTPAuthorizationCredentials = Depends(verify_token)):
    r = http.get(
        f"{SUPABASE_URL}/rest/v1/ideas?order=created_at.desc",
        headers=supabase_headers(),
    )
    # Sin comprobar el estado, el cuerpo de error de Supabase (con sus mensajes
    # internos) se reenviaba tal cual al cliente — justo lo que evita _supabase_error.
    if r.status_code >= 300:
        raise _supabase_error(r)
    return r.json()

@app.delete("/ideas/{idea_id}")
def delete_idea(
    idea_id: str = _uuid_path(),
    credentials: HTTPAuthorizationCredentials = Depends(verify_token),
):
    r = http.delete(
        f"{SUPABASE_URL}/rest/v1/ideas?id=eq.{idea_id}",
        headers=supabase_headers(),
    )
    return {"ok": r.status_code < 300}

_HORA_RE = re.compile(r'^([01]\d|2[0-3]):[0-5]\d$')


def sugerencia_evento(idea_data: dict) -> dict | None:
    """Valida la fecha/hora que propone el modelo antes de ofrecerla al usuario.

    Lo que devuelve un LLM no se envía a Graph tal cual: aquí solo pasa lo que tiene
    forma de fecha (YYYY-MM-DD) y de hora (HH:MM). El evento no se crea solo — el
    frontend enseña la sugerencia y solo la crea si el usuario la pulsa.
    """
    fecha = idea_data.get("fecha")
    if not isinstance(fecha, str) or not _DATE_RE.match(fecha):
        return None
    try:
        datetime.strptime(fecha, "%Y-%m-%d")   # descarta 2026-13-45
    except ValueError:
        return None
    hora = idea_data.get("hora")
    if not isinstance(hora, str) or not _HORA_RE.match(hora):
        hora = None
    titulo = str(idea_data.get("key") or "").strip()[:200]
    if not titulo:
        return None
    return {"titulo": titulo, "fecha": fecha, "hora": hora}


def extract_idea_from_text(text: str) -> dict:
    """Extrae key/tag/full_text de un texto libre con GPT-4o mini.

    También intenta detectar si la nota es en realidad algo con fecha ("el martes
    tengo que llamar al dentista"). Se le da la fecha de hoy porque si no, no puede
    resolver referencias relativas.
    """
    hoy = datetime.now(LOCAL_TZ)
    completion = get_openai_client().chat.completions.create(
        model="gpt-4o-mini",
        messages=[
            {
                "role": "system",
                "content": (
                    "Eres un asistente que extrae ideas clave de notas de voz o texto. "
                    f"Hoy es {hoy.strftime('%Y-%m-%d')} ({DIAS_SEMANA[hoy.weekday()]}). "
                    "Dado un texto, responde SOLO con un JSON válido con este formato exacto: "
                    '{"key": "Título corto de la idea (máx 8 palabras)", "tag": "una palabra categoría", '
                    '"full_text": "Resumen claro y completo de la idea en 2-3 frases", '
                    '"fecha": "YYYY-MM-DD o null", "hora": "HH:MM o null"}. '
                    "Rellena fecha SOLO si el texto señala un momento concreto para hacer algo "
                    "('el martes', 'mañana', 'el 3 de junio', 'la semana que viene'); resuélvelo a "
                    "fecha absoluta usando la de hoy. Si es una idea sin cita, fecha y hora van a null. "
                    "Si hay día pero no hora concreta, hora va a null."
                ),
            },
            {"role": "user", "content": text},
        ],
        max_tokens=350,
        temperature=0.3,
    )
    raw = completion.choices[0].message.content.strip()
    raw = raw.replace("```json", "").replace("```", "").strip()
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return {}


def save_idea(text: str, idea_data: dict) -> dict:
    payload = {
        "key": str(idea_data.get("key", text[:60]))[:100],
        "full_text": str(idea_data.get("full_text", text))[:2000],
        "tag": str(idea_data.get("tag", "idea"))[:50],
    }
    r = http.post(
        f"{SUPABASE_URL}/rest/v1/ideas",
        headers={**supabase_headers(), "Prefer": "return=representation"},
        json=payload,
    )
    return r.json()[0] if r.status_code < 300 else payload


@app.post("/ideas/audio")
async def create_idea_from_audio(
    request: Request,
    audio: UploadFile = File(...),
    credentials: HTTPAuthorizationCredentials = Depends(verify_token),
):
    _check_rate("ideas_audio", _client_ip(request), AUDIO_MAX_REQUESTS, AUDIO_WINDOW_SECONDS)

    # 1. Transcribir con Whisper. Se lee un byte más del tope para poder distinguir
    # "justo en el límite" de "se ha pasado" sin cargar el resto en memoria.
    audio_bytes = await audio.read(MAX_AUDIO_BYTES + 1)
    if len(audio_bytes) > MAX_AUDIO_BYTES:
        raise HTTPException(
            status_code=status.HTTP_413_CONTENT_TOO_LARGE,
            detail=f"Audio demasiado grande (máximo {MAX_AUDIO_BYTES // (1024 * 1024)} MB)",
        )
    transcript = get_openai_client().audio.transcriptions.create(
        model="whisper-1",
        file=(audio.filename or "audio.webm", audio_bytes, audio.content_type or "audio/webm"),
        language="es",
    )
    text = transcript.text.strip()
    if not text:
        raise HTTPException(status_code=400, detail="No se pudo transcribir el audio")

    # 2. Extraer idea clave con GPT-4o mini y guardar en Supabase
    idea_data = extract_idea_from_text(text)
    idea = save_idea(text, idea_data)
    return {"ok": True, "idea": idea, "transcript": text, "evento_sugerido": sugerencia_evento(idea_data)}


class IdeaTextIn(BaseModel):
    text: str


@app.post("/ideas/text")
def create_idea_from_text(
    body: IdeaTextIn,
    credentials: HTTPAuthorizationCredentials = Depends(verify_token),
):
    text = body.text.strip()
    if not text:
        raise HTTPException(status_code=400, detail="El texto está vacío")

    idea_data = extract_idea_from_text(text)
    idea = save_idea(text, idea_data)
    return {"ok": True, "idea": idea, "evento_sugerido": sugerencia_evento(idea_data)}


# ── EXPORT / BACKUP ────────────────────────────────────────────────────────────
# Volcado completo de los datos personales para tener un backup manual. Solo se
# exportan los datos del usuario; nunca los tokens OAuth (secretos) ni la cola de
# jobs (estado operativo efímero). El frontend descarga el JSON como fichero.

# (tabla Supabase, clave de salida en el JSON). El orden es el que tiene sentido
# leer en el backup, no el de creación.
_EXPORT_TABLES = (
    ("ideas",             "ideas",             "order=created_at.desc"),
    ("training_clients",  "training_clients",  "order=created_at.asc"),
    ("training_sessions", "training_sessions", "order=date.desc"),
    ("training_payments", "training_payments", "order=date.desc"),
    ("health_metrics",    "health_metrics",    "order=metric_date.desc"),
    ("clothing",          "clothing",          "order=created_at.desc"),
)


@app.get("/export")
def export_data(credentials: HTTPAuthorizationCredentials = Depends(verify_token)):
    """Devuelve todos los datos personales en un único JSON para backup manual."""
    export: dict = {"exported_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")}

    def _tabla(table: str, order: str):
        # limit alto para traer el histórico completo de cada tabla en una llamada.
        return http.get(
            f"{SUPABASE_URL}/rest/v1/{table}?{order}&limit=100000",
            headers=supabase_headers(),
        )

    # Las seis tablas son independientes entre sí: en serie el backup costaba la suma
    # de las seis latencias (y aquí cada fila puede traer el histórico entero).
    with ThreadPoolExecutor(max_workers=len(_EXPORT_TABLES)) as pool:
        respuestas = list(pool.map(lambda t: _tabla(t[1], t[2]), _EXPORT_TABLES))

    for (key, _table, _order), r in zip(_EXPORT_TABLES, respuestas):
        if r.status_code >= 300:
            raise _supabase_error(r)
        export[key] = r.json()
    return export


# ── CONTEO DE ROPA (widget temporal) ──────────────────────────────────────────
# Lleva la cuenta de la ropa comprada hasta saldar el gasto. La foto llega como
# data URL ya redimensionada en el navegador; el backend solo la persiste.

_CLOTHING_CURRENCIES = ("EUR", "THB")
# Tope defensivo de la foto: el frontend la reduce a ~600px/JPEG (bastante menos),
# pero limitamos el tamaño para no aceptar payloads arbitrariamente grandes.
_CLOTHING_PHOTO_MAX = 3_000_000

class ClothingItemIn(BaseModel):
    name:     str = Field(default="", max_length=200)
    price:    float = Field(default=0.0, ge=0)
    currency: str = Field(default="EUR")
    photo:    Optional[str] = Field(default=None, max_length=_CLOTHING_PHOTO_MAX)

    @field_validator("currency")
    @classmethod
    def validate_currency(cls, v: str) -> str:
        if v not in _CLOTHING_CURRENCIES:
            raise ValueError("currency debe ser 'EUR' o 'THB'")
        return v


@app.get("/clothing")
def get_clothing(credentials: HTTPAuthorizationCredentials = Depends(verify_token)):
    r = http.get(
        f"{SUPABASE_URL}/rest/v1/clothing?order=created_at.desc",
        headers=supabase_headers(),
    )
    if r.status_code >= 300:
        raise _supabase_error(r)
    return r.json()


@app.post("/clothing")
def create_clothing(
    body: ClothingItemIn,
    credentials: HTTPAuthorizationCredentials = Depends(verify_token),
):
    payload = {
        "name":     body.name.strip(),   # el largo ya lo valida Pydantic (max_length=200)
        "price":    body.price,
        "currency": body.currency,
        "photo":    body.photo,
    }
    r = http.post(
        f"{SUPABASE_URL}/rest/v1/clothing",
        headers={**supabase_headers(), "Prefer": "return=representation"},
        json=payload,
    )
    if r.status_code >= 300:
        raise _supabase_error(r)
    return {"ok": True, "item": r.json()[0]}


@app.delete("/clothing/{item_id}")
def delete_clothing(
    item_id: str = _uuid_path(),
    credentials: HTTPAuthorizationCredentials = Depends(verify_token),
):
    r = http.delete(
        f"{SUPABASE_URL}/rest/v1/clothing?id=eq.{item_id}",
        headers=supabase_headers(),
    )
    if r.status_code >= 300:
        raise _supabase_error(r)
    return {"ok": True}


# ── HOME ASSISTANT INTEGRATION ────────────────────────────────────────────────

@app.get("/ha/events/soon")
def ha_events_soon(request: Request, token: str = ""):
    """Devuelve el primer evento que empieza en ~15 min. HA lo consulta cada minuto."""
    if not _token_ok(_extract_service_token(request, token), HA_POLL_TOKEN):
        raise HTTPException(status_code=403, detail="Forbidden")

    graph_token = get_valid_token()
    if not graph_token:
        return {"event": None}

    now = datetime.now(timezone.utc)
    end = now + timedelta(hours=1)
    headers = {"Authorization": f"Bearer {graph_token}"}
    # La llamada va envuelta porque `_graph_fallo` solo cubre la mitad del problema:
    # atiende las respuestas CON error (un 401, un 500 con HTML), pero no los fallos
    # SIN respuesta —conexión cortada, DNS, timeout—, que salen como excepción, se
    # saltan este manejo y acaban en un 500. HA no sabe leer un 500: espera el
    # {"event": None} de siempre, y con cualquier otra cosa la automatización de voz
    # se queda a medias. Es la misma regla que ya aplica al resto del endpoint, solo
    # que le faltaba el caso en que Graph no llega ni a contestar.
    try:
        response = http.get(
            "https://graph.microsoft.com/v1.0/me/calendarView"
            f"?startDateTime={now.strftime('%Y-%m-%dT%H:%M:%SZ')}"
            f"&endDateTime={end.strftime('%Y-%m-%dT%H:%M:%SZ')}"
            "&$top=20&$select=subject,start,isAllDay&$orderby=start/dateTime",
            headers=headers,
        )
    except requests.RequestException as e:
        logger.error("calendarView (ha/events/soon): sin respuesta de Graph (%s)", type(e).__name__)
        return {"event": None}
    # Sin esta comprobación, un fallo de Graph acababa en `.json()` sobre un cuerpo que
    # puede no ser JSON (500 con HTML → excepción y 500 propio) o en un `.get("value")`
    # vacío que HA interpreta como "no hay nada a la vista". Se registra y se devuelve
    # el mismo `{"event": None}` de siempre para no romper la automatización.
    if _graph_fallo(response, "calendarView (ha/events/soon)"):
        return {"event": None}
    for event in response.json().get("value", []):
        if event.get("isAllDay"):
            continue
        start_iso = normalize_graph_dt(event.get("start", {}))
        event_dt = datetime.fromisoformat(start_iso.replace("Z", "+00:00"))
        minutes_until = (event_dt - now).total_seconds() / 60
        if 13 <= minutes_until <= 17:
            return {"event": {"title": _clean_class_title(event.get("subject", "")), "start": start_iso}}
    return {"event": None}


# ── JOB QUEUE (SUPABASE) ─────────────────────────────────────────────────────

def _safe_worker(worker_id: str) -> str:
    if not _SAFE_ID_RE.match(worker_id):
        raise HTTPException(status_code=400, detail="worker_id inválido")
    return worker_id

@app.post("/wake-pc")
def wake_pc(credentials: HTTPAuthorizationCredentials = Depends(verify_token)):
    """Marca WOL pendiente — HA lo recoge en su próximo poll y envía el magic packet."""
    global _wol_pending
    _wol_pending = True
    return {"ok": True}

@app.get("/ha/wol-pending")
def ha_wol_pending(request: Request, token: str = ""):
    """HA sondea este endpoint cada 30s. Si hay WOL pendiente, devuelve pending=true y lo limpia."""
    if not _token_ok(_extract_service_token(request, token), HA_POLL_TOKEN):
        raise HTTPException(status_code=403, detail="Forbidden")
    global _wol_pending
    pending = _wol_pending
    _wol_pending = False
    return {"pending": pending}

@app.post("/relaunch-agent")
def relaunch_agent(credentials: HTTPAuthorizationCredentials = Depends(verify_token)):
    """Marca relanzado del agente pendiente — para cuando el PC ya está encendido y
    el agente efímero ya terminó. HA lo recoge en su poll y arranca el agente por SSH."""
    global _agent_relaunch_pending
    _agent_relaunch_pending = True
    return {"ok": True}

@app.get("/ha/agent-relaunch-pending")
def ha_agent_relaunch_pending(request: Request, token: str = ""):
    """HA sondea este endpoint. Si hay relanzado pendiente, devuelve pending=true y lo limpia."""
    if not _token_ok(_extract_service_token(request, token), HA_POLL_TOKEN):
        raise HTTPException(status_code=403, detail="Forbidden")
    global _agent_relaunch_pending
    pending = _agent_relaunch_pending
    _agent_relaunch_pending = False
    return {"pending": pending}

@app.post("/shutdown-pc")
def shutdown_pc(credentials: HTTPAuthorizationCredentials = Depends(verify_token)):
    """Marca apagado del PC pendiente — HA lo ejecuta por SSH en su próximo poll."""
    global _pc_power_action
    _pc_power_action = "shutdown"
    return {"ok": True}

@app.post("/suspend-pc")
def suspend_pc(credentials: HTTPAuthorizationCredentials = Depends(verify_token)):
    """Marca suspensión del PC pendiente — HA lo ejecuta por SSH en su próximo poll."""
    global _pc_power_action
    _pc_power_action = "suspend"
    return {"ok": True}

@app.get("/ha/pc-power-pending")
def ha_pc_power_pending(request: Request, token: str = ""):
    """HA sondea este endpoint. Devuelve la acción pendiente ("shutdown"|"suspend"|null) y la limpia."""
    if not _token_ok(_extract_service_token(request, token), HA_POLL_TOKEN):
        raise HTTPException(status_code=403, detail="Forbidden")
    global _pc_power_action
    action = _pc_power_action
    _pc_power_action = None
    return {"action": action}

@app.post("/jobs")
def create_job(body: JobCreateRequest, credentials: HTTPAuthorizationCredentials = Depends(verify_token)):
    # Segunda barrera de la misma comprobación que hace /calendar/events: el payload de
    # un job puede llegar por otras vías (una integración, un cliente manipulado), y lo
    # que se guarde aquí es exactamente lo que el agente ejecutará en el PC.
    alud_url = body.payload.get("alud_url") if isinstance(body.payload, dict) else None
    if alud_url is not None and not alud_url_permitida(alud_url):
        raise HTTPException(status_code=400, detail="alud_url no permitida")
    payload = {"dedupe_key": body.dedupe_key, "payload": body.payload}
    # `on_conflict=dedupe_key` es obligatorio (mismo motivo que en la ingesta de salud):
    # sin él PostgREST resuelve el conflicto contra la clave primaria, que aquí es `id`
    # —uuid nuevo en cada inserción, nunca colisiona—, así que la clave repetida acababa
    # en el índice único y Supabase devolvía un 409 que salía como 502. El camino de
    # "ya existe" de más abajo era, en la práctica, inalcanzable.
    # Y la resolución es `ignore-duplicates`, no `merge-duplicates`: si ya hay un job con
    # esa clave lo que queremos es devolverlo tal cual, no pisarle el payload — puede
    # estar ya en claimed/running y el agente trabajando sobre lo que leyó.
    r = http.post(
        f"{SUPABASE_URL}/rest/v1/jobs?on_conflict=dedupe_key",
        headers={**supabase_headers(), "Prefer": "return=representation,resolution=ignore-duplicates"},
        json=payload,
    )
    if r.status_code >= 300:
        raise _supabase_error(r)
    data = r.json()
    if data:
        return {"ok": True, "job": data[0]}
    # Conflicto de dedupe: el insert no devolvió filas — recuperar el job existente.
    # quote() obligatorio: la clave lleva el título del evento, y un '&' abriría un
    # parámetro nuevo mientras que un '#' convertiría el resto en fragmento (que ni
    # siquiera se envía al servidor, perdiendo también el &limit=1).
    r2 = http.get(
        f"{SUPABASE_URL}/rest/v1/jobs?dedupe_key=eq.{quote(body.dedupe_key, safe='')}&limit=1",
        headers=supabase_headers(),
    )
    data2 = r2.json() if r2.status_code < 300 else []
    return {"ok": True, "job": data2[0] if data2 else None}

@app.get("/jobs/pending")
def get_pending_job(_auth = Depends(verify_agente)):
    """El job pendiente más reciente de la última hora, para que lo recoja el agente.

    Antes esta consulta la hacía el propio agente directamente contra Supabase con la
    service_role key — la clave que salta toda la RLS de la base entera — guardada en
    un `.env` en el PC Windows. Era la única llamada que le obligaba a tenerla; con
    este endpoint el agente solo necesita el JWT del dashboard, igual que para
    claim/start/finish.
    """
    # Sufijo "Z" y no "+00:00": esto viaja en una query string, donde el "+" significa
    # espacio, así que PostgREST recibía "...T05:10:01 00:00" y respondía 400 (22007).
    cutoff = (datetime.now(timezone.utc) - timedelta(hours=1)).strftime("%Y-%m-%dT%H:%M:%SZ")
    r = http.get(
        f"{SUPABASE_URL}/rest/v1/jobs?status=eq.pending&created_at=gt.{cutoff}&order=created_at.desc&limit=1",
        headers=supabase_headers(),
    )
    if r.status_code >= 300:
        raise _supabase_error(r)
    rows = r.json()
    return {"ok": True, "job": rows[0] if rows else None}

_JOB_ID_PATH = _uuid_path()

@app.get("/jobs/by-id/{job_id}")
def get_job_by_id(
    job_id: str = _JOB_ID_PATH,
    credentials: HTTPAuthorizationCredentials = Depends(verify_token),
):
    r = http.get(
        f"{SUPABASE_URL}/rest/v1/jobs?id=eq.{job_id}&select=id,status,claimed_by,claimed_at,attempt,created_at",
        headers=supabase_headers(),
    )
    if r.status_code >= 300:
        raise _supabase_error(r)
    rows = r.json()
    return {"ok": True, "job": rows[0] if rows else None}

@app.post("/jobs/{job_id}/claim")
def claim_job(
    job_id: str = _JOB_ID_PATH,
    body: JobClaimRequest = ...,
    _auth = Depends(verify_agente),
):
    now_iso = datetime.now(timezone.utc).isoformat()
    worker = _safe_worker(body.worker_id)
    r = http.patch(
        f"{SUPABASE_URL}/rest/v1/jobs?id=eq.{job_id}&status=eq.pending",
        headers={**supabase_headers(), "Prefer": "return=representation"},
        json={"status": "claimed", "claimed_by": worker, "claimed_at": now_iso},
    )
    if r.status_code >= 300:
        raise _supabase_error(r)
    rows = r.json()
    if len(rows) == 0:
        return {"ok": False, "claimed": False, "reason": "already_claimed"}
    return {"ok": True, "claimed": True, "job": rows[0]}

@app.post("/jobs/{job_id}/start")
def start_job(
    job_id: str = _JOB_ID_PATH,
    body: JobStartRequest = ...,
    _auth = Depends(verify_agente),
):
    worker = _safe_worker(body.worker_id)
    r = http.patch(
        f"{SUPABASE_URL}/rest/v1/jobs?id=eq.{job_id}&status=eq.claimed&claimed_by=eq.{worker}",
        headers={**supabase_headers(), "Prefer": "return=representation"},
        json={"status": "running"},
    )
    if r.status_code >= 300:
        raise _supabase_error(r)
    rows = r.json()
    if len(rows) == 0:
        raise HTTPException(status_code=409, detail="El job no está en estado claimed para este worker")
    return {"ok": True, "job": rows[0]}

@app.post("/jobs/{job_id}/finish")
def finish_job(
    job_id: str = _JOB_ID_PATH,
    body: JobFinishRequest = ...,
    _auth = Depends(verify_agente),
):
    if body.status not in ("done", "failed"):
        raise HTTPException(status_code=400, detail="status debe ser done o failed")
    worker = _safe_worker(body.worker_id)
    r = http.patch(
        f"{SUPABASE_URL}/rest/v1/jobs?id=eq.{job_id}&status=eq.running&claimed_by=eq.{worker}",
        headers={**supabase_headers(), "Prefer": "return=representation"},
        json={"status": body.status},
    )
    if r.status_code >= 300:
        raise _supabase_error(r)
    rows = r.json()
    if len(rows) == 0:
        raise HTTPException(status_code=409, detail="El job no está en estado running para este worker")
    return {"ok": True, "job": rows[0]}

@app.post("/jobs/{job_id}/events")
def create_job_event(
    job_id: str = _JOB_ID_PATH,
    body: JobEventCreateRequest = ...,
    _auth = Depends(verify_agente),
):
    payload = {
        "job_id": job_id,
        "stage": body.stage,
        "message": body.message,
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    r = http.post(
        f"{SUPABASE_URL}/rest/v1/job_events",
        headers={**supabase_headers(), "Prefer": "return=representation"},
        json=payload,
    )
    if r.status_code >= 300:
        raise _supabase_error(r)
    rows = r.json()
    return {"ok": True, "event": rows[0] if rows else payload}

@app.get("/jobs/{job_id}/events")
def get_job_events(
    job_id: str = _JOB_ID_PATH,
    credentials: HTTPAuthorizationCredentials = Depends(verify_token),
):
    r = http.get(
        f"{SUPABASE_URL}/rest/v1/job_events?job_id=eq.{job_id}&select=job_id,stage,message,created_at&order=created_at.asc",
        headers=supabase_headers(),
    )
    if r.status_code >= 300:
        raise _supabase_error(r)
    return {"ok": True, "events": r.json()}

@app.post("/jobs/{job_id}/retry")
def retry_job(
    job_id: str = _JOB_ID_PATH,
    body: JobRetryRequest = ...,
    credentials: HTTPAuthorizationCredentials = Depends(verify_token),
):
    worker = _safe_worker(body.worker_id)
    get_r = http.get(
        f"{SUPABASE_URL}/rest/v1/jobs?id=eq.{job_id}&status=eq.failed&claimed_by=eq.{worker}&select=id,attempt",
        headers=supabase_headers(),
    )
    if get_r.status_code >= 300:
        raise _supabase_error(get_r)
    rows = get_r.json()
    if len(rows) == 0:
        raise HTTPException(status_code=409, detail="Job no elegible para retry")
    attempt = int(rows[0].get("attempt", 0)) + 1
    if attempt > MAX_JOB_ATTEMPTS:
        raise HTTPException(status_code=409, detail=f"Máximo de reintentos alcanzado ({MAX_JOB_ATTEMPTS})")

    patch_r = http.patch(
        f"{SUPABASE_URL}/rest/v1/jobs?id=eq.{job_id}&status=eq.failed&claimed_by=eq.{worker}",
        headers={**supabase_headers(), "Prefer": "return=representation"},
        json={"status": "pending", "attempt": attempt, "claimed_by": None, "claimed_at": None},
    )
    if patch_r.status_code >= 300:
        raise _supabase_error(patch_r)
    upd = patch_r.json()
    if len(upd) == 0:
        raise HTTPException(status_code=409, detail="Conflicto al aplicar retry")
    return {"ok": True, "job": upd[0], "max_attempts": MAX_JOB_ATTEMPTS}


@app.post("/agents/heartbeat")
def agent_heartbeat(body: AgentHeartbeatRequest, _auth = Depends(verify_agente)):
    if body.status not in ("starting", "online", "busy", "offline"):
        raise HTTPException(status_code=400, detail="status inválido")
    now_iso = datetime.now(timezone.utc).isoformat()
    payload = {
        "agent_id": body.agent_id,
        "status": body.status,
        "last_seen_at": now_iso,
        "hostname": body.hostname,
        "version": body.version,
        "updated_at": now_iso,
    }
    r = http.post(
        f"{SUPABASE_URL}/rest/v1/pc_agents",
        headers={**supabase_headers(), "Prefer": "return=representation,resolution=merge-duplicates"},
        json=payload,
    )
    if r.status_code >= 300:
        raise _supabase_error(r)
    rows = r.json()
    return {"ok": True, "agent": rows[0] if rows else payload}


@app.get("/agents/{agent_id}")
def get_agent(
    agent_id: str = Path(..., pattern=r'^[a-zA-Z0-9_-]{1,64}$'),
    credentials: HTTPAuthorizationCredentials = Depends(verify_token),
):
    r = http.get(
        f"{SUPABASE_URL}/rest/v1/pc_agents?agent_id=eq.{agent_id}&select=agent_id,status,last_seen_at,hostname,version",
        headers=supabase_headers(),
    )
    if r.status_code >= 300:
        raise _supabase_error(r)
    rows = r.json()
    if len(rows) == 0:
        return {"exists": False, "status": "offline", "offline": True}

    agent = rows[0]
    try:
        last_seen = datetime.fromisoformat(agent["last_seen_at"].replace("Z", "+00:00"))
    except Exception:
        last_seen = datetime.now(timezone.utc) - timedelta(seconds=9999)
    silence_seconds = (datetime.now(timezone.utc) - last_seen).total_seconds()
    offline = silence_seconds > 60
    if offline:
        agent["status"] = "offline"
    agent["offline"] = offline
    agent["silence_seconds"] = int(silence_seconds)
    agent["heartbeat_timeout_seconds"] = 60
    return agent


# ── ENTRENAMIENTO ─────────────────────────────────────────────────────────────

class TrainingSessionCreate(BaseModel):
    date: str = Field(max_length=10)
    duration_hours: float = Field(gt=0, le=24)

    @field_validator("date")
    @classmethod
    def validate_date(cls, v):
        if not _DATE_RE.match(v):
            raise ValueError("date debe tener formato YYYY-MM-DD")
        return v

class TrainingPaymentCreate(BaseModel):
    date: str = Field(max_length=10)

    @field_validator("date")
    @classmethod
    def validate_date(cls, v):
        if not _DATE_RE.match(v):
            raise ValueError("date debe tener formato YYYY-MM-DD")
        return v

def _get_training_client():
    r = http.get(
        f"{SUPABASE_URL}/rest/v1/training_clients?limit=1&order=created_at.asc",
        headers=supabase_headers(),
    )
    rows = r.json() if r.status_code < 300 else []
    return rows[0] if rows else None

@app.get("/training/summary")
def training_summary(credentials: HTTPAuthorizationCredentials = Depends(verify_token)):
    client = _get_training_client()
    if not client:
        return {"client": None}

    client_id = client["id"]
    price = float(client["price_per_hour"])
    sessions_per_payment = int(client["sessions_per_payment"])

    # Antes esto eran cuatro viajes a Supabase en serie, y se ejecuta en cada carga del
    # dashboard con el arranque en frío de Fly por delante. Ahora son dos: el pago y las
    # sesiones no dependen entre sí, así que van en paralelo, y de una sola lista de
    # sesiones salen tanto las posteriores al último cobro como las diez más recientes.
    def _pago():
        r = http.get(
            f"{SUPABASE_URL}/rest/v1/training_payments?client_id=eq.{client_id}&order=created_at.desc&limit=1",
            headers=supabase_headers(),
        )
        return r.json() if r.status_code < 300 else []

    def _sesiones():
        r = http.get(
            f"{SUPABASE_URL}/rest/v1/training_sessions?client_id=eq.{client_id}"
            f"&select=id,date,duration_hours,created_at&order=date.desc&limit={MAX_SESIONES_RESUMEN}",
            headers=supabase_headers(),
        )
        return r.json() if r.status_code < 300 else []

    with ThreadPoolExecutor(max_workers=2) as pool:
        f_pay, f_sess = pool.submit(_pago), pool.submit(_sesiones)
        payments, todas = f_pay.result(), f_sess.result()

    last_payment = payments[0] if payments else None
    all_sessions = todas[:10]
    if last_payment:
        # Mismo criterio que antes (created_at posterior al cobro), pero filtrando en
        # memoria en vez de pidiendo otra vez lo mismo con otro filtro.
        corte = last_payment["created_at"]
        sessions = [s for s in todas if (s.get("created_at") or "") > corte]
    else:
        sessions = todas

    total_hours = sum(float(s["duration_hours"]) for s in sessions)
    return {
        "client": client,
        "sessions_since_payment": len(sessions),
        "hours_since_payment": total_hours,
        "amount_owed": round(total_hours * price, 2),
        "sessions_per_payment": sessions_per_payment,
        "last_payment_date": last_payment["date"] if last_payment else None,
        "last_session_date": sessions[0]["date"] if sessions else None,
        "recent_sessions": sessions[:5],
        "all_recent_sessions": all_sessions,
    }

@app.post("/training/sessions")
def add_training_session(
    body: TrainingSessionCreate,
    credentials: HTTPAuthorizationCredentials = Depends(verify_token),
):
    client = _get_training_client()
    if not client:
        raise HTTPException(status_code=400, detail="No hay ningún cliente de entrenamiento")
    r = http.post(
        f"{SUPABASE_URL}/rest/v1/training_sessions",
        headers={**supabase_headers(), "Prefer": "return=representation"},
        json={"client_id": client["id"], "date": body.date, "duration_hours": body.duration_hours},
    )
    if r.status_code >= 300:
        raise _supabase_error(r)
    return {"ok": True, "session": r.json()[0]}

class TrainingClientUpdate(BaseModel):
    price_per_hour: float | None = Field(None, gt=0, le=1000)
    sessions_per_payment: int | None = Field(None, gt=0, le=100)

@app.patch("/training/client")
def update_training_client(
    body: TrainingClientUpdate,
    credentials: HTTPAuthorizationCredentials = Depends(verify_token),
):
    client = _get_training_client()
    if not client:
        raise HTTPException(status_code=400, detail="No hay ningún cliente de entrenamiento")
    patch = {}
    if body.price_per_hour is not None:
        patch["price_per_hour"] = body.price_per_hour
    if body.sessions_per_payment is not None:
        patch["sessions_per_payment"] = body.sessions_per_payment
    if not patch:
        raise HTTPException(status_code=400, detail="Nada que actualizar")
    r = http.patch(
        f"{SUPABASE_URL}/rest/v1/training_clients?id=eq.{client['id']}",
        headers={**supabase_headers(), "Prefer": "return=representation"},
        json=patch,
    )
    if r.status_code >= 300:
        raise _supabase_error(r)
    return {"ok": True, "client": r.json()[0]}

@app.delete("/training/sessions/{session_id}")
def delete_training_session(
    session_id: str = _uuid_path(),
    credentials: HTTPAuthorizationCredentials = Depends(verify_token),
):
    r = http.delete(
        f"{SUPABASE_URL}/rest/v1/training_sessions?id=eq.{session_id}",
        headers=supabase_headers(),
    )
    return {"ok": r.status_code < 300}

# ── SALUD (Apple Watch via Health Auto Export) ────────────────────────────────

# Métricas que se acumulan a lo largo del día: llegan snapshots parciales, así que un
# valor nuevo solo pisa al guardado si es MAYOR. Constantes de módulo y compartidas por
# las dos rutas de ingesta — cuando cada una tenía su propia copia, a la del Shortcut le
# faltaba resting_energy y un snapshot de mediodía podía pisar el total del día.
CUMULATIVE_METRICS = {"step_count", "active_energy", "basal_energy", "resting_energy"}
# Energía que Apple puede mandar en kJ y guardamos siempre en kcal.
ENERGY_METRICS = {"active_energy", "basal_energy", "resting_energy"}

# El upsert de health_metrics tiene que resolverse contra unique(metric_date,
# metric_name), y PostgREST solo lo hace si se le nombra la restricción: sin
# on_conflict usa la CLAVE PRIMARIA, que aquí es `id`, un uuid generado en cada
# inserción y que por tanto no colisiona nunca. La fila repetida llegaba entonces al
# índice único y Supabase devolvía 409 para el lote ENTERO — también para las métricas
# nuevas que venían en la misma llamada. Es exactamente el 409 que el esquema
# documenta; antes no se notaba porque cada métrica se escribía por separado y tenía un
# PATCH de respaldo, y al pasar a un upsert en bloque ese respaldo desapareció.
HEALTH_UPSERT_URL = f"{SUPABASE_URL}/rest/v1/health_metrics?on_conflict=metric_date,metric_name"

def _resumen_cuerpo(request: Request, raw: bytes, body) -> dict:
    """Qué forma tenía lo que llegó, para una sincronización que no guardó nada.

    Un cuerpo bien formado pero con la estructura equivocada (`{}`, o el envoltorio de
    otra versión del exportador) pasa todas las validaciones y sale como
    `200 {"ok": true, "upserted": 0}`: exactamente igual de silencioso que el 409 que
    dejó al Watch sin sincronizar. Esto dice qué claves traía, que es lo único que hace
    falta para distinguir "el cliente no manda nada" de "manda otra cosa".

    Solo claves y tamaños, nunca los valores: el resumen acaba en app_logs.
    """
    claves = sorted(body.keys()) if isinstance(body, dict) else f"<{type(body).__name__}>"
    dentro = body.get("data") if isinstance(body, dict) else None
    return {
        "bytes": len(raw),
        "content_type": request.headers.get("content-type", ""),
        "claves": claves,
        "claves_de_data": sorted(dentro.keys()) if isinstance(dentro, dict) else None,
    }


def _lote_vacio(body) -> bool:
    """True si el cuerpo tiene la forma que este endpoint espera pero venía sin nada.

    "No tengo nada que exportar" y "te estoy hablando en otro idioma" son cosas
    distintas y hasta ahora salían iguales: las dos como WARNING con `ok: false`.
    Health Auto Export manda lotes vacíos varias veces al día cuando el Watch no ha
    volcado nada nuevo —es su funcionamiento normal, no un fallo— y eso llenaba
    `app_logs` de avisos que tapaban los que sí importan.

    La forma se reconoce por `data` y por que dentro no haya claves ajenas: un `{}`
    pelado o el envoltorio de otro exportador siguen siendo estructura desconocida,
    que es justo lo que la protección del 409 existía para cazar. Y si `metrics` trae
    muestras pero no se reconoce ninguna, tampoco es un lote vacío: llegaron datos y
    no se entendió ni uno, que sí es un problema.
    """
    if not isinstance(body, dict):
        return False
    data = body.get("data")
    if not isinstance(data, dict):
        return False
    if set(data) - {"metrics", "workouts"}:
        return False
    return not data.get("metrics") and not data.get("workouts")


def _diagnostico_cuerpo(request: Request, raw: bytes, msg: str) -> dict:
    """Detalle de error que muestra qué llegó realmente al servidor, para poder
    diagnosticar por qué un cliente (Shortcut, app) no consigue enviar datos."""
    return {
        "error": msg,
        "content_type": request.headers.get("content-type", ""),
        "longitud_bytes": len(raw),
        "inicio": raw[:400].decode("utf-8", errors="replace"),
    }



def _existentes_por_clave(fechas: set, nombres: set) -> dict:
    """Trae de una sola vez las filas ya guardadas para esas fechas y métricas.

    Se filtra por rango de fechas (in.(...)) y por nombre: acotar por ambos evita
    arrastrar el histórico entero cuando el lote toca solo un par de días.
    """
    if not fechas or not nombres:
        return {}
    f = ",".join(sorted(fechas))
    n = ",".join(sorted(nombres))
    r = http.get(
        f"{SUPABASE_URL}/rest/v1/health_metrics"
        f"?metric_date=in.({quote(f, safe=',')})&metric_name=in.({quote(n, safe=',')})"
        f"&select=metric_date,metric_name,value,extra&limit=10000",
        headers=supabase_headers(),
    )
    if r.status_code >= 300:
        logger.error("Ingesta de salud: no se pudo leer lo existente (%s)", r.status_code)
        return {}
    return {(row["metric_date"], row["metric_name"]): row for row in r.json()}


def _guardar_metricas(agrupadas: dict) -> int:
    """Aplica la regla de las acumulativas y escribe todo en un upsert en bloque."""
    if not agrupadas:
        return 0
    existentes = _existentes_por_clave(
        {fecha for fecha, _ in agrupadas},
        {nombre for _, nombre in agrupadas},
    )

    filas = []
    for (metric_date, name), data in agrupadas.items():
        value = data["value"]
        if name in CUMULATIVE_METRICS and value is not None:
            previo = (existentes.get((metric_date, name)) or {}).get("value")
            # Solo se salta si lo guardado es un valor real (>0) y ya es mayor o igual:
            # llegan snapshots parciales a lo largo del día y no deben pisar el total.
            if previo is not None and float(previo) > 0 and float(previo) >= value:
                continue
        filas.append({
            "metric_date": metric_date,
            "metric_name": name,
            "value": value,
            "unit": data["unit"],
            "extra": data["extra"],
        })

    if not filas:
        return 0
    # merge-duplicates + on_conflict (ver HEALTH_UPSERT_URL): inserción y actualización
    # en una sola llamada, resueltas contra unique(metric_date, metric_name).
    r = http.post(
        HEALTH_UPSERT_URL,
        headers={**supabase_headers(), "Prefer": "return=minimal,resolution=merge-duplicates"},
        json=filas,
    )
    # Un fallo aquí es que no se ha guardado NADA del lote. Devolver 0 y seguir hacía
    # que el endpoint respondiera 200 {"ok": true}, así que el Watch y el Shortcut
    # daban la sincronización por buena mientras los datos se perdían en silencio.
    if r.status_code >= 300:
        logger.error("Ingesta de salud: upsert en bloque de %d filas falló", len(filas))
        raise _supabase_error(r)
    return len(filas)

@app.post("/health/ingest")
async def health_ingest(request: Request, token: str = ""):
    """Health Auto Export envía aquí los datos periódicamente."""
    if not _token_ok(_extract_service_token(request, token), HEALTH_INGEST_TOKEN):
        raise HTTPException(status_code=403, detail="Forbidden")

    raw = await _leer_cuerpo_limitado(request, MAX_INGEST_BYTES)
    try:
        body = json.loads(raw.decode("utf-8-sig", errors="replace")) if raw.strip() else None
    except (json.JSONDecodeError, ValueError):
        body = None
    if not isinstance(body, dict):
        raise HTTPException(status_code=400, detail=_diagnostico_cuerpo(
            request, raw, "El cuerpo no es un objeto JSON. Esto es lo que recibí:"))
    data_block = body.get("data", {})
    metrics    = data_block.get("metrics", [])
    workouts   = data_block.get("workouts", [])

    upserted = 0

    # ── Workouts: agrupar por fecha y guardar como una fila por día ──
    if workouts:
        from collections import defaultdict
        by_date: dict = defaultdict(list)
        for w in workouts:
            date_raw = str(w.get("start", w.get("date", "")))
            d = date_raw[:10] if len(date_raw) >= 10 else None
            if d:
                by_date[d].append(w)
        for d, day_workouts in by_date.items():
            payload = {
                "metric_date": d,
                "metric_name": "workouts",
                "value": float(len(day_workouts)),
                "unit": "count",
                "extra": {"workouts": day_workouts},
            }
            r = http.post(
                f"{SUPABASE_URL}/rest/v1/health_metrics",
                headers={**supabase_headers(), "Prefer": "return=minimal"},
                json=payload,
            )
            if r.status_code == 409:
                r = http.patch(
                    f"{SUPABASE_URL}/rest/v1/health_metrics"
                    f"?metric_date=eq.{d}&metric_name=eq.workouts",
                    headers={**supabase_headers(), "Prefer": "return=minimal"},
                    json={"value": payload["value"], "extra": payload["extra"]},
                )
            if r.status_code < 300:
                upserted += 1

    # ── Métricas normales (CUMULATIVE_METRICS/ENERGY_METRICS son de módulo) ──

    # Agrupar por (date, name) y quedarse con el valor máximo del batch entrante
    grouped_metrics: dict = {}
    for metric in metrics:
        name = metric.get("name", "")
        unit = metric.get("units", "")
        for point in metric.get("data", []):
            date_raw = str(point.get("date", ""))
            metric_date = date_raw[:10] if len(date_raw) >= 10 else None
            if not metric_date:
                continue

            if name in CUMULATIVE_METRICS:
                # Health Auto Export v2 usa "qty" para el total diario; "sum" puede venir como 0.
                # Tomamos el mayor valor no-None entre todos los campos posibles.
                _candidates = [v for k in ("qty", "sum", "value") if (v := point.get(k)) is not None]
                raw_value = max(_candidates) if _candidates else None
            elif name == "sleep_analysis":
                raw_value = (
                    point.get("totalSleep") if point.get("totalSleep") else
                    point.get("asleep") if point.get("asleep") else
                    point.get("qty")
                )
            else:
                raw_value = (
                    point.get("qty") if point.get("qty") is not None else
                    point.get("avg") if point.get("avg") is not None else
                    point.get("value")
                )
            value = float(raw_value) if raw_value is not None else None

            # Normalizar energía de kJ a kcal
            if name in ENERGY_METRICS and unit == "kJ" and value is not None:
                value = round(value / 4.184, 2)
                unit = "kcal"

            extra = {k: v for k, v in point.items() if k != "date"}
            # Para sleep_analysis, preservar la hora de inicio del sueño
            if name == "sleep_analysis" and len(date_raw) >= 16:
                extra["sleep_start"] = date_raw[11:16]  # "HH:MM"

            key = (metric_date, name)
            if key not in grouped_metrics:
                grouped_metrics[key] = {"unit": unit, "value": value, "extra": extra}
            elif name in CUMULATIVE_METRICS and value is not None:
                # Para métricas acumulativas, conservar el mayor valor del batch
                current = grouped_metrics[key]["value"]
                if current is None or value > current:
                    grouped_metrics[key] = {"unit": unit, "value": value, "extra": extra}

    # Escritura en dos viajes en vez de uno por métrica.
    #
    # Antes, por cada métrica: un GET para ver si existía, luego un POST y a veces un
    # PATCH si salía 409. Un lote normal del Watch son decenas de métricas, o sea del
    # orden de 60–90 viajes secuenciales a Supabase. Ahora es un GET que trae de golpe
    # lo ya guardado de esas fechas y un upsert en bloque con el resto.
    upserted += _guardar_metricas(grouped_metrics)

    # Si en el lote venía el sueño de esta noche, el Watch ya la ha cerrado: eso es lo
    # más parecido a "ya está despierto" que sabe el backend por su cuenta.
    _avisar_sueno_recibido({f for f, n in grouped_metrics if n == "sleep_analysis"})

    # Una sincronización de la que no se reconoce NADA no es un éxito: el cuerpo no
    # traía lo que este endpoint sabe leer (otro envoltorio, un `{}` porque el Shortcut
    # no adjunta el fichero...). Eso pasaba todas las validaciones y salía como
    # `200 {"ok": true, "upserted": 0}`, indistinguible de haber sincronizado.
    #
    # La condición mira lo RECONOCIDO, no lo escrito: un lote entero de acumulativas que
    # ya tenían guardado un valor mayor escribe cero y es perfectamente correcto.
    if not grouped_metrics and not workouts:
        recibido = _resumen_cuerpo(request, raw, body)
        # Un lote vacío del exportador es normal (ver _lote_vacio): se responde ok
        # porque no hay nada roto, y se registra a INFO para que no se persista.
        if _lote_vacio(body):
            logger.info("Ingesta de salud: lote vacío, nada que exportar. Recibido: %s", recibido)
            return {"ok": True, "upserted": 0, "vacio": True,
                    "detalle": "El exportador no tenía datos nuevos que enviar"}
        logger.warning("Ingesta de salud: nada que guardar. Recibido: %s", recibido)
        # El resumen va también en la respuesta, no solo al registro: el cliente es un
        # Shortcut que enseña el cuerpo en pantalla, así que la siguiente ejecución ya
        # dice qué llegó sin tener que ir a buscarlo a ningún sitio.
        return {"ok": False, "upserted": 0,
                "detalle": "No se guardó ninguna métrica: el cuerpo no traía datos legibles",
                "recibido": recibido}

    return {"ok": True, "upserted": upserted}


class SimpleHealthSample(BaseModel):
    metric: str
    date: str
    value: Optional[float] = None
    unit: Optional[str] = None
    extra: Optional[dict] = None


@app.post("/health/ingest/simple")
async def health_ingest_simple(request: Request, token: str = ""):
    """Endpoint simplificado para iOS Shortcuts. Acepta array plano o dict único."""
    if not _token_ok(_extract_service_token(request, token), HEALTH_INGEST_TOKEN):
        raise HTTPException(status_code=403, detail="Forbidden")

    parse_errors = []

    # Parseo de NDJSON tolerante: una línea mal formada se descarta y se reporta en
    # parse_errors en vez de tumbar el lote entero (antes daba un 500 y el Shortcut
    # dejaba de sincronizar sin explicación).
    def _parse_ndjson(text: str) -> list:
        out = []
        for line in text.strip().splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                out.append(json.loads(line))
            except (json.JSONDecodeError, ValueError):
                parse_errors.append({"line": line[:200], "error": "JSON inválido"})
        return out

    # El Shortcut de iOS puede mandar el cuerpo de varias formas: array/objeto JSON,
    # un objeto con la lista como string NDJSON bajo una clave, o NDJSON crudo (un
    # JSON por línea) directamente en el cuerpo — este último no es un JSON de una
    # pieza y `request.json()` fallaría. Leemos el cuerpo crudo y lo interpretamos:
    # utf-8-sig descarta el BOM que iOS a veces añade.
    raw  = await _leer_cuerpo_limitado(request, MAX_INGEST_BYTES)
    text = raw.decode("utf-8-sig", errors="replace").strip()
    body = None
    if text:
        try:
            body = json.loads(text)
        except (json.JSONDecodeError, ValueError):
            body = None
    if body is None:
        body = _parse_ndjson(text)  # NDJSON crudo
        if not body:
            raise HTTPException(status_code=400, detail=_diagnostico_cuerpo(
                request, raw, "No pude interpretar el cuerpo (ni JSON ni NDJSON). Esto es lo que recibí:"))

    if isinstance(body, dict):
        # iOS Shortcuts serializa listas como NDJSON dentro de un string bajo una clave
        if len(body) == 1:
            val = list(body.values())[0]
            if isinstance(val, str):
                body = _parse_ndjson(val)
            elif isinstance(val, list):
                body = val
            else:
                body = [body]
        else:
            body = [body]
    if not isinstance(body, list):
        body = [body]

    samples = []
    for item in body:
        try:
            v = item.get("value")
            if v is None:
                parse_errors.append({"metric": item.get("metric"), "reason": "value is None"})
                continue
            if v == "":
                v = 0
            samples.append(SimpleHealthSample(
                metric=item["metric"],
                date=item["date"],
                value=float(v),
                unit=item.get("unit"),
                extra=item.get("extra"),
            ))
        except (KeyError, ValueError, TypeError, AttributeError) as e:
            parse_errors.append({"item": str(item)[:200], "error": str(e)})
            continue

    upserted = 0
    skipped = []

    # Mismo patrón que /health/ingest (M4): una lectura en bloque de lo ya guardado y
    # un upsert con el resto, en vez de dos GET y un POST/PATCH por muestra.
    validas = []
    for s in samples:
        metric_date = s.date[:10] if s.date and len(s.date) >= 10 else None
        if not metric_date:
            skipped.append(f"{s.metric}: fecha inválida")
            continue
        validas.append((metric_date, s))

    existentes = _existentes_por_clave(
        {d for d, _ in validas}, {m.metric for _, m in validas},
    )

    filas = []
    for metric_date, s in validas:
        previo = existentes.get((metric_date, s.metric)) or {}
        extra = s.extra or {}

        # Respetar las noches que el usuario anuló a mano: el flag vive en la fila
        # guardada y una sincronización posterior no debe borrarlo.
        if s.metric == "sleep_analysis" and (previo.get("extra") or {}).get("excluded"):
            extra = {**extra, "excluded": True}

        if s.metric in CUMULATIVE_METRICS:
            valor_previo = previo.get("value")
            if valor_previo is not None and float(valor_previo) >= s.value:
                skipped.append(f"{s.metric}: existente={valor_previo} >= nuevo={s.value}")
                continue

        filas.append({
            "metric_date": metric_date,
            "metric_name": s.metric,
            "value": s.value,
            "unit": s.unit,
            "extra": extra,
        })

    if filas:
        r = http.post(
            HEALTH_UPSERT_URL,
            headers={**supabase_headers(), "Prefer": "return=minimal,resolution=merge-duplicates"},
            json=filas,
        )
        # Igual que en /health/ingest: si el upsert falla no se ha guardado nada, y
        # responder 200 {"ok": true} con el fallo escondido en `errors` es lo que hacía
        # que el Shortcut no diera ningún error mientras dejaba de sincronizar. El
        # detalle real va al log del servidor (invariante 5), al cliente solo el 502.
        if r.status_code >= 300:
            logger.error("Ingesta de salud (Shortcut): upsert en bloque de %d filas falló", len(filas))
            raise _supabase_error(r)
        upserted += len(filas)

    # Igual que en /health/ingest: el sueño de esta noche recién llegado es la señal de
    # que el Watch ya ha cerrado la noche.
    _avisar_sueno_recibido({d for d, s in validas if s.metric == "sleep_analysis"})

    # Mismo criterio que en /health/ingest, y con la misma precaución: se mira lo
    # RECONOCIDO (`samples`), no lo escrito. Cero muestras legibles es que el cuerpo no
    # traía nada aprovechable; cero escrituras teniendo muestras puede ser sencillamente
    # que ya estuviera todo guardado con un valor mayor.
    if not samples:
        logger.warning(
            "Ingesta de salud (Shortcut): ninguna muestra legible de %d elementos recibidos",
            len(parse_errors),
        )
        return {"ok": False, "upserted": 0, "received": 0,
                "detalle": "No se guardó ninguna métrica: el cuerpo no traía datos legibles",
                "skipped": skipped, "parse_errors": parse_errors}

    return {"ok": True, "upserted": upserted, "received": len(samples), "skipped": skipped, "parse_errors": parse_errors}


@app.patch("/health/sleep/{date}/exclude")
def toggle_sleep_exclude(
    date: str = Path(..., pattern=r"^\d{4}-\d{2}-\d{2}$"),
    credentials: HTTPAuthorizationCredentials = Depends(verify_token),
):
    """Alterna el flag excluded en extra de sleep_analysis para una fecha dada."""
    r = http.get(
        f"{SUPABASE_URL}/rest/v1/health_metrics"
        f"?metric_name=eq.sleep_analysis&metric_date=eq.{date}&select=extra",
        headers=supabase_headers(),
    )
    if r.status_code >= 300:
        raise _supabase_error(r)
    rows = r.json()
    if not rows:
        raise HTTPException(status_code=404, detail="No hay datos de sueño para esa fecha")
    extra = rows[0].get("extra") or {}
    extra["excluded"] = not extra.get("excluded", False)
    patch = http.patch(
        f"{SUPABASE_URL}/rest/v1/health_metrics"
        f"?metric_name=eq.sleep_analysis&metric_date=eq.{date}",
        headers={**supabase_headers(), "Prefer": "return=minimal"},
        json={"extra": extra},
    )
    if patch.status_code >= 300:
        raise _supabase_error(patch)
    return {"date": date, "excluded": extra["excluded"]}


@app.get("/health/metrics")
def get_health_metrics(
    days: int = 30,
    credentials: HTTPAuthorizationCredentials = Depends(verify_token),
):
    """Devuelve todas las métricas de los últimos N días, agrupadas por nombre."""
    if days < 1 or days > 365:
        raise HTTPException(status_code=400, detail="days debe estar entre 1 y 365")
    since = (datetime.now(timezone.utc) - timedelta(days=days)).strftime("%Y-%m-%d")
    r = http.get(
        f"{SUPABASE_URL}/rest/v1/health_metrics"
        f"?metric_date=gte.{since}&order=metric_date.asc&limit=5000",
        headers=supabase_headers(),
    )
    if r.status_code >= 300:
        raise _supabase_error(r)

    grouped: dict = {}
    last_sync: str | None = None
    today_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    has_today = False
    for row in r.json():
        name = row["metric_name"]
        if name not in grouped:
            grouped[name] = []
        grouped[name].append({
            "date": row["metric_date"],
            "value": row["value"],
            "unit": row["unit"],
            "extra": row.get("extra", {}),
        })
        if row["metric_date"] == today_str:
            has_today = True
        ca = row.get("created_at")
        if ca and (last_sync is None or ca > last_sync):
            last_sync = ca

    # Si hay datos de hoy, el sync es reciente aunque created_at sea antiguo (PATCH no lo actualiza)
    if has_today:
        last_sync = datetime.now(timezone.utc).isoformat()

    return {"metrics": grouped, "last_sync": last_sync}


@app.get("/health/latest")
def get_health_latest(
    credentials: HTTPAuthorizationCredentials = Depends(verify_token),
):
    """Último valor disponible de cada métrica."""
    r = http.get(
        f"{SUPABASE_URL}/rest/v1/health_metrics?order=metric_date.desc&limit=500",
        headers=supabase_headers(),
    )
    if r.status_code >= 300:
        raise _supabase_error(r)

    latest: dict = {}
    for row in r.json():
        name = row["metric_name"]
        if name not in latest:
            latest[name] = {
                "date": row["metric_date"],
                "value": row["value"],
                "unit": row["unit"],
                "extra": row.get("extra", {}),
            }

    return {"latest": latest}


@app.post("/training/payments")
def add_training_payment(
    body: TrainingPaymentCreate,
    credentials: HTTPAuthorizationCredentials = Depends(verify_token),
):
    client = _get_training_client()
    if not client:
        raise HTTPException(status_code=400, detail="No hay ningún cliente de entrenamiento")

    client_id = client["id"]
    r_pay = http.get(
        f"{SUPABASE_URL}/rest/v1/training_payments?client_id=eq.{client_id}&order=created_at.desc&limit=1",
        headers=supabase_headers(),
    )
    payments = r_pay.json() if r_pay.status_code < 300 else []
    last_payment = payments[0] if payments else None

    date_filter = f"&created_at=gt.{quote(last_payment['created_at'])}" if last_payment else ""
    r_sess = http.get(
        f"{SUPABASE_URL}/rest/v1/training_sessions?client_id=eq.{client_id}{date_filter}",
        headers=supabase_headers(),
    )
    sessions = r_sess.json() if r_sess.status_code < 300 else []
    amount = round(sum(float(s["duration_hours"]) for s in sessions) * float(client["price_per_hour"]), 2)

    r = http.post(
        f"{SUPABASE_URL}/rest/v1/training_payments",
        headers={**supabase_headers(), "Prefer": "return=representation"},
        json={"client_id": client_id, "date": body.date, "amount": amount},
    )
    if r.status_code >= 300:
        raise _supabase_error(r)
    return {"ok": True, "payment": r.json()[0]}


# ── PRESENCIA (la manda Home Assistant) ───────────────────────────────────────
# Único punto del sistema donde HA EMPUJA un dato en vez de sondear: aquí el que sabe
# es HA (tiene el device_tracker de la app del móvil) y el que necesita saber es el
# backend, así que el patrón pull del resto de la integración no sirve — el backend no
# puede llamar a HA, que vive en la LAN y no está expuesto (el mismo mixed content que
# obligó a que el WOL pasara por aquí).
#
# Se guarda en Supabase y no en un flag de módulo por lo mismo que los intentos de
# login: Fly escala a cero. La diferencia con los flags de WOL/apagado es que aquellos
# son ÓRDENES pendientes (perderlas en un cold start solo cuesta volver a pulsar el
# botón) y esto es ESTADO (perderlo deja al dashboard sin saber dónde estás hasta que
# te muevas de zona, que puede ser mañana).

PRESENCE_URL = f"{SUPABASE_URL}/rest/v1/presence"
PRESENCE_ID  = "actual"
# Nombre de la métrica diaria derivada. Va a health_metrics y no a una tabla propia
# para que entre sola en /health/metrics y, con ella, en el motor de correlaciones del
# frontend (`_CRUCES` en helpers.js) sin tener que abrirle otra vía de datos.
PRESENCE_METRIC = "time_at_home"
# Zonas de HA que cuentan como "en casa" si el aviso no trae `en_casa` explícito.
ZONAS_CASA = {"home", "casa"}

# Copia en memoria, igual que la del token de Graph y por el mismo motivo: /weather y
# /maps/departure la consultan en cada carga del dashboard y el dato solo cambia cuando
# HA manda un aviso, momento en el que esta copia se actualiza sola.
_presencia_cache: dict | None = None
_presencia_lock = threading.Lock()


def _cachear_presencia(data: dict | None):
    global _presencia_cache
    with _presencia_lock:
        _presencia_cache = data


def _leer_presencia() -> dict | None:
    with _presencia_lock:
        if _presencia_cache is not None:
            return _presencia_cache
    r = http.get(
        f"{PRESENCE_URL}?id=eq.{PRESENCE_ID}&select=zona,en_casa,lat,lon,precision_m,fuente,updated_at",
        headers=supabase_headers(),
    )
    if r.status_code >= 300:
        logger.error("Presencia: no se pudo leer (%s)", r.status_code)
        return None
    filas = r.json()
    if not filas:
        return None
    _cachear_presencia(filas[0])
    return filas[0]


def _edad_presencia(p: dict) -> float | None:
    """Minutos desde el último aviso, o None si el timestamp no se puede leer."""
    try:
        visto = datetime.fromisoformat((p.get("updated_at") or "").replace("Z", "+00:00"))
    except (ValueError, AttributeError):
        return None
    if visto.tzinfo is None:
        visto = visto.replace(tzinfo=timezone.utc)
    return (datetime.now(timezone.utc) - visto).total_seconds() / 60


def presencia_vigente() -> dict | None:
    """La ubicación actual solo si es reciente (PRESENCE_TTL_MINUTES).

    Un dato caducado NO se devuelve: quien llama lo usa para geolocalizar, y dar el
    clima de donde estabas hace horas como si fuera el de donde estás es peor que caer
    a las coordenadas de casa, que al menos son un default declarado.
    """
    p = _leer_presencia()
    if not p:
        return None
    edad = _edad_presencia(p)
    if edad is None or edad > PRESENCE_TTL_MINUTES:
        return None
    return p


def coords_presencia() -> tuple[float, float] | None:
    """(lat, lon) actuales, o None. Hay device_trackers sin GPS: la zona puede ser
    conocida y las coordenadas no."""
    p = presencia_vigente()
    if not p or p.get("lat") is None or p.get("lon") is None:
        return None
    return float(p["lat"]), float(p["lon"])


def _tramos_por_dia(inicio: datetime, fin: datetime) -> list[tuple[str, float]]:
    """Trocea [inicio, fin) por día LOCAL → [(YYYY-MM-DD, horas), ...].

    Sin trocear, el tramo que cruza la medianoche se imputaría entero al día en que
    empezó — y ese tramo es justo el de la noche, el que más pesa en cualquier cruce
    con el sueño."""
    tramos: list[tuple[str, float]] = []
    cursor = inicio.astimezone(LOCAL_TZ)
    final  = fin.astimezone(LOCAL_TZ)
    while cursor < final:
        # Medianoche local del día siguiente. Se calcula sumando el día ANTES de poner
        # la hora a cero para que un cambio de hora no deje el corte en las 23:00.
        siguiente = (cursor + timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)
        corte = min(siguiente, final)
        horas = (corte - cursor).total_seconds() / 3600
        if horas > 0:
            tramos.append((cursor.date().isoformat(), horas))
        cursor = corte
    return tramos


def _acumular_presencia(desde: datetime, hasta: datetime, en_casa: bool):
    """Suma el tramo transcurrido a la métrica diaria `time_at_home`.

    Se guardan HORAS, nunca lugares: la serie sirve para cruzarla con sueño y HRV, y
    para eso basta cuánto tiempo estuviste en casa. `value` son las horas en casa y
    `extra.fuera` las de fuera, así que un día con pocos avisos se distingue de uno
    entero en la calle (los dos tendrían value≈0, pero solo el segundo tiene fuera>0).
    """
    horas_hueco = (hasta - desde).total_seconds() / 3600
    if horas_hueco <= 0 or horas_hueco > PRESENCE_MAX_GAP_HOURS:
        return

    tramos = _tramos_por_dia(desde, hasta)
    if not tramos:
        return
    existentes = _existentes_por_clave({f for f, _ in tramos}, {PRESENCE_METRIC})

    agrupadas = {}
    for fecha, horas in tramos:
        fila  = existentes.get((fecha, PRESENCE_METRIC)) or {}
        extra = dict(fila.get("extra") or {})
        casa  = float(fila.get("value") or 0)
        fuera = float(extra.get("fuera") or 0)
        if en_casa:
            casa += horas
        else:
            fuera += horas
        extra["fuera"] = round(fuera, 3)
        agrupadas[(fecha, PRESENCE_METRIC)] = {
            "value": round(casa, 3),
            "unit":  "hr",
            "extra": extra,
        }

    try:
        _guardar_metricas(agrupadas)
    except HTTPException:
        # La serie diaria es un derivado: que no se pueda escribir no puede tumbar el
        # aviso de presencia, cuyo efecto principal (saber dónde estás AHORA) sí ha
        # funcionado. _guardar_metricas ya lo ha registrado.
        pass


class PresenciaRequest(BaseModel):
    zona: str = Field(max_length=64)
    en_casa: bool | None = None
    lat: float | None = Field(default=None, ge=-90, le=90)
    lon: float | None = Field(default=None, ge=-180, le=180)
    precision_m: float | None = Field(default=None, ge=0, le=100000)
    fuente: str = Field(default="ha_companion", max_length=32)


@app.post("/ha/presencia")
def ha_presencia(body: PresenciaRequest, request: Request, token: str = ""):
    """HA manda aquí cada cambio de zona Y un aviso periódico de refresco.

    Los dos hacen falta: solo con los cambios, un dato se quedaría vigente durante
    horas sin que nadie confirme que HA sigue vivo, y el TTL nunca podría distinguir
    "sigues en casa" de "HA se cayó". El periódico es el que hace que el silencio
    signifique algo.
    """
    if not _token_ok(_extract_service_token(request, token), HA_POLL_TOKEN):
        raise HTTPException(status_code=403, detail="Forbidden")

    zona    = body.zona.strip() or "desconocida"
    en_casa = body.en_casa if body.en_casa is not None else zona.lower() in ZONAS_CASA
    ahora   = datetime.now(timezone.utc)

    # El tramo que acaba ahora se atribuye a donde se estaba ANTES, no a donde se está.
    anterior = _leer_presencia()
    if anterior:
        try:
            desde = datetime.fromisoformat((anterior.get("updated_at") or "").replace("Z", "+00:00"))
            if desde.tzinfo is None:
                desde = desde.replace(tzinfo=timezone.utc)
            _acumular_presencia(desde, ahora, bool(anterior.get("en_casa")))
        except (ValueError, AttributeError):
            logger.warning("Presencia: updated_at anterior ilegible, no se acumula el tramo")

    fila = {
        "id":          PRESENCE_ID,
        "zona":        zona,
        "en_casa":     en_casa,
        "lat":         body.lat,
        "lon":         body.lon,
        "precision_m": body.precision_m,
        "fuente":      body.fuente,
        "updated_at":  ahora.isoformat(),
    }
    r = http.post(
        f"{PRESENCE_URL}?on_conflict=id",
        headers={**supabase_headers(), "Prefer": "return=minimal,resolution=merge-duplicates"},
        json=[fila],
    )
    # Quien llama es una automatización de HA que no mira el cuerpo: un fallo de
    # escritura tiene que salir como error HTTP, no escondido en una clave del JSON.
    if r.status_code >= 300:
        logger.error("Presencia: no se pudo guardar (%s)", r.status_code)
        raise _supabase_error(r)

    _cachear_presencia({k: v for k, v in fila.items() if k != "id"})
    return {"ok": True, "zona": zona, "en_casa": en_casa}


@app.get("/presencia")
def get_presencia(credentials: HTTPAuthorizationCredentials = Depends(verify_token)):
    """Lo que pinta la fila de presencia del panel de estado. Devuelve el dato aunque
    esté caducado, marcándolo: "hace 6 h en casa" y "no se sabe" son cosas distintas y
    el panel tiene que poder decir cuál de las dos es."""
    p = _leer_presencia()
    if not p:
        return {"conocida": False}
    edad = _edad_presencia(p)
    return {
        "conocida":     True,
        "zona":         p.get("zona"),
        "en_casa":      bool(p.get("en_casa")),
        "hace_minutos": round(edad) if edad is not None else None,
        "vigente":      edad is not None and edad <= PRESENCE_TTL_MINUTES,
        "ttl_minutos":  PRESENCE_TTL_MINUTES,
        "tiene_coords": p.get("lat") is not None and p.get("lon") is not None,
    }


# ── RESUMEN DIARIO POR CORREO ─────────────────────────────────────────────────
# Reúne agenda, clima, salud y entrenamiento del día y los manda por correo COMO
# DATOS CRUDOS, sin interpretarlos. El consumidor es la rutina de Claude Code que
# compone el correo diario del usuario: lee su buzón, así que la vía de entrada tiene
# que ser un email, no una llamada a la API.
#
# Deliberadamente NO hay conclusiones aquí. El motor de conclusiones
# (`healthConclusions` y compañía) vive en src/lib/helpers.js, es JavaScript y son
# ~135 líneas de reglas; portarlo a Python lo duplicaría en dos lenguajes y el propio
# CLAUDE.md marca ese fichero como única fuente de verdad. Quien lee este correo ya es
# un modelo capaz de sacar las conclusiones por su cuenta.

# (clave de salida, nombres posibles en health_metrics, unidad)
_BRIEF_METRICAS = (
    ("hrv",         ("heart_rate_variability", "heartRateVariability"), "ms"),
    ("fc_reposo",   ("resting_heart_rate",),                            "bpm"),
    ("respiracion", ("respiratory_rate",),                              "rpm"),
    ("pasos",       ("step_count", "steps"),                            "pasos"),
    ("ejercicio",   ("apple_exercise_time", "exercise_time"),           "min"),
    ("peso",        ("weight_body_mass", "weight"),                     "kg"),
    ("vo2max",      ("vo2_max", "cardioFitness"),                       "ml/kg/min"),
)


def _horas_sueno(fila: dict) -> float:
    """Horas de sueño efectivas de una fila de health_metrics.

    Mismo criterio que `_sleepHours` en src/lib/helpers.js: si cambia la forma en que
    llegan los datos del Watch, hay que tocar los dos. Es forma del dato, no regla de
    negocio — las conclusiones siguen viviendo solo en el frontend.
    """
    try:
        if fila.get("value") and float(fila["value"]) > 0:
            return float(fila["value"])
    except (TypeError, ValueError):
        pass
    extra = fila.get("extra") or {}

    def _num(clave):
        try:
            return float(extra.get(clave) or 0)
        except (TypeError, ValueError):
            return 0.0

    if _num("asleep") > 0:
        return _num("asleep")
    return sum(_num(k) for k in ("deep", "rem", "light", "core"))


def _media(valores: list) -> float | None:
    return round(sum(valores) / len(valores), 2) if valores else None


def _dias_hasta(iso: str) -> int | None:
    """Días desde hoy hasta una fecha ISO-UTC, contados en la zona del usuario."""
    try:
        fecha = datetime.fromisoformat(iso.replace("Z", "+00:00")).astimezone(LOCAL_TZ).date()
    except (ValueError, AttributeError, TypeError):
        return None
    return (fecha - datetime.now(LOCAL_TZ).date()).days


def _brief_salud() -> dict:
    """Últimos valores y medias de 7/30 días de las métricas del Watch.

    Un solo viaje a Supabase: se traen 30 días y se agrupa en memoria.
    """
    desde = (datetime.now(LOCAL_TZ) - timedelta(days=30)).strftime("%Y-%m-%d")
    r = http.get(
        f"{SUPABASE_URL}/rest/v1/health_metrics?metric_date=gte.{desde}"
        f"&select=metric_date,metric_name,value,unit,extra&order=metric_date.asc&limit=5000",
        headers=supabase_headers(),
    )
    if r.status_code >= 300:
        logger.error("Resumen diario: no se pudieron leer las métricas de salud (%s)", r.status_code)
        return {}

    por_nombre: dict = {}
    for fila in r.json():
        por_nombre.setdefault(fila["metric_name"], []).append(fila)

    salud: dict = {}

    for clave, nombres, unidad in _BRIEF_METRICAS:
        filas = next((por_nombre[n] for n in nombres if por_nombre.get(n)), [])
        validas = []
        for f in filas:
            try:
                v = float(f["value"])
            except (TypeError, ValueError, KeyError):
                continue
            if v > 0:
                validas.append({"fecha": f["metric_date"], "valor": v})
        if not validas:
            continue
        salud[clave] = {
            "unidad":    unidad,
            "ultimo":    validas[-1]["valor"],
            "fecha":     validas[-1]["fecha"],
            "media_7d":  _media([d["valor"] for d in validas[-7:]]),
            "media_30d": _media([d["valor"] for d in validas]),
        }

    # Sueño: valor derivado y respetando las noches que el usuario anuló a mano.
    noches = []
    for f in next((por_nombre[n] for n in ("sleep_analysis", "sleep") if por_nombre.get(n)), []):
        if (f.get("extra") or {}).get("excluded"):
            continue
        horas = _horas_sueno(f)
        if horas > 0:
            noches.append({"fecha": f["metric_date"], "valor": round(horas, 2),
                           "inicio": (f.get("extra") or {}).get("sleep_start")})
    if noches:
        salud["sueno"] = {
            "unidad":    "h",
            "ultimo":    noches[-1]["valor"],
            "fecha":     noches[-1]["fecha"],
            "inicio":    noches[-1]["inicio"],
            "media_7d":  _media([d["valor"] for d in noches[-7:]]),
            "media_30d": _media([d["valor"] for d in noches]),
        }

    # Entrenos del Watch: cuántos días desde el último.
    entrenos = next((por_nombre[n] for n in ("workouts", "workout") if por_nombre.get(n)), [])
    fechas = sorted({f["metric_date"] for f in entrenos})
    if fechas:
        try:
            ultima = datetime.strptime(fechas[-1], "%Y-%m-%d").date()
            salud["ultimo_entreno"] = {
                "fecha": fechas[-1],
                "dias":  (datetime.now(LOCAL_TZ).date() - ultima).days,
            }
        except ValueError:
            pass

    return salud


def _sin_error(resultado, clave: str) -> list:
    """Lista de eventos de un endpoint de calendario, o [] si devolvió error.

    Los endpoints de calendario devuelven {"error": ...} en vez de lanzar cuando Graph
    falla o no hay sesión: un fallo de Outlook no debe tumbar el resumen entero, el
    resto de secciones siguen siendo útiles.
    """
    if not isinstance(resultado, dict) or "error" in resultado:
        return []
    return resultado.get(clave) or []


def construir_brief() -> dict:
    """Reúne todo lo que va en el correo. Las cuatro fuentes son independientes, así
    que se piden en paralelo: esto corre con el arranque en frío de Fly por delante."""
    # Se llaman las funciones de los endpoints directamente (credentials=None): ninguna
    # usa ese parámetro, lo resuelve FastAPI solo cuando entra por HTTP. Así el resumen
    # hereda la normalización de fechas, el filtrado de alud_url y el manejo de errores
    # que ya tienen, en vez de duplicar sus consultas.
    with ThreadPoolExecutor(max_workers=6) as pool:
        f_eventos = pool.submit(get_events, credentials=None)
        f_clases  = pool.submit(get_class_events, credentials=None)
        f_clima   = pool.submit(_brief_clima)
        f_salud   = pool.submit(_brief_salud)
        f_entren  = pool.submit(_brief_entrenamiento)
        f_presen  = pool.submit(_brief_presencia)
        eventos = _sin_error(f_eventos.result(), "events")
        clases  = _sin_error(f_clases.result(), "events")
        clima, salud, entrenamiento = f_clima.result(), f_salud.result(), f_entren.result()
        presencia = f_presen.result()

    hoy = datetime.now(LOCAL_TZ).date()

    def _es_hoy(ev):
        d = _dias_hasta(ev.get("start", ""))
        return d == 0

    def _limpio(ev):
        return {
            "titulo": ev.get("title") or "(sin título)",
            "inicio": ev.get("start"),
            "fin":    ev.get("end"),
            "lugar":  ev.get("location") or None,
            "todo_el_dia": bool(ev.get("isAllDay")),
        }

    agenda = sorted(
        [_limpio(e) for e in eventos if _es_hoy(e)],
        key=lambda e: e["inicio"] or "",
    )
    clases_hoy = sorted(
        [_limpio(e) for e in clases if _es_hoy(e)],
        key=lambda e: e["inicio"] or "",
    )

    # Entregas: mismo criterio que el widget del dashboard (marcador en el título,
    # de hoy en adelante), acotado a BRIEF_DIAS_ENTREGAS para que el correo no crezca.
    entregas = []
    for ev in [*eventos, *clases]:
        titulo = ev.get("title") or ""
        if ENTREGAS_MARKER not in titulo:
            continue
        dias = _dias_hasta(ev.get("start", ""))
        if dias is None or dias < 0 or dias > BRIEF_DIAS_ENTREGAS:
            continue
        entregas.append({
            "titulo": titulo.replace(ENTREGAS_MARKER, "").strip() or "(sin título)",
            "dias":   dias,
            "fecha":  (ev.get("start") or "")[:10],
        })
    entregas.sort(key=lambda e: e["dias"])

    return {
        "fecha":         hoy.isoformat(),
        "dia_semana":    DIAS_SEMANA[hoy.weekday()],
        "zona":          TIMEZONE,
        "agenda":        agenda,
        "clases":        clases_hoy,
        "entregas":      entregas,
        "clima":         clima,
        "salud":         salud,
        "entrenamiento": entrenamiento,
        "presencia":     presencia,
    }


def _brief_clima() -> dict:
    try:
        datos = get_weather(credentials=None)
    except HTTPException as e:
        logger.error("Resumen diario: clima no disponible (%s)", e.detail)
        return {}
    return {
        "ahora":       datos.get("temp"),
        "max":         datos.get("temp_max"),
        "min":         datos.get("temp_min"),
        "codigo_wmo":  datos.get("code"),
        "sensacion":   datos.get("feels_like"),
        "humedad":     datos.get("humidity"),
        "viento":      datos.get("wind"),
        "lluvia_prob": (datos.get("daily") or [{}])[0].get("precip_prob"),
    }


def _brief_presencia() -> dict:
    """Dónde estás ahora y cuántas horas has estado en casa hoy y ayer.

    Va en el correo porque es contexto que cambia cómo se leen el resto de los datos:
    un día de 3.000 pasos con doce horas fuera no significa lo mismo que uno con doce
    horas en casa. Nunca sale un lugar concreto: la zona (que la nombras tú en HA) y
    horas, nada de coordenadas."""
    ahora = _leer_presencia()
    salida: dict = {}
    if ahora:
        edad = _edad_presencia(ahora)
        salida.update({
            "zona":         ahora.get("zona"),
            "en_casa":      bool(ahora.get("en_casa")),
            "hace_minutos": round(edad) if edad is not None else None,
            "vigente":      edad is not None and edad <= PRESENCE_TTL_MINUTES,
        })

    hoy   = datetime.now(LOCAL_TZ).date()
    ayer  = hoy - timedelta(days=1)
    r = http.get(
        f"{SUPABASE_URL}/rest/v1/health_metrics"
        f"?metric_name=eq.{PRESENCE_METRIC}&metric_date=gte.{ayer.isoformat()}"
        "&select=metric_date,value,extra",
        headers=supabase_headers(),
    )
    if r.status_code >= 300:
        logger.error("Resumen diario: horas en casa no disponibles (%s)", r.status_code)
        return salida
    por_fecha = {fila["metric_date"]: fila for fila in r.json()}
    for clave, fecha in (("horas_casa_hoy", hoy), ("horas_casa_ayer", ayer)):
        fila = por_fecha.get(fecha.isoformat())
        if fila:
            salida[clave] = round(float(fila.get("value") or 0), 1)
            salida[clave.replace("casa", "fuera")] = round(float((fila.get("extra") or {}).get("fuera") or 0), 1)
    return salida


def _brief_entrenamiento() -> dict:
    try:
        resumen = training_summary(credentials=None)
    except HTTPException as e:
        logger.error("Resumen diario: entrenamiento no disponible (%s)", e.detail)
        return {}
    if not resumen.get("client"):
        return {}
    return {
        "sesiones_desde_cobro": resumen.get("sessions_since_payment"),
        "horas_desde_cobro":    resumen.get("hours_since_payment"),
        "importe_pendiente":    resumen.get("amount_owed"),
        "sesiones_por_cobro":   resumen.get("sessions_per_payment"),
        "ultimo_cobro":         resumen.get("last_payment_date"),
        "ultima_sesion":        resumen.get("last_session_date"),
    }


def _hora_local(iso: str | None) -> str:
    if not iso:
        return "--:--"
    try:
        return datetime.fromisoformat(iso.replace("Z", "+00:00")).astimezone(LOCAL_TZ).strftime("%H:%M")
    except (ValueError, AttributeError):
        return "--:--"


def render_brief_texto(d: dict) -> str:
    """Texto plano del correo. Datos etiquetados, sin interpretar: lo lee un modelo
    que redacta el correo diario, y de paso es legible si lo abres tú."""
    L = [
        f"Datos de Life Assistant — {d['dia_semana']} {d['fecha']} ({d['zona']})",
        "",
        "Son datos crudos, sin interpretar, para el resumen diario.",
        "",
    ]

    def _lineas_eventos(items):
        if not items:
            return ["  (nada)"]
        salida = []
        for e in items:
            cuando = "todo el día" if e["todo_el_dia"] else f"{_hora_local(e['inicio'])}-{_hora_local(e['fin'])}"
            lugar = f"  [{e['lugar']}]" if e["lugar"] else ""
            salida.append(f"  {cuando}  {e['titulo']}{lugar}")
        return salida

    L.append("## AGENDA DE HOY")
    L += _lineas_eventos(d["agenda"])
    L.append("")
    L.append("## CLASES DE HOY")
    L += _lineas_eventos(d["clases"])
    L.append("")

    L.append(f"## ENTREGAS (próximos {BRIEF_DIAS_ENTREGAS} días)")
    if d["entregas"]:
        for e in d["entregas"]:
            cuando = "hoy" if e["dias"] == 0 else "mañana" if e["dias"] == 1 else f"en {e['dias']} días"
            L.append(f"  {e['titulo']} — {cuando} ({e['fecha']})")
    else:
        L.append("  (nada)")
    L.append("")

    c = d["clima"]
    L.append("## CLIMA")
    if c:
        L.append(
            f"  Ahora {c.get('ahora')}°, máx {c.get('max')}°, mín {c.get('min')}°, "
            f"código WMO {c.get('codigo_wmo')}"
        )
        L.append(
            f"  Sensación {c.get('sensacion')}°, humedad {c.get('humedad')}%, "
            f"viento {c.get('viento')} km/h, prob. lluvia {c.get('lluvia_prob')}%"
        )
    else:
        L.append("  (no disponible)")
    L.append("")

    p = d.get("presencia") or {}
    L.append("## UBICACIÓN")
    if p.get("zona"):
        estado = "en casa" if p.get("en_casa") else f"fuera ({p['zona']})"
        visto  = f"hace {p['hace_minutos']} min" if p.get("hace_minutos") is not None else "sin fecha"
        L.append(f"  Ahora {estado} — dato de {visto}{'' if p.get('vigente') else ' (CADUCADO, puede haber cambiado)'}")
    else:
        L.append("  (sin datos de presencia)")
    if p.get("horas_casa_hoy") is not None:
        L.append(f"  Hoy  {p['horas_casa_hoy']} h en casa · {p.get('horas_fuera_hoy', 0)} h fuera")
    if p.get("horas_casa_ayer") is not None:
        L.append(f"  Ayer {p['horas_casa_ayer']} h en casa · {p.get('horas_fuera_ayer', 0)} h fuera")
    L.append("")

    s = d["salud"]
    L.append("## SALUD  (último · media 7d · media 30d)")
    if s:
        etiquetas = [
            ("sueno",       "Sueño anoche"),
            ("hrv",         "HRV"),
            ("fc_reposo",   "FC en reposo"),
            ("respiracion", "Frec. respiratoria"),
            ("pasos",       "Pasos"),
            ("ejercicio",   "Min. ejercicio"),
            ("peso",        "Peso"),
            ("vo2max",      "VO2 máx"),
        ]
        for clave, etiqueta in etiquetas:
            m = s.get(clave)
            if not m:
                continue
            L.append(
                f"  {etiqueta:<20} {m['ultimo']} {m['unidad']}"
                f"   (7d: {m['media_7d']}, 30d: {m['media_30d']})   [{m['fecha']}]"
            )
        if s.get("sueno", {}).get("inicio"):
            L.append(f"  {'Se acostó a las':<20} {s['sueno']['inicio']}")
        if s.get("ultimo_entreno"):
            ue = s["ultimo_entreno"]
            dias = ue["dias"]
            cuando = "hoy" if dias == 0 else "ayer" if dias == 1 else f"hace {dias} días"
            L.append(f"  {'Último entreno':<20} {cuando} ({ue['fecha']})")
    else:
        L.append("  (sin datos)")
    L.append("")

    t = d["entrenamiento"]
    L.append("## ENTRENAMIENTO PERSONAL (cliente)")
    if t:
        L.append(
            f"  {t.get('sesiones_desde_cobro')} sesiones desde el último cobro "
            f"({t.get('horas_desde_cobro')} h) — {t.get('importe_pendiente')} €"
        )
        L.append(
            f"  Cobra cada {t.get('sesiones_por_cobro')} sesiones · "
            f"último cobro {t.get('ultimo_cobro') or 'nunca'} · "
            f"última sesión {t.get('ultima_sesion') or '—'}"
        )
    else:
        L.append("  (sin cliente configurado)")

    return "\n".join(L) + "\n"


def enviar_correo(asunto: str, cuerpo: str):
    """Envía por SMTP con la librería estándar: no hace falta ninguna dependencia
    nueva ni una cuenta en un servicio de envío. Con Gmail, usa una contraseña de
    aplicación en SMTP_PASSWORD (la normal no sirve si tienes 2FA)."""
    faltan = [n for n, v in (
        ("SMTP_HOST", SMTP_HOST), ("SMTP_USER", SMTP_USER),
        ("SMTP_PASSWORD", SMTP_PASSWORD), ("BRIEF_TO", BRIEF_TO),
    ) if not v]
    if faltan:
        raise HTTPException(
            status_code=503,
            detail=f"Envío de correo no configurado: falta {', '.join(faltan)}",
        )
    msg = EmailMessage()
    msg["Subject"] = asunto
    msg["From"] = BRIEF_FROM or SMTP_USER
    msg["To"] = BRIEF_TO
    msg.set_content(cuerpo)
    # 465 abre TLS desde el principio (SMTPS); 587 empieza en claro y sube con
    # STARTTLS. Gmail acepta los dos. Con timeout: sin él, un SMTP que no responde
    # retiene el hilo igual que una llamada HTTP colgada.
    if SMTP_PORT == 465:
        with smtplib.SMTP_SSL(SMTP_HOST, SMTP_PORT, timeout=HTTP_TIMEOUT) as smtp:
            smtp.login(SMTP_USER, SMTP_PASSWORD)
            smtp.send_message(msg)
    else:
        with smtplib.SMTP(SMTP_HOST, SMTP_PORT, timeout=HTTP_TIMEOUT) as smtp:
            smtp.starttls()
            smtp.login(SMTP_USER, SMTP_PASSWORD)
            smtp.send_message(msg)


# ── DESPERTAR: CUÁNDO SALE EL RESUMEN ─────────────────────────────────────────
#
# El correo ya no sale a una hora fija, sino cuando te despiertas — y si nadie avisa
# de que te has despertado, a BRIEF_HORA_TOPE como muy tarde.
#
# El disparador ya no puede ser el cron de GitHub Actions: se retrasa 10-15 min
# cuando su cola va cargada, así que el correo llegaba tarde y a una hora distinta
# cada día. Actions queda solo como red de seguridad por si se cae la casa entera, y
# el reloj puntual lo pone Home Assistant, que está siempre encendido y ya sondea
# este backend. Un hilo de fondo aquí dentro no serviría: Fly escala a cero, y sin
# nadie que llame no hay proceso vivo que pueda mirar el reloj.
#
# Ojo con la intuición de "el reloj sabe cuándo me despierto": el Watch lo sabe, pero
# el backend no se entera hasta que el iPhone sincroniza. De ahí que haya dos fuentes
# y gane la que llegue antes.

BRIEF_ENVIOS_URL = f"{SUPABASE_URL}/rest/v1/brief_envios"


def _hora_config(valor: str, defecto: tuple) -> tuple:
    """"HH:MM" → (hora, minuto). Una hora mal escrita cae al defecto en vez de tumbar
    el arranque: dejar el dashboard entero sin backend por la hora de un correo sería
    peor que ignorar la variable."""
    m = re.fullmatch(r"\s*(\d{1,2}):(\d{2})\s*", valor or "")
    if not m or int(m.group(1)) > 23 or int(m.group(2)) > 59:
        logger.warning("Resumen diario: hora '%s' ilegible, se usa %02d:%02d", valor, *defecto)
        return defecto
    return int(m.group(1)), int(m.group(2))


HORA_DESPERTAR_DESDE = _hora_config(BRIEF_DESPERTAR_DESDE, (5, 30))
HORA_DESPERTAR_HASTA = _hora_config(BRIEF_DESPERTAR_HASTA, (11, 30))
HORA_TOPE            = _hora_config(BRIEF_HORA_TOPE, (10, 0))
HORA_RUTINA          = _hora_config(BRIEF_RUTINA_DESDE, (8, 0))


def _lanzar_rutina(fecha: str, ahora: datetime) -> None:
    """Arranca la rutina que lee este correo y redacta el briefing.

    Reparto de trabajo entre los dos triggers de la rutina, que existe porque las dos
    situaciones piden cosas distintas:
      - Te despiertas PRONTO → el correo de datos sale pronto, pero el briefing no debe
        redactarse aún: recoge newsletters que a las 6 de la mañana no han llegado. De
        eso se encarga el trigger de HORARIO de la propia rutina, y aquí no hacemos nada.
      - Te despiertas TARDE → esperar al reloj significaría redactar el briefing sin los
        datos del día, o con horas de retraso. Ahí dispara este.

    Nunca puede tumbar el envío: cuando se llega aquí el correo YA ha salido, que es lo
    que de verdad importa. Un fallo se registra y se sigue — la rutina siempre puede
    ejecutarse a mano, y el correo con los datos está en el buzón de todos modos.
    """
    if not RUTINA_FIRE_URL or not RUTINA_FIRE_TOKEN:
        return
    if (ahora.hour, ahora.minute) < HORA_RUTINA:
        return

    try:
        r = http.post(
            RUTINA_FIRE_URL,
            headers={
                "Authorization":     f"Bearer {RUTINA_FIRE_TOKEN}",
                "anthropic-version": "2023-06-01",
                "anthropic-beta":    RUTINA_BETA,
                "Content-Type":      "application/json",
            },
            # `text` llega a la rutina envuelto y etiquetado como dato no fiable, así que
            # es contexto para el registro de la sesión, no una instrucción: la rutina no
            # debe depender de él para saber qué hacer.
            json={"text": f"El correo de datos del {fecha} acaba de salir."},
        )
        if r.status_code >= 300:
            logger.error("Rutina del briefing: el disparo devolvió %s", r.status_code)
        else:
            logger.info("Rutina del briefing lanzada tras el correo del %s", fecha)
    except requests.RequestException:
        logger.exception("Rutina del briefing: no se pudo lanzar el disparo")


def _reservar_envio(fecha: str, fuente: str, despertar: Optional[datetime]) -> bool:
    """Marca el día como enviado. True si la reserva es nuestra, False si ya estaba.

    Se reserva ANTES de mandar el correo, y con un INSERT normal en vez de un upsert
    con merge-duplicates a propósito: el 409 contra la clave primaria es lo que hace
    la comprobación atómica. Comprobándolo con un GET previo, dos disparadores que
    coincidan en el mismo minuto (el móvil al desenchufarse y el sondeo de HA) leerían
    los dos "no enviado" y mandarían dos correos.
    """
    fila = {
        "fecha":      fecha,
        "fuente":     fuente,
        "enviado_at": datetime.now(timezone.utc).isoformat(),
    }
    if despertar is not None:
        fila["despertar_at"] = despertar.astimezone(timezone.utc).isoformat()
    r = http.post(
        BRIEF_ENVIOS_URL,
        headers={**supabase_headers(), "Prefer": "return=minimal"},
        json=[fila],
    )
    if r.status_code == 409:
        return False
    if r.status_code >= 300:
        logger.error("Resumen diario: no se pudo reservar el envío del %s (%s)", fecha, r.status_code)
        raise _supabase_error(r)
    return True


def _liberar_envio(fecha: str) -> None:
    """Retira la reserva cuando el correo no ha llegado a salir.

    Sin esto, un fallo de SMTP o de Supabase dejaría el día marcado como enviado y
    ningún disparador posterior lo reintentaría: un error transitorio de un minuto te
    costaría el briefing de todo el día.
    """
    try:
        r = http.delete(
            f"{BRIEF_ENVIOS_URL}?fecha=eq.{fecha}",
            headers={**supabase_headers(), "Prefer": "return=minimal"},
        )
        if r.status_code >= 300:
            logger.error(
                "Resumen diario: la reserva del %s se quedó puesta tras fallar el envío (%s). "
                "Hoy ya no se reintentará solo", fecha, r.status_code,
            )
    except requests.RequestException:
        logger.exception("Resumen diario: no se pudo liberar la reserva del %s", fecha)


def _ahora_local() -> datetime:
    """Punto único de "ahora" para todo el disparo del resumen. Existe para que los
    tests puedan fijar la hora sin tocar el reloj del módulo entero: aquí casi todas
    las decisiones dependen de qué hora es, y no habría forma de probarlas si no."""
    return datetime.now(LOCAL_TZ)


def _senal_de_despertar_valida(ahora: datetime) -> bool:
    """Si una señal a esta hora cuenta como haberse despertado.

    La ventana es propiedad de la SEÑAL, no del envío: la red de seguridad y la hora
    tope disparan por definición fuera de ella y no deben pasar por aquí.

    Tiene los dos extremos y cada uno protege de una cosa distinta: el suelo, de tomarse
    por despertar un desenchufe de madrugada camino del baño; el techo, de que una señal
    de media tarde mande el correo del día cuando ya no sirve de nada.
    """
    hm = (ahora.hour, ahora.minute)
    return HORA_DESPERTAR_DESDE <= hm <= HORA_DESPERTAR_HASTA


def enviar_brief_si_toca(fuente: str, despertar: Optional[datetime] = None) -> dict:
    """Manda el resumen del día si aún no ha salido. Idempotente por día.

    Única puerta de entrada al envío automático: la usan la señal de despertar del
    móvil, la llegada del sueño del Watch y el reloj de respaldo de HA. Cada uno sabe
    CUÁNDO llamar; el que decide SI se manda es este.
    """
    ahora = _ahora_local()
    fecha = ahora.date().isoformat()

    if not _reservar_envio(fecha, fuente, despertar):
        return {"enviado": False, "motivo": "el resumen de hoy ya se envió"}

    try:
        datos = construir_brief()
        enviar_correo(f"Life Assistant — datos del {datos['fecha']}", render_brief_texto(datos))
    except Exception:
        _liberar_envio(fecha)
        raise

    logger.info("Resumen diario enviado a %s (%s), disparado por: %s", BRIEF_TO, datos["fecha"], fuente)
    _lanzar_rutina(datos["fecha"], ahora)
    return {"enviado": True, "fecha": datos["fecha"], "fuente": fuente}


def _avisar_sueno_recibido(fechas_sueno: set) -> None:
    """Acaba de llegar el sueño de esta noche: si el Watch ya la ha cerrado y
    sincronizado, lo probable es que estés despierto.

    Es una deducción, no un aviso, y por eso lleva dos frenos: solo cuentan las noches
    de hoy y ayer (el Atajo reenvía los últimos días en cada sync, y un backfill de la
    semana pasada no significa nada), y el envío vuelve a comprobar la ventana horaria.
    Aun así puede adelantarse si el iPhone sincroniza una noche a medias mientras
    duermes: se puede desactivar con BRIEF_DISPARA_SUENO=0 y quedarse solo con la
    señal del móvil, que sí es exacta.

    Nunca puede tumbar la ingesta: guardar los datos del Watch importa más que el
    correo, y el correo tiene otras dos fuentes que lo disparan.
    """
    if not BRIEF_DISPARA_SUENO or not fechas_sueno:
        return
    ahora = _ahora_local()
    recientes = {ahora.date().isoformat(), (ahora.date() - timedelta(days=1)).isoformat()}
    if not (set(fechas_sueno) & recientes) or not _senal_de_despertar_valida(ahora):
        return
    try:
        enviar_brief_si_toca("sueno", despertar=ahora)
    except Exception:
        logger.exception("Resumen diario: fallo al enviarlo tras recibir el sueño del Watch")


@app.post("/despertar")
def marcar_despertar(request: Request, token: str = "", fuente: str = ""):
    """Alguien avisa de que ya estás despierto — el Atajo del iPhone al desenchufar el
    cargador, o una automatización de HA. Si el resumen de hoy no ha salido aún, sale
    ahora.

    Va con BRIEF_TOKEN y no con un JWT de usuario: lo llama una máquina que arranca
    sola, y un JWT caduca a los 30 días y dejaría de funcionar sin avisar a nadie
    (ya pasó con el agente PC).
    """
    if not _token_ok(_extract_service_token(request, token), BRIEF_TOKEN):
        raise HTTPException(status_code=403, detail="Forbidden")

    # La etiqueta acaba en una fila de Supabase: se limpia en vez de confiar en ella.
    etiqueta = re.sub(r"[^a-zA-Z0-9_-]", "", fuente)[:40] or "despertar"
    ahora    = _ahora_local()

    # Fuera de la ventana no cuenta: ni un desenchufe de las 04:00 camino del baño, ni
    # uno de media tarde cuando el correo del día ya no aporta nada.
    if not _senal_de_despertar_valida(ahora):
        return {"ok": True, "enviado": False,
                "motivo": f"fuera de la ventana de despertar "
                          f"({HORA_DESPERTAR_DESDE[0]:02d}:{HORA_DESPERTAR_DESDE[1]:02d}"
                          f"–{HORA_DESPERTAR_HASTA[0]:02d}:{HORA_DESPERTAR_HASTA[1]:02d})"}
    try:
        resultado = enviar_brief_si_toca(etiqueta, despertar=ahora)
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("Despertar: fallo al construir o enviar el resumen")
        raise HTTPException(status_code=502, detail=f"No se pudo enviar el resumen: {e}")
    return {"ok": True, **resultado}


@app.post("/ha/brief-tick")
def ha_brief_tick(request: Request, token: str = ""):
    """El reloj de respaldo, que sondea HA cada pocos minutos.

    Solo hace algo pasada BRIEF_HORA_TOPE: si a esa hora no ha habido ninguna señal de
    despertar, se asume que la señal falló (móvil descargado, Atajo desactivado) y se
    manda el correo igual. Antes de esa hora no hace nada y contesta en un suspiro —
    que es lo que permite sondearlo a menudo sin coste.

    Es HA quien pone el reloj porque está siempre encendido y es puntual al minuto,
    las dos cosas que el cron de Actions no garantiza.
    """
    if not _token_ok(_extract_service_token(request, token), HA_POLL_TOKEN):
        raise HTTPException(status_code=403, detail="Forbidden")

    ahora = _ahora_local()
    if (ahora.hour, ahora.minute) < HORA_TOPE:
        return {"enviado": False, "motivo": "aún no es la hora tope"}

    try:
        resultado = enviar_brief_si_toca("tope")
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("Resumen diario: fallo al enviarlo por hora tope")
        raise HTTPException(status_code=502, detail=f"No se pudo enviar el resumen: {e}")
    return {"ok": True, **resultado}


@app.get("/brief")
def get_brief(credentials: HTTPAuthorizationCredentials = Depends(verify_token)):
    """Los mismos datos que van en el correo, en JSON. Para comprobar qué se enviaría
    sin tener que esperar al disparador de la mañana."""
    return construir_brief()


@app.post("/brief/send")
def send_brief(request: Request, token: str = "", forzar: int = 0):
    """Compone el resumen y lo manda por correo, si hoy no ha salido ya.

    Lo llama la red de seguridad (.github/workflows/resumen-diario.yml), que es una
    máquina: token de servicio dedicado, igual que HA y la ingesta de salud — un JWT
    de usuario caducaría a los 30 días y el correo dejaría de llegar sin avisar.

    Pasa por `enviar_brief_si_toca` como todo lo demás, así que llegar tarde y
    encontrarse el correo ya enviado no duplica nada: contesta que no hacía falta. Con
    `?forzar=1` se salta esa comprobación, que es como se prueba el correo a mano sin
    esperar a mañana ni tener que borrar la fila del día.
    """
    if not _token_ok(_extract_service_token(request, token), BRIEF_TOKEN):
        raise HTTPException(status_code=403, detail="Forbidden")
    # Sin este try/except, cualquier fallo (Graph, Supabase, SMTP) subía sin capturar
    # y el disparador solo veía un "Internal Server Error" genérico y sin detalle —
    # nada que distinguir un problema de Outlook de uno de credenciales SMTP. El
    # llamador es el workflow de GitHub Actions, protegido por BRIEF_TOKEN, no un
    # navegador: el mensaje de la excepción es diagnóstico útil, no un dato sensible.
    try:
        if forzar:
            datos = construir_brief()
            enviar_correo(f"Life Assistant — datos del {datos['fecha']}", render_brief_texto(datos))
            logger.info("Resumen diario enviado a %s (%s), forzado a mano", BRIEF_TO, datos["fecha"])
            return {"ok": True, "enviado": True, "enviado_a": BRIEF_TO, "fecha": datos["fecha"]}
        resultado = enviar_brief_si_toca("respaldo")
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("Resumen diario: fallo inesperado al construir o enviar el correo")
        raise HTTPException(status_code=502, detail=f"No se pudo enviar el resumen: {e}")
    return {"ok": True, "enviado_a": BRIEF_TO, **resultado}


# ── REGISTRO: CONSULTA DESDE EL DASHBOARD ─────────────────────────────────────

@app.get("/logs")
def get_logs(
    nivel: str = "",
    dias: int = 7,
    limite: int = 100,
    credentials: HTTPAuthorizationCredentials = Depends(verify_token),
):
    """Últimas entradas de app_logs, para el panel de estado del sistema."""
    if limite < 1 or limite > 500:
        raise HTTPException(status_code=400, detail="limite debe estar entre 1 y 500")
    if dias < 1 or dias > 90:
        raise HTTPException(status_code=400, detail="dias debe estar entre 1 y 90")
    # `nivel` se interpola en la URL de Supabase (invariante 6): lista blanca, no regex.
    filtro = ""
    if nivel:
        if nivel.upper() not in NIVELES_LOG:
            raise HTTPException(status_code=400, detail="nivel inválido")
        filtro = f"&level=eq.{nivel.upper()}"
    # Volcado inmediato: sin esto, lo que acaba de fallar todavía está en la cola en
    # memoria y el panel lo enseñaría hasta LOG_FLUSH_SECONDS más tarde — justo cuando
    # abres el panel PORQUE algo acaba de fallar.
    _registro.volcar()
    desde = (datetime.now(timezone.utc) - timedelta(days=dias)).isoformat()
    r = http.get(
        f"{SUPABASE_URL}/rest/v1/app_logs"
        f"?created_at=gte.{quote(desde, safe='')}{filtro}"
        f"&select=created_at,level,source,message,context"
        f"&order=created_at.desc&limit={limite}",
        headers=supabase_headers(),
    )
    if r.status_code >= 300:
        raise _supabase_error(r)
    entradas = r.json()
    return {
        "entradas": entradas,
        "errores": sum(1 for e in entradas if e.get("level") in ("ERROR", "CRITICAL")),
    }


@app.delete("/logs")
def borrar_logs(credentials: HTTPAuthorizationCredentials = Depends(verify_token)):
    """Vacía el registro. Para dejarlo limpio y ver si un problema se reproduce."""
    r = http.delete(
        f"{SUPABASE_URL}/rest/v1/app_logs?id=not.is.null",
        headers={**supabase_headers(), "Prefer": "return=minimal"},
    )
    if r.status_code >= 300:
        raise _supabase_error(r)
    return {"ok": True}
