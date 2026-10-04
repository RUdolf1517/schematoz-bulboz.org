"""Сайт превращается в тамагочи про гриб: Q&A, стена, задания и черновики удалены.

Revision ID: 0012_tamagotchi
Revises: 0011_diary_drafts
"""
from alembic import op

revision = "0012_tamagotchi"
down_revision = "0011_diary_drafts"
branch_labels = None
depends_on = None

DROP = ["drafts", "task_submissions", "tasks", "wall_posts", "comments", "question_votes", "votes",
        "reputation_events", "debate_votes", "answer_media", "follows"]


def upgrade() -> None:
    op.execute("ALTER TABLE bans DROP COLUMN IF EXISTS report_id, DROP COLUMN IF EXISTS room_id")
    for t in DROP + ["answers", "questions", "room_members", "rooms", "categories", "reports"]:
        op.execute(f"DROP TABLE IF EXISTS {t} CASCADE")
    op.execute("DELETE FROM notifications WHERE kind IN ('answer','scheme','follow','task','task_done','comment','wall','mention')")


def downgrade() -> None:
    raise RuntimeError("Q&A-часть удалена насовсем — откатывать некуда")
