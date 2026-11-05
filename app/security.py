"""Tokens, hashing and encryption of user secrets."""

import hashlib
import secrets

from cryptography.fernet import Fernet, InvalidToken, MultiFernet

from app.config import get_settings


def new_token() -> str:
    return secrets.token_urlsafe(32)


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def normalize_email(email: str) -> str:
    return email.strip().lower()


class EncryptionNotConfigured(RuntimeError):
    pass


def _fernet() -> MultiFernet:
    raw = get_settings().app_encryption_key
    keys = [k.strip() for k in raw.split(",") if k.strip()]
    if not keys:
        raise EncryptionNotConfigured("APP_ENCRYPTION_KEY is not set")
    return MultiFernet([Fernet(k) for k in keys])


def encrypt_secret(plain: str) -> bytes:
    return _fernet().encrypt(plain.encode())


def decrypt_secret(blob: bytes) -> str:
    try:
        return _fernet().decrypt(blob).decode()
    except InvalidToken as e:
        raise EncryptionNotConfigured("cannot decrypt: wrong APP_ENCRYPTION_KEY") from e


def generate_encryption_key() -> str:
    return Fernet.generate_key().decode()
