import asyncio
import uuid
import zipfile
from pathlib import Path
from typing import Annotated, Any

from arq import create_pool
from arq.connections import RedisSettings
from fastapi import APIRouter, File, Form, HTTPException, Query, UploadFile
from pydantic import BaseModel, Field

from app.code.sources import (
    RepositorySourceError,
    validate_git_url,
    validate_local_path,
)
from app.code.workspace import CodeWorkspace
from app.core.config import settings
from app.core.database import SessionLocal
from app.models.code import Repository
from app.rag.code import CodeRetriever

router = APIRouter()


class GitRepositoryRequest(BaseModel):
    url: str
    name: str = Field(default="", max_length=120)


class LocalRepositoryRequest(BaseModel):
    path: str
    name: str = Field(default="", max_length=120)


def _repository_root(repository_id: str) -> Path:
    return Path(settings.CODE_REPOSITORY_PATH).resolve() / repository_id


async def _enqueue(repository_id: str) -> None:
    pool = await create_pool(RedisSettings.from_dsn(settings.REDIS_URL))
    try:
        await pool.enqueue_job("ingest_repository", repository_id)
    finally:
        await pool.aclose()


async def _queue_or_fail(repository_id: str) -> None:
    try:
        await _enqueue(repository_id)
    except Exception as exc:
        with SessionLocal.begin() as session:
            repository = session.get(Repository, repository_id)
            repository.status = "failed"
            repository.error = "Queue unavailable. Start Redis and retry indexing."
        raise HTTPException(
            503, "Repository saved, but indexing queue is unavailable"
        ) from exc


def _create_repository(
    *,
    repository_id: str,
    name: str,
    source_type: str,
    source_uri: str | None,
    root_path: Path,
    metadata: dict[str, Any] | None = None,
) -> Repository:
    repository = Repository(
        id=repository_id,
        workspace_id=settings.LOCAL_WORKSPACE_ID,
        name=name[:120],
        source_type=source_type,
        source_uri=source_uri,
        root_path=str(root_path),
        status="pending",
        metadata_json=metadata or {},
    )
    with SessionLocal.begin() as session:
        session.add(repository)
    return repository


@router.get("/repositories")
def list_repositories() -> list[dict[str, Any]]:
    return CodeWorkspace().list_repositories(settings.LOCAL_WORKSPACE_ID)


@router.post("/repositories/zip", status_code=202)
async def upload_repository(
    file: Annotated[UploadFile, File()],
    name: Annotated[str, Form()] = "",
) -> dict[str, Any]:
    filename = (file.filename or "repository.zip").replace("\\", "/").split("/")[-1]
    if Path(filename).suffix.lower() != ".zip":
        raise HTTPException(415, "Upload a ZIP repository archive")
    data = await file.read(settings.CODE_MAX_ARCHIVE_BYTES + 1)
    await file.close()
    if not data or len(data) > settings.CODE_MAX_ARCHIVE_BYTES:
        raise HTTPException(413, "Repository archive exceeds the configured limit")
    repository_id = str(uuid.uuid4())
    managed = _repository_root(repository_id)
    managed.mkdir(parents=True, exist_ok=False)
    archive = managed / "source.zip"
    await asyncio.to_thread(archive.write_bytes, data)
    if not zipfile.is_zipfile(archive):
        archive.unlink(missing_ok=True)
        managed.rmdir()
        raise HTTPException(422, "Archive is not a valid ZIP file")
    repository = _create_repository(
        repository_id=repository_id,
        name=(name.strip() or Path(filename).stem),
        source_type="zip",
        source_uri=None,
        root_path=managed / "worktree",
        metadata={"archive_path": str(archive), "filename": filename},
    )
    await _queue_or_fail(repository_id)
    return {"id": repository.id, "name": repository.name, "status": repository.status}


