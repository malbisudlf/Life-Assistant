"""Las rutinas de la casa, sacadas del archivo. Ver docs/GEMELO.md.

Tres cosas que se pueden contar sin entender nada, y que son justo las que acaban siendo
una automatización:

- **Horarios**: algo que pasa casi todos los días a la misma hora («la luz del despacho se
  enciende hacia las 07:10 los laborables, 18 de 22 días»).
- **Secuencias**: algo que alguien hace a mano justo después de otra cosa («al llegar a
  casa, enciende la luz de la entrada: 9 de 11 veces»).
- **Olvidos**: algo que se queda encendido o abierto mucho más de lo normal («el garaje se
  quedó abierto más de 20 minutos en 4 ocasiones»).

Cada rutina sale con sus números y con una **regla ya escrita** (el formato de
`reglas.py`), para pasarla por el reproductor antes de decidir nada. Aquí no se instala
nada en Home Assistant: se propone, y lo aprueba una persona.

Lo que la primera pasada con la casa de verdad enseñó (2026-11-09), y por eso está aquí:

- Un estado que dura segundos no es una rutina: `arming` antes de `armed`, la luz que
  parpadea al sonar una alarma. Solo cuenta lo que **se queda** (`DURA_*`).
- Dos entidades del mismo aparato se mueven juntas (el ventilador de una impresora cuando
  carga filamento): no es alguien haciendo algo, es el aparato.
- Lo que responde en menos de tres segundos no lo hace una persona: **ya es una
  automatización**. Se dice aparte y no se propone otra vez.
- Una luz que se queda sin corriente pasa a `unavailable`, no a `off`: contarla como
  encendida hasta el siguiente `off` inventaba olvidos de horas.
"""
from __future__ import annotations

import bisect
from collections import defaultdict
from datetime import datetime
from statistics import median

from reglas import SIN_DATO, ZONA

# Lo que una automatización puede mover. Un sensor dispara; esto es lo que se dispara.
ACTUABLES = ("light", "switch", "cover", "climate", "fan", "lock", "input_boolean")
ENCENDIDOS = ("on", "open", "heat", "cool", "unlocked")

VENTANA_MIN = 40            # un horario: lo que cae en una ventana así de ancha
HORARIO_MIN_DIAS = 6        # y pasa al menos estos días…
HORARIO_FRACCION = 0.6      # …y este porcentaje de los días de ese tipo
DURA_HORARIO_S = 600        # y se queda así al menos esto
SECUENCIA_S = 300           # B «justo después» de A
SECUENCIA_MIN = 5           # A tiene que haber pasado al menos estas veces
SECUENCIA_FRACCION = 0.7
PASO_S = 60                 # un estado más corto que esto es un paso hacia otro
DURA_EFECTO_S = 120         # B se queda así al menos esto
YA_AUTOMATICO_S = 3         # más rápido que esto no es una persona
RUIDOSA_AL_DIA = 12         # más cambios al día que esto no es una rutina, es un sensor de paso
MISMO_APARATO = 8           # letras iguales al principio del nombre: mismo aparato
OLVIDO_MIN = {"cover": 20, "lock": 20}   # minutos; lo demás, OLVIDO_POR_DEFECTO
OLVIDO_POR_DEFECTO = 240
OLVIDO_VECES = 3
OLVIDO_MAX_ENCENDIDO = 0.5  # encendido más de la mitad del tiempo: no es un olvido, es un ajuste


def _dominio(entidad: str) -> str:
    return entidad.split(".", 1)[0]


def _hhmm(minuto: float) -> str:
    m = int(round(minuto)) % 1440
    return f"{m // 60:02d}:{m % 60:02d}"


def _mismo_aparato(a: str, b: str) -> bool:
    x, y = a.split(".", 1)[-1], b.split(".", 1)[-1]
    n = 0
    while n < min(len(x), len(y)) and x[n] == y[n]:
        n += 1
    return n >= MISMO_APARATO


def tramos(cambios: list) -> dict:
    """{entidad: [(ts, estado, segundos)]}: cada estado por el que pasó y cuánto duró, con
    `unavailable` incluido (que algo se caiga también es dejar de estar encendido)."""
    fin = cambios[-1][0] if cambios else 0
    crudo = defaultdict(list)
    for ts, entidad, estado in cambios:
        if not crudo[entidad] or crudo[entidad][-1][1] != estado:
            crudo[entidad].append((ts, estado))
    return {e: [(ts, s, (l[i + 1][0] if i + 1 < len(l) else fin) - ts) for i, (ts, s) in enumerate(l)]
            for e, l in crudo.items()}


