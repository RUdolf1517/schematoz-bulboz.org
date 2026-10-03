"""kombucha diary + drafts

Revision ID: 0011_diary_drafts
Revises: 0010_tasks_hardcore
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "0011_diary_drafts"
down_revision = "0010_tasks_hardcore"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "kombucha_events",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column("kombucha_id", sa.BigInteger(), sa.ForeignKey("kombuchas.id", ondelete="CASCADE"), nullable=False),
        sa.Column("kind", sa.String(24), nullable=False),
        sa.Column("body", sa.String(300), nullable=False),
        sa.Column("emoji", sa.String(16), server_default="📝", nullable=False),
        sa.Column("data", postgresql.JSONB(), server_default=sa.text("'{}'::jsonb"), nullable=False),
        sa.Column("at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_kombucha_events_kb", "kombucha_events", ["kombucha_id", sa.text("id DESC")])
    op.create_table(
        "drafts",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column("user_id", sa.BigInteger(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("kind", sa.String(16), nullable=False),
        sa.Column("question_id", sa.BigInteger(), sa.ForeignKey("questions.id", ondelete="CASCADE")),
        sa.Column("title", sa.String(300), server_default="", nullable=False),
        sa.Column("body", sa.String(5000), server_default="", nullable=False),
        sa.Column("extra", postgresql.JSONB(), server_default=sa.text("'{}'::jsonb"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_drafts_user", "drafts", ["user_id", sa.text("updated_at DESC")])
    op.create_index("uq_drafts_answer", "drafts", ["user_id", "question_id"], unique=True,
                    postgresql_where=sa.text("kind = 'answer'"))


def downgrade() -> None:
    op.drop_table("drafts")
    op.drop_table("kombucha_events")
