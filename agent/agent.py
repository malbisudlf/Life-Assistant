"""
Life Assistant — Agente PC (efímero + despachador)
==================================================
Arranca con Windows (lo enciende el WOL cuando pulsas un botón desde el móvil),
mira si hay algún job pendiente y, según su 'accion', DECIDE qué hacer. Cuando
drena la cola, se apaga: NO se queda residente. El PC arranca casi "tonto" y el
agente vive lo justo para ejecutar lo que le hayas pedido.

Flujo:
  1. Mira si hay jobs pendientes. Si no hay nada → se cierra sin más.
  2. Por cada job pendiente, lo reclama y despacha según payload["accion"]:
       - "resolver_alud"   → abre Alud en Edge, extrae el enunciado y lanza Cowork
       - "abrir_streaming" → lanza Sunshine para conectar con Moonlight desde el móvil
  3. Cuando no quedan jobs: heartbeat offline y termina.

Añadir una acción nueva = una función + una entrada en el diccionario ACCIONES.

En "resolver_alud" el agente nunca toca el formulario de entrega:
Cowork se encarga de resolver y rellenar — el usuario revisa y envía.
"""

import os
import sys
import time
import uuid
import random
import socket
import logging
import tempfile
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

CLAUDE_APPID       = "Claude_pzs8sxrjxfjjc!Claude"  # MSIX Store app
HEARTBEAT_INTERVAL = 10    # segundos entre heartbeats mientras espera job
POLL_INTERVAL      = 5     # segundos entre checks de job pendiente
OKTA_TIMEOUT       = 120   # segundos máx esperando aprobación push Okta
CLAUDE_LAUNCH_WAIT = 6     # segundos esperando a que Claude Desktop cargue
# Puerto CDP aleatorio por ejecución en vez de un 9222 fijo y predecible.
# Chromium solo escucha el puerto de depuración en loopback (127.0.0.1), así que el
# acceso queda restringido a procesos de la propia máquina; randomizarlo reduce la
# ventana de exposición frente a algo que sondee el puerto conocido.
EDGE_DEBUG_PORT    = random.randint(49200, 49900)

_EDGE_PATHS = [
    r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
    r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
]
EDGE_EXE = next((p for p in _EDGE_PATHS if os.path.exists(p)), None)

# ── Sunshine (host de streaming para Moonlight) ────────────────────────────────
# Sunshine NO arranca solo con Windows (su autoarranque se desactiva a propósito):
# lo ÚNICO residente es este agente, que lo lanza bajo demanda cuando llega un job
# de streaming. Ruta configurable por si se instala en otra ubicación.
_SUNSHINE_PATHS = [
    r"C:\Program Files\Sunshine\sunshine.exe",
    r"C:\Program Files (x86)\Sunshine\sunshine.exe",
]
SUNSHINE_EXE = os.getenv("SUNSHINE_EXE") or next((p for p in _SUNSHINE_PATHS if os.path.exists(p)), None)

ALUD_HOME      = "https://alud.deusto.es"
DEUSTO_BUTTON  = "@deusto | @opendeusto"
TARGET_ACCOUNT = os.getenv("ALUD_ACCOUNT", "")

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
        r = requests.post(
            f"{API_BASE}/jobs/{job_id}/events",
            headers=api_headers(),
            json={"stage": stage, "message": message},
            timeout=10,
        )
        if r.status_code >= 300:
            log.warning(f"Stage '{stage}' rechazado por el backend: {r.status_code} {r.text[:200]}")
        else:
            log.info(f"Stage → {stage}")
    except Exception as e:
        log.warning(f"No se pudo reportar stage '{stage}': {e}")

