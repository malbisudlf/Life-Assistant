"""Copia de seguridad cifrada de las tablas de Supabase que no se pueden regenerar.

Por qué existe (idea 5.4 / 6.6 de `docs/IDEAS.md`): el histórico del Apple Watch vive
en un solo sitio. El calendario está en Outlook, la configuración en el `.env` y el
código en GitHub, pero `health_metrics` no se puede reconstruir desde ninguna parte, y
la ingesta resuelve por upsert `(metric_date, metric_name)`: un cliente que escriba mal
pisa la serie sin dejar rastro.

Cómo se usa:

    # Volcado cifrado del día (crea copias/copia-supabase-AAAA-MM-DD.json.gpg)
    python scripts/copia_supabase.py

    # Comprobar una copia ya hecha: la descifra en memoria y cuenta filas
    python scripts/copia_supabase.py --verificar copias/copia-supabase-2026-09-03.json.gpg

Variables de entorno (ninguna tiene valor por defecto, y sin ellas el script falla):

    SUPABASE_URL        el mismo del backend
    SUPABASE_KEY        service key: es la única que salta la RLS y ve las tablas
    COPIA_PASSPHRASE    frase de cifrado simétrico del volcado

Tres reglas que no se pueden relajar, y el motivo de cada una:

1. **El fichero nace cifrado y nunca existe en claro en disco.** El repositorio es
   PÚBLICO y los artefactos de Actions de un repositorio público los puede descargar
   cualquiera. El JSON viaja de memoria a la entrada estándar de `gpg`, así que no hay
   un instante en el que el volcado en claro esté escrito en ninguna parte.
2. **Nada de lo que se imprime lleva datos.** Los mensajes solo dicen nombres de tabla
   y recuentos; ni valores, ni la clave, ni la URL con la clave dentro. La salida del
   script acaba en el log del workflow, que también es público.
3. **Una copia vacía no es una copia.** Si una tabla obligatoria vuelve con cero filas,
   el script falla ruidosamente y NO escribe nada. El fallo clásico de estos scripts es
   sustituir una copia buena por un fichero vacío el día que la lectura falla en
   silencio, y ese fallo solo se descubre el día que hace falta restaurar.

Restaurar: `docs/COPIA_SEGURIDAD.md`.
"""
import argparse
import json
import os
import subprocess
import sys
import tempfile
from datetime import datetime, timezone

import requests

# Misma disciplina que el backend: todo lo que sale va por esta sesión, con timeout
# siempre puesto. Los tests la monkeypatchean (`copia.http.get`), igual que hacen con
# `main.http`.
http = requests.Session()

# PostgREST corta las respuestas (`db-max-rows`), y `health_metrics` lleva meses de
# serie: hay que paginar sí o sí. El tamaño de página es una petición, no una promesa —
# el servidor puede devolver menos, y por eso el total se saca del `Content-Range` en
# vez de deducirlo de "han venido menos filas de las que pedí".
PAGINA = 1000

# Tope de seguridad para que un `Content-Range` absurdo o un servidor que ignore el
# offset no dejen el bucle dando vueltas hasta llenar la memoria de la máquina.
MAX_FILAS_POR_TABLA = 500_000

TIMEOUT = 60

