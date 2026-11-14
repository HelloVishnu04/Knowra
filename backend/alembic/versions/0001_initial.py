"""Initial Phase 2 schema and local development workspace."""

import sqlalchemy as sa

from alembic import op

revision = "0001"
down_revision = None


def upgrade():
    def table(name, *columns):
        op.create_table(
            name,
            sa.Column("id", sa.String(), primary_key=True),
            *columns,
            sa.Column(
                "created_at", sa.DateTime(timezone=True), server_default=sa.func.now()
            ),
        )

    def ref(name, target):
        return sa.Column(
            name, sa.String(), sa.ForeignKey(target + ".id"), nullable=False
        )

    table("organizations", sa.Column("name", sa.String(), nullable=False))
    table(
        "workspaces",
        ref("organization_id", "organizations"),
        sa.Column("name", sa.String(), nullable=False),
    )
    table(
        "users",
        sa.Column("email", sa.String(), nullable=False),
        sa.Column("hashed_password", sa.String(), nullable=False),
    )
    op.create_index("ix_users_email", "users", ["email"], unique=True)
    table(
        "workspace_members",
        ref("workspace_id", "workspaces"),
        ref("user_id", "users"),
        sa.Column("role", sa.String()),
    )
    table(
        "knowledge_bases",
        ref("workspace_id", "workspaces"),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("description", sa.String()),
    )
    table(
        "documents",
        ref("knowledge_base_id", "knowledge_bases"),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("status", sa.String()),
        sa.Column("error", sa.String()),
    )
    table(
        "document_versions",
        ref("document_id", "documents"),
        sa.Column("version", sa.Integer()),
        sa.Column("file_path", sa.String(), nullable=False),
    )
    table(
        "document_chunks",
        ref("document_id", "documents"),
        sa.Column("chunk_index", sa.Integer(), nullable=False),
        sa.Column("content", sa.String(), nullable=False),
        sa.Column("metadata_json", sa.JSON()),
    )
    table(
        "conversations",
        ref("workspace_id", "workspaces"),
        ref("user_id", "users"),
        sa.Column("title", sa.String()),
    )
    table(
        "messages",
        ref("conversation_id", "conversations"),
        sa.Column("role", sa.String(), nullable=False),
        sa.Column("content", sa.String(), nullable=False),
        sa.Column("run_id", sa.String()),
        sa.Column("citations_json", sa.JSON()),
    )
    for name, column in [
        ("knowledge_bases", "workspace_id"),
        ("documents", "knowledge_base_id"),
        ("document_chunks", "document_id"),
    ]:
        op.create_index(f"ix_{name}_{column}", name, [column])
    from app.core.config import settings

    op.bulk_insert(
        sa.table("organizations", sa.column("id"), sa.column("name")),
        [{"id": "local-org", "name": "Local development"}],
    )
    op.bulk_insert(
        sa.table(
            "workspaces",
            sa.column("id"),
            sa.column("organization_id"),
            sa.column("name"),
        ),
        [
            {
                "id": settings.LOCAL_WORKSPACE_ID,
                "organization_id": "local-org",
                "name": "Local workspace",
            }
        ],
    )


def downgrade():
    for name in [
        "messages",
        "conversations",
        "document_chunks",
        "document_versions",
        "documents",
        "knowledge_bases",
        "workspace_members",
        "users",
        "workspaces",
        "organizations",
    ]:
        op.drop_table(name)
