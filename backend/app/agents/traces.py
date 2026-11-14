from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any

from sqlalchemy.orm import Session

from app.core.database import SessionLocal
from app.models.runs import (
    AgentRun,
    Citation,
    CodingAttempt,
    ExecutionJob,
    RetrievalRun,
    ToolCall,
)
from app.rag.base import RetrievalResult

SessionFactory = Callable[[], Session]


def _now() -> datetime:
    return datetime.now(UTC)


def _iso(value: datetime | None) -> str | None:
    return value.isoformat() if value is not None else None


class AgentTraceStore:
    """Small transactional writes that keep the SQL trace useful during failures."""

    def __init__(self, session_factory: SessionFactory | None = None) -> None:
        self.session_factory = session_factory or SessionLocal

    def create_run(
        self,
        *,
        run_id: str,
        workspace_id: str,
        user_query: str,
        provider: str,
        model: str,
        conversation_id: str | None = None,
    ) -> None:
        with self.session_factory.begin() as session:
            session.add(
                AgentRun(
                    id=run_id,
                    workspace_id=workspace_id,
                    conversation_id=conversation_id,
                    user_query=user_query,
                    route="classifying",
                    planned_routes_json=[],
                    status="running",
                    provider=provider,
                    model=model,
                    trace_json=[],
                )
            )

    def add_step(
        self, run_id: str, node: str, status: str, details: dict[str, Any]
    ) -> None:
        with self.session_factory.begin() as session:
            run = session.get(AgentRun, run_id)
            if run is None:
                return
            trace = list(run.trace_json or [])
            trace.append(
                {
                    "node": node,
                    "status": status,
                    "at": _now().isoformat(),
                    "details": details,
                }
            )
            run.trace_json = trace

    def set_route(self, run_id: str, route: str, planned_routes: list[str]) -> None:
        with self.session_factory.begin() as session:
            run = session.get(AgentRun, run_id)
            if run is not None:
                run.route = route
                run.planned_routes_json = planned_routes

    def add_retrieval(
        self,
        run_id: str,
        source: str,
        query: str,
        *,
        result: RetrievalResult | None = None,
        error: str | None = None,
    ) -> None:
        chunks = []
        if result is not None:
            chunks = [
                {
                    "id": chunk.id,
                    "source": chunk.source,
                    "score": chunk.score,
                    "metadata": chunk.metadata,
                    "preview": chunk.content[:280],
                }
                for chunk in result.chunks
            ]
        with self.session_factory.begin() as session:
            session.add(
                RetrievalRun(
                    agent_run_id=run_id,
                    source=source,
                    query=query,
                    status="failed" if error else "completed",
                    latency_ms=result.latency_ms if result is not None else 0,
                    result_count=len(chunks),
                    chunks_json=chunks,
                    error=error,
                )
            )

    def replace_citations(self, run_id: str, citations: list[dict[str, Any]]) -> None:
        with self.session_factory.begin() as session:
            session.query(Citation).filter(Citation.agent_run_id == run_id).delete()
            for item in citations:
                source = str(item.get("source", "unknown"))
                metadata = {
                    key: value
                    for key, value in item.items()
                    if key not in {"number", "chunk_id", "source", "label"}
                }
                session.add(
                    Citation(
                        agent_run_id=run_id,
                        chunk_id=(
                            str(item["chunk_id"])
                            if source == "document" and item.get("chunk_id")
                            else None
                        ),
                        number=int(item["number"]),
                        source=source,
                        label=str(item.get("label", source.title())),
                        metadata_json=metadata,
                    )
                )

    def ensure_tool_call(
        self, run_id: str, name: str, arguments: dict[str, Any]
    ) -> None:
        with self.session_factory.begin() as session:
            existing = (
                session.query(ToolCall)
                .filter(
                    ToolCall.agent_run_id == run_id,
                    ToolCall.tool_name == name,
                    ToolCall.status.in_(["pending", "approved"]),
                )
                .first()
            )
            if existing is None:
                session.add(
                    ToolCall(
                        agent_run_id=run_id,
                        tool_name=name,
                        arguments_json=arguments,
                        requires_approval=True,
                        status="pending",
                    )
                )
            run = session.get(AgentRun, run_id)
            if run is not None:
                run.status = "pending_approval"

    def update_tool_call(
        self,
        run_id: str,
        name: str,
        status: str,
        *,
        result: dict[str, Any] | None = None,
        error: str | None = None,
    ) -> None:
        with self.session_factory.begin() as session:
            call = (
                session.query(ToolCall)
                .filter(
                    ToolCall.agent_run_id == run_id,
                    ToolCall.tool_name == name,
                )
                .order_by(ToolCall.created_at.desc())
                .first()
            )
            if call is not None:
                call.status = status
                call.result_json = result
                call.error = error
                if status in {"completed", "failed", "rejected"}:
                    call.completed_at = _now()

    def update_tool_arguments(
        self, run_id: str, name: str, arguments: dict[str, Any]
    ) -> None:
        with self.session_factory.begin() as session:
            call = (
                session.query(ToolCall)
                .filter(
                    ToolCall.agent_run_id == run_id,
                    ToolCall.tool_name == name,
                )
                .order_by(ToolCall.created_at.desc())
                .first()
            )
            if call is not None:
                call.arguments_json = arguments

    def add_coding_attempt(
        self,
        *,
        run_id: str,
        repository_id: str,
        attempt: int,
        plan: str,
        patch: str,
        checks: list[dict[str, Any]],
        status: str,
        error: str | None = None,
    ) -> None:
        with self.session_factory.begin() as session:
            session.add(
                CodingAttempt(
                    agent_run_id=run_id,
                    repository_id=repository_id,
                    attempt=attempt,
                    plan=plan,
                    patch=patch,
                    checks_json=checks,
                    status=status,
                    error=error,
                )
            )

    def complete(self, run_id: str, answer: str) -> None:
        with self.session_factory.begin() as session:
            run = session.get(AgentRun, run_id)
            if run is not None:
                run.status = "completed"
                run.answer = answer
                run.completed_at = _now()

    def fail(self, run_id: str, error: str) -> None:
        with self.session_factory.begin() as session:
            run = session.get(AgentRun, run_id)
            if run is not None:
                run.status = "failed"
                run.error = error[:2000]
                run.completed_at = _now()

    def list_runs(self, *, workspace_id: str, limit: int = 50) -> list[dict[str, Any]]:
        with self.session_factory() as session:
            rows = (
                session.query(AgentRun)
                .filter(AgentRun.workspace_id == workspace_id)
                .order_by(AgentRun.created_at.desc())
                .limit(min(max(limit, 1), 100))
                .all()
            )
            return [self._run_summary(row) for row in rows]

    def get_run(self, run_id: str, *, workspace_id: str) -> dict[str, Any] | None:
        with self.session_factory() as session:
            run = session.get(AgentRun, run_id)
            if run is None or run.workspace_id != workspace_id:
                return None
            retrievals = (
                session.query(RetrievalRun)
                .filter(RetrievalRun.agent_run_id == run_id)
                .order_by(RetrievalRun.created_at)
                .all()
            )
            citations = (
                session.query(Citation)
                .filter(Citation.agent_run_id == run_id)
                .order_by(Citation.number)
                .all()
            )
            tools = (
                session.query(ToolCall)
                .filter(ToolCall.agent_run_id == run_id)
                .order_by(ToolCall.created_at)
                .all()
            )
            coding_attempts = (
                session.query(CodingAttempt)
                .filter(CodingAttempt.agent_run_id == run_id)
                .order_by(CodingAttempt.attempt)
                .all()
            )
            execution_jobs = (
                session.query(ExecutionJob)
                .filter(ExecutionJob.agent_run_id == run_id)
                .order_by(ExecutionJob.created_at)
                .all()
            )
            return {
                **self._run_summary(run),
                "user_query": run.user_query,
                "answer": run.answer,
                "error": run.error,
                "trace": run.trace_json or [],
                "retrievals": [
                    {
                        "id": item.id,
                        "source": item.source,
                        "query": item.query,
                        "status": item.status,
                        "latency_ms": item.latency_ms,
                        "result_count": item.result_count,
                        "chunks": item.chunks_json or [],
                        "error": item.error,
                    }
                    for item in retrievals
                ],
                "citations": [
                    {
                        "number": item.number,
                        "chunk_id": item.chunk_id,
                        "source": item.source,
                        "label": item.label,
                        **(item.metadata_json or {}),
                    }
                    for item in citations
                ],
                "tool_calls": [
                    {
                        "id": item.id,
                        "name": item.tool_name,
                        "arguments": item.arguments_json or {},
                        "requires_approval": item.requires_approval,
                        "status": item.status,
                        "result": item.result_json,
                        "error": item.error,
                    }
                    for item in tools
                ],
                "coding_attempts": [
                    {
                        "id": item.id,
                        "repository_id": item.repository_id,
                        "attempt": item.attempt,
                        "plan": item.plan,
                        "patch": item.patch,
                        "checks": item.checks_json or [],
                        "status": item.status,
                        "error": item.error,
                        "created_at": _iso(item.created_at),
                    }
                    for item in coding_attempts
                ],
                "execution_jobs": [
                    {
                        "id": item.id,
                        "repository_id": item.repository_id,
                        "attempt": item.attempt,
                        "stage": item.stage,
                        "command": item.command_json or [],
                        "image": item.image,
                        "status": item.status,
                        "stdout": item.stdout,
                        "stderr": item.stderr,
                        "exit_code": item.exit_code,
                        "duration_ms": item.duration_ms,
                        "error": item.error,
                        "created_at": _iso(item.created_at),
                        "started_at": _iso(item.started_at),
                        "completed_at": _iso(item.completed_at),
                    }
                    for item in execution_jobs
                ],
            }

    @staticmethod
    def _run_summary(run: AgentRun) -> dict[str, Any]:
        return {
            "id": run.id,
            "route": run.route,
            "planned_routes": run.planned_routes_json or [],
            "status": run.status,
            "provider": run.provider,
            "model": run.model,
            "created_at": _iso(run.created_at),
            "completed_at": _iso(run.completed_at),
            "query_preview": run.user_query[:160],
        }
