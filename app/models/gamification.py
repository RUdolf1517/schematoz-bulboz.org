from __future__ import annotations

from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Index, String, func, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base


class UserBadge(Base):
    """Выданный бейдж. Каталог бейджей — в коде (app/services/badges.py),
    чтобы названия/описания правились без миграций."""
    __tablename__ = "user_badges"
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), primary_key=True)
    code: Mapped[str] = mapped_column(String(32), primary_key=True)
    awarded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Notification(Base):
    """Уведомление внутри сайта. kind: answer | scheme | badge | ban | appeal | follow.
    payload — всё, что нужно для текста и ссылки (question_id, answer_id, username, code…)."""
    __tablename__ = "notifications"
    __table_args__ = (Index("ix_notifications_user", "user_id", "is_read", text("id DESC")),)
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    kind: Mapped[str] = mapped_column(String(32))
    payload: Mapped[dict] = mapped_column(JSONB, default=dict)
    is_read: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Kombucha(Base):
    """Мини-игра «Чайный гриб»: один живой гриб на юзера.
    Показатели хранятся «на момент updated_at», убывание со временем досчитывается
    при чтении (app/services/kombucha.py) — никаких кронов."""
    __tablename__ = "kombuchas"
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), primary_key=True)
    name: Mapped[str] = mapped_column(String(32), default="Гриша")
    xp: Mapped[int] = mapped_column(default=0, server_default="0")
    best_xp: Mapped[int] = mapped_column(default=0, server_default="0")
    generation: Mapped[int] = mapped_column(default=1, server_default="1")
    sweet: Mapped[float] = mapped_column(default=70.0)
    tea: Mapped[float] = mapped_column(default=70.0)
    clean: Mapped[float] = mapped_column(default=90.0)
    happy: Mapped[float] = mapped_column(default=70.0)
    alive: Mapped[bool] = mapped_column(Boolean, default=True, server_default="true")
    zero_since: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    cooldowns: Mapped[dict] = mapped_column(JSONB, default=dict, server_default=text("'{}'::jsonb"))
    born_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    died_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
