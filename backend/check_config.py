"""Comprobador de configuración del kit self-hosted.

Uso:  python backend/check_config.py [--probar-voz]
Lee backend/.env (o el entorno) y dice qué funciona y qué falta, agrupado por
funcionalidad, sin llamar a ningún servicio externo.

`--probar-voz` es la única excepción, y es opt-in por eso: sintetiza una palabra con
ElevenLabs para saber si la voz configurada se puede usar de verdad. Ver `probar_voz`.
"""
import os
import sys
from zoneinfo import ZoneInfo

from dotenv import load_dotenv

load_dotenv(os.path.join(os.path.dirname(__file__), ".env"))
load_dotenv()  # por si se ejecuta desde backend/

# La consola de Windows usa cp1252 por defecto y los emojis la hacen reventar con un
# UnicodeEncodeError: el script que existe para ayudar a configurar el kit se caía en
# la primera línea, justo en la máquina donde más falta hace. Se intenta pasar la salida
# a UTF-8 y, si no se puede, se usan marcas ASCII.
try:
    sys.stdout.reconfigure(encoding="utf-8")
    OK, KO, WARN = "✅", "❌", "⚠️ "
except Exception:
    OK, KO, WARN = "[OK]", "[--]", "[!!]"


def _set(*names):
    return all(os.getenv(n) for n in names)


def probar_voz() -> int:
    """Comprueba que ELEVENLABS_VOICE_ID se puede usar con esta clave. Devuelve errores.

    Existe porque este fallo es MUDO por el camino que usa el modo llamada. El navegador
    sintetiza por WebSocket, y ahí una voz que la cuenta no puede usar no da error: llega
    `isFinal` con cero bytes y el frontend, que no tiene forma de distinguirlo de un
    fallo cualquiera, se cae a la voz del navegador sin decir por qué. Ya pasó: el secret
    de Fly tenía una voz de la Voice Library, que el plan gratuito no permite por API, y
    la llamada llevaba semanas sonando robótica sin un solo rastro en los logs.

    Por HTTP el mismo intento SÍ dice el motivo (402 `paid_plan_required`), así que la
    comprobación va por HTTP a propósito. Gasta unos pocos caracteres de la cuota.
    """
    clave = os.getenv("ELEVENLABS_API_KEY", "")
    voz   = os.getenv("ELEVENLABS_VOICE_ID", "")
    if not (clave and voz):
        print(f"{WARN} Voz: sin ELEVENLABS_API_KEY / ELEVENLABS_VOICE_ID, no hay nada que probar")
        return 0
    try:
        import httpx
        r = httpx.post(
            f"https://api.elevenlabs.io/v1/text-to-speech/{voz}",
            headers={"xi-api-key": clave},
            json={"text": "Prueba.", "model_id": os.getenv("ELEVENLABS_MODEL", "eleven_flash_v2_5")},
            timeout=60,
        )
    except Exception as e:
        print(f"{KO} Voz: no se ha podido hablar con ElevenLabs ({e})")
        return 1
    if r.status_code == 200 and r.content:
        print(f"{OK} Voz: la voz {voz} sintetiza ({len(r.content)} bytes)")
        return 0
    print(f"{KO} Voz: la voz {voz} NO se puede usar — HTTP {r.status_code}: {r.text[:200]}")
    if r.status_code == 402:
        print("     Es una voz de la Voice Library y la cuenta es de plan gratuito. Pon una")
        print("     voz por defecto (p. ej. George, JBFqnCBsd6RMkjVDRZzb) o sube de plan.")
    return 1


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
        ("Ideas por voz y Jarvis (Whisper + GPT)", ["OPENAI_API_KEY"]),
        ("Poll de Home Assistant (WOL, eventos)", ["HA_POLL_TOKEN"]),
        ("Ingesta de salud (Apple Watch)", ["HEALTH_INGEST_TOKEN"]),
        ("Resumen diario por correo", ["BRIEF_TOKEN", "BRIEF_TO", "SMTP_HOST", "SMTP_USER", "SMTP_PASSWORD"]),
        ("Agente PC (cola de jobs)", ["AGENT_TOKEN"]),
        ("Finanzas (cartera de Indexa Capital)", ["INDEXA_TOKEN"]),
        ("Revisión nocturna accionable (aviso con botones)",
         ["REVISION_TOKEN", "ARREGLO_FIRE_URL", "ARREGLO_FIRE_TOKEN", "JARVIS_REPO"]),
        ("Voz de Jarvis con ElevenLabs", ["ELEVENLABS_API_KEY", "ELEVENLABS_VOICE_ID"]),
        ("Despliegue con permiso (arreglo automático del CI roto)",
         ["REVISION_TOKEN", "ARREGLO_FIRE_URL", "DEPLOY_GITHUB_TOKEN", "JARVIS_REPO"]),
        ("Avísame (una sesión te avisa y le contestas hablando)",
         ["SESION_TOKEN", "SESION_FIRE_URL", "SESION_FIRE_TOKEN"]),
        ("Jarvis desde el Atajo de iOS (\"Oye Siri, dile a Jarvis...\")", ["JARVIS_TOKEN"]),
        ("El teléfono (Jarvis te llama)",
         ["TWILIO_ACCOUNT_SID", "TWILIO_AUTH_TOKEN", "TWILIO_NUMERO", "TWILIO_MI_NUMERO",
          "BACKEND_URL", "ELEVENLABS_API_KEY", "OPENAI_API_KEY"]),
    ]
    for nombre, vars_ in grupos:
        faltan = [v for v in vars_ if not os.getenv(v)]
        if not faltan:
            print(f"{OK} {nombre}")
        else:
            print(f"{WARN} {nombre}: sin configurar ({', '.join(faltan)}) — esa parte no funcionará")

    if _set("ELEVENLABS_API_KEY", "ELEVENLABS_VOICE_ID") and os.getenv("JARVIS_VOZ_ELEVENLABS") != "1":
        print(f"{WARN}  ElevenLabs configurado pero JARVIS_VOZ_ELEVENLABS no vale 1 — /voz/token responderá 503")

    print(f"\nCORS: {os.getenv('CORS_ORIGINS', '(default: localhost + dominio de Mikel — pon el tuyo)')}")
    print(f"Calendario de clases: {os.getenv('CLASSES_CALENDAR', 'clases')}")
    print(f"Clima (lat, lon): {os.getenv('WEATHER_LAT', '40.4168')}, {os.getenv('WEATHER_LON', '-3.7038')}")
    print(f"Marcador de entregas: {os.getenv('ENTREGAS_MARKER', '📚')} (debe coincidir con VITE_ENTREGAS_MARKER)")

    if "--probar-voz" in sys.argv:
        print()
        errores += probar_voz()

    if errores:
        print(f"\n{KO} {errores} error(es) bloqueante(s).")
        return 1
    print(f"\n{OK} Configuración mínima correcta. Lo marcado con {WARN.strip()} es opcional por funcionalidad.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
