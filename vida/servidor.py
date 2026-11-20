"""El buscador de la vida, en jacobo: guarda y busca lo que le manda el backend.

Corre en jacobo porque allí no estorba (caja no carga con nada pesado) y porque el texto
no sale de casa: el índice vive en un fichero de jacobo y solo viaja lo que Jarvis
encuentra al buscar, como cuando lee un WhatsApp. La lógica está en `indice.py`; aquí
solo hay HTTP. Ver docs/VIDA.md.

Las reglas de los otros servicios de jacobo (oído, huella, voz):

1. NADA QUE ESCUCHE FUERA DE LOCAL SIN CREDENCIAL: con `VIDA_HOST` distinto de 127.0.0.1
   no arranca sin `VIDA_TOKEN`, y el token va en cabecera (`X-Auth-Token` o
   `Authorization: Bearer`), nunca en la URL. Aquí más que en ningún otro: lo que hay
   detrás son sus mensajes.
2. EL REGISTRO NO DICE QUÉ SE BUSCA NI QUÉ SE GUARDA: cuántos y cuánto tardó, nada más.

API (todo con llave salvo `/vivo`):

  GET  /vivo     → {ok}                                  (el healthcheck de Docker)
  GET  /salud    → {ok, fuentes: {fuente: {n, ultimo}}}
  POST /indexar  {documentos: [{id, fuente, fecha, titulo, texto, quien, extra}]}
                 → {guardados, rechazados}               (como mucho MAX_LOTE por petición)
  POST /buscar   {consulta, fuentes?, desde?, hasta?, limite?}
                 → {modo, palabras, resultados: [{id, fuente, fecha, titulo, quien, fragmento}]}
  POST /listar   {desde, hasta, fuentes?, limite?}       (ISO en UTC; `hasta` no entra)
                 → {total, documentos: [{id, fuente, fecha, titulo, quien, fragmento}]}
  POST /olvidar  {fuente} o {ids: [...]}                 → {borrados}
"""

import asyncio
import hmac
import json
import logging
import os
import sys
import time

from aiohttp import web

from indice import Indice

HOST     = os.getenv("VIDA_HOST", "127.0.0.1")
PUERTO   = int(os.getenv("VIDA_PUERTO", "8773"))
TOKEN    = os.getenv("VIDA_TOKEN", "")
RUTA_DB  = os.getenv("VIDA_DB", "/datos/vida.db")
MAX_LOTE = 500
MAX_CUERPO = 8 * 1024 * 1024

log = logging.getLogger("vida")


def autorizado(request) -> bool:
    if not TOKEN:
        return True                      # solo posible en 127.0.0.1 (ver principal)
    dado = request.headers.get("X-Auth-Token", "")
    if not dado and request.headers.get("Authorization", "").startswith("Bearer "):
        dado = request.headers["Authorization"][7:]
    return hmac.compare_digest(dado.encode(), TOKEN.encode())


@web.middleware
async def con_llave(request, handler):
    if request.path != "/vivo" and not autorizado(request):
        return web.json_response({"error": "sin_credencial"}, status=401)
    return await handler(request)


async def _json(request) -> dict:
    try:
        datos = await request.json()
    except (json.JSONDecodeError, UnicodeDecodeError):
        raise web.HTTPBadRequest(text='{"error": "json_no_valido"}', content_type="application/json")
    if not isinstance(datos, dict):
        raise web.HTTPBadRequest(text='{"error": "json_no_valido"}', content_type="application/json")
    return datos


async def vivo(request):
    return web.json_response({"ok": True})


async def salud(request):
    fuentes = await asyncio.to_thread(request.app["indice"].estado)
    return web.json_response({"ok": True, "fuentes": fuentes})


async def indexar(request):
    docs = (await _json(request)).get("documentos")
    if not isinstance(docs, list):
        return web.json_response({"error": "sin_documentos"}, status=400)
    if len(docs) > MAX_LOTE:
        return web.json_response({"error": "lote_grande", "max": MAX_LOTE}, status=413)
    inicio = time.monotonic()
    r = await asyncio.to_thread(request.app["indice"].guardar, docs)
    log.info("indexar: %d guardados, %d rechazados en %d ms", r["guardados"], r["rechazados"],
             int((time.monotonic() - inicio) * 1000))
    return web.json_response(r)


async def buscar(request):
    datos = await _json(request)
    consulta = str(datos.get("consulta") or "")[:300]
    fuentes = datos.get("fuentes") if isinstance(datos.get("fuentes"), list) else None
    inicio = time.monotonic()
    r = await asyncio.to_thread(request.app["indice"].buscar, consulta, fuentes,
                                str(datos.get("desde") or ""), str(datos.get("hasta") or ""),
                                datos.get("limite") or 10)
    log.info("buscar: %d palabras, %d resultados (%s) en %d ms", len(r["palabras"]),
             len(r["resultados"]), r["modo"] or "nada", int((time.monotonic() - inicio) * 1000))
    return web.json_response(r)


async def listar(request):
    datos = await _json(request)
    fuentes = datos.get("fuentes") if isinstance(datos.get("fuentes"), list) else None
    inicio = time.monotonic()
    r = await asyncio.to_thread(request.app["indice"].listar, str(datos.get("desde") or ""),
                                str(datos.get("hasta") or ""), fuentes, datos.get("limite") or 200)
    log.info("listar: %d de %d en %d ms", len(r["documentos"]), r["total"],
             int((time.monotonic() - inicio) * 1000))
    return web.json_response(r)


async def olvidar(request):
    datos = await _json(request)
    ids = datos.get("ids") if isinstance(datos.get("ids"), list) else None
    n = await asyncio.to_thread(request.app["indice"].olvidar, str(datos.get("fuente") or ""), ids)
    log.info("olvidar: %d borrados", n)
    return web.json_response({"borrados": n})


def crear_app(indice: Indice) -> web.Application:
    app = web.Application(middlewares=[con_llave], client_max_size=MAX_CUERPO)
    app["indice"] = indice
    app.router.add_get("/vivo", vivo)
    app.router.add_get("/salud", salud)
    app.router.add_post("/indexar", indexar)
    app.router.add_post("/buscar", buscar)
    app.router.add_post("/listar", listar)
    app.router.add_post("/olvidar", olvidar)
    return app


def principal():
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s",
                        stream=sys.stdout)
    if HOST not in ("127.0.0.1", "localhost") and not TOKEN:
        log.error("VIDA_HOST=%s sin VIDA_TOKEN: no arranco escuchando fuera sin llave", HOST)
        sys.exit(2)
    web.run_app(crear_app(Indice(RUTA_DB)), host=HOST, port=PUERTO, access_log=None)


if __name__ == "__main__":
    principal()
