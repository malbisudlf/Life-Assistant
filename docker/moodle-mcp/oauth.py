"""El inicio de sesión que pide la app de Claude para usar un servidor MCP propio.

Por qué existe: los conectores de claude.ai (web, escritorio, móvil y las sesiones de
Claude Code en la nube) llaman al servidor DESDE LOS SERVIDORES DE ANTHROPIC, no desde tu
máquina. Eso pide dos cosas que el modo LAN no tiene: una URL https pública, y una forma
de autenticarse que esa app sepa usar. La llave fija en una cabecera no vale: la sección
«Request headers» de los conectores está en beta para unas pocas organizaciones, y en un
plan personal no aparece. Lo que sí sabe hacer siempre es OAuth.

Así que esto es un servidor OAuth mínimo, montado sobre el que trae el SDK de MCP (que ya
hace el descubrimiento, el registro dinámico de clientes, PKCE y el canje de códigos).
Lo único que se escribe aquí es lo que el SDK deja a cada uno:

- **Quién da el permiso**: una página (`/entrar`) que pide `MOODLE_MCP_CLAVE`. No hay
  usuarios: es un servidor de una sola persona, y la clave es la persona.
- **A dónde puede volver un permiso**: solo a la app de Claude y a Claude Code en tu
  máquina (`_redireccion_permitida`). Sin esto, cualquiera podría registrar un cliente
  que devuelva el código a su web y mandarte el enlace: tú pondrías la clave en una
  página que es de verdad la tuya, y el código acabaría en la suya.
- **Dónde se guarda**: un JSON en un volumen. Si se perdiera en cada reinicio, la app de
  Claude se quedaría con un token que ya no vale y habría que volver a conectarla a mano.
  De los tokens solo se guarda el hash: quien lea el fichero no se lleva nada usable.

La llave fija (`MOODLE_MCP_TOKEN`) sigue valiendo en este modo, para Jarvis y para Claude
Code: la comprueba `Verificador` antes de mirar los tokens de OAuth.
"""

import hashlib
import hmac
import html
import json
import os
import secrets
import time
from urllib.parse import urlsplit

from mcp.server.auth.provider import (
    AccessToken,
    AuthorizationCode,
    AuthorizationParams,
    RefreshToken,
    RegistrationError,
    TokenError,
    construct_redirect_uri,
)
from mcp.shared.auth import OAuthClientInformationFull, OAuthToken
from starlette.requests import Request
from starlette.responses import HTMLResponse, RedirectResponse, Response

# Las dos callbacks de la app de Claude (web, escritorio, móvil). Claude Code usa una
# redirección a localhost en un puerto que cambia, y esa se admite aparte.
_CALLBACKS_CLAUDE = {
    "https://claude.ai/api/mcp/auth_callback",
    "https://claude.com/api/mcp/auth_callback",
}
ACCESO_S        = 3600                  # lo que dura un token de acceso
REFRESCO_S      = 90 * 86400            # lo que dura uno de refresco
CODIGO_S        = 300                   # el código, entre la clave y el canje
SOLICITUD_S     = 600                   # la página de la clave, abierta
MAX_CLIENTES    = 50                    # el registro dinámico es abierto: con tope
MAX_FALLOS      = 5                     # claves mal puestas antes de cerrar la puerta…
VENTANA_FALLOS  = 15 * 60               # …durante este rato


def _hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def _redireccion_permitida(uri: str) -> bool:
    if uri in _CALLBACKS_CLAUDE:
        return True
    partes = urlsplit(uri)
    # Claude Code: http a localhost o 127.0.0.1, en el puerto que le toque (RFC 8252).
    return partes.scheme == "http" and partes.hostname in ("localhost", "127.0.0.1")


