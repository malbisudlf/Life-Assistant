#!/usr/bin/env python3
"""El chat escrito de Jarvis, pensado por Claude Code. Corre en `caja`, fuera de Docker.

El backend le manda cada turno del chat (`POST /turno`) y esto lanza `claude -p` —una
sesión normal de Claude Code, con la suscripción con la que está iniciada la CLI en esta
máquina— con UNA sola cosa a mano: el servidor MCP de Jarvis (`/mcp/chat` del backend).
Ver «El chat con Claude Code» en docs/JARVIS.md.

Lo que no se negocia, y por eso los argumentos de `claude` se montan AQUÍ y no los
manda el backend:

- **Sin herramientas propias** (`--tools ""`): ni terminal, ni ficheros, ni web. Al chat
  llegan correos, páginas y documentos que ha escrito cualquiera; con una terminal, un
  texto bien escrito podría acabar en un comando en la máquina que lo aloja todo.
- **Solo el MCP de Jarvis** (`--strict-mcp-config`): los servidores MCP que tenga
  configurados el usuario de esta máquina —el del teléfono incluido— no se cargan.
- **Nada que preguntar** (`--permission-mode dontAsk` + `--allowedTools mcp__jarvis`): no
  hay nadie delante para aprobar un permiso. Lo que necesita confirmación lo resuelve el
  propio MCP, que lo deja propuesto para el botón del dashboard.
- `--restricted` si la versión de Claude Code lo tiene: otra capa encima de lo anterior.

Sin dependencias: biblioteca estándar de Python, para no tener que mantener otro entorno.
"""
import hmac
import json
import os
import re
import subprocess
import sys
import tempfile
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

TOKEN      = os.environ.get("JARVIS_CLAUDE_TOKEN", "")
MCP_URL    = os.environ.get("JARVIS_MCP_URL", "").rstrip("/")
MCP_TOKEN  = os.environ.get("JARVIS_MCP_CHAT_TOKEN", "")
MODELO     = os.environ.get("JARVIS_CLAUDE_MODELO", "claude-sonnet-5-5")
CLAUDE_BIN = os.environ.get("CLAUDE_BIN", "claude")
HOST       = os.environ.get("JARVIS_CLAUDE_HOST", "127.0.0.1")
PUERTO     = int(os.environ.get("JARVIS_CLAUDE_PUERTO", "3340"))
# Un poco por debajo del tope del backend (JARVIS_CLAUDE_TIMEOUT, 150 s): si se cuelga,
# que lo mate esto y no se quede un `claude` huérfano corriendo.
TIMEOUT_S  = int(os.environ.get("JARVIS_CLAUDE_TIMEOUT", "140"))
# Cuántas sesiones a la vez. Es un chat de una persona: más de dos a la vez es que algo
# reintenta en bucle, y cada una es un proceso de Node entero.
MAX_A_LA_VEZ = int(os.environ.get("JARVIS_CLAUDE_CONCURRENCIA", "2"))
MAX_CUERPO   = 512 * 1024
# El directorio de trabajo: vacío a propósito, para que no se cuele el CLAUDE.md de
# ningún proyecto (el del teléfono vive en otro).
DIRECTORIO = os.environ.get("JARVIS_CLAUDE_DIR", os.path.expanduser("~/jarvis-chat"))

_UUID = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$")
_cupo = threading.BoundedSemaphore(MAX_A_LA_VEZ)


def _opciones_disponibles() -> str:
    """La ayuda de la CLI, para saber qué opciones tiene ESTA versión."""
    try:
        return subprocess.run([CLAUDE_BIN, "--help"], capture_output=True, text=True,
                              timeout=30).stdout
    except (OSError, subprocess.SubprocessError):
        return ""


def entorno() -> dict:
    """El entorno de `claude`: el del servicio, sin el buscador de herramientas.

    Claude Code (2.1) no le da al modelo las herramientas MCP de entrada: las deja tras su
    buscador de herramientas, que es una herramienta propia más. Con `--tools ""` ese
    buscador también desaparece, y Jarvis arrancaba cada turno con las 76 herramientas
    conectadas e invisibles: «no tengo acceso al tiempo», con el MCP en verde. Visto el
    2026-10-13, la primera vez que se probó en `caja` contra el backend de verdad.
    """
    return {**os.environ, "ENABLE_TOOL_SEARCH": "false"}


def comando(mcp_config: str, sistema: str, ayuda: str) -> list:
    """Los argumentos de `claude`. Se exportan para poder probarlos sin lanzarlo."""
    args = [CLAUDE_BIN, "-p",
            "--model", MODELO,
            "--output-format", "json",
            "--tools", "",
            "--strict-mcp-config", "--mcp-config", mcp_config,
            "--allowedTools", "mcp__jarvis",
            "--permission-mode", "dontAsk",
            "--no-session-persistence"]
    if "--restricted" in ayuda:
        args.append("--restricted")
    # El prompt de Jarvis SUSTITUYE al de Claude Code, que es el de un asistente de
    # programación. En fichero, porque como argumento puede pasar del límite del sistema.
    if "--system-prompt-file" in ayuda:
        args += ["--system-prompt-file", sistema]
    else:
        with open(sistema, encoding="utf-8") as f:
            args += ["--system-prompt", f.read()]
    return args


def config_mcp(turno: str) -> dict:
    """El único servidor MCP de la sesión. El turno va en la URL: es lo que ata lo que
    pase dentro de `/mcp/chat` a la respuesta de este turno."""
    return {"mcpServers": {"jarvis": {
        "type": "http",
        "url": f"{MCP_URL}?turno={turno}",
        "headers": {"Authorization": f"Bearer {MCP_TOKEN}"},
    }}}


