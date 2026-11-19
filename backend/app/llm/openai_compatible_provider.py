import json
from collections.abc import AsyncGenerator

import httpx
import structlog

from app.llm.base import LLMProvider
from app.llm.urls import assert_provider_egress_allowed

logger = structlog.get_logger(__name__)


class OpenAICompatibleProvider(LLMProvider):
    def __init__(self, base_url: str, api_key: str | None = None):
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key

    def _headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self.api_key}"} if self.api_key else {}

    async def list_models(self) -> list[str]:
        await assert_provider_egress_allowed(self.base_url)
        async with httpx.AsyncClient(follow_redirects=False) as client:
            response = await client.get(
                f"{self.base_url}/models", headers=self._headers(), timeout=10.0
            )
            response.raise_for_status()
            data = response.json().get("data", [])
            return sorted(
                str(item["id"])
                for item in data
                if isinstance(item, dict) and item.get("id")
            )

    async def chat(self, messages: list[dict], model: str) -> str:
        await assert_provider_egress_allowed(self.base_url)
        async with httpx.AsyncClient(follow_redirects=False) as client:
            response = await client.post(
                f"{self.base_url}/chat/completions",
                headers=self._headers(),
                json={"model": model, "messages": messages, "stream": False},
                timeout=60.0,
            )
            response.raise_for_status()
            return str(response.json()["choices"][0]["message"]["content"])

    async def stream_chat(
        self, messages: list[dict], model: str
    ) -> AsyncGenerator[str, None]:
        await assert_provider_egress_allowed(self.base_url)
        async with (
            httpx.AsyncClient(follow_redirects=False) as client,
            client.stream(
                "POST",
                f"{self.base_url}/chat/completions",
                headers=self._headers(),
                json={"model": model, "messages": messages, "stream": True},
                timeout=60.0,
            ) as response,
        ):
            response.raise_for_status()
            async for line in response.aiter_lines():
                if not line.startswith("data:"):
                    continue
                payload = line[5:].strip()
                if not payload or payload == "[DONE]":
                    continue
                data = json.loads(payload)
                content = data.get("choices", [{}])[0].get("delta", {}).get("content")
                if content:
                    yield str(content)
