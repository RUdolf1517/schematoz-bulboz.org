"""Защита мини-игр от автокликеров.

Сервер и так сам считает очки по seed и не пускает «слишком быстрые» партии. Здесь — поведенческие
признаки бота. Живой человек:
* реагирует не быстрее ~120 мс (медиана реакции у людей 200–350 мс);
* никогда не попадает с идеальной стабильностью — разброс реакции/попадания в ритм ≥ 10–15 мс;
* жмёт настоящими событиями (`isTrusted`), а не `dispatchEvent`.

Подозрительная партия не даёт наград (точность → 0). Три подозрительные партии за сутки —
игрок помечается для антиспама: следующая игра потребует капчу kremle-detect.
"""
from __future__ import annotations

import statistics

from ..extensions import get_redis
from . import antispam

MIN_TAPS = 6               # на меньшей выборке статистика врёт — не судим
FAST_REACTION_MS = 120     # быстрее человек не успевает
FAST_SHARE = 0.4           # доля «сверхбыстрых» реакций, после которой это бот
MIN_JITTER_MS = 8          # стандартное отклонение реакции/попадания у людей заметно больше
FLAGS_FOR_CAPTCHA = 3
FLAG_TTL = 24 * 3600


def _flag_key(uid: int) -> str:
    return f"antibot:{uid}"


def check_reactions(reactions: list[float]) -> str | None:
    """reactions — задержки «предмет появился → тап» (мс)."""
    r = [x for x in reactions if isinstance(x, (int, float)) and x >= 0]
    if len(r) < MIN_TAPS:
        return None
    if sum(1 for x in r if x < FAST_REACTION_MS) / len(r) >= FAST_SHARE:
        return "fast_reactions"
    if statistics.pstdev(r) < MIN_JITTER_MS:
        return "robotic_timing"
    return None


def check_offsets(offsets: list[float]) -> str | None:
    """offsets — отклонения тапа от такта (мс). Идеальная стабильность = скрипт."""
    o = [x for x in offsets if isinstance(x, (int, float))]
    if len(o) < MIN_TAPS:
        return None
    if statistics.pstdev(o) < MIN_JITTER_MS / 2:
        return "robotic_rhythm"
    return None


def check_intervals(times: list[float]) -> str | None:
    """Ровные интервалы между тапами (автокликер с таймером)."""
    t = sorted(x for x in times if isinstance(x, (int, float)))
    if len(t) < MIN_TAPS + 1:
        return None
    gaps = [b - a for a, b in zip(t, t[1:])]
    if statistics.pstdev(gaps) < 3:
        return "even_intervals"
    return None


def check_client(meta) -> str | None:
    """Клиент считает синтетические события (`!e.isTrusted`). Подделать можно, но отсекает ленивых ботов."""
    if isinstance(meta, dict) and isinstance(meta.get("synthetic"), int) and meta["synthetic"] > 0:
        return "synthetic_events"
    return None


def disabled() -> bool:
    """ANTIBOT_DISABLED=1 — только для e2e в jsdom (там все события синтетические)."""
    from flask import current_app
    return bool(current_app.config.get("ANTIBOT_DISABLED"))


def verdict(*reasons: str | None) -> str | None:
    if disabled():
        return None
    return next((r for r in reasons if r), None)


def register(user_id: int, reason: str | None) -> int:
    """Учесть подозрительную партию. Возвращает число флагов за сутки."""
    if not reason:
        return 0
    r = get_redis()
    key = _flag_key(user_id)
    n = r.incr(key)
    if n == 1:
        r.expire(key, FLAG_TTL)
    if n >= FLAGS_FOR_CAPTCHA:
        antispam.mark_suspicious(f"u:{user_id}", f"autoclicker:{reason}")
    return int(n)


def flags(user_id: int) -> int:
    return int(get_redis().get(_flag_key(user_id)) or 0)
