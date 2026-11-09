"""El reproductor del gemelo: qué habría hecho una regla si hubiera existido.

Ver docs/GEMELO.md. Una automatización nueva se estrena a ciegas: se instala, y a los tres
días se descubre que salta cada vez que un sensor se reconecta, o a las cuatro de la
mañana. Aquí la regla se pasa antes por los meses que ya han ocurrido y dice cuántas veces
habría saltado, cuándo, y cuántas de esas habrían sido en falso.

Una regla es un diccionario (ver `validar`). No es el YAML de Home Assistant: es lo justo
para poder reproducirla con exactitud, y se traduce a YAML cuando ya se sabe que vale.

    {"id": "garaje-abierto", "descripcion": "Avisar si el garaje lleva 10 minutos abierto",
     "cuando": {"entidad": "binary_sensor.garaje", "pasa_a": "on", "durante_min": 10},
     "si": [{"entidad": "device_tracker.movil", "es": "not_home"}, {"entre": ["22:00", "07:00"]}],
     "espera_min": 30,
     "en_falso_si": {"entidad": "binary_sensor.garaje", "pasa_a": "off", "antes_de_min": 2}}

Como en Home Assistant, un disparador de estado salta también cuando la entidad vuelve de
`unavailable`: es el falso positivo de todos los días, y por eso se cuenta aparte.
"""
from __future__ import annotations

import bisect
import heapq
from collections import Counter, defaultdict
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

ZONA = ZoneInfo("Europe/Madrid")
SIN_DATO = ("unavailable", "unknown", "")
DIAS = ("lun", "mar", "mie", "jue", "vie", "sab", "dom")
RAFAGA_S = 300      # dos disparos a menos de esto son el mismo susto contado dos veces


def _lista(v) -> list:
    return [str(x) for x in v] if isinstance(v, (list, tuple)) else [str(v)]


def _minutos(hhmm: str) -> int:
    h, m = str(hhmm).split(":")
    return int(h) * 60 + int(m)


def _numero(estado):
    try:
        return float(estado)
    except (TypeError, ValueError):
        return None


def validar(regla: dict) -> str:
    """'' si la regla se entiende; si no, qué le pasa."""
    if not isinstance(regla, dict) or not isinstance(regla.get("cuando"), dict):
        return "Falta `cuando`."
    c = regla["cuando"]
    try:
        if "a_las" in c:
            _minutos(c["a_las"])
        elif not c.get("entidad"):
            return "`cuando` necesita `entidad` o `a_las`."
        elif not any(k in c for k in ("pasa_a", "por_encima", "por_debajo")):
            return "`cuando` necesita `pasa_a`, `por_encima` o `por_debajo`."
        for k in ("por_encima", "por_debajo", "durante_min"):
            if k in c:
                float(c[k])
        for s in regla.get("si") or []:
            if "entre" in s:
                _minutos(s["entre"][0]), _minutos(s["entre"][1])
            elif "dias" in s:
                if any(d not in DIAS for d in s["dias"]):
                    return f"Los días son {', '.join(DIAS)}."
            elif not s.get("entidad") or not any(k in s for k in ("es", "no_es", "por_encima", "por_debajo")):
                return "Cada condición de `si` necesita `entidad` con `es`/`no_es`/`por_encima`/`por_debajo`, o `entre`, o `dias`."
        f = regla.get("en_falso_si")
        if f is not None and not (f.get("entidad") and "pasa_a" in f and float(f.get("antes_de_min", 0)) > 0):
            return "`en_falso_si` necesita `entidad`, `pasa_a` y `antes_de_min`."
    except (ValueError, TypeError, IndexError, KeyError, AttributeError):
        return "Hay una hora o un número mal escrito."
    return ""


def entidades_de(regla: dict) -> set:
    """Las entidades que la regla mira: lo que hay que sacar del archivo."""
    e = {regla["cuando"].get("entidad")}
    e |= {s.get("entidad") for s in regla.get("si") or []}
    e.add((regla.get("en_falso_si") or {}).get("entidad"))
    return {x for x in e if x}


