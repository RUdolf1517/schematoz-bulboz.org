from __future__ import annotations

from sqlalchemy import case, func, select

from ..db import session_scope
from ..errors import ApiError
from ..models import Category, RepReason, ReputationEvent, Room, User
from . import bp
from .utils import user_public

EXPERT_MIN_BEST = 15


@bp.get("/users/<username>")
async def profile(username: str):
    """Прозрачная репутация: разбивка по темам, а не одно число."""
    async with session_scope() as s:
        user = await s.scalar(select(User).where(User.username == username.lower()))
        if user is None:
            raise ApiError("Пользователь не найден", 404, "not_found")
        best = func.count().filter(
            (ReputationEvent.reason == RepReason.AUTHOR_VOTE) & (ReputationEvent.delta == 5))
        rows = (await s.execute(
            select(
                ReputationEvent.room_id, Room.title,
                best.label("best"),
                func.sum(case((ReputationEvent.delta > 0, 1), else_=0)).label("plus"),
                func.sum(case((ReputationEvent.delta < 0, 1), else_=0)).label("minus"),
                func.sum(ReputationEvent.delta).label("total"),
            )
            .outerjoin(Room, Room.id == ReputationEvent.room_id)
            .where(ReputationEvent.user_id == user.id,
                   ReputationEvent.reason != RepReason.VOTE_REVOKED)
            .group_by(ReputationEvent.room_id, Room.title)
            .order_by(func.sum(ReputationEvent.delta).desc())
        )).all()
    topics = []
    for room_id, title, best_n, plus, minus, total in rows:
        votes = (plus or 0) + (minus or 0)
        minus_share = (minus or 0) / votes if votes else 0
        topics.append({
            "room_id": room_id, "title": title or "Общая лента",
            "schemes": best_n, "plus": plus, "minus": minus, "points": total,
            "status": "expert" if best_n >= EXPERT_MIN_BEST and minus_share < 0.15
                      else "connoisseur" if best_n >= 5 else "newbie",
        })
    return {"user": {**user_public(user), "bio": user.bio}, "topics": topics}
