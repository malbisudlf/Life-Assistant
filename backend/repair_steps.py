"""
Script de reparación: corrige los valores de step_count en Supabase
que quedaron en 0 o con valores erróneos por el bug del campo 'sum'.

Ejecutar en Fly.io:
  fly sftp put backend/repair_steps.py /app/repair_steps.py
  fly ssh console -C "python3 /app/repair_steps.py"
"""
import os, requests

SUPABASE_URL = os.environ["SUPABASE_URL"]
SUPABASE_KEY = os.environ["SUPABASE_KEY"]

HEADERS = {
    "apikey": SUPABASE_KEY,
    "Authorization": f"Bearer {SUPABASE_KEY}",
    "Content-Type": "application/json",
}

# Totales diarios extraídos del export CSV de Health Auto Export (2026-04-21 a 2026-05-21)
STEP_DATA = {
    "2026-04-21": 9637,
    "2026-04-22": 5322,
    "2026-04-23": 9340,
    "2026-04-24": 9358,
    "2026-04-25": 6850,
    "2026-04-26": 2833,
    "2026-04-27": 5080,
    "2026-04-28": 3155,
    "2026-04-29": 2856,
    "2026-04-30": 8137,
    "2026-05-01": 25749,
    "2026-05-02": 26094,
    "2026-05-03": 19089,
    "2026-05-04": 1929,
    "2026-05-05": 5988,
    "2026-05-06": 6014,
    "2026-05-07": 4905,
    "2026-05-08": 4958,
    "2026-05-09": 6996,
    "2026-05-10": 8155,
    "2026-05-11": 5268,
    "2026-05-12": 5339,
    "2026-05-13": 5784,
    "2026-05-14": 2964,
    "2026-05-15": 10473,
    "2026-05-16": 7529,
    "2026-05-17": 4732,
    "2026-05-18": 6369,
    "2026-05-19": 3877,
    "2026-05-20": 5318,
    "2026-05-21": 5235,
}

fixed = 0
skipped = 0

for date, steps in STEP_DATA.items():
    # Comprobar valor actual en Supabase
    r = requests.get(
        f"{SUPABASE_URL}/rest/v1/health_metrics"
        f"?metric_date=eq.{date}&metric_name=eq.step_count&select=value",
        headers=HEADERS,
    )
    rows = r.json() if r.status_code < 300 else []
    existing = float(rows[0]["value"]) if rows and rows[0].get("value") is not None else None

    # Solo actualizar si el valor existente es menor que el correcto (o no existe)
    if existing is not None and existing >= steps:
        print(f"  skip {date}: existente={existing:.0f} >= correcto={steps}")
        skipped += 1
        continue

    if rows:
        # Ya existe: PATCH (update)
        r2 = requests.patch(
            f"{SUPABASE_URL}/rest/v1/health_metrics"
            f"?metric_date=eq.{date}&metric_name=eq.step_count",
            headers={**HEADERS, "Prefer": "return=minimal"},
            json={"value": steps, "unit": "steps"},
        )
    else:
        # No existe: INSERT
        r2 = requests.post(
            f"{SUPABASE_URL}/rest/v1/health_metrics",
            headers={**HEADERS, "Prefer": "return=minimal"},
            json={"metric_date": date, "metric_name": "step_count", "value": steps, "unit": "steps"},
        )
    if r2.status_code < 300:
        print(f"  fix  {date}: {existing} -> {steps}")
        fixed += 1
    else:
        print(f"  ERROR {date}: {r2.status_code} {r2.text}")

print(f"\nFijados: {fixed}, sin cambios: {skipped}")
