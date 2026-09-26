from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from flask import request

from ..errors import ApiError
from ..models import Answer, Question, User
from ..services.answer_content import serialize_answer


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
            "streak_days": u.streak_days}


def answer_out(a: Answer, author: User | None = None, *, is_best: bool = False,
               my_vote: int | None = None) -> dict:
    return {
        "id": a.id, "question_id": a.question_id, "author_id": a.author_id,
        "author": user_public(author) if author else None,
        "content": serialize_answer(a),
        "debate_side": a.debate_side.value if a.debate_side else None,
        "score": a.score, "is_best": is_best, "my_vote": my_vote,
        "created_at": a.created_at.isoformat(),
    }


def question_out(q: Question, author: User | None = None, top_answer: dict | None = None) -> dict:
    return {
        "id": q.id, "kind": q.kind.value, "title": q.title, "body": q.body,
        "author": user_public(author) if author else None, "author_id": q.author_id,
        "room_id": q.room_id, "category_id": q.category_id,
        "debate": {"a": q.debate_side_a, "b": q.debate_side_b} if q.kind.value == "debate" else None,
        "best_answer_id": q.best_answer_id, "answers_count": q.answers_count,
        "status": q.status.value, "created_at": q.created_at.isoformat(),
        "top_answer": top_answer,
    }
