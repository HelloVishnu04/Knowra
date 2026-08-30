from abc import ABC, abstractmethod
from typing import AsyncGenerator

class LLMProvider(ABC):
    @abstractmethod
    async def chat(self, messages: list[dict], model: str) -> str:
        """Non-streaming chat generation."""
        pass

    @abstractmethod
    async def stream_chat(self, messages: list[dict], model: str) -> AsyncGenerator[str, None]:
        """Streaming chat generation."""
        pass
