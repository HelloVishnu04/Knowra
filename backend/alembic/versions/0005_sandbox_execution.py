"""Persist Phase 8 isolated execution jobs."""

import sqlalchemy as sa

from alembic import op

revision = "0005"
down_revision = "0004"


def upgrade():
    op.create_table(
        "execution_jobs",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column(
            "workspace_id",
            sa.String(),
            sa.ForeignKey("workspaces.id"),
            nullable=False,
        ),
        sa.Column(
            "agent_run_id",
            sa.String(),
            sa.ForeignKey("agent_runs.id"),
            nullable=True,
        ),
        sa.Column(
            "repository_id",
            sa.String(),
            sa.ForeignKey("repositories.id"),
            nullable=True,
        ),
        sa.Column("attempt", sa.Integer(), nullable=False),
        sa.Column("stage", sa.String(), nullable=False),
        sa.Column("command_json", sa.JSON(), nullable=False),
        sa.Column("image", sa.String(), nullable=False),
        sa.Column("files_json", sa.JSON(), nullable=False),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column("stdout", sa.Text(), nullable=False),
        sa.Column("stderr", sa.Text(), nullable=False),
        sa.Column("exit_code", sa.Integer()),
        sa.Column("duration_ms", sa.Integer()),
        sa.Column("error", sa.Text()),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now()
        ),
        sa.Column("started_at", sa.DateTime(timezone=True)),
        sa.Column("completed_at", sa.DateTime(timezone=True)),
    )
    op.create_index(
        "ix_execution_jobs_agent_run_id", "execution_jobs", ["agent_run_id"]
    )
    op.create_index("ix_execution_jobs_status", "execution_jobs", ["status"])


def downgrade():
    op.drop_table("execution_jobs")
