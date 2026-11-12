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

Open the application after the containers and model downloads finish:

- Knowledge bases and document upload: http://localhost:3000/knowledge
- Chat: http://localhost:3000/chat
- API health: http://localhost:8000/health
- API documentation: http://localhost:8000/docs
- Qdrant dashboard: http://localhost:6333/dashboard

Create a knowledge base and use the dashboard to manage documents. AI-backed
indexing and chat can be configured later; they are not required to start or
inspect the application.

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
BM25, RRF, reranking, reindexing and evaluation.

This is currently a single-user local development system. Authentication is not
implemented, and the loopback-only Compose deployment must not be exposed to other
users until authentication and workspace membership checks are complete.
