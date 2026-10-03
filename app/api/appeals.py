"""Бан и апелляция глазами пользователя."""
from __future__ import annotations

from datetime import datetime, timezone

from flask import g
from sqlalchemy import select

from ..auth.rbac import active_global_ban, login_required
from ..db import session_scope
from ..errors import ApiError
from ..models import AppealStatus, Ban
from . import bp
from .utils import json_body, req_str


def ban_out(b: Ban) -> dict:
    return {"id": b.id, "reason": b.reason, "starts_at": b.starts_at.isoformat(),
            "ends_at": b.ends_at.isoformat() if b.ends_at else None,
            "appeal_status": b.appeal_status.value, "appeal_text": b.appeal_text,
            "appeal_comment": b.appeal_comment}


@bp.get("/me/ban")
@login_required
async def my_ban():
    ban = await active_global_ban(g.user.id)
    return {"ban": ban_out(ban) if ban else None}


@bp.post("/bans/<int:ban_id>/appeal")
@login_required  # без проверки бана — забаненный должен иметь возможность обжаловать
async def appeal(ban_id: int):
    text = req_str(json_body(), "text", min_len=10, max_len=2000)
    async with session_scope() as s:
        b = await s.get(Ban, ban_id, with_for_update=True)
        if b is None or b.user_id != g.user.id:
            raise ApiError("Бан не найден", 404, "not_found")
        if b.appeal_status != AppealStatus.NONE:
            raise ApiError("Апелляцию по этому бану уже подавали", 409, "already_appealed")
        b.appeal_status, b.appeal_text = AppealStatus.PENDING, text
        b.appeal_created_at = datetime.now(timezone.utc)
    return {"ok": True, "appeal_status": "pending"}
