"""Persist Phase 4 agent runs and trace details."""

import sqlalchemy as sa

from alembic import op

revision = "0002"
down_revision = "0001"


def upgrade():
    op.create_table(
        "agent_runs",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column(
            "workspace_id",
            sa.String(),
            sa.ForeignKey("workspaces.id"),
            nullable=False,
        ),
        sa.Column(
            "conversation_id",
            sa.String(),
            sa.ForeignKey("conversations.id"),
            nullable=True,
        ),
        sa.Column("user_query", sa.String(), nullable=False),
        sa.Column("route", sa.String(), nullable=False),
        sa.Column("planned_routes_json", sa.JSON()),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column("provider", sa.String(), nullable=False),
        sa.Column("model", sa.String(), nullable=False),
        sa.Column("answer", sa.String()),
        sa.Column("error", sa.String()),
        sa.Column("trace_json", sa.JSON()),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now()
        ),
        sa.Column("completed_at", sa.DateTime(timezone=True)),
    )
    op.create_index("ix_agent_runs_workspace_id", "agent_runs", ["workspace_id"])
    op.create_index("ix_agent_runs_created_at", "agent_runs", ["created_at"])

    op.create_table(
        "retrieval_runs",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column(
            "agent_run_id",
            sa.String(),
            sa.ForeignKey("agent_runs.id"),
            nullable=False,
        ),
        sa.Column("source", sa.String(), nullable=False),
        sa.Column("query", sa.String(), nullable=False),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column("latency_ms", sa.Integer(), nullable=False),
        sa.Column("result_count", sa.Integer(), nullable=False),
        sa.Column("chunks_json", sa.JSON()),
        sa.Column("error", sa.String()),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now()
        ),
    )
    op.create_index(
        "ix_retrieval_runs_agent_run_id", "retrieval_runs", ["agent_run_id"]
    )

    op.create_table(
        "citations",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column(
            "agent_run_id",
            sa.String(),
            sa.ForeignKey("agent_runs.id"),
            nullable=False,
        ),
        sa.Column(
            "chunk_id",
            sa.String(),
            sa.ForeignKey("document_chunks.id"),
            nullable=True,
        ),
        sa.Column("number", sa.Integer(), nullable=False),
        sa.Column("source", sa.String(), nullable=False),
        sa.Column("label", sa.String(), nullable=False),
        sa.Column("metadata_json", sa.JSON()),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now()
        ),
    )
    op.create_index("ix_citations_agent_run_id", "citations", ["agent_run_id"])

    op.create_table(
        "tool_calls",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column(
            "agent_run_id",
            sa.String(),
            sa.ForeignKey("agent_runs.id"),
            nullable=False,
        ),
        sa.Column("tool_name", sa.String(), nullable=False),
        sa.Column("arguments_json", sa.JSON()),
        sa.Column("requires_approval", sa.Boolean(), nullable=False),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column("result_json", sa.JSON()),
        sa.Column("error", sa.String()),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now()
        ),
        sa.Column("completed_at", sa.DateTime(timezone=True)),
    )
    op.create_index("ix_tool_calls_agent_run_id", "tool_calls", ["agent_run_id"])


def downgrade():
    for name in ["tool_calls", "citations", "retrieval_runs", "agent_runs"]:
        op.drop_table(name)
