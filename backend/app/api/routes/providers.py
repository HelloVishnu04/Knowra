from typing import Annotated, Literal
from urllib.parse import urlparse

import httpx
from fastapi import APIRouter, Depends, HTTPException, Response
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.audit import record_audit_event
from app.api.dependencies import Principal, require_authenticated_principal
from app.core.database import get_session
from app.core.security import encrypt_secret, provider_active_key_id
from app.llm.gateway import gateway
from app.llm.urls import (
    ProviderEgressError,
    normalize_provider_url,
    validate_provider_url_policy,
)
from app.models.provider import ProviderConfiguration

router = APIRouter()
PrincipalDependency = Annotated[Principal, Depends(require_authenticated_principal)]
ProviderType = Literal["ollama", "lm_studio", "google_gemini", "openai_compatible"]


class ProviderInput(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    provider_type: ProviderType
    base_url: str = Field(min_length=8, max_length=500)
    api_key: str | None = Field(default=None, max_length=1000)
    models: list[str] = Field(default_factory=list, max_length=100)
    is_enabled: bool = True

    @field_validator("base_url")
    @classmethod
    def validate_base_url(cls, value: str) -> str:
        parsed = urlparse(value.strip())
        if parsed.scheme not in {"http", "https"} or not parsed.hostname:
            raise ValueError("Base URL must be a valid HTTP or HTTPS URL")
        if parsed.username or parsed.password:
            raise ValueError("Credentials must not be included in the base URL")
        return value.strip().rstrip("/")

    @field_validator("models")
    @classmethod
    def normalize_models(cls, values: list[str]) -> list[str]:
        return sorted({value.strip() for value in values if value.strip()})


class ProviderUpdate(ProviderInput):
    api_key: str | None = None


def serialize(config: ProviderConfiguration) -> dict:
    return {
        "id": config.id,
        "name": config.name,
        "provider_type": config.provider_type,
        "base_url": config.base_url,
        "has_api_key": bool(config.api_key_encrypted),
        "api_key_version": config.api_key_version,
        "models": config.models_json or [],
        "is_enabled": config.is_enabled,
        "created_at": config.created_at,
        "updated_at": config.updated_at,
    }


def validated_provider_url(provider_type: str, base_url: str) -> str:
    normalized = normalize_provider_url(provider_type, base_url)
    try:
        validate_provider_url_policy(normalized)
    except ProviderEgressError as exc:
        raise HTTPException(422, str(exc)) from exc
    return normalized


@router.get("/providers")
def list_providers(
    principal: PrincipalDependency,
    session: Annotated[Session, Depends(get_session)],
) -> list[dict]:
    configs = session.scalars(
        select(ProviderConfiguration)
        .where(
            ProviderConfiguration.user_id == principal.user_id,
            ProviderConfiguration.workspace_id == principal.workspace_id,
        )
        .order_by(ProviderConfiguration.created_at)
    ).all()
    return [serialize(config) for config in configs]


@router.post("/providers", status_code=201)
def create_provider(
    payload: ProviderInput,
    principal: PrincipalDependency,
    session: Annotated[Session, Depends(get_session)],
) -> dict:
    if payload.provider_type == "google_gemini" and not payload.api_key:
        raise HTTPException(422, "A Google Gemini API key is required")
    config = ProviderConfiguration(
        workspace_id=principal.workspace_id,
        user_id=principal.user_id,
        name=payload.name.strip(),
        provider_type=payload.provider_type,
        base_url=validated_provider_url(payload.provider_type, payload.base_url),
        api_key_encrypted=encrypt_secret(payload.api_key) if payload.api_key else None,
        api_key_version=provider_active_key_id() if payload.api_key else None,
        models_json=payload.models,
        is_enabled=payload.is_enabled,
    )
    session.add(config)
    session.flush()
    record_audit_event(
        session,
        principal,
        action="provider.created",
        resource_type="provider_configuration",
        resource_id=str(config.id),
        details={
            "name": config.name,
            "provider_type": config.provider_type,
            "has_api_key": bool(config.api_key_encrypted),
        },
    )
    session.commit()
    session.refresh(config)
    return serialize(config)


def owned_provider(
    session: Session, provider_id: str, user_id: str, workspace_id: str
) -> ProviderConfiguration:
    config = session.scalar(
        select(ProviderConfiguration).where(
            ProviderConfiguration.id == provider_id,
            ProviderConfiguration.user_id == user_id,
            ProviderConfiguration.workspace_id == workspace_id,
        )
    )
    if config is None:
        raise HTTPException(404, "Provider configuration not found")
    return config


@router.put("/providers/{provider_id}")
def update_provider(
    provider_id: str,
    payload: ProviderUpdate,
    principal: PrincipalDependency,
    session: Annotated[Session, Depends(get_session)],
) -> dict:
    config = owned_provider(
        session, provider_id, str(principal.user_id), principal.workspace_id
    )
    if (
        payload.provider_type == "google_gemini"
        and not payload.api_key
        and not config.api_key_encrypted
    ):
        raise HTTPException(422, "A Google Gemini API key is required")
    config.name = payload.name.strip()
    config.provider_type = payload.provider_type
    config.base_url = validated_provider_url(payload.provider_type, payload.base_url)
    config.models_json = payload.models
    config.is_enabled = payload.is_enabled
    if payload.api_key:
        config.api_key_encrypted = encrypt_secret(payload.api_key)
        config.api_key_version = provider_active_key_id()
        record_audit_event(
            session,
            principal,
            action="provider.secret_replaced",
            resource_type="provider_configuration",
            resource_id=str(config.id),
            details={"key_version": config.api_key_version},
        )
    record_audit_event(
        session,
        principal,
        action="provider.updated",
        resource_type="provider_configuration",
        resource_id=str(config.id),
        details={
            "name": config.name,
            "provider_type": config.provider_type,
            "has_api_key": bool(config.api_key_encrypted),
            "is_enabled": config.is_enabled,
        },
    )
    session.commit()
    session.refresh(config)
    return serialize(config)


@router.delete("/providers/{provider_id}", status_code=204)
def delete_provider(
    provider_id: str,
    principal: PrincipalDependency,
    session: Annotated[Session, Depends(get_session)],
) -> Response:
    config = owned_provider(
        session, provider_id, str(principal.user_id), principal.workspace_id
    )
    record_audit_event(
        session,
        principal,
        action="provider.deleted",
        resource_type="provider_configuration",
        resource_id=str(config.id),
        details={"name": config.name, "provider_type": config.provider_type},
    )
    session.delete(config)
    session.commit()
    return Response(status_code=204)


async def discover(
    config: ProviderConfiguration, session: Session, principal: Principal
) -> list[str]:
    try:
        provider, _ = gateway.get_configured_provider(
            session,
            str(config.id),
            str(principal.user_id),
            principal.workspace_id,
        )
        list_models = getattr(provider, "list_models", None)
        if list_models is None:
            raise ValueError("This provider does not support model discovery")
        return await list_models()
    except ProviderEgressError as exc:
        raise HTTPException(403, str(exc)) from exc
    except httpx.ConnectError as exc:
        hint = (
            "LM Studio must have its local server running. Knowra automatically uses "
            "host.docker.internal and the /v1 API path."
            if config.provider_type == "lm_studio"
            else "Check that the provider URL is reachable from the Knowra container."
        )
        raise HTTPException(502, f"Provider connection refused. {hint}") from exc
    except httpx.TimeoutException as exc:
        raise HTTPException(
            504, "The provider did not respond before the timeout"
        ) from exc
    except httpx.HTTPStatusError as exc:
        status = exc.response.status_code
        raise HTTPException(
            502,
            f"Provider returned HTTP {status}. Check the API key, URL, and model access.",
        ) from exc
    except (ValueError, KeyError) as exc:
        raise HTTPException(502, f"Provider response was invalid: {exc}") from exc


@router.post("/providers/{provider_id}/discover")
async def discover_models(
    provider_id: str,
    principal: PrincipalDependency,
    session: Annotated[Session, Depends(get_session)],
) -> dict:
    config = owned_provider(
        session, provider_id, str(principal.user_id), principal.workspace_id
    )
    models = await discover(config, session, principal)
    config.models_json = sorted(set((config.models_json or []) + models))
    session.commit()
    return {"models": config.models_json}


@router.post("/providers/{provider_id}/test")
async def test_provider(
    provider_id: str,
    principal: PrincipalDependency,
    session: Annotated[Session, Depends(get_session)],
) -> dict:
    config = owned_provider(
        session, provider_id, str(principal.user_id), principal.workspace_id
    )
    models = await discover(config, session, principal)
    return {"status": "ok", "models_found": len(models), "models": models}
