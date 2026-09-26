"""login keys (файл входа)

Revision ID: 0004_login_keys
Revises: 6bde81f6aaed
"""
from alembic import op
import sqlalchemy as sa

revision = "0004_login_keys"
down_revision = "6bde81f6aaed"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "login_keys",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("user_id", sa.BigInteger(), nullable=False),
        sa.Column("key_hash", sa.String(length=64), nullable=False),
        sa.Column("label", sa.String(length=64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("last_used_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], name=op.f("fk_login_keys_user_id_users"), ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_login_keys")),
        sa.UniqueConstraint("key_hash", name=op.f("uq_login_keys_key_hash")),
    )
    op.create_index(op.f("ix_login_keys_user_id"), "login_keys", ["user_id"])


def downgrade() -> None:
    op.drop_index(op.f("ix_login_keys_user_id"), table_name="login_keys")
    op.drop_table("login_keys")
