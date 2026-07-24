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
import httpx
import os
import json
import time
import hmac
import logging
import threading
from urllib.parse import quote

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
HA_URL              = os.getenv("HA_URL", "")
HA_TOKEN            = os.getenv("HA_TOKEN")
HA_POLL_TOKEN       = os.getenv("HA_POLL_TOKEN", "")
HEALTH_INGEST_TOKEN = os.getenv("HEALTH_INGEST_TOKEN", "")
# Personalización de la instancia (kit self-hosted)
TIMEZONE         = os.getenv("TIMEZONE", "Europe/Madrid")   # zona horaria IANA del usuario
CLASSES_CALENDAR = os.getenv("CLASSES_CALENDAR", "clases")  # nombre del calendario de clases en Outlook
WEATHER_LAT      = os.getenv("WEATHER_LAT", "40.4168")      # coordenadas para el clima (Open-Meteo)
WEATHER_LON      = os.getenv("WEATHER_LON", "-3.7038")      # por defecto Madrid

try:
    LOCAL_TZ = ZoneInfo(TIMEZONE)
except Exception:
    raise RuntimeError(f"TIMEZONE inválida: {TIMEZONE!r} — usa un nombre IANA, p.ej. Europe/Madrid")

openai_client = OpenAI(api_key=OPENAI_API_KEY)

def supabase_headers():
    return {
        "apikey": SUPABASE_KEY,
        "Authorization": f"Bearer {SUPABASE_KEY}",
        "Content-Type": "application/json",
    }

bearer_scheme = HTTPBearer()

# ── Seguridad: rate limiting del login ────────────────────────────────────────
# Limitador en memoria por IP. Suficiente para un backend de una sola máquina que
# escala a cero; se resetea en cold start, lo cual es aceptable para este caso.
LOGIN_MAX_ATTEMPTS   = int(os.getenv("LOGIN_MAX_ATTEMPTS", "5"))
LOGIN_WINDOW_SECONDS = int(os.getenv("LOGIN_WINDOW_SECONDS", "300"))
_login_attempts: dict = {}
_login_lock = threading.Lock()


def _client_ip(request: Request) -> str:
    fwd = request.headers.get("x-forwarded-for")
    if fwd:
        return fwd.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


def _check_login_rate(ip: str):
    now = time.time()
    with _login_lock:
        attempts = [t for t in _login_attempts.get(ip, []) if now - t < LOGIN_WINDOW_SECONDS]
        _login_attempts[ip] = attempts
        if len(attempts) >= LOGIN_MAX_ATTEMPTS:
            retry = int(LOGIN_WINDOW_SECONDS - (now - attempts[0]))
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail=f"Demasiados intentos. Reintenta en {retry}s",
                headers={"Retry-After": str(max(retry, 1))},
            )


def _register_login_failure(ip: str):
    with _login_lock:
        _login_attempts.setdefault(ip, []).append(time.time())


def _reset_login_attempts(ip: str):
    with _login_lock:
        _login_attempts.pop(ip, None)


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

SCOPES = ["Calendars.ReadWrite", "User.Read"]
OAUTH_PROVIDER = "microsoft_graph"
import json
import re

_UUID_RE = re.compile(
    r'^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$',
    re.IGNORECASE,
)
_SAFE_ID_RE = re.compile(r'^[a-zA-Z0-9_-]{1,64}$')

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

def save_token_data(data: dict):
    """Persiste el token de Microsoft Graph en Supabase (sobrevive a redeploys del backend)."""
    payload = {
        "provider": OAUTH_PROVIDER,
        "access_token": data["access_token"],
        "refresh_token": data.get("refresh_token"),
        "expires_at": data["expires_at"],
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }
    r = requests.get(
        f"{SUPABASE_URL}/rest/v1/oauth_tokens?provider=eq.{OAUTH_PROVIDER}&select=provider",
        headers=supabase_headers(),
    )
    if r.status_code < 300 and r.json():
        requests.patch(
            f"{SUPABASE_URL}/rest/v1/oauth_tokens?provider=eq.{OAUTH_PROVIDER}",
            headers={**supabase_headers(), "Prefer": "return=minimal"},
            json=payload,
        )
    else:
        requests.post(
            f"{SUPABASE_URL}/rest/v1/oauth_tokens",
            headers={**supabase_headers(), "Prefer": "return=minimal"},
            json=payload,
        )

