"""Durable repository work; Redis contains delivery hints, never authoritative state."""

import uuid

from sqlalchemy import Column, DateTime, ForeignKey, Integer, String
from sqlalchemy.sql import func

from app.models.base import Base


class RepositoryJob(Base):
    __tablename__ = "repository_jobs"

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    repository_id = Column(
        String, ForeignKey("repositories.id"), nullable=False, index=True
    )
    workspace_id = Column(String, ForeignKey("workspaces.id"), nullable=False)
    actor_user_id = Column(String, ForeignKey("users.id"))
    operation = Column(String, nullable=False)
    state = Column(String, nullable=False, default="pending", index=True)
    attempt = Column(Integer, nullable=False, default=0)
    lease_token = Column(String)
    lease_expires_at = Column(DateTime(timezone=True))
    heartbeat_at = Column(DateTime(timezone=True))
    deadline_at = Column(DateTime(timezone=True), nullable=False)
    progress = Column(String, nullable=False, default="Queued")
    error_code = Column(String)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    finished_at = Column(DateTime(timezone=True))


class RepositoryOutbox(Base):
    __tablename__ = "repository_outbox"

    job_id = Column(String, ForeignKey("repository_jobs.id"), primary_key=True)
    next_delivery_at = Column(DateTime(timezone=True), nullable=False, index=True)
    deliveries = Column(Integer, nullable=False, default=0)
