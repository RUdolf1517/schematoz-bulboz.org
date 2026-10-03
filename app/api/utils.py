from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from flask import request

from ..errors import ApiError
from ..models import User
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
            "avatar_url": u.avatar_url, "level": u.level,
            "level_name": level_name(u.level),
            "streak_days": visible_streak(u.streak_days, u.streak_last_date, None, u.streak_freeze_week),
            "streak_freeze_available": freeze_available(u.streak_freeze_week, msk_today()),
            "avatar_frame": (u.profile or {}).get("avatar_frame", "none"),
            "accent": (u.profile or {}).get("accent"),
            "status_emoji": (u.profile or {}).get("status_emoji", ""),
            "role": "admin" if u.rating_tier == 2 else "user"}
