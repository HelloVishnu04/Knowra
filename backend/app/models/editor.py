import uuid

from sqlalchemy import (
    JSON,
    Column,
    DateTime,
    ForeignKey,
    Integer,
    LargeBinary,
    String,
    UniqueConstraint,
)
from sqlalchemy.sql import func

from app.models.base import Base


class EditorWorkspace(Base):
    __tablename__ = "editor_workspaces"
    __table_args__ = (
        UniqueConstraint(
            "repository_id", "owner_key", name="uq_editor_repository_owner"
        ),
    )

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    repository_id = Column(String, ForeignKey("repositories.id"), nullable=False)
    workspace_id = Column(
        String, ForeignKey("workspaces.id"), nullable=False, index=True
    )
    owner_user_id = Column(String, ForeignKey("users.id"))
    owner_key = Column(String, nullable=False)
    snapshot_hash = Column(String, nullable=False)
    manifest_json = Column(JSON, nullable=False)
    excluded_json = Column(JSON, nullable=False, default=list)
    revision = Column(Integer, nullable=False, default=0)
    created_at = Column(DateTime(timezone=True), server_default=func.now())


class FileMutation(Base):
    __tablename__ = "file_mutations"

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    editor_workspace_id = Column(
        String, ForeignKey("editor_workspaces.id"), nullable=False, index=True
    )
    path = Column(String, nullable=False)
    before_hash = Column(String)
    after_hash = Column(String, nullable=False)
    before_bytes = Column(LargeBinary)
    after_bytes = Column(LargeBinary, nullable=False)
    state = Column(String, nullable=False, default="prepared")
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    finished_at = Column(DateTime(timezone=True))
