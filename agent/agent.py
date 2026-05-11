"""
Life Assistant — Agente PC
==========================
Flujo:
  1. Heartbeat → online
  2. Recoge job pendiente de Supabase
  3. Abre Alud con Playwright, gestiona login + Okta
  4. Navega a la URL de la entrega y extrae el enunciado
  5. Deja el navegador abierto en la página de la entrega
  6. Abre Claude Desktop → Ctrl+2 (Cowork)
  7. Escribe la instrucción completa con el enunciado y Enter
  8. Heartbeat → offline, se para

El agente nunca toca el formulario de entrega.
Cowork se encarga de resolver y rellenar — el usuario revisa y envía.
"""

import os
import sys
import time
import uuid
import socket
import logging
import subprocess
import requests
import pyautogui
from dotenv import load_dotenv
from playwright.sync_api import sync_playwright, TimeoutError as PWTimeout

# ── Config ────────────────────────────────────────────────────────────────────
load_dotenv()

API_BASE      = os.getenv("LA_API_BASE", "https://backend-tender-glow-160.fly.dev")
LA_TOKEN      = os.getenv("LA_TOKEN")
SUPABASE_URL  = os.getenv("SUPABASE_URL")
SUPABASE_KEY  = os.getenv("SUPABASE_KEY")
AGENT_ID      = "pc-mikel"
AGENT_VERSION = "1.1.0"
WORKER_ID     = f"{AGENT_ID}-{uuid.uuid4().hex[:8]}"

CLAUDE_EXE         = r"C:\Users\malbi\.local\bin\claude.exe"
HEARTBEAT_INTERVAL = 10    # segundos entre heartbeats mientras espera job
POLL_INTERVAL      = 5     # segundos entre checks de job pendiente
OKTA_TIMEOUT       = 120   # segundos máx esperando aprobación push Okta
CLAUDE_LAUNCH_WAIT = 6     # segundos esperando a que Claude Desktop cargue

ALUD_HOME      = "https://alud.deusto.es"
DEUSTO_BUTTON  = "@deusto | @opendeusto"
TARGET_ACCOUNT = "mikel.albisudela@opendeusto.es"

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler("agent.log", encoding="utf-8"),
    ],
)
log = logging.getLogger(__name__)

# ── Helpers API ───────────────────────────────────────────────────────────────

def api_headers():
    return {"Authorization": f"Bearer {LA_TOKEN}", "Content-Type": "application/json"}

def supabase_headers():
    return {
        "apikey": SUPABASE_KEY,
        "Authorization": f"Bearer {SUPABASE_KEY}",
        "Content-Type": "application/json",
        "Prefer": "return=representation",
    }

def heartbeat(status: str):
    try:
        r = requests.post(
            f"{API_BASE}/agents/heartbeat",
            headers=api_headers(),
            json={
                "agent_id": AGENT_ID,
                "status": status,
                "hostname": socket.gethostname(),
                "version": AGENT_VERSION,
            },
            timeout=10,
        )
        log.info(f"Heartbeat → {status} ({r.status_code})")
    except Exception as e:
        log.warning(f"Heartbeat falló: {e}")


def report_stage(job_id: str, stage: str, message: str = ""):
    try:
        requests.post(
            f"{API_BASE}/jobs/{job_id}/events",
            headers=api_headers(),
            json={"stage": stage, "message": message},
            timeout=10,
        )
        log.info(f"Stage → {stage}")
    except Exception as e:
        log.warning(f"No se pudo reportar stage '{stage}': {e}")

def poll_pending_job():
    try:
        r = requests.get(
            f"{SUPABASE_URL}/rest/v1/jobs?status=eq.pending&order=created_at.asc&limit=1",
            headers=supabase_headers(),
            timeout=10,
        )
        jobs = r.json()
        return jobs[0] if jobs else None
    except Exception as e:
        log.warning(f"Error polling jobs: {e}")
        return None

def claim_job(job_id: str) -> bool:
    try:
        r = requests.post(
            f"{API_BASE}/jobs/{job_id}/claim",
            headers=api_headers(),
            json={"worker_id": WORKER_ID},
            timeout=10,
        )
        return r.json().get("claimed", False)
    except Exception as e:
        log.warning(f"Error claiming job: {e}")
        return False