def transiciones(cambios: list) -> dict:
    """{entidad: [(ts, de, a, segundos que duró, segundos que duró lo anterior)]}, sin lo
    que viene de o va a `unavailable` (un sensor que se cae no es alguien haciendo algo)."""
    salida = defaultdict(list)
    for entidad, lista in tramos(cambios).items():
        for i in range(1, len(lista)):
            (_, previo, antes), (ts, estado, dura) = lista[i - 1], lista[i]
            if previo in SIN_DATO or estado in SIN_DATO:
                continue
            # «Lo anterior» es lo último que duró: `arming` antes de `armed` son segundos,
            # y lo que había de verdad era `disarmed`. Si lo que había es lo mismo que
            # hay ahora, esto es la vuelta de un parpadeo, no un cambio.
            j = i - 1
            while j > 0 and lista[j][2] < PASO_S:
                j -= 1
            if j != i - 1:
                antes = 0 if lista[j][1] == estado else lista[j][2]
            salida[entidad].append((ts, previo, estado, dura, antes))
    return salida


def _dias_del_archivo(cambios: list) -> dict:
    """Cuántos días laborables y de fin de semana cubre el archivo."""
    vistos = {"laborables": set(), "fin de semana": set()}
    if not cambios:
        return vistos
    t, fin = cambios[0][0], cambios[-1][0]
    while t <= fin:
        d = datetime.fromtimestamp(t, ZONA)
        vistos["laborables" if d.weekday() < 5 else "fin de semana"].add(d.date())
        t += 86400
    return vistos


def horarios(cambios: list) -> list:
    trans = transiciones(cambios)
    dias_tipo = _dias_del_archivo(cambios)
    total_dias = sum(len(v) for v in dias_tipo.values()) or 1
    salida = []
    for entidad, lista in trans.items():
        if len(lista) / total_dias > RUIDOSA_AL_DIA:
            continue
        por = defaultdict(lambda: defaultdict(list))   # (tipo, estado) → día → [minuto]
        for ts, _de, a, dura, antes in lista:
            # De algo estable a algo estable: el apagado que cierra un parpadeo de un
            # minuto no es «se apaga a las siete».
            if dura < DURA_HORARIO_S or antes < DURA_HORARIO_S:
                continue
            d = datetime.fromtimestamp(ts, ZONA)
            tipo = "laborables" if d.weekday() < 5 else "fin de semana"
            por[(tipo, a)][d.date()].append(d.hour * 60 + d.minute)
        for (tipo, estado), dias in por.items():
            n_tipo = len(dias_tipo[tipo])
            if n_tipo < HORARIO_MIN_DIAS:
                continue
            # La ventana de VENTANA_MIN con más días distintos dentro.
            puntos = sorted((m, dia) for dia, ms in dias.items() for m in ms)
            mejor, i = (0, []), 0
            for j in range(len(puntos)):
                while puntos[j][0] - puntos[i][0] > VENTANA_MIN:
                    i += 1
                dentro = puntos[i:j + 1]
                distintos = len({d for _, d in dentro})
                if distintos > mejor[0]:
                    mejor = (distintos, dentro)
            n, dentro = mejor
            if n >= HORARIO_MIN_DIAS and n / n_tipo >= HORARIO_FRACCION:
                hora = _hhmm(median(m for m, _ in dentro))
                dias_regla = ["lun", "mar", "mie", "jue", "vie"] if tipo == "laborables" else ["sab", "dom"]
                r = {"tipo": "horario", "entidad": entidad, "estado": estado, "hora": hora,
                     "dias": n, "de": n_tipo, "cuando": tipo,
                     "frase": f"{entidad} pasa a «{estado}» hacia las {hora} los {tipo}: {n} de {n_tipo} días."}
                if _dominio(entidad) in ACTUABLES:
                    # Solo lo que se puede mover: «el móvil entra en modo descanso a las
                    # 21:45» es una rutina que conviene saber, no una regla que instalar.
                    r["regla"] = {"id": f"horario-{entidad}-{estado}-{tipo.split()[0]}",
                                  "descripcion": f"A las {hora}, {entidad} → {estado} ({tipo})",
                                  "cuando": {"a_las": hora},
                                  "si": [{"dias": dias_regla}, {"entidad": entidad, "no_es": estado}],
                                  "entonces": {"entidad": entidad, "estado": estado}}
                salida.append(r)
    return sorted(salida, key=lambda r: -r["dias"] / r["de"])


