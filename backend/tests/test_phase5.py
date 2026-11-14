import asyncio
from collections.abc import AsyncGenerator
from types import SimpleNamespace
from typing import Any, cast

import pytest
from langgraph.checkpoint.memory import InMemorySaver
from sqlalchemy import Engine, create_engine, text
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.agents.graph import AgentOrchestrator
from app.agents.traces import AgentTraceStore
from app.core.config import settings
from app.llm.base import LLMProvider
from app.models import Base, Organization, Workspace
from app.rag.sql import (
    SensitiveSQLApprovalRequired,
    SQLExecutor,
    SQLGuardrailError,
    SQLGuardrails,
    SQLRetriever,
)


class SQLProvider(LLMProvider):
    async def chat(self, messages: list[dict], model: str) -> str:
        del model
        if messages[0]["content"].startswith("Convert the question"):
            return "```sql\nSELECT category, COUNT(*) AS total FROM records GROUP BY category\n```"
        return "The result contains two categories [1]."

    async def stream_chat(
        self, messages: list[dict], model: str
    ) -> AsyncGenerator[str, None]:
        yield await self.chat(messages, model)


@pytest.mark.parametrize(
    "sql",
    [
        "INSERT INTO records (category) VALUES ('x')",
        "UPDATE records SET category = 'x'",
        "DELETE FROM records",
        "DROP TABLE records",
        "WITH changed AS (DELETE FROM records RETURNING *) SELECT * FROM changed",
    ],
)
def test_ast_rejects_mutations(sql: str):
    guardrails = SQLGuardrails({"public.records"})
    with pytest.raises(SQLGuardrailError):
        guardrails.validate(sql)


@pytest.mark.parametrize(
    "sql",
    [
        "SELECT * FROM private.records",
        'SELECT * FROM "private"."records"',
        "SELECT * FROM public.records r JOIN private.secrets s ON true",
        "SELECT pg_read_file('/etc/passwd') FROM public.records",
        "SELECT 1",
        "SELECT * FROM public.records; SELECT * FROM public.records",
    ],
)
def test_allow_list_bypasses_are_rejected(sql: str):
    guardrails = SQLGuardrails({"public.records"})
    with pytest.raises(SQLGuardrailError):
        guardrails.validate(sql)


def test_row_limit_is_added_and_clamped():
    guardrails = SQLGuardrails({"public.records"}, row_limit=25)
    assert guardrails.validate("SELECT id FROM public.records").sql.endswith("LIMIT 25")
    assert guardrails.validate("SELECT id FROM public.records LIMIT 999").sql.endswith(
        "LIMIT 25"
    )
    assert guardrails.validate("SELECT id FROM public.records LIMIT 5").sql.endswith(
        "LIMIT 5"
    )


def test_executor_configures_read_only_transaction_and_timeout():
    calls: list[tuple[str, dict[str, Any] | None]] = []

    class Connection:
        def execute(self, statement, parameters=None):
            calls.append((str(statement), parameters))

    fake_engine = SimpleNamespace(dialect=SimpleNamespace(name="postgresql"))
    executor = SQLExecutor(
        cast(Engine, fake_engine), statement_timeout_ms=4321, row_limit=10
    )
    executor._configure_transaction(Connection())

    assert calls[0][0] == "SET TRANSACTION READ ONLY"
    assert "statement_timeout" in calls[1][0]
    assert calls[1][1] == {"value": "4321ms"}


@pytest.fixture
def sql_stack():
    engine = create_engine(
        "sqlite://", poolclass=StaticPool, connect_args={"check_same_thread": False}
    )
    Base.metadata.create_all(engine)
    with engine.begin() as connection:
        connection.execute(
            text(
                "CREATE TABLE records (id INTEGER PRIMARY KEY, category TEXT NOT NULL)"
            )
        )
        connection.execute(
            text("INSERT INTO records (category) VALUES ('alpha'), ('beta'), ('alpha')")
        )
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
    provider = SQLProvider()
    retriever = SQLRetriever(
        provider,
        model="test-model",
        guardrails=SQLGuardrails(
            {"records"}, sensitive_tables={"records"}, row_limit=10
        ),
        executor=SQLExecutor(engine, statement_timeout_ms=100, row_limit=10),
    )
    yield factory, provider, retriever
    engine.dispose()


def test_sensitive_table_requires_approval(sql_stack):
    _, _, retriever = sql_stack
    with pytest.raises(SensitiveSQLApprovalRequired):
        asyncio.run(
            retriever.retrieve(
                "Count records by category", workspace_id=settings.LOCAL_WORKSPACE_ID
            )
        )


def test_sensitive_sql_resumes_then_persists_result_and_trace(sql_stack):
    factory, provider, retriever = sql_stack
    store = AgentTraceStore(factory)
    orchestrator = AgentOrchestrator(
        provider=provider,
        checkpointer=InMemorySaver(),
        trace_store=store,
        retrievers={"sql": retriever},
    )
    state = orchestrator.initial_state(
        run_id="sql-approval-run",
        workspace_id=settings.LOCAL_WORKSPACE_ID,
        messages=[{"role": "user", "content": "Count database records by category"}],
        provider="test",
        model="test-model",
        requested_route="sql",
    )

    asyncio.run(orchestrator.run(state))
    pending = store.get_run(
        "sql-approval-run", workspace_id=settings.LOCAL_WORKSPACE_ID
    )
    assert pending is not None
    assert pending["status"] == "pending_approval"
    assert pending["tool_calls"][0]["arguments"]["sql"].endswith("LIMIT 10")

    result = asyncio.run(orchestrator.resume("sql-approval-run", approved=True))
    assert result["answer"] == "The result contains two categories [1]."
    completed = store.get_run(
        "sql-approval-run", workspace_id=settings.LOCAL_WORKSPACE_ID
    )
    assert completed is not None
    assert completed["status"] == "completed"
    assert completed["retrievals"][0]["source"] == "sql"
    assert completed["retrievals"][0]["result_count"] == 1
    assert completed["tool_calls"][0]["status"] == "completed"
    assert any(step["node"] == "sql_guardrails" for step in completed["trace"])
