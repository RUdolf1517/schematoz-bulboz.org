from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import INET, JSONB
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base


class LegalPage(Base):
    __tablename__ = "legal_pages"
    id: Mapped[int] = mapped_column(primary_key=True)
    slug: Mapped[str] = mapped_column(String(32), unique=True)  # rules|terms|privacy|requisites
    title: Mapped[str] = mapped_column(String(128))
    current_version: Mapped[int] = mapped_column(Integer, default=1)
    requires_consent: Mapped[bool] = mapped_column(default=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class LegalPageVersion(Base):
    __tablename__ = "legal_page_versions"
    __table_args__ = (UniqueConstraint("page_id", "version", name="uq_legal_version"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    page_id: Mapped[int] = mapped_column(ForeignKey("legal_pages.id", ondelete="CASCADE"))
    version: Mapped[int] = mapped_column(Integer)
    body_md: Mapped[str] = mapped_column(Text)
    edited_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class UserConsent(Base):
    __tablename__ = "user_consents"
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    page_slug: Mapped[str] = mapped_column(String(32))
    version: Mapped[int] = mapped_column(Integer)
    ip: Mapped[str | None] = mapped_column(INET)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Setting(Base):
    __tablename__ = "settings"
    key: Mapped[str] = mapped_column(String(64), primary_key=True)
    value: Mapped[dict] = mapped_column(JSONB)
    updated_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
