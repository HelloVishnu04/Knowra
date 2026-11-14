# Phase 5: guarded SQL retrieval

Phase 5 adds natural-language analytical queries over an explicit PostgreSQL
allow-list. The SQL route introspects only configured tables, asks the selected
model for one PostgreSQL query, parses it with `sqlglot`, and executes it through
a dedicated read-only database role.

## Guardrail pipeline

Every generated statement must pass all of these checks before execution:

1. It parses as exactly one PostgreSQL query.
2. The root is a `SELECT`/query expression and contains no nested DML, DDL,
   administrative command, `SELECT INTO`, or locking clause.
3. Every physical table resolves to `SQL_ALLOWED_TABLES`; CTE aliases cannot be
   used to bypass the allow-list.
4. SQL functions must be on a small analytical-function allow-list; server,
   file, settings, extension, and side-effecting functions are rejected.
5. A configured maximum `LIMIT` is inserted or clamps a larger limit.
6. PostgreSQL executes the query inside a read-only transaction with a local
   `statement_timeout`.

Tables in `SQL_SENSITIVE_TABLES` are prepared and shown in the run trace, but not
executed until the user approves the persisted `sql_query` tool call. The resumed
run re-parses the approved SQL and verifies its table set before execution.

## Configuration

The Compose defaults expose two application metadata tables to SQL retrieval:

```dotenv
SQL_DATABASE_URL=postgresql://knowra_reader:reader-password@postgres:5432/omnirag
SQL_ALLOWED_TABLES=public.knowledge_bases,public.documents
SQL_SENSITIVE_TABLES=public.documents
DEFAULT_ROW_LIMIT=100
STATEMENT_TIMEOUT_MS=10000
```

An empty `SQL_ALLOWED_TABLES` disables SQL execution. Treat the allow-list as a
security boundary: add purpose-built analytical views rather than broad
application tables, and put any view containing personal or confidential data in
the sensitive list.

On a fresh Compose database, `infra/postgres/001_readonly.sql` creates the
`knowra_reader` login and grants present and future tables read-only access. Docker
only runs initialization scripts when the database volume is first created. For
an existing development volume, apply the script once without deleting data:

```powershell
Get-Content .\infra\postgres\001_readonly.sql |
  docker compose exec -T postgres psql -U user -d omnirag
```

Use a secret-managed password and narrower schema grants outside local
development.

## User and trace behavior

Questions containing SQL/database/aggregation intent route to the SQL retriever.
The answer is grounded in a synthetic SQL result excerpt. The run detail page
shows a dedicated **Generated SQL** panel, the guardrail trace event, result
metadata, citations, and any approval decision.

## Verification

From `backend`:

```powershell
uv run pytest tests/test_phase5.py
uv run pytest tests
uv run ruff check app tests alembic
uv run ruff format --check app tests alembic
```

From `frontend`:

```powershell
npm test
npm run lint
npx tsc --noEmit
npm run build
```

The Phase 5 suite covers mutation rejection, allow-list bypasses, timeout setup,
row-limit enforcement, sensitive-table approval/resume, SQL result retrieval, and
trace persistence.

Recorded on 2026-11-14: 26 backend tests passed and four opt-in live Docling
format tests were skipped; the 15-case Phase 5 suite passed. Three frontend tests,
ESLint, TypeScript, the Webpack production build, Ruff, formatting, lockfile
resolution, and Docker Compose configuration also passed. A live Compose SQL
smoke test was not run because Docker Desktop was not running.
