from __future__ import annotations

import asyncio

from flask import Response
from sqlalchemy import select

from ..db import session_scope
from ..errors import ApiError
from ..models import Answer, ContentStatus, Question, User
from ..services import share
from ..services.gamification import level_name, user_badges, visible_streak
from . import bp


def _png(data: bytes) -> Response:
    return Response(data, mimetype="image/png",
                    headers={"Cache-Control": "public, max-age=300",
                             "Content-Disposition": "inline; filename=bulboz-story.png"})


@bp.get("/share/answer/<int:aid>.png")
async def share_answer(aid: int):
    async with session_scope() as s:
        row = (await s.execute(
            select(Answer, Question, User).join(Question, Question.id == Answer.question_id)
            .join(User, User.id == Answer.author_id).where(Answer.id == aid)
        )).first()
    if row is None or row[0].status != ContentStatus.ACTIVE or row[1].status != ContentStatus.ACTIVE:
        raise ApiError("Ответ не найден", 404, "not_found")
    a, q, u = row
    data = await asyncio.to_thread(
        share.render_answer_card, question_title=q.title, answer_body=a.body or "",
        author=u.username, score=a.score, is_scheme=q.best_answer_id == a.id, question_id=q.id)
    return _png(data)


@bp.get("/share/user/<username>.png")
async def share_profile(username: str):
    from .profile import profile as profile_view  # переиспользуем подсчёт схем
    data = await profile_view(username)
    u = data["user"]
    png = await asyncio.to_thread(
        share.render_profile_card, username=u["username"], level=u["level"],
        level_name=u["level_name"], streak=u["streak_days"], reputation=u["reputation"],
        schemes=data["stats"]["schemes"], badges=data["badges"])
    return _png(png)
