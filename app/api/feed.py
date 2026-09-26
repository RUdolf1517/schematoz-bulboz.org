from __future__ import annotations

from flask import request
from sqlalchemy import select

from ..auth.sessions import current_user_id
from ..db import session_scope
from ..errors import ApiError
from ..models import Answer, ContentStatus, Follow, Question, Room, RoomMember, User
from . import bp
from .utils import answer_out, question_out

PAGE = 20
TABS = {"hot", "new", "unanswered", "my_rooms", "following"}


def best_answer_order(q_best_id):
    return ((Answer.id == q_best_id).desc(), Answer.score.desc(), Answer.id)


@bp.get("/feed")
async def feed():
    """Вертикальная лента: карточка = вопрос + лучший ответ («Схема» или топ по очкам)."""
    tab = request.args.get("tab", "hot")
    if tab not in TABS:
        raise ApiError(f"tab: {' | '.join(sorted(TABS))}", 400, "validation_error")
    room_slug = request.args.get("room")
    offset = max(request.args.get("offset", 0, type=int), 0)
    uid = current_user_id()

    async with session_scope() as s:
        stmt = (select(Question, User).join(User, User.id == Question.author_id)
                .where(Question.status == ContentStatus.ACTIVE))
        if room_slug:
            room_id = await s.scalar(select(Room.id).where(Room.slug == room_slug))
            if room_id is None:
                raise ApiError("Комната не найдена", 404, "not_found")
            stmt = stmt.where(Question.room_id == room_id)
        if tab == "unanswered":
            stmt = stmt.where(Question.answers_count == 0)
        if tab == "my_rooms":
            if not uid:
                raise ApiError("Нужно войти", 401, "unauthorized")
            stmt = stmt.where(Question.room_id.in_(
                select(RoomMember.room_id).where(RoomMember.user_id == uid)))
        if tab == "following":
            if not uid:
                raise ApiError("Нужно войти", 401, "unauthorized")
            stmt = stmt.where(Question.author_id.in_(
                select(Follow.followee_id).where(Follow.follower_id == uid)))
        order = ((Question.id.desc(),) if tab in {"new", "unanswered", "following"}
                 else (Question.score_hot.desc(), Question.id.desc()))
        rows = (await s.execute(stmt.order_by(*order).offset(offset).limit(PAGE))).all()

        room_ids = {q.room_id for q, _ in rows if q.room_id}
        rooms = {r.id: r for r in (await s.scalars(select(Room).where(Room.id.in_(room_ids))))} if room_ids else {}
        cards = []
        for q, author in rows:
            top = (await s.execute(
                select(Answer, User).join(User, User.id == Answer.author_id)
                .where(Answer.question_id == q.id, Answer.status == ContentStatus.ACTIVE)
                .order_by(*best_answer_order(q.best_answer_id)).limit(1)
            )).first()
            top_out = answer_out(top[0], top[1], is_best=top[0].id == q.best_answer_id) if top else None
            cards.append(question_out(q, author, top_out, rooms.get(q.room_id)))
    next_offset = offset + PAGE if len(rows) == PAGE else None
    return {"items": cards, "next_offset": next_offset}
