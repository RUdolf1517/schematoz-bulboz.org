"""Periodic game-state alerts. Run via `flask --app app run-notification-jobs` from a timer/cron."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from sqlalchemy import select

from ..extensions import get_redis
from ..models import Kombucha, User
from . import halloween, kombucha as kb
from .notifications import notify_once
from .push import enqueue_push

UTC = timezone.utc


async def _emit(s, user_id: int, category: str, key: str, title: str, body: str,
               url: str = "/", kombucha_id: int | None = None) -> bool:
    site_notice = await notify_once(s, user_id, "kombucha", key, text=body,
                                    kombucha_id=kombucha_id, category=category)
    push_notice = await enqueue_push(s, user_id, category, title, body, url, key)
    return site_notice or push_notice


def _cooldown_due(k, action: str, hours: float, at: datetime) -> datetime | None:
    stamp = (k.cooldowns or {}).get(action)
    if not stamp:
        return None
    try:
        return datetime.fromisoformat(stamp) + timedelta(hours=hours)
    except (TypeError, ValueError):
        return None


async def scan_notifications(at: datetime | None = None) -> dict:
    """Create idempotent website notices and opt-in PWA outbox rows for due alerts."""
    at = at or datetime.now(UTC)
    if at.tzinfo is None:
        at = at.replace(tzinfo=UTC)
    at = at.astimezone(UTC)
    today = at.astimezone(halloween.MSK).date().isoformat()
    async with _session_scope() as s:
        users = (await s.scalars(select(User))).all()
        by_id = {u.id: u for u in users}
        kombuchas = (await s.scalars(select(Kombucha).where(
            Kombucha.alive.is_(True), Kombucha.frozen.is_(False)).order_by(Kombucha.id))).all()
        created = 0
        death_alerted: set[int] = set()
        for k in kombuchas:
            owner = by_id.get(k.user_id)
            if not owner:
                continue
            was_alive = k.alive
            kb.tick(k, at)
            route = f"/g/{k.id}"
            if was_alive and not k.alive:
                key = f"dead:{k.id}:{k.died_at.isoformat() if k.died_at else today}"
                created += await _emit(s, owner.id, "dead", key, "Я закис 🪦",
                                       "Я закис. Если читаешь это — поливай своих грибов вовремя.", route, k.id)
                death_alerted.add(k.id)
                continue
            if not k.alive:
                continue
            key_prefix = f"{k.id}:{today}"
            low = [("sweet", "сахар"), ("tea", "заварка"), ("clean", "чистота"), ("happy", "настроение")]
            weakest = next(((name, title) for name, title in low if getattr(k, name) < 30), None)
            if weakest:
                stat, title_stat = weakest
                key = f"stat_low:{key_prefix}:{stat}"
                created += await _emit(s, owner.id, "stat_low", key, "Банка просит ухода",
                                       f"Я не обижаюсь. Просто {title_stat} уже ниже 30 — и я это запомнил.", route, k.id)
            pet_due = _cooldown_due(k, "pet", 0.5, at)
            if pet_due and pet_due <= at:
                key = f"pet_ready:{k.id}:{(k.cooldowns or {}).get('pet')}"
                created += await _emit(s, owner.id, "pet_ready", key, "Можно погладить 🍄",
                                       f"Я не навязываюсь. Кулдаун на поглаживание уже прошёл.", route, k.id)
            if k.mold:
                key = f"mold:{key_prefix}"
                created += await _emit(s, owner.id, "mold", key, "У меня новые соседи 🦠",
                                       f"Плесень растёт быстрее меня. Уксусная ванна — сейчас.", route, k.id)
            if k.zero_since:
                dying_at = k.zero_since + kb.DEATH_AFTER
                if at <= dying_at <= at + timedelta(hours=3):
                    key = f"dying:{k.id}:{k.zero_since.isoformat()}"
                    created += await _emit(s, owner.id, "dying", key, "Я на грани 🥀",
                                           f"Если не поднять показатель с нуля, я закисну через {max(1, round((dying_at-at).total_seconds()/3600))} ч.", route, k.id)
            if kb._cd_left(k, "daily", kb.DAILY_COOLDOWN, at) == 0:
                key = f"daily_bonus:{key_prefix}"
                created += await _emit(s, owner.id, "daily_bonus", key, "Бонус дня готов 🏆",
                                       "Мой бонус дня готов. Я, конечно, не намекаю — но кнопка там.", route, k.id)
            if kb.can_sprout(k, at):
                key = f"sharing:{k.id}:{k.sprout_count}:{k.last_sprout_at.isoformat() if k.last_sprout_at else 'first'}"
                created += await _emit(s, owner.id, "sharing", key, "Я готов делиться 🌱",
                                       "Я дорос до деления. Осталось заглянуть на подоконник.", route, k.id)

            # A single daily reminder if at least one mini-game's reward window is open.
            r = get_redis()
            games = ("pour", "memory", "sugar", "flies")
            ready = any(r.exists(f"mg:played:{k.id}:{game}") and r.ttl(f"mg:cd:{k.id}:{game}") <= 0
                        for game in games)
            ready = ready or bool(r.exists(f"med:played:{k.id}") and r.ttl(f"med:cd:{k.id}") <= 0)
            if ready:
                key = f"game_reward:{key_prefix}"
                created += await _emit(s, owner.id, "game_reward", key, "Награда снова доступна 🎮",
                                       "В одной из моих мини-игр снова готова награда. Пальцы размялись?", route, k.id)

        # The game API can lazily tick a mushroom to death before this worker sees it.
        recent_deaths = (await s.scalars(select(Kombucha).where(
            Kombucha.alive.is_(False), Kombucha.died_at >= at - timedelta(minutes=10),
        ))).all()
        for k in recent_deaths:
            if k.id in death_alerted:
                continue
            owner = by_id.get(k.user_id)
            if owner:
                key = f"dead:{k.id}:{k.died_at.isoformat() if k.died_at else today}"
                created += await _emit(s, owner.id, "dead", key, "Я закис 🪦",
                                       "Я закис. Если читаешь это — поливай своих грибов вовремя.",
                                       f"/g/{k.id}", k.id)

        for user in users:
            if user.last_seen_at and user.last_seen_at <= at - timedelta(hours=6):
                key = f"missing:{user.id}:{int(user.last_seen_at.timestamp())}"
                created += await _emit(s, user.id, "missing", key, "Я тут. Один. В банке.",
                                       "Я не обижаюсь. Я просто закисаю, пока тебя нет уже шесть часов.")
            if user.streak_days and user.streak_last_date == today_date(at) - timedelta(days=1):
                local = at.astimezone(halloween.MSK)
                if local.hour == 21:
                    key = f"streak_expiring:{user.id}:{today}"
                    created += await _emit(s, user.id, "streak_expiring", key, "Твой стрик истекает 🔥",
                                           "До полуночи около трёх часов. Я бы напомнил раньше, но ты же занят(а).", "/")
        return {"checked_users": len(users), "checked_mushrooms": len(kombuchas), "created": created}



def today_date(at: datetime):
    return at.astimezone(halloween.MSK).date()


from contextlib import asynccontextmanager


@asynccontextmanager
async def _session_scope():
    from ..db import session_scope
    async with session_scope() as s:
        yield s
