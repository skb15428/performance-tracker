"""Print fresh secrets for a .env file: JWT, Fernet, jobs secret and a VAPID keypair."""

import base64
import secrets

from cryptography.fernet import Fernet
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ec


def b64url(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).decode().rstrip("=")


key = ec.generate_private_key(ec.SECP256R1())
print(f"JWT_SECRET={secrets.token_urlsafe(48)}")
print(f"FERNET_KEY={Fernet.generate_key().decode()}")
print(f"JOBS_SECRET={secrets.token_urlsafe(32)}")
print(f"VAPID_PRIVATE_KEY={b64url(key.private_numbers().private_value.to_bytes(32, 'big'))}")
print(f"VAPID_PUBLIC_KEY="
      f"{b64url(key.public_key().public_bytes(serialization.Encoding.X962, serialization.PublicFormat.UncompressedPoint))}")
