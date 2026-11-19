import uuid

from sqlalchemy import JSON, Column, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.sql import func

from app.models.base import Base


class Repository(Base):
    __tablename__ = "repositories"

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    workspace_id = Column(String, ForeignKey("workspaces.id"), nullable=False)
    name = Column(String, nullable=False)
    source_type = Column(String, nullable=False)
    source_uri = Column(String)
    root_path = Column(String, nullable=False)
    default_branch = Column(String)
    status = Column(String, nullable=False, default="pending")
    source_state = Column(String, nullable=False, default="queued")
    parse_state = Column(String, nullable=False, default="pending")
    index_state = Column(String, nullable=False, default="pending")
    archive_path = Column(String)
    active_job_id = Column(String)
    error = Column(String)
    metadata_json = Column(JSON, default=dict)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    indexed_at = Column(DateTime(timezone=True))


class CodeSymbol(Base):
    __tablename__ = "code_symbols"

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    repository_id = Column(String, ForeignKey("repositories.id"), nullable=False)
    workspace_id = Column(String, ForeignKey("workspaces.id"), nullable=False)
    name = Column(String, nullable=False)
    qualified_name = Column(String, nullable=False)
    kind = Column(String, nullable=False)
    language = Column(String, nullable=False)
    file_path = Column(String, nullable=False)
    start_line = Column(Integer, nullable=False)
    end_line = Column(Integer, nullable=False)
    signature = Column(Text)
    docstring = Column(Text)
    source_text = Column(Text, nullable=False)
    content_hash = Column(String, nullable=False)
    metadata_json = Column(JSON, default=dict)
    created_at = Column(DateTime(timezone=True), server_default=func.now())


class CodeReference(Base):
    __tablename__ = "code_references"

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    repository_id = Column(String, ForeignKey("repositories.id"), nullable=False)
    source_symbol_id = Column(String, ForeignKey("code_symbols.id"), nullable=True)
    target_symbol_id = Column(String, ForeignKey("code_symbols.id"), nullable=True)
    target_name = Column(String, nullable=False)
    kind = Column(String, nullable=False)
    file_path = Column(String, nullable=False)
    line = Column(Integer, nullable=False)
    metadata_json = Column(JSON, default=dict)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
