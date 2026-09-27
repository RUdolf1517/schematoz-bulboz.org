"""«Чайный гриб» — тамагочи в трёхлитровой банке.

Правила (всё считает сервер, фронт только рисует):
- 4 показателя 0..100: сахар, заварка, чистота, настроение. Падают ступенькой
  РАЗ В 12 ЧАСОВ (DROP), отсчёт от рождения гриба — уход не сдвигает таймер.
- Действия с кулдаунами дают показатель и опыт. Пересластил (сахар > 90) — гриб слипся.
- «Схема дня»: раз в 20 часов бонус опыта за твои ответы на сайте за сутки.
- Если любой показатель лежит на нуле 24 часа — гриб закисает. Можно перезавести
  (поколение +1) или реанимировать за $₽.
- Имя гриба уникально на весь сайт (без учёта регистра).
- Несколько банок: одна бесплатно, остальные покупаются за «Деревянные».
- Отросток: если гриб дошёл до последней стадии и за ним ухаживали 7+ разных дней,
  от него отрастает новый гриб (в свободную банку, либо ждёт, пока купишь).
- 20 мутаций: выпадают случайно при действиях, у каждой своя стадия и условие.
  Остаются на грибе навсегда + попадают в коллекцию юзера (kombucha_codex).
"""
from __future__ import annotations

import random
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Callable

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert

from ..errors import ApiError
from ..models import Answer, ContentStatus, DebateVote, Kombucha, KombuchaCodex, User
from . import wood

MSK = timezone(timedelta(hours=3))
rng = random.Random()          # в тестах подменяется, чтобы мутации были детерминированы

STATS = ("sweet", "tea", "clean", "happy")
PERIOD = timedelta(hours=12)
DROP = {"sweet": 30.0, "tea": 25.0, "clean": 15.0, "happy": 25.0}  # за каждые 12 часов
DEATH_AFTER = timedelta(hours=24)

# действие: (показатель, прирост, кулдаун, опыт, фраза)
ACTIONS = {
    "sugar": ("sweet", 35, timedelta(hours=6), 5, "Хрум-хрум, сахарок 🍬"),
    "tea": ("tea", 40, timedelta(hours=6), 5, "Свежая заварка, как у бабушки ☕"),
    "clean": ("clean", 60, timedelta(hours=12), 8, "Банка сияет ✨"),
    "pet": ("happy", 10, timedelta(hours=1), 1, "Гриб довольно булькает 🫧"),
}
DAILY_COOLDOWN = timedelta(hours=20)
SPROUT_CARE_DAYS = 7

STAGES = [  # (с какого опыта, название, размер 1..6)
    (0, "Спора", 1), (60, "Плёночка", 2), (180, "Блинчик", 3), (400, "Медуза", 4),
    (700, "Гриб-гигант", 5), (1000, "Легенда трёхлитровой банки", 6),
]

NAMES = ["Гриша", "Бульбоз", "Кефирыч", "Чайнобой", "Медузий", "Шипучка", "Бражник", "Грибозавр",
         "Пузырь", "Заварыч", "Кисляк", "Блинчик", "Сахарок", "Бульк"]

TALK = {
    "happy": ["Жизнь — как заварка: главное, не пересластить.", "Я сегодня особенно газированный 😎",
              "Ответь на вопрос в ленте — мне от этого тоже хорошо.", "Бульк. Это значит «спасибо»."],
    "hungry": ["Сахарку бы…", "Я не капризничаю, я ферментируюсь без сахара."],
    "thirsty": ["Заварки! Полцарства за заварку!", "Я почти компот. Долей чаю."],
    "dirty": ["Банка мутная, как объяснения у доски.", "Помой банку, пожалуйста. Мне неловко."],
    "sad": ["Со мной никто не разговаривает…", "Погладь, а?"],
    "sticky": ["Я слипся. Это был перебор с сахаром.", "Сахарная кома, не беспокоить."],
}


