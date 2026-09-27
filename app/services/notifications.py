"""Уведомления внутри сайта. Пишутся в той же транзакции, что и событие.
Пуши в мобилку (FCM/APNs) позже будут читать эту же таблицу воркером."""
from __future__ import annotations

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from ..models import Notification

KINDS = {"answer", "scheme", "badge", "ban", "appeal", "follow", "comment", "trade", "sale", "wall"}


def notify(s: AsyncSession, user_id: int, kind: str, **payload) -> Notification:
    assert kind in KINDS, kind
    n = Notification(user_id=user_id, kind=kind, payload=payload)
    s.add(n)
    return n


async def unread_count(s: AsyncSession, user_id: int) -> int:
    return await s.scalar(select(func.count(Notification.id)).where(
        Notification.user_id == user_id, Notification.is_read.is_(False))) or 0


async def mark_read(s: AsyncSession, user_id: int, ids: list[int] | None = None) -> int:
    stmt = update(Notification).where(Notification.user_id == user_id, Notification.is_read.is_(False))
    if ids is not None:
        stmt = stmt.where(Notification.id.in_(ids))
    res = await s.execute(stmt.values(is_read=True))
    return res.rowcount or 0
