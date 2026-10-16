from cryptography.fernet import Fernet, InvalidToken

from app.core.config import get_settings


def _fernet() -> Fernet | None:
    key = get_settings().fernet_key
    return Fernet(key.encode()) if key else None


def encrypt(value: str) -> str:
    f = _fernet()
    if f is None:
        raise RuntimeError("FERNET_KEY is not configured; cannot store secrets")
    return f.encrypt(value.encode()).decode()


def decrypt(token: str | None) -> str | None:
    f = _fernet()
    if not token or f is None:
        return None
    try:
        return f.decrypt(token.encode()).decode()
    except InvalidToken:
        return None