class Proveedor:
    """Lo que el SDK llama `OAuthAuthorizationServerProvider`."""

    def __init__(self, base: str, clave: str, fichero: str):
        self.base, self.clave, self.fichero = base.rstrip("/"), clave, fichero
        self.solicitudes: dict = {}     # id → (cliente, params, caduca): en memoria
        self.codigos: dict = {}         # código → AuthorizationCode: en memoria
        self.fallos: list = []          # horas de los últimos intentos fallidos
        self.estado = {"clientes": {}, "acceso": {}, "refresco": {}}
        try:
            with open(fichero, encoding="utf-8") as f:
                self.estado.update(json.load(f))
        except FileNotFoundError:
            pass

    # ── Persistencia ──

    def _guardar(self):
        ahora = time.time()
        for tipo in ("acceso", "refresco"):
            self.estado[tipo] = {h: t for h, t in self.estado[tipo].items()
                                 if (t.get("expires_at") or ahora + 1) > ahora}
        temporal = self.fichero + ".tmp"
        with open(temporal, "w", encoding="utf-8") as f:
            json.dump(self.estado, f)
        os.chmod(temporal, 0o600)
        os.replace(temporal, self.fichero)

    # ── Clientes ──

    async def get_client(self, client_id: str):
        datos = self.estado["clientes"].get(client_id)
        return OAuthClientInformationFull.model_validate(datos) if datos else None

    async def register_client(self, client_info: OAuthClientInformationFull) -> None:
        uris = [str(u) for u in (client_info.redirect_uris or [])]
        if not uris or not all(_redireccion_permitida(u) for u in uris):
            raise RegistrationError("invalid_redirect_uri",
                                    "Solo se admiten la app de Claude y Claude Code en local.")
        clientes = self.estado["clientes"]
        while len(clientes) >= MAX_CLIENTES:
            # El más antiguo fuera: el registro lo puede llamar cualquiera, y sin tope
            # bastaría un bucle para llenar el disco.
            del clientes[min(clientes, key=lambda c: clientes[c].get("client_id_issued_at") or 0)]
        clientes[client_info.client_id] = client_info.model_dump(mode="json", exclude_none=True)
        self._guardar()

    # ── Autorización: la página de la clave ──

    async def authorize(self, client: OAuthClientInformationFull, params: AuthorizationParams) -> str:
        ahora = time.time()
        self.solicitudes = {k: v for k, v in self.solicitudes.items() if v[2] > ahora}
        solicitud = secrets.token_urlsafe(32)
        self.solicitudes[solicitud] = (client, params, ahora + SOLICITUD_S)
        return f"{self.base}/entrar?solicitud={solicitud}"

    def _cerrada(self) -> bool:
        ahora = time.time()
        self.fallos = [t for t in self.fallos if t > ahora - VENTANA_FALLOS]
        return len(self.fallos) >= MAX_FALLOS

    async def pagina(self, request: Request) -> Response:
        if request.method == "POST":
            form = await request.form()
            solicitud = str(form.get("solicitud") or "")
        else:
            form, solicitud = {}, str(request.query_params.get("solicitud") or "")
        pendiente = self.solicitudes.get(solicitud)
        if not pendiente or pendiente[2] < time.time():
            return _html("Este enlace ha caducado. Vuelve a conectar desde la app de Claude.",
                         estado=400)
        cliente, params, _ = pendiente
        if request.method == "GET":
            return _formulario(solicitud, cliente, params)

        if form.get("accion") == "denegar":
            del self.solicitudes[solicitud]
            return RedirectResponse(construct_redirect_uri(
                str(params.redirect_uri), error="access_denied", state=params.state), 302)
        if self._cerrada():
            return _formulario(solicitud, cliente, params,
                               "Demasiados intentos fallidos. Espera un cuarto de hora.", 429)
        if not hmac.compare_digest(str(form.get("clave") or "").encode(), self.clave.encode()):
            self.fallos.append(time.time())
            return _formulario(solicitud, cliente, params, "Esa no es la clave.", 403)

        del self.solicitudes[solicitud]
        codigo = secrets.token_urlsafe(32)
        self.codigos[codigo] = AuthorizationCode(
            code=codigo, scopes=params.scopes or [], expires_at=time.time() + CODIGO_S,
            client_id=cliente.client_id, code_challenge=params.code_challenge,
            redirect_uri=params.redirect_uri,
            redirect_uri_provided_explicitly=params.redirect_uri_provided_explicitly,
            resource=params.resource,
        )
        return RedirectResponse(construct_redirect_uri(
            str(params.redirect_uri), code=codigo, state=params.state), 302)

    # ── Códigos y tokens ──

    async def load_authorization_code(self, client, authorization_code: str):
        codigo = self.codigos.get(authorization_code)
        if not codigo or codigo.client_id != client.client_id or codigo.expires_at < time.time():
            return None
        return codigo

    def _emitir(self, client_id: str, scopes: list, resource) -> OAuthToken:
        acceso, refresco = secrets.token_urlsafe(32), secrets.token_urlsafe(48)
        ahora = int(time.time())
        comun = {"client_id": client_id, "scopes": scopes, "resource": resource}
        self.estado["refresco"][_hash(refresco)] = {**comun, "expires_at": ahora + REFRESCO_S}
        self.estado["acceso"][_hash(acceso)] = {**comun, "expires_at": ahora + ACCESO_S,
                                                "refresco": _hash(refresco)}
        self._guardar()
        return OAuthToken(access_token=acceso, expires_in=ACCESO_S, refresh_token=refresco,
                          scope=" ".join(scopes) or None)

    async def exchange_authorization_code(self, client, authorization_code) -> OAuthToken:
        # Se consume aquí: un código sirve una sola vez.
        if not self.codigos.pop(authorization_code.code, None):
            raise TokenError("invalid_grant", "El código ya se usó.")
        return self._emitir(client.client_id, authorization_code.scopes, authorization_code.resource)

    async def load_refresh_token(self, client, refresh_token: str):
        datos = self.estado["refresco"].get(_hash(refresh_token))
        if (not datos or datos["client_id"] != client.client_id
                or datos["expires_at"] < time.time()):
            return None
        return RefreshToken(token=refresh_token, **datos)

    async def exchange_refresh_token(self, client, refresh_token, scopes) -> OAuthToken:
        # Rotación: el de refresco viejo y sus tokens de acceso dejan de valer.
        self._revocar_refresco(_hash(refresh_token.token))
        return self._emitir(client.client_id, scopes or refresh_token.scopes, refresh_token.resource)

    async def load_access_token(self, token: str):
        datos = self.estado["acceso"].get(_hash(token))
        if not datos or datos["expires_at"] < time.time():
            return None
        return AccessToken(token=token, client_id=datos["client_id"], scopes=datos["scopes"],
                           expires_at=datos["expires_at"], resource=datos.get("resource"))

    def _revocar_refresco(self, h: str):
        self.estado["refresco"].pop(h, None)
        self.estado["acceso"] = {k: v for k, v in self.estado["acceso"].items()
                                 if v.get("refresco") != h}
        self._guardar()

    async def revoke_token(self, token) -> None:
        h = _hash(token.token)
        if h in self.estado["refresco"]:
            self._revocar_refresco(h)
        elif h in self.estado["acceso"]:
            self._revocar_refresco(self.estado["acceso"][h].get("refresco") or "")
            self.estado["acceso"].pop(h, None)
            self._guardar()


