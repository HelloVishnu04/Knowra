# OmniRAG — Phased Implementation Guide

**Project:** OmniRAG — Agentic Multi-RAG & AI Software Engineering Platform  
**Implementation baseline:** Version 1.0  
**Source:** `OmniRAG_Project_Implementation_Report.docx`  
**Execution model:** Solo-first, production-style capstone; modular monolith; Docker Compose  
**Estimated effort:** 76 person-days  
**Indicative calendar:** 15–16 weeks at a sustainable solo pace; 10–11 weeks at an aggressive 5-day/week pace

---

## 1. Purpose

This document converts the OmniRAG implementation report into an execution checklist that can be followed phase by phase.

The build must preserve these architectural rules from the source design:

1. OmniRAG is a **local-first, model-agnostic AI platform** covering document, web, SQL, code, and controlled execution workflows.
2. The platform is a **modular monolith**: one FastAPI backend, one Next.js frontend, and background workers, orchestrated with Docker Compose.
3. Every retriever implements a shared retrieval contract so the router can fan out to multiple sources without source-specific merge logic.
4. Model serving is hidden behind an `LLMProvider` / `LLMGateway` abstraction.
5. Retrieval must be scoped to the active workspace **before** context reaches the LLM.
6. Side-effecting actions require explicit **human-in-the-loop approval**.
7. Code execution must never run inside the API process; it must run in an isolated, resource-capped sandbox worker.
8. Evaluation is based on a golden dataset and automated metrics, not only subjective demo quality.
9. Secrets belong in environment configuration or a deployment secret store and never in source code or LLM context.

---

## 2. Target Architecture

```text
                    ┌────────────────────────────┐
                    │     Next.js / React UI      │
                    │ Chat / KB / Code / Runs     │
                    └──────────────┬─────────────┘
                                   │ REST + SSE
                                   ▼
                    ┌────────────────────────────┐
                    │        FastAPI API          │
                    │ Auth / API / SSE / Limits   │
                    └──────────────┬─────────────┘
                                   │
                                   ▼
                    ┌────────────────────────────┐
                    │    LangGraph Orchestrator   │
                    │ classify → plan → retrieve  │
                    │ → fuse/rerank → generate    │
                    │ → HITL → tool → trace       │
                    └───────┬────┬────┬────┬─────┘
                            │    │    │    │
                 ┌──────────┘    │    │    └──────────┐
                 ▼               ▼    ▼               ▼
          Document RAG       Web RAG SQL RAG       Code RAG
          Docling/Qdrant    Search API PG      Tree-sitter/Qdrant
                 └───────────────┬───────────────────┘
                                 ▼
                    ┌────────────────────────────┐
                    │     RRF + Cross-Encoder     │
                    │       Fusion / Rerank       │
                    └──────────────┬─────────────┘
                                   ▼
                    ┌────────────────────────────┐
                    │        LLM Gateway          │
                    │ Ollama / OpenAI / others    │
                    └──────────────┬─────────────┘
                                   ▼
                    ┌────────────────────────────┐
                    │ Answer + Citations + Trace  │
                    │ Diff + Streamed Run Events  │
                    └────────────────────────────┘

  Async infrastructure:
    Redis + ARQ → ingestion / indexing / sandbox jobs
    worker-ingest → document + code indexing
    worker-sandbox → disposable Docker execution containers

  Persistent infrastructure:
    PostgreSQL → identity, workspace, documents, chats, runs, audit
    Qdrant → dense + sparse vector retrieval
    Object Store → original files and execution artifacts
```

---

## 3. Technology Baseline

| Layer | Technology | Implementation role |
|---|---|---|
| Frontend | Next.js 14, React 18, TypeScript 5 | Application UI and streaming client |
| UI | Tailwind CSS + shadcn/ui | UI system |
| Data fetching | TanStack Query 5 | Caching, mutations, request state |
| Code editor | Monaco Editor | Code workspace + diff review |
| Backend | FastAPI + Pydantic v2 | Async API gateway |
| Orchestration | LangGraph + LangChain core | Router state machine + HITL |
| Local inference | Ollama | Chat, streaming, tool calls, embeddings |
| Coding model | Qwen3-Coder:30B Q4_K_M baseline | Coding workflow |
| Embeddings | embeddinggemma or qwen3-embedding | Vector embeddings |
| Reranking | BGE/Jina cross-encoder or Qdrant late interaction | Candidate reranking |
| Vector DB | Qdrant | Dense+sparse hybrid retrieval |
| Relational DB | PostgreSQL 16 | System of record + SQL RAG target |
| Queue/cache | Redis 7 + ARQ | Background jobs, cache, rate limiting |
| Document parsing | Docling + HybridChunker | PDF/DOCX/PPTX/XLSX ingestion |
| Code parsing | Tree-sitter | Symbol extraction + reference graph |
| Sandbox | Docker | Disposable execution environment |
| Git | GitPython + REST APIs | Local repo operations |
| Evaluation | Ragas + pytest | Retrieval/answer evaluation |
| Observability | LangSmith + Sentry + structlog | Traces, errors, structured logs |
| Metrics | OpenTelemetry + Prometheus + Grafana/APM | Runtime telemetry |
| Packaging | uv + `pyproject.toml` | Reproducible Python builds |
| Local deployment | Docker Compose v2 | Single-host orchestration |

### Local model rule

Keep model serving behind `LLMGateway` from the beginning. Provider/model changes must be configuration changes, not application-code rewrites.

Recommended logical roles:

```text
fast        → low-latency general chat / router work
coder       → code generation and repair
strong      → complex reasoning / synthesis
embedding   → vector generation
reranker    → fused candidate scoring
```

---

## 4. Repository Structure to Create

