"""Enforce one role per user and workspace."""

import sqlalchemy as sa

from alembic import op

revision = "0007"
down_revision = "0006"


def upgrade():
    op.execute("UPDATE workspace_members SET role = 'member' WHERE role IS NULL")
    op.execute(
        "DELETE FROM workspace_members WHERE id IN ("
        "SELECT id FROM ("
        "SELECT id, ROW_NUMBER() OVER ("
        "PARTITION BY workspace_id, user_id ORDER BY "
        "CASE role WHEN 'owner' THEN 1 WHEN 'administrator' THEN 2 "
        "WHEN 'member' THEN 3 WHEN 'viewer' THEN 4 ELSE 5 END, id"
        ") AS duplicate_rank FROM workspace_members"
        ") ranked WHERE duplicate_rank > 1)"
    )
    with op.batch_alter_table("workspace_members") as batch:
        batch.alter_column("role", existing_type=sa.String(), nullable=False)
        batch.create_unique_constraint(
            "uq_workspace_member", ["workspace_id", "user_id"]
        )


def downgrade():
    with op.batch_alter_table("workspace_members") as batch:
        batch.drop_constraint("uq_workspace_member", type_="unique")
        batch.alter_column("role", existing_type=sa.String(), nullable=True)
