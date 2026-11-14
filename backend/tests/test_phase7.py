import asyncio
import uuid
from collections.abc import AsyncGenerator
from pathlib import Path
from typing import Any

from langgraph.checkpoint.memory import InMemorySaver
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.agents.coding import CheckResult, CodingAgent
from app.agents.graph import AgentOrchestrator
from app.agents.traces import AgentTraceStore
from app.code.patches import apply_patch_in_memory, parse_unified_diff
from app.core.config import settings
from app.llm.base import LLMProvider
from app.models import Base, Organization, Repository, Workspace
from app.rag.base import RetrievalResult, RetrievedChunk, Retriever

FIRST_PATCH = """diff --git a/calculator.py b/calculator.py
--- a/calculator.py
+++ b/calculator.py
@@ -1,2 +1,2 @@
 def add(a, b):
-    return a - b
+    return a * b
"""

REPAIRED_PATCH = """diff --git a/calculator.py b/calculator.py
--- a/calculator.py
+++ b/calculator.py
@@ -1,2 +1,2 @@
 def add(a, b):
-    return a - b
+    return a + b
"""


class CodingProvider(LLMProvider):
    def __init__(self) -> None:
        self.patch_calls = 0

    async def chat(self, messages: list[dict], model: str) -> str:
        del model
        if messages[0]["content"].startswith("Plan the smallest"):
            return "1. Correct add.\n2. Run the calculator tests."
        self.patch_calls += 1
        return FIRST_PATCH if self.patch_calls == 1 else REPAIRED_PATCH

    async def stream_chat(
        self, messages: list[dict], model: str
    ) -> AsyncGenerator[str, None]:
        yield await self.chat(messages, model)


class SeededRunner:
    def __init__(self) -> None:
        self.calls = 0

    async def run(self, **kwargs):
        self.calls += 1
        patched = kwargs["patched_files"]["calculator.py"]
        if "a * b" in patched:
            return [
                CheckResult(
                    "tests",
                    "pytest tests/test_calculator.py",
                    "failed",
                    "expected add(1, 2) == 3, got 2",
                    1,
                )
            ]
        return [
            CheckResult(
                "tests", "pytest tests/test_calculator.py", "passed", "1 passed", 0
            )
        ]


class CodeContext(Retriever):
    async def retrieve(
        self,
        query: str,
        *,
        workspace_id: str,
        top_k: int = 20,
        filters: dict[str, Any] | None = None,
    ) -> RetrievalResult:
        del workspace_id, top_k, filters
        return RetrievalResult(
            source="code",
            query=query,
            chunks=[
                RetrievedChunk(
                    id="calculator-add",
                    source="code",
                    score=1.0,
                    content="def add(a, b):\n    return a - b",
                    metadata={
                        "file_path": "calculator.py",
                        "start_line": 1,
                        "end_line": 2,
                    },
                )
            ],
        )


def _database(tmp_path: Path):
    engine = create_engine(
        "sqlite://", poolclass=StaticPool, connect_args={"check_same_thread": False}
    )
    Base.metadata.create_all(engine)
    factory = sessionmaker(engine, expire_on_commit=False)
    repository_id = str(uuid.uuid4())
    root = tmp_path / "repository"
    root.mkdir()
    (root / "calculator.py").write_text(
        "def add(a, b):\n    return a - b\n", encoding="utf-8"
    )
    with factory.begin() as session:
        session.add(Organization(id="org", name="Test"))
        session.add(
            Workspace(
                id=settings.LOCAL_WORKSPACE_ID,
                organization_id="org",
                name="Local",
            )
        )
        session.add(
            Repository(
                id=repository_id,
                workspace_id=settings.LOCAL_WORKSPACE_ID,
                name="Calculator",
                source_type="local",
                root_path=str(root),
                status="ready",
            )
        )
    return engine, factory, repository_id, root


def test_unified_diff_integrity_and_multi_file_application(tmp_path: Path):
    (tmp_path / "one.py").write_text("value = 1\n", encoding="utf-8")
    patch = parse_unified_diff(
        """diff --git a/one.py b/one.py
--- a/one.py
+++ b/one.py
@@ -1 +1 @@
-value = 1
+value = 2
diff --git a/two.py b/two.py
new file mode 100644
--- /dev/null
+++ b/two.py
@@ -0,0 +1,2 @@
+def two():
+    return 2
"""
    )
    result = apply_patch_in_memory(tmp_path, patch)
    assert result == {
        "one.py": "value = 2\n",
        "two.py": "def two():\n    return 2\n",
    }
    assert (tmp_path / "one.py").read_text(encoding="utf-8") == "value = 1\n"
    assert not (tmp_path / "two.py").exists()


def test_repair_loop_stops_after_seeded_failure(tmp_path: Path):
    (tmp_path / "calculator.py").write_text(
        "def add(a, b):\n    return a - b\n", encoding="utf-8"
    )
    runner = SeededRunner()
    outcome = asyncio.run(
        CodingAgent(CodingProvider(), model="test", runner=runner, max_attempts=3).run(
            task="Fix add", repository_root=tmp_path, context=[]
        )
    )
    assert outcome.status == "review"
    assert outcome.attempts == 2
    assert runner.calls == 2
    assert "return a + b" in outcome.patch


def test_coding_run_persists_attempts_and_edit_approval(tmp_path: Path):
    engine, factory, repository_id, root = _database(tmp_path)
    store = AgentTraceStore(factory)
    orchestrator = AgentOrchestrator(
        provider=CodingProvider(),
        checkpointer=InMemorySaver(),
        trace_store=store,
        retrievers={"code": CodeContext()},
        code_check_runner=SeededRunner(),
    )
    state = orchestrator.initial_state(
        run_id="coding-run",
        workspace_id=settings.LOCAL_WORKSPACE_ID,
        messages=[{"role": "user", "content": "Fix the add function"}],
        provider="test",
        model="test-model",
        repository_id=repository_id,
        requested_route="code",
    )
    asyncio.run(orchestrator.run(state))
    pending = store.get_run("coding-run", workspace_id=settings.LOCAL_WORKSPACE_ID)
    assert pending is not None
    assert pending["status"] == "pending_approval"
    assert len(pending["coding_attempts"]) == 2
    assert pending["coding_attempts"][0]["status"] == "failed"
    assert pending["coding_attempts"][1]["status"] == "ready_for_review"
    assert pending["tool_calls"][0]["name"] == "create_patch"

    edited = REPAIRED_PATCH.replace("a + b", "sum((a, b))")
    result = asyncio.run(
        orchestrator.resume("coding-run", decision={"action": "edit", "patch": edited})
    )
    assert result["approval_status"] == "approved"
    completed = store.get_run("coding-run", workspace_id=settings.LOCAL_WORKSPACE_ID)
    assert completed is not None
    assert completed["status"] == "completed"
    assert completed["tool_calls"][0]["status"] == "completed"
    assert completed["tool_calls"][0]["arguments"]["edited_by_reviewer"] is True
    assert "sum((a, b))" in completed["tool_calls"][0]["arguments"]["patch"]
    assert (
        (root / "calculator.py").read_text(encoding="utf-8").endswith("return a - b\n")
    )
    engine.dispose()