def leer_salida(salida: str) -> dict:
    """Lo que devuelve `claude -p --output-format json`: un objeto con `result`."""
    try:
        datos = json.loads(salida or "{}")
    except json.JSONDecodeError:
        return {"error": "Claude Code no devolvió JSON"}
    if not isinstance(datos, dict):
        return {"error": "Claude Code devolvió algo inesperado"}
    if datos.get("is_error") or datos.get("subtype") not in (None, "success"):
        return {"error": str(datos.get("result") or datos.get("subtype") or "error")[:300]}
    return {"respuesta": str(datos.get("result") or "").strip(),
            "turnos": datos.get("num_turns")}


def turno(cuerpo: dict, ayuda: str) -> tuple:
    """Un turno entero. Devuelve (código HTTP, respuesta)."""
    turno_id = str(cuerpo.get("turno") or "")
    prompt   = str(cuerpo.get("prompt") or "").strip()
    sistema  = str(cuerpo.get("sistema") or "")
    if not _UUID.match(turno_id) or not prompt:
        return 400, {"error": "Falta el turno o el mensaje"}
    if not _cupo.acquire(blocking=False):
        return 429, {"error": "Ya hay demasiadas sesiones a la vez"}
    try:
        os.makedirs(DIRECTORIO, exist_ok=True)
        with tempfile.TemporaryDirectory(prefix="jarvis-") as tmp:
            mcp = os.path.join(tmp, "mcp.json")
            sis = os.path.join(tmp, "sistema.txt")
            # Llevan el token del MCP: solo para este usuario, y se borran al salir.
            with open(os.open(mcp, os.O_WRONLY | os.O_CREAT, 0o600), "w", encoding="utf-8") as f:
                json.dump(config_mcp(turno_id), f)
            with open(sis, "w", encoding="utf-8") as f:
                f.write(sistema)
            try:
                hecho = subprocess.run(comando(mcp, sis, ayuda), input=prompt,
                                       capture_output=True, text=True, cwd=DIRECTORIO,
                                       env=entorno(), timeout=TIMEOUT_S)
            except subprocess.TimeoutExpired:
                return 504, {"error": f"Claude Code no terminó en {TIMEOUT_S} s"}
            except OSError as e:
                return 503, {"error": f"No se pudo lanzar Claude Code ({e})"}
        datos = leer_salida(hecho.stdout)
        if "error" in datos or hecho.returncode != 0:
            # La sesión OAuth caducada sale por aquí, y es lo primero que hay que poder leer.
            print(f"jarvis-claude: falló el turno (código {hecho.returncode}): "
                  f"{datos.get('error') or ''} {hecho.stderr[-500:]}", file=sys.stderr, flush=True)
            return 502, {"error": datos.get("error") or f"Claude Code salió con {hecho.returncode}"}
        return 200, datos
    finally:
        _cupo.release()


class Manejador(BaseHTTPRequestHandler):
    ayuda = ""

    def _responder(self, codigo: int, datos: dict) -> None:
        cuerpo = json.dumps(datos, ensure_ascii=False).encode("utf-8")
        self.send_response(codigo)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(cuerpo)))
        self.end_headers()
        self.wfile.write(cuerpo)

    def do_GET(self):
        if self.path == "/salud":
            return self._responder(200, {"ok": True, "modelo": MODELO})
        self._responder(404, {"error": "No existe"})

    def do_POST(self):
        recibido = self.headers.get("Authorization", "")
        # Sin token configurado no entra nadie: fail-closed, como en el backend.
        if not TOKEN or not hmac.compare_digest(recibido.encode(), f"Bearer {TOKEN}".encode()):
            return self._responder(401, {"error": "Token inválido"})
        if self.path != "/turno":
            return self._responder(404, {"error": "No existe"})
        try:
            largo = int(self.headers.get("Content-Length") or 0)
        except ValueError:
            largo = 0
        if not 0 < largo <= MAX_CUERPO:
            return self._responder(413, {"error": "Cuerpo vacío o demasiado grande"})
        try:
            cuerpo = json.loads(self.rfile.read(largo).decode("utf-8"))
        except (json.JSONDecodeError, UnicodeDecodeError):
            return self._responder(400, {"error": "JSON inválido"})
        if not isinstance(cuerpo, dict):
            return self._responder(400, {"error": "JSON inválido"})
        self._responder(*turno(cuerpo, self.ayuda))

    def log_message(self, formato, *args):
        # Sin el cuerpo: lleva lo que has escrito en el chat.
        print(f"jarvis-claude: {self.address_string()} {formato % args}", file=sys.stderr, flush=True)


def main() -> None:
    faltan = [n for n, v in (("JARVIS_CLAUDE_TOKEN", TOKEN), ("JARVIS_MCP_URL", MCP_URL),
                             ("JARVIS_MCP_CHAT_TOKEN", MCP_TOKEN)) if not v]
    if faltan:
        sys.exit(f"jarvis-claude: faltan {', '.join(faltan)}")
    Manejador.ayuda = _opciones_disponibles()
    if "--tools" not in Manejador.ayuda:
        # Sin `--tools` no hay forma de quitarle la terminal: mejor no arrancar.
        sys.exit("jarvis-claude: esta versión de Claude Code no tiene --tools; actualízala")
    print(f"jarvis-claude: escuchando en {HOST}:{PUERTO} con {MODELO}", file=sys.stderr, flush=True)
    ThreadingHTTPServer((HOST, PUERTO), Manejador).serve_forever()


if __name__ == "__main__":
    main()
