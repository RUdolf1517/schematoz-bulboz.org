from __future__ import annotations

from datetime import date, datetime

from sqlalchemy import Boolean, Date, DateTime, ForeignKey, Index, Integer, String, Text, UniqueConstraint, func, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base


class PushPreference(Base):
    """PWA push preferences: independent alert switches, quiet hours and local timezone."""
    __tablename__ = "push_preferences"
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), primary_key=True)
    enabled: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
    categories: Mapped[dict] = mapped_column(JSONB, default=dict, server_default=text("'{}'::jsonb"))
    quiet_start: Mapped[str] = mapped_column(String(5), default="23:00", server_default="23:00")
    quiet_end: Mapped[str] = mapped_column(String(5), default="09:00", server_default="09:00")
    timezone: Mapped[str] = mapped_column(String(64), default="Europe/Moscow", server_default="Europe/Moscow")
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


class PushSubscription(Base):
    """Web Push endpoint and browser encryption keys. One user may have several devices."""
    __tablename__ = "push_subscriptions"
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    endpoint: Mapped[str] = mapped_column(String(2048), unique=True)
    p256dh: Mapped[str] = mapped_column(String(128))
    auth: Mapped[str] = mapped_column(String(64))
    user_agent: Mapped[str] = mapped_column(String(256), default="", server_default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class PushQueue(Base):
    """Transactional outbox. Web Push is delivered by the scheduled CLI job, never in a request."""
    __tablename__ = "push_queue"
    __table_args__ = (
        UniqueConstraint("user_id", "dedupe_key", name="uq_push_queue_user_dedupe"),
        Index("ix_push_queue_pending", "sent_at", "scheduled_at"),
    )
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    category: Mapped[str] = mapped_column(String(32))
    dedupe_key: Mapped[str] = mapped_column(String(128))
    title: Mapped[str] = mapped_column(String(120))
    body: Mapped[str] = mapped_column(String(300))
    url: Mapped[str] = mapped_column(String(512), default="/", server_default="/")
    scheduled_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    attempts: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    last_error: Mapped[str | None] = mapped_column(Text)


class HalloweenTreat(Base):
    """One trick-or-treat result per visitor, mushroom and event day."""
    __tablename__ = "halloween_treats"
    __table_args__ = (
        UniqueConstraint("actor_user_id", "kombucha_id", "day", name="uq_halloween_treat_daily"),
        Index("ix_halloween_treat_day", "day"),
    )
    id: Mapped[int] = mapped_column(primary_key=True)
    actor_user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    kombucha_id: Mapped[int] = mapped_column(ForeignKey("kombuchas.id", ondelete="CASCADE"))
    owner_user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    day: Mapped[date] = mapped_column(Date, nullable=False)
    reward: Mapped[str] = mapped_column(String(24))
    reward_code: Mapped[str | None] = mapped_column(String(32))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class HalloweenRaid(Base):
    """Shared Halloween raid boss (the app currently has no club/group model)."""
    __tablename__ = "halloween_raid"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    hp: Mapped[int] = mapped_column(Integer, default=10000, server_default="10000")
    max_hp: Mapped[int] = mapped_column(Integer, default=10000, server_default="10000")
    phase: Mapped[int] = mapped_column(Integer, default=1, server_default="1")
    total_damage: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class HalloweenRaidPlayer(Base):
    """Player's shared-raid team, per-phase contribution, earned gifts and tap throttle."""
    __tablename__ = "halloween_raid_players"
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), primary_key=True)
    last_tap_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    damage: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    kombucha_ids: Mapped[list] = mapped_column(JSONB, default=list, server_default=text("'[]'::jsonb"))
    stage_damage: Mapped[dict] = mapped_column(JSONB, default=dict, server_default=text("'{}'::jsonb"))
    gifts_received: Mapped[list] = mapped_column(JSONB, default=list, server_default=text("'[]'::jsonb"))
