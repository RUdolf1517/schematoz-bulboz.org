from __future__ import annotations

from flask import g
from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert

from ..auth.rbac import require_perm
from ..db import session_scope
from ..errors import ApiError
from ..models import ContentStatus, DebateSide, DebateVote, Question, QuestionKind
from ..services import wood
from . import bp


async def debate_counts(s, qid: int) -> dict:
    rows = dict((await s.execute(
        select(DebateVote.side, func.count()).where(DebateVote.question_id == qid)
        .group_by(DebateVote.side))).all())
    a, b = rows.get(DebateSide.A, 0), rows.get(DebateSide.B, 0)
    total = a + b
    return {"a": a, "b": b, "a_pct": round(100 * a / total) if total else 50,
            "b_pct": round(100 * b / total) if total else 50}


@bp.put("/questions/<int:qid>/debate-vote")
@require_perm("vote.cast")
async def debate_vote(qid: int):
    """Голос «за/против» в холиваре. Отдельно от оценок ответов, репутацию не меняет.
    Голос можно поменять."""
    from .utils import json_body
    try:
        side = DebateSide(json_body().get("side"))
    except ValueError:
        raise ApiError("side: a | b", 400, "validation_error", field="side")
    async with session_scope() as s:
        q = await s.get(Question, qid)
        if q is None or q.status != ContentStatus.ACTIVE:
            raise ApiError("Вопрос не найден", 404, "not_found")
        if q.kind is not QuestionKind.DEBATE:
            raise ApiError("Это не холивар", 400, "not_a_debate")
        await s.execute(insert(DebateVote).values(question_id=qid, user_id=g.user.id, side=side)
                        .on_conflict_do_update(index_elements=["question_id", "user_id"],
                                               set_={"side": side}))
        await wood.earn(s, g.user.id, "debate_vote", qid)  # один раз за холивар, смена стороны не фармит
        counts = await debate_counts(s, qid)
    return {"my_side": side.value, **counts}
