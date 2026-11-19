from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.security import (
    decrypt_secret,
    provider_active_key_id,
    provider_secret_key_id,
    reencrypt_secret,
)
from app.models.audit import AuditEvent
from app.models.provider import ProviderConfiguration


@dataclass(frozen=True)
class ProviderKeyRotationResult:
    rotated: int
    verified_current: int


def rotate_provider_credentials(session: Session) -> ProviderKeyRotationResult:
    """Atomically verify all provider credentials and rewrite non-active versions."""
    active_key_id = provider_active_key_id()
    configurations = session.scalars(
        select(ProviderConfiguration).where(
            ProviderConfiguration.api_key_encrypted.is_not(None)
        )
    ).all()
    replacements: list[tuple[ProviderConfiguration, str, str | None]] = []
    verified_current = 0

    for config in configurations:
        encrypted = str(config.api_key_encrypted)
        current_key_id = provider_secret_key_id(encrypted)
        if current_key_id == active_key_id:
            decrypt_secret(encrypted)
            verified_current += 1
            continue
        replacements.append((config, reencrypt_secret(encrypted), current_key_id))

    for config, encrypted, previous_key_id in replacements:
        config.api_key_encrypted = encrypted
        config.api_key_version = active_key_id
        session.add(
            AuditEvent(
                workspace_id=config.workspace_id,
                actor_user_id=None,
                action="provider.secret_reencrypted",
                resource_type="provider_configuration",
                resource_id=str(config.id),
                details_json={
                    "previous_key_version": previous_key_id,
                    "key_version": active_key_id,
                },
            )
        )
    session.commit()
    return ProviderKeyRotationResult(
        rotated=len(replacements), verified_current=verified_current
    )
