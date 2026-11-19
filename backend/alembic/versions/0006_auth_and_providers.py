"""Add persisted model provider configurations."""

import sqlalchemy as sa

from alembic import op

revision = "0006"
down_revision = "0005"


def upgrade():
    op.create_table(
        "provider_configurations",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column(
            "workspace_id",
            sa.String(),
            sa.ForeignKey("workspaces.id"),
            nullable=False,
        ),
        sa.Column("user_id", sa.String(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("provider_type", sa.String(), nullable=False),
        sa.Column("base_url", sa.String(), nullable=False),
        sa.Column("api_key_encrypted", sa.Text()),
        sa.Column("models_json", sa.JSON(), nullable=False),
        sa.Column("is_enabled", sa.Boolean(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now()
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()
        ),
    )
    op.create_index(
        "ix_provider_configurations_workspace_id",
        "provider_configurations",
        ["workspace_id"],
    )
    op.create_index(
        "ix_provider_configurations_user_id",
        "provider_configurations",
        ["user_id"],
    )


def downgrade():
    op.drop_table("provider_configurations")
