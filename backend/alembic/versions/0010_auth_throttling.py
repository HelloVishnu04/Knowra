"""Add persistent authentication throttling state."""

import sqlalchemy as sa

from alembic import op

revision = "0010"
down_revision = "0009"


def upgrade():
    op.create_table(
        "authentication_throttles",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("failure_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("window_started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("locked_until", sa.DateTime(timezone=True)),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()
        ),
    )


def downgrade():
    op.drop_table("authentication_throttles")