class Verificador:
    """La llave fija primero (Jarvis, Claude Code); si no, un token de OAuth."""

    def __init__(self, proveedor: Proveedor, llave: str):
        self.proveedor, self.llave = proveedor, llave

    async def verify_token(self, token: str):
        if hmac.compare_digest(token.encode(), self.llave.encode()):
            return AccessToken(token=token, client_id="llave", scopes=[])
        return await self.proveedor.load_access_token(token)


# ── La página ──

_CABECERAS = {
    # Una página que da permisos no se deja meter en un iframe ajeno: sería pedirte la
    # clave con un botón de otro encima.
    "X-Frame-Options": "DENY",
    "Content-Security-Policy": "default-src 'none'; style-src 'unsafe-inline'; form-action 'self'",
    "Cache-Control": "no-store",
    "Referrer-Policy": "no-referrer",
}


def _html(cuerpo: str, estado: int = 200) -> HTMLResponse:
    return HTMLResponse(
        "<!doctype html><meta charset=utf-8><meta name=viewport content='width=device-width'>"
        "<title>Moodle · Life Assistant</title>"
        "<body style='font-family:system-ui;max-width:26rem;margin:3rem auto;padding:0 1rem'>"
        f"{cuerpo}</body>", status_code=estado, headers=_CABECERAS)


def _formulario(solicitud, cliente, params, error: str = "", estado: int = 200) -> HTMLResponse:
    # El host al que vuelve el permiso, a la vista: lo exige la especificación de MCP y es
    # lo único que distingue esta página de una idéntica puesta por otro.
    vuelve = urlsplit(str(params.redirect_uri)).hostname or "?"
    nombre = cliente.client_name or "Un cliente sin nombre"
    aviso = f"<p style='color:#b00'>{html.escape(error)}</p>" if error else ""
    return _html(
        f"<h2>¿Dar acceso a tu Moodle?</h2>"
        f"<p><b>{html.escape(nombre)}</b> quiere leer tus cursos, entregas y notas.</p>"
        f"<p>El permiso vuelve a <code>{html.escape(vuelve)}</code>.</p>{aviso}"
        "<form method=post>"
        f"<input type=hidden name=solicitud value='{html.escape(solicitud, quote=True)}'>"
        "<p><input type=password name=clave autocomplete=current-password placeholder=Clave "
        "style='width:100%;padding:.5rem' autofocus></p>"
        "<button name=accion value=permitir>Permitir</button> "
        "<button name=accion value=denegar>No</button></form>", estado)