def secuencias(cambios: list, anclas=None) -> list:
    """Después de A, B. `anclas`: las entidades A que se miran (por defecto, todas las que
    no sean ruidosas)."""
    trans = transiciones(cambios)
    dias = sum(len(v) for v in _dias_del_archivo(cambios).values()) or 1
    tranquilas = {e: l for e, l in trans.items() if len(l) / dias <= RUIDOSA_AL_DIA}
    efectos = sorted((ts, e, a) for e, l in tranquilas.items() if _dominio(e) in ACTUABLES
                     for ts, _de, a, dura, _antes in l if dura >= DURA_EFECTO_S)
    tiempos = [x[0] for x in efectos]
    salida = []
    for a_ent, lista in tranquilas.items():
        if anclas is not None and a_ent not in anclas:
            continue
        por_estado = defaultdict(list)
        for ts, _de, a, _dura, _antes in lista:
            por_estado[a].append(ts)
        for a_estado, veces in por_estado.items():
            if len(veces) < SECUENCIA_MIN:
                continue
            seguidas = defaultdict(dict)   # (B, estado) → {índice de A: segundos que tardó}
            for k, t in enumerate(veces):
                i = bisect.bisect_right(tiempos, t)
                while i < len(efectos) and efectos[i][0] <= t + SECUENCIA_S:
                    tb, b_ent, b_estado = efectos[i]
                    if b_ent != a_ent and not _mismo_aparato(a_ent, b_ent):
                        seguidas[(b_ent, b_estado)].setdefault(k, tb - t)
                    i += 1
            for (b_ent, b_estado), ks in seguidas.items():
                if len(ks) / len(veces) < SECUENCIA_FRACCION:
                    continue
                tarda = median(ks.values())
                ya = tarda < YA_AUTOMATICO_S
                r = {"tipo": "secuencia", "tras": a_ent, "tras_estado": a_estado,
                     "entidad": b_ent, "estado": b_estado, "veces": len(ks), "de": len(veces),
                     "tarda_s": round(tarda, 1), "ya_automatizada": ya,
                     "frase": f"Cuando {a_ent} pasa a «{a_estado}», {b_ent} pasa a «{b_estado}» "
                              + (f"al instante: {len(ks)} de {len(veces)} veces. Ya lo hace una automatización."
                                 if ya else
                                 f"a los {round(tarda)} s de mediana: {len(ks)} de {len(veces)} veces.")}
                if not ya:
                    r["regla"] = {"id": f"tras-{a_ent}-{a_estado}-{b_ent}",
                                  "descripcion": f"Al pasar {a_ent} a {a_estado}, {b_ent} → {b_estado}",
                                  "cuando": {"entidad": a_ent, "pasa_a": a_estado},
                                  "si": [{"entidad": b_ent, "no_es": b_estado}],
                                  "entonces": {"entidad": b_ent, "estado": b_estado}}
                salida.append(r)
    # Lo que aún se hace a mano, delante: es lo único que se puede proponer.
    return sorted(salida, key=lambda r: (r["ya_automatizada"], -r["veces"] / r["de"], -r["de"]))


PUERTAS = ("puerta", "door", "garaje", "garage")


def olvidos(cambios: list, puertas=()) -> list:
    """`puertas`: los `binary_sensor` que son una puerta (la configuración, clave `puertas`);
    sin eso, los que lo llevan en el nombre. Del resto de sensores no se sabe qué es «on»."""
    salida = []
    for entidad, lista in tramos(cambios).items():
        dominio = _dominio(entidad)
        es_puerta = dominio == "binary_sensor" and (entidad in puertas or any(p in entidad for p in PUERTAS))
        if not es_puerta and (dominio not in ACTUABLES or dominio == "input_boolean"):
            continue
        umbral = 20 if es_puerta else OLVIDO_MIN.get(dominio, OLVIDO_POR_DEFECTO)
        duraciones = [dura / 60 for _ts, estado, dura in lista if estado in ENCENDIDOS]
        total = sum(dura for _ts, _estado, dura in lista) / 60
        # Lo que está encendido casi siempre no se olvida encendido: es un ajuste (el «no
        # molestar» de un altavoz, el LED de un enchufe), y su estado normal es ese.
        if not total or sum(duraciones) / total > OLVIDO_MAX_ENCENDIDO:
            continue
        largos = [d for d in duraciones if d >= umbral]
        if len(largos) >= OLVIDO_VECES and len(duraciones) > len(largos):
            normal = median(d for d in duraciones if d < umbral)
            salida.append({
                "tipo": "olvido", "entidad": entidad, "veces": len(largos), "de": len(duraciones),
                "umbral_min": umbral, "normal_min": round(normal, 1),
                "frase": f"{entidad} se quedó así más de {umbral} minutos {len(largos)} veces de {len(duraciones)} "
                         f"(lo normal son {round(normal)} min).",
                "regla": {"id": f"olvido-{entidad}", "descripcion": f"Avisar si {entidad} lleva {umbral} minutos así",
                          "cuando": {"entidad": entidad, "pasa_a": list(ENCENDIDOS), "durante_min": umbral},
                          "entonces": {"avisar": f"{entidad} lleva {umbral} minutos así"}},
            })
    return sorted(salida, key=lambda r: -r["veces"])


def todas(cambios: list, anclas=None, puertas=()) -> list:
    return secuencias(cambios, anclas) + horarios(cambios) + olvidos(cambios, puertas)
