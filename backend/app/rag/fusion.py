from collections.abc import Sequence

from app.rag.base import RetrievalResult, RetrievedChunk


def reciprocal_rank_fusion(
    results: Sequence[RetrievalResult], *, limit: int = 20, k: int = 60
) -> list[RetrievedChunk]:
    """Fuse ranked results from different retrievers without comparing raw scores."""
    if k < 1:
        raise ValueError("RRF k must be positive")
    if limit < 1:
        return []

    scores: dict[str, float] = {}
    chunks: dict[str, RetrievedChunk] = {}
    source_scores: dict[str, dict[str, float]] = {}
    for result in results:
        seen: set[str] = set()
        for rank, chunk in enumerate(result.chunks, start=1):
            key = chunk.id
            if key in seen:
                continue
            seen.add(key)
            scores[key] = scores.get(key, 0.0) + 1.0 / (k + rank)
            chunks.setdefault(key, chunk)
            source_scores.setdefault(key, {})[result.source] = chunk.score

    ranked_ids = sorted(scores, key=lambda key: (-scores[key], key))[:limit]
    return [
        chunks[key].model_copy(
            update={
                "score": scores[key],
                "metadata": {
                    **chunks[key].metadata,
                    "rrf_score": scores[key],
                    "source_scores": source_scores[key],
                },
            }
        )
        for key in ranked_ids
    ]
