"""Personal editor snapshots and recoverable single-file saves."""

import sqlalchemy as sa

from alembic import op

revision = "0013"
down_revision = "0012"


def upgrade():
    op.create_table(
        "editor_workspaces",
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
        sa.Column("owner_user_id", sa.String(), sa.ForeignKey("users.id")),
        sa.Column("owner_key", sa.String(), nullable=False),
        sa.Column("snapshot_hash", sa.String(), nullable=False),
        sa.Column("manifest_json", sa.JSON(), nullable=False),
        sa.Column("excluded_json", sa.JSON(), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now()
        ),
        sa.UniqueConstraint(
            "repository_id", "owner_key", name="uq_editor_repository_owner"
        ),
    )
    op.create_index(
        "ix_editor_workspaces_workspace_id", "editor_workspaces", ["workspace_id"]
    )
    op.create_table(
        "file_mutations",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column(
            "editor_workspace_id",
            sa.String(),
            sa.ForeignKey("editor_workspaces.id"),
            nullable=False,
        ),
        sa.Column("path", sa.String(), nullable=False),
        sa.Column("before_hash", sa.String()),
        sa.Column("after_hash", sa.String(), nullable=False),
        sa.Column("before_bytes", sa.LargeBinary()),
        sa.Column("after_bytes", sa.LargeBinary(), nullable=False),
        sa.Column("state", sa.String(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now()
        ),
        sa.Column("finished_at", sa.DateTime(timezone=True)),
    )
    op.create_index(
        "ix_file_mutations_editor_workspace_id",
        "file_mutations",
        ["editor_workspace_id"],
    )


def downgrade():
    op.drop_table("file_mutations")
    op.drop_table("editor_workspaces")
