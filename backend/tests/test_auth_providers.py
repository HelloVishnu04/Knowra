import asyncio
import base64
import hashlib
import json
import socket

import pytest
from cryptography.fernet import Fernet

from app.core.config import Settings, settings
from app.core.security import (
    create_access_token,
    decode_access_token,
    decrypt_secret,
    encrypt_secret,
    hash_password,
    provider_secret_key_id,
    reencrypt_secret,
    verify_password,
)
from app.llm.urls import (
    ProviderEgressError,
    assert_provider_egress_allowed,
    normalize_provider_url,
    validate_provider_url_policy,
)


def test_password_hash_round_trip():
    encoded = hash_password("StrongPassword123!")

    assert encoded != "StrongPassword123!"
    assert verify_password("StrongPassword123!", encoded)
    assert not verify_password("wrong-password", encoded)


def test_access_token_round_trip():
    token = create_access_token("user-123", "session-456")

    assert decode_access_token(token)["sub"] == "user-123"
    assert decode_access_token(token)["sid"] == "session-456"
    with pytest.raises(ValueError, match="Invalid or expired token"):
        decode_access_token(token + "tampered")


def test_provider_secret_encryption_round_trip():
    encrypted = encrypt_secret("provider-api-key")

    assert encrypted != "provider-api-key"
    assert "provider-api-key" not in encrypted
    assert (
        provider_secret_key_id(encrypted) == settings.PROVIDER_ENCRYPTION_ACTIVE_KEY_ID
    )
    assert decrypt_secret(encrypted) == "provider-api-key"


def test_provider_secret_keyring_reads_old_and_writes_active(monkeypatch):
    old_key = Fernet.generate_key().decode()
    new_key = Fernet.generate_key().decode()
    keyring = json.dumps({"old-v1": old_key, "new-v2": new_key})
    monkeypatch.setattr(settings, "PROVIDER_ENCRYPTION_KEYS", keyring)
    monkeypatch.setattr(settings, "PROVIDER_ENCRYPTION_ACTIVE_KEY_ID", "old-v1")
    old_ciphertext = encrypt_secret("rotating-secret")

    monkeypatch.setattr(settings, "PROVIDER_ENCRYPTION_ACTIVE_KEY_ID", "new-v2")
    assert decrypt_secret(old_ciphertext) == "rotating-secret"
    new_ciphertext = reencrypt_secret(old_ciphertext)
    assert provider_secret_key_id(new_ciphertext) == "new-v2"
    assert decrypt_secret(new_ciphertext) == "rotating-secret"

    monkeypatch.setattr(
        settings, "PROVIDER_ENCRYPTION_KEYS", json.dumps({"new-v2": new_key})
    )
    assert decrypt_secret(new_ciphertext) == "rotating-secret"
    with pytest.raises(ValueError, match="unavailable"):
        decrypt_secret(old_ciphertext)


def test_legacy_provider_secret_can_be_read_until_disabled(monkeypatch):
    legacy_key = base64.urlsafe_b64encode(
        hashlib.sha256(settings.JWT_SECRET.encode()).digest()
    )
    legacy_ciphertext = Fernet(legacy_key).encrypt(b"legacy-secret").decode()

    assert provider_secret_key_id(legacy_ciphertext) == "legacy-jwt-v0"
    assert decrypt_secret(legacy_ciphertext) == "legacy-secret"
    monkeypatch.setattr(settings, "PROVIDER_ALLOW_LEGACY_JWT_KEY", False)
    with pytest.raises(ValueError, match="Legacy provider credential"):
        decrypt_secret(legacy_ciphertext)


def test_lm_studio_url_is_normalized_for_docker():
    assert normalize_provider_url("lm_studio", "http://127.0.0.1:1234") == (
        "http://host.docker.internal:1234/v1"
    )
    assert (
        normalize_provider_url("lm_studio", "http://host.docker.internal:1234/v1")
        == "http://host.docker.internal:1234/v1"
    )