# Qué se copia. Cada entrada: (tabla, columna(s) de orden, obligatoria, columnas).
#
# - El orden es obligatorio: sin `order` PostgREST no garantiza que dos páginas
#   consecutivas no repitan o se salten filas.
# - `obligatoria` marca las tablas que en esta instalación NO pueden estar vacías. Si
#   una lo está, la copia entera se descarta.
# - `columnas` a None es "todas". Solo se concreta donde hay algo que dejar fuera.
#
# Lo que NO se copia, a propósito:
#   · `oauth_tokens` — son credenciales vivas de Microsoft Graph. Una copia de
#     seguridad multiplica los sitios donde vive un refresh token, y se regenera entera
#     pasando otra vez por /auth/login.
#   · `jobs`, `job_events`, `job_results`, `pc_agents`, `app_logs`, `login_attempts`,
#     `presence`, `brief_envios`, `informe_envios`, `vigilante_estado`,
#     `revision_hallazgos`, `averias` — estado operativo y registro. Se regeneran solos
#     y perderlos no cuesta nada.
TABLAS = (
    # (nombre,                orden,                     obligatoria, columnas)
    ("health_metrics",        "metric_date,metric_name", True,        None),
    ("training_clients",      "created_at,id",           False,       None),
    ("training_sessions",     "date,id",                 False,       None),
    ("training_payments",     "date,id",                 False,       None),
    ("ideas",                 "created_at,id",           False,       None),
    ("clothing",              "created_at,id",           False,       None),
    ("jarvis_memoria",        "clave",                   False,       None),
    ("jarvis_recordatorios",  "cuando,id",               False,       None),
    # Sin la columna `token`: es una credencial de GitHub que además caduca sola, así
    # que copiarla solo sirve para tener un secreto de más dentro del volcado.
    ("jarvis_mcp_servidores", "nombre",                  False,
     "nombre,url,confiar,lectura_directa,creado"),
    ("reglas_usuario",        "clave",                   False,       None),
    ("vigilancias",           "clave",                   False,       None),
    ("avisos_reglas",         "regla",                   False,       None),
    ("ha_entidades",          "id",                      False,       None),
    ("salud_ajustes",         "id",                      False,       None),
    ("brief_ajustes",         "id",                      False,       None),
    ("etf_holdings",          "ticker",                  False,       None),
    ("etf_aportaciones",      "fecha,id",                False,       None),
)

VERSION_FORMATO = 1


class ErrorCopia(Exception):
    """Algo ha ido mal y la copia no vale. Siempre acaba en salida distinta de 0."""


def _cabeceras(clave: str) -> dict:
    return {
        "apikey": clave,
        "Authorization": f"Bearer {clave}",
        "Accept": "application/json",
    }


def total_de_content_range(valor):
    """Saca el total de filas de la cabecera `Content-Range` de PostgREST ("0-999/4213").

    Devuelve None si la cabecera no viene o el total es `*` (lo que responde PostgREST
    cuando no se le pide `count`). Es la única forma fiable de saber cuándo ha terminado
    la paginación: parar porque "han venido menos filas de las que pedí" da una copia
    truncada en silencio el día que el servidor baje su `db-max-rows`.
    """
    if not valor or "/" not in str(valor):
        return None
    total = str(valor).rsplit("/", 1)[1].strip()
    if not total.isdigit():
        return None
    return int(total)


def descargar_tabla(tabla, orden, columnas, url, clave):
    """Trae una tabla entera de Supabase paginando, o revienta."""
    cabeceras = _cabeceras(clave)
    cabeceras["Prefer"] = "count=exact"
    filas = []
    total = None
    offset = 0

    while True:
        destino = (f"{url}/rest/v1/{tabla}"
                   f"?select={columnas or '*'}&order={orden}"
                   f"&limit={PAGINA}&offset={offset}")
        try:
            r = http.get(destino, headers=cabeceras, timeout=TIMEOUT)
        except requests.RequestException as e:
            raise ErrorCopia(
                f"{tabla}: la petición a Supabase falló ({type(e).__name__})") from e

        if r.status_code >= 300:
            # Nunca el cuerpo de la respuesta: puede traer filas dentro.
            raise ErrorCopia(f"{tabla}: Supabase respondió {r.status_code}")

        lote = r.json()
        if not isinstance(lote, list):
            raise ErrorCopia(f"{tabla}: la respuesta no es una lista de filas")

        visto = total_de_content_range(getattr(r, "headers", {}).get("Content-Range"))
        if visto is not None:
            total = visto

        filas.extend(lote)
        if len(filas) > MAX_FILAS_POR_TABLA:
            raise ErrorCopia(f"{tabla}: más de {MAX_FILAS_POR_TABLA} filas, algo va mal")
        if not lote:
            break
        offset += len(lote)
        if total is not None and offset >= total:
            break

    if total is not None and len(filas) != total:
        raise ErrorCopia(f"{tabla}: Supabase dice que hay {total} filas "
                         f"y solo han llegado {len(filas)}")
    return filas


