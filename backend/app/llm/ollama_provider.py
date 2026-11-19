import json
from collections.abc import AsyncGenerator

import httpx
import structlog

from app.core.config import settings
from app.llm.base import LLMProvider
from app.llm.urls import assert_provider_egress_allowed

logger = structlog.get_logger(__name__)


class OllamaProvider(LLMProvider):
    def __init__(self, base_url: str | None = None):
        self.base_url = (base_url or settings.OLLAMA_BASE_URL).rstrip("/")

    async def list_models(self) -> list[str]:
        await assert_provider_egress_allowed(self.base_url)
        async with httpx.AsyncClient(follow_redirects=False) as client:
            response = await client.get(f"{self.base_url}/api/tags", timeout=10.0)
            response.raise_for_status()
            return sorted(
                str(item["name"])
                for item in response.json().get("models", [])
                if isinstance(item, dict) and item.get("name")
            )

    async def chat(self, messages: list[dict], model: str) -> str:
        await assert_provider_egress_allowed(self.base_url)
        async with httpx.AsyncClient(follow_redirects=False) as client:
            try:
                response = await client.post(
                    f"{self.base_url}/api/chat",
                    json={"model": model, "messages": messages, "stream": False},
                    timeout=30.0,
                )
                response.raise_for_status()
                data = response.json()
                return data["message"]["content"]
            except Exception as e:
                logger.error("ollama_chat_error", error=str(e))
                raise

    async def stream_chat(
        self, messages: list[dict], model: str
    ) -> AsyncGenerator[str, None]:
        await assert_provider_egress_allowed(self.base_url)
        async with httpx.AsyncClient(follow_redirects=False) as client:
            try:
                async with client.stream(
                    "POST",
                    f"{self.base_url}/api/chat",
                    json={"model": model, "messages": messages, "stream": True},
                    timeout=30.0,
                ) as response:
                    response.raise_for_status()
                    async for chunk in response.aiter_lines():
                        if not chunk:
                            continue
                        data = json.loads(chunk)
                        if "message" in data and "content" in data["message"]:
                            yield data["message"]["content"]
            except Exception as e:
                logger.error("ollama_stream_error", error=str(e))
                raise