def test_google_gemini_uses_official_compatible_endpoint():
    assert normalize_provider_url("google_gemini", "https://example.invalid") == (
        "https://generativelanguage.googleapis.com/v1beta/openai"
    )


@pytest.mark.parametrize(
    "url",
    [
        "http://127.0.0.1:11434",
        "http://10.0.0.8/v1",
        "http://169.254.169.254/latest/meta-data",
        "http://[::1]:11434",
        "http://localhost:11434",
    ],
)
def test_provider_policy_rejects_private_and_local_destinations(url):
    with pytest.raises(ProviderEgressError, match="private or local"):
        validate_provider_url_policy(url, block_private=True)


def test_provider_policy_supports_explicit_private_host_allowlist():
    validate_provider_url_policy(
        "http://host.docker.internal:11434",
        block_private=True,
        allowed_private_hosts={"host.docker.internal"},
    )


def test_provider_policy_allows_public_ip_literal():
    validate_provider_url_policy("https://8.8.8.8/v1", block_private=True)


def test_provider_policy_rejects_private_dns_resolution(monkeypatch):
    monkeypatch.setattr(settings, "PROVIDER_BLOCK_PRIVATE_NETWORKS", True)
    monkeypatch.setattr(settings, "PROVIDER_PRIVATE_HOST_ALLOWLIST", "")
    monkeypatch.setattr(
        socket,
        "getaddrinfo",
        lambda *args, **kwargs: [
            (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("169.254.169.254", 443))
        ],
    )

    with pytest.raises(ProviderEgressError, match="resolves to a private"):
        asyncio.run(assert_provider_egress_allowed("https://models.example/v1"))


def test_provider_policy_allows_public_dns_resolution(monkeypatch):
    monkeypatch.setattr(settings, "PROVIDER_BLOCK_PRIVATE_NETWORKS", True)
    monkeypatch.setattr(settings, "PROVIDER_PRIVATE_HOST_ALLOWLIST", "")
    monkeypatch.setattr(
        socket,
        "getaddrinfo",
        lambda *args, **kwargs: [
            (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", 443))
        ],
    )

    asyncio.run(assert_provider_egress_allowed("https://models.example/v1"))


def test_production_rejects_weak_authentication_configuration():
    with pytest.raises(ValueError, match="Production JWT_SECRET"):
        Settings(
            _env_file=None,
            APP_ENVIRONMENT="production",
            JWT_SECRET="changeme",
            AUTH_REQUIRED=True,
            AUTH_COOKIE_SECURE=True,
        )
    with pytest.raises(ValueError, match="AUTH_REQUIRED"):
        Settings(
            _env_file=None,
            APP_ENVIRONMENT="production",
            JWT_SECRET="a-production-secret-that-is-long-enough",
            AUTH_REQUIRED=False,
            AUTH_COOKIE_SECURE=True,
        )
    configured = Settings(
        _env_file=None,
        APP_ENVIRONMENT="production",
        JWT_SECRET="a-production-secret-that-is-long-enough",
        AUTH_REQUIRED=True,
        AUTH_COOKIE_SECURE=True,
        PROVIDER_BLOCK_PRIVATE_NETWORKS=True,
        PROVIDER_ENCRYPTION_ACTIVE_KEY_ID="prod-v1",
        PROVIDER_ENCRYPTION_KEYS=(
            '{"prod-v1":"MDAwMDAwMDAwMDAwMDAwMDAwMDAwMDAwMDAwMDAwMDA="}'
        ),
    )
    assert configured.APP_ENVIRONMENT == "production"


def test_production_requires_provider_private_network_blocking():
    with pytest.raises(ValueError, match="PROVIDER_BLOCK_PRIVATE_NETWORKS"):
        Settings(
            _env_file=None,
            APP_ENVIRONMENT="production",
            JWT_SECRET="a-production-secret-that-is-long-enough",
            AUTH_REQUIRED=True,
            AUTH_COOKIE_SECURE=True,
            PROVIDER_BLOCK_PRIVATE_NETWORKS=False,
        )
