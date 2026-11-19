"""Transactional scheduling, fenced leases, and repeatable outbox delivery."""

import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import select, update

from app.core.config import settings
from app.core.database import SessionLocal
from app.models.code import Repository
from app.models.jobs import RepositoryJob, RepositoryOutbox
from app.models.user import WorkspaceMember

ACTIVE = {"pending", "running"}
LEASE_SECONDS = 90
MAX_ATTEMPTS = 3


class LeaseLost(RuntimeError):
    pass


def utc(value):
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value


def schedule(session, repository, operation, actor_user_id=None):
    """Caller holds the repository row lock; active requests are idempotent."""
    if repository.active_job_id:
        active = session.get(RepositoryJob, repository.active_job_id)
        if active and active.state in ACTIVE:
            return active
    now = datetime.now(UTC)
    job = RepositoryJob(
        id=str(uuid.uuid4()),
        repository_id=repository.id,
        workspace_id=repository.workspace_id,
        actor_user_id=actor_user_id,
        operation=operation,
        deadline_at=now + timedelta(minutes=30),
    )
    session.add(job)
    session.flush()
    session.add(RepositoryOutbox(job_id=job.id, next_delivery_at=now))
    repository.active_job_id = job.id
    repository.status = "pending"
    repository.error = None
    return job


def authorized(session, job):
    if job.actor_user_id is None:
        # Do not carry anonymous work into a later authenticated deployment.
        return not settings.AUTH_REQUIRED
    return (
        session.scalar(
            select(WorkspaceMember.id).where(
                WorkspaceMember.workspace_id == job.workspace_id,
                WorkspaceMember.user_id == job.actor_user_id,
                WorkspaceMember.role.in_(["owner", "administrator", "member"]),
            )
        )
        is not None
    )


def finish(session, job, state, error_code=None):
    job.state = state
    job.error_code = error_code
    job.finished_at = datetime.now(UTC)
    job.lease_token = None
    job.lease_expires_at = None
    repository = session.get(Repository, job.repository_id)
    if repository and repository.active_job_id == job.id and state != "succeeded":
        repository.status = "failed" if state != "cancelled" else "cancelled"
        repository.error = {
            "access_revoked": "Workspace write access was revoked.",
            "deadline_exceeded": "Processing deadline exceeded. Retry when a worker is available.",
            "worker_lost": "Worker stopped repeatedly. Retry processing.",
            "ingestion_failed": "Processing failed. Files already acquired remain available; retry processing.",
        }.get(error_code)
        if repository.source_state == "fetching":
            repository.source_state = "failed"
        if repository.parse_state == "running":
            repository.parse_state = "failed"
        if repository.index_state == "running":
            repository.index_state = "failed"
    event = session.get(RepositoryOutbox, job.id)
    if event:
        session.delete(event)


def claim(job_id):
    now = datetime.now(UTC)
    token = str(uuid.uuid4())
    with SessionLocal.begin() as session:
        # Conditional UPDATE, not a read-then-write race (also works on SQLite).
        result = session.execute(
            update(RepositoryJob)
            .where(
                RepositoryJob.id == job_id,
                RepositoryJob.state == "pending",
                RepositoryJob.deadline_at > now,
            )
            .values(
                state="running",
                lease_token=token,
                attempt=RepositoryJob.attempt + 1,
                heartbeat_at=now,
                lease_expires_at=now + timedelta(seconds=LEASE_SECONDS),
            )
        )
        if result.rowcount != 1:
            return None
        job = session.get(RepositoryJob, job_id)
        repository = session.get(Repository, job.repository_id)
        if (
            not repository
            or repository.active_job_id != job.id
            or not authorized(session, job)
        ):
            finish(session, job, "cancelled", "access_revoked")
            return None
    return token


def guard(session, job_id, token):
    job = session.scalar(
        select(RepositoryJob).where(RepositoryJob.id == job_id).with_for_update()
    )
    now = datetime.now(UTC)
    if (
        not job
        or job.state != "running"
        or job.lease_token != token
        or utc(job.lease_expires_at) <= now
        or utc(job.deadline_at) <= now
    ):
        raise LeaseLost("Repository job lease is no longer valid")
    if not authorized(session, job):
        raise LeaseLost("Workspace write access was revoked")
    repository = session.get(Repository, job.repository_id)
    if not repository or repository.active_job_id != job_id:
        raise LeaseLost("Repository job was superseded")
    return job


def heartbeat(job_id, token):
    with SessionLocal.begin() as session:
        job = guard(session, job_id, token)
        job.heartbeat_at = datetime.now(UTC)
        job.lease_expires_at = job.heartbeat_at + timedelta(seconds=LEASE_SECONDS)


def reconcile(workspace_id: str | None = None):
    now = datetime.now(UTC)
    with SessionLocal.begin() as session:
        query = select(RepositoryJob).where(RepositoryJob.state.in_(ACTIVE))
        if workspace_id:
            query = query.where(RepositoryJob.workspace_id == workspace_id)
        jobs = session.scalars(query.with_for_update(skip_locked=True)).all()
        for job in jobs:
            if not authorized(session, job):
                finish(session, job, "cancelled", "access_revoked")
            elif utc(job.deadline_at) <= now:
                finish(session, job, "failed", "deadline_exceeded")
            elif job.state == "running" and utc(job.lease_expires_at) <= now:
                if job.attempt >= MAX_ATTEMPTS:
                    finish(session, job, "failed", "worker_lost")
                else:
                    job.state = "pending"
                    job.lease_token = None
                    job.lease_expires_at = None
                    job.progress = "Worker interrupted; queued for retry"
                    session.get(RepositoryOutbox, job.id).next_delivery_at = now


async def dispatch_repository_jobs(ctx):
    reconcile()
    now = datetime.now(UTC)
    with SessionLocal() as session:
        ids = session.scalars(
            select(RepositoryOutbox.job_id)
            .join(RepositoryJob)
            .where(
                RepositoryJob.state == "pending",
                RepositoryOutbox.next_delivery_at <= now,
            )
            .limit(100)
        ).all()
    for job_id in ids:
        # A crash between enqueue and commit repeats delivery, safely fenced by claim.
        await ctx["redis"].enqueue_job("run_repository_job", job_id)
        with SessionLocal.begin() as session:
            event = session.get(RepositoryOutbox, job_id)
            if event:
                event.deliveries += 1
                event.next_delivery_at = now + timedelta(seconds=60)


def job_json(job):
    return {
        key: getattr(job, key)
        for key in (
            "id",
            "repository_id",
            "operation",
            "state",
            "attempt",
            "progress",
            "error_code",
            "created_at",
            "heartbeat_at",
            "deadline_at",
            "finished_at",
        )
    }
