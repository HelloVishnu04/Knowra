from abc import ABC, abstractmethod
from typing import Any

from pydantic import BaseModel, Field


class RetrievedChunk(BaseModel):
    id: str
    content: str
    source: str
    score: float
    metadata: dict[str, Any] = Field(default_factory=dict)


class RetrievalResult(BaseModel):
    source: str
    query: str
    chunks: list[RetrievedChunk]
    latency_ms: int


class Retriever(ABC):
    @abstractmethod
    async def retrieve(
        self,
        query: str,
        *,
        workspace_id: str,
        top_k: int = 20,
        filters: dict[str, Any] | None = None,
    ) -> RetrievalResult: ...
