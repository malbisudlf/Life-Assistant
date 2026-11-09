"""La memoria del gemelo de la casa: el histórico de Home Assistant, guardado aparte.

Ver docs/GEMELO.md. Home Assistant borra su histórico a los ~30 días (`purge_keep_days`);
el gemelo copia cada noche lo de las entidades que le interesan a un SQLite en `caja`, y
así su memoria crece sin tocar la configuración ni el disco del Green.

Tres cosas que no se relajan:

- **Solo lee.** De Home Assistant se pide `/api/history` y `/api/states`, nada más. Aquí
  no hay ni una llamada a un servicio: el gemelo no puede encender ni abrir nada.
- **En la casa vive más gente.** No se archiva la ubicación de nadie salvo el móvil que
  diga la configuración (`movil`), ni las personas, ni lo que suena en teles y altavoces.
  Lo que no está en el archivo no se puede minar ni contar.
- **No sale de `caja`.** El archivo dice cuándo hay alguien en casa y cuándo no. El
  repositorio es público: aquí no hay ni un nombre de entidad de verdad.
"""
from __future__ import annotations

import fnmatch
import json
import os
import sqlite3
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path

# Lo que se archiva si la configuración no dice otra cosa: lo que tiene un estado que
# significa algo en una regla. Los `sensor` quedan fuera por defecto (son cientos, casi
# todos números que cambian cada minuto); se añaden uno a uno en `incluir`.
DOMINIOS = ("light", "switch", "binary_sensor", "cover", "climate", "lock", "fan",
            "alarm_control_panel", "input_boolean", "sun", "vacuum")
# Nunca, lo diga quien lo diga: de quién es cada móvil no se deduce, se configura.
NUNCA = ("person.*", "device_tracker.*", "media_player.*", "camera.*", "notify.*", "tts.*",
         "conversation.*", "todo.*", "update.*")

# Entidades por petición. El Green es un aparato pequeño: con 40 por petición, un día
# cargado tardó más de un minuto y se cortó (2026-11-09).
LOTE = 15
ESPERA_S = 120


class HaNoContesta(RuntimeError):
    """Home Assistant no ha devuelto lo pedido."""


def configuracion(ruta: str | os.PathLike | None) -> dict:
    """`{"movil": "device_tracker.x", "incluir": [...], "excluir": [...]}`, o vacía."""
    if not ruta or not Path(ruta).exists():
        return {}
    datos = json.loads(Path(ruta).read_text(encoding="utf-8"))
    return datos if isinstance(datos, dict) else {}


def se_archiva(entidad: str, conf: dict) -> bool:
    """¿Esta entidad entra en el archivo? El móvil configurado es la única excepción a NUNCA."""
    if entidad == conf.get("movil"):
        return True
    if any(fnmatch.fnmatch(entidad, p) for p in NUNCA):
        return False
    if any(fnmatch.fnmatch(entidad, p) for p in conf.get("excluir") or []):
        return False
    if any(fnmatch.fnmatch(entidad, p) for p in conf.get("incluir") or []):
        return True
    return entidad.split(".", 1)[0] in DOMINIOS


# ── El archivo ────────────────────────────────────────────────────────────────

def abrir(ruta: str | os.PathLike) -> sqlite3.Connection:
    ruta = Path(ruta)
    ruta.parent.mkdir(parents=True, exist_ok=True)
    nueva = not ruta.exists()
    db = sqlite3.connect(ruta)
    db.execute("create table if not exists cambios ("
               " entidad text not null, ts real not null, estado text not null,"
               " primary key (entidad, ts)) without rowid")
    db.execute("create table if not exists dias (dia text primary key, cambios integer not null)")
    db.commit()
    if nueva:
        # Solo para su usuario: dice cuándo no hay nadie en casa.
        os.chmod(ruta, 0o600)
    return db


def guardar(db: sqlite3.Connection, filas) -> int:
    """`filas`: (entidad, ts, estado). Repetir un día no duplica nada."""
    antes = db.total_changes
    db.executemany("insert or ignore into cambios (entidad, ts, estado) values (?, ?, ?)", filas)
    db.commit()
    return db.total_changes - antes


def leer(db: sqlite3.Connection, desde: float | None = None, hasta: float | None = None,
         entidades=None) -> list:
    """Los cambios en orden: [(ts, entidad, estado)]."""
    sql, args = "select ts, entidad, estado from cambios where 1=1", []
    if desde is not None:
        sql += " and ts >= ?"
        args.append(desde)
    if hasta is not None:
        sql += " and ts < ?"
        args.append(hasta)
    if entidades:
        entidades = list(entidades)
        sql += f" and entidad in ({','.join('?' * len(entidades))})"
        args += entidades
    return db.execute(sql + " order by ts, entidad", args).fetchall()


