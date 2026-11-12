# Phase 2: document knowledge bases

The local workspace supports knowledge-base creation, multipart uploads, background
indexing, grounded chat and clickable chunk citations. Supported uploads are PDF,
DOCX, PPTX and XLSX (25 MB default maximum).

## Start locally

1. Start Docker Desktop (Linux containers).
2. Run `docker compose up --build -d` from the repository root. The API applies
   Alembic migrations after PostgreSQL becomes healthy; the worker waits for the API.
3. Run `docker compose exec ollama ollama pull embeddinggemma` and
   `docker compose exec ollama ollama pull qwen:0.5b`. Larger chat models such as
   `qwen:7b` are optional and require substantially more disk and memory.
4. Open http://localhost:3000/knowledge, create a knowledge base and upload a file.
5. Wait for `ready`, then use “Ask questions about this knowledge base”.
   Answers use numbered citations; click a source to inspect the stored excerpt.
6. Inspect failures with `docker compose logs worker-ingest`. After correcting the
   cause, use “Retry indexing”. The first conversion/chunking may download Docling
   models and the configured tokenizer; the worker caches these in `model_cache`.

This is a single-user local development setup. Authentication remains the Phase 1
stub. Workspace identity is fixed by server configuration, never supplied by the
browser. Compose publishes ports only on loopback. Do not expose this deployment
to other users until real authentication and membership checks are implemented.

## Pipeline and data

The API stores the original using an `ObjectStore`, inserts document/version rows,
and enqueues an ARQ job. The worker transitions through pending, parsing, chunking,
embedding and ready (or failed), converts with Docling, chunks using HybridChunker,
stores text/provenance in PostgreSQL, embeds via Ollama and upserts Qdrant vectors.
Qdrant has named dense and sparse vector slots; only dense search is used in Phase 2.
Deterministic chunk IDs make retry upserts safe. SQL readiness is checked during
retrieval so a failed or partially indexed document cannot supply context.

All queries filter workspace, knowledge base and embedding model before vector
search. SQL then checks ownership and readiness again. The retriever returns the
shared `RetrievedChunk`/`RetrievalResult` contract. Empty results produce an explicit
no-content answer. Citation labels include page numbers when the source format
provides them, and section headings otherwise. Retrieved sources are displayed
separately from the model's numbered claims; their presence alone does not prove
every generated claim is supported.

For host development, copy `.env.example` to `backend/.env`, use Python 3.12,
`uv sync --frozen`, `uv run alembic upgrade head`, `uv run uvicorn app.main:app`,
and a second terminal with `uv run arq app.workers.ingest.WorkerSettings`.
The frontend uses `NEXT_PUBLIC_API_URL` at build time (default localhost:8000).

Local originals persist in `object_data`. The S3 adapter uses `OBJECT_STORE=s3`,
`S3_BUCKET`, optional `S3_ENDPOINT_URL`, and standard AWS credentials. Configure
these identically for API and worker. Configure a new collection and reindex if
changing the embedding model/dimensions. Production file scanning, per-user
authorization, quotas, document deletion/version replacement, queue crash
reconciliation and answer-quality evaluation remain follow-up work.

## Verification

Run `uv run pytest tests` in backend; run `npm run lint` and `npx tsc --noEmit`
in frontend; `npm test` (Node 22.18+ or 24) checks streaming boundaries. The build
uses Webpack because the installed Turbopack crashes during CSS processing on this
Windows machine. Fonts use the system stack so building does not need Google Fonts.
The automated pipeline tests mock external model/vector calls while
exercising SQL, upload, worker transitions, ownership filters, citations and chat.
They do not establish real parser or retrieval quality. The acceptance gate also
requires live PDF/DOCX/PPTX/XLSX indexing and a grounded answer with the local models.
With the full dependencies and model artifacts available, set `RUN_DOCLING_TESTS=1`
and run `uv run pytest tests/test_docling.py` to generate and convert all four formats.

API: GET/POST `/api/v1/knowledge-bases`, GET/POST
`/api/v1/knowledge-bases/{id}/documents`, POST
`/api/v1/knowledge-bases/{id}/documents/{document_id}/retry`, GET
`/api/v1/chunks/{chunk_id}`, and POST `/api/v1/chat` with `knowledge_base_id`.

## Verification recorded on 2026-11-06

- Backend: 6 tests passed, including migration upgrade/downgrade and the mocked
  upload/index/retrieve/chat flow. Four real Docling format tests were skipped.
- Frontend: lint, TypeScript, 2 stream-boundary tests, and Webpack production build passed.
- Compose configuration and dependency lockfile consistency checks passed.
- Live Docker, PostgreSQL, Redis, Qdrant, Docling and Ollama acceptance remains
  pending: Docker Desktop's Linux engine was not running during implementation.
- Backend tests used an isolated `.phase2-venv`; the pre-existing `.venv` still
  references a missing interpreter. Recreate the development environment using
  Python 3.12 before running the full dependency set.