# ---------------------------------------------------------------- мутации
@dataclass(frozen=True)
class Ctx:
    action: str
    k: Kombucha
    hour: int                 # час по Москве
    answers_24h: int = 0
    debate_24h: int = 0
    was_in_danger: bool = False


@dataclass(frozen=True)
class Mutation:
    code: str
    title: str
    emoji: str
    desc: str          # подсказка, как получить (видна в коллекции после открытия)
    hint: str          # намёк до открытия
    stage: int         # минимальная стадия (1..6)
    chance: float      # шанс за подходящее действие
    cond: Callable[[Ctx], bool] = lambda c: True


def _night(c: Ctx) -> bool:
    return 0 <= c.hour < 5


MUTATIONS: list[Mutation] = [
    # Спора
    Mutation("sparkle", "Искристый", "✨", "Иногда просто везёт: любое действие.", "Просто ухаживай", 1, 0.03),
    Mutation("night", "Ночной", "🌙", "Уход за грибом с 0 до 5 утра.", "Совы поймут", 1, 0.25, _night),
    Mutation("sweet_tooth", "Сладкоежка", "🍭", "Сахар, когда гриб и так сладкий (больше 80).",
             "Слишком сладко", 1, 0.15, lambda c: c.action == "sugar" and c.k.sweet > 80),
    # Плёночка
    Mutation("striped", "Полосатый", "🦓", "Случайно на стадии «Плёночка» и дальше.", "Случайность", 2, 0.04),
    Mutation("bubbly", "Газировка", "🫧", "Заварка, когда её почти не осталось (меньше 30).",
             "Жажда", 2, 0.2, lambda c: c.action == "tea" and c.k.tea < 30),
    Mutation("clean_freak", "Чистюля", "🧼", "Мыть банку, когда она и так чистая (больше 70).",
             "Перфекционизм", 2, 0.1, lambda c: c.action == "clean" and c.k.clean > 70),
    Mutation("early", "Жаворонок", "🌅", "Уход за грибом с 5 до 8 утра.", "Ранний подъём", 2, 0.2,
             lambda c: 5 <= c.hour < 8),
    # Блинчик
    Mutation("golden", "Золотой", "🥇", "Редкая удача на стадии «Блинчик» и выше.", "Очень редкая", 3, 0.015),
    Mutation("spotted", "Мухоморный", "🍄", "Случайно на стадии «Блинчик» и выше.", "Случайность", 3, 0.04),
    Mutation("chatty", "Болтун", "🗣️", "Поболтать с грибом 50+ раз.", "Много разговоров", 3, 0.3,
             lambda c: c.action == "pet" and c.k.pet_count >= 50),
    Mutation("survivor", "Выживший", "🩹", "Спасти гриб, когда показатель был на нуле.", "На грани", 3, 0.5,
             lambda c: c.was_in_danger),
    # Медуза
    Mutation("glow", "Светящийся", "💡", "Случайно на стадии «Медуза» и выше.", "Случайность", 4, 0.03),
    Mutation("jelly", "Желейный", "🍮", "Случайно на стадии «Медуза» и выше.", "Случайность", 4, 0.04),
    Mutation("scholar", "Ботаник", "🎓", "«Схема дня», если за сутки ты дал 3+ ответа.", "Учёба", 4, 0.35,
             lambda c: c.action == "daily" and c.answers_24h >= 3),
    Mutation("holivar", "Холиварщик", "⚔️", "«Схема дня», если за сутки голосовал в холиваре.", "Споры",
             4, 0.3, lambda c: c.action == "daily" and c.debate_24h >= 1),
    # Гриб-гигант
    Mutation("rainbow", "Радужный", "🌈", "Редкость на стадии «Гриб-гигант».", "Редкая", 5, 0.02),
    Mutation("crystal", "Кристальный", "💎", "Действие, когда все показатели 80+.", "Идеальный уход", 5, 0.1,
             lambda c: all(getattr(c.k, s) >= 80 for s in STATS)),
    Mutation("cosmic", "Космический", "🪐", "Ночью на стадии «Гриб-гигант». Очень редко.", "Звёзды", 5, 0.05,
             _night),
    # Легенда
    Mutation("crown", "Коронованный", "👑", "Уход за Легендой трёхлитровой банки.", "Только для легенд", 6, 0.2),
    Mutation("phoenix", "Феникс", "🔥", "Гриб второго+ поколения дорос до «Медузы».", "Перерождение", 4, 0.25,
             lambda c: c.k.generation >= 2),
]
MUT_BY_CODE = {m.code: m for m in MUTATIONS}
assert len(MUTATIONS) == 20