def construir_copia(url, clave, tablas=TABLAS):
    """Vuelca todas las tablas a un diccionario listo para serializar."""
    datos = {}
    recuentos = {}
    for tabla, orden, _obligatoria, columnas in tablas:
        filas = descargar_tabla(tabla, orden, columnas, url, clave)
        datos[tabla] = filas
        recuentos[tabla] = len(filas)
        print(f"  {tabla}: {len(filas)} filas")
    return {
        "version":     VERSION_FORMATO,
        "generado_en": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "recuentos":   recuentos,
        "tablas":      datos,
    }


def verificar_recuentos(recuentos, tablas=TABLAS):
    """Falla si falta una tabla obligatoria o si viene vacía.

    Una copia vacía que sustituye a una buena es peor que no tener copia: parece que el
    respaldo funciona, y el día que haga falta restaurar no hay nada dentro.
    """
    problemas = []
    for tabla, _orden, obligatoria, _columnas in tablas:
        if not obligatoria:
            continue
        if tabla not in recuentos:
            problemas.append(f"falta la tabla {tabla}")
        elif not recuentos[tabla]:
            problemas.append(f"{tabla} ha venido con 0 filas")
    if problemas:
        raise ErrorCopia("la copia no vale: " + "; ".join(problemas))


def _recortar(salida):
    """El stderr de gpg puede ser largo; nunca lleva datos, pero sí rutas."""
    texto = (salida or b"").decode("utf-8", "replace").strip().replace("\n", " ")
    return texto[:200]


def _gpg(argumentos, passphrase, entrada):
    """Llama a gpg con la frase en un fichero temporal y los datos por entrada estándar.

    La frase no puede ir en la línea de órdenes (`--passphrase`): queda visible en la
    lista de procesos de la máquina. Y no puede ir por la entrada estándar
    (`--passphrase-fd 0`) porque por ahí van los datos. Queda el fichero temporal, que
    vive milisegundos, lo crea el sistema con permisos de solo el dueño y se borra en el
    `finally` pase lo que pase. Lo que NUNCA toca el disco en claro son los datos.
    """
    fd, ruta = tempfile.mkstemp(prefix="copia-supabase-", suffix=".pass")
    try:
        os.write(fd, passphrase.encode("utf-8"))
        os.close(fd)
        try:
            os.chmod(ruta, 0o600)
        except OSError:
            pass
        orden = ["gpg", "--batch", "--yes", "--quiet",
                 "--pinentry-mode", "loopback", "--passphrase-file", ruta] + argumentos
        try:
            return subprocess.run(orden, input=entrada, capture_output=True, check=False)
        except FileNotFoundError as e:
            raise ErrorCopia("no se encuentra el ejecutable `gpg` en el PATH") from e
    finally:
        try:
            os.remove(ruta)
        except OSError:
            pass


def cifrar(datos, passphrase, destino):
    proc = _gpg(["--symmetric", "--cipher-algo", "AES256", "--output", destino, "-"],
                passphrase, datos)
    if proc.returncode != 0:
        raise ErrorCopia(f"gpg no pudo cifrar (código {proc.returncode}): "
                         f"{_recortar(proc.stderr)}")


def descifrar(ruta, passphrase):
    with open(ruta, "rb") as f:
        cifrado = f.read()
    proc = _gpg(["--decrypt"], passphrase, cifrado)
    if proc.returncode != 0:
        raise ErrorCopia(f"gpg no pudo descifrar (código {proc.returncode}): "
                         f"{_recortar(proc.stderr)}")
    return proc.stdout


