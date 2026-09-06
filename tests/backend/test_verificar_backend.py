"""Tests de `scripts/verificar_backend.py` (el smoke test de un backend recién desplegado).

No hay red: se sustituye `verificar._peticion`, que es el único punto por el que
el script sale afuera.

Este verificador se escribió para la mudanza de Fly a Koyeb y su valor entero
depende de una propiedad: **que no dé por buena una comprobación que no ha
hecho**. Si miente, migras a ciegas creyendo que no. De ahí que los dos casos
más cuidados aquí sean el falso OK por credenciales ausentes y el falso FALLO
por leer mal una cabecera — este último ocurrió de verdad contra producción
antes de que los tests existieran.
"""
import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "scripts"))

import verificar_backend as verificar  # noqa: E402


BASE = "https://backend.test"
ORIGEN = "https://life-assistant-smoky.vercel.app"


@pytest.fixture(autouse=True)
def _limpiar(monkeypatch):
    """El script acumula el resultado en globales de módulo; sin esto un test
    heredaría los fallos del anterior."""
    verificar.fallos.clear()
    verificar.saltadas.clear()
    for var in ("DASHBOARD_PASSWORD", "HA_POLL_TOKEN", "CORS_ORIGIN"):
        monkeypatch.delenv(var, raising=False)


def _responder(monkeypatch, respuestas):
    """`respuestas` mapea (metodo, ruta) -> (status, cabeceras, texto)."""
    def falsa(url, metodo="GET", cabeceras=None, cuerpo=None):
        ruta = url[len(BASE):]
        return respuestas[(metodo, ruta)]

    monkeypatch.setattr(verificar, "_peticion", falsa)


# ── Cabeceras ────────────────────────────────────────────────────────────────

def test_minusculas_normaliza_las_claves():
    """HTTP define las cabeceras como insensibles a mayúsculas y un dict de
    Python no lo es. Sobre HTTP/2 llegan en minúsculas."""
    assert verificar._minusculas({"Access-Control-Allow-Origin": "x"}) == {
        "access-control-allow-origin": "x"
    }


def test_cors_no_falla_por_el_caso_de_la_cabecera(monkeypatch):
    """El fallo real: se buscaba `Access-Control-Allow-Origin` en un dict cuya
    clave era `access-control-allow-origin`, y un CORS que funcionaba se
    declaraba roto."""
    _responder(monkeypatch, {
        ("OPTIONS", "/auth/password"): (
            200, {"access-control-allow-origin": ORIGEN}, ""
        ),
    })
    verificar.comprobar_cors(BASE)
    assert verificar.fallos == []


def test_cors_detecta_un_origen_no_permitido(monkeypatch):
    """Un CORS mal puesto se manifiesta en la UI como «credenciales
    incorrectas», así que tiene que saltar aquí."""
    _responder(monkeypatch, {
        ("OPTIONS", "/auth/password"): (200, {}, ""),
    })
    verificar.comprobar_cors(BASE)
    assert verificar.fallos == ["CORS"]


# ── Nada se da por bueno sin comprobarlo ─────────────────────────────────────

def test_login_sin_contrasena_es_saltada_no_ok():
    verificar.comprobar_login(BASE)
    assert verificar.saltadas == ["login"]
    assert verificar.fallos == []


def test_token_de_servicio_sin_token_es_saltada_no_ok():
    verificar.comprobar_token_servicio(BASE)
    assert verificar.saltadas == ["token de servicio"]
    assert verificar.fallos == []


# ── Login ────────────────────────────────────────────────────────────────────

def test_login_lee_el_campo_token(monkeypatch):
    """`/auth/password` devuelve `{"token": ...}`, no `access_token`."""
    monkeypatch.setenv("DASHBOARD_PASSWORD", "secreta")
    _responder(monkeypatch, {
        ("POST", "/auth/password"): (200, {}, '{"token": "jwt-de-prueba"}'),
    })
    verificar.comprobar_login(BASE)
    assert verificar.fallos == []


def test_login_falla_si_el_200_no_trae_token(monkeypatch):
    monkeypatch.setenv("DASHBOARD_PASSWORD", "secreta")
    _responder(monkeypatch, {
        ("POST", "/auth/password"): (200, {}, "{}"),
    })
    verificar.comprobar_login(BASE)
    assert verificar.fallos == ["login"]


def test_login_con_rate_limit_no_cuenta_como_fallo(monkeypatch):
    """El límite es global y por intentos fallidos: toparse con él mientras se
    verifica no dice nada del despliegue."""
    monkeypatch.setenv("DASHBOARD_PASSWORD", "secreta")
    _responder(monkeypatch, {
        ("POST", "/auth/password"): (429, {}, ""),
    })
    verificar.comprobar_login(BASE)
    assert verificar.fallos == []
    assert verificar.saltadas == ["login"]


# ── Auth de servicio ─────────────────────────────────────────────────────────

def test_token_de_servicio_correcto(monkeypatch):
    monkeypatch.setenv("HA_POLL_TOKEN", "token-ha")
    _responder(monkeypatch, {
        ("GET", "/ha/wol-pending"): (200, {}, "{}"),
    })
    # La segunda llamada (sin token) tiene que devolver otra cosa: se resuelve
    # por el contenido de las cabeceras que manda el script.
    llamadas = []

    def falsa(url, metodo="GET", cabeceras=None, cuerpo=None):
        llamadas.append(cabeceras)
        return (200, {}, "{}") if cabeceras else (403, {}, "")

    monkeypatch.setattr(verificar, "_peticion", falsa)
    verificar.comprobar_token_servicio(BASE)
    assert verificar.fallos == []
    assert len(llamadas) == 2


def test_token_de_servicio_detecta_endpoint_desprotegido(monkeypatch):
    """Si responde 200 SIN token, la casa y la ingesta de salud quedan abiertas
    a internet. Es el peor resultado posible y no puede pasar en silencio."""
    monkeypatch.setenv("HA_POLL_TOKEN", "token-ha")
    monkeypatch.setattr(
        verificar, "_peticion", lambda *a, **k: (200, {}, "{}")
    )
    verificar.comprobar_token_servicio(BASE)
    assert verificar.fallos == ["token de servicio"]


# ── Arranque ─────────────────────────────────────────────────────────────────

def test_backend_caido_se_reporta_sin_reventar(monkeypatch):
    """Un fallo de red es un dato, no una excepción: `_peticion` devuelve
    status None y el script tiene que contarlo."""
    monkeypatch.setattr(
        verificar, "_peticion", lambda *a, **k: (None, {}, "connection refused")
    )
    verificar.comprobar_vivo(BASE)
    assert verificar.fallos == ["responde"]


# ── Identidad del cliente ────────────────────────────────────────────────────

def test_manda_un_user_agent_propio(monkeypatch):
    """El User-Agent por defecto de urllib (`Python-urllib/3.x`) está en las
    reglas de bots de Cloudflare y responde 403. Con el backend detrás de un
    túnel de Cloudflare, el verificador declaraba caído un servicio que
    respondía 200 a curl y a `requests`. Se comprobó UA por UA."""
    vistas = {}

    class RespuestaFalsa:
        status = 200
        headers = {}

        def read(self):
            return b'{"status": "Life Assistant API running"}'

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    def urlopen_falso(req, timeout=None):
        vistas["ua"] = req.get_header("User-agent")
        return RespuestaFalsa()

    monkeypatch.setattr(verificar.urllib.request, "urlopen", urlopen_falso)
    verificar.comprobar_vivo("https://backend.test")

    assert vistas["ua"], "no se mandó ningún User-Agent"
    assert "urllib" not in vistas["ua"].lower()
