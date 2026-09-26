from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Index, SmallInteger, String, Text, UniqueConstraint, func, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base, pg_enum
from .enums import AppealStatus, BanScope, ReportReason, ReportStatus, ReportTarget


class Report(Base):
    __tablename__ = "reports"
    __table_args__ = (
        UniqueConstraint("reporter_id", "target_type", "target_id", name="uq_reports_once"),
        Index("ix_reports_queue", "status", text("priority DESC"), "created_at"),
    )
    id: Mapped[int] = mapped_column(primary_key=True)
    reporter_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    target_type: Mapped[ReportTarget] = mapped_column(pg_enum(ReportTarget, "report_target"))
    target_id: Mapped[int]
    reason: Mapped[ReportReason] = mapped_column(pg_enum(ReportReason, "report_reason"))
    comment: Mapped[str | None] = mapped_column(String(1000))
    status: Mapped[ReportStatus] = mapped_column(
        pg_enum(ReportStatus, "report_status"), default=ReportStatus.OPEN,
        server_default=ReportStatus.OPEN.value,
    )
    priority: Mapped[int] = mapped_column(SmallInteger, default=0, server_default="0")
    assigned_to: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    resolved_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Ban(Base):
    __tablename__ = "bans"
    __table_args__ = (Index("ix_bans_user_active", "user_id", "ends_at"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    issued_by: Mapped[int] = mapped_column(ForeignKey("users.id"))
    reason: Mapped[str] = mapped_column(Text)
    report_id: Mapped[int | None] = mapped_column(ForeignKey("reports.id"))
    scope: Mapped[BanScope] = mapped_column(pg_enum(BanScope, "ban_scope"), default=BanScope.GLOBAL)
    room_id: Mapped[int | None] = mapped_column(ForeignKey("rooms.id"))
    starts_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    ends_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))  # NULL = перманент
    lifted_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    lifted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    appeal_status: Mapped[AppealStatus] = mapped_column(
        pg_enum(AppealStatus, "appeal_status"), default=AppealStatus.NONE,
        server_default=AppealStatus.NONE.value,
    )
    appeal_text: Mapped[str | None] = mapped_column(Text)
    appeal_created_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    appeal_resolved_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    appeal_resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    appeal_comment: Mapped[str | None] = mapped_column(Text)


class ModAction(Base):
    """Лог действий модераторов/админов. Только INSERT (в проде UPDATE/DELETE
    запрещены правами роли БД — см. миграцию)."""
    __tablename__ = "mod_actions"
    __table_args__ = (Index("ix_mod_actions_actor", "actor_id", text("created_at DESC")),)
    id: Mapped[int] = mapped_column(primary_key=True)
    actor_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    action: Mapped[str] = mapped_column(String(64))
    target_type: Mapped[str] = mapped_column(String(32))
    target_id: Mapped[int | None]
    payload: Mapped[dict | None] = mapped_column(JSONB)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