def catalog() -> list[dict]:
    return [{"code": m.code, "title": m.title, "emoji": m.emoji, "desc": m.desc, "hint": m.hint,
             "stage": m.stage, "stage_title": STAGES[m.stage - 1][1]} for m in MUTATIONS]


def has_mut(k: Kombucha, code: str) -> bool:
    return any(x.get("code") == code for x in (k.mutations or []))


def roll_mutation(ctx: Ctx) -> Mutation | None:
    """Максимум одна новая мутация за действие."""
    size = stage_for(ctx.k.xp)["size"]
    for m in MUTATIONS:
        if size >= m.stage and not has_mut(ctx.k, m.code) and m.cond(ctx) and rng.random() < m.chance:
            return m
    return None


async def add_mutation(s, k: Kombucha, m: Mutation, at: datetime) -> bool:
    """Повесить мутацию на гриб и в коллекцию. True — если в коллекции её раньше не было."""
    k.mutations = [*(k.mutations or []), {"code": m.code, "at": at.isoformat()}]
    new = (await s.execute(insert(KombuchaCodex).values(user_id=k.user_id, code=m.code, kombucha_name=k.name)
                           .on_conflict_do_nothing().returning(KombuchaCodex.code))).scalar() is not None
    if new:
        await wood.earn(s, k.user_id, "mutation", m.code)
    return new


# ---------------------------------------------------------------- время и состояние
def now() -> datetime:
    return datetime.now(timezone.utc)


def stage_for(xp: int) -> dict:
    cur, nxt = STAGES[0], None
    for i, st in enumerate(STAGES):
        if xp >= st[0]:
            cur = st
            nxt = STAGES[i + 1] if i + 1 < len(STAGES) else None
    return {"title": cur[1], "size": cur[2], "from_xp": cur[0], "next_xp": nxt[0] if nxt else None,
            "next_title": nxt[1] if nxt else None}


def tick(k: Kombucha, at: datetime | None = None) -> None:
    """Применить все прошедшие 12-часовые ступеньки убывания и проверить, не закис ли гриб.
    updated_at — якорь ступенек: сдвигается только на целое число периодов."""
    at = at or now()
    if not k.alive:
        return
    steps = int((at - k.updated_at) / PERIOD) if at > k.updated_at else 0
    for i in range(steps):
        step_at = k.updated_at + PERIOD * (i + 1)
        if k.zero_since and step_at - k.zero_since >= DEATH_AFTER:
            break
        for s in STATS:
            setattr(k, s, max(getattr(k, s) - DROP[s], 0.0))
        if k.zero_since is None and any(getattr(k, s) <= 0 for s in STATS):
            k.zero_since = step_at
    k.updated_at = k.updated_at + PERIOD * steps
    if k.zero_since and at - k.zero_since >= DEATH_AFTER:
        k.alive = False
        k.died_at = k.zero_since + DEATH_AFTER


def mood(k: Kombucha) -> str:
    if not k.alive:
        return "dead"
    if k.sweet > 95:
        return "sticky"
    low = min(STATS, key=lambda s: getattr(k, s))
    if getattr(k, low) < 25:
        return {"sweet": "hungry", "tea": "thirsty", "clean": "dirty", "happy": "sad"}[low]
    return "happy"