def poll_pending_job():
    try:
        from datetime import datetime, timezone, timedelta
        cutoff = (datetime.now(timezone.utc) - timedelta(hours=1)).strftime("%Y-%m-%dT%H:%M:%S+00:00")
        r = requests.get(
            f"{SUPABASE_URL}/rest/v1/jobs?status=eq.pending&created_at=gt.{cutoff}&order=created_at.desc&limit=1",
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

def login_alud_if_needed(page, context):
    try:
        page.wait_for_selector(f"text={DEUSTO_BUTTON}", timeout=4000)
    except PWTimeout:
        log.info("Login no requerido, sesión activa.")
        return

    log.info("Pantalla de login → click en @deusto")

    # Con el perfil real de Edge, Google puede abrir un popup o hacer SSO directo.
    # Usamos expect_page para capturar el popup si aparece; si no, la misma página navega.
    auth_page = None
    try:
        with context.expect_page(timeout=5000) as popup_info:
            page.click(f"text={DEUSTO_BUTTON}")
        auth_page = popup_info.value
        log.info("Google OAuth en ventana nueva (popup).")
    except PWTimeout:
        # Sin popup — la misma página navega (click ya ocurrió dentro del with)
        log.info("Google OAuth navega en la misma página.")

    # Intentar seleccionar cuenta si el picker aparece (puede saltarse por SSO)
    target = auth_page if auth_page else page
    if not TARGET_ACCOUNT:
        log.warning("ALUD_ACCOUNT no configurado en .env — no se puede seleccionar cuenta automáticamente.")
    else:
        try:
            target.wait_for_selector(f"text={TARGET_ACCOUNT}", timeout=6000)
            target.click(f"text={TARGET_ACCOUNT}")
            log.info("Cuenta Google seleccionada.")
        except Exception:
            log.info("Selector de cuenta no apareció — SSO automático o ya seleccionada.")

    # Esperar que la página principal llegue a Alud (con o sin Okta)
    try:
        page.wait_for_url(f"{ALUD_HOME}/**", timeout=10000)
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

def extract_enunciado(page, context, alud_url: str) -> str:
    log.info(f"Navegando a la entrega: {alud_url}")
    page.goto(alud_url, wait_until="networkidle", timeout=30000)

    # Si nos redirigen al login (sesión caducada)
    if "login" in page.url:
        login_alud_if_needed(page, context)
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
        f"Ten en cuenta que el usuario no está en el ordenador, esto es un mensaje automatizado, por lo que no podrá responder preguntas. Si tienes alguna duda, elige la opción recomendada, o la que mas se ajuste a las instrucciones"
    )

def _focus_claude_window() -> bool:
    """Enfoca la ventana de Claude Desktop usando PowerShell + win32. Devuelve True si tuvo éxito."""
    result = subprocess.run(
        ["powershell", "-Command", """
$proc = Get-Process -Name 'claude' -ErrorAction SilentlyContinue | Where-Object { $_.MainWindowHandle -ne 0 } | Select-Object -First 1
if ($proc) {
    Add-Type @'
    using System;
    using System.Runtime.InteropServices;
    public class Win32 {
        [DllImport("user32.dll")] public static extern bool SetForegroundWindow(IntPtr hWnd);
        [DllImport("user32.dll")] public static extern bool ShowWindow(IntPtr hWnd, int nCmdShow);
    }
'@
    [Win32]::ShowWindow($proc.MainWindowHandle, 3)  # SW_MAXIMIZE = 3
    [Win32]::SetForegroundWindow($proc.MainWindowHandle)
    Write-Output "OK"
} else {
    Write-Output "NOT_FOUND"
}
"""],
        capture_output=True, text=True,
    )
    ok = "OK" in result.stdout
    log.info(f"Foco Claude Desktop: {'OK' if ok else 'no encontrado'}")
    return ok


