import uuid

from sqlalchemy import (
    JSON,
    Boolean,
    Column,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
)
from sqlalchemy.sql import func

from app.models.base import Base


class AgentRun(Base):
    __tablename__ = "agent_runs"

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    workspace_id = Column(String, ForeignKey("workspaces.id"), nullable=False)
    conversation_id = Column(String, ForeignKey("conversations.id"), nullable=True)
    user_query = Column(String, nullable=False)
    route = Column(String, nullable=False, default="direct")
    planned_routes_json = Column(JSON, default=list)
    status = Column(String, nullable=False, default="running")
    provider = Column(String, nullable=False)
    model = Column(String, nullable=False)
    answer = Column(String)
    error = Column(String)
    trace_json = Column(JSON, default=list)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    completed_at = Column(DateTime(timezone=True))


class RetrievalRun(Base):
    __tablename__ = "retrieval_runs"

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    agent_run_id = Column(String, ForeignKey("agent_runs.id"), nullable=False)
    source = Column(String, nullable=False)
    query = Column(String, nullable=False)
    status = Column(String, nullable=False)
    latency_ms = Column(Integer, nullable=False, default=0)
    result_count = Column(Integer, nullable=False, default=0)
    chunks_json = Column(JSON, default=list)
    error = Column(String)
    created_at = Column(DateTime(timezone=True), server_default=func.now())


class Citation(Base):
    __tablename__ = "citations"

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    agent_run_id = Column(String, ForeignKey("agent_runs.id"), nullable=False)
    chunk_id = Column(String, ForeignKey("document_chunks.id"), nullable=True)
    number = Column(Integer, nullable=False)
    source = Column(String, nullable=False)
    label = Column(String, nullable=False)
    metadata_json = Column(JSON, default=dict)
    created_at = Column(DateTime(timezone=True), server_default=func.now())


class ToolCall(Base):
    __tablename__ = "tool_calls"

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    agent_run_id = Column(String, ForeignKey("agent_runs.id"), nullable=False)
    tool_name = Column(String, nullable=False)
    arguments_json = Column(JSON, default=dict)
    requires_approval = Column(Boolean, nullable=False, default=True)
    status = Column(String, nullable=False, default="pending")
    result_json = Column(JSON)
    error = Column(String)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    completed_at = Column(DateTime(timezone=True))


class CodingAttempt(Base):
    __tablename__ = "coding_attempts"

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    agent_run_id = Column(String, ForeignKey("agent_runs.id"), nullable=False)
    repository_id = Column(String, ForeignKey("repositories.id"), nullable=False)
    attempt = Column(Integer, nullable=False)
    plan = Column(Text, nullable=False)
    patch = Column(Text, nullable=False)
    checks_json = Column(JSON, default=list)
    status = Column(String, nullable=False)
    error = Column(Text)
    created_at = Column(DateTime(timezone=True), server_default=func.now())


class ExecutionJob(Base):
    __tablename__ = "execution_jobs"

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    workspace_id = Column(String, ForeignKey("workspaces.id"), nullable=False)
    agent_run_id = Column(String, ForeignKey("agent_runs.id"), nullable=True)
    repository_id = Column(String, ForeignKey("repositories.id"), nullable=True)
    attempt = Column(Integer, nullable=False, default=1)
    stage = Column(String, nullable=False)
    command_json = Column(JSON, nullable=False)
    image = Column(String, nullable=False)
    files_json = Column(JSON, nullable=False)
    status = Column(String, nullable=False, default="queued")
    stdout = Column(Text, nullable=False, default="")
    stderr = Column(Text, nullable=False, default="")
    exit_code = Column(Integer)
    duration_ms = Column(Integer)
    error = Column(Text)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    started_at = Column(DateTime(timezone=True))
    completed_at = Column(DateTime(timezone=True))
