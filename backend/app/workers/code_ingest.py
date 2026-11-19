import asyncio
import contextlib
import hashlib
import subprocess
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import structlog
from qdrant_client import AsyncQdrantClient, models

from app.code.parser import ParsedReference, ParsedSymbol
from app.code.parser_process import ParserFailure, parse_isolated
from app.code.sources import (
    clone_git,
    extract_zip,
    iter_source_files,
    validate_local_path,
)
from app.core.config import settings
from app.core.database import SessionLocal
from app.models.code import CodeReference, CodeSymbol, Repository
from app.models.jobs import RepositoryJob
from app.rag.documents import embed
from app.workers import repository_jobs as jobs

logger = structlog.get_logger(__name__)


def _set_status(
    repository_id: str,
    status: str,
    *,
    error: str | None = None,
    metadata: dict[str, Any] | None = None,
    lease: tuple[str, str] | None = None,
    **states,
) -> None:
    with SessionLocal.begin() as session:
        if lease:
            job = jobs.guard(session, *lease)
            job.progress = status.capitalize()
        repository = session.get(Repository, repository_id)
        if repository is None:
            return
        repository.status = status
        repository.error = error
        if metadata is not None:
            repository.metadata_json = {**(repository.metadata_json or {}), **metadata}
        for key, value in states.items():
            setattr(repository, key, value)
        if status == "ready":
            repository.indexed_at = datetime.now(UTC)


def _prepare_worktree(repository: Repository, operation="import", suffix=None) -> Path:
    root = Path(repository.root_path)
    # Reindex never fetches or extracts over a worktree, including legacy worktrees.
    if root.is_dir():
        return root.resolve()
    if operation == "reindex":
        raise ValueError("Repository checkout is missing; retry import instead")
    if repository.source_type == "local":
        return validate_local_path(str(repository.source_uri)).resolve()
    staged = root.parent / (".import-" + (suffix or str(uuid.uuid4())))
    if repository.source_type == "zip":
        archive = Path(
            repository.archive_path
            or (repository.metadata_json or {}).get("archive_path", "")
        )
        if not archive.is_file():
            raise ValueError("Repository ZIP is missing")
        extract_zip(archive, staged)
    elif repository.source_type == "git":
        clone_git(str(repository.source_uri), staged)
    else:
        raise ValueError("Unsupported repository source type")
    return staged.resolve()


