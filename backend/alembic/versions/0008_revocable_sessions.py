"""Add revocable login sessions and rotating refresh credentials."""

import sqlalchemy as sa

from alembic import op

revision = "0008"
down_revision = "0007"


def upgrade():
    op.create_table(
        "user_sessions",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("user_id", sa.String(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("user_agent", sa.String(), nullable=False, server_default=""),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True)),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now()
        ),
    )
    op.create_index("ix_user_sessions_user_id", "user_sessions", ["user_id"])
    op.create_index("ix_user_sessions_expires_at", "user_sessions", ["expires_at"])
    op.create_table(
        "refresh_credentials",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column(
            "session_id",
            sa.String(),
            sa.ForeignKey("user_sessions.id"),
            nullable=False,
        ),
        sa.Column("token_hash", sa.String(), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("used_at", sa.DateTime(timezone=True)),
        sa.Column("replaced_by_id", sa.String()),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now()
        ),
        sa.ForeignKeyConstraint(
            ["replaced_by_id"], ["refresh_credentials.id"], ondelete="SET NULL"
        ),
    )
    op.create_index(
        "ix_refresh_credentials_session_id", "refresh_credentials", ["session_id"]
    )
    op.create_index(
        "ix_refresh_credentials_token_hash",
        "refresh_credentials",
        ["token_hash"],
        unique=True,
    )
    op.create_index(
        "ix_refresh_credentials_expires_at", "refresh_credentials", ["expires_at"]
    )


def downgrade():
    op.drop_table("refresh_credentials")
    op.drop_table("user_sessions")
