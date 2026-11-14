import asyncio
import hashlib
import subprocess
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import structlog
from qdrant_client import AsyncQdrantClient, models

from app.code.parser import ParsedReference, ParsedSymbol, parse_source
from app.code.sources import (
    clone_git,
    extract_zip,
    iter_source_files,
    validate_local_path,
)
from app.core.config import settings
from app.core.database import SessionLocal
from app.models.code import CodeReference, CodeSymbol, Repository
from app.rag.documents import embed

logger = structlog.get_logger(__name__)


def _set_status(
    repository_id: str,
    status: str,
    *,
    error: str | None = None,
    metadata: dict[str, Any] | None = None,
) -> None:
    with SessionLocal.begin() as session:
        repository = session.get(Repository, repository_id)
        if repository is None:
            return
        repository.status = status
        repository.error = error
        if metadata is not None:
            repository.metadata_json = metadata
        if status == "ready":
            repository.indexed_at = datetime.now(UTC)


def _prepare_worktree(repository: Repository) -> Path:
    root = Path(repository.root_path)
    if repository.source_type == "zip":
        archive = Path((repository.metadata_json or {}).get("archive_path", ""))
        if not archive.is_file():
            raise ValueError("Repository ZIP is missing")
        extract_zip(archive, root)
    elif repository.source_type == "git":
        clone_git(str(repository.source_uri), root)
    elif repository.source_type == "local":
        root = validate_local_path(str(repository.source_uri))
    else:
        raise ValueError("Unsupported repository source type")
    return root.resolve()


def _parse_repository(
    root: Path,
) -> tuple[list[ParsedSymbol], list[ParsedReference], int]:
    symbols: list[ParsedSymbol] = []
    references: list[ParsedReference] = []
    files = 0
    for path, relative, language in iter_source_files(root):
        source = path.read_text(encoding="utf-8", errors="replace")
        parsed = parse_source(relative, language, source)
        symbols.extend(parsed.symbols)
        references.extend(parsed.references)
        files += 1
    if not symbols:
        raise ValueError("No supported source files were found")
    return symbols, references, files


def _symbol_id(repository_id: str, symbol: ParsedSymbol) -> str:
    key = (
        f"{symbol.file_path}:{symbol.start_line}:{symbol.end_line}:"
        f"{symbol.kind}:{symbol.qualified_name}"
    )
    return str(uuid.uuid5(uuid.UUID(repository_id), key))


def _persist_graph(
    repository_id: str,
    workspace_id: str,
    symbols: list[ParsedSymbol],
    references: list[ParsedReference],
) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    qualified_ids: dict[str, str] = {}
    name_ids: dict[str, list[str]] = {}
    for symbol in symbols:
        symbol_id = _symbol_id(repository_id, symbol)
        qualified_ids[symbol.qualified_name] = symbol_id
        name_ids.setdefault(symbol.name, []).append(symbol_id)
        embedding_text = "\n".join(
            value
            for value in (
                f"{symbol.kind} {symbol.qualified_name}",
                symbol.signature,
                symbol.docstring,
                symbol.source_text[:6000],
            )
            if value
        )
        records.append(
            {
                "id": symbol_id,
                "symbol": symbol,
                "embedding_text": embedding_text,
            }
        )

    with SessionLocal.begin() as session:
        session.query(CodeReference).filter_by(repository_id=repository_id).delete()
        session.query(CodeSymbol).filter_by(repository_id=repository_id).delete()
        for record in records:
            symbol = record["symbol"]
            session.add(
                CodeSymbol(
                    id=record["id"],
                    repository_id=repository_id,
                    workspace_id=workspace_id,
                    name=symbol.name,
                    qualified_name=symbol.qualified_name,
                    kind=symbol.kind,
                    language=symbol.language,
                    file_path=symbol.file_path,
                    start_line=symbol.start_line,
                    end_line=symbol.end_line,
                    signature=symbol.signature,
                    docstring=symbol.docstring,
                    source_text=symbol.source_text,
                    content_hash=hashlib.sha256(
                        symbol.source_text.encode()
                    ).hexdigest(),
                    metadata_json=symbol.metadata,
                )
            )
        session.flush()
        for index, reference in enumerate(references):
            target_candidates = name_ids.get(reference.target_name, [])
            target_id = target_candidates[0] if len(target_candidates) == 1 else None
            session.add(
                CodeReference(
                    id=str(
                        uuid.uuid5(
                            uuid.UUID(repository_id),
                            f"ref:{index}:{reference.file_path}:{reference.line}:{reference.kind}:{reference.target_name}",
                        )
                    ),
                    repository_id=repository_id,
                    source_symbol_id=qualified_ids.get(
                        reference.source_qualified_name or ""
                    ),
                    target_symbol_id=target_id,
                    target_name=reference.target_name,
                    kind=reference.kind,
                    file_path=reference.file_path,
                    line=reference.line,
                    metadata_json=reference.metadata,
                )
            )
    return records


