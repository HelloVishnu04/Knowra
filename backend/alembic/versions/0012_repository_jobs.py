"""Durable repository jobs and independent processing states."""

import sqlalchemy as sa

from alembic import op

revision = "0012"
down_revision = "0011"


def upgrade():
    for name, default in (
        ("source_state", "queued"),
        ("parse_state", "pending"),
        ("index_state", "pending"),
    ):
        op.add_column(
            "repositories",
            sa.Column(name, sa.String(), nullable=False, server_default=default),
        )
    op.add_column("repositories", sa.Column("archive_path", sa.String()))
    op.add_column("repositories", sa.Column("active_job_id", sa.String()))
    # Availability of legacy worktrees is checked on disk, not guessed in SQL.
    op.execute("UPDATE repositories SET source_state = 'unknown'")
    op.execute(
        "UPDATE repositories SET parse_state = 'ready', index_state = 'ready' WHERE status = 'ready'"
    )
    op.execute(
        "UPDATE repositories SET archive_path = metadata_json->>'archive_path' WHERE source_type = 'zip'"
    )
    op.create_table(
        "repository_jobs",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column(
            "repository_id",
            sa.String(),
            sa.ForeignKey("repositories.id"),
            nullable=False,
        ),
        sa.Column(
            "workspace_id", sa.String(), sa.ForeignKey("workspaces.id"), nullable=False
        ),
        sa.Column("actor_user_id", sa.String(), sa.ForeignKey("users.id")),
        sa.Column("operation", sa.String(), nullable=False),
        sa.Column("state", sa.String(), nullable=False),
        sa.Column("attempt", sa.Integer(), nullable=False),
        sa.Column("lease_token", sa.String()),
        sa.Column("lease_expires_at", sa.DateTime(timezone=True)),
        sa.Column("heartbeat_at", sa.DateTime(timezone=True)),
        sa.Column("deadline_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("progress", sa.String(), nullable=False),
        sa.Column("error_code", sa.String()),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now()
        ),
        sa.Column("finished_at", sa.DateTime(timezone=True)),
    )
    op.create_index(
        "ix_repository_jobs_repository_id", "repository_jobs", ["repository_id"]
    )
    op.create_index("ix_repository_jobs_state", "repository_jobs", ["state"])
    op.create_table(
        "repository_outbox",
        sa.Column(
            "job_id", sa.String(), sa.ForeignKey("repository_jobs.id"), primary_key=True
        ),
        sa.Column("next_delivery_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("deliveries", sa.Integer(), nullable=False),
    )
    op.create_index(
        "ix_repository_outbox_next_delivery_at",
        "repository_outbox",
        ["next_delivery_at"],
    )


def downgrade():
    op.drop_table("repository_outbox")
    op.drop_table("repository_jobs")
    for name in (
        "active_job_id",
        "archive_path",
        "index_state",
        "parse_state",
        "source_state",
    ):
        op.drop_column("repositories", name)
