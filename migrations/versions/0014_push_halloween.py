"""PWA push outbox, preferences and Halloween event data.

Revision ID: 0014_push_halloween
Revises: 0013_quotes_no_moderators
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "0014_push_halloween"
down_revision = "0013_quotes_no_moderators"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("notifications", sa.Column("dedupe_key", sa.String(length=128), nullable=True))
    op.create_index("uq_notifications_user_dedupe", "notifications", ["user_id", "dedupe_key"], unique=True)

    op.create_table(
        "push_preferences",
        sa.Column("user_id", sa.BigInteger(), nullable=False),
        sa.Column("enabled", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("categories", postgresql.JSONB(astext_type=sa.Text()), server_default=sa.text("'{}'::jsonb"), nullable=False),
        sa.Column("quiet_start", sa.String(length=5), server_default="23:00", nullable=False),
        sa.Column("quiet_end", sa.String(length=5), server_default="09:00", nullable=False),
        sa.Column("timezone", sa.String(length=64), server_default="Europe/Moscow", nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], name=op.f("fk_push_preferences_user_id_users"), ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("user_id", name=op.f("pk_push_preferences")),
    )
    op.create_table(
        "push_subscriptions",
        sa.Column("id", sa.BigInteger(), nullable=False),
        sa.Column("user_id", sa.BigInteger(), nullable=False),
        sa.Column("endpoint", sa.String(length=2048), nullable=False),
        sa.Column("p256dh", sa.String(length=128), nullable=False),
        sa.Column("auth", sa.String(length=64), nullable=False),
        sa.Column("user_agent", sa.String(length=256), server_default="", nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("last_used_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], name=op.f("fk_push_subscriptions_user_id_users"), ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_push_subscriptions")),
        sa.UniqueConstraint("endpoint", name=op.f("uq_push_subscriptions_endpoint")),
    )
    op.create_index(op.f("ix_push_subscriptions_user_id"), "push_subscriptions", ["user_id"], unique=False)
    op.create_table(
        "push_queue",
        sa.Column("id", sa.BigInteger(), nullable=False),
        sa.Column("user_id", sa.BigInteger(), nullable=False),
        sa.Column("category", sa.String(length=32), nullable=False),
        sa.Column("dedupe_key", sa.String(length=128), nullable=False),
        sa.Column("title", sa.String(length=120), nullable=False),
        sa.Column("body", sa.String(length=300), nullable=False),
        sa.Column("url", sa.String(length=512), server_default="/", nullable=False),
        sa.Column("scheduled_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("sent_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("attempts", sa.Integer(), server_default="0", nullable=False),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], name=op.f("fk_push_queue_user_id_users"), ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_push_queue")),
        sa.UniqueConstraint("user_id", "dedupe_key", name="uq_push_queue_user_dedupe"),
    )
    op.create_index("ix_push_queue_pending", "push_queue", ["sent_at", "scheduled_at"], unique=False)

    op.add_column("kombuchas", sa.Column("halloween_hat", sa.String(length=24), nullable=True))
    op.add_column("kombuchas", sa.Column("halloween_mutations", postgresql.JSONB(astext_type=sa.Text()),
                                         server_default=sa.text("'[]'::jsonb"), nullable=False))
    op.add_column("kombuchas", sa.Column("halloween_gone_day", sa.Date(), nullable=True))
    op.add_column("kombuchas", sa.Column("halloween_gone", sa.Boolean(), server_default=sa.text("false"), nullable=False))
    op.add_column("kombuchas", sa.Column("halloween_web_until", sa.DateTime(timezone=True), nullable=True))

    # Earlier revisions used either of these names depending on SQLAlchemy's naming convention.
    op.execute("ALTER TABLE kombucha_quotes DROP CONSTRAINT IF EXISTS ck_quote_kind")
    op.execute("ALTER TABLE kombucha_quotes DROP CONSTRAINT IF EXISTS ck_kombucha_quotes_ck_quote_kind")
    op.execute("ALTER TABLE kombucha_quotes ADD CONSTRAINT ck_kombucha_quotes_kind_allowed "
               "CHECK (kind IN ('dubious', 'philo', 'halloween'))")

    op.create_table(
        "halloween_treats",
        sa.Column("id", sa.BigInteger(), nullable=False),
        sa.Column("actor_user_id", sa.BigInteger(), nullable=False),
        sa.Column("kombucha_id", sa.BigInteger(), nullable=False),
        sa.Column("owner_user_id", sa.BigInteger(), nullable=False),
        sa.Column("day", sa.Date(), nullable=False),
        sa.Column("reward", sa.String(length=24), nullable=False),
        sa.Column("reward_code", sa.String(length=32), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["actor_user_id"], ["users.id"], name=op.f("fk_halloween_treats_actor_user_id_users"), ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["kombucha_id"], ["kombuchas.id"], name=op.f("fk_halloween_treats_kombucha_id_kombuchas"), ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["owner_user_id"], ["users.id"], name=op.f("fk_halloween_treats_owner_user_id_users"), ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_halloween_treats")),
        sa.UniqueConstraint("actor_user_id", "kombucha_id", "day", name="uq_halloween_treat_daily"),
    )
    op.create_index("ix_halloween_treat_day", "halloween_treats", ["day"], unique=False)

    op.create_table(
        "halloween_raid",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("hp", sa.Integer(), server_default="10000", nullable=False),
        sa.Column("max_hp", sa.Integer(), server_default="10000", nullable=False),
        sa.Column("phase", sa.Integer(), server_default="1", nullable=False),
        sa.Column("total_damage", sa.Integer(), server_default="0", nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_halloween_raid")),
        sa.CheckConstraint("id = 1", name="ck_halloween_raid_singleton"),
    )
    op.execute("INSERT INTO halloween_raid (id, hp, max_hp, phase, total_damage) VALUES (1, 10000, 10000, 1, 0)")
    op.create_table(
        "halloween_raid_players",
        sa.Column("user_id", sa.BigInteger(), nullable=False),
        sa.Column("last_tap_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("damage", sa.Integer(), server_default="0", nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], name=op.f("fk_halloween_raid_players_user_id_users"), ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("user_id", name=op.f("pk_halloween_raid_players")),
    )


def downgrade() -> None:
    op.drop_table("halloween_raid_players")
    op.drop_table("halloween_raid")
    op.drop_index("ix_halloween_treat_day", table_name="halloween_treats")
    op.drop_table("halloween_treats")
    op.execute("ALTER TABLE kombucha_quotes DROP CONSTRAINT IF EXISTS ck_kombucha_quotes_kind_allowed")
    op.execute("ALTER TABLE kombucha_quotes ADD CONSTRAINT ck_quote_kind CHECK (kind IN ('dubious', 'philo'))")
    for col in ("halloween_web_until", "halloween_gone", "halloween_gone_day", "halloween_mutations", "halloween_hat"):
        op.drop_column("kombuchas", col)
    op.drop_index("ix_push_queue_pending", table_name="push_queue")
    op.drop_table("push_queue")
    op.drop_index(op.f("ix_push_subscriptions_user_id"), table_name="push_subscriptions")
    op.drop_table("push_subscriptions")
    op.drop_table("push_preferences")
    op.drop_index("uq_notifications_user_dedupe", table_name="notifications")
    op.drop_column("notifications", "dedupe_key")
