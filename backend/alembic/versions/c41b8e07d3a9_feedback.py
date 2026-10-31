"""feedback

Revision ID: c41b8e07d3a9
Revises: a7c3d91e5b20
Create Date: 2026-10-28 10:00:00.000000

"""
from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "c41b8e07d3a9"
down_revision: str | Sequence[str] | None = "a7c3d91e5b20"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "feedback",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("identity_id", sa.UUID(), nullable=False),
        sa.Column("run_id", sa.UUID(), nullable=False),
        sa.Column("reaction", sa.String(length=16), nullable=False),
        sa.Column("comment", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["identity_id"], ["identities.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_feedback_identity_id", "feedback", ["identity_id"])
    op.create_index("ix_feedback_run_id", "feedback", ["run_id"], unique=True)


def downgrade() -> None:
    op.drop_index("ix_feedback_run_id", table_name="feedback")
    op.drop_index("ix_feedback_identity_id", table_name="feedback")
    op.drop_table("feedback")
