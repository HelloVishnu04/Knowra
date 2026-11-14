from app.llm.base import LLMProvider
from app.llm.ollama_provider import OllamaProvider


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


gateway = LLMGateway()
