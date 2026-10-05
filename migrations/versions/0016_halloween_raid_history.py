"""Persist completed Halloween raid archives and hat presentation metadata.

Revision ID: 0016_halloween_raid_history
Revises: 0015_halloween_raid_teams
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "0016_halloween_raid_history"
down_revision = "0015_halloween_raid_teams"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("kombuchas", sa.Column("halloween_hat_meta", postgresql.JSONB(astext_type=sa.Text()), nullable=True))
    op.create_table(
        "halloween_raid_archives",
        sa.Column("event_key", sa.String(length=64), nullable=False),
        sa.Column("summary", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("archived_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("event_key", name=op.f("pk_halloween_raid_archives")),
    )
    op.create_index("ix_halloween_raid_archives_archived_at", "halloween_raid_archives",
                    [sa.text("archived_at DESC")], unique=False)


def downgrade() -> None:
    op.drop_index("ix_halloween_raid_archives_archived_at", table_name="halloween_raid_archives")
    op.drop_table("halloween_raid_archives")
    op.drop_column("kombuchas", "halloween_hat_meta")
