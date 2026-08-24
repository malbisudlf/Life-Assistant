"""Corrige las filas de energía que se guardaron en kilojulios como si fueran kcal.

Tres fallos de la ingesta (ya arreglados en main.py) dejaron kJ crudos en
`health_metrics`: la comparación exacta `unit == "kJ"`, la reasignación de `unit`
dentro del bucle de puntos —que convertía solo el primer día de cada lote— y la ruta
del Atajo de iOS, que no convertía nada.

Esas filas NO se arreglan solas. Las métricas de energía son acumulativas y solo se
pisan si el valor nuevo es MAYOR; un número inflado x4,184 le gana siempre a la medida
buena, así que ninguna sincronización posterior lo puede corregir. Hay que reescribirlas.

Uso (desde la máquina de Fly, que es donde están SUPABASE_URL/SUPABASE_KEY):

    fly ssh console -a backend-tender-glow-160 \\
        -C "python3 /app/corregir_energia_kj.py"            # simulacro, no escribe
    fly ssh console -a backend-tender-glow-160 \\
        -C "python3 /app/corregir_energia_kj.py --aplicar"   # escribe de verdad

Sin --aplicar solo enseña lo que haría. Míralo antes: la conversión es irreversible en
la práctica, porque después ya no se distingue un 409 corregido de un 409 medido.
"""
import argparse
import os
import sys

import requests
from dotenv import load_dotenv

load_dotenv(os.path.join(os.path.dirname(__file__), ".env"))
load_dotenv()

SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")

KJ_POR_KCAL = 4.184
UNIDADES_KJ = {"kj", "kilojoule", "kilojoules", "kilojulio", "kilojulios"}

# Techo de kcal/día por encima del cual el valor no puede ser kcal y es kJ sin
# convertir. Hace falta un umbral porque el fallo del bucle escribía `unit` = "kcal"
# en filas que llevaban kJ: ahí la columna de unidad miente y no sirve para detectarlas.
# Los topes son deliberadamente altos — se trata de no tocar ninguna fila buena, aunque
# eso deje sin corregir algún día flojo que quede por debajo.
TECHOS_KCAL = {
    "active_energy":  1500,
    "resting_energy": 3000,
    "basal_energy":   3000,
}


def es_kilojulios(unit) -> bool:
    if not unit:
        return False
    return "".join(str(unit).split()).lower() in UNIDADES_KJ


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--aplicar", action="store_true",
                    help="escribe los cambios (sin esto solo los enseña)")
    args = ap.parse_args()

    if not SUPABASE_URL or not SUPABASE_KEY:
        print("Faltan SUPABASE_URL / SUPABASE_KEY en el entorno.")
        return 1

    cabeceras = {
        "apikey": SUPABASE_KEY,
        "Authorization": f"Bearer {SUPABASE_KEY}",
        "Content-Type": "application/json",
    }
    metricas = ",".join(TECHOS_KCAL)
    url = (f"{SUPABASE_URL}/rest/v1/health_metrics"
           f"?metric_name=in.({metricas})"
           f"&select=metric_date,metric_name,value,unit"
           f"&order=metric_date.asc&limit=20000")

    r = requests.get(url, headers=cabeceras, timeout=30)
    if r.status_code >= 300:
        print(f"Error leyendo health_metrics: {r.status_code}")
        return 1
    filas = r.json()
    print(f"Filas de energía leídas: {len(filas)}")

    pendientes = []
    for f in filas:
        valor = f.get("value")
        if valor is None:
            continue
        valor = float(valor)
        nombre = f["metric_name"]
        por_unidad = es_kilojulios(f.get("unit"))
        por_techo  = valor > TECHOS_KCAL[nombre]
        if not (por_unidad or por_techo):
            continue
        pendientes.append({
            "metric_date": f["metric_date"],
            "metric_name": nombre,
            "antes":  valor,
            "despues": round(valor / KJ_POR_KCAL, 2),
            "motivo": "unidad" if por_unidad else "supera el techo de kcal",
        })

    if not pendientes:
        print("No hay ninguna fila en kilojulios. Nada que hacer.")
        return 0

    por_metrica: dict = {}
    for p in pendientes:
        por_metrica.setdefault(p["metric_name"], []).append(p)

    for nombre, grupo in sorted(por_metrica.items()):
        antes  = sum(g["antes"] for g in grupo) / len(grupo)
        despues = sum(g["despues"] for g in grupo) / len(grupo)
        print(f"\n{nombre}: {len(grupo)} filas "
              f"({grupo[0]['metric_date']} → {grupo[-1]['metric_date']})")
        print(f"  media antes: {antes:.0f}  →  media después: {despues:.0f} kcal/día")
        for g in grupo[:3]:
            print(f"    {g['metric_date']}: {g['antes']:.0f} → {g['despues']:.0f}  ({g['motivo']})")
        if len(grupo) > 3:
            print(f"    ... y {len(grupo) - 3} más")

    if not args.aplicar:
        print(f"\nSIMULACRO: no se ha escrito nada. Repite con --aplicar para "
              f"corregir las {len(pendientes)} filas.")
        return 0

    fallos = 0
    for p in pendientes:
        destino = (f"{SUPABASE_URL}/rest/v1/health_metrics"
                   f"?metric_date=eq.{p['metric_date']}"
                   f"&metric_name=eq.{p['metric_name']}")
        r = requests.patch(destino, headers=cabeceras,
                           json={"value": p["despues"], "unit": "kcal"}, timeout=30)
        if r.status_code >= 300:
            print(f"  fallo en {p['metric_date']} {p['metric_name']}: {r.status_code}")
            fallos += 1

    print(f"\nCorregidas {len(pendientes) - fallos} filas. Fallos: {fallos}.")
    return 1 if fallos else 0


if __name__ == "__main__":
    sys.exit(main())
