"""Halloween event rules and persistent, cosmetic event state."""
from __future__ import annotations

import copy
import hashlib
import random
import re
from datetime import date, datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert

from ..errors import ApiError
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
DEFAULT_RAID_CONFIG = {
    "boss_name": "Тыквенная плесень",
    "regen_per_minute": 6,
    "stages": [{"title": "Первая волна", "max_hp": 10000,
                "description": "Пробейся сквозь плесень и помоги всему сайту."}],
    "gifts": [],
}
DEFAULT_CONFIG = {
    # По умолчанию событие выключено: админ включает его в /admin → «Ивенты»
    # и сам закрывает итоги кнопкой (см. halloween_raid.close_season).
    "enabled": False,
    "results_closed": False,
    "start_at": "2026-10-01T00:00:00+00:00",
    "end_at": "2026-11-02T00:00:00+00:00",
    "raid": DEFAULT_RAID_CONFIG,
}


def normalize_raid_config(value: dict | None) -> dict:
    """Merge persisted event settings with safe defaults (including older settings rows)."""
    raw = value if isinstance(value, dict) else {}
    defaults = copy.deepcopy(DEFAULT_RAID_CONFIG)
    stages = raw.get("stages")
    gifts = raw.get("gifts")
    if not isinstance(stages, list) or not stages:
        stages = defaults["stages"]
    if not isinstance(gifts, list):
        gifts = defaults["gifts"]
    normalized_stages = []
    for index, stage in enumerate(stages[:20]):
        if not isinstance(stage, dict):
            continue
        try:
            hp = int(stage.get("max_hp", defaults["stages"][0]["max_hp"]))
        except (TypeError, ValueError):
            hp = defaults["stages"][0]["max_hp"]
        normalized_stages.append({
            "title": str(stage.get("title") or f"Стадия {index + 1}")[:80],
            "max_hp": max(1, min(hp, 1_000_000)),
            "description": str(stage.get("description") or "")[:280],
        })
    if not normalized_stages:
        normalized_stages = defaults["stages"]
    normalized_gifts = []
    for gift in gifts[:100]:
        if not isinstance(gift, dict):
            continue
        try:
            stage = int(gift.get("stage", 1))
            damage = int(gift.get("required_damage", 1))
        except (TypeError, ValueError):
            continue
        gift_id = str(gift.get("id") or "")[:48]
        if not gift_id:
            continue
        reward_type = gift.get("reward_type")
        if reward_type != "badge":
            continue
        normalized_gifts.append({
            "id": gift_id, "stage": max(1, min(stage, len(normalized_stages))),
            "required_damage": max(1, min(damage, 1_000_000)),
            "reward_type": reward_type,
            "emoji": str(gift.get("emoji") or "🏅")[:12],
            "title": str(gift.get("title") or "Бейдж за вклад")[:80],
            "description": str(gift.get("description") or "")[:240],
        })
    try:
        regen = int(raw.get("regen_per_minute", defaults["regen_per_minute"]))
    except (TypeError, ValueError):
        regen = defaults["regen_per_minute"]
    return {
        "boss_name": str(raw.get("boss_name") or defaults["boss_name"])[:80],
        "regen_per_minute": max(0, min(regen, 60)),
        "stages": normalized_stages,
        "gifts": normalized_gifts,
    }


