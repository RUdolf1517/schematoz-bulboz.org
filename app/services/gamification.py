"""Стрики, уровни и бейджи. Всё считается правилами — без ML.

Стрик: день засчитывается, если пользователь ОТВЕТИЛ хотя бы на один вопрос
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

from ..models import Answer, ContentStatus, Question, RepReason, ReputationEvent, User, UserBadge
from .notifications import notify

MSK = ZoneInfo("Europe/Moscow")


@dataclass(frozen=True)
class Badge:
    code: str
    title: str
    emoji: str
    description: str


BADGES: dict[str, Badge] = {b.code: b for b in [
    Badge("first_answer", "Первый блин", "🥞", "Дал первый ответ"),
    Badge("first_question", "Почемучка", "❓", "Задал первый вопрос"),
    Badge("first_scheme", "Рабочая схема", "🔥", "Автор вопроса впервые поставил твоему ответу +5"),
    Badge("schemes_10", "Схематозник", "🧠", "10 ответов стали «Схемой»"),
    Badge("schemes_100", "Легенда схем", "👑", "100 ответов стали «Схемой»"),
    Badge("streak_7", "Неделя в деле", "📅", "Стрик 7 дней"),
    Badge("streak_30", "Месяц без пропусков", "🗓️", "Стрик 30 дней"),
    Badge("streak_100", "Сотка", "💯", "Стрик 100 дней"),
    Badge("night_watch", "Ночной дозор", "🌙", "Ответил между 2 и 5 ночи по Москве"),
    Badge("debater", "В бой!", "⚔️", "Впервые занял сторону в холиваре"),
]}

LEVEL_NAMES = [
    (1, "Нуб"), (5, "Шарящий"), (10, "Мудрец с подъезда"), (20, "Легенда форума"),
    (35, "Тот самый с Ответов"),
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


async def on_answer_created(s: AsyncSession, user: User, answer: Answer,
                            now: datetime | None = None) -> list[str]:
    now = (now or datetime.now(MSK)).astimezone(MSK)
    today = now.date()
    db_user = await s.get(User, user.id, with_for_update=True)
    db_user.streak_days, used_freeze = next_streak(
        db_user.streak_days, db_user.streak_last_date, today, db_user.streak_freeze_week)
    if used_freeze:
        db_user.streak_freeze_week = iso_week(today)
    db_user.streak_last_date = today

    new = []
    count = await s.scalar(select(func.count(Answer.id)).where(Answer.author_id == user.id))
    if count == 1 and await award(s, user.id, "first_answer"):
        new.append("first_answer")
    for days in (7, 30, 100):
        if db_user.streak_days >= days and await award(s, user.id, f"streak_{days}"):
            new.append(f"streak_{days}")
    if 2 <= now.hour < 5 and await award(s, user.id, "night_watch"):
        new.append("night_watch")
    if answer.debate_side is not None and await award(s, user.id, "debater"):
        new.append("debater")
    return new


async def on_question_created(s: AsyncSession, user_id: int) -> list[str]:
    return ["first_question"] if await award(s, user_id, "first_question") else []


async def on_scheme(s: AsyncSession, user_id: int) -> list[str]:
    """Вызывается, когда ответ пользователя получил +5 от автора вопроса."""
    n = await s.scalar(select(func.count(func.distinct(ReputationEvent.answer_id))).where(
        ReputationEvent.user_id == user_id, ReputationEvent.reason == RepReason.AUTHOR_VOTE,
        ReputationEvent.delta == 5))
    new = []
    for code, need in (("first_scheme", 1), ("schemes_10", 10), ("schemes_100", 100)):
        if n >= need and await award(s, user_id, code):
            new.append(code)
    return new


async def user_badges(s: AsyncSession, user_id: int) -> list[dict]:
    rows = (await s.execute(select(UserBadge).where(UserBadge.user_id == user_id)
                            .order_by(UserBadge.awarded_at))).scalars().all()
    return [{**BADGES[r.code].__dict__, "awarded_at": r.awarded_at.isoformat()}
            for r in rows if r.code in BADGES]
