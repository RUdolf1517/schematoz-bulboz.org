"""Антиспам на правилах (без ML): rate limit и флаг «подозрительный» в Redis."""
from __future__ import annotations

import hashlib
import re

from flask import current_app, g, request

from ..extensions import get_redis

SUSPICION_TTL = 3600
LINK_RE = re.compile(r"https?://|www\.", re.I)


def client_key() -> str:
    user = g.get("user")
    if user is not None:
        return f"u:{user.id}"
    ip = request.headers.get("X-Forwarded-For", request.remote_addr or "").split(",")[0].strip()
    return f"ip:{ip}"


def mark_suspicious(key: str, reason: str) -> None:
    get_redis().setex(f"susp:{key}", SUSPICION_TTL, reason)


def is_suspicious(key: str) -> bool:
    return bool(get_redis().exists(f"susp:{key}"))


def clear_suspicion(key: str) -> None:
    get_redis().delete(f"susp:{key}")


def hit_rate(action: str, key: str, limit: int, window: int = 60) -> bool:
    """Фиксированное окно. Возвращает True, если лимит превышен."""
    r = get_redis()
    k = f"rl:{action}:{key}"
    n = r.incr(k)
    if n == 1:
        r.expire(k, window)
    return n > limit


def _fingerprint(text: str) -> str:
    norm = re.sub(r"\W+", " ", text.lower()).strip()
    return hashlib.sha1(norm.encode()).hexdigest()


def check_post(text: str, account_age_hours: float) -> None:
    """Вызывается перед созданием вопроса/ответа. Ничего не блокирует сама —
    только помечает клиента подозрительным, после чего следующий пост потребует капчу."""
    key = client_key()
    limit = current_app.config["ANTISPAM_POSTS_PER_MINUTE"]
    if hit_rate("post", key, limit):
        mark_suspicious(key, "rate")
    r = get_redis()
    fp_key = f"dup:{key}:{_fingerprint(text)}"
    if r.incr(fp_key) > 2:
        mark_suspicious(key, "duplicate")
    r.expire(fp_key, 3600)
    if account_age_hours < 24 and LINK_RE.search(text):
        mark_suspicious(key, "new_account_links")
