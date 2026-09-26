"""profile customization + FAQ page

Revision ID: 0006_profile_faq
Revises: 0005_ratings
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "0006_profile_faq"
down_revision = "0005_ratings"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("users", sa.Column("banner_url", sa.String(length=128), nullable=True))
    op.add_column("users", sa.Column("profile", postgresql.JSONB(astext_type=sa.Text()),
                                     server_default=sa.text("'{}'::jsonb"), nullable=False))
    # FAQ — редактируемая админом страница (как юридические). В существующих БД создаём сразу.
    from app.seed import LEGAL
    title, consent, body = LEGAL["faq"]
    conn = op.get_bind()
    if conn.execute(sa.text("SELECT 1 FROM legal_pages WHERE slug = 'faq'")).first() is None \
            and conn.execute(sa.text("SELECT 1 FROM legal_pages LIMIT 1")).first() is not None:
        pid = conn.execute(sa.text(
            "INSERT INTO legal_pages (slug, title, current_version, requires_consent) "
            "VALUES ('faq', :t, 1, false) RETURNING id"), {"t": title}).scalar()
        conn.execute(sa.text("INSERT INTO legal_page_versions (page_id, version, body_md) VALUES (:p, 1, :b)"),
                     {"p": pid, "b": body.strip()})


def downgrade() -> None:
    op.execute("DELETE FROM legal_page_versions WHERE page_id IN (SELECT id FROM legal_pages WHERE slug = 'faq')")
    op.execute("DELETE FROM legal_pages WHERE slug = 'faq'")
    op.drop_column("users", "profile")
    op.drop_column("users", "banner_url")
