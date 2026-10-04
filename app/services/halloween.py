"""Halloween event rules and persistent, cosmetic event state."""
from __future__ import annotations

import random
from datetime import date, datetime, timedelta, timezone

from sqlalchemy import select

from ..models import Kombucha, Setting, User
from . import kombucha_diary as diary

MSK = timezone(timedelta(hours=3))
EVENT_KEY = "halloween"

HATS = {
    "pumpkin": {"title": "Тыква", "emoji": "🎃"},
    "witch": {"title": "Ведьмина шляпа", "emoji": "🧙‍♀️"},
    "horns": {"title": "Рога", "emoji": "😈"},
    "ghost_halo": {"title": "Нимб-призрак", "emoji": "👻"},
    "foil": {"title": "Шапочка из фольги", "emoji": "🛸"},
}
TEMP_MUTATIONS = {
    "halloween_ghost": {"title": "Призрачная прозрачность", "emoji": "👻", "color": "#b9e9ff", "effect": "ghost"},
    "halloween_zombie": {"title": "Зомби-зелень", "emoji": "🧟", "color": "#76d66f", "effect": "zombie"},
    "halloween_eyes": {"title": "Светящиеся глаза", "emoji": "👁️", "color": "#ff5b21", "effect": "eyes"},
}
DEFAULT_CONFIG = {
    # Default season is visible during October 2026; admins can change the dates or disable it.
    "enabled": True,
    "start_at": "2026-10-01T00:00:00+00:00",
    "end_at": "2026-11-02T00:00:00+00:00",
}


def _parse_dt(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        out = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None
    if out.tzinfo is None:
        return None
    return out.astimezone(timezone.utc)


def active(config: dict, at: datetime | None = None) -> bool:
    if not config.get("enabled"):
        return False
    at = at or datetime.now(timezone.utc)
    start, end = _parse_dt(config.get("start_at")), _parse_dt(config.get("end_at"))
    return bool(start and end and start <= at < end)


async def get_config(s) -> dict:
    setting = await s.get(Setting, EVENT_KEY)
    return {**DEFAULT_CONFIG, **(setting.value or {})} if setting else dict(DEFAULT_CONFIG)


def public_state(config: dict, user: User | None = None) -> dict:
    profile = (user.profile or {}) if user else {}
    return {
        "active": active(config),
        "enabled": bool(config.get("enabled")),
        "start_at": config.get("start_at"),
        "end_at": config.get("end_at"),
        "hats": HATS,
        "owned_hats": list(dict.fromkeys(x for x in profile.get("halloween_hats", []) if x in HATS)),
    }


def day_for(at: datetime | None = None) -> date:
    return (at or datetime.now(timezone.utc)).astimezone(MSK).date()


def active_mutations(k: Kombucha, at: datetime | None = None) -> list[dict]:
    at = at or datetime.now(timezone.utc)
    out = []
    for entry in (k.halloween_mutations or []):
        spec = TEMP_MUTATIONS.get(entry.get("code"))
        expires = _parse_dt(entry.get("expires_at"))
        if spec and expires and expires > at:
            out.append({
                "code": entry["code"], "title": spec["title"], "emoji": spec["emoji"],
                "color": spec["color"], "rarity": "event", "rarity_title": "Временная хэллоуинская",
                "stage": 0, "serial": None, "inherited": False,
                "at": entry.get("at"), "expires_at": entry.get("expires_at"),
            })
    return out


def add_temp_mutation(s, k: Kombucha, at: datetime | None = None, force: bool = False) -> dict | None:
    at = at or datetime.now(timezone.utc)
    if not force and random.random() >= 0.1:
        return None
    current_codes = {x["code"] for x in active_mutations(k, at)}
    pool = [code for code in TEMP_MUTATIONS if code not in current_codes] or list(TEMP_MUTATIONS)
    code = random.choice(pool)
    entry = {"code": code, "at": at.isoformat(), "expires_at": (at + timedelta(days=3)).isoformat()}
    k.halloween_mutations = [*(k.halloween_mutations or []), entry][-20:]
    spec = TEMP_MUTATIONS[code]
    diary.log(s, k, "halloween_mutation", at=at, title=spec["title"])
    return {"code": code, **spec, "expires_at": entry["expires_at"]}


async def alert_temp_mutation(s, k: Kombucha, mutation: dict) -> None:
    from .notifications import notify_once
    from .push import enqueue_push
    key = f"halloween_mutation:{k.id}:{mutation['expires_at']}"
    body = f"Я обзавёлся временной мутацией: {mutation['emoji']} «{mutation['title']}». До трёх дней."
    await notify_once(s, k.user_id, "kombucha", key, text=body, kombucha_id=k.id, category="mutation")
    await enqueue_push(s, k.user_id, "mutation", "Хэллоуинская мутация 👁️", body, f"/g/{k.id}", key)


async def prepare_k(s, k: Kombucha, config: dict, at: datetime | None = None) -> None:
    """Persist the daily disappearance roll and guarantee a first temporary mutation."""
    at = at or datetime.now(timezone.utc)
    if not active(config, at) or not k.alive or k.frozen:
        return
    day = day_for(at)
    if k.halloween_gone_day != day:
        k.halloween_gone_day = day
        k.halloween_gone = random.random() < 0.5
        if k.halloween_gone:
            diary.log(s, k, "haunted", at=at)
    # Keep at least one temporary mutation visible throughout the event; each lasts three days.
    if not active_mutations(k, at):
        mutation = add_temp_mutation(s, k, at=at, force=True)
        if mutation:
            await alert_temp_mutation(s, k, mutation)


async def on_action(s, k: Kombucha, config: dict, at: datetime | None = None) -> dict | None:
    at = at or datetime.now(timezone.utc)
    if not active(config, at) or not k.alive or k.frozen:
        return None
    await prepare_k(s, k, config, at)
    mutation = add_temp_mutation(s, k, at=at, force=False)
    if mutation:
        await alert_temp_mutation(s, k, mutation)
    return mutation


async def inventory(user: User) -> list[str]:
    return list(dict.fromkeys(x for x in ((user.profile or {}).get("halloween_hats") or []) if x in HATS))


async def award_survivor(s, user_id: int) -> bool:
    from .gamification import award
    return await award(s, user_id, "halloween_survivor_2026")
