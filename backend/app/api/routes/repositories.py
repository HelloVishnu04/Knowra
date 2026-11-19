import asyncio
import logging
import uuid
import zipfile
from pathlib import Path
from typing import Annotated, Any

from arq import create_pool
from arq.connections import RedisSettings
from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile
from pydantic import BaseModel, Field
from redis.exceptions import RedisError
from sqlalchemy import select

from app.api.dependencies import Principal, get_principal, require_workspace_writer
from app.code.sources import (
    RepositorySourceError,
    validate_git_url,
    validate_local_path,
)
from app.code.workspace import CodeWorkspace
from app.core.config import settings
from app.core.database import SessionLocal
from app.models.code import Repository
from app.models.jobs import RepositoryJob
from app.rag.code import CodeRetriever
from app.workers import repository_jobs as jobs

router = APIRouter()
PrincipalDependency = Annotated[Principal, Depends(get_principal)]
WriterDependency = Annotated[Principal, Depends(require_workspace_writer)]


class GitRepositoryRequest(BaseModel):
    url: str
    name: str = Field(default="", max_length=120)


class LocalRepositoryRequest(BaseModel):
    path: str
    name: str = Field(default="", max_length=120)


def _repository_root(repository_id: str) -> Path:
    return Path(settings.CODE_REPOSITORY_PATH).resolve() / repository_id


async def _enqueue(repository_id: str) -> None:
    redis_settings = RedisSettings.from_dsn(settings.REDIS_URL)
    redis_settings.conn_retries = 0
    pool = await create_pool(redis_settings)
    try:
        with SessionLocal() as session:
            job_id = session.get(Repository, repository_id).active_job_id
        await pool.enqueue_job("run_repository_job", job_id)
    finally:
        await pool.aclose()


async def _queue_or_fail(repository_id: str) -> None:
    try:
        await _enqueue(repository_id)
    except (OSError, TimeoutError, RedisError):
        # The transaction already committed the outbox. The worker dispatcher retries.
        logging.getLogger(__name__).warning(
            "Repository dispatch deferred: %s", repository_id
        )


def _create_repository(
    *,
    repository_id: str,
    name: str,
    source_type: str,
    source_uri: str | None,
    root_path: Path,
    workspace_id: str,
    metadata: dict[str, Any] | None = None,
    actor_user_id: str | None = None,
) -> Repository:
    repository = Repository(
        id=repository_id,
        workspace_id=workspace_id,
        name=name[:120],
        source_type=source_type,
        source_uri=source_uri,
        root_path=str(root_path),
        status="pending",
        metadata_json=metadata or {},
        archive_path=(metadata or {}).get("archive_path"),
    )
    with SessionLocal.begin() as session:
        session.add(repository)
        session.flush()
        jobs.schedule(session, repository, "import", actor_user_id)
    return repository


@router.get("/repositories")
def list_repositories(principal: PrincipalDependency) -> list[dict[str, Any]]:
    jobs.reconcile(principal.workspace_id)
    return CodeWorkspace().list_repositories(principal.workspace_id)


@router.post("/repositories/zip", status_code=202)
async def upload_repository(
    file: Annotated[UploadFile, File()],
    principal: WriterDependency,
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
        workspace_id=principal.workspace_id,
        actor_user_id=principal.user_id,
        metadata={"archive_path": str(archive), "filename": filename},
    )
    await _queue_or_fail(repository_id)
    return {"id": repository.id, "name": repository.name, "status": repository.status}


@router.post("/repositories/git", status_code=202)
async def add_git_repository(
    body: GitRepositoryRequest, principal: WriterDependency
) -> dict[str, Any]:
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
        workspace_id=principal.workspace_id,
        actor_user_id=principal.user_id,
    )
    await _queue_or_fail(repository_id)
    return {"id": repository.id, "name": repository.name, "status": repository.status}


@router.post("/repositories/local", status_code=202)
async def add_local_repository(
    body: LocalRepositoryRequest, principal: WriterDependency
) -> dict[str, Any]:
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
        workspace_id=principal.workspace_id,
        actor_user_id=principal.user_id,
    )
    await _queue_or_fail(repository_id)
    return {"id": repository.id, "name": repository.name, "status": repository.status}


@router.post("/repositories/{repository_id}/reindex", status_code=202)
async def reindex_repository(
    repository_id: str, principal: WriterDependency
) -> dict[str, str]:
    jobs.reconcile(principal.workspace_id)
    workspace = CodeWorkspace()
    try:
        workspace.repository(repository_id, principal.workspace_id)
    except RepositorySourceError as exc:
        raise HTTPException(404, str(exc)) from exc
    with SessionLocal.begin() as session:
        repository = session.scalar(
            select(Repository).where(Repository.id == repository_id).with_for_update()
        )
        if not Path(repository.root_path).is_dir():
            raise HTTPException(409, "Checkout is missing. Retry source import first.")
        job = jobs.schedule(session, repository, "reindex", principal.user_id)
        job_id = job.id
    await _queue_or_fail(repository_id)
    return {"id": repository_id, "status": "pending", "job_id": job_id}