def validate_raid_config(value: dict) -> dict:
    """Validate the complete admin-edited raid configuration."""
    if not isinstance(value, dict):
        raise ApiError("Настройки рейда должны быть объектом", 400, "validation_error", field="raid")

    def text(value, field, minimum, maximum):
        if not isinstance(value, str):
            raise ApiError(f"Поле «{field}» должно быть текстом", 400, "validation_error", field=field)
        result = value.strip()
        if not minimum <= len(result) <= maximum:
            raise ApiError(f"Поле «{field}»: от {minimum} до {maximum} символов", 400,
                           "validation_error", field=field)
        return result

    def integer(value, field, minimum, maximum):
        if isinstance(value, bool) or not isinstance(value, int) or not minimum <= value <= maximum:
            raise ApiError(f"Поле «{field}»: целое число от {minimum} до {maximum}", 400,
                           "validation_error", field=field)
        return value

    boss_name = text(value.get("boss_name"), "boss_name", 1, 80)
    regen = integer(value.get("regen_per_minute"), "regen_per_minute", 0, 60)
    raw_stages = value.get("stages")
    if not isinstance(raw_stages, list) or not 1 <= len(raw_stages) <= 20:
        raise ApiError("Добавь от 1 до 20 стадий рейда", 400, "validation_error", field="stages")
    stages = []
    for index, stage in enumerate(raw_stages, 1):
        if not isinstance(stage, dict):
            raise ApiError(f"Стадия {index} заполнена неверно", 400, "validation_error", field="stages")
        stages.append({
            "title": text(stage.get("title"), f"stages[{index}].title", 1, 80),
            "max_hp": integer(stage.get("max_hp"), f"stages[{index}].max_hp", 1, 1_000_000),
            "description": text(stage.get("description", ""), f"stages[{index}].description", 0, 280),
        })

    raw_gifts = value.get("gifts", [])
    if not isinstance(raw_gifts, list) or len(raw_gifts) > 100:
        raise ApiError("Можно создать не больше 100 бейджей", 400, "validation_error", field="gifts")
    gifts, gift_ids = [], set()
    for index, gift in enumerate(raw_gifts, 1):
        if not isinstance(gift, dict):
            raise ApiError(f"Бейдж {index} заполнен неверно", 400, "validation_error", field="gifts")
        gift_id = text(gift.get("id"), f"gifts[{index}].id", 1, 48)
        if not re.fullmatch(r"[A-Za-z0-9_-]+", gift_id) or gift_id in gift_ids:
            raise ApiError("ID бейджей должны быть уникальными латинскими буквами, цифрами, _ или -",
                           400, "validation_error", field="gifts")
        gift_ids.add(gift_id)
        stage = integer(gift.get("stage"), f"gifts[{index}].stage", 1, len(stages))
        reward_type = gift.get("reward_type", "badge")
        if reward_type != "badge":
            raise ApiError("В рейде можно настраивать только бейджи", 400,
                           "validation_error", field=f"gifts[{index}].reward_type")
        gifts.append({
            "id": gift_id, "stage": stage,
            "required_damage": integer(gift.get("required_damage"), f"gifts[{index}].required_damage", 1, 1_000_000),
            "reward_type": reward_type,
            "emoji": text(gift.get("emoji"), f"gifts[{index}].emoji", 1, 12),
            "title": text(gift.get("title"), f"gifts[{index}].title", 1, 80),
            "description": text(gift.get("description", ""), f"gifts[{index}].description", 0, 240),
        })
    return {"boss_name": boss_name, "regen_per_minute": regen, "stages": stages, "gifts": gifts}


def stage_for(config: dict, phase: int) -> tuple[dict, int]:
    raid = normalize_raid_config(config.get("raid"))
    number = max(1, min(int(phase or 1), len(raid["stages"])))
    return raid["stages"][number - 1], number


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


def decay_window(config: dict) -> tuple[datetime, datetime] | None:
    if not config.get("enabled") or config.get("results_closed"):
        return None
    start, end = _parse_dt(config.get("start_at")), _parse_dt(config.get("end_at"))
    return (start, end) if start and end and end > start else None


def active(config: dict, at: datetime | None = None) -> bool:
    at = at or datetime.now(timezone.utc)
    if config.get("results_closed"):
        return False
    window = decay_window(config)
    return bool(window and window[0] <= at < window[1])


async def get_config(s, *, lock: bool = False) -> dict:
    if lock:
        setting = await s.scalar(
            select(Setting).where(Setting.key == EVENT_KEY).with_for_update()
        )
        if setting is None:
            await s.execute(insert(Setting).values(
                key=EVENT_KEY, value=DEFAULT_CONFIG
            ).on_conflict_do_nothing(index_elements=["key"]))
            setting = await s.scalar(
                select(Setting).where(Setting.key == EVENT_KEY).with_for_update()
            )
    else:
        setting = await s.get(Setting, EVENT_KEY)
    saved = (setting.value or {}) if setting else {}
    config = {**DEFAULT_CONFIG, **saved}
    config["raid"] = normalize_raid_config(saved.get("raid"))
    return config