def start_job(job_id: str):
    requests.post(
        f"{API_BASE}/jobs/{job_id}/start",
        headers=api_headers(),
        json={"worker_id": WORKER_ID},
        timeout=10,
    )

def finish_job(job_id: str, status: str):
    requests.post(
        f"{API_BASE}/jobs/{job_id}/finish",
        headers=api_headers(),
        json={"worker_id": WORKER_ID, "status": status},
        timeout=10,
    )

# ── Playwright: login Alud ────────────────────────────────────────────────────

def login_alud_if_needed(page):
    try:
        page.wait_for_selector(f"text={DEUSTO_BUTTON}", timeout=4000)
    except PWTimeout:
        log.info("Login no requerido, sesión activa.")
        return

    log.info("Pantalla de login → click en @deusto")
    page.click(f"text={DEUSTO_BUTTON}")

    log.info("Esperando selección de cuenta Google...")
    page.wait_for_selector(f"text={TARGET_ACCOUNT}", timeout=15000)
    page.click(f"text={TARGET_ACCOUNT}")

    # ¿Redirige directamente o pide Okta?
    try:
        page.wait_for_url(f"{ALUD_HOME}/**", timeout=8000)
        log.info("Login completado sin Okta.")
        return
    except PWTimeout:
        pass

    # Esperar Okta push — el usuario aprueba desde el móvil
    log.info(f"Okta push enviado. Esperando aprobación en el móvil (máx {OKTA_TIMEOUT}s)...")
    try:
        page.wait_for_url(f"{ALUD_HOME}/**", timeout=OKTA_TIMEOUT * 1000)
        log.info("Okta aprobado, acceso a Alud confirmado.")
    except PWTimeout:
        raise RuntimeError("Timeout esperando aprobación Okta.")

# ── Playwright: extraer enunciado ─────────────────────────────────────────────

def extract_enunciado(page, alud_url: str) -> str:
    log.info(f"Navegando a la entrega: {alud_url}")
    page.goto(alud_url, wait_until="networkidle", timeout=30000)

    # Si nos redirigen al login (sesión caducada)
    if "login" in page.url:
        login_alud_if_needed(page)
        page.goto(alud_url, wait_until="networkidle", timeout=30000)

    page.wait_for_selector(".page-content, #region-main", timeout=15000)

    selectors = [
        ".assign-intro",
        ".que .formulation",
        "#intro",
        ".activity-description",
        ".box.generalbox",
        "#region-main",
    ]

    for sel in selectors:
        try:
            el = page.query_selector(sel)
            if el:
                texto = el.inner_text().strip()
                if len(texto) > 50:
                    log.info(f"Enunciado extraído con '{sel}' ({len(texto)} chars)")
                    return texto
        except Exception:
            continue

    raise RuntimeError("No se pudo extraer el enunciado de la página.")

# ── Cowork: abrir Claude Desktop y escribir instrucción ───────────────────────

def build_cowork_instruction(titulo: str, enunciado: str, alud_url: str) -> str:
    return (
        f"Tengo una entrega universitaria que resolver en Alud (Moodle de Deusto). "
        f"El navegador ya está abierto y con sesión iniciada en la página de la entrega.\n\n"
        f"URL de la entrega: {alud_url}\n\n"
        f"Título: {titulo}\n\n"
        f"Enunciado:\n{enunciado}\n\n"
        f"Por favor:\n"
        f"1. Ve al navegador que está abierto con esa URL\n"
        f"2. Lee el enunciado en pantalla para confirmar que lo entiendes\n"
        f"3. Resuelve la actividad y rellena el campo de respuesta\n"
        f"4. NO pulses ningún botón de enviar, entregar ni submit — "
        f"el usuario lo revisará y enviará manualmente cuando llegue a casa"
    )

