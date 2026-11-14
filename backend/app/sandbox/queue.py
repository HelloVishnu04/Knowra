import asyncio
import os
import shlex
import uuid
from pathlib import Path, PurePosixPath
from typing import Literal, cast

from arq import create_pool
from arq.connections import RedisSettings

from app.agents.coding import CheckPlan, CheckResult
from app.code.sources import IGNORED_DIRECTORIES
from app.core.config import settings
from app.core.database import SessionLocal
from app.models.runs import ExecutionJob

SECRET_NAMES = {".env", ".npmrc", ".pypirc", "credentials", "id_rsa", "id_ed25519"}
SECRET_DIRECTORIES = {".aws", ".ssh", ".gnupg"}
ALLOWED_PREFIXES = (
    ("ruff", "format", "--check"),
    ("ruff", "check"),
    ("pytest",),
    ("npm", "run", "lint"),
    ("npx", "tsc", "--noEmit"),
    ("npm", "test"),
    ("python", "main.py"),
    ("node", "main.js"),
)


def _safe_relative(value: str) -> bool:
    path = PurePosixPath(value.replace("\\", "/"))
    return bool(value) and not path.is_absolute() and ".." not in path.parts


def command_argv(command: str) -> list[str]:
    """Convert a selected check to argv without ever invoking a shell."""
    try:
        values = shlex.split(command, posix=True)
    except ValueError as exc:
        raise ValueError("Malformed sandbox command") from exc
    prefix = next(
        (
            candidate
            for candidate in ALLOWED_PREFIXES
            if tuple(values[: len(candidate)]) == candidate
        ),
        None,
    )
    if prefix is None:
        raise ValueError("Command is outside the sandbox allow-list")
    extra = values[len(prefix) :]
    if prefix in {
        ("npm", "run", "lint"),
        ("npx", "tsc", "--noEmit"),
        ("npm", "test"),
        ("python", "main.py"),
        ("node", "main.js"),
    }:
        if extra:
            raise ValueError("Unexpected arguments for sandbox command")
    elif any(not _safe_relative(item) or item.startswith("-") for item in extra):
        raise ValueError("Sandbox command contains an unsafe path")
    return values


def snapshot_repository(
    root: Path, patched_files: dict[str, str | None]
) -> dict[str, str]:
    root = root.resolve()
    snapshot: dict[str, str] = {}
    total = 0
    for current, directories, files in os.walk(root):
        directories[:] = sorted(
            item
            for item in directories
            if item not in IGNORED_DIRECTORIES and item not in SECRET_DIRECTORIES
        )
        current_path = Path(current)
        for name in sorted(files):
            path = current_path / name
            relative = path.relative_to(root).as_posix()
            if (
                path.is_symlink()
                or name in SECRET_NAMES
                or (name.startswith(".env") and name != ".env.example")
            ):
                continue
            size = path.stat().st_size
            if size > settings.CODE_MAX_SOURCE_BYTES:
                continue
            try:
                value = path.read_text(encoding="utf-8", errors="strict")
            except (OSError, UnicodeError):
                continue
            total += len(value.encode("utf-8"))
            if total > settings.SANDBOX_SNAPSHOT_BYTES:
                raise ValueError("Repository snapshot exceeds the sandbox limit")
            snapshot[relative] = value
    for path, value in patched_files.items():
        if not _safe_relative(path):
            raise ValueError("Patched file path is unsafe")
        if value is None:
            snapshot.pop(path, None)
        else:
            snapshot[path] = value
    return snapshot


def create_execution_job(
    *,
    workspace_id: str,
    agent_run_id: str | None,
    repository_id: str | None,
    attempt: int,
    stage: str,
    command: str,
    files: dict[str, str],
) -> ExecutionJob:
    argv = command_argv(command)
    image = (
        settings.SANDBOX_NODE_IMAGE
        if argv[0] in {"npm", "npx", "node"}
        else settings.SANDBOX_PYTHON_IMAGE
    )
    job = ExecutionJob(
        id=str(uuid.uuid4()),
        workspace_id=workspace_id,
        agent_run_id=agent_run_id,
        repository_id=repository_id,
        attempt=attempt,
        stage=stage,
        command_json=argv,
        image=image,
        files_json=files,
        status="queued",
        stdout="",
        stderr="",
    )
    with SessionLocal.begin() as session:
        session.add(job)
    return job


