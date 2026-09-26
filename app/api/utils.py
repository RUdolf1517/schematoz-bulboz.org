from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from flask import request

from ..errors import ApiError
from ..models import Answer, Comment, Question, User
from ..services.answer_content import serialize_answer
from ..services.markdown import render as render_md
from ..services.rating import public_rating
from ..services.gamification import freeze_available, level_name, msk_today, visible_streak


def json_body() -> dict[str, Any]:
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        raise ApiError("Ожидается JSON-объект", 400, "invalid_json")
    return data


def req_str(data: dict, key: str, *, min_len: int = 1, max_len: int = 10_000,
            optional: bool = False) -> str | None:
    val = data.get(key)
    if val is None or (isinstance(val, str) and not val.strip() and optional):
        if optional:
            return None
        raise ApiError(f"Поле «{key}» обязательно", 400, "validation_error", field=key)
    if not isinstance(val, str):
        raise ApiError(f"Поле «{key}» должно быть строкой", 400, "validation_error", field=key)
    val = val.strip()
    if not min_len <= len(val) <= max_len:
        raise ApiError(f"Поле «{key}»: от {min_len} до {max_len} символов", 400,
                       "validation_error", field=key)
    return val


def account_age_hours(user: User) -> float:
    return (datetime.now(timezone.utc) - user.created_at).total_seconds() / 3600


def user_public(u: User) -> dict:
    return {"id": u.id, "username": u.username, "display_name": u.display_name,
            "avatar_url": u.avatar_url, "reputation": max(u.reputation, 0), "level": u.level,
            "level_name": level_name(u.level),
            "streak_days": visible_streak(u.streak_days, u.streak_last_date, None, u.streak_freeze_week),
            "streak_freeze_available": freeze_available(u.streak_freeze_week, msk_today()),
            "avatar_frame": (u.profile or {}).get("avatar_frame", "none"),
            "accent": (u.profile or {}).get("accent"),
            "status_emoji": (u.profile or {}).get("status_emoji", ""),
            **public_rating(u)}


def comment_out(c: Comment, author: User | None = None) -> dict:
    return {"id": c.id, "answer_id": c.answer_id, "author_id": c.author_id,
            "author": user_public(author) if author else None,
            "body": c.body, "body_html": render_md(c.body, inline=True),
            "created_at": c.created_at.isoformat(),
            "edited_at": c.edited_at.isoformat() if c.edited_at else None}


def answer_out(a: Answer, author: User | None = None, *, is_best: bool = False,
               my_vote: int | None = None, comments: list[dict] | None = None) -> dict:
    return {
        "body_html": render_md(a.body),
        "comments_count": a.comments_count,
        "comments": comments if comments is not None else [],
        "id": a.id, "question_id": a.question_id, "author_id": a.author_id,
        "author": user_public(author) if author else None,
        "content": serialize_answer(a),
        "debate_side": a.debate_side.value if a.debate_side else None,
        "score": a.score, "is_best": is_best, "my_vote": my_vote,
        "created_at": a.created_at.isoformat(),
        "edited_at": a.edited_at.isoformat() if a.edited_at else None,
    }


def question_out(q: Question, author: User | None = None, top_answer: dict | None = None,
                 room=None, my_vote: int | None = None) -> dict:
    return {
        "body_html": render_md(q.body), "cover_url": q.cover_url,
        "rating": q.rating, "votes_score": q.votes_score, "comments_count": q.comments_count,
        "my_vote": my_vote,
        "id": q.id, "kind": q.kind.value, "title": q.title, "body": q.body,
        "author": user_public(author) if author else None, "author_id": q.author_id,
        "room_id": q.room_id, "category_id": q.category_id,
        "room": {"slug": room.slug, "title": room.title} if room else None,
        "debate": {"a": q.debate_side_a, "b": q.debate_side_b} if q.kind.value == "debate" else None,
        "best_answer_id": q.best_answer_id, "answers_count": q.answers_count,
        "status": q.status.value, "created_at": q.created_at.isoformat(),
        "edited_at": q.edited_at.isoformat() if q.edited_at else None,
        "top_answer": top_answer,
    }