def hat_catalog(user: User | None = None) -> dict[str, dict]:
    """The pre-existing Halloween hats collected via trick-or-treat."""
    return HATS


def reward_code(season_key: str, reward_id: str) -> str:
    digest = hashlib.sha256(f"{season_key}:{reward_id}".encode()).hexdigest()[:20]
    return "hrb_" + digest


def _owned_hat_codes(user: User | None = None) -> list[str]:
    profile = (user.profile or {}) if user else {}
    catalog = hat_catalog(user)
    return list(dict.fromkeys(code for code in (profile.get("halloween_hats") or [])
                              if isinstance(code, str) and code in catalog))


def public_state(config: dict, user: User | None = None, at: datetime | None = None) -> dict:
    return {
        "active": active(config, at),
        "enabled": bool(config.get("enabled")),
        "results_closed": bool(config.get("results_closed")),
        "start_at": config.get("start_at"),
        "end_at": config.get("end_at"),
        "hats": hat_catalog(user),
        "owned_hats": _owned_hat_codes(user),
    }


def day_for(at: datetime | None = None) -> date:
    return (at or datetime.now(timezone.utc)).astimezone(MSK).date()


def active_mutations(k: Kombucha, at: datetime | None = None) -> list[dict]:
    """Return every known Halloween mutation, including legacy entries past expires_at.

    `at` is retained for compatibility with callers; Halloween mutations no longer expire.
    """
    out, seen = [], set()
    for entry in (k.halloween_mutations or []):
        code = entry.get("code")
        spec = TEMP_MUTATIONS.get(code)
        if not spec or code in seen:
            continue
        seen.add(code)
        out.append({
            "code": code, "title": spec["title"], "emoji": spec["emoji"],
            "color": spec["color"], "rarity": "event", "rarity_title": "Постоянная хэллоуинская",
            "stage": 0, "serial": None, "inherited": False,
            "at": entry.get("at"),
        })
    return out


def add_temp_mutation(s, k: Kombucha, at: datetime | None = None, force: bool = False) -> dict | None:
    """Award one permanent Halloween mutation, preserving legacy function compatibility."""
    at = at or datetime.now(timezone.utc)
    if not force and random.random() >= 0.1:
        return None
    current_codes = {x["code"] for x in active_mutations(k, at)}
    pool = [code for code in TEMP_MUTATIONS if code not in current_codes]
    if not pool:
        return None
    code = random.choice(pool)
    entry = {"code": code, "at": at.isoformat()}
    k.halloween_mutations = [*(k.halloween_mutations or []), entry]
    spec = TEMP_MUTATIONS[code]
    diary.log(s, k, "halloween_mutation", at=at, title=spec["title"])
    return {"code": code, **spec}


async def alert_temp_mutation(s, k: Kombucha, mutation: dict) -> None:
    from .notifications import notify_once
    from .push import enqueue_push
    key = f"halloween_mutation:{k.id}:{mutation['code']}"
    body = f"Я обзавёлся хэллоуинской мутацией: {mutation['emoji']} «{mutation['title']}». Она останется со мной навсегда."
    await notify_once(s, k.user_id, "kombucha", key, text=body, kombucha_id=k.id, category="mutation")
    await enqueue_push(s, k.user_id, "mutation", "Постоянная хэллоуинская мутация 👁️", body, f"/g/{k.id}", key)


async def prepare_k(s, k: Kombucha, config: dict, at: datetime | None = None) -> None:
    """Persist the daily disappearance roll and guarantee a first permanent mutation."""
    at = at or datetime.now(timezone.utc)
    if not active(config, at) or not k.alive or k.frozen:
        return
    day = day_for(at)
    if k.halloween_gone_day != day:
        k.halloween_gone_day = day
        k.halloween_gone = random.random() < 0.5
        if k.halloween_gone:
            diary.log(s, k, "haunted", at=at)
    # Give each eligible mushroom a first permanent mutation during the event.
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
    return _owned_hat_codes(user)


async def award_survivor(s, user_id: int) -> bool:
    from .gamification import award
    return await award(s, user_id, "halloween_survivor_2026")
