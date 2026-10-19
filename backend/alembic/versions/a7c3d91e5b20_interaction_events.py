"""interaction events

Revision ID: a7c3d91e5b20
Revises: 0016e7f48c5e
Create Date: 2026-10-19 10:00:00.000000

"""
from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "a7c3d91e5b20"
down_revision: str | Sequence[str] | None = "0016e7f48c5e"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "interaction_events",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("identity_id", sa.UUID(), nullable=False),
        sa.Column("run_id", sa.UUID(), nullable=False),
        sa.Column("event_type", sa.String(length=32), nullable=False),
        sa.Column("payload", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["identity_id"], ["identities.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_interaction_events_identity_id", "interaction_events", ["identity_id"])
    op.create_index("ix_interaction_events_run_id", "interaction_events", ["run_id"])


def downgrade() -> None:
    op.drop_index("ix_interaction_events_run_id", table_name="interaction_events")
    op.drop_index("ix_interaction_events_identity_id", table_name="interaction_events")
    op.drop_table("interaction_events")
