from __future__ import annotations

from flask import g
from sqlalchemy import select

from ..auth.rbac import require_perm
from ..db import session_scope
from ..errors import ApiError
from ..models import (
    Answer, ContentStatus, DebateVote, Question, QuestionKind, Room, User, Vote,
)
from .debates import debate_counts
from ..services import antispam
from ..services.captcha import captcha_required
from ..services.gamification import on_question_created
from ..services.ranking import hot_score
from ..auth.sessions import current_user_id
from . import bp
from .utils import account_age_hours, answer_out, json_body, question_out, req_str


@bp.post("/questions")
@require_perm("question.create")
@captcha_required()
async def create_question():
    data = json_body()
    try:
        kind = QuestionKind(data.get("kind", "opinion"))
    except ValueError:
        raise ApiError("kind: opinion | knowledge | story | debate", 400, "validation_error", field="kind")
    title = req_str(data, "title", min_len=5, max_len=300)
    body = req_str(data, "body", max_len=5000, optional=True)
    side_a = side_b = None
    if kind is QuestionKind.DEBATE:
        side_a = req_str(data, "side_a", max_len=80, optional=True) or "За"
        side_b = req_str(data, "side_b", max_len=80, optional=True) or "Против"
    antispam.check_post(f"{title} {body or ''}", account_age_hours(g.user))

    async with session_scope() as s:
        room_id = data.get("room_id")
        category_id = None
        if room_id is not None:
            room = await s.get(Room, room_id)
            if room is None:
                raise ApiError("Комната не найдена", 404, "not_found")
            category_id = room.category_id
        q = Question(author_id=g.user.id, kind=kind, title=title, body=body, room_id=room_id,
                     category_id=category_id, debate_side_a=side_a, debate_side_b=side_b)
        s.add(q)
        await s.flush()
        await s.refresh(q)
        q.score_hot = hot_score(0, 0, q.created_at)
        new_badges = await on_question_created(s, g.user.id)
    return {"question": question_out(q, g.user), "new_badges": new_badges}, 201


@bp.get("/questions/<int:qid>")
async def get_question(qid: int):
    uid = current_user_id()
    async with session_scope() as s:
        q = await s.get(Question, qid)
        if q is None or q.status != ContentStatus.ACTIVE:
            raise ApiError("Вопрос не найден", 404, "not_found")
        author = await s.get(User, q.author_id)
        room = await s.get(Room, q.room_id) if q.room_id else None
        debate = None
        if q.kind is QuestionKind.DEBATE:
            my_side = await s.scalar(select(DebateVote.side).where(
                DebateVote.question_id == qid, DebateVote.user_id == uid)) if uid else None
            debate = {**await debate_counts(s, qid), "my_side": my_side.value if my_side else None}
        rows = (await s.execute(
            select(Answer, User).join(User, User.id == Answer.author_id)
            .where(Answer.question_id == qid, Answer.status == ContentStatus.ACTIVE)
            .order_by((Answer.id == q.best_answer_id).desc(), Answer.score.desc(), Answer.id)
        )).all()
        my_votes = {}
        if uid:
            my_votes = dict((await s.execute(
                select(Vote.answer_id, Vote.value).where(
                    Vote.voter_id == uid, Vote.answer_id.in_([a.id for a, _ in rows]))
            )).all())
    answers = [answer_out(a, u, is_best=a.id == q.best_answer_id, my_vote=my_votes.get(a.id))
               for a, u in rows]
    return {"question": question_out(q, author, room=room), "answers": answers,
            "debate_votes": debate,
            "you_are_author": uid == q.author_id,
            "vote_values": ([5, -1] if uid == q.author_id else [1, -1]) if uid else []}
