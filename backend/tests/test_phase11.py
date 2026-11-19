import asyncio
import subprocess
import sys
import uuid
import zipfile
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.api.dependencies import Principal, get_principal
from app.code import parser_process
from app.code.parser import parse_source
from app.code.workspace import CodeWorkspace
from app.core.config import settings
from app.main import app
from app.models import (
    Base,
    Organization,
    Repository,
    RepositoryJob,
    RepositoryOutbox,
    User,
    Workspace,
    WorkspaceMember,
)
from app.workers import code_ingest
from app.workers import repository_jobs as jobs


@pytest.fixture
def repository_db(tmp_path, monkeypatch):
    engine = create_engine(
        "sqlite://", poolclass=StaticPool, connect_args={"check_same_thread": False}
    )
    Base.metadata.create_all(engine)
    factory = sessionmaker(engine, expire_on_commit=False)
    root = tmp_path / "managed" / "repo" / "worktree"
    root.mkdir(parents=True)
    (root / "hello.py").write_text("def hello(): return 'world'\n", encoding="utf-8")
    repo_id = str(uuid.uuid4())
    with factory.begin() as session:
        session.add(Organization(id="org", name="Org"))
        session.add(Workspace(id="workspace", organization_id="org", name="Test"))
        session.add(
            User(id="alice", email="alice@example.com", hashed_password="unused")
        )
        session.add(
            WorkspaceMember(
                id="member", workspace_id="workspace", user_id="alice", role="owner"
            )
        )
        session.add(
            Repository(
                id=repo_id,
                workspace_id="workspace",
                name="Test",
                source_type="zip",
                root_path=str(root),
                source_state="available",
            )
        )
    monkeypatch.setattr(jobs, "SessionLocal", factory)
    monkeypatch.setattr(code_ingest, "SessionLocal", factory)
    monkeypatch.setattr("app.api.routes.repositories.SessionLocal", factory)
    monkeypatch.setattr("app.code.workspace.SessionLocal", factory)
    monkeypatch.setattr(settings, "CODE_REPOSITORY_PATH", str(tmp_path / "managed"))
    monkeypatch.setattr(settings, "CODE_INDEX_EMBEDDINGS", False)
    monkeypatch.setattr(settings, "AUTH_REQUIRED", False)
    app.dependency_overrides[get_principal] = lambda: Principal(
        None, "workspace", "owner"
    )
    yield factory, repo_id, root
    app.dependency_overrides.clear()
    engine.dispose()


def queue(factory, repo_id, actor=None):
    with factory.begin() as session:
        return jobs.schedule(
            session, session.get(Repository, repo_id), "reindex", actor
        ).id


def test_schedule_and_outbox_commit_together_and_deduplicate(repository_db):
    factory, repo_id, _ = repository_db
    first = queue(factory, repo_id)
    assert queue(factory, repo_id) == first
    with factory() as session:
        assert len(session.scalars(select(RepositoryJob)).all()) == 1
        assert session.get(RepositoryOutbox, first) is not None
    with factory.begin() as session:
        jobs.finish(session, session.get(RepositoryJob, first), "cancelled")
    with pytest.raises(RuntimeError), factory.begin() as session:
        jobs.schedule(session, session.get(Repository, repo_id), "reindex")
        raise RuntimeError("transaction rolled back")
    with factory() as session:
        assert len(session.scalars(select(RepositoryJob)).all()) == 1
        assert session.scalar(select(RepositoryOutbox)) is None


def test_duplicate_claim_and_expired_worker_cannot_publish(repository_db):
    factory, repo_id, _ = repository_db
    job_id = queue(factory, repo_id)
    first_token = jobs.claim(job_id)
    assert first_token
    assert jobs.claim(job_id) is None
    with factory.begin() as session:
        session.get(RepositoryJob, job_id).lease_expires_at = datetime.now(
            UTC
        ) - timedelta(seconds=1)
    jobs.reconcile()
    next_token = jobs.claim(job_id)
    assert next_token and next_token != first_token
    with pytest.raises(jobs.LeaseLost):
        code_ingest._set_status(repo_id, "ready", lease=(job_id, first_token))
    with factory() as session:
        assert session.get(Repository, repo_id).status == "pending"
        assert session.get(RepositoryJob, job_id).attempt == 2


