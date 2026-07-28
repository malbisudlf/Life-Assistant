"""Genera el par de claves VAPID que necesitan las notificaciones push.

Uso:  python backend/generar_vapid.py

Imprime las tres variables listas para pegar en backend/.env (o en los secrets de Fly).
Las claves identifican a TU servidor ante el servicio de push del navegador: se generan
una vez y no se cambian, porque al cambiarlas todas las suscripciones existentes dejan
de valer y hay que volver a activar las notificaciones en cada dispositivo.
"""
import base64
import sys

try:
    from py_vapid import Vapid01
except ImportError:
    sys.exit("Falta la dependencia: pip install -r backend/requirements.txt")


def _b64(datos: bytes) -> str:
    """base64url sin relleno, que es lo que esperan tanto pywebpush como el navegador."""
    return base64.urlsafe_b64encode(datos).rstrip(b"=").decode("ascii")


def main() -> int:
    vapid = Vapid01()
    vapid.generate_keys()

    from cryptography.hazmat.primitives import serialization

    privada = vapid.private_key.private_bytes(
        encoding=serialization.Encoding.DER,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    )
    publica = vapid.public_key.public_bytes(
        encoding=serialization.Encoding.X962,
        format=serialization.PublicFormat.UncompressedPoint,
    )

    print("# Claves VAPID para notificaciones push — pégalas en backend/.env")
    print("# Guárdalas: si las cambias, todos los dispositivos tendrán que volver a")
    print("# activar las notificaciones.\n")
    print(f"VAPID_PRIVATE_KEY={_b64(privada)}")
    print(f"VAPID_PUBLIC_KEY={_b64(publica)}")
    print("VAPID_SUBJECT=mailto:tu-correo@ejemplo.com   # <- pon tu correo real")
    return 0


if __name__ == "__main__":
    sys.exit(main())
