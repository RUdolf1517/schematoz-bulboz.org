"""«Деревянные» ($₽), несколько грибов на юзера, мутации, уникальные имена грибов

Revision ID: 0008_wood_kombucha
Revises: 0007_kombucha
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "0008_wood_kombucha"
down_revision = "0007_kombucha"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("users", sa.Column("wood", sa.BigInteger(), server_default="0", nullable=False))
    op.add_column("users", sa.Column("jars", sa.SmallInteger(), server_default="1", nullable=False))

    # kombuchas: PK user_id → id (у юзера теперь может быть несколько грибов)
    op.drop_constraint("pk_kombuchas", "kombuchas", type_="primary")
    op.execute("ALTER TABLE kombuchas ADD COLUMN id BIGSERIAL")
    op.create_primary_key("pk_kombuchas", "kombuchas", ["id"])
    op.create_index("ix_kombuchas_user_id", "kombuchas", ["user_id"])
    op.add_column("kombuchas", sa.Column("parent_id", sa.BigInteger(), nullable=True))
    op.create_foreign_key("fk_kombuchas_parent_id_kombuchas", "kombuchas", "kombuchas", ["parent_id"], ["id"],
                          ondelete="SET NULL")
    op.add_column("kombuchas", sa.Column("mutations", postgresql.JSONB(astext_type=sa.Text()),
                                         server_default=sa.text("'[]'::jsonb"), nullable=False))
    op.add_column("kombuchas", sa.Column("care_days", sa.BigInteger(), server_default="0", nullable=False))
    op.add_column("kombuchas", sa.Column("last_care_day", sa.Date(), nullable=True))
    op.add_column("kombuchas", sa.Column("pet_count", sa.BigInteger(), server_default="0", nullable=False))
    op.add_column("kombuchas", sa.Column("sprouted", sa.Boolean(), server_default="false", nullable=False))
    op.add_column("kombuchas", sa.Column("sprout_pending", sa.Boolean(), server_default="false", nullable=False))
    op.alter_column("kombuchas", "name", server_default=None)
    # имена были по умолчанию «Гриша» у всех — делаем уникальными до создания индекса
    op.execute("""
        UPDATE kombuchas k SET name = left(k.name, 24) || ' ' || k.id
        WHERE EXISTS (SELECT 1 FROM kombuchas o WHERE lower(o.name) = lower(k.name) AND o.id < k.id)
    """)
    op.create_index("uq_kombuchas_name_lower", "kombuchas", [sa.text("lower(name)")], unique=True)

    op.create_table(
        "kombucha_codex",
        sa.Column("user_id", sa.BigInteger(), nullable=False),
        sa.Column("code", sa.String(length=32), nullable=False),
        sa.Column("kombucha_name", sa.String(length=32), nullable=True),
        sa.Column("found_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], name=op.f("fk_kombucha_codex_user_id_users"),
                                ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("user_id", "code", name=op.f("pk_kombucha_codex")),
    )
    op.create_table(
        "wood_tx",
        sa.Column("id", sa.BigInteger(), nullable=False),
        sa.Column("user_id", sa.BigInteger(), nullable=False),
        sa.Column("delta", sa.BigInteger(), nullable=False),
        sa.Column("reason", sa.String(length=32), nullable=False),
        sa.Column("ref", sa.String(length=64), nullable=False),
        sa.Column("balance_after", sa.BigInteger(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], name=op.f("fk_wood_tx_user_id_users"), ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_wood_tx")),
    )
    op.create_index("uq_wood_tx_ref", "wood_tx", ["user_id", "reason", "ref"], unique=True)
    op.create_index("ix_wood_tx_user", "wood_tx", ["user_id", sa.text("id DESC")])


def downgrade() -> None:
    op.drop_index("ix_wood_tx_user", table_name="wood_tx")
    op.drop_index("uq_wood_tx_ref", table_name="wood_tx")
    op.drop_table("wood_tx")
    op.drop_table("kombucha_codex")
    op.drop_index("uq_kombuchas_name_lower", table_name="kombuchas")
    # назад к «один гриб на юзера»: оставляем самый старый
    op.execute("DELETE FROM kombuchas k WHERE EXISTS (SELECT 1 FROM kombuchas o WHERE o.user_id = k.user_id AND o.id < k.id)")
    for col in ("sprout_pending", "sprouted", "pet_count", "last_care_day", "care_days", "mutations"):
        op.drop_column("kombuchas", col)
    op.drop_constraint("fk_kombuchas_parent_id_kombuchas", "kombuchas", type_="foreignkey")
    op.drop_column("kombuchas", "parent_id")
    op.drop_index("ix_kombuchas_user_id", table_name="kombuchas")
    op.drop_constraint("pk_kombuchas", "kombuchas", type_="primary")
    op.drop_column("kombuchas", "id")
    op.create_primary_key("pk_kombuchas", "kombuchas", ["user_id"])
    op.drop_column("users", "jars")
    op.drop_column("users", "wood")
