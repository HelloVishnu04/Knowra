import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.api.routes import chat, knowledge
from app.core.config import settings
from app.core.database import get_session
from app.main import app
from app.models import (
    Base,
    Document,
    DocumentChunk,
    KnowledgeBase,
    Organization,
    Workspace,
)
from app.rag import documents
from app.rag.base import RetrievalResult, RetrievedChunk
from app.rag.fusion import reciprocal_rank_fusion
from app.storage.objects import LocalObjectStore
from app.workers import ingest


@pytest.fixture
def database(monkeypatch, tmp_path):
    engine = create_engine(
        "sqlite://", poolclass=StaticPool, connect_args={"check_same_thread": False}
    )
    Base.metadata.create_all(engine)
    factory = sessionmaker(engine, expire_on_commit=False)
    with factory.begin() as session:
        session.add(Organization(id="org", name="Test"))
        session.add(
            Workspace(
                id=settings.LOCAL_WORKSPACE_ID, organization_id="org", name="Local"
            )
        )
        session.add(Workspace(id="other", organization_id="org", name="Other"))

    def sessions():
        with factory() as session:
            yield session

    app.dependency_overrides[get_session] = sessions
    monkeypatch.setattr(ingest, "SessionLocal", factory)
    monkeypatch.setattr(documents, "SessionLocal", factory)
    monkeypatch.setattr(settings, "OBJECT_STORE_PATH", str(tmp_path))
    monkeypatch.setattr(knowledge, "enqueue", AsyncMock())
    yield factory
    app.dependency_overrides.clear()
    engine.dispose()


def test_object_store_rejects_escape(tmp_path):
    store = LocalObjectStore(str(tmp_path))
    with pytest.raises(ValueError):
        store.put("../outside", b"bad")
    store.put("workspace/doc.pdf", b"document")
    assert store.get("workspace/doc.pdf") == b"document"


def test_initial_migration(monkeypatch, tmp_path):
    from alembic.config import Config
    from sqlalchemy import inspect

    from alembic import command
    from app.core import database as db

    engine = create_engine(f"sqlite:///{tmp_path / 'migration.db'}")
    monkeypatch.setattr(db, "engine", engine)
    command.upgrade(Config("alembic.ini"), "head")
    assert set(Base.metadata.tables).issubset(inspect(engine).get_table_names())
    with sessionmaker(engine)() as session:
        assert session.get(Workspace, settings.LOCAL_WORKSPACE_ID) is not None
    command.downgrade(Config("alembic.ini"), "base")
    assert not set(Base.metadata.tables).intersection(inspect(engine).get_table_names())
    engine.dispose()


def test_upload_and_scope(database):
    client = TestClient(app)
    kb = client.post("/api/v1/knowledge-bases", json={"name": "Research"}).json()
    response = client.post(
        f"/api/v1/knowledge-bases/{kb['id']}/documents",
        files={"file": ("test.pdf", b"%PDF-1.4\nexample")},
    )
    assert response.status_code == 202
    assert response.json()["status"] == "pending"
    assert knowledge.enqueue.await_count == 1
    assert (
        client.post(
            f"/api/v1/knowledge-bases/{kb['id']}/documents",
            files={"file": ("bad.pdf", b"not PDF")},
        ).status_code
        == 422
    )
    with database.begin() as session:
        session.add(KnowledgeBase(id="private", workspace_id="other", name="Private"))
    assert client.get("/api/v1/knowledge-bases/private/documents").status_code == 404
    assert all(
        k["id"] != "private" for k in client.get("/api/v1/knowledge-bases").json()
    )


def test_upload_size_and_queue_failure(database, monkeypatch):
    client = TestClient(app)
    kb = client.post("/api/v1/knowledge-bases", json={"name": "Research"}).json()
    url = f"/api/v1/knowledge-bases/{kb['id']}/documents"
    monkeypatch.setattr(settings, "MAX_UPLOAD_BYTES", 8)
    assert (
        client.post(url, files={"file": ("big.pdf", b"%PDF-" + b"x" * 10)}).status_code
        == 413
    )
    monkeypatch.setattr(knowledge, "enqueue", AsyncMock(side_effect=ConnectionError()))
    result = client.post(url, files={"file": ("ok.pdf", b"%PDF-x")}).json()
    assert result["status"] == "failed"
    monkeypatch.setattr(knowledge, "enqueue", AsyncMock())
    assert client.post(f"{url}/{result['id']}/retry").json()["status"] == "pending"


