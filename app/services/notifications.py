"""Уведомления внутри сайта. Пишутся в той же транзакции, что и событие.
Web Push использует отдельную транзакционную outbox-очередь из app.services.push."""
from __future__ import annotations

from sqlalchemy import func, select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from ..models import Notification

KINDS = {"badge", "ban", "appeal", "trade", "sale", "kombucha", "halloween"}


def notify(s: AsyncSession, user_id: int, kind: str, **payload) -> Notification:
    assert kind in KINDS, kind
    n = Notification(user_id=user_id, kind=kind, payload=payload)
    s.add(n)
    return n


async def notify_once(s: AsyncSession, user_id: int, kind: str, dedupe_key: str, **payload) -> bool:
    """Create one in-site alert per logical event, even if the scheduler runs repeatedly."""
    assert kind in KINDS, kind
    result = await s.execute(
        insert(Notification).values(user_id=user_id, kind=kind, payload=payload, dedupe_key=dedupe_key[:128])
        .on_conflict_do_nothing(index_elements=["user_id", "dedupe_key"])
        .returning(Notification.id)
    )
    return result.scalar() is not None


async def unread_count(s: AsyncSession, user_id: int) -> int:
    return await s.scalar(select(func.count(Notification.id)).where(
        Notification.user_id == user_id, Notification.is_read.is_(False))) or 0


async def mark_read(s: AsyncSession, user_id: int, ids: list[int] | None = None) -> int:
    stmt = update(Notification).where(Notification.user_id == user_id, Notification.is_read.is_(False))
    if ids is not None:
        stmt = stmt.where(Notification.id.in_(ids))
    res = await s.execute(stmt.values(is_read=True))
    return res.rowcount or 0
