"""moodle-mcp (github.com/loyaniu/moodle-mcp) servido por HTTP y con llave.

El paquete de origen solo sabe hablar por stdio, que es lo que pide Claude Desktop: un
proceso hijo por cliente. Jarvis no es un proceso hijo de nadie —su cliente MCP habla
Streamable HTTP (`_mcp_rpc` en `backend/main.py`)—, así que esto lo levanta como servidor
HTTP en `caja` sin tocar una línea del original. Tres cosas que el original no trae y que
aquí no son opcionales:

1. UNA LLAVE. El original no tiene autenticación porque por stdio no le hace falta: solo
   le habla quien lo lanzó. Por HTTP le habla cualquiera que llegue al puerto, y detrás
   está el token de Moodle, con el que se leen notas, entregas y foros. Sin
   `MOODLE_MCP_TOKEN` no arranca (mismo criterio que `SECRET_KEY` en el backend: un
   valor por defecto en un repositorio público es una llave publicada).
2. TODO ES DE SOLO LECTURA, y se declara. Las 24 herramientas del original solo hacen GET
   a la API de Moodle, pero no lo anotan, y el cliente de Jarvis pide confirmación ante
   la duda (`_mcp_pide_confirmar`): sin la anotación, cada «¿qué entregas tengo?» sería
   un botón que aprobar. Si una versión nueva del original trae una herramienta que
   ESCRIBE, esta anotación mentiría — por eso la versión va fijada en el Dockerfile y
   subirla obliga a volver a mirar la lista.
3. EL TOKEN DE MOODLE, FUERA DE LA URL. El original lo manda por GET como `wstoken=` en
   la query, y `requests` mete la URL entera en el texto de sus excepciones: un Moodle
   caído devolvía el token, en claro, como resultado de la herramienta —o sea, al modelo
   y a la conversación—. Aquí va por POST en el cuerpo, que el servicio REST de Moodle
   acepta igual, y de paso no queda en los registros de ningún proxy.
4. Sin la protección de DNS rebinding del SDK. Solo admite `Host: localhost`, así que
   desde otra máquina de la LAN (o desde otro contenedor) contestaba 421 a todo. Esa
   protección existe para servidores locales SIN autenticación; aquí la puerta es la
   llave, que un navegador engañado no conoce.

DOS MODOS, según haya o no `MOODLE_MCP_URL_PUBLICA`:

- **Sin ella (LAN)**: solo la llave, en `Authorization: Bearer`. Es lo que usa Jarvis.
- **Con ella (público, por el Cloudflare Tunnel)**: además, el inicio de sesión OAuth que
  pide la app de Claude para un conector propio (`oauth.py`, con el porqué). La llave
  sigue valiendo igual. Sin `MOODLE_MCP_CLAVE` este modo no arranca: un OAuth sin clave
  sería dar acceso a tus notas a cualquiera que encontrara la URL.
"""

import hmac
import os
import sys

# El original lee MOODLE_URL al importarse y la quiere entera, con la ruta del servicio
# REST. Aquí basta con la del sitio (la misma `MOODLE_URL` que usa el backend), y se
# completa ANTES de importar nada suyo.
_SERVICIO = "/webservice/rest/server.php"
_url = os.getenv("MOODLE_URL", "").strip().rstrip("/")
if not _url.startswith("https://") or not os.getenv("MOODLE_TOKEN", "").strip():
    sys.exit("Faltan MOODLE_URL (https://...) o MOODLE_TOKEN: ver docker/moodle-mcp/.env.example")
if not _url.endswith(_SERVICIO):
    _url += _SERVICIO
os.environ["MOODLE_URL"] = _url

LLAVE = os.getenv("MOODLE_MCP_TOKEN", "").strip()
if len(LLAVE) < 32:
    sys.exit("MOODLE_MCP_TOKEN falta o es corto (mínimo 32 caracteres): openssl rand -hex 32")