def test_deadline_and_retry_limit_are_terminal(repository_db):
    factory, repo_id, _ = repository_db
    job_id = queue(factory, repo_id)
    for _ in range(jobs.MAX_ATTEMPTS):
        assert jobs.claim(job_id)
        with factory.begin() as session:
            session.get(RepositoryJob, job_id).lease_expires_at = datetime.now(
                UTC
            ) - timedelta(seconds=1)
        jobs.reconcile()
    with factory() as session:
        assert session.get(RepositoryJob, job_id).error_code == "worker_lost"
    next_id = queue(factory, repo_id)
    with factory.begin() as session:
        session.get(RepositoryJob, next_id).deadline_at = datetime.now(UTC) - timedelta(
            seconds=1
        )
    jobs.reconcile()
    with factory() as session:
        assert session.get(RepositoryJob, next_id).error_code == "deadline_exceeded"
        assert session.scalar(select(RepositoryOutbox)) is None


def test_revoked_membership_cancels_queued_and_running_jobs(repository_db):
    factory, repo_id, _ = repository_db
    job_id = queue(factory, repo_id, "alice")
    token = jobs.claim(job_id)
    with factory.begin() as session:
        session.get(WorkspaceMember, "member").role = "viewer"
    with pytest.raises(jobs.LeaseLost):
        jobs.heartbeat(job_id, token)
    jobs.reconcile()
    with factory() as session:
        assert session.get(RepositoryJob, job_id).state == "cancelled"
    next_id = queue(factory, repo_id, "alice")
    assert jobs.claim(next_id) is None


def test_dispatch_repeats_after_queue_loss(repository_db):
    factory, repo_id, _ = repository_db
    job_id = queue(factory, repo_id)

    class Queue:
        def __init__(self):
            self.calls = []

        async def enqueue_job(self, name, identifier):
            self.calls.append((name, identifier))

    redis = Queue()
    asyncio.run(jobs.dispatch_repository_jobs({"redis": redis}))
    with factory.begin() as session:
        session.get(RepositoryOutbox, job_id).next_delivery_at = datetime.now(
            UTC
        ) - timedelta(seconds=1)
    asyncio.run(jobs.dispatch_repository_jobs({"redis": redis}))
    assert redis.calls == [("run_repository_job", job_id)] * 2


def test_zip_reindex_twice_preserves_edits_and_never_calls_models(
    repository_db, monkeypatch
):
    factory, repo_id, root = repository_db
    (root / "hello.py").write_text("def edited(): return 42\n", encoding="utf-8")
    monkeypatch.setattr(code_ingest, "parse_isolated", parse_source)

    def forbidden(*args, **kwargs):
        pytest.fail(
            "Reindex must not reacquire sources or contact embeddings by default"
        )

    monkeypatch.setattr(code_ingest, "extract_zip", forbidden)
    monkeypatch.setattr(code_ingest, "clone_git", forbidden)
    monkeypatch.setattr(code_ingest, "AsyncQdrantClient", forbidden)
    for _ in range(2):
        asyncio.run(code_ingest.run_repository_job({}, queue(factory, repo_id)))
    with factory() as session:
        repository = session.get(Repository, repo_id)
        assert repository.source_state == "available"
        assert repository.parse_state == "ready"
        assert repository.index_state == "unavailable"
        assert all(
            job.state == "succeeded" for job in session.scalars(select(RepositoryJob))
        )
    assert (root / "hello.py").read_text() == "def edited(): return 42\n"
    assert any(
        item["name"] == "edited"
        for item in CodeWorkspace(factory).search_symbols(
            repo_id, "workspace", "edited"
        )
    )


