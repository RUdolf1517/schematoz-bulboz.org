"""Уведомления."""
from __future__ import annotations

from flask import g, request
from sqlalchemy import select

from ..auth.rbac import login_required
from ..db import session_scope
from ..errors import ApiError
from ..models import Notification
from ..services.notifications import mark_read, unread_count
from . import bp


# ---------- уведомления ----------
def notification_out(n: Notification) -> dict:
    return {"id": n.id, "kind": n.kind, "payload": n.payload, "is_read": n.is_read,
            "created_at": n.created_at.isoformat()}


@bp.get("/notifications")
@login_required
async def notifications():
    async with session_scope() as s:
        rows = (await s.scalars(select(Notification).where(Notification.user_id == g.user.id)
                                .order_by(Notification.id.desc()).limit(50))).all()
        unread = await unread_count(s, g.user.id)
    return {"items": [notification_out(n) for n in rows], "unread": unread}


@bp.post("/notifications/read")
@login_required
async def notifications_read():
    """{"ids": [..]} — прочитать выбранные; без ids — все."""
    data = request.get_json(silent=True) or {}
    ids = data.get("ids")
    if ids is not None and (not isinstance(ids, list) or not all(isinstance(i, int) for i in ids)):
        raise ApiError("ids — список чисел", 400, "validation_error")
    async with session_scope() as s:
        n = await mark_read(s, g.user.id, ids)
        unread = await unread_count(s, g.user.id)
    return {"marked": n, "unread": unread}
