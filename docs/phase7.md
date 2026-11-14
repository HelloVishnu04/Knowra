# Phase 7: reviewable coding agent

Phase 7 turns repository retrieval into a controlled patch workflow. Change-oriented
code requests retrieve repository symbols, produce a small implementation plan,
generate a git-style unified diff, validate it against the current files entirely
in memory, select relevant checks, and repair a failing attempt at most three times.

## Safety boundary

Generated patches are artifacts, not filesystem operations. The API rejects path
traversal, malformed hunks, mismatched context, duplicate file changes, binary
patches, renames, and copies. Validation applies the patch to an in-memory file map;
the repository is never modified. Approval records a review decision only and does
not apply, commit, or push the diff.

The formatter, static-analysis, and test stages use an injectable runner. Phase 7
ships a deferred production runner because the API process must not execute model-
generated commands. The repair-loop tests use a deterministic isolated fake runner
to prove selection, failure analysis, repair, the three-attempt cap, and trace
persistence. Phase 8 replaces the adapter with the queued throwaway-container
sandbox and enables live execution.

## Review flow

Every attempt is persisted in `coding_attempts`, including the plan, complete diff,
check results, status, and failure output. A successful candidate creates a
`create_patch` approval:

- **Approve patch** accepts the generated artifact for handoff.
- **Edit patch** opens the unified diff in Monaco, validates the replacement, marks
  prior checks invalidated, and records reviewer approval.
- **Reject** records the decision and ends the run without side effects.

The run detail page displays all attempts, commands selected for formatter/static/
test stages, check output, and the final diff in a Monaco editor.

## Verification

From `backend`:

```powershell
.\.phase2-venv\Scripts\python.exe -m pytest tests\test_phase7.py -q
.\.phase2-venv\Scripts\python.exe -m pytest tests -q
.\.phase2-venv\Scripts\python.exe -m ruff check app tests alembic
.\.phase2-venv\Scripts\python.exe -m ruff format --check app tests alembic
```

From `frontend`:

```powershell
npm test
npm run lint
npx tsc --noEmit
npm run build
```

Recorded on 2026-11-15: 41 backend tests passed and four opt-in live Docling
format tests were skipped. The Phase 7 suite covers multi-file patch integrity,
in-memory application, a seeded failing check repaired on attempt two, durable
attempt traces, edited approval, and proof that review does not modify the source
repository. Four frontend tests, ESLint, TypeScript, and the production build passed.