```text
omnirag/
├── backend/
│   ├── app/
│   │   ├── main.py
│   │   ├── core/
│   │   │   ├── config.py
│   │   │   ├── security.py
│   │   │   ├── logging.py
│   │   │   └── deps.py
│   │   ├── models/
│   │   ├── schemas/
│   │   ├── api/routes/
│   │   │   ├── auth.py
│   │   │   ├── chat.py
│   │   │   ├── documents.py
│   │   │   ├── knowledge_bases.py
│   │   │   ├── repositories.py
│   │   │   ├── code.py
│   │   │   ├── executions.py
│   │   │   ├── approvals.py
│   │   │   ├── runs.py
│   │   │   └── evaluation.py
│   │   ├── llm/
│   │   │   ├── base.py
│   │   │   ├── ollama_provider.py
│   │   │   ├── openai_provider.py
│   │   │   ├── anthropic_provider.py
│   │   │   └── gateway.py
│   │   ├── agents/
│   │   │   ├── graph.py
│   │   │   ├── router_agent.py
│   │   │   ├── code_agent.py
│   │   │   └── review_agent.py
│   │   ├── rag/
│   │   │   ├── base.py
│   │   │   ├── document_rag/
│   │   │   ├── web_rag/
│   │   │   ├── sql_rag/
│   │   │   └── code_rag/
│   │   ├── retrieval/
│   │   │   ├── fusion.py
│   │   │   └── reranking.py
│   │   ├── embeddings/
│   │   │   └── embedder.py
│   │   ├── execution/
│   │   │   ├── sandbox_client.py
│   │   │   └── patch_engine.py
│   │   ├── services/
│   │   │   ├── workspace_service.py
│   │   │   ├── citation_service.py
│   │   │   └── audit_service.py
│   │   ├── workers/
│   │   │   ├── ingest_worker.py
│   │   │   └── sandbox_worker.py
│   │   └── evaluation/
│   │       ├── golden_dataset.py
│   │       └── ragas_runner.py
│   ├── tests/
│   │   ├── unit/
│   │   ├── integration/
│   │   └── evaluation/
│   ├── alembic/
│   │   └── versions/
│   ├── pyproject.toml
│   └── Dockerfile
│
├── frontend/
│   ├── app/
│   │   ├── (auth)/login/page.tsx
│   │   ├── (dashboard)/
│   │   │   ├── layout.tsx
│   │   │   ├── page.tsx
│   │   │   ├── chat/[conversationId]/page.tsx
│   │   │   ├── knowledge-bases/page.tsx
│   │   │   ├── code/[repositoryId]/page.tsx
│   │   │   ├── runs/[runId]/page.tsx
│   │   │   ├── evaluation/page.tsx
│   │   │   └── settings/page.tsx
│   │   └── api/
│   ├── components/
│   └── ...
│
├── infra/
│   ├── docker-compose.yml
│   ├── prometheus/
│   ├── grafana/
│   └── stackhawk.yml
│
├── datasets/
│   └── eval/
│       └── golden.jsonl
│
├── docs/
│   ├── architecture.md
│   ├── security.md
│   ├── runbook.md
│   └── api.md
│
├── scripts/
├── .env.example
├── .gitignore
├── README.md
└── implementation.md
```

---

# 5. Phased Implementation Plan

## Phase 0 — Project Bootstrap and Engineering Guardrails

**Purpose:** Prepare a stable development baseline before the ten delivery phases.

**Recommended effort:** Treat as setup work inside Phase 1 rather than a separate project phase.

### Tasks

- [ ] Create Git repository.
- [ ] Create `backend/`, `frontend/`, `infra/`, `datasets/`, `docs/`, and `scripts/` directories.
- [ ] Initialize Python project with `uv` and `pyproject.toml`.
- [ ] Initialize Next.js + TypeScript App Router project.
- [ ] Add Tailwind CSS and shadcn/ui.
- [ ] Add Dockerfiles for backend and frontend.
- [ ] Create `.env.example` with placeholders only.
- [ ] Add `.env` to `.gitignore`.
- [ ] Add baseline formatter/linter/type-check configuration.
- [ ] Add `README.md` and this `implementation.md`.
- [ ] Create branch strategy: `main` + short-lived feature branches.
- [ ] Add a minimal pull-request checklist.
- [ ] Decide the target local inference hardware tier.

### Exit gate

- [ ] `docker compose config` succeeds.
- [ ] Backend installs with `uv sync`.
- [ ] Frontend installs/builds.
- [ ] Secrets are not tracked.
- [ ] First commit contains no credentials.

---

## Phase 1 — Local Chat Gateway

**Effort:** 6 person-days  
**Calendar target:** Weeks 1–2  
**Milestone:** Local streaming chat gateway demo

### Goal

Get a real end-to-end conversation working against a local Ollama model before adding any RAG complexity.

### Backend

- [ ] Scaffold FastAPI application factory in `app/main.py`.
- [ ] Add Pydantic Settings in `app/core/config.py`.
- [ ] Add structured logging with `structlog`.
- [ ] Add health endpoint(s).
- [ ] Add JWT auth foundations.
- [ ] Create `LLMProvider` abstract interface.
- [ ] Implement `OllamaProvider`.
- [ ] Implement `LLMGateway` role resolution.
- [ ] Add `/api/v1/auth/*` endpoints.
- [ ] Add `/api/v1/chat` endpoint.
- [ ] Start with non-streaming response path to validate the provider.
- [ ] Add SSE token streaming.
- [ ] Give every request a `run_id` / trace identifier.

### Frontend

- [ ] Create login page.
- [ ] Create dashboard shell.
- [ ] Build Chat page.
- [ ] Create chat composer and message list.
- [ ] Implement SSE client hook.
- [ ] Render streamed assistant tokens incrementally.
- [ ] Show selected model/provider in a non-sensitive settings area.

### Infrastructure

Create the first Compose baseline:

```text
frontend
api
ollama
postgres
redis
```

Qdrant and sandbox workers can be added to the Compose file as subsequent phases mature.

### Suggested API

```http
POST /api/v1/auth/register
POST /api/v1/auth/login
POST /api/v1/auth/refresh
POST /api/v1/chat
GET  /api/v1/conversations
```

### Definition of Done

A user can type a message in the UI and receive a streamed response from a local Ollama model. The model is selected entirely from configuration.

### Phase tests

