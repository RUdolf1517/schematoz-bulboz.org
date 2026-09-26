from __future__ import annotations

from sqlalchemy import case, func, select

from ..db import session_scope
from ..errors import ApiError
from ..models import (
    Answer, ContentStatus, Question, RepReason, ReputationEvent, Room, User,
)
from ..services.gamification import user_badges
from . import bp
from .utils import user_public

EXPERT_MIN_BEST = 15
CONNOISSEUR_MIN_BEST = 5


def topic_status(schemes: int, plus: int, minus: int) -> str:
    votes = plus + minus
    minus_share = minus / votes if votes else 0
    if schemes >= EXPERT_MIN_BEST and minus_share < 0.15:
        return "expert"
    if schemes >= CONNOISSEUR_MIN_BEST:
        return "connoisseur"
    return "newbie"


@bp.get("/users/<username>")
async def profile(username: str):
    """Прозрачная репутация: разбивка по темам + бейджи + последние «Схемы»."""
    async with session_scope() as s:
        user = await s.scalar(select(User).where(User.username == username.lower()))
        if user is None:
            raise ApiError("Пользователь не найден", 404, "not_found")
        # схемы считаем по уникальным ответам (автор мог менять голос туда-обратно)
        scheme_answers = (select(ReputationEvent.answer_id).where(
            ReputationEvent.user_id == user.id, ReputationEvent.reason == RepReason.AUTHOR_VOTE,
            ReputationEvent.delta == 5))
        rows = (await s.execute(
            select(
                ReputationEvent.room_id, Room.title, Room.slug,
                func.count(func.distinct(case(
                    ((ReputationEvent.reason == RepReason.AUTHOR_VOTE) & (ReputationEvent.delta == 5),
                     ReputationEvent.answer_id)))).label("schemes"),
                func.sum(case((ReputationEvent.delta > 0, 1), else_=0)).label("plus"),
                func.sum(case((ReputationEvent.delta < 0, 1), else_=0)).label("minus"),
                func.sum(ReputationEvent.delta).label("total"),
            )
            .outerjoin(Room, Room.id == ReputationEvent.room_id)
            .where(ReputationEvent.user_id == user.id,
                   ReputationEvent.reason != RepReason.VOTE_REVOKED)
            .group_by(ReputationEvent.room_id, Room.title, Room.slug)
            .order_by(func.sum(ReputationEvent.delta).desc())
        )).all()
        best = (await s.execute(
            select(Answer, Question).join(Question, Question.id == Answer.question_id)
            .where(Answer.id.in_(scheme_answers), Question.best_answer_id == Answer.id,
                   Answer.status == ContentStatus.ACTIVE, Question.status == ContentStatus.ACTIVE)
            .order_by(Answer.id.desc()).limit(10)
        )).all()
        stats = (await s.execute(select(
            select(func.count(Question.id)).where(Question.author_id == user.id,
                                                  Question.status == ContentStatus.ACTIVE).scalar_subquery(),
            select(func.count(Answer.id)).where(Answer.author_id == user.id,
                                                Answer.status == ContentStatus.ACTIVE).scalar_subquery(),
        ))).one()
        badges = await user_badges(s, user.id)

    topics = [{
        "room_id": room_id, "room_slug": slug, "title": title or "Общая лента",
        "schemes": schemes, "plus": plus or 0, "minus": minus or 0, "points": total or 0,
        "status": topic_status(schemes, plus or 0, minus or 0),
    } for room_id, title, slug, schemes, plus, minus, total in rows]
    return {
        "user": {**user_public(user), "bio": user.bio, "created_at": user.created_at.isoformat()},
        "stats": {"questions": stats[0], "answers": stats[1],
                  "schemes": sum(t["schemes"] for t in topics)},
        "topics": topics,
        "badges": badges,
        "best_answers": [{"answer_id": a.id, "question_id": q.id, "question_title": q.title,
                          "body": (a.body or "")[:280]} for a, q in best],
    }