def load_token_data() -> dict | None:
    r = requests.get(
        f"{SUPABASE_URL}/rest/v1/oauth_tokens?provider=eq.{OAUTH_PROVIDER}&select=access_token,refresh_token,expires_at",
        headers=supabase_headers(),
    )
    if r.status_code < 300 and r.json():
        return r.json()[0]
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
    msal_app = msal.ConfidentialClientApplication(
        CLIENT_ID,
        authority="https://login.microsoftonline.com/common",
        client_credential=CLIENT_SECRET,
    )
    result = msal_app.acquire_token_by_refresh_token(refresh_token, scopes=SCOPES)
    if "access_token" in result:
        _store_result(result)
        return result["access_token"]
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
    ip = _client_ip(request)
    _check_login_rate(ip)
    if not hmac.compare_digest(body.password, DASHBOARD_PASSWORD):
        _register_login_failure(ip)
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Contraseña incorrecta")
    _reset_login_attempts(ip)
    return {"token": create_token()}

@app.get("/auth/login")
def login():
    app_msal = msal.ConfidentialClientApplication(
        CLIENT_ID,
        authority="https://login.microsoftonline.com/common",
        client_credential=CLIENT_SECRET,
    )
    auth_url = app_msal.get_authorization_request_url(
        SCOPES,
        redirect_uri=REDIRECT_URI,
    )
    return {"auth_url": auth_url}