def resumen(db: sqlite3.Connection) -> dict:
    n, primero, ultimo, entidades = db.execute(
        "select count(*), min(ts), max(ts), count(distinct entidad) from cambios").fetchone()
    return {"cambios": n, "entidades": entidades, "desde": primero, "hasta": ultimo,
            "dias": round((ultimo - primero) / 86400, 1) if n else 0}


# ── Home Assistant, solo lectura ──────────────────────────────────────────────

def _pedir(url: str, token: str):
    req = urllib.request.Request(url, headers={"Authorization": f"Bearer {token}"})
    try:
        with urllib.request.urlopen(req, timeout=ESPERA_S) as r:
            return json.loads(r.read().decode("utf-8"))
    except Exception as e:   # noqa: BLE001 — cualquier fallo es «no contesta»
        raise HaNoContesta(f"{type(e).__name__} al pedir el histórico") from e


def entidades_de_ha(url: str, token: str, conf: dict, pedir=_pedir) -> list:
    estados = pedir(url.rstrip("/") + "/api/states", token)
    return sorted(e["entity_id"] for e in estados if se_archiva(e.get("entity_id", ""), conf))


def _ts(iso: str) -> float:
    return datetime.fromisoformat(iso.replace("Z", "+00:00")).timestamp()


def historia_de_ha(url: str, token: str, entidades: list, desde: datetime, hasta: datetime,
                   pedir=_pedir):
    """Los cambios de esas entidades en ese tramo, como filas (entidad, ts, estado)."""
    for i in range(0, len(entidades), LOTE):
        lote = entidades[i:i + LOTE]
        q = urllib.parse.urlencode({"end_time": hasta.isoformat(), "filter_entity_id": ",".join(lote)})
        ruta = (f"{url.rstrip('/')}/api/history/period/{urllib.parse.quote(desde.isoformat())}"
                f"?{q}&minimal_response&no_attributes")
        for serie in pedir(ruta, token) or []:
            entidad = None
            for punto in serie:
                entidad = punto.get("entity_id") or entidad
                cuando = punto.get("last_changed") or punto.get("last_updated")
                # Solo lo pedido: si Home Assistant devolviera de más, no entra en el archivo.
                if entidad in lote and cuando and punto.get("state") is not None:
                    # El primer punto de cada serie es el estado que traía al empezar el
                    # tramo, fechado al empezar: no es un cambio. Se guarda igual (el
                    # reproductor ignora un «cambio» al mismo estado) porque es lo que
                    # permite saber cómo estaba algo que no se movió en todo el día.
                    yield (entidad, _ts(cuando), str(punto["state"])[:64])


def archivar(db: sqlite3.Connection, url: str, token: str, conf: dict, dias: int = 35,
             ahora: datetime | None = None, pedir=_pedir, decir=print) -> dict:
    """Copia al archivo los días que falten, del más viejo al más nuevo. Ayer siempre se
    repite: el día pudo archivarse a medias."""
    ahora = ahora or datetime.now(timezone.utc)
    entidades = entidades_de_ha(url, token, conf, pedir)
    if not entidades:
        raise HaNoContesta("Home Assistant no ha devuelto ninguna entidad que archivar")
    # Lo que la configuración ya no deja archivar se va también de lo archivado: excluir
    # el altavoz del cuarto de otro tiene que valer hacia atrás, no solo desde hoy.
    for (entidad,) in db.execute("select distinct entidad from cambios").fetchall():
        if not se_archiva(entidad, conf):
            db.execute("delete from cambios where entidad = ?", (entidad,))
    db.commit()
    hechos = {d for (d,) in db.execute("select dia from dias")}
    hoy = ahora.replace(hour=0, minute=0, second=0, microsecond=0)
    nuevos = total = 0
    fallidos = []
    for atras in range(dias, -1, -1):
        dia = hoy - timedelta(days=atras)
        clave = dia.strftime("%Y-%m-%d")
        if clave in hechos and atras > 1:
            continue
        fin = min(dia + timedelta(days=1), ahora)
        try:
            n = guardar(db, historia_de_ha(url, token, entidades, dia, fin, pedir))
        except HaNoContesta:
            # Un día que no llega no tumba los demás: no se marca como hecho, y la noche
            # siguiente se vuelve a pedir (mientras Home Assistant aún lo guarde).
            fallidos.append(clave)
            continue
        if atras >= 1:   # hoy no se da por hecho: aún no ha acabado
            db.execute("insert or replace into dias (dia, cambios) values (?, ?)", (clave, n))
            db.commit()
        if n:
            nuevos += 1
            total += n
    decir(f"Archivo: {len(entidades)} entidades, {total} cambios nuevos en {nuevos} días."
          + (f" Sin poder leer: {', '.join(fallidos)}." if fallidos else ""))
    return {"entidades": len(entidades), "cambios": total, "dias": nuevos, "fallidos": fallidos}