async def _ensure_collection(client: AsyncQdrantClient, vector_size: int) -> None:
    if not await client.collection_exists(settings.CODE_COLLECTION):
        await client.create_collection(
            settings.CODE_COLLECTION,
            vectors_config={
                "dense": models.VectorParams(
                    size=vector_size, distance=models.Distance.COSINE
                )
            },
            sparse_vectors_config={
                "sparse": models.SparseVectorParams(modifier=models.Modifier.IDF)
            },
        )
        for field in (
            "workspace_id",
            "repository_id",
            "language",
            "embedding_model",
            "sparse_model",
        ):
            await client.create_payload_index(
                settings.CODE_COLLECTION, field, models.PayloadSchemaType.KEYWORD
            )


async def _index_vectors(
    client: AsyncQdrantClient,
    repository_id: str,
    workspace_id: str,
    records: list[dict[str, Any]],
) -> None:
    if await client.collection_exists(settings.CODE_COLLECTION):
        await client.delete(
            settings.CODE_COLLECTION,
            points_selector=models.FilterSelector(
                filter=models.Filter(
                    must=[
                        models.FieldCondition(
                            key="repository_id",
                            match=models.MatchValue(value=repository_id),
                        )
                    ]
                )
            ),
            wait=True,
        )
    for start in range(0, len(records), 16):
        batch = records[start : start + 16]
        vectors = await embed([record["embedding_text"] for record in batch])
        await _ensure_collection(client, len(vectors[0]))
        await client.upsert(
            settings.CODE_COLLECTION,
            wait=True,
            points=[
                models.PointStruct(
                    id=record["id"],
                    vector={
                        "dense": vector,
                        "sparse": models.Document(
                            text=record["embedding_text"], model=settings.SPARSE_MODEL
                        ),
                    },
                    payload={
                        "workspace_id": workspace_id,
                        "repository_id": repository_id,
                        "language": record["symbol"].language,
                        "embedding_model": settings.EMBEDDING_MODEL,
                        "sparse_model": settings.SPARSE_MODEL,
                    },
                )
                for record, vector in zip(batch, vectors, strict=True)
            ],
        )


def _default_branch(root: Path) -> str | None:
    if not (root / ".git").is_dir():
        return None
    result = subprocess.run(
        ["git", "-C", str(root), "branch", "--show-current"],
        check=False,
        capture_output=True,
        text=True,
        timeout=15,
    )
    return result.stdout.strip() or None


async def ingest_repository(ctx: dict[str, Any], repository_id: str) -> None:
    del ctx
    client = AsyncQdrantClient(url=settings.QDRANT_URL)
    try:
        with SessionLocal() as session:
            repository = session.get(Repository, repository_id)
            if repository is None:
                return
            session.expunge(repository)
        _set_status(repository_id, "preparing")
        root = await asyncio.to_thread(_prepare_worktree, repository)
        _set_status(repository_id, "parsing")
        symbols, references, file_count = await asyncio.to_thread(
            _parse_repository, root
        )
        _set_status(repository_id, "embedding")
        records = await asyncio.to_thread(
            _persist_graph,
            repository_id,
            repository.workspace_id,
            symbols,
            references,
        )
        await _index_vectors(client, repository_id, repository.workspace_id, records)
        branch = await asyncio.to_thread(_default_branch, root)
        with SessionLocal.begin() as session:
            current = session.get(Repository, repository_id)
            current.root_path = str(root)
            current.default_branch = branch
        _set_status(
            repository_id,
            "ready",
            metadata={
                "file_count": file_count,
                "symbol_count": len(symbols),
                "reference_count": len(references),
            },
        )
    except Exception as exc:
        logger.exception(
            "code_repository_ingestion_failed", repository_id=repository_id
        )
        _set_status(repository_id, "failed", error=str(exc)[:1000])
        raise
    finally:
        await client.close()
