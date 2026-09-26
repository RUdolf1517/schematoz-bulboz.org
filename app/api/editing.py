"""Редактирование и удаление своего контента.

Правила (чтобы нельзя было «подменить» вопрос после ответов):
  * вопрос: подробности (body) можно править всегда; заголовок — только пока нет ответов;
  * вопрос нельзя удалить, если у него уже есть «Схема» — это чужой труд;
  * ответ: текст можно править всегда (помечается «изменено»), удалить — тоже;
  * скрытое модератором редактировать нельзя (для автора такой контент — 404);
  * удаление мягкое (status=deleted); начисленная репутация НЕ откатывается,
    иначе можно было бы удалять ответы с минусами и «отмывать» репутацию.
"""
from __future__ import annotations

from datetime import datetime, timezone

from flask import current_app, g
from sqlalchemy import update

from ..auth.rbac import require_perm
from ..db import session_scope
from ..errors import ApiError
from ..models import Answer, ContentStatus, Question
from . import bp
from .utils import answer_out, json_body, question_out, req_str


async def _own(s, model, obj_id: int):
    obj = await s.get(model, obj_id, with_for_update=True)
    if obj is None or obj.status != ContentStatus.ACTIVE:
        raise ApiError("Не найдено", 404, "not_found")
    if obj.author_id != g.user.id:
        raise ApiError("Можно менять только своё", 403, "not_owner")
    return obj


@bp.patch("/questions/<int:qid>")
@require_perm("question.create")
async def edit_question(qid: int):
    data = json_body()
    async with session_scope() as s:
        q = await _own(s, Question, qid)
        if "title" in data:
            title = req_str(data, "title", min_len=5, max_len=300)
            if title != q.title and q.answers_count > 0:
                raise ApiError("Заголовок нельзя менять после первого ответа — допиши подробности",
                               409, "title_locked")
            q.title = title
        if "body" in data:
            q.body = req_str(data, "body", max_len=5000, optional=True)
        q.edited_at = datetime.now(timezone.utc)
    return {"question": question_out(q, g.user)}


@bp.delete("/questions/<int:qid>")
@require_perm("question.create")
async def delete_question(qid: int):
    async with session_scope() as s:
        q = await _own(s, Question, qid)
        if q.best_answer_id is not None:
            raise ApiError("У вопроса уже есть «Схема» — удалить его нельзя", 409, "has_scheme")
        q.status = ContentStatus.DELETED
    return {"ok": True}


@bp.patch("/answers/<int:aid>")
@require_perm("answer.create")
async def edit_answer(aid: int):
    body = req_str(json_body(), "body", max_len=current_app.config["ANSWER_TEXT_MAX_LEN"])
    async with session_scope() as s:
        a = await _own(s, Answer, aid)
        if a.content_type.value != "text":
            raise ApiError("Редактировать можно только текстовые ответы", 400, "not_text")
        a.body = body
        a.edited_at = datetime.now(timezone.utc)
    return {"answer": answer_out(a, g.user)}


@bp.delete("/answers/<int:aid>")
@require_perm("answer.create")
async def delete_answer(aid: int):
    async with session_scope() as s:
        a = await _own(s, Answer, aid)
        a.status = ContentStatus.DELETED
        await s.execute(update(Question).where(Question.id == a.question_id)
                        .values(answers_count=Question.answers_count - 1))
        await s.execute(update(Question).where(Question.id == a.question_id,
                                               Question.best_answer_id == aid)
                        .values(best_answer_id=None))
    return {"ok": True}
