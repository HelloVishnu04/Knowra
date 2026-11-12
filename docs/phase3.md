# Phase 3: hybrid retrieval and reranking

Phase 3 adds BM25 sparse retrieval to the existing Ollama dense embeddings, fuses
both candidate lists with Qdrant reciprocal-rank fusion (RRF), and optionally
reranks a bounded shortlist with the local `BAAI/bge-reranker-base` cross-encoder.

## Upgrade and reindex

1. Rebuild the images with `docker compose up --build -d`. Qdrant is pinned to
   v1.20.0 because the BM25 document inference used by this phase requires a recent
   server. The API image includes FastEmbed.
2. Keep `QDRANT_COLLECTION=documents_kb_phase3`, or choose another new collection
   name. A fresh name prevents Phase 2 points without sparse vectors from mixing
   with Phase 3 points.
3. Re-index every ready SQL chunk with
   `docker compose exec api python -m app.workers.reindex`. The command is
   idempotent because chunk IDs are deterministic and Qdrant upserts replace points.
4. The first reranked query downloads the configured BGE ONNX model into the shared
   `model_cache` volume. Set `RERANKER_ENABLED=false` to run dense+BM25 RRF without
   the cross-encoder.

Each dense and sparse prefetch applies workspace, knowledge-base, dense-model and
sparse-model filters. The fused candidate count is bounded at 100 (40 by default),
and reranking is bounded independently (20 by default). PostgreSQL still verifies
that every returned chunk belongs to a ready document before content is exposed.
If the reranker cannot load or score, retrieval logs the error and safely falls back
to the fused RRF order.

## Evaluation baseline

Upload `datasets/eval/phase3_identifier_corpus.md` to a knowledge base and wait for
it to become ready. From `backend`, install the optional Ragas dependency and run:

```powershell
uv sync --extra eval
uv run python -m app.eval.document_retrieval --kb-id <knowledge-base-id>
```

The runner executes the 15 identifier-heavy golden cases in
`datasets/eval/document_route_golden.jsonl` against dense-only, hybrid RRF, and
hybrid+reranker modes. It records Ragas ID-based context precision/recall, MRR and
latency under `datasets/eval/reports/`. Use `--skip-ragas` for the equivalent local
ID calculations. A live report is required before claiming that Phase 3 improves
the Phase 2 baseline; the automated tests verify mechanics, not retrieval quality.

## Verification

Run backend tests, lint and type checks as in Phase 2. Phase 3 tests additionally
cover sparse collection configuration, BM25 point payloads, hybrid prefetch/RRF
query construction, bounded reranking, and the reusable cross-source RRF helper.

### Verification recorded on 2026-11-12

- Backend: 7 tests passed; four live Docling format tests were skipped.
- Phase 3 Python: Ruff and formatting passed, and the new retrieval, reindex and
  evaluation modules passed focused strict MyPy checks.
- Ragas 0.4.3 ID metrics were smoke-tested against the locked compatibility pin;
  the expected precision/recall result was `(0.5, 1.0)`.
- Frontend: two stream-boundary tests, ESLint, TypeScript and the Webpack production
  build passed.
- Docker Compose configuration and the 234-package uv lockfile passed validation.
- Live Qdrant/Ollama reindexing and the dense-versus-hybrid quality report remain
  pending because Docker Desktop's Linux engine was not running. No quality gain is
  claimed until that report is produced.
