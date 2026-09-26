"""Комментарии к ответам: markdown, до 200 символов. Поднимают рейтинг ответа и вопроса."""
from __future__ import annotations

from datetime import datetime, timezone

from flask import current_app, g
from sqlalchemy import update

from ..auth.rbac import require_perm
from ..db import session_scope
from ..errors import ApiError
from ..models import Answer, Comment, ContentStatus, Question
from ..services import antispam
from ..services.captcha import captcha_required
from ..services.notifications import notify
from ..services.rating import recompute_user, refresh_question
from . import bp
from .utils import account_age_hours, comment_out, json_body, req_str


def _body() -> str:
    return req_str(json_body(), "body", max_len=current_app.config["COMMENT_MAX_LEN"])


async def _bump(s, comment: Comment, delta: int) -> None:
    await s.execute(update(Answer).where(Answer.id == comment.answer_id)
                    .values(comments_count=Answer.comments_count + delta))
    await s.execute(update(Question).where(Question.id == comment.question_id)
                    .values(comments_count=Question.comments_count + delta))
    q = await s.get(Question, comment.question_id)
    await s.refresh(q)
    await refresh_question(s, q)
    a = await s.get(Answer, comment.answer_id)
    await recompute_user(s, comment.author_id)
    if a.author_id != comment.author_id:
        await recompute_user(s, a.author_id)  # «комментарии, которые получили ответы» — часть формулы


@bp.post("/answers/<int:aid>/comments")
@require_perm("answer.create")
@captcha_required()
async def create_comment(aid: int):
    body = _body()
    antispam.check_post(body, account_age_hours(g.user))
    async with session_scope() as s:
        a = await s.get(Answer, aid)
        q = await s.get(Question, a.question_id) if a else None
        if a is None or a.status != ContentStatus.ACTIVE or q.status != ContentStatus.ACTIVE:
            raise ApiError("Ответ не найден", 404, "not_found")
        c = Comment(answer_id=aid, question_id=a.question_id, author_id=g.user.id, body=body)
        s.add(c)
        await s.flush()
        await s.refresh(c)
        await _bump(s, c, +1)
        if a.author_id != g.user.id:
            notify(s, a.author_id, "comment", question_id=q.id, answer_id=aid, comment_id=c.id,
                   username=g.user.username, question_title=q.title[:120])
        out = comment_out(c, g.user)
    return {"comment": out}, 201


async def _own_comment(s, cid: int) -> Comment:
    c = await s.get(Comment, cid, with_for_update=True)
    if c is None or c.status != ContentStatus.ACTIVE:
        raise ApiError("Комментарий не найден", 404, "not_found")
    return c


@bp.patch("/comments/<int:cid>")
@require_perm("answer.create")
async def edit_comment(cid: int):
    body = _body()
    async with session_scope() as s:
        c = await _own_comment(s, cid)
        if c.author_id != g.user.id:
            raise ApiError("Можно менять только своё", 403, "not_owner")
        c.body = body
        c.edited_at = datetime.now(timezone.utc)
        out = comment_out(c, g.user)
    return {"comment": out}


@bp.delete("/comments/<int:cid>")
@require_perm("answer.create")
async def delete_comment(cid: int):
    """Автор удаляет свой комментарий (status=deleted). Модераторы скрывают через /mod/content/comment/<id>/hide."""
    async with session_scope() as s:
        c = await _own_comment(s, cid)
        if c.author_id != g.user.id:
            raise ApiError("Можно удалять только своё", 403, "not_owner")
        c.status = ContentStatus.DELETED
        await _bump(s, c, -1)
    return {"ok": True}