def launch_cowork(titulo: str, enunciado: str, alud_url: str):
    instruccion = build_cowork_instruction(titulo, enunciado, alud_url)

    # Copiar al portapapeles ANTES de abrir Claude, para no perder el foco.
    # El enunciado proviene de una página web externa (Alud): NUNCA se interpola en el
    # comando de PowerShell. Se escribe a un fichero temporal (ruta generada por el SO,
    # sin contenido no confiable) y Set-Clipboard lo lee de ahí → sin inyección posible.
    log.info("Copiando instrucción al portapapeles...")
    clip_path = None
    try:
        with tempfile.NamedTemporaryFile("w", suffix=".txt", delete=False, encoding="utf-8") as tf:
            tf.write(instruccion)
            clip_path = tf.name
        ps_cmd = [
            "powershell", "-NoProfile", "-Command",
            f"Set-Clipboard -Value (Get-Content -Raw -Encoding UTF8 -LiteralPath '{clip_path}')",
        ]
        subprocess.run(ps_cmd, check=True)
    finally:
        if clip_path:
            try:
                os.remove(clip_path)
            except OSError:
                pass
    time.sleep(0.3)

    log.info("Abriendo Claude Desktop...")
    subprocess.Popen(["explorer.exe", f"shell:AppsFolder\\{CLAUDE_APPID}"])
    time.sleep(CLAUDE_LAUNCH_WAIT)

    # Enfocar y maximizar Claude Desktop
    log.info("Enfocando Claude Desktop...")
    _focus_claude_window()
    time.sleep(1.5)  # tiempo suficiente para que la ventana esté lista

    # Ctrl+2 → Cowork
    log.info("Ctrl+2 → Cowork...")
    pyautogui.hotkey("ctrl", "2")
    time.sleep(3)  # esperar a que Cowork cargue

    # Click en el input del chat
    screen_w, screen_h = pyautogui.size()
    pyautogui.click(screen_w // 2, screen_h - 90)
    time.sleep(0.6)

    # Win+V → abre historial → Enter selecciona el más reciente → Enter envía
    log.info("Pegando instrucción via historial de portapapeles...")
    pyautogui.hotkey("win", "v")
    time.sleep(1.0)  # esperar a que aparezca el panel
    pyautogui.press("enter")
    time.sleep(0.4)
    pyautogui.press("enter")
    log.info("Instrucción enviada a Cowork.")

# ── Acciones ──────────────────────────────────────────────────────────────────
# Cada acción es una función (job_id, payload) que hace el trabajo y reporta sus
# stages. Si algo va mal, lanza una excepción: procesar_job la captura y marca el
# job como 'failed'. Para añadir una acción nueva: define la función y regístrala
# en el diccionario ACCIONES.

def accion_resolver_alud(job_id: str, payload: dict):
    """Abre Alud en Edge, extrae el enunciado de la entrega y lanza Claude Cowork."""
    titulo   = payload.get("titulo", "Sin título")
    alud_url = payload.get("alud_url", "")
    if not alud_url:
        raise RuntimeError("El job no tiene 'alud_url' en el payload")

    log.info(f"Resolver Alud: '{titulo}' | {alud_url}")

    # ── Lanzar Edge como proceso independiente (DETACHED) ──
    # Al ser DETACHED, Edge no es hijo de Python — sobrevive cuando Python termina.
    edge_profile = os.getenv("EDGE_PROFILE_DIR") or os.path.join(os.path.expanduser("~"), "AppData", "Local", "Microsoft", "Edge", "User Data")
    if not EDGE_EXE:
        raise RuntimeError("No se encontró el ejecutable de Edge")
    log.info(f"Lanzando Edge detached desde {EDGE_EXE}...")
    subprocess.Popen(
        [EDGE_EXE,
         f"--user-data-dir={edge_profile}",
         "--profile-directory=Default",
         f"--remote-debugging-port={EDGE_DEBUG_PORT}",
         "--no-first-run"],
        creationflags=subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP,
        stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )
    time.sleep(4)  # esperar a que Edge arranque y exponga el puerto CDP

    pw = sync_playwright().start()
    try:
        browser = pw.chromium.connect_over_cdp(f"http://localhost:{EDGE_DEBUG_PORT}")
        # Usar el contexto existente de Edge (el que tiene el perfil del usuario)
        context = browser.contexts[0] if browser.contexts else browser.new_context()
        page = context.new_page()

        log.info("Abriendo Alud...")
        page.goto(ALUD_HOME, wait_until="networkidle", timeout=20000)
        login_alud_if_needed(page, context)
        report_stage(job_id, "login_ok", "Sesión Alud activa")

        report_stage(job_id, "assignment_opened", f"Entrega abierta: {alud_url}")
        enunciado = extract_enunciado(page, context, alud_url)
        report_stage(job_id, "enunciado_extracted", f"{len(enunciado)} chars extraídos")

        log.info("Navegador listo en la entrega. Pasando a Cowork...")

        # ── pyautogui: Claude Desktop → Cowork ──
        report_stage(job_id, "solver_started", "Iniciando Claude Cowork")
        launch_cowork(titulo, enunciado, alud_url)
        report_stage(job_id, "result_saved", "Instrucción enviada a Cowork")
        log.info("✅ Cowork está ejecutando la entrega.")
    finally:
        # Cerramos solo la conexión de Playwright; Edge queda abierto (DETACHED) a propósito.
        try:
            pw.stop()
        except Exception:
            pass


def accion_abrir_streaming(job_id: str, payload: dict):
    """Lanza Sunshine bajo demanda para conectar con Moonlight desde el móvil."""
    if not SUNSHINE_EXE:
        raise RuntimeError("No se encontró Sunshine instalado (define SUNSHINE_EXE en .env)")
    report_stage(job_id, "streaming_starting", "Lanzando Sunshine")
    log.info(f"Lanzando Sunshine desde {SUNSHINE_EXE}...")
    # DETACHED: Sunshine sobrevive a la salida del agente y sigue sirviendo el stream.
    subprocess.Popen(
        [SUNSHINE_EXE],
        creationflags=subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP,
        stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )
    report_stage(job_id, "streaming_ready", "Sunshine abierto — conéctate con Moonlight")
    log.info("✅ Sunshine lanzado.")


ACCIONES = {
    "resolver_alud":   accion_resolver_alud,
    "abrir_streaming": accion_abrir_streaming,
}


def resolver_accion(payload: dict) -> str:
    """Determina la acción del job. Compatibilidad: los jobs antiguos no traían
    'accion' pero sí 'alud_url' → se tratan como 'resolver_alud'."""
    accion = payload.get("accion")
    if not accion and payload.get("alud_url"):
        accion = "resolver_alud"
    return accion


def procesar_job(job: dict):
    """Reclama un job, ejecuta su acción y lo cierra (done/failed)."""
    job_id  = job["id"]
    payload = job.get("payload", {}) or {}
    accion  = resolver_accion(payload)
    handler = ACCIONES.get(accion)

    if handler is None:
        log.warning(f"Acción desconocida o ausente: {accion!r} — marcando job como fallido.")
        if claim_job(job_id):
            start_job(job_id)
            finish_job(job_id, "failed")
            report_stage(job_id, "job_done", f"failed: acción desconocida '{accion}'")
        return

    if not claim_job(job_id):
        log.info("Job ya reclamado por otro worker.")
        return

    report_stage(job_id, "job_claimed", f"Worker {WORKER_ID} reclamó el job ({accion})")
    start_job(job_id)
    heartbeat("busy")
    try:
        handler(job_id, payload)
        finish_job(job_id, "done")
        report_stage(job_id, "job_done", "done")
        log.info(f"✅ Job '{accion}' completado.")
    except Exception as e:
        log.error(f"Error en job '{accion}': {e}", exc_info=True)
        finish_job(job_id, "failed")
        report_stage(job_id, "job_done", f"failed: {e}")


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    if not LA_TOKEN:
        log.error("LA_TOKEN no configurado en .env — abortando.")
        sys.exit(1)

    log.info(f"Agente iniciado. Worker: {WORKER_ID}")
    log.info(f"Sunshine: {SUNSHINE_EXE or 'NO ENCONTRADO'}")

    # Efímero: mira si hay algo pendiente. Si no hay nada, se cierra sin más.
    job = poll_pending_job()
    if not job:
        log.info("No hay jobs pendientes. Agente finalizado sin acción.")
        return

    heartbeat("online")
    # Cada job se intenta como máximo una vez por ejecución: si claim/finish falla por
    # un error de red y el job sigue 'pending', evitamos volver a recogerlo en bucle
    # (lo reintentará la próxima ejecución del agente).
    attempted = set()
    try:
        # Drena la cola: procesa jobs mientras queden pendientes nuevos, luego termina.
        while job and job["id"] not in attempted:
            attempted.add(job["id"])
            procesar_job(job)
            job = poll_pending_job()
    finally:
        heartbeat("offline")
        log.info("Agente finalizado.")


if __name__ == "__main__":
    main()