@router.post("/repositories/{repository_id}/retry", status_code=202)
async def retry_repository(repository_id: str, principal: WriterDependency):
    jobs.reconcile(principal.workspace_id)
    try:
        CodeWorkspace().repository(repository_id, principal.workspace_id)
    except RepositorySourceError as exc:
        raise HTTPException(404, str(exc)) from exc
    with SessionLocal.begin() as session:
        repository = session.scalar(
            select(Repository).where(Repository.id == repository_id).with_for_update()
        )
        operation = "reindex" if Path(repository.root_path).is_dir() else "import"
        job = jobs.schedule(session, repository, operation, principal.user_id)
        result = jobs.job_json(job)
    await _queue_or_fail(repository_id)
    return result


@router.get("/repositories/{repository_id}/job")
def repository_job(repository_id: str, principal: PrincipalDependency):
    jobs.reconcile(principal.workspace_id)
    try:
        repository = CodeWorkspace().repository(repository_id, principal.workspace_id)
    except RepositorySourceError as exc:
        raise HTTPException(404, str(exc)) from exc
    with SessionLocal() as session:
        job = (
            session.get(RepositoryJob, repository.active_job_id)
            if repository.active_job_id
            else None
        )
        return jobs.job_json(job) if job else None


@router.post("/repositories/{repository_id}/cancel")
def cancel_repository(repository_id: str, principal: WriterDependency):
    try:
        repository = CodeWorkspace().repository(repository_id, principal.workspace_id)
    except RepositorySourceError as exc:
        raise HTTPException(404, str(exc)) from exc
    with SessionLocal.begin() as session:
        job = session.scalar(
            select(RepositoryJob)
            .where(RepositoryJob.id == repository.active_job_id)
            .with_for_update()
        )
        if job and job.state in jobs.ACTIVE:
            jobs.finish(session, job, "cancelled")
        return jobs.job_json(job) if job else None


@router.get("/repositories/{repository_id}/tree")
def repository_tree(
    repository_id: str, principal: PrincipalDependency
) -> list[dict[str, Any]]:
    try:
        return CodeWorkspace().tree(repository_id, principal.workspace_id)
    except RepositorySourceError as exc:
        raise HTTPException(404, str(exc)) from exc


@router.get("/repositories/{repository_id}/file")
def read_repository_file(
    repository_id: str,
    principal: PrincipalDependency,
    path: str = Query(min_length=1),
    start: int = Query(default=1, ge=1),
    end: int | None = Query(default=None, ge=1),
) -> dict[str, Any]:
    try:
        return CodeWorkspace().read_file(
            repository_id,
            principal.workspace_id,
            path,
            start=start,
            end=end,
        )
    except RepositorySourceError as exc:
        raise HTTPException(422, str(exc)) from exc


@router.get("/repositories/{repository_id}/symbols")
def search_symbols(
    repository_id: str,
    principal: PrincipalDependency,
    q: str = "",
    limit: int = Query(default=50, ge=1, le=100),
) -> list[dict[str, Any]]:
    try:
        return CodeWorkspace().search_symbols(
            repository_id, principal.workspace_id, q, limit=limit
        )
    except RepositorySourceError as exc:
        raise HTTPException(404, str(exc)) from exc


@router.get("/repositories/{repository_id}/search")
async def semantic_code_search(
    repository_id: str,
    principal: PrincipalDependency,
    q: str = Query(min_length=1),
    limit: int = Query(default=10, ge=1, le=20),
) -> list[dict[str, Any]]:
    try:
        result = await CodeRetriever().retrieve(
            q,
            workspace_id=principal.workspace_id,
            top_k=limit,
            filters={"repository_id": repository_id},
        )
    except ValueError as exc:
        raise HTTPException(404, str(exc)) from exc
    return [chunk.model_dump() for chunk in result.chunks]


@router.get("/repositories/{repository_id}/references")
def find_references(
    repository_id: str,
    principal: PrincipalDependency,
    symbol: str = Query(min_length=1),
):
    try:
        return CodeWorkspace().find_references(
            repository_id, principal.workspace_id, symbol
        )
    except RepositorySourceError as exc:
        raise HTTPException(404, str(exc)) from exc


@router.get("/repositories/{repository_id}/diff")
def repository_diff(
    repository_id: str, principal: PrincipalDependency
) -> dict[str, str]:
    try:
        return CodeWorkspace().git_diff(repository_id, principal.workspace_id)
    except RepositorySourceError as exc:
        raise HTTPException(422, str(exc)) from exc