def _parse_repository(
    root: Path,
    lease: tuple[str, str] | None = None,
) -> tuple[list[ParsedSymbol], list[ParsedReference], int, list[dict[str, str]]]:
    symbols: list[ParsedSymbol] = []
    references: list[ParsedReference] = []
    files = 0
    warnings = []
    for path, relative, language in iter_source_files(root):
        if lease:
            with SessionLocal() as session:
                jobs.guard(session, *lease)
        files += 1
        try:
            with path.open("rb") as handle:
                source = handle.read(settings.CODE_MAX_SOURCE_BYTES + 1).decode(
                    "utf-8", errors="replace"
                )
            parsed = parse_isolated(relative, language, source)
        except (ParserFailure, OSError) as exc:
            warnings.append(
                {
                    "path": relative,
                    "code": str(exc)
                    if isinstance(exc, ParserFailure)
                    else "file_unreadable",
                }
            )
            continue
        symbols.extend(parsed.symbols)
        references.extend(parsed.references)
    return symbols, references, files, warnings


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
    lease: tuple[str, str] | None = None,
    failed_paths: list[str] | None = None,
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
        if lease:
            jobs.guard(session, *lease)
        session.query(CodeReference).filter_by(repository_id=repository_id).delete()
        previous = session.query(CodeSymbol).filter_by(repository_id=repository_id)
        if failed_paths:
            previous = previous.filter(CodeSymbol.file_path.notin_(failed_paths))
        previous.delete(synchronize_session=False)
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
    generation: str,
    lease: tuple[str, str] | None = None,
) -> None:
    for start in range(0, len(records), 16):
        if lease:
            with SessionLocal() as session:
                jobs.guard(session, *lease)
        batch = records[start : start + 16]
        vectors = await embed([record["embedding_text"] for record in batch])
        await _ensure_collection(client, len(vectors[0]))
        await client.upsert(
            settings.CODE_COLLECTION,
            wait=True,
            points=[
                models.PointStruct(
                    id=str(uuid.uuid5(uuid.UUID(generation), record["id"])),
                    vector={
                        "dense": vector,
                        "sparse": models.Document(
                            text=record["embedding_text"], model=settings.SPARSE_MODEL
                        ),
                    },
                    payload={
                        "workspace_id": workspace_id,
                        "repository_id": repository_id,
                        "generation": generation,
                        "symbol_id": record["id"],
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
    """Discard pre-migration Redis messages; resubmit through the authorized API."""
    logger.warning("legacy_repository_delivery_ignored", repository_id=repository_id)


async def _process_repository(job_id: str, token: str) -> None:
    lease = (job_id, token)
    with SessionLocal() as session:
        job = session.get(RepositoryJob, job_id)
        repository = session.get(Repository, job.repository_id)
        operation = job.operation
        session.expunge(repository)
    repository_id = repository.id
    _set_status(
        repository_id,
        "preparing",
        lease=lease,
        source_state="available" if Path(repository.root_path).is_dir() else "fetching",
    )
    root = await asyncio.to_thread(_prepare_worktree, repository, operation, token)
    branch = await asyncio.to_thread(_default_branch, root)
    with SessionLocal.begin() as session:
        jobs.guard(session, *lease)
        current = session.get(Repository, repository_id)
        target = Path(current.root_path).resolve()
        if root != target and repository.source_type != "local":
            # Staged import is published only while holding the current job lease.
            # An existing checkout is never removed or replaced.
            if not target.exists():
                root.rename(target)
            root = target
        current.root_path = str(root)
        current.source_state = "available"
        current.default_branch = branch
    _set_status(repository_id, "parsing", lease=lease, parse_state="running")
    symbols, references, file_count, warnings = await asyncio.to_thread(
        _parse_repository, root, lease
    )
    parse_state = (
        "partial"
        if warnings and symbols
        else "failed"
        if warnings
        else "ready"
        if symbols
        else "unavailable"
    )
    _set_status(
        repository_id,
        "parsing",
        lease=lease,
        parse_state=parse_state,
        index_state="pending",
        metadata={
            "file_count": file_count,
            "symbol_count": len(symbols),
            "reference_count": len(references),
            "parse_warnings": warnings[:100],
            "parse_warning_count": len(warnings),
        },
    )
    records = await asyncio.to_thread(
        _persist_graph,
        repository_id,
        repository.workspace_id,
        symbols,
        references,
        lease,
        [item["path"] for item in warnings],
    )
    if warnings or not records or not settings.CODE_INDEX_EMBEDDINGS:
        _set_status(repository_id, "available", lease=lease, index_state="unavailable")
        return
    _set_status(repository_id, "embedding", lease=lease, index_state="running")
    client = AsyncQdrantClient(url=settings.QDRANT_URL)
    try:
        await _index_vectors(
            client, repository_id, repository.workspace_id, records, token, lease
        )
        _set_status(
            repository_id,
            "ready",
            lease=lease,
            index_state="ready",
            metadata={"index_generation": token},
        )
    finally:
        await client.close()


async def run_repository_job(ctx: dict[str, Any], job_id: str) -> None:
    token = jobs.claim(job_id)
    if token is None:
        return

    async def keep_alive():
        while True:
            await asyncio.sleep(20)
            jobs.heartbeat(job_id, token)

    processing = asyncio.create_task(_process_repository(job_id, token))
    pulse = asyncio.create_task(keep_alive())
    try:
        with SessionLocal() as session:
            remaining = max(
                0,
                (
                    jobs.utc(session.get(RepositoryJob, job_id).deadline_at)
                    - datetime.now(UTC)
                ).total_seconds(),
            )
        done, _ = await asyncio.wait(
            {processing, pulse}, timeout=remaining, return_when=asyncio.FIRST_COMPLETED
        )
        if not done:
            raise TimeoutError("Repository job deadline exceeded")
        for task in done:
            task.result()
        with SessionLocal.begin() as session:
            job = jobs.guard(session, job_id, token)
            job.progress = "Processing complete"
            jobs.finish(session, job, "succeeded")
    except jobs.LeaseLost:
        # Revocation/recovery owns the final state. No stale worker writes.
        jobs.reconcile()
    except Exception:
        logger.exception("repository_job_failed", job_id=job_id)
        with SessionLocal.begin() as session, contextlib.suppress(jobs.LeaseLost):
            job = jobs.guard(session, job_id, token)
            jobs.finish(session, job, "failed", "ingestion_failed")
        jobs.reconcile()
    finally:
        for task in (processing, pulse):
            task.cancel()
        await asyncio.gather(processing, pulse, return_exceptions=True)
