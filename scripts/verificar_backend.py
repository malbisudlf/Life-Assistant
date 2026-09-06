#!/usr/bin/env python3
"""Comprueba que un backend recién desplegado responde como el de producción.

Nació para la mudanza de Fly a Koyeb (ver `docs/MIGRACION_BACKEND.md`): la idea
es levantar el backend nuevo con el viejo todavía en marcha y no cambiar ni un
apuntador hasta que esto salga limpio. Sirve igual para cualquier despliegue.

    python scripts/verificar_backend.py https://mi-backend.koyeb.app

Solo biblioteca estándar a propósito: se ejecuta desde cualquier sitio sin
instalar nada, incluso desde una máquina que no es la de desarrollo.

Las comprobaciones que necesitan credenciales se saltan solas si no están en el
entorno, y se dicen como SALTADA — nunca como OK. Un verificador que da por
buena una prueba que no ha hecho es peor que no tenerlo:

    DASHBOARD_PASSWORD=...  la contraseña del dashboard (auth de usuario)
    HA_POLL_TOKEN=...       el token de servicio que usa Home Assistant
    CORS_ORIGIN=...         origen a probar en el preflight (por defecto, Vercel)
"""

import json
import os
import sys
import urllib.error
import urllib.request

TIMEOUT = 30  # el arranque en frío de una plataforma que escala a cero es lento

ORIGEN_POR_DEFECTO = "https://life-assistant-smoky.vercel.app"

fallos = []
saltadas = []


def _peticion(url, metodo="GET", cabeceras=None, cuerpo=None):
    """Devuelve (status, cabeceras, texto). No lanza: un fallo de red es un dato.

    Las cabeceras salen con la clave en minúsculas porque HTTP las define como
    insensibles a mayúsculas y un `dict` de Python no lo es. Buscar
    `Access-Control-Allow-Origin` en un dict cuya clave llegó como
    `access-control-allow-origin` (lo normal sobre HTTP/2) daba None y este
    verificador declaraba roto un CORS que funcionaba.
    """
    req = urllib.request.Request(url, method=metodo, data=cuerpo)
    # Identificarse explícitamente, y no por cortesía: el User-Agent que urllib
    # pone por defecto (`Python-urllib/3.x`) está en las reglas de bots de
    # Cloudflare y responde **403**. Con el backend detrás de un túnel de
    # Cloudflare, el verificador daba por caído un servicio que funcionaba —
    # justo el falso negativo que este script existe para evitar.
    req.add_header("User-Agent", "life-assistant-verificador/1.0")
    for k, v in (cabeceras or {}).items():
        req.add_header(k, v)
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
            return r.status, _minusculas(r.headers), r.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as e:
        # Un 401 o un 429 son respuestas legítimas que aquí queremos inspeccionar.
        return e.code, _minusculas(e.headers), e.read().decode("utf-8", "replace")
    except Exception as e:
        return None, {}, str(e)


def _minusculas(cabeceras):
    return {k.lower(): v for k, v in cabeceras.items()}


def ok(nombre, detalle=""):
    print(f"  OK       {nombre}" + (f" — {detalle}" if detalle else ""))


def mal(nombre, detalle):
    print(f"  FALLO    {nombre} — {detalle}")
    fallos.append(nombre)


def saltada(nombre, motivo):
    print(f"  SALTADA  {nombre} — {motivo}")
    saltadas.append(nombre)


def comprobar_vivo(base):
    """El backend arranca. Si faltan SECRET_KEY o DASHBOARD_PASSWORD ni llega aquí:
    `main.py` lanza RuntimeError al importar (fail-fast, y es deliberado)."""
    status, _, texto = _peticion(base + "/")
    if status is None:
        return mal("responde", f"no se pudo conectar ({texto})")
    if status != 200:
        return mal("responde", f"HTTP {status}")
    try:
        if json.loads(texto).get("status") != "Life Assistant API running":
            return mal("responde", f"cuerpo inesperado: {texto[:120]}")
    except ValueError:
        return mal("responde", f"no devuelve JSON: {texto[:120]}")
    ok("responde", "el proceso arrancó, así que los secretos críticos están")


