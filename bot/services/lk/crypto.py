"""Шифрование паролей от ЛК (Fernet: AES-128-CBC + HMAC). Ключ — ENCRYPTION_KEY в .env, хранится отдельно от БД."""

from cryptography.fernet import Fernet, InvalidToken

from bot.config import settings


class CryptoError(Exception):
    pass


def _fernet() -> Fernet:
    if settings.encryption_key is None:
        raise CryptoError("ENCRYPTION_KEY не задан в .env")
    return Fernet(settings.encryption_key.get_secret_value().encode())


def encrypt(plain: str) -> str:
    return _fernet().encrypt(plain.encode()).decode()


def decrypt(token: str) -> str:
    try:
        return _fernet().decrypt(token.encode()).decode()
    except InvalidToken as e:
        raise CryptoError("не удалось расшифровать пароль — сменился ENCRYPTION_KEY?") from e
