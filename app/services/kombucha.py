"""«Чайный гриб» — тамагочи в трёхлитровой банке.

Правила (всё считает сервер, фронт только рисует):
- 4 показателя 0..100: сахар, заварка, чистота, настроение. Каждый час убывают
  (DECAY), так что заглядывать нужно примерно раз в день.
- Действия с кулдаунами дают показатель и опыт. Пересластил (сахар > 90) — гриб
  «слипся», настроение падает. Мыть банку слишком часто тоже нельзя: кулдаун 4 ч.
- «Схема дня»: раз в 20 часов гриб получает бонус опыта за твои ответы на сайте
  за последние сутки (связь игры с основной активностью — удержание).
- Если какой-то показатель лежит на нуле больше 24 часов — гриб закисает.
  Можно завести новый (поколение +1), рекорд опыта сохраняется.
- Стадии роста по опыту: от споры до легенды трёхлитровой банки.
"""
from __future__ import annotations

import random
from datetime import datetime, timedelta, timezone

from sqlalchemy import func, select

from ..errors import ApiError
from ..models import Answer, ContentStatus, Kombucha, User

STATS = ("sweet", "tea", "clean", "happy")
DECAY = {"sweet": 4.0, "tea": 3.0, "clean": 1.5, "happy": 3.0}  # в час
DEATH_AFTER = timedelta(hours=24)

# действие: (показатель, прирост, кулдаун, опыт, фраза)
ACTIONS = {
    "sugar": ("sweet", 35, timedelta(hours=1), 5, "Хрум-хрум, сахарок 🍬"),
    "tea": ("tea", 40, timedelta(hours=1), 5, "Свежая заварка, как у бабушки ☕"),
    "clean": ("clean", 60, timedelta(hours=4), 8, "Банка сияет ✨"),
    "pet": ("happy", 15, timedelta(minutes=10), 2, "Гриб довольно булькает 🫧"),
}
DAILY_COOLDOWN = timedelta(hours=20)

STAGES = [  # (с какого опыта, название, размер 1..6)
    (0, "Спора", 1), (50, "Плёночка", 2), (150, "Блинчик", 3), (400, "Медуза", 4),
    (900, "Гриб-гигант", 5), (2000, "Легенда трёхлитровой банки", 6),
]

TALK = {
    "happy": ["Жизнь — как заварка: главное, не пересластить.", "Я сегодня особенно газированный 😎",
              "Ответь на вопрос в ленте — мне от этого тоже хорошо.", "Бульк. Это значит «спасибо»."],
    "hungry": ["Сахарку бы…", "Я не капризничаю, я ферментируюсь без сахара."],
    "thirsty": ["Заварки! Полцарства за заварку!", "Я почти компот. Долей чаю."],
    "dirty": ["Банка мутная, как объяснения у доски.", "Помой банку, пожалуйста. Мне неловко."],
    "sad": ["Со мной никто не разговаривает…", "Погладь, а?"],
    "sticky": ["Я слипся. Это был перебор с сахаром.", "Сахарная кома, не беспокоить."],
}


def now() -> datetime:
    return datetime.now(timezone.utc)


def stage_for(xp: int) -> dict:
    cur = STAGES[0]
    nxt = None
    for i, st in enumerate(STAGES):
        if xp >= st[0]:
            cur = st
            nxt = STAGES[i + 1] if i + 1 < len(STAGES) else None
    return {"title": cur[1], "size": cur[2], "from_xp": cur[0], "next_xp": nxt[0] if nxt else None,
            "next_title": nxt[1] if nxt else None}


def tick(k: Kombucha, at: datetime | None = None) -> None:
    """Досчитать убывание с updated_at до `at` и проверить, не закис ли гриб."""
    at = at or now()
    if not k.alive:
        return
    hours = max((at - k.updated_at).total_seconds() / 3600, 0)
    if hours <= 0:
        return
    hit_zero_at = None
    for s in STATS:
        v = getattr(k, s)
        rate = DECAY[s]
        if v - rate * hours <= 0:
            t0 = k.updated_at + timedelta(hours=v / rate if rate else 0)
            hit_zero_at = t0 if hit_zero_at is None else min(hit_zero_at, t0)
        setattr(k, s, max(v - rate * hours, 0.0))
    if any(getattr(k, s) <= 0 for s in STATS):
        k.zero_since = k.zero_since or hit_zero_at or at
    else:
        k.zero_since = None
    if k.zero_since and at - k.zero_since >= DEATH_AFTER:
        k.alive = False
        k.died_at = k.zero_since + DEATH_AFTER
    k.updated_at = at


