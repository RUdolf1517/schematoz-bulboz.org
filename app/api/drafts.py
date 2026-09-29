"""Черновики вопросов и ответов. Фронт автосохраняет форму (PUT с debounce), публикация удаляет черновик."""
from __future__ import annotations

from datetime import datetime, timezone

from flask import g, request
from sqlalchemy import delete, func, select

from ..auth.rbac import login_required
from ..db import session_scope
from ..errors import ApiError
from ..models import Draft, Question
from . import bp
from .utils import json_body

MAX_DRAFTS = 50
EXTRA_KEYS = {"kind": 16, "side_a": 80, "side_b": 80, "cover_url": 200, "debate_side": 1}


def _out(d: Draft, qtitle: str | None = None) -> dict:
    return {"id": d.id, "kind": d.kind, "question_id": d.question_id, "question_title": qtitle, "title": d.title,
            "body": d.body, "extra": d.extra or {}, "updated_at": d.updated_at.isoformat(),
            "created_at": d.created_at.isoformat()}


def _clean(data: dict) -> tuple[str, str, dict]:
    title = str(data.get("title") or "")[:300]
    body = str(data.get("body") or "")[:5000]
    raw = data.get("extra") or {}
    extra = {k: str(raw[k])[:n] for k, n in EXTRA_KEYS.items() if isinstance(raw, dict) and raw.get(k) not in (None, "")}
    if isinstance(raw, dict) and isinstance(raw.get("room_id"), int):
        extra["room_id"] = raw["room_id"]
    return title, body, extra


@bp.get("/drafts")
@login_required
async def drafts_list():
    async with session_scope() as s:
        rows = (await s.execute(select(Draft, Question.title).outerjoin(Question, Question.id == Draft.question_id)
                                .where(Draft.user_id == g.user.id).order_by(Draft.updated_at.desc()))).all()
        return {"items": [_out(d, t) for d, t in rows], "max": MAX_DRAFTS}


@bp.get("/drafts/answer/<int:qid>")
@login_required
async def draft_for_answer(qid: int):
    async with session_scope() as s:
        d = (await s.execute(select(Draft).where(Draft.user_id == g.user.id, Draft.kind == "answer",
                                                 Draft.question_id == qid))).scalar()
        return {"draft": _out(d) if d else None}


@bp.get("/drafts/<int:did>")
@login_required
async def draft_get(did: int):
    async with session_scope() as s:
        d = await s.get(Draft, did)
        if d is None or d.user_id != g.user.id:
            raise ApiError("Черновик не найден", 404, "not_found")
        return {"draft": _out(d)}


@bp.post("/drafts")
@login_required
async def draft_create():
    """Новый черновик вопроса, либо upsert черновика ответа (один на вопрос)."""
    data = json_body()
    kind = data.get("kind")
    if kind not in ("question", "answer"):
        raise ApiError("kind: question | answer", 400, "validation_error", field="kind")
    title, body, extra = _clean(data)
    if not (title.strip() or body.strip()):
        raise ApiError("Пустой черновик не сохраняем", 400, "validation_error")
    async with session_scope() as s:
        qid = None
        if kind == "answer":
            qid = data.get("question_id")
            if not isinstance(qid, int) or await s.get(Question, qid) is None:
                raise ApiError("Вопрос не найден", 404, "not_found")
            d = (await s.execute(select(Draft).where(Draft.user_id == g.user.id, Draft.kind == "answer",
                                                     Draft.question_id == qid))).scalar()
            if d:
                d.body, d.extra, d.updated_at = body, extra, datetime.now(timezone.utc)
                await s.flush()
                return {"draft": _out(d)}
        n = (await s.execute(select(func.count()).select_from(Draft).where(Draft.user_id == g.user.id))).scalar()
        if n >= MAX_DRAFTS:
            raise ApiError(f"Черновиков максимум {MAX_DRAFTS} — удали старые", 409, "drafts_limit")
        d = Draft(user_id=g.user.id, kind=kind, question_id=qid, title=title if kind == "question" else "",
                  body=body, extra=extra)
        s.add(d)
        await s.flush()
        await s.refresh(d)
        return {"draft": _out(d)}, 201


@bp.put("/drafts/<int:did>")
@login_required
async def draft_update(did: int):
    title, body, extra = _clean(json_body())
    async with session_scope() as s:
        d = await s.get(Draft, did)
        if d is None or d.user_id != g.user.id:
            raise ApiError("Черновик не найден", 404, "not_found")
        if d.kind == "question":
            d.title = title
        d.body, d.extra, d.updated_at = body, extra, datetime.now(timezone.utc)
        await s.flush()
        return {"draft": _out(d)}


@bp.delete("/drafts/<int:did>")
@login_required
async def draft_delete(did: int):
    async with session_scope() as s:
        res = await s.execute(delete(Draft).where(Draft.id == did, Draft.user_id == g.user.id))
        if not res.rowcount:
            raise ApiError("Черновик не найден", 404, "not_found")
        return {"ok": True}


async def drop_draft(s, user_id: int, draft_id=None, answer_qid: int | None = None) -> None:
    """Вызывается при публикации: вопрос удаляет свой черновик по id, ответ — по question_id."""
    if isinstance(draft_id, int):
        await s.execute(delete(Draft).where(Draft.id == draft_id, Draft.user_id == user_id))
    if answer_qid is not None:
        await s.execute(delete(Draft).where(Draft.user_id == user_id, Draft.kind == "answer",
                                            Draft.question_id == answer_qid))
