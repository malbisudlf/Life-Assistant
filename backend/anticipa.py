"""Jarvis que se anticipa, fase 1: la lógica pura. Diseño en `docs/JARVIS_ANTICIPA.md`.

Aquí no hay red, ni base de datos, ni reloj: todo entra por parámetro, para poder probarlo.
El enganche con el backend (cuándo se apunta, cuándo se aprende, por dónde sale la
sugerencia) está en la sección «JARVIS QUE SE ANTICIPA» de `main.py`.

Las reglas que no se negocian, y dónde se hacen cumplir:

- **Lista cerrada.** Solo se apunta y solo se sugiere lo que `nucleo_seguridad.json`
  declara, con los argumentos que declara. Ese fichero lo cambia Mikel a mano; Jarvis lo lee.
- **Lo ajeno no enseña.** Un turno que ha leído texto de otros no deja evento: lo decide
  quien llama (`tras_ajeno`), con la misma frontera de `_ajeno_bloquea`. Aquí además no
  existe ningún origen que no sea una boca de Mikel.
- **Nada se ejecuta solo.** `puede_ejecutar_sola` devuelve False en fase 1, diga lo que diga
  el núcleo; y aunque algún día diga otra cosa, solo para el nivel `bajo`.
- **La confianza es aritmética.** La calcula este fichero; ningún modelo opina sobre si un
  patrón vale.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import unicodedata
from datetime import date, datetime, timedelta
from statistics import median
from typing import Optional

DIAS = ("lunes", "martes", "miércoles", "jueves", "viernes", "sábado", "domingo")
UBICACIONES = frozenset({"casa", "gimnasio", "uni", "coche", "fuera"})
# Las bocas por las que habla Mikel. `sistema` (lo que el backend hace solo) no está: una
# acción que nadie pidió no es un hábito suyo.
ORIGENES = frozenset({"chat", "voz", "telefono", "telegram", "atajo", "dashboard"})
NIVELES = ("bajo", "medio")

VENTANA_DIAS = 42          # lo que se mira hacia atrás para aprender
ANCHO_MIN = 60             # dos veces «a la misma hora» caben en una hora
N_MINIMO = 4               # días distintos para que exista un patrón general
N_MINIMO_DIA = 3           # … y para uno de un día concreto de la semana
PROPORCION_MINIMA = 0.6
CONFIANZA_INICIAL = 0.6
U_SUGERIR = 0.55
U_EJECUTAR = 0.90          # fase 2; hoy no ejecuta nada
ALFA_SI = 0.15
BETA_NO = 0.25             # un no pesa más que un sí: insistir cuesta más que callar
ALFA_PROPIA = 0.05         # que lo vuelva a hacer él confirma el patrón, poco a poco
DECAIMIENTO_DIARIO = 0.98
U_OLVIDAR = 0.20           # por debajo, el patrón se borra solo
MARGEN_ANTES = 15          # se propone un poco antes de su hora de siempre…
MARGEN_DESPUES = 15        # …y, pasado este rato, ya no

_GRUPOS_GENERALES = ("cada_dia", "laborables", "finde")
_ENTIDAD_RE = re.compile(r"^[a-z_]{1,32}\.[a-z0-9_]{1,64}$")
_HORA_RE = re.compile(r"^([01]\d|2[0-3]):[0-5]\d$")
_TEXTO_MAX = 80


# ── El núcleo de solo lectura ─────────────────────────────────────────────────

def ruta_nucleo() -> str:
    return os.path.join(os.path.dirname(os.path.abspath(__file__)), "nucleo_seguridad.json")


def cargar_nucleo(ruta: Optional[str] = None) -> dict:
    """Lee y valida el núcleo. Si está mal, falla: sin reglas no hay anticipación."""
    with open(ruta or ruta_nucleo(), encoding="utf-8") as f:
        nucleo = json.load(f)
    ant = nucleo.get("anticipa") or {}
    acciones = ant.get("acciones")
    if not isinstance(acciones, dict) or not acciones:
        raise RuntimeError("nucleo_seguridad.json: falta anticipa.acciones")
    prohibidas = set((nucleo.get("irreversible") or {}).get("herramientas") or [])
    for nombre, regla in acciones.items():
        if regla.get("nivel") not in NIVELES:
            raise RuntimeError(f"nucleo_seguridad.json: nivel no válido en {nombre}")
        if nombre in prohibidas:
            raise RuntimeError(f"nucleo_seguridad.json: {nombre} es irreversible y no se sugiere")
        if not isinstance(regla.get("argumentos"), list):
            raise RuntimeError(f"nucleo_seguridad.json: faltan los argumentos de {nombre}")
    lim = ant.get("limites") or {}
    for clave in ("espera_min_entre_sugerencias", "max_sugerencias_dia", "minutos_para_contestar"):
        if not isinstance(lim.get(clave), int) or lim[clave] <= 0:
            raise RuntimeError(f"nucleo_seguridad.json: falta el límite {clave}")
    return nucleo


# ── De una herramienta usada a una acción normalizada ─────────────────────────

def _plano(texto) -> str:
    t = unicodedata.normalize("NFKD", str(texto or "").lower())
    return re.sub(r"\s+", " ", t.encode("ascii", "ignore").decode()).strip()


def _dato(valor):
    """Un extra de la casa: un número o un texto corto. Nada anidado."""
    if isinstance(valor, bool):
        return None
    if isinstance(valor, (int, float)):
        return valor
    if isinstance(valor, str) and 0 < len(valor) <= 24:
        return valor
    return None


def normalizar(herramienta: str, argumentos: Optional[dict], nucleo: dict) -> Optional[dict]:
    """La acción tal como se apunta, o None si no es de las que se aprenden.

    Devuelve `herramienta`, `argumentos` (solo los declarados, limpios: es lo que se
    volvería a ejecutar), `accion` (la clave que agrupa «lo mismo») y `nivel`.
    """
    regla = ((nucleo.get("anticipa") or {}).get("acciones") or {}).get(herramienta)
    if not regla:
        return None
    entrada = argumentos if isinstance(argumentos, dict) else {}
    limpios: dict = {}
    for nombre in regla["argumentos"]:
        valor = entrada.get(nombre)
        if valor in (None, "", {}):
            continue
        if nombre == "datos":
            if not isinstance(valor, dict):
                return None
            permitidos = set(regla.get("datos") or [])
            datos = {k: _dato(v) for k, v in valor.items() if k in permitidos}
            datos = {k: v for k, v in datos.items() if v is not None}
            if len(datos) != len(valor):
                return None      # traía algo que no se sabe repetir: no es un hábito limpio
            if datos:
                limpios[nombre] = datos
        else:
            limpios[nombre] = " ".join(str(valor).split())[:_TEXTO_MAX]
    for nombre, validos in (regla.get("solo") or {}).items():
        if limpios.get(nombre) not in validos:
            return None
    if "dominios" in regla:
        prohibidos = set((nucleo.get("irreversible") or {}).get("dominios_casa") or [])
        for campo in ("servicio", "entidad"):
            valor = str(limpios.get(campo) or "").lower()
            if not _ENTIDAD_RE.match(valor):
                return None
            dominio = valor.split(".")[0]
            if dominio not in regla["dominios"] or dominio in prohibidos:
                return None
            limpios[campo] = valor
    if herramienta == "recordarme":
        if not _HORA_RE.match(str(limpios.get("hora") or "")) or not limpios.get("texto"):
            return None
    firma = {k: (_plano(v) if isinstance(v, str) else v) for k, v in limpios.items()}
    huella = hashlib.sha1(json.dumps(firma, sort_keys=True, ensure_ascii=True).encode()).hexdigest()[:12]
    return {"herramienta": herramienta, "argumentos": limpios,
            "accion": f"{herramienta}:{huella}", "nivel": regla["nivel"]}


def evento(ahora: datetime, ubicacion: str, origen: str, norm: dict, *,
           tipo: str = "peticion", patron: str = "", pregunta: str = "") -> Optional[dict]:
    """La fila del registro. None si el origen o el lugar no son de los conocidos."""
    if origen not in ORIGENES and tipo == "peticion":
        return None
    if ubicacion not in UBICACIONES:
        return None
    if tipo not in ("peticion", "sugerencia"):
        return None
    fila = {
        "ts": ahora.isoformat(),
        "dia": ahora.date().isoformat(),
        "minuto": ahora.hour * 60 + ahora.minute,
        "dia_semana": ahora.weekday(),
        "ubicacion": ubicacion,
        "tipo": tipo,
        "accion": norm["accion"],
        "herramienta": norm["herramienta"],
        "argumentos": norm["argumentos"],
        "origen": origen if tipo == "peticion" else "sugerencia",
    }
    if patron:
        fila["patron"] = patron
    if pregunta:
        fila["pregunta"] = pregunta
    return fila


# ── Cómo se dice ──────────────────────────────────────────────────────────────

_SERVICIOS = {"turn_on": "encender", "turn_off": "apagar", "toggle": "cambiar"}


def describir(herramienta: str, argumentos: dict) -> str:
    """La acción, en infinitivo y escrita por el backend: «poner «lofi»»."""
    a = argumentos or {}
    if herramienta == "musica_poner":
        donde = f" en {a['dispositivo']}" if a.get("dispositivo") else ""
        return f"poner «{a.get('que', 'música')}»{donde}"
    if herramienta == "tele":
        if a.get("accion") == "abrir":
            return f"abrir {a.get('valor') or 'una aplicación'} en la tele"
        return f"{a.get('accion', 'encender')} la tele"
    if herramienta == "pc_abrir":
        return f"abrir «{a.get('que', '')}» en el PC"
    if herramienta == "encender_pc":
        return "encender el PC"
    if herramienta == "lanzar_streaming":
        return "preparar el PC para jugar en remoto"
    if herramienta == "casa_ordenar":
        servicio = str(a.get("servicio") or "").split(".")[-1]
        cosa = str(a.get("entidad") or "").split(".")[-1].replace("_", " ")
        datos = a.get("datos") or {}
        if servicio == "set_temperature" and "temperature" in datos:
            return f"poner {cosa} a {datos['temperature']} grados"
        extra = f" al {datos['brightness_pct']} %" if "brightness_pct" in datos else ""
        return f"{_SERVICIOS.get(servicio, servicio.replace('_', ' '))} {cosa}{extra}"
    if herramienta == "recordarme":
        return f"apuntarle un aviso a las {a.get('hora')}: «{a.get('texto')}»"
    return herramienta


def _hhmm(minuto: int) -> str:
    return f"{minuto // 60}:{minuto % 60:02d}"


def _cuando(grupo: str, minuto: int) -> str:
    hora = f"sobre las {_hhmm(minuto)}"
    if grupo == "cada_dia":
        return f"cada día, {hora},"
    if grupo == "laborables":
        return f"entre semana, {hora},"
    if grupo == "finde":
        return f"los fines de semana, {hora},"
    return f"los {DIAS[int(grupo[1:])]}, {hora},"


def _donde(ubicacion: str) -> str:
    return {"casa": "en casa", "gimnasio": "en el gimnasio", "uni": "en la uni",
            "coche": "en el coche"}.get(ubicacion, "fuera de casa")


def frase(patron: dict) -> str:
    """La sugerencia: una frase y una sola pregunta. La escribe el backend, no un modelo."""
    return (f"Señor, {_cuando(patron['grupo'], patron['minuto'])} suele "
            f"{describir(patron['herramienta'], patron['argumentos'])} {_donde(patron['ubicacion'])}. "
            "¿Lo hago?")


def explicar(patron: dict) -> str:
    """La respuesta a «¿por qué me propones esto?»: el patrón, con sus números."""
    pct = round(float(patron["proporcion"]) * 100)
    return (f"Porque {_cuando(patron['grupo'], patron['minuto'])} {_donde(patron['ubicacion'])}, "
            f"ha pedido {describir(patron['herramienta'], patron['argumentos'])} "
            f"{patron['ocurrencias']} de {patron['dias_posibles']} días ({pct} %). "
            f"Confianza {float(patron['confianza']):.2f}; propongo a partir de {U_SUGERIR:.2f}.")


# ── El detector: frecuencias condicionadas ────────────────────────────────────

def _en_grupo(grupo: str, dia_semana: int) -> bool:
    if grupo == "cada_dia":
        return True
    if grupo == "laborables":
        return dia_semana < 5
    if grupo == "finde":
        return dia_semana >= 5
    return dia_semana == int(grupo[1:])


def _cuenta(evento_: dict) -> bool:
    """Lo que cuenta como «lo hizo»: lo pidió él, o dijo que sí a una sugerencia. Sin esto
    último, cada sugerencia aceptada borraría el patrón que la originó."""
    return evento_.get("tipo") == "peticion" or (
        evento_.get("tipo") == "sugerencia" and evento_.get("respuesta") == "si")


def _mejor_ventana(por_dia: dict) -> tuple:
    """(días distintos, minuto central) de la hora en la que más días coincide."""
    marcas = sorted((m, d) for d, minutos in por_dia.items() for m in minutos)
    mejor: tuple = (0, 0)
    for i, (inicio, _) in enumerate(marcas):
        dentro = [(m, d) for m, d in marcas[i:] if m < inicio + ANCHO_MIN]
        dias = {d for _, d in dentro}
        if len(dias) > mejor[0]:
            # Por día, la primera vez: pedirlo tres veces una mañana no son tres mañanas.
            primeras = {}
            for m, d in dentro:
                primeras.setdefault(d, m)
            mejor = (len(dias), int(median(primeras.values())))
    return mejor


def _dias_posibles(grupo: str, primera: date, hoy: date, por_dia: dict) -> int:
    """Cuántos días de ese tipo ha habido desde la primera vez. Hoy solo cuenta si ya lo ha
    hecho: si no, a media mañana todo patrón de tarde parecería roto."""
    return sum(1 for k in range((hoy - primera).days + 1)
               if _en_grupo(grupo, (primera + timedelta(days=k)).weekday())
               and (primera + timedelta(days=k) < hoy or hoy in por_dia))


def detectar(eventos: list, hoy: date) -> list:
    """Los patrones que hay en el registro: P(acción | tipo de día, hora, lugar).

    Para cada acción y lugar se prueba de lo general a lo concreto (cada día, entre semana,
    el fin de semana, un día de la semana) y se queda lo más general que se sostenga. La
    proporción es sobre los días que había para hacerlo desde la primera vez, no sobre las
    veces que se hizo: «4 de 5 lunes» y no «4 de 4».
    """
    desde = hoy - timedelta(days=VENTANA_DIAS)
    por_accion: dict = {}
    for e in eventos:
        if not _cuenta(e) or e.get("ubicacion") not in UBICACIONES:
            continue
        try:
            dia = date.fromisoformat(str(e["dia"])[:10])
            minuto = int(e["minuto"])
        except (KeyError, TypeError, ValueError):
            continue
        if not desde <= dia <= hoy or not 0 <= minuto < 1440:
            continue
        clave = (e["accion"], e["ubicacion"])
        grupo = por_accion.setdefault(clave, {"dias": {}, "herramienta": e.get("herramienta"),
                                               "argumentos": e.get("argumentos") or {}})
        grupo["dias"].setdefault(dia, []).append(minuto)

    patrones = []
    for (accion, ubicacion), datos in por_accion.items():
        primera = min(datos["dias"])
        cubiertos: set = set()
        for grupo in _GRUPOS_GENERALES + tuple(f"d{n}" for n in range(7)):
            # Lo que ya explica un patrón más general no se repite por debajo.
            if {d for d in range(7) if _en_grupo(grupo, d)} <= cubiertos:
                continue
            por_dia = {d: m for d, m in datos["dias"].items() if _en_grupo(grupo, d.weekday())}
            if not por_dia:
                continue
            n, centro = _mejor_ventana(por_dia)
            minimo = N_MINIMO_DIA if grupo.startswith("d") else N_MINIMO
            posibles = _dias_posibles(grupo, primera, hoy, por_dia)
            if n < minimo or not posibles or n / posibles < PROPORCION_MINIMA:
                continue
            # «Cada día» tiene que sostenerse también el fin de semana: diez mañanas de
            # lunes a viernes no son «cada día», y propondrían la música del trabajo un sábado.
            if grupo == "cada_dia" and any(
                    _dias_posibles(parte, primera, hoy, por_dia)
                    and sum(1 for d in por_dia if _en_grupo(parte, d.weekday()))
                    / _dias_posibles(parte, primera, hoy, por_dia) < PROPORCION_MINIMA
                    for parte in ("laborables", "finde")):
                continue
            patrones.append({
                "clave": f"{accion}@{grupo}@{ubicacion}",
                "accion": accion, "herramienta": datos["herramienta"],
                "argumentos": datos["argumentos"], "grupo": grupo, "minuto": centro,
                "ubicacion": ubicacion, "ocurrencias": n, "dias_posibles": posibles,
                "proporcion": round(n / posibles, 2),
                "ultima_vez": max(por_dia).isoformat(),
            })
            cubiertos |= {d for d in range(7) if _en_grupo(grupo, d)}
    return sorted(patrones, key=lambda p: (-p["proporcion"], -p["ocurrencias"], p["clave"]))


# ── La confianza ──────────────────────────────────────────────────────────────

def _acotar(c: float) -> float:
    return round(min(max(c, 0.0), 1.0), 4)


def tras_respuesta(confianza: float, respuesta: Optional[str]) -> float:
    """Sí sube, no baja más, ignorada no cuenta: «no lo vi» no es un no."""
    if respuesta == "si":
        return _acotar(confianza + ALFA_SI * (1 - confianza))
    if respuesta == "no":
        return _acotar(confianza - BETA_NO * confianza)
    return _acotar(confianza)


def repasar(confianza: float, dias_sin_mirar: int, lo_ha_hecho: bool) -> float:
    """El repaso diario: si lo ha vuelto a hacer él, sube un poco; si no, decae."""
    if lo_ha_hecho:
        return _acotar(confianza + ALFA_PROPIA * (1 - confianza))
    return _acotar(confianza * DECAIMIENTO_DIARIO ** max(int(dias_sin_mirar), 0))


def puede_ejecutar_sola(nivel: str, confianza: float, nucleo: dict) -> bool:
    """Fase 1: nunca. Se deja escrita la frontera de la fase 2 para que no haya que
    inventarla después: solo nivel bajo, solo con confianza alta y solo si el núcleo lo
    enciende; y aun así hoy devuelve False."""
    return False


# ── La entrega ────────────────────────────────────────────────────────────────

def toca(patron: dict, ahora: datetime, ubicacion: str) -> bool:
    """Si este patrón es de ahora: su tipo de día, su hora (un poco antes) y su lugar."""
    if float(patron.get("confianza") or 0) < U_SUGERIR:
        return False
    if patron.get("ubicacion") != ubicacion or not _en_grupo(patron["grupo"], ahora.weekday()):
        return False
    minuto = ahora.hour * 60 + ahora.minute
    return patron["minuto"] - MARGEN_ANTES <= minuto <= patron["minuto"] + MARGEN_DESPUES


def puede_entregar(ahora: datetime, ultima: Optional[datetime], hoy_van: int,
                   callado: bool, nucleo: dict) -> bool:
    """Los frenos de la entrega: nunca si hay que callar, con un mínimo entre dos y un tope
    al día. Los números salen del núcleo, no de aquí."""
    lim = nucleo["anticipa"]["limites"]
    if callado or hoy_van >= lim["max_sugerencias_dia"]:
        return False
    if ultima is None:
        return True
    return (ahora - ultima).total_seconds() >= lim["espera_min_entre_sugerencias"] * 60


def aceptacion(sugerencias: list) -> dict:
    """El criterio de éxito, contado: sí / (sí + no). Las ignoradas van aparte."""
    si = sum(1 for s in sugerencias if s.get("respuesta") == "si")
    no = sum(1 for s in sugerencias if s.get("respuesta") == "no")
    ignoradas = sum(1 for s in sugerencias if s.get("respuesta") == "ignorada")
    return {"si": si, "no": no, "ignoradas": ignoradas,
            "sin_contestar": len(sugerencias) - si - no - ignoradas,
            "aceptacion_pct": round(100 * si / (si + no)) if si + no else None}
