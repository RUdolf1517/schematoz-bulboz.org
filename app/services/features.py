"""Фича-флаги: значения по умолчанию из Config.FEATURES, переопределения — в таблице
settings (ключ 'features'), кэш в Redis."""
from __future__ import annotations

import json

from flask import current_app
from sqlalchemy import select

from ..db import session_scope
from ..extensions import get_redis
from ..models import Setting

CACHE_KEY = "settings:features"
CACHE_TTL = 60


async def get_features() -> dict[str, bool]:
    r = get_redis()
    cached = r.get(CACHE_KEY)
    if cached is None:
        async with session_scope() as s:
            row = await s.scalar(select(Setting).where(Setting.key == "features"))
        overrides = row.value if row else {}
        r.setex(CACHE_KEY, CACHE_TTL, json.dumps(overrides))
    else:
        overrides = json.loads(cached)
    return {**current_app.config["FEATURES"], **overrides}


async def feature_enabled(flag: str) -> bool:
    return bool((await get_features()).get(flag, False))


def invalidate_features() -> None:
    get_redis().delete(CACHE_KEY)
