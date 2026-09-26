from __future__ import annotations

from flask import g
from sqlalchemy import update

from ..auth.rbac import require_perm
from ..db import session_scope
from ..errors import ApiError
from ..models import Answer, ContentStatus, DebateSide, Question, QuestionKind
from ..services import antispam
from ..services.answer_content import AnswerDraft, enabled_types, get_handler
from ..services.captcha import captcha_required
from ..services.gamification import on_answer_created
from ..services.notifications import notify
from ..services.reputation import cast_vote, remove_vote
from . import bp
from .utils import account_age_hours, answer_out, json_body


@bp.get("/answers/capabilities")
async def capabilities():
    """Клиент показывает кнопки 🎤/🎥 только для включённых типов."""
    from flask import current_app
    return {"types": await enabled_types(),
            "max_text_len": current_app.config["ANSWER_TEXT_MAX_LEN"],
            "max_media_ms": current_app.config["ANSWER_MEDIA_MAX_DURATION_MS"]}


@bp.post("/questions/<int:qid>/answers")
@require_perm("answer.create")
@captcha_required()
async def create_answer(qid: int):
    data = json_body()
    draft = AnswerDraft(content_type=data.get("content_type") or "text",
                        body=data.get("body"), upload_id=data.get("upload_id"))
    handler = await get_handler(draft.content_type)  # voice/video → 422, пока флаг выключен
    await handler.validate(draft)
    antispam.check_post(draft.body or "", account_age_hours(g.user))

    async with session_scope() as s:
        q = await s.get(Question, qid)
        if q is None or q.status != ContentStatus.ACTIVE:
            raise ApiError("Вопрос не найден", 404, "not_found")
        side = None
        if q.kind is QuestionKind.DEBATE:
            try:
                side = DebateSide(data.get("debate_side"))
            except ValueError:
                raise ApiError("В холиваре выбери сторону: a или b", 400, "validation_error",
                               field="debate_side")
        answer = Answer(question_id=qid, author_id=g.user.id, content_type=draft.content_type,
                        body=draft.body, debate_side=side)
        s.add(answer)
        await s.flush()
        await handler.persist(s, answer, draft)
        new_badges = await on_answer_created(s, g.user, answer)
        if q.author_id != g.user.id:
            notify(s, q.author_id, "answer", question_id=q.id, answer_id=answer.id,
                   username=g.user.username, question_title=q.title[:120])
        await s.execute(update(Question).where(Question.id == qid)
                        .values(answers_count=Question.answers_count + 1))
        await s.refresh(answer)
    return {"answer": answer_out(answer, g.user), "new_badges": new_badges}, 201


@bp.put("/answers/<int:aid>/vote")
@require_perm("vote.cast")
async def vote(aid: int):
    value = json_body().get("value")
    if not isinstance(value, int) or isinstance(value, bool):
        raise ApiError("value должно быть числом", 400, "validation_error", field="value")
    async with session_scope() as s:
        result = await cast_vote(s, g.user, aid, value)
    return result


@bp.delete("/answers/<int:aid>/vote")
@require_perm("vote.cast")
async def unvote(aid: int):
    async with session_scope() as s:
        result = await remove_vote(s, g.user, aid)
    return result
