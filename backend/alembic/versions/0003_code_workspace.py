"""Persist repositories, semantic code symbols, and references."""

import sqlalchemy as sa

from alembic import op

revision = "0003"
down_revision = "0002"


def upgrade():
    op.create_table(
        "repositories",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column(
            "workspace_id",
            sa.String(),
            sa.ForeignKey("workspaces.id"),
            nullable=False,
        ),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("source_type", sa.String(), nullable=False),
        sa.Column("source_uri", sa.String()),
        sa.Column("root_path", sa.String(), nullable=False),
        sa.Column("default_branch", sa.String()),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column("error", sa.String()),
        sa.Column("metadata_json", sa.JSON()),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now()
        ),
        sa.Column("indexed_at", sa.DateTime(timezone=True)),
    )
    op.create_index("ix_repositories_workspace_id", "repositories", ["workspace_id"])

    op.create_table(
        "code_symbols",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column(
            "repository_id",
            sa.String(),
            sa.ForeignKey("repositories.id"),
            nullable=False,
        ),
        sa.Column(
            "workspace_id",
            sa.String(),
            sa.ForeignKey("workspaces.id"),
            nullable=False,
        ),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("qualified_name", sa.String(), nullable=False),
        sa.Column("kind", sa.String(), nullable=False),
        sa.Column("language", sa.String(), nullable=False),
        sa.Column("file_path", sa.String(), nullable=False),
        sa.Column("start_line", sa.Integer(), nullable=False),
        sa.Column("end_line", sa.Integer(), nullable=False),
        sa.Column("signature", sa.Text()),
        sa.Column("docstring", sa.Text()),
        sa.Column("source_text", sa.Text(), nullable=False),
        sa.Column("content_hash", sa.String(), nullable=False),
        sa.Column("metadata_json", sa.JSON()),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now()
        ),
    )
    op.create_index("ix_code_symbols_repository_id", "code_symbols", ["repository_id"])
    op.create_index(
        "ix_code_symbols_repository_name",
        "code_symbols",
        ["repository_id", "name"],
    )

    op.create_table(
        "code_references",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column(
            "repository_id",
            sa.String(),
            sa.ForeignKey("repositories.id"),
            nullable=False,
        ),
        sa.Column(
            "source_symbol_id",
            sa.String(),
            sa.ForeignKey("code_symbols.id"),
            nullable=True,
        ),
        sa.Column(
            "target_symbol_id",
            sa.String(),
            sa.ForeignKey("code_symbols.id"),
            nullable=True,
        ),
        sa.Column("target_name", sa.String(), nullable=False),
        sa.Column("kind", sa.String(), nullable=False),
        sa.Column("file_path", sa.String(), nullable=False),
        sa.Column("line", sa.Integer(), nullable=False),
        sa.Column("metadata_json", sa.JSON()),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now()
        ),
    )
    op.create_index(
        "ix_code_references_repository_target",
        "code_references",
        ["repository_id", "target_name"],
    )


def downgrade():
    op.drop_table("code_references")
    op.drop_table("code_symbols")
    op.drop_table("repositories")