def next_drop_in(k: Kombucha, at: datetime | None = None) -> int:
    at = at or now()
    return max(int((k.updated_at + PERIOD - at).total_seconds()), 0)


# ---------------------------------------------------------------- имена
async def name_taken(s, name: str, exclude_id: int | None = None) -> bool:
    q = select(Kombucha.id).where(func.lower(Kombucha.name) == name.lower())
    if exclude_id:
        q = q.where(Kombucha.id != exclude_id)
    return (await s.scalar(q.limit(1))) is not None


async def free_name(s, base: str | None = None) -> str:
    base = (base or rng.choice(NAMES))[:24]
    if not await name_taken(s, base):
        return base
    for _ in range(50):
        cand = f"{base} {rng.randint(2, 9999)}"
        if not await name_taken(s, cand):
            return cand
    raise ApiError("Не удалось придумать имя, задай своё", 409, "name_taken")


async def ensure_name(s, name: str, exclude_id: int | None = None) -> str:
    if await name_taken(s, name, exclude_id):
        raise ApiError(f"Имя «{name}» уже занято другим грибом — придумай своё", 409, "name_taken",
                       field="name")
    return name


# ---------------------------------------------------------------- грибы и банки
def _new(user_id: int, name: str, parent: Kombucha | None = None) -> Kombucha:
    t = now()
    return Kombucha(user_id=user_id, name=name, xp=0, best_xp=0, generation=1, sweet=70.0, tea=70.0,
                    clean=90.0, happy=70.0, alive=True, cooldowns={}, mutations=[], care_days=0, pet_count=0,
                    sprouted=False, sprout_pending=False, parent_id=parent.id if parent else None,
                    born_at=t, updated_at=t)


async def list_for(s, user_id: int, lock: bool = False) -> list[Kombucha]:
    q = select(Kombucha).where(Kombucha.user_id == user_id).order_by(Kombucha.id)
    if lock:
        q = q.with_for_update()
    items = list((await s.scalars(q)).all())
    for k in items:
        tick(k)
    return items


async def ensure_first(s, user: User) -> list[Kombucha]:
    """Первый гриб выдаётся бесплатно при самом первом заходе в игру
    (флаг в users.profile, чтобы выброшенный гриб не возвращался сам)."""
    user_id = user.id
    items = await list_for(s, user_id, lock=True)
    if not items and not (user.profile or {}).get("kombucha_started"):
        user.profile = {**(user.profile or {}), "kombucha_started": True}
        s.add(_new(user_id, await free_name(s)))
        await s.flush()
        items = await list_for(s, user_id, lock=True)
    return items


async def get_own(s, user_id: int, kid: int) -> Kombucha:
    k = await s.get(Kombucha, kid, with_for_update=True)
    if k is None or k.user_id != user_id:
        raise ApiError("Гриб не найден", 404, "not_found")
    tick(k)
    return k


async def jars_info(s, user: User) -> dict:
    used = await s.scalar(select(func.count(Kombucha.id)).where(Kombucha.user_id == user.id)) or 0
    return {"jars": user.jars, "used": used, "free": max(user.jars - used, 0), "max": wood.MAX_JARS}


async def plant(s, user: User, name: str | None = None, parent: Kombucha | None = None) -> Kombucha:
    info = await jars_info(s, user)
    if info["free"] <= 0:
        raise ApiError("Нет свободной банки — купи ещё одну в магазине", 409, "no_free_jar")
    if name:
        await ensure_name(s, name)
    else:
        name = await free_name(s, f"{parent.name[:20]} мл." if parent else None)
    k = _new(user.id, name, parent)
    if parent and parent.mutations:
        # наследственность: одна случайная мутация родителя
        inherited = rng.choice(parent.mutations)
        k.mutations = [{"code": inherited["code"], "at": now().isoformat(), "inherited": True}]
    s.add(k)
    await s.flush()
    return k


