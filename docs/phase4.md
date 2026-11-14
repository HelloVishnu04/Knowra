# Phase 4: agentic router and persisted run traces

Phase 4 replaces the chat endpoint's document-specific branch with a LangGraph
state machine. Every request now receives a durable `run_id` and passes through
classification, route planning, retrieval, cross-source fusion/reranking,
generation, optional approval, and trace persistence.

## Runtime flow

The router recognizes `direct`, `document`, `web`, `sql`, `code`, and `multi`
routes. A selected knowledge base participates as the document source. Independent
retrievers are called concurrently with `asyncio.gather`; a failed or unavailable
source is recorded without hiding successful source results. Cross-source rankings
use RRF and the configured reranker when enabled.

Only `DocumentRetriever` is production-configured in Phase 4. Web, SQL, and code
routes are classified and traced, but report that their source is unavailable
until their implementations arrive in Phases 5 and 6. The retriever registry is
injectable, and the Phase 4 fan-out test exercises all four source contracts in
parallel.

The graph streams model tokens while it runs. SQL persists `agent_runs`,
`retrieval_runs`, `citations`, and `tool_calls`; the run row also contains ordered
node events, route decisions, fusion/rerank scores, and model-call metadata. Open
`/runs` in the frontend or follow **View run trace** from an assistant response.

## Checkpointing and approvals

Compose now runs Redis 8 because the LangGraph Redis saver requires RedisJSON and
RediSearch. The API initializes the indices at startup. Host development falls
back to an in-memory saver when Redis is unavailable, so ordinary chat remains
usable, but approval pauses do not survive an API restart in that fallback mode.
Set `LANGGRAPH_CHECKPOINTER=memory` explicitly for isolated tests.

Tool execution is approval-first. A graph containing a `pending_tool_call` stops
at LangGraph `interrupt()`; `POST /api/v1/runs/{run_id}/approval` resumes the saved
thread with an approve/reject decision. No production side-effecting tools are
registered in this phase. Later phases can add handlers without bypassing the
approval node.

## API

- `GET /api/v1/runs` lists recent workspace-scoped runs.
- `GET /api/v1/runs/{run_id}` returns the full persisted trace.
- `POST /api/v1/runs/{run_id}/approval` resumes a paused run.
- `POST /api/v1/chat` accepts optional `route` (`auto` by default) and returns or
  streams `run_id`, selected route, citations, and status.

## Verification

From `backend`:

```powershell
uv run pytest tests
uv run ruff check app tests alembic
uv run python -m app.eval.router
```

From `frontend`:

```powershell
npm test
npm run lint
npx tsc --noEmit
npm run build
```

Recorded on 2026-11-14: 11 backend tests passed and four opt-in live Docling
format tests were skipped. The 16-case router golden set reached 1.0 route
accuracy. Three frontend tests, ESLint, TypeScript, the Webpack production build,
Docker Compose configuration, Ruff, formatting, and the 239-package uv lockfile
all passed.
