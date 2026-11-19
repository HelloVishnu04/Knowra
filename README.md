# Knowra

Local document knowledge bases and grounded chat using Next.js, FastAPI, Ollama,
PostgreSQL, Qdrant and an ARQ ingestion worker.

## Requirements

- Docker Desktop running Linux containers
- An internet connection for the first container-image download
- Enough free disk space for the application containers and document-processing cache

## Start the application

Run these commands in PowerShell from the repository root:

```powershell
# Build and start the containerized application services in the background.
docker compose up --build -d

# Confirm that every container is running.
docker compose ps
```

Open the application after the container-image downloads finish:

- Knowledge bases and document upload: http://localhost:3000/knowledge
- Chat: http://localhost:3000/chat
- Runs and traces: http://localhost:3000/runs
- Code workspace: http://localhost:3000/code
- Workspace access and audit: http://localhost:3000/settings/access
- API health: http://localhost:8000/health
- API documentation: http://localhost:8000/docs
- Qdrant dashboard: http://localhost:6333/dashboard

Create an account on the login screen, then create a knowledge base or connect a
repository. Each new account receives its own workspace. API access is resolved
through workspace membership, and viewer memberships cannot mutate workspace
resources.

Knowra does not download LLM, embedding, reranking, OCR, or tokenizer models at
startup. File browsing and the application shell work without a model provider;
configure an existing local or remote provider from **Models & Providers** when
you want generation features.

If this workspace already contains ready Phase 2 documents, re-index their stored
chunks into the Phase 3 dense + BM25 collection once:

```powershell
docker compose exec api python -m app.workers.reindex
```

## Logs and status

```powershell
docker compose ps
docker compose logs -f api frontend worker-ingest
docker compose logs -f qdrant postgres redis
```

If a document shows `failed`, inspect `worker-ingest`, correct the reported issue,
and use **Retry indexing** in the interface.

## Stop or restart

```powershell
# Stop containers while preserving databases, uploaded files and model caches.
docker compose down

# Restart an existing installation.
docker compose up -d

# Rebuild after source or dependency changes.
docker compose up --build -d
```

Do not add `-v` to `docker compose down` unless you intentionally want to remove
the PostgreSQL, Qdrant, Redis, uploaded-file and model volumes.

## Development and architecture

See [Phase 2 setup and verification](docs/phase2.md) for the ingestion foundation
and host-development commands. See [Phase 3 hybrid retrieval](docs/phase3.md) for
BM25, RRF, reranking, reindexing and evaluation. See
[Phase 4 agent routing and traces](docs/phase4.md) for LangGraph routing, Redis
checkpointing, run inspection, and approval resume behavior. See
[Phase 5 guarded SQL retrieval](docs/phase5.md) for the read-only database role,
table allow-list, AST validation, timeouts, and sensitive-table approvals.
See [Phase 6 code RAG and workspace](docs/phase6.md) for repository ingestion,
Tree-sitter symbol indexing, reference graphs, code search, and Monaco navigation.
See [Phase 7 coding agent](docs/phase7.md) for diff-only patch generation, bounded
repair attempts, persisted checks, and approve/edit/reject review in Monaco.
See [Phase 8 sandbox execution](docs/phase8.md) for the dedicated Redis queue,
throwaway Docker worker, resource limits, streamed output, and adversarial gates.
See the [production implementation plan](docs/production-implementation-plan.md)
for Phases 9–22 and the [Phase 11 repository reliability foundation](docs/phase11.md)
for durable repository jobs, crash-isolated parsing, preserved checkouts, and
model-free file browsing and symbol search. Repository embeddings are opt-in with
`CODE_INDEX_EMBEDDINGS=true`; reindexing preserves existing files. Apply migration
`0012` and restart both API and ingestion worker before using this foundation.
The current Phase 10 foundation provides account authentication,
personal workspaces, membership-derived API scope, owner/member/viewer mutation
rules, personal provider isolation, revocable login sessions, and rotating refresh
credentials with replay detection. Cookie-authenticated mutations use double-submit
CSRF validation, while browser origins come from `CORS_ALLOWED_ORIGINS`. Owners and
administrators can manage workspace membership, protected roles preserve a final
owner, and every membership change produces a durable audit event. Account
registration can be disabled, failed sign-ins are persistently throttled by account
and client address, and production mode rejects weak authentication settings.
Provider create, update, and delete operations are audited without storing API keys.
Production provider requests also reject loopback, private, link-local, and metadata
destinations after DNS resolution; trusted internal provider hostnames require an
explicit `PROVIDER_PRIVATE_HOST_ALLOWLIST` entry. Account recovery, broader audit
coverage, and the remaining Phase 10 production gates are
still planned work.
After applying migration `0008`, users with an older stateless login token must
sign in again so Knowra can create a revocable server-side session.

The Compose setup enables authentication by default. Replace `JWT_SECRET` in the
environment before sharing a deployment, keep it bound to trusted interfaces, and
set `AUTH_COOKIE_SECURE=true` when the application is served over HTTPS.
For a hosted deployment, set `APP_ENVIRONMENT=production`, use a unique secret of
at least 32 characters, and set `REGISTRATION_ENABLED=false` until an invitation or
verified signup policy is ready. Production also requires
`PROVIDER_BLOCK_PRIVATE_NETWORKS=true`; keep the private-host allowlist empty unless
Knowra intentionally connects to a trusted internal model service.

### Rotate provider encryption keys

Provider credentials use a versioned keyring independent of `JWT_SECRET`. Generate
Fernet keys with `python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"`, then configure a JSON keyring such as
`PROVIDER_ENCRYPTION_KEYS={"2026-11":"...","2026-06":"..."}` and select the
write key with `PROVIDER_ENCRYPTION_ACTIVE_KEY_ID=2026-11`. Keep the previous key
available while running:

```powershell
cd backend
alembic upgrade head
python -m app.cli.rotate_provider_keys
```

The command first decrypts and verifies every stored provider credential, then
rewrites all older versions in one database transaction and emits audit events.
After a verified backup and successful rotation, remove retired keys and set
`PROVIDER_ALLOW_LEGACY_JWT_KEY=false` once no `legacy-jwt-v0` records remain.
