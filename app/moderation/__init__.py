"""Баны и апелляции (JSON API): /mod/*. Модераторов нет — всё это права админа."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from flask import Blueprint, g, request
from sqlalchemy import func, select

from ..auth.rbac import require_perm
from ..auth.sessions import revoke_all_sessions
from ..db import session_scope
from ..errors import ApiError
from ..models import AppealStatus, Ban, BanScope, ModAction, User
from ..services.modlog import log_action
from ..services.notifications import notify
from ..api.utils import json_body

bp = Blueprint("mod", __name__, url_prefix="/mod")

MAX_MOD_BAN_DAYS = 30


@bp.get("/users")
@require_perm("ban.temporary")
async def find_users():
    """Поиск игрока по нику (для бана) + его активные баны."""
    q = (request.args.get("q") or "").strip().lower()
    if len(q) < 2:
        return {"items": []}
    async with session_scope() as s:
        users = (await s.scalars(select(User).where(User.username.contains(q, autoescape=True))
                                 .order_by(func.length(User.username)).limit(20))).all()
        now = datetime.now(timezone.utc)
        bans = {b.user_id: b for b in (await s.scalars(select(Ban).where(
            Ban.user_id.in_([u.id for u in users]), Ban.lifted_at.is_(None),
            (Ban.ends_at.is_(None)) | (Ban.ends_at > now)))).all()} if users else {}
    from ..services import antibot
    return {"items": [{"id": u.id, "username": u.username, "display_name": u.display_name,
                       "bot_flags": antibot.flags(u.id),
                       "ban": {"id": bans[u.id].id, "reason": bans[u.id].reason,
                               "ends_at": bans[u.id].ends_at.isoformat() if bans[u.id].ends_at else None}
                       if u.id in bans else None} for u in users]}


@bp.post("/bans")
@require_perm("ban.temporary")
async def ban():
    """{user_id, reason, days (1..30 | null = перманент, только admin)}"""
    data = json_body()
    user_id, reason, days = data.get("user_id"), (data.get("reason") or "").strip(), data.get("days")
    if not isinstance(user_id, int) or not reason:
        raise ApiError("user_id и reason обязательны", 400, "validation_error")
    if days is None:
        if "ban.permanent" not in g.perms:
            raise ApiError("Перманентный бан — только администратор", 403, "forbidden")
        ends_at = None
    else:
        if not isinstance(days, int) or days < 1:
            raise ApiError("days — целое ≥ 1", 400, "validation_error")
        if days > MAX_MOD_BAN_DAYS and "ban.permanent" not in g.perms:
            raise ApiError(f"Модератор может банить максимум на {MAX_MOD_BAN_DAYS} дней", 403, "forbidden")
        ends_at = datetime.now(timezone.utc) + timedelta(days=days)
    if user_id == g.user.id:
        raise ApiError("Себя банить нельзя", 400, "self_ban")
    async with session_scope() as s:
        if await s.get(User, user_id) is None:
            raise ApiError("Пользователь не найден", 404, "not_found")
        b = Ban(user_id=user_id, issued_by=g.user.id, reason=reason, scope=BanScope.GLOBAL,
                ends_at=ends_at)
        s.add(b)
        await s.flush()
        log_action(s, g.user.id, "ban.issue", "user", user_id, ban_id=b.id, days=days, reason=reason)
        notify(s, user_id, "ban", ban_id=b.id, reason=reason,
               until=ends_at.isoformat() if ends_at else None)
        ban_id = b.id
    revoke_all_sessions(user_id)
    return {"ban_id": ban_id, "ends_at": ends_at.isoformat() if ends_at else None}, 201


@bp.post("/bans/<int:ban_id>/lift")
@require_perm("ban.temporary")
async def lift(ban_id: int):
    async with session_scope() as s:
        b = await s.get(Ban, ban_id, with_for_update=True)
        if b is None or b.lifted_at is not None:
            raise ApiError("Бан не найден или уже снят", 404, "not_found")
        if b.issued_by != g.user.id and "ban.lift_any" not in g.perms:
            raise ApiError("Снять чужой бан может только администратор", 403, "forbidden")
        b.lifted_by, b.lifted_at = g.user.id, datetime.now(timezone.utc)
        log_action(s, g.user.id, "ban.lift", "user", b.user_id, ban_id=ban_id)
    return {"ok": True}


def modlog_out(a: ModAction) -> dict:
    return {"id": a.id, "actor_id": a.actor_id, "action": a.action, "target_type": a.target_type,
            "target_id": a.target_id, "payload": a.payload, "created_at": a.created_at.isoformat()}


@bp.get("/log")
@require_perm("modlog.read_own")
async def own_log():
    async with session_scope() as s:
        rows = (await s.scalars(select(ModAction).where(ModAction.actor_id == g.user.id)
                                .order_by(ModAction.id.desc()).limit(100))).all()
    return {"items": [modlog_out(a) for a in rows]}


# ---------- Апелляции ----------
def appeal_out(b: Ban, user: User | None) -> dict:
    return {"ban_id": b.id, "user_id": b.user_id, "username": user.username if user else None,
            "issued_by": b.issued_by, "reason": b.reason, "text": b.appeal_text,
            "ends_at": b.ends_at.isoformat() if b.ends_at else None,
            "appeal_created_at": b.appeal_created_at.isoformat() if b.appeal_created_at else None}


@bp.get("/appeals")
@require_perm("ban.temporary")
async def appeals():
    """Очередь апелляций (все, включая выданные этим админом — помечены own)."""
    async with session_scope() as s:
        rows = (await s.execute(
            select(Ban, User).join(User, User.id == Ban.user_id)
            .where(Ban.appeal_status == AppealStatus.PENDING)
            .order_by(Ban.appeal_created_at)
        )).all()
    return {"items": [{**appeal_out(b, u), "own": b.issued_by == g.user.id} for b, u in rows]}


@bp.post("/appeals/<int:ban_id>/decide")
@require_perm("ban.temporary")
async def decide_appeal(ban_id: int):
    """{decision: accept | reject, comment}. accept снимает бан."""
    data = json_body()
    decision = data.get("decision")
    if decision not in {"accept", "reject"}:
        raise ApiError("decision: accept | reject", 400, "validation_error")
    async with session_scope() as s:
        b = await s.get(Ban, ban_id, with_for_update=True)
        if b is None or b.appeal_status != AppealStatus.PENDING:
            raise ApiError("Апелляция не найдена", 404, "not_found")
        if decision == "accept" and b.ends_at is None and "ban.lift_any" not in g.perms:
            raise ApiError("Перманентный бан снимает только администратор", 403, "forbidden")
        now = datetime.now(timezone.utc)
        b.appeal_status = AppealStatus.ACCEPTED if decision == "accept" else AppealStatus.REJECTED
        b.appeal_resolved_by, b.appeal_resolved_at = g.user.id, now
        b.appeal_comment = (data.get("comment") or "").strip() or None
        if decision == "accept":
            b.lifted_by, b.lifted_at = g.user.id, now
        log_action(s, g.user.id, f"appeal.{decision}", "user", b.user_id, ban_id=ban_id,
                   comment=b.appeal_comment)
        notify(s, b.user_id, "appeal", ban_id=ban_id, decision=decision, comment=b.appeal_comment)
    return {"ok": True, "appeal_status": b.appeal_status.value}
