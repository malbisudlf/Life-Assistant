from fastapi import FastAPI, Depends, HTTPException, status, UploadFile, File, Path
from fastapi.middleware.cors import CORSMiddleware
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from dotenv import load_dotenv
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo
from pydantic import BaseModel, Field, field_validator
from jose import JWTError, jwt
from openai import OpenAI
import msal
import requests
import httpx
import os
import json

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

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "https://life-assistant-smoky.vercel.app"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

CLIENT_ID = os.getenv("CLIENT_ID")
TENANT_ID = os.getenv("TENANT_ID")
CLIENT_SECRET = os.getenv("CLIENT_SECRET")
REDIRECT_URI = os.getenv("REDIRECT_URI")
DASHBOARD_PASSWORD = os.getenv("DASHBOARD_PASSWORD", "changeme")
SECRET_KEY = os.getenv("SECRET_KEY", "fallback-secret")
ALGORITHM = "HS256"
TOKEN_EXPIRE_DAYS = 30
GOOGLE_MAPS_API_KEY = os.getenv("GOOGLE_MAPS_API_KEY")
SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")
HOME_ADDRESS = os.getenv("HOME_ADDRESS", "Calle Astigar 35, Durango, Vizcaya, España")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
MAX_JOB_ATTEMPTS = int(os.getenv("MAX_JOB_ATTEMPTS", "3"))
HA_URL        = os.getenv("HA_URL", "http://100.84.40.119:8123")
HA_TOKEN      = os.getenv("HA_TOKEN")
HA_POLL_TOKEN = os.getenv("HA_POLL_TOKEN", "")

openai_client = OpenAI(api_key=OPENAI_API_KEY)

bearer_scheme = HTTPBearer()

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

SCOPES = ["Calendars.Read", "User.Read"]
TOKEN_FILE = ".token"
import json
import re

_UUID_RE = re.compile(
    r'^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$',
    re.IGNORECASE,
)
_SAFE_ID_RE = re.compile(r'^[a-zA-Z0-9_-]{1,64}$')

_wol_pending = False

def _clean_class_title(subject: str) -> str:
    s = re.sub(r"^\d+\s*-\s*", "", subject)
    s = re.sub(r"\s*Grupo:\s*\d+\s*-\s*Asignatura\s*$", "", s, flags=re.IGNORECASE)
    return s.strip()

def save_token_data(data: dict):
    with open(TOKEN_FILE, "w") as f:
        json.dump(data, f)

def load_token_data() -> dict | None:
    if os.path.exists(TOKEN_FILE):
        with open(TOKEN_FILE, "r") as f:
            return json.load(f)
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
def login_password(body: LoginRequest):
    if body.password != DASHBOARD_PASSWORD:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Contraseña incorrecta")
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
        alud_match = _re.search(r"alud_url:\s*(https?://\S+)", body_content) or \
                     _re.search(r"alud_url:\s*(https?://\S+)", preview_content)
        alud_url = alud_match.group(1).rstrip("</>&;") if alud_match else None
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


@app.get("/calendar/classes")
def get_class_events(credentials: HTTPAuthorizationCredentials = Depends(verify_token)):
    token = get_valid_token()
    if not token:
        return {"error": "No autenticado"}
    headers = {"Authorization": f"Bearer {token}"}
    # Buscar el calendario llamado 'Clases'
    r = requests.get("https://graph.microsoft.com/v1.0/me/calendars", headers=headers)
    calendars = r.json().get("value", [])
    cal = next((c for c in calendars if c["name"].lower() == "clases"), None)
    if not cal:
        return {"error": "Calendario 'Clases' no encontrado", "available": [c["name"] for c in calendars]}
    cal_id = cal["id"]
    # Inicio del día en hora local (Europe/Madrid) para no perder clases de hoy
    madrid_tz = ZoneInfo("Europe/Madrid")
    today_start = datetime.now(madrid_tz).replace(hour=0, minute=0, second=0, microsecond=0)
    start = today_start.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    end = (today_start + timedelta(days=7)).astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    r2 = requests.get(
        f"https://graph.microsoft.com/v1.0/me/calendars/{cal_id}/calendarView"
        f"?startDateTime={start}&endDateTime={end}&$top=50"
        f"&$select=subject,start,end,location,isAllDay&$orderby=start/dateTime",
        headers=headers
    )
    r2.encoding = "utf-8"
    data2 = r2.json()

    events = []
    for event in data2.get("value", []):
        raw_start = event.get("start", {})
        raw_end = event.get("end", {})
        print(f"[CLASES DEBUG] subject={event.get('subject')} tz={raw_start.get('timeZone')} start_raw={raw_start.get('dateTime')}")
        events.append({
            "id": event.get("id"),
            "title": _clean_class_title(event.get("subject", "")),
            "start": normalize_graph_dt(raw_start),
            "end": normalize_graph_dt(raw_end),
            "location": event.get("location", {}).get("displayName"),
            "isAllDay": event.get("isAllDay"),
        })
    print(f"[CLASES DEBUG] Total eventos devueltos: {len(events)}")
    return {"events": events}


@app.get("/")
def root():
    return {"status": "Life Assistant API running"}