- [ ] Provider unit tests.
- [ ] JWT authentication tests.
- [ ] `/chat` integration test with mocked provider.
- [ ] Ollama live smoke test.
- [ ] Frontend SSE stream test.
- [ ] Docker Compose smoke test.

### Phase 1 freeze

Do **not** begin router-agent work yet. The base provider and streaming path must be stable first.

---

## Phase 2 — Document RAG

**Effort:** 10 person-days  
**Calendar target:** Weeks 3–4  
**Milestone:** Document upload + grounded Q&A with citations

### Goal

Introduce the first real knowledge source and establish the retrieval abstraction used by every later RAG mode.

### Data layer

Implement PostgreSQL migrations for:

- [ ] `organizations`
- [ ] `workspaces`
- [ ] `users`
- [ ] `workspace_members`
- [ ] `knowledge_bases`
- [ ] `documents`
- [ ] `document_versions`
- [ ] `document_chunks`
- [ ] `conversations`
- [ ] `messages`

### Document ingestion pipeline

```text
Upload
  ↓
Persist original file
  ↓
Create document row (pending)
  ↓
ARQ ingest job
  ↓
Docling parse
  ↓
HybridChunker
  ↓
Embedding generation
  ↓
Qdrant upsert
  ↓
Document status = ready
```

### Tasks

- [ ] Implement multipart document upload.
- [ ] Store originals behind an `ObjectStore` abstraction.
- [ ] Add local filesystem object storage for development.
- [ ] Add S3-compatible option for later deployment.
- [ ] Parse PDF/DOCX/PPTX/XLSX via Docling.
- [ ] Use structure-aware chunking.
- [ ] Persist page/section metadata.
- [ ] Create `documents_kb` collection.
- [ ] Add dense vector + sparse-vector structure to the collection design, even if Phase 2 retrieval initially uses dense-only querying.
- [ ] Create ARQ ingestion worker.
- [ ] Implement document status transitions:
  - `pending`
  - `parsing`
  - `chunking`
  - `embedding`
  - `ready`
  - `failed`
- [ ] Implement `RetrievedChunk` and `RetrievalResult`.
- [ ] Implement `DocumentRetriever`.
- [ ] Add citations linked to document chunks.
- [ ] Add KB list/create UI.
- [ ] Add document upload UI.
- [ ] Add document indexing status UI.

### Common retrieval contract

Implement before adding other retrievers:

```python
class RetrievedChunk(BaseModel):
    id: str
    content: str
    source: str
    score: float
    metadata: dict

class RetrievalResult(BaseModel):
    source: str
    query: str
    chunks: list[RetrievedChunk]
    latency_ms: int

class Retriever(ABC):
    async def retrieve(
        self,
        query: str,
        *,
        workspace_id: str,
        top_k: int = 20,
        filters: dict | None = None,
    ) -> RetrievalResult: ...
```

### Definition of Done

Document upload completes indexing, the user can ask a question about the document, and the assistant answers from retrieved content with a page/section citation.

### Phase tests

- [ ] Parser tests for representative PDF/DOCX/PPTX/XLSX fixtures.
- [ ] Chunking unit tests.
- [ ] Embedding/upsert integration tests.
- [ ] Workspace-filtered retrieval test.
- [ ] Citation rendering test.
- [ ] End-to-end upload → ingest → chat test.

### Phase 2 freeze

Do not implement the agentic router yet. Validate dense retrieval quality first so later hybrid improvements have a measurable baseline.

---

## Phase 3 — Hybrid Retrieval + Reranking

**Effort:** 7 person-days  
**Calendar target:** Week 5  
**Milestone:** Hybrid retrieval live; first evaluation baseline

### Goal

Move from vector-only retrieval to dense + sparse retrieval with RRF and reranking.

### Tasks

- [ ] Add sparse BM25 named vector to `documents_kb`.
- [ ] Re-index existing document chunks.
- [ ] Implement Qdrant `Prefetch` for dense and sparse candidates.
- [ ] Use Qdrant `FusionQuery(RRF)` for within-collection hybrid retrieval.
- [ ] Add cross-source RRF helper for later document/web/SQL/code fusion.
- [ ] Integrate BGE/Jina reranker or Qdrant late-interaction approach.
- [ ] Limit reranking input to a bounded candidate set.
- [ ] Create at least 15 document-route golden cases.
- [ ] Build the first Ragas evaluation runner.
- [ ] Record the dense-only baseline.
- [ ] Compare hybrid retrieval against baseline.

### Retrieval flow

```text
query
 ├── dense search ──┐
 └── sparse search ─┤
                    ▼
                 RRF fuse
                    ▼
               top candidate set
                    ▼
                 reranker
                    ▼
              RetrievalResult
```

### Definition of Done

Hybrid retrieval measurably improves context precision/recall over the Phase 2 dense-only baseline on at least three identifier-heavy queries.

### Phase tests

- [ ] Dense retrieval regression suite.
- [ ] Sparse retrieval regression suite.
- [ ] RRF ranking unit tests.
- [ ] Reranker integration tests.
- [ ] Ragas baseline report committed to `datasets/eval/`.

---

## Phase 4 — Agentic Router + Full Trace

**Effort:** 8 person-days  
**Calendar target:** Weeks 6–7  
**Milestone:** Agentic router + Runs/Traces UI

### Goal

Replace hard-coded route selection with a LangGraph state machine that can choose document, web, SQL, code, or multi-source routing.

### Agent state

```python
class AgentState(TypedDict):
    conversation_id: str
    workspace_id: str
    user_query: str
    route: Literal["document", "web", "sql", "code", "multi"]
    retrieval_results: list[RetrievalResult]
    fused_chunks: list[RetrievedChunk]
    pending_tool_call: ToolCallRequest | None
    approval_status: Literal["not_required", "pending", "approved", "rejected"]
    answer: str
    citations: list[dict]
```

### Graph

```text
classify_intent
      ↓
plan_route
      ↓
retrieve
      ↓
fuse_rerank
      ↓
generate
   ↙     ↘
tool?     no tool
  ↓          ↓
await      persist_trace
approval
  ↓
execute_tool
  ↓
persist_trace
```

### Tasks

