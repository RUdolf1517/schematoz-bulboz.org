"""Модераторская панель (JSON API): /mod/*"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from flask import Blueprint, g, request
from sqlalchemy import func, select

from ..auth.rbac import require_perm
from ..auth.sessions import revoke_all_sessions
from ..db import session_scope
from ..errors import ApiError
from ..models import (
    Answer, AppealStatus, Ban, BanScope, Comment, ContentStatus, ModAction, Question, Report,
    ReportStatus, ReportTarget, User,
)
from ..services.modlog import log_action
from ..services.notifications import notify
from ..api.utils import json_body

bp = Blueprint("mod", __name__, url_prefix="/mod")

CONTENT = {"question": Question, "answer": Answer, "comment": Comment}
MAX_MOD_BAN_DAYS = 30


def _report_out(r: Report) -> dict:
    return {"id": r.id, "target_type": r.target_type.value, "target_id": r.target_id,
            "reason": r.reason.value, "comment": r.comment, "status": r.status.value,
            "priority": r.priority, "reporter_id": r.reporter_id,
            "created_at": r.created_at.isoformat()}


async def _target_preview(s, r: Report) -> dict | None:
    """Контекст для модератора: что именно обжаловали и кто автор."""
    if r.target_type is ReportTarget.USER:
        u = await s.get(User, r.target_id)
        return u and {"author_id": u.id, "author": u.username, "text": u.bio or "", "status": None}
    model = CONTENT[r.target_type.value]
    obj = await s.get(model, r.target_id)
    if obj is None:
        return None
    author = await s.get(User, obj.author_id)
    text = obj.title if isinstance(obj, Question) else (obj.body or "")
    qid = obj.id if isinstance(obj, Question) else obj.question_id
    return {"author_id": author.id, "author": author.username, "text": text[:500],
            "status": obj.status.value, "question_id": qid}


@bp.get("/reports")
@require_perm("report.review")
async def queue():
    try:
        status = ReportStatus(request.args.get("status", "open"))
    except ValueError:
        raise ApiError("Неизвестный статус", 400, "validation_error")
    async with session_scope() as s:
        rows = (await s.scalars(
            select(Report).where(Report.status == status)
            .order_by(Report.priority.desc(), Report.created_at).limit(50)
        )).all()
        items = []
        for r in rows:
            same = await s.scalar(select(func.count(Report.id)).where(
                Report.target_type == r.target_type, Report.target_id == r.target_id,
                Report.status == status))
            items.append({**_report_out(r), "target": await _target_preview(s, r), "same_target_count": same})
    return {"items": items}


@bp.post("/reports/<int:rid>/resolve")
@require_perm("report.review")
async def resolve(rid: int):
    """decision: 'reject' (нарушений нет) | 'hide' (скрыть контент, на который жалоба)."""
    decision = json_body().get("decision")
    if decision not in {"reject", "hide"}:
        raise ApiError("decision: reject | hide", 400, "validation_error")
    async with session_scope() as s:
        r = await s.get(Report, rid, with_for_update=True)
        if r is None:
            raise ApiError("Жалоба не найдена", 404, "not_found")
        if r.status in (ReportStatus.RESOLVED, ReportStatus.REJECTED):
            raise ApiError("Жалоба уже закрыта", 409, "already_closed")
        if decision == "hide":
            if "content.hide" not in g.perms:
                raise ApiError("Недостаточно прав", 403, "forbidden")
            model = CONTENT.get(r.target_type.value)
            if model is None:
                raise ApiError("На пользователя — используй бан", 400, "use_ban")
            obj = await s.get(model, r.target_id)
            if obj is not None:
                was_active = obj.status == ContentStatus.ACTIVE
                obj.status = ContentStatus.HIDDEN
                await _after_status_change(s, r.target_type.value, obj, was_active)
                log_action(s, g.user.id, "content.hide", r.target_type.value, r.target_id, report_id=rid)
        # все открытые жалобы на ту же цель закрываем одним решением
        same = (await s.scalars(select(Report).where(
            Report.target_type == r.target_type, Report.target_id == r.target_id,
            Report.status.in_([ReportStatus.OPEN, ReportStatus.IN_REVIEW])))).all()
        now = datetime.now(timezone.utc)
        for rep in same:
            rep.status = ReportStatus.RESOLVED if decision == "hide" else ReportStatus.REJECTED
            rep.resolved_by, rep.resolved_at = g.user.id, now
        log_action(s, g.user.id, f"report.{decision}", "report", rid, closed=[x.id for x in same])
    return {"ok": True, "closed": len(same)}


async def _after_status_change(s, kind: str, obj, was_active: bool) -> None:
    """Скрытие/восстановление влияет на счётчики и рейтинги (скрытое режет рейтинг автора)."""
    from sqlalchemy import update
    from ..services.rating import recompute_user, refresh_question
    now_active = obj.status == ContentStatus.ACTIVE
    if kind == "comment" and was_active != now_active:
        delta = 1 if now_active else -1
        await s.execute(update(Answer).where(Answer.id == obj.answer_id)
                        .values(comments_count=Answer.comments_count + delta))
        await s.execute(update(Question).where(Question.id == obj.question_id)
                        .values(comments_count=Question.comments_count + delta))
    await s.flush()
    qid = obj.id if kind == "question" else obj.question_id
    q = await s.get(Question, qid)
    await s.refresh(q)
    await refresh_question(s, q)
    await recompute_user(s, obj.author_id)


async def _set_status(kind: str, cid: int, status: ContentStatus, action: str):
    model = CONTENT.get(kind)
    if model is None:
        raise ApiError("kind: question | answer | comment", 400, "validation_error")
    async with session_scope() as s:
        obj = await s.get(model, cid, with_for_update=True)
        if obj is None:
            raise ApiError("Не найдено", 404, "not_found")
        was_active = obj.status == ContentStatus.ACTIVE
        obj.status = status
        await _after_status_change(s, kind, obj, was_active)
        log_action(s, g.user.id, action, kind, cid,
                   reason=(request.get_json(silent=True) or {}).get("reason"))
    return {"ok": True, "status": status.value}


@bp.post("/content/<kind>/<int:cid>/hide")
@require_perm("content.hide")
async def hide(kind: str, cid: int):
    return await _set_status(kind, cid, ContentStatus.HIDDEN, "content.hide")


@bp.post("/content/<kind>/<int:cid>/restore")
@require_perm("content.restore")
async def restore(kind: str, cid: int):
    return await _set_status(kind, cid, ContentStatus.ACTIVE, "content.restore")


@bp.post("/bans")
@require_perm("ban.temporary")
async def ban():
    """{user_id, reason, days (1..30 | null = перманент, только admin), report_id?}"""
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
                ends_at=ends_at, report_id=data.get("report_id"))
        s.add(b)
        await s.flush()
        await s.flush()
        from ..services.rating import recompute_user
        await recompute_user(s, user_id)
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
@require_perm("report.review")
async def appeals():
    """Очередь апелляций. Свои баны модератор не видит — их разбирает кто-то другой."""
    async with session_scope() as s:
        rows = (await s.execute(
            select(Ban, User).join(User, User.id == Ban.user_id)
            .where(Ban.appeal_status == AppealStatus.PENDING, Ban.issued_by != g.user.id)
            .order_by(Ban.appeal_created_at)
        )).all()
    return {"items": [appeal_out(b, u) for b, u in rows]}


@bp.post("/appeals/<int:ban_id>/decide")
@require_perm("report.review")
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
        if b.issued_by == g.user.id:
            raise ApiError("Нельзя рассматривать апелляцию на собственный бан", 403, "own_ban")
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
