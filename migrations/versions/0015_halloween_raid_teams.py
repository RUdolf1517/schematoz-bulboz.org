"""Save raid teams, per-stage contribution, and earned gifts.

Revision ID: 0015_halloween_raid_teams
Revises: 0014_push_halloween
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "0015_halloween_raid_teams"
down_revision = "0014_push_halloween"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("halloween_raid_players", sa.Column(
        "kombucha_ids", postgresql.JSONB(astext_type=sa.Text()),
        server_default=sa.text("'[]'::jsonb"), nullable=False))
    op.add_column("halloween_raid_players", sa.Column(
        "stage_damage", postgresql.JSONB(astext_type=sa.Text()),
        server_default=sa.text("'{}'::jsonb"), nullable=False))
    op.add_column("halloween_raid_players", sa.Column(
        "gifts_received", postgresql.JSONB(astext_type=sa.Text()),
        server_default=sa.text("'[]'::jsonb"), nullable=False))


def downgrade() -> None:
    op.drop_column("halloween_raid_players", "gifts_received")
    op.drop_column("halloween_raid_players", "stage_damage")
    op.drop_column("halloween_raid_players", "kombucha_ids")