- [ ] Implement `classify_intent`.
- [ ] Implement `plan_route`.
- [ ] Implement multi-source fan-out.
- [ ] Use `asyncio.gather` for independent retrievers.
- [ ] Implement cross-source fusion.
- [ ] Persist `agent_runs`.
- [ ] Persist `retrieval_runs`.
- [ ] Persist `citations`.
- [ ] Persist `tool_calls`.
- [ ] Add LangGraph Redis checkpointer.
- [ ] Implement `interrupt()` for approval gates.
- [ ] Create `/runs/{id}` endpoint.
- [ ] Build Runs/Traces screen.
- [ ] Show route, retrievals, rerank scores, model calls, citations, and statuses.
- [ ] Add router cases to the golden dataset.

### Route contract

```text
document → DocumentRetriever
web      → WebRetriever
sql      → SqlRetriever
code     → CodeRetriever
multi    → 2+ retrievers in parallel + cross-source RRF + rerank
```

### Definition of Done

For every chat request, the UI can show a persisted trace from route decision → retrieval → rerank → generation, linked by `run_id`.

### Phase tests

- [ ] Router classification tests.
- [ ] Multi-RAG fan-out test.
- [ ] Trace persistence tests.
- [ ] Resume-after-interrupt test.
- [ ] UI trace rendering test.

---

## Phase 5 — SQL RAG + Database Guardrails

**Effort:** 6 person-days  
**Calendar target:** Week 8  
**Milestone:** SQL RAG live with read-only guardrails

### Goal

Allow natural-language analytical questions against an explicit, controlled database schema without granting the model unrestricted SQL power.

### Security-first architecture

```text
User question
   ↓
Schema introspection
   ↓
NL → SQL generation
   ↓
sqlglot AST parse
   ↓
Allow-list validation
   ↓
LIMIT + statement timeout
   ↓
Optional sensitive-data HITL approval
   ↓
Read-only execution
   ↓
Result explanation + trace
```

### Tasks

- [ ] Provision a dedicated read-only PostgreSQL role.
- [ ] Explicitly allow-list tables/views.
- [ ] Implement schema introspection.
- [ ] Implement natural-language-to-SQL generation.
- [ ] Validate generated SQL using an AST parser such as `sqlglot`.
- [ ] Reject non-`SELECT` statements.
- [ ] Reject references outside the allow-list.
- [ ] Enforce a default row limit.
- [ ] Enforce connection-level statement timeout.
- [ ] Tag sensitive tables/views in configuration.
- [ ] Require HITL approval for sensitive-table reads and SQL mutations.
- [ ] Persist the generated SQL into the trace.
- [ ] Display generated SQL to the user in an inspectable panel.

### Definition of Done

A natural-language analytical question against the allow-listed schema returns a correct, read-only, time-bounded result and shows the generated SQL.

### Phase tests

- [ ] AST rejects `INSERT`, `UPDATE`, `DELETE`, `DROP`, etc.
- [ ] Table allow-list bypass tests.
- [ ] Timeout enforcement test.
- [ ] Row-limit enforcement test.
- [ ] Sensitive-table approval test.
- [ ] SQL retrieval trace test.

---

## Phase 6 — Code RAG + Code Workspace

**Effort:** 10 person-days  
**Calendar target:** Weeks 9–10  
**Milestone:** Code RAG + Code Workspace UI

### Goal

Index software repositories by semantic code symbols rather than treating source code as ordinary document text.

### Repository ingestion

```text
Upload ZIP / Git URL / local path
            ↓
clone / unpack
            ↓
respect .gitignore
            ↓
exclude node_modules / dist / vendor / binaries
            ↓
language detection
            ↓
Tree-sitter parse
            ↓
symbol extraction
            ↓
reference graph
            ↓
embedding
            ↓
Postgres + Qdrant
```

### Tasks

- [ ] Create `repositories` table.
- [ ] Create `code_symbols` table.
- [ ] Implement ZIP ingestion.
- [ ] Implement Git URL ingestion.
- [ ] Implement local-path ingestion for controlled local development.
- [ ] Detect supported languages.
- [ ] Parse with Tree-sitter grammars.
- [ ] Extract function/method/class/interface/module symbols.
- [ ] Preserve start/end line ranges.
- [ ] Build import/call reference graph.
- [ ] Implement `find_references()`.
- [ ] Embed symbol source text + concise signature/docstring metadata.
- [ ] Upsert symbols into `code_symbols` Qdrant collection.
- [ ] Persist symbol metadata in PostgreSQL.
- [ ] Implement `CodeRetriever`.

### Code agent read-only tools to establish now

```text
search_code(query, top_k)
read_file(path, start, end)
find_references(symbol)
git_diff()
```

All code retrieval must be repository/workspace filtered. `read_file` must reject path traversal.

### Frontend

- [ ] Repository list.
- [ ] Repository indexing status.
- [ ] Repository tree.
- [ ] Monaco code editor.
- [ ] Symbol search.
- [ ] File/line citation links.
- [ ] Reference search panel.

### Definition of Done

On an indexed repository, `search_code("JWT validation")` returns the correct function/symbol with an accurate file and line range, and the Code Workspace can render it.

### Phase tests

- [ ] Parser fixture suite.
- [ ] Symbol extraction tests.
- [ ] Reference graph tests.
- [ ] Path traversal tests.
- [ ] Code retrieval accuracy cases.
- [ ] UI file/line navigation test.

---

## Phase 7 — Coding Agent

**Effort:** 10 person-days  
**Calendar target:** Weeks 11–12  
**Milestone:** Patch → test → repair loop

### Goal

Turn the Code RAG foundation into a controlled software-engineering workflow.

### Coding loop

```text
understand_task
      ↓
retrieve_repository_context
      ↓
plan_change
      ↓
generate_patch
      ↓
formatter + static checks
      ↓
run_tests
   ↙       ↘
pass       fail
 ↓           ↓
review      analyze_failure
             ↓
          repair_patch
             ↓
          run_tests
             ↓
         max 3 iterations
             ↓
          human review
```

### Tools