def execution_job(job_id: str) -> dict[str, object] | None:
    with SessionLocal() as session:
        job = session.get(ExecutionJob, job_id)
        if job is None:
            return None
        return {
            "id": job.id,
            "workspace_id": job.workspace_id,
            "status": job.status,
            "stdout": job.stdout,
            "stderr": job.stderr,
            "exit_code": job.exit_code,
            "duration_ms": job.duration_ms,
            "error": job.error,
        }


async def enqueue_execution_job(job_id: str) -> None:
    pool = await create_pool(RedisSettings.from_dsn(settings.REDIS_URL))
    try:
        queued = await pool.enqueue_job(
            "execute_sandbox_job",
            job_id,
            _job_id=job_id,
            _queue_name=settings.SANDBOX_QUEUE,
        )
        if queued is None:
            raise RuntimeError("Sandbox job could not be queued")
    finally:
        await pool.aclose()


class QueuedSandboxRunner:
    def __init__(
        self, *, workspace_id: str, agent_run_id: str, repository_id: str
    ) -> None:
        self.workspace_id = workspace_id
        self.agent_run_id = agent_run_id
        self.repository_id = repository_id
        self.attempt = 0

    async def run(
        self,
        *,
        repository_root: Path,
        patched_files: dict[str, str | None],
        plan: CheckPlan,
    ) -> list[CheckResult]:
        self.attempt += 1
        files = await asyncio.to_thread(
            snapshot_repository, repository_root, patched_files
        )
        pool = None
        results: list[CheckResult] = []
        try:
            pool = await create_pool(RedisSettings.from_dsn(settings.REDIS_URL))
            for stage, commands in (
                ("formatter", plan.formatter),
                ("static", plan.static),
                ("tests", plan.tests),
            ):
                for command in commands:
                    if command == "project test suite":
                        results.append(
                            CheckResult(
                                cast(Literal["formatter", "static", "tests"], stage),
                                command,
                                "skipped",
                                "No safe project-specific test command was selected.",
                            )
                        )
                        continue
                    job = await asyncio.to_thread(
                        create_execution_job,
                        workspace_id=self.workspace_id,
                        agent_run_id=self.agent_run_id,
                        repository_id=self.repository_id,
                        attempt=self.attempt,
                        stage=stage,
                        command=command,
                        files=files,
                    )
                    queued = await pool.enqueue_job(
                        "execute_sandbox_job",
                        job.id,
                        _job_id=job.id,
                        _queue_name=settings.SANDBOX_QUEUE,
                    )
                    if queued is None:
                        raise RuntimeError("Sandbox job could not be queued")
                    deadline = (
                        asyncio.get_running_loop().time()
                        + settings.SANDBOX_WALL_TIMEOUT_SECONDS
                        + 30
                    )
                    value = None
                    while asyncio.get_running_loop().time() < deadline:
                        value = await asyncio.to_thread(execution_job, job.id)
                        if value and value["status"] in {
                            "passed",
                            "failed",
                            "timed_out",
                        }:
                            break
                        await asyncio.sleep(0.25)
                    if not value or value["status"] not in {
                        "passed",
                        "failed",
                        "timed_out",
                    }:
                        results.append(
                            CheckResult(
                                cast(Literal["formatter", "static", "tests"], stage),
                                command,
                                "failed",
                                "Sandbox worker did not finish before the queue deadline.",
                            )
                        )
                        continue
                    output = "\n".join(
                        item
                        for item in (
                            str(value["stdout"]),
                            str(value["stderr"]),
                            str(value["error"] or ""),
                        )
                        if item
                    )
                    results.append(
                        CheckResult(
                            cast(Literal["formatter", "static", "tests"], stage),
                            command,
                            "passed" if value["status"] == "passed" else "failed",
                            output,
                            cast(int | None, value["exit_code"]),
                        )
                    )
        except Exception as exc:  # noqa: BLE001 - queue failure has a safe skip fallback
            if not results:
                for stage, commands in (
                    ("formatter", plan.formatter),
                    ("static", plan.static),
                    ("tests", plan.tests),
                ):
                    results.extend(
                        CheckResult(
                            cast(Literal["formatter", "static", "tests"], stage),
                            command,
                            "skipped",
                            f"Sandbox queue unavailable: {exc}",
                        )
                        for command in commands
                    )
        finally:
            if pool is not None:
                await pool.aclose()
        return results
