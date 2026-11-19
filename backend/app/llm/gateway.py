from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.security import decrypt_secret
from app.llm.base import LLMProvider
from app.llm.ollama_provider import OllamaProvider
from app.llm.openai_compatible_provider import OpenAICompatibleProvider
from app.llm.urls import normalize_provider_url
from app.models.provider import ProviderConfiguration


class LLMGateway:
    def __init__(self):
        self.providers = {"ollama": OllamaProvider()}
        self.default_provider = "ollama"

    def get_provider(self, provider_name: str | None = None) -> LLMProvider:
        name = provider_name or self.default_provider
        provider = self.providers.get(name)
        if not provider:
            raise ValueError(f"Provider {name} not found")
        return provider

    def get_configured_provider(
        self, session: Session, provider_id: str, user_id: str, workspace_id: str
    ) -> tuple[LLMProvider, ProviderConfiguration]:
        config = session.scalar(
            select(ProviderConfiguration).where(
                ProviderConfiguration.id == provider_id,
                ProviderConfiguration.user_id == user_id,
                ProviderConfiguration.workspace_id == workspace_id,
                ProviderConfiguration.is_enabled.is_(True),
            )
        )
        if config is None:
            raise ValueError("Model provider configuration was not found")
        base_url = normalize_provider_url(config.provider_type, str(config.base_url))
        if config.provider_type == "ollama":
            provider: LLMProvider = OllamaProvider(base_url)
        elif config.provider_type in {
            "lm_studio",
            "google_gemini",
            "openai_compatible",
        }:
            provider = OpenAICompatibleProvider(
                base_url, decrypt_secret(config.api_key_encrypted)
            )
        else:
            raise ValueError(f"Unsupported provider type: {config.provider_type}")
        return provider, config


gateway = LLMGateway()