```text
search_code     → read-only
read_file      → read-only, repo-root allow-list
find_references→ read-only
create_patch   → generates a diff only; never auto-applies
git_diff       → read-only
run_tests      → sandboxed execution
run_code       → sandboxed execution

git_commit     → explicit approval required; never auto-push
```

### Tasks

- [ ] Implement `create_patch`.
- [ ] Implement unified-diff generation.
- [ ] Add formatter/static analysis stage.
- [ ] Add test selection.
- [ ] Add failure-analysis step.
- [ ] Add repair loop.
- [ ] Cap repair loop at three iterations.
- [ ] Persist each attempt in the run trace.
- [ ] Render diff in Monaco.
- [ ] Add explicit approval UI.
- [ ] Add approve / edit / reject flow.
- [ ] Add code-route evaluation cases.
- [ ] Include at least one multi-file change case.

### Definition of Done

For a representative feature request, the agent generates a correct reviewable diff, runs affected tests, and self-repairs at least one seeded failing case within three iterations before human approval.

### Phase tests

- [ ] Patch parse/apply tests.
- [ ] Diff integrity tests.
- [ ] Formatter/static-check integration tests.
- [ ] Repair-loop termination test.
- [ ] Approval state-machine test.
- [ ] Code golden subset regression test.

---

## Phase 8 — Secure Sandbox Execution

**Effort:** 6 person-days  
**Calendar target:** Week 13  
**Milestone:** Hardened sandbox + adversarial testing

### Goal

Execute generated code safely enough for an internal/portfolio MVP while clearly documenting the security boundary limitation.

### Critical rule

The API process must **never** call arbitrary subprocesses or Docker directly. Execution requests go through the `queue:sandbox` ARQ queue and are consumed by `worker-sandbox`.

### Baseline sandbox controls

```text
network_mode = none
read_only    = true
tmpfs        = /workspace
memory cap   = 512 MB baseline
CPU cap      = 1 CPU baseline
pids cap     = 128
non-root UID
no-new-privileges
wall-clock timeout
throwaway container per attempt
remove container after completion
```

### Tasks

- [ ] Build `worker-sandbox`.
- [ ] Create per-language sandbox base images.
- [ ] Dispatch jobs through ARQ.
- [ ] Implement `run_code`.
- [ ] Implement `run_tests`.
- [ ] Capture stdout/stderr.
- [ ] Persist `execution_jobs`.
- [ ] Persist exit code and duration.
- [ ] Stream output/state to UI.
- [ ] Ensure no secrets are injected into the sandbox.
- [ ] Ensure no host project directories are mounted directly.
- [ ] Ensure network is disabled.
- [ ] Clean up execution containers on success, failure, and timeout.

### Adversarial tests

- [ ] Infinite loop.
- [ ] Fork bomb/process explosion attempt.
- [ ] Disk-fill attempt.
- [ ] Network escape attempt.
- [ ] Timeout.
- [ ] Resource exhaustion.
- [ ] Container cleanup after crash.

### Definition of Done

All adversarial sandbox tests are contained, and execution output reaches the UI within the configured timeout.

### Explicit MVP limitation

Docker is the baseline isolation mechanism for the portfolio/internal build. It is not a hard security boundary against a determined kernel-level attacker. Public untrusted multi-tenant execution requires a stronger future runtime such as gVisor or Firecracker.

---

## Phase 9 — Security + Multi-Tenancy Hardening

**Effort:** 6 person-days  
**Calendar target:** Week 14  
**Milestone:** Cross-tenant isolation + first DAST pass

### Goal

Prove that users can only retrieve and operate on data belonging to their authorized workspace and that agent actions are auditable.

### Workspace enforcement

Enforce workspace filtering:

- [ ] API routes.
- [ ] Document retriever.
- [ ] Code retriever.
- [ ] SQL RAG.
- [ ] Web evidence where workspace policy requires it.
- [ ] Conversation access.
- [ ] Run/trace access.
- [ ] Approval access.

### Prompt injection defense

Retrieved content is untrusted data.

Implementation rules:

```text
<retrieved_evidence>
  ...untrusted document/web/code/sql evidence...
</retrieved_evidence>
```

- [ ] System prompt explicitly says evidence is not instructions.
- [ ] Never execute tools because retrieved text says to execute them.
- [ ] Only accept model-generated structured tool calls that match registered schemas.
- [ ] Sanitize/truncate fetched web content before context insertion.

### Audit trail

Persist immutable records for:

- [ ] tool calls.
- [ ] approvals.
- [ ] execution jobs.
- [ ] workspace membership changes.
- [ ] model configuration changes.
- [ ] knowledge-base permission changes.

### Secrets

- [ ] Keep `.env` out of version control.
- [ ] Maintain `.env.example` with placeholders.
- [ ] Use deployment secret storage in staging/production.
- [ ] Never bake secrets into container images.
- [ ] Redact secrets from structured logs.

### Security testing

- [ ] Cross-workspace retrieval test.
- [ ] Authorization bypass tests.
- [ ] Prompt-injection regression cases.
- [ ] `bandit`.
- [ ] `pip-audit`.
- [ ] `npm audit --production`.
- [ ] HawkScan DAST on staging.
- [ ] Fix all high/critical findings before exit.

### Definition of Done

Cross-tenant isolation passes with zero leaks and staging has zero unresolved high/critical DAST findings.

---

## Phase 10 — Evaluation, Observability, Documentation, Release

**Effort:** 7 person-days  
**Calendar target:** Weeks 15–16  
**Milestone:** Demo-ready release

### Goal

Turn the system from a working demo into a measurable, traceable, documented release candidate.

### Evaluation dataset

Grow the golden dataset to at least **50 cases across all five route categories**:

```text
document
web
sql
code
multi
```

Include positive, ambiguous, identifier-heavy, cross-source, security-sensitive, and failure-recovery cases.

### Required release thresholds

| Metric | Threshold | Release impact |
|---|---:|---|
| Route selection accuracy | ≥ 0.90 | Block |
| Context precision | ≥ 0.75 | Block |
| Context recall | ≥ 0.80 | Block |
| Faithfulness | ≥ 0.85 | Block |
| Answer relevancy | ≥ 0.80 | Warn only by itself |
| Code patch test-pass rate | ≥ 0.90 on code subset | Block |

