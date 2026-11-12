import logging
import time
from typing import Any, cast

import httpx
from qdrant_client import AsyncQdrantClient, models

from app.core.config import settings
from app.core.database import SessionLocal
from app.models.knowledge import Document, DocumentChunk, KnowledgeBase
from app.rag.base import RetrievalResult, RetrievedChunk, Retriever
from app.rag.rerank import rerank

logger = logging.getLogger(__name__)


async def embed(texts: list[str]) -> list[list[float]]:
    async with httpx.AsyncClient(timeout=120) as client:
        response = await client.post(
            f"{settings.OLLAMA_BASE_URL}/api/embed",
            json={
                "model": settings.EMBEDDING_MODEL,
                "input": texts,
                "truncate": False,
            },
        )
        response.raise_for_status()
        vectors = cast(list[list[float]], response.json()["embeddings"])
        if len(vectors) != len(texts) or not vectors or not vectors[0]:
            raise ValueError("Invalid embedding response")
        return vectors


def scope_filter(workspace_id: str, kb_id: str) -> models.Filter:
    return models.Filter(
        must=[
            models.FieldCondition(
                key="workspace_id", match=models.MatchValue(value=workspace_id)
            ),
            models.FieldCondition(
                key="knowledge_base_id", match=models.MatchValue(value=kb_id)
            ),
            models.FieldCondition(
                key="embedding_model",
                match=models.MatchValue(value=settings.EMBEDDING_MODEL),
            ),
            models.FieldCondition(
                key="sparse_model",
                match=models.MatchValue(value=settings.SPARSE_MODEL),
            ),
        ]
    )


class DocumentRetriever(Retriever):
    async def retrieve(
        self,
        query: str,
        *,
        workspace_id: str,
        top_k: int = 20,
        filters: dict[str, Any] | None = None,
    ) -> RetrievalResult:
        started = time.monotonic()
        kb_id = (filters or {}).get("knowledge_base_id")
        if not workspace_id or not kb_id:
            raise ValueError("Workspace and knowledge base are required")
        with SessionLocal() as session:
            kb = session.get(KnowledgeBase, kb_id)
            if kb is None or kb.workspace_id != workspace_id:
                raise ValueError("Knowledge base not found")
        retrieval_mode = (filters or {}).get(
            "retrieval_mode",
            "hybrid" if settings.HYBRID_RETRIEVAL_ENABLED else "dense",
        )
        if retrieval_mode not in {"dense", "hybrid"}:
            raise ValueError("retrieval_mode must be dense or hybrid")
        use_reranker = bool((filters or {}).get("rerank", settings.RERANKER_ENABLED))
        result_limit = min(max(top_k, 1), 20)
        candidate_limit = min(
            max(result_limit, settings.RETRIEVAL_CANDIDATE_LIMIT), 100
        )
        client = AsyncQdrantClient(url=settings.QDRANT_URL)
        try:
            if not await client.collection_exists(settings.QDRANT_COLLECTION):
                return RetrievalResult(
                    source="document", query=query, chunks=[], latency_ms=0
                )
            vector = (await embed([query]))[0]
            query_filter = scope_filter(workspace_id, kb_id)
            if retrieval_mode == "hybrid":
                result = await client.query_points(
                    collection_name=settings.QDRANT_COLLECTION,
                    prefetch=[
                        models.Prefetch(
                            query=vector,
                            using="dense",
                            filter=query_filter,
                            limit=candidate_limit,
                        ),
                        models.Prefetch(
                            query=models.Document(
                                text=query, model=settings.SPARSE_MODEL
                            ),
                            using="sparse",
                            filter=query_filter,
                            limit=candidate_limit,
                        ),
                    ],
                    query=models.FusionQuery(fusion=models.Fusion.RRF),
                    query_filter=query_filter,
                    limit=candidate_limit,
                    with_payload=False,
                )
            else:
                result = await client.query_points(
                    collection_name=settings.QDRANT_COLLECTION,
                    query=vector,
                    using="dense",
                    query_filter=query_filter,
                    limit=candidate_limit,
                    with_payload=False,
                )

            point_scores = {
                str(point.id): float(point.score) for point in result.points
            }
            chunks: list[RetrievedChunk] = []
            with SessionLocal() as session:
                # SQL is authoritative: never expose stale or partially indexed chunks.
                rows = (
                    session.query(DocumentChunk, Document)
                    .join(Document, Document.id == DocumentChunk.document_id)
                    .join(KnowledgeBase, KnowledgeBase.id == Document.knowledge_base_id)
                    .filter(
                        DocumentChunk.id.in_(point_scores),
                        Document.status == "ready",
                        KnowledgeBase.id == kb_id,
                        KnowledgeBase.workspace_id == workspace_id,
                    )
                    .all()
                )
                rows_by_id = {chunk.id: (chunk, doc) for chunk, doc in rows}
                for point in result.points:
                    row = rows_by_id.get(str(point.id))
                    if row is None:
                        continue
                    chunk, doc = row
                    chunks.append(
                        RetrievedChunk(
                            id=chunk.id,
                            content=chunk.content,
                            source="document",
                            score=point_scores[chunk.id],
                            metadata={
                                **chunk.metadata_json,
                                "document_id": doc.id,
                                "document_name": doc.name,
                                "retrieval_mode": retrieval_mode,
                            },
                        )
                    )

            if use_reranker and chunks:
                rerank_limit = min(
                    len(chunks), max(1, settings.RERANKER_CANDIDATE_LIMIT)
                )
                shortlist, remainder = chunks[:rerank_limit], chunks[rerank_limit:]
                try:
                    scores = await rerank(
                        query,
                        [chunk.content for chunk in shortlist],
                        model_name=settings.RERANKER_MODEL,
                    )
                    if len(scores) != len(shortlist):
                        raise ValueError("Reranker returned an invalid score count")
                    reranked = sorted(
                        zip(shortlist, scores, strict=True),
                        key=lambda item: item[1],
                        reverse=True,
                    )
                    chunks = [
                        chunk.model_copy(
                            update={
                                "score": score,
                                "metadata": {
                                    **chunk.metadata,
                                    "retrieval_score": chunk.score,
                                    "reranker_model": settings.RERANKER_MODEL,
                                },
                            }
                        )
                        for chunk, score in reranked
                    ] + remainder
                except Exception:
                    logger.exception(
                        "Reranking failed; returning fused retrieval order"
                    )
            return RetrievalResult(
                source="document",
                query=query,
                chunks=chunks[:result_limit],
                latency_ms=int((time.monotonic() - started) * 1000),
            )
        finally:
            await client.close()
