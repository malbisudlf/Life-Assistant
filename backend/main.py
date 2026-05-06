from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from dotenv import load_dotenv
from datetime import datetime, timedelta, timezone
import msal
import requests
import os

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
def get_events():
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
    
    events = []
    for event in data.get("value", []):
        events.append({
            "id": event.get("id"),
            "title": event.get("subject"),
            "start": event.get("start", {}).get("dateTime"),
            "end": event.get("end", {}).get("dateTime"),
            "location": event.get("location", {}).get("displayName"),
            "preview": event.get("bodyPreview"),
            "isAllDay": event.get("isAllDay"),
        })
    
    return {"events": events}

@app.get("/")
def root():
    return {"status": "Life Assistant API running"}