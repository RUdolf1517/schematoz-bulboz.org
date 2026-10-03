"""Цитаты гриба из админки; роль модератора упразднена (остаются игрок и админ).

Revision ID: 0013_quotes_no_moderators
Revises: 0012_tamagotchi
"""
import sqlalchemy as sa
from alembic import op

revision = "0013_quotes_no_moderators"
down_revision = "0012_tamagotchi"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "kombucha_quotes",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("kind", sa.String(16), nullable=False),
        sa.Column("body", sa.Text, nullable=False),
        sa.Column("author", sa.String(80), nullable=False, server_default=""),
        sa.Column("source", sa.String(120), nullable=False, server_default=""),
        sa.Column("enabled", sa.Boolean, nullable=False, server_default=sa.true()),
        sa.Column("created_by", sa.Integer, sa.ForeignKey("users.id", ondelete="SET NULL")),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint("kind IN ('dubious', 'philo')", name="ck_quote_kind"),
    )
    op.create_index("ix_kombucha_quotes_kind", "kombucha_quotes", ["kind"])
    # модераторы становятся обычными игроками (их баны и записи лога остаются)
    op.execute("DELETE FROM roles WHERE code = 'moderator'")
    op.execute("UPDATE users SET rating_tier = 0 WHERE rating_tier = 1")


def downgrade() -> None:
    op.drop_table("kombucha_quotes")
