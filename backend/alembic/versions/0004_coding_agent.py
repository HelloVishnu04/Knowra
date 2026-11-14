"""Persist Phase 7 coding-agent patch attempts."""

import sqlalchemy as sa

from alembic import op

revision = "0004"
down_revision = "0003"


def upgrade():
    op.create_table(
        "coding_attempts",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column(
            "agent_run_id",
            sa.String(),
            sa.ForeignKey("agent_runs.id"),
            nullable=False,
        ),
        sa.Column(
            "repository_id",
            sa.String(),
            sa.ForeignKey("repositories.id"),
            nullable=False,
        ),
        sa.Column("attempt", sa.Integer(), nullable=False),
        sa.Column("plan", sa.Text(), nullable=False),
        sa.Column("patch", sa.Text(), nullable=False),
        sa.Column("checks_json", sa.JSON()),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column("error", sa.Text()),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now()
        ),
        sa.UniqueConstraint("agent_run_id", "attempt", name="uq_coding_attempt_run_no"),
    )
    op.create_index(
        "ix_coding_attempts_agent_run_id", "coding_attempts", ["agent_run_id"]
    )


def downgrade():
    op.drop_table("coding_attempts")