def test_upload_ingest_retrieve_chat(database, monkeypatch):
    client = TestClient(app)
    kb = client.post("/api/v1/knowledge-bases", json={"name": "Research"}).json()
    doc = client.post(
        f"/api/v1/knowledge-bases/{kb['id']}/documents",
        files={"file": ("test.pdf", b"%PDF-1.4")},
    ).json()
    vector_client = SimpleNamespace(
        collection_exists=AsyncMock(return_value=False),
        create_collection=AsyncMock(),
        create_payload_index=AsyncMock(),
        upsert=AsyncMock(),
        close=AsyncMock(),
    )
    monkeypatch.setattr(ingest, "AsyncQdrantClient", lambda **kwargs: vector_client)
    monkeypatch.setattr(ingest, "parse_document", lambda path: "parsed")
    monkeypatch.setattr(
        ingest,
        "chunk_document",
        lambda doc: [
            {
                "content": "The launch is in June.",
                "metadata": {"pages": [2], "sections": ["Schedule"]},
            }
        ],
    )
    monkeypatch.setattr(ingest, "embed", AsyncMock(return_value=[[0.1, 0.2]]))
    asyncio.run(ingest.ingest_document({}, doc["id"]))
    assert vector_client.upsert.await_count == 1
    collection = vector_client.create_collection.call_args.kwargs
    assert collection["sparse_vectors_config"]["sparse"].modifier.value == "idf"
    point = vector_client.upsert.call_args.kwargs["points"][0]
    assert point.vector["sparse"].model == settings.SPARSE_MODEL
    with database() as session:
        assert session.get(Document, doc["id"]).status == "ready"
        chunk_id = session.query(DocumentChunk).one().id
    # Include a foreign/stale point to verify SQL revalidation as well as vector scope.
    vector_client.collection_exists = AsyncMock(return_value=True)
    vector_client.query_points = AsyncMock(
        return_value=SimpleNamespace(
            points=[
                SimpleNamespace(id=chunk_id, score=0.9),
                SimpleNamespace(id="foreign", score=1),
            ]
        )
    )
    monkeypatch.setattr(documents, "AsyncQdrantClient", lambda **kwargs: vector_client)
    monkeypatch.setattr(documents, "embed", AsyncMock(return_value=[[0.1, 0.2]]))
    monkeypatch.setattr(settings, "RERANKER_ENABLED", True)
    monkeypatch.setattr(documents, "rerank", AsyncMock(return_value=[0.75]))
    result = asyncio.run(
        documents.DocumentRetriever().retrieve(
            "When?",
            workspace_id=settings.LOCAL_WORKSPACE_ID,
            filters={"knowledge_base_id": kb["id"]},
        )
    )
    assert len(result.chunks) == 1
    assert result.chunks[0].score == 0.75
    assert result.chunks[0].metadata["retrieval_score"] == 0.9
    assert documents.rerank.await_count == 1
    query_call = vector_client.query_points.call_args.kwargs
    assert query_call["query"].fusion.value == "rrf"
    assert [item.using for item in query_call["prefetch"]] == ["dense", "sparse"]
    conditions = query_call["query_filter"].must
    assert conditions[0].match.value == settings.LOCAL_WORKSPACE_ID
    assert conditions[1].match.value == kb["id"]
    assert conditions[3].match.value == settings.SPARSE_MODEL
    provider = SimpleNamespace(chat=AsyncMock(return_value="June [1]."))
    monkeypatch.setattr(chat.gateway, "get_provider", lambda _: provider)
    response = client.post(
        "/api/v1/chat",
        json={
            "messages": [{"role": "user", "content": "When?"}],
            "stream": False,
            "knowledge_base_id": kb["id"],
        },
    )
    assert response.status_code == 200
    assert response.json()["citations"][0]["pages"] == [2]
    assert response.json()["citations"][0]["chunk_id"] == chunk_id
    assert "The launch is in June." in provider.chat.call_args.args[0][0]["content"]
    assert client.get(f"/api/v1/chunks/{chunk_id}").status_code == 200
    with database.begin() as session:
        session.get(Document, doc["id"]).status = "failed"
    assert client.get(f"/api/v1/chunks/{chunk_id}").status_code == 404


def test_ingestion_failure_is_visible(database, monkeypatch):
    client = TestClient(app)
    kb = client.post("/api/v1/knowledge-bases", json={"name": "Broken"}).json()
    doc = client.post(
        f"/api/v1/knowledge-bases/{kb['id']}/documents",
        files={"file": ("broken.pdf", b"%PDF-broken")},
    ).json()
    monkeypatch.setattr(
        ingest,
        "parse_document",
        lambda path: (_ for _ in ()).throw(ValueError("invalid")),
    )
    with pytest.raises(ValueError):
        asyncio.run(ingest.ingest_document({}, doc["id"]))
    with database() as session:
        assert session.get(Document, doc["id"]).status == "failed"


def test_rrf_fuses_rankings_without_raw_score_comparison():
    first = RetrievedChunk(id="a", content="A", source="document", score=0.01)
    shared = RetrievedChunk(
        id="shared", content="Shared", source="document", score=0.001
    )
    second = RetrievedChunk(id="b", content="B", source="web", score=1000)
    fused = reciprocal_rank_fusion(
        [
            RetrievalResult(
                source="document", query="q", chunks=[first, shared], latency_ms=1
            ),
            RetrievalResult(
                source="web", query="q", chunks=[second, shared], latency_ms=1
            ),
        ],
        k=60,
    )
    assert [chunk.id for chunk in fused] == ["shared", "a", "b"]
    assert fused[0].metadata["source_scores"] == {
        "document": 0.001,
        "web": 0.001,
    }
