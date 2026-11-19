# Phase 11 — repository reliability foundation

Implemented on 17 November 2026. This is a tested foundation, not completion of
every Phase 11 production gate in the [roadmap](production-implementation-plan.md).

## Behavior

- Imports and reindex requests commit a PostgreSQL job and outbox entry in the
  same transaction as the repository change. Redis failure leaves accepted work
  pending, rather than losing the request or requiring another upload.
- The ingestion worker dispatches outbox entries at startup and every 15 seconds
  when it has capacity. Pending deliveries repeat after 60 seconds, including
  after Redis loses its queue. Duplicate deliveries cannot claim an active lease.
- Jobs have a 30-minute deadline including queue time, a 90-second lease, and a
  heartbeat every 20 seconds. Expired worker leases retry up to three attempts.
  Explicit processing errors require manual retry. Status reads also reconcile
  overdue jobs, so an absent worker does not leave the UI indefinitely processing.
- The repository row serializes scheduling; repeated requests while its current
  job is active return that job. Every database publication checks the current
  lease, deadline, active job, and the submitting user's workspace write access.
  Removed or downgraded memberships cancel subsequent work. Cancel invalidates
  the lease immediately; an already running file parser can take up to its timeout
  to exit. It cannot publish after cancellation.
- Files, symbols, and embeddings have independent states. A checkout is browsable
  as soon as it is published. Legacy checkouts are inspected on disk, including
  repositories previously stuck in `parsing` or marked `failed`. Empty text files
  open correctly. The code screen refreshes the tree when source availability
  changes, shows partial-parser warnings, and supplies cancel/retry/reindex actions.
- Reindex uses the existing directory. It never clones, extracts, or resets it.
  ZIP archive paths now have a typed persistent field and remain in legacy metadata
  for compatibility. Metadata updates merge rather than discard the archive path.
- Initial Git and ZIP acquisition happens in a unique staging directory. Only a
  valid lease may publish it, and an existing checkout is never replaced. If a
  process stops between rename and database commit, the retry reuses the directory.
- Each supported source file is parsed in a separate Python process. Native crashes,
  invalid output, and timeouts become per-file warnings. Successful symbols remain
  searchable without embeddings; previously stored symbols for failed files are
  retained. Reference edges are rebuilt from the successfully parsed files.
- Repository embeddings are opt-in. New vector points use a separate generation;
  only a completed upload activates it. Failed/stale generations never replace
  older vector points. During or after a failed rebuild, semantic retrieval is
  disabled because the SQL symbol graph may have changed; old vectors are retained
  for future versioned rollback, not served against mismatched symbols.

## Configuration and rollout

Back up existing data using the Phase 9 procedures before applying migrations.
Stop old ingestion workers before upgrading: they do not enforce the new leases.
Migration `0012` adds job/outbox tables, state fields, and ZIP archive references.
It neither deletes nor moves repository files, and does not guess legacy filesystem
availability in SQL.

```powershell
cd backend
alembic upgrade head
```

Rebuild/restart the API and ingestion worker together. Pre-migration Redis
`ingest_repository` messages are intentionally ignored: use **Reindex existing
files** or **Retry import** in the code screen to create authorized durable jobs.
No historical worktree is automatically recloned.

| Setting | Default | Meaning |
|---|---|---|
| `CODE_INDEX_EMBEDDINGS` | `false` | Enable vector indexing only with an explicitly configured embedding runtime. |
| `CODE_PARSER_TIMEOUT_SECONDS` | `20` | Maximum time for one native parser child. |
| `CODE_PARSER_MEMORY_MB` | `512` | Child address-space limit on Linux. |

Parser input retains the existing `CODE_MAX_SOURCE_BYTES` limit; output is bounded
at 32 MiB. Linux also enforces the output file limit and disables core dumps.
Windows uses process isolation, the timeout, and input/output checks; it does not
yet impose a Windows Job Object memory limit. No model artifacts are downloaded
by the new repository processing path.

New API routes are workspace-scoped: `GET /repositories/{id}/job`,
`POST /repositories/{id}/retry`, and `POST /repositories/{id}/cancel`.
`POST /repositories/{id}/reindex` requires an existing checkout. Mutations require
owner, administrator, or member access. The job response omits internal lease
tokens and filesystem paths.

## Verification and remaining gates

Local verification: **107 backend tests passed, 4 optional tests skipped**;
frontend tests (4), lint, TypeScript checks, and the production build passed.
Backend Ruff lint/format checks and Compose configuration validation also passed.
Windows sandbox restrictions required running asyncio tests and the Next.js build
outside the sandbox. No live application database was migrated during this work.

Regression coverage in `backend/tests/test_phase11.py` uses isolated databases,
temporary worktrees, real parser subprocesses, and fake queues/model providers.
It covers transactional rollback, duplicate scheduling/claiming, stale leases,
bounded recovery, membership revocation, queue loss, ZIP reindex preserving edits,
partial parsing, empty files, cross-workspace denial, Redis-outage acceptance,
native child exit/timeout, staged acquisition, deadline reconciliation without a
worker, and retaining vector generations after a partial failed upload.

Migration `0011:0012` generates PostgreSQL upgrade SQL successfully. A full-history
offline SQL export still fails in pre-existing migration `0001`'s untyped seed
insert; this is separate from the new migration. Docker Desktop was stopped during
local verification, so live PostgreSQL migration/concurrency, Redis restart, Linux
parser resource limits, and production-container checks still need CI/staging.

Remaining Phase 11 work includes immutable source snapshots/manifests, explicit
fetch/ref/history controls, private Git credentials, LFS/submodule reporting,
Git-aware nested ignore inventories, unsupported-language lexical content search,
incremental parsing, retained SQL graph generations, safe orphan-generation/staging
cleanup, disk quotas, failed-file-only retry, and real multi-worker fault injection.
Document ingestion still uses its earlier queue path; these durable jobs currently
cover repositories only. Phase 10's remaining production gates also remain open.
