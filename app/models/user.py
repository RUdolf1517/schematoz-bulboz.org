from __future__ import annotations

from datetime import date, datetime

from sqlalchemy import BigInteger, Column, DateTime, Float, ForeignKey, Index, SmallInteger, String, Table, Text, func, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .base import Base, TimestampMixin

role_permissions = Table(
    "role_permissions",
    Base.metadata,
    Column("role_id", ForeignKey("roles.id", ondelete="CASCADE"), primary_key=True),
    Column("permission_id", ForeignKey("permissions.id", ondelete="CASCADE"), primary_key=True),
)


class Role(Base):
    __tablename__ = "roles"
    id: Mapped[int] = mapped_column(primary_key=True)
    code: Mapped[str] = mapped_column(String(32), unique=True)
    title: Mapped[str] = mapped_column(String(64))
    permissions: Mapped[list["Permission"]] = relationship(secondary=role_permissions, lazy="selectin")


class Permission(Base):
    __tablename__ = "permissions"
    id: Mapped[int] = mapped_column(primary_key=True)
    code: Mapped[str] = mapped_column(String(64), unique=True)


class UserRole(Base):
    __tablename__ = "user_roles"
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), primary_key=True)
    role_id: Mapped[int] = mapped_column(ForeignKey("roles.id", ondelete="CASCADE"), primary_key=True)
    granted_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    granted_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class User(TimestampMixin, Base):
    __tablename__ = "users"
    __table_args__ = (Index("ix_users_rating_rank", text("rating_tier DESC"), text("rating DESC")),)
    id: Mapped[int] = mapped_column(primary_key=True)
    username: Mapped[str] = mapped_column(String(32), unique=True)  # хранится в lower-case
    email: Mapped[str] = mapped_column(String(254), unique=True)    # хранится в lower-case
    password_hash: Mapped[str] = mapped_column(Text)
    display_name: Mapped[str] = mapped_column(String(64))
    bio: Mapped[str | None] = mapped_column(String(300))
    avatar_url: Mapped[str | None] = mapped_column(Text)
    birth_year: Mapped[int] = mapped_column(SmallInteger)
    reputation: Mapped[int] = mapped_column(default=0, server_default="0")
    level: Mapped[int] = mapped_column(SmallInteger, default=1, server_default="1")
    streak_days: Mapped[int] = mapped_column(default=0, server_default="0")
    wood: Mapped[int] = mapped_column(BigInteger, default=0, server_default="0")   # «Деревянные», $₽
    jars: Mapped[int] = mapped_column(SmallInteger, default=1, server_default="1")  # банок для грибов
    streak_last_date: Mapped[date | None]
    # ISO-неделя последней использованной заморозки стрика, например "2026-W39"
    streak_freeze_week: Mapped[str | None] = mapped_column(String(8))
    last_seen_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # Рейтинг юзера (формула в services/rating.py). rating_tier: 2 — админ (∞), 1 — модер (∞, но ниже админа), 0 — все
    rating: Mapped[float] = mapped_column(Float, default=0.0, server_default="0")
    rating_tier: Mapped[int] = mapped_column(SmallInteger, default=0, server_default="0")
    # Кастомизация профиля: обложка + JSON с настройками (схема и валидация — services/profile_custom.py)
    banner_url: Mapped[str | None] = mapped_column(String(128))
    profile: Mapped[dict] = mapped_column(JSONB, default=dict, server_default=text("'{}'::jsonb"))

    roles: Mapped[list[Role]] = relationship(
        secondary="user_roles",
        primaryjoin="User.id == UserRole.user_id",
        secondaryjoin="Role.id == UserRole.role_id",
        lazy="selectin",
        viewonly=True,
    )


class LoginKey(Base):
    """Ключ из «файла входа». Храним только sha256 — сам ключ видит лишь пользователь."""
    __tablename__ = "login_keys"
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    key_hash: Mapped[str] = mapped_column(String(64), unique=True)
    label: Mapped[str] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