def test_parser_failure_is_per_file_and_checkout_remains_browsable(
    repository_db, monkeypatch
):
    factory, repo_id, root = repository_db
    (root / "bad.py").write_text("broken native parser fixture", encoding="utf-8")

    def parse(path, language, source):
        if path == "bad.py":
            raise parser_process.ParserFailure("parser_crashed")
        return parse_source(path, language, source)

    monkeypatch.setattr(code_ingest, "parse_isolated", parse)
    asyncio.run(code_ingest.run_repository_job({}, queue(factory, repo_id)))
    with factory() as session:
        repo = session.get(Repository, repo_id)
        assert repo.parse_state == "partial"
        assert repo.metadata_json["parse_warnings"] == [
            {"path": "bad.py", "code": "parser_crashed"}
        ]
    assert len(CodeWorkspace(factory).tree(repo_id, "workspace")) == 2


@pytest.mark.parametrize("source_state", ["unknown", "fetching", "failed"])
def test_legacy_failed_checkout_and_empty_file_are_browsable(
    repository_db, source_state
):
    factory, repo_id, root = repository_db
    (root / "empty.txt").touch()
    with factory.begin() as session:
        repo = session.get(Repository, repo_id)
        repo.status = "failed"
        repo.source_state = source_state
    workspace = CodeWorkspace(factory)
    assert workspace.list_repositories("workspace")[0]["source_state"] == "available"
    assert len(workspace.tree(repo_id, "workspace")) == 2
    assert workspace.read_file(repo_id, "workspace", "empty.txt")["content"] == ""


def test_missing_checkout_is_not_reported_available(repository_db):
    factory, repo_id, root = repository_db
    with factory.begin() as session:
        session.get(Repository, repo_id).root_path = str(root.parent / "missing")
    assert (
        CodeWorkspace(factory).list_repositories("workspace")[0]["source_state"]
        == "failed"
    )


def test_enabling_authentication_cancels_anonymous_queued_work(
    repository_db, monkeypatch
):
    factory, repo_id, _ = repository_db
    job_id = queue(factory, repo_id)
    monkeypatch.setattr(settings, "AUTH_REQUIRED", True)
    assert jobs.claim(job_id) is None
    with factory() as session:
        assert session.get(RepositoryJob, job_id).state == "cancelled"


def test_api_accepts_durable_work_during_redis_outage_and_enforces_scope(
    repository_db, monkeypatch
):
    _, repo_id, _ = repository_db

    async def unavailable(*args):
        raise ConnectionError("Redis unavailable")

    monkeypatch.setattr("app.api.routes.repositories._enqueue", unavailable)
    client = TestClient(app)
    response = client.post(f"/api/v1/repositories/{repo_id}/reindex")
    assert response.status_code == 202
    job_id = response.json()["job_id"]
    assert (
        client.get(f"/api/v1/repositories/{repo_id}/job").json()["state"] == "pending"
    )
    app.dependency_overrides[get_principal] = lambda: Principal(None, "other", "owner")
    assert client.get(f"/api/v1/repositories/{repo_id}/job").status_code == 404
    assert client.post(f"/api/v1/repositories/{repo_id}/cancel").status_code == 404
    app.dependency_overrides[get_principal] = lambda: Principal(
        None, "workspace", "viewer"
    )
    assert client.post(f"/api/v1/repositories/{repo_id}/reindex").status_code == 403
    app.dependency_overrides[get_principal] = lambda: Principal(
        None, "workspace", "owner"
    )
    assert (
        client.post(f"/api/v1/repositories/{repo_id}/cancel").json()["state"]
        == "cancelled"
    )
    assert jobs.claim(job_id) is None


def test_supervised_parser_round_trip():
    parsed = parser_process.parse_isolated(
        "hello.py", "python", "def hello(): return 42\n"
    )
    assert any(symbol.name == "hello" for symbol in parsed.symbols)


