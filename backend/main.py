from fastapi import FastAPI, Depends, HTTPException, status, UploadFile, File
from fastapi.middleware.cors import CORSMiddleware
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from dotenv import load_dotenv
from datetime import datetime, timedelta, timezone
from pydantic import BaseModel
from jose import JWTError, jwt
from openai import OpenAI
import msal
import requests
import httpx
import os
import json

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
SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")

openai_client = OpenAI(api_key=OPENAI_API_KEY)

bearer_scheme = HTTPBearer()

class LoginRequest(BaseModel):
    password: str

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
        f"https://graph.microsoft.com/v1.0/me/calendarView?startDateTime={start}&endDateTime={end}&$top=100&$select=subject,start,end,location,bodyPreview,isAllDay&$orderby=start/dateTime",
        headers=headers
    )
    data = response.json()
    
    def normalize_dt(dt_obj: dict) -> str:
        """Si la fecha viene en UTC, añade Z para que el navegador la convierta correctamente."""
        dt_str = dt_obj.get("dateTime", "")
        tz = dt_obj.get("timeZone", "")
        if tz.upper() == "UTC" and dt_str and not dt_str.endswith("Z"):
            return dt_str + "Z"
        return dt_str

    events = []
    for event in data.get("value", []):
        events.append({
            "id": event.get("id"),
            "title": event.get("subject"),
            "start": normalize_dt(event.get("start", {})),
            "end": normalize_dt(event.get("end", {})),
            "location": event.get("location", {}).get("displayName"),
            "preview": event.get("bodyPreview"),
            "isAllDay": event.get("isAllDay"),
        })
    
    return {"events": events}

@app.get("/")
def root():
    return {"status": "Life Assistant API running"}


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
def delete_idea(idea_id: str, credentials: HTTPAuthorizationCredentials = Depends(verify_token)):
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
    idea_data = json.loads(raw)

    # 3. Guardar en Supabase
    payload = {
        "key": idea_data.get("key", text[:60]),
        "full_text": idea_data.get("full_text", text),
        "tag": idea_data.get("tag", "idea"),
    }
    r = requests.post(
        f"{SUPABASE_URL}/rest/v1/ideas",
        headers={**supabase_headers(), "Prefer": "return=representation"},
        json=payload,
    )
    return {"ok": True, "idea": r.json()[0] if r.status_code < 300 else payload, "transcript": text}