# ── MAPS ──────────────────────────────────────────────────────────────────────

class DepartureRequest(BaseModel):
    destination: str = Field(max_length=500)
    event_time: str = Field(max_length=50)
    origin: str = Field(default=HOME_ADDRESS, max_length=500)

    @field_validator("event_time")
    @classmethod
    def validate_event_time(cls, v: str) -> str:
        try:
            datetime.fromisoformat(v.replace("Z", "+00:00"))
        except ValueError:
            raise ValueError("event_time debe ser una fecha ISO válida")
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
        "mode": "driving",
        "departure_time": "now",
        "traffic_model": "best_guess",
        "language": "es",
        "key": GOOGLE_MAPS_API_KEY,
    }
    r = requests.get(url, params=params)
    data = r.json()

    try:
        element = data["rows"][0]["elements"][0]
        if element["status"] != "OK":
            raise HTTPException(status_code=400, detail="No se pudo calcular la ruta")

        # Duración con tráfico (en segundos)
        duration_seconds = element.get("duration_in_traffic", element["duration"])["value"]
        duration_text = element.get("duration_in_traffic", element["duration"])["text"]
        distance_text = element["distance"]["text"]

        # Calcular hora de salida
        event_dt = datetime.fromisoformat(body.event_time.replace("Z", "+00:00"))
        # Añadir 10 min de margen
        departure_dt = event_dt - timedelta(seconds=duration_seconds) - timedelta(minutes=10)
        # Convertir siempre a hora de Bilbao (Europa/Madrid)
        madrid_tz = ZoneInfo("Europe/Madrid")
        departure_local = departure_dt.astimezone(madrid_tz)

        return {
            "duration_text": duration_text,
            "distance_text": distance_text,
            "departure_time": departure_local.strftime("%H:%M"),
            "departure_iso": departure_local.isoformat(),
        }
    except (KeyError, IndexError):
        raise HTTPException(status_code=500, detail="Error procesando respuesta de Maps")


# ── IDEAS ─────────────────────────────────────────────────────────

def supabase_headers():
    return {
        "apikey": SUPABASE_KEY,
        "Authorization": f"Bearer {SUPABASE_KEY}",
        "Content-Type": "application/json",
    }

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

    # 2. Extraer idea clave con GPT-4o mini
    completion = openai_client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[
            {
                "role": "system",
                "content": (
                    "Eres un asistente que extrae ideas clave de notas de voz. "
                    "Dado un texto transcrito, responde SOLO con un JSON válido con este formato exacto: "
                    '{"key": "Título corto de la idea (máx 8 palabras)", "tag": "una palabra categoría", "full_text": "Resumen claro y completo de la idea en 2-3 frases"}'
                ),
            },
            {"role": "user", "content": text},
        ],
        max_tokens=300,
        temperature=0.3,
    )
    raw = completion.choices[0].message.content.strip()
    # Limpiar posibles backticks
    raw = raw.replace("```json", "").replace("```", "").strip()
    try:
        idea_data = json.loads(raw)
    except json.JSONDecodeError:
        idea_data = {}

    # 3. Guardar en Supabase
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
    return {"ok": True, "idea": r.json()[0] if r.status_code < 300 else payload, "transcript": text}


# ── HOME ASSISTANT INTEGRATION ────────────────────────────────────────────────

@app.get("/ha/events/soon")
def ha_events_soon(token: str = ""):
    """Devuelve el primer evento que empieza en ~15 min. HA lo consulta cada minuto."""
    if not HA_POLL_TOKEN or token != HA_POLL_TOKEN:
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
def ha_wol_pending(token: str = ""):
    """HA sondea este endpoint cada 30s. Si hay WOL pendiente, devuelve pending=true y lo limpia."""
    if token != HA_POLL_TOKEN or not HA_POLL_TOKEN:
        raise HTTPException(status_code=403, detail="Forbidden")
    global _wol_pending
    pending = _wol_pending
    _wol_pending = False
    return {"pending": pending}

@app.post("/jobs")
def create_job(body: JobCreateRequest, credentials: HTTPAuthorizationCredentials = Depends(verify_token)):
    payload = {"dedupe_key": body.dedupe_key, "payload": body.payload}
    r = requests.post(
        f"{SUPABASE_URL}/rest/v1/jobs",
        headers={**supabase_headers(), "Prefer": "return=representation,resolution=merge-duplicates"},
        json=payload,
    )
    if r.status_code >= 300:
        raise HTTPException(status_code=400, detail=r.text)
    data = r.json()
    return {"ok": True, "job": data[0] if data else None}

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
        raise HTTPException(status_code=400, detail=r.text)
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
        raise HTTPException(status_code=400, detail=r.text)
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
        raise HTTPException(status_code=400, detail=r.text)
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
        raise HTTPException(status_code=400, detail=r.text)
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
        raise HTTPException(status_code=400, detail=r.text)
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
        raise HTTPException(status_code=400, detail=r.text)
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
        raise HTTPException(status_code=400, detail=get_r.text)
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
        raise HTTPException(status_code=400, detail=patch_r.text)
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
        raise HTTPException(status_code=400, detail=r.text)
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
        raise HTTPException(status_code=400, detail=r.text)
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
