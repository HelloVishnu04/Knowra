import asyncio
import time
from collections.abc import AsyncGenerator
from typing import Any

import pytest
from langgraph.checkpoint.memory import InMemorySaver
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.agents.graph import AgentOrchestrator, ToolCallRequest, classify_route
from app.agents.traces import AgentTraceStore
from app.core.config import settings
from app.eval.router import evaluate
from app.llm.base import LLMProvider
from app.models import AgentRun, Base, Organization, RetrievalRun, ToolCall, Workspace
from app.rag.base import RetrievalResult, RetrievedChunk, Retriever


class FakeProvider(LLMProvider):
    async def chat(self, messages: list[dict], model: str) -> str:
        return "Grounded answer [1]."

    async def stream_chat(
        self, messages: list[dict], model: str
    ) -> AsyncGenerator[str, None]:
        yield "Grounded "
        yield "answer [1]."


class FakeRetriever(Retriever):
    def __init__(self, source: str, delay: float = 0.0) -> None:
        self.source = source
        self.delay = delay

    async def retrieve(
        self,
        query: str,
        *,
        workspace_id: str,
        top_k: int = 20,
        filters: dict[str, Any] | None = None,
    ) -> RetrievalResult:
        await asyncio.sleep(self.delay)
        return RetrievalResult(
            source=self.source,
            query=query,
            latency_ms=int(self.delay * 1000),
            chunks=[
                RetrievedChunk(
                    id=f"{self.source}-1",
                    content=f"Evidence from {self.source}",
                    source=self.source,
                    score=0.8,
                    metadata={"title": f"{self.source} source"},
                )
            ],
        )


@pytest.fixture
def database():
    engine = create_engine(
        "sqlite://", poolclass=StaticPool, connect_args={"check_same_thread": False}
    )
    Base.metadata.create_all(engine)
    factory = sessionmaker(engine, expire_on_commit=False)
    with factory.begin() as session:
        session.add(Organization(id="org", name="Test"))
        session.add(
            Workspace(
                id=settings.LOCAL_WORKSPACE_ID,
                organization_id="org",
                name="Local",
            )
        )
    yield factory
    engine.dispose()


def test_router_classification_cases():
    assert classify_route("Hello there") == ("direct", [])
    assert classify_route("Summarize the uploaded PDF", knowledge_base_id="kb") == (
        "document",
        ["document"],
    )
    assert classify_route(
        "Compare the document with the latest web news", knowledge_base_id="kb"
    ) == (
        "multi",
        ["document", "web"],
    )
    assert classify_route("Count database rows with SQL") == ("sql", ["sql"])
    assert classify_route("Debug this repository function") == ("code", ["code"])


def test_router_golden_set_meets_phase_target():
    report = evaluate()
    assert report["summary"]["case_count"] >= 15
    assert report["summary"]["route_accuracy"] >= 0.9


def test_multi_source_fanout_and_trace_persistence(database):
    retrievers = {
        name: FakeRetriever(name, 0.05) for name in ("document", "web", "sql", "code")
    }
    store = AgentTraceStore(database)
    orchestrator = AgentOrchestrator(
        provider=FakeProvider(),
        checkpointer=InMemorySaver(),
        trace_store=store,
        retrievers=retrievers,
    )
    state = orchestrator.initial_state(
        run_id="multi-run",
        workspace_id=settings.LOCAL_WORKSPACE_ID,
        messages=[{"role": "user", "content": "Compare all sources"}],
        provider="test",
        model="test-model",
        knowledge_base_id="kb",
        requested_route="multi",
    )
    started = time.monotonic()
    result = asyncio.run(orchestrator.run(state))
    elapsed = time.monotonic() - started

    assert elapsed < 0.16
    assert result["route"] == "multi"
    assert len(result["retrieval_results"]) == 4
    assert result["answer"] == "Grounded answer [1]."
    detail = store.get_run("multi-run", workspace_id=settings.LOCAL_WORKSPACE_ID)
    assert detail is not None
    assert detail["status"] == "completed"
    assert len(detail["retrievals"]) == 4
    assert {step["node"] for step in detail["trace"]} >= {
        "classify_intent",
        "plan_route",
        "retrieve",
        "fuse_rerank",
        "generate",
        "persist_trace",
    }
    with database() as session:
        assert session.query(AgentRun).count() == 1
        assert session.query(RetrievalRun).count() == 4


def test_resume_after_interrupt_executes_only_after_approval(database):
    calls: list[dict[str, Any]] = []

    async def preview(arguments: dict[str, Any]) -> dict[str, Any]:
        calls.append(arguments)
        return {"previewed": True}

    store = AgentTraceStore(database)
    checkpointer = InMemorySaver()
    orchestrator = AgentOrchestrator(
        provider=FakeProvider(),
        checkpointer=checkpointer,
        trace_store=store,
        tool_handlers={"preview": preview},
    )
    state = orchestrator.initial_state(
        run_id="approval-run",
        workspace_id=settings.LOCAL_WORKSPACE_ID,
        messages=[{"role": "user", "content": "Prepare a preview"}],
        provider="test",
        model="test-model",
        requested_route="direct",
        tool_call=ToolCallRequest(name="preview", arguments={"id": 7}),
    )

    asyncio.run(orchestrator.run(state))
    assert calls == []
    pending = store.get_run("approval-run", workspace_id=settings.LOCAL_WORKSPACE_ID)
    assert pending is not None
    assert pending["status"] == "pending_approval"

    result = asyncio.run(orchestrator.resume("approval-run", approved=True))
    assert result["approval_status"] == "approved"
    assert calls == [{"id": 7}]
    completed = store.get_run("approval-run", workspace_id=settings.LOCAL_WORKSPACE_ID)
    assert completed is not None
    assert completed["status"] == "completed"
    with database() as session:
        tool = session.query(ToolCall).one()
        assert tool.status == "completed"