def mood(k: Kombucha) -> str:
    if not k.alive:
        return "dead"
    if k.sweet > 95:
        return "sticky"
    low = min(STATS, key=lambda s: getattr(k, s))
    if getattr(k, low) < 25:
        return {"sweet": "hungry", "tea": "thirsty", "clean": "dirty", "happy": "sad"}[low]
    return "happy"


async def get_or_create(s, user_id: int) -> Kombucha:
    k = await s.get(Kombucha, user_id, with_for_update=True)
    if k is None:
        k = Kombucha(user_id=user_id, name="Гриша", xp=0, best_xp=0, generation=1, sweet=70.0, tea=70.0,
                     clean=90.0, happy=70.0, alive=True, cooldowns={}, born_at=now(), updated_at=now())
        s.add(k)
        await s.flush()
    tick(k)
    return k


def _cd_left(k: Kombucha, key: str, cd: timedelta, at: datetime) -> int:
    last = (k.cooldowns or {}).get(key)
    if not last:
        return 0
    left = datetime.fromisoformat(last) + cd - at
    return max(int(left.total_seconds()), 0)


async def answers_last_day(s, user_id: int) -> int:
    return await s.scalar(select(func.count(Answer.id)).where(
        Answer.author_id == user_id, Answer.status == ContentStatus.ACTIVE,
        Answer.created_at >= now() - timedelta(hours=24))) or 0


async def act(s, k: Kombucha, action: str) -> str:
    at = now()
    if not k.alive:
        raise ApiError("Гриб закис 😢 Заведи новый", 409, "kombucha_dead")
    if action == "daily":
        left = _cd_left(k, "daily", DAILY_COOLDOWN, at)
        if left:
            raise ApiError("Схема дня уже забрана", 429, "cooldown", retry_after=left)
        n = min(await answers_last_day(s, k.user_id), 6)
        gain = 10 + 8 * n
        k.xp += gain
        k.happy = min(k.happy + 10, 100.0)
        msg = (f"+{gain} опыта: ты дал {n} ответ(ов) за сутки, гриб гордится 🏆" if n
               else f"+{gain} опыта. Ответь на вопросы в ленте, завтра бонус будет больше 😉")
    elif action in ACTIONS:
        stat, add, cd, xp, msg = ACTIONS[action]
        left = _cd_left(k, action, cd, at)
        if left:
            raise ApiError("Рано, гриб ещё не соскучился", 429, "cooldown", retry_after=left)
        if action == "sugar" and k.sweet > 90:
            k.happy = max(k.happy - 10, 0.0)
            msg = "Перебор! Гриб слипся 🥴 (−настроение)"
            xp = 0
        setattr(k, stat, min(getattr(k, stat) + add, 100.0))
        if action == "pet":
            msg = random.choice(TALK[mood(k)] if mood(k) in TALK else TALK["happy"])
        k.xp += xp
    else:
        raise ApiError("Неизвестное действие", 400, "validation_error")
    k.cooldowns = {**(k.cooldowns or {}), action: at.isoformat()}
    k.best_xp = max(k.best_xp, k.xp)
    if all(getattr(k, st) > 0 for st in STATS):
        k.zero_since = None
    k.updated_at = at
    return msg


def restart(k: Kombucha, name: str | None = None) -> None:
    if k.alive:
        raise ApiError("Гриб жив, его не надо перезаводить", 409, "kombucha_alive")
    at = now()
    k.generation += 1
    k.name = (name or k.name)[:32]
    k.xp = 0
    k.sweet, k.tea, k.clean, k.happy = 70.0, 70.0, 90.0, 70.0
    k.alive, k.zero_since, k.died_at, k.cooldowns = True, None, None, {}
    k.born_at = k.updated_at = at


def out(k: Kombucha) -> dict:
    at = now()
    cds = {a: _cd_left(k, a, cd, at) for a, (_, _, cd, _, _) in ACTIONS.items()}
    cds["daily"] = _cd_left(k, "daily", DAILY_COOLDOWN, at)
    m = mood(k)
    danger = None
    if k.alive and k.zero_since:
        danger = max(int((k.zero_since + DEATH_AFTER - at).total_seconds()), 0)
    return {
        "name": k.name, "xp": k.xp, "best_xp": k.best_xp, "generation": k.generation, "alive": k.alive,
        "stats": {s: round(getattr(k, s)) for s in STATS}, "mood": m,
        "phrase": random.choice(TALK[m]) if m in TALK else "…",
        "stage": stage_for(k.xp), "cooldowns": cds, "dies_in": danger,
        "age_days": (at - k.born_at).days, "born_at": k.born_at.isoformat(),
        "died_at": k.died_at.isoformat() if k.died_at else None,
    }
