# Phase 8: queued secure sandbox execution

Phase 8 moves code and test execution out of the API process. The API can only
persist an `execution_jobs` row and enqueue its identifier on `queue:sandbox`.
Only `worker-sandbox` has Docker access, and it creates a fresh container for every
allow-listed command.

## Isolation contract

Each execution container is created with:

```text
network              none
root filesystem      read-only
/workspace           bounded tmpfs
memory               512 MiB default
CPU                  1 CPU default
processes             128 PIDs default
identity              UID/GID 65532
Linux capabilities    all dropped
security option       no-new-privileges
wall timeout          60 seconds default
```

The worker copies a bounded UTF-8 snapshot into tmpfs with `docker cp`; it never
mounts a repository or host project directory into the execution container. `.env`,
`.aws`, `.ssh`, `.gnupg`, package caches, VCS data, build output, and dependency
directories are excluded. No API/worker environment variables are forwarded.

Commands are argv arrays, never shell strings. The worker revalidates the stored
argv against a small formatter/static/test/run allow-list before execution. It
streams bounded stdout/stderr chunks into SQL while the run page polls job state,
then persists the exit code and duration. Timeout, startup failure, test failure,
and success all end in a forced `docker rm -f` cleanup.

## Enable locally

Sandbox execution is disabled by default. Build the two tool images and worker,
then enable it explicitly:

```powershell
docker compose --profile sandbox build sandbox-python sandbox-node worker-sandbox
$env:SANDBOX_EXECUTION_ENABLED = "true"
docker compose --profile sandbox up -d api worker-sandbox
```

The Python image contains Python 3.12, Pytest, and Ruff. The Node image contains
Node 22, npm, and TypeScript. Network remains disabled during jobs, so a repository
must be testable with the tools already present in its selected image. Project-
specific dependency images are a future extension.

`POST /api/v1/execution/run` queues bounded Python or JavaScript snippets using a
fixed filename and argv. Coding-agent formatter/static/test plans use the same job
pipeline. `GET /api/v1/execution/{job_id}` returns live state and bounded output.

## Verification

```powershell
cd backend
.\.phase2-venv\Scripts\python.exe -m pytest tests\test_phase8.py -q
.\.phase2-venv\Scripts\python.exe -m pytest tests -q
.\.phase2-venv\Scripts\python.exe -m ruff check app tests alembic
.\.phase2-venv\Scripts\python.exe -m ruff format --check app tests alembic

cd ..
docker compose config --quiet
```

The automated Phase 8 suite covers command injection rejection, secret stripping,
patched snapshot construction, infinite-loop timeout behavior, all required Docker
resource flags, absence of bind mounts, and cleanup after termination. A live Docker
smoke test passed on 2026-11-15 with captured stdout, exit code `0`, a 396 ms job
duration, and no residual sandbox container. The complete live adversarial matrix
remains a release gate; do not claim public-untrusted containment until it passes.

Recorded on 2026-11-15: 48 backend tests passed and four opt-in live Docling tests
were skipped. Four frontend tests, ESLint, TypeScript, the production build, both
Compose configurations, Ruff, formatting, and the 19-case router golden set passed.

Docker is an internal/portfolio MVP boundary, not protection against a determined
kernel-level attacker. Public untrusted multi-tenant execution requires stronger
isolation such as gVisor or Firecracker.
