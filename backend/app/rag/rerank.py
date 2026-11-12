import asyncio
from functools import lru_cache
from typing import Any


@lru_cache(maxsize=4)
def _cross_encoder(model_name: str) -> Any:
    from fastembed.rerank.cross_encoder import TextCrossEncoder

    return TextCrossEncoder(model_name=model_name)


def _score(model_name: str, query: str, documents: list[str]) -> list[float]:
    model = _cross_encoder(model_name)
    return [float(score) for score in model.rerank(query, documents)]


async def rerank(query: str, documents: list[str], *, model_name: str) -> list[float]:
    """Score a bounded candidate list with a local cross-encoder."""
    if not documents:
        return []
    return await asyncio.to_thread(_score, model_name, query, documents)