def recuentos_del_fichero(ruta, passphrase):
    """Descifra una copia EN MEMORIA y devuelve las filas que tiene de verdad.

    No se fía del campo `recuentos` del volcado: lo que interesa saber es que el fichero
    se puede abrir, que el JSON de dentro está entero y que las listas tienen lo que
    dicen tener. Es la diferencia entre "el fichero pesa" y "la copia sirve".
    """
    crudo = descifrar(ruta, passphrase)
    try:
        copia = json.loads(crudo.decode("utf-8"))
    except (ValueError, UnicodeDecodeError) as e:
        raise ErrorCopia("la copia descifrada no es un JSON válido") from e
    tablas = copia.get("tablas")
    if not isinstance(tablas, dict):
        raise ErrorCopia("la copia descifrada no tiene el bloque `tablas`")
    return {t: len(f) for t, f in tablas.items() if isinstance(f, list)}


def nombre_por_defecto(directorio, hoy=None):
    dia = (hoy or datetime.now(timezone.utc)).strftime("%Y-%m-%d")
    return os.path.join(directorio, f"copia-supabase-{dia}.json.gpg")


def hacer_copia(url, clave, passphrase, destino, tablas=TABLAS):
    """Vuelca, verifica, cifra y vuelve a abrir el resultado. Devuelve los recuentos."""
    print("Leyendo Supabase:")
    copia = construir_copia(url, clave, tablas)
    verificar_recuentos(copia["recuentos"], tablas)

    carpeta = os.path.dirname(os.path.abspath(destino))
    os.makedirs(carpeta, exist_ok=True)
    # Idempotente a propósito: dos ejecuciones el mismo día escriben el mismo fichero.
    cifrar(json.dumps(copia, ensure_ascii=False).encode("utf-8"), passphrase, destino)

    # Releer lo escrito es la única comprobación que vale: una copia que no se puede
    # abrir no es una copia, y eso no se sabe hasta que se intenta.
    reales = recuentos_del_fichero(destino, passphrase)
    if reales != copia["recuentos"]:
        raise ErrorCopia("el fichero cifrado no coincide con lo que se descargó")
    verificar_recuentos(reales, tablas)
    return reales


def _entorno(nombre):
    valor = (os.getenv(nombre) or "").strip()
    if not valor:
        raise ErrorCopia(f"falta la variable de entorno {nombre}")
    return valor


def main(argv=None):
    ap = argparse.ArgumentParser(description="Copia de seguridad cifrada de Supabase.")
    ap.add_argument("--salida", default="copias",
                    help="carpeta donde dejar la copia (por defecto: copias/)")
    ap.add_argument("--fichero", default=None,
                    help="ruta exacta del fichero cifrado (por defecto, uno por día)")
    ap.add_argument("--verificar", metavar="FICHERO", default=None,
                    help="no copia nada: abre esa copia y cuenta las filas que tiene")
    args = ap.parse_args(argv)

    try:
        passphrase = _entorno("COPIA_PASSPHRASE")

        if args.verificar:
            recuentos = recuentos_del_fichero(args.verificar, passphrase)
            print("Contenido de la copia:")
            for tabla in sorted(recuentos):
                print(f"  {tabla}: {recuentos[tabla]} filas")
            verificar_recuentos(recuentos)
            print("La copia se abre y tiene datos.")
            return 0

        destino = args.fichero or nombre_por_defecto(args.salida)
        recuentos = hacer_copia(_entorno("SUPABASE_URL"), _entorno("SUPABASE_KEY"),
                                passphrase, destino)
        print(f"Copia cifrada en {destino} "
              f"({sum(recuentos.values())} filas de {len(recuentos)} tablas).")
        return 0
    except ErrorCopia as e:
        # A stderr y con código 1: este script corre solo, y un fallo que no se ve es
        # exactamente el escenario que la copia existe para evitar.
        print(f"ERROR: {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
