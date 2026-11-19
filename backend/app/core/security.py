import base64
import hashlib
import hmac
import json
import os
import time
from typing import Any

from cryptography.fernet import Fernet, InvalidToken

from app.core.config import settings

PASSWORD_ITERATIONS = 600_000


def _b64encode(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).rstrip(b"=").decode("ascii")


def _b64decode(value: str) -> bytes:
    return base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))


def hash_password(password: str) -> str:
    salt = os.urandom(16)
    digest = hashlib.pbkdf2_hmac(
        "sha256", password.encode("utf-8"), salt, PASSWORD_ITERATIONS
    )
    return (
        f"pbkdf2_sha256${PASSWORD_ITERATIONS}${_b64encode(salt)}${_b64encode(digest)}"
    )


def verify_password(password: str, encoded: str) -> bool:
    try:
        algorithm, iterations, salt, expected = encoded.split("$", 3)
        if algorithm != "pbkdf2_sha256":
            return False
        digest = hashlib.pbkdf2_hmac(
            "sha256",
            password.encode("utf-8"),
            _b64decode(salt),
            int(iterations),
        )
        return hmac.compare_digest(_b64encode(digest), expected)
    except (TypeError, ValueError):
        return False


def create_access_token(user_id: str, session_id: str | None = None) -> str:
    now = int(time.time())
    header = _b64encode(
        json.dumps(
            {"alg": settings.JWT_ALGORITHM, "typ": "JWT"}, separators=(",", ":")
        ).encode()
    )
    claims: dict[str, Any] = {
        "sub": user_id,
        "iat": now,
        "exp": now + settings.ACCESS_TOKEN_EXPIRE_MINUTES * 60,
    }
    if session_id:
        claims["sid"] = session_id
    payload = _b64encode(
        json.dumps(
            claims,
            separators=(",", ":"),
        ).encode()
    )
    unsigned = f"{header}.{payload}"
    signature = hmac.new(
        settings.JWT_SECRET.encode(), unsigned.encode(), hashlib.sha256
    ).digest()
    return f"{unsigned}.{_b64encode(signature)}"


def decode_access_token(token: str) -> dict[str, Any]:
    try:
        header, payload, signature = token.split(".", 2)
        unsigned = f"{header}.{payload}"
        expected = hmac.new(
            settings.JWT_SECRET.encode(), unsigned.encode(), hashlib.sha256
        ).digest()
        if not hmac.compare_digest(expected, _b64decode(signature)):
            raise ValueError("Invalid token signature")
        header_data = json.loads(_b64decode(header))
        data = json.loads(_b64decode(payload))
        if header_data.get("alg") != settings.JWT_ALGORITHM:
            raise ValueError("Invalid token algorithm")
        if int(data.get("exp", 0)) <= int(time.time()):
            raise ValueError("Token expired")
        if not data.get("sub"):
            raise ValueError("Token subject is missing")
        return data
    except (ValueError, TypeError, json.JSONDecodeError) as exc:
        raise ValueError("Invalid or expired token") from exc


def encrypt_secret(value: str) -> str:
    key_id = provider_active_key_id()
    token = _provider_fernet(key_id).encrypt(value.encode()).decode()
    return f"knowra-secret:{key_id}:{token}"


def decrypt_secret(value: str | None) -> str | None:
    if not value:
        return None
    try:
        if value.startswith("knowra-secret:"):
            _, key_id, token = value.split(":", 2)
            return _provider_fernet(key_id).decrypt(token.encode()).decode()
        if not settings.PROVIDER_ALLOW_LEGACY_JWT_KEY:
            raise ValueError("Legacy provider credential encryption is disabled")
        return _legacy_fernet().decrypt(value.encode()).decode()
    except (InvalidToken, KeyError) as exc:
        raise ValueError("Stored credential cannot be decrypted") from exc


def reencrypt_secret(value: str) -> str:
    plaintext = decrypt_secret(value)
    if plaintext is None:
        raise ValueError("Stored credential is empty")
    encrypted = encrypt_secret(plaintext)
    if decrypt_secret(encrypted) != plaintext:
        raise ValueError("Re-encrypted credential verification failed")
    return encrypted


def provider_active_key_id() -> str:
    return settings.PROVIDER_ENCRYPTION_ACTIVE_KEY_ID


def provider_secret_key_id(value: str | None) -> str | None:
    if not value:
        return None
    if value.startswith("knowra-secret:"):
        try:
            return value.split(":", 2)[1]
        except IndexError:
            return None
    return "legacy-jwt-v0"


def _provider_keyring() -> dict[str, str]:
    if settings.PROVIDER_ENCRYPTION_KEYS.strip():
        try:
            keyring = json.loads(settings.PROVIDER_ENCRYPTION_KEYS)
        except json.JSONDecodeError as exc:
            raise ValueError("Provider encryption keyring is invalid") from exc
        if not isinstance(keyring, dict):
            raise ValueError("Provider encryption keyring must be an object")
        return {str(key): str(value) for key, value in keyring.items()}
    development_key = base64.urlsafe_b64encode(
        hashlib.sha256(f"provider:{settings.JWT_SECRET}".encode()).digest()
    ).decode()
    return {provider_active_key_id(): development_key}


def _provider_fernet(key_id: str) -> Fernet:
    try:
        return Fernet(_provider_keyring()[key_id].encode())
    except (KeyError, ValueError) as exc:
        raise ValueError(f"Provider encryption key {key_id!r} is unavailable") from exc


def _legacy_fernet() -> Fernet:
    key = base64.urlsafe_b64encode(
        hashlib.sha256(settings.JWT_SECRET.encode()).digest()
    )
    return Fernet(key)
