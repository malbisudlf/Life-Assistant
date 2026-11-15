#!/usr/bin/env python3
"""El espejo de parches: la puerta de seguridad, el informe y el rastro.

Cuando Jarvis propone un cambio en su propio código, antes de probar nada se mira QUÉ toca
(`revisar`). Si toca el núcleo de seguridad o amplía lo que Jarvis puede hacer, se rechaza
sin ejecutarlo. Lo que pasa la puerta se prueba en el espejo (`espejo.sh`, en `caja`, sin
red) y de ahí sale un informe de tres líneas y una sola pregunta (`informe`). Todo queda
apuntado (`apuntar`). Diseño en `docs/JARVIS_PARCHES_ESPEJO.md`.

Aquí no hay red ni se ejecuta nada del parche: solo se lee su diff. Sin dependencias, para
que corra igual en `caja`, en el CI y en el PC.

    espejo.py revisar  --diff cambio.diff [--capacidad nombre ...]
    espejo.py informe  --diff cambio.diff --pruebas pruebas.json --resumen "qué cambia"
    espejo.py apuntar  --rastro rastro.jsonl --id P --paso propuesto|probado|aprobado|canario|vuelta --dato k=v ...
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
from datetime import datetime, timezone

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
NUCLEO = os.path.join(RAIZ, "backend", "nucleo_seguridad.json")
# Quién puede proponer un parche. No hay ningún valor para «lo pidió un mensaje»: lo que
# escribe otra persona (un correo, un WhatsApp, una web) es un dato, nunca un encargo.
PROPONENTES = ("mikel", "jarvis:fallo")
PASOS = ("propuesto", "rechazado", "probado", "aprobado", "canario", "confirmado", "vuelta")

_CABECERA = re.compile(r"^diff --git a/(.+?) b/(.+)$")
_HERRAMIENTA = re.compile(r'^\s{4}"([a-z][a-z0-9_]*)":\s*\{\s*$')
_CONFIRMAR = re.compile(r'"confirmar"\s*:\s*(\S+)')
_FLAG = re.compile(r'_flag\(\s*"([A-Z0-9_]+)"\s*(?:,\s*"([01])")?\s*\)')
_ESCRIBE = r"\s*(=(?!=)|\+=|-=|\|=|&=|\.(add|update|append|extend|remove|discard|pop|clear|insert)\()"


def cargar_nucleo(ruta: str = NUCLEO) -> dict:
    with open(ruta, encoding="utf-8") as f:
        nucleo = json.load(f)
    if not (nucleo.get("parches") or {}).get("rutas_protegidas"):
        raise RuntimeError("nucleo_seguridad.json: faltan las rutas protegidas")
    return nucleo


def leer_diff(texto: str) -> dict:
    """De un `git diff` a {ruta: {"mas": [...], "menos": [...]}}. Un renombrado cuenta para
    las dos rutas: mover un fichero protegido es tocarlo."""
    ficheros: dict = {}
    actuales: list = []
    for linea in texto.splitlines():
        m = _CABECERA.match(linea)
        if m:
            actuales = sorted({m.group(1), m.group(2)})
            for ruta in actuales:
                ficheros.setdefault(ruta, {"mas": [], "menos": []})
            continue
        if linea.startswith(("+++", "---")) or not actuales:
            continue
        if linea.startswith("+"):
            for ruta in actuales:
                ficheros[ruta]["mas"].append(linea[1:])
        elif linea.startswith("-"):
            for ruta in actuales:
                ficheros[ruta]["menos"].append(linea[1:])
    return ficheros


def _protegida(ruta: str, protegidas: list) -> bool:
    ruta = ruta.replace("\\", "/").removeprefix("./")
    return any(ruta == p or (p.endswith("/") and ruta.startswith(p)) for p in protegidas)


def _es_codigo(ruta: str) -> bool:
    return ruta.endswith(".py") and not ruta.startswith("tests/")


def revisar(texto_diff: str, nucleo: dict, capacidades: tuple = ()) -> dict:
    """El veredicto de la puerta: `rechazos` (no se prueba ni se despliega) y `avisos`.

    Cuatro reglas, todas sobre el diff y ninguna sobre lo que el parche diga de sí mismo:
      1. No toca una ruta protegida.
      2. No cambia un símbolo del núcleo: ni quita una línea que lo nombre, ni lo redefine,
         ni escribe en él, ni lo nombra entre comillas (que es como se parchea por detrás).
         Usarlo sí puede: un endpoint nuevo tiene que poder pedir `Depends(verify_token)`.
      3. Los permisos solo bajan: una herramienta nueva es una capacidad nueva y necesita que
         Mikel la haya aprobado POR SU NOMBRE; y ninguna confirmación se quita.
      4. Lo nuevo nace apagado: un interruptor que nazca encendido se rechaza.
    """
    reglas = nucleo["parches"]
    ficheros = leer_diff(texto_diff)
    rechazos: list = []
    avisos: list = []
    if not ficheros:
        return {"ok": False, "rechazos": ["El diff está vacío o no es un `git diff`."],
                "avisos": [], "ficheros": [], "capacidades_nuevas": []}

    for ruta in sorted(ficheros):
        if _protegida(ruta, reglas["rutas_protegidas"]):
            rechazos.append(f"Toca una ruta protegida: {ruta}")

    simbolos = reglas.get("simbolos_protegidos") or []
    for ruta, cambio in sorted(ficheros.items()):
        if not _es_codigo(ruta):
            continue
        for s in simbolos:
            nombre = re.compile(r"(?<![A-Za-z0-9_])" + re.escape(s) + ("" if s.endswith("_") else r"(?![A-Za-z0-9_])"))
            cola = r"[A-Za-z0-9_]*" if s.endswith("_") else ""
            define = re.compile(r"^\s*(async\s+def|def|class)\s+" + re.escape(s) + cola + r"\b")
            escribe = re.compile(r"(?<![A-Za-z0-9_.])" + re.escape(s) + cola + r"(\[[^\]]*\])?" + _ESCRIBE)
            comillas = re.compile(r"[\"']" + re.escape(s) + cola + r"[\"']")
            if any(nombre.search(l) for l in cambio["menos"]):
                rechazos.append(f"Quita o cambia una línea del núcleo ({s}) en {ruta}")
            elif any(define.search(l) or escribe.search(l) or comillas.search(l) for l in cambio["mas"]):
                rechazos.append(f"Redefine o escribe en el núcleo ({s}) en {ruta}")

    nuevas: list = []
    for ruta, cambio in sorted(ficheros.items()):
        if not _es_codigo(ruta):
            continue
        mas = cambio["mas"]
        for i, linea in enumerate(mas):
            m = _HERRAMIENTA.match(linea)
            if m and any(_CONFIRMAR.search(l) for l in mas[i + 1:i + 4]):
                nuevas.append(m.group(1))
        quitadas = sum(1 for l in cambio["menos"] if (c := _CONFIRMAR.search(l)) and c.group(1).startswith("True"))
        puestas = sum(1 for l in mas if (c := _CONFIRMAR.search(l)) and c.group(1).startswith("True"))
        if quitadas > puestas:
            rechazos.append(f"Quita una confirmación (`\"confirmar\": True`) en {ruta}")
        for l in mas:
            f = _FLAG.search(l)
            if f and f.group(2) != "0":
                rechazos.append(f"El interruptor {f.group(1)} nace encendido en {ruta}: lo nuevo nace apagado")
    irreversibles = set((nucleo.get("irreversible") or {}).get("herramientas") or [])
    for nombre in nuevas:
        if nombre not in capacidades:
            rechazos.append(f"Añade una capacidad nueva ({nombre}) que Mikel no ha aprobado por su nombre")
        elif nombre in irreversibles:
            avisos.append(f"{nombre} es de las irreversibles: tiene que llevar confirmación")

    tocan_codigo = [r for r in ficheros if _es_codigo(r)]
    con_interruptor = any(_FLAG.search(l) and "PARCHE_" in l
                          for r in tocan_codigo for l in ficheros[r]["mas"])
    if tocan_codigo and not con_interruptor:
        avisos.append("Sin interruptor PARCHE_NN: el canario no puede apagarlo solo, "
                      "la vuelta atrás será al commit anterior")
    con_prueba = any(r.startswith("tests/") and ficheros[r]["mas"] for r in ficheros)
    if tocan_codigo and not con_prueba:
        rechazos.append("No trae ninguna prueba nueva: un parche sin prueba no se presenta")
    return {"ok": not rechazos, "rechazos": rechazos, "avisos": avisos,
            "ficheros": sorted(ficheros), "capacidades_nuevas": nuevas,
            "mas": sum(len(c["mas"]) for c in ficheros.values()),
            "menos": sum(len(c["menos"]) for c in ficheros.values()),
            "con_interruptor": con_interruptor}


def riesgo(veredicto: dict) -> str:
    """Bajo, medio o alto, por lo que toca. No por lo que el parche diga de sí mismo."""
    if not veredicto["ok"]:
        return "alto"
    if veredicto["capacidades_nuevas"] or not veredicto["con_interruptor"] \
            or veredicto["mas"] + veredicto["menos"] > 200:
        return "medio"
    return "bajo"


def informe(veredicto: dict, pruebas: dict, resumen: str) -> str:
    """Tres líneas y una pregunta. Si algo no pasó, no hay pregunta: no hay nada que desplegar."""
    resumen = " ".join((resumen or "").split())[:160] or "(sin resumen)"
    n = len(veredicto["ficheros"])
    que = f"Qué cambia: {resumen} ({n} fichero{'s' if n != 1 else ''}, +{veredicto.get('mas', 0)}/−{veredicto.get('menos', 0)})."
    if not veredicto["ok"]:
        return "\n".join([que, "Qué se probó: nada. La puerta de seguridad lo ha rechazado: "
                          + "; ".join(veredicto["rechazos"]) + ".",
                          "Riesgo: alto. No se despliega; necesita que lo mire usted."])
    u, c = pruebas.get("unitarias") or {}, pruebas.get("conversacion") or {}
    probado = (f"Qué se probó: {u.get('pasan', 0)} pruebas en el espejo sin red"
               f" ({u.get('fallan', 0)} fallan, {u.get('nuevas', 0)} nuevas), "
               f"{c.get('pasan', 0)} de conversación ({c.get('regresiones', 0)} regresiones) "
               f"y la puerta de seguridad.")
    limpio = (pruebas.get("aislado") is True and not u.get("fallan") and not c.get("regresiones")
              and u.get("pasan", 0) > 0)
    cola = f" {' '.join(veredicto['avisos'])}." if veredicto["avisos"] else ""
    if not limpio:
        motivo = ("el espejo no estaba aislado" if pruebas.get("aislado") is not True
                  else "hay pruebas en rojo o regresiones")
        return "\n".join([que, probado, f"Riesgo: alto, {motivo}. No se despliega."])
    return "\n".join([que, probado, f"Riesgo: {riesgo(veredicto)}.{cola}", "¿Lo despliego?"])


def apuntar(rastro: str, parche: str, paso: str, datos: dict) -> dict:
    """Una línea más en el rastro. Solo se añade: nada se reescribe ni se borra."""
    if paso not in PASOS:
        raise ValueError(f"paso desconocido: {paso}")
    if paso == "propuesto" and datos.get("propuesto_por") not in PROPONENTES:
        raise ValueError("un parche solo lo propone Mikel o un fallo repetido del registro")
    if paso == "aprobado" and not (datos.get("aprobado_por") == "mikel" and datos.get("literal")):
        raise ValueError("la aprobación es de Mikel, con sus palabras tal cual")
    entrada = {"ts": datetime.now(timezone.utc).isoformat(), "parche": parche, "paso": paso, **datos}
    os.makedirs(os.path.dirname(os.path.abspath(rastro)) or ".", exist_ok=True)
    with open(rastro, "a", encoding="utf-8") as f:
        f.write(json.dumps(entrada, ensure_ascii=False, sort_keys=True) + "\n")
    return entrada


def huella(texto_diff: str) -> str:
    return hashlib.sha256(texto_diff.encode("utf-8")).hexdigest()[:16]


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    sub = ap.add_subparsers(dest="orden", required=True)
    r = sub.add_parser("revisar")
    r.add_argument("--diff", required=True)
    r.add_argument("--capacidad", action="append", default=[])
    i = sub.add_parser("informe")
    i.add_argument("--diff", required=True)
    i.add_argument("--pruebas", required=True)
    i.add_argument("--resumen", default="")
    i.add_argument("--capacidad", action="append", default=[])
    a = sub.add_parser("apuntar")
    a.add_argument("--rastro", required=True)
    a.add_argument("--id", required=True)
    a.add_argument("--paso", required=True, choices=PASOS)
    a.add_argument("--dato", action="append", default=[])
    args = ap.parse_args(argv)
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")

    if args.orden == "apuntar":
        datos = dict(d.split("=", 1) for d in args.dato)
        print(json.dumps(apuntar(args.rastro, args.id, args.paso, datos), ensure_ascii=False))
        return 0
    with open(args.diff, encoding="utf-8", errors="replace") as f:
        texto = f.read()
    veredicto = revisar(texto, cargar_nucleo(), tuple(args.capacidad))
    veredicto["huella"] = huella(texto)
    if args.orden == "revisar":
        print(json.dumps(veredicto, ensure_ascii=False, indent=2))
        return 0 if veredicto["ok"] else 2
    with open(args.pruebas, encoding="utf-8") as f:
        pruebas = json.load(f)
    texto_informe = informe(veredicto, pruebas, args.resumen)
    print(texto_informe)
    return 0 if texto_informe.endswith("¿Lo despliego?") else 2


if __name__ == "__main__":
    sys.exit(main())