async def place_pending_sprouts(s, user: User) -> list[Kombucha]:
    """После покупки банки — сначала сажаем отростки, которые ждали."""
    planted = []
    parents = (await s.scalars(select(Kombucha).where(Kombucha.user_id == user.id, Kombucha.sprout_pending.is_(True))
                               .order_by(Kombucha.id).with_for_update())).all()
    for p in parents:
        if (await jars_info(s, user))["free"] <= 0:
            break
        planted.append(await plant(s, user, parent=p))
        p.sprout_pending = False
    return planted


async def buy_jar(s, user: User) -> dict:
    if user.jars >= wood.MAX_JARS:
        raise ApiError(f"Больше {wood.MAX_JARS} банок на подоконник не влезет", 409, "max_jars")
    await wood.spend(s, user.id, wood.PRICES["jar"], "buy_jar", f"jar{user.jars + 1}")
    user.jars += 1
    await s.flush()
    return {"sprouts": [k.name for k in await place_pending_sprouts(s, user)]}


# ---------------------------------------------------------------- действия
def _cd_left(k: Kombucha, key: str, cd: timedelta, at: datetime) -> int:
    last = (k.cooldowns or {}).get(key)
    if not last:
        return 0
    return max(int((datetime.fromisoformat(last) + cd - at).total_seconds()), 0)


async def answers_last_day(s, user_id: int) -> int:
    return await s.scalar(select(func.count(Answer.id)).where(
        Answer.author_id == user_id, Answer.status == ContentStatus.ACTIVE,
        Answer.created_at >= now() - timedelta(hours=24))) or 0


async def debate_votes_last_day(s, user_id: int) -> int:
    return await s.scalar(select(func.count()).select_from(DebateVote).where(
        DebateVote.user_id == user_id, DebateVote.created_at >= now() - timedelta(hours=24))) or 0


async def act(s, user: User, k: Kombucha, action: str) -> dict:
    """Выполнить действие. Возвращает {message, mutation?, sprout?, wood}."""
    at = now()
    if not k.alive:
        raise ApiError("Гриб закис 😢 Перезаведи или реанимируй", 409, "kombucha_dead")
    in_danger = k.zero_since is not None
    answers_24h = debate_24h = 0
    if action == "daily":
        left = _cd_left(k, "daily", DAILY_COOLDOWN, at)
        if left:
            raise ApiError("Схема дня уже забрана", 429, "cooldown", retry_after=left)
        answers_24h = await answers_last_day(s, user.id)
        debate_24h = await debate_votes_last_day(s, user.id)
        n = min(answers_24h, 6)
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
            msg, xp = "Перебор! Гриб слипся 🥴 (−настроение)", 0
        setattr(k, stat, min(getattr(k, stat) + add, 100.0))
        if action == "pet":
            k.pet_count += 1
            m = mood(k)
            msg = rng.choice(TALK.get(m, TALK["happy"]))
        k.xp += xp
    else:
        raise ApiError("Неизвестное действие", 400, "validation_error")

    k.cooldowns = {**(k.cooldowns or {}), action: at.isoformat()}
    k.best_xp = max(k.best_xp, k.xp)
    rescued = in_danger and all(getattr(k, st) > 0 for st in STATS)
    if rescued:
        k.zero_since = None
    today = at.astimezone(MSK).date()
    if k.last_care_day != today:
        k.last_care_day = today
        k.care_days += 1
    earned = await wood.earn(s, user.id, "kombucha_care", f"{k.id}:{action}:{at.isoformat()}")

    res: dict = {"message": msg, "mutation": None, "sprout": None, "wood": earned}
    m = roll_mutation(Ctx(action=action, k=k, hour=at.astimezone(MSK).hour, answers_24h=answers_24h,
                          debate_24h=debate_24h, was_in_danger=rescued))
    if m:
        first = await add_mutation(s, k, m, at)
        res["mutation"] = {"code": m.code, "title": m.title, "emoji": m.emoji, "first_time": first}

    # отросток: легенда + неделя ухода
    if not k.sprouted and stage_for(k.xp)["size"] == 6 and k.care_days >= SPROUT_CARE_DAYS:
        k.sprouted = True
        await wood.earn(s, user.id, "sprout", k.id)
        if (await jars_info(s, user))["free"] > 0:
            child = await plant(s, user, parent=k)
            res["sprout"] = {"planted": True, "name": child.name}
        else:
            k.sprout_pending = True
            res["sprout"] = {"planted": False}
    return res


