#!/usr/bin/env python3
"""El gemelo de la casa: probar una regla contra lo que ya pasó, y sacar las rutinas.

Ver docs/GEMELO.md. Se ejecuta EN caja, que es quien llega a Home Assistant:

    python3 gemelo/gemelo.py archivar                 # copia lo que falte del histórico
    python3 gemelo/gemelo.py estado                   # qué hay en el archivo
    python3 gemelo/gemelo.py probar regla.json        # qué habría hecho esa regla
    python3 gemelo/gemelo.py probar regla.json --dias 14 --lista
    python3 gemelo/gemelo.py rutinas                  # lo que la casa hace sola o a mano
    python3 gemelo/gemelo.py rutinas --probar         # y cada una, pasada por el reproductor

No gasta nada: ni un modelo, ni una API de pago. Y no puede tocar la casa: de Home
Assistant solo lee (`historia.py`).
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import historia   # noqa: E402
import reglas     # noqa: E402
import rutinas    # noqa: E402

CASA = Path(os.environ.get("GEMELO_DIR", Path.home() / "gemelo-casa"))


def _entorno() -> tuple:
    """HA_URL y HA_TOKEN: del entorno, o del `backend.env` de caja (el mismo token)."""
    url, token = os.environ.get("HA_URL", ""), os.environ.get("HA_TOKEN", "")
    fichero = Path(os.environ.get("GEMELO_ENV", Path.home() / "stack" / "backend.env"))
    if not (url and token) and fichero.exists():
        for linea in fichero.read_text(encoding="utf-8").splitlines():
            k, _, v = linea.partition("=")
            if k == "HA_URL" and not url:
                url = v.strip().strip('"')
            if k == "HA_TOKEN" and not token:
                token = v.strip().strip('"')
    if not (url and token):
        raise SystemExit("Faltan HA_URL y HA_TOKEN (en el entorno o en ~/stack/backend.env).")
    return url, token


def _fecha(ts) -> str:
    return time.strftime("%d/%m/%Y", time.localtime(ts)) if ts else "—"


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description="El gemelo de la casa")
    sub = p.add_subparsers(dest="orden", required=True)
    a = sub.add_parser("archivar")
    a.add_argument("--dias", type=int, default=35)
    sub.add_parser("estado")
    pr = sub.add_parser("probar")
    pr.add_argument("regla")
    pr.add_argument("--dias", type=int, default=0, help="solo los últimos N días")
    pr.add_argument("--lista", action="store_true", help="cada disparo, con su hora")
    pr.add_argument("--json", action="store_true")
    r = sub.add_parser("rutinas")
    r.add_argument("--probar", action="store_true", help="pasar cada propuesta por el reproductor")
    r.add_argument("--todas", action="store_true", help="también lo que ya hace una automatización")
    r.add_argument("--json", action="store_true")
    r.add_argument("--max", type=int, default=25)
    o = p.parse_args(argv)

    db = historia.abrir(CASA / "historia.sqlite")
    conf = historia.configuracion(CASA / "config.json")

    if o.orden == "archivar":
        url, token = _entorno()
        try:
            historia.archivar(db, url, token, conf, dias=o.dias)
        except historia.HaNoContesta as e:
            print(f"Gemelo: {e}", file=sys.stderr)
            return 2
        return 0

    res = historia.resumen(db)
    if o.orden == "estado":
        print(f"{res['cambios']} cambios de {res['entidades']} entidades, del {_fecha(res['desde'])} "
              f"al {_fecha(res['hasta'])} ({res['dias']} días).")
        return 0
    if not res["cambios"]:
        print("El archivo está vacío: pasa antes `archivar`.", file=sys.stderr)
        return 2

    if o.orden == "probar":
        regla = json.loads(Path(o.regla).read_text(encoding="utf-8"))
        motivo = reglas.validar(regla)
        if motivo:
            print(f"La regla no vale: {motivo}", file=sys.stderr)
            return 2
        cambios = historia.leer(db, entidades=reglas.entidades_de(regla))
        vistas = {e for _, e, _ in cambios}
        faltan = reglas.entidades_de(regla) - vistas
        if faltan:
            print(f"⚠ El archivo no tiene nada de: {', '.join(sorted(faltan))}", file=sys.stderr)
        desde = res["hasta"] - o.dias * 86400 if o.dias else res["desde"]
        inf = reglas.reproducir(regla, cambios, desde=desde, hasta=res["hasta"])
        if o.json:
            print(json.dumps(inf, ensure_ascii=False, indent=1))
            return 0
        print(f"{inf['id'] or o.regla}: {reglas.frase(inf)}")
        if inf["disparos"]:
            print("  por hora: " + "  ".join(f"{h:02d}h×{n}" for h, n in inf["por_hora"].items()))
            print("  por día:  " + "  ".join(f"{d}×{n}" for d, n in inf["por_dia_semana"].items())
                  + f"   (máximo en un día: {inf['max_en_un_dia']})")
        if o.lista:
            for d in inf["lista"]:
                marcas = [m for m, si in (("reconexión", d["tras_reconexion"]), ("en falso", d["en_falso"]),
                                           ("ráfaga", d["rafaga"])) if si]
                print(f"  {d['cuando']}" + (f"   ← {', '.join(marcas)}" if marcas else ""))
        return 0

    # rutinas
    cambios = historia.leer(db)
    encontradas = rutinas.todas(cambios, puertas=tuple(conf.get("puertas") or ()))
    if not o.todas:
        # Lo que ya hace una automatización no es una propuesta: se enseña con --todas.
        encontradas = [ru for ru in encontradas if not ru.get("ya_automatizada")]
    encontradas = encontradas[: o.max]
    if o.probar:
        for ru in encontradas:
            regla = ru.get("regla")
            if regla:
                ru["prueba"] = reglas.frase(reglas.reproducir(
                    regla, [c for c in cambios if c[1] in reglas.entidades_de(regla)]))
    if o.json:
        print(json.dumps(encontradas, ensure_ascii=False, indent=1))
        return 0
    if not encontradas:
        print(f"Con {res['dias']} días de archivo no sale ninguna rutina clara todavía.")
        return 0
    for ru in encontradas:
        print(f"[{ru['tipo']}] {ru['frase']}")
        if ru.get("prueba"):
            print(f"      como regla: {ru['prueba']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