@pytest.mark.parametrize(
    "script,code",
    [
        ("import os; os._exit(139)", "parser_crashed"),
        ("import time; time.sleep(10)", "parser_timeout"),
    ],
)
def test_supervisor_survives_crashed_and_hung_child(monkeypatch, script, code):
    original_run = subprocess.run

    def run(*args, **kwargs):
        kwargs["timeout"] = 0.3
        return original_run([sys.executable, "-c", script], **kwargs)

    monkeypatch.setattr(parser_process.subprocess, "run", run)
    with pytest.raises(parser_process.ParserFailure, match=code):
        parser_process.parse_isolated("hello.py", "python", "pass")


def test_import_stages_zip_before_publication(repository_db):
    factory, repo_id, root = repository_db
    archive = root.parent / "source.zip"
    with zipfile.ZipFile(archive, "w") as bundle:
        bundle.writestr("new.py", "pass")
    with factory() as session:
        repo = session.get(Repository, repo_id)
        repo.root_path = str(root.parent / "new-worktree")
        repo.archive_path = str(archive)
        staged = code_ingest._prepare_worktree(repo)
        assert staged != Path(repo.root_path)
        assert not Path(repo.root_path).exists()
        assert (staged / "new.py").exists()
    assert (root / "hello.py").exists()


def test_status_read_expires_overdue_jobs_without_a_worker(repository_db):
    factory, repo_id, _ = repository_db
    job_id = queue(factory, repo_id)
    with factory.begin() as session:
        session.get(RepositoryJob, job_id).deadline_at = datetime.now(UTC) - timedelta(
            seconds=1
        )
    response = TestClient(app).get(f"/api/v1/repositories/{repo_id}/job")
    assert response.status_code == 200
    assert response.json()["state"] == "failed"
    assert response.json()["error_code"] == "deadline_exceeded"


def test_failed_vector_rebuild_retains_old_generation_and_files(
    repository_db, monkeypatch
):
    factory, repo_id, root = repository_db
    (root / "hello.py").write_text(
        "\n".join(f"def f{index}(): return {index}" for index in range(20)),
        encoding="utf-8",
    )
    monkeypatch.setattr(code_ingest, "parse_isolated", parse_source)
    monkeypatch.setattr(settings, "CODE_INDEX_EMBEDDINGS", True)
    stored = {}
    calls = 0
    fail_at = 100

    class Vectors:
        async def collection_exists(self, name):
            return True

        async def upsert(self, name, *, wait, points):
            stored.update({point.id: point for point in points})

        async def delete(self, *args, **kwargs):
            pytest.fail("Rebuild must retain prior generations")

        async def close(self):
            pass

    async def embed(texts):
        nonlocal calls
        calls += 1
        if calls == fail_at:
            raise ConnectionError("Provider unavailable")
        return [[0.1, 0.2] for _ in texts]

    monkeypatch.setattr(code_ingest, "AsyncQdrantClient", lambda **kwargs: Vectors())
    monkeypatch.setattr(code_ingest, "embed", embed)
    asyncio.run(code_ingest.run_repository_job({}, queue(factory, repo_id)))
    original = dict(stored)
    with factory() as session:
        generation = session.get(Repository, repo_id).metadata_json["index_generation"]
    fail_at = calls + 2
    asyncio.run(code_ingest.run_repository_job({}, queue(factory, repo_id)))
    assert original
    assert all(stored[key] == value for key, value in original.items())
    with factory() as session:
        repo = session.get(Repository, repo_id)
        assert repo.metadata_json["index_generation"] == generation
        assert repo.source_state == "available"
        assert repo.index_state == "failed"
        assert session.get(RepositoryJob, repo.active_job_id).state == "failed"
    assert CodeWorkspace(factory).read_file(repo_id, "workspace", "hello.py")["content"]
