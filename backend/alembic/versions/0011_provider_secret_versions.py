"""Add provider credential encryption version metadata."""

import sqlalchemy as sa

from alembic import op

revision = "0011"
down_revision = "0010"


def upgrade():
    op.add_column("provider_configurations", sa.Column("api_key_version", sa.String()))
    op.execute(
        "UPDATE provider_configurations "
        "SET api_key_version = 'legacy-jwt-v0' "
        "WHERE api_key_encrypted IS NOT NULL"
    )


def downgrade():
    op.drop_column("provider_configurations", "api_key_version")
