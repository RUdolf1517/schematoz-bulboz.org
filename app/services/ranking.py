"""Ранжирование ленты — формула, без ML."""
from __future__ import annotations

import math
from datetime import datetime, timezone

EPOCH = datetime(2026, 1, 1, tzinfo=timezone.utc)


def hot_score(answers_score_sum: int, answers_count: int, created_at: datetime) -> float:
    engagement = answers_score_sum + 2 * answers_count
    order = math.log10(max(abs(engagement), 1))
    sign = 1 if engagement > 0 else -1 if engagement < 0 else 0
    age = (created_at - EPOCH).total_seconds()
    return round(sign * order + age / 45000, 7)