### Observability

Implement:

- [ ] Structured JSON logs.
- [ ] `run_id` on every relevant log event.
- [ ] LangSmith tracing for LangGraph/model/tool activity.
- [ ] OpenTelemetry spans around retrievers, fusion/rerank, and LLM gateway.
- [ ] Sentry exception reporting.
- [ ] Prometheus metrics.
- [ ] Grafana/APM dashboards.

### Baseline dashboards

Track:

- [ ] P50/P95/P99 request latency.
- [ ] Time-to-first-token.
- [ ] Route distribution.
- [ ] Retrieval candidate counts.
- [ ] Rerank latency.
- [ ] Model tokens/sec.
- [ ] Model queue time.
- [ ] Sandbox executions/minute.
- [ ] Sandbox average duration.
- [ ] Sandbox timeout rate.
- [ ] Error rate by route/tool/provider.
- [ ] Container RAM/VRAM/CPU.

### Baseline alerts

- [ ] P95 chat latency > 8s for 5 consecutive minutes → warning.
- [ ] Error rate > 5% over 5 minutes → critical.
- [ ] Sandbox timeout rate > 10% over 15 minutes → warning.
- [ ] Failed agent runs > 3× rolling baseline → warning.
- [ ] Qdrant/Postgres storage > 85% → warning; >95% → critical.

### Documentation

Create:

- [ ] `docs/architecture.md`
- [ ] `docs/security.md`
- [ ] `docs/runbook.md`
- [ ] `docs/api.md`
- [ ] deployment instructions.
- [ ] environment-variable reference.
- [ ] local model setup instructions.
- [ ] evaluation instructions.
- [ ] sandbox limitations and upgrade path.
- [ ] troubleshooting guide.

### Demo flows

Record/test at minimum:

1. **Document:** “What is the leave policy?”
2. **Web:** “What happened in AI news today?”
3. **SQL:** “Which product had the highest Q4 revenue?”
4. **Code:** “Where is JWT verification implemented?”
5. **Coding Agent:** “Add rate limiting to this FastAPI API.”
6. **Multi-RAG:** “Compare our revenue with current industry growth.”

### Definition of Done

All release acceptance criteria pass, the evaluation harness runs in CI and blocks regressions below threshold, and staging dashboards/alerts are live.

---

# 6. Cross-Phase Definition of Done

Every phase should satisfy the following before moving forward:

```text
[ ] Code complete
[ ] Unit tests written
[ ] Integration tests written where applicable
[ ] Error handling complete
[ ] Logs/traces added
[ ] Documentation updated
[ ] No known high/critical security issue
[ ] Docker/local environment reproducible
[ ] Demo path works
[ ] Phase-specific acceptance criterion passes
```

Do not mark a phase complete because a feature “works on one machine.”

---

# 7. Database Implementation Order

Create PostgreSQL migrations in dependency order.

```text
organizations
    ↓
workspaces
    ↓
users + workspace_members
    ↓
knowledge_bases
    ↓
documents
    ↓
document_versions
    ↓
document_chunks

repositories
    ↓
code_symbols

conversations
    ↓
messages
    ↓
retrieval_runs
    ↓
citations

agent_runs
    ↓
tool_calls
    ↓
approvals
    ↓
execution_jobs

feedback
evaluation_cases
```

### Required indexes

At minimum, mirror the source report's recommended indexes for:

- documents by knowledge base.
- documents by workspace.
- document chunks by document.
- conversations by workspace/user.
- messages by conversation/time.
- agent runs by conversation/time.
- tool calls by agent run/status.
- citations by message.
- code symbols by repository/symbol.

---

# 8. Qdrant Implementation Order

## Collection: `documents_kb`

Required payload concepts:

```text
workspace_id
knowledge_base_id
document_id
chunk_index
page_number
section_path
permissions
```

Vectors:

```text
dense → cosine
bm25  → sparse / IDF
```

## Collection: `code_symbols`

Required payload concepts:

```text
workspace_id
repository_id
file_path
language
symbol_name
symbol_type
class_name
start_line
end_line
commit_sha
```

### Security rule

Build the Qdrant filter from workspace identity before executing vector search. Never retrieve broadly and filter after retrieval.

---

# 9. Redis / Queue Design

Use the following key conventions:

```text
cache:route:{hash(query)}
cache:embed:{hash(text)}
ratelimit:{user_id}:{window}
queue:ingest
queue:sandbox
stream:run:{run_id}
lock:repo_index:{repository_id}
```

### Queue responsibilities

| Queue/job | Purpose |
|---|---|
| `queue:ingest` | Document/code indexing |
| `queue:sandbox` | Code/test execution |
| `recompute_embeddings` | Re-embed data after model changes |
| `run_evaluation_batch` | Execute golden evaluations |
| `purge_expired_locks` | Safety cleanup |

---

# 10. Object Storage Layout

Use an `ObjectStore` interface so local storage and S3-compatible storage can be swapped.

```text
s3://omnirag-{env}/
  workspaces/{workspace_id}/
    documents/{document_id}/{version}/original.{ext}
    repositories/{repository_id}/snapshots/{commit_sha}.tar.gz
    executions/{execution_job_id}/stdout.log
    executions/{execution_job_id}/stderr.log
    executions/{execution_job_id}/artifacts/...
```

Development can use the local filesystem; staging/production can use MinIO or S3-compatible storage.

---

# 11. API Build Order

All APIs live under `/api/v1`.

## Foundation

```text
POST /auth/register
POST /auth/login
POST /auth/refresh
```

## Chat

```text
POST /chat
GET  /conversations
```

## Knowledge

```text
POST /knowledge-bases
POST /documents
GET  /documents/{id}
```

## Code

```text
POST /repositories
GET  /repositories/{id}
POST /code/search
POST /code/patch
```

## Execution / governance

```text
POST /executions
GET  /executions/{id}
POST /approvals/{id}
GET  /runs/{id}
```

