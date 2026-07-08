"""Login inicial en MyBMW (se ejecuta UNA VEZ, en local, no en Fly).

El primer login de bimmer_connected requiere resolver un hCaptcha a mano:
  1. Ve a https://bimmer-connected.readthedocs.io/en/stable/captcha.html
     y resuelve el captcha de tu región para obtener un token temporal.
  2. Ejecuta:  python backend/bmw_login.py
     (necesita backend/.env con BMW_USERNAME, BMW_PASSWORD, SUPABASE_URL, SUPABASE_KEY)
  3. El refresh token se guarda en la tabla oauth_tokens (provider='bmw') y el
     backend lo usará/rotará automáticamente — no hace falta repetir el captcha.

NOTA: bimmer_connected 0.17.4 avisa de que la API de MyBMW cambió y la librería
está no-funcional. Si el login falla con errores de auth, no es culpa tuya:
comprueba si hay versión nueva (pip index versions bimmer_connected) y actualiza
requirements.txt. Mientras tanto, el dashboard usa el fallback de Home Assistant.
"""
import asyncio
import getpass
import os
import sys
from datetime import datetime, timezone

import requests
from dotenv import load_dotenv

load_dotenv()

SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")
BMW_USERNAME = os.getenv("BMW_USERNAME") or input("Email de MyBMW: ").strip()
BMW_PASSWORD = os.getenv("BMW_PASSWORD") or getpass.getpass("Contraseña de MyBMW: ")
BMW_REGION   = os.getenv("BMW_REGION", "row")

if not (SUPABASE_URL and SUPABASE_KEY):
    sys.exit("Faltan SUPABASE_URL / SUPABASE_KEY en backend/.env")


def _headers():
    return {
        "apikey": SUPABASE_KEY,
        "Authorization": f"Bearer {SUPABASE_KEY}",
        "Content-Type": "application/json",
    }


async def main():
    from bimmer_connected.account import MyBMWAccount
    from bimmer_connected.api.regions import Regions

    captcha = input("Token del hCaptcha (ver docstring): ").strip()
    region = {"na": Regions.NORTH_AMERICA, "cn": Regions.CHINA}.get(BMW_REGION, Regions.REST_OF_WORLD)
    account = MyBMWAccount(BMW_USERNAME, BMW_PASSWORD, region, hcaptcha_token=captcha or None)
    await account.get_vehicles()
    print(f"Login correcto. Vehículos: {[v.vin for v in account.vehicles]}")

    auth = account.config.authentication
    payload = {
        "provider": "bmw",
        "access_token": auth.access_token or "",
        "refresh_token": auth.refresh_token,
        "expires_at": auth.expires_at.timestamp() if auth.expires_at else 0,
        "extra": {"gcid": auth.gcid},
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }
    existing = requests.get(
        f"{SUPABASE_URL}/rest/v1/oauth_tokens?provider=eq.bmw&select=provider",
        headers=_headers(),
    )
    if existing.status_code < 300 and existing.json():
        r = requests.patch(f"{SUPABASE_URL}/rest/v1/oauth_tokens?provider=eq.bmw", headers=_headers(), json=payload)
    else:
        r = requests.post(f"{SUPABASE_URL}/rest/v1/oauth_tokens", headers=_headers(), json=payload)
    if r.status_code >= 300:
        sys.exit(f"Error guardando tokens en Supabase ({r.status_code}): {r.text[:300]}\n"
                 "¿Has aplicado la migración 20260706_oauth_tokens_extra.sql?")
    print("Tokens guardados en oauth_tokens (provider='bmw'). El backend ya puede enviar destinos.")


if __name__ == "__main__":
    asyncio.run(main())
