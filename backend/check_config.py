"""Comprobador de configuración del kit self-hosted.

Uso:  python backend/check_config.py
Lee backend/.env (o el entorno) y dice qué funciona y qué falta, agrupado por
funcionalidad, sin llamar a ningún servicio externo.
"""
import os
import sys
from zoneinfo import ZoneInfo

from dotenv import load_dotenv

load_dotenv(os.path.join(os.path.dirname(__file__), ".env"))
load_dotenv()  # por si se ejecuta desde backend/

OK, KO, WARN = "✅", "❌", "⚠️ "


def _set(*names):
    return all(os.getenv(n) for n in names)


def main() -> int:
    print("Life Assistant — comprobación de configuración\n")
    errores = 0

    # Núcleo: sin esto el backend ni arranca
    if _set("SECRET_KEY", "DASHBOARD_PASSWORD"):
        print(f"{OK} Núcleo: SECRET_KEY y DASHBOARD_PASSWORD definidos")
        if len(os.getenv("SECRET_KEY", "")) < 32:
            print(f"{WARN}  SECRET_KEY corta (<32 chars); genera una con: openssl rand -hex 32")
    else:
        print(f"{KO} Núcleo: faltan SECRET_KEY y/o DASHBOARD_PASSWORD — el backend no arrancará")
        errores += 1

    tz = os.getenv("TIMEZONE", "Europe/Madrid")
    try:
        ZoneInfo(tz)
        print(f"{OK} Zona horaria: {tz}")
    except Exception:
        print(f"{KO} TIMEZONE inválida: {tz!r} (usa un nombre IANA, p.ej. Europe/Madrid)")
        errores += 1

    grupos = [
        ("Base de datos (ideas, salud, entrenamiento, jobs)", ["SUPABASE_URL", "SUPABASE_KEY"]),
        ("Calendario Outlook", ["CLIENT_ID", "TENANT_ID", "CLIENT_SECRET", "REDIRECT_URI"]),
        ("Hora de salida con tráfico", ["GOOGLE_MAPS_API_KEY", "HOME_ADDRESS"]),
        ("Ideas por voz (Whisper + GPT)", ["OPENAI_API_KEY"]),
        ("Poll de Home Assistant (WOL, eventos)", ["HA_POLL_TOKEN"]),
        ("Ingesta de salud (Apple Watch)", ["HEALTH_INGEST_TOKEN"]),
    ]
    for nombre, vars_ in grupos:
        faltan = [v for v in vars_ if not os.getenv(v)]
        if not faltan:
            print(f"{OK} {nombre}")
        else:
            print(f"{WARN} {nombre}: sin configurar ({', '.join(faltan)}) — esa parte no funcionará")

    print(f"\nCORS: {os.getenv('CORS_ORIGINS', '(default: localhost + dominio de Mikel — pon el tuyo)')}")
    print(f"Calendario de clases: {os.getenv('CLASSES_CALENDAR', 'clases')}")
    print(f"Clima (lat, lon): {os.getenv('WEATHER_LAT', '40.4168')}, {os.getenv('WEATHER_LON', '-3.7038')}")

    if errores:
        print(f"\n{KO} {errores} error(es) bloqueante(s).")
        return 1
    print(f"\n{OK} Configuración mínima correcta. Lo marcado con {WARN.strip()} es opcional por funcionalidad.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