## Evaluation / feedback

```text
GET  /evaluation/cases
POST /evaluation/run
POST /feedback
```

### API rule

Use FastAPI's generated OpenAPI schema as the source of truth for frontend typing.

---

# 12. Frontend Build Order

```text
1. Login
2. Dashboard shell
3. Chat + SSE
4. Knowledge Bases
5. Document Upload
6. Run / Trace screen
7. SQL result inspection
8. Repository list
9. Code Workspace
10. Monaco diff review
11. Approval UI
12. Execution output panel
13. Evaluation dashboard
14. Settings / provider configuration
```

### Frontend state model

The Chat and Code Workspace pages are client components because they hold streaming/live state. Read-mostly dashboard/settings pages can use server components.

Suggested component groups:

```text
components/chat/
components/knowledge/
components/code/
components/runs/
components/approvals/
components/evaluation/
components/ui/
```

---

# 13. Testing Strategy

## Unit tests

Focus on pure logic:

- [ ] RRF/fusion math.
- [ ] Chunking.
- [ ] SQL AST validation.
- [ ] Patch generation/application.
- [ ] Path allow-listing.
- [ ] Router classification helpers.

### Unit coverage target

At least 85% on high-value retrieval/chunking/patch modules.

## Integration tests

Test real component boundaries:

- [ ] API ↔ PostgreSQL.
- [ ] Retriever ↔ Qdrant.
- [ ] Worker ↔ queue.
- [ ] Sandbox worker ↔ Docker.
- [ ] API ↔ LLM provider contract.

### Integration coverage target

At least 80% on key API/retriever modules.

## Contract tests

Every `LLMProvider` implementation must pass the same provider contract suite.

## End-to-end tests

Use Playwright/scripted API flows for all golden scenarios.

## Security tests

- [ ] SAST.
- [ ] Dependency audit.
- [ ] DAST.
- [ ] Multi-tenant isolation.
- [ ] Prompt injection.
- [ ] SQL guardrail bypass.
- [ ] Sandbox containment.

---

# 14. CI/CD Implementation

The pipeline should fail early and cheaply.

```text
Pull Request / main push
          ↓
backend lint
          ↓
backend type-check
          ↓
backend unit + integration tests
          ↓
frontend checks
          ↓
SAST / dependency audit
          ↓
evaluation dataset
          ↓
stage app
          ↓
HawkScan DAST
          ↓
build images
          ↓
push images
```

### Baseline backend checks

```bash
uv sync --frozen
uv run ruff check .
uv run mypy app
uv run pytest tests/unit tests/integration --cov=app --cov-fail-under=80
uv run bandit -r app -ll
```

### Frontend baseline

```bash
npm ci
npm run lint
npm run build
npm audit --production
```

### Evaluation gate

Run the golden dataset in CI and fail the pipeline when release-blocking thresholds are missed.

---

# 15. Environment Promotion

## Local

Purpose: feature development and manual testing.

```text
Ollama
Seed workspace
Sample fixtures
Docker Compose
```

## CI

Purpose: deterministic tests/evaluation/security checks.

```text
Small model or mocked provider
Golden dataset
Ephemeral services
```

## Staging

Purpose: pre-release verification and demo.

```text
GPU-equipped local host / Tier 2–3
Synthetic or anonymized data
Full observability
DAST
```

## Production (optional MVP deployment)

Purpose: real usage.

```text
Local Ollama or cloud fallback
Real tenant data
Backups
Secret store
```

---

# 16. Scaling Path

Keep the modular monolith until scale justifies extraction.

```text
Stage 1 → single host, Docker Compose
Stage 2 → multiple API replicas behind a load balancer
Stage 3 → dedicated ingest/sandbox hosts
Stage 4 → extract highest-traffic RAG modality
Stage 5 → managed PostgreSQL/Qdrant + orchestrator if justified
```

Do not introduce Kubernetes or microservices simply because they are available. The MVP architecture is intentionally optimized for low operational overhead.

---

# 17. Hardware Planning for Local Inference

Use hardware to select the model, not the other way around.

| Tier | Approx. capability | Intended use |
|---|---|---|
| Tier 1 | 16–32 GB RAM, 6–12 core CPU | 4B–8B models, CPU-first development |
| Tier 2 | 32–64 GB RAM + 12–16 GB VRAM | 8B–14B models |
| Tier 3 | 64 GB RAM + ~24 GB VRAM | Recommended coding workstation; Qwen3-Coder:30B Q4 class |
| Tier 4 | 128 GB+ RAM, high-end GPU | 30B+ / multiple concurrent models |
| Tier 5 | 250 GB+ memory class | Server-class huge local models |

For a practical coding-focused build, Tier 3 is the target baseline when hardware permits; smaller models can be used during development because the gateway is provider/model agnostic.

---

# 18. Risk Management During Implementation

| Risk | Implementation response |
|---|---|
| Local model quality too weak | Keep role-based model selection and cloud fallback behind gateway |
| Retrieval misses evidence | Hybrid search + metadata filters + reranking + query rewriting |
| Context becomes too large | Tune Top-K and add context compression where required |
| Agent loops | LangGraph state + max 3 iterations + timeouts |
| Sandbox abuse | Layered controls + no network + no secrets + future microVM path |
| Cross-tenant leakage | Pre-retrieval workspace filters + isolation tests |
| Model drift | Pin model tags and benchmark before upgrades |
| Hardware bottleneck | Start with smaller models and benchmark early |
| Scope creep | Keep documented non-goals and defer non-blocking requests |
| Weak evaluation dataset | Grow golden cases every phase |

---

# 19. Project Non-Goals for MVP

Do not let these become accidental blockers:

- Multi-node Kubernetes scaling.
- MicroVM-grade sandbox isolation.
- GitHub/GitLab PR automation beyond local diff review.
- OCR/vision extraction for scanned PDFs.
- Custom model training or fine-tuning.

These belong in the post-MVP roadmap unless a release gate explicitly depends on them.

---

# 20. Recommended Daily Development Loop

For every feature:

