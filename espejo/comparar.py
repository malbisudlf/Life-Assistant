#!/usr/bin/env python3
"""Compara dos pasadas de pytest (JUnit XML): la de main y la de la rama.

    comparar.py main.xml rama.xml  →  JSON en la salida estándar

Una REGRESIÓN es una prueba que pasaba en main y en la rama ya no pasa (falla, da error o
ha desaparecido). Las de conversación son las que guionizan un turno entero de Jarvis: son
el banco de referencia de `docs/JARVIS_PARCHES_ESPEJO.md`, y una regresión ahí pesa aparte.
"""
from __future__ import annotations

import json
import sys
import xml.etree.ElementTree as ET

# Los ficheros que prueban conversaciones enteras (el modelo guionizado, sus herramientas y
# las fronteras de lo que puede hacer), no una función suelta.
CONVERSACION = ("test_jarvis", "test_ajeno", "test_mcp_telefono", "test_llamada",
                "test_llamadas_", "test_casa_llamada", "test_confirmar_en_movil",
                "test_preguntas_jarvis", "test_no_molestar", "test_anticipa", "test_recados")


def leer(ruta: str) -> dict:
    """{id de la prueba: "pasa" | "falla" | "saltada"}. Vacío si no se pudo leer."""
    try:
        raiz = ET.parse(ruta).getroot()
    except (OSError, ET.ParseError):
        return {}
    estados = {}
    for caso in raiz.iter("testcase"):
        nombre = f"{caso.get('classname', '')}::{caso.get('name', '')}"
        if caso.find("failure") is not None or caso.find("error") is not None:
            estados[nombre] = "falla"
        elif caso.find("skipped") is not None:
            estados[nombre] = "saltada"
        else:
            estados[nombre] = "pasa"
    return estados


def _es_conversacion(nombre: str) -> bool:
    return any(trozo.startswith(CONVERSACION) for trozo in nombre.split("::")[0].split("."))


def comparar(base: dict, rama: dict) -> dict:
    pasaban = {n for n, e in base.items() if e == "pasa"}
    pasan = {n for n, e in rama.items() if e == "pasa"}
    fallan = sorted(n for n, e in rama.items() if e == "falla")
    regresiones = sorted(pasaban - pasan)
    conv = {n for n in pasan if _es_conversacion(n)}
    return {
        "aislado": True,
        "unitarias": {"pasan": len(pasan), "fallan": len(fallan),
                      "nuevas": len(pasan - set(base)), "en_main": len(pasaban)},
        "conversacion": {"pasan": len(conv),
                         "regresiones": len([n for n in regresiones if _es_conversacion(n)])},
        "regresiones": regresiones[:50],
        "fallos": fallan[:50],
        # Si main no se pudo probar, no hay con qué comparar: no vale como «sin regresiones».
        "comparable": bool(base) and bool(rama),
    }


def main(argv=None) -> int:
    args = (argv or sys.argv)[1:]
    if len(args) != 2:
        print("uso: comparar.py main.xml rama.xml", file=sys.stderr)
        return 64
    resultado = comparar(leer(args[0]), leer(args[1]))
    if not resultado["comparable"]:
        resultado["unitarias"]["fallan"] = max(resultado["unitarias"]["fallan"], 1)
    elif resultado["regresiones"]:
        resultado["unitarias"]["fallan"] = max(resultado["unitarias"]["fallan"],
                                               len(resultado["regresiones"]))
    print(json.dumps(resultado, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
