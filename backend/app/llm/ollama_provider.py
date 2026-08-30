import json
import httpx
from typing import AsyncGenerator
from app.llm.base import LLMProvider
from app.core.config import settings
import structlog

logger = structlog.get_logger(__name__)

class OllamaProvider(LLMProvider):
    def __init__(self):
        self.base_url = settings.OLLAMA_BASE_URL

    async def chat(self, messages: list[dict], model: str) -> str:
        async with httpx.AsyncClient() as client:
            try:
                response = await client.post(
                    f"{self.base_url}/api/chat",
                    json={"model": model, "messages": messages, "stream": False},
                    timeout=30.0
                )
                response.raise_for_status()
                data = response.json()
                return data["message"]["content"]
            except Exception as e:
                logger.error("ollama_chat_error", error=str(e))
                raise e

    async def stream_chat(self, messages: list[dict], model: str) -> AsyncGenerator[str, None]:
        async with httpx.AsyncClient() as client:
            try:
                async with client.stream(
                    "POST",
                    f"{self.base_url}/api/chat",
                    json={"model": model, "messages": messages, "stream": True},
                    timeout=30.0
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
                raise e