URL_PUBLICA = os.getenv("MOODLE_MCP_URL_PUBLICA", "").strip().rstrip("/")
CLAVE       = os.getenv("MOODLE_MCP_CLAVE", "")
if URL_PUBLICA and (not URL_PUBLICA.startswith("https://") or len(CLAVE) < 12):
    sys.exit("Con MOODLE_MCP_URL_PUBLICA hacen falta una URL https:// y MOODLE_MCP_CLAVE "
             "(mínimo 12 caracteres): ver docker/moodle-mcp/.env.example")

import requests                                         # noqa: E402
import uvicorn                                          # noqa: E402
from mcp.server.transport_security import TransportSecuritySettings  # noqa: E402
from mcp.types import ToolAnnotations                   # noqa: E402
from moodle_mcp import moodle as _moodle                # noqa: E402
from moodle_mcp.server import mcp                       # noqa: E402


class _PorPost:
    """Lo único que el original usa de `requests`, con el GET cambiado por un POST."""
    RequestException = requests.RequestException

    @staticmethod
    def get(url, params=None, timeout=30):
        return requests.post(url, data=params, timeout=timeout)


_moodle.requests = _PorPost

for herramienta in mcp._tool_manager.list_tools():
    herramienta.annotations = ToolAnnotations(readOnlyHint=True)

mcp.settings.transport_security = TransportSecuritySettings(enable_dns_rebinding_protection=False)
# Respuestas JSON en vez de SSE y sin sesión que recordar: el cliente de Jarvis entiende
# las dos cosas, pero así un reinicio del contenedor no deja a nadie con una sesión
# que el servidor ya no conoce.
mcp.settings.json_response = True
mcp.settings.stateless_http = True


class Puerta:
    """Middleware ASGI: sin `Authorization: Bearer <MOODLE_MCP_TOKEN>`, 401.

    Deja pasar lo que no es HTTP (el `lifespan`), que es lo que arranca el gestor de
    sesiones del SDK: cortarlo dejaría el servidor contestando 500 a todo.
    """

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)
        cabeceras = dict(scope.get("headers") or [])
        dada = cabeceras.get(b"authorization", b"").decode("latin-1")
        if not (dada.startswith("Bearer ")
                and hmac.compare_digest(dada[7:].strip().encode(), LLAVE.encode())):
            await send({"type": "http.response.start", "status": 401,
                        "headers": [(b"content-type", b"application/json"),
                                    (b"www-authenticate", b"Bearer")]})
            await send({"type": "http.response.body", "body": b'{"error":"no autorizado"}'})
            return
        return await self.app(scope, receive, send)


def _app():
    if not URL_PUBLICA:
        return Puerta(mcp.streamable_http_app())

    from mcp.server.auth.settings import AuthSettings, ClientRegistrationOptions, RevocationOptions
    from oauth import Proveedor, Verificador

    proveedor = Proveedor(URL_PUBLICA, CLAVE,
                          os.getenv("MOODLE_MCP_DATOS", "/datos/oauth.json"))
    mcp.settings.auth = AuthSettings(
        issuer_url=URL_PUBLICA, resource_server_url=f"{URL_PUBLICA}/mcp",
        client_registration_options=ClientRegistrationOptions(enabled=True),
        revocation_options=RevocationOptions(enabled=True),
        # El token se comprueba contra lo guardado, que ya dice para qué se emitió.
        validate_token_resource=False,
    )
    # Por los atributos y no por el constructor: el `FastMCP` lo crea el paquete original
    # al importarse, y este fichero no toca su código.
    mcp._auth_server_provider = proveedor
    mcp._token_verifier = Verificador(proveedor, LLAVE)
    mcp.custom_route("/entrar", methods=["GET", "POST"])(proveedor.pagina)
    # Sin `Puerta`: con OAuth, el 401 lo da el SDK, y lo da con el `WWW-Authenticate`
    # que la app de Claude necesita para encontrar dónde iniciar sesión.
    return mcp.streamable_http_app()


if __name__ == "__main__":
    uvicorn.run(_app(), host="0.0.0.0",
                port=int(os.getenv("MOODLE_MCP_PUERTO", "8765")),
                # Sin el registro de accesos de uvicorn: no lleva secretos (la llave va en
                # cabecera), pero en un contenedor que nadie mira es ruido en el disco.
                access_log=False)
