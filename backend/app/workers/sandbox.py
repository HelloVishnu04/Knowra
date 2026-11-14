import asyncio
import io
import shlex
import subprocess
import tarfile
import tempfile
import threading
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import ClassVar

from arq.connections import RedisSettings

from app.code.sources import safe_repository_path
from app.core.config import settings
from app.core.database import SessionLocal
from app.models.runs import ExecutionJob
from app.sandbox.queue import command_argv


def _now() -> datetime:
    return datetime.now(UTC)


def _set_running(job_id: str) -> None:
    with SessionLocal.begin() as session:
        job = session.get(ExecutionJob, job_id)
        if job is not None:
            job.status = "running"
            job.started_at = _now()


def _append_output(job_id: str, field: str, value: str) -> None:
    if not value:
        return
    with SessionLocal.begin() as session:
        job = session.get(ExecutionJob, job_id)
        if job is None:
            return
        current = str(getattr(job, field) or "")
        setattr(job, field, (current + value)[-settings.SANDBOX_OUTPUT_BYTES :])


def _complete(
    job_id: str,
    *,
    status: str,
    exit_code: int | None,
    duration_ms: int,
    error: str | None = None,
) -> None:
    with SessionLocal.begin() as session:
        job = session.get(ExecutionJob, job_id)
        if job is not None:
            job.status = status
            job.exit_code = exit_code
            job.duration_ms = duration_ms
            job.error = error
            job.completed_at = _now()


def _docker(*arguments: str, timeout: int = 30) -> subprocess.CompletedProcess[str]:
    try:
        return subprocess.run(
            ["docker", *arguments],
            check=True,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
    except subprocess.CalledProcessError as exc:
        details = (exc.stderr or exc.stdout or str(exc)).strip()
        raise RuntimeError(f"docker {arguments[0]} failed: {details}") from exc


def _materialize(root: Path, files: dict[str, str]) -> None:
    for relative, value in files.items():
        target = safe_repository_path(root, relative)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(value, encoding="utf-8")


def _copy_workspace(container: str, root: Path) -> None:
    """Stream files into the writable tmpfs without using docker cp."""
    payload = io.BytesIO()
    with tarfile.open(fileobj=payload, mode="w") as archive:
        for path in sorted(root.rglob("*")):
            archive.add(
                path,
                arcname=path.relative_to(root).as_posix(),
                recursive=False,
            )
    result = subprocess.run(
        [
            "docker",
            "exec",
            "-i",
            "--user",
            "65532:65532",
            "--workdir",
            "/workspace",
            container,
            "tar",
            "-x",
            "-C",
            "/workspace",
        ],
        input=payload.getvalue(),
        check=False,
        capture_output=True,
        timeout=30,
    )
    if result.returncode != 0:
        details = (result.stderr or result.stdout or b"").decode(
            "utf-8", errors="replace"
        )
        raise RuntimeError(f"Workspace transfer failed: {details.strip()}")


def _drain(pipe, job_id: str, field: str) -> None:
    while True:
        value = pipe.read(4096)
        if not value:
            break
        _append_output(job_id, field, value)


def _execute_sync(job_id: str) -> None:
    with SessionLocal() as session:
        job = session.get(ExecutionJob, job_id)
        if job is None or job.status != "queued":
            return
        argv = [str(item) for item in job.command_json]
        image = str(job.image)
        files = {str(key): str(value) for key, value in job.files_json.items()}
    if command_argv(shlex.join(argv)) != argv:
        _complete(
            job_id,
            status="failed",
            exit_code=None,
            duration_ms=0,
            error="Stored command failed the sandbox allow-list",
        )
        return

    started = time.monotonic()
    container = f"knowra-sandbox-{job_id}"
    created = False
    _set_running(job_id)
    try:
        with tempfile.TemporaryDirectory(prefix="knowra-sandbox-") as directory:
            root = Path(directory)
            _materialize(root, files)
            _docker(
                "create",
                "--name",
                container,
                "--network",
                "none",
                "--read-only",
                "--tmpfs",
                "/workspace:rw,nosuid,nodev,mode=1777,size=268435456",
                "--memory",
                str(settings.SANDBOX_MEMORY_BYTES),
                "--cpus",
                "1",
                "--pids-limit",
                str(settings.SANDBOX_PIDS_LIMIT),
                "--user",
                "65532:65532",
                "--security-opt",
                "no-new-privileges:true",
                "--cap-drop",
                "ALL",
                image,
                "tail",
                "-f",
                "/dev/null",
            )
            created = True
            _docker("start", container)
            _copy_workspace(container, root)
            process = subprocess.Popen(
                [
                    "docker",
                    "exec",
                    "--user",
                    "65532:65532",
                    "--workdir",
                    "/workspace",
                    container,
                    *argv,
                ],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )
            stdout_thread = threading.Thread(
                target=_drain, args=(process.stdout, job_id, "stdout"), daemon=True
            )
            stderr_thread = threading.Thread(
                target=_drain, args=(process.stderr, job_id, "stderr"), daemon=True
            )
            stdout_thread.start()
            stderr_thread.start()
            try:
                exit_code = process.wait(timeout=settings.SANDBOX_WALL_TIMEOUT_SECONDS)
                status = "passed" if exit_code == 0 else "failed"
                error = None
            except subprocess.TimeoutExpired:
                _docker("kill", container, timeout=15)
                process.terminate()
                try:
                    process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    process.kill()
                exit_code = None
                status = "timed_out"
                error = "Execution exceeded the wall-clock timeout"
            stdout_thread.join(timeout=5)
            stderr_thread.join(timeout=5)
            _complete(
                job_id,
                status=status,
                exit_code=exit_code,
                duration_ms=int((time.monotonic() - started) * 1000),
                error=error,
            )
    except Exception as exc:
        _complete(
            job_id,
            status="failed",
            exit_code=None,
            duration_ms=int((time.monotonic() - started) * 1000),
            error=str(exc)[:2000],
        )
        raise
    finally:
        if created:
            subprocess.run(
                ["docker", "rm", "-f", container],
                check=False,
                capture_output=True,
                text=True,
                timeout=30,
            )


async def execute_sandbox_job(ctx, job_id: str) -> None:
    del ctx
    await asyncio.to_thread(_execute_sync, job_id)


class WorkerSettings:
    functions: ClassVar = [execute_sandbox_job]
    redis_settings = RedisSettings.from_dsn(settings.REDIS_URL)
    queue_name = settings.SANDBOX_QUEUE
    max_jobs = 1
    job_timeout = settings.SANDBOX_WALL_TIMEOUT_SECONDS + 120
    max_tries = 1
