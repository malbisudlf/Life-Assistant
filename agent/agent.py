"""
Life Assistant — Agente PC
==========================
Arranca con Windows (Task Scheduler), recoge el primer job pendiente de
Supabase, resuelve la entrega con Playwright + Claude API, guarda la
solución en Supabase, y se para.

NO toca el formulario de entrega en Moodle en ningún momento.
El usuario revisa la solución guardada y envía él mismo.
"""

import os
import sys
import time
import uuid
import socket
import logging
import requests
import anthropic
from dotenv import load_dotenv
from playwright.sync_api import sync_playwright, TimeoutError as PWTimeout

# ── Config ────────────────────────────────────────────────────────────────────
load_dotenv()

API_BASE      = os.getenv("LA_API_BASE", "https://backend-tender-glow-160.fly.dev")
LA_TOKEN      = os.getenv("LA_TOKEN")          # JWT del dashboard
SUPABASE_URL  = os.getenv("SUPABASE_URL")
SUPABASE_KEY  = os.getenv("SUPABASE_KEY")
ANTHROPIC_KEY = os.getenv("ANTHROPIC_API_KEY")
AGENT_ID      = "pc-mikel"
AGENT_VERSION = "1.0.0"
WORKER_ID     = f"{AGENT_ID}-{uuid.uuid4().hex[:8]}"

HEARTBEAT_INTERVAL = 10   # segundos entre heartbeats mientras espera
POLL_INTERVAL      = 5    # segundos entre checks de job pendiente
OKTA_TIMEOUT       = 120  # segundos máx esperando aprobación push Okta

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

def poll_pending_job():
    """Devuelve el primer job pendiente o None."""
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
        data = r.json()
        return data.get("claimed", False)
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

def save_solution(job_id: str, titulo: str, enunciado: str, solucion: str):
    """Guarda la solución en la tabla job_results de Supabase."""
    payload = {
        "job_id": job_id,
        "titulo": titulo,
        "enunciado": enunciado,
        "solucion": solucion,
    }
    r = requests.post(
        f"{SUPABASE_URL}/rest/v1/job_results",
        headers=supabase_headers(),
        json=payload,
        timeout=10,
    )
    log.info(f"Solución guardada en Supabase ({r.status_code})")

# ── Playwright: login Alud ────────────────────────────────────────────────────

def login_alud_if_needed(page):
    """
    Gestiona el login en Alud si es necesario.
    Pasos:
      1. Si hay botón '@deusto | @opendeusto' → click
      2. Seleccionar cuenta mikel.albisudela@opendeusto.es en Google
      3. Si hay Okta push → esperar hasta OKTA_TIMEOUT segundos a que el
         usuario lo apruebe desde el móvil
    """
    # ¿Estamos ya dentro? (comprobamos si aparece el botón de login)
    try:
        page.wait_for_selector(f"text={DEUSTO_BUTTON}", timeout=4000)
    except PWTimeout:
        log.info("Login no requerido, ya autenticado.")
        return

    log.info("Pantalla de login detectada → click en @deusto")
    page.click(f"text={DEUSTO_BUTTON}")

    # Selección de cuenta Google
    log.info("Esperando selección de cuenta Google...")
    page.wait_for_selector(f"text={TARGET_ACCOUNT}", timeout=15000)
    page.click(f"text={TARGET_ACCOUNT}")

    # ¿Redirige directamente o pide Okta?
    try:
        # Si en 8s ya está en Alud, listo
        page.wait_for_url(f"{ALUD_HOME}/**", timeout=8000)
        log.info("Login completado sin Okta.")
        return
    except PWTimeout:
        pass

    # Esperar Okta push (el usuario aprueba desde el móvil)
    log.info(f"Okta push enviado — esperando aprobación del usuario (máx {OKTA_TIMEOUT}s)...")
    try:
        page.wait_for_url(f"{ALUD_HOME}/**", timeout=OKTA_TIMEOUT * 1000)
        log.info("Okta aprobado, login completado.")
    except PWTimeout:
        raise RuntimeError("Timeout esperando aprobación Okta. El usuario no aprobó a tiempo.")

# ── Playwright: extraer enunciado ─────────────────────────────────────────────