def launch_cowork(titulo: str, enunciado: str, alud_url: str):
    instruccion = build_cowork_instruction(titulo, enunciado, alud_url)

    log.info("Abriendo Claude Desktop...")
    subprocess.Popen([CLAUDE_EXE])
    time.sleep(CLAUDE_LAUNCH_WAIT)

    log.info("Ctrl+2 → Cowork...")
    pyautogui.hotkey("ctrl", "2")
    time.sleep(2)

    # Click en el centro de la pantalla para asegurar foco en el chat
    screen_w, screen_h = pyautogui.size()
    pyautogui.click(screen_w // 2, screen_h - 120)  # área del input, parte baja
    time.sleep(0.5)

    # Copiar instrucción al portapapeles via PowerShell
    # (pyautogui.write falla con tildes y caracteres especiales)
    log.info("Copiando instrucción al portapapeles...")
    ps_cmd = ["powershell", "-Command", f"Set-Clipboard -Value @'\n{instruccion}\n'@"]
    subprocess.run(ps_cmd, check=True)
    time.sleep(0.3)

    pyautogui.hotkey("ctrl", "v")
    time.sleep(0.5)
    pyautogui.press("enter")
    log.info("Instrucción enviada a Cowork.")

# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    if not LA_TOKEN:
        log.error("LA_TOKEN no configurado en .env — abortando.")
        sys.exit(1)

    log.info(f"Agente iniciado. Worker: {WORKER_ID}")
    heartbeat("starting")

    # Esperar job pendiente (máx 5 minutos)
    log.info("Buscando job pendiente...")
    job = None
    deadline = time.time() + 300

    while time.time() < deadline:
        heartbeat("online")
        # hito de disponibilidad del agente
        # (sin job todavía no se reporta en job_events)
        job = poll_pending_job()
        if job:
            break
        time.sleep(POLL_INTERVAL)

    if not job:
        log.info("No hay jobs tras 5 minutos. Agente finalizado.")
        heartbeat("offline")
        return

    job_id   = job["id"]
    payload  = job.get("payload", {})
    titulo   = payload.get("titulo", "Sin título")
    alud_url = payload.get("alud_url", "")

    log.info(f"Job: {job_id} | '{titulo}' | {alud_url}")

    if not alud_url:
        log.error("El job no tiene 'alud_url' en el payload — abortando.")
        finish_job(job_id, "failed")
        report_stage(job_id, "job_done", "failed: missing alud_url")
        heartbeat("offline")
        return

    report_stage(job_id, "heartbeat_online", "Agente disponible y polling activo")

    if not claim_job(job_id):
        log.info("Job ya reclamado por otro worker.")
        heartbeat("offline")
        return

    report_stage(job_id, "job_claimed", f"Worker {WORKER_ID} reclamó el job")
    start_job(job_id)
    heartbeat("busy")

    try:
        # ── Playwright: login + extracción ──
        # Iniciamos playwright manualmente (sin `with`) para que el navegador
        # permanezca abierto después de la extracción y Cowork pueda verlo.
        pw = sync_playwright().start()
        # Usar el perfil real de Edge para tener cookies y sesiones guardadas
        context = pw.chromium.launch_persistent_context(
            user_data_dir=r"C:\Users\malbi\AppData\Local\Microsoft\Edge\User Data",
            channel="msedge",
            headless=False,
            args=["--profile-directory=Default"],
            viewport={"width": 1280, "height": 900},
        )
        page = context.new_page()

        log.info("Abriendo Alud...")
        page.goto(ALUD_HOME, wait_until="networkidle", timeout=20000)
        login_alud_if_needed(page)

        report_stage(job_id, "assignment_opened", f"Entrega abierta: {alud_url}")
        enunciado = extract_enunciado(page, alud_url)
        report_stage(job_id, "enunciado_extracted", f"{len(enunciado)} chars extraídos")

        # Navegador ABIERTO en la entrega — Cowork lo usará directamente.
        # NO cerramos browser ni pw — el proceso termina y el navegador queda vivo.
        log.info("Navegador abierto en la entrega. Pasando control a Cowork...")

        # ── pyautogui: Claude Desktop → Cowork ──
        report_stage(job_id, "solver_started", "Iniciando Claude Cowork")
        launch_cowork(titulo, enunciado, alud_url)
        report_stage(job_id, "result_saved", "Instrucción enviada a Cowork")

        finish_job(job_id, "done")
        report_stage(job_id, "job_done", "done")
        log.info("✅ Job completado. Cowork está ejecutando la entrega.")

    except Exception as e:
        log.error(f"Error: {e}", exc_info=True)
        finish_job(job_id, "failed")
        report_stage(job_id, "job_done", "failed: missing alud_url")

    finally:
        heartbeat("offline")
        log.info("Agente finalizado.")


if __name__ == "__main__":
    main()
