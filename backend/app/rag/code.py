import time
from typing import Any

from qdrant_client import AsyncQdrantClient, models

from app.core.config import settings
from app.core.database import SessionLocal
from app.models.code import CodeSymbol, Repository
from app.rag.base import RetrievalResult, RetrievedChunk, Retriever
from app.rag.documents import embed


def code_scope_filter(
    workspace_id: str, repository_id: str, generation: str | None = None
) -> models.Filter:
    scope = models.Filter(
        must=[
            models.FieldCondition(
                key="workspace_id", match=models.MatchValue(value=workspace_id)
            ),
            models.FieldCondition(
                key="repository_id", match=models.MatchValue(value=repository_id)
            ),
            models.FieldCondition(
                key="embedding_model",
                match=models.MatchValue(value=settings.EMBEDDING_MODEL),
            ),
            models.FieldCondition(
                key="sparse_model", match=models.MatchValue(value=settings.SPARSE_MODEL)
            ),
        ]
    )
    if generation:
        scope.must.append(
            models.FieldCondition(
                key="generation", match=models.MatchValue(value=generation)
            )
        )
    return scope


class CodeRetriever(Retriever):
    async def retrieve(
        self,
        query: str,
        *,
        workspace_id: str,
        top_k: int = 20,
        filters: dict[str, Any] | None = None,
    ) -> RetrievalResult:
        started = time.monotonic()
        repository_id = str((filters or {}).get("repository_id", ""))
        if not workspace_id or not repository_id:
            raise ValueError("Workspace and repository are required")
        with SessionLocal() as session:
            repository = session.get(Repository, repository_id)
            if (
                repository is None
                or repository.workspace_id != workspace_id
                or repository.status != "ready"
            ):
                raise ValueError("Indexed repository not found")
            generation = (repository.metadata_json or {}).get("index_generation")

        limit = min(max(top_k, 1), 20)
        candidates = min(max(limit, settings.RETRIEVAL_CANDIDATE_LIMIT), 100)
        client = AsyncQdrantClient(url=settings.QDRANT_URL)
        try:
            if not await client.collection_exists(settings.CODE_COLLECTION):
                return RetrievalResult(
                    source="code", query=query, chunks=[], latency_ms=0
                )
            vector = (await embed([query]))[0]
            scope = code_scope_filter(workspace_id, repository_id, generation)
            result = await client.query_points(
                collection_name=settings.CODE_COLLECTION,
                prefetch=[
                    models.Prefetch(
                        query=vector,
                        using="dense",
                        filter=scope,
                        limit=candidates,
                    ),
                    models.Prefetch(
                        query=models.Document(text=query, model=settings.SPARSE_MODEL),
                        using="sparse",
                        filter=scope,
                        limit=candidates,
                    ),
                ],
                query=models.FusionQuery(fusion=models.Fusion.RRF),
                query_filter=scope,
                limit=limit,
                with_payload=True,
            )

            def symbol_id(point):
                return str(
                    (getattr(point, "payload", None) or {}).get("symbol_id", point.id)
                )

            scores = {symbol_id(point): float(point.score) for point in result.points}
            with SessionLocal() as session:
                rows = (
                    session.query(CodeSymbol)
                    .filter(
                        CodeSymbol.id.in_(scores),
                        CodeSymbol.repository_id == repository_id,
                        CodeSymbol.workspace_id == workspace_id,
                    )
                    .all()
                )
                by_id = {item.id: item for item in rows}
                chunks = []
                for point in result.points:
                    symbol = by_id.get(symbol_id(point))
                    if symbol is None:
                        continue
                    chunks.append(
                        RetrievedChunk(
                            id=symbol.id,
                            content="\n".join(
                                value
                                for value in (
                                    symbol.signature,
                                    symbol.docstring,
                                    symbol.source_text[:8000],
                                )
                                if value
                            ),
                            source="code",
                            score=scores[symbol.id],
                            metadata={
                                "repository_id": repository_id,
                                "symbol": symbol.name,
                                "qualified_name": symbol.qualified_name,
                                "kind": symbol.kind,
                                "language": symbol.language,
                                "file_path": symbol.file_path,
                                "start_line": symbol.start_line,
                                "end_line": symbol.end_line,
                                "label": (
                                    f"{symbol.file_path}:{symbol.start_line}-"
                                    f"{symbol.end_line}"
                                ),
                            },
                        )
                    )
            return RetrievalResult(
                source="code",
                query=query,
                chunks=chunks,
                latency_ms=int((time.monotonic() - started) * 1000),
            )
        finally:
            await client.close()