def _cumple(cond: dict, estados: dict, cuando: datetime) -> bool:
    if "entre" in cond:
        a, b, m = _minutos(cond["entre"][0]), _minutos(cond["entre"][1]), cuando.hour * 60 + cuando.minute
        return a <= m < b if a <= b else (m >= a or m < b)   # 22:00–07:00 cruza la medianoche
    if "dias" in cond:
        return DIAS[cuando.weekday()] in cond["dias"]
    estado = estados.get(cond["entidad"])
    if "es" in cond:
        return estado in _lista(cond["es"])
    if "no_es" in cond:
        return estado is not None and estado not in _lista(cond["no_es"])
    n = _numero(estado)
    if n is None:
        return False
    return n > float(cond["por_encima"]) if "por_encima" in cond else n < float(cond["por_debajo"])


def _activa(c: dict, estado) -> bool:
    """¿El estado es el que el disparador espera?"""
    if "pasa_a" in c:
        return estado in _lista(c["pasa_a"])
    n = _numero(estado)
    if n is None:
        return False
    return n > float(c["por_encima"]) if "por_encima" in c else n < float(c["por_debajo"])


def reproducir(regla: dict, cambios: list, desde: float | None = None, hasta: float | None = None) -> dict:
    """Pasa la regla por `cambios` ([(ts, entidad, estado)] en orden) y devuelve los disparos.

    `desde`/`hasta` acotan lo que se cuenta, no lo que se lee: los cambios anteriores a
    `desde` sirven para saber cómo estaba cada cosa al empezar.
    """
    motivo = validar(regla)
    if motivo:
        raise ValueError(motivo)
    c = regla["cuando"]
    durante = float(c.get("durante_min") or 0) * 60
    espera = float(regla.get("espera_min") or 0) * 60
    condiciones = regla.get("si") or []
    if not cambios:
        return _informe(regla, [], desde, hasta)
    desde = cambios[0][0] if desde is None else desde
    hasta = cambios[-1][0] if hasta is None else hasta

    # Para `en_falso_si`: cuándo pasó cada entidad a cada estado, para mirar hacia delante.
    pasos = defaultdict(list)
    ultimo = {}
    for ts, entidad, estado in cambios:
        if ultimo.get(entidad) != estado:
            pasos[(entidad, estado)].append(ts)
            ultimo[entidad] = estado

    estados: dict = {}
    disparos: list = []
    pendientes: list = []      # (vence, n): un `durante_min` corriendo
    vigente = [0]              # el último `durante_min` armado que sigue valiendo
    ultimo_disparo = [None]

    def disparar(ts: float, previo, de_hora: bool = False):
        if not (desde <= ts <= hasta):
            return
        cuando = datetime.fromtimestamp(ts, ZONA)
        if not all(_cumple(s, estados, cuando) for s in condiciones):
            return
        if espera and ultimo_disparo[0] is not None and ts - ultimo_disparo[0] < espera:
            return
        d = {"ts": ts, "cuando": cuando.strftime("%Y-%m-%d %H:%M"), "previo": previo,
             "tras_reconexion": (not de_hora) and previo in SIN_DATO, "en_falso": False,
             "rafaga": ultimo_disparo[0] is not None and ts - ultimo_disparo[0] < RAFAGA_S}
        f = regla.get("en_falso_si")
        if f:
            tope = ts + float(f["antes_de_min"]) * 60
            for destino in _lista(f["pasa_a"]):
                veces = pasos.get((f["entidad"], destino), [])
                i = bisect.bisect_right(veces, ts)
                if i < len(veces) and veces[i] <= tope:
                    d["en_falso"] = True
        ultimo_disparo[0] = ts
        disparos.append(d)

    def vencer(antes_de: float):
        while pendientes and pendientes[0][0] <= antes_de:
            vence, n, previo = heapq.heappop(pendientes)
            if n == vigente[0]:
                disparar(vence, previo)

    if "a_las" in c:
        # Un disparo al día a esa hora local: se mezclan con los cambios para que las
        # condiciones vean el estado de ese momento.
        minuto = _minutos(c["a_las"])
        dia = datetime.fromtimestamp(desde, ZONA).replace(hour=0, minute=0, second=0, microsecond=0)
        horas = []
        while dia.timestamp() <= hasta:
            t = (dia + timedelta(minutes=minuto)).timestamp()
            if desde <= t <= hasta:
                horas.append(t)
            dia = (dia + timedelta(days=1, hours=3)).replace(hour=0)   # sobrevive al cambio de hora
        i = 0
        for ts, entidad, estado in cambios:
            while i < len(horas) and horas[i] <= ts:
                disparar(horas[i], None, de_hora=True)
                i += 1
            estados[entidad] = estado
        for t in horas[i:]:
            disparar(t, None, de_hora=True)
        return _informe(regla, disparos, desde, hasta)

    entidad_c = c["entidad"]
    de = _lista(c["de"]) if "de" in c else None
    n = 0
    for ts, entidad, estado in cambios:
        vencer(ts)
        previo = estados.get(entidad)
        estados[entidad] = estado
        if entidad != entidad_c or previo == estado:
            continue
        ahora_si, antes_si = _activa(c, estado), _activa(c, previo)
        if not ahora_si:
            vigente[0] = 0          # dejó de cumplirse: el `durante_min` en marcha ya no vale
            continue
        if antes_si or previo is None:
            continue                # ya estaba así, o es el primer dato: no es un cambio
        if de is not None and previo not in de:
            continue
        if durante:
            n += 1
            vigente[0] = n
            heapq.heappush(pendientes, (ts + durante, n, previo))
        else:
            disparar(ts, previo)
    vencer(hasta)
    return _informe(regla, disparos, desde, hasta)