def comprobar_cors(base):
    """El fallo de CORS se disfraza de error de credenciales en el login y ha
    costado ya dos depuraciones largas. Se comprueba antes de tocar nada."""
    origen = os.getenv("CORS_ORIGIN", ORIGEN_POR_DEFECTO)
    status, cabeceras, _ = _peticion(
        base + "/auth/password",
        metodo="OPTIONS",
        cabeceras={
            "Origin": origen,
            "Access-Control-Request-Method": "POST",
            "Access-Control-Request-Headers": "content-type",
        },
    )
    if status is None:
        return mal("CORS", "no se pudo conectar")
    permitido = cabeceras.get("access-control-allow-origin")
    if permitido != origen:
        return mal(
            "CORS",
            f"el preflight de {origen} devuelve "
            f"Allow-Origin={permitido!r} — revisa CORS_ORIGINS",
        )
    ok("CORS", f"{origen} permitido")


def comprobar_login(base):
    """Auth de usuario: contraseña → JWT. Prueba de verdad SECRET_KEY."""
    clave = os.getenv("DASHBOARD_PASSWORD")
    if not clave:
        return saltada("login", "DASHBOARD_PASSWORD no está en el entorno")
    cuerpo = json.dumps({"password": clave}).encode()
    status, _, texto = _peticion(
        base + "/auth/password",
        metodo="POST",
        cabeceras={"Content-Type": "application/json"},
        cuerpo=cuerpo,
    )
    if status == 429:
        return saltada("login", "rate limit activo; reintenta en unos minutos")
    if status != 200:
        return mal("login", f"HTTP {status}: {texto[:120]}")
    if not json.loads(texto).get("token"):
        return mal("login", "200 pero sin token en la respuesta")
    ok("login", "contraseña aceptada y JWT emitido")


def comprobar_token_servicio(base):
    """Auth de servicio: es lo que usan HA, el Atajo de iOS y el agente. Si esto
    falla, el dashboard parece ir bien y la casa deja de responder en silencio."""
    token = os.getenv("HA_POLL_TOKEN")
    if not token:
        return saltada("token de servicio", "HA_POLL_TOKEN no está en el entorno")

    # Con la cabecera correcta: 200.
    status, _, texto = _peticion(
        base + "/ha/wol-pending", cabeceras={"X-Auth-Token": token}
    )
    if status != 200:
        return mal("token de servicio", f"con token válido devuelve HTTP {status}")

    # Y sin ella: 401. Un endpoint de servicio abierto es peor que uno roto.
    status_sin, _, _ = _peticion(base + "/ha/wol-pending")
    if status_sin == 200:
        return mal(
            "token de servicio",
            "responde 200 SIN token — el endpoint está desprotegido",
        )
    ok("token de servicio", f"200 con token, {status_sin} sin él")


def main():
    if len(sys.argv) != 2:
        print(__doc__)
        return 2
    base = sys.argv[1].rstrip("/")
    print(f"\nVerificando {base}\n")

    comprobar_vivo(base)
    # Si no está vivo, el resto solo añade ruido sobre la misma causa.
    if not fallos:
        comprobar_cors(base)
        comprobar_login(base)
        comprobar_token_servicio(base)

    print()
    if fallos:
        print(f"FALLA: {len(fallos)} comprobación(es) — {', '.join(fallos)}")
        print("No cambies ningún apuntador hasta que esto salga limpio.")
        return 1
    if saltadas:
        print(f"Sin fallos, pero {len(saltadas)} saltada(s): {', '.join(saltadas)}.")
        print("Pon esas variables en el entorno y vuelve a pasarlo: lo que no se")
        print("ha probado no está verificado.")
        return 0
    print("Todo correcto. El backend nuevo se comporta como el de producción.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
