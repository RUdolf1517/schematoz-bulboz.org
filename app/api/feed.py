from __future__ import annotations

from flask import request
from sqlalchemy import select

from ..db import session_scope
from ..models import Answer, ContentStatus, Question, User
from . import bp
from .utils import answer_out, question_out

PAGE = 20


@bp.get("/feed")
async def feed():
    """Вертикальная лента: карточка = вопрос + его лучший ответ («Схема» или топ по очкам).
    Курсорная пагинация по (score_hot, id)."""
    room_id = request.args.get("room_id", type=int)
    cursor = request.args.get("cursor")
    async with session_scope() as s:
        stmt = (select(Question, User).join(User, User.id == Question.author_id)
                .where(Question.status == ContentStatus.ACTIVE))
        if room_id:
            stmt = stmt.where(Question.room_id == room_id)
        if cursor:
            hot, qid = cursor.split("_")
            stmt = stmt.where((Question.score_hot, Question.id) < (float(hot), int(qid)))
        rows = (await s.execute(
            stmt.order_by(Question.score_hot.desc(), Question.id.desc()).limit(PAGE)
        )).all()
        cards = []
        for q, author in rows:
            top = (await s.execute(
                select(Answer, User).join(User, User.id == Answer.author_id)
                .where(Answer.question_id == q.id, Answer.status == ContentStatus.ACTIVE)
                .order_by((Answer.id == q.best_answer_id).desc(), Answer.score.desc(), Answer.id)
                .limit(1)
            )).first()
            top_out = answer_out(top[0], top[1], is_best=top[0].id == q.best_answer_id) if top else None
            cards.append(question_out(q, author, top_out))
    next_cursor = f"{rows[-1][0].score_hot}_{rows[-1][0].id}" if len(rows) == PAGE else None
    return {"items": cards, "next_cursor": next_cursor}
