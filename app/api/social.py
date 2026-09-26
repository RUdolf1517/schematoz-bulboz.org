"""Уведомления, подписки, поиск."""
from __future__ import annotations

from flask import g, request
from sqlalchemy import func, literal_column, select
from sqlalchemy.dialects.postgresql import insert

from ..auth.rbac import login_required
from ..db import session_scope
from ..errors import ApiError
from ..models import ContentStatus, Follow, Notification, Question, Room, User
from ..services.notifications import mark_read, notify, unread_count
from . import bp
from .utils import question_out


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


# ---------- подписки ----------
async def _user_by_name(s, username: str) -> User:
    u = await s.scalar(select(User).where(User.username == username.lower()))
    if u is None:
        raise ApiError("Пользователь не найден", 404, "not_found")
    return u


async def follow_counts(s, user_id: int) -> dict:
    followers = await s.scalar(select(func.count()).select_from(Follow).where(Follow.followee_id == user_id))
    following = await s.scalar(select(func.count()).select_from(Follow).where(Follow.follower_id == user_id))
    return {"followers": followers, "following": following}


@bp.put("/users/<username>/follow")
@login_required
async def follow(username: str):
    async with session_scope() as s:
        target = await _user_by_name(s, username)
        if target.id == g.user.id:
            raise ApiError("На себя подписаться нельзя", 400, "self_follow")
        res = await s.execute(insert(Follow).values(follower_id=g.user.id, followee_id=target.id)
                              .on_conflict_do_nothing().returning(Follow.follower_id))
        if res.scalar() is not None:
            notify(s, target.id, "follow", username=g.user.username)
        counts = await follow_counts(s, target.id)
    return {"following": True, **counts}


@bp.delete("/users/<username>/follow")
@login_required
async def unfollow(username: str):
    from sqlalchemy import delete
    async with session_scope() as s:
        target = await _user_by_name(s, username)
        await s.execute(delete(Follow).where(Follow.follower_id == g.user.id, Follow.followee_id == target.id))
        counts = await follow_counts(s, target.id)
    return {"following": False, **counts}


# ---------- поиск ----------
@bp.get("/search")
async def search():
    """Полнотекстовый поиск по вопросам (русская морфология Postgres);
    если по словоформам ничего не нашлось — подстрока в заголовке."""
    q = (request.args.get("q") or "").strip()
    if len(q) < 2:
        raise ApiError("Запрос — от 2 символов", 400, "validation_error")
    if len(q) > 200:
        raise ApiError("Слишком длинный запрос", 400, "validation_error")
    doc = func.to_tsvector(literal_column("'russian'"),
                           Question.title + literal_column("' '") + func.coalesce(Question.body, ""))
    tsq = func.websearch_to_tsquery(literal_column("'russian'"), q)
    async with session_scope() as s:
        base = (select(Question, User).join(User, User.id == Question.author_id)
                .where(Question.status == ContentStatus.ACTIVE))
        rows = (await s.execute(base.where(doc.op("@@")(tsq))
                                .order_by(func.ts_rank(doc, tsq).desc(), Question.id.desc()).limit(30))).all()
        mode = "fulltext"
        if not rows:
            rows = (await s.execute(base.where(Question.title.icontains(q, autoescape=True))
                                    .order_by(Question.id.desc()).limit(30))).all()
            mode = "substring"
        room_ids = {qq.room_id for qq, _ in rows if qq.room_id}
        rooms = {r.id: r for r in (await s.scalars(select(Room).where(Room.id.in_(room_ids))))} if room_ids else {}
    return {"items": [question_out(qq, u, None, rooms.get(qq.room_id)) for qq, u in rows], "mode": mode}