@router.post("/repositories/git", status_code=202)
async def add_git_repository(body: GitRepositoryRequest) -> dict[str, Any]:
    try:
        url = validate_git_url(body.url)
    except RepositorySourceError as exc:
        raise HTTPException(422, str(exc)) from exc
    repository_id = str(uuid.uuid4())
    repository = _create_repository(
        repository_id=repository_id,
        name=(body.name.strip() or Path(url.rstrip("/")).stem.removesuffix(".git")),
        source_type="git",
        source_uri=url,
        root_path=_repository_root(repository_id) / "worktree",
    )
    await _queue_or_fail(repository_id)
    return {"id": repository.id, "name": repository.name, "status": repository.status}


@router.post("/repositories/local", status_code=202)
async def add_local_repository(body: LocalRepositoryRequest) -> dict[str, Any]:
    try:
        path = validate_local_path(body.path)
    except RepositorySourceError as exc:
        raise HTTPException(422, str(exc)) from exc
    repository_id = str(uuid.uuid4())
    repository = _create_repository(
        repository_id=repository_id,
        name=(body.name.strip() or path.name),
        source_type="local",
        source_uri=str(path),
        root_path=path,
    )
    await _queue_or_fail(repository_id)
    return {"id": repository.id, "name": repository.name, "status": repository.status}


@router.post("/repositories/{repository_id}/reindex", status_code=202)
async def reindex_repository(repository_id: str) -> dict[str, str]:
    workspace = CodeWorkspace()
    try:
        workspace.repository(repository_id, settings.LOCAL_WORKSPACE_ID)
    except RepositorySourceError as exc:
        raise HTTPException(404, str(exc)) from exc
    with SessionLocal.begin() as session:
        repository = session.get(Repository, repository_id)
        repository.status = "pending"
        repository.error = None
    await _queue_or_fail(repository_id)
    return {"id": repository_id, "status": "pending"}


@router.get("/repositories/{repository_id}/tree")
def repository_tree(repository_id: str) -> list[dict[str, Any]]:
    try:
        return CodeWorkspace().tree(repository_id, settings.LOCAL_WORKSPACE_ID)
    except RepositorySourceError as exc:
        raise HTTPException(404, str(exc)) from exc


@router.get("/repositories/{repository_id}/file")
def read_repository_file(
    repository_id: str,
    path: str = Query(min_length=1),
    start: int = Query(default=1, ge=1),
    end: int | None = Query(default=None, ge=1),
) -> dict[str, Any]:
    try:
        return CodeWorkspace().read_file(
            repository_id,
            settings.LOCAL_WORKSPACE_ID,
            path,
            start=start,
            end=end,
        )
    except RepositorySourceError as exc:
        raise HTTPException(422, str(exc)) from exc


@router.get("/repositories/{repository_id}/symbols")
def search_symbols(
    repository_id: str,
    q: str = "",
    limit: int = Query(default=50, ge=1, le=100),
) -> list[dict[str, Any]]:
    try:
        return CodeWorkspace().search_symbols(
            repository_id, settings.LOCAL_WORKSPACE_ID, q, limit=limit
        )
    except RepositorySourceError as exc:
        raise HTTPException(404, str(exc)) from exc


@router.get("/repositories/{repository_id}/search")
async def semantic_code_search(
    repository_id: str,
    q: str = Query(min_length=1),
    limit: int = Query(default=10, ge=1, le=20),
) -> list[dict[str, Any]]:
    try:
        result = await CodeRetriever().retrieve(
            q,
            workspace_id=settings.LOCAL_WORKSPACE_ID,
            top_k=limit,
            filters={"repository_id": repository_id},
        )
    except ValueError as exc:
        raise HTTPException(404, str(exc)) from exc
    return [chunk.model_dump() for chunk in result.chunks]


@router.get("/repositories/{repository_id}/references")
def find_references(repository_id: str, symbol: str = Query(min_length=1)):
    try:
        return CodeWorkspace().find_references(
            repository_id, settings.LOCAL_WORKSPACE_ID, symbol
        )
    except RepositorySourceError as exc:
        raise HTTPException(404, str(exc)) from exc


@router.get("/repositories/{repository_id}/diff")
def repository_diff(repository_id: str) -> dict[str, str]:
    try:
        return CodeWorkspace().git_diff(repository_id, settings.LOCAL_WORKSPACE_ID)
    except RepositorySourceError as exc:
        raise HTTPException(422, str(exc)) from exc