def _informe(regla: dict, disparos: list, desde, hasta) -> dict:
    dias = max(1, round(((hasta or 0) - (desde or 0)) / 86400)) if disparos or desde is not None else 0
    por_dia = Counter(d["cuando"][:10] for d in disparos)
    por_hora = Counter(int(d["cuando"][11:13]) for d in disparos)
    por_semana = Counter(DIAS[datetime.fromtimestamp(d["ts"], ZONA).weekday()] for d in disparos)
    return {
        "id": regla.get("id", ""), "descripcion": regla.get("descripcion", ""),
        "dias": dias, "disparos": len(disparos),
        "dias_con_disparo": len(por_dia),
        "max_en_un_dia": max(por_dia.values(), default=0),
        "tras_reconexion": sum(d["tras_reconexion"] for d in disparos),
        "en_falso": sum(d["en_falso"] for d in disparos),
        "en_rafaga": sum(d["rafaga"] for d in disparos),
        "de_madrugada": sum(n for h, n in por_hora.items() if h < 7),
        "por_hora": dict(sorted(por_hora.items())),
        "por_dia_semana": {d: por_semana[d] for d in DIAS if por_semana[d]},
        "lista": disparos,
    }


def frase(inf: dict) -> str:
    """El informe en una frase, para decirla."""
    if not inf["disparos"]:
        return f"En {inf['dias']} días no habría saltado ni una vez."
    partes = [f"En {inf['dias']} días habría saltado {inf['disparos']} "
              f"{'vez' if inf['disparos'] == 1 else 'veces'}, en {inf['dias_con_disparo']} días distintos"]
    dudosas = []
    if inf["tras_reconexion"]:
        dudosas.append(f"{inf['tras_reconexion']} al reconectarse el sensor")
    if inf["en_falso"]:
        dudosas.append(f"{inf['en_falso']} en falso")
    if inf["en_rafaga"]:
        dudosas.append(f"{inf['en_rafaga']} repetidas en menos de cinco minutos")
    if inf["de_madrugada"]:
        dudosas.append(f"{inf['de_madrugada']} de madrugada")
    return partes[0] + ((": " + ", ".join(dudosas)) if dudosas else "") + "."
