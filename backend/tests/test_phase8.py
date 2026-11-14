import io
import subprocess
from pathlib import Path

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.config import settings
from app.models import Base, ExecutionJob, Organization, Workspace
from app.sandbox.queue import command_argv, snapshot_repository
from app.workers import sandbox


@pytest.mark.parametrize(
    "command",
    [
        "sh -c whoami",
        "python -c 'import os'",
        "npm install left-pad",
        "pytest ../outside",
        "ruff check --fix app.py",
    ],
)
def test_sandbox_command_allow_list_rejects_shells_and_unsafe_args(command: str):
    with pytest.raises(ValueError):
        command_argv(command)


def test_repository_snapshot_excludes_secrets_dependencies_and_applies_patch(
    tmp_path: Path,
):
    (tmp_path / "app.py").write_text("value = 1\n", encoding="utf-8")
    (tmp_path / ".env").write_text("TOKEN=secret\n", encoding="utf-8")
    (tmp_path / ".aws").mkdir()
    (tmp_path / ".aws" / "credentials").write_text("secret", encoding="utf-8")
    (tmp_path / "node_modules").mkdir()
    (tmp_path / "node_modules" / "package.js").write_text("secret", encoding="utf-8")

    result = snapshot_repository(tmp_path, {"app.py": "value = 2\n"})
    assert result == {"app.py": "value = 2\n"}


def test_timeout_uses_hardening_flags_and_always_removes_container(
    tmp_path: Path, monkeypatch
):
    engine = create_engine(
        "sqlite://", poolclass=StaticPool, connect_args={"check_same_thread": False}
    )
    Base.metadata.create_all(engine)
    factory = sessionmaker(engine, expire_on_commit=False)
    with factory.begin() as session:
        session.add(Organization(id="org", name="Test"))
        session.add(
            Workspace(
                id=settings.LOCAL_WORKSPACE_ID,
                organization_id="org",
                name="Local",
            )
        )
        session.add(
            ExecutionJob(
                id="timeout-job",
                workspace_id=settings.LOCAL_WORKSPACE_ID,
                attempt=1,
                stage="run_code",
                command_json=["python", "main.py"],
                image=settings.SANDBOX_PYTHON_IMAGE,
                files_json={"main.py": "while True: pass\n"},
                status="queued",
                stdout="",
                stderr="",
            )
        )
    monkeypatch.setattr(sandbox, "SessionLocal", factory)
    monkeypatch.setattr(settings, "SANDBOX_WALL_TIMEOUT_SECONDS", 1)
    docker_calls: list[tuple[str, ...]] = []

    def fake_docker(*args: str, timeout: int = 30):
        del timeout
        docker_calls.append(args)
        return subprocess.CompletedProcess(args, 0, stdout="container", stderr="")

    class FakeProcess:
        def __init__(self):
            self.stdout = io.StringIO("")
            self.stderr = io.StringIO("")
            self.terminated = False

        def wait(self, timeout=None):
            if not self.terminated:
                raise subprocess.TimeoutExpired("docker exec", timeout)
            return -15

        def terminate(self):
            self.terminated = True

        def kill(self):
            self.terminated = True

    cleanup_calls: list[list[str]] = []
    monkeypatch.setattr(sandbox, "_docker", fake_docker)
    monkeypatch.setattr(
        sandbox.subprocess, "Popen", lambda *args, **kwargs: FakeProcess()
    )
    monkeypatch.setattr(
        sandbox.subprocess,
        "run",
        lambda args, **kwargs: (
            cleanup_calls.append(args)
            or subprocess.CompletedProcess(args, 0, stdout="", stderr="")
        ),
    )

    sandbox._execute_sync("timeout-job")

    create = next(call for call in docker_calls if call[0] == "create")
    assert ("--network", "none") == create[
        create.index("--network") : create.index("--network") + 2
    ]
    assert "--read-only" in create
    assert "/workspace:rw,nosuid,nodev,mode=1777,size=268435456" in create
    assert ("--memory", str(settings.SANDBOX_MEMORY_BYTES)) == create[
        create.index("--memory") : create.index("--memory") + 2
    ]
    assert ("--cpus", "1") == create[
        create.index("--cpus") : create.index("--cpus") + 2
    ]
    assert ("--pids-limit", str(settings.SANDBOX_PIDS_LIMIT)) == create[
        create.index("--pids-limit") : create.index("--pids-limit") + 2
    ]
    assert "no-new-privileges:true" in create
    assert ("--user", "65532:65532") == create[
        create.index("--user") : create.index("--user") + 2
    ]
    assert ("--cap-drop", "ALL") == create[
        create.index("--cap-drop") : create.index("--cap-drop") + 2
    ]
    assert "--volume" not in create
    assert any(call[0] == "kill" for call in docker_calls)
    assert cleanup_calls[0][:3] == ["docker", "exec", "-i"]
    assert cleanup_calls[-1][:3] == ["docker", "rm", "-f"]
    with factory() as session:
        job = session.get(ExecutionJob, "timeout-job")
        assert job.status == "timed_out"
        assert job.exit_code is None
        assert job.completed_at is not None
    engine.dispose()