def extract_enunciado(page, alud_url: str) -> str:
    """
    Navega a la URL de la actividad y extrae el texto del enunciado.
    Funciona para actividades tipo 'assign' (tarea) en Moodle.
    """
    log.info(f"Navegando a: {alud_url}")
    page.goto(alud_url, wait_until="networkidle", timeout=30000)
    login_alud_if_needed(page)

    # Esperar contenido principal
    page.wait_for_selector(".page-content, #region-main, .assign-intro", timeout=15000)

    # Intentar selectores comunes de Moodle para el enunciado
    selectors = [
        ".assign-intro",          # Tarea
        ".que .formulation",      # Quiz / pregunta
        "#intro",                 # Intro genérico Moodle
        ".activity-description",  # Descripción de actividad
        "#region-main",           # Fallback: todo el contenido principal
    ]

    for sel in selectors:
        try:
            el = page.query_selector(sel)
            if el:
                texto = el.inner_text().strip()
                if len(texto) > 50:   # descartar hits vacíos
                    log.info(f"Enunciado extraído con selector '{sel}' ({len(texto)} chars)")
                    return texto
        except Exception:
            continue

    raise RuntimeError("No se pudo extraer el enunciado de la página.")

# ── Claude API: resolver entrega ──────────────────────────────────────────────

def resolver_con_claude(titulo: str, enunciado: str) -> str:
    log.info("Llamando a Claude API para resolver la entrega...")
    client = anthropic.Anthropic(api_key=ANTHROPIC_KEY)

    prompt = f"""Eres un asistente académico que ayuda a un estudiante de la Universidad de Deusto.

A continuación tienes el enunciado de una entrega universitaria. Tu tarea es:
1. Entender exactamente qué pide el enunciado
2. Elaborar una respuesta completa, bien estructurada y de calidad académica
3. Ser claro sobre cualquier suposición que hagas si el enunciado es ambiguo

IMPORTANTE: El estudiante revisará esta solución personalmente antes de entregarla.
No indiques que eres una IA en la respuesta final — escribe directamente la solución.

---
TÍTULO DE LA ENTREGA: {titulo}

ENUNCIADO:
{enunciado}
---

Proporciona la solución completa:"""

    message = client.messages.create(
        model="claude-opus-4-5",
        max_tokens=4096,
        messages=[{"role": "user", "content": prompt}],
    )
    solucion = message.content[0].text
    log.info(f"Solución generada ({len(solucion)} chars)")
    return solucion

# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    if not LA_TOKEN:
        log.error("LA_TOKEN no configurado en .env — abortando.")
        sys.exit(1)

    log.info(f"Agente iniciado. Worker: {WORKER_ID}")
    heartbeat("starting")

    # Esperar hasta encontrar un job pendiente
    log.info("Buscando job pendiente...")
    job = None
    deadline = time.time() + 300  # máx 5 minutos esperando job

    while time.time() < deadline:
        heartbeat("online")
        job = poll_pending_job()
        if job:
            break
        time.sleep(POLL_INTERVAL)

    if not job:
        log.info("No hay jobs pendientes tras 5 minutos. El agente se para.")
        heartbeat("offline")
        return

    job_id  = job["id"]
    payload = job.get("payload", {})
    titulo  = payload.get("titulo", "Sin título")
    alud_url = payload.get("alud_url", "")

    log.info(f"Job encontrado: {job_id} | '{titulo}' | {alud_url}")

    if not alud_url:
        log.error("El job no tiene 'alud_url' en el payload. Abortando.")
        finish_job(job_id, "failed")
        heartbeat("offline")
        return

    # Intentar claim atómico
    if not claim_job(job_id):
        log.info("El job ya fue reclamado por otro worker. Saliendo.")
        heartbeat("offline")
        return

    start_job(job_id)
    heartbeat("busy")

    try:
        with sync_playwright() as pw:
            browser = pw.chromium.launch(headless=False)  # visible para que el usuario vea qué pasa
            context = browser.new_context(viewport={"width": 1280, "height": 900})
            page = context.new_page()

            # Ir a Alud (puede pedir login)
            log.info("Abriendo Alud...")
            page.goto(ALUD_HOME, wait_until="networkidle", timeout=20000)
            login_alud_if_needed(page)

            # Navegar a la actividad concreta
            enunciado = extract_enunciado(page, alud_url)
            browser.close()

        # Resolver con Claude
        solucion = resolver_con_claude(titulo, enunciado)

        # Guardar en Supabase
        save_solution(job_id, titulo, enunciado, solucion)

        finish_job(job_id, "done")
        log.info("✅ Job completado. Solución guardada en Supabase.")

    except Exception as e:
        log.error(f"Error ejecutando job: {e}", exc_info=True)
        finish_job(job_id, "failed")

    finally:
        heartbeat("offline")
        log.info("Agente finalizado.")


if __name__ == "__main__":
    main()