async def restart(s, k: Kombucha, name: str | None = None) -> None:
    if k.alive:
        raise ApiError("Гриб жив, его не надо перезаводить", 409, "kombucha_alive")
    if name:
        k.name = await ensure_name(s, name, exclude_id=k.id)
    at = now()
    k.generation += 1
    k.xp = 0
    k.sweet, k.tea, k.clean, k.happy = 70.0, 70.0, 90.0, 70.0
    k.alive, k.zero_since, k.died_at, k.cooldowns = True, None, None, {}
    k.care_days, k.last_care_day, k.pet_count, k.sprouted, k.sprout_pending = 0, None, 0, False, False
    k.mutations = []  # в коллекции юзера мутации остаются навсегда
    k.born_at = k.updated_at = at


async def revive(s, user: User, k: Kombucha) -> None:
    """Реанимация за $₽: опыт и мутации сохраняются, показатели — на 50."""
    if k.alive:
        raise ApiError("Гриб и так жив", 409, "kombucha_alive")
    await wood.spend(s, user.id, wood.PRICES["revive"], "revive", f"{k.id}:{k.died_at.isoformat()}")
    at = now()
    k.sweet = k.tea = k.clean = k.happy = 50.0
    k.alive, k.zero_since, k.died_at = True, None, None
    k.updated_at = at


def out(k: Kombucha) -> dict:
    at = now()
    cds = {a: _cd_left(k, a, cd, at) for a, (_, _, cd, _, _) in ACTIONS.items()}
    cds["daily"] = _cd_left(k, "daily", DAILY_COOLDOWN, at)
    m = mood(k)
    danger = None
    if k.alive and k.zero_since:
        danger = max(int((k.zero_since + DEATH_AFTER - at).total_seconds()), 0)
    muts = [{**{kk: v for kk, v in MUT_BY_CODE[x["code"]].__dict__.items() if kk in ("code", "title", "emoji")},
             "inherited": bool(x.get("inherited")), "at": x.get("at")}
            for x in (k.mutations or []) if x.get("code") in MUT_BY_CODE]
    st = stage_for(k.xp)
    return {
        "id": k.id, "name": k.name, "xp": k.xp, "best_xp": k.best_xp, "generation": k.generation, "alive": k.alive,
        "stats": {s: round(getattr(k, s)) for s in STATS}, "mood": m,
        "phrase": rng.choice(TALK[m]) if m in TALK else "…",
        "stage": st, "cooldowns": cds, "dies_in": danger, "next_drop_in": next_drop_in(k, at) if k.alive else None,
        "age_days": (at - k.born_at).days, "born_at": k.born_at.isoformat(),
        "died_at": k.died_at.isoformat() if k.died_at else None,
        "mutations": muts, "care_days": k.care_days, "sprouted": k.sprouted, "sprout_pending": k.sprout_pending,
        "sprout_progress": {"care_days": min(k.care_days, SPROUT_CARE_DAYS), "need_days": SPROUT_CARE_DAYS,
                            "legend": st["size"] == 6},
        "is_sprout": k.parent_id is not None,
    }