```text
1. Read the phase task.
2. Define the smallest testable unit.
3. Implement backend contract.
4. Implement persistence/retrieval behavior.
5. Add frontend surface.
6. Add logs/trace fields.
7. Add unit + integration test.
8. Run local Docker stack.
9. Run the phase-specific demo.
10. Update the phase checklist.
```

For AI features, always test both:

```text
happy path
failure / adversarial path
```

---

# 21. Recommended Git Commit Sequence

A predictable commit structure makes the project easier to review.

```text
chore: bootstrap repository
feat(api): scaffold fastapi gateway
feat(llm): add provider abstraction
feat(llm): add ollama provider
feat(chat): add sse streaming
feat(db): add workspace and document schema
feat(rag): add docling ingestion
feat(rag): add qdrant document retriever
feat(rag): add hybrid retrieval
feat(agent): add langgraph router
feat(sql): add guarded sql retriever
feat(code): add tree-sitter indexing
feat(code-agent): add patch workflow
feat(sandbox): add execution worker
feat(security): add workspace isolation
feat(eval): add golden evaluation runner
feat(obs): add telemetry dashboards
docs: add runbook and architecture docs
```

---

# 22. Definition-of-Release Checklist

The MVP is ready only when every item below is checked.

### Core platform

- [ ] Streamed local chat works.
- [ ] Model choice is configuration-driven.
- [ ] Four retrievers exist and share the retrieval contract.
- [ ] Multi-source retrieval can run in parallel.
- [ ] Hybrid retrieval is default for Qdrant knowledge-bearing collections.

### Grounding

- [ ] Document answers have citations.
- [ ] Web answers have source citations.
- [ ] SQL answers show generated SQL.
- [ ] Code answers show file/line ranges.
- [ ] Multi-RAG answers expose source-level trace information.

### Agent safety

- [ ] Side effects require approval.
- [ ] Tool calls are schema validated.
- [ ] Approval decisions are persisted.
- [ ] Code execution is outside the API process.
- [ ] Sandbox is network disabled.
- [ ] Sandbox has resource/time limits.

### Security

- [ ] Workspace isolation tests pass.
- [ ] Secrets are absent from source and image builds.
- [ ] SQL allow-list is enforced.
- [ ] Prompt injection defenses are active.
- [ ] SAST passes.
- [ ] Dependency audit passes.
- [ ] DAST has no unresolved high/critical findings.

### Evaluation

- [ ] Golden dataset has at least 50 cases.
- [ ] Route accuracy ≥ 0.90.
- [ ] Context precision ≥ 0.75.
- [ ] Context recall ≥ 0.80.
- [ ] Faithfulness ≥ 0.85.
- [ ] Answer relevancy ≥ 0.80.
- [ ] Code patch test-pass rate ≥ 0.90.

### Operations

- [ ] Logs contain `run_id`.
- [ ] Tracing works.
- [ ] Error reporting works.
- [ ] Metrics dashboards work.
- [ ] Alerts are configured.
- [ ] Backup/restore procedure is documented.
- [ ] Runbook is complete.

### Demo

- [ ] Document RAG demo recorded.
- [ ] Web RAG demo recorded.
- [ ] SQL RAG demo recorded.
- [ ] Code RAG demo recorded.
- [ ] Coding Agent demo recorded.
- [ ] Multi-RAG demo recorded.

---

# 23. Calendar View

| Week | Phase | Primary milestone |
|---:|---|---|
| 1–2 | Phase 1 | Local streaming chat gateway |
| 3–4 | Phase 2 | Document upload + citations |
| 5 | Phase 3 | Hybrid retrieval + baseline |
| 6–7 | Phase 4 | Agentic router + traces |
| 8 | Phase 5 | SQL RAG + guardrails |
| 9–10 | Phase 6 | Code RAG + Code Workspace |
| 11–12 | Phase 7 | Coding agent loop |
| 13 | Phase 8 | Sandbox execution |
| 14 | Phase 9 | Security/multi-tenancy hardening |
| 15–16 | Phase 10 | Evaluation + observability + release |

---

# 24. Final Build Order Rule

**Do not reorder the major phases without a strong engineering reason.**

The intended dependency chain is:

```text
Local LLM Gateway
      ↓
Document RAG
      ↓
Hybrid Retrieval
      ↓
Evaluation Baseline
      ↓
Agentic Router
      ↓
SQL RAG
      ↓
Code RAG
      ↓
Coding Agent
      ↓
Sandbox
      ↓
Security Hardening
      ↓
Evaluation + Observability + Release
```

The most important discipline is to establish the shared interfaces early and postpone complexity until the preceding layer has measurable quality.

In particular:

- Keep the **LLM Gateway** abstract from day one.
- Build **hybrid retrieval** before spending time on broad retrieval optimization.
- Apply **workspace filters before retrieval** rather than after generation.
- Require **human approval for every side-effecting tool**.
- Grow the **golden evaluation dataset throughout the project**.
- Keep execution outside the API process.
- Treat the full run trace as a first-class product capability, not a debug-only feature.

---

# 25. Phase Tracking Template

Copy this block for each phase during development.

```markdown
## Phase X — <Name>

Status: NOT STARTED
Owner: <name>
Start date: YYYY-MM-DD
Target finish: YYYY-MM-DD

### Tasks
- [ ] task 1
- [ ] task 2
- [ ] task 3

### Tests
- [ ] unit
- [ ] integration
- [ ] e2e
- [ ] security/evaluation as applicable

### Evidence
- PR:
- Demo:
- Evaluation report:
- Logs/trace:

### Definition of Done
- [ ] phase-specific acceptance criterion passes

### Notes
-
```

---

# 26. Source Alignment Note

This implementation guide is a phased execution rendering of the supplied **OmniRAG Project Implementation Report v1.0**. The source report defines the architecture, technology stack, database design, API contract, RAG abstractions, LangGraph flow, sandbox model, CI/CD approach, evaluation thresholds, risk register, acceptance criteria, and 10-phase delivery plan. This file reorganizes those decisions into a practical build sequence and adds execution checklists without changing the project's core architecture or stated MVP boundaries.
