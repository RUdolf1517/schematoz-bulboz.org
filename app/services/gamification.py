"""Стрики, уровни и бейджи. Всё считается правилами — без ML.

Стрик: день засчитывается, если пользователь хоть раз УХАЖИВАЛ за грибом
(просто зайти мало). Дни считаются по московскому времени.
Заморозка: одна в ISO-неделю. Если пропущен ровно один день, заморозка тратится
автоматически и стрик продолжается.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from ..models import User, UserBadge
from .notifications import notify

MSK = ZoneInfo("Europe/Moscow")


@dataclass(frozen=True)
class Badge:
    code: str
    title: str
    emoji: str
    description: str


BADGES: dict[str, Badge] = {b.code: b for b in [
    Badge("streak_7", "Неделя в деле", "📅", "Стрик 7 дней"),
    Badge("streak_30", "Месяц без пропусков", "🗓️", "Стрик 30 дней"),
    Badge("streak_100", "Сотка", "💯", "Стрик 100 дней"),
    Badge("night_watch", "Ночной дозор", "🌙", "Ухаживал за грибом между 2 и 5 ночи по Москве"),
    Badge("halloween_survivor_2026", "Пережил Хэллоуин 2026", "🎃", "Заглянул на подоконник во время Хэллоуина 2026"),
]}
# достижения мини-игры «Чайный гриб»
from .kombucha_achievements import KB_BADGES as _KB  # noqa: E402
BADGES.update({c: Badge(c, t, e, d) for c, t, e, d in _KB})

LEVEL_NAMES = [
    (1, "Грибной нуб"), (5, "Садовод банки"), (10, "Заварщик"), (20, "Грибной магистр"),
    (35, "Тот самый с трёхлитровой банкой"),
]


def level_name(level: int) -> str:
    name = LEVEL_NAMES[0][1]
    for threshold, title in LEVEL_NAMES:
        if level >= threshold:
            name = title
    return name


def msk_today(now: datetime | None = None) -> date:
    return (now or datetime.now(MSK)).astimezone(MSK).date()


def iso_week(d: date) -> str:
    y, w, _ = d.isocalendar()
    return f"{y}-W{w:02d}"


def freeze_available(freeze_week: str | None, today: date) -> bool:
    return freeze_week != iso_week(today)


def next_streak(current: int, last: date | None, today: date,
                freeze_week: str | None = "used") -> tuple[int, bool]:
    """Возвращает (новый стрик, потрачена ли заморозка)."""
    if last == today:
        return current, False
    if last == today - timedelta(days=1):
        return current + 1, False
    if last == today - timedelta(days=2) and current > 0 and freeze_available(freeze_week, today):
        return current + 1, True
    return 1, False


def visible_streak(current: int, last: date | None, today: date | None = None,
                   freeze_week: str | None = "used") -> int:
    """Стрик «сгорает», если вчера и сегодня не было ответов (с учётом доступной заморозки)."""
    today = today or msk_today()
    if last is None:
        return 0
    if last >= today - timedelta(days=1):
        return current
    if last == today - timedelta(days=2) and freeze_available(freeze_week, today):
        return current  # ещё можно спасти: сегодняшний ответ потратит заморозку
    return 0


async def award(s: AsyncSession, user_id: int, code: str) -> bool:
    """Выдать бейдж (идемпотентно). True — если выдан только что."""
    assert code in BADGES, code
    res = await s.execute(
        insert(UserBadge).values(user_id=user_id, code=code)
        .on_conflict_do_nothing().returning(UserBadge.code)
    )
    new = res.scalar() is not None
    if new:
        b = BADGES[code]
        notify(s, user_id, "badge", code=code, title=b.title, emoji=b.emoji)
    return new


async def on_care(s: AsyncSession, user_id: int, now: datetime | None = None) -> list[str]:
    """Любой уход за грибом двигает стрик (раз в день по Москве) и может выдать бейджи."""
    now = (now or datetime.now(MSK)).astimezone(MSK)
    today = now.date()
    db_user = await s.get(User, user_id, with_for_update=True)
    new = []
    if db_user.streak_last_date != today:
        db_user.streak_days, used_freeze = next_streak(
            db_user.streak_days, db_user.streak_last_date, today, db_user.streak_freeze_week)
        if used_freeze:
            db_user.streak_freeze_week = iso_week(today)
        db_user.streak_last_date = today
        for days in (7, 30, 100):
            if db_user.streak_days >= days and await award(s, user_id, f"streak_{days}"):
                new.append(f"streak_{days}")
    if 2 <= now.hour < 5 and await award(s, user_id, "night_watch"):
        new.append("night_watch")
    return new


async def user_badges(s: AsyncSession, user_id: int) -> list[dict]:
    rows = (await s.execute(select(UserBadge).where(UserBadge.user_id == user_id)
                            .order_by(UserBadge.awarded_at))).scalars().all()
    return [{**BADGES[r.code].__dict__, "awarded_at": r.awarded_at.isoformat()}
            for r in rows if r.code in BADGES]