@app.get("/auth/callback")
def callback(code: str):
    app_msal = msal.ConfidentialClientApplication(
        CLIENT_ID,
        authority="https://login.microsoftonline.com/common",
        client_credential=CLIENT_SECRET,
    )
    result = app_msal.acquire_token_by_authorization_code(
        code,
        scopes=SCOPES,
        redirect_uri=REDIRECT_URI,
    )
    if "access_token" in result:
        token = result["access_token"]
        # Guardamos el token en memoria por ahora
        app.state.token = token
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
    response = requests.get(
        f"https://graph.microsoft.com/v1.0/me/calendarView?startDateTime={start}&endDateTime={end}&$top=100&$select=subject,start,end,location,body,bodyPreview,isAllDay&$orderby=start/dateTime",
        headers=headers
    )
    response.encoding = "utf-8"
    data = response.json()
    
    events = []
    for event in data.get("value", []):
        body_content = event.get("body", {}).get("content", "") or ""
        preview_content = event.get("bodyPreview", "") or ""
        import re as _re
        # No incluir <, > ni comillas en la URL: en cuerpos HTML la URL suele ir pegada
        # a la etiqueta de cierre (p.ej. ...id=99</p>) y \S+ se la tragaba entera.
        alud_match = _re.search(r"alud_url:\s*(https?://[^\s<>\"']+)", body_content) or \
                     _re.search(r"alud_url:\s*(https?://[^\s<>\"']+)", preview_content)
        alud_url = alud_match.group(1).rstrip("&;.,") if alud_match else None
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
    r = requests.get("https://graph.microsoft.com/v1.0/me/calendars", headers=headers)
    data = r.json()
    return [{"id": c["id"], "name": c["name"]} for c in data.get("value", [])]


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
    url = (
        f"https://graph.microsoft.com/v1.0/me/calendars/{body.calendar_id}/events"
        if body.calendar_id
        else "https://graph.microsoft.com/v1.0/me/events"
    )
    r = requests.post(url, headers=headers, json=payload)
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
    event_id: str,
    body: UpdateEventRequest,
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
    r = requests.patch(
        f"https://graph.microsoft.com/v1.0/me/events/{event_id}",
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
    r = requests.get("https://graph.microsoft.com/v1.0/me/calendars", headers=headers)
    calendars = r.json().get("value", [])
    cal = next((c for c in calendars if c["name"].lower() == CLASSES_CALENDAR.lower()), None)
    if not cal:
        return {"error": "Calendario 'Clases' no encontrado", "available": [c["name"] for c in calendars]}
    cal_id = cal["id"]
    # Inicio del día en hora local del usuario para no perder clases de hoy
    today_start = datetime.now(LOCAL_TZ).replace(hour=0, minute=0, second=0, microsecond=0)
    start = today_start.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    end = (today_start + timedelta(days=60)).astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    r2 = requests.get(
        f"https://graph.microsoft.com/v1.0/me/calendars/{cal_id}/calendarView"
        f"?startDateTime={start}&endDateTime={end}&$top=200"
        f"&$select=subject,start,end,location,isAllDay&$orderby=start/dateTime",
        headers=headers
    )
    r2.encoding = "utf-8"
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
    origin: str = Field(default=HOME_ADDRESS, max_length=500)
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

    # Calcular cuánto tarda en llegar
    url = "https://maps.googleapis.com/maps/api/distancematrix/json"
    params = {
        "origins": body.origin,
        "destinations": body.destination,
        "mode": body.mode,
        "language": "es",
        "key": GOOGLE_MAPS_API_KEY,
    }
    if body.mode == "driving":
        params["departure_time"] = "now"
        params["traffic_model"] = "best_guess"
    r = requests.get(url, params=params)
    data = r.json()

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
    """Clima actual + máx/mín de hoy vía Open-Meteo (gratis, sin API key). Si el
    dispositivo manda lat/lon (geolocalización del navegador) se usan esas; si no,
    caen a WEATHER_LAT/WEATHER_LON. El código WMO lo traduce el frontend a
    icono/texto (helpers.weatherFromCode)."""
    latitude  = lat if lat is not None else WEATHER_LAT
    longitude = lon if lon is not None else WEATHER_LON
    r = requests.get(
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
    r = requests.get(
        f"{SUPABASE_URL}/rest/v1/ideas?order=created_at.desc",
        headers=supabase_headers(),
    )
    return r.json()

@app.delete("/ideas/{idea_id}")
def delete_idea(
    idea_id: str = Path(..., pattern=r'^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$'),
    credentials: HTTPAuthorizationCredentials = Depends(verify_token),
):
    r = requests.delete(
        f"{SUPABASE_URL}/rest/v1/ideas?id=eq.{idea_id}",
        headers=supabase_headers(),
    )
    return {"ok": r.status_code < 300}

def extract_idea_from_text(text: str) -> dict:
    """Extrae key/tag/full_text de un texto libre con GPT-4o mini."""
    completion = openai_client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[
            {
                "role": "system",
                "content": (
                    "Eres un asistente que extrae ideas clave de notas de voz o texto. "
                    "Dado un texto, responde SOLO con un JSON válido con este formato exacto: "
                    '{"key": "Título corto de la idea (máx 8 palabras)", "tag": "una palabra categoría", "full_text": "Resumen claro y completo de la idea en 2-3 frases"}'
                ),
            },
            {"role": "user", "content": text},
        ],
        max_tokens=300,
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
    r = requests.post(
        f"{SUPABASE_URL}/rest/v1/ideas",
        headers={**supabase_headers(), "Prefer": "return=representation"},
        json=payload,
    )
    return r.json()[0] if r.status_code < 300 else payload


@app.post("/ideas/audio")
async def create_idea_from_audio(
    audio: UploadFile = File(...),
    credentials: HTTPAuthorizationCredentials = Depends(verify_token),
):
    # 1. Transcribir con Whisper
    audio_bytes = await audio.read()
    transcript = openai_client.audio.transcriptions.create(
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
    return {"ok": True, "idea": idea, "transcript": text}


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
    return {"ok": True, "idea": idea}


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
    r = requests.get(
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
        "name":     body.name.strip()[:200],
        "price":    body.price,
        "currency": body.currency,
        "photo":    body.photo,
    }
    r = requests.post(
        f"{SUPABASE_URL}/rest/v1/clothing",
        headers={**supabase_headers(), "Prefer": "return=representation"},
        json=payload,
    )
    if r.status_code >= 300:
        raise _supabase_error(r)
    return {"ok": True, "item": r.json()[0]}


@app.delete("/clothing/{item_id}")
def delete_clothing(
    item_id: str = Path(..., pattern=r'^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$'),
    credentials: HTTPAuthorizationCredentials = Depends(verify_token),
):
    r = requests.delete(
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
    response = requests.get(
        "https://graph.microsoft.com/v1.0/me/calendarView"
        f"?startDateTime={now.strftime('%Y-%m-%dT%H:%M:%SZ')}"
        f"&endDateTime={end.strftime('%Y-%m-%dT%H:%M:%SZ')}"
        "&$top=20&$select=subject,start,isAllDay&$orderby=start/dateTime",
        headers=headers,
    )
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
    payload = {"dedupe_key": body.dedupe_key, "payload": body.payload}
    r = requests.post(
        f"{SUPABASE_URL}/rest/v1/jobs",
        headers={**supabase_headers(), "Prefer": "return=representation,resolution=merge-duplicates"},
        json=payload,
    )
    if r.status_code >= 300:
        raise _supabase_error(r)
    data = r.json()
    if data:
        return {"ok": True, "job": data[0]}
    # Conflicto de dedupe: el upsert no devolvió filas — recuperar el job existente
    r2 = requests.get(
        f"{SUPABASE_URL}/rest/v1/jobs?dedupe_key=eq.{body.dedupe_key}&limit=1",
        headers=supabase_headers(),
    )
    data2 = r2.json() if r2.status_code < 300 else []
    return {"ok": True, "job": data2[0] if data2 else None}

_JOB_ID_PATH = Path(..., pattern=r'^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$')

@app.get("/jobs/by-id/{job_id}")
def get_job_by_id(
    job_id: str = _JOB_ID_PATH,
    credentials: HTTPAuthorizationCredentials = Depends(verify_token),
):
    r = requests.get(
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
    credentials: HTTPAuthorizationCredentials = Depends(verify_token),
):
    now_iso = datetime.now(timezone.utc).isoformat()
    worker = _safe_worker(body.worker_id)
    r = requests.patch(
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
    credentials: HTTPAuthorizationCredentials = Depends(verify_token),
):
    worker = _safe_worker(body.worker_id)
    r = requests.patch(
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
    credentials: HTTPAuthorizationCredentials = Depends(verify_token),
):
    if body.status not in ("done", "failed"):
        raise HTTPException(status_code=400, detail="status debe ser done o failed")
    worker = _safe_worker(body.worker_id)
    r = requests.patch(
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
    credentials: HTTPAuthorizationCredentials = Depends(verify_token),
):
    payload = {
        "job_id": job_id,
        "stage": body.stage,
        "message": body.message,
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    r = requests.post(
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
    r = requests.get(
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
    get_r = requests.get(
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

    patch_r = requests.patch(
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
def agent_heartbeat(body: AgentHeartbeatRequest, credentials: HTTPAuthorizationCredentials = Depends(verify_token)):
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
    r = requests.post(
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
    r = requests.get(
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

_DATE_RE = re.compile(r'^\d{4}-\d{2}-\d{2}$')

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
    r = requests.get(
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

    r_pay = requests.get(
        f"{SUPABASE_URL}/rest/v1/training_payments?client_id=eq.{client_id}&order=created_at.desc&limit=1",
        headers=supabase_headers(),
    )
    payments = r_pay.json() if r_pay.status_code < 300 else []
    last_payment = payments[0] if payments else None

    date_filter = f"&created_at=gt.{quote(last_payment['created_at'])}" if last_payment else ""
    r_sess = requests.get(
        f"{SUPABASE_URL}/rest/v1/training_sessions?client_id=eq.{client_id}{date_filter}&order=date.desc",
        headers=supabase_headers(),
    )
    sessions = r_sess.json() if r_sess.status_code < 300 else []

    r_all = requests.get(
        f"{SUPABASE_URL}/rest/v1/training_sessions?client_id=eq.{client_id}&order=date.desc&limit=10",
        headers=supabase_headers(),
    )
    all_sessions = r_all.json() if r_all.status_code < 300 else []

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
    r = requests.post(
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
    r = requests.patch(
        f"{SUPABASE_URL}/rest/v1/training_clients?id=eq.{client['id']}",
        headers={**supabase_headers(), "Prefer": "return=representation"},
        json=patch,
    )
    if r.status_code >= 300:
        raise _supabase_error(r)
    return {"ok": True, "client": r.json()[0]}

@app.delete("/training/sessions/{session_id}")
def delete_training_session(
    session_id: str = Path(..., pattern=r'^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$'),
    credentials: HTTPAuthorizationCredentials = Depends(verify_token),
):
    r = requests.delete(
        f"{SUPABASE_URL}/rest/v1/training_sessions?id=eq.{session_id}",
        headers=supabase_headers(),
    )
    return {"ok": r.status_code < 300}

# ── SALUD (Apple Watch via Health Auto Export) ────────────────────────────────

@app.post("/health/ingest")
async def health_ingest(request: Request, token: str = ""):
    """Health Auto Export envía aquí los datos periódicamente."""
    if not _token_ok(_extract_service_token(request, token), HEALTH_INGEST_TOKEN):
        raise HTTPException(status_code=403, detail="Forbidden")

    body = await request.json()
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
            r = requests.post(
                f"{SUPABASE_URL}/rest/v1/health_metrics",
                headers={**supabase_headers(), "Prefer": "return=minimal"},
                json=payload,
            )
            if r.status_code == 409:
                r = requests.patch(
                    f"{SUPABASE_URL}/rest/v1/health_metrics"
                    f"?metric_date=eq.{d}&metric_name=eq.workouts",
                    headers={**supabase_headers(), "Prefer": "return=minimal"},
                    json={"value": payload["value"], "extra": payload["extra"]},
                )
            if r.status_code < 300:
                upserted += 1

    # ── Métricas normales ──
    # Métricas acumulativas: solo guardar si el nuevo valor es mayor que el almacenado
    CUMULATIVE_METRICS = {"step_count", "active_energy", "basal_energy", "resting_energy"}

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
            ENERGY_METRICS = {"active_energy", "basal_energy", "resting_energy"}
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

    for (metric_date, name), data in grouped_metrics.items():
        value = data["value"]

        row_exists = False
        # Para métricas acumulativas, no sobreescribir si ya hay un valor mayor en BD
        if name in CUMULATIVE_METRICS and value is not None:
            existing = requests.get(
                f"{SUPABASE_URL}/rest/v1/health_metrics"
                f"?metric_date=eq.{metric_date}&metric_name=eq.{name}&select=value",
                headers=supabase_headers(),
            )
            if existing.status_code < 300:
                rows = existing.json()
                if rows and rows[0].get("value") is not None:
                    row_exists = True
                    existing_val = float(rows[0]["value"])
                    # Solo saltar si el valor existente es real (>0) y ya es mayor o igual
                    if existing_val > 0 and existing_val >= value:
                        continue
                elif rows:
                    row_exists = True  # fila existe pero value es None

        payload = {
            "metric_date": metric_date,
            "metric_name": name,
            "value": value,
            "unit": data["unit"],
            "extra": data["extra"],
        }
        if row_exists:
            r = requests.patch(
                f"{SUPABASE_URL}/rest/v1/health_metrics"
                f"?metric_date=eq.{metric_date}&metric_name=eq.{name}",
                headers={**supabase_headers(), "Prefer": "return=minimal"},
                json=payload,
            )
        else:
            r = requests.post(
                f"{SUPABASE_URL}/rest/v1/health_metrics",
                headers={**supabase_headers(), "Prefer": "return=minimal,resolution=merge-duplicates"},
                json=payload,
            )
            if r.status_code == 409:
                r = requests.patch(
                    f"{SUPABASE_URL}/rest/v1/health_metrics"
                    f"?metric_date=eq.{metric_date}&metric_name=eq.{name}",
                    headers={**supabase_headers(), "Prefer": "return=minimal"},
                    json=payload,
                )
        if r.status_code < 300:
            upserted += 1

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

    body = await request.json()
    if isinstance(body, dict):
        # iOS Shortcuts serializa listas como NDJSON (un JSON por línea) dentro de un string
        if len(body) == 1:
            val = list(body.values())[0]
            if isinstance(val, str):
                import json as _json
                body = [_json.loads(line) for line in val.strip().splitlines() if line.strip()]
            elif isinstance(val, list):
                body = val
            else:
                body = [body]
        else:
            body = [body]

    samples = []
    parse_errors = []
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
        except (KeyError, ValueError, TypeError) as e:
            parse_errors.append({"item": str(item)[:200], "error": str(e)})
            continue

    CUMULATIVE_METRICS = {"step_count", "active_energy", "basal_energy"}
    upserted = 0
    skipped = []
    errors = []

    for s in samples:
        metric_date = s.date[:10] if s.date and len(s.date) >= 10 else None
        if not metric_date:
            skipped.append(f"{s.metric}: fecha inválida")
            continue

        extra = s.extra or {}
        if s.metric == "sleep_analysis":
            existing_sleep = requests.get(
                f"{SUPABASE_URL}/rest/v1/health_metrics"
                f"?metric_date=eq.{metric_date}&metric_name=eq.sleep_analysis&select=extra",
                headers=supabase_headers(),
            )
            if existing_sleep.status_code < 300:
                rows = existing_sleep.json()
                if rows and (rows[0].get("extra") or {}).get("excluded"):
                    extra = {**extra, "excluded": True}

        row_exists = False
        if s.metric in CUMULATIVE_METRICS:
            existing = requests.get(
                f"{SUPABASE_URL}/rest/v1/health_metrics"
                f"?metric_date=eq.{metric_date}&metric_name=eq.{s.metric}&select=value",
                headers=supabase_headers(),
            )
            if existing.status_code < 300:
                rows = existing.json()
                if rows:
                    row_exists = True
                    if rows[0].get("value") is not None and float(rows[0]["value"]) >= s.value:
                        skipped.append(f"{s.metric}: existente={rows[0]['value']} >= nuevo={s.value}")
                        continue

        if row_exists:
            r = requests.patch(
                f"{SUPABASE_URL}/rest/v1/health_metrics"
                f"?metric_date=eq.{metric_date}&metric_name=eq.{s.metric}",
                headers={**supabase_headers(), "Prefer": "return=minimal"},
                json={"value": s.value, "unit": s.unit, "extra": extra},
            )
        else:
            r = requests.post(
                f"{SUPABASE_URL}/rest/v1/health_metrics",
                headers={**supabase_headers(), "Prefer": "return=minimal,resolution=merge-duplicates"},
                json={
                    "metric_date": metric_date,
                    "metric_name": s.metric,
                    "value": s.value,
                    "unit": s.unit,
                    "extra": extra,
                },
            )
        if r.status_code == 409:
            r = requests.patch(
                f"{SUPABASE_URL}/rest/v1/health_metrics"
                f"?metric_date=eq.{metric_date}&metric_name=eq.{s.metric}",
                headers={**supabase_headers(), "Prefer": "return=minimal"},
                json={"value": s.value, "unit": s.unit, "extra": extra},
            )
        if r.status_code < 300:
            upserted += 1
        else:
            errors.append(f"{s.metric}: HTTP {r.status_code} {r.text[:100]}")

    return {"ok": True, "upserted": upserted, "received": len(samples), "skipped": skipped, "errors": errors, "parse_errors": parse_errors}


@app.patch("/health/sleep/{date}/exclude")
def toggle_sleep_exclude(
    date: str = Path(..., pattern=r"^\d{4}-\d{2}-\d{2}$"),
    credentials: HTTPAuthorizationCredentials = Depends(verify_token),
):
    """Alterna el flag excluded en extra de sleep_analysis para una fecha dada."""
    r = requests.get(
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
    patch = requests.patch(
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
    r = requests.get(
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
    r = requests.get(
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
    r_pay = requests.get(
        f"{SUPABASE_URL}/rest/v1/training_payments?client_id=eq.{client_id}&order=created_at.desc&limit=1",
        headers=supabase_headers(),
    )
    payments = r_pay.json() if r_pay.status_code < 300 else []
    last_payment = payments[0] if payments else None

    date_filter = f"&created_at=gt.{quote(last_payment['created_at'])}" if last_payment else ""
    r_sess = requests.get(
        f"{SUPABASE_URL}/rest/v1/training_sessions?client_id=eq.{client_id}{date_filter}",
        headers=supabase_headers(),
    )
    sessions = r_sess.json() if r_sess.status_code < 300 else []
    amount = round(sum(float(s["duration_hours"]) for s in sessions) * float(client["price_per_hour"]), 2)

    r = requests.post(
        f"{SUPABASE_URL}/rest/v1/training_payments",
        headers={**supabase_headers(), "Prefer": "return=representation"},
        json={"client_id": client_id, "date": body.date, "amount": amount},
    )
    if r.status_code >= 300:
        raise _supabase_error(r)
    return {"ok": True, "payment": r.json()[0]}